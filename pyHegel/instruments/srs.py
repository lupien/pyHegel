# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2011-2019  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from __future__ import absolute_import

import numpy as np
import time
from scipy.optimize import brentq as brentq_rootsolver

from ..instruments_base import visaInstrument, visaInstrumentAsync,\
                            BaseDevice, scpiDevice, MemoryDevice, ReadvalDev,\
                            ChoiceMultiple, ChoiceIndex, make_choice_list,\
                            ChoiceDevDep, ChoiceLimits,\
                            decode_float64, _decode_block_base, visa_wrap, locked_calling,\
                            wait, resource_info, ProxyMethod
from ..types import dict_improved
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

#######################################################
##    Stanford Research SR830 Lock-in Amplifier
#######################################################

#@register_instrument('Stanford_Research_Systems', 'SR830', 'ver1.07 ')
@register_instrument('Stanford_Research_Systems', 'SR830', alias='SR830 LIA')
class sr830_lia(visaInstrument):
    """
    Most useful devices:
        readval/fetch
        srclvl
        freq

    Don't forget to set the async_wait to some usefull values.
     might do set(sr1.async_wait, 1.)
    when using 24dB/oct, 100ms filter.

    You can use find_n_time and find_fraction to set the time.
    For example: set(sr1.async_wait, sr1.find_n_time(.99,sec=True))

    To read more than one channel at a time use readval/fetch(snap)
    Otherwise you can use x, y, t, theta

    Note that the sync filters lowers the instrument resolution (so only use it if needed)
    and it applies to the harmonic, not the fundamental (so it will not filter out the
    fundamental frequency when detecting harmonics.)
    """
    # TODO setup snapsel to use the names instead of the numbers
    _snap_type = {1:'x', 2:'y', 3:'R', 4:'theta', 5:'Aux_in1', 6:'Aux_in2',
                  7:'Aux_in3', 8:'Aux_in4', 9:'Ref_Freq', 10:'Ch1', 11:'Ch2'}
    def init(self, full=False):
        # This empties the instrument buffers
        self._dev_clear()
    def _check_snapsel(self,sel):
        if not (2 <= len(sel) <= 6):
            raise ValueError, 'snap sel needs at least 2 and no more thant 6 elements'
    def _snap_getdev(self, sel=[1,2], norm=False):
        # sel must be a list
        self._check_snapsel(sel)
        sel = map(str, sel)
        data = decode_float64(self.ask('snap? '+','.join(sel)))
        if norm:
            amp = self.srclvl.get()
            data_norm = data/amp
            data = np.concatenate( (data_norm, data) )
        return data
    def _snap_getformat(self, sel=[1,2], norm=False, **kwarg):
        self._check_snapsel(sel)
        headers = [ self._snap_type[i] for i in sel]
        if norm:
            headers = map(lambda x: x+'_norm', headers) + headers
        d = self.snap._format
        d.update(multi=headers, graph=range(len(sel)))
        return BaseDevice.getformat(self.snap, sel=sel, **kwarg)
    def auto_offset(self, ch='x'):
        """
           commands the auto offset for channel ch
           which can be 'x', 'y' or 'r'
        """
        choices=ChoiceIndex(['x', 'y', 'r'], offset=1)
        ch_i = choices.tostr(ch)
        self.write('aoff '+ch_i)
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        #base = ['async_delay=%r'%self.async_delay]
        return self._conf_helper('async_wait', 'freq', 'sens', 'srclvl', 'harm', 'phase', 'timeconstant', 'filter_slope',
                                 'sync_filter', 'reserve_mode',
                                 'offset_expand_x', 'offset_expand_y', 'offset_expand_r',
                                 'input_conf', 'grounded_conf', 'dc_coupled_conf', 'linefilter_conf',
                                 'reference_trigger', 'reference_mode',
                                 'ch1_out', 'ch2_out', 'display_conf1', 'display_conf2',
                                 'auxout1', 'auxout2', 'auxout3', 'auxout4', options)
    def _create_devs(self):
        self.freq = scpiDevice('freq', str_type=float, setget=True, min=0.001, max=102e3)
        self.reference_trigger = scpiDevice('rslp', choices=ChoiceIndex(['sine_zero', 'ttl_rising', 'ttl_falling']))
        self.reference_mode = scpiDevice('fmod', choices=ChoiceIndex(['external', 'internal']))
        sens = ChoiceIndex(make_choice_list([2,5,10], -9, -1), normalize=True)
        self.sens = scpiDevice('sens', choices=sens, doc='Set the sensitivity in V (for currents it is in uA)')
        self.oauxi1 = scpiDevice(getstr='oaux? 1', str_type=float)
        self.auxout1 = scpiDevice('AUXV 1,{val}', 'AUXV? 1', str_type=float, setget=True, min=-10.5, max=10.5)
        self.auxout2 = scpiDevice('AUXV 2,{val}', 'AUXV? 2', str_type=float, setget=True, min=-10.5, max=10.5)
        self.auxout3 = scpiDevice('AUXV 3,{val}', 'AUXV? 3', str_type=float, setget=True, min=-10.5, max=10.5)
        self.auxout4 = scpiDevice('AUXV 4,{val}', 'AUXV? 4', str_type=float, setget=True, min=-10.5, max=10.5)
        self.srclvl = scpiDevice('slvl', str_type=float, min=0.004, max=5., setget=True)
        self.harm = scpiDevice('harm', str_type=int, min=1, max=19999)
        self.phase = scpiDevice('phas', str_type=float, min=-360., max=729.90, setget=True)
        timeconstants = ChoiceIndex(make_choice_list([10, 30], -6, 3), normalize=True)
        self.timeconstant = scpiDevice('oflt', choices=timeconstants)
        filter_slopes=ChoiceIndex([6, 12, 18, 24])
        self.filter_slope = scpiDevice('ofsl', choices=filter_slopes, doc='in dB/oct\n')
        self.sync_filter = scpiDevice('sync', str_type=bool)
        self.x = scpiDevice(getstr='outp? 1', str_type=float, trig=True)
        self.y = scpiDevice(getstr='outp? 2', str_type=float, trig=True)
        self.r = scpiDevice(getstr='outp? 3', str_type=float, trig=True)
        off_exp = ChoiceMultiple(['offset_pct', 'expand_factor'], [float, ChoiceIndex([1, 10 ,100])])
        self.ch1_out = scpiDevice('fpop 1,{val}', 'fpop? 1', choices=ChoiceIndex(['display', 'X']))
        self.ch2_out = scpiDevice('fpop 2,{val}', 'fpop? 2', choices=ChoiceIndex(['display', 'Y']))
        disp_ratio1 = ChoiceMultiple(['display', 'ratio'], [ChoiceIndex(['X', 'R', 'Xnoise', 'AuxIn1', 'AuxIn2']), ChoiceIndex(['off', 'AuxIn1', 'AuxIn2'])])
        disp_ratio2 = ChoiceMultiple(['display', 'ratio'], [ChoiceIndex(['Y', 'theta', 'Ynoise', 'AuxIn3', 'AuxIn3']), ChoiceIndex(['off', 'AuxIn3', 'AuxIn4'])])
        self.display_conf1 = scpiDevice('DDEF 1,{val}', 'DDEF? 1', choices=disp_ratio1)
        self.display_conf2 = scpiDevice('DDEF 2,{val}', 'DDEF? 2', choices=disp_ratio2)
        self.offset_expand_x = scpiDevice('oexp 1,{val}', 'oexp? 1', choices=off_exp, setget=True)
        self.offset_expand_y = scpiDevice('oexp 2,{val}', 'oexp? 2', choices=off_exp, setget=True)
        self.offset_expand_r = scpiDevice('oexp 3,{val}', 'oexp? 3', choices=off_exp, setget=True)
        self.theta = scpiDevice(getstr='outp? 4', str_type=float, trig=True)
        input_conf = ChoiceIndex(['A', 'A-B', 'I1', 'I100'])
        self.input_conf = scpiDevice('isrc', choices=input_conf, doc='For currents I1 refers to 1 MOhm, I100 refers to 100 MOhm\n')
        self.grounded_conf = scpiDevice('ignd', str_type=bool)
        self.dc_coupled_conf = scpiDevice('icpl', str_type=bool)
        reserve_mode = ChoiceIndex(['high', 'normal', 'low'])
        self.reserve_mode = scpiDevice('rmod', choices=reserve_mode)
        linefilter = ChoiceIndex(['none', 'line', '2xline', 'both'])
        self.linefilter_conf = scpiDevice('ilin', choices=linefilter, doc='Selects the notch filters')
        # status: b0=Input/Reserver ovld, b1=Filter ovld, b2=output ovld, b3=unlock,
        # b4=range change (accross 200 HZ, hysteresis), b5=indirect time constant change
        # b6=triggered, b7=unused
        self.status_byte = scpiDevice(getstr='LIAS?', str_type=int, doc=
        """
        Reading clears the status word. Unused bits are not listed.
            bit 0  (1):    Input or Amplifier overload
            bit 1  (2):    Filter overload
            bit 2  (4):    Output overload
            bit 3  (8):    Unlocked reference
            bit 4  (16):   Frequency range switch (200Hz)
            bit 5  (32):   Timeconstant changed indirectly
            bit 6  (64):   Triggered data storage
        """)
        self._devwrap('snap', trig=True, doc="""
            This device can be called snap or fetch (they are both the same)
            This device obtains simultaneous readings from many inputs.
            To select the inputs, use the parameter
             sel
            which is [1,2] by default.
            The numbers are taken from the following dictionnary:
                %r
            The option norm when True return the data divided by the srclvl (and followed by raw data)
                """%self._snap_type)
        self.fetch = self.snap
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
    def get_error(self):
        """
         returns a byte of bit flags
          bit 0 (1):   unused
          bit 1 (2):   Backup error
          bit 2 (4):   RAM error
          bit 3 (8):   Unused
          bit 4 (16):  Rom error
          bit 5 (32):  GPIB error
          bit 6 (64):  DSP error
          bit 7 (128): Math Error
        """
        return int(self.ask('ERRS?'))
    def find_fraction(self, n_time_constant, n_filter=None, time_constant=None, sec=False):
        """
        Calculates the fraction of a step function that is obtained after
        n_time_constant*time_constant time when using n_filter
        n_filter is the order of the filter: 1, 2, 3 ...
        By default time_constant and n_filter are the current ones
        When sec is True the input time is in sec, not in time_constants
        """
        if n_filter is None:
            n_filter = self.filter_slope.getcache()
            n_filter = self.filter_slope.choices.index(n_filter)+1
        if time_constant is None:
            time_constant = self.timeconstant.getcache()
        if sec:
            n_time_constant /= time_constant
        t = n_time_constant
        et = np.exp(-t)
        if n_filter == 1:
            return 1.-et
        elif n_filter == 2:
            return 1.-et*(1.+t)
#        elif n_filter == 3:
#            return 1.-et*(1.+t+0.5*t**2)
#        elif n_filter == 4:
#            return 1.-et*(1.+t+0.5*t**2+t**3/6.)
        else:
            # general formula: 1-exp(-t)*( 1+t +t**/2 + ... t**(n-1)/(n-1)!) )
            m = 1.
            tt = 1.
            for i in range(1, n_filter):
                tt *= t/i
                m += tt
            return 1.-et*m
    def find_n_time(self, frac=.99, n_filter=None, time_constant=None, sec=False):
        """
        Does the inverse of find_fraction.
        Here, given a fraction, we find the number of time_constants needed to wait.
        When sec is true, it returs the time in sec not in number of time_constants.
        """
        if n_filter is None:
            n_filter = self.filter_slope.getcache()
            n_filter = self.filter_slope.choices.index(n_filter)+1
        if time_constant is None:
            time_constant = self.timeconstant.getcache()
        func = lambda x: self.find_fraction(x, n_filter, time_constant)-frac
        n_time = brentq_rootsolver(func, 0, 100)
        if sec:
            return n_time*time_constant
        else:
            return n_time

#######################################################
##    Stanford Research SR865 Lock-in Amplifier
#######################################################

register_usb_name('Stanford_Research_Systems', 0xB506)

@register_instrument('Stanford_Research_Systems', 'SR865A', usb_vendor_product=[0xB506, 0x2000])
#@register_instrument('Stanford_Research_Systems', 'SR865A', 'V1.51')
class sr865_lia(visaInstrument):
    """
    Most useful devices:
        readval/fetch
        src_level
        src_offset
        freq

    Don't forget to set the async_wait to some usefull values.
     might do set(sr1.async_wait, 1.)
    when using 24dB/oct, 100ms filter.

    You can use find_n_time and find_fraction to set the time.
    For example: set(sr1.async_wait, sr1.find_n_time(.99,sec=True))

    To read more than one channel at a time use readval/fetch(snap)
    Otherwise you can use x, y, t, theta

    Note that contrary to the SR830, this instrument sync filters applies to the fundamental
    harmonic even if harmonics is turned on.
    It also does not lower the resolution, but it requires a correct sensitivity range
    that does not overload.
    """
    # TODO scan mode, FFT, data capture and streaming
    # Contratry to the SR830, the output buffers is overwritten after every request
    # so it is unecessary to reset it.
    # TODO check OPC usage
    # TODO find out about advanced filters in my filter calculations

    def _check_snapsel(self, sel):
        if not (2 <= len(sel) <= 3):
            raise ValueError, 'snap sel needs at least 1 and no more thant 3 elements'
        if not isinstance(sel, (np.ndarray, list, tuple)):
            sel = [sel]
        return sel
    def _snap_getdev(self, sel=['X', 'Y'], norm=False):
        sel = self._check_snapsel(sel)
        single = False
        if len(sel) == 1:
            single = True
            sel = sel[0]
            if sel in self._param_op:
                sel = self._param_op.tostr(sel)
                data = decode_float64(self.ask('outp? '+sel))
            else:
                sel = self._disp_param_op.tostr(sel)
                data = decode_float64(self.ask('outr? '+sel))
        else:
            sel = [self._param_op.tostr(s) for s in sel]
            data = decode_float64(self.ask('snap? '+','.join(sel)))
        if norm:
            amp = self.src_level.get()
            data_norm = data/amp
            data = np.concatenate( (data_norm, data) )
            single = False
        if single:
            return data[0]
        return data
    def _snap_getformat(self, sel=['X', 'Y'], norm=False, **kwarg):
        sel = self._check_snapsel(sel)
        headers = sel
        if norm:
            headers = map(lambda x: x+'_norm', headers) + headers
        d = self.snap._format
        if len(headers) == 1:
            headers = False
        d.update(multi=headers, graph=range(len(sel)))
        return BaseDevice.getformat(self.snap, sel=sel, **kwarg)

    def _input_conf_setdev(self, val):
        if val.startswith('I'):
            if val == 'I100':
                c = '100MEG'
            else:
                c = '1MEG'
            self.write('ICUR %s'%c)
            self.write('IVMD CURRent')
        else:
            self.write('ISRC %s'%val)
            self.write('IVMD VOLTage')
    def _input_conf_getdev(self):
        is_I = bool(int(self.ask('ivmd?')))
        if not is_I:
            is_AB = bool(int(self.ask('isrc?')))
            return 'A-B' if is_AB else 'A'
        else:
            is_100 = bool(int(self.ask('icur?')))
            return 'I100' if is_100 else 'I1'

    def _snap_bmp_getdev(self):
        """ obtains a .BMP file capturing the display. the .bmp option is added if not provided. """
        self.write('getscreen?')
        while True:
            # TODO could improve this logic
            if self.read_status_byte()&0x10: # MAV bit set
                break
            wait(.1)
        return _decode_block_base(self.read(raw=True))

    def conf_datetime(self, set=False):
        """ When set is True, it sends the current computer date and time to the device.
            It always returns the devices date/time
        """
        if set:
            dt = time.localtime()
            for i,x in enumerate([dt.tm_mday, dt.tm_mon, dt.tm_year%100]):
                self.write('date %i,%i'%(i, x))
            for i,x in enumerate([dt.tm_sec, dt.tm_min, dt.tm_hour]):
                self.write('time %i,%i'%(i, x))
        sec, min, hour = [int(self.ask('time? %i'%i)) for i in range(3)]
        day, month, year = [int(self.ask('date? %i'%i)) for i in range(3)]
        return '%04i-%02i-%02i %02i:%02i:%02i'%(year+2000, month, day, hour, min, sec)

    def auto_range(self):
        self.write('ARNG')

    def auto_offset(self, ch='x'):
        """
           commands the auto offset for channel ch
           which can be 'x', 'y' or 'r'
        """
        choices=ChoiceIndex(['x', 'y', 'r'], offset=1)
        ch_i = choices.tostr(ch)
        self.write('aoff '+ch_i)
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        origsel = self.outch_sel.get()
        ch_info = []
        for c in ['X', 'Y', 'R']:
            self.outch_sel.set(c)
            expand = self.ch_expand.get()
            offset_en = self.ch_offset_en.get()
            offset_prct = self.ch_offset_prct.get()
            ratio_en = self.ch_ratio_en.get()
            info = dict(expand=expand, offset_en=offset_en, offset_prct=offset_prct, ratio_en=ratio_en)
            ch_info.append('ch%s=%r'%(c, info))
        self.outch_sel.set(origsel)
        base = self._conf_helper('async_wait', 'freq', 'freq_internal', 'freq_external',
                                 'freq_detection', 'reference_trigger', 'reference_impedance', 'reference_mode',
                                 'src_level', 'src_offset', 'src_offset_mode',
                                 'input_range', 'input_conf', 'input_ground_en', 'input_dc_coupled_en',
                                 'sens', 'harm', 'harm_dual', 'phase', 'timeconstant', 'filter_slope',
                                 'filter_sync', 'filter_advanced_en', 'enbw',
                                 'ch1_out', 'ch2_out')
        rest = self._conf_helper('chopper_slots', 'chopper_phase', 'blazex_out',
                                 'display_blank_en', 'display_dat1', 'display_dat2', 'display_dat3', 'display_dat4',
                                 'auxout1', 'auxout2', 'auxout3', 'auxout4',
                                 'timebase_mode', 'timebase_mode_state', options)
        return base + ch_info + rest

    def _create_devs(self):
        self.timebase_mode = scpiDevice('tbmode', choices=ChoiceIndex(['auto', 'internal']))
        self.timebase_mode_state = scpiDevice(getstr='tbstat?', choices=ChoiceIndex(['auto', 'internal']))
        minfreq, maxfreq = 1e-3, 4e6
        minsrc, maxsrc = 0, 2
        minsrc_off, maxsrc_off = -5, 5
        self.freq = scpiDevice('freq', str_type=float, setget=True, min=minfreq, max=maxfreq)
        self.freq_internal = scpiDevice('freqint', str_type=float, setget=True, min=minfreq, max=maxfreq)
        self.freq_external = scpiDevice(getstr='freqext?', str_type=float)
        self.freq_detection = scpiDevice(getstr='freqdet?', str_type=float)
        self.reference_trigger = scpiDevice('rtrg', choices=ChoiceIndex(['sine_zero', 'ttl_rising', 'ttl_falling']))
        self.reference_impedance = scpiDevice('refz', choices=ChoiceIndex(['50', '1M']))
        self.preset_sel = MemoryDevice(1, choices=[1, 2, 3, 4])
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.preset_sel)
            app = kwarg.pop('options_apply', ['ch'])
            conv = dict(ch=lambda val, valstr: str(val-1))
            kwarg.update(options=options, options_apply=app, options_conv=conv)
            return scpiDevice(*arg, **kwarg)
        self.preset_freq = devChOption('PSTF {ch},{val}', 'PSTF? {ch}', str_type=float, min=minfreq, max=maxfreq)
        self.preset_amp = devChOption('PSTA {ch},{val}', 'PSTA? {ch}', str_type=float, min=minsrc, max=maxsrc)
        self.preset_offset = devChOption('PSTL {ch},{val}', 'PSTL? {ch}', str_type=float, min=minsrc_off, max=maxsrc_off)
        sens = ChoiceIndex(make_choice_list([1,.5,.2], 0, -9)[:-2], normalize=True)
        self.sens = scpiDevice('scal', choices=sens, doc='Set the sensitivity in V (for currents it is in uA). Only affects display and ch1-2 outputs, not the values read.')
        self.input_indicator = scpiDevice(getstr='ilvl?', str_type=int, doc='input range indicator. From 0 to 4 (overload)')
        self.input_range = scpiDevice('irng', choices=ChoiceIndex([1, .3, .1, .03, .01]))
        self.auxin1 = scpiDevice(getstr='oaux? 0', str_type=float)
        self.auxin2 = scpiDevice(getstr='oaux? 1', str_type=float)
        self.auxin3 = scpiDevice(getstr='oaux? 2', str_type=float)
        self.auxin4 = scpiDevice(getstr='oaux? 3', str_type=float)
        self.auxout1 = scpiDevice('AUXV 0,{val}', 'AUXV? 0', str_type=float, setget=True, min=-10.5, max=10.5)
        self.auxout2 = scpiDevice('AUXV 1,{val}', 'AUXV? 1', str_type=float, setget=True, min=-10.5, max=10.5)
        self.auxout3 = scpiDevice('AUXV 2,{val}', 'AUXV? 2', str_type=float, setget=True, min=-10.5, max=10.5)
        self.auxout4 = scpiDevice('AUXV 3,{val}', 'AUXV? 3', str_type=float, setget=True, min=-10.5, max=10.5)
        self.src_level = scpiDevice('slvl', str_type=float, min=minsrc, max=maxsrc, setget=True, doc='level resolution is 1 nV')
        self.src_offset = scpiDevice('soff', str_type=float, min=minsrc_off, max=maxsrc_off, setget=True, doc='DC voltage resolution is 0.1 mV. See also src_offset_mode')
        self.src_offset_mode = scpiDevice('refm', choices=ChoiceIndex(['common', 'differential']))
        self.reference_mode = scpiDevice('rsrc', choices=ChoiceIndex(['internal', 'external', 'dual', 'chop']))
        self.harm = scpiDevice('harm', str_type=int, min=1, max=99, setget=True)
        self.harm_dual = scpiDevice('harmdual', str_type=int, min=1, max=99, setget=True)
        self.phase = scpiDevice('phas', str_type=float, setget=True)
        self.chopper_slots =  scpiDevice('bladeslots', choices=ChoiceIndex(['slt6', 'slt30']))
        self.chopper_phase =  scpiDevice('bladephase', str_type=float, setget=True)
        timeconstants = ChoiceIndex(make_choice_list([1, 3], -6, 4), normalize=True)
        self.timeconstant = scpiDevice('oflt', choices=timeconstants)
        filter_slopes=ChoiceIndex([6, 12, 18, 24])
        self.filter_slope = scpiDevice('ofsl', choices=filter_slopes, doc='in dB/oct\n')
        self.filter_sync = scpiDevice('sync', str_type=bool)
        self.filter_advanced_en = scpiDevice('advfilt', str_type=bool)
        self.enbw = scpiDevice(getstr='enbw?', str_type=float, doc='Does not include effect of sync filter.')
        self.x = scpiDevice(getstr='outp? 0', str_type=float, trig=True)
        self.y = scpiDevice(getstr='outp? 1', str_type=float, trig=True)
        self.r = scpiDevice(getstr='outp? 2', str_type=float, trig=True)
        self.theta = scpiDevice(getstr='outp? 3', str_type=float, trig=True)
        self.ch1_out = scpiDevice('cout 0,{val}', 'cout? 0', choices=ChoiceIndex(['X', 'R']))
        self.ch2_out = scpiDevice('cout 1,{val}', 'cout? 1', choices=ChoiceIndex(['Y', 'theta']))
        self.outch_sel = MemoryDevice('X', choices=ChoiceIndex(['X', 'Y', 'R']))
        def devChOutOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.outch_sel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.ch_expand = devChOutOption('cexp {ch},{val}', 'cexp? {ch}', choices=ChoiceIndex([1, 10, 100]),
                                        doc='expand only modifies display and output, not the read values.')
        self.ch_offset_en = devChOutOption('cofa {ch},{val}', 'cofa? {ch}', str_type=bool)
        self.ch_offset_prct = devChOutOption('cofp {ch},{val}', 'cofp? {ch}', str_type=float)
        self.ch_ratio_en = devChOutOption('crat {ch},{val}', 'crat? {ch}', str_type=bool)
        self.input_ground_en = scpiDevice('ignd', str_type=bool)
        self.input_dc_coupled_en = scpiDevice('icpl', str_type=bool)
        self.display_blank_en = scpiDevice('dblk', str_type=bool)
        self.blazex_out = scpiDevice('blazex', choices=ChoiceIndex(['blazex', 'bipolar_sync', 'unipolar_sync']))
        self.overload_status = scpiDevice(getstr='curovldstat?', str_type=int, doc=
        """  These are the overlaod state at the time of the command. unused bit are not listed.
            bit 0  (1):    CH1 output scale
            bit 1  (2):    CH2 output scale
            bit 3  (8):    Ext ref unlocked
            bit 4  (16):   Input range
            bit 8  (256):  Data Channel 1 Scale (green)
            bit 9  (512):  Data Channel 2 Scale (blue)
            bit 10 (1024): Data Channel 3 Scale (yellow)
            bit 11 (2048): Data Channel 4 Scale (orange)
        """)
        param_op = ChoiceIndex(['X', 'Y', 'R', 'theta', 'in1', 'in2', 'in3', 'in4',
                                'Xnoise', 'Ynoise', 'out1', 'out2', 'phase',
                                'src_level', 'src_offset', 'Fint', 'Fext'])
        self._param_op = param_op
        self._disp_param_op = ChoiceIndex(['dat1', 'dat2', 'dat3', 'dat4'])
        self.display_dat1 = scpiDevice('cdsp 0,{val}', 'cdsp? 0', choices=param_op, doc='This is the green display.')
        self.display_dat2 = scpiDevice('cdsp 1,{val}', 'cdsp? 1', choices=param_op, doc='This is the blue display.')
        self.display_dat3 = scpiDevice('cdsp 2,{val}', 'cdsp? 2', choices=param_op, doc='This is the yellow display.')
        self.display_dat4 = scpiDevice('cdsp 3,{val}', 'cdsp? 3', choices=param_op, doc='This is the orange display.')
        self.status_input_overload = scpiDevice(getstr='LIAS? 4', str_type=int)
        self.status_byte = scpiDevice(getstr='LIAS?', str_type=int, doc=
        """
        Reading clears the status word. unused bits are not listed
            bit 0  (1):    CH1 output scale overload
            bit 1  (2):    CH2 output scale overload
            bit 3  (8):    Ext ref unlocked
            bit 4  (16):   Input range overload
            bit 5  (32):   Sync filter frequency out of range
            bit 6  (64):   Sync filter overload
            bit 7  (128):  Data storage triggered
            bit 8  (256):  Data Channel 1 scale overload (green)
            bit 9  (512):  Data Channel 2 scale overload (blue)
            bit 10 (1024): Data Channel 3 scale overload (yellow)
            bit 11 (2048): Data Channel 4 scale overload (orange)
            bit 12 (4096): Display capture to USB completed
            bit 13 (8192): Scan started
            bit 14 (16384):Scan completed
        """)
        self._devwrap('input_conf', choices=['A', 'A-B', 'I1', 'I100'], doc='For currents I1 refers to 1 MOhm, I100 refers to 100 MOhm\n')
        self._devwrap('snap', trig=True, doc="""
            This device can be called snap or fetch (they are both the same)
            This device obtains simultaneous readings from many inputs (1-3).
            To select the inputs, use the parameter
             sel
            which is ['X', 'Y'] by default.
            The options are for:
                %r
            When reading only one value, you can also use:
                %r
            which correspond the the greem blue, yellow than orange display values.
            The option norm when True return the data divided by the src_level (and followed by raw data)
                """%(self._param_op, self._disp_param_op))
        self.fetch = self.snap
        self._devwrap('snap_bmp', autoinit=False, trig=True)
        self.snap_bmp._format['bin']='.bmp'
        self.snap_display = scpiDevice(getstr='snapd?', str_type=decode_float64, doc='This reads the 4 values on screen, as green, blue, yellow than orange.')
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
    def get_error(self):
        err = int(self.ask('ERRS?'))
        if err == 0:
            return ['No errors']
        errors = ['External 10 MHz clock input error.',
                  'Battery backup failed.'
                  '--', # unused
                  '---', # unused
                  'VXI-11 error.',
                  'GPIB fast data transfer mode aborted',
                  'USB device error.',
                  'USB host error (memory stick error)']
        errs = [e for e,i in enumerate(errors) if (err>>i)&1]
        return errs

    def find_fraction(self, n_time_constant, n_filter=None, time_constant=None, sec=False):
        """
        Calculates the fraction of a step function that is obtained after
        n_time_constant*time_constant time when using n_filter
        n_filter is the order of the filter: 1, 2, 3 ...
        By default time_constant and n_filter are the current ones
        When sec is True the input time is in sec, not in time_constants
        This does not take into account sync or advanced filter.
        """
        if n_filter is None:
            n_filter = self.filter_slope.getcache()
            n_filter = self.filter_slope.choices.index(n_filter)+1
        if time_constant is None:
            time_constant = self.timeconstant.getcache()
        if sec:
            n_time_constant /= time_constant
        t = n_time_constant
        et = np.exp(-t)
        if n_filter == 1:
            return 1.-et
        elif n_filter == 2:
            return 1.-et*(1.+t)
#        elif n_filter == 3:
#            return 1.-et*(1.+t+0.5*t**2)
#        elif n_filter == 4:
#            return 1.-et*(1.+t+0.5*t**2+t**3/6.)
        else:
            # general formula: 1-exp(-t)*( 1+t +t**/2 + ... t**(n-1)/(n-1)!) )
            m = 1.
            tt = 1.
            for i in range(1, n_filter):
                tt *= t/i
                m += tt
            return 1.-et*m
    def find_n_time(self, frac=.99, n_filter=None, time_constant=None, sec=False):
        """
        Does the inverse of find_fraction.
        Here, given a fraction, we find the number of time_constants needed to wait.
        When sec is true, it returs the time in sec not in number of time_constants.
        """
        if n_filter is None:
            n_filter = self.filter_slope.getcache()
            n_filter = self.filter_slope.choices.index(n_filter)+1
        if time_constant is None:
            time_constant = self.timeconstant.getcache()
        func = lambda x: self.find_fraction(x, n_filter, time_constant)-frac
        n_time = brentq_rootsolver(func, 0, 100)
        if sec:
            return n_time*time_constant
        else:
            return n_time


#######################################################
##    Stanford Research SR384 RF source
#######################################################

#@register_instrument('Stanford Research Systems', 'SG384', 'ver1.02.0E')
@register_instrument('Stanford Research Systems', 'SG384', alias='SG384 RF source')
class sr384_rf(visaInstrument):
    # This instruments needs to be on local state or to pass through local state
    #  after a local_lockout to actually turn off the local key.
    # allowed units: amp: dBm, rms, Vpp; freq: GHz, MHz, kHz, Hz; Time: ns, us, ms, s
    def init(self, full=False):
        # This clears the error state
        self.clear()
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('freq', 'en_lf', 'amp_lf_dbm', 'offset_low',
                                 'en_rf', 'amp_rf_dbm', 'en_hf', 'amp_hf_dbm',
                                 'phase', 'mod_en', options)
    def _create_devs(self):
        self.freq = scpiDevice('freq',str_type=float, min=1e-6, max=8.1e9)
        self.offset_low = scpiDevice('ofsl',str_type=float, min=-1.5, max=+1.5) #volts
        self.amp_lf_dbm = scpiDevice('ampl',str_type=float, min=-47, max=14.96) # all channel output power calibrated to +13 dBm only, manual says 15.5 for low but intruments stops at 14.96
        self.amp_rf_dbm = scpiDevice('ampr',str_type=float, min=-110, max=16.53)
        self.amp_hf_dbm = scpiDevice('amph',str_type=float, min=-10, max=16.53) # doubler
        self.en_lf = scpiDevice('enbl', str_type=bool) # 0 is off, 1 is on, read value depends on freq
        self.en_rf = scpiDevice('enbr', str_type=bool) # 0 is off, 1 is on, read value depends on freq
        self.en_hf = scpiDevice('enbh', str_type=bool) # 0 is off, 1 is on, read value depends on freq
        self.phase = scpiDevice('phas',str_type=float, min=-360, max=360) # deg, only change by 360
        self.mod_en = scpiDevice('modl', str_type=bool) # 0 is off, 1 is on
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
    def get_error(self):
        """
         Pops last error
          ## Execution Errors
          0: No error
         10: Illegal value
         11: Illegal Mode
         12: Not allowed
         13: Recall Failed
         14: No clock option
         15: No RF doubler option
         16: No IQ option
         17: Failed self test
          ## Query Errors
         30: Lost data
         32: No listener
          ## Device dependent errors
         40: Failed ROM check
         42: Failed EEPROM check
         43: Failed FPGA check
         44: Failed SRAM check
         45: Failed GPIB check
         46: Failed LF DDS check
         47: Failed RF DDS check
         48: Failed 20 MHz PLL
         49: Failed 100 MHz PLL
         50: Failed 19 MHz PLL
         51: Failed 1 GHz PLL
         52: Failed 4 GHz PLL
         53: Failed DAC
          ## Parsing errors
        110: Illegal command
        111: Undefined command
        112: Illegal query
        113: Illegal set
        114: Null parameter
        115: Extra parameters
        116: Missing parameters
        117: Parameter overflow
        118: Invalid floating point number
        120: Invalid Integer
        121: Integer overflow
        122: Invalid Hexadecimal
        126: Syntax error
        127: Illegal units
        128: Missing units
          ## Communication errors
        170: Communication error
        171: Over run
          ## Other errors
        254: Too many errors
        """
        return int(self.ask('LERR?'))


#######################################################
##    Stanford Research SR780 2 channel network analyzer
#######################################################

#@register_instrument('Stanford_Research_Systems', 'SR780', 'ver116')
@register_instrument('Stanford_Research_Systems', 'SR780', alias='SR780 network analyser')
class sr780_analyzer(visaInstrumentAsync):
    """
    This controls a 2 channel network analyzer
    It currently only handles the FFT measurement group (not octave or swept sine).
    Markers are not handled. Only sine sources are handled.
    Useful devices:
        fetch, readval
        dump
        current_display
        current_channel
        freq_start, freq_stop, freq_center, freq_span
        window_type
        average_en
        average_type
        average_mode
        average_count_requested
        async_wait (needed for exponential average, not for linear)
    Useful methods:
        start
        get_xscale

    Changing a setup should be done in the following order
        meas_grp
        meas
        meas_view
        unit
    """
    def __init__(self, *args, **kwargs):
        super(sr780_analyzer, self).__init__(*args, **kwargs)
        # The parant __init__ overrides our selection of 'wait' mode
        # in _async_detect_setup(reset=True) in init. So lets set it back
        self._async_mode = 'wait'
    def init(self, full=False):
        # This empties the instrument buffers
        self._dev_clear()
        # This clears the error state, and status/event flags
        self.clear()
        if full:
            self._async_sre_flag = 2
            self.write('DSPE 0;*sre 2') # Display flags
            self._async_detect_setup(reset=True)
            #self._async_tocheck = 0
            #self._async_use_delay = False
            self.visa.write_termination = '\n'
            #self.visa.term_chars='\n'
            # The above turned on detection of termchar on read. This is not good for
            # raw reads so turn it off.
            # visa.vpp43.set_attribute(self.visa.vi, visa.VI_ATTR_TERMCHAR_EN, visa.VI_FALSE)
            self.write('OUTX 0') # Force interface to be on GPIB, in case it is not anymore (problem with dump function)
    def _async_select(self, devs=[]):
        # This is called during init of async mode.
        self._async_detect_setup(reset=True)
        for dev, kwarg in devs:
            if dev in [self.fetch, self.readval]:
                disp = kwarg.get('disp', None)
                self._async_detect_setup(disp=disp)
    def _async_detect_setup(self, disp=None, reset=False):
        if reset:
            # make the default async_mode is 'wait' so that if
            # _async_tocheck == 0, we just turn on wait.
            # This could happen when using run_and_wait before anything is set
            # Otherwise, getasync and readval both call async_select to setup
            # the mode properly (_async_mode and_async_tocheck).
            self._async_tocheck = 0
            self._async_mode = 'wait'
            return
        self._async_mode = 'srq'
        disp_org = self.current_display.getcache()
        if disp is None:
            disp = disp_org
        self.current_display.set(disp)
        # 0x2=A-linear avg, 0x4=A-settled, 0x200=B-linear, 0x400=B-settled
        if self.average_en.get(disp=disp):
            if self.average_type.get() in ['linear', 'FixedLength']:
                tocheck = 0x2
            else:
                self._async_mode = 'wait+srq'
                tocheck = 0x4
        else:
            tocheck = 0x4
        if disp == 'B':
            tocheck <<= 8
        self._async_tocheck |= tocheck
        self.current_display.set(disp_org)
    def _async_trigger_helper(self):
        # We are setup so that run_and_wait resuses the last config which starts
        # with a simple wait (could be invalid now if averaging is changed on the instrument).
        # Should not be a big deal since that is not a normal use of it.
        self._cum_display_status = 0
        self.write('PAUS') # make sure we are not scanning anymore.
        self.get_display_status() # reset the display status flags
        self.write('DSPE %i'%self._async_tocheck)
        self.write('STRT')
    def _get_esr(self):
        # This disables the get_esr in the async routines.
        return 0
    @locked_calling
    def start(self):
        """
        Same as pressing Start/Reset button.
        """
        self._async_trigger_helper()
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        ret = super(sr780_analyzer, self)._async_detect(max_time)
        if self._async_mode == 'wait':
            # pure wait
            return ret
        if not ret:
            # Did not receive SRQ or wait long enough
            return False
        # Received SRQ, check if we are done
        disp_st = self.get_display_status()
        self._cum_display_status |= disp_st
        tocheck = self._async_tocheck
        #print 'tocheck %0x %0x %0x'%(tocheck, self._cum_display_status, disp_st)
        if self._cum_display_status&tocheck == tocheck:
            self.write('DSPE 0')
            self._cum_display_status = 0
            return True # We are done!
        return False
    def _fetch_getformat(self, **kwarg):
        xaxis = kwarg.get('xaxis', True)
        if xaxis:
            multi = ('freq', 'data')
        else:
            multi = True
        fmt = self.fetch._format
        fmt.update(multi=multi, graph=[], xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_getdev(self, disp=None, xaxis=True):
        """
        Optional parameter: disp and xaxis
         -disp:  To select which display to read.
         -xaxis: when True(default), the first column of data is the xaxis
        For faster transfer, make the view and unit the same type (both linear or both log)
        It is STRONGLY recommended to use linear averaging.
        For exponential averaging you need to specify a wait time with async_wait
         i.e. set(srnet.async_wait,3)  # for 3 seconds
        """
        # The instrument has 5 Traces that can be used for memory.
        # There is REFY? d,j to obtain pint j (0..length-1) in ref curve of display d
        #  DSPN? d to obtain lenght of data set
        if disp is not None:
            self.current_display.set(disp)
        disp = self.current_display.getcache()
        disp = self.current_display._tostr(disp)
        # DSPY returns ascii but is slower than DSPB (binary)
        # TODO implement handling of nyquist and nichols plot which return 2 values per datapoint.
        # TODO handle waterfalls: dswb
        data = self.ask('DSPB? %s'%disp, raw=True)
        ret = np.fromstring(data, np.float32)
        if xaxis:
            ret = ret = np.asarray([self.get_xscale(), ret])
        return ret
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        if options.has_key('disp'):
            self.current_display.set(options['disp'])
        want_ch = 1
        meas = self.meas.getcache()
        # This does not handle Coherence, CrossSpectrum F2/F1 ...
        if meas[-1] == '2' and meas[-4:-1] != 'ser':
            want_ch = 2
        orig_ch = self.current_channel.getcache()
        if want_ch != orig_ch:
            self.current_channel.set(want_ch)
        conf = self._conf_helper('current_display', 'current_channel',
                                 'input_source', 'input_mode', 'input_grounding', 'input_coupling',
                                 'input_range_dBV', 'input_autorange_en', 'input_autorange_mode', 'input_antialiasing_en',
                                 'input_aweight_en', 'input_auto_offset_en', 'input_eng_unit_en', 'input_eng_label',
                                 'input_eng_unit_scale', 'input_eng_unit_user',
                                 'freq_start', 'freq_stop', 'freq_resolution', 'freq_baseline', 'window_type',
                                 'meas_group', 'meas', 'meas_view',
                                 'meas_unit', 'dBm_ref', 'disp_PSD_en', 'disp_transducer_unit_mode',
                                 'disp_live_en',
                                 'average_en', 'average_mode', 'average_type', 'average_count_requested',
                                 'average_increment_pct', 'average_overload_reject_en', 'average_preview_type',
                                 'source_en', 'source_type', 'source_freq1', 'source_ampl1_V',
                                 'source_offset_V', 'source_freq2', 'source_ampl2_V', 'async_wait',
                                 options)
        if want_ch != orig_ch:
            self.current_channel.set(orig_ch)
        return conf
    def _create_devs(self):
        display_sel = ChoiceIndex(['A', 'B']) # also both=2
        self.current_display = MemoryDevice('A', choices=display_sel)
        self.current_channel = MemoryDevice(1, choices=[1, 2])
        self.freq_baseline = scpiDevice('FBAS 2,{val}', 'FBAS? 0', choices=ChoiceIndex([100e3, 102.4e3]))
        self.dBm_ref = scpiDevice('DBMR 2,{val}', 'DBMR? 2', str_type=float, min=0)
        self.source_en = scpiDevice('SRCO', str_type=bool)
        self.source_type = scpiDevice('STYP', choices=ChoiceIndex(['Sine', 'Chirp', 'Noise', 'Arbitrary']))
        self.source_freq1 = scpiDevice('S1FR', str_type=float)
        self.source_ampl1_V = scpiDevice('S1AM', str_type=float)
        self.source_offset_V = scpiDevice('SOFF', str_type=float)
        self.source_freq2 = scpiDevice('S2FR', str_type=float)
        self.source_ampl2_V = scpiDevice('S2AM', str_type=float)
        self.input_source = scpiDevice('ISRC', choices=ChoiceIndex(['Analog', 'Capture']))
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.input_mode = devChOption('I{ch}MD', choices=ChoiceIndex(['Analog', 'Capture']))
        self.input_grounding = devChOption('I{ch}GD', choices=ChoiceIndex(['Float', 'Ground']))
        self.input_coupling = devChOption('I{ch}CP', choices=ChoiceIndex(['DC', 'AC', 'ICP']))
        self.input_range_dBV = devChOption('I{ch}RG', str_type=int, choices=range(-50, 36, 2))
        self.input_autorange_en = devChOption('A{ch}RG', str_type=bool)
        self.input_autorange_mode = devChOption('I{ch}AR', choices=ChoiceIndex(['Normal', 'Tracking']))
        self.input_antialiasing_en = devChOption('I{ch}AF', str_type=bool)
        self.input_aweight_en = devChOption('I{ch}AW', str_type=bool)
        self.input_auto_offset_en = scpiDevice('IAOM', str_type=bool)
        self.input_eng_unit_en = devChOption('EU{ch}M', str_type=bool)
        self.input_eng_label = devChOption('EU{ch}L', str_type=ChoiceIndex(['m/s2', 'm/s', 'm', 'in/s2', 'in/s', 'in', 'mil', 'g', 'kg', 'lbs', 'N', 'dyne', 'Pas', 'bar', 'USER']))
        self.input_eng_unit_scale = devChOption('EU{ch}V', str_type=float, doc='number of eng.unit/Volt')
        self.input_eng_unit_user = devChOption('EU{ch}U', str_type=str)
        def devDispOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(disp=self.current_display)
            app = kwarg.pop('options_apply', ['disp'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.freq_span = devDispOption('FSPN {disp},{val}', 'FSPN? {disp}', str_type=float, setget=True)
        self.freq_start = devDispOption('FSTR {disp},{val}', 'FSTR? {disp}', str_type=float, setget=True, min=0, max=102.4e3)
        self.freq_stop = devDispOption('FEND {disp},{val}', 'FEND? {disp}', str_type=float, setget=True, min=0, max=102.4e3)
        self.freq_center = devDispOption('FCTR {disp},{val}', 'FCTR? {disp}', str_type=float, setget=True, min=0, max=102.4e3)
        resol_sel = ChoiceIndex([100, 200, 400, 800])
        self.freq_resolution = devDispOption('FLIN {disp},{val}', 'FLIN? {disp}', choices=resol_sel)
        mgrp_sel = ChoiceIndex(['FFT', 'Octave', 'Swept Sine'])
        self.meas_group = devDispOption('MGRP {disp},{val}', 'MGRP? {disp}', choices=mgrp_sel)
        meas_sel = ChoiceIndex(['FFT1', 'FFT2', 'Time1', 'Time2', 'WindowedTime1', 'WindowedTime2',
                                'Orbit', 'Coherence', 'CrossSpectrum', '<F2/F1>', '<F2>/<F1>',
                                'AutoCorr1', 'AutoCorr2', 'CaptureBuffer1', 'CaptureBuffer2',
                                'FFTuser1', 'FFTuser2', 'FFTuser3', 'FFTuser4', 'FFTuser5',
                                'Octave1', 'Octave2', 'OctaveCapBuff1', 'OctaveCapBuff2',
                                'OctaveUser1', 'OctaveUser2', 'OctaveUser3', 'OctaveUser4', 'OctaveUser5',
                                'SweptSpectrum1', 'SweptSpectrum2', 'SweptCross', 'SweptTransferFunction',
                                'SweptUser1', 'SweptUser2', 'SweptUser3', 'SweptUser4', 'SweptUser5'])
        self.meas = devDispOption('MEAS {disp},{val}', 'MEAS? {disp}', choices=meas_sel)
        view_sel = ChoiceIndex(['LogMag', 'LinMag', 'MagSquared', 'Real', 'Imag', 'Phase', 'UnWrapPhase', 'Nyquist', 'Nichols'])
        self.meas_view = devDispOption('VIEW {disp},{val}', 'VIEW? {disp}', choices=view_sel)
        unit_sel = ChoiceIndex(['Vpk', 'Vrms', 'Vpk2', 'Vrms2', 'dBVpk', 'dBVrms', 'dBm', 'dBspl', 'deg', 'rad', 'Units', 'dB'])
        self.meas_unit = devDispOption('UNIT {disp},{val}', 'UNIT? {disp}', choices=unit_sel)
        self.disp_live_en = devDispOption('DISP {disp},{val}', 'DISP? {disp}', str_type=bool)
        self.disp_log_xscale = devDispOption('XAXS {disp},{val}', 'XAXS? {disp}', str_type=bool)
        self.disp_PSD_en = devDispOption('PSDU {disp},{val}', 'PSDU? {disp}', str_type=bool, doc='Wether PSD (power spectral density) is enabled.')
        self.disp_transducer_unit_mode = devDispOption('TDRC {disp},{val}', 'TDRC? {disp}', choices=ChoiceIndex(['acceleration', 'velocity', 'displacement']))
        self.average_en = devDispOption('FAVG {disp},{val}', 'FAVG? {disp}', str_type=bool)
        self.average_mode = devDispOption('FAVM {disp},{val}', 'FAVM? {disp}', choices=ChoiceIndex(['vector', 'RMS', 'PeakHold']))
        self.average_type = devDispOption('FAVT {disp},{val}', 'FAVT? {disp}', choices=ChoiceIndex(['linear', 'exponential', 'FixedLength', 'continuous']))
        self.average_count_requested = devDispOption('FAVN {disp},{val}', 'FAVN? {disp}', str_type=int, min=2, max=32767)
        self.average_count = devDispOption(getstr='NAVG? {disp}', str_type=int)
        self.average_increment_pct = devDispOption('FOVL {disp},{val}', 'FOVL? {disp}', str_type=float, min=0, max=300)
        self.average_overload_reject_en = scpiDevice('FREJ 2,{val}', 'FREJ? 0', str_type=bool)
        self.average_preview_type = devDispOption('PAVO {disp},{val}', 'PAVO? {disp}', choices=ChoiceIndex(['off', 'manual', 'timed']))
        self.window_type = devDispOption('FWIN {disp},{val}', 'FWIN? {disp}', choices=ChoiceIndex(['uniform', 'flattop', 'hanning', 'BMH', 'kaiser', 'force', 'exponential', 'user', '-T/2..T/2', '0..T/2', '-T/4..T/4',]))
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        self._devwrap('dump', autoinit=False)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
    @locked_calling
    def get_xscale(self):
        # only works for fft
        start = self.freq_start.getcache()
        stop = self.freq_stop.getcache()
        npoints = self.freq_resolution.getcache() + 1 # could also use DSPN? d
        return np.linspace(start, stop, npoints)
    def _dump_getformat(self, ps=True, **kwarg):
        fmt = self.dump._format
        if ps:
            binfmt = '.ps'
        else:
            binfmt = '.gif'
        fmt.update(bin=binfmt)
        return BaseDevice.getformat(self.dump, **kwarg)
    def _dump_getdev(self, ps=True, area='all'):
        """
        options are ps, area
         -ps: when True (default) returns a postscript object, otherwise returns a GIF file
         -area: used for GIF files, one of 'graph', 'menu', 'status' or 'all'(default)
        """
        # Reading data is tricky because the instrument does not send
        # EOI on its last byte so we either need to detect the ending comment
        # of the postscript or wait for the first timeout to occur for
        # the bitmap.
        # Also when the remote output is set to GPIB we do no receive the last byte.
        # So we need to switch the output to RS232 first.
        area_sel = dict(graph=0, menu=1, status=2, all=3)
        # POUT sets hardware print key to bitmap or vector
        # PDST 3 selects GPIB
        # PCIC 0 selects host controller
        # PLTP selects postscript
        # PRTP selects GIF
        r=''
        old_to = self.set_timeout
        self.set_timeout=.5 # useful for bitmap mode since we need to wait for timeout
        self.write('OUTX 1') # Go to RS232 interface
        if ps:
            self.write('POUT 1;PDST 3;PCIC 0;PLTP 1;PLOT')
            while r[-11:] != '%%Trailer\r\n':
                r += self.visa.read_raw_n(1)
        else:
            self.write('POUT 0;PDST 3;PCIC 0;PRTP 4;PSCR %d;PRNT'%area_sel[area])
            try:
                while True:
                    r += self.visa.read_raw_n(1)
            except visa_wrap.VisaIOError:
                pass
        self.write('OUTX 0') # return to gpib interface
        self.set_timeout = old_to
        return r
    # serial poll status word: 0=INSTrument, 1=DISPlay, 2=INPuT, 3=ERRor, 4=output buffer empty
    #                          5=standard status word, 6=SRQ, 7=IFC (no command execution in progress)
    def get_instrument_status(self):
        """
         returns a byte of bit flags
          bit 0 (1):   A measurement has been triggered
          bit 1 (2):   Disk operation complete
          bit 2 (4):   Hardcopy output complete
          bit 3 (8):   unused
          bit 4 (16):  Capture buffer filled
          bit 5 (32):  Measurement has been paused
          bit 6 (64):  Measurement has been started
          bit 7 (128): Single shot capture playback has finished
          bit 8 (256): Measurement stopped to wait for average preview
          bit 9-15: unused
        """
        # can access bits with inst? 1
        # can enable in status register with INSE
        return int(self.ask('INST?'))
    def get_display_status(self):
        """
         returns a byte of bit flags
          bit 0 (1):    displayA has new data
          bit 1 (2):    displayA linear average complete
          bit 2 (4):    displayA new settled data available
          bit 3 (8):    displayA failed a limit test
          bit 4 (16):   displayA swept sine has failed
          bit 5 (32):   displayA 1-shot waterfall has finished
          bit 6-7:      unused
          bit 8 (256):  displayB has new data
          bit 9 (512):  displayB linear average complete
          bit 10 (1024):displayB new settled data available
          bit 11 (2048):displayB failed a limit test
          bit 12 (4096):displayB swept sine has failed
          bit 13 (8192):displayB 1-shot waterfall has finished
          bit 14-15:    unused
         except for waterfall always test for new data (bit 0/8) for
         the correct display first.
        """
        # can access bits with inst? 1
        # can enable in status register with DSPE
        return int(self.ask('DSPS?'))
    def get_input_status(self):
        """
         returns a byte of bit flags
          bit 0 (1):    input1 has fallend below half of full scale
          bit 1 (2):    input1 has exceeded half of full scale
          bit 2 (4):    input1 has exceeded full scale
          bit 3 (8):    input1 has exceeded 35 dBV, range switched to 34 dBV
          bit 4 (16):   input1 has autoranged
          bit 5-7:      unused
          bit 8 (256):  input2 has fallend below half of full scale
          bit 9 (512):  input2 has exceeded half of full scale
          bit 10 (1024):input2 has exceeded full scale
          bit 11 (2048):input2 has exceeded 35 dBV, range switched to 34 dBV
          bit 12 (4096):input2 has autoranged
          bit 13-15:    unused
        """
        # can access bits with inst? 1
        # can enable in status register with INPE
        # also see INPC? 0 (ch1) or INPC? 1 (ch2)
        # which returns instanteneous a value 0-3 where:
        #   0=input under half full scale
        #   1=input over half full scale
        #   2=input overloaded
        #   3=input is HighV
        return int(self.ask('INPS?'))
    @locked_calling
    def get_error(self):
        """
         returns two byte of bit flags
         first:
          bit 0-1:     unused
          bit 2 (4):   Too many responses are pending
          bit 3 (8):   too many commands received
          bit 4 (16):  command cannot execute successfully
          bit 5 (32):  command syntax error
          bit 6 (64):  key press or knob rotated
          bit 7 (128): power is turned on
          bit 8-15:    unused
         second:
          bit 0 (1):   An output error as occured (print, plot, dump)
          bit 1 (2):   disk errro
          bit 2 (4):   math error
          bit 3 (8):   RAM memory test fails
          bit 4 (16):  ROM memory test fails
          bit 5 (32):  Video memory test fails
          bit 6 (64):  Help memory test fails
          bit 7 (128): DSP data memory fails
          bit 8 (256): DSP program memory fails
          bit 9 (512): DSP DRAM memory fails
          bit 10 (1024): DSP calibration memory fails
          bit 11 (2048): Ch1 calibration memory fails
          bit 12 (4096): Ch2 calibration memory fails
          bit 13-15: unused
        """
        # can access bits with errs? 1
        # can enable in status register with ERRE
        # enable *ese with *ese
        return int(self.ask('*esr?')),int(self.ask('ERRS?'))


#######################################################
##    Stanford Research DC205 Precision DC Voltage Source
#######################################################

#@register_instrument('Stanford_Research_Systems', 'DC205', 'ver1.80')
@register_instrument('Stanford_Research_Systems', 'DC205', alias='DC205 Precision Voltage Source')
class sr_dc205(visaInstrument):
    """
    This controls a Stanford Research DC205 Precision Voltage Source.
    Changing the range is not allowed when the output is enabled.
    Useful devices:
        level
        range
        output_en
    """
    def __init__(self, visa_addr, usb=True, **kwargs):
        """ When usb is True, the default, it sets the requisite baud rate for the internal usb to serial
            converter. """
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == visa_wrap.constants.InterfaceType.asrl:
            if usb:
                kwargs['baud_rate'] = 115200
        super(sr_dc205, self).__init__(visa_addr, **kwargs)

    def init(self, full=False):
        if full:
            self.write('TOKN 0')
            self.write('DCPT 0, 1') # 0 to 1 transition for overload bit

    def get_error(self):
        exe = int(self.ask('LEXE?'))
        cmd = int(self.ask('LCME?'))
        exe_errors = {0:'NoErrors',
                      1: 'Illegal value',
                      2: 'Wrong Token',
                      3: 'Invalid bit',
                      4: 'Queue full',
                      5: 'Not compatible'}
        cmd_errors = {0: 'NoError',
                      1: 'Illegal command',
                      2: 'Undefined command',
                      3: 'Illegal query',
                      4: 'Illegal set',
                      5: 'Missing parameter(s)',
                      6: 'Extra parameter(s)',
                      7: 'Null parameter(s)',
                      8: 'Parameter buffer overflow',
                      9: 'Bad floating-point',
                      10: 'Bad integer',
                      11: 'Bad integer token',
                      12: 'Bad token value',
                      13: 'Bad hex block',
                      14: 'Unknown Token',
                      }
        exe_msg = exe_errors[exe]
        cmd_msg = cmd_errors[cmd]
        if exe == cmd == 0:
            return "No Errors"
        elif cmd == 0:
            return exe_msg
        elif exe == 0:
            return cmd_msg
        else:
            return cmd_msg + ', ' + exe_msg
    def _extra_check_output_en(self, val, dev_obj):
        if self.output_en.get():
            raise RuntimeError(dev_obj.perror('dev cannot be changed while output is enabled.'))

    def trigger(self):
        self.write('*TRG')
    def scan_repeat_stop(self):
        """ This turns off repeat. It will stop at the end of the current cycle. """
        self.scan_repeat_en.set(False)

    @locked_calling
    def set_scan(self, start, stop, duration, range='current', updown=False, repeat=False):
        """ range can be one of the ranges (1, 10, 100) or it can be
                  'auto' to adjust depending on the start/stop values or
                  'current' to select the currently enabled range.
                  It defaults to current
        """
        if range not in ['current', 'auto', 1, 10, 100]:
            raise ValueError('Invalid range.')
        if range == 'current':
            range = self.range.get()
        elif range == 'auto':
            largest = max(abs(start), abs(stop))
            if largest > 10.1:
                range = 100.
            elif largest > 1.01:
                range = 10.
            else:
                range = 1.
        if abs(start) > range*1.01:
            raise ValueError('start value is out of range')
        if abs(stop) > range*1.01:
            raise ValueError('stop value is out of range')
        self.scan_range.set(range)
        self.scan_start.set(start)
        self.scan_stop.set(stop)
        self.scan_time.set(duration)
        self.scan_updown_en.set(updown)
        self.scan_repeat_en.set(repeat)
    @locked_calling
    def show_scan(self):
        return dict(range=self.scan_range.get(),
                    start=self.scan_start.get(),
                    stop=self.scan_stop.get(),
                    duration=self.scan_stop.get(),
                    updown=self.scan_updown_en.get(),
                    repeat=self.scan_repeat_en.get())

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('level', 'output_en', 'range', 'remote_sense_en', 'floating_en',
                                 'is_overloaded', 'is_interlocked', 'is_overloaded_in_past',
                                 'scan_range', 'scan_start', 'scan_stop',
                                 'scan_time', 'scan_updown_en', 'scan_repeat_en', options)

    def _create_devs(self):
        self.floating_en = scpiDevice('ISOL', str_type=bool, doc="When False, the instrument is grounded. When True, it is floating with 10 MOhm")
        extra_check_output_en = ProxyMethod(self._extra_check_output_en)
        ranges = ChoiceIndex([1., 10., 100.])
        self.range = scpiDevice('RNGE', choices=ranges, extra_check_func=extra_check_output_en)
        self.remote_sense_en = scpiDevice('SENS', str_type=bool)
        self.output_en =  scpiDevice('SOUT', str_type=bool)
        level_choices = ChoiceDevDep(self.range, {1.: ChoiceLimits(-1.01, 1.01, str_type=float),
                                                  10: ChoiceLimits(-10.1, 10.1, str_type=float),
                                                  100:ChoiceLimits(-101., 101., str_type=float)})
        self.level = scpiDevice('VOLT', choices=level_choices, setget=True)
        self.is_overloaded = scpiDevice(getstr='OVLD?', str_type=bool)
        self.is_interlocked = scpiDevice(getstr='ILOC?', str_type=bool)
        self.is_overloaded_in_past = scpiDevice(getstr='DCEV? 0', str_type=bool)

        self.scan_range = scpiDevice('SCAR', choices=ranges)
        self.scan_start = scpiDevice('SCAB', str_type=float, setget=True)
        self.scan_stop = scpiDevice('SCAE', str_type=float, setget=True)
        self.scan_time = scpiDevice('SCAT', str_type=float, setget=True, min=0.1, max=9999.9)
        self.scan_updown_en = scpiDevice('SCAS', str_type=bool)
        self.scan_repeat_en = scpiDevice('SCAC', str_type=bool)
        self.scan_display_update_en = scpiDevice('SCAD', str_type=bool)
        self.scan_arm = scpiDevice('SCAA', str_type=bool)
        self.scan_arm_status = scpiDevice(getstr='SCAA?', choices=ChoiceIndex(['idle', 'armed', 'scanning']))

        self.alias = self.level
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
