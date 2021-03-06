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

from ..instruments_base import visaInstrument, visaInstrumentAsync,\
                            BaseDevice, scpiDevice, MemoryDevice, ReadvalDev,\
                            ChoiceMultiple, Choice_bool_OnOff, _repr_or_string,\
                            quoted_string, quoted_list, quoted_dict, ChoiceLimits,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDev, ChoiceDevSwitch, ChoiceIndex,\
                            decode_float64, decode_float64_avg, decode_float64_meanstd,\
                            decode_uint16_bin, _decode_block_base, decode_float64_2col,\
                            decode_complex128, sleep, locked_calling, visa_wrap, _encode_block,\
                            dict_improved, _general_check, _tostr_helper, ChoiceBase, ProxyMethod,\
                            OrderedDict
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

#######################################################
##    Agilent E5270B mainframe with E5281B precision medium power SMU modules
#######################################################

# decorator to cache values for 100 ms
def cache_result(func):
    def wrapped_func(self, *args, **kwargs):
        last, cache, prev_args, prev_kwargs = self._wrapped_cached_results.get(func, (None, None, None, None))
        now = time.time()
        if last is None or now - last > 0.1 or args != prev_args or kwargs != prev_kwargs:
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
    def _ch_helper(self, ch=None):
        args = ()
        if self._nch is not None:
            ch = self.instr._ch_helper(ch)
            args += (ch, )
        elif ch is not None:
            raise ValueError(self.perror('You cannnot specify a channel for this device.'))
        return ch, args
    def _getdev(self, ch=None):
        ch, args = self._ch_helper(ch)
        if ch is None:
            return super(MemoryDevice_update, self)._getdev(self)
        return self._internal_vals[ch-1]
    def _setdev(self, val, ch=None):
        ch, args = self._ch_helper(None) # Channel already changed in check
        if ch is not None:
            self._internal_vals[ch-1] = val
        super(MemoryDevice_update, self)._setdev(val)
        if self._update_func is not None:
            self._update_func(*args)
    def _checkdev(self, val, ch=None):
        ch, args = self._ch_helper(ch)
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


#@register_instrument('Agilent Technologies', 'E5270B', 'B.01.13')
@register_instrument('Agilent Technologies', 'E5270B', alias='E5270B SMU')
class agilent_SMU(visaInstrumentAsync):
    """
    This is to control the E5281B precision medium power SMU modules within
    an E5270B mainframe.
    """
    def __init__(self, *args, **kwargs):
        self._wrapped_cached_results = {}
        super(agilent_SMU, self).__init__(*args, **kwargs)

    def init(self, full=False):
        self.write('FMT21')
        self.calibration_auto_en.set(False)
        #self.sendValueToOther('Auto Calibration Enable', False)
          # Calibration is performed every 30 min after all outputs are off.
        self.remote_display_en.set(True)
        #super(agilent_SMU, self).init(full=full) # don't use this, it sets *esr which does not exist for SMU
        # self.clear() # SMU does not have *cls
        self.write('*sre 0') # disable trigger (we enable it only when needed)
        self._async_trigger_helper_string = None

    def _async_trigger_helper(self):
        async_string = self._async_trigger_helper_string
        if async_string is None:
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
        data = self.read()
        self._async_trig_current_data = data
        return ret

    @locked_calling
    def _async_trig(self):
        async_string = self._async_trigger_helper_string
        if async_string != '*cal?':
            if self.measurement_spot_en.get():
                async_string = None
            else:
                async_string = 'XE'
                self.write('BC') # empty buffer
                # Trigger on Set Ready. This generates an event which will need to be cleaned up.
                # *opc? is used to make sure we waited long enough to see the event if it was to occur.
                # Note that the event is not always detected by NI autopoll so this is why
                # we wait and then empty the buffer of all/any status.
                #   (see details in comment section below to class code.)
                self.ask('*sre 16;*opc?')
                # absorb all status bytes created.
                #i=0
                while self.read_status_byte()&0x40:
#                    i += 1
                    pass
#                print 'skipped %i'%i
            self._async_trigger_helper_string =  async_string
        super(agilent_SMU, self)._async_trig()

    def _get_esr(self):
        # does not have esr register
        return 0

    def get_error(self):
        errors = self.ask('ERR?')
        errn = [int(s) for s in errors.split(',')]
        errm = ['%i: %s'%(e, self.ask('EMG? %i'%e)) for e in errn]
        return ', '.join(errm)

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
        try:
            self._async_trigger_helper_string = '*cal?'
            self.run_and_wait()
            res = int(self._async_trig_current_data)
        finally:
            self._async_trigger_helper_string = prev_str
            del self._async_trig_current_data
        if res != 0:
            raise RuntimeError(self.perror('Calibration failed (at least one module failed). Returned value is %i'%res))

    def _fetch_opt_helper(self, chs=None, auto='all'):
        mode = 'spot'
        if not self.measurement_spot_en.get():
            mode = self.set_mode().mode
            full_chs = [[c, 'ch'] for c in self.set_mode()['channels']]
            return full_chs, auto, mode
        auto = auto.lower()
        if auto not in ['all', 'i', 'v']:
            raise ValueError(self.perror("Invalid auto setting"))
        if chs is None:
            chs = [i+1 for i,v in enumerate(self._get_enabled_state()) if v]
            if len(chs) == 0:
                raise RuntimeError(self.perror('All channels are off so cannot fetch.'))
        if not isinstance(chs, (list, tuple, np.ndarray)):
            chs = [chs]
        full_chs = []
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
                     force/compliance to get the force value (source) or
                       the complicance value
        auto is used when chs is None (all enabled channels)
           or chs is a list of channel numbers.
        Otherwise, chs can also use strings like 'v1' to read the voltage of channel 1
                     'i2' to read the current of channel 2.
        status when True, adds the status of every reading to the return value.
        xaxis when True and when getting stair data, will add the xaxis as a first column
        """
        full_chs, auto, mode = self._fetch_opt_helper(chs, auto)
        if mode != 'spot':
            try:
                data = self._async_trig_current_data
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
        ch_orig = self.current_channel.get()
        for ch, meas in full_chs:
            if meas == 'v':
                val = self.measV.get(ch=ch)
            else:
                val = self.measI.get(ch=ch)
            ret.append(val)
            if status:
                ret.append(self.meas_last_status.get())
        self.current_channel.set(ch_orig)
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
        return ch

    def _level_comp_check_helper(self, fnc, val, comp=False):
        if fnc.mode == 'disabled':
            raise RuntimeError(self.perror('The output is currently disabled.'))
        mode = fnc.mode
        if comp:
            mode = 'current' if mode == 'voltage' else 'voltage'
        if mode == 'current':
            _general_check(val, min=-.1, max=.1)
        else:
            _general_check(val, min=-100, max=100)

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
            self._level_comp_check_helper(fnc, compliance, comp=True)

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
        self._level_comp_check_helper(fnc, val, comp=False)

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
        self._level_comp_check_helper(fnc, val, comp=True)

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

    def _measIV_helper(self, voltage, ch, range, rgdev):
        ch = self._ch_helper(ch) # this set ch for the next entries
        if range is None:
            if self.range_meas_use_compliance_en.get():
                range = 'comp'
            else:
                range = rgdev.get()
        else:
            if not (range == 'comp' or range in rgdev.choices):
                raise ValueError(self.perror('Invalid range selected'))
        quest = 'TV' if voltage else 'TI'
        quest += '%i'%ch
        if range != 'comp':
            quest += ',%s'%rgdev.choices.tostr(range)
        result_str = self.ask(quest)
        value, channel, status, type = self._parse_data(result_str)
        if type is not None and type != {True:'V', False:'I'}[voltage]:
            raise RuntimeError(self.perror('Read back the wrong signal type'))
        if channel is not None and channel != ch:
            raise RuntimeError(self.perror('Read back the wrong channel'))
        self.meas_last_status.set(status)
        return value

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


    def _integration_set_helper(self, speed=True, mode=None, time=None):
        prev_result = self._get_avg_time_and_autozero()
        if speed:
            prev_result = prev_result['high_speed']
            base = 'AIT 0,%s,%i'
        else:
            prev_result = prev_result['high_res']
            base = 'AIT 1,%s,%i'
        if mode is None:
            mode = prev_result[0]
        if time is None:
            time = prev_result[1]
        if mode == 'plc':
            time = min(time, 100) # limit to 100.
        mode = self._integ_choices.tostr(mode)
        self.write(base%(mode, time))

    def conf_general(self, autozero=None, remote_display=None, auto_calib=None):
        para_dict = dict(autozero=self.auto_zero_en,
                         remote_display=self.remote_display_en,
                         auto_calib=self.calibration_auto_en,
                         measurement_spot_en=self.measurement_spot_en )
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
        """
        para_dict = OrderedDict(function=self.function,
                                level=self.level,
                                range=None,
                                compliance=self.compliance,
                                comp_range=None,
                                polarity=self.compliance_polarity_auto_en,
                                integrator=self.integration_type,
                                Vmeas_range=self.range_voltage_meas,
                                Imeas_range=self.range_current_meas,
                                meas_range_comp=self.range_meas_use_compliance_en,
                                filter=self.output_filter_en,
                                series_r=self.series_resistor_en,
                                meas_auto_type=self.meas_auto_type)
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
        for k, dev in para_dict.items():
            func = self.function.get(ch=ch)
            adjust_range(func)
            val = params.get(k)
            if val is not None:
                dev.set(val)

    def conf_integration(self, speed_mode=None, speed_time=None, resol_mode=None, resol_time=None):
        para_dict = dict(speed_mode=self.integration_high_speed_mode,
                         speed_time=self.integration_high_speed_time,
                         resol_mode=self.integration_high_resolution_mode,
                         resol_time=self.integration_high_resolution_time)
        params = locals()
        if all(params.get(k) is None for k in para_dict):
            return {k:dev.get() for k, dev in para_dict.items()}
        for k, dev in para_dict.items():
            val = params.get(k)
            if val is not None:
                dev.set(val)

    def set_mode(self, mode=None, channels=None, **kwargs):
        """
        To use one of these mode, set measurement_spot_en to False
        if no options are given, it returns the current setting
        mode can be 'single' or 'stair'
        channels is a list of channels to read. When not specified it uses
          the current instrument set, and if never set, all the active channels.
        when using 'stair' extra keywords are passed to conf_staircase
        """
        res = self._get_tn_av_cm_fmt_mm()
        res_mode = res['meas_mode']
        res_channels = [i+1 for i,v in enumerate(res['enabled']) if v]
        if mode == channels == None:
            mode = res_mode
            channels = res_channels
            ret = dict_improved([('mode', mode), ('channels', channels)])
            if mode == 'stair':
                ret['stair'] = self.conf_staircase()
            return ret
        valid_modes = dict(single=1, stair=16)
        if mode is None:
            mode = res['meas_mode']
        elif mode not in valid_modes:
            raise ValueError(self.perror('Selected an invalide mode'))
        if channels is None:
             channels = res_channels
        elif not isinstance(channels, (list, tuple, np.ndarray)):
            channels = [channels]
        if any(c not in self._valid_ch for c in channels):
            raise ValueError(self.perror('Invalid channel selection'))
        if len(channels) == 0:
            en_ch = self._get_enabled_state()
            channels = [i+1 for i,v in enumerate(en_ch) if v]
            if len(channels) == 0:
                raise RuntimeError(self.perror('All channels are disabled. You should enable at least one.'))
        self.write('MM %i,%s'%(valid_modes[mode], ','.join(map(str, channels))))
        N_kwargs = len(kwargs)
        if mode == 'stair' and N_kwargs > 0:
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

    def conf_staircase(self, ch=None, start=None, stop=None, nsteps=None, mode=None, end_to=None, hold=None, delay=None):
        """
        call with no values to see current setup.
        When setting it uses the current settings of ch for func, range and compliance.
        When reading there are the values that will be used.
        WARNING: you probably don't want the settings of ch after calling this function.
        end_to can be 'start' or 'stop'
        mode can be 'linear', 'log', 'linear_updown', 'log_updown'
          updown makes it go from start to stop then from stop to start.
        """
        func = None
        para_val = locals()
        params = ['func', 'ch', 'start', 'stop', 'nsteps', 'mode', 'end_to', 'hold', 'delay']
        params_prev = ['sweep_var', 'sweep_ch', 'start', 'stop', 'steps', 'mode', 'ending_value', 'hold_time', 'delay_time']
        conf = dict_improved([(p,para_val[p]) for p in params])
        allnone = False
        if all(v is None for v in conf.values()):
            allnone = True
        prev_stair =  self._get_staircase_settings()
        for k in prev_stair.keys():
            if k == 'abort':
                continue
            if k in ['active_range', 'power', 'compliance']:
                conf[k] = prev_stair[k]
            else:
                kp = params[params_prev.index(k)]
                if conf[kp] is None:
                    conf[kp] = prev_stair[k]
        if allnone:
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
        if not (0 <= conf.hold <= 65.535):
            raise ValueError(self.perror("Invalid delay (must be 0-65.535)."))
        mode_ch = {'linear':1, 'log':2, 'linear_updown':3, 'log_updown':4}
        if conf.mode not in mode_ch:
            raise ValueError(self.perror("Invalid mode (must be one of %r)."%mode_ch.keys()))
        end_to_ch = dict(start=1, stop=2)
        mode = mode_ch[conf.mode]
        #self.write(base%(conf.ch, mode, sRange, conf.start, conf.stop, conf.nsteps, compliance))
        self.write(base%(conf.ch, mode, sRange, conf.start, conf.stop, conf.nsteps))
        self.write('WT %.7e,%.7e'%(conf.hold, conf.delay))
        self.write('WM 1,%i'%end_to_ch[conf.end_to])
        conf.func = func
        self._calc_x_axis(conf)


    def _create_devs(self):
        self.write('BC') # make sure to empty output buffer
        valid_ch, options_dict, Nmax = self._get_unit_conf()
        self._valid_ch = valid_ch
        self._Nvalid_ch = len(valid_ch)
        self._unit_conf = options_dict
        self._N_channels = Nmax
        self.current_channel = MemoryDevice(valid_ch[0], choices=valid_ch)
        # E5281B/E5287A also has 5:0.5, 50:5.; 5280B/E5290A also has 2000:200.
        v_range = ChoiceIndex({0:0., 5:0.5, 20:2., 50:5., 200:20., 400:40., 1000:100.})
        v_range_meas =  ChoiceIndex({0:0., 5:0.5,   20:2.,   50:5.,   200:20.,   400:40.,   1000:100.,
                                          -5:-0.5, -20:-2., -50:-5., -200:-20., -400:-40., -1000:-100.})
        self._v_range_meas_choices = v_range_meas
        # E5287A+E5288A ASU has: 8:1e-12
        # E5287A has: 9:10e-12, 10: 100e-12
        # E5280B/E5281B/E5287A has: 11:1e-9, 12:10e-9
        # E5291A has: 20:200e-3
        # E5280B/E5290A has: 20:1.
        i_range = ChoiceIndex({0:0., 11:1e-9, 12:10e-9, 13:100e-9, 14:1e-6, 15:10e-6, 16:100e-6, 17:1e-3, 18:10e-3, 19:100e-3})
        i_range_meas = ChoiceIndex({0:0., 11:1e-9,   12:10e-9,   13:100e-9,   14:1e-6,   15:10e-6,   16:100e-6,   17:1e-3,   18:10e-3,   19:100e-3,
                                         -11:-1e-9, -12:-10e-9, -13:-100e-9, -14:-1e-6, -15:-10e-6, -16:-100e-6, -17:-1e-3, -18:-10e-3, -19:-100e-3})
        self._i_range_meas_choices = i_range_meas

        def MemoryDevice_ch(*args, **kwargs):
            args = (self._set_level_comp,) + args
            kwargs['nch'] = Nmax
            return MemoryDevice_update(*args, **kwargs)

        self.range_voltage = MemoryDevice_ch(0., choices=v_range, doc="""
                                          This is for compliance/force. Not for measurement.
                                          It is a MemoryDevice (so cannot be read from instrument.)
                                          See active_range_voltage to see what is the instrument using.
                                          0. means auto range.
                                          Otherwise the range set is a minimum one. It will use higher ones if necessary.
                                          """)
        self.range_current = MemoryDevice_ch(0., choices=i_range, doc="""
                                          This is for compliance/force. Not for measurement.
                                          It is a MemoryDevice (so cannot be read from instrument.)
                                          See active_range_current to see what is the instrument using.
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
                                               lambda v, ch: v[ch][0],
                                               'RI {ch},{val}', choices=i_range_meas, ch_mode=True,
                                               doc='This does not apply on the force channel. Measurement then use the force range.')
        self.range_voltage_meas = CommonDevice(self._get_meas_ranges,
                                               lambda v, ch: v[ch][1],
                                               'RV {ch},{val}', choices=v_range_meas, ch_mode=True,
                                               doc='This does not apply on the force channel. Measurement then use the force range.')
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

        self._integ_choices = ChoiceIndex(['auto', 'manual', 'plc'])
        self.integration_high_speed_mode = CommonDevice(self._get_avg_time_and_autozero,
                                                             lambda v: v['high_speed'][0],
                                                             lambda self, val: self.instr._integration_set_helper(speed=True, mode=val),
                                                             choices=self._integ_choices)
        self.integration_high_resolution_mode = CommonDevice(self._get_avg_time_and_autozero,
                                                             lambda v: v['high_res'][0],
                                                             lambda self, val: self.instr._integration_set_helper(speed=False, mode=val),
                                                             choices=self._integ_choices)
        self.integration_high_speed_time = CommonDevice(self._get_avg_time_and_autozero,
                                                             lambda v: v['high_speed'][1],
                                                             lambda self, val: self.instr._integration_set_helper(speed=True, time=val),
                                                             type=int, min=1, max=1023, setget=True,
                                                             doc=""" time is internally limited to 100 for plc mode """)
        self.integration_high_resolution_time = CommonDevice(self._get_avg_time_and_autozero,
                                                             lambda v: v['high_res'][1],
                                                             lambda self, val: self.instr._integration_set_helper(speed=False, time=val),
                                                             type=int, min=1, max=127, setget=True,
                                                             doc=""" time is internally limited to 100 for plc mode """)

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
        self.meas_last_status = MemoryDevice_update(None, None, nch=Nmax)
        self._devwrap('measI', autoinit=False, trig=True)
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval

        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

    @cache_result
    def _get_enabled_state(self):
        "Returns the enabled state of each channels"
        N = self._N_channels
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
        N = self._N_channels
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
            for ch in self._valid_ch:
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

    def _get_values_helper(self, lrn_type, basename, types=[int], Nv_min=None):
        """ This parses entries like (for basename='AA', types=[float, int])
                AA1,1.,3;AA2,5.,6;AA3...
            with the first integer after AA the ch num
            if basename=['AA', 'BB'] it parses
                AA1,a1;BB1,b1;AA2,a2;BB2,b2 ...
            and returns result as [[a1,b1], [a1,b2], ...]
        """
        Nch = self._N_channels
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
        if len(rs) != Nvalid:
            raise RuntimeError(self.perror('Invalid number of entries for %i'%lrn_type))
        for r, b, off in zip(rs, basename, base_offsets):
            vals = self._parse_block_helper(r, b, types, Nv_min)
            ch = vals[0]
            i = (ch-1)*Nbasename + off
            if state[i] is not None:
                raise RuntimeError(self.perror('Unexpected repeat entry for %i'%lrn_type))
            state[i] = vals[1] if one_val else vals[1:]
        for ch in self._valid_ch:
            i = ch-1
            b = i*Nbasename
            if None in state[b:b+Nbasename]:
                raise RuntimeError(self.perror('Unexpected missing entry for %i'%lrn_type))
        if Nbasename > 1:
            state = [[state[i*Nbasename+j] for j in range(Nbasename)] for i in range(Nch)]
        return state

    def _only_valid_ch(self, list):
        return [l for i,l in enumerate(list) if i+1 in self._valid_ch]

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
        states = self._get_values_helper(55, 'AAD', option_type )
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
        if len(rs) != 3:
            raise RuntimeError(self.perror('Invalid number of elemnts for lrn 56'))
        mode_type = self._integ_choices
        high_speed = self._parse_block_helper(rs[0], 'AIT0,', [mode_type, int]) # mode(0=auto, 1=manual, 2=PLC), time
        high_res = self._parse_block_helper(rs[1], 'AIT1,', [mode_type, int]) # mode(0=auto, 1=manual, 2=PLC), time
        autozero_en = self._parse_block_helper(rs[2], 'AZ', [lambda s: bool(int(s))])
        return dict(high_speed=high_speed,
                    high_res=high_res,
                    autozero_en=autozero_en[0])

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
        enabled = [False]*self._N_channels
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
            comp = None if len(stair) < 7 else stair[6]
            power = None if len(stair) < 8 else stair[7]
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
        Nmax = len(rs) # should be 8 for E5270B mainframe
        options = [r.split(',')for r in rs]
        options_en = [o[0] != '0' for o in options]
        options_dict = {}
        valid_ch = []
        N = 0
        for i, opt in enumerate(options):
            if options_en[i]:
                N += 1
                ch = i+1
                valid_ch.append(ch)
                options_dict[ch] = opt
        return valid_ch, options_dict, Nmax



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
