
# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2022-2023  Claude Rohrbacher & Benjamin Bureau
#  <claude.rohrbacher@usherbrooke.ca>                                        #
#                                                                            #
# This file is part of pyHegel.  http://github.com/lupien/pyHegel            #
#                                                                            #
# pyHegel is free software: you can redistribute it and/or modify it under   #
# the terms of the GNU Lesser General Public License as published by the     #
# Free Software Foundation, either version 3 of the License, or (at your     #
# option) any later version.                                                 #
#                                                                            #
# pyHegel is distributed in the hope that it will be useful, but WITHOUT     #
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or      #
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public        #
# License for more details.                                                  #
#                                                                            #
# You should have received a copy of the GNU Lesser General Public License   #
# along with pyHegel.  If not, see <http://www.gnu.org/licenses/>.           #
#                                                                            #
##############################################################################
from __future__ import absolute_import, print_function, division

import numpy as np
import scipy
import os.path

from ..instruments_base import visaInstrument, visaInstrumentAsync,\
                            BaseDevice, scpiDevice, MemoryDevice, ReadvalDev,\
                            ChoiceMultiple, Choice_bool_OnOff, _repr_or_string,\
                            quoted_string, quoted_list, quoted_dict, ChoiceLimits,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDev, ChoiceDevSwitch, ChoiceIndex,\
                            decode_float64, decode_float64_avg, decode_float64_meanstd,\
                            decode_uint16_bin, _decode_block_base, _decode_block_auto, decode_float64_2col,\
                            decode_complex128, sleep, locked_calling, visa_wrap, _encode_block,\
                            ChoiceSimple, _retry_wait, Block_Codec, ChoiceSimpleMap
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

register_usb_name('TEKTRONIX', 0x0699)


#@register_instrument('TEKTRONIX', 'AWG5204', 'FV:6.7.0235.0')
# TCPIP0::192.168.137.252::inst0::INSTR
@register_instrument('TEKTRONIX', 'AWG5204', usb_vendor_product=[0x0699, 0x0503])
class tektronix_AWG(visaInstrumentAsync):
    """
    This is to control the Tektronix Arbitrary Waveform Generator 5000 series.
    It has 4 independent channels that can be coupled (for start/stop)
    """
    def init(self, full=False):
        self.write(':format:border swap')
        # initialize async stuff
        super(tektronix_AWG, self).init(full=full)
        self._async_trigger_helper_string = '*OPC'
    def _async_trigger_helper(self):
        self.write(self._async_trigger_helper_string)
        #self._async_trigger_helper_string = '*OPC'
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        orig_ch = self.current_channel.getcache()
        ch_list = ['current_channel', 'ref_source', 'coupled_en', 'trigger_mode','trigger_source',
                                'sample_rate','sampling_mode','output_mode', 'volt_ampl', 'volt_offset',
                                'marker_volt_ampl','marker_volt_high','marker_volt_low','marker_volt_offset']
        self.current_channel.set(1)
        ch1 = self._conf_helper(*ch_list)
        self.current_channel.set(2)
        ch2 = self._conf_helper(*ch_list)
        self.current_channel.set(3)
        ch3 = self._conf_helper(*ch_list)
        self.current_channel.set(4)
        ch4 = self._conf_helper(*ch_list)
        self.current_channel.set(orig_ch)
        return ch1+ch2+ch3+ch4+self._conf_helper('coupled_en', 'sample_rate', 'sampling_mode',
                                         'ref_source', options)
    @locked_calling
    def _create_devs(self):
        self.current_channel = MemoryDevice(1, min=1, max=4)
        self.current_wfname = MemoryDevice('init')
        self.current_mkr = MemoryDevice(1)

        self.follow_recommended_settings = scpiDevice('AWGControl:ARSettings', choices=ChoiceStrings('0', '1'), doc=
            """
            If set to 1 and waveforms have a recommended sample rate, amplitude, etc. the awg will follow these instruction.
            Otherwise it will follow the global parameters.
            """)

        self.coupled_en = scpiDevice(':INSTrument:COUPle:SOURce',
                                    choices=ChoiceStrings('NONE', 'ALL','PAIR'))
        self.sample_rate = scpiDevice(':CLOCk:SRATe', str_type=float)
        self.sampling_mode = MemoryDevice("fast", choices=ChoiceStrings("slow", "fast"), doc=
            """
            slow mode for sampling rates from 298 S/s to 2.5 G/s
            fast mode for sampling rates from 2.5 GS/s to 5 G/s
            The only way to change the mode is to close the program on the awg controller and launch the other one.
            """) # Trouver un moyen de déterminer le mode de l'appareil
        self.ref_source = scpiDevice(':CLOCk:SOURce', choices=ChoiceStrings('INTernal','EFIXed','EVARiable','EXTernal'),doc=
         """
            INTernal - Clock signal is generated internally and the reference frequency is
            derived from the internal oscillator.

            EFIXed – Clock is generated internally and the reference frequency is derived
            from a fixed 10 MHz reference supplied at the Reference In connector.

            EVARiable – Clock is generated internally and the reference frequency is derived
            from a variable reference supplied at the Reference In connector.

            EXTernal – Clock signal supplied
            """)

        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)

        def devMkrOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_mkr)
            app = kwarg.pop('options_apply', ['ch', 'mkr'])
            kwarg.update(options=options, options_apply=app)
            return devChOption(*arg, **kwarg)

        def devWfOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(wfname=self.current_wfname)
            app = kwarg.pop('options_apply', ['wfname'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)


        self.list_waveforms = scpiDevice(getstr='WLISt:LIST?', str_type=quoted_list())

        # Channel specific:
        self.trigger_mode = devChOption(':SOURCE{ch}:RMODE', choices=ChoiceStrings('CONTinuous','TRIGgered','GATed'))    
        self.trigger_source = devChOption(':SOURce{ch}:TINPut',choices=ChoiceStrings('ITRigger','ATRigger','BTRigger'))
        self.output_en=devChOption('OUTput{ch}:STATe', str_type=bool, doc=
            """
            ON or 1 : output is on
            OFF or 0 the output is off
            """)
        self.output_mode=devChOption('OUTput{ch}:PATH',choices=ChoiceStrings('DCHB','DCHV','ACD','ACAM'))
        self.volt_ampl = devChOption('SOURce{ch}:VOLTage:LEVel:IMMediate:AMPLitude', str_type=float)
        self.volt_offset = devChOption('SOURce{ch}:VOLTage:LEVEL:IMMediate:OFFSET', str_type=float)
        self.channel_waveform = devChOption(setstr='SOURce{ch}:CASSet:WAVeform', getstr='SOURce{ch}:CASSet?', 
                                            choices=ChoiceDev(self.list_waveforms), str_type=quoted_string(),doc=
            'Load a waveform onto a specific channel')


        # Waveform specific:
        self.waveform_sample_rate = devWfOption(getstr='WLISt:WAVeform:SRATe? "{wfname}"', setstr='WLISt:WAVeform:SRATe "{wfname}", ', str_type=float, autoinit=False)
        self.waveform_volt_ampl = devWfOption(getstr='WLISt:WAVeform:AMPLitude? "{wfname}"',setstr='WLISt:WAVeform:AMPLitude "{wfname}"', str_type=float, autoinit=False)

        self.waveform_length = devWfOption(getstr='WLISt:WAVeform:LENGth? "{wfname}"', setstr='WLIST:WAVEFORM:RESAMPLE "{wfname}", ', str_type=int, autoinit=False)
        self.waveform_data = devWfOption(getstr='WLISt:WAVeform:DATA? "{wfname}"', setstr='WLISt:WAVeform:DATA "{wfname}", {val}; *OPC', str_type=Block_Codec(np.float32), autoinit=False)
        self.waveform_marker_data = devWfOption(setstr='WLISt:WAVeform:MARKer:DATA "{wfname}",{val}', getstr='WLISt:WAVeform:MARKer:DATA? "{wfname}"', str_type=Block_Codec(np.uint8), autoinit=False)
        self.marker_volt_ampl = devMkrOption('SOURce{ch}:MARKer{mkr}:VOLTage:AMPLitude', str_type=float, min=0.2, max=1.75,autoinit=False) # min et max déterminés en essayant
        self.marker_volt_offset = devMkrOption('SOURce{ch}:MARKer{mkr}:VOLTage:OFFSet', str_type=float, min=-0.4, max=1.65,autoinit=False) # min et max déterminés en essayant
        self.marker_volt_high = devMkrOption('SOURce{ch}:MARKer{mkr}:VOLTage:HIGH', str_type=float, min=-0.3, max=1.75,autoinit=False) # min et max déterminés en essayant
        self.marker_volt_low = devMkrOption('SOURce{ch}:MARKer{mkr}:VOLTage:LOW', str_type=float, min=-0.5, max=1.55,autoinit=False) # min et max déterminés en essayant


        # Faite a test
        self.freq_ext = scpiDevice(':CLOCk:ECLock:FREQuency', str_type=float,doc=
            """Set or get the external clock frequency
                min = 2.5GHz
                max=5 GHz
            """)
        self.ref_freq = scpiDevice(':CLOCk:EREFerence:FREQuency', str_type=float,min=35e6,max=250e6)


        self.alias = self.volt_ampl
        super(tektronix_AWG, self)._create_devs()
# erreur de timout mais fonctionne
    def run(self, enable=True):
        if enable==True:
            self.write('AWGCONTROL:RUN:IMMEDIATE')
        else:
            self.write('AWGControl:STOP:IMMediate')

    def waveform_create(self, wav, wfname, sample_rate=None, amplitude=None, force=False, marker=(0, -1)):
        """
        Creates a waveform wfname with wav as its data (wav is a list or ndarray)
        If wfname already exists and force is set to True, the existing
        waveform will be deleted
        If wfname already exists and force is set to False, the function will raise an error
        and return 1
        marker is a tuple (marker_on, marker_off)
        """
        # Test if wfname is already taken
        if wfname in self.list_waveforms.get():
            if force:
                self.waveform_delete(wfname)
                print("Waveform {} was deleted".format(wfname))
            else:
                raise RuntimeError('Destination waveform name already exists. Add the option "force=True" to overwrite')
                return 1
        self.write('wlist:wav:new "{}",{}'.format(wfname,len(wav)))
        print("Waveform {} was created".format(wfname))
        self.write('wlist:wav:data "{}",{}'.format(wfname,Block_Codec(np.float32).tostr(wav)))
        if sample_rate is not None:
            self.waveform_sample_rate.set(sample_rate, wfname=wfname)
        if amplitude is not None:
            self.waveform_volt_ampl.set(amplitude, wfname=wfname)
        self.waveform_edit_marker(*marker, wfname=wfname)


    def waveform_delete(self, wfname):
        """
        Deletes the waveform wfname from AWG memory
        If wfname does not exist, nothing happens
        """
        self.write('wlist:waveform:delete "{}"'.format(wfname))

    def waveform_resample(self, wfname, n=1, multiply=True):
        if multiply:
            n *= self.length(wfname)
        self.write('WLIST:WAVEFORM:RESAMPLE "{}", {}'.format(wfname, n))

    def waveform_get_marker(self, wfname):
        """
        Returns the waveform in the awg in an ndarray of float32
        """
        wavstr = self.ask('WLISt:WAVeform:MARKer:DATA? "{}"'.format(wfname))
        # trim length bytes :
        # the wavstr start with "#nxxxx" where xxxx indicates the length of the following raw
        # data and n indicates the number of digits used for xxxx
        # Ex : a data of length 256 would start with "#3256"
        n = int(wavstr[1])
        wavstr = wavstr[n + 2:] # + 2 is for the # and the first digit
        assert len(wavstr) % 4 == 0, "Error when trimming the beginning of the waveform data"
        # convert to float32 :
        wavbytes = np.array([ord(char) for char in wavstr], dtype=np.uint8)
        return wavbytes.view(dtype=np.float32)

    def waveform_edit_marker(self, marker_on=0, marker_off=-1, wfname="test"):
        """
        Generate and send marker to given waveform.
        only work for two level marker ( step function), not a great one
        marker_on= index of start for on state, 0 by default
        marker_off= index of start for off state, len/2 by default
        """
        length = self.waveform_length.get(wfname=wfname)
        marker_off = length // 2 if marker_off == -1 else marker_off
        marker_on = length // 2 if marker_on == -1 else marker_on
        if marker_on > length or marker_off > length:
            raise ValueError("Marker indices must be inferior to the length of the waveform: {} points".format(length))
        if marker_on == marker_off:
            wav = length * 0
        elif marker_on < marker_off:
            wav = marker_on * [0] + (marker_off - marker_on) * [1] + (length - marker_off) * [0]
        else:
            wav = marker_off * [1] + (marker_on - marker_off) * [0] + (length - marker_on) * [1]
        # wavstr = "".join([chr(b<<7) for b in wav])
        wavstr = np.array([i<<7 for i in wav], dtype=np.uint8)
        self.waveform_marker_data.set(wavstr, wfname=wfname)
        # wavstr = '#' + str(len(str(len(wav)))) + str(len(wav)) + wavstr
        # self.write('wlist:wav:mark:data "{}",{}'.format(wfname,wavstr))

    def wait_for_trig(self):
        """
        Generate an Trigger event, (check if awg is ready first)
        """
        while(self.ask('STATus:OPERation:CONdition?')=='0'):
            sleep(0.01)
        self.write('*TRG')
