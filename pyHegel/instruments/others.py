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
import random
import time
from scipy.optimize import brentq as brentq_rootsolver
import codecs

from ..instruments_base import BaseInstrument, visaInstrument, visaInstrumentAsync,\
                            BaseDevice, scpiDevice, MemoryDevice, Dict_SubDevice, ReadvalDev,\
                            ChoiceBase, ChoiceMultiple, ChoiceMultipleDep, ChoiceSimpleMap,\
                            ChoiceStrings, ChoiceIndex,\
                            make_choice_list, _fromstr_helper, _tostr_helper,\
                            decode_float64, visa_wrap, locked_calling,\
                            Lock_Extra, Lock_Instruments, _sleep_signal_context_manager, wait,\
                            release_lock_context, mainStatusLine, quoted_string, Choice_bool_OnOff,\
                            resource_info, ProxyMethod
from ..types import dict_improved
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

from .logical import FunctionDevice, ScalingDevice

# for pfeiffer
import threading
import weakref

# for agilent pump
import operator

# for BIAS-DAC
import struct

# for micro_lambda_wireless
import socket

#######################################################
##    Yokogawa source
#######################################################

register_usb_name('Yokogawa Electric Corporation', 0x0B21)

# To implement hardware sweeping:
#  can use program with interval and slope.
#   interval needs to be >= slope
#  They both are time with resolution of .1 s
#  can have 10000 program steps
#  cannot readback ramping state or program
#  can use pause/cont  or hold/hold to pause and restart
#    pause/cont produce errors
#  the program steps consists of level,range,function
#  can define program like:
#     :prog:memory "0,1,V\n.5,1,V"
#  When the range changes (between prog steps or between current and first step),
#   the slope is not working.
#  Count is incremented will the program is running. Goes back to 1 at the end
#  Can see level/steps/prog completion with :status:event? bits 5,6,7 (32,64,128)
#      level is set when slope is done, steps when interval is done.
#  the :status:event bit 8 (256) is toggled by changing the program (prog:edit:start, prog:edit:end, or frontpanel)
#   but not by prog:memory
# can't run a program if the output is disabled
# OPC does not work for programs

@register_instrument('YOKOGAWA', 'GS210', usb_vendor_product=[0x0B21, 0x0039])
#@register_instrument('YOKOGAWA', 'GS210', '1.05')
#@register_instrument('YOKOGAWA', 'GS210', '1.02')
class yokogawa_gs200(visaInstrument):
    # TODO: implement multipliers, units. The multiplier
    #      should be the same for all instruments, and be stripped
    #      before writing and going to the cache (in BaseDevice)
    #      This is probably not needed. Just use 1e3
    # case insensitive
    multipliers = ['YO', 'ZE', 'EX', 'PE', 'T', 'G', 'MA', 'K', 'M', 'U', 'N', 'P',
                   'F', 'A', 'Z', 'Y']
    multvals    = [1e24, 1e21, 1e18, 1e15, 1e12, 1e9, 1e6, 1e3, 1e-3, 1e-6, 1e-9, 1e-12,
                   1e-15, 1e-18, 1e-21, 1e-24]
    def init(self, full=False):
        # clear event register, extended event register and error queue
        self.clear()
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('function', 'range', 'level', 'output_en', options)
    def _create_devs(self):
        #self.level_2 = wrapDevice(self.levelsetdev, self.levelgetdev, self.levelcheck)
        self.function = scpiDevice(':source:function', choices=ChoiceStrings('VOLT', 'CURRent')) # use 'voltage' or 'current'
        # voltage or current means to add V or A in the string (possibly with multiplier)
        self.range = scpiDevice(':source:range', str_type=float, setget=True) # can be a voltage, current, MAX, MIN, UP or DOWN
        #self.level = scpiDevice(':source:level') # can be a voltage, current, MAX, MIN
        self.voltlim = scpiDevice(':source:protection:voltage', str_type=float, setget=True) #voltage, MIN or MAX
        self.currentlim = scpiDevice(':source:protection:current', str_type=float, setget=True) #current, MIN or MAX
        self.output_en = scpiDevice('OUTPut', str_type=bool)
        self._devwrap('level', setget=True)
        self.alias = self.level
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
    def _level_checkdev(self, val):
        rnge = 1.2*self.range.getcache()
        if self.function.getcache()=='CURR' and rnge>.2:
            rnge = .2
        if abs(val) > rnge:
            raise ValueError, self.perror('level is invalid')
    def _level_getdev(self):
        return float(self.ask(':source:level?'))
    def _level_setdev(self, val):
        # used %.6e instead of repr
        # repr sometimes sends 0.010999999999999999
        # which the yokogawa understands as 0.010 instead of 0.011
        self.write(':source:level %.6e'%val)


#######################################################
##    Colby Instruments Programmable delay line PDL-100A-20NS
#######################################################

#@register_instrument('Colby Instruments', 'PDL-100A-20.00NS', 'V1.70')
@register_instrument('Colby Instruments', 'PDL-100A-20.00NS')
class colby_pdl_100a(visaInstrument):
    """
    Colby Instruments delay box: PDL-100A-20NS
    Useful devices:
        delay_ps (default alias): enter delay value in ps
    It can take up to 1.5s to change the delay.
    Make sure visa timeout is not made too short (initialized to 3s).

    Useful methods:
        get_error
        reset
    """
    _errors_dict = {0: 'No Error', 1: 'Invalid Command', 2: 'Invalid Argument',
                    3: 'Unit did not pass calibration',
                    4: 'Delay setting requested beyond range of device',
                    5: 'Delay not set', 99: 'Buffer overflow'}
    def init(self, full=False):
        # This clears the error state, and status/event flags
        self.clear()
        if full:
            self.set_timeout = 3
            #self.visa.term_chars='\n'
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        #return self._conf_helper('delay_ps', 'mode', 'rate', 'accel', options)
        return self._conf_helper('delay_ps', 'mode', options)
    def _delay_ps_setdev(self, val):
        # TODO could use async instead of using *OPC and visa timeout
        # OPC is to wait for completion, could require up to 1.5s
        self.ask('DEL %f PS;*OPC?'%val)
    def reset(self):
        """
        Returns to power on state (goes to 0 ps)
        """
        self.write('*rst')
        self.delay_ps.setcache(0.)
    def caltest(self, test=False):
        """
        Does either a calibration (only trombone) or an internal self-test
        (longer: trombone and relays)
        The state of the delay after calibration (because of relays) is not
        known.
        """
        if test:
            self.ask('*tst?')
        else:
            self.ask('*cal?')
        self.delay_ps.setcache(0.)
    def cal(self):
        self.write('*rst')
    def _delay_ps_getdev(self):
        return float(self.ask('DEL?'))*1e12
    def _create_devs(self):
        # other commands REL? relay query which returns bit flag, total delay ns
        #                REL n ON or REL n OFF to turn relay n (1..5) on or off.
        self.mode = scpiDevice('MODE', choices=ChoiceStrings('SER', 'PAR', '312.5PS', '625PS'))
        #self.rate = scpiDevice('RATE', str_type=int, min=100, max=550)
        #self.accel = scpiDevice('XDD', str_type=int, min=500, max=2000)
        self._devwrap('delay_ps', min=0, max=20e3, setget=True)
        self.alias = self.delay_ps
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
    def get_error(self):
        val = int(self.ask('ERR?'))
        err_str = self._errors_dict[val]
        return val, err_str


#######################################################
##    BNC 845 microwave/RF generator
#######################################################

register_usb_name('Berkeley Nucleonics Corporation', 0x03EB)

#@register_instrument('Berkeley Nucleonics Corporation', 'MODEL 845', '0.4.35', usb_vendor_product=[0x03EB, 0xAFFF])
@register_instrument('Berkeley Nucleonics Corporation', 'MODEL 845', usb_vendor_product=[0x03EB, 0xAFFF])
class BNC_rf_845(visaInstrument):
    """
    This controls a BNC 845 signal generetor
    Most useful devices:
        ampl_dbm
        rf_en
        freq_cw
    The alc devices refer to automatic level (amplitude) control.
    Available methods:
        phase_sync

    According to specs, it takes less than 0.1 ms for settling after
    a frequency change.
    """
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        # TODO Get the proper config
        return self._conf_helper('oscillator_source', 'oscillator_ext_freq_MHz', 'oscillator_locked',
                                 'oscillator_out_en', 'oscillator_out_freq',
                                 'rf_en', 'ampl_dbm', 'amp_flatness_corr_en', 'output_blanking_en',
                                 'ampl_mode', 'ampl_start', 'ampl_stop',
                                 'alc_en', 'alc_low_amp_noise_en', 'alc_hold_en',
                                 'attenuation_db', 'attenuation_auto_en', 'amp_flatness_corr_en',
                                 'freq_mode', 'freq_cw', 'freq_start', 'freq_stop',
                                 'sweep_nbpoints', 'sweep_type', 'sweep_dwell_s', 'sweep_delay_s', 'sweep_delay_auto_en',
                                 'sweep_direction',
                                 'lowfout_freq', 'lowfout_amp_V', 'lowfout_shape', 'lowfout_source', 'lowfout_en',
                                 'phase', 'mod_am_en', 'mod_fm_en', 'mod_phase_en', 'mod_pulse_en', options)
    def _create_devs(self):
        self.installed_options = scpiDevice(getstr='*OPT?')
        self.oscillator_source = scpiDevice(':ROSCillator:SOURce', choices=ChoiceStrings('INTernal', 'EXTernal')) # 'SLAVe' not useful for us
        self.oscillator_ext_freq_MHz = scpiDevice(':ROSCillator:EXTernal:FREQuency', str_type=float, min=1, max=250)
        self.oscillator_locked = scpiDevice(getstr=':ROSCillator:LOCKed?', str_type=bool)
        self.oscillator_out_en = scpiDevice(':ROSCillator:OUTPut:STATe', str_type=bool)
        self.oscillator_out_freq = scpiDevice(':ROSCillator:OUTPut:FREQuency', str_type=float, choices=[10e6, 100e6])
        self.rf_en = scpiDevice(':OUTPut', str_type=bool)
        #self.unit_power('UNIT:POWer', choices=ChoiceStrings('W', 'V', 'DBM', 'DB')) # only affects display
        #self.unit_freq('UNIT:FREQuency', choices=ChoiceStrings('HZ', 'MHZ', 'GHZ')) # only affects display
        self.ampl_dbm = scpiDevice(':POWer', str_type=float, setget=True, min=-105, max=20)
        # unit:volt:type affects volt scale like power:alc:search:ref:level, which are not user changeable
        self.ampl_mode = scpiDevice(':POWer:MODE', choices=ChoiceStrings('FIXed', 'LIST', 'SWEep'))
        self.ampl_start = scpiDevice(':POWer:STARt', str_type=float, setget=True)
        self.ampl_stop = scpiDevice(':POWer:STOP', str_type=float, setget=True)
        self.ampl_step = scpiDevice(getstr=':POWer:STEP?', str_type=float)
        self.alc_en = scpiDevice(':POWer:ALC', str_type=bool)
        self.alc_low_amp_noise_en = scpiDevice(':POWer:ALC:LOWN', str_type=bool, doc='When enabled provides up to 0.001 dB output resolution. Works similarly to hold')
        self.alc_hold_en = scpiDevice(':POWer:ALC:HOLD', str_type=bool, doc='Open loops ALC control')
        att_list = list(decode_float64(self.ask('POWer:ATTenuation:LIST?')))
        self.attenuation_db = scpiDevice(':POWer:ATTenuation', str_type=float, choices=att_list)
        self.attenuation_auto_en = scpiDevice(':POWer:ATTenuation:AUTO', str_type=bool)
        self.amp_flatness_corr_en = scpiDevice(':CORRection:FLATness', str_type=bool)
        self.output_blanking_en = scpiDevice(':OUTPut:BLANKing:STATe', str_type=bool, doc='disable RF output when changing frequency')
        self.phase = scpiDevice(':PHASe', str_type=float, min=0, max=2*np.pi, doc='Adjust phase arounf ref. In rad.')
        self.freq_mode = scpiDevice(':FREQuency:MODE', choices=ChoiceStrings('CW', 'FIXed', 'LIST', 'SWEep', 'CHIRp'), doc='CW and FIXed are the same.')
        minfreq=9e3
        maxfreq=20.5e9
        self.freq_cw = scpiDevice(':FREQuency', str_type=float, min=minfreq, max=maxfreq)
        self.freq_start = scpiDevice('FREQuency:STARt', str_type=float, min=minfreq, max=maxfreq)
        self.freq_stop = scpiDevice('FREQuency:STOP', str_type=float, min=minfreq, max=maxfreq)
        self.freq_step = scpiDevice(getstr='FREQuency:STEP?', str_type=float)
        #self.freq_steplog = scpiDevice(getstr='FREQuency:STEP:LOGarithmic?', str_type=float) # This is in the manual but does not seem to work
        self.sweep_nbpoints = scpiDevice('SWEep:POINts', str_type=int, min=2, max=65535)
        self.sweep_progress = scpiDevice(getstr='SWEep:PROGress?', str_type=float) # manual says proggress but is wrong
        self.sweep_type = scpiDevice('SWEep:SPACing', choices=ChoiceStrings('LINear', 'LOGarithmic'))
        self.sweep_dwell_s = scpiDevice('SWEep:DWELl', str_type=float)
        self.sweep_delay_s = scpiDevice('SWEep:DELay', str_type=float)
        self.sweep_delay_auto_en = scpiDevice('SWEep:DELay:AUTO', str_type=bool)
        self.sweep_direction = scpiDevice('SWEep:DIRection', choices=ChoiceStrings('UP', 'DOWN', 'RANDom'))
        self.lowfout_freq = scpiDevice(':LFOutput:FREQuency', str_type=float, min=10, max=5e6)
        self.lowfout_amp_V = scpiDevice(':LFOutput:AMPLitude', str_type=float, min=0, max=2.5, doc=
            """Vpp, only for LFGenerator and sine or triangle into 50 Ohm
               (not accurate, and with an offset).
               For Square amp=5V CMOS always.""")
        self.lowfout_shape = scpiDevice(':LFOutput:SHAPe', choices=ChoiceStrings('SINE', 'TRIangle', 'SQUare'))
        self.lowfout_source = scpiDevice(':LFOutput:SOURce', choices=ChoiceStrings('LFGenerator', 'PULM', 'TRIGger'))
        self.lowfout_en = scpiDevice(':LFOutput:STATe', str_type=bool)
        self.mod_am_en = scpiDevice(':AM:STATe', str_type=bool)
        self.mod_fm_en = scpiDevice(':FM:STATe', str_type=bool)
        self.mod_phase_en = scpiDevice(':PM:STATe', str_type=bool)
        self.mod_pulse_en = scpiDevice(':PULM:STATe', str_type=bool)
        self.alias = self.freq_cw
        # This needs to be last to complete creation
        super(BNC_rf_845, self)._create_devs()
    def phase_sync(self):
        """
        Sets the current output phase as a zero reference.
        """
        self.write('PHASe:REFerence')


#######################################################
##    Scientific Magnetics Magnet Controller SMC120-10ECS
#######################################################

_parse_magnet_glitches = 0

def _parse_magnet_return(s, conv):
    """
    s is the input string
    conv is a list of tuples (start symbol, name, type)
    """
    global _parse_magnet_glitches
    names = []
    vals = []
    for symb, name, t in conv[::-1]:
        if symb=='last':
            vals.append(_fromstr_helper(s[-1], t))
            s = s[:-1]
        else:
            sp = s.rsplit(symb, 1)
            # I have notice that sometimes the instrument does not send the first
            # letter of the reply (at least for status update K, it sometimes (1 out of 20000),
            #  skips sending R). So capture that and handle it.
            if len(sp) == 1:
                vals.append(_fromstr_helper(sp[0], t))
                s = ""
                _parse_magnet_glitches += 1
            else:
                vals.append(_fromstr_helper(sp[1], t))
                s = sp[0]
        names.append(name)
    if s != "":
        raise RuntimeError('There is some leftovers (%s) in the string'%s)
    return dict_improved(zip(names[::-1], vals[::-1]))

def _repeat_getdev_dec(func):
    def _repeat_getdev_wrap(self, *arg, **kwarg):
        i = 0
        while True:
            try:
                ret = func(self, *arg, **kwarg)
                break
            except Exception as e:
                if isinstance(e, KeyboardInterrupt):
                    raise
                if i == 2:
                    raise
            i += 1
        _repeat_getdev_wrap._bad_count += i
        return ret
    _repeat_getdev_wrap._bad_count = 0
    return _repeat_getdev_wrap


@register_instrument('Scientific Magnetics', 'SMC120-10', '5.67')
class MagnetController_SMC(visaInstrument):
    """
    This controls a Scientific Magnetics Magnet Controller SMC120-10ECS
    Usefull device:
        ramp_T
        ramp_wait_after
        field
        rawIV
    You only control the lower setpoint. The upper setpoint is to control
    maximum value.
    Important, either leave the instrument in Tesla or at least
    do not change the calibration (it is read during init.)
    This only handles serial address connections (like ASRL1)
    Important: To changes values like display Unit, the instrument needs to be
    in remote (press remote button).
    To change the polarity(reverse option of operating_parameters),
    the current needs to be near zero to work (<0.09 A). It fails silently
    when above (reread operating_parameters to confirm the change).
    """
    def __init__(self, address):
        cnsts = visa_wrap.constants
        super(MagnetController_SMC, self).__init__(address, parity=cnsts.Parity.none, flow_control=cnsts.VI_ASRL_FLOW_XON_XOFF,
                                            baud_rate=9600, data_bits=8, stop_bits=cnsts.StopBits.two)
    def init(self, full=False):
        super(MagnetController_SMC, self).init(full=full)
        self._magnet_cal_T_per_A = self.operating_parameters.get()['calibTpA']
        maxT = self._magnet_max_T = self.setpoints.get(Tunit=True).upper
        self._magnet_max_I = self.setpoints.get(Tunit=False).upper
        self.ramp_T.min = -maxT
        self.ramp_T.max = maxT
    def idn(self):
        return 'Scientific Magnetics,SMC120-10,000000,5.67'
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('field', 'current_status', 'setpoints', 'status', 'operating_parameters', 'ramp_wait_after', options)
    @_repeat_getdev_dec
    def _field_internal(self):
        s=self.ask('N')
        if s[0] == 'F':
            d = _parse_magnet_return(s, [('F', 'field', float), ('V', 'volt', float),
                                         ('R', 'target', ChoiceIndex(['zero', 'lower','upper'])),
                                          ('last', 'ramptype', ChoiceSimpleMap(dict(A='current_limit', V='volt_limit')))])
            field = d.field
        else:
            d = _parse_magnet_return(s, [('I', 'current', float), ('V', 'volt', float),
                                     ('R', 'target', ChoiceIndex(['zero', 'lower','upper'])),
                                     ('last', 'ramptype', ChoiceSimpleMap(dict(A='current_limit', V='volt_limit')))])
            field = d.current * self._magnet_cal_T_per_A
        return field, d
    def _field_getdev(self):
        field, d = self._field_internal()
        return field
    @_repeat_getdev_dec
    def _current_status_getdev(self):
        # Note that G,N returns the live output, while only J returns the persistent current (this is different than
        #  what the manual says.)
        s=self.ask('G')
        d = _parse_magnet_return(s, [('I', 'current', float), ('V', 'volt', float),
                                     ('R', 'target', ChoiceIndex(['zero', 'lower','upper'])),
                                     ('last', 'ramptype', ChoiceSimpleMap(dict(A='current_limit', V='volt_limit')))])
        return d
    def _rawIV_getdev(self):
        d = self._current_status_getdev()
        return d.current, d.volt
    def _operating_parameters_setdev(self, value):
        """
        When setting, you need a dictionnary.
        You can only set the following keys, to the corresponding values:
            rate:  sign of value is lost. in A/s.
            Tunit: True or False
            reverse: True or False
        But reverse will only work if field and voltage are 0.
        """
        for k,v in value.iteritems():
            if k == 'rate':
                self.write('A%.5f'%abs(v))
            elif k == 'Tunit':
                 self.write('T%i'%v)
            elif k == 'reverse':
                 self.write('D%i'%v)
            else:
                raise NotImplementedError('Changing %s is not implememented'%k)
    @_repeat_getdev_dec
    def _operating_parameters_getdev(self):
        s = self.ask('O')
        return _parse_magnet_return(s, [('A', 'rate', float), ('D', 'reverse', bool),
                                        ('T', 'Tunit', bool), ('B', 'lockout', bool),
                                        ('W', 'Htr_current', float), ('C', 'calibTpA', float)])

    def _setpoints_setdev(self, values):
        """
        When setting, use a dictionnary with keys of 'lower' and/or 'voltLim'
        and with value the setpoint/limit you want (the sign of the value is lost).
        Also use 'Tunit' key with value False/True.
        For lower/upper you should also always set Tunit (if not it will use the current unit of the instrument.)
        For set, any unspecified value is unchanged.
        upper can only be set if password is given with the value 'IReallyKnowWhatIAmDoing'
        """
        password = values.pop('password', '!NoPasswordUsed!')
        Tunit = values.pop('Tunit', None)
        if Tunit is not None:
            self.write('T%i'%Tunit)
        for k,v in values.iteritems():
            v = abs(v)
            if k == 'lower':
                self.write('L%f'%v)
            elif k == 'voltLim':
                self.write('Y%f'%v)
            elif k == 'upper':
                if password == '!NoPasswordUsed!':
                    print 'Password not given, changing upper skipped.'
                    continue
                if password != 'IReallyKnowWhatIAmDoing':
                    raise ValueError(self.setpoints.perror('Invalid password provided, which is required to change upper.'))
                self.write('U%f'%v)
            else:
                raise NotImplementedError('Changing %s is not implememented'%k)
    @_repeat_getdev_dec
    def _setpoints_getdev(self, Tunit='default'):
        s = self.ask('S')
        d = _parse_magnet_return(s, [ ('T', 'Tunit', bool), ('U', 'upper', float), ('L', 'lower', float),
                                     ('Y', 'voltLim', float)])
        if Tunit != 'default' and Tunit != d['Tunit']:
            if Tunit:
                f = self._magnet_cal_T_per_A
            else:
                f = 1./self._magnet_cal_T_per_A
            d['upper'] *= f
            d['lower'] *= f
            d['Tunit'] = Tunit
        return d
    def persistent_force(self):
        """
        This is very dangerous. It is currently disabled.
        """
        #self.write('H2')
        pass
    def persistent_forget(self):
        """
        This is dangerous. It is currently disabled.
        """
        #self.write('H9')
        pass
    def _status_setdev(self, value):
        for k,v in value.iteritems():
            if k == 'target':
                ch=ChoiceIndex(['zero', 'lower','upper'])
                self.write('R%s'%ch.tostr(v))
            elif k == 'pause':
                self.write('P%i'%v)
            elif k == 'persistent':
                # note that persistent could be True(1), False(0), see also persistent_force and forget
                self.write('H%i'%v)
            else:
                raise NotImplementedError('Changing %s is not implememented'%k)

    @_repeat_getdev_dec
    def _status_getdev(self):
        """
        When setting, you need a dictionnary.
        You can only set the following keys, to the corresponding values:
            target: 'zero', 'lower' or 'upper'
            pause: True or False
            persistent: True or False
        """
        s = self.ask('K')
        d= _parse_magnet_return(s, [('R', 'target', ChoiceIndex(['zero', 'lower','upper'])),
                                    ('M', 'rampstate', ChoiceIndex(['ramping', 'unknown', 'at_target'])),
                                    ('P', 'pause', bool), ('X', 'trip', ChoiceIndex(['off', 'on_inactive', 'on_active', 'off_active', 'on_auto_inactive', 'on_auto_active'])),
                                    ('H', 'persistent', bool), ('Z', 'foo', float),
                                    ('E', 'error', int), ('Q', 'trip_point', float)])
        # Note that the value of M is not properly described in manual. At least it does not match
        # what I observe (0=ramping, 2=at target, 1 is not seen)
        # at target is shown when control has reached the value. The actual outputs gets there a little bit later
        d.pop('foo')
        return d

    def is_ramping(self, param_dict=None):
        """ Returns True when the magnet is ramping the field. Can be used for the sequencer. """
        sts = self.status.get()
        return sts.rampstate in ['ramping'] and sts.error == 0
    def is_stable(self, param_dict=None):
        """ Returns True when the magnet is not ramping. Can be used for the sequencer. """
        sts = self.status.get()
        return sts.rampstate in ['at_target'] and sts.error == 0

    def get_error(self):
        return 'This instrument does not return the communication error state. Use status error value instead.'

    def _ramping_helper(self, stay_states, end_states=None, extra_wait=None):
        to = time.time()
        if self._last_state == 'ramp':
            # Reaching here, the cache should be ok.
            factor = -1. if self.operating_parameters.getcache().reverse else 1.
            prog_base = 'Magnet Ramping {field:.3f}/%.3f T'%(self.setpoints.getcache().lower*factor)
        else: # zeroing field
            prog_base = 'Magnet Ramping {field:.3f}/0 T'
        if isinstance(stay_states, basestring):
            stay_states = [stay_states]
        with release_lock_context(self):
            with mainStatusLine.new(priority=10, timed=True) as progress:
                check = lambda x: x.rampstate in stay_states and x.error == 0
                while check(self.status.get()):
                    # The instrument is slow. Trying to read too fast is counter productive
                    wait(.5)
                    progress(prog_base.format(field=self.field.get(), time=time.time()-to))
            if self.status.getcache().error != 0:
                error_code = self.status.getcache().error
                errors = []
                if error_code >= 10:
                    errors.append({1:'Changing polarity with I/V != 0.',
                                    2:'Polarity did not switch correctly',
                                    3:'Polarity switch in invalid state'}[error_code//10])
                if error_code%10 != 0:
                    errors.append({1:'Quenched!!',
                                    2:'External trip',
                                    3:'Quenched!! and External trip',
                                    4:'Brick trip',
                                    5:'Heatsink overtemperature trip',
                                    6:'Slave trip',
                                    7:'Heatsink overvoltage trip'}[error_code%10])
                # Polarity switch (I/V) != 0. error is only reset once a proper polarity change is performed
                # i.e. when changing polarity (operating_parameters reverse option)  with I=V=0.
                raise RuntimeError(self.perror('Magnet is in error: %s'%', '.join(errors)))
            if extra_wait:
                wait(extra_wait, progress_base='Magnet wait')
        if end_states is not None:
            if isinstance(end_states, basestring):
                end_states = [end_states]
            if self.status.get().rampstate not in end_states:
                raise RuntimeError(self.perror('The magnet state did not change to %s as expected'%end_states))

    def _do_ramp(self, field_target, wait_time, no_wait_end=False):
        status = self.status.get()
        # chaning pause or target status takes 0.6 each and it is cumulative.
        # Therefore check if the change is needed before doing it.
        if field_target == 0:
            if status.target != 'zero':
                self.status.set(target='zero')
            if status.pause:
                self.status.set(pause=False)
            self._last_state = 'zero'
        else:
            #self.status.set(pause=True)
            self.setpoints.set(lower=field_target, Tunit=True)
            if status.target != 'lower':
                # This can take 0.6s so only do it when necessary.
                self.status.set(target='lower')
            if status.pause:
                self.status.set(pause=False)
            self._last_state = 'ramp'
        if no_wait_end:
            wait(1) # give a chance for the state to change.
            return
        # unknow state seems to be a possible transient between ramping and at_target.
        # I only see it once (when continuously reading status) immediately followed by 'at_target'
        # I don't always see it.
        # Since the end_states check is done after a second reading of status (and a possible wait)
        # we should never have to check for it but to be safe I add it anyway (my observations time was not infinite)
        self._ramping_helper('ramping', ['at_target', 'unknown'], wait_time)
        # With a ramping rate of 0.00585 A/s  = 0.031 T/min
        # when going to zero, at_target shows up at about 3 mT and it takes about another 5 s to go to 0.
        # going to non-zero field (+0.05), at_target shows up at about 20 mT from target, and it takes another 15-20 s to become stable (0.0505 T)

    def _ramp_T_checkdev(self, val, wait=None, quiet=True, no_wait_end=False):
        BaseDevice._checkdev(self.ramp_T, val)

    def _ramp_T_setdev(self, val, wait=None, quiet=True, no_wait_end=False):
        """ Goes to the requested setpoint and then waits until it is reached.
            After the instrument says we have reached the setpoint, we wait for the
            duration set by ramp_wait_after (in s).
            wait can be used to set a wait time (in s) after the ramp. It overrides ramp_wait_after.
            no_wait_end when True, will skip waiting for the ramp to finish and return immediately after
                      starting the ramp. Useful for record sequence. This will not work when changing sign.
            When the field polarity of the target is different than the current one, it will first go to  0T,
                     then wait 20s before going to the target.
            When using get, returns the magnet field in T.
        """
        def print_if(s):
            if not quiet:
                print s
        if wait is None:
            wait = self.ramp_wait_after.getcache()
        reverse_en = self.operating_parameters.get().reverse
        neg_val = True if val<0 else False
        if val != 0 and reverse_en != neg_val:
            # We need to switch polarity
            print_if('Ramping to zero for polarity change ...')
            # When switching polarity, need to wait. 5s is minium I observed as necessary.
            #  To be safe make it 20.
            self._do_ramp(0, 20.)
            self.operating_parameters.set(reverse = not reverse_en)
        print_if('Ramping...')
        self._do_ramp(val, wait, no_wait_end)

    def _ramp_T_getdev(self, wait=None, quiet=True, no_wait_end=False):
        return self.field.get()

    def _create_devs(self):
        self.ramp_wait_after = MemoryDevice(20., min=0.)
        self._devwrap('field', doc='units are Tesla')
        self._devwrap('operating_parameters', setget=True, allow_kw_as_dict=True,
                      choices=ChoiceMultiple(['rate', 'reverse', 'Tunit'], [float, bool, bool], allow_missing_keys=True))
        self._devwrap('setpoints', setget=True, allow_kw_as_dict=True,
                      choices=ChoiceMultiple(['lower', 'upper', 'voltLim', 'Tunit', 'password'], [float, float, float, bool, str], allow_missing_keys=True))
        self._devwrap('status', setget=True, allow_kw_as_dict=True,
                      choices=ChoiceMultiple(['pause', 'target', 'persistent'], [bool, float, bool], allow_missing_keys=True))
        self._devwrap('current_status')
        self._devwrap('rawIV')
        self.rawIV._format['multi'] = ['current', 'volt']
        self._devwrap('ramp_T')
        self.alias = self.field
        # This needs to be last to complete creation
        super(MagnetController_SMC, self)._create_devs()


#######################################################
##    Pfeiffer DCU400 TC400
#######################################################

class pfeiffer_turbo_loop(threading.Thread):
    def __init__(self, master):
        super(pfeiffer_turbo_loop, self).__init__()
        self.master = master
        self._stop = False
    def cancel(self):
        self._stop = True
    def run(self):
        # empty buffer
        self.master.visa.flush(visa_wrap.constants.VI_IO_IN_BUF_DISCARD)
        # trow away first partial data
        self.master.read()
        while True:
            if self._stop:
                return
            string = self.master.read()
            res = self.master.parse(string)
            if res is None:
                continue
            param, data = res
            #self.master._alldata_lock.acquire()
            self.master._alldata[param] = data, time.time()
            #self.master._alldata_lock.release()
    def wait(self, timeout=None):
        # we use a the context manager because join uses sleep.
        with _sleep_signal_context_manager():
            self.join(timeout)
        return not self.is_alive()

class pfeiffer_dev(BaseDevice):
    def __init__(self, param, type, enable_set=False, *args, **kwargs):
        super(pfeiffer_dev, self).__init__(*args, **kwargs)
        self._param = param
        self._param_type = type
        self._getdev_p = 'foo'
        if enable_set:
            self._setdev_p = 'foo'
    def _getdev(self):
        if self.instr._monitor_mode:
            return self.instr.get_param(self._param, self._param_type)
        else:
            request = self.instr._create_req(self._param)
            self.instr.write(request)
            return self.instr.get_param(self._param, self._param_type)
    def _setdev(self, val):
        if self.instr._monitor_mode:
            raise NotImplementedError(self.perror('The set for this device is not available'))
        request = self.instr._create_req(self._param, val, self._param_type)
        self.instr.write(request)
        ret = self.instr.get_param(self._param, self._param_type)
        self.setcache(ret)

@register_instrument('Pfeiffer', 'TC400')
class pfeiffer_turbo_log(visaInstrument):
    """
        This reads the information from a Pfeiffer pump
        using a serial to rs-485 converter.
        The pump is connected to a DCU unit that requests and reads
        all the values. We just capture all of them (when monitor_mode == True,
        the default).
    """
    # we had trouble with the Visa serial connection that kept frezzing.
    # So we use the serial module instead.
    def __init__(self, address, monitor_mode=True):
        cnsts = visa_wrap.constants
        super(pfeiffer_turbo_log, self).__init__(address, timeout=5, parity=cnsts.Parity.none, baud_rate=9600, data_bits=8,
             stop_bits=cnsts.StopBits.one, write_termination='\r', read_termination='\r', end_input=cnsts.SerialTermination.termination_char)
        self._monitor_mode = monitor_mode
        if monitor_mode:
            # Locking makes the get code go slow so don't do it
            self._lock_extra = Lock_Extra()
            self._lock_instrument = Lock_Extra()
            self._alldata = dict()
            self._alldata_lock = threading.Lock()
            s = weakref.proxy(self)
            self._helper_thread = pfeiffer_turbo_loop(s)
            self._helper_thread.start()
    def __del__(self):
        self._helper_thread.cancel()
        self._helper_thread.wait(.1)
        super(pfeiffer_turbo_log, self).__del__()
    def idn(self):
        return 'Pfeiffer,TC400,no_serial,no_firmare'
    def parse(self, string):
        chksum = string[-3:]
        try:
            chksum = int(chksum)
        except ValueError:
            print 'Invalid Checksum value', string
            return None
        if np.sum(bytearray(string[:-3]))%256 != chksum:
            print 'Invalid Checksum', string
            return None
        addr = string[:3]
        if addr != '001':
            print 'Invalid address', string
            return None
        action = string[3:5]
        if action != '10':
            if action != '00':
                print 'Invalid action', string
            return None
        # action == '00' is for a question
        param = int(string[5:8])
        len = int(string[8:10])
        data = string[10:10+len]
        return param, data
    def _create_req(self, param, data=None, type='string'):
        """ if data is None, creates a request for a value.
            possible types:
                boolean
                string
                integer
                real
                expo
                vector
                boolean_new
                short_int
                tms_old
                expo_new
                string16
                string8
        """
        addr = '001'
        action = '00'
        param_s = '%03i'%param
        if data is None:
            data_str = '=?'
        else:
            data_str = ''
            def check(data, min_val, max_val):
                if data>max_val or data<min_val:
                    raise ValueError(self.perror('Value(%s) outside of valid range(%s,%s)'%(data, min_val, max_val)))
                return data
            if type == 'boolean':
                s = '1' if data else '0'
                s = s*6
            elif type == 'boolean_new':
                s = '1' if data else '0'
            elif type in ['string', 'string16', 'string8']:
                l = dict(string=6, string16=16, string8=8)[type]
                s = '%-*s'%(l, data[:l])
            elif type == 'integer':
                s = '%06i'%check(data, 0, 999999)
            elif type == 'short_int':
                s = '%03i'%check(data,0,999)
            elif type == 'real':
                s = '%06i'%check(data*100, 0, 999999)
            elif type == 'expo_new':
                fexp = int(np.floor(np.log10(check(data, 0, 9.9994e79))))
                fman = int(np.round(data/10.**(fexp-3)))
                if fman>9999:
                    fman = fman//10
                    fexp += 1
                check(fexp, -20, 79)
                check(fman, 0, 9999)
                s = '%04i%02i'%(fman, fexp+20)
            elif type in ['expo', 'tms_old', 'vector']:
                raise NotImplementedError(self.perror('tms_old and vector are not implemented yet'))
            else:
                raise ValueError(self.perror('Invalid type'))
            data_str = s
        data_len = '%02i'%len(data_str)
        req = addr + action + param_s + data_len + data_str
        chksum = np.sum(bytearray(req))%256
        req += '%03i'%chksum
        return req
    def get_param(self, param, type='string'):
        """ possible type:
                boolean
                string
                integer
                real
                expo
                vector
                boolean_new
                short_int
                tms_old
                expo_new
                string16
                string8
        """
        if self._monitor_mode:
            self._alldata_lock.acquire()
            val = self._alldata.get(param)
            self._alldata_lock.release()
            if val is None:
                print 'Data not available yet'
                return None
            val, last = val
        else:
            val_str = self.read()
            param_read, val = self.parse(val_str)
            if param_read != param:
                raise RuntimeError(self.perror('Received unexpected param (%i!=%i)'%(param_read, param)))
        if type in ['boolean',  'boolean_new']:
            return bool(int(val))
        elif type in ['integer', 'short_int']: #integer is 6 digits, short is 3
            return int(val)
        elif type == 'real':
            return int(val)/100.
        elif type == 'expo':
            return float(val)
        elif type == 'expo_new':
            return val[:4]/1000. * 10**(int(val[4:])-20)
        elif type in ['string', 'string16', 'string8']: # string is 6 long
            return val
        elif type in ['tms_old', 'vector']:
            raise NotImplementedError(self.perror('tms_old and vector are not implemented yet'))
        else:
            raise ValueError(self.perror('Invalid type'))
        return val
    def _create_devs(self):
        self.temp_power_stage = pfeiffer_dev(324, 'integer')
        self.temp_elec = pfeiffer_dev(326, 'integer')
        self.temp_pump_bottom = pfeiffer_dev(330, 'integer')
        self.temp_bearing = pfeiffer_dev(342, 'integer')
        self.temp_motor = pfeiffer_dev(346, 'integer')
        self.actual_speed = pfeiffer_dev(309, 'integer')
        self.drive_current = pfeiffer_dev(310, 'real')
        self.drive_power = pfeiffer_dev(316, 'integer')
        #self._devwrap('temp_pump_bottom')
        #self.alias = self.field
        # This needs to be last to complete creation
        super(pfeiffer_turbo_log, self)._create_devs()

#######################################################
##    Pfeiffer ASM 390 leak detector
#######################################################

class compressed_fmt(object):
    """ This is to handle the floating point values returned like
           123-45 which means 123e-45
    """
    def __init__(self, skip_end=None):
        self._skip_end = skip_end
    def __call__(self, input_str):
        if self._skip_end is not None:
            ok = False
            for e in self._skip_end:
                if input_str.endswith(e):
                    input_str = input_str[:-len(e)]
                    ok = True
                    break
            if not ok:
                raise RuntimeError('Missing ending character.')
        if len(input_str) != 6:
            raise RuntimeError('Invalid floating point value')
        if input_str[3] not in ['+', '-']:
            raise RuntimeError('Invalid floating point value')
        s = input_str[:3] + 'e' + input_str[3:]
        return float(s)

#@register_instrument('Pfeiffer', 'ASM390', 'L0413 V3.7r01')
@register_instrument('Pfeiffer', 'ASM390')
class pfeiffer_leak_detector_ASM390(visaInstrument):
    """
    This instruments class will communicate with a Pfeiffer ASM390 leak detector.
    It uses the advanced mode.
    It can use the usb connector (which looks like a serial port to the computer)
    """
    def __init__(self, visa_addr, *args, **kwargs):
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == visa_wrap.constants.InterfaceType.asrl:
            baud_rate = kwargs.pop('baud_rate', 9600)
            parity = kwargs.pop('parity', visa_wrap.constants.Parity.none)
            data_bits = kwargs.pop('data_bits', 8)
            stop_bits = kwargs.pop('data_bits',  visa_wrap.constants.StopBits.one)
            read_term = kwargs.pop('read_termination', '\r')
            write_term = kwargs.pop('write_termination', '\r')
            kwargs['baud_rate'] = baud_rate
            kwargs['parity'] = parity
            kwargs['data_bits'] = data_bits
            kwargs['stop_bits'] = stop_bits
            kwargs['read_termination'] = read_term
            kwargs['write_termination'] = write_term
        super(pfeiffer_leak_detector_ASM390, self).__init__(visa_addr, *args, **kwargs)
    @locked_calling
    def read(self, raw=False, count=None, chunk_size=None, skip_response_handler=False):
        ret = super(pfeiffer_leak_detector_ASM390, self).read(raw=raw, count=count, chunk_size=chunk_size)
        if skip_response_handler:
            return ret
        ak = ret[0]
        ret = ret[1:]
        if ak not in ['\x06', '\x15']:
            raise RuntimeError(self.perror('Invalid aknowledgement received.'))
        if ak == '\x15':
            raise RuntimeError(self.perror('Incorrect command.'))
        return ret
    def _current_config(self, dev_obj=None, options={}):
        base = self._conf_helper('tracer_gas', 'autozero_en', 'leak_cal', 'leak_uncal', 'leak_unit', 'pressure_inlet', 'pressure_cell')
        base += ['status=%r'%self.get_status()]
        return base + self._conf_helper(options)
    def idn(self):
        version = self.ask('?MD')
        model, firm = version.split(' ', 1)
        return 'Pfeiffer,%s,NoSerial,%s'%(model, firm)
    def get_error(self):
        err = self.ask('?ER')
        if err == '0':
            return 'No Error.'
        else:
            return err
    def get_warning(self):
        err = self.ask('?WA')
        if err == '0':
            return 'No Warning.'
        else:
            return err
    def get_status(self):
        status = self.status.get()
        st = lambda bit: bool(status&(1<<bit))
        if not st(2):
            cycle = 'out'
        else:
            n = (status>>3)&3
            cycle = ['roughing', 'gross leak', 'normal', 'high sensitivity'][n]
        # bits 12, 13 and 15 should return 1.
        # However bit 13 seems to be 0.
        #if not (st(12) and st(13) and st(15)):
        #    raise RuntimeError(self.perror('Unexpected status value.'))
        result = dict_improved(filament_used=(status&1)+1,
                               filament_on=st(1),
                               cycle=cycle,
                               sniffing_en=st(5),
                               autocal_ok=st(6),
                               control_panel_locked=not st(7),
                               default_presence=not st(8),
                               vent_en=st(9),
                               cycle_start_avail=st(10),
                               hv_pump_sync=st(11),
                               sniffer_probe_clogged=not st(14))
        return result
    def _create_devs(self):
        self.pressure_inlet = scpiDevice(getstr='?PE', str_type=compressed_fmt())
        self.pressure_cell = scpiDevice(getstr='?PS', str_type=compressed_fmt())
        self.leak_cal = scpiDevice(getstr='?LE', str_type=compressed_fmt(skip_end=['R', 'C']))
        self.leak_uncal = scpiDevice(getstr='?LE2', str_type=compressed_fmt())
        self.status = scpiDevice(getstr='?ST', str_type=int)
        self.leak_unit = scpiDevice('=UN{val}','?UN', choices=ChoiceIndex(
                            ['mbar.l/s', 'Pa.m3/s', 'Torr.l/s', 'atm.cc/s', 'ppm', 'sccm', 'sccs', 'mTorr.l/s'], offset=1))
#    These are from the documention but do not work.
#                            ['ppm', 'mbar.l/s', 'Pa.m3/h', 'Torr.l/s', 'gr/yr', 'oz/yr', 'lb/yr', 'custom']))
        self.tracer_gas = scpiDevice(getstr='?GZ', choices=ChoiceIndex({2:'H', 3:'He3', 4:'He4'}))
        self.gage_status = scpiDevice(getstr='?GAU')
        self.autozero_en = scpiDevice(getstr='?AZ', choices=ChoiceSimpleMap(dict(E=True, D=False)))
        self.alias = self.leak_cal
        # This needs to be last to complete creation
        super(pfeiffer_leak_detector_ASM390, self)._create_devs()

#######################################################
##    Agilent TPS-compact
#######################################################

class agilent_dev(BaseDevice):
    def __init__(self, window, type, enable_set=False, time_scale=False, *args, **kwargs):
        super(agilent_dev, self).__init__(*args, **kwargs)
        self._window = window
        self._window_type = type
        self._getdev_p = 'foo'
        self._time_scale = time_scale
        if enable_set:
            self._setdev_p = 'foo'
    def _getdev(self):
        ret = self.instr.ask_window(self._window, type=self._window_type)
        if isinstance(self.choices, ChoiceBase):
            ret = self.choices(ret)
        if self._time_scale:
            ret = 0.2 * ret
        return ret
    def _setdev(self, val):
        if self._time_scale:
            val = int(val/0.2)
        if isinstance(self.choices, ChoiceBase):
            val = self.choices.tostr(val) # here to tostr might return a number.
        parsed = self.instr.write_window(self._window, val, self._window_type)
        if parsed != 'ack':
            raise RuntimeError(self.perror('Invalid response: %s'%parsed))
        self.setcache(val)


@register_instrument('Agilent', 'TwisTorr')
class agilent_twis_torr(visaInstrument):
    """
    This is the driver for a TPS compact agilent pump.
    Most useful devices:
        pumping_en
        vent_open_en
        vent_automatic_en
        pressure
        rotation_rpm
        rotation_Hz
        pump_power
        pump_current
        pump_voltage
        pump_status
    Some devices require control_mode to be in 'serial' to allow set.
    Available methods:
        ask_window
        write_window
    """
    def __init__(self, visa_address, serial_address=0, **kwargs):
        """
        serial_address should be 0 for RS-232, and 0-31 for RS-485
        """
        self._serial_address = serial_address
        cnsts = visa_wrap.constants
        baud_rate = kwargs.pop('baud_rate', 9600)
        parity = kwargs.pop('parity', cnsts.Parity.none)
        data_bits = kwargs.pop('data_bits', 8)
        stop_bits = kwargs.pop('stop_bits', visa_wrap.constants.StopBits.one)
        kwargs['baud_rate'] = baud_rate
        kwargs['parity'] = parity
        kwargs['data_bits'] = data_bits
        kwargs['stop_bits'] = stop_bits
        kwargs['write_termination'] = ''
        kwargs['read_termination'] = ''
        super(agilent_twis_torr, self).__init__(visa_address, **kwargs)
    def idn(self):
        return 'Agilent,TwisTorr,no_serial,no_firmare'
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('pumping_en', 'pressure', 'pressure_unit', 'gage_status', 'gage_power', 'pump_status', 'pump_life_hour', 'pump_cycles', options)
    def _do_chksum(self, message):
        cks = reduce(operator.xor, bytearray(message))
        return '%02X'%cks
    def _parse(self, string, window, read=False):
        string = bytes(string) # string can be a bytearray which returns int when indexing. Make it bytes.
        chksum = string[-2:]
        if self._do_chksum(string[1:-2]) != chksum:
            raise RuntimeError('Invalid Checksum: %r'%string)
        if string[0] != '\x02' or string[-3] != '\x03':
            raise RuntimeError('Invalid start/end: %r'%string)
        addr = string[1]
        if addr != chr(0x80 + self._serial_address):
            raise RuntimeError('Invalid address: %r'%string)
        resp = string[2]
        known_answers = {'\x06':'ack', '\x15': 'nack', '\x32': 'unknown window',
                         '\x33': 'wrong type', '\x34': 'out of range', '\x35':'window disabled'}
        if len(string) == 6:
            ret = known_answers[resp]
            if read:
                raise RuntimeError('Invalid response (%s): %r'%(ret, string))
            return ret
        win = int(string[2:5])
        if win != window:
            raise RuntimeError('Invalid window: %r'%string)
        if string[5] != '\x30':
            raise RuntimeError('Invalid read-write code: %r'%string)
        return string[6:-3]
    def _create_req(self, window, data=None, type='string'):
        """ if data is None, creates a request for a value.
            possible types:
                boolean
                real
                integer
                exp
                string
        """
        addr = chr(0x80+self._serial_address)
        if window>999 or window<0:
            raise ValueError(self.perror('window is out of range'))
        window = '%03i'%window
        if data is None:
            # read
            rw = '\x30'
            data_str = ''
        else:
            # write
            rw = '\x31'
            if type == 'boolean':
                data_str = '1' if data else '0'
            elif type in ['real', 'integer']:
                if data >=1e6 or data <=-1e-5:
                    raise ValueError(self.perror('Data is too large'))
                if type == 'integer':
                    data_str = '%06d'%data
                else:
                    # TODO improve this when needed. I have not seen it used.
                    data_str = '%06.2f'%data
                data_str = data_str[:6]
            elif type == 'exp':
                data_str = '%.1E'%data
            elif type == 'string':
                data_str = '%-10s'%data
                data_str = data_str[:10]
            else:
                raise ValueError(self.perror('Invalid type'))
        req = '\x02' + addr + window + rw + data_str + '\x03'
        chksum = self._do_chksum(req[1:])
        req += chksum
        return req

    def read(self, raw=False, count=None, chunk_size=None):
        ret = ''
        while True:
            c = self.visa.read_raw_n(1)
            if c == '\x02':
                # start
                if ret != '':
                    print 'We are loosing some reply: %r'% ret
                ret = c
            elif c == '\x03': # end
                cksum = self.visa.read_raw_n_all(2)
                return ret+c+cksum
            else:
                ret += c

    def get_param(self, data_str, window, type='string'):
        """ possible type:
                boolean
                string
                integer
                real
                exp
        """
        val = self._parse(data_str, window, read=True)
        if type == 'boolean':
            return bool(int(val))
        elif type in ['real', 'exp']:
            return float(val)
        elif type == 'integer':
            return int(val)
        elif type in 'string':
            # I have seen responses of 10 and 12 bytes
            # The are left align with extra spaces.
            return val.rstrip(' ')
        else:
            raise ValueError(self.perror('Invalid type'))
        return val
    def ask_window(self, window, type='string'):
        request = self._create_req(window)
        result = self.ask(request)
        return self.get_param(result, window, type)
    def write_window(self, window, data, type='string'):
        request = self._create_req(window, data, type)
        ret = self.ask(request)
        parsed =  self._parse(ret, window)
        return parsed
    def _pressure_getdev(self):
        p = self.pressure_raw.get()
        if p == 0.:
            status = self.gauge_status.get()
            power = self.gauge_power.get()
            if power == 'off' or status in ['no gauge connected', 'rid unknown']:
                return -1
            if status.startswith('over'):
                p = 1e10
        if p>1e9:
            # overange
            unit = self.pressure_unit.getcache()
            return {'mbar':1.5e3, 'Pa':150e3, 'Torr':1e3}[unit]
        return p
    def _create_devs(self):
        self.pumping_en = agilent_dev(0, 'boolean', enable_set=True)
        # It does not seem possible to enable low speed
        #self.pump_low_speed_en = agilent_dev(1, 'boolean', enable_set=True)
        self.pump_soft_start_en = agilent_dev(100, 'boolean', enable_set=True)
        self.pressure_unit = agilent_dev(163, 'integer', enable_set=True, choices=ChoiceSimpleMap({0:'mbar', 1:'Pa', 2:'Torr'}))
        #self.pressure = agilent_dev(224, 'exp', autoinit=False)
        self.pressure_raw = agilent_dev(224, 'exp')
        self.gauge_status_raw = agilent_dev(257, 'integer')
        self.gauge_status = agilent_dev(257, 'integer', choices=ChoiceSimpleMap({0:'no gauge connected', 1:'gauge connected',
                                                                                 2:'under range/gage error', 3:'over range/gage error',
                                                                                 4:'rid unknown'}))
        self.gauge_power = agilent_dev(267, 'integer', enable_set=True,
                                       choices=ChoiceSimpleMap({0:'off', 1:'on', 2:'prog sp1', 3:'prog sp2', 4:'prog sp3'}))
        self.rotation_rpm = agilent_dev(226, 'real')
        self.pump_current_mA = agilent_dev(200, 'real')
        self.pump_voltage = agilent_dev(201, 'real')
        self.controller_temp = agilent_dev(216, 'real')
        #self.vent_control = agilent_dev(122, 'boolean', enable_set=True, choices=ChoiceSimpleMap({False:'closed', True:'open'}))
        self.vent_open_en = agilent_dev(122, 'boolean', enable_set=True)
        self.vent_automatic_en = agilent_dev(125, 'boolean', enable_set=True, choices=ChoiceSimpleMap({False:True, True:False}))
        self.vent_opening_delay = agilent_dev(126, 'integer', enable_set=True, time_scale=True, doc='in seconds')
        self.vent_opening_time = agilent_dev(147, 'integer', enable_set=True, time_scale=True, doc='in seconds. 0 is infinite')
        self.rotation_speed_reading_when_stopping_en = agilent_dev(167, 'boolean', enable_set=True)
        self.control_mode = agilent_dev(8, 'boolean', enable_set=True, choices=ChoiceSimpleMap({False:'serial', True:'remote'}))
        self.active_stop_en = agilent_dev(107, 'boolean', enable_set=True)
        # Field taken from Agilent T-plus program
        self.pump_status = agilent_dev(205, 'integer', doc="""\
            0: Stop, 1: Waiting interlock, 2: Ramp, 3: Autotuning, 4: Braking, 5: Normal, 6: Fail""")
        self.error_code = agilent_dev(206, 'integer', doc="""\
            0: No Error, 1: No connection, 2: Pump overtemp, 4: Controller overtemp, 8: Power fail,
            16: --, 32: --, 64: Short circuit, 128: Too high load""")
        self.pump_power = agilent_dev(202, 'real')
        self.pump_temp = agilent_dev(204, 'real')
        self.rotation_Hz = agilent_dev(203, 'real') # t-plus says it is the rotation target, but it fallows  rotation_rpm
        self.controller_heatsink_temp = agilent_dev(211, 'real') # t-plus says: (208=25 C, ... 128=60 C), but I think its in Celsius
        self.controller_part_number = agilent_dev(319, 'string')
        self.controller_serial_number = agilent_dev(323, 'string')
        self.pump_cycles = agilent_dev(301, 'real')
        self.pump_life_hour = agilent_dev(302, 'real')
        # Others: 106=Cooling (0:air or water)
        self._devwrap('pressure')
        self.alias = self.pressure
        # This needs to be last to complete creation
        super(agilent_twis_torr, self)._create_devs()

@register_instrument('Agilent', 'TPS')
class agilent_tps_pump(agilent_twis_torr):
    def idn(self):
        return 'Agilent,TPS,no_serial,no_firmare'
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('pumping_en', 'pressure_unit', 'pump_status', 'pump_life_hour', 'pump_cycles', 'tip_seal_life_hour', options)
    def _pressure_getdev(self):
        p = self.pressure_raw.get()
        if p>1e9:
            # overange
            unit = self.pressure_unit.getcache()
            return {'mbar':1.5e3, 'Pa':150e3, 'Torr':1e3}[unit]
        return p
    def _create_devs(self):
        #self.pressure = agilent_dev(224, 'exp', autoinit=False)
        self.tip_seal_life_hour = agilent_dev(358, 'real')
        # This needs to be last to complete creation
        super(agilent_tps_pump, self)._create_devs()
        # Remove stuff from base class that do not work here.
        del self.gauge_power
        del self.gauge_status
        del self.gauge_status_raw


#######################################################
##    Innficon VCG50x control unit
#######################################################
class inficon_dev(BaseDevice):
    """
    if choices is given, it overrides str_type
    if nch_en is given, if more than one channel is available, then
     choices or str_type will be applied as many times as necessary.
     Both get and set will handle ch. if not set it will use current_ch.
     When a ch is selected only that value will be returned or set.
     When ch is 'all' a vector of all the valus will be set or change.
      if ch is 'all' and set is only given a value, it is repeated to all the channels.
     n_elem is is the number of elements to treat together. It only works for get.
    """
    def __init__(self, cmd, str_type=None, n_elem=1, enable_set=False, nch_en=False, **kwargs):
        super(inficon_dev, self).__init__(**kwargs)
        self._cmd = cmd
        self._str_type = str_type
        self._nch_en = nch_en
        self._n_elem = n_elem
        self._getdev_p = 'foo'
        if enable_set:
            self._setdev_p = 'foo'

    def _getch(self, ch=None, tmp=False):
        if self.instr._nchannels == 1:
            ch = 1
        else:
            prev_ch = self.instr.current_ch.get()
            if ch is not None:
                if isinstance(ch, slice):
                    ch = 'all'
                self.instr.current_ch.set(ch)
            ch =  self.instr.current_ch.get()
            if ch == 'all':
                ch = slice(None)
            if tmp:
                self.instr.current_ch.set(prev_ch)
        return ch

    def _get_nch(self):
        if self._nch_en:
            return self.instr._nchannels
        else:
            return 1

    def _checkdev(self, val, ch=None):
        nch = self._get_nch()
        if nch > 1:
            ch = self._getch(ch)
            if isinstance(ch, slice):
                if isinstance(val, (list, tuple, np.ndarray)):
                    if len(val) != nch:
                        raise ValueError(self.perror('Invalid length for values. It should have %i elements.'%nch))
                    for i in range(nch):
                        super(inficon_dev, self)._checkdev(val[i])
                else:
                    super(inficon_dev, self)._checkdev(val)
        else:
            super(inficon_dev, self)._checkdev(val)

    def getformat(self, **kwarg):
        nch = self._get_nch()
        multi = False
        graph = [0]
        if nch > 1:
            ch = kwarg.get('ch', None)
            ch = self._getch(ch, tmp=True)
            if isinstance(ch, slice):
                multi = False
            else:
                multi = ['ch%i'%i for i in range(1, nch+1)]
                graph = range(3)
        else:
            multi = False
        fmt = self._format
        fmt.update(multi=multi, graph=graph)
        return super(inficon_dev, self).getformat(**kwarg)

    def _getdev(self, ch=None, tmp=False):
        res = self.instr.ask(self._cmd)
        def conv(val):
            if isinstance(self.choices, ChoiceBase):
                return self.choices(val)
            else:
                return _fromstr_helper(val, self._str_type)
        nch = self._get_nch()
        if nch > 1:
            r = res.split(',')
            N = self._n_elem
            if N != 1:
                r = [r[i*N:(i+1)*N] for i in range(nch)]
            ret = [conv(d) for d in r]
            ch = self._getch(ch, tmp)
            ret = ret[ch]
        else:
            ret = conv(res)
        return ret

    def _setdev(self, val, ch=None):
        def conv(val):
            if isinstance(self.choices, ChoiceBase):
                return self.choices.tostr(val)
            else:
                return _tostr_helper(val, self._str_type)
        nch = self._get_nch()
        if nch > 1:
            if isinstance(val, (list, tuple, np.ndarray)):
                # we already checked this is valid
                pass
            else:
                # onlt a single value given
                ch = self._getch(ch)
                if isinstance(ch, slice):
                    # we repeat the value to all sensors
                    val = [val]*nch
                else:
                    vals = self.get(ch='all', tmp=True)
                    vals[ch-1] = val
                    val = vals
            val_str = ','.join([conv(d) for d in val])
        else:
            val_str = conv(val)
        self.write('%s,%s'%(self._cmd, val_str))
        self.setcache(val)


@register_instrument('INFICON', 'VGC503') # Untested
@register_instrument('INFICON', 'VGC502') # Untested
#@register_instrument('INFICON', 'VGC501', 'fw:1.07-hw:1.0-model:398-481')
@register_instrument('INFICON', 'VGC501')
class inficon_vgc50x(visaInstrument):
    """
    This is the driver for a Inficon gage control unit.
    Most useful devices:
        pressure
    Useful methods:
        datetime
        continous_output_disable
    """
    # we had trouble with the Visa serial connection that kept frezzing.
    # So we use the serial module instead.
    def __init__(self, visa_addr, overrange_val=1500., underrange_val=0., sensor_off_val=-1., **kwargs):
        """
        overrange_val, underrange val and sensor_off_val are the pressure returned when the gauge is in that condition.
            It is a single value used for all channels.
        """
        self._underrange_val = underrange_val
        self._overrange_val = overrange_val
        self._sensor_off_val = sensor_off_val
        cnsts = visa_wrap.constants
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == cnsts.InterfaceType.asrl:
            #baud_rate = kwargs.pop('baud_rate', 115200)
            baud_rate = kwargs.pop('baud_rate', 9600)
            parity = kwargs.pop('parity', cnsts.Parity.none)
            data_bits = kwargs.pop('data_bits', 8)
            stop_bits = kwargs.pop('stop_bits', cnsts.StopBits.one)
            kwargs['baud_rate'] = baud_rate
            kwargs['parity'] = parity
            kwargs['data_bits'] = data_bits
            kwargs['stop_bits'] = stop_bits
        kwargs['write_termination'] = '\r\n'
        kwargs['read_termination'] = '\r\n'
        self._write_top_level = True
        super(inficon_vgc50x, self).__init__(visa_addr, **kwargs)
    def idn(self):
        res = self.ask('AYT')
        r = res.split(',')
        return 'INFICON,{0},{2},fw:{3}-hw:{4}-model:{1}'.format(*r)
    def get_error_raw(self):
        return self.ask('ERR')
    def get_error(self, raw_val=None):
        if raw_val is None:
            err = self.get_error_raw()
        else:
            err = raw_val
        res = []
        if err == '0000':
            return "No error."
        if err[0] == '1':
            res.append('Controller error')
        if err[1] == '1':
            res.append('No Hardware error')
        if err[2] == '1':
            res.append('inadmissible error')
        if err[3] == '1':
            res.append('Syntax error')
        return ','.join(err) + '.'
    def reset(self, perform=False):
        """ if perform is not True, the reset is not done but it returns
            the list of present error messages
        """
        cmd = 'RES'
        if perform:
            cmd += ',1'
        res = self.ask(cmd)
        if perform:
            wait(5)
            # The continous mode was reenable. So stop it.
            self.continous_output_disable()
        msgs = ['No error', 'Watchdog has responded', 'Task fail error', 'Flash error',
                'RAM error', 'EEPROM error', 'DISPLAY error', 'A/D converter error', 'UART error',
                'Gauge 1 general error', 'Gauge 1 ID error',
                'Gauge 2 general error', 'Gauge 2 ID error',
                'Gauge 3 general error', 'Gauge 3 ID error']
        return [msgs[int(r)] for r in res.split(',')]

    def _conv_pressure(self, val):
        if not isinstance(val, list):
            val = val.split(',')
        #return dict(pressure=float(val[1]), status=int(val[0]))
        status, pressure = int(val[0]), float(val[1])
        if status >= 1:
            # status are: 0= measurement okay, 1= underrange, 2= overrange,
            #             3=  Sensore error, 4= Sensor off, 5= No sensor,
            #             6= identification error, 7= Error BPG, HPG, BCG
            pressure = [None, self._underrange_val, self._overrange_val, -3e6,
                        self._sensor_off_val, -5e6, -6e6, -7e6][status]
        return pressure


    def datetime(self, set=False):
        """ If set is True, it will push the computer time. Otherwise
            it reads the value from the controller.
        """
        if set:
            lt = time.localtime()
            self.write('DAT,'+time.strftime('%Y-%m-%d', lt))
            self.write('TIM,'+time.strftime('%H:%M', lt))
        else:
            date = self.ask('DAT')
            tm = self.ask('TIM')
            return date+' '+tm

    def _current_config(self, dev_obj=None, options={}):
        prev_ch = self.current_ch.get()
        self.current_ch.set('all')
        base = self._conf_helper('pressures', 'pressure_unit', 'gas_type', 'cal_factor',
                                 'offset_correction', 'offset_correction_val', 'gage_type',
                                 'filter', 'HV_control_en')
        base += ['vals_under_over_off=%r'%[self._underrange_val, self._overrange_val, self._sensor_off_val]]
        self.current_ch.set(prev_ch)
        return base + self._conf_helper('current_ch', options)

    @locked_calling
    def write(self, cmd, termination='default'):
        if self._write_top_level:
            try:
                self._write_top_level = False
                self.ask(cmd, not_enq=True)
            finally:
                self._write_top_level = True
        else:
            super(inficon_vgc50x, self).write(cmd, termination=termination)

    def continous_output_disable(self):
        """ This stops continous output and empties the read buffer """
        super(inficon_vgc50x, self).write('\x03', termination=None) # Sends ETX, end of Text (CTRL-C)
        # It takes a little while before the system recovers
        wait(1)
        self.visa.flush(visa_wrap.constants.VI_IO_IN_BUF_DISCARD)


    def continuous_output_enable(self, interval=1):
        """ set the continuous reporting of values (like when it is turned on)
            interval can be 0.1, 1 or 60 s. The default is 1.
        """
        i = [.1, 1, 60].index(interval)
        self.write('COM,%i'%i)

    @locked_calling
    def ask(self, cmd, not_enq=False):
        if self._write_top_level:
            try:
                self._write_top_level = False
                res = super(inficon_vgc50x, self).ask(cmd)
            finally:
                self._write_top_level = True
        else:
            res = super(inficon_vgc50x, self).ask(cmd)
        if res != '\x06': # \x06 is ACK
            if res == '\x15': # this is NACK
                raise RuntimeError(self.perror('Received NACK (negative acknowledge)'))
            else:
                raise RuntimeError(self.perror('Received unexpected reply (hex:"%s")'%codecs.encode(res, 'hex_codec')))
        if not_enq:
            return
        super(inficon_vgc50x, self).write('\x05', termination=None) # ENQ character: enquiry (request data)
        return self.read()
    def _create_devs(self):
        self.continous_output_disable()
        nch = int(self.idn_split()['model'].split('_')[0][-1])
        self._nchannels = nch
        self.current_ch = MemoryDevice('all', choices=['all']+range(1, nch+1))
        pressure_doc = """
            see pressure_unit device for unit used.
            Some special values are returned for the following conditions:
                underrange: see underrange_val as instrument instantation parameter (default to 0.)
                overrange: see overrange_val as instrument instantation parameter (default to 1500.)
                sensor error:         -3e-6
                sensor off: see sensor_off_val as instrument instantation parameter (default to -1.)
                no sensor:            -5e-6
                identification error: -6e-6
                error BPG, HPG, BCG:  -7e-6
            """
        conv_pressure = ProxyMethod(self._conv_pressure)
        self.pressure1 = inficon_dev('PR1', str_type=conv_pressure, autoinit=False, doc=pressure_doc)
        if nch >= 2:
            self.pressure2 = inficon_dev('PR2', str_type=conv_pressure, autoinit=False, doc=pressure_doc)
        if nch == 3:
            self.pressure3 = inficon_dev('PR3', str_type=conv_pressure, autoinit=False, doc=pressure_doc)
        self.pressures = inficon_dev('PRX', str_type=conv_pressure, nch_en=True, doc=pressure_doc)
        self.pressure_unit = inficon_dev('UNI', enable_set=True, choices=ChoiceIndex(['mbar/bar', 'Torr', 'Pascal', 'Micron', 'hPascal', 'Volt']))
        self.gas_type = inficon_dev('GAS', enable_set=True, nch_en=True, choices=ChoiceIndex(['N2', 'Ar', 'H2', 'He', 'Ne', 'Kr', 'Xe', 'Other']))
        self.cal_factor = inficon_dev('COR', enable_set=True, nch_en=True, str_type=float, min=0.1, max= 10., setget=True)
        self.offset_correction = inficon_dev('OFC', enable_set=True, nch_en=True, choices=ChoiceIndex(['off', 'on', 'activate', 'adjust_zero']))
        self.offset_correction_val = inficon_dev('OFD', enable_set=True, nch_en=True, str_type=float, setget=True)
        self.gage_type = inficon_dev('TID', str_type=str, nch_en=True)
        self.filter = inficon_dev('FIL', enable_set=True, nch_en=True, choices=ChoiceIndex(['off', 'fast', 'normal', 'slow']))
        self.HV_control_en = inficon_dev('HVC', enable_set=True, nch_en=True, str_type=bool)
        self.temp_inner = inficon_dev('TMP', str_type=int, doc='In Celsius.')
        self.resistance_id_test = inficon_dev('TAI', nch_en=True, str_type=float, autoinit=False)
        self.operating_hours = inficon_dev('RHR', str_type=int, autoinit=False)
        self.alias = self.pressures
        # This needs to be last to complete creation
        super(inficon_vgc50x, self)._create_devs()



#######################################################
##    Delft BIAS-DAC
#######################################################

#@register_instrument('Delft', 'BIAS-DAC', '1.4')
@register_instrument('Delft', 'BIAS-DAC')
class delft_BIAS_DAC(visaInstrument):
    """
       This is to set the voltages on a Delft made BIAS-DAC.
       It works with version 1.4 of the fiber control box.
       The box is only connected with a serial port.
       WARNING: the voltages that are read are only what the
         control box remembers it sent to the hardware. If the
         power is lost on the hardware or the control box, the
         values are INVALID until new ones are set.
       For the voltages to be valid, the programs needs to
       know the settings of the 4 dials. You should set them
       up properly before using the device.

       Useful device:
          level
          level_all
          current_ch
       Useful methods:
          set_config
          get_config
    """
    def __init__(self, address):
        self._last_error_val = 0
        self._dac_modes_blocks = [None]*4
        self._last_dac_read_time = None
        self._last_dac_read_vals = None
        cnsts = visa_wrap.constants
        super(delft_BIAS_DAC, self).__init__(address, parity=cnsts.Parity.odd, baud_rate=115200, data_bits=8,
             stop_bits=cnsts.StopBits.one, write_termination=None, read_termination=None, end_input=cnsts.SerialTermination.none)
        # Note that end_input default is cnsts.SerialTermination.termination_char
        #  the read code works even in that case. However to be clearer about our intentions we set it properly here
        #  (the difference is that self.visa.read_raw_n will stop at term char (newline). read_raw_n_all will
        #   repeat the read until the full count is received)
    def _base_command(self, command, *args):
        """
        This handles commands 'set_dac', 'read_dacs', 'get_version', 'set_interface_bits'
                              and even 'continues_send_data'
        The args for 'set_dac', 'continues_send_data' are
            channel number (1-16)
            dac value (uint16)
        The args for 'set_interface_bits' are
            values: uint32
                     note that value 1<<27 turns the LED on.
                     some bits cannot be toggle (masked with 0xff00a0a0)
        The return value is None except for:
            'get_version': where is is an integer (divide by 10 to get version number)
            'read_dacs': where it is 16 uint16
        """
        send_header = '>bbbb' # size, error, out_size, action
        recv_header = '>bb'   # size, error
        if command in ('set_dac','continues_send_data') :
            send_header += 'bH' # channel, dac_value(uint16)
            cmd_val = 1 if command == 'set_dac' else 3
            n_arg = 2
            ch = args[0]
            daq_val = args[1]
            if ch<1 or ch>16:
                raise ValueError('Invalid channel number. Should be 1<=ch<=16')
            if daq_val<0 or daq_val>0xffff:
                raise ValueError('Invalid daq_val. Should be 0<= val <= 0xffff')
        elif command == 'read_dacs':
            cmd_val = 2
            n_arg = 0
            recv_header += '16H'
        elif command == 'get_version':
            cmd_val = 4
            n_arg = 0
            recv_header += 'b'
        elif command == 'set_interface_bits':
            send_header += 'bH4s' # channel, dac_value(uint16), inteface_bits(uint32)
            cmd_val= 5
            n_arg = 3
            ib = struct.pack('<I', args[0]&0xff00a0a0)
            # the inteface bit has the wrong endianness
            args = (0,0)+(ib,)+args[1:]
        else:
            raise ValueError('Invalid Command')
        if len(args) != n_arg:
            raise ValueError('Invalid number of arguments')
        send_len = struct.calcsize(send_header)
        recv_len = struct.calcsize(recv_header)
        send_str = struct.pack(send_header, send_len, 0, recv_len, cmd_val, *args)
        self.write(send_str)
        res = self.read(count=recv_len)
        ret_vals = struct.unpack(recv_header, res)
        n_read, error = ret_vals[:2]
        self._last_error_val = error
        if n_read != recv_len:
            raise RuntimeError('Unexpected return value header length')
        if error != 0:
            if error & 0x20:
                print "WARNING: The controller was reset (watchdog) (%i)"%error
                #raise RuntimeError('The controller was reset (watchdog) (%i)'%error)
            if error & 0x40:
                raise RuntimeError('Invalid dac channel (%i)'%error)
            if error & 0x80:
                raise RuntimeError('Wrong Action (%i)'%error)
            raise RuntimeError('Unknown error (%i)'%error)
        rest = ret_vals[2:]
        if len(rest):
            return rest
        else:
            return None
    def _get_ch_mode(self, ch):
        block_index = (ch-1)//4
        mode = self._dac_modes_blocks[block_index]
        return mode
    def _set_ch_command(self, val, ch):
        mode = self._get_ch_mode(ch)
        if mode is None:
            raise RuntimeError(self.perror('You did not initialize the mode for ch=%i. See set_config method.'%ch))
        dac_val = self._v2dac_conv(val, mode)
        self._base_command('set_dac', ch, dac_val)
        self._last_dac_read_time = None
    def _get_all_command(self):
        last = self._last_dac_read_time
        now = time.time()
        if last is None or last+0.5 < now:
            # force a read after a set, or after more than 0.5s since last read
            #print 'READING DAC'
            data = self._base_command('read_dacs')
            self._last_dac_read_time = now
            self._last_dac_read_vals = data
            return data
        else:
            return self._last_dac_read_vals
    def _get_ch_command(self, ch, do_exc=True):
        data = self._get_all_command()
        val = data[ch-1]
        mode = self._get_ch_mode(ch)
        if mode is None:
            if do_exc:
                raise RuntimeError(self.perror('You did not initialize the mode for ch=%i. See set_config method.'%ch))
            else:
                return val
        return self._dac2v_conv(val, mode)
    def read(self, raw=False, count=2, chunk_size=None):
        # change the count default.
        return super(delft_BIAS_DAC, self).read(count=count)
    def idn(self):
        firm_version = self._base_command('get_version')[0]/10.
        return 'Delft,BIAS-DAC,serial-unknown,%r'%firm_version
    def get_error(self):
        return self._last_error_val
    _mode_offset = dict(neg=4., bip=2., pos=0.)
    _dac_full_range = 2**16
    def _dac2v_conv(self, dac, mode):
        v = dac*4./self._dac_full_range
        v -= self._mode_offset[mode]
        return v
    def _v2dac_conv(self, v, mode):
        full_range = self._dac_full_range
        v += self._mode_offset[mode]
        dac = v/4. * full_range
        dac = int(round(dac))
        # make sure 0 <= dac < full_range
        dac = min(max(dac, 0), full_range-1)
        return dac
    def set_config(self, dac_mode_1_4=None, dac_mode_5_8=None, dac_mode_9_12=None, dac_mode_13_16=None):
        """
        For all the blocks the valid options are None, 'pos', 'neg', 'bip'
        where None means keep the previous value,
        'pos', 'neg', 'bip' mean positive (0 - 4V), negative (-4 - 0V) and bipolar (-2 - 2V)
        """
        modes = [dac_mode_1_4, dac_mode_5_8, dac_mode_9_12, dac_mode_13_16]
        for i, m in enumerate(modes):
            if m is None:
                continue
            if m not in ['pos', 'neg', 'bip']:
                raise ValueError(self.perror('invalid mode'))
            self._dac_modes_blocks[i] = m
    def get_config(self, do_return=False):
        blocks = self._dac_modes_blocks
        if do_return:
            return blocks
        print 'Current dac mode is:'
        for i in range(4):
            mode = blocks[i]
            print '   DAC mode %2i - %2i: %s'%(i*4+1, i*4+4, mode)
    def _level_helper(self, ch):
        if ch is None:
            return self.current_ch.get()
        if ch<1 or ch>16:
            raise ValueError(self.perror('channel is outside the 1-16 range.'))
        self.current_ch.set(ch)
        return ch
    def _level_checkdev(self, val, ch=None):
        ch = self._level_helper(ch)
    def _level_setdev(self, val, ch=None):
        ch = self._level_helper(ch)
        self._set_ch_command(val, ch)
    def _level_getdev(self, ch=None):
        ch = self._level_helper(ch)
        return self._get_ch_command(ch)
    def _level_all_setdev(self, all_values):
        if len(all_values) != 16:
            raise ValueError(self.perror('Need to provide a vector of 16 elements'))
        for i, val in enumerate(all_values):
            self._set_ch_command(val, i+1)
    def _level_all_getdev(self):
        return np.array([self._get_ch_command(ch) for ch in range(1,17)])
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        modes = self.get_config(do_return=True)
        values = [self._get_ch_command(ch, do_exc=False) for ch in range(1,17)]
        for i, m in enumerate(modes):
            if m is None:
                for ch in range(i*4, i*4+4):
                    values[ch] = '%#06x'%values[ch]
        base = ['modes=%r'%modes, 'values=%r'%values]
        return base+self._conf_helper('current_ch', options)
    def _create_devs(self):
        self.current_ch = MemoryDevice(1, choices=range(1,17))
        self._devwrap('level', autoinit=False, setget=True, doc='option ch: it is the channel to use (1-16). When not given it reuses the last one.')
        titles = ['dac_%02i'%i for i in range(1, 17)]
        self._devwrap('level_all', setget=True, autoinit=False, multi=titles)
        self.alias = self.level
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

#######################################################
##    Micro Lambda Wireless MLBF filter
#######################################################

#@register_instrument('micro_lambda_wireless', 'MLBFP-78020', '1.2  Aug 29 2016')
@register_instrument('micro_lambda_wireless', 'MLBFP-78020')
class micro_lambda_mlbf(BaseInstrument):
    """
    This is the driver for the Micro Lambda Wireless MLBF YIG filter.
    It currently works using the UDP (network) protocol or the USB protocol
    if cython-hipapi isinstalled. To install cython-hipapi on windows can be
    done with: pip install hidapi
    You need to specify either the udp_address (like '192.168.137.10' or 'mlbf0093')
    or the usb value (True or a serial number string like '0093')
    NOTE: the usb driver does hang when communicating a lot. When that happens the whole
    instrument is completely frozen and requires disconnecting the power cable.
    """
    def __init__(self, udp_address=None, udp_port=30303, usb=None, **kwargs):
        if usb is not None and usb is not False:
            import hid
            usbdev = hid.device()
            usb_kwargs = {}
            if usb is not True:
                usb_kwargs['serial_number'] = unicode(usb)
            usbdev.open(0x04d8, 0x003f, **usb_kwargs)
            usbdev.set_nonblocking(True) # just to be safe. Probably unecessary since I used read timeouts.
            self._usbdev = usbdev
            self._usb_timeout = None
            self._socket = None
        else:
            self._socket = socket.socket(type=socket.SOCK_DGRAM)
            self._socket.connect((udp_address, udp_port))
            self._usbdev = None
        self.set_timeout = 3
        self._last_write = 0
        # from testing 0.001 seems good enough. So to be safe, make it 0.01
        self._write_delay = 0.01
        super(micro_lambda_mlbf, self).__init__(**kwargs)

    def idn(self):
        conf = self.conf_general()
        return 'micro_lambda_wireless,%s,%s,%s'%(conf['model'], conf['serial'], conf['firmware_date'])

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = self._conf_helper('freq', 'temperature', 'temperature_highest')
        opts += ['conf_general=%s'%self.conf_general()]
        opts += ['protocol=%s'%('udp' if self._socket is not None else 'usb')]
        opts += self._conf_helper(options)
        return opts

    @locked_calling
    def write(self, val):
        # writing to fast after a write prevents the first one from working
        # (for example a query of the freq immediately after setting it, prevents
        #  the frequency from changing)
        now = time.time()
        delta = now-self._last_write
        delay = self._write_delay
        if delta < delay:
            wait(delay-delta)
        if self._socket is not None:
            self._socket.send(val)
        else:
            data = [0]*65
            for i, s in enumerate(val):
                data[i+1] = ord(s)
            self._usbdev.write(data)
        self._last_write = time.time()

    @locked_calling
    def read(self, raw=None, chunk_size=None):
        if self._socket is not None:
            ret = self._socket.recv(256)
        else:
            ret = self._usbdev.read(65, timeout_ms=int(self._usb_timeout*1e3))
            if len(ret) == 0:
                raise RuntimeError(self.perror('Timeout when reading.'))
            ret = ''.join(map(chr, ret))
        self._last_write = 0
        # all the reads I have seen have been 18 byte long.
        # Theres is padding with \0 and for socket only (not usb) terminates with \r\n
        zero_ind = ret.find('\0')
        if zero_ind >= 0:
            ret = ret[:zero_ind]
        return ret

    @property
    def set_timeout(self):
        """ The timeout in seconds """
        if self._socket is not None:
            return self._socket.gettimeout()
        else:
            return self._usb_timeout
    @set_timeout.setter
    def set_timeout(self, val):
        if self._socket is not None:
            self._socket.settimeout(val)
        else:
            self._usb_timeout = val
    @locked_calling

    def ask(self, val, raw=None, chunk_size=None):
        self.write(val)
        return self.read()

    @locked_calling
    def close(self):
        if self._socket is not None:
            self._socket.shutdown()
            self._socket.close()
        else:
            self._usbdev.close()

    def _freq_setdev(self, val):
        """ Set/get frequency in Hz """
        if self._socket is not None:
            self.write('F%.4f'%(val*1e-6))
        else: # usb returns an empty string, udp returns nothing
            self.ask('F%.4f'%(val*1e-6))
    def _freq_getdev(self):
        s = self.ask('R16')
        return float(s)*1e6

    def set_display(self, display_string=None):
        """ Sets the instrument 2 line display to the given string.
            if None, set the first line to freq, the second to temperature.
        """
        if display_string is None:
            return self.ask('DT')
        if len(display_string) > 32:
            raise ValueError(self.perror('The requested display string is too long. Need length <= 32.'))
        self.write('"%s"'%display_string)

    def conf_general(self):
        clean = lambda x: x.rstrip('\n\r ')
        model = self.ask('R0')
        serial = self.ask('R1')
        product = self.ask('R2')
        freq_min_MHz = float(self.ask('R3'))
        freq_max_MHz = float(self.ask('R4'))
        v3_0 = float(self.ask('V1')[:-1]) # Need to remove terminating V
        v3_3 = float(self.ask('V2')[:-1]) # Need to remove terminating V
        v5_0 = float(self.ask('V3')[:-1]) # Need to remove terminating V
        vp15 = float(self.ask('V4')[:-1]) # Need to remove terminating V
        vn15 = float(self.ask('V5')[:-1]) # Need to remove terminating V
        filter_bandwidth_MHz = float(self.ask('R5'))
        filter_insertion_loss_dB = float(self.ask('R6'))
        filter_limit_power_dBm = float(self.ask('R7'))
        temperature_min = float(self.ask('R8'))
        temperature_max = float(self.ask('R9'))
        non_volatile_state = clean(self.ask('R11'))
        firmware_date = clean(self.ask('R12'))
        unit_health = self.ask('R13')
        unit_calibration_status = self.ask('R14')
        unit_self_test_result = self.ask('R15')
        filter_passband_spurs_ripples_max_dB = float(self.ask('R17'))
        filter_off_resonance_isolation_min_dB = float(self.ask('R18'))
        filter_bandwidth_meas_spec_db = float(self.ask('R23'))
        unit_coarse_calibration_status = self.ask('R26')
        unit_fine_calibration_status = self.ask('R27')
        firmware_tcpip_stack_version = self.ask('R29')
        firmware_build_time = self.ask('R30')
        ret = locals()
        del ret['self']
        del ret['clean']
        return ret

    def conf_network(self):
        clean = lambda x: x.rstrip('\n\r ')
        dhcp_status = clean(self.ask('R100'))
        ip_addr = clean(self.ask('R101'))
        ip_mask = clean(self.ask('R102'))
        ip_gateway = clean(self.ask('R103'))
        ip_dns1 = clean(self.ask('R104'))
        ip_dns2 = clean(self.ask('R105'))
        mac_address = clean(self.ask('R106'))
        hostname = clean(self.ask('R107'))
        udp_port = int(self.ask('R108'))
        ret = locals()
        del ret['self']
        del ret['clean']
        return ret

    def get_status(self):
        status = self.ask('?')
        val = int(status, 2)
        return dict(self_test_pass=bool(val&0x40), novo_locked=bool(val&0x80))

    def _create_devs(self):
        self.temperature = scpiDevice(getstr='T', str_type=lambda x: float(x[:-1])) # Need to remove terminating C
        self.temperature_highest = scpiDevice(getstr='R10', str_type=float)
        fmin = float(self.ask('R3'))-100
        fmax = float(self.ask('R4'))+100
        self._devwrap('freq', min=fmin*1e6, max=fmax*1e6, setget=True)
        self.alias = self.freq
        self.freq_MHz = ScalingDevice(self.freq, 1e-6, quiet_del=True)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

# Above we use the UDP or USB connection protocol.
# You can also connect using telnet.
#  - The windows telnet works ok
#  - The cygwin works if you specify the port (23) because that prevents
#        automatic initiation of TELNET options.
#  - The protocol seem fragile (hence preventing option negotiation)
#      bad entries can easily block it
#  - It allows only one connection at a time.
# You can also use the web server:
#  - connect to http://192.168.137.10 or something to that effect (standard port 80)
#  - in python
#     import httplib
#     ht = httplib.HTTPConnection('192.168.137.10')
#     ht.request('POST', '/diag.htm', 'cmd=r1'); resp = ht.getresponse()
#     resp.status, resp.reason, resp.read()
#   - can replace /diag.htm  by /commands.htm
#   - should also be able to use /index.htm but that does not seem to work

#######################################################
##    Andeen Hagerling AH 2550A  Ultra-Precision 1 kHz capacitance bridge
#######################################################

#@register_instrument('ANDEEN-HAGERLING', 'AH2550A', 'AH2X0217')
@register_instrument('ANDEEN-HAGERLING', 'AH2550A')
class ah_2550a_capacitance_bridge(visaInstrumentAsync):
    """
    This is the driver for the Andeen Hagerling AH 2550A  Ultra-Precision 1 kHz capacitance bridge.
    The protect the life of the instrument relays, do not measure continously (or for long periods
    of time) with the averaging at 7 or above.
       Useful device:
           readval
           fetch
           average
           bias
    """
    def __init__(self, *args, **kwargs):
        self._async_trig_current_data = None
        super(ah_2550a_capacitance_bridge, self).__init__(*args, **kwargs)

    def idn_split(self):
        idn = self.idn()
        no_labels = False
        if idn.startswith('\n'):
            no_labels = True
        #'MANUFACTURER    ANDEEN-HAGERLING\nMODEL/OPTIONS   AH2550A  --------\nSERIAL NUMBER   00100319\nACTIVE FIRMWARE AH2X0217'
        pp = idn.split('\n')
        def check_skip(s, start_str):
            if not no_labels:
                if not s.startswith(start_str):
                    raise RuntimeError('Unexepected idn string format')
                s = s[len(start_str):].lstrip()
            return s
        vm = check_skip(pp[0], 'MANUFACTURER')
        if vm == '':
            # without labels the current firmware (AH2X0217) returns an empty manufacturer
            vm = 'ANDEEN-HAGERLING'
        model_option = check_skip(pp[1], 'MODEL/OPTIONS')
        if ',' in model_option:
            # using ieee:
            mo = model_option.split(',')
        else:
            mo = model_option.split(' ')
        model = mo[0].rstrip()
        option = mo[-1]
        sn = check_skip(pp[2], 'SERIAL NUMBER')
        fm = check_skip(pp[3], 'ACTIVE FIRMWARE')
        return dict(vendor=vm, model=model, option=option, serial=sn, firmware=fm)

    def _get_esr(self):
        # does not have esr register
        return 0

    def _async_trigger_helper(self):
        self._async_trig_current_data = None
        self.write('*sre 16;SIngle')

    def _async_detect(self, max_time=.5): # 0.5 s max by default
        ret = super(ah_2550a_capacitance_bridge, self)._async_detect(max_time)
        if not ret:
            # This cycle is not finished
            return ret
        # we got a trigger telling data is available. so read it, before we turn off triggering in cleanup
        data = self.read()
        self._async_trig_current_data = data
        return ret

    def _async_cleanup_after(self):
        self._async_trig_current_data = None
        self.write('*sre 0') # disable trigger on data ready to prevent unread status byte from showing up
        super(ah_2550a_capacitance_bridge, self)._async_cleanup_after()


    def get_error(self, no_reset=False):
        """ when no_reset is True, the error state is read but not reset """
        if no_reset:
            flags = self.read_status_byte()
        else:
            # This will also reset the flags
            flags = int(self.ask('*STB?'))
        errors = []
        if flags & 0x01:
            errors.append('Oven temperature invalid')
        if flags & 0x02:
            errors.append('Command error')
        if flags & 0x04:
            errors.append('User request')
        if flags & 0x08:
            errors.append('Powered on')
        # flags & 0x10 is ready for command
        if flags & 0x20:
            errors.append('Execution Erro')
        # flags & 0x40 is Master summary
        # flags & 0x80 is message available
        if len(errors):
            return ', '.join(errors)
        else:
            return 'No errors.'

    def clear(self):
        #some device buffer status byte so clear them
        while self.read_status_byte()&0x40:
            pass

    def init(self, full=False):
        self.write('*sre 0') # disable trigger (we enable it only when needed)
        self.clear()
        if full:
            # These are normally reset during power on.
            #  float (could be sci or eng), labels off, ieee on (commas), variable spacing (as opposed to fix)
            self.write('FORMAT float,OFF,ON,VARIABLE')
            # fields: sample off, frequency off, Cap 9 digits, loss 9 digits, voltage on, message(error) off means a number
            #  The error shows first
            self.write('FIELD OFF,OFF,9,9,ON,OFF')
            # With this configuration, an invalid question returns '32' or '36'
            #  when error are off the corresponding messages are: ILLEGAL WORD, and SYNTAX ERROR
            #  Table B3 says ILLEGAL WORD is 31, SYNTAX ERROR is 35

    def conf_datetime(self, set_to_now=False, passcode='INVALID'):
        """ The correct passcode(owner or calibrator) is necessary to change the date/time """
        if set_to_now:
            if passcode == 'INVALID':
                raise ValueError(self.perror('You need to specify a valid passcode'))
            tm = time.localtime()
            cmd = 'STOre DAte %i,%i,%i\n%s\nSTOre TIme %i,%i,%i\n%s'%(tm.tm_year, tm.tm_mon, tm.tm_mday, passcode,
                                                                    tm.tm_hour, tm.tm_min, tm.tm_sec, passcode)
            self.write(cmd)
        d = self.ask('SHow DAte')
        t = self.ask('SHow TIme')
        d = map(int, d.split(','))
        t = map(int, t.split(','))
        runtime_hours = int(self.ask('SHow STAtus'))
        return dict(date='%04i-%02i-%02i %02i:%02i:%02i'%tuple(d+t), runtime_hours=runtime_hours)

    def conf_firmwares(self):
        firmwares = self.ask('SHow FIRMware')
        return dict(zip(['bank_rom', 'bank_flash1', 'bank_flash2'], firmwares.split('\n')))

    def conf_zero(self, enable=None, cap=None, loss=None, use_last=False):
        """ This is used to configure zero mode.
            If none of the entries are specified, it returns the current setting.
            If you use use_last (uses last reading as 0 value) you cannont use cap or loss.
            If either cap or loss is specified, the other value is unchanged.
        """
        if use_last and (cap is not None or loss is not None):
            raise ValueError(self.perror('You can only specify cap/loss or use_last'))
        if enable is not None and not enable:
            self.write('Zero '+Choice_bool_OnOff.tostr(enable))
        if use_last:
            self.write('Zero FEtch')
        if cap is not None or loss is not None:
            prev = self.conf_zero()
            if cap is None:
                cap = prev.cap
            if loss is None:
                loss = prev.loss
            # Need to always specify both, otherwise it is an error
            self.write('Zero POINT %r,%r'%(cap, loss))
        if enable is not None and enable:
            self.write('Zero '+Choice_bool_OnOff.tostr(enable))
        res = self.ask('SHow Zero')
        # returns: 'OFF\n" ",0.00000000," ",0.00000000'
        en, points_raw = res.split('\n')
        ret = dict_improved(enabled = Choice_bool_OnOff(en))
        zero_fmt = ChoiceMultiple(['cap_lbl', 'cap', 'loss_lbl', 'loss'], [quoted_string(), float, quoted_string(), float])
        ret.update(zero_fmt(points_raw).items())
        return ret

    def conf_reference(self, enable=None, cap=None, loss=None, percent=None, use_last=False):
        """ This is used to configure reference mode.
            If none of the entries are specified, it returns the current setting.
            enable/use_last/percent can be None, 'cap', 'loss', 'all' (or True), 'none' (or False)
            If you use use_last (uses last reading as 0 value) you cannont use cap or loss.
            If either cap or loss is specified, the other value is unchanged.
        """
        def cleanup(x):
            if x is None:
                return x
            if x not in [True, False, 'all', 'none', 'cap', 'loss']:
                raise ValueError(self.perror('Invalid option'))
            if x is True:
                x = 'all'
            elif x is False:
                x = 'none'
            return x
        enable = cleanup(enable)
        percent = cleanup(percent)
        use_last = cleanup(use_last)
        if use_last in ['cap', 'all'] and cap is not None:
            raise ValueError(self.perror('You can only specify cap or use_last'))
        if use_last in ['loss', 'all'] and loss is not None:
            raise ValueError(self.perror('You can only specify cap or use_last'))
        if enable is not None and enable != 'all':
            # These all return the measurement in the new configuration
            # Not reading it sometimes prevents the change to actually happen
            #  so use ask instead of write
            if enable == 'none':
                self.ask('REFerence ALL OFF')
            elif enable == 'cap':
                self.ask('REFerence LOSs OFF')
            elif enable == 'loss':
                self.ask('REFerence Cap OFF')
        if use_last != 'none':
            self.write('REFerence FEtch %s'%use_last)
        if cap is not None:
            self.write('REFerence POINT Cap %r'%cap)
        if loss is not None:
            self.write('REFerence POINT LOSs %r'%loss)
        if percent is not None:
            if percent in ['all', 'cap']:
                self.write('REFerence PERcent Cap ON')
            if percent in ['all', 'loss']:
                self.write('REFerence PERcent LOSs ON')
            if percent in ['none', 'cap']:
                self.write('REFerence PERcent LOSs OFF')
            if percent in ['none', 'loss']:
                self.write('REFerence PERcent Cap OFF')
        if enable is not None and enable != 'none':
            # These all return the measurement in the new configuration
            # Not reading it sometimes prevents the change to actually happen
            #  so use ask instead of write
            if enable == 'all':
                self.ask('REFerence ALL ON')
            elif enable == 'cap':
                self.ask('REFerence Cap ON')
            elif enable == 'loss':
                self.ask('REFerence LOSs ON')
        res = self.ask('SHow REFerence')
        # returns: 'OFF,OFF\n" ",0.00000000," ",0.00000000\nOFF,OFF'
        en, points_raw, percent = res.split('\n')
        ret = dict_improved()
        ret.update(zip(['cap_en', 'loss_en'], map(Choice_bool_OnOff, en.split(','))))
        zero_fmt = ChoiceMultiple(['cap_lbl', 'cap', 'loss_lbl', 'loss'], [quoted_string(), float, quoted_string(), float])
        ret.update(zero_fmt(points_raw).items())
        ret.update(zip(['cap_percent_en', 'loss_percent_en'], map(Choice_bool_OnOff, percent.split(','))))
        return ret

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = self._conf_helper('average', 'units', 'voltage_max', 'frequency', 'commutate', 'bias', 'cable')
        opts += ['zero=%r'%self.conf_zero()]
        opts += ['reference=%r'%self.conf_reference()]
        opts += self._conf_helper(options)
        return opts

    _data_format = ChoiceMultiple(['error', 'cap_lbl', 'cap', 'loss_lbl', 'loss', 'volt'], [int, quoted_string(), float, quoted_string(), float, float])
    @locked_calling
    def _read_data(self, force_req=True):
        """ using force_req will send a fetch request (it will show BUSY on the display)
            When in continuous you can use force_req=False to read the latest value (then wait for the next one.)
            It can also be 'async' to read available async data.
        """
        data = None
        if force_req == 'async':
            data = self._async_trig_current_data
            self._async_trig_current_data = None
        elif force_req:
            self.write('fetch')
        if data is None:
            data = self.read()
        return self._data_format(data)

    def continous(self, state=None):
        """ state can be True/False. If none it returns the current state """
        if state is not None:
            self.write('COntinuous %s'%Choice_bool_OnOff.tostr(state))
        else:
            data = self.ask('SHow COntinuous').split('\n')
            data = map(lambda x: x[0](x[1]), zip([float, int, int], data))
            return dict(zip(['interval', 'stop_count', 'count'], data))

    def _fetch_getdev(self):
        """ error contains cap uncertainty flag (>) if 1000 and loss uncertainty flag (>) if 2000.
            errors codes <100 are listed in Appendix B of manual (careful some numbers are off by 1).
        """
        if self._async_trig_current_data is not None:
            data  = self._read_data('async')
        else:
            data  = self._read_data(True)
        error = data.error
        if data.cap_lbl != ' ':
            if data.cap_lbl != '>':
                raise RuntimeError(self.perror('Unexpected cap label received'))
            error += 1000
        if data.loss_lbl != ' ':
            if data.loss_lbl != '>':
                raise RuntimeError(self.perror('Unexpected loss label received'))
            error += 2000
        return data.cap, data.loss, data.volt, error

    def _create_devs(self):
        # TODO: commands to program:
        #   calibrate? / store calibarate
        #   continuous interval, reset, total
        #   dev mode
        #   dev auto
        #   dev average
        #   dev bound
        #   dev fetch
        #   dev format
        #   dev margin
        #   dev point
        #   dev position
        #   dev rolloff
        #   dev span
        #   dev stream
        #   gpib  (to read this use: show gpib list)
        #     logger (to turn it off)
        #     scan to disable it.
        #   serial (to read this use: show serial list)
        #   test?
        # Note that deviation mode does not seem to work with AH2550A (probably only for AH2700)
        cold_k = np.array([.28,.29,.30,.33,.37,.44,.58,.82,1.2,1.8,3,5,9,17,34,68])
        cold_f = np.array([80,110,150,200,260,350,520,820,1300,2200,3900,7000,14000,27000,57000,120000])
        warm_k = np.array([.027, .033,.042,.058,.085,.12,.18])
        warm_f = np.array([11,23,42,75,130,230,400])
        cold_time = cold_k+cold_f/1e3 # at 1 kHz
        warm_time = warm_k+warm_f/1e3 # at 1 kHz
        time_doc = '%6s  %10s %10s\n'%('','cold', 'warm')
        for i in range(len(cold_time)):
            if i < len(warm_time):
                time_doc += '%6i: %10.3f %10.3f\n'%(i, cold_time[i], warm_time[i])
            else:
                time_doc += '%6i: %10.3f %10s\n'%(i, cold_time[i], 'n/a')
        # Note that for loss range the table is not clear if that f is in Hz or kHz but
        # comparing with table 4-3 it seems to be kHz for loss formula hence 12 uS.
        self.average = scpiDevice('AVerage', 'SHow AVerage', str_type=int, min=0, max=15,
                                  doc=u"""
The averaging time is seen in table 4-1 and A-1 of the manual.
Note cold start measurement are longer because they readjust all the relays.
Warm start only adjust the stages that don't use relays.
For cold start by using average >= 7 (but don't use continous because relays will age too quickly.)
There is a frequency dependence but for 1 kHz it is and C<0.165 µF (G<12 µS):
%s
                                  """%time_doc)
        self.bias = scpiDevice('BIas', 'SHow BIas', choices=ChoiceStrings('OFF', 'ILow', 'IHigh'),
                               doc=u'ihigh is 1 MΩ, ilow is 100 MΩ')
        self.units = scpiDevice('UNits', 'SHow UNits',
                                    choices=ChoiceStrings('NS', 'DS', 'KO', 'GO', 'JP'),
                                    doc=u"""
                                    Choices mean:
                                        NS: Nanosiemens (nS)
                                        DS: Dissipation factor or tanδ (dimensionless)
                                        KO: Series resistance in kilohms (kΩ)
                                        GO: Parallel resistance in gigohms (GΩ)
                                        JP: G/ω  (jpF)
                                    Note that series option (KO) means series capacitance is measured.
                                    Otherwise it is the parallel capacitance that is measured.
                                        """)
        self.voltage_max = scpiDevice('Voltage', 'SH Voltage', str_type=float, min=0.3e-3, max=15, setget=True,
                                      doc="""For optimal use select one of the following voltages: 15, 7.5, 3, 1.5, 0.75, 0.25, 0.1, 0.03, 0.01, 0.003, 0.001""")
        #self.frequency =  scpiDevice('FRequency', 'SHow FRequency', str_type=float, setget=True)
        self.frequency =  scpiDevice(getstr='SHow FRequency', str_type=float)
        self.commutate = scpiDevice('COMmutate', 'SHow COMmutate', choices=ChoiceStrings('OFF', 'LINERej', 'ASync'))
        self.cable = scpiDevice('CABle', 'SHow CABle',
                                choices=ChoiceMultiple(['length', 'R', 'L', 'C'], [(float, (0, 999.99)), (float, (0, 9999)), (float, (0, 99.99)), (float, (0, 999.9))], reading_sep='\n'),
                                doc=u"""Units are: length (m), R(mΩ/m), L(µH/m), C(pF/m)""")
        self._devwrap('fetch', autoinit=False, trig=True, multi=['cap', 'loss', 'volt', 'error'], graph=[0,1])
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval
        # This needs to be last to complete creation
        super(ah_2550a_capacitance_bridge, self)._create_devs()


#######################################################
##    Sumitomo F70 compressor
#######################################################

class sumitomo_dev(BaseDevice):
    def __init__(self, cmd_name, ret_types=None, **kwargs):
        super(sumitomo_dev, self).__init__(**kwargs)
        self.cmd_name = cmd_name
        self.ret_types = ret_types
        self._getdev_p = 'foo'
    def _getdev(self):
        ret_strs = self.instr.request('$'+self.cmd_name)
        ret_vals = [t(v) for t,v in zip(self.ret_types, ret_strs)]
        if len(self.ret_types) == 1:
            ret_vals = ret_vals[0]
        return ret_vals


@register_instrument('Sumitomo', 'F70')
class sumitomo_F70(visaInstrument):
    """
    This is to control a Sumitomo F70 compressor.
       Useful device:
           temperatures
           pressure_return
       Useful methods:
           compressor_start
           compressor_stop
           request
    WARNING: compressor ON/OFF frequency must be less than 6 times per hour and
             less than 24 times per day. The restart interval must be more than 3 minutes.
    """
    def __init__(self, visa_addr, **kwargs):
        cnsts = visa_wrap.constants
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == cnsts.InterfaceType.asrl:
            baud_rate = kwargs.pop('baud_rate', 9600)
            parity = kwargs.pop('parity', cnsts.Parity.none)
            data_bits = kwargs.pop('data_bits', 8)
            stop_bits = kwargs.pop('stop_bits', cnsts.StopBits.one)
            kwargs['baud_rate'] = baud_rate
            kwargs['parity'] = parity
            kwargs['data_bits'] = data_bits
            kwargs['stop_bits'] = stop_bits
        kwargs['write_termination'] = '\r'
        kwargs['read_termination'] = '\r'
        super(sumitomo_F70, self).__init__(visa_addr, **kwargs)
    def idn(self):
        res = self.request('$ID1')
        firmware = res[0]
        return 'Sumitomo,F70,no_serial,%s'%(firmware)
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('temperatures', 'pressures', 'operating_hours', 'status', options)
    def _operating_hours_getdev(self):
        res = self.request('$ID1')
        return float(res[1])
    def _crc16(self, mesg):
        crc = 0xffff
        for s in mesg:
            crc ^= ord(s)
            for bit in range(8):
                if crc&1:
                    crc >>= 1
                    crc ^= 0xa001
                else:
                    crc >>= 1
        return '%04X'%(crc&0xffff)
    def request(self, cmd):
        """ cmd is the full request, including the starting $ code.
            The CRC checksum will be added.
            It returns a list of strings of the answer split on the ','
        """
        mesg = cmd + self._crc16(cmd)
        resp = self.ask(mesg)
        resp_base = resp[:-4]
        resp_crc = resp[-4:]
        if self._crc16(resp_base) != resp_crc:
            raise RuntimeError(self.perror('Invalid crc16 in message.'))
        if resp_base == '$???,':
            raise RuntimeError(self.perror('Invalid or malformed message.'))
        if resp_base[:4] != cmd[:4]:
            raise RuntimeError(self.perror('Invalid start of message.'))
        answer = resp_base[5:].split(',') # 5: skips the first comma
        if answer[-1] == '': # This skips the last comma before the crc if needed.
            answer = answer[:-1]
        return answer
    def compressor_start(self):
        self.request('$ON1')
    def compressor_stop(self):
        self.request('$OFF')
    def reset_error(self):
        self.request('RS1')
    # Other cmds: $CHR=cold head run (when compressor off. Cold head can be stopped with compressor_stop or it stops after 30min.),
    #             $CHP=cold head pause (when compressor on), $POF=cold head pause off
    def _create_devs(self):
        self.temperatures = sumitomo_dev('TEA', [int]*4, multi=['helium_C', 'water_out_C', 'water_in_C', 'unused'],
                                         graph=[0, 1, 2],
                                         doc="In Celsius. [helium, water out, water in, unused].")
        self.temp_he = sumitomo_dev('TE1', [int], doc="In Celsius.")
        self.temp_water_out = sumitomo_dev('TE2', [int], doc="In Celsius.")
        self.temp_water_in = sumitomo_dev('TE3', [int], doc="In Celsius.")
        self.temp_4 = sumitomo_dev('TE4', [int], doc="In Celsius.")
        self.pressures = sumitomo_dev('PRA', [int]*2, multi=['return_psig', 'unused'], graph=[0],
                                      doc="In psig. [return pressure, unused_usually]")
        self.pressure_return = sumitomo_dev('PR1', [int], doc="In psig")
        self.pressure_2 = sumitomo_dev('PR2', [int], doc="In psig")
        self.status = sumitomo_dev('STA', [lambda x: int(x, 16)], doc=
                    """
                    It is a bit field.
                    bit 15 (32768): 0=Configuration 1, 1=Configuration 2
                    bit 12-14: unused
                    bit 9-11: Operating state
                           0 = Local Off, 1 = Local On, 2 = Remote Off, 3= Remote On
                           4 = Cold Head Run, 5 = Cold Head Pause, 6 = Fault Off, 7 = Oil Fault Off
                    bit 8 (256): Solenoid on
                    bit 7 (128): Pressure alarm
                    bit 6 (64): Oil level alarm
                    bit 5 (32): Water Flow alarm
                    bit 4 (16): Water Temperature alarm
                    bit 3 (8): Helium temperature alarm
                    bit 2 (4): Phase Sequence/fuse alarm
                    bit 1 (2): Motor temperature alarm
                    bit 0 (1): System on
                    """)
        self._devwrap('operating_hours')
        # This needs to be last to complete creation
        super(sumitomo_F70, self)._create_devs()


#######################################################
##    Dummy instrument
#######################################################

@register_instrument('pyHegel_Instrument', 'dummy', '1.0')
class dummy(BaseInstrument):
    """ This is a dummy device (just in memory) to use for testing.
        There are 5 devices: volt, current, incr, rand and other
          incr is a device that is incremented by 1 after every get
          rand returns a random value from a normal distribution
        Both incr and rand wait the time set in the wait attribute
        before returning from get. The wait attribute defaults to 0.1
    """
    def init(self, full=False):
        self.incr_val = 0
        self.wait = .1
    def idn(self):
        return 'pyHegel_Instrument,dummy,00000,1.0'
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('volt', 'current', 'other', options)
    def _incr_getdev(self):
        ret = self.incr_val
        self.incr_val += 1
        wait(self.wait)
        return ret
    def _incr_setdev(self, val):
        self.incr_val = val
    #incr3 = wrapDevice(_incr_setdev, _incr_getdev)
    #incr2 = wrapDevice(getdev=_incr_getdev)
    def _rand_getdev(self):
        wait(self.wait)
        return random.normalvariate(0,1.)
    def _create_devs(self):
        self.volt = MemoryDevice(0., doc='This is a memory voltage, a float')
        self.current = MemoryDevice(1., doc='This is a memory current, a float')
        self.other = MemoryDevice(autoinit=False, doc='This takes a boolean')
        #self.freq = scpiDevice('freq', str_type=float)
        self._devwrap('rand', doc='This returns a random value. There is not set.', trig=True)
        self._devwrap('incr')
        self.alias = self.current
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


#######################################################
##    Loop instrument
#######################################################

@register_instrument('pyHegel_Instrument', 'loop', '1.0')
class loop(BaseInstrument):
    """
        This is a dummy instrument (just in memory) to use for
        looping/repeating (multi_sweep).
        There are 5 devices: loop1 to loop5
    """
    def idn(self):
        return 'pyHegel_Instrument,dummy,00000,1.0'
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('loop1', 'loop2',  'loop3', 'loop4', 'loop5', options)
    def _create_devs(self):
        self.loop1 = MemoryDevice(0.)
        self.loop2 = MemoryDevice(0.)
        self.loop3 = MemoryDevice(0.)
        self.loop4 = MemoryDevice(0.)
        self.loop5 = MemoryDevice(0.)
        self.alias = self.loop1
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
