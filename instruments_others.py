# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

import numpy as np
import random
import time
from scipy.optimize import brentq as brentq_rootsolver

import traces

from instruments_base import BaseInstrument, visaInstrument, visaInstrumentAsync,\
                            BaseDevice, scpiDevice, MemoryDevice, Dict_SubDevice, ReadvalDev,\
                            ChoiceBase, ChoiceMultiple, ChoiceMultipleDep,\
                            ChoiceStrings, ChoiceIndex,\
                            make_choice_list,\
                            decode_float64, visa, sleep, locked_calling

#######################################################
##    Yokogawa source
#######################################################

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
        self.write('*cls')
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
    def _level_check(self, val):
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

class sr830_lia(visaInstrument):
    """
    When using async mode, don't forget to set the async_delay
    to some usefull values.
     might do sr1.async_delay = 1
    when using 24dB/oct, 100ms filter.

    You can use find_n_time and find_fraction to set the time.
    For example: sr1.async_delay = sr1.find_n_time(.99,sec=True)

    To read more than one channel at a time use snap
    Otherwise you can use x, y, t, theta and snap
    """
    # TODO setup snapsel to use the names instead of the numbers
    _snap_type = {1:'x', 2:'y', 3:'R', 4:'theta', 5:'Aux_in1', 6:'Aux_in2',
                  7:'Aux_in3', 8:'Aux_in4', 9:'Ref_Freq', 10:'Ch1', 11:'Ch2'}
    def init(self, full=False):
        # This empties the instrument buffers
        self._clear()
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
        base = ['async_delay=%r'%self.async_delay]
        return base+self._conf_helper('freq', 'sens', 'srclvl', 'harm', 'phase', 'timeconstant', 'filter_slope',
                                 'sync_filter', 'reserve_mode',
                                 'offset_expand_x', 'offset_expand_y', 'offset_expand_r',
                                 'input_conf', 'grounded_conf', 'dc_coupled_conf', 'linefilter_conf', options)
    def _create_devs(self):
        self.freq = scpiDevice('freq', str_type=float, setget=True, min=0.001, max=102e3)
        sens = ChoiceIndex(make_choice_list([2,5,10], -9, -1), normalize=True)
        self.sens = scpiDevice('sens', choices=sens, doc='Set the sensitivity in V (for currents it is in uA)')
        self.oauxi1 = scpiDevice(getstr='oaux? 1', str_type=float, setget=True)
        self.srclvl = scpiDevice('slvl', str_type=float, min=0.004, max=5., setget=True)
        self.harm = scpiDevice('harm', str_type=int, min=1, max=19999)
        self.phase = scpiDevice('phas', str_type=float, min=-360., max=729.90, setget=True)
        timeconstants = ChoiceIndex(make_choice_list([10, 30], -6, 3), normalize=True)
        self.timeconstant = scpiDevice('oflt', choices=timeconstants)
        filter_slopes=ChoiceIndex([6, 12, 18, 24])
        self.filter_slope = scpiDevice('ofsl', choices=filter_slopes, doc='in dB/oct\n')
        self.sync_filter = scpiDevice('sync', str_type=bool)
        self.x = scpiDevice(getstr='outp? 1', str_type=float, delay=True)
        self.y = scpiDevice(getstr='outp? 2', str_type=float, delay=True)
        self.r = scpiDevice(getstr='outp? 3', str_type=float, delay=True)
        off_exp = ChoiceMultiple(['offset_pct', 'expand_factor'], [float, ChoiceIndex([1, 10 ,100])])
        self.offset_expand_x = scpiDevice('oexp 1,{val}', 'oexp? 1', choices=off_exp, setget=True)
        self.offset_expand_y = scpiDevice('oexp 2,{val}', 'oexp? 2', choices=off_exp, setget=True)
        self.offset_expand_r = scpiDevice('oexp 3,{val}', 'oexp? 3', choices=off_exp, setget=True)
        self.theta = scpiDevice(getstr='outp? 4', str_type=float, delay=True)
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
        self._devwrap('snap', delay=True, doc="""
            This device obtains simultaneous readings from many inputs.
            To select the inputs, use the parameter
             sel
            which is [1,2] by default.
            The numbers are taken from the following dictionnary:
                %r
                """%self._snap_type)
        self.alias = self.snap
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
        if n_filter == None:
            n_filter = self.filter_slope.getcache()
            n_filter = self.filter_slope.choices.index(n_filter)+1
        if time_constant == None:
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
        if n_filter == None:
            n_filter = self.filter_slope.getcache()
            n_filter = self.filter_slope.choices.index(n_filter)+1
        if time_constant == None:
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

class sr384_rf(visaInstrument):
    # This instruments needs to be on local state or to pass through local state
    #  after a local_lockout to actually turn off the local key.
    # allowed units: amp: dBm, rms, Vpp; freq: GHz, MHz, kHz, Hz; Time: ns, us, ms, s
    def init(self, full=False):
        # This clears the error state
        self.write('*cls')
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
    Useful attribute:
        async_delay (needed for exponential average, not for linear)
    Useful methods:
        start
        get_xscale

    Changing a setup should be done in the following order
        meas_grp
        meas
        meas_view
        unit
    """
    def init(self, full=False):
        # This empties the instrument buffers
        self._clear()
        # This clears the error state, and status/event flags?
        self.write('*cls')
        if full:
            self._async_sre_flag = 2
            self.write('DSPE 0;*sre 2') # Display flags
            self._cum_display_status = 0
            self._async_detect_setup(reset=True)
            #self._async_tocheck = 0
            #self._async_use_delay = False
            self._async_trig_time = 0
            self._async_delay_check = True
            self.visa.term_chars='\n'
            # The above turned on detection of termchar on read. This is not good for
            # raw reads so turn it off.
            visa.vpp43.set_attribute(self.visa.vi, visa.VI_ATTR_TERMCHAR_EN, visa.VI_FALSE)
            self.write('OUTX 0') # Force interface to be on GPIB, in case it is not anymore (problem with dump function)
    def _get_async(self, async, obj, delay=False, trig=False, **kwarg):
        ret = super(sr780_analyzer, self)._get_async(async,  obj, delay=delay, trig=trig, **kwarg)
        if async == 0: #setup
            if self._async_list_init == []: # first time through
                self._async_list_init.append((self._async_detect_setup, dict(reset=True)))
            # Assuming we only get called by fetch/readval
            disp = kwarg.get('disp', None)
            self._async_list_init.append((self._async_detect_setup, dict(disp=disp)))
        return ret
    def _async_detect_setup(self, disp=None, reset=False):
        if reset:
            self._async_tocheck = 0
            self._async_use_delay = False
            self._cum_display_status = 0
            return
        disp_org = self.current_display.getcache()
        if disp==None:
            disp = disp_org
        self.current_display.set(disp)
        # 0x2=A-linear avg, 0x4=A-settled, 0x200=B-linear, 0x400=B-settled
        if self.average_en.get(disp=disp):
            if self.average_type.get() in ['linear', 'FixedLength']:
                tocheck = 0x2
            else:
                if self._async_delay_check and self.async_delay == 0.:
                    print self.perror('***** WARNING You should give a value for async_delay *****')
                    self._async_delay_check = False
                self._async_use_delay = True
                tocheck = 0x4
        else:
            tocheck = 0x4
        if disp == 'B':
            tocheck <<= 8
        self._async_tocheck |= tocheck
        self.current_display.set(disp_org)
    def _async_trigger_helper(self):
        if self._async_use_delay==False and self._async_tocheck==0:
            # Need to setup for both channels since we don't know which one
            # is needed (for exemple: get srnet.readval,disp='B' while current_disp is 'A',
            #  run_and_wait is called before current_disp is changed)
            self._async_detect_setup('A')
            self._async_detect_setup('B')
        self.write('PAUS') # make sure we are not scanning anymore.
        self.get_display_status() # reset the display status flags
        self.write('DSPE %i'%self._async_tocheck)
        self.write('STRT')
        self._async_trig_time = time.time()
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
        if not ret:
            # Did not receive SRQ
            return ret
        # Received SRQ, check if we are done
        disp_st = self.get_display_status()
        self._cum_display_status |= disp_st
        if self._async_use_delay:
            if time.time()-self._async_trig_time < self.async_delay:
                #print 'wait delay %0x %f'%(self._cum_display_status, time.time()-self._async_trig_time)
                return False
        tocheck = self._async_tocheck
        #print 'tocheck %0x %0x %0x'%(tocheck, self._cum_display_status, disp_st)
        if self._cum_display_status&tocheck == tocheck:
            self.write('DSPE 0')
            self._async_detect_setup(reset=True)
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
        For exponential averaging you need to specify a wait time with async_delay
         i.e. srnet.async_delay=3  # for 2 seconds
        """
        # The instrument has 5 Traces that can be used for memory.
        # There is REFY? d,j to obtain pint j (0..length-1) in ref curve of display d
        #  DSPN? d to obtain lenght of data set
        if disp != None:
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
                                 'source_offset_V', 'source_freq2', 'source_ampl2_V',
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
        self.input_coupling = devChOption('I{ch}GD', choices=ChoiceIndex(['DC', 'AC', 'ICP']))
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
        self.window_type = devDispOption('FWIN {disp},{val}', 'FWIN? {disp}', choices=ChoiceIndex(['uniform', 'hanning', 'flattop', 'BMH', 'kaiser', 'force', 'exponential', 'user', '-T/2..T/2', '0..T/2', '-T/4..T/4',]))
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
         -ps: when true returns a postscript object, otherwirse returns a GIF file
         -area: used for GIF files, one of 'graph', 'menu', 'status' or 'all'
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
                r += visa.vpp43.read(self.visa.vi, 1)
        else:
            self.write('POUT 0;PDST 3;PCIC 0;PRTP 4;PSCR %d;PRNT'%area_sel[area])
            try:
                while True:
                    r += visa.vpp43.read(self.visa.vi, 1)
            except visa.VisaIOError:
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
##    Lakeshore 322 Temperature controller
#######################################################

class lakeshore_322(visaInstrument):
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('sp', options)
    def _create_devs(self):
        self.crdg = scpiDevice(getstr='CRDG? A', str_type=float)
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
        self.alias = self.tb
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


#######################################################
##    Lakeshore 340 Temperature controller
#######################################################

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
        if ch == None:
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
        self.alias = self.t
        self._devwrap('enabled_list')
        self._devwrap('fetch', autoinit=False)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


#######################################################
##    Lakeshore 370 Temperature controller
#######################################################

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
           still_raw
       s and t return the sensor(Ohm) or kelvin value of a certain channel
       which defaults to current_ch
       status_ch returns the status of ch
       fetch allows to read all channels
    """
    def init(self, full=False):
        self._last_command_time = None
        if full and isinstance(self.visa, visa.SerialInstrument):
            self.visa.parity = True
            self.visa.data_bits = 7
            self.visa.term_chars = '\r\n'
            self._last_command_time = time.time()
        super(lakeshore_370, self).init(full=full)
    @locked_calling
    def write(self, val):
        last = self._last_command_time
        if last != None:
            # we need to wait at least 50ms after last write or read
            delta = (last+.050) - time.time()
            if delta > 0:
                sleep(delta)
        super(lakeshore_370, self).write(val)
        if last != None:
            self._last_command_time = time.time()
    @locked_calling
    def read(self):
        ret = super(lakeshore_370, self).read()
        if self._last_command_time != None:
            self._last_command_time = time.time()
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
        base += self._conf_helper('sp', 'pid', 'still_raw', 'heater_range',
                                  'control_mode', 'control_setup', options)
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
        if ch == None:
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
    def _fetch_getdev(self, ch=None):
        """
        Optional parameter:
            ch: To select which channels to read. Default to all the enabled
                ones. Otherwise ch=4 selects only channel 4 and
                ch=[3,5] selects channels 3 and 5.

        For each channels, two values are returned. The tempereture in Kelvin
        and the sensor value in Ohm.
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
        self.input_set = devChOption('INSET {ch},{val}', 'INSET? {ch}',
                                     choices=ChoiceMultiple(['enabled', 'dwell', 'pause', 'curvno', 'tempco'],
                                                       [bool, (int, (1, 200)), (int, (3, 200)), (int, (0, 20)), tempco]))
        self.input_filter = devChOption('FILTER {ch},{val}', 'FILTER? {ch}',
                                      choices=ChoiceMultiple(['filter_en', 'settle_time', 'window'], [bool, (int, (1, 200)), (int, (1, 80))]))
        res_ranges = ChoiceIndex(make_choice_list([2, 6.32], -3, 7), offset=1, normalize=True)
        cur_ranges = ChoiceIndex(make_choice_list([1, 3.16], -12, -2), offset=1, normalize=True)
        volt_ranges = ChoiceIndex(make_choice_list([2, 6.32], -6, -1), offset=1, normalize=True)
        curvolt_ranges = ChoiceMultipleDep('exc_mode', {'voltage':volt_ranges, 'current':cur_ranges})
        self.input_meas = devChOption('RDGRNG {ch},{val}', 'RDGRNG? {ch}',
                                     choices=ChoiceMultiple(['exc_mode', 'exc_range', 'range', 'autorange_en', 'excitation_disabled'],
                                                       [ChoiceIndex(['voltage', 'current']), curvolt_ranges, res_ranges, bool, bool]))
        # scan returns the channel currently being read
        #  it is the channel that flashes, not necessarily the one after scan on the
        #  display (they differ when temperature control is enabled, the instrument goes back
        #  to the control channel after all readings. This command follows that.)
        self.scan = scpiDevice('SCAN', choices=ChoiceMultiple(['ch', 'autoscan_en'], [int, bool]))
        #self.current_loop = MemoryDevice(1, choices=[1, 2])
        #def devLoopOption(*arg, **kwarg):
        #    options = kwarg.pop('options', {}).copy()
        #    options.update(loop=self.current_loop)
        #    app = kwarg.pop('options_apply', ['loop'])
        #    kwarg.update(options=options, options_apply=app)
        #    return scpiDevice(*arg, **kwarg)
        #self.pid = scpiDevice('PID', choices=ChoiceMultiple(['P', 'I', 'D'], float))
        self.pid = scpiDevice('PID', choices=ChoiceMultiple(['P', 'I', 'D'], [(float, (0.001, 1000)), (float,(0, 10000)), (float, (0, 2500))]))
        self.pid_P = Dict_SubDevice(self.pid, 'P', force_default=False)
        self.pid_I = Dict_SubDevice(self.pid, 'I', force_default=False)
        self.pid_D = Dict_SubDevice(self.pid, 'D', force_default=False)
        self.htr = scpiDevice(getstr='HTR?', str_type=float) #heater out in % or in W
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
        self.control_setup = scpiDevice('CSET', choices=csetup)
        self.control_setup_heater_limit = Dict_SubDevice(self.control_setup, 'heater_limit', force_default=False)
        self.sp = scpiDevice('SETP', str_type=float)
        self.still_raw = scpiDevice('STILL', str_type=float)
        self._devwrap('enabled_list')
        self._devwrap('fetch', autoinit=False)
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


#######################################################
##    Colby Instruments Programmable delay line PDL-100A-20NS
#######################################################

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
        # This clears the error state, and status/event flags?
        self.write('*cls')
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
##    Dummy instrument
#######################################################

class dummy(BaseInstrument):
    def init(self, full=False):
        self.incr_val = 0
        self.wait = .1
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('volt', 'current', 'other', options)
    def _incr_getdev(self):
        ret = self.incr_val
        self.incr_val += 1
        traces.wait(self.wait)
        return ret
    def _incr_setdev(self, val):
        self.incr_val = val
    #incr3 = wrapDevice(_incr_setdev, _incr_getdev)
    #incr2 = wrapDevice(getdev=_incr_getdev)
    def _rand_getdev(self):
        traces.wait(self.wait)
        return random.normalvariate(0,1.)
    def _create_devs(self):
        self.volt = MemoryDevice(0., doc='This is a memory voltage, a float')
        self.current = MemoryDevice(1., doc='This is a memory current, a float')
        self.other = MemoryDevice(autoinit=False, doc='This takes a boolean')
        #self.freq = scpiDevice('freq', str_type=float)
        self._devwrap('rand', doc='This returns a random value. There is not set.', delay=True)
        self._devwrap('incr')
        self.alias = self.current
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
