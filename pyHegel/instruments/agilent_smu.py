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
import weakref

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
        getfunc is called as getfunc(subfunc(), ch) (ch is present only if ch_mode option is True)
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
        measZ           when an MFCMU board is installed.
    There is a fetch device but it will not work on its own. Use readval or fetch with async
    (but since readval with async does the same, you should always use readval here.)
    To configure the instrument, look at the methods:
        conf_general
        conf_integration
        conf_ch
        set_mode
        conf_staircase
        conf_impedance      when an MFCMU board is installed
        conf_impedance_corr when an MFCMU board is installed, to perform a calibration.
    Other useful method:
        empty_buffer   Use it to clear the buffer when stopping a reading.
                       Otherwise the next request will return previous (and wrong)
                       answers.
        abort
        reset          To return the instrument to the power on condition
        perform_calibration
        do_impedance_correction
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
            self._async_trigger_parsers = [] # list of (func, args, kwargs, last_status)
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
                    quest, slot = self._measIV_helper_get_quest(is_voltage, ch, None, rng)
                    last_status = self.meas_last_status
                    parser = self._measIV_helper_ret_val
                elif meas == 'i':
                    is_voltage = False
                    rng = self.range_current_meas
                    quest, slot = self._measIV_helper_get_quest(is_voltage, ch, None, rng)
                    last_status = self.meas_last_status
                    parser = self._measIV_helper_ret_val
                else:
                    quest, slot = self._measZ_helper_get_quest(None, ch)
                    last_status = dict(Z=self.measZ_last_status,
                                      bias=self.measZ_bias_last_status,
                                      level=self.measZ_level_last_status)[ch]
                    is_voltage = ch
                    parser = self._measZ_helper_ret_val
                async_string += ';' + quest
                async_parsers.append((parser, (is_voltage, slot), {}, last_status))
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
        if self._cmu_slot is not None:
            opts += ['conf_impedance=%s'%self.conf_impedance(),
                     'conf_impedance_corr=%s'%self.conf_impedance_corr()]
        if not conf_gen['measurement_spot_en']:
            opts += ['set_mode=%s'%self.set_mode()]
        return opts+self._conf_helper(options)

    def _reset_wrapped_cache(self, func):
        self._wrapped_cached_results[func._internal_func] = (None, None, None, None)

    @locked_calling
    def reset(self):
        self.write('*rst')
        self.init(True)

    @locked_calling
    def _call_and_wait(self, cmd):
        prev_str = self._async_trigger_helper_string
        prev_n_read = self._async_trigger_n_read
        try:
            self._async_trigger_helper_string = cmd
            self._async_trigger_n_read = 1
            self.run_and_wait()
            res = self._async_trig_current_data
        finally:
            self._async_trigger_helper_string = prev_str
            self._async_trigger_n_read = prev_n_read
            del self._async_trig_current_data
        return res

    def perform_calibration(self):
        ret = self._call_and_wait('*cal?')
        res = int(ret[0])
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
            en_chs, en_chs2 = self._get_enabled_state()
            chs = [self._slot2smu[i+1] for i,v in enumerate(en_chs) if v and i+1 in self._slot2smu]
            cmu_slot = self._cmu_slot
            if cmu_slot is not None and en_chs[cmu_slot-1]:
                chs += ['c']
            if len(chs) == 0:
                raise RuntimeError(self.perror('All channels are off so cannot fetch.'))
        if not isinstance(chs, (list, tuple, np.ndarray)):
            chs = [chs]
        full_chs = []
        conv_force = dict(voltage='v', current='i')
        conv_compl = dict(voltage='i', current='v')
        conv_z = dict(z='Z', l='level', b='bias')
        for ch in chs:
            if isinstance(ch, basestring):
                meas = ch[0].lower()
                if meas == 'c':
                    # handle CMU
                    if len(ch) == 1:
                        full_chs.append(['Z', 'c'])
                    else:
                        if len(ch)>2:
                            raise ValueError(self.perror("Invalid ch specification starting with 'c'"))
                        c = ch[1].lower()
                        if c not in conv_z:
                            raise ValueError(self.perror("Invalid ch specification with 'c' should add only 'z', 'l' or 'b'"))
                        full_chs.append([conv_z[c], 'c'])
                else:
                    # handle SMU
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
        i=0
        for c, m in full_chs:
            if m == 'c' and c == 'Z':
                base = 'cmu_Z_'
                if status:
                    multi.extend([base+'prim', base+'prim_stat', base+'sec', base+'sec_stat'])
                    graph.extend([i, i+2])
                    i += 4
                else:
                    graph.extend([i, i+1])
                    multi.extend([base+'prim', base+'sec'])
                    i += 2
                continue
            elif m == 'c':
                base = 'cmu_%s'%c
            else:
                base = '%s%i'%(m, c)
            graph.append(i)
            i += 1
            if status:
                multi.extend([base, base+'_stat'])
                i += 1
            else:
                multi.append(base)
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
           or chs is a list of channel numbers, or 'c' which means the cmu Z meas.
        Otherwise, chs can also use strings like 'v1' to read the voltage of channel 1
                     'i2' to read the current of channel 2.
                     'cz', 'cl', 'cb' to read the z, level or bias of Z cmu.
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
        For Z status description see measZ_last_status
        """
        full_chs, auto, mode = self._fetch_opt_helper(chs, auto)
        if self._async_trig_current_data is None or self._async_trig_current_data == []:
            raise RuntimeError(self.perror('No data is available, use readval.'))
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
        ret = []
        def ret_append(val):
            # measZ returns a list of 2 values.
            if isinstance(val, list):
                ret.extend(val)
            else:
                ret.append(val)
        for ch, meas in full_chs:
            val_str = self._async_trig_current_data.pop(0)
            func, args, kwargs, last_status = self._async_trigger_parsers.pop(0)
            val = func(val_str, *args, **kwargs)
            if status:
                stat = last_status.get()
                if isinstance(val, list):
                    # this is for measZ
                    val = [val[0], stat[0], val[1], stat[1]]
                else:
                    val = [val, stat]
            ret_append(val)
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
        self._reset_wrapped_cache(self._get_enabled_state)
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
        self._reset_wrapped_cache(self._get_function_cached)

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
        # 41 status obtain form keysigth support
        conv = {'00':'output off', '01':'force voltage', '02':'force positive current', '03':'force negative current',
                '11':'compliance voltage', '12':'compliance positive current', '13':'compliance negative current',
                '20':'oscillating', '40':'applying DC', '41':'connect output and cmu DC bias force', '51':'null loop unbalanced', '52':'IV amplifier saturation'}
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

    def _measZ_helper_get_quest(self, range, mode):
        """ mode is either Z, bias or level """
        cmu_slot = self._cmu_slot
        if mode is 'Z':
            if range is None:
                range = self.impedance_range.getcache()
            base = 'TC %i,'%cmu_slot
        elif mode == 'bias':
            if range is None:
                range = self.impedance_bias_meas_range.get()
            base = 'TMDCV %i,'%cmu_slot
        elif mode == 'level':
            if range is None:
                range = self.impedance_level_meas_range.get()
            base = 'TMACV %i,'%cmu_slot
        else:
            raise ValueError('Invalid mode in _measZ_helper_get_quest')
        if range == 0.:
            quest = base + '0'
        else:
            quest = base + '0,%r'%range
        return quest, cmu_slot

    def _measZ_helper_ret_val(self, result_str, mode, cmu_slot):
        """ mode is either Z, bias or level """
        if mode is 'Z':
            rets = result_str.split(',')
            value1, channel1, status1, type1 = self._parse_data(rets[0])
            value2, channel2, status2, type2 = self._parse_data(rets[1])
            last_status = self.measZ_last_status
            status = [status1, status2]
            channel = channel1
            if channel1 is not None and channel1 != channel2:
                raise RuntimeError(self.perror('Read back the wrong channel'))
            value = [value1, value2]
        elif mode == 'bias':
            value, channel, status, type = self._parse_data(result_str)
            last_status = self.measZ_bias_last_status
        elif mode == 'level':
            value, channel, status, type = self._parse_data(result_str)
            last_status = self.measZ_level_last_status
        else:
            raise ValueError('Invalid mode in _measZ_helper_get_quest')
        if channel is not None and channel != cmu_slot:
            raise RuntimeError(self.perror('Read back the wrong channel'))
        last_status.set(status)
        return value

    def _measZ_getdev(self, range=None):
        """\
            The returns the impedance (MFCMU) spot measurement.
            It returns the 2 values selected by impedance_meas_mode.
            range selects the range. If None it uses impedance_range.
            The status is saved in measZ_last_status.
        """
        quest, cmu_slot = self._measZ_helper_get_quest(range, 'Z')
        result_str = self.ask(quest)
        return self._measZ_helper_ret_val(result_str, 'Z', cmu_slot)

    def _measZ_bias_getdev(self, range=None):
        """\
            The returns the impedance dc bias voltage (MFCMU) spot measurement.
            range selects the range. If none it uses impedance_bias_meas_range
            The status is saved in measZ_bias_last_status.
        """
        quest, cmu_slot = self._measZ_helper_get_quest(range, 'bias')
        result_str = self.ask(quest)
        return self._measZ_helper_ret_val(result_str, 'bias', cmu_slot)

    def _measZ_level_getdev(self, range=None):
        """\
            The returns the impedance ac level rms voltage (MFCMU) spot measurement.
            range selects the range. If none it uses impedance_level_meas_range
            The status is saved in measZ_level_last_status.
        """
        quest, cmu_slot = self._measZ_helper_get_quest(range, 'level')
        result_str = self.ask(quest)
        return self._measZ_helper_ret_val(result_str, 'level', cmu_slot)

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

    def _impedance_avg_helper(self, mode=None, N=None):
        prev_result = self._get_impedance_avg()
        if mode == None:
            mode = prev_result['mode']
        cmd = 'ACT %s'%self.impedance_avg_mode.choices.tostr(mode)
        # if N is not set, the instrument uses 2 for auto and 1 for plc. It does not return
        #  to previous values
        if N is not None:
            cmd += ',%i'%N
        self.write(cmd)

    def _impedance_range_helper(self, range):
        base = 'RC%i,'%self._cmu_slot
        if range == 0.:
            self.write(base+'0,0')
        else:
            self.write(base+'2,%i'%range)

    def _impedance_en_helper(self, enable):
        slot = self._cmu_slot
        if enable:
            self.write('CN %i'%slot)
        else:
            self.write('CL %i'%slot)

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
            single_ch = None
            if not isinstance(ch, (list, tuple)):
                single_ch = ch
                ch = [ch]
            result_dict = {}
            for c in ch:
                func = self.function.get(ch=c) # we set ch here
                adjust_range(func)
                result_dict[c] = {k:dev.get() for k, dev in para_dict.items()}
            if single_ch is not None:
                result_dict = result_dict[single_ch]
            return result_dict
        else:
            func = params.get('function', None)
            if func is None:
                func = self.function.get(ch=ch)
            elif ch is not None:
                self.current_channel.set(ch)
            else:
                ch = self.current_channel.get()
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
            en_ch, en_ch2 = self._get_enabled_state()
            en_slots = [i+1 for i,v in enumerate(en_ch) if v]
            channels =  [self._slot2smu[c] for c in en_slots if c in self._slot2smu]
            if len(channels) == 0:
                raise RuntimeError(self.perror('All channels are disabled. You should enable at least one.'))
        slots = [self._smu2slot[c] for c in channels]
        self.write('MM %i,%s'%(valid_modes[meas_mode], ','.join(map(str, slots))))
        self._reset_wrapped_cache(self._get_tn_av_cm_fmt_mm)
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
        hold is extra wait delay for the first point.
        delay is the wait between changing the force and starting the measurement.
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
        self._reset_wrapped_cache(self._get_staircase_settings)
        conf.func = func
        self._calc_x_axis(conf)

    def _check_cmu(self):
        if self._cmu_slot is None:
            raise RuntimeError("Your instrument does not have a MFCMU card. No impedance method will work.")
        return self._cmu_slot

    def conf_impedance(self, output_en=None, level=None, freq=None, bias=None, meas_mode=None, phase_adjust_mode=None,
                       avg_mode=None, avg_N=None, range=None, level_meas_range=None, bias_meas_range=None):
        """\
        without any parameters, returns the enable states of the impedance corrections.
        otherwise changes the specified parameter.
        """
        slot = self._check_cmu()
        para_dict = OrderedDict([('output_en', self.impedance_output_en),
                                ('level', self.impedance_level),
                                ('freq', self.impedance_freq),
                                ('bias', self.impedance_bias),
                                ('meas_mode', self.impedance_meas_mode),
                                ('phase_adjust_mode', self.impedance_phase_adjust_mode),
                                ('avg_mode', self.impedance_avg_mode),
                                ('avg_N', self.impedance_avg_N),
                                ('range', self.impedance_range),
                                ('level_meas_range', self.impedance_level_meas_range),
                                ('bias_meas_range', self.impedance_bias_meas_range)])
        params = locals()
        if all(params.get(k) is None for k in para_dict):
            result_dict = {k:dev.get() for k, dev in para_dict.items()}
            return result_dict
        else:
            for k, dev in para_dict.items():
                val = params.get(k)
                if val is not None:
                    dev.set(val)

    def conf_impedance_corr(self, short_en=None, open_en=None, load_en=None):
        """\
        without any parameters, returns the enable states of the impedance corrections.
        otherwise changes the specified parameter.
        To enable a correction, it first needs to be performed:
         - enable the impedance_output, set the level, averaging ...
         - if needed, select a different set of calibration frequencies (conf_impedance_corr_freq)
         - if needed, adjust the calibration standards to be used (conf_impedance_corr_standards)
         - perform the needed calibrations (do_impedance_correction)
        You can also perform a phase correction (if the mode is manual with impedance_phase_adjust_now)
        """
        slot = self._check_cmu()
        corr_map = dict(short_en=2, open_en=1, load_en=3)
        if short_en is None and open_en is None and load_en is None:
            ret = []
            for k,i in corr_map.items():
                v = self.ask('CORRST? %i,%i'%(slot, i))
                res = bool(int(v))
                ret.append((k, res))
            return dict_improved(ret)
        # We ask for a change
        conv = lambda v: {True:'1', False:'0'}[bool(v)]
        base = 'CORRST %i,{corr},{state}'%self._cmu_slot
        for k, i in corr_map.items():
            new_val = locals()[k]
            if new_val is not None:
                self.write(base.format(corr=i, state=conv(new_val)))

    def _conf_impedance_corr_N(self):
        ret = self.ask('CORRL? %i'%self._cmu_slot)
        return int(ret)

    def conf_impedance_corr_freq(self, freqs=None):
        """ either returns the list of frequencies for the impedance correction or changes it.
            freqs can be 'default' to use the standard list.
            Setting the freqs will also disable the calibration.
        """
        slot = self._check_cmu()
        if freqs is None:
            base = 'CORRL? %i,'%slot
            N = self._conf_impedance_corr_N()
            ret = []
            for i in range(1, N+1):
                r = float(self.ask(base+'%i'%i))
                ret.append(r)
            return np.array(ret)
        # We do the change
        if freqs == 'default':
            self.write('CLCORR %i,2'%slot)
        else:
            self.write('CLCORR %i,1'%slot)
            for f in freqs:
                self.write('CORRL %i,%r'%(slot, f))

    def conf_impedance_corr_values(self, data=None):
        u"""\
            either returns the measured correction data or sets it.
            The data is 2 2D array with shape (N, 7) where N is the number of frequencies
            used and 7 are: freq (Hz), open_real (S), open_imag (S), short_real (Ω), short_imag(Ω),
                            load_real (Ω), load_imag (Ω)
            You don't need to change all the frequencies, but you need to provide the same ones
                    as in conf_impedance_corr_freq
        """
        slot = self._check_cmu()
        if data is None:
            N = self._conf_impedance_corr_N()
            ret = []
            base = 'CORRDT? %i,'%slot
            for i in range(1, N+1):
                data_str = self.ask(base+'%i'%i)
                d_s = data_str.split(',')
                r = map(float, d_s)
                ret.append(r)
            return np.array(ret)
        sh = data.shape
        if len(sh) != 2 and sh[1] != 7:
            raise ValueError('Wrong shape for the data')
        base = 'CORRDT %i,'%slot
        for d in data:
            cmd = base + ','.join(map(repr, d))
            self.write(cmd)

    def conf_impedance_corr_standards(self, open=None, short=None, load=None):
        """\
            either returns the current standard (if none are specified) or
            sets them (only the ones specified, the others are unchanged).
            Changing the standards will disable any correction and clear the calib data.
            open, short and load are each 2 values.
            open is Cp (Farad), G (Siemen)
            short and load are Ls (Henry), Rs (Ohm)
            Instrument power on default is: open=[0,0], short=[0,0], load=[0,50]
        """
        slot = self._check_cmu()
        if open is None and short is None and load is None:
            base = 'DCORR? %i,'%slot
            conv = lambda s: map(float, s.split(','))
            open_d = conv(self.ask(base+'1'))
            short_d = conv(self.ask(base+'2'))
            load_d = conv(self.ask(base+'3'))
            if open_d[0] != 100 or short_d[0] != 400 or load_d[0] != 400:
                raise RuntimeError('Unexpected answers.')
            if len(open_d) != len(short_d) != len(load_d) != 3:
                raise RuntimeError('Unexpected answers (length).')
            return dict_improved(short=short_d[1:], open=open_d[1:], load=load_d[1:])
        else:
            base = 'DCORR %i,'%slot
            def set_std(std, hdr):
                if std is not None:
                    if len(std) != 2:
                        raise ValueError('You need to have a list with 2 floats.')
                    self.write(base+hdr+',%r,%r'%(float(std[0]), float(std[1])))
            set_std(open, '1,100')
            set_std(short, '2,400')
            set_std(load, '3,400')

    def do_impedance_correction(self, standard):
        """ This performs the correction measurement selected by standard and enables it.
            It is one of 'short', 'open', 'load'.
            The standard needs to be connected before calling this method.
            The impedance output needs to be enabled and the level selected.
            You should also have selected your prefered averaging time.
        """
        slot = self._check_cmu()
        std = dict(short=2, open=1, load=3)
        if standard not in std:
            raise ValueError('Invalid standard selected.')
        ret = self._call_and_wait('CORR? %i,%i'%(slot, std[standard]))
        result = int(ret[0])
        if result == 0:
            return
        if result == 1:
            raise RuntimeError('Correction data measurement failed (standard=%s)'%standard)
        elif result == 2:
            raise RuntimeError('Correction data measurement aborted (standard=%s)'%standard)
        else:
            raise RuntimeError('Correction data measurement unknown result (standard=%s, result=%i)'%(standard, result))

    def impedance_phase_adjust_now(self, mode='perform'):
        """\
            mode can be 'perform' or 'last' to reuse the last data and not perform a measurement.
            It will change the frequency and level.
            It will take abou 30s.
            You need to undo the connections (keeping Lc,Lp together, also Hc,Hp together).
            It applies a signal in Lc and measures the delay in Lp (normally Lp is virtual ground.)
        """
        slot = self._check_cmu()
        mode_map = dict(perform=1, last=0)
        if mode not in mode_map:
            raise ValueError('Invalid mode selected.')
        if mode == 'perform':
            print 'Wait for phase adjust. It will take about 30s...'
        ret = self._call_and_wait('ADJ? %i,%i'%(slot, mode_map[mode]))
        result = int(ret[0])
        if result == 0:
            return
        if result == 1:
            raise RuntimeError('Phase compensation failed')
        elif result == 2:
            raise RuntimeError('Phase compensation was aborted')
        elif result == 3:
            raise RuntimeError('Phase compensation not performed')
        else:
            raise RuntimeError('Phase compensation unknown result (result=%i)'%(result))

    def _create_devs(self):
        # This check is to wait if the B1500 instrument has been recently powered up.
        # Because it will perform some test or calibration and we will fail on the empty_buffer call.
        first_check = True
        while self.read_status_byte() & 0x10 != 16:
            if first_check:
                print 'The instrument is not ready. It could be executing a command or doing a calibration or self-test.\n  PLEASE WAIT'
                first_check = False
            sleep(1)
        self.empty_buffer() # make sure to empty output buffer
        self._isB1500 = self.idn_split()['model'] in ['B1500A']
        valid_ch, options_dict, smu_slots, cmu_slots, Nmax = self._get_unit_conf()
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
        # now handle MFCMU presence
        if len(cmu_slots) > 0:
            if len(cmu_slots) > 1:
                print 'Unexpected number of MFCMU cards. Will only enable the first one'
            self._cmu_slot = cmu_slots[0]
            cmu_present = True
        else:
            self._cmu_slot = None
            cmu_present = False

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
        self.range_meas_use_compliance_en = MemoryDevice_update(None, False, choices=[True, False], nch=Nmax, doc="It is a MemoryDevice (so cannot be read from instrument.)")

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
                                                With this False, you need to use set_mode. It is a MemoryDevice (so cannot be read from instrument.)
                                                """)
        if cmu_present:
            meas_mode_ch = ChoiceIndex({1:'RX', 2:'GB', 10:'ZRad', 11:'ZDeg', 20:'YRad', 21:'YDeg',
                                        100:'CpG', 101:'CpD', 102:'CpQ', 103:'CpRp',
                                        200:'CsRs', 201:'CsD', 202:'CpQ',
                                        300:'LpG', 301:'LpD', 302:'LpQ', 303:'LpRp',
                                        400:'LsRs', 401:'LsD', 402:'LpQ'})
            self.impedance_meas_mode = CommonDevice(self._get_impedance_meas_mode,
                                                    lambda v: v[0],
                                                    'IMP{val}',
                                                    choices=meas_mode_ch,
                                                    doc="""\
                                                        the mode consist of the primary+secondary parameter to measure.
                                                        R is for resistance (in Ohms)
                                                        X is reactance (in Ohms)
                                                        G is Conductance (in Siemens)
                                                        B is susceptance (in Siemens)
                                                        Rad/Deg are the phase in radians or degrees
                                                        Cp/Cs is parallel/series capacitance (in Farads)
                                                        Lp/Ls is parallel/series inductance (in Henrys)
                                                        Rp/Rs is parallel/series resistance (in Ohms)
                                                        D is dissipation factor
                                                        Q is quality factor""")
            self.impedance_bias = CommonDevice(self._get_impedance_exc, lambda v:v['bias'][0], 'DCV%i,{val}'%self._cmu_slot, type=float, min=-25, max=25, setget=True)
            self.impedance_level = CommonDevice(self._get_impedance_exc, lambda v:v['level'][0], 'ACV%i,{val}'%self._cmu_slot, type=float, min=0, max=.25, setget=True, doc='In Vrms')
            self.impedance_freq = CommonDevice(self._get_impedance_exc, lambda v:v['freq'][0], 'FC%i,{val}'%self._cmu_slot, type=float, min=1e3, max=5e6, setget=True)
            self.impedance_avg_mode = CommonDevice(self._get_impedance_avg,
                                                   lambda v: v['mode'],
                                                   lambda self, v: self.instr._impedance_avg_helper(mode=v),
                                                   choices=ChoiceIndex({0:'auto', 2:'plc'}))
            self.impedance_avg_N = CommonDevice(self._get_impedance_avg,
                                                   lambda v: v['N'],
                                                   lambda self, v: self.instr._impedance_avg_helper(N=v),
                                                   choices=ChoiceDevDep(self.impedance_avg_mode, dict(auto=ChoiceLimits(1, 1023, int), plc=ChoiceLimits(1, 100, int))))
            self.impedance_data_monitor_bias_level_en =  CommonDevice(self._get_impedance_monitor, lambda v: v[0], 'LMN {val}', type=bool,
                                                                      doc='This is for internal sweeps.')
            self.impedance_range = CommonDevice(self._get_impedance_range,
                                                   lambda v: v['range'],
                                                   lambda self, v: self.instr._impedance_range_helper(v),
                                                   choices=[0., 50., 100., 300., 1e3, 3e3, 10e3, 30e3, 100e3, 300e3], setget=True,
                                                   doc="0. is for auto range. Available ranges depend on frequency (higher f, lower the limit).")
            self.impedance_phase_adjust_mode =  CommonDevice(self._get_impedance_phase_adj, lambda v: v[0], 'ADJ %i,{val}'%self._cmu_slot,
                                                             choices=ChoiceIndex(['auto', 'manual', 'adaptive']), doc=
                                                             "For manual mode, use the impedance_phase_adjust_now method. adaptive performs the phase adjust before all measurements.")
            weak_self = weakref.proxy(self)
            self.impedance_output_en =  CommonDevice(self._get_enabled_state,
                                                     lambda v: v[0][weak_self._cmu_slot-1],
                                                     lambda self,v: self.instr._impedance_en_helper(v), type=bool)
            self.impedance_bias_meas_range = MemoryDevice(0., choices=[0., 8, 12, 25], doc="""0. is for auto range. It is a MemoryDevice (so cannot be read from instrument.)""")
            self.impedance_level_meas_range = MemoryDevice(0., choices=[0., 16e-3, 32e-3, 64e-3, 125e-3, 250e-3], doc="""0. is for auto range. It is a MemoryDevice (so cannot be read from instrument.)""")
            self.measZ_last_status = MemoryDevice([0,0], multi=['prim_status', 'sec_status'], doc="""\
                To read status for cmu, the bit field is:
                   bit 0 (  1): A/D converter overflowed.
                   bit 1 (  2): CMU is in the NULL loop unbalance condition.
                   bit 2 (  4): CMU is in the IV amplifier saturation condition.
                   bit 3 (  8): not assigned.
                   bit 4 ( 16): not assigned.
                   bit 5 ( 32): not assigned.
                   bit 6 ( 64): Invalid data is returned. D is not used.
                   bit 7 (128): EOD (End of Data).
                """)
            self.measZ_bias_last_status = MemoryDevice(0, doc='see measZ_last_status for bit field description')
            self.measZ_level_last_status = MemoryDevice(0, doc='see measZ_last_status for bit field description')
            self._devwrap('measZ', multi=['primary', 'secondary'], autoinit=False, trig=True)
            self._devwrap('measZ_bias',  autoinit=False, trig=True)
            self._devwrap('measZ_level', autoinit=False, trig=True)

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
        super(agilent_SMU, self)._create_devs()

    @cache_result
    def _get_enabled_state(self):
        "Returns the enabled state of each channels"
        N = self._N_slots
        ret = self.ask("*LRN? 0")
        state1 = [False]*N
        state2 = [False]*N
        if ret == 'CL':
            pass
        elif ret.startswith('CN'):
            for i_s in ret[2:].split(','):
                ch_i = int(i_s)
                if ch_i > 100:
                    ch = ch_i//100 - 1
                    sub = ch_i % 100
                    if sub not in [1, 2]:
                        raise RuntimeError('Unexpected sub channel number')
                    state = state1 if sub == 1 else state2
                else:
                    ch = ch_i - 1
                    state = state1
                state[ch] = True
        else:
            raise RuntimeError(self.perror('Unexpected format for get_enabled_state'))
        return state1, state2

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

    _status_letter_2_num = dict(N=0, T=4, C=8, V=1, X=2, G=16, S=32, F=2, U=2, D=4)
    def _parse_data(self, data_string):
        """ Automatically parses the data into value, channel, status, type """
        # FMT12 and FMT22 seem to be the same
        if data_string[2] in 'VIFZYCLRPDQXT': # FMT1 or FMT5 (12 digits data), or FMT11 or FMT15 (13 digits data)
            status = data_string[0] # W/E E is for last sweep step data for source,  N<G<S<T<C<V<X<F  (pulse is  N<T<C<V<X<G or S)
                # N: No error, T: Another channel compliance, C: This channel Compliance, V: over range
                # X: channel oscillating, G: search not found or over time on quasi-pulse, S: search stopped or quasi-pulse too slow
            status = self._status_letter_2_num[status]
            channel = data_string[1] # A-H = 1-8
            type = data_string[2]  # V (volt) I (current) F (freq) Z (impedance Ohm) Y(admitance Siemens) C (capacitance) L(inductance)
                                   # R (phase rad) P (phase deg) D (dissipation factor) Q (quality factor) X (sampling index) T(time)
            value = float(data_string[3:])
        elif data_string[4] in 'VvIifzZYCLRPDQXT': # FMT21 or FMT25
            if data_string.startswith('  '):
                status = 128 if data_string[2] == 'E' else 0 # W/E E is for last sweep step data for source
            else:
                status = int(data_string[:3]) # Status, 1=A/D overflow(V), 2:some unit oscillating(X), 4: Another unit reached compliance(T), 8: This unit reached compliance(C)
                # 16: Target not found (G), 32: Search stopped (S), 64: Invalid data (), 128: End of data
            channel = data_string[3] # A-H = 1-8, V=GNDU, Z=extra or TSQ or invalid
            type = data_string[4] # V/v/I/i/f/z is Volt/Volt source/Current/Current source/frequency/invalid + ZYCLRPDQXT like above
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
        cmu_slots = []
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
                elif t in ['MFCMU']:
                    cmu_slots.append(ch)
            o = opt[0]
        return valid_ch, options_dict, smu_slots, cmu_slots, Nmax

    @cache_result
    def _get_impedance_exc(self):
        imp_slot = self._cmu_slot
        ret = self.ask("*LRN? 7")
        rs = ret.split(';')
        if len(rs) == 1 and rs[0] == 'CL%i'%imp_slot:
                # we are off
                return dict(bias=[0.], level=[0.], freq=[1e3])
        if len(rs) != 3:
            raise RuntimeError(self.perror('Invalid number of elemnts for lrn %i'%imp_slot))
        bias = self._parse_block_helper(rs[0], 'DCV%i,'%imp_slot, [float])
        level = self._parse_block_helper(rs[1], 'ACV%i,'%imp_slot, [float])
        freq = self._parse_block_helper(rs[2], 'FC%i,'%imp_slot, [float])
        return dict(bias=bias, level=level, freq=freq)

    @cache_result
    def _get_impedance_meas_mode(self):
        ret = self.ask("*LRN? 70")
        choices =  self.impedance_meas_mode.choices
        mode = self._parse_block_helper(ret, 'IMP', [choices])
        return mode

    @cache_result
    def _get_impedance_monitor(self):
        ret = self.ask("*LRN? 71")
        monitor = self._parse_block_helper(ret, 'LMN', [lambda s: bool(int(s))])
        return monitor

    @cache_result
    def _get_impedance_avg(self):
        ret = self.ask("*LRN? 72")
        choices =  self.impedance_avg_mode.choices
        rs = self._parse_block_helper(ret, 'ACT', [choices, int])
        return dict(mode=rs[0], N=rs[1])

    @cache_result
    def _get_impedance_range(self):
        ret = self.ask("*LRN? 73")
        imp_slot = self._cmu_slot
        rs = self._parse_block_helper(ret, 'RC%i,'%imp_slot, [int, int])
        return dict(mode=rs[0], range=rs[1])

    @cache_result
    def _get_impedance_phase_adj(self):
        ret = self.ask("*LRN? 90")
        imp_slot = self._cmu_slot
        choices =  self.impedance_phase_adjust_mode.choices
        rs = self._parse_block_helper(ret, 'ADJ%i,'%imp_slot, [choices])
        return rs


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

#@register_instrument('Keysight Technologies', 'B2912A', '3.4.2011.5100')
#@register_instrument('Agilent Technologies', 'B2912A', '2.0.1225.1717')
@register_instrument('Keysight Technologies', 'B2902B', usb_vendor_product=[0x2A8D, 0x9201]) # fw: 5.0.2029.1911
@register_instrument('Keysight Technologies', 'B2912A', skip_add=True)
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
     conf_mode
     abort
     reset
     get_error
    """
    def init(self, full=False):
        # This empties the instrument buffers
        self._dev_clear()
        self.write('FORMat:BORDer SWAPped') # other option is NORMal.
        self.write('FORMat ASCii') # other option is REAL,32 or REAL,64
        #self.write('FORMat:ELEMents:SENSe VOLTage,CURRent,RESistance,STATus,SOURce')
        self.write('FORMat:ELEMents:SENSe VOLTage,CURRent,RESistance,TIME,STATus,SOURce')
        self.write('SYSTem:GROup (@%s)'%(_encode_block(self._valid_ch, ',')))
        self.write('TRACe1:FEED SENSe;:TRACe1:FEED:CONTrol NEVer;:TRACe1:TSTamp:FORMat ABSolute')
        self.write('TRACe1:POINts MAX')
        self.write('TRACe1:FEED:CONTrol NEXT')
        self.write('SENSe1:RESistance:RANGe:AUTO:ULIMit DEF')
        if 2 in self._valid_ch:
            self.write('TRACe2:FEED SENSe;:TRACe2:FEED:CONTrol NEVer;:TRACe2:TSTamp:FORMat ABSolute')
            self.write('TRACe2:POINts MAX')
            self.write('TRACe2:FEED:CONTrol NEXT')
            self.write('SENSe2:RESistance:RANGe:AUTO:ULIMit DEF')
        self.conf_mode('spot')
        self._set_async_trigger_helper_string()
        super(agilent_B2900_smu, self).init(full=full)

    def abort(self):
        chs = ','.join(map(str, self._valid_ch))
        self.write('ABORt (@2%s)'%chs)

    @locked_calling
    def reset(self):
        """ Reset the instrument to power on configuration """
        self.write('*RST')
        self.init(True)
        self._enabled_chs_cache_reset()

    def _set_async_trigger_helper_string(self, chs=None):
        if chs is None:
            chs = self._valid_ch
        # make a clean ordered list (without repeats)
        chs = sorted(list(set(chs)))
        ch_string = _encode_block(chs, ',')
        mode = 'ACQuire' if self._trigger_mode[0] in ['spot', 'repeats'] else 'ALL'
        self._async_trigger_helper_string = 'INItiate:{} (@{});*OPC'.format(mode, ch_string)

    def _async_select(self, devs=[]):
        # This is called during init of async mode.
        self._async_detect_setup(reset=True)
        for dev, kwarg in devs:
            if dev in [self.fetch, self.readval]:
                chs = kwarg.get('chs', None)
                auto = kwarg.get('auto', 'all')
                status = kwarg.get('status', False)
                self._async_detect_setup(chs=chs, auto=auto, status=status)

    def _async_detect_setup(self, chs=None, auto=None, status=None, reset=False):
        if reset:
            # default to triggering everything
            self._set_async_trigger_helper_string()
            mode, en_chs = self._trigger_mode
            if mode == 'stairs':
                self._async_trigger_list = en_chs[:] # make a copy
            else:
                self._async_trigger_list = []
            return
        trigger_list = self._async_trigger_list
        full_chs, chs_en = self._fetch_opt_helper(chs, auto, status)
        trigger_list += chs_en
        self._set_async_trigger_helper_string(trigger_list)

    def _async_trigger_helper(self):
        mode, en_chs = self._trigger_mode
        if mode == 'stairs':
            orig_ch = self.current_channel.get()
            if 1 not in en_chs:
                lvl = self.src_level.get(ch=1)
                func = self.src_function.getcache()
                self.write(':SOURce1:%s:TRIGgered %r'%(func, lvl))
            if 2 in self._valid_ch and 2 not in en_chs:
                lvl = self.src_level.get(ch=2)
                func = self.src_function.getcache()
                self.write(':SOURce2:%s:TRIGgered %r'%(func, lvl))
            self.current_channel.set(orig_ch)
            self.data_clear()
        elif mode == 'repeats':
            self.data_clear()
        async_string = self._async_trigger_helper_string
        self.write(async_string)

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
        conf_mode = self.conf_mode()
        opts += ['conf_ch=%s'%conf_ch]
        opts += ['conf_mode=%s'%conf_mode]
        opts += self._conf_helper('line_freq', 'interlock_not_ok')
        return opts+self._conf_helper(options)

    def data_clear(self):
        """ This clears data.
        """
        self.write('TRACe1:FEED:CONTrol NEVer')
        self.write('TRACe1:CLEar')
        self.write('TRACe1:FEED:CONTrol NEXT')
        if 2 in self._valid_ch:
            self.write('TRACe2:FEED:CONTrol NEVer')
            self.write('TRACe2:CLEar')
            self.write('TRACe2:FEED:CONTrol NEXT')

    def _fetch_opt_helper(self, chs=None, auto='all', status=False, xaxis=True):
        auto = auto.lower()
        if auto not in ['all', 'i', 'v', 'force', 'compliance']:
            raise ValueError(self.perror("Invalid auto setting"))
        if chs is None:
            chs = self.enabled_chs()
            if len(chs) == 0:
                raise RuntimeError(self.perror('All channels are off so cannot fetch.'))
        if not isinstance(chs, (list, tuple, np.ndarray)):
            chs = [chs]
        full_chs = []
        conv_force = dict(voltage='v', current='i')
        conv_compl = dict(voltage='i', current='v')
        is_stairs = self._trigger_mode[0] == 'stairs'
        orig_ch = self.current_channel.get()
        for ch in chs:
            if isinstance(ch, basestring):
                meas = ch[0].lower()
                c = int(ch[1:])
                if meas not in ['v', 'i', 'r', 's', 'f', 't']:
                    raise ValueError(self.perror("Invalid measurement requested, should be 'i', 'v', 'r', 's', 't' or 'f'"))
                if c not in self._valid_ch:
                    raise ValueError(self.perror('Invalid channel requested'))
                full_chs.append([c, meas])
            else:
                if ch not in self._valid_ch:
                    raise ValueError(self.perror('Invalid channel requested'))
                if is_stairs and xaxis:
                    full_chs.append([ch, 'f'])
                if auto in ['force', 'compliance']:
                    func = self.src_mode.get(ch=ch)
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
                    if status:
                        full_chs.append([ch, 's'])
        self.current_channel.set(orig_ch)
        chs_en = sorted(list(set(c for c,f in full_chs)))
        return full_chs, chs_en

    def _fetch_getformat(self,  **kwarg):
        chs = kwarg.get('chs', None)
        auto = kwarg.get('auto', 'all')
        status = kwarg.get('status', False)
        xaxis = kwarg.get('xaxis', True)
        repeats_avg = kwarg.get('repeats_avg', True)
        full_chs, chs_en = self._fetch_opt_helper(chs, auto, status, xaxis)
        multi = []
        graph = []
        for i, (c, m) in enumerate(full_chs):
            base = '%s%i'%(m, c)
            multi.append(base)
            if m != 's': # exclude status from graph
                graph.append(i)
        mode = self._trigger_mode[0]
        if (mode == 'repeats' and not repeats_avg) or mode == 'stairs':
            multi = tuple(multi)
            graph = []
        fmt = self.fetch._format
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch, **kwarg)

    def _fetch_getdev(self, chs=None, auto='all', status=False, xaxis=True, repeats_avg=True):
        """
        auto can be: 'all' (both I and V), 'I' or 'V' to get just one,
                     'force'/'compliance' to get the force value (source) or
                       the compliance value
        auto is used when chs is None (all enabled channels)
           or chs is a list of channel numbers.
        Otherwise, chs can also use strings like 'v1' to read the voltage of channel 1
                     'i2' to read the current of channel 2,
                     'r1' to read the resistance of ch1,
                     's1' to read the status of ch1.
                     'f1' to read the force value of ch1
                     't1' to read the time value of ch1
        xaxis is used when mode is 'stairs' and then in the same condition as auto above (it adds the force column when True)
        repeats_avg when True (default) will return the averaged data when in 'repeats' mode, otherwise all the data is returned
        status when True, adds the status of every channel reading to the return value with auto
            The status is a bit field with the various bit representing:
                 bit  0 (     1): Voltage source(0) or current source(1)
                 bit  1 (     2): Compliance condition
                 bit  2 (     4): Compliance condition
                 bit  3 (     8): Over voltage condition
                 bit  4 (    16): Over current condition
                 bit  5 (    32): High temperature condition
                 bit 6-12:  Unused
                 bit 13 (  8192): Measurement range overflow
                 bit 14 ( 16384): Offset compensation enable condition
                 bit 15: Unused
                 bit 16-20: Composite limit test result (0-31)
            Note thhe bit 1 and 2 both represent the compliance having reached its limit.
            Both bits can be 1 (therefore decimal of 6). And it only applies to the measured channel.
            The unused bit might record the measurement range but it is not described in the documentation.
        """
        full_chs, chs_en = self._fetch_opt_helper(chs, auto, status, xaxis)
        mode = self._trigger_mode[0]
        if (mode == 'repeats' and not repeats_avg) or mode == 'stairs':
            multi = True
        else:
            multi = False
        if mode == 'repeats' and not multi:
            orig_ch = self.current_channel.get()
            # This only returns V, I, R, force
            v1 = self.data_fetch_mean.get(ch=1)
            if 2 in self._valid_ch:
                v2 = self.data_fetch_mean.get(ch=2)
            else:
                v2 = v1
            # when data is not triggered, it returns a single value
            if len(v2) == 1:
                v2 = v1
            elif len(v1) == 1:
                v1 = v2
            self.current_channel.set(orig_ch)
            nv = np.concatenate((v1,v2))
            nv.shape = (2, 4)
            v = np.zeros((2, 6))
            v[:, :3] = nv[:, :3]
            v[:, 5] = nv[:, 3]
        else:
            if self._trigger_mode[0] == 'spot':
                fetch_base = 'FETCh?'
            else:
                fetch_base = 'FETCh:ARRay?'
            # I always read all
            if 2 in self._valid_ch:
                v_raw = self.ask(fetch_base+' (@1,2)')
            else:
                v_raw = self.ask(fetch_base+' (@1)')
            v = _decode_block_auto(v_raw)
            if multi:
                if 2 in self._valid_ch:
                    v.shape = (-1, 2, 6)
                else:
                    v.shape = (-1, 1, 6)
            else:
                #v.shape = (-1,5)
                v.shape = (-1,6)
        #sel = dict(v=0, i=1, r=2, s=3, f=4)
        sel = dict(v=0, i=1, r=2, t=3, s=4, f=5)
        # Because of elements selection in init, the data is voltage, current, resistance, status, source
        data = []
        for c, m in full_chs:
            data.append(v[..., c-1, sel[m]])
        return np.array(data)

    def _enabled_chs_cache_reset(self, val=None, dev_obj=None, **kwargs):
        self._enabled_chs_cache = None

    def enabled_chs(self):
        v = self._enabled_chs_cache
        if v is not None:
            data, last_time = v
            if time.time() - last_time < 1:
                return data
        orig_ch = self.current_channel.get()
        chs = [c for c in self._valid_ch if self.output_en.get(ch=c)]
        self.current_channel.set(orig_ch)
        self._enabled_chs_cache = chs, time.time()
        return chs

    def conf_ch(self, ch=None, function=None, level=None, range=None, compliance=None,
             output_en=None, output_high_capacitance_mode_en=None, output_low_conf=None, output_off_mode=None,
             output_protection_en=None, output_filter_auto_en=None, output_filter_freq=None, output_filter_en=None,
             sense_remote_en=None,
             Vmeas=None, Imeas=None, Rmeas=None, Vmeas_range=None, Imeas_range=None, Rmeas_range=None,
             Vmeas_autorange_mode=None, Imeas_autorange_mode=None, Vmeas_autorange_threshold=None, Imeas_autorange_threshold=None,
             filter_auto_en=None, filter_aperture=None, filter_nplc=None,
             meas_resistance_mode=None, meas_resistance_offset_comp_en=None,
             output_auto_on_en=None, output_auto_off_en=None,
             #output_transient_speed=None):
             ):
        """\
           When call with no parameters, returns all channels settings,
           When called with only one ch selected, only returns its settings.
           Otherwise only the ones that are not None are changed.
           Use 0 for the range, Vmeas_range or Imeas_range to enable default autorange.
            Use a positive value to set the autorange lower limit.
            Use a negative value for the fix manual range. Note that the ranges are limited (upper) to the compliance range,
            which is set by the compliance value.
            Not that the default autorange is not the full range for current (1e-6 vs 1e-7 or 1e-8)
           Changing the range for the force channel will not have an effect (the force range will be used)
        """
        para_dict = OrderedDict([('meas_resistance_mode', self.meas_resistance_mode),
                                ('function', self.src_function),
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
                                #('output_transient_speed', self.output_transient_speed),
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
            single_ch = None
            if not isinstance(ch, (list, tuple)):
                single_ch = ch
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
                                data = self.src_range_auto_lower_limit.get()
                            else:
                                data = -self.src_range.get()
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
            if single_ch is not None:
                result_dict = result_dict[single_ch]
            return result_dict
        else:
            orig_meas_mode = self.meas_mode.get()
            func = params.get('function', None)
            if func is None:
                func = self.src_function.get(ch=ch)
            elif ch is None:
                ch = self.current_channel.get()
            else:
                self.current_channel.set(ch)
            for k, (dev, meas_mode) in para_dict.items():
                val = params.get(k)
                if val is not None:
                    if meas_mode is not None:
                        self.meas_mode.set(meas_mode)
                    else:
                        meas_mode = self.meas_mode.get()
                    if dev is None:
                        if k == 'range':
                            # source
                            if val == 0:
                                # DEF is not the same as MIN for current ranges
                                self.write('SOURCe{ch}:{func}:RANGe:AUTO:LLimit DEF'.format(ch=ch, func=func))
                                self.src_range_auto_en.set(True)
                            elif val > 0:
                                self.src_range_auto_lower_limit.set(val)
                                self.src_range_auto_en.set(True)
                            else:
                                self.src_range_auto_en.set(False)
                                self.src_range.set(-val)
                        else:
                            # Vmeas or Imeas range
                            if val == 0:
                                # DEF is not the same as MIN for current ranges
                                self.write('SENSe{ch}:{meas_mode}:RANGe:AUTO:LLimit DEF'.format(ch=ch, meas_mode=meas_mode))
                                self.meas_autorange_en.set(True)
                            elif val > 0:
                                self.meas_autorange_lower_limit.set(val)
                                self.meas_autorange_en.set(True)
                            else:
                                self.meas_range.set(-val)
                    else:
                        dev.set(val)
            self.meas_mode.set(orig_meas_mode)

    @locked_calling
    def conf_mode(self, mode=None, repeats=None, values1=None, values2=None, Mdelay1=None, Mdelay2=None,
                  keep_last_en1=None, keep_last_en2=None,
                  pulse_en1=None, pulse_en2=None,
                  Pdelay1=None, Pdelay2=None, Pwidth1=None, Pwidth2=None):
        """\
        with mode not given, returns the current settings.
        If it reports inconsistent parameters, just set them with this method to reset them.
        mode can be 'spot', 'repeats', 'stairs'
           'spot' is the default mode (readval only does one measurement)
           'repeats' makes readval do repeats measurements. You need to also specify repeats number.
           'stairs' changes the force at values1/values2 and does a measurement. You need to specify Mdelay, pulse_en.
               values should be a list of values to set or the value 'keep' (which will keep the same value as the level
               before the stairs is started.). You can only use 'keep' in a 2 channel instrument and for only one of the channels.
               The channel with keep will not be triggerd if not needed.
        Mdelay is the measurement delay,
        Pdelay, Pwidth are the pulse delay and width when pulse_en is True
        The source delay and wait are set to 0. The sense wait is also set to 0.
        pulse_en is to enable pulse mode for the channel (only for stairs). When True, also set Pdelay and Pwidth

        WARNING: not all the parameters are tested for validity. So you should check the parameters have changed
        properly by calling conf_mode without parameters before starting a measurement.
        """
        # if changing delays for measurement only (repeats) in 2 ch mode, the delays should be the
        # same otherwise the measurement are not started in parallel but are done one after the other.
        # So to simplify things here: No delay for repeats (both set at 0.)
        # This does not seem to be a problem when doing init:all
        if mode is None:
            orig_ch = self.current_channel.get()
            def conv(val):
                val = val.lower()
                v = val.split(';')
                return [f(i) for f,i in zip([str, str, int, int, int, float] + [str]*(len(v)-6), v)]
            if conv(self.ask(':trig1:tran:source?;:trig1:acq:source?; :sense1:wait:auto?; :sense1:wait?; :source1:wait?; :trig1:tran:delay?')) != \
                ['aint', 'aint', 0, 1, 0, 0.]:
                    raise RuntimeError('Inconsistent parameters on instrument for ch1. They were probably changed by hand.')
            if 2 in self._valid_ch:
                if conv(self.ask(':trig2:tran:source?; :trig2:acq:source?; :sense2:wait:auto?; :sense2:wait?; :source2:wait?; :trig2:tran:delay?')) != \
                    ['aint', 'aint', 0, 1, 0, 0.]:
                        raise RuntimeError('Inconsistent parameters on instrument for ch1. They were probably changed by hand.')
            md1 = self.src_mode.get(ch=1)
            if 2 in self._valid_ch:
                md2 = self.src_mode.get(ch=2)
            paras = {}
            mode, en_chs = self._trigger_mode
            if mode in ['spot', 'repeats']:
                # either 'spot' or repeat
                if md1 != 'fixed':
                    raise RuntimeError('Inconsistent src_mode on instrument for ch1.  It was probably changed by hand.')
                N = int(self.ask('trig1:acq:count?'))
                if 2 in self._valid_ch:
                    if md1 != md2:
                        raise RuntimeError('Inconsistent src_mode on instrument for ch2.  It was probably changed by hand.')
                    N2 = int(self.ask('trig2:acq:count?'))
                    if N != N2:
                        raise RuntimeError('Inconsistent parameters on instrument for ch2 trig acq count. It was probably changed by hand.')
                if N != 1:
                    paras['mode'] = 'repeat'
                    paras['repeats'] = N
                else:
                    paras['mode'] = 'spot'
            else:
                if (1 in en_chs and md1 != 'list') or (1 not in en_chs and md1 != 'fixed'):
                    raise RuntimeError('Inconsistent src_mode on instrument for ch1.  It was probably changed by hand.')
                paras['mode'] = 'stairs'
                func1 = self.src_function.get(ch=1)
                if md1 == 'fixed':
                    vals1 = 'keep'
                else:
                    vals1 =  _decode_block_auto(self.ask('source1:list:%s?'%func1))
                paras['values1'] = vals1
                paras['Mdelay1'] = float(self.ask('trig1:acq:delay?'))
                #paras['Mwait1'] = float(self.ask('sense1:wait:offset?'))
                pulse1 = self.src_shape.get(ch=1).lower() == 'pulse'
                paras['pulse_en1'] = pulse1
                paras['keep_last_en1'] = self.src_sweep_keep_last_en.get()
                if pulse1:
                    paras['Pdelay1'] = self.pulse_delay.get()
                    paras['Pwidth1'] = self.pulse_width.get()
                if 2 in self._valid_ch:
                    if (2 in en_chs and md2 != 'list') or (2 not in en_chs and md2 != 'fixed'):
                        raise RuntimeError('Inconsistent src_mode on instrument for ch2.  It was probably changed by hand.')
                    func2 = self.src_function.get(ch=2)
                    if md2 == 'fixed':
                        vals2 = 'keep'
                    else:
                        vals2 =_decode_block_auto(self.ask('source2:list:%s?'%func2))
                    paras['values2'] = vals2
                    paras['Mdelay2'] = float(self.ask('trig2:acq:delay?'))
                    #paras['Mwait2'] = float(self.ask('sense2:wait:offset?'))
                    pulse2 = self.src_shape.get(ch=2).lower() == 'pulse'
                    paras['pulse_en2'] = pulse2
                    paras['keep_last_en2'] = self.src_sweep_keep_last_en.get()
                    if pulse2:
                        paras['Pdelay2'] = self.pulse_delay.get()
                        paras['Pwidth2'] = self.pulse_width.get()
                    if vals1 != 'keep' and vals2 != 'keep' and len(vals1) != len(vals2):
                        raise RuntimeError('Inconsistent source lists on instrument for ch2. It was probably changed by hand.')
            self.current_channel.set(orig_ch)
            return paras
        self.write(':trig1:all:source aint')
        self.write('sense1:wait:auto 0')
        self.write('sense1:wait 1')
        self.write('source1:wait 0')
        self.write('trig1:tran:delay 0')
        orig_ch = self.current_channel.get()
        if 2 in self._valid_ch:
            self.write(':trig2:all:source aint')
            self.write('sense2:wait:auto 0')
            self.write('sense2:wait 1')
            self.write('source2:wait 0')
            self.write('trig2:tran:delay 0')
        if mode == 'spot':
            self._trigger_mode = ('spot', [])
            self.src_mode.set('fixed', ch=1)
            self.write('trig1:acq:count 1')
            self.write('trig1:acq:delay 0')
            if 2 in self._valid_ch:
                self.src_mode.set('fixed', ch=2)
                self.write('trig2:acq:count 1')
                self.write('trig2:acq:delay 0')
        elif mode == 'repeats':
            if repeats is None or repeats <1:
                raise ValueError('You need to specify a valid repeats')
            self._trigger_mode = ('repeats', [])
            self.src_mode.set('fixed', ch=1)
            self.write('trig1:acq:count %i'%repeats)
            self.write('trig1:acq:delay 0')
            if 2 in self._valid_ch:
                self.src_mode.set('fixed', ch=2)
                self.write(':trig2:acq:count %i'%repeats)
                self.write('trig2:acq:delay 0')
        elif mode == 'stairs':
            enabled_chs = []
            if values1 is None or Mdelay1 is None or pulse_en1 is None:
                raise ValueError('You need to specify values1, Mdelay1, pulse_en1')
            if isinstance(values1, (list, tuple, np.ndarray)):
                N = len(values1)
                enabled_chs.append(1)
            elif values1 == 'keep':
                if 2 not in self._valid_ch or not isinstance(values2, (list, tuple, np.ndarray)):
                    raise ValueError("Invalid use of 'keep'. It cannot be use for both channels or for a single channel instrument.")
                N = len(values2)
            else:
                raise ValueError('Incorrect type or value for values1')
            shape = {False:'DC', True:'pulse'}
            self.write('trig1:all:count %i'%N)
            self.write('trig1:acq:delay %r'%Mdelay1)
            self.write('trig1:tran:delay 0')
            #self.write('sense1:wait:offset %r'%Mwait1)
            self.src_shape.set(shape[pulse_en1], ch=1)
            self.src_sweep_keep_last_en.set(keep_last_en1)
            if pulse_en1:
                if Pdelay1 is None or Pwidth1 is None:
                    raise ValueError('You need to specify Pdelay1 and Pwidth1')
                self.pulse_delay.set(Pdelay1)
                self.pulse_width.set(Pwidth1)
            func1 = self.src_function.get(ch=1)
            if 1 in enabled_chs:
                self.src_mode.set('list')
                self.write('source1:list:%s %s'%(func1, _encode_block(values1, ',')))
            else:
                self.src_mode.set('fixed')
            if 2 in self._valid_ch:
                if values2 is None or Mdelay2 is None or pulse_en2 is None:
                    raise ValueError('You need to specify values2, Mdelay2, pulse_en2')
                if isinstance(values2, (list, tuple, np.ndarray)):
                    if len(values2) != N:
                        raise ValueError('Both values need to have the same number of elements')
                    enabled_chs.append(2)
                elif values2 == 'keep':
                    pass
                else:
                    raise ValueError('Incorrect type or value for values2')
                self.write('trig2:all:count %i'%N)
                self.write('trig2:acq:delay %r'%Mdelay2)
                self.write('trig2:tran:delay 0')
                #self.write('sense2:wait:offset %r'%Mwait2)
                self.src_shape.set(shape[pulse_en2], ch=2)
                self.src_sweep_keep_last_en.set(keep_last_en2)
                if pulse_en2:
                    if Pdelay2 is None or Pwidth2 is None:
                        raise ValueError('You need to specify Pdelay2 and Pwidth2')
                    self.pulse_delay.set(Pdelay2)
                    self.pulse_width.set(Pwidth2)
                func2 = self.src_function.get(ch=2)
                if 2 in enabled_chs:
                    self.src_mode.set('list')
                    self.write('source2:list:%s %s'%(func2, _encode_block(values2, ',')))
                self._trigger_mode = ('stairs', enabled_chs)
        else:
            raise ValueError('Invalid mode.')
        self.current_channel.set(orig_ch)

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
        self._enabled_chs_cache_reset()
        self.current_channel = MemoryDevice(1, choices=ch_choice)
        curr_range = [100e-9, 1e-6, 10e-6, 100e-6, 1e-3, 10e-3, 100e-3, 1., 1.5, 3., 10.]
        volt_range = [0, 0.2, 2., 20., 200.]
        res_range = [0, 2., 20., 200., 2e3, 20e3, 200e3, 2e6, 20e6, 200e6]
        if is_b291x:
            curr_range = [10e-9] + curr_range
        curr_range = [0] + curr_range
        def chOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.output_en = chOption('OUTPut{ch}', str_type=bool, extra_set_after_func=ProxyMethod(self._enabled_chs_cache_reset))
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
        src_func_opt = ChoiceStrings('CURRent', 'VOLTage')
        self.src_function = chOption('SOURce{ch}:FUNCtion:MODE', choices=src_func_opt, autoinit=20)
        self.src_shape = chOption('SOURce{ch}:FUNCtion:SHAPe', choices=ChoiceStrings('PULSe', 'DC'))
        meas_mode_opt = ChoiceStrings('CURRent', 'CURRent:DC', 'VOLTage', 'VOLTage:DC', 'RESistance', quotes=True)
        meas_mode_opt_nores = meas_mode_opt[['VOLTage', 'VOLTage:DC', 'CURRent', 'CURRent:DC']]
        meas_volt = meas_mode_opt[['VOLTage', 'VOLTage:DC']]
        meas_curr = meas_mode_opt[['CURRent', 'CURRent:DC']]
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
            options.update(func=self.src_function)
            app = kwarg.pop('options_apply', ['ch', 'func'])
            kwarg.update(options=options, options_apply=app)
            return chOption(*arg, **kwarg)
        limit_conv_d = {src_func_opt[['current']]:'voltage', src_func_opt[['voltage']]:'current'}
        def limit_conv(val, conv_val):
            for k, v in limit_conv_d.iteritems():
                if val in k:
                    return v
            raise KeyError('Unable to find key in limit_conv')
        def srcLimitDevOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(func=self.src_function)
            app = kwarg.pop('options_apply', ['ch', 'func'])
            options_conv = kwarg.pop('options_conv', {}).copy()
            options_conv.update(dict(func=limit_conv))
            kwarg.update(options=options, options_apply=app, options_conv=options_conv)
            return chOption(*arg, **kwarg)
        self._devwrap('src_level', setget=True)
        limit_choices = ChoiceDevDep(self.src_function, {src_func_opt[['voltage']]:ChoiceLimits(min_I, max_I), src_func_opt[['current']]:ChoiceLimits(min_V, max_V)})
        self.compliance = srcLimitDevOption('SENSe{ch}:{func}:PROTection', str_type=float, choices=limit_choices, setget=True)
        self.compliance_tripped = srcLimitDevOption(getstr='SENSe{ch}:{func}:PROTection:TRIPped?', str_type=bool)
        src_range_choices = ChoiceDevDep(self.src_function, {src_func_opt[['CURRent']]:curr_range, src_func_opt[['voltage']]:volt_range})
        self.src_range = srcDevOption('SOURce{ch}:{func}:RANGe', str_type=float, choices=src_range_choices, setget=True)
        self.src_range_auto_lower_limit = srcDevOption('SOURce{ch}:{func}:RANGe:AUTO:LLIMit', str_type=float, choices=src_range_choices, setget=True)
        self.src_range_auto_en = srcDevOption('SOURce{ch}:{func}:RANGe:AUTO', str_type=bool)
        # This is not present on my device. It did not show up in the newer firmware. Error in manual?
        #self.output_transient_speed = srcDevOption('SOURce{ch}:{func}:TRANsient:SPEed', choices=ChoiceStrings('NORMal', 'FAST'))
        self.src_sweep_keep_last_en = chOption('SOURce{ch}:FUNCtion:TRIGgered:CONTinuous', str_type=bool)
        self.src_mode = srcDevOption('SOURce{ch}:{func}:MODE', choices=ChoiceStrings('SWEep', 'LIST', 'FIXed'))

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

        self.pulse_delay = chOption('SOURce{ch}:PULSe:DELay', str_type=float, min=0, max=99999.9)
        self.pulse_width = chOption('SOURce{ch}:PULSe:WIDTh', str_type=float, min=5e-5, max=100000)

        self.sense_remote_en = chOption('SENSe{ch}:REMote', str_type=bool)

        self.snap_png = scpiDevice(getstr='HCOPy:SDUMp:FORMat PNG;DATA?', raw=True, str_type=_decode_block_base, autoinit=False)
        self.snap_png._format['bin']='.png'

        # TODO: calc (offset and math)
        # The stats only return V, I, R, force
        self.data_fetch_mean = chOption(getstr=':TRACe{ch}:STATistic:FORMat MEAN;:TRACe{ch}:STATistic:DATA?', str_type=_decode_block_auto, trig=True, autoinit=False)
        self.data_fetch_std = chOption(getstr=':TRACe{ch}:STATistic:FORMat SDEV;:TRACe{ch}:STATistic:DATA?', str_type=_decode_block_auto, trig=True, autoinit=False, doc='The instrument does the equivalent of np.std(ddof=1)')
        self.data_fetch_max = chOption(getstr=':TRACe{ch}:STATistic:FORMat MAX;:TRACe{ch}:STATistic:DATA?', str_type=_decode_block_auto, trig=True, autoinit=False)
        self.data_fetch_min = chOption(getstr=':TRACe{ch}:STATistic:FORMat MIN;:TRACe{ch}:STATistic:DATA?', str_type=_decode_block_auto, trig=True, autoinit=False)
        self.data_fetch_p2p = chOption(getstr=':TRACe{ch}:STATistic:FORMat PKPK;:TRACe{ch}:STATistic:DATA?', str_type=_decode_block_auto, trig=True, autoinit=False)
#        self.trace_feed = scpiDevice('TRACe:FEED', choices=ChoiceStrings('SENS1', 'CALC1', 'CALC2'))
#        self.trace_npoints_storable = scpiDevice('TRACe:POINts', str_type=int, setget=True, min=1, max=2500)
        self.trace_npoints =  chOption(getstr='TRACe{ch}:POINts:ACTUal?', str_type=int)
#        self.trace_en = scpiDevice('TRACe:FEED:CONTrol', choices=ChoiceSimpleMap(dict(NEXT=True, NEV=False), filter=string.upper))
#        self.trace_data = scpiDevice(getstr='TRACe:DATA?', str_type=_decode_block_auto, trig=True, autoinit=False)

        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval
        # This needs to be last to complete creation
        super(agilent_B2900_smu, self)._create_devs()

    def _src_level_getdev(self, ch=None, func=None):
        if ch is not None:
            self.current_channel.set(ch)
        ch = self.current_channel.get()
        if func is not None:
            self.src_function.set(func)
        func = self.src_function.getcache()
        return float(self.ask('SOURce{ch}:{func}?'.format(ch=ch, func=func)))
    def  _src_level_checkdev(self, val, ch=None, func=None):
        if ch is not None:
            self.current_channel.set(ch)
        ch = self.current_channel.get()
        if func is not None:
            self.src_function.set(func)
        func = self.src_function.getcache()
        autorange = self.src_range_auto_en.getcache()
        K = 1.05
        if autorange:
            if func in self.src_function.choices[['voltage']]:
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
    def _src_level_setdev(self, val, ch=None, func=None):
        # these were set by checkdev.
        func = self.src_function.getcache()
        ch = self.current_channel.get()
        self.write('SOURce{ch}:{func} {val!r}'.format(ch=ch, func=func, val=val))

# Trace allows caluclating stats (avg, stderr). It needs to be reset between inits (if the number of trace:points is larger than
#    what is to be acquired)
# The enable lists (stairs is similar):
# set the source mode volt:mode list
# set the list of points list:volt
# the acq and tran trigger should have the same number of points as the list length
# start the acquisition with init:all
# read with fetch:arr
# can play with the timing with trig:acq:delay, trig:tran:delay
# and sense:wait, sense:wait:auto (and gain and offset)
# and the same for source.
# playing with arm (count) does not seem to be useful (except to repeat the inner)
# if the arm*trigger count is larger than the list of value, it is repeated (it cycles through the values again)
# if the count for acq is larger that tran, it just keeps using the last tran values for the other acq.
# It is not clear how the wait and delay interact. And how trigger source like timer would interact with them.
# With a short timer of .1 s and a delay of 0.3 s, the readings are taken at .3, .4, .5 ... and are not
# necessarily matched to the source changes.
# I think aint setups timers.
# If timers are too short for the measurement, I think the measurement is truncated.
# measurement can be in the midle of an output change. It averages the value over the measured interval.
# Source wait works but is complicated in 2 channel modes. It adds time after a change before the next trans trigger can
# can be sent.
# Sense wait: I never saw it do anything.
