# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2011-2015  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from ..instruments_base import BaseInstrument, visaInstrument, visaInstrumentAsync,\
                            BaseDevice, scpiDevice, MemoryDevice, Dict_SubDevice, ReadvalDev,\
                            ChoiceBase, ChoiceMultiple, ChoiceMultipleDep, ChoiceSimpleMap,\
                            ChoiceStrings, ChoiceIndex,\
                            make_choice_list, _fromstr_helper,\
                            decode_float64, visa_wrap, locked_calling,\
                            Lock_Extra, Lock_Instruments, _sleep_signal_context_manager, wait,\
                            release_lock_context, mainStatusLine, quoted_string, Choice_bool_OnOff
from ..types import dict_improved
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

from .logical import FunctionDevice, ScalingDevice

# for pfeiffer
import threading
import weakref

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
##    Stanford Research SR830 Lock-in Amplifier
#######################################################

#@register_instrument('Stanford_Research_Systems', 'SR830', 'ver1.07 ')
@register_instrument('Stanford_Research_Systems', 'SR830', alias='SR830 LIA')
class sr830_lia(visaInstrument):
    """
    Don't forget to set the async_wait to some usefull values.
     might do set(sr1.async_wait, 1.)
    when using 24dB/oct, 100ms filter.

    You can use find_n_time and find_fraction to set the time.
    For example: set(sr1.async_wait, sr1.find_n_time(.99,sec=True))

    To read more than one channel at a time use readval/fetch(snap)
    Otherwise you can use x, y, t, theta
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
    def _snap_getdev(self, sel=[1,2]):
        # sel must be a list
        self._check_snapsel(sel)
        sel = map(str, sel)
        return decode_float64(self.ask('snap? '+','.join(sel)))
    def _snap_getformat(self, sel=[1,2], **kwarg):
        self._check_snapsel(sel)
        headers = [ self._snap_type[i] for i in sel]
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
    def _current_config(self, dev_obj=None, options={}):
        #base = ['async_delay=%r'%self.async_delay]
        return self._conf_helper('async_delay','async_wait', 'freq', 'sens', 'srclvl', 'harm', 'phase', 'timeconstant', 'filter_slope',
                                 'sync_filter', 'reserve_mode',
                                 'offset_expand_x', 'offset_expand_y', 'offset_expand_r',
                                 'input_conf', 'grounded_conf', 'dc_coupled_conf', 'linefilter_conf',
                                 'auxout1', 'auxout2', 'auxout3', 'auxout4', options)
    def _create_devs(self):
        self.freq = scpiDevice('freq', str_type=float, setget=True, min=0.001, max=102e3)
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
        self.status_byte = scpiDevice(getstr='LIAS?', str_type=int)
        self._devwrap('snap', trig=True, doc="""
            This device can be called snap or fetch (they are both the same)
            This device obtains simultaneous readings from many inputs.
            To select the inputs, use the parameter
             sel
            which is [1,2] by default.
            The numbers are taken from the following dictionnary:
                %r
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
##    Lakeshore 325 Temperature controller
#######################################################

#@register_instrument('LSCI', 'MODEL325', '1.7/1.1')
@register_instrument('LSCI', 'MODEL325')
class lakeshore_325(visaInstrument):
    """
       Temperature controller
       Useful device:
           sa
           sb
           ta
           tb
           status_a
           status_b
           fetch
       s? and t? return the sensor or kelvin value of a certain channel
       status_? returns the status of the channel
       fetch allows to read all channels
    """
    def _fetch_helper(self, ch=None):
        if ch is None:
            ch = self.enabled_list.getcache()
        if not isinstance(ch, (list, ChoiceBase)):
            ch = [ch]
        return ch
    def _fetch_getformat(self, **kwarg):
        ch = kwarg.get('ch', None)
        ch = self._fetch_helper(ch)
        multi = []
        graph = []
        for i, c in enumerate(ch):
            graph.append(2*i)
            multi.extend([c+'_T', c+'_S'])
        fmt = self.fetch._format
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_getdev(self, ch=None):
        """
        reads thermometers temperature and their sensor values.
        option ch: can be a single channel or a list of channels.
                   by default (None), all active channels are used
                   possible channels names are:
                       A, B
        """
        ch = self._fetch_helper(ch)
        ret = []
        for c in ch:
            if c == 'A':
                ret.append(self.ta.get())
                ret.append(self.sa.get())
            elif c == 'B':
                ret.append(self.tb.get())
                ret.append(self.sb.get())
            else:
                raise ValueError("Invalid selection for ch. If it is None, check that enabled_list is a list with 'A' and/or 'B'")
        return ret
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('sp', options)
    def _create_devs(self):
        self.crdg = scpiDevice(getstr='CRDG? A', str_type=float)
        self.enabled_list = MemoryDevice(['A', 'B'])
        self.thermocouple = scpiDevice(getstr='TEMP?', str_type=float)
        self.ta = scpiDevice(getstr='KRDG? A', str_type=float) #in Kelvin
        self.tb = scpiDevice(getstr='KRDG? B', str_type=float) #in Kelvin
        self.sa = scpiDevice(getstr='SRDG? A', str_type=float) #in sensor unit: Ohm, V or mV
        self.sb = scpiDevice(getstr='SRDG? B', str_type=float) #in sensor unit
        self.status_a = scpiDevice(getstr='RDGST? A', str_type=int) #flags 1(0)=invalid, 16(4)=temp underrange,
                               #32(5)=temp overrange, 64(6)=sensor under (<0), 128(7)=sensor overrange
                               # 000 = valid
        self.status_b = scpiDevice(getstr='RDGST? b', str_type=int)
        self.htr = scpiDevice(getstr='HTR?', str_type=float) #heater out in %
        self.sp = scpiDevice(setstr='SETP 1,', getstr='SETP? 1', str_type=float)
        self._devwrap('fetch', autoinit=False)
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


#######################################################
##    Lakeshore 340 Temperature controller
#######################################################

register_idn_alias('Lake Shore Cryotronics', 'LSCI')

#@register_instrument('LSCI', 'MODEL340', '061407')
@register_instrument('LSCI', 'MODEL340')
class lakeshore_340(visaInstrument):
    """
       Temperature controller used for He3 system
       Useful device:
           s
           t
           fetch
           status_ch
           current_ch
       s and t return the sensor or kelvin value of a certain channel
       which defaults to current_ch
       status_ch returns the status of ch
       fetch allows to read all channels
    """
    def _current_config(self, dev_obj=None, options={}):
        if dev_obj == self.fetch:
            old_ch = self.current_ch.getcache()
            ch = options.get('ch', None)
            ch = self._fetch_helper(ch)
            ch_list = []
            in_set = []
            in_crv = []
            in_type = []
            for c in ch:
                ch_list.append(c)
                in_set.append(self.input_set.get(ch=c))
                in_crv.append(self.input_crv.get())
                in_type.append(self.input_type.get())
            self.current_ch.set(old_ch)
            base = ['current_ch=%r'%ch_list, 'input_set=%r'%in_set,
                    'input_crv=%r'%in_crv, 'input_type=%r'%in_type]
        else:
            base = self._conf_helper('current_ch', 'input_set', 'input_crv', 'input_type')
        base += self._conf_helper('current_loop', 'sp', 'pid', options)
        return base
    def _enabled_list_getdev(self):
        old_ch = self.current_ch.getcache()
        ret = []
        for c in self.current_ch.choices:
            d = self.input_set.get(ch=c)
            if d['enabled']:
                ret.append(c)
        self.current_ch.set(old_ch)
        return ret
    def _fetch_helper(self, ch=None):
        if ch is None:
            ch = self.enabled_list.getcache()
        if not isinstance(ch, (list, ChoiceBase)):
            ch = [ch]
        return ch
    def _fetch_getformat(self, **kwarg):
        ch = kwarg.get('ch', None)
        ch = self._fetch_helper(ch)
        multi = []
        graph = []
        for i, c in enumerate(ch):
            graph.append(2*i)
            multi.extend([c+'_T', c+'_S'])
        fmt = self.fetch._format
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_getdev(self, ch=None):
        """
        reads thermometers temperature and their sensor values.
        option ch: can be a single channel or a list of channels.
                   by default (None), all active channels are used
                   possible channels names are:
                       A, B, C, D, C1, C2, C3, C4, D1, D2, D3, D4
                   (depending on installed options)
        """
        old_ch = self.current_ch.getcache()
        ch = self._fetch_helper(ch)
        ret = []
        for c in ch:
            ret.append(self.t.get(ch=c))
            ret.append(self.s.get())
        self.current_ch.set(old_ch)
        return ret
    def _create_devs(self):
        rev_str = self.ask('rev?')
        conv = ChoiceMultiple(['master_rev_date', 'master_rev_num', 'master_serial_num', 'sw1', 'input_rev_date',
                         'input_rev_num', 'option_id', 'option_rev_date', 'option_rev_num'], fmts=str)
        rev_dic = conv(rev_str)
        ch_Base = ChoiceStrings('A', 'B')
        ch_3462_3464 = ChoiceStrings('A', 'B', 'C', 'D') # 3462=2 other channels, 3464=2 thermocouple
        ch_3468 = ChoiceStrings('A', 'B', 'C1', 'C2', 'C3', 'C4', 'D1', 'D2','D3','D4') # 2 groups of 4, limited rate, limited current sources (10u or 1m)
        ch_3465 = ChoiceStrings('A', 'B', 'C') # single capacitance
        ch_opt = {'3462':ch_3462_3464, '3464':ch_3462_3464, '3468':ch_3468, '3465':ch_3465}
        ch_opt_sel = ch_opt.get(rev_dic['option_id'], ch_Base)
        self.current_ch = MemoryDevice('A', choices=ch_opt_sel)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.t = devChOption(getstr='KRDG? {ch}', str_type=float, doc='Return the temperature in Kelvin for the selected sensor(ch)')
        self.s = devChOption(getstr='SRDG? {ch}', str_type=float, doc='Return the sensor value in Ohm, V(diode), mV (thermocouple), nF (for capacitance)  for the selected sensor(ch)')
        self.status_ch = devChOption(getstr='RDGST? {ch}', str_type=int) #flags 1(0)=invalid, 16(4)=temp underrange,
                               #32(5)=temp overrange, 64(6)=sensor under (<0), 128(7)=sensor overrange
                               # 000 = valid
        self.input_set = devChOption('INSET {ch},{val}', 'INSET? {ch}', choices=ChoiceMultiple(['enabled', 'compens'],[bool, int]))
        self.input_crv = devChOption('INCRV {ch},{val}', 'INCRV? {ch}', str_type=int)
        self.input_type = devChOption('INTYPE {ch},{val}', 'INTYPE? {ch}',
                                      choices=ChoiceMultiple(['type', 'units', 'coeff', 'exc', 'range']))
        self.input_filter = devChOption('FILTER {ch},{val}', 'FILTER? {ch}',
                                      choices=ChoiceMultiple(['filter_en', 'n_points', 'window'], [bool, int, int]))
        self.current_loop = MemoryDevice(1, choices=[1, 2])
        def devLoopOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(loop=self.current_loop)
            app = kwarg.pop('options_apply', ['loop'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.pid = devLoopOption('PID {loop},{val}', 'PID? {loop}',
                                 choices=ChoiceMultiple(['P', 'I', 'D'], float))
        self.htr = scpiDevice(getstr='HTR?', str_type=float) #heater out in %
        self.sp = devLoopOption(setstr='SETP {loop},{val}', getstr='SETP? {loop}', str_type=float)
        self._devwrap('enabled_list')
        self._devwrap('fetch', autoinit=False)
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

#######################################################
##    Lakeshore 224 Temperature monitor
#######################################################
class quoted_name(object):
    def __call__(self, read_str):
        # the instruments returns a 15 character string with spaces if unused
        return read_str.rstrip()
    def tostr(self, input_str):
        if '"' in input_str:
            raise ValueError, 'The given string already contains a quote :":'
        return '"'+input_str[:15]+'"'

#@register_instrument('LSCI', 'MODEL224', '1.0')
@register_instrument('LSCI', 'MODEL224')
class lakeshore_224(lakeshore_340):
    """
       Temperature monitor
       Useful device:
           s
           t
           fetch
           status_ch
           current_ch
       s and t return the sensor or kelvin value of a certain channel
       which defaults to current_ch
       status_ch returns the status of ch
       fetch allows to read all channels (which is the alias)

       Note: The device USB is actually a serial to USB port. Therfore it
             shows on the computer as a serial connection (once the driver
             is installed, which could happen automatically.)
    """
    def init(self, full=False):
        if full:
            if self.visa.is_serial():
                self.visa.baud_rate = 57600
                self.visa.parity = visa_wrap.constants.Parity.odd
                self.visa.data_bits = 7
            if self.visa.is_serial():
                self._write_write_wait = 0.100
            else: # GPIB, LAN: This is unchecked but should be ok. Shorter time might be better...
                self._write_write_wait = 0.050
    def _current_config(self, dev_obj=None, options={}):
        if dev_obj == self.fetch:
            old_ch = self.current_ch.getcache()
            ch = options.get('ch', None)
            ch = self._fetch_helper(ch)
            ch_list = []
            in_set = []
            in_crv = []
            in_type = []
            in_diode = []
            for c in ch:
                ch_list.append(c)
                in_crv.append(self.input_crv.get(ch=c))
                in_type.append(self.input_type.get())
                in_diode.append(self.input_diode_current.get())
            self.current_ch.set(old_ch)
            base = ['current_ch=%r'%ch_list, 'input_crv=%r'%in_crv, 'input_type=%r'%in_type, 'input_diode_current=%r'%in_diode]
        else:
            base = self._conf_helper('current_ch', 'input_crv', 'input_type', 'input_diode_current')
        base += self._conf_helper(options)
        return base
    def _enabled_list_getdev(self):
        old_ch = self.current_ch.getcache()
        ret = []
        for c in self.current_ch.choices:
            d = self.input_type.get(ch=c)
            if d['type'] != 'disabled':
                ret.append(c)
        self.current_ch.set(old_ch)
        return ret
    def _get_esr(self):
        return int(self.ask('*esr?'))
    def get_error(self):
        esr = self._get_esr()
        ret = ''
        if esr&0x80:
            ret += 'Power on. '
        if esr&0x20:
            ret += 'Command Error. '
        if esr&0x10:
            ret += 'Execution Error. '
        if esr&0x04:
            ret += 'Query Error (output queue full). '
        if esr&0x01:
            ret += 'OPC received.'
        if ret == '':
            ret = 'No Error.'
        return ret
    def _create_devs(self):
        ch_opt_sel = ['A', 'B', 'C1', 'C2', 'C3', 'C4', 'C5', 'D1', 'D2', 'D3', 'D4', 'D5']
        self.current_ch = MemoryDevice('A', choices=ch_opt_sel)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.t = devChOption(getstr='KRDG? {ch}', str_type=float, doc='Return the temperature in Kelvin for the selected sensor(ch)')
        self.s = devChOption(getstr='SRDG? {ch}', str_type=float, doc='Return the sensor value in Ohm, V(diode), mV (thermocouple), nF (for capacitance)  for the selected sensor(ch)')
        self.status_ch = devChOption(getstr='RDGST? {ch}', str_type=int) #flags 1(0)=invalid, 16(4)=temp underrange,
                               #32(5)=temp overrange, 64(6)=sensor under (<0), 128(7)=sensor overrange
                               # 000 = valid
        self.input_crv = devChOption('INCRV {ch},{val}', 'INCRV? {ch}', str_type=int)
        intypes = ChoiceIndex({0:'disabled', 1:'diode', 2:'PTC_RTD', 3:'NTC_RTD'})
        units = ChoiceIndex({1:'Kelvin', 2:'Celsius', 3:'Sensor'})
        ranges_disabled = ChoiceIndex({0:0})
        ranges_diode = ChoiceIndex({0:2.5, 1:10}) # V
        ranges_PTC = ChoiceIndex(make_choice_list([1, 3], 1, 4)[:-1], normalize=True) # Ohm
        ranges_NTC = ChoiceIndex(make_choice_list([1, 3], 1, 5)[:-1], normalize=True) # Ohm
        type_ranges = ChoiceMultipleDep('type', {'disabled':ranges_disabled, 'diode':ranges_diode, 'PTC_RTD':ranges_PTC, 'NTC_RTD':ranges_NTC})
        self.input_type = devChOption('INTYPE {ch},{val}', 'INTYPE? {ch}',
                                      allow_kw_as_dict=True, allow_missing_dict=True,
                                      choices=ChoiceMultiple(['type', 'autorange_en', 'range', 'compensation_en', 'units'], [intypes, bool, type_ranges, bool, units]))
        self.input_filter = devChOption('FILTER {ch},{val}', 'FILTER? {ch}',
                                      allow_kw_as_dict=True, allow_missing_dict=True,
                                      choices=ChoiceMultiple(['filter_en', 'n_points', 'window'], [bool, int, int]))
        self.input_diode_current = devChOption('DIOCUR {ch},{val}', 'DIOCUR? {ch}', choices=ChoiceIndex({0:10e-6, 1:1e-3}), doc=
                """Only valid when input is a diode type. Options are in Amps.
                   Default of instrument is 10 uA (used after every change of sensor type).""")
        self.input_name = devChOption('INNAME {ch},{val}', 'INNAME? {ch}', str_type=quoted_name())
        self._devwrap('enabled_list')
        self._devwrap('fetch', autoinit=False)
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(lakeshore_340, self)._create_devs()
    def disable_ch(self, ch):
        """
        This method set a channel to disabled.
        Note that the settings of the channel are lost. To reenable use
          input_type with at least options autorange_en (PTC, NTC), range (allways, any value is allowed if autorange is enabled)
                     compensation_en (PTC, NTC)
          input_crv
          input_diode_current (for diodes if want 1 mA)
        """
        self.input_type.set(ch=ch, type='disabled', range=0)

#######################################################
##    Lakeshore 370 Temperature controller
#######################################################

#@register_instrument('LSCI', 'MODEL370', '04102008')
@register_instrument('LSCI', 'MODEL370')
class lakeshore_370(visaInstrument):
    """
       Temperature controller used for dilu system
       Useful device:
           s
           t
           fetch
           status_ch
           current_ch
           pid
           still
           still_raw
       s and t return the sensor(Ohm) or kelvin value of a certain channel
       which defaults to current_ch
       status_ch returns the status of ch
       fetch allows to read all channels

       Notes about T control:
           - the htr values is either in W (assuming the resistance is correctly
           programmed) or % of current full scale. Therefore we have
           W = ((%/100)*Ifullscale)**2 * Rheater
           - The feedback formula is:
               Iheater = Imax * P * [e + I integral(e dt) + D de/dt]
               with e = 2*log10(Rmeas/Rsetpoint)
                 at least for sensors calibrated as log scale
           - Therefore increasing currrent scale by x3.16 (power by x10)
             would require decreasing P by x3.16
       Notes about timing:
           - takes 10 readings / s, has a 200 ms hardware input filter
           - the digital filter is a linear average
           - Hardware settling time is about 1s, 2-3s for range change
             (scan channel change)
           - Time to a stable reading after channel change:
               max(hardware_settling, pause) + digital_filter
             so if pause it too small, it will take hardware settling time
             to get first reading used for the filter. Otherwise it will be
             the pause time (pause and hardware settling don't add)
           - When under PID control:
               The control channel is measured between all the other channels
               (toggles between control channel and non control channels).
               channel switch time is the same but the dwell times are changed
               about 5s for control and 1s for others (non-control).
               These are fixed (see  Manual 4.11.8.1 Reading Sequence p 4-23)
               There does not seem to be a way to change these dwell times.
    """
    def __init__(self, visa_addr, still_res=120., still_full_res=136.4, **kwarg):
        """
        still_res is the still heater resistance
        still_full_res is the still heater resistance with the wire resistance
                       included (the 2 wire resistance seen from outside the fridge)
        They are both used fot the still device
        """
        self._still_res = still_res
        self._still_full_res = still_full_res
        super(lakeshore_370, self).__init__(visa_addr, **kwarg)
        self._data_valid_last_ch = 0
        self._data_valid_last_t = 0.
        self._data_valid_last_start = 0., [0, False]
    def init(self, full=False):
        if full:
            if self.visa.is_serial():
                # we need to set this before any writes.
                self._write_write_wait = 0.100
                self.visa.parity = visa_wrap.constants.Parity.odd
                self.visa.data_bits = 7
                #self.visa.term_chars = '\r\n'
                self.write('*ESE 255') # needed for get_error
                self.write('*sre 4') # neede for _data_valid
            else: # GPIB
                self._write_write_wait = 0.050
        super(lakeshore_370, self).init(full=full)
    def _get_esr(self):
        return int(self.ask('*esr?'))
    def get_error(self):
        esr = self._get_esr()
        ret = ''
        if esr&0x80:
            ret += 'Power on. '
        if esr&0x20:
            ret += 'Command Error. '
        if esr&0x10:
            ret += 'Execution Error. '
        if esr&0x04:
            ret += 'Query Error (output queue full). '
        if esr&0x01:
            ret += 'OPC received.'
        if ret == '':
            ret = 'No Error.'
        return ret
    def _current_config(self, dev_obj=None, options={}):
        if dev_obj == self.fetch:
            old_ch = self.current_ch.getcache()
            ch = options.get('ch', None)
            ch = self._fetch_helper(ch)
            ch_list = []
            in_set = []
            in_filter = []
            in_meas = []
            for c in ch:
                ch_list.append(c)
                in_set.append(self.input_set.get(ch=c))
                in_filter.append(self.input_filter.get())
                in_meas.append(self.input_meas.get())
            self.current_ch.set(old_ch)
            base = ['current_ch=%r'%ch_list, 'input_set=%r'%in_set,
                    'input_filter=%r'%in_filter, 'input_meas=%r'%in_meas]
        else:
            base = self._conf_helper('current_ch', 'input_set', 'input_filter', 'input_meas')
        base += self._conf_helper('sp', 'pid', 'manual_out_raw', 'still', 'heater_range',
                                  'control_mode', 'control_setup', 'control_ramp', options)
        return base
    def _enabled_list_getdev(self):
        old_ch = self.current_ch.getcache()
        ret = []
        for c in self.current_ch.choices:
            d = self.input_set.get(ch=c)
            if d['enabled']:
                ret.append(c)
        self.current_ch.set(old_ch)
        return ret
    def _fetch_helper(self, ch=None):
        if ch is None:
            ch = self.enabled_list.getcache()
        if not isinstance(ch, (list, ChoiceBase)):
            ch = [ch]
        return ch
    def _fetch_getformat(self, **kwarg):
        ch = kwarg.get('ch', None)
        ch = self._fetch_helper(ch)
        multi = []
        graph = []
        for i, c in enumerate(ch):
            graph.append(2*i)
            multi.extend([str(c)+'_T', str(c)+'_S'])
        fmt = self.fetch._format
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch, **kwarg)
    @locked_calling
    def _data_valid_start(self):
        """ returns channel and autoscan_en """
        to = time.time()
        if to - self._data_valid_last_start[0] < 0.02:
            # nothing has changed since last call so speedup by reusing result
            return self._data_valid_last_start[1]
        # the only way to clear the status when using serial is with *cls
        # and it is faster to also ask a question (less wait time later)
        result = self.ask('*cls;scan?').split(',')
        ret = int(result[0]), bool(int(result[1]))
        self._data_valid_last_start = time.time(), ret
        return ret
    def _data_valid(self):
        """
        waits until we have valid data
        returns the current scan channel when done
        """
        with self._lock_instrument: # protect object variables
            to = time.time()
            start_ch, foo = self._data_valid_start()
            if to-self._data_valid_last_t < 1. and self._data_valid_last_ch == start_ch:
                # we should still be having good data, skip the wait
                self._data_valid_last_t = to
                return start_ch
        while not self.read_status_byte()&4:
            wait(.02)
        after_ch, foo = self._data_valid_start()
        tf = time.time()
        if tf-to > 1.: # we waited after a channel change
            ch = after_ch
        else:  # the channel is the same or it got changed just after our wait.
            ch = start_ch
        with self._lock_instrument: # protect object variables
            self._data_valid_last_t = tf
            self._data_valid_last_ch = ch
        return ch
    def _fetch_getdev(self, ch=None, lastval=False, wait_new=False):
        """
        Optional parameter:
            ch: To select which channels to read. Default to all the enabled
                ones. Otherwise ch=4 selects only channel 4 and
                ch=[3,5] selects channels 3 and 5.
          lastval: When enabled, and when scanning, waits and picks the last value
                   read from that channel before switching
          wait_new: only returns values the are fresh. If a channel is never scanned
                    it will hang
        lastval and wait_new do something only when scanning is enabled.
        You can enable both at the same time.

        For each channels, two values are returned. The tempereture in Kelvin
        and the sensor value in Ohm.
        """
        old_ch = self.current_ch.getcache()
        ch = self._fetch_helper(ch)
        nmeas = len(ch) # the number of measures to do
        ret = [None] * nmeas*2
        ich = list(enumerate(ch)) # this makes a list of (i,c)
        ch2i = {c:i for i,c in ich} # maps channel # to index
        # for lastval only:
        # We assume the scanning is slower than getting all the values
        # so we first get all channel except the active one.
        # This should be ok since the first seconds after a channel change
        # returns the previous value and the sequence order is not too critical
        # since we have seconds to read all other channels
        if lastval or wait_new:
            # use _data_valid_start here because it can save some time over
            # self.scan.get()
            start_scan_ch, autoscan_en = self._data_valid_start()
            current_ch = start_scan_ch
            if not autoscan_en:
                lastval = False
                wait_new = False
        if lastval or wait_new:
            # They both introduce delays so we unlock to allow other threads
            # to use this device. The reset of the code has been checked to
            # be thread safe
            # TODO better unlockin/locking: This way, if the code is interrupted
            #             by KeyboardInterrupt it will produce an unlocking
            #             error in the previous with handler (the re-acquire)
            #             is not performed.
            self._lock_release()
        skip = False
        indx = 0
        while nmeas != 0:
            if wait_new and lastval:
                while True:
                    ch, foo = self._data_valid_start()
                    if ch == current_ch: # we wait until the channel changes
                        wait(.2)
                    else:
                        break
                if current_ch not in ch2i:
                    current_ch = ch
                    continue
                i, c = ch2i[current_ch], current_ch
                current_ch = ch
                # In PID control we will repeat the control channel multiple times
                # So check that. We will return the last one only
                if ret[i*2] is None:
                    nmeas -= 1
            elif wait_new: # only
                while True:
                    current_ch = self._data_valid()
                    if current_ch not in ch2i: # we want valid data for this channel
                        wait(.5)
                    else:
                        i, c = ch2i.pop(current_ch), current_ch
                        nmeas -= 1
                        break
            else: # lastval only or nothing
                i, c = ich[indx]
                indx += 1
                nmeas -= 1
                if lastval and c == start_scan_ch:
                    skip = True
                    continue
            ret[i*2] = self.t.get(ch=c)
            ret[i*2+1] = self.s.get(ch=c) # repeating channels means we don't need the lock
        if skip and lastval:
            while True:
                ch, foo = self._data_valid_start()
                if ch != start_scan_ch:
                    break
                wait(.1)
            i = ch2i[start_scan_ch]
            ret[i*2] = self.t.get(ch=start_scan_ch)
            ret[i*2+1] = self.s.get(ch=start_scan_ch)
        if lastval or wait_new:
            # we need to reacquire the lock before leaving
            self._lock_acquire()
        self.current_ch.set(old_ch)
        return ret
    def _htr_getdev(self):
        """Always in W, using control_setup heater_Ohms if necessary."""
        csetup = self.control_setup.getcache()
        htr = self.htr_raw.get()
        if csetup.output_display == 'power':
            return htr
        else:
            rng = self.heater_range.get()
            return (htr/100.*rng)**2 * csetup.heater_Ohms
    def _create_devs(self):
        ch_opt_sel = range(1, 17)
        self.current_ch = MemoryDevice(1, choices=ch_opt_sel)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.t = devChOption(getstr='RDGK? {ch}', str_type=float, doc='Return the temperature in Kelvin for the selected sensor(ch)')
        self.s = devChOption(getstr='RDGR? {ch}', str_type=float, doc='Return the sensor value in Ohm for the selected sensor(ch)')
        self.status_ch = devChOption(getstr='RDGST? {ch}', str_type=int) #flags 1(0)=CS OVL, 2(1)=VCM OVL, 4(2)=VMIX OVL, 8(3)=VDIF OVL
                               #16(4)=R. OVER, 32(5)=R. UNDER, 64(6)=T. OVER, 128(7)=T. UNDER
                               # 000 = valid
        tempco = ChoiceIndex({1:'negative', 2:'positive'})
        self.input_set = devChOption('INSET {ch},{val}', 'INSET? {ch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                     choices=ChoiceMultiple(['enabled', 'dwell', 'pause', 'curvno', 'tempco'],
                                                       [bool, (int, (1, 200)), (int, (3, 200)), (int, (0, 20)), tempco]))
        self.input_filter = devChOption('FILTER {ch},{val}', 'FILTER? {ch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                      choices=ChoiceMultiple(['filter_en', 'settle_time', 'window'], [bool, (int, (1, 200)), (int, (1, 80))]))
        res_ranges = ChoiceIndex(make_choice_list([2, 6.32], -3, 7), offset=1, normalize=True)
        cur_ranges = ChoiceIndex(make_choice_list([1, 3.16], -12, -2), offset=1, normalize=True)
        volt_ranges = ChoiceIndex(make_choice_list([2, 6.32], -6, -1), offset=1, normalize=True)
        curvolt_ranges = ChoiceMultipleDep('exc_mode', {'voltage':volt_ranges, 'current':cur_ranges})
        self.input_meas = devChOption('RDGRNG {ch},{val}', 'RDGRNG? {ch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                     choices=ChoiceMultiple(['exc_mode', 'exc_range', 'range', 'autorange_en', 'excitation_disabled'],
                                                       [ChoiceIndex(['voltage', 'current']), curvolt_ranges, res_ranges, bool, bool]))
        # scan returns the channel currently being read
        #  it is the channel that flashes, not necessarily the one after scan on the
        #  display (they differ when temperature control is enabled, the instrument goes back
        #  to the control channel after all readings. This command follows that.)
        self.scan = scpiDevice('SCAN', allow_kw_as_dict=True, allow_missing_dict=True,
                               choices=ChoiceMultiple(['ch', 'autoscan_en'], [int, bool]))
        #self.current_loop = MemoryDevice(1, choices=[1, 2])
        #def devLoopOption(*arg, **kwarg):
        #    options = kwarg.pop('options', {}).copy()
        #    options.update(loop=self.current_loop)
        #    app = kwarg.pop('options_apply', ['loop'])
        #    kwarg.update(options=options, options_apply=app)
        #    return scpiDevice(*arg, **kwarg)
        #self.pid = scpiDevice('PID', choices=ChoiceMultiple(['P', 'I', 'D'], float))
        pid_ch = ChoiceMultiple(['P', 'I', 'D'], [(float, (0.001, 1000)), (float,(0, 10000)), (float, (0, 2500))])
        self.pid = scpiDevice('PID', allow_kw_as_dict=True, allow_missing_dict=True, choices=pid_ch, multi=pid_ch.field_names, doc="You can use as set(tc3.pid, P=21)")
        self.pid_P = Dict_SubDevice(self.pid, 'P', force_default=False)
        self.pid_I = Dict_SubDevice(self.pid, 'I', force_default=False)
        self.pid_D = Dict_SubDevice(self.pid, 'D', force_default=False)
        self.manual_out_raw = scpiDevice('MOUT', str_type=float,
                                  doc='manual heater output in % of Imax or in W depending on control_setup output_display option')
        self.htr_raw = scpiDevice(getstr='HTR?', str_type=float,
                                  doc='heater output in % of Imax or in W depending on control_setup output_display option')
        self._devwrap('htr')
        cmodes = ChoiceIndex({1:'pid', 2:'zone', 3:'open_loop', 4:'off'})
        self.control_mode = scpiDevice('CMODE', choices=cmodes)
        # heater range of 0 means off
        htrrng_dict = {0:0., 1:31.6e-6, 2:100e-6, 3:316e-6,
                       4:1.e-3, 5:3.16e-3, 6:10e-3, 7:31.6e-3, 8:100e-3}
        htrrng = ChoiceIndex(htrrng_dict)
        self.heater_range = scpiDevice('HTRRNG', choices=htrrng)
        csetup_htrrng_dict = htrrng_dict.copy()
        del csetup_htrrng_dict[0]
        csetup_htrrng = ChoiceIndex(csetup_htrrng_dict)
        csetup = ChoiceMultiple(['channel','filter_en', 'units', 'delay', 'output_display',
                           'heater_limit', 'heater_Ohms'],
                          [(int, (1, 16)), bool, ChoiceIndex({1:'kelvin', 2:'ohm'}), (int, (1, 255)),
                           ChoiceIndex({1:'current', 2:'power'}), csetup_htrrng, (float, (1, 1e5))])
        self.control_setup = scpiDevice('CSET', choices=csetup, allow_kw_as_dict=True, allow_missing_dict=True)
        self.control_setup_heater_limit = Dict_SubDevice(self.control_setup, 'heater_limit', force_default=False)
        self.control_ramp = scpiDevice('RAMP', allow_kw_as_dict=True, allow_missing_dict=True,
                                       choices=ChoiceMultiple(['en', 'rate'], [bool, (float,(0.001, 10))]), doc="Activates the sweep mode. rate is in K/min.", setget=True)
        self.ramp_sweeping = devChOption(getstr='RAMPST?', str_type=bool)
        self.sp = scpiDevice('SETP', str_type=float)
        self.still_raw = scpiDevice('STILL', str_type=float)
        self._devwrap('enabled_list')
        self._devwrap('fetch', autoinit=False)
        self.alias = self.fetch

        Rfull = self._still_full_res
        Rhtr = self._still_res
        htr_from_raw = lambda x:  (x/10./Rfull)**2 * Rhtr*1e3 # x is % of 10V scale so x/10 is volt
        htr_to_raw = lambda p:    np.sqrt(p*1e-3/Rhtr)*Rfull*10.  # p is in mW
        self.still = FunctionDevice(self.still_raw, htr_from_raw, htr_to_raw, quiet_del=True, doc='still power in mW')

        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


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

@register_instrument('Berkeley Nucleonics Corporation', 'MODEL 845', '0.4.35', usb_vendor_product=[0x03EB, 0xAFFF])
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

def _parse_magnet_return(s, conv):
    """
    s is the input string
    conv is a list of tuples (start symbol, name, type)
    """
    names = []
    vals = []
    for symb, name, t in conv[::-1]:
        if symb=='last':
            vals.append(_fromstr_helper(s[-1], t))
            s = s[:-1]
        else:
            sp = s.rsplit(symb, 1)
            vals.append(_fromstr_helper(sp[1], t))
            s = sp[0]
        names.append(name)
    if s != "":
        raise RuntimeError('There is some leftovers (%s) in the string'%s)
    return dict_improved(zip(names[::-1], vals[::-1]))


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
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('field', 'current_status', 'setpoints', 'status', 'operating_parameters', 'ramp_wait_after', options)
    def _field_internal(self):
        s=self.ask('N')
        try:
            d = _parse_magnet_return(s, [('F', 'field', float), ('V', 'volt', float),
                                         ('R', 'target', ChoiceIndex(['zero', 'lower','upper'])),
                                          ('last', 'ramptype', ChoiceSimpleMap(dict(A='current_limit', V='volt_limit')))])
            field = d.field
        except IndexError:
            d = _parse_magnet_return(s, [('I', 'current', float), ('V', 'volt', float),
                                     ('R', 'target', ChoiceIndex(['zero', 'lower','upper'])),
                                     ('last', 'ramptype', ChoiceSimpleMap(dict(A='current_limit', V='volt_limit')))])
            field = d.current * self._magnet_cal_T_per_A
        return field, d
    def _field_getdev(self):
        field, d = self._field_internal()
        return field
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
    def _operating_parameters_getdev(self):
        s = self.ask('O')
        return _parse_magnet_return(s, [('A', 'rate', float), ('D', 'reverse', bool),
                                        ('T', 'Tunit', bool), ('B', 'lockout', bool),
                                        ('W', 'Htr_current', float), ('C', 'calibTpA', float)])
    def _setpoints_setdev(self, values):
        Tunit = values.pop('Tunit', None)
        if Tunit is not None:
            self.write('T%i'%Tunit)
        for k,v in values.iteritems():
            v = abs(v)
            if k == 'lower':
                self.write('L%f'%v)
            #elif k == 'upper':
            #    self.write('U%f'%v)
            elif k == 'voltLim':
                self.write('Y%f'%v)
            else:
                raise NotImplementedError('Changing %s is not implememented'%k)
    def _setpoints_getdev(self, Tunit='default'):
        """
        When setting, use a dictionnary with keys of 'lower' and/or 'voltLim'
        and with value the setpoint/limit you want (the sign of the value is lost).
        Also use 'Tunit' key with value False/True.
        For upper/lower you should also always set Tunit (if not it will use the current unit of the instrument.)
        For set, any unspecified value is unchanged.
        """
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

    def _do_ramp(self, field_target, wait):
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
        # unknow state seems to be a possible transient between ramping and at_target.
        # I only see it once (when continuously reading status) immediately followed by 'at_target'
        # I don't always see it.
        # Since the end_states check is done after a second reading of status (and a possible wait)
        # we should never have to check for it but to be safe I add it anyway (my observations time was not infinite)
        self._ramping_helper('ramping', ['at_target', 'unknown'], wait)
        # With a ramping rate of 0.00585 A/s  = 0.031 T/min
        # when going to zero, at_target shows up at about 3 mT and it takes about another 5 s to go to 0.
        # going to non-zero field (+0.05), at_target shows up at about 20 mT from target, and it takes another 15-20 s to become stable (0.0505 T)

    def _ramp_T_checkdev(self, val, wait=None, quiet=True):
        BaseDevice._checkdev(self.ramp_T, val)

    def _ramp_T_setdev(self, val, wait=None, quiet=True):
        """ Goes to the requested setpoint and then waits until it is reached.
            After the instrument says we have reached the setpoint, we wait for the
            duration set by ramp_wait_after (in s).
            wait can be used to set a wait time (in s) after the ramp. It overrides ramp_wait_after.
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
        self._do_ramp(val, wait)

    def _ramp_T_getdev(self):
        return self.field.get()

    def _create_devs(self):
        self.ramp_wait_after = MemoryDevice(20., min=0.)
        self._devwrap('field', doc='units are Tesla')
        self._devwrap('operating_parameters', setget=True, allow_kw_as_dict=True,
                      choices=ChoiceMultiple(['rate', 'reverse', 'Tunit'], [float, bool, bool], allow_missing_keys=True))
        self._devwrap('setpoints', setget=True, allow_kw_as_dict=True,
                      choices=ChoiceMultiple(['lower', 'voltLim', 'Tunit'], [float, float, bool], allow_missing_keys=True))
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
            tm = time.localtime()
            cmd = 'STOre DAte %i,%i,%i;%s; STOre TIme %i,%i,%i;%s'%(tm.tm_year, tm.tm_mon, tm.tm_mday, passcode,
                                                                    tm.tm_hour, tm.tm_min, tm.tm_sec, passcode)
            print cmd
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

    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('average', 'units', 'voltage_max', 'frequency', 'commutate', 'bias', 'cable', options)

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
        #   reference
        #   reference percent
        #   reference point
        #     scan to disable it.
        #   serial (to read this use: show serial list)
        #   test?
        #   zero
        #   zero point
        #
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
