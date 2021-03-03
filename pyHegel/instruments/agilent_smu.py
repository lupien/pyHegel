# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2019-2019  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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
import types
import string

from ..instruments_base import visaInstrument, visaInstrumentAsync,\
                            BaseDevice, scpiDevice, MemoryDevice, ReadvalDev,\
                            ChoiceMultiple, Choice_bool_OnOff, _repr_or_string,\
                            quoted_string, quoted_list, quoted_dict, ChoiceLimits,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDev, ChoiceDevSwitch, ChoiceIndex,\
                            decode_float64, decode_float64_avg, decode_float64_meanstd,\
                            decode_uint16_bin, _decode_block_base, decode_float64_2col,\
                            decode_complex128, sleep, locked_calling, visa_wrap, _encode_block,\
                            dict_improved, _general_check, _tostr_helper, ChoiceBase, ProxyMethod,\
                            OrderedDict, _decode_block_auto, ChoiceSimpleMap
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

#######################################################
##    Agilent E5270B mainframe with E5281B precision medium power SMU modules
#######################################################

# decorator to cache values for 1s
def cache_result(func):
    def wrapped_func(self, *args, **kwargs):
        last, cache, prev_args, prev_kwargs = self._wrapped_cached_results.get(func, (None, None, None, None))
        now = time.time()
        if last is None or now - last > 1. or args != prev_args or kwargs != prev_kwargs:
            #print 'Updating cache'
            cache = func(self, *args, **kwargs)
            self._wrapped_cached_results[func] = (now, cache, args, kwargs)
        return cache
    wrapped_func._internal_func = func
    return wrapped_func

class ProxyMethod_cached(ProxyMethod):
    def __init__(self, bound_method, *args, **kwargs):
        super(ProxyMethod_cached, self).__init__(bound_method, *args, **kwargs)
        try:
            self._internal_func = bound_method._internal_func
        except AttributeError:
            pass

class MemoryDevice_update(MemoryDevice):
    def __init__(self, update_func, *args, **kwargs):
        """ update_func is called after a set to update the instrument
            nch, when set is the number of channels of data to save internally.
              With this, it enables the use of ch as an option for set/get
        """
        self._update_func = func_or_proxy(update_func)
        nch = self._nch = kwargs.pop('nch', None)
        super(MemoryDevice_update, self).__init__(*args, **kwargs)
        if nch is not None:
            val = self.getcache(local=True)
            self._internal_vals = [val]*nch
    def _ch_helper(self, ch=None, slot=None):
        args = ()
        if self._nch is not None:
            if slot is not None:
                ch = slot
            else:
                ch = self.instr._ch_helper(ch)
            args += (ch, )
        elif ch is not None:
            raise ValueError(self.perror('You cannnot specify a channel for this device.'))
        return ch, args
    def _getdev(self, ch=None, slot=None):
        ch, args = self._ch_helper(ch, slot)
        if ch is None:
            return super(MemoryDevice_update, self)._getdev(self)
        return self._internal_vals[ch-1]
    def _setdev(self, val, ch=None, slot=None):
        ch, args = self._ch_helper(None) # Channel already changed in check
        if ch is not None:
            self._internal_vals[ch-1] = val
        super(MemoryDevice_update, self)._setdev(val)
        if self._update_func is not None:
            self._update_func(*args)
    def _checkdev(self, val, ch=None, slot=None):
        ch, args = self._ch_helper(ch, slot)
        super(MemoryDevice_update, self)._checkdev(val)

def func_or_proxy(func):
    if isinstance(func, types.MethodType):
        if func.im_self is not None:
            return ProxyMethod_cached(func)
    return func

class CommonDevice(BaseDevice):
    # This is hard coded to use
    #  self.instr._ch_helper
    #  self._reset_wrapped_cache
    #  self.choices.tostr or self.type
    def __init__(self, subfunc, getfunc, setstr, *args, **kwargs):
        """
        Need subfunc (called as subfunc(); with not parameters) and cache reset after set.
        getfunc is called as getfunc(subfunc(), ch) (ch is present only if ch_mode option is not None)
        ch_mode can be False(default) or True
        setstr is the string to set with the {val} and {ch} arguments properly placed.
               or it can be a function that will be called as setstr(self, val, ch) (again ch only present if required)
        You need to set either a type or a choice.
        """
        self._ch_mode = kwargs.pop('ch_mode', False)
        self.type = kwargs.pop('type', None)
        self._getfunc = func_or_proxy(getfunc)
        self._subfunc = func_or_proxy(subfunc)
        super(CommonDevice, self).__init__(*args, **kwargs)
        if not isinstance(setstr, basestring):
            setstr = func_or_proxy(setstr)
        self._setdev_p = setstr
        self._getdev_p = True
        if self.choices is not None and isinstance(self.choices, ChoiceBase):
            self.type = self.choices
    def _ch_helper(self, ch=None):
        args = ()
        if self._ch_mode:
            ch = self.instr._ch_helper(ch)
            args += (ch, )
        elif ch is not None:
            raise ValueError(self.perror('You cannnot specify a channel for this device.'))
        return ch, args
    def _getdev(self, ch=None):
        ch, args = self._ch_helper(ch)
        subval = self._subfunc()
        args = (subval,) + args
        return self._getfunc(*args)
    def _setdev(self, val, ch=None):
        ch, args = self._ch_helper(None) # Channel already changed in check
        if isinstance(self._setdev_p, basestring):
            kwargs = dict(val=_tostr_helper(val, self.type))
            if ch is not None:
                kwargs['ch'] = '%i'%ch
            outstr = self._setdev_p.format(**kwargs)
            self.instr.write(outstr)
        else:
            args = (self, val) + args
            self._setdev_p(*args)
        self.instr._reset_wrapped_cache(self._subfunc)
    def _checkdev(self, val, ch=None):
        ch, args = self._ch_helper(ch)
        super(CommonDevice, self)._checkdev(val)


#@register_instrument('Agilent Technologies', 'B1500A', 'A.06.01.2019.0423')
#@register_instrument('Agilent Technologies', 'E5270B', 'B.01.13')
@register_instrument('Agilent Technologies', 'B1500A', alias='B1500A SMU', skip_add=True)
@register_instrument('Agilent Technologies', 'E5270B', alias='E5270B SMU')
class agilent_SMU(visaInstrumentAsync):
    """
    This is to control the E5281B precision medium power SMU modules within
    an E5270B mainframe. And also the B1517A (HR), B1511B (MP) SMU in the
    B1500A (Semiconductor Device Analyzer) mainframe.
    Useful devices:
        readval
        level
        compliance
        measV, measI    These migth be a little faster than readval for a single measurement,
                        but could fail with a timeout (so only use them for very quick measurements,
                        or increase the timeout (see the set_timeout attribute).
    There is a fetch device but it will not work on its own. Use readval or fetch with async
    (but since readval with async does the same, you should always use readval here.)
    To configure the instrument, look at the methods:
        conf_general
        conf_integration
        conf_ch
        set_mode
        conf_staircase
    Other useful method:
        empty_buffer   Use it to clear the buffer when stopping a reading.
                       Otherwise the next request will return previous (and wrong)
                       answers.
        abort
    Note: The B1500A needs to have the EasyExpert Start button running for
          remote GPIB to work. Do not start the application.
    """
    def __init__(self, *args, **kwargs):
        """
        smu_channel_map when specified, is a dictionnary of slot number (keys) to smu channel
                number (values). If not given, it will be created with automatically for slots
                with smu modules in increasing order starting at 1.
        """
        self._wrapped_cached_results = {}
        self._smu_channel_map = kwargs.pop('smu_channel_map', None)
        if self._smu_channel_map is not None:
            ch_map = self._smu_channel_map
            N = len(ch_map)
            if len(set(ch_map.values())) != N:
                # repeated keys is not possible.
                raise ValueError('Invalid smu_channel_map: repeated key or value.')
        super(agilent_SMU, self).__init__(*args, **kwargs)

    def empty_buffer(self):
        self.write('BC')

    def init(self, full=False):
        self.empty_buffer()
        self.write('FMT21')
        if self._isB1500:
            # for parallel measurments also on spot, stairs (MM 1, 2), Not necessary for MM 16 (multi stairs, the one I use)
            # Read back the value with *LRN? 110
            self.write('PAD 1')
        self.calibration_auto_en.set(False)
        #self.sendValueToOther('Auto Calibration Enable', False)
          # Calibration is performed every 30 min after all outputs are off.
        self.remote_display_en.set(True)
        #super(agilent_SMU, self).init(full=full) # don't use this, it sets *esr which does not exist for SMU
        # self.clear() # SMU does not have *cls
        self.write('*sre 0') # disable trigger (we enable it only when needed)
        self._async_trigger_helper_string = None
        self._async_trigger_n_read = None
        self._async_trig_current_data = None
        self._async_trigger_parsers = None

    def _async_select(self, devs=[]):
        # This is called during init of async mode.
        self._async_detect_setup(reset=True)
        for dev, kwarg in devs:
            if dev in [self.fetch, self.readval]:
                chs = kwarg.get('chs', None)
                auto = kwarg.get('auto', 'all')
                self._async_detect_setup(chs=chs, auto=auto)

    def _async_detect_setup(self, chs=None, auto=None, reset=False):
        if reset:
            # make the default async_mode is 'wait' so that if
            # _async_tocheck == 0, we just turn on wait.
            # This could happen when using run_and_wait before anything is set
            # Otherwise, getasync and readval both call async_select to setup
            # the mode properly (_async_mode and_async_tocheck).
            self._async_trigger_helper_string = ''
            self._async_trigger_parsers = [] # list of (func, args, kwargs)
            self._async_trigger_n_read = 0
            return
        n_read = self._async_trigger_n_read
        async_string = self._async_trigger_helper_string
        async_parsers = self._async_trigger_parsers
        full_chs, auto, mode = self._fetch_opt_helper(chs, auto)
        if mode != 'spot':
            async_string += ';XE'
            async_parsers.append((None, (), {}))
            n_read += 1
        else:
            for ch, meas in full_chs:
                if meas == 'v':
                    is_voltage = True
                    rng = self.range_voltage_meas
                else:
                    is_voltage = False
                    rng = self.range_current_meas
                quest, slot = self._measIV_helper_get_quest(is_voltage, ch, None, rng)
                async_string += ';' + quest
                async_parsers.append((self._measIV_helper_ret_val, (is_voltage, slot), {}))
                n_read += 1
        if len(async_string) >= 1:
             # we skip the first ';'
             async_string = async_string[1:]
        self._async_trigger_helper_string = async_string
        self._async_trigger_n_read = n_read
        self._async_trigger_parsers = async_parsers

    def _async_trigger_helper(self):
        async_string = self._async_trigger_helper_string
        if async_string is None or async_string == '':
            return
        self._async_trig_current_data = None
        self.write(async_string)

    def _async_cleanup_after(self):
        self.write('*sre 0') # disable trigger on data ready to prevent unread status byte from showing up
        super(agilent_SMU, self)._async_cleanup_after()

    def _async_detect(self, max_time=.5): # 0.5 s max by default
        async_string = self._async_trigger_helper_string
        if async_string is None:
            return True
        ret = super(agilent_SMU, self)._async_detect(max_time)
        if not ret:
            # This cycle is not finished
            return ret
        # we got a trigger telling data is available. so read it, before we turn off triggering in cleanup
        data = [self.read() for i in range(self._async_trigger_n_read)]
        self._async_trig_current_data = data
        return ret

    @locked_calling
    def _async_trig(self):
        #self.empty_buffer()
        # Trigger on Set Ready. This generates an event which will need to be cleaned up.
        # *opc? is used to make sure we waited long enough to see the event if it was to occur.
        # Note that the event is not always detected by NI autopoll so this is why
        # we wait and then empty the buffer of all/any status.
        #   (see details in comment section below to class code.)
        self.ask('*sre 16;*opc?')
        # absorb all status bytes created.
        #i=0
        while self.read_status_byte()&0x40:
#            i += 1
            pass
#        print 'skipped %i'%i
        super(agilent_SMU, self)._async_trig()

    def _get_esr(self):
        # does not have esr register
        return 0

    def get_error(self):
        if self._isB1500:
            error = self.ask('ERRX?')
            er_no, er_mes = error.split(',', 1)
            er_no = int(er_no)
            er_mes = quoted_string()(er_mes)
            errm = '%i: %s'%(er_no, er_mes)
        else:
            errors = self.ask('ERR?')
            errn = [int(s) for s in errors.split(',')]
            errm = ['%i: %s'%(e, self.ask('EMG? %i'%e)) for e in errn]
            errm = ', '.join(errm)
        return errm

    def abort(self):
        """\
        Call this to stop an internal sweep.
        It might be good to also call the empty_buffer method.
        """
        self.write('AB')

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = []
        conf_gen = self.conf_general()
        opts += ['conf_general=%s'%conf_gen]
        opts += ['conf_ch=%s'%self.conf_ch()]
        opts += ['conf_integration=%s'%self.conf_integration()]
        if not conf_gen['measurement_spot_en']:
            opts += ['set_mode=%s'%self.set_mode()]
        return opts+self._conf_helper(options)

    def _reset_wrapped_cache(self, func):
        self._wrapped_cached_results[func._internal_func] = (None, None, None, None)

    @locked_calling
    def reset(self):
        self.write('*rst')
        self.init()

    @locked_calling
    def perform_calibration(self):
        prev_str = self._async_trigger_helper_string
        prev_n_read = self._async_trigger_n_read
        try:
            self._async_trigger_helper_string = '*cal?'
            self._async_trigger_n_read = 1
            self.run_and_wait()
            res = int(self._async_trig_current_data[0])
        finally:
            self._async_trigger_helper_string = prev_str
            self._async_trigger_n_read = prev_n_read
            del self._async_trig_current_data
        if res != 0:
            raise RuntimeError(self.perror('Calibration failed (at least one module failed). Returned value is %i'%res))

    def _fetch_opt_helper(self, chs=None, auto='all'):
        mode = 'spot'
        if not self.measurement_spot_en.get():
            mode = self.set_mode().meas_mode
            full_chs = [[c, 'ch'] for c in self.set_mode()['channels']]
            return full_chs, auto, mode
        auto = auto.lower()
        if auto not in ['all', 'i', 'v', 'force', 'compliance']:
            raise ValueError(self.perror("Invalid auto setting"))
        if chs is None:
            chs = [self._slot2smu[i+1] for i,v in enumerate(self._get_enabled_state()) if v]
            if len(chs) == 0:
                raise RuntimeError(self.perror('All channels are off so cannot fetch.'))
        if not isinstance(chs, (list, tuple, np.ndarray)):
            chs = [chs]
        full_chs = []
        conv_force = dict(voltage='v', current='i')
        conv_compl = dict(voltage='i', current='v')
        for ch in chs:
            if isinstance(ch, basestring):
                meas = ch[0].lower()
                c = int(ch[1:])
                if meas not in ['v', 'i']:
                    raise ValueError(self.perror("Invalid measurement requested, should be 'i' or 'v'"))
                if c not in self._valid_ch:
                    raise ValueError(self.perror('Invalid channel requested'))
                full_chs.append([c, meas])
            else:
                if ch not in self._valid_ch:
                    raise ValueError(self.perror('Invalid channel requested'))
                if auto in ['force', 'compliance']:
                    func = self._get_function_cached(self._smu2slot[ch]).mode
                    if auto == 'force':
                        func = conv_force[func]
                    else:
                        func = conv_compl[func]
                    full_chs.append([ch, func])
                else:
                    if auto in ['all', 'i']:
                        full_chs.append([ch, 'i'])
                    if auto in ['all', 'v']:
                        full_chs.append([ch, 'v'])
        return full_chs, auto, mode

    def _fetch_getformat(self,  **kwarg):
        chs = kwarg.get('chs', None)
        auto = kwarg.get('auto', 'all')
        status = kwarg.get('status', False)
        xaxis = kwarg.get('xaxis', True)
        full_chs, auto, mode = self._fetch_opt_helper(chs, auto)
        multi = []
        graph = []
        for i, (c, m) in enumerate(full_chs):
            base = '%s%i'%(m, c)
            if status:
                multi.extend([base, base+'_stat'])
                graph.append(2*i)
            else:
                multi.append(base)
                graph.append(i)
        if mode == 'stair':
            graph = []
            if xaxis:
                multi = ['force']+multi
            multi = tuple(multi)
        fmt = self.fetch._format
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch, **kwarg)

    def _fetch_getdev(self, chs=None, auto='all', status=False, xaxis=True):
        """
        auto/chs can are only used when measurement_spot_en is True
        auto can be: 'all' (both V and I), 'I' or 'V' to get just one,
                     'force'/'compliance' to get the force value (source) or
                       the compliance value
        auto is used when chs is None (all enabled channels)
           or chs is a list of channel numbers.
        Otherwise, chs can also use strings like 'v1' to read the voltage of channel 1
                     'i2' to read the current of channel 2.
        status when True, adds the status of every reading to the return value.
        xaxis when True and when getting stair data, will add the xaxis as a first column
        To read status for smu, the bit field is:
           bit 0 (  1): A/D converter overflowed.
           bit 1 (  2): Oscillation or force saturation occurred.
           bit 2 (  4): Another unit reached its compliance setting.
           bit 3 (  8): This unit reached its compliance setting.
           bit 4 ( 16): Target value was not found within the search range.
           bit 5 ( 32): Search measurement was automatically stopped.
           bit 6 ( 64): Invalid data is returned. D is not used.
           bit 7 (128): EOD (End of Data).
        """
        full_chs, auto, mode = self._fetch_opt_helper(chs, auto)
        if mode != 'spot':
            try:
                data = self._async_trig_current_data.pop(0)
                if mode == 'stair':
                    x_data = self._x_axis
            except AttributeError:
                raise RuntimeError(self.perror('No data is available. Probably prefer to use readval.'))
            data = data.split(',')
            # _parse_data returns: value, channel, status, type
            ret = map(self._parse_data, data)
            if status:
                ret = map(lambda x: [x[0], x[2]], ret)
            else:
                ret = map(lambda x: x[0], ret)
            ret = np.array(ret)
            if status and mode == 'single':
                ret.shape = (-1, 2)
            elif mode == 'stair':
                N = len(x_data)
                ret.shape = (N, -1)
                if xaxis:
                    ret = np.concatenate([x_data[:, None], ret], axis=1)
                ret = ret.T
            return ret
        # TODO, do run and wait for long TI/TV?
        # The longest measurement time for TI/TV seems to be for PLC mode (100/50 or 100/60) so a max of 2s.
        # so just use ask? for short times and run_and_wait (note that it needs to behave properly under async.)
        ret = []
        for ch, meas in full_chs:
            val_str = self._async_trig_current_data.pop(0)
            func, args, kwargs = self._async_trigger_parsers.pop(0)
            val = func(val_str, *args, **kwargs)
            ret.append(val)
            if status:
                ret.append(self.meas_last_status.get())
        ret = np.array(ret)
        if status:
            ret.shape = (-1, 2)
        return ret

        #self._async_trigger_helper_string = 'XE'
        #self.run_and_wait()
        #res = self._read_after_wait()

    def _ch_helper(self, ch):
        curr_ch = self.current_channel
        if ch is None:
            ch = curr_ch.get()
        else:
            curr_ch.set(ch)
        return self._smu2slot[ch]

    def _level_comp_check_helper(self, slot, fnc, val, comp=False):
        if fnc.mode == 'disabled':
            raise RuntimeError(self.perror('The output is currently disabled.'))
        mode = fnc.mode
        if comp:
            mode = 'current' if mode == 'voltage' else 'voltage'
        if mode == 'current':
            mx = self._i_range_max[slot]
        else:
            mx = self._v_range_max[slot]
        _general_check(val, min=-mx, max=mx)

    def _function_getdev(self, ch=None):
        """ Possible values are 'voltage', 'current', 'disabled'
            ch is the option to select the channel number.
            compliance can be use to set the compliance.
                 It defaults to the current one when staying in the same state.
                 When switching function it is 0.1 mA for voltage and 0.1 V for current.
            Also will update the force/compliance range and polarity according to:
                voltage_range_mode, voltage_range, current_range_mode, current_range
                compliance_polarity_auto_en
        """
        ch = self._ch_helper(ch)
        fnc = self._get_function_cached(ch)
        return fnc.mode
    def _function_setdev(self, val, ch=None, compliance=None):
        ch = self._ch_helper(ch)
        if val == 'disabled':
            self.write('CL %i'%ch)
        else:
            # When channel was off, this always enables voltage mode.
            self.write('CN %i'%ch)
            fnc = self._get_function_cached(ch)
            if compliance is not None:
                fnc.compliance_val = compliance
            if fnc.mode != val:
                fnc.level = 0.
                if compliance is None:
                    if val == 'voltage':
                        fnc.compliance_val = 0.1e-3 # A
                    else: # current
                        fnc.compliance_val = 0.1 # V
            fnc.mode = val
            self._set_level_comp(ch, fnc)
            self._reset_wrapped_cache(self._get_function_cached)
    def _function_checkdev(self, val, ch=None, compliance=None):
        ch = self._ch_helper(ch)
        BaseDevice._checkdev(self.function, val)
        if val != 'disabled' and compliance is not None:
            fnc = dict_improved(mode=val)
            self._level_comp_check_helper(ch, fnc, compliance, comp=True)

    def _level_getdev(self, ch=None):
        """ ch is the option to select the channel number.
            if inactive, it returns 0
        """
        ch = self._ch_helper(ch)
        fnc = self._get_function_cached(ch)
        return fnc.level
    def _level_setdev(self, val, ch=None):
        ch = self._ch_helper(None) # Channel already changed in check
        fnc = self._get_function_cached(ch)
        self._set_level_comp(ch, fnc, level=val)
        self._reset_wrapped_cache(self._get_function_cached)
    def _level_checkdev(self, val, ch=None):
        ch = self._ch_helper(ch)
        fnc = self._get_function_cached(ch)
        self._level_comp_check_helper(ch, fnc, val, comp=False)

    def _compliance_getdev(self, ch=None):
        """ ch is the option to select the channel number.
            a current compliance of 0 is changed to 1 pA.
        """
        ch = self._ch_helper(ch)
        fnc = self._get_function_cached(ch)
        return fnc.compliance_val
    def _compliance_setdev(self, val, ch=None):
        ch = self._ch_helper(None) # Channel already changed in check
        fnc = self._get_function_cached(ch)
        self._set_level_comp(ch, fnc, comp=val)
        self._reset_wrapped_cache(self._get_function_cached)
    def _compliance_checkdev(self, val, ch=None):
        ch = self._ch_helper(ch)
        fnc = self._get_function_cached(ch)
        self._level_comp_check_helper(ch, fnc, val, comp=True)

    def _set_level_comp(self, ch, fnc=None, level=None, comp=None):
        if fnc is None:
            fnc = self._get_function_cached(ch)
        if fnc.mode == 'disabled':
            # We might get here when using range_voltage and company
            # silent abort
            return
        if level is None:
            level = fnc.level
        if comp is None:
            comp = fnc.compliance_val
        mode = fnc.mode
        comp_mode = 'current' if mode == 'voltage' else 'voltage'
        sRange = self._conv_range(mode)
        sCompRange = self._conv_range(comp_mode)
        sCompPolarity = '0' if self.compliance_polarity_auto_en.get() else '1'
        root = dict(voltage='DV', current='DI')[mode]
        #  Use %.7e since instruments chop the resolution instead of rounding it (we get 99.99 instead of 100 sometimes)
        self.write(root+"%i,%s,%.7e,%.7e,%s,%s"%(ch, sRange, level, comp, sCompPolarity, sCompRange))

    def _conv_range(self, signal='current'):
        if signal == 'current':
            rg = self.range_current
        else:
            rg = self.range_voltage
        val = rg.get()
        sVal = rg.choices.tostr(val)
        return sVal

    def get_status(self):
        ret = self.ask('LOP?')
        if not ret.startswith('LOP'):
            raise RuntimeError(self.perror('Problem reading the status'))
        ret = ret[3:]
        ret = ret.split(',')
        conv = {'00':'output off', '01':'force voltage', '02':'force positive current', '03':'force negative current',
                '11':'compliance voltage', '12':'compliance positive current', '13':'compliance negative current'}
        return [conv[s] for s in ret]

    def _active_range_current_getdev(self, ch=None):
        """ ch is the option to select the channel number.
            This is the force or compliance range. Not the measurement one.
        """
        ch = self._ch_helper(ch)
        fnc = self._get_function(ch)
        return fnc.active_Irange

    def _active_range_voltage_getdev(self, ch=None):
        """ ch is the option to select the channel number.
            This is the force or compliance range. Not the measurement one.
        """
        ch = self._ch_helper(ch)
        fnc = self._get_function(ch)
        return fnc.active_Vrange

    def _measIV_helper_get_quest(self, voltage, ch, range, rgdev):
        slot = self._ch_helper(ch) # this set ch for the next entries
        if range is None:
            if self.range_meas_use_compliance_en.get():
                range = 'comp'
            else:
                range = rgdev.get()
        else:
            if not (range == 'comp' or range in rgdev.choices):
                raise ValueError(self.perror('Invalid range selected'))
        quest = 'TV' if voltage else 'TI'
        quest += '%i'%slot
        if range != 'comp':
            quest += ',%s'%rgdev.choices.tostr(range)
        return quest, slot

    def _measIV_helper_ret_val(self, result_str, voltage, slot):
        if result_str is None:
            # This is when we are in async mode.
            result_str = self.read()
        value, channel, status, type = self._parse_data(result_str)
        if type is not None and type != {True:'V', False:'I'}[voltage]:
            raise RuntimeError(self.perror('Read back the wrong signal type'))
        if channel is not None and channel != slot:
            raise RuntimeError(self.perror('Read back the wrong channel'))
        self.meas_last_status.set(status, slot=slot)
        return value

    def _measIV_helper(self, voltage, ch, range, rgdev):
        quest, slot = self._measIV_helper_get_quest(voltage, ch, range, rgdev)
        result_str = self.ask(quest)
        return self._measIV_helper_ret_val(result_str, voltage, slot)

    def _measV_getdev(self, ch=None, range=None):
        """ This returns the spot measurement.
            ch is the option to select the channel number.
            specifying range does not change the other devices so the effect is temporary.
            range will only be effective for the compliance measurement.
                  For force side measurement it always use the force channel range.
            range is range_voltage_meas/range_meas_use_compliance_en if None
               to specify complicance range use: 'comp'
                    otherwise use the same entries as range_voltage_meas
        """
        return self._measIV_helper(voltage=True, ch=ch, range=range, rgdev=self.range_voltage_meas)
    def _measI_getdev(self, ch=None, range=None):
        """ This returns the spot measurement.
            ch is the option to select the channel number.
            specifying range does not change the other devices so the effect is temporary.
            range will only be effective for the compliance measurement.
                  For force side measurement it always use the force channel range.
            range is range_current_meas/range_meas_use_compliance_en if None
               to specify complicance range use: 'comp'
                    otherwise use the same entries as range_voltage_meas
        """
        return self._measIV_helper(voltage=False, ch=ch, range=range, rgdev=self.range_current_meas)


    def _integration_set_helper(self, type='speed', mode=None, time=None):
        prev_result = self._get_avg_time_and_autozero()
        if type == 'speed':
            prev_result = prev_result['high_speed']
            base = 'AIT 0,%s'
        elif type == 'res':
            prev_result = prev_result['high_res']
            base = 'AIT 1,%s'
        elif type == 'pulse':
            prev_result = prev_result['pulse']
            base = 'AIT 2,%s'
        prev_mode = prev_result[0]
        if mode is None:
            mode = prev_mode
        mode_str = self._integ_choices.tostr(mode)
        if time is None:
            # If time is not given, switch only the mode, and use the intrument default time
            if prev_mode != mode:
                self.write(base%mode_str)
                return
            time = prev_result[1]
        if mode == 'time':
            base += ',%.7e'
        else:
            base += ',%i'
        self.write(base%(mode_str, time))

    def conf_general(self, autozero=None, remote_display=None, auto_calib=None):
        """\
        When called with no parameters, returns all settings. Otherwise:
        autozero sets auto_zero_en (this is only for the high resolution adc)
        remote_display sets remote_display_en (not usefull on B1500A)
        auto_calib set calibration_auto_en
        measurement_spot_en sets measurement_spot_en
        """
        para_dict = dict(autozero=self.auto_zero_en,
                         remote_display=self.remote_display_en,
                         auto_calib=self.calibration_auto_en,
                         measurement_spot_en=self.measurement_spot_en)
        params = locals()
        if all(params.get(k) is None for k in para_dict):
            return {k:dev.get() for k, dev in para_dict.items()}
        for k, dev in para_dict.items():
            val = params.get(k)
            if val is not None:
                dev.set(val)

    def conf_ch(self, ch=None, function=None, level=None, range=None, compliance=None, comp_range=None,
                polarity=None, integrator=None, Vmeas_range=None, Imeas_range=None, meas_range_comp=None,
                filter=None, series_r=None, meas_auto_type=None):
        """ when call with no parameters, returns all channels settings,
        when called with only one ch selected, only returns its settings.
        Otherwise modifies the settings that are not None
        range is for the range for the force
        comp_range is the range for the compliance
        Vmeas_range, Imeas_range are the measurement range (only works on compliance side)
        polarity is the value for compliance_polarity_auto_en
        integrator for integration_type
        meas_range_comp is range_meas_use_compliance_en
        filter is output_filter_en
        series_r is series_resistor_en
        meas_auto_type is not used when set_mode mode is set to 'stair'
        """
        para_dict = OrderedDict([('function', self.function),
                                ('range', None),
                                ('level', self.level),
                                ('comp_range', None),
                                ('compliance', self.compliance),
                                ('polarity', self.compliance_polarity_auto_en),
                                ('integrator', self.integration_type),
                                ('Vmeas_range', self.range_voltage_meas),
                                ('Imeas_range', self.range_current_meas),
                                ('meas_range_comp', self.range_meas_use_compliance_en),
                                ('filter', self.output_filter_en),
                                ('series_r', self.series_resistor_en),
                                ('meas_auto_type', self.meas_auto_type)])
        params = locals()
        def adjust_range(func):
            if func == 'current':
                 para_dict['range'] = self.range_current
                 para_dict['comp_range'] = self.range_voltage
            else:
                 para_dict['range'] = self.range_voltage
                 para_dict['comp_range'] = self.range_current
        if all(params.get(k) is None for k in para_dict):
            if ch is None:
                ch = self._valid_ch
            if not isinstance(ch, (list, tuple)):
                ch = [ch]
            result_dict = {}
            for c in ch:
                func = self.function.get(ch=c) # we set ch here
                adjust_range(func)
                result_dict[c] = {k:dev.get() for k, dev in para_dict.items()}
            return result_dict
        else:
            func = params.get('function', None)
            if func is None:
                func = self.function.get(ch=ch)
            else:
                self.current_channel.set(ch)
            adjust_range(func)
            for k, dev in para_dict.items():
                val = params.get(k)
                if val is not None:
                    dev.set(val)

    def conf_integration(self, speed_mode=None, speed_time=None, resol_mode=None, resol_time=None, pulse_mode=None, pulse_time=None):
        u"""
        When called with no parameters, returns all settings. Otherwise:
        speed_mode sets integration_high_speed_mode
        speed_time sets integration_high_speed_time
        resol_mode sets integration_high_resolution_mode
        resol_time sets integration_high_resolution_time
        pulse_mode sets integration_pulse_mode
        pulse_time sets integration_pulse_time

        For 'auto' mode the time of averaging is N*initial_average (N is 1-1023 for spped, 1-127 for resol)
        For 'manual' mode the time of number of averaging is N for speed (1-1023) or
                        N*(80 µs) for resol (1-127)
                    (for speed, the number of reading per sample is >256 Sa/cycle. It is not
                    the 128 that seem to be specified in the datasheet.)
        For 'plc' the averging time is N*plc (N is 1-100).
                speed and pulse takes 128 readings per cycle (16.7 ms (60Hz) or 20 ms(50Hz)), resol takes 1.
        For 'time', you provide the actual measurement time (max of 20 ms). Only valid for speed and pulse.
        """
        # OrderedDict to update mode before time, otherwise times are truncated.
        para_dict = OrderedDict([('speed_mode', self.integration_high_speed_mode),
                         ('speed_time', self.integration_high_speed_time),
                         ('resol_mode', self.integration_high_resolution_mode),
                         ('resol_time', self.integration_high_resolution_time),
                         ('pulse_mode', self.integration_pulse_mode),
                         ('pulse_time', self.integration_pulse_time)])
        params = locals()
        if all(params.get(k) is None for k in para_dict):
            return {k:dev.get() for k, dev in para_dict.items()}
        for k, dev in para_dict.items():
            val = params.get(k)
            if val is not None:
                dev.set(val)

    def set_mode(self, meas_mode=None, channels=None, **kwargs):
        """
        This configures one of the instrument internal measurment mode.
        To use one of these mode, set measurement_spot_en to False.
        if no options are given, it returns the current setting
        meas_mode can be 'single' or 'stair'
        channels is a list of channels to read. When not specified it uses
          the current instrument set, and if never set, all the active channels.
        when using 'stair' extra keywords are passed to conf_staircase
        """
        res = self._get_tn_av_cm_fmt_mm()
        res_mode = res['meas_mode']
        res_slots = [i+1 for i,v in enumerate(res['enabled']) if v and i+1 in self._smu_slots]
        if meas_mode == channels == None:
            meas_mode = res_mode
            channels = [self._slot2smu[c] for c in res_slots]
            ret = dict_improved([('meas_mode', meas_mode), ('channels', channels)])
            if meas_mode == 'stair':
                ret['stair'] = self.conf_staircase()
            return ret
        valid_modes = dict(single=1, stair=16)
        if meas_mode is None:
            meas_mode = res['meas_mode']
        elif meas_mode not in valid_modes:
            raise ValueError(self.perror('Selected an invalide meas_mode'))
        if channels is None:
             channels =  [self._slot2smu[c] for c in res_slots]
        elif not isinstance(channels, (list, tuple, np.ndarray)):
            channels = [channels]
        if any(c not in self._valid_ch for c in channels):
            raise ValueError(self.perror('Invalid channel selection'))
        if len(channels) == 0:
            en_ch = self._get_enabled_state()
            en_slots = [i+1 for i,v in enumerate(en_ch) if v]
            channels =  [self._slot2smu[c] for c in en_slots]
            if len(channels) == 0:
                raise RuntimeError(self.perror('All channels are disabled. You should enable at least one.'))
        slots = [self._smu2slot[c] for c in channels]
        self.write('MM %i,%s'%(valid_modes[meas_mode], ','.join(map(str, slots))))
        N_kwargs = len(kwargs)
        if meas_mode == 'stair' and N_kwargs > 0:
            self.conf_staircase(**kwargs)
        elif N_kwargs > 0:
            raise ValueError(self.perror('extra arguments are invalid'))

    def _calc_x_axis(self, conf):
        if conf.func is None:
            return
        sweep_mode_opt = {'linear':(False, False),
                            'log':(True, False),
                            'linear_updown':(False, True),
                            'log_updown':(True, True)}
        isLog, isUpDown = sweep_mode_opt[conf.mode]
        if isLog:
            x = np.logspace(np.log10(conf.start), np.log10(conf.stop), conf.nsteps)
        else:
            x = np.linspace(conf.start, conf.stop, conf.nsteps)
        if isUpDown:
            x = np.concatenate( (x, x[::-1]) )
        self._x_axis = x

    def conf_staircase(self, ch=None, start=None, stop=None, nsteps=None, mode=None, end_to=None, hold=None, delay=None, Icomp=None, Pcomp=None):
        """
        call with no values to see current setup.
        When setting it uses the current settings of ch for func, range and compliance.
        When reading there are the values that will be used.
        WARNING: you probably don't want to change the settings of ch (func, range, compliance) after calling this function.
        end_to can be 'start' or 'stop'
        mode can be 'linear', 'log', 'linear_updown', 'log_updown'
          updown makes it go from start to stop then from stop to start.
        Icomp is the current compliance. None reuses the previous value. 'empty' will remove the setting.
        Pcomp is the power compliance. None reuses the previous value. 'empty' will remove the setting.
        """
        func = None
        para_val = locals()
        params = ['func', 'ch', 'start', 'stop', 'nsteps', 'mode', 'end_to', 'hold', 'delay', 'Icomp', 'Pcomp']
        params_prev = ['sweep_var', 'sweep_ch', 'start', 'stop', 'steps', 'mode', 'ending_value', 'hold_time', 'delay_time', 'compliance', 'power']
        conf = dict_improved([(p,para_val[p]) for p in params])
        allnone = False
        if all(v is None for v in conf.values()):
            allnone = True
        prev_stair =  self._get_staircase_settings()
        for k in prev_stair.keys():
            if k == 'abort':
                continue
            if k in ['active_range']:
                conf[k] = prev_stair[k]
            else:
                kp = params[params_prev.index(k)]
                if conf[kp] is None:
                    conf[kp] = prev_stair[k]
        if conf['Icomp'] is None:
            conf['Icomp'] = 'empty'
        if conf['Pcomp'] is None:
            conf['Pcomp'] = 'empty'
        if allnone:
            # This will use the previous sweep_var as func if it was available.
            self._calc_x_axis(conf)
            return conf
        del conf['func']
        if any(v is None for v in conf.values()):
            raise ValueError(self.perror('Some values (None) need to be specified: {conf}', conf=conf))
        if conf.ch not in self._valid_ch:
            raise ValueError(self.perror("Invalid ch selection."))
        func = self.function.get(ch=conf.ch)
        if func not in ['voltage', 'current']:
            raise ValueError(self.perror("Selected channel is disabled"))
        else:
            if func == 'voltage':
                base = 'WV'
                minmax = 100.
                rgdev = self.range_voltage
            else:
                base = 'WI'
                minmax = 0.1
                rgdev = self.range_current
        range = rgdev.get()
        sRange = rgdev.choices.tostr(range)
        compliance = self.compliance.get()
        #base += "%i,%i,%s,%.7e,%.7e,%i,%.7e"
        base += "%i,%i,%s,%.7e,%.7e,%i"
        if not (-minmax <= conf.start <= minmax):
            raise ValueError(self.perror("Invalid start."))
        if not (-minmax <= conf.stop <= minmax):
            raise ValueError(self.perror("Invalid stop."))
        if not (1 <= conf.nsteps <= 1001):
            raise ValueError(self.perror("Invalid steps (must be 1-1001)."))
        if not (0 <= conf.hold <= 655.35):
            raise ValueError(self.perror("Invalid hold (must be 0-655.35)."))
        if not (0 <= conf.delay <= 65.535):
            raise ValueError(self.perror("Invalid delay (must be 0-65.535)."))
        mode_ch = {'linear':1, 'log':2, 'linear_updown':3, 'log_updown':4}
        if conf.mode not in mode_ch:
            raise ValueError(self.perror("Invalid mode (must be one of %r)."%mode_ch.keys()))
        end_to_ch = dict(start=1, stop=2)
        mode = mode_ch[conf.mode]
        slot = self._smu2slot[conf.ch]
        base_str = base%(slot, mode, sRange, conf.start, conf.stop, conf.nsteps)
        Pcomp = conf.Pcomp
        Icomp = conf.Icomp
        if conf.Pcomp != 'empty' and Icomp == 'empty':
            Icomp = 20e-3
        if Icomp != 'empty':
            base_str += ',%.7e'%Icomp
        if Pcomp != 'empty':
            base_str += ',%.7e'%Pcomp
        self.write(base_str)
        self.write('WT %.7e,%.7e'%(conf.hold, conf.delay))
        self.write('WM 1,%i'%end_to_ch[conf.end_to])
        conf.func = func
        self._calc_x_axis(conf)


    def _create_devs(self):
        self.empty_buffer() # make sure to empty output buffer
        self._isB1500 = self.idn_split()['model'] in ['B1500A']
        valid_ch, options_dict, smu_slots, Nmax = self._get_unit_conf()
        #self._valid_ch = valid_ch
        #self._Nvalid_ch = len(valid_ch)
        self._valid_all_ch = valid_ch
        self._Nvalid_all_ch = len(valid_ch)
        self._unit_conf = options_dict
        self._smu_slots = smu_slots
        #self._valid_ch = smu_slots
        #self._Nvalid_ch = len(smu_slots)
        self._N_slots = Nmax
        if self._smu_channel_map is None:
            self._smu_channel_map = {s:(i+1) for i,s in enumerate(smu_slots)}
        if len(self._smu_channel_map) != len(smu_slots):
            print "Warning: missing some channels in the smu_channel_map"
        if [s for s in self._smu_channel_map.keys() if s not in smu_slots] != []:
            raise ValueError('smu_channel_map is using slots which are not smus.')
        self._slot2smu = self._smu_channel_map
        self._smu2slot = {c:s for s,c in self._smu_channel_map.items()}
        self._valid_ch = sorted(self._smu_channel_map.values())
        self._Nvalid_ch = len(self._valid_ch)
        smu_chs = self._valid_ch
        smu_slots = self._smu2slot.items()

        self.current_channel = MemoryDevice(smu_chs[0], choices=smu_chs)
        #v_range = ChoiceIndex({0:0., 5:0.5, 20:2., 50:5., 200:20., 400:40., 1000:100.})
        v_range_all = ChoiceIndex({0:0., 20:2., 5:0.5, 20:2., 50:5., 200:20., 400:40., 1000:100., 2000:200.})
        v_range_HRMP = ChoiceIndex({0:0., 5:0.5, 20:2., 50:5., 200:20., 400:40., 1000:100.})
        v_range_HP = ChoiceIndex({0:0., 20:2., 200:20., 400:40., 1000:100., 2000:200.})
        v_range_MC = ChoiceIndex({0:0.,  2:0.2,   20:2.,   200:20.,   400:40.})
        #v_range_meas =  ChoiceIndex({0:0., 5:0.5,   20:2.,   50:5.,   200:20.,   400:40.,   1000:100.,
        #                                  -5:-0.5, -20:-2., -50:-5., -200:-20., -400:-40., -1000:-100.})
        v_range_meas_HRMP =  ChoiceIndex({0:0., 5:0.5,   20:2.,   50:5.,   200:20.,   400:40.,   1000:100.,
                                               -5:-0.5, -20:-2., -50:-5., -200:-20., -400:-40., -1000:-100.})
        v_range_meas_HP =  ChoiceIndex({0:0.,  20:2.,   200:20.,   400:40.,   1000:100.,   2000:200.,
                                              -20:-2., -200:-20., -400:-40., -1000:-100., -2000:-200.})
        v_range_meas_MC =  ChoiceIndex({0:0.,  2:0.2,   20:2.,   200:20.,   400:40.,
                                              -2:-0.2, -20:-2., -200:-20., -400:-40.})
        v_range_meas_all =  ChoiceIndex({0:0., 5:0.5,   20:2.,   50:5.,   200:20.,   400:40.,   1000:100.,   2000:200.,
                                              -5:-0.5, -20:-2., -50:-5., -200:-20., -400:-40., -1000:-100., -2000:-200.})
        self._v_range_meas_choices = v_range_meas_all
        sel = {'HRSMU':v_range_HRMP, 'MPSMU':v_range_HRMP, 'HPSMU':v_range_HP, 'MCSMU':v_range_MC}
        v_range = ChoiceDevDep(self.current_channel, {ch:sel[self._unit_conf[slot][1]] for ch,slot in smu_slots})
        sel = {'HRSMU':v_range_meas_HRMP, 'MPSMU':v_range_meas_HRMP, 'HPSMU':v_range_meas_HP, 'MCSMU':v_range_meas_MC}
        v_range_meas = ChoiceDevDep(self.current_channel, {ch:sel[self._unit_conf[slot][1]] for ch,slot in smu_slots})
        sel = {'HRSMU':100., 'MPSMU':100., 'HPSMU':200., 'MCSMU':40.}
        self._v_range_max = {slot:sel[self._unit_conf[slot][1]] for ch,slot in smu_slots}
        # E5287A+E5288A ASU has: 8:1e-12
        # E5287A has: 9:10e-12, 10: 100e-12
        # E5280B/E5281B/E5287A has: 11:1e-9, 12:10e-9
        # E5291A has: 20:200e-3
        #i_range = ChoiceIndex({0:0., 11:1e-9, 12:10e-9, 13:100e-9, 14:1e-6, 15:10e-6, 16:100e-6, 17:1e-3, 18:10e-3, 19:100e-3})
        i_range_all = ChoiceIndex({0:0., 8:1e-12, 9:10e-12, 10:100e-12, 11:1e-9, 12:10e-9, 13:100e-9, 14:1e-6, 15:10e-6, 16:100e-6, 17:1e-3, 18:10e-3, 19:100e-3, 20:1.})
        i_range_HR = ChoiceIndex({0:0., 9:10e-12, 10:100e-12, 11:1e-9, 12:10e-9, 13:100e-9, 14:1e-6, 15:10e-6, 16:100e-6, 17:1e-3, 18:10e-3, 19:100e-3})
        i_range_MP = ChoiceIndex({0:0., 11:1e-9, 12:10e-9, 13:100e-9, 14:1e-6, 15:10e-6, 16:100e-6, 17:1e-3, 18:10e-3, 19:100e-3})
        i_range_HP = ChoiceIndex({0:0., 11:1e-9, 12:10e-9, 13:100e-9, 14:1e-6, 15:10e-6, 16:100e-6, 17:1e-3, 18:10e-3, 19:100e-3, 20:1.})
        i_range_MC = ChoiceIndex({0:0., 15:10e-6, 16:100e-6, 17:1e-3, 18:10e-3, 19:100e-3, 20:1.})
        #i_range_meas = ChoiceIndex({0:0., 11:1e-9,   12:10e-9,   13:100e-9,   14:1e-6,   15:10e-6,   16:100e-6,   17:1e-3,   18:10e-3,   19:100e-3,
        #                                 -11:-1e-9, -12:-10e-9, -13:-100e-9, -14:-1e-6, -15:-10e-6, -16:-100e-6, -17:-1e-3, -18:-10e-3, -19:-100e-3})
        i_range_meas_HR = ChoiceIndex({0:0.,  9:10e-12,   10:100e-12,   11:1e-9,   12:10e-9,   13:100e-9,   14:1e-6,   15:10e-6,   16:100e-6,   17:1e-3,   18:10e-3,   19:100e-3,
                                             -9:-10e-12, -10:-100e-12, -11:-1e-9, -12:-10e-9, -13:-100e-9, -14:-1e-6, -15:-10e-6, -16:-100e-6, -17:-1e-3, -18:-10e-3, -19:-100e-3})
        i_range_meas_MP = ChoiceIndex({0:0., 11:1e-9,   12:10e-9,   13:100e-9,   14:1e-6,   15:10e-6,   16:100e-6,   17:1e-3,   18:10e-3,   19:100e-3,
                                            -11:-1e-9, -12:-10e-9, -13:-100e-9, -14:-1e-6, -15:-10e-6, -16:-100e-6, -17:-1e-3, -18:-10e-3, -19:-100e-3})
        i_range_meas_HP = ChoiceIndex({0:0., 11:1e-9,   12:10e-9,   13:100e-9,   14:1e-6,   15:10e-6,   16:100e-6,   17:1e-3,   18:10e-3,   19:100e-3,   20:1.,
                                            -11:-1e-9, -12:-10e-9, -13:-100e-9, -14:-1e-6, -15:-10e-6, -16:-100e-6, -17:-1e-3, -18:-10e-3, -19:-100e-3, -20:-1.})
        i_range_meas_MC = ChoiceIndex({0:0., 15:10e-6,   16:100e-6,   17:1e-3,   18:10e-3,   19:100e-3,   20:1.,
                                            -15:-10e-6, -16:-100e-6, -17:-1e-3, -18:-10e-3, -19:-100e-3, -20:-1.})
        i_range_meas_all = ChoiceIndex({0:0.,  9:10e-12,   10:100e-12,   11:1e-9,   12:10e-9,   13:100e-9,   14:1e-6,   15:10e-6,   16:100e-6,   17:1e-3,   18:10e-3,   19:100e-3,   20:1.,
                                              -9:-10e-12, -10:-100e-12, -11:-1e-9, -12:-10e-9, -13:-100e-9, -14:-1e-6, -15:-10e-6, -16:-100e-6, -17:-1e-3, -18:-10e-3, -19:-100e-3, -20:-1.})
        self._i_range_meas_choices = i_range_meas_all
        sel = {'HRSMU':i_range_HR, 'MPSMU':i_range_MP, 'HPSMU':i_range_HP, 'MCSMU':i_range_MC}
        i_range = ChoiceDevDep(self.current_channel, {ch:sel[self._unit_conf[slot][1]] for ch,slot in smu_slots})
        sel = {'HRSMU':i_range_meas_HR, 'MPSMU':i_range_meas_MP, 'HPSMU':i_range_meas_HP, 'MCSMU':i_range_meas_MC}
        i_range_meas = ChoiceDevDep(self.current_channel, {ch:sel[self._unit_conf[slot][1]] for ch,slot in smu_slots})
        sel = {'HRSMU':100e-3, 'MPSMU':100e-3, 'HPSMU':1., 'MCSMU':1.}
        self._i_range_max = {slot:sel[self._unit_conf[slot][1]] for ch,slot in smu_slots}

        def MemoryDevice_ch(*args, **kwargs):
            args = (self._set_level_comp,) + args
            kwargs['nch'] = Nmax # Uses internal array of slots
            return MemoryDevice_update(*args, **kwargs)

        self.range_voltage = MemoryDevice_ch(0., choices=v_range, doc="""
                                          This is for compliance/force. Not for measurement.
                                          It is a MemoryDevice (so cannot be read from instrument.)
                                          See active_range_voltage to see what the instrument is using.
                                          0. means auto range.
                                          Otherwise the range set is a minimum one. It will use higher ones if necessary.
                                          """)
        self.range_current = MemoryDevice_ch(0., choices=i_range, doc="""
                                          This is for compliance/force. Not for measurement.
                                          It is a MemoryDevice (so cannot be read from instrument.)
                                          See active_range_current to see what the instrument is using.
                                          0. means auto range.
                                          Otherwise the range set is a minimum one. It will use higher ones if necessary.
                                          """)
        self.compliance_polarity_auto_en = MemoryDevice_ch(True, choices=[True, False],
                                                        doc="""
                                                        When True, polarity of compliance is the same as force (0 force is positive).
                                                        When False, the polarity is the one set by the compliance (Described as Manual mode
                                                        in instrument manual, see figures 6.1, 6.2 and 6.3)
                                                        It is a MemoryDevice (so cannot be read from instrument.)
                                                        """)

        self.range_current_meas = CommonDevice(self._get_meas_ranges,
                                               lambda v, ch: v[ch-1][0],
                                               'RI {ch},{val}', choices=i_range_meas, ch_mode=True,
                                               doc="""\
                                               Negative ranges are fixed range. Positive ranges are limited autoranging ones (can
                                               autorange to a larger value but will not gol lower.)
                                               See also range_meas_use_compliance_en. When that is enabled it will override this range on spot measurement
                                               and instead use the compliance range.
                                               This does not apply on the force channel. Measurement then use the force range.""")
        self.range_voltage_meas = CommonDevice(self._get_meas_ranges,
                                               lambda v, ch: v[ch-1][1],
                                               'RV {ch},{val}', choices=v_range_meas, ch_mode=True,
                                               doc="""\
                                               Negative ranges are fixed range. Positive ranges are limited autoranging ones (can
                                               autorange to a larger value but will not gol lower.)
                                               See also range_meas_use_compliance_en. When that is enabled it will override this range on spot measurement
                                               and instead use the compliance range.
                                               This does not apply on the force channel. Measurement then use the force range.""")
        self.range_meas_use_compliance_en = MemoryDevice_update(None, False, choices=[True, False], nch=Nmax)

        self.remote_display_en = CommonDevice(self._get_display_settings,
                                              lambda v: v['remote_dsp_en'],
                                              'RED {val}', type=bool)
        self.calibration_auto_en = CommonDevice(self._get_tn_av_cm_fmt_mm,
                                                lambda v: v['auto_cal_en'],
                                                'CM{val}', type=bool)
        self.series_resistor_en = CommonDevice(self._get_series_resistor_en,
                                               lambda v, ch: v[ch-1],
                                               'SSR{ch},{val}', type=bool, ch_mode=True,
                                               doc=""" When enabled, add a ~1M series resitor to the output ch""")
        self.output_filter_en = CommonDevice(self._get_filters,
                                             lambda v, ch: v[ch-1],
                                             'FL{val},{ch}', type=bool, ch_mode=True)
        self.integration_type = CommonDevice(self._get_ad_converter_highres_en,
                                             lambda v, ch: v[ch-1],
                                             'AAD {ch},{val}', ch_mode=True,
                                             choices=ChoiceIndex(['speed', 'resolution']))
        self.auto_zero_en = CommonDevice(self._get_avg_time_and_autozero,
                                         lambda v: v['autozero_en'],
                                         'AZ {val}', type=bool)
        self.meas_auto_type = CommonDevice(self._get_meas_operation_mode,
                                           lambda v, ch: v[ch-1],
                                           'CMM {ch},{val}', ch_mode=True,
                                           choices=ChoiceIndex(['compliance', 'current', 'voltage', 'force']))

        hr_integ = ChoiceIndex(['auto', 'manual', 'plc'])
        if self._isB1500:
            self._integ_choices = ChoiceIndex(['auto', 'manual', 'plc', 'time'])
            pulse_integ =  ChoiceIndex(['plc', 'time'])
        else:
            self._integ_choices = hr_integ
        self.integration_high_speed_mode = CommonDevice(self._get_avg_time_and_autozero,
                                                             lambda v: v['high_speed'][0],
                                                             lambda self, val: self.instr._integration_set_helper(type='speed', mode=val),
                                                             choices=self._integ_choices)
        self.integration_high_resolution_mode = CommonDevice(self._get_avg_time_and_autozero,
                                                             lambda v: v['high_res'][0],
                                                             lambda self, val: self.instr._integration_set_helper(type='res', mode=val),
                                                             choices=hr_integ)
        self.integration_high_speed_time = CommonDevice(self._get_avg_time_and_autozero,
                                                             lambda v: v['high_speed'][1],
                                                             lambda self, val: self.instr._integration_set_helper(type='speed', time=val),
                                                             choices=ChoiceDevDep(self.integration_high_speed_mode, dict(auto=ChoiceLimits(1, 1023, int), manual=ChoiceLimits(1, 1023, int), plc=ChoiceLimits(1, 100, int), time=ChoiceLimits(2e-6, 20e-3, float))),
                                                             setget=True,
                                                             doc=""" allowed values depends on integration_high_speed_mode """)
        self.integration_high_resolution_time = CommonDevice(self._get_avg_time_and_autozero,
                                                             lambda v: v['high_res'][1],
                                                             lambda self, val: self.instr._integration_set_helper(type='res', time=val),
                                                             choices=ChoiceDevDep(self.integration_high_resolution_mode, dict(auto=ChoiceLimits(1, 127, int), manual=ChoiceLimits(1, 127, int), plc=ChoiceLimits(1, 100, int))),
                                                             setget=True,
                                                             doc=""" allowed values depends on integration_high_resolution_mode """)
        if self._isB1500:
            self.integration_pulse_mode = CommonDevice(self._get_avg_time_and_autozero,
                                                                 lambda v: v['pulse'][0],
                                                                 lambda self, val: self.instr._integration_set_helper(type='pulse', mode=val),
                                                                 choices=self._integ_choices)
            self.integration_pulse_time = CommonDevice(self._get_avg_time_and_autozero,
                                                                 lambda v: v['pulse'][1],
                                                                 lambda self, val: self.instr._integration_set_helper(type='pulse', time=val),
                                                                 choices=ChoiceDevDep(self.integration_pulse_mode, dict(plc=ChoiceLimits(1, 100, int), time=ChoiceLimits(2e-6, 20e-3, float))),
                                                                 doc=""" allowed values depends on integration_pulse_mode """)

        self.measurement_spot_en = MemoryDevice(True, choices=[True, False],
                                                doc="""
                                                With this False, you need to use set_mode
                                                """)

        self._devwrap('function', choices=['voltage', 'current', 'disabled'])
        self._devwrap('level', setget=True)
        self._devwrap('compliance', setget=True)
        self._devwrap('active_range_current')
        self._devwrap('active_range_voltage')
        self._devwrap('measV', autoinit=False, trig=True)
        self.meas_last_status = MemoryDevice_update(None, None, nch=Nmax, doc='See readval/fetch for the description of the bit field')
        self._devwrap('measI', autoinit=False, trig=True)
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval

        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

    @cache_result
    def _get_enabled_state(self):
        "Returns the enabled state of each channels"
        N = self._N_slots
        ret = self.ask("*LRN? 0")
        state = [False]*N
        if ret == 'CL':
            pass
        elif ret.startswith('CN'):
            for i_s in ret[2:].split(','):
                state[int(i_s)-1] = True
        else:
            raise RuntimeError(self.perror('Unexpected format for get_enabled_state'))
        return state

    @cache_result
    def _get_function_cached(self, ch):
        return self._get_function(ch)

    # Don't use cache here because active_Vrange, active_Irange can change.
    #@cache_result
    def _get_function(self, ch):
        ret = self.ask('*LRN? %i'% ch)
        d = dict_improved()
        if int(ret[2]) != ch:
            raise RuntimeError(self.perror('Unexpected channel in get_function'))
        mode = ret[:2]
        if mode == 'DV':
            # Vrange, voltage, Icomp, Icomp_pol, Irange. Icomp_pol is 0 when both voltage and Icomp have same polarity.
            #                                            That is not the way we want to use it, so do not use it.
            # Both ranges are the active ones (never autorange or fix)
            vs = self._parse_block_helper(ret, 'DV', [int, int, float, float, int, int])[1:]
            d.mode = 'voltage'
            d.level = vs[1]
            d.active_Vrange = vs[0]/10.
            d.active_Irange = 10**(vs[4]-11-9)
            d.compliance_val = vs[2]
            d.polarity = vs[3]
        elif mode == 'DI':
            # Irange, current, Vcomp, Vcomp_pol, Vrange. Vcomp behaves similarly to Icomp (see above).
            # Both ranges are the active ones (never autorange or fix)
            vs = self._parse_block_helper(ret, 'DI', [int, int, float, float, int, int])[1:]
            d.mode = 'current'
            d.level = vs[1]
            d.active_Vrange = vs[4]/10.
            d.active_Irange = 10**(vs[0]-11-9)
            d.compliance_val = vs[2]
            d.polarity = vs[3]
        elif mode == 'CL':
            d.mode = 'disabled'
            d.level = 0
            d.compliance_val = 0
            d.active_Vrange = 0.
            d.active_Irange = 0.
        else:
            raise RuntimeError(self.perror('Unexpected mode in get_function'))
        return d

    @cache_result
    def _get_filters(self):
        "Returns the filter enabled state of each channels"
        N = self._N_slots
        ret = self.ask("*LRN? 30")
        state = [False]*N
        if ret == 'FL0':
            pass
        elif ret == 'FL1':
            state = [True]*N
        else:
            r = ret.split(';')
            if not (r[0].startswith('FL0,') and r[1].startswith('FL1,')):
                raise RuntimeError(self.perror('Unexpected filter structure data'))
            state = [None]*N
            for i in [int(v) for v in r[0].split(',')[1:]]:
                if state[i-1] is not None:
                    raise RuntimeError(self.perror('Unexpected filter date (repeat)'))
                state[i-1]  = False
            for i in [int(v) for v in r[1].split(',')[1:]]:
                if state[i-1] is not None:
                    raise RuntimeError(self.perror('Unexpected filter date (repeat)'))
                state[i-1]  = True
            for ch in self._smu_slots:
                i = ch-1
                if state[i] is None:
                    raise RuntimeError(self.perror('Unexpected missing entry for _get_filters'))
        return state

    def _parse_block_helper(self, root_string, basename, types=[int], Nv_min=None):
        Nv = len(types)
        if not root_string.startswith(basename):
            raise RuntimeError(self.perror('Unexpected entry start for %s (%s)'%(basename, root_string)))
        r = root_string[len(basename):]
        vs = r.split(',')
        if Nv_min is None:
            Nv_min = Nv
        if not (Nv_min <= len(vs) <= Nv):
            raise RuntimeError(self.perror('Invalid number of values for %s (%s)'%(basename, root_string)))
        vals = [types[i](v) for i,v in enumerate(vs)]
        return vals

    def _get_values_helper(self, lrn_type, basename, types=[int], Nv_min=None, skip_empty=False):
        """ This parses entries like (for basename='AA', types=[float, int])
                AA1,1.,3;AA2,5.,6;AA3...
            with the first integer after AA the ch num
            if basename=['AA', 'BB'] it parses
                AA1,a1;BB1,b1;AA2,a2;BB2,b2 ...
            and returns result as [[a1,b1], [a1,b2], ...]
        """
        Nch = self._N_slots
        Nvalid_ch = self._Nvalid_ch
        if not isinstance(basename, (list, tuple)):
            basename = [basename]
        Nbasename = len(basename)
        basename = basename*Nvalid_ch
        base_offsets = list(range(Nbasename))*Nvalid_ch
        N = Nbasename*Nch
        Nvalid = Nbasename*Nvalid_ch
        state = [None]*N
        one_val = False
        if not isinstance(types, (list, tuple)):
            types = [types]
            one_val = True
        types = [int] + types # first entry is ch number
        Nv = len(types)
        if Nv_min is None:
            Nv_min = Nv
        else:
            Nv_min += 1
        ret = self.ask("*LRN? %i"%lrn_type)
        rs = ret.split(';')
        if skip_empty:
            rs = [r for r in rs if r != '']
        if len(rs) != Nvalid:
            raise RuntimeError(self.perror('Invalid number of entries for %i'%lrn_type))
        for r, b, off in zip(rs, basename, base_offsets):
            vals = self._parse_block_helper(r, b, types, Nv_min)
            ch = vals[0]
            i = (ch-1)*Nbasename + off
            if state[i] is not None:
                raise RuntimeError(self.perror('Unexpected repeat entry for %i'%lrn_type))
            state[i] = vals[1] if one_val else vals[1:]
        for ch in self._smu_slots:
            i = ch-1
            b = i*Nbasename
            if None in state[b:b+Nbasename]:
                raise RuntimeError(self.perror('Unexpected missing entry for %i'%lrn_type))
        if Nbasename > 1:
            state = [[state[i*Nbasename+j] for j in range(Nbasename)] for i in range(Nch)]
        return state

    def _only_valid_ch(self, list):
        return [l for i,l in enumerate(list) if i+1 in self._smu_slots]

    def _apply_ch_changes(self, quant_ch, states):
        for i, state in enumerate(states):
            ch = i+1
            self.setValue(self._quant_ch(quant_ch, ch), state)

    @cache_result
    def _get_series_resistor_en(self):
        states = self._get_values_helper(53, 'SSR', lambda s: bool(int(s)))
        return states

    @cache_result
    def _get_current_autorange(self):
        autorg = self._get_values_helper(54, 'RM', [int, int], Nv_min=1)
        return autorg
        # This is not used or handled.

    @cache_result
    def _get_ad_converter_highres_en(self): # vs high_speed
        option_type = self.integration_type.choices
        if self._isB1500:
            # the second AAD is for pulse and is always 2
            # Also the current firmware returns ;; between groups:
            #  'AAD3,0;AAD3,2;;AAD4,0;AAD4,2;;AAD5,0;AAD5,2;;AAD6,0;AAD6,2;'
            states = self._get_values_helper(55, ['AAD', 'AAD'], skip_empty=True)
            states = [option_type(s[0][0]) if s[0] is not None else None for s in states]
        else:
            states = self._get_values_helper(55, 'AAD', option_type)
        return states

    @cache_result
    def _get_meas_operation_mode(self):
        choices =  self.meas_auto_type.choices
        modes = self._get_values_helper(46, 'CMM', choices)
        return modes

    @cache_result
    def _get_meas_ranges(self):
        ranges = self._get_values_helper(32, ['RI', 'RV'], lambda x: x) # keep as string
        ich = lambda v: self._i_range_meas_choices(v) if v is not None else None
        vch = lambda v: self._v_range_meas_choices(v) if v is not None else None
        ranges = [[ich(i), vch(v)] for i,v in ranges]
        return ranges

    @cache_result
    def _get_avg_time_and_autozero(self):
        ret = self.ask("*LRN? 56")
        rs = ret.split(';')
        if self._isB1500:
            N = 4
            az = 3
        else:
            N = 3
            az = 2
            pulse = ['time', 0.]
        if len(rs) != N:
            raise RuntimeError(self.perror('Invalid number of elemnts for lrn 56'))
        mode_type = self._integ_choices
        # TODO float for mode time otherwise int
        high_speed = self._parse_block_helper(rs[0], 'AIT0,', [mode_type, float]) # mode(0=auto, 1=manual, 2=PLC), time
        high_res = self._parse_block_helper(rs[1], 'AIT1,', [mode_type, float]) # mode(0=auto, 1=manual, 2=PLC), time
        if self._isB1500:
            pulse = self._parse_block_helper(rs[2], 'AIT2,', [mode_type, float])
        autozero_en = self._parse_block_helper(rs[az], 'AZ', [lambda s: bool(int(s))])
        return dict(high_speed=high_speed,
                    high_res=high_res,
                    autozero_en=autozero_en[0],
                    pulse=pulse)

    @cache_result
    def _get_tn_av_cm_fmt_mm(self):
        ret = self.ask("*LRN? 31")
        rs = ret.split(';')
        N = len(rs)
        if not (4 <= len(rs) <= 5):
            raise RuntimeError(self.perror('Invalid number of elements for lrn 31'))
        trigger = self._parse_block_helper(rs[0], 'TM', [int])
        average_high_speed_adc = self._parse_block_helper(rs[1], 'AV', [int, int], Nv_min=1) # number, mode
        auto_cal_en = self._parse_block_helper(rs[2], 'CM', [lambda s: bool(int(s))])
        outfmt = self._parse_block_helper(rs[3], 'FMT', [int, int]) # format, mode
        enabled = [False]*self._N_slots
        if N == 5:
            mm_modes = {1:'single', 2:'staircase', 3:'pulsed spot', 4:'pulsed sweep', 5:'staircase pulsed bias',
                        9:'quasi-pulsed spot', 14:'linear search', 15:'binary search', 16:'stair'}
            mm = self._parse_block_helper(rs[4], 'MM', [int]*9, Nv_min=1) # mode, chnum, chnum ... (max of 8 chnum)
            meas_mode = mm_modes[mm[0]]
            for m in mm[1:]:
                enabled[m-1] = True
        else:
            meas_mode = 'none'
            mm = None
        return dict(meas_mode=meas_mode,
                    trigger=trigger[0],
                    average_high_speed_adc=average_high_speed_adc,
                    auto_cal_en=auto_cal_en[0],
                    outfmt=outfmt,
                    enabled=enabled)
        # trigger, outfmt not handled. average_high_speed_adc not handled but same as get_avg_time_and_autozero

    @cache_result
    def _get_display_settings(self):
        ret = self.ask("*LRN? 61")
        rs = ret.split(';')
        if len(rs) != 8:
            raise RuntimeError(self.perror('Invalid number of elements for lrn 61'))
        bool_int = lambda s: bool(int(s))
        remote_dsp_en = self._parse_block_helper(rs[0], 'RED', [bool_int])
        front_panel_lock_en = self._parse_block_helper(rs[1], 'KLC', [bool_int])
        display_scientific_en = self._parse_block_helper(rs[2], 'DFM', [bool_int]) # False is Engineering
        source_display_line1 = self._parse_block_helper(rs[3], 'SPA1,', [int]) # 1=source, 2=compliance, 3=Volt meas range, 4=current meas range, 5: last error
        source_display_line2 = self._parse_block_helper(rs[4], 'SPA2,', [int]) # 1=source, 2=compliance, 3=Volt meas range, 4=current meas range, 5: last error
        measurement_display = self._parse_block_helper(rs[5], 'MPA', [int]) # 1=compliance side, 2=compliance and force, 3=resistance, 4=power
        source_ch_disp = self._parse_block_helper(rs[6], 'SCH', [int])
        measurement_ch_disp = self._parse_block_helper(rs[7], 'MCH', [int])
        return dict(remote_dsp_en=remote_dsp_en[0],
                    front_panel_lock_en=front_panel_lock_en[0],
                    display_scientific_en=display_scientific_en[0],
                    source_display_line1=source_display_line1[0],
                    source_display_line2=source_display_line2[0],
                    measurement_display=measurement_display[0],
                    source_ch_disp=source_ch_disp[0],
                    measurement_ch_disp=measurement_ch_disp[0])

    @cache_result
    def _get_staircase_settings(self):
        ret = self.ask("*LRN? 33")
        rs = ret.split(';')
        if not (2 <= len(rs) <= 3):
            raise RuntimeError(self.perror('Invalid number of elements for lrn 33'))
        abort, end = self._parse_block_helper(rs[0], 'WM', [int, int])
        delays = self._parse_block_helper(rs[1], 'WT', [float]*5)
        if any(delays[2:]):
            raise RuntimeError('Did not get expected 0. for Sdelay, Tdelay, Mdelay')
        ret_dict = dict_improved(ending_value = {1:'start', 2:'end'}[end],
                        hold_time = delays[0],
                        delay_time = delays[1],
                        abort=abort)
        if len(rs) == 3:
            if rs[2][1] == 'I':
                stair = self._parse_block_helper(rs[2], 'WI', [int, int, int, float, float, int, float, float], Nv_min=6)
                ch = stair[0]
                ret_dict['sweep_var'] = 'current'
                ret_dict['active_range'] = 10**(stair[2]-11-9)
                ret_dict['compliance'] = stair[6]
                ret_dict['power'] = stair[7]
            else:
                stair = self._parse_block_helper(rs[2], 'WV', [int, int, int, float, float, int, float, float], Nv_min=6)
                ch = stair[0]
                ret_dict['sweep_var'] = 'voltage'
                ret_dict['active_range'] = stair[2]/10.
            comp = 'empty' if len(stair) < 7 else stair[6]
            power = 'empty' if len(stair) < 8 else stair[7]
            mode_opt = {1:'linear', 2:'log', 3:'linear updown', 4:'log updown'}
            ret_dict.update(dict(sweep_ch = ch,
                                 mode = mode_opt[stair[1]],
                                 start = stair[3],
                                 stop = stair[4],
                                 steps =  stair[5],
                                 power = power,
                                 compliance = comp))
        else:
            ret_dict['sweep_var'] = None
        return ret_dict

    _status_letter_2_num = dict(N=0, T=4, C=8, V=1, X=2, G=16, S=32)
    def _parse_data(self, data_string):
        """ Automatically parses the data into value, channel, status, type """
        # FMT12 and FMT22 seem to be the same
        if data_string[2] in 'VIT': # FMT1 or FMT5 (12 digits data), or FMT11 or FMT15 (13 digits data)
            status = data_string[0] # W/E E is for last sweep step data for source,  N<G<S<T<C<V<X<F  (pulse is  N<T<C<V<X<G or S)
                # N: No error, T: Another channel compliance, C: This channel Compliance, V: over range
                # X: channel oscillating, G: search not found or over time on quasi-pulse, S: search stopped or quasi-pulse too slow
            status = self._status_letter_2_num[status]
            channel = data_string[1] # A-H = 1-8
            type = data_string[2]  # V/I/T for Volt, Current, Time
            value = float(data_string[3:])
        elif data_string[4] in 'VvIiTZz': # FMT21 or FMT25
            if data_string.startswith('  '):
                status = 128 if data_string[2] == 'E' else 0 # W/E E is for last sweep step data for source
            else:
                status = int(data_string[:3]) # Status, 1=A/D overflow(V), 2:some unit oscillating(X), 4: Another unit reached compliance(T), 8: This unit reached compliance(C)
                # 16: Target not found (G), 32: Search stopped (S), 64: Invalid data (), 128: End of data
            channel = data_string[3] # A-H = 1-8, V=GNDU, Z=extra or TSQ or invalid
            type = data_string[4] # V/v/I/i/T/Z/z is Volt/Volt source/Current/Current source/Time/Invalid/Invalid
            value = float(data_string[5:])
        else: # FMT2 (12 digits), FMT12 or FMT22 (13 digits)
            status = 0
            channel = None
            type = None
            value = float(data_string)
        if channel is not None and channel in 'ABCDEFGH':
            channel = ord(channel) - ord('A') + 1
        return value, channel, status, type

    def _get_unit_conf(self):
        # obtain list of model_slot_1, rev_slot_1; model_slot_2m rev_slot_2
        #   like 'E5281B,0;E5281B,0;E5281B,0;E5281B,0;0,0;0,0;0,0;0,0'
        ret = self.ask('UNT?')
        rs = ret.split(';')
        Nmax = len(rs) # should be 8 for E5270B mainframe, 10 for B1500A
        options = [r.split(',')for r in rs]
        options_en = [o[0] != '0' for o in options]
        options_dict = {}
        valid_ch = []
        smu_slots = []
        N = 0
        for i, opt in enumerate(options):
            if options_en[i]:
                N += 1
                ch = i+1
                valid_ch.append(ch)
                o = opt[0]
                if o in ['E5280B', 'B1510A']:
                    t = 'HPSMU'
                elif o in ['E5281B', 'B1511A', 'B1511B']:
                    t = 'MPSMU'
                elif o in ['E5287A', 'B1517A']:
                    t = 'HRSMU'
                elif o in ['B1520A']:
                    t = 'MFCMU'
                elif o in ['B1514A']:
                    t = 'MCSMU'
                elif o in ['B1525A']:
                    t = 'HVSPGU'
                elif o in ['B1530A']:
                    t = 'WGFMU'
                else:
                    t = 'UNKNOWN'
                options_dict[ch] = (opt, t)
                if t in ['HPSMU', 'MPSMU', 'HRSMU']:
                    smu_slots.append(ch)
            o = opt[0]
        return valid_ch, options_dict, smu_slots, Nmax



# When switching from DI to DV, The compliance is required
# when switching from off to DI/DV the outputs first need to be enabled.

# *LRN? 0 return CL or CN1,2,3,4 or CN1,2,3
# *LRN? 1 returns DV1,200,+00.0000E+00,+100.000E-06,0,16 or DI... or CL1
#   ..4
# *LRN? 30 returns FL0 or FL1 or FL0,1,2,3;FL1,4
# *LRN? 31 returns TM1;AV1,0;CM1;FMT1,0;MM16,1
# *LRN? 32 returns RI1,0;RV1,0;RI2,0;RV2,0;RI3,0;RV3,0;RI4,0;RV4,0
#   33 staircase, 34 pules, 37 quasi-pulse,  38 is io ports, 40 channel mapping (ACH), 50 linear search, 51 binary search, 58 is trigger, 59 multi channel sweep
#   61 is display settings, 62,64,64 ASU setting (atto),
# *LRN? 46 returns CMM1,0;CMM2,0;CMM3,0;CMM4,0
# *LRN? 53 returns SSR1,0;SSR2,0;SSR3,0;SSR4,0
# *LRN? 54 returns RM1,1,50;RM2,1,50;RM3,1,50;RM4,1,50
# *LRN? 55 returns AAD1,1;AAD2,1;AAD3,1;AAD4,1
# *LRN? 56 returns AIT0,0,1;AIT1,0,6;AZ0
# *LRN? 57 returns WAT1,1.0,0.0000;WAT2,1.0,0.0000
# *LRN? 60 returns TSC0

# When doing the calibration, the channels are openned and the settings are changed.
# The output should be left floating. Voltage spikes of around +-400 mV  (100 us to 1 ms long) can be observed during calibration.
# Calibration is automatically started after every 30 min once all channels are off (unless autocal is off)

#  AV and AIT0 have the same information. Setting one changes the other.
# TV and TI use the high-resolution or high-speed depending on the settings of the channel

# To be able to use High-speed measurement in parallel:
#  - need to use Measurement mode 16 (multi channel sweep) (it does not work with the others like spot=1 or staircase=2) (MM)
#  - need to set the measurement range for all the channels to read to a fixed range (not auto nor limited auto) (RV or RI)
#  - need to use high-speed measurement (not high-resolution)  (AAD)
# Example: AAD1,0; RI1,-14; RI2,14; AAD2,0; MM 16,1,2; WV1,1,0,.1,.2,1
#    Note that the above sets a sweep with just one point. It stays at the point after if WM post is 1. It goes to last value if it is 2.
#    Even for up/down (WV1,4), WM post=1,2 use start,stop value so here .1, .2 at the end.
#    Up/down repeats the last point (so for 3 pts sweep does: A,B,C,C,B,A)
#
# For timing use WT hold,delay,[Sdelay,[Tdelay,[Mdelay]]]
#  for staircase or multi channel sweep:
#     hold: delay before first step (forces first point and then waits this time)
#             This first setup trigger is sent after this.
#     delay: time between force start and measurement start
#     Sdelay: delay after start measurement before next force start
#               if measurement is longer than Sdelay, Start force immediately after measurement
#  The next two are for triggers (no effect if triggers are not used).
#     Tdelay: delay between step output setup and outputing a step output setup completion trigger
#     Mdelay: delay between receiving a step measurement trigger and starting a step measurement.
#
# Also for timing is WAT1,N, offset and WAT2, N, offset
#    where the wait time  = N*(initial time) + offset
#       N goes from 0 to 10, offset is 0 to 1s
#    WAT1 is a time to stay in force at a new value before doing a measurement or changing the force again.
#          The programming manual (edition 4, page 1.44) says it is the time before changing source.
#          But at least for the first point, the extra time is added after the change.
#        It is added to hold or delay. It can be absorbed in the Sdelay time that is in extra of the measurement time.
#        It even affects DV/DI
#       So if the output has been at the first point of the sweep for a little while,
#       then WAT1 does not add anything.
#       I think this time can be repeated when autoranging
#    WAT2 is a time to wait before data when autoranging (can be multiple times)
#       It can be absorbed in the Sdelay time that is in extra of the measurement time.
#    both WAT can overlap. The longest is the larger of them (except when used multiple times because of autoranging)
#

# The filter Provides a Rise time (10-90% from scope) of 0.42 ms (at least for voltage under certain conditions)
#   This risetime would meand a time constant of 0.2 ms (f3db = 800 Hz)

# Compliance Polarity behaves as described in User Guide (see Figure 6-1, 6-2, 6-3)

# Volt measurement range: (value in () can be used, but instrument returns the other one.
#  0=auto, 5=0.5, 20(or 11)=2 (lim), 50=5 (lim), 200(or 12)=20 (lim), 400(or 13)=40 (lim), 1000(or 14)=100 (lim)
#        -5=0.5 (fix), -20(or -11)=2 (fix), -50=5 (fix), -200(or -12)=20 (fix), -400(or -13)=40 (fix), -1000(or -14)=100 (fix)
# Current measurement range:
#  0=auto, 11=1n (lim), 12=10n (lim), 13=100n (lim), 14=1u (lim), 15=10u (lim), 16=100u (lim), 17=1m (lim), 18=10m (lim),19=100m (lim)
#          -11=1n (fix), -12=10n (fix), -13=100n (fix), -14=1u (fix), -15=10u (fix), -16=100u (fix), -17=1m (fix), -18=10m (fix),-19=100m (fix)
# For output range selection, only use auto or limited ones (not the fixed ranges).
#  The fixed ones can be used, but if they are too small, we have a parameter error and nothing is changed.

# Observations about RQS (some of it with NI trace, some with a scope on pin 10 of cable):
#  When using *sre 16 (that bit is high except when executing a command)
#  The SRQ line should and does get activated at the end of execution
#  However, it does seem to also produce a glitch when writing a command.
#   The SRQ line momentarally get activated, but only for about 20 us.
#   This probably causes NI autopoll to sometimes misbehave (it can miss some events.)
#   NI autopoll is disabled by board level calls (but I check and the iblck calls don't seem
#   to be a problem.) and also by Stuck SRQ line (ESRQ error return from ibwait). But I
#   was unable to observe the ESRQ error (and it was not stuck on, more more like it was
#   already off when the autopoll tried to see the source.)
#  Even when using going back to *sre 0, there is a glitch (the first time) on the SRQ line.
#   Again it is short (20 us) and probably skipped by autopoll code
#     (could depend on the number of device opened on the gpib (my test uses only one)
#      and computer speed ...) It could cause some extraneous status cleanup (unread))
# The solution:
#   my event wait internnally (the NI visa library) uses ibwait which restarts autopoll.
#   some I just need to make sure to properly clean the status_byte buffer before
#   using it. The safest, after *sre 16 (which does create the event, sometimes),
#   is to wait a little to make sure the instruments did trigger it (I use *OPC?)
#   and then empty the buffer.


#######################################################
##    Agilent B2900 series
#######################################################

class _meas_en_type(object):
    conv = {True:'ON', False:'OFF'}
    def __call__(self, from_str):
        return bool(int(from_str))
    def tostr(self, data):
        return self.conv[data]
meas_en_type = _meas_en_type()

#@register_instrument('Agilent Technologies', 'B2912A', '2.0.1225.1717')
@register_instrument('Agilent Technologies', 'B2912A', usb_vendor_product=[0x0957, 0x8E18])
class agilent_B2900_smu(visaInstrumentAsync):
    """\
    This controls the agilent B2900 series source mesure unit (SMU).
    Important devices:
     output_en
     src_level
     compliance
     readval  same as initiating a measurement, waiting then fetch
     fetch
     meas_en_current, meas_en_voltage, meas_en_resistance
    Useful method:
     conf_ch
     abort
     reset
     get_error
    """
    def init(self, full=False):
        # This empties the instrument buffers
        self._dev_clear()
        self.write('FORMat:BORDer SWAPped') # other option is NORMal.
        self.write('FORMat ASCii') # other option is REAL,32 or REAL,64
        self.write('FORMat:ELEMents:SENSe VOLTage,CURRent,RESistance,STATus,SOURce')
        super(agilent_B2900_smu, self).init(full=full)

    def abort(self):
        self.write('ABORt')

    def reset(self):
        """ Reset the instrument to power on configuration """
        self.write('*RST')

    def _async_trigger_helper(self):
        # hardcode both channles for now
        self.write('INItiate:ACQuire (@1,2);*OPC')

    @locked_calling
    def set_time(self, set_time=False):
        """ Reads the time from the instrument or set it from the computer value """
        if set_time:
            now = time.localtime()
            self.write('SYSTem:DATE %i,%i,%i'%(now.tm_year, now.tm_mon, now.tm_mday))
            self.write('SYSTem:TIME %i,%i,%i'%(now.tm_hour, now.tm_min, now.tm_sec))
        else:
            date_str = self.ask('SYSTem:DATE?')
            time_str = self.ask('SYSTem:TIME?')
            date = map(float, date_str.split(','))
            timed = map(float, time_str.split(','))
            return '%i-%02i-%02i %02i:%02i:%02f '%tuple(date+timed)

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = self._conf_helper('output_en')
        conf_ch = self.conf_ch()
        opts += ['conf_ch=%s'%conf_ch]
        opts += self._conf_helper('line_freq', 'interlock_not_ok')
        return opts+self._conf_helper(options)

    def data_clear(self):
        """ This clears data.
        """
        self.write('TRACe:CLEar')
    def _fetch_helper(self, voltage=None, current=None, resistance=None, relative=None):
        if voltage is None:
            voltage = self.meas_en_voltage.getcache()
        if current is None:
            current = self.meas_en_current.getcache()
        if resistance is None:
            resistance = self.meas_en_resistance.getcache()
        if voltage is None:
            voltage = self.meas_en_voltage.getcache()
        if voltage is None:
            voltage = self.meas_en_voltage.getcache()
        any_fetch = voltage or current or resistance
        if not (any_fetch or relative):
            raise ValueError(self.perror("fetch requires at least one of voltage, current, resistance or relative"))
        return voltage, current, resistance, relative, any_fetch

    def _fetch_getformat(self, voltage=None, current=None, resistance=None, relative=None, status=False, **kwarg):
#        voltage, current, resistance, relative, any_fetch = self._fetch_helper(voltage, current, resistance, relative)
#        multi = []
#        if voltage:
#            multi.append('volt')
#        if current:
#            multi.append('current')
#        if resistance:
#            multi.append('res')
#        if relative:
#            multi.append('rel')
#        if status:
#            multi.append('stat')
        fmt = self.fetch._format
#        multi = map(lambda x: x+'1', multi) + map(lambda x: x+'2', multi)
        fmt.update(multi=['i1', 'v1', 'i2', 'v2'])
        return BaseDevice.getformat(self.fetch, **kwarg)

    def _fetch_getdev(self, voltage=None, current=None, resistance=None, relative=None, status=False):
        """\
        options (all boolean):
            volt: to read volt. When None it is auto enabled depending on cached meas_en_voltage
            current: to read current. When None it is auto enabled depending on cached meas_en_current
            resistance: to read resistance. When None it is auto enabled depending on cached meas_en_resistance
            relative: to read the relative value. When None it is auto enabled depending on cached meas_relative_en
            status: to read the status. False by default.
            The status is a bit field with the various bit representing:
                 bit  0 (     1): Measurement range overflow
                 bit  1 (     2): Filter enabled
                 bit  2 (     4): Front terminales selected
                 bit  3 (     8): In real compliance (for source)
                 bit  4 (    16): Over voltage protection reached
                 bit  5 (    32): Math (calc1) expression enabled
                 bit  6 (    64): Null (relative) enabled
                 bit  7 (   128): Limit (calc2) test enabled
                 bit  8,9,19,20,21: Limit results (256, 512, 524288, 1048576, 2097152)
                 bit 10 (  1024): Auto Ohms enabled
                 bit 11 (  2048): Voltage measure enabled
                 bit 12 (  4096): Current measure enabled
                 bit 13 (  8192): Resistance measure enabled
                 bit 14 ( 16384): Voltage source used
                 bit 15 ( 32768): Current source used
                 bit 16 ( 65536): In range compliance (for measurement)
                 bit 17 (131072): Resistance offset compensation enabled
                 bit 18 (262144): Contact check failure
                 bit 22 (4194304): Remote sense enabled
                 bit 23 (8388608): In pulse mode
        """
#        voltage, current, resistance, relative, any_fetch = self._fetch_helper(voltage, current, resistance, relative)
#        if any_fetch or status:
        v_raw = self.ask('FETCh? (@1,2)')
        v = _decode_block_auto(v_raw)
        # Because of elements selection in init, the data is voltage, current, resistance, status
        volt1, cur1, res1, stat1, src1, volt2, cur2, res2, stat2, src2 = v
        return [cur1, volt1, cur2, volt2]
        data = v
        return data
        if voltage:
            data.extend([volt1, volt2])
        if current:
            data.extend([cur1, cur2])
        if resistance:
            data.extend(res)
        if relative:
            vr = self.data_fetch_relative_last.get()
            data.append(vr[0])
        if status:
            data.append(stat)
        return data

    def conf_ch(self, ch=None, function=None, level=None, range=None, compliance=None,
             output_en=None, output_high_capacitance_mode_en=None, output_low_conf=None, output_off_mode=None,
             output_protection_en=None, output_filter_auto_en=None, output_filter_freq=None, output_filter_en=None,
             sense_remote_en=None,
             Vmeas=None, Imeas=None, Rmeas=None, Vmeas_range=None, Imeas_range=None, Rmeas_range=None,
             Vmeas_autorange_mode=None, Imeas_autorange_mode=None, Vmeas_autorange_threshold=None, Imeas_autorange_threshold=None,
             filter_auto_en=None, filter_aperture=None, filter_nplc=None,
             meas_resistance_mode=None, meas_resistance_offset_comp_en=None,
             output_auto_on_en=None, output_auto_off_en=None):
        """\
           When call with no parameters, returns all channels settings,
           When called with only one ch selected, only returns its settings.
           Otherwise only the ones that are not None are changed.
           For the range (source). Use 0 to enable autorange or a value to fix it.
           Use 0 for the Vmeas_range or Imeas_range to enable autorange. Use a positive value to set the autorange lower limit.
            Use a negative value for the fix manual range. Note that the ranges are limited (upper) to the compliance range,
            which is set by the compliance value.
        """
        para_dict = OrderedDict([('meas_resistance_mode', self.src_mode),
                                ('function', self.src_mode),
                                ('range', None),
                                ('level', self.src_level),
                                ('compliance', self.compliance),
                                ('Vmeas', self.meas_en_voltage),
                                ('Imeas', self.meas_en_current),
                                ('Rmeas', self.meas_en_resistance),
                                ('Vmeas_range', (None, 'voltage')),
                                ('Imeas_range', (None, 'current')),
                                ('Rmeas_range', (None, 'res')),
                                ('Vmeas_autorange_mode', (self.meas_autorange_mode, 'voltage')),
                                ('Imeas_autorange_mode', (self.meas_autorange_mode, 'current')),
                                ('Vmeas_autorange_threshold', (self.meas_autorange_threshold, 'voltage')),
                                ('Imeas_autorange_threshold', (self.meas_autorange_threshold, 'current')),
                                ('filter_auto_en',self. meas_filter_auto_en),
                                ('filter_aperture', self.meas_filter_aperture),
                                ('filter_nplc', self.meas_filter_nplc),
                                ('output_en', self.output_en),
                                ('output_high_capacitance_mode_en', self.output_high_capacitance_mode_en),
                                ('output_low_conf', self.output_low_conf),
                                ('output_off_mode', self.output_off_mode),
                                ('output_protection_en', self.output_protection_en),
                                ('output_filter_auto_en', self.output_filter_auto_en),
                                ('output_filter_freq', self.output_filter_freq),
                                ('output_filter_en', self.output_filter_en),
                                ('output_auto_on_en', self.output_auto_on_en),
                                ('output_auto_off_en', self.output_auto_off_en),
                                ('meas_resistance_offset_comp_en', self.meas_resistance_offset_comp_en),
                                ('sense_remote_en', self.sense_remote_en)])
        # Add None as third element if not there
        for k, v in para_dict.items():
            if not isinstance(v, tuple):
                para_dict[k] = (v, None)
        params = locals()
        if all(params.get(k) is None for k in para_dict):
            if ch is None:
                ch = self._valid_ch
            if not isinstance(ch, (list, tuple)):
                ch = [ch]
            result_dict = {}
            orig_meas_mode = self.meas_mode.get()
            orig_ch = self.current_channel.get()
            for c in ch:
                result_c_dict = {}
                func = self.src_mode.get(ch=c) # we set channel here and update mode as necessary
                for k, (dev, meas_mode) in para_dict.items():
                    if meas_mode is not None:
                        self.meas_mode.set(meas_mode)
                    if dev is None:
                        if k == 'range':
                            # source
                            if self.src_range_auto_en.get():
                                data = 0
                            else:
                                data = self.src_range.get()
                        else:
                            # Vmeas or Imeas range
                            if self.meas_autorange_en.get():
                                data = self.meas_autorange_lower_limit.get()
                            else:
                                data = -self.meas_range.get()
                    else:
                        data = dev.get()
                    result_c_dict[k] = data
                result_dict[c] = result_c_dict
            self.current_channel.set(orig_ch)
            self.meas_mode.set(orig_meas_mode)
            return result_dict
        else:
            orig_meas_mode = self.meas_mode.get()
            func = params.get('function', None)
            if func is None:
                func = self.function.get(ch=ch)
            else:
                self.current_channel.set(ch)
            for k, (dev, meas_mode) in para_dict.items():
                val = params.get(k)
                if val is not None:
                    if meas_mode is not None:
                        self.meas_mode.set(meas_mode)
                    if dev is None:
                        if k == 'range':
                            # source
                            if val == 0:
                                self.src_range_auto_en.set(True)
                            else:
                                self.src_range.set(val)
                        else:
                            # Vmeas or Imeas range
                            if val == 0:
                                self.meas_autorange_en.set(True)
                            elif val > 0:
                                self.meas_autorange_lower_limit.set(val)
                                self.meas_autorange_en.set(True)
                            else:
                                self.meas_range.set(-val)
                    else:
                        dev.set(val)
            self.meas_mode.set(orig_meas_mode)

    def _create_devs(self):
        idn_split = self.idn_split()
        model = idn_split['model'] # Something like B2912A
        is_2ch = model[4] == '2'
        is_b291x = model[3] == '1'
        min_V = 0.1e-6 if is_b291x else 1e-6
        min_I = 0.01e-12 if is_b291x else 1e-12
        max_V = 210
        max_I = 3.03
        self._max_limits = dict(max_V=max_V, max_I=max_I)
        ch_choice = [1, 2] if is_2ch else [1]
        self._valid_ch = ch_choice
        self.current_channel = MemoryDevice(1, choices=ch_choice)
        curr_range = [100e-9, 1e-6, 10e-6, 100e-6, 1e-3, 10e-3, 100e-3, 1., 1.5, 3., 10.]
        volt_range = [0.2, 2., 20., 200.]
        res_range = [2., 20., 200., 2e3, 20e3, 200e3, 2e6, 20e6, 200e6]
        if is_b291x:
            curr_range = [10e-9] + curr_range
        def chOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.output_en = chOption('OUTPut{ch}', str_type=bool)
        self.interlock_not_ok = scpiDevice(getstr='SYSTEM:INTerlock:TRIPped?', str_type=bool)
        self.output_filter_auto_en = chOption('OUTPut{ch}:FILTer:AUTO', str_type=bool)
        self.output_filter_freq = chOption('OUTPut{ch}:FILTer:FREQuency', str_type=float, min=31.830, max=31.831e3, doc='this is 1/2*pi*tc see output_filter_tc')
        self.output_filter_tc = chOption('OUTPut{ch}:FILTer:TCONstant', str_type=float, min=5e-6, max=5e-3, doc='this is 1/2*pi*freq see output_filter_freq')
        self.output_filter_en = chOption('OUTPut{ch}:FILTer', str_type=bool)
        self.output_high_capacitance_mode_en = chOption('OUTPut{ch}:HCAPacitance', str_type=bool)
        self.output_auto_on_en = chOption('OUTPut{ch}:ON:AUTO', str_type=bool)
        self.output_auto_off_en = chOption('OUTPut{ch}:OFF:AUTO', str_type=bool)
        self.output_low_conf = chOption('OUTPut{ch}:LOW', choices=ChoiceStrings('FLOat', 'GROund'), doc="The output must be off before changing this.")
        self.output_off_mode = chOption('OUTPut{ch}:OFF:MODE', choices=ChoiceStrings('ZERO', 'HIZ', 'NORMal'), doc="""\
                                        normal: output relay open (func=volt, level=0, compliance=100e-6)
                                        hiz: output relay open (func=kept, level<40 V or <100 mA)
                                        zero: output relay closed (func=volt, level=0, compliance=100e-6)
                                        """)
        self.output_protection_en = chOption('OUTPut{ch}:PROTection', str_type=bool, doc='When enabled, this turns off the output upon reaching compliance. It uses option "normal" of output_off_mode')
        self.line_freq = scpiDevice(getstr='SYSTem:LFRequency?', str_type=float)
        src_mode_opt = ChoiceStrings('CURRent', 'VOLTage')
        self.src_mode = chOption('SOURce{ch}:FUNCtion:MODE', choices=src_mode_opt, autoinit=20)
        self.src_shape = chOption('SOURce{ch}:FUNCtion:SHAPe', choices=ChoiceStrings('PULSe', 'DC'))
        meas_mode_opt = ChoiceStrings('CURRent', 'CURRent:DC', 'VOLTage', 'VOLTage:DC', 'RESistance', quotes=True)
        meas_mode_opt_nores = meas_mode_opt[['VOLTage', 'VOLTage:DC', 'CURRent', 'CURRent:DC']]
        meas_volt = meas_mode_opt[['VOLTage', 'VOLTage:DC']]
        meas_curr = meas_mode_opt[['CURRent', 'CURRent:DC']]
        #self.meas_mode = scpiDevice('FUNCtion', choices=meas_mode_opt, autoinit=20)
        self.meas_mode = MemoryDevice('current')
        def measDevOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mode=self.meas_mode)
            app = kwarg.pop('options_apply', ['ch', 'mode'])
            options_conv = kwarg.pop('options_conv', {}).copy()
            options_conv.update(dict(mode=lambda val, conv_val: val))
            kwarg.update(options=options, options_apply=app, options_conv=options_conv)
            return chOption(*arg, **kwarg)
        def measDevOptionLim(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mode=self.meas_mode)
            app = kwarg.pop('options_apply', ['ch', 'mode'])
            options_conv = kwarg.pop('options_conv', {}).copy()
            options_lim =  kwarg.pop('options_lim', {}).copy()
            options_lim.update(mode=meas_mode_opt_nores)
            options_conv.update(dict(mode=lambda val, conv_val: val))
            kwarg.update(options=options, options_apply=app, options_conv=options_conv, options_lim=options_lim)
            return chOption(*arg, **kwarg)
        def srcDevOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mode=self.src_mode)
            app = kwarg.pop('options_apply', ['mode', 'ch'])
            kwarg.update(options=options, options_apply=app)
            return chOption(*arg, **kwarg)
        limit_conv_d = {src_mode_opt[['current']]:'voltage', src_mode_opt[['voltage']]:'current'}
        def limit_conv(val, conv_val):
            for k, v in limit_conv_d.iteritems():
                if val in k:
                    return v
            raise KeyError('Unable to find key in limit_conv')
        #limit_conv = lambda val, conv_val: limit_conv_d[val]
        def srcLimitDevOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mode=self.src_mode)
            app = kwarg.pop('options_apply', ['ch, ''mode'])
            options_conv = kwarg.pop('options_conv', {}).copy()
            options_conv.update(dict(mode=limit_conv))
            kwarg.update(options=options, options_apply=app, options_conv=options_conv)
            return chOption(*arg, **kwarg)
        self._devwrap('src_level', setget=True)
        limit_choices = ChoiceDevDep(self.src_mode,{ src_mode_opt[['voltage']]:ChoiceLimits(min_I, max_I), src_mode_opt[['current']]:ChoiceLimits(min_V, max_V)})
        self.compliance = srcLimitDevOption('SENSe{ch}:{mode}:PROTection', str_type=float, choices=limit_choices, setget=True)
        self.compliance_tripped = srcLimitDevOption(getstr='SENSe{ch}:{mode}:PROTection:TRIPped?', str_type=bool)
        src_range_choices = ChoiceDevDep(self.src_mode, {src_mode_opt[['CURRent']]:curr_range, src_mode_opt[['voltage']]:volt_range})
        self.src_range = srcDevOption('SOURce{ch}:{mode}:RANGe', str_type=float, choices=src_range_choices, setget=True)
        self.src_range_auto_lower_limit = srcDevOption('SOURce{ch}:{mode}:RANGe', str_type=float, choices=src_range_choices, setget=True)
        self.src_range_auto_en = srcDevOption('SOURce{ch}:{mode}:RANGe:AUTO', str_type=bool)

        self.meas_en_voltage = chOption('SENSe{ch}:FUNCtion:{val} "voltage"', 'SENSe{ch}:FUNCtion:STATe? "voltage"', str_type=meas_en_type)
        self.meas_en_current = chOption('SENSe{ch}:FUNCtion:{val} "current"', 'SENSe{ch}:FUNCtion:STATe? "current"', str_type=meas_en_type)
        self.meas_en_resistance = chOption('SENSe{ch}:FUNCtion:{val} "resistance"', 'SENSe{ch}:FUNCtion:STATe? "resistance"', str_type=meas_en_type)
        # apperture and nplc applies to current and volt measurement
        self.meas_filter_auto_en = chOption('SENSe{ch}:CURRent:APERture:AUTO', str_type=bool)
        self.meas_filter_aperture = chOption('SENSe{ch}:CURRent:APERture', str_type=float, min=8e-6, max=2, setget=True)
        # The actual limits depend on the line frequency (50 or 60 Hz)
        self.meas_filter_nplc = chOption('SENSe{ch}:CURRent:NPLCycles', str_type=float, min=4e-4, max=120, setget=True)
        self.meas_resistance_offset_comp_en = chOption('SENSe{ch}:RESistance:OCOMpensated', str_type=bool)
        self.meas_resistance_mode = chOption('SENSe{ch}:RESistance:MODE', choices=ChoiceStrings('MANual', 'AUTO'))
        self.meas_autorange_en = measDevOption('SENSe{ch}:{mode}:RANGe:AUTO', str_type=bool)
        range_choices = ChoiceDevDep(self.meas_mode, {meas_curr:curr_range, meas_volt:volt_range, meas_mode_opt[['resistance']]:res_range})
        self.meas_autorange_lower_limit = measDevOption('SENSe{ch}:{mode}:RANGe:AUTO:LLIMit', str_type=float, choices=range_choices, setget=True)
        self.meas_autorange_upper_limit = measDevOption('SENSe{ch}:{mode}:RANGe:AUTO:ULIMit', str_type=float, choices=range_choices, setget=True,
                                                        doc="upper limit can only be changed for a resistance measurement.")
        self.meas_autorange_mode = measDevOptionLim('SENSe{ch}:{mode}:RANGe:AUTO:MODE', choices=ChoiceStrings('NORMal', 'RESolution', 'SPEed'))
        self.meas_autorange_threshold = measDevOptionLim('SENSe{ch}:{mode}:RANGe:AUTO:THReshold', str_type=float, min=11, max=100.)
        self.meas_range = measDevOption('SENSe{ch}:{mode}:RANGe', str_type=float, choices=range_choices, setget=True)

        self.sense_remote_en = chOption('SENSe{ch}:REMote', str_type=bool)

        self.snap_png = scpiDevice(getstr='HCOPy:SDUMp:FORMat PNG;DATA?', raw=True, str_type=_decode_block_base, autoinit=False)
        self.snap_png._format['bin']='.png'

        # TODO: implement various wait time, sweeps
        #       calc (offset and math)
        #       trace data and stats
#
#        self.data_fetch_relative_last = scpiDevice(getstr='CALCulate2:DATA:LATest?', str_type=_decode_block_auto, trig=True, autoinit=False)
#
#        self.data_fetch_mean = scpiDevice(getstr='CALCulate3:FORMat MEAN;DATA?', str_type=_decode_block_auto, trig=True, autoinit=False)
#        self.data_fetch_std = scpiDevice(getstr='CALCulate3:FORMat SDEViation;DATA?', str_type=_decode_block_auto, trig=True, autoinit=False)
#        self.data_fetch_max = scpiDevice(getstr='CALCulate3:FORMat MAXimum;DATA?', str_type=_decode_block_auto, trig=True, autoinit=False)
#        self.data_fetch_min = scpiDevice(getstr='CALCulate3:FORMat MINimum;DATA?', str_type=_decode_block_auto, trig=True, autoinit=False)
#        self.data_fetch_p2p = scpiDevice(getstr='CALCulate3:FORMat PKPK;DATA?', str_type=_decode_block_auto, trig=True, autoinit=False)
#
#        self.trace_feed = scpiDevice('TRACe:FEED', choices=ChoiceStrings('SENS1', 'CALC1', 'CALC2'))
#        self.trace_npoints_storable = scpiDevice('TRACe:POINts', str_type=int, setget=True, min=1, max=2500)
#        self.trace_npoints =  scpiDevice(getstr='TRACe:POINts:ACTUal?', str_type=int)
#        self.trace_en = scpiDevice('TRACe:FEED:CONTrol', choices=ChoiceSimpleMap(dict(NEXT=True, NEV=False), filter=string.upper))
#        self.trace_data = scpiDevice(getstr='TRACe:DATA?', str_type=_decode_block_auto, trig=True, autoinit=False)

        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval
        # This needs to be last to complete creation
        super(agilent_B2900_smu, self)._create_devs()

    def _src_level_getdev(self, ch=None, mode=None):
        if ch is not None:
            self.current_channel.set(ch)
        ch = self.current_channel.get()
        if mode is not None:
            self.src_mode.set(mode)
        mode = self.src_mode.getcache()
        return float(self.ask('SOURce{ch}:{mode}?'.format(ch=ch, mode=mode)))
    def  _src_level_checkdev(self, val, ch=None, mode=None):
        if ch is not None:
            self.current_channel.set(ch)
        ch = self.current_channel.get()
        if mode is not None:
            self.src_mode.set(mode)
        mode = self.src_mode.getcache()
        autorange = self.src_range_auto_en.getcache()
        K = 1.05
        if autorange:
            if mode in self.src_mode.choices[['voltage']]:
                rnge = self._max_limits['max_V']
            else:
                rnge = self._max_limits['max_I']
            K = 1.
        else:
            rnge = self.src_range.getcache()
            if rnge in [1.5, 3., 10.]:
                K = 1.
                rnge = {1.5:1.515, 3.:3.03, 10:10.5}
        if abs(val) > rnge*K:
            raise ValueError, self.perror('level is outside current range')
    def _src_level_setdev(self, val, ch=None, mode=None):
        # these were set by checkdev.
        mode = self.src_mode.getcache()
        ch = self.current_channel.get()
        self.write('SOURce{ch}:{mode} {val!r}'.format(ch=ch, mode=mode, val=val))
