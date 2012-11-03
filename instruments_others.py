# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

import numpy as np
import random
from scipy.optimize import brentq as brentq_rootsolver

import traces

from instruments_base import BaseInstrument, visaInstrument,\
                            BaseDevice, scpiDevice, MemoryDevice,\
                            ChoiceBase, dict_str,\
                            ChoiceStrings, ChoiceIndex, make_choice_list,\
                            decode_float64, visa

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
    For example: set sr1,sr1.find_n_time(.99,sec=True)

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
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('freq', 'sens', 'srclvl', 'harm', 'phase', 'timeconstant', 'filter_slope',
                                 'sync_filter', 'reserve_mode',
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
        conv = dict_str(['master_rev_date', 'master_rev_num', 'master_serial_num', 'sw1', 'input_rev_date',
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
        self.input_set = devChOption('INSET {ch},{val}', 'INSET? {ch}', str_type=dict_str(['enabled', 'compens'],[bool, int]))
        self.input_crv = devChOption('INCRV {ch},{val}', 'INCRV? {ch}', str_type=int)
        self.input_type = devChOption('INTYPE {ch},{val}', 'INTYPE? {ch}',
                                      str_type=dict_str(['type', 'units', 'coeff', 'exc', 'range']))
        self.input_filter = devChOption('FILTER {ch},{val}', 'FILTER? {ch}',
                                      str_type=dict_str(['filter_en', 'n_points', 'window'], [bool, int, int]))
        self.current_loop = MemoryDevice(1, choices=[1, 2])
        def devLoopOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(loop=self.current_loop)
            app = kwarg.pop('options_apply', ['loop'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.pid = devLoopOption('PID {loop},{val}', 'PID? {loop}',
                                 str_type=dict_str(['P', 'I', 'D'], float))
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
        if full and isinstance(self.visa, visa.SerialInstrument):
            self.visa.parity = True
            self.visa.data_bits = 7
            self.visa.term_chars = '\r\n'
        super(lakeshore_370, self).init(full=full)
    def _current_config(self, dev_obj=None, options={}):
        if dev_obj == self.fetch:
            old_ch = self.current_ch.getcache()
            ch = options.get('ch', None)
            ch = self._fetch_helper(ch)
            ch_list = []
            in_set = []
            for c in ch:
                ch_list.append(c)
                in_set.append(self.input_set.get(ch=c))
            self.current_ch.set(old_ch)
            base = ['current_ch=%r'%ch_list, 'input_set=%r'%in_set]
        else:
            base = self._conf_helper('current_ch', 'input_set')
        base += self._conf_helper('sp', 'pid', 'still_raw', options)
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
        self.input_set = devChOption('INSET {ch},{val}', 'INSET? {ch}', str_type=dict_str(['enabled', 'dwell', 'pause', 'curvno', 'tempco'],[bool, int, int, int]))
        self.input_filter = devChOption('FILTER {ch},{val}', 'FILTER? {ch}',
                                      str_type=dict_str(['filter_en', 'settle_time', 'window'], [bool, int, int]))
        self.scan = scpiDevice('SCAN', str_type=dict_str(['ch', 'autoscan_en'], [int, bool]))
        #self.current_loop = MemoryDevice(1, choices=[1, 2])
        #def devLoopOption(*arg, **kwarg):
        #    options = kwarg.pop('options', {}).copy()
        #    options.update(loop=self.current_loop)
        #    app = kwarg.pop('options_apply', ['loop'])
        #    kwarg.update(options=options, options_apply=app)
        #    return scpiDevice(*arg, **kwarg)
        self.pid = scpiDevice('PID', str_type=dict_str(['P', 'I', 'D'], float))
        self.htr = scpiDevice(getstr='HTR?', str_type=float) #heater out in % or in W
        self.sp = scpiDevice('SETP', str_type=float)
        self.still_raw = scpiDevice('STILL', str_type=float)
        self.alias = self.t
        self._devwrap('enabled_list')
        self._devwrap('fetch', autoinit=False)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


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
