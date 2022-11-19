# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2018-2018  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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
import scipy
import os.path

from ..instruments_base import visaInstrument, visaInstrumentAsync,\
                            scpiDevice, MemoryDevice, ReadvalDev, BaseDevice,\
                            ChoiceMultiple, Choice_bool_OnOff, Choice_bool_YesNo, _repr_or_string,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDev, ChoiceDevSwitch, ChoiceIndex,\
                            ChoiceLimits, quoted_string, _fromstr_helper, ProxyMethod, decode_float64,\
                            locked_calling, _encode_block, _decode_block
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

register_usb_name('Rigol Technologies', 0x1AB1)

#######################################################
##    Rigol Programmable DC Power Supply DP831A
#######################################################

#@register_instrument('RIGOL TECHNOLOGIES', 'DP831A', '00.01.14')
@register_instrument('RIGOL TECHNOLOGIES', 'DP831A', usb_vendor_product=[0x1AB1, 0x0E11])
class rigol_power_dp831a(visaInstrument):
    """
    This is the driver for the RIGOL programmable DC power supply DP831A.
    Channels 1, 2, 3 are respectively the 8V/5A, +30V/2A and -30V/2A.
    Useful devices:
      voltage, current, output_en
    """
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        chs = self.channel_en_list()
        opts = ['enabled_channels=%r'%chs ]
        cch = self.current_meas_channel.get()
        opt_c = []
        for c in [1, 2, 3]:
            self.current_channel.set(c)
            r = self._conf_helper('output_en', 'current', 'voltage', 'output_mode', 'voltage_protection_en', 'voltage_protection_level', 'voltage_protection_tripped', 'current_protection_en', 'current_protection_level', 'current_protection_tripped', 'output_track_en')
            opt_c.append(r)
        titles =  [ t.split('=', 1)[0] for t in opt_c[0] ]
        data = [ [o.split('=', 1)[1] for o in ol] for ol in opt_c]
        for i, t in enumerate(titles):
            d = '%s=[%s]'%(t, ','.join([data[j][i] for j in range(3)]))
            opts.append(d)
        opts += self._conf_helper('on_off_sync', 'over_temperature_protection_en' , 'track_mode')
        return opts + self._conf_helper(options)

    def _fetch_getformat(self, **kwarg):
        ch = kwarg.get('ch', None)
        select = kwarg.get('select', 'all')
        chs, select = self._fetch_helper(ch, select)
        multi = []
        for c in chs:
            multi.extend(['ch%i_'%c+s for s in select])
        fmt = self.fetch._format
        fmt.update(multi=multi)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_helper(self, ch, select):
        if ch is None:
            ch = self.channel_en_list()
        if not isinstance(ch, (list, tuple, np.ndarray)):
            ch = [ch]
        if len(ch)==0:
            raise RuntimeError(self.perror('No output are enabled/selected for fetch.'))
        if select == 'all':
            select = ['voltage', 'current', 'power']
        if not isinstance(select, (list, tuple, np.ndarray)):
            select = [select]
        for s in select:
            if s not in ['voltage', 'current', 'power']:
                raise ValueError(self.perror('Invalid option for select in fetch'))
        return ch, select
    def _fetch_getdev(self, ch=None, select='all'):
        """ ch can ne a single channel, or a list of channels to read.
                 by default reads all enabled channels
            select can be a single or a list of 'power, voltage, current'
                   the default 'all' is the same as ['voltage', 'current', 'power']
        """
        chs, select = self._fetch_helper(ch, select)
        cch = self.current_meas_channel.get()
        ret = []
        ind = dict(voltage=0, current=1, power=2)
        for c in chs:
            vals = self.meas_all.get(ch=c)
            for s in select:
                ret.append(vals[ind[s]])
        self.current_meas_channel.set(cch)
        return ret

    def channel_en_list(self):
        cch = self.current_channel.getcache()
        ret = [ ch for ch in range(1,4) if self.output_en.get(ch=ch)]
        self.current_channel.setcache(cch)
        return ret

    def current_protection_clear(self, ch=None):
        if ch is None:
            ch = self.current_channel.getcache()
        else:
            self.current_channel.set(ch)
        self.write('CURRent:PROTection:CLEar')
    def voltage_protection_clear(self, ch=None):
        if ch is None:
            ch = self.current_channel.getcache()
        else:
            self.current_channel.set(ch)
        self.write('VOLTage:PROTection:CLEar')

    def get_questionable_status(self):
        def do_ch(ch):
            return dict(voltage_control=bool(ch&1), current_control=bool(ch&2), ovp_tripped=bool(ch&4), ocp_tripped=bool(ch&8))
        ch1 = int(self.ask('STATus:QUEStionable:INSTrument:ISUMmary1?'))
        ch2 = int(self.ask('STATus:QUEStionable:INSTrument:ISUMmary2?'))
        ch3 = int(self.ask('STATus:QUEStionable:INSTrument:ISUMmary3?'))
        # ch_sum = int(self.ask('STATus:QUEStionable:INSTrument?')) # bit 1,2,3 correspond to above ch1,ch2 ch3 summary. (bit 0 is first one)
        other = int(self.ask('STATus:QUEStionable?')) # bit 13 is ch_sum summary
        fan = bool((other>>11)&1)
        temp = bool((other>>4)&1)
        return dict(fan_problem=fan, temperature_problem=temp, ch1=do_ch(ch1), ch2=do_ch(ch2), ch3=do_ch(ch3))

    def _create_devs(self):
        # TODO: add analyzer, delay, Memory, Monitor, output:timer, Preset, Recall, Recorder, Store, Timer, Trigger
        self.current_channel = MemoryDevice(choices=[1, 2, 3], initval=1)
        def devChOption(setstr=None, getstr=None,  **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            if setstr and '{ch}' not in setstr:
                getstr = setstr+'? CH{ch}'
                setstr = setstr+' CH{ch},{val}'
            return scpiDevice(setstr, getstr, **kwarg)
        self.current_meas_channel = MemoryDevice(choices=[1, 2, 3], initval=1)
        def devChMeasOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_meas_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.meas_all = devChMeasOption(getstr='MEASure:ALL? CH{ch}', str_type=decode_float64, autoinit=False,
                multi=['voltage_V', 'current_A', 'power_W'])
        self.meas_current = devChMeasOption(getstr='MEASure:CURRent? CH{ch}', str_type=float, autoinit=False)
        self.meas_voltage = devChMeasOption(getstr='MEASure:VOLTage? CH{ch}', str_type=float, autoinit=False)
        self.meas_power = devChMeasOption(getstr='MEASure:POWEr? CH{ch}', str_type=float, autoinit=False)
        self.output_en = devChOption('OUTPut', choices=Choice_bool_OnOff)
        self.output_mode = devChOption(getstr='OUTPut:MODE? CH{ch}', choices=ChoiceStrings('CC', 'CV', 'UR'))
        # output:ocp, output:ovp are the same as source:current:protection, source:voltage:protection
        chs = [2,3] #for dp831a
        self.output_track_en = devChOption('OUTPut:TRACk', choices=Choice_bool_OnOff, options_lim=dict(ch=chs))
        #self.output_track_en = devChOption('OUTPut:TRACk', choices=Choice_bool_OnOff, options_lim=dict(ch=chs), autoinit=False)
        #self.output_sense_en = devChOption('OUTPut:SENSe', choices=Choice_bool_OnOff)
        lims = [self._get_dev_min_max('SOURce{ch}:CURRent?'.format(ch=i)) for i in range(1,4)]
        current_lims = ChoiceDevDep(self.current_channel, {i+1:ChoiceLimits(min=lims[i][0], max=lims[i][1]) for i in range(3) })
        self.current = devChOption('SOURce{ch}:CURRent', str_type=float, choices=current_lims)
        self.current_protection_level = devChOption('SOURce{ch}:CURRent:PROTection', str_type=float)
        self.current_protection_en = devChOption('SOURce{ch}:CURRent:PROTection:STATe', choices=Choice_bool_OnOff)
        self.current_protection_tripped = devChOption(getstr='SOURce{ch}:CURRent:PROTection:TRIPped?', choices=Choice_bool_YesNo)
        lims = [self._get_dev_min_max('SOURce{ch}:VOLTage?'.format(ch=i)) for i in range(1,4)]
        lims[2] = sorted(lims[2]) # instrument returns min/max incorrectly for the negative channel
        voltage_lims = ChoiceDevDep(self.current_channel, {i+1:ChoiceLimits(min=lims[i][0], max=lims[i][1]) for i in range(3) })
        self.voltage = devChOption('SOURce{ch}:VOLTage', str_type=float, choices=voltage_lims)
        self.voltage_protection_level = devChOption('SOURce{ch}:VOLTage:PROTection', str_type=float)
        self.voltage_protection_en = devChOption('SOURce{ch}:VOLTage:PROTection:STATe', choices=Choice_bool_OnOff)
        self.voltage_protection_tripped = devChOption(getstr='SOURce{ch}:VOLTage:PROTection:TRIPped?', choices=Choice_bool_YesNo)
        self.on_off_sync = scpiDevice('SYSTem:ONOFFSync', choices=Choice_bool_OnOff)
        self.over_temperature_protection_en = scpiDevice('SYSTem:OTP', choices=Choice_bool_OnOff)
        self.track_mode = scpiDevice('SYSTem:TRACKMode', choices=ChoiceStrings('SYNC', 'INDE'))
        self._devwrap('fetch', autoinit=False)
        self.alias = self.voltage
        # This needs to be last to complete creation
        super(rigol_power_dp831a, self)._create_devs()


#######################################################
##    Rigol AWG DG812
#######################################################

class float_as_int(object):
    def __call__(self, input_str):
        return int(float(input_str))
    def tostr(self, val):
        return '%d'%val

#@register_instrument('Rigol Technologies', 'DG812', '00.02.05.00.00 ')
@register_instrument('Rigol Technologies', 'DG812', usb_vendor_product=[0x1AB1, 0x643])
class rigol_awg_dg812(visaInstrument):
    """
    This is the driver for the RIGOL AWG generator DG812.
    """
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = self._conf_helper('ref_oscillator_current_state', 'coupled_ampl_en', 'coupled_freq_en')
        if self.coupled_freq_en.getcache():
            opts += self._conf_helper('coupled_freq_mode')
            if self.coupled_freq_mode.getcache().upper().startswith('OFF'):
                opts += self._conf_helper('coupled_freq_offset')
            else:
                opts += self._conf_helper('coupled_freq_ratio')
        curr_ch = self.current_ch.getcache()
        ch = options.get('ch', None)
        if ch is not None:
            self.current_ch.set(ch)
        opts += self._conf_helper('current_ch', 'out_en', 'ampl', 'ampl_unit', 'offset',
                                  'volt_limit_low', 'volt_limit_high', 'volt_limit_en', 'out_load_ohm', 'out_polarity',
                                  'out_sync_polarity', 'out_sync_en',
                                  'freq', 'phase', 'mode', 'pulse_width',
                                  'mod_am_en', 'mod_am_depth_pct', 'mod_am_dssc_en', 'mod_am_src', 'mod_am_int_func', 'mod_am_int_freq',
                                  'mod_fm_en', 'mod_phase_en',
                                  'seq_filter', 'seq_sample_rate', 'seq_edge_time',
                                  'current_seq', 'seq_n_period', 'seq_n_period'
                                  )
        self.current_ch.set(curr_ch)
        return opts + self._conf_helper(options)

    def _wait_after_write(self, *args, **kwargs):
        self.ask('*OPC?')

    def _create_devs(self):
        self.ref_oscillator = scpiDevice('SYSTem:ROSCillator:SOURce', choices=ChoiceStrings('INTernal', 'EXTernal'))
        self.ref_oscillator_current_state = scpiDevice(getstr='ROSCillator:SOURce:CURRent?', choices=ChoiceStrings('INTernal', 'EXTernal'))
        # new interface
        self.current_ch = MemoryDevice(1, min=1, max=2)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.coupled_ampl_en = devChOption('SOURce{ch}:VOLTage:COUPle', str_type=Choice_bool_OnOff)
        self.ampl = devChOption('SOURce{ch}:VOLTage', str_type=float, setget=True, doc="""Minimum is 2 mVpp. See ampl_unit device for unit type (Vrms, Vpp or dBm)""")
        self.offset = devChOption('SOURce{ch}:VOLTage:OFFSet', str_type=float, setget=True)
        self.ampl_unit = devChOption('SOURce{ch}:VOLTage:UNIT', choices=ChoiceStrings('VPP', 'VRMS', 'DBM'))
        self.volt_limit_low = devChOption('OUTPut{ch}:VOLLimit:LOW', str_type=float, setget=True, doc="""Output will not go below this voltage, if limit is enabled.""")
        self.volt_limit_high = devChOption('OUTPut{ch}:VOLLimit:HIGH', str_type=float, setget=True, doc="""Output will not go above this voltage, if limit is enabled.""")
        self.volt_limit_en = devChOption('OUTPut{ch}:VOLLimit:STATe', str_type=Choice_bool_OnOff)
        self.coupled_freq_en = devChOption('SOURce{ch}:FREQuency:COUPle', str_type=Choice_bool_OnOff)
        self.coupled_freq_mode = devChOption('SOURce{ch}:FREQuency:COUPle:MODE', choices=ChoiceStrings('OFFSet', 'RATio'))
        self.coupled_freq_offset = devChOption('SOURce{ch}:FREQuency:COUPle:OFFSet', str_type=float, setget=True)
        self.coupled_freq_ratio = devChOption('SOURce{ch}:FREQuency:COUPle:RATio', str_type=float, setget=True)
        self.freq = devChOption('SOURce{ch}:FREQuency', str_type=float, setget=True)
        self.phase = devChOption('SOURce{ch}:PHASe', str_type=float, setget=True, min=0, max=360, doc='Angle in degrees')
        self.mode = devChOption('SOURce{ch}:FUNCtion', choices=ChoiceStrings(
                'SINusoid', 'SQUare', 'RAMP', 'PULSe', 'NOISe', 'USER', 'HARMonic', 'DC', 'KAISER',
                'ROUNDPM', 'SINC', 'NEGRAMP', 'ATTALT', 'AMPALT', 'STAIRDN', 'STAIRUP', 'STAIRUD',
                'CPULSE', 'PPULSE', 'NPULSE', 'TRAPEZIA', 'ROUNDHALF', 'ABSSINE', 'ABSSINEHALF',
                'SINETRA', 'SINEVER', 'EXPRISE', 'EXPFALL', 'TAN', 'COT', 'SQRT', 'X2DATA', 'GAUSS',
                'HAVERSINE', 'LORENTZ', 'DIRICHLET', 'GAUSSPULSE', 'AIRY', 'CARDIAC', 'QUAKE', 'GAMMA',
                'VOICE', 'TV', 'COMBIN', 'BANDLIMITED', 'STEPRESP', 'BUTTERWORTH', 'CHEBYSHEV1', 'CHEBYSHEV2',
                'BOXCAR', 'BARLETT', 'TRIANG', 'BLACKMAN', 'HAMMING', 'HANNING', 'DUALTONE', 'ACOS', 'ACOSH',
                'ACOTCON', 'ACOTPRO', 'ACOTHCON', 'ACOTHPRO', 'ACSCCON', 'ACSCPRO', 'ACSCHCON', 'ACSCHPRO',
                'ASECCON', 'ASECPRO', 'ASECH', 'ASIN', 'ASINH', 'ATAN', 'ATANH', 'BESSELJ', 'BESSELY',
                'CAUCHY', 'COSH', 'COSINT', 'COTHCON', 'COTHPRO', 'CSCCON', 'CSCPRO', 'CSCHCON', 'CSCHPRO',
                'CUBIC', 'ERF', 'ERFC', 'ERFCINV', 'ERFINV', 'LAGUERRE', 'LAPLACE', 'LEGEND', 'LOG', 'LOGNORMAL',
                'MAXWELL', 'RAYLEIGH', 'RECIPCON', 'RECIPPRO', 'SECCON', 'SECPRO', 'SECH', 'SINH', 'SININT', 'TANH',
                'VERSIERA', 'WEIBULL', 'BARTHANN', 'BLACKMANH', 'BOHMANWIN', 'CHEBWIN', 'FLATTOPWIN', 'NUTTALLWIN',
                'PARZENWIN', 'TAYLORWIN', 'TUKEYWIN', 'CWPUSLE', 'LFPULSE', 'LFMPULSE', 'EOG', 'EEG', 'EMG',
                'PULSILOGRAM', 'TENS1', 'TENS2', 'TENS3', 'SURGE', 'DAMPEDOSC', 'SWINGOSC', 'RADAR', 'THREEAM',
                'THREEFM', 'THREEPM', 'THREEPWM', 'THREEPFM', 'RESSPEED', 'MCNOSIE', 'PAHCUR', 'RIPPLE', 'ISO76372TP1',
                'ISO76372TP2A', 'ISO76372TP2B', 'ISO76372TP3A', 'ISO76372TP3B', 'ISO76372TP4', 'ISO76372TP5A',
                'ISO76372TP5B', 'ISO167502SP', 'ISO167502VR', 'SCR', 'IGNITION', 'NIMHDISCHARGE', 'GATEVIBR', 'SEQUENCE'),
                  extra_set_after_func=ProxyMethod(self._wait_after_write))
        self.pulse_width = devChOption('SOURce{ch}:PULSe:WIDTh', str_type=float) # s
        self.out_en = devChOption('OUTPut{ch}', str_type=Choice_bool_OnOff)
        self.out_load_ohm = devChOption('OUTPut{ch}:LOAD', str_type=float, setget=True, min=1, doc="max is 10 kOhm. For High impedance (INFinity) use 9.9e37")
        self.out_polarity = devChOption('OUTPut{ch}:POLarity', choices=ChoiceStrings('NORMal', 'INVerted'))
        self.out_sync_polarity = devChOption('OUTPut{ch}:SYNC:POLarity', choices=ChoiceStrings('POSitive', 'NEGative'))
        self.out_sync_en = devChOption('OUTPut{ch}:SYNC', str_type=Choice_bool_OnOff)

        # Modulations parameters
        self.mod_am_en = devChOption('SOURce{ch}:AM:STATe', str_type=Choice_bool_OnOff)
        self.mod_am_depth_pct = devChOption('SOURce{ch}:AM:DEPTh', str_type=float, min=0, max=120, setget=True)
        self.mod_am_dssc_en = devChOption('SOURce{ch}:AM:DSSC', str_type=Choice_bool_OnOff, doc="DSSC = Double Sideband Suppressed Carrier")
        self.mod_am_src = devChOption('SOURce{ch}:AM:SOURce', choices=ChoiceStrings('INTernal', 'EXTernal'))
        self.mod_am_int_func = devChOption('SOURce{ch}:AM:INTernal:FUNCtion', choices=ChoiceStrings('SINusoid', 'SQUare', 'RAMP', 'NRAMp', 'TRIangle', 'NOISe', 'USER'))
        self.mod_am_int_freq = devChOption('SOURce{ch}:AM:INTernal:FREQuency', str_type=float, min=2e-3, max=1e6, setget=True)

        self.mod_fm_en = devChOption('SOURce{ch}:FM:STATe', str_type=Choice_bool_OnOff)
        self.mod_phase_en = devChOption('SOURce{ch}:PM:STATe', str_type=Choice_bool_OnOff)

        self.seq_filter = devChOption('SOURce{ch}:FUNCtion:SEQuence:FILTer', choices=ChoiceStrings('SMOOth', 'STEP', 'INSErt'),
                                        extra_set_after_func=ProxyMethod(self._wait_after_write),
                                        doc="INSErt means interpolation filter.")
        self.seq_sample_rate = devChOption('SOURce{ch}:FUNCtion:SEQuence:SRATe', str_type=float)
        self.seq_edge_time = devChOption('SOURce{ch}:FUNCtion:SEQuence:EDGETime', str_type=float,
                                         doc="Only for interpolation(INSErt) filter.")
        # This is documented but does not work (possible replaced by unlisted mode "SEQUENCE")
        #self.seq_en = devChOption('SOURce{ch}:FUNCtion:SEQuence', str_type=bool)
        self.current_seq = MemoryDevice(1, min=1, max=8)
        def devChSeqOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(seq=self.current_seq)
            app = kwarg.pop('options_apply', ['ch', 'seq'])
            kwarg.update(options=options, options_apply=app)
            return devChOption(*arg, **kwarg)
        # this returns floats?
        self.seq_n_period = devChSeqOption('SOURce{ch}:FUNCtion:SEQuence:PERiod {val},{seq}',
                                           'SOURce{ch}:FUNCtion:SEQuence:PERiod? {seq}', str_type=float_as_int())
        self.seq_n_wave = devChSeqOption('SOURce{ch}:FUNCtion:SEQuence:WAVE {val},{seq}',
                                         'SOURce{ch}:FUNCtion:SEQuence:WAVE? {seq}', choices=ChoiceStrings(
                                            'SINusoid', 'SQUare ', 'RAMP', 'PULSe', 'NOISe', 'USER', 'HARMonic',
                                            'CUSTom', 'DC', 'KAISER', 'ROUNDPM', 'SINC', 'NEGRAMP', 'ATTALT',
                                            'AMPALT', 'STAIRDN', 'STAIRUP', 'STAIRUD', 'CPULSE', 'PPULSE',
                                            'NPULSE', 'TRAPEZIA', 'ROUNDHALF', 'ABSSINE', 'ABSSINEHALF',
                                            'SINETRA', 'SINEVER', 'EXPRISE', 'EXPFALL', 'TAN', 'COT', 'SQRT',
                                            'X2DATA', 'GAUSS', 'HAVERSINE', 'LORENTZ', 'DIRICHLET', 'GAUSSPULSE',
                                            'AIRY', 'CARDIAC', 'QUAKE', 'GAMMA', 'VOICE', 'TV', 'COMBIN', 'BANDLIMITED',
                                            'STEPRESP', 'BUTTERWORTH', 'CHEBYSHEV1', 'CHEBYSHEV2', 'BOXCAR',
                                            'BARLETT', 'TRIANG', 'BLACKMAN', 'HAMMING', 'HANNING', 'DUALTONE',
                                            'ACOS', 'ACOSH', 'ACOTCON', 'ACOTPRO', 'ACOTHCON', 'ACOTHPRO',
                                            'ACSCCON', 'ACSCPRO', 'ACSCHCON', 'ACSCHPRO', 'ASECCON', 'ASECPRO',
                                            'ASECH', 'ASIN', 'ASINH', 'ATAN', 'ATANH', 'BESSELJ', 'BESSELY',
                                            'CAUCHY', 'COSH', 'COSINT', 'COTHCON', 'COTHPRO', 'CSCCON',
                                            'CSCPRO', 'CSCHCON', 'CSCHPRO', 'CUBIC', 'ERF', 'ERFC',
                                            'ERFCINV', 'ERFINV', 'LAGUERRE', 'LAPLACE', 'LEGEND', 'LOG',
                                            'LOGNORMAL', 'MAXWELL', 'RAYLEIGH', 'RECIPCON', 'RECIPPRO',
                                            'SECCON', 'SECPRO', 'SECH', 'SINH', 'SININT', 'TANH', 'VERSIERA',
                                            'WEIBULL', 'BARTHANN', 'BLACKMANH', 'BOHMANWIN', 'CHEBWIN',
                                            'FLATTOPWIN', 'NUTTALLWIN', 'PARZENWIN', 'TAYLORWIN', 'TUKEYWIN',
                                            'CWPUSLE', 'LFPULSE', 'LFMPULSE', 'EOG', 'EEG', 'EMG', 'PULSILOGRAM',
                                            'TENS1', 'TENS2', 'TENS3', 'SURGE', 'DAMPEDOSC', 'SWINGOSC', 'RADAR',
                                            'THREEAM', 'THREEFM', 'THREEPM', 'THREEPWM', 'THREEPFM', 'RESSPEED',
                                            'MCNOSIE', 'PAHCUR', 'RIPPLE', 'ISO76372TP1', 'ISO76372TP2A',
                                            'ISO76372TP2B', 'ISO76372TP3A', 'ISO76372TP3B', 'ISO76372TP4',
                                            'ISO76372TP5A', 'ISO76372TP5B', 'ISO167502SP', 'ISO167502VR',
                                            'SRC', 'IGNITION', 'NIMHDISCHARGE', 'GATEVIBR'))

        self.remote_cwd = scpiDevice('MMEMory:CDIRectory', str_type=quoted_string(fromstr=False),
                             doc=r"""
                                  instrument default is C:\\
                                  Available drives are C or D.
                                  """)

        self.alias = self.freq
        # This needs to be last to complete creation
        super(rigol_awg_dg812, self)._create_devs()
    def phase_sync(self):
        self.write('PHASe:SYNChronize')
    def file_store(self, filename):
        """
          stores the current config (.RSF) or currrent arbitrary (.RAF)
          into filename.
          The filename is limited to 7 uppercase characters or numbers.
          You need to include the extension, either .RSF or .RAF.
        """
        self.write(':MMEMory:STORe "%s"'%filename)
    def file_load(self, filename):
        """
          load the config (.RSF) or arbitrary (.RAF)
          from filename to the current setting or arb curve.
          The filename is limited to 7 uppercase characters or numbers.
          You need to include the extension, either .RSF or .RAF.
        """
        self.write(':MMEMory:LOAD "%s"'%filename)
    def remote_ls(self, remote_path=None, show_space=False, show_size=False):
        """
            if remote_path is None, get catalog of device remote_cwd.
            Directories are show with an ending /
            returns None for empty and invalid directories.
            The drives are called C: and D: (usb drive).
            if show_space is enable, it returns
               file_list, used, free
            if show_size is enabled, file_list are tuples of name, size
        """
        extra = ""
        if remote_path:
            extra = ' "%s"'%remote_path
        res = self.ask('MMEMory:CATalog?'+extra)
        p = res.split(',', 2)
        used = int(p[0])
        free = int(p[1])
        if len(p) <= 2:
            return None
        # Here I presume no " or , can show up inside the filename.
        lst = p[2].strip('"').rstrip('"').split('","')
        outlst = []
        for l in lst:
            fsize, ftype, fname = l.rsplit(',', 2)
            fsize = int(fsize)
            if ftype == 'DIR':
                fname += '/'
            if show_size:
                outlst.append((fname, fsize))
            else:
                outlst.append(fname)
        if show_space:
            return outlst, used, free
        return outlst

######  This is the documented way to do it and generates no error but also
######  does not create the file. Don't know what is wrong
#    @locked_calling
#    def send_file(self, dest_file, local_src_file=None, src_data=None, overwrite=False):
#        """
#            dest_file: is the file name (absolute or relative to device remote_cwd)
#                       you can use / to separate directories
#            overwrite: when True will skip testing for the presence of the file on the
#                       instrument and proceed to overwrite it without asking confirmation.
#            Use one of local_src_file (local filename) or src_data (data string)
#        """
#        if not overwrite:
#            # split seeks both / and \
#            directory, filename = os.path.split(dest_file)
#            ls = self.remote_ls(directory)
#            if ls:
#                ls = map(lambda s: s.lower(), ls)
#                if filename.lower() in ls:
#                    raise RuntimeError('Destination file already exists. Will not overwrite.')
#        if src_data is local_src_file is None:
#            raise ValueError('You need to specify one of local_src_file or src_data')
#        if src_data and local_src_file:
#            raise ValueError('You need to specify only one of local_src_file or src_data')
#        if local_src_file:
#            with open(local_src_file, 'rb') as f:
#                src_data = f.read()
#        data_str = _encode_block(src_data)
#        # manually add terminiation to prevent warning if data already ends with termination
#        self.write('MMEMory:DOWNload:FNAMe "%s"'%dest_file)
#        self.write('MMEMory:DOWNload:DATA %s\n'%data_str, termination=None)
    @locked_calling
    def arb_send_data(self, data, ch=None):
        """
        data can be a numpy array of float32 (from -1.0 to 1.0) or of int16 (from -32768 to 32767).
              The length can be 8 pts (16 B)  to the memory limit.
              floats are converted to the integers.
        The channel must be in sequence mode.
        """
        # the manual said 0 to 0x3ff (14 bits) but this instrument is 16 bit resolution and needs
        #  signed 16 bits
        if ch is not None:
            self.current_ch.set(ch)
        ch=self.current_ch.getcache()
        mode = self.mode.get()
        if mode.lower() != 'sequence':
            raise ValueError(self.perror('The channel mode must be in sequence mode for method to work.'))
        if data.dtype in [np.float32, np.float64]:
            data = data*0x7fff
            data = data.astype(np.int16)
        elif data.dtype in [np.int16, np.uint16]:
            pass
        else:
            raise ValueError('Unknown data type')
        max_size = 2**15 # valid for sequence
        #max_size = 2**13 # for ARB without sequence
        N = len(data)
        i = 0
        pre = b'SOURce{ch}:DATA:DAC16 VOLATILE'
        if N > max_size:
            while N-i > max_size:
                data_str = _encode_block(data[i:i+max_size])
                self.write(pre + b',CON,{data}\n'.format(ch=ch, data=data_str), termination=None)
                self._wait_after_write()
                #pre = b''
                i += max_size
        data_str = _encode_block(data[i:])
        self.write(pre + b',END,{data}\n'.format(ch=ch, data=data_str), termination=None)
        self._wait_after_write()
