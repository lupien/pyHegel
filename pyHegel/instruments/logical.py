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

import os
import subprocess
import numpy as np
from scipy.optimize import brentq as brentq_rootsolver
import weakref
import time

from ..instruments_base import BaseDevice, BaseInstrument, ProxyMethod, MemoryDevice,\
                        _find_global_name, _get_conf_header, locked_calling_dev,\
                        FastEvent, wait_on_event
from ..traces import wait
from ..instruments_registry import add_to_instruments

def _asDevice(dev):
    if isinstance(dev, BaseInstrument):
        dev = dev.alias
        if dev is None:
            raise ValueError, 'We required a device, but the given instrument has no alias'
    return dev

class _dummy_delay_Dev(object):
    def __init__(self, log_device_proxy):
        self.log_device = log_device_proxy
    def getcache(self):
        return self.log_device.async_delay

class _LogicalInstrument(BaseInstrument):
    """
        This is only used to handle async mode properly.
        It is not fully functionnal (no create_devs ...)
        We also use it for force_get
    """
    def __init__(self, device, **kwarg):
        super(_LogicalInstrument, self).__init__(**kwarg)
        self.log_device = weakref.proxy(device)
        # We don't want to use _create_devs but we need a working async_delay
        # for the getasync
        self.async_delay = _dummy_delay_Dev(self.log_device)
    def _async_trig(self): #override BaseInstrument versions.
        pass
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        return self.log_device._async_detect(max_time)
    def get_xscale(self):
        self.log_device._get_xscale()
    def _create_devs(self):
        # override the BaseInstrument._create_devs
        # we don't want it here
        pass
    def __del__(self):
        # skip BaseInstrument print statement
        pass


#######################################################
##    Logical Base device
#######################################################

@add_to_instruments
class LogicalDevice(BaseDevice):
    """
       Base device for logical devices.
       Devices can be a device (instrument which will use the alias device)
       or a tuple (device, dict), where dict is the default parameters to pass to get/set/check.
       Need to define instr attribute for getasync, locking and get_xscale (scope)
        also _basedev for default implementation of force_get
             (can be None)
       Need to overwrite force_get method, _current_config
       And may be change getformat

       User either basedev (a single device) or basedevs (a list of devices), not both.
       It could also be neither. For subclasses with basedevs, basedev is then basedevs[0]

       autoget can be 'all', then all basedev or basedevs are get automatically in get and
       getasync. (use self._cached_data in logical _getdev). For a single basedev in can
       be True or False. For Basedevs it can be a list of True or False.
       When autoget is False, we assume the user will perform the get himself so we bypass
       basedev handling in get and getasync (for async this probably only makes sense for devices
       that don't have an async mode.)
       force_get always forces all subdevice unless it is overriden.
       When using async, the attribute async_delay does the same as the async_delay device of
       a normal instrument.

       The quiet_del option prevents the destructor from printing. Useful when within an instrument.
       To include a device within an instrument, do it within _create_devs, so it gets
       to know instrument.device name. _create_devs_helper(once=True) does not work
       for logical device.

       To pass extra parameters to basedev or basedevs, you can often just list them for
       set, get, check and they will be passed on (default _combine_kwarg) or
       you can use option kw with a dict (basedev) or a list of dict (basedevs).
    """
    def __init__(self, basedev=None, basedevs=None, autoget='all', doc='',
                 quiet_del=False, setget=None, autoinit=None, **kwarg):
        # use either basedev (single one) or basedevs, multiple devices
        #   in the latter _basedev = _basedevs[0]
        # can also leave both blank
        # autoinit defaults to the one from _basedev
        self._basedev_orig = basedev
        self._basedevs_orig = basedevs
        basedev_kwarg={}
        if basedev is not None:
            if isinstance(basedev, tuple):
                basedev_kwarg = basedev[1]
                basedev = basedev[0]
            basedev = _asDevice(basedev) # deal with instr.alias
        basedevs_kwarg=[]
        if basedevs is not None:
            if basedev is not None:
                print 'You should not use basedev and basedevs at the same time. basedev is now basedevs[0]'
            basedevs = basedevs[:] # make a copy of the list so we don't change the original
            for i, dev in enumerate(basedevs):
                if isinstance(dev, tuple):
                    basedevs_kwarg.append(dev[1])
                    dev = dev[0]
                else:
                    basedevs_kwarg.append({})
                dev = _asDevice(dev) # deal with instr.alias
                basedevs[i] = dev
            basedev = basedevs[0]
            self._basedevs_N = len(basedevs)
        else:
            self._basedevs_N = -1
        self._basedev = basedev
        self._basedev_kwarg = basedev_kwarg
        self._basedevs = basedevs
        self._basedevs_kwarg = basedevs_kwarg
        self._cached_data = []
        self._autoget = self._autoget_normalize(autoget)
        if basedev:
            if autoinit is None:
                autoinit = basedev._autoinit
            if setget is None:
                setget = basedev._setget
        if autoinit is not None:
            kwarg['autoinit'] = autoinit
        if setget is not None:
            kwarg['setget'] = setget
        self._quiet_del = quiet_del
        super(LogicalDevice, self).__init__(doc=doc, trig=True, **kwarg)
        self._instr_internal = _LogicalInstrument(self)
        self._instr_parent = None
        self.async_delay = 0.
        self._async_done_event = FastEvent()
        fmt = self._format
        if not fmt['header'] and hasattr(self, '_current_config'):
            conf = ProxyMethod(self._current_config)
            fmt['header'] = conf
        # This reference could be used in _current_config (but we already know
        # who we are) and also in _write_dev which can be called from
        # get filename so we cannot just remove it but we must handle it
        # so we can delete this object properly.
        fmt['obj'] = weakref.proxy(self)
        self.name = self.__class__.__name__ # this should not be used
    def __del__(self):
        if not self._quiet_del:
            print 'Deleting logical device:', self
    def _get_docstring(self, added=''):
        added += '\nbasedev=%r\nbasedevs=%r\n'%(self._basedev_orig, self._basedevs_orig)
        return super(LogicalDevice, self)._get_docstring(added=added)

    # These override the behavior when put in an instrument _create_devs is called
    # _create_devs changes self.instr, self.name and self._format['header'] if not set
    # since self._format['header'] should already be set, and self.name is not
    # use by default for Logical device, we only need to protect instr
    @property
    def instr(self):
        return self._instr_internal
    @instr.setter
    def instr(self, val):
        self._instr_parent = val
    def _autoget_normalize(self, autoget):
        if autoget == 'all':
            if self._basedevs:
                autoget = [True]*self._basedevs_N
            else:
                autoget = True
        return autoget
    def _getclassname(self):
        return self.__class__.__name__
    def getfullname(self):
        if self._instr_parent:
            # we have a parent, behave differently
            return self._instr_parent.header.getcache()+'.'+self.name
        gn, cn, p = self._info()
        return gn
    def __repr__(self):
        gn, cn, p = self._info()
        return '<device "%s" (class "%s" at 0x%08x)>'%(gn, cn, p)
    def find_global_name(self):
        if self._instr_parent:
            # we have a parent, behave differently
            return self._instr_parent.find_global_name()+'.'+self.name
        return _find_global_name(self)
    def _info(self):
        return self.find_global_name(), self._getclassname(), id(self)
    def perror(self, error_str='', **dic):
        dic.update(name=self.getfullname())
        return ('{name}: '+error_str).format(**dic)
    def _get_auto_list(self, kwarg={}, autoget=None, op='get'):
        kwarg = kwarg.copy() # just to be safe. It is probably unecessary.
        kwarg_clean = kwarg.copy() # This will be returned if there is no autoget, we just pass all the kwarg including the kw
        kw = kwarg.pop('kw', None)
        devs=[]
        kwargs=[]
        if autoget is None:
            autoget = self._autoget
        autoget = self._autoget_normalize(autoget)
        if autoget == False or (self._basedevs is None and self._basedev is None):
            pass
        elif not self._basedevs and self._basedev is not None:
            if autoget:
                devs = [self._basedev]
                base_kwarg, kwarg_clean = self._combine_kwarg(kwarg, self._basedev_kwarg, op)
                if kw is None:
                    kw = {}
                if not isinstance(kw, dict):
                    raise ValueError, "kw option needs to be a dictionnary"
                base_kwarg.update(kw)
                kwargs = [base_kwarg]
        else:
            if kw is None:
                kw = [{}]*len(self._basedevs)
            if not isinstance(kw, list):
                raise ValueError, "kw option needs to be a list of dictionnary"
            if len(kw) != self._basedevs_N:
                raise ValueError, self.perror('When using kw, it needs to have the correct number of elements. Was %i, should have been %i.'%(len(kw), self._basedevs_N))
            for dev, base_kwarg, subkw, a_get in zip(self._basedevs, self._basedevs_kwarg, kw, autoget):
                if a_get:
                    if not isinstance(subkw, dict):
                        raise ValueError, "kw option needs to be a list of dictionnary"
                    devs.append(dev)
                    base_kwarg, kwarg_clean = self._combine_kwarg(kwarg, base_kwarg, op)
                    base_kwarg.update(subkw)
                    kwargs.append(base_kwarg)
        return zip(devs, kwargs), kwarg_clean
    @locked_calling_dev
    def force_get(self):
        gl, kwarg = self._get_auto_list(autoget='all')
        for dev, kwarg in gl:
            dev.force_get()
        super(LogicalDevice, self).force_get()
    def _getdev_log(self, **kwarg):
        raise NotImplementedError('The logical device is missing its _getdev_log method')
    def _getdev(self, **kwarg):
        if self._autoget == False:
            # we bypass the handling below
            return self._getdev_log(**kwarg)
        # when not doing async, get all basedevs
        # when doing async, the basedevs are obtained automatically
        #task = getattr(self.instr, '_async_task', None) # tasks are deleted when async is done
        #if not (task and task.is_alive()):
        if not self.instr._under_async():
            gl, kwarg = self._get_auto_list(kwarg)
            self._cached_data = []
            for dev, base_kwarg in gl:
                self._cached_data.append(dev.get(**base_kwarg))
        ret = self._getdev_log(**kwarg)
        if self._basedev is not None:
            self._last_filename = self._basedev._last_filename
        #else: # in async_task, we don't know data yet so return something temporary
        #    ret = 'To be replaced' # in getasync
        return ret
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        return wait_on_event(self._async_done_event, max_time=max_time)
    def getasync(self, async, **kwarg):
        if async == 0:
            if self._autoget != False:
                self._async_done_event.clear()
            else:
                self._async_done_event.set()
        gl, kwarg = self._get_auto_list(kwarg)
        if async == 2 and self._autoget != False:
            self._cached_data = []
            for dev, base_kwarg in gl:
                dev.getasync(2, **base_kwarg)
            for dev, base_kwarg in gl:
                self._cached_data.append(dev.getasync(3, **base_kwarg))
            self._async_done_event.set()
            #ret = super(LogicalDevice, self).get(**kwarg)
            # replace data with correct one
            #d = self.instr._get_async_local_data()
            #d.async_task.replace_result(ret)
        elif async == 3 and self._autoget != False:
            pass # we already did that async=3 on subdevices
        else:
            for dev, base_kwarg in gl:
                dev.getasync(async, **base_kwarg)
        return super(LogicalDevice, self).getasync(async, **kwarg)
    def _combine_kwarg(self, kwarg_dict, base=None, op='get'):
        # this combines the kwarg_dict with a base.
        # It returns the new base_device kwarg to use and
        # the possibly cleaned up kwarg for this device.
        # This default ones removes all kwarg and transfer them
        # to the base devices.
        # Overwrite this if necessary.
        # op can be 'get' 'set' 'check'
        # Note that the kw option is always stripped before calling this function.
        if base is None:
            base = self._basedev_kwarg
        base_kwarg = base.copy()
        kwarg_clean = {}
        base_kwarg.update(kwarg_dict)
        return base_kwarg, kwarg_clean
    def _current_config_addbase(self, head, options=None):
        if options is None:
            options={}
        gl, kwarg = self._get_auto_list(options, autoget='all', op='get') # pick op='get' here but we don't really know (could be 'set' or 'check')
        for dev, base_kwarg in gl:
            head.append('::'+dev.getfullname())
            frmt = dev.getformat(**base_kwarg)
            base = _get_conf_header(frmt)
            if base is not None:
                head.extend(base)
        head.append('::other_options=%r'%kwarg)
        return head
    def _get_xscale(self):
        self._basedev.get_xscale()


#######################################################
##    Logical Scaling device
#######################################################

@add_to_instruments()
class ScalingDevice(LogicalDevice):
    """
       This class provides a wrapper around a device.
       On reading, it returns basedev.get()*scale_factor + offset
       On writing it will write basedev.set((val - offset)/scale_factor)
       When only_val is False, get returns a tuple of (converted val, base_device raw)
    """
    def __init__(self, basedev, scale_factor, offset=0., only_val=False, doc='', **extrak):
        self._scale = float(scale_factor)
        self._offset = offset
        self._only_val = only_val
        doc+= 'scale_factor=%g (initial)\noffset=%g'%(scale_factor, offset)
        super(type(self), self).__init__(basedev=basedev, doc=doc, setget=False, **extrak)
        if not only_val:
            self._format['multi'] = ['scale', 'raw']
            self._format['graph'] = [0]
        self._setdev_p = True
        self._getdev_p = True
    def _current_config(self, dev_obj=None, options={}):
        head = ['Scaling:: fact=%r offset=%r basedev=%s'%(self._scale, self._offset, self._basedev.getfullname())]
        return self._current_config_addbase(head, options=options)
    def conv_fromdev(self, raw):
        return raw * self._scale + self._offset
    def conv_todev(self, val):
        return (val - self._offset) / self._scale
    def _prep_output(self, raw):
        val = self.conv_fromdev(raw)
        if self._only_val:
            return val
        else:
            return val, raw
    def _getdev_log(self):
        raw = self._cached_data[0]
        return self._prep_output(raw)
    def _setdev(self, val, **kwarg):
        ((basedev, base_kwarg),), kwarg = self._get_auto_list(kwarg, op='set')
        basedev.set(self.conv_todev(val), **base_kwarg)
        # read basedev cache, in case the values is changed by setget mode.
        raw = self._basedev.getcache(local=True)
        self._set_delayed_cache = self._prep_output(raw)
    def check(self, val, **kwarg):
        ((basedev, base_kwarg),), kwarg = self._get_auto_list(kwarg, op='check')
        raw = self.conv_todev(val)
        basedev.check(raw, **base_kwarg)


#######################################################
##    Logical Function device
#######################################################

@add_to_instruments
class FunctionDevice(LogicalDevice):
    """
       This class provides a wrapper around a device.
       On reading, it returns from_raw(basedev.get())
       On writing it will write basedev.set(toraw)
       from_raw is a function
       to_raw is either a function (the inverse of from_raw).
        or it is the interval of possible raw values
        that is used for the function inversion (scipy.optimize.brent)
       When only_val is False, get returns a tuple of (converted val, base_device raw)
       To check the functions match properly use check_funcs method
    """
    def __init__(self, basedev, from_raw, to_raw=[-1e12, 1e12], only_val=False, doc='', **extrak):
        self.from_raw = from_raw
        self._only_val = only_val
        if isinstance(to_raw, list):
            self._to_raw = to_raw
        else: # assume it is a function
            self.to_raw = to_raw
        super(type(self), self).__init__(basedev=basedev, doc=doc, setget=False, **extrak)
        if not only_val:
            self._format['multi'] = ['conv', 'raw']
            self._format['graph'] = [0]
        self._setdev_p = True
        self._getdev_p = True
    def _current_config(self, dev_obj=None, options={}):
        head = ['Func Convert:: basedev=%s'%(self._basedev.getfullname())]
        return self._current_config_addbase(head, options=options)
    def to_raw(self, val):
        # only handle scalar val not arrays
        func = lambda x: self.from_raw(x)-val
        a,b = self._to_raw
        # extend limits to make sure the limits are invertable
        diff = b-a
        a -= diff/1e6
        b += diff/1e6
        x = brentq_rootsolver(func, a, b)
        return x
    def _prep_output(self, raw):
        val = self.from_raw(raw)
        if self._only_val:
            return val
        else:
            return val, raw
    def _getdev_log(self):
        raw = self._cached_data[0]
        return self._prep_output(raw)
    def _setdev(self, val, **kwarg):
        ((basedev, base_kwarg),), kwarg = self._get_auto_list(kwarg, op='set')
        basedev.set(self.to_raw(val), **base_kwarg)
        raw = self._basedev.getcache(local=True)
        self._set_delayed_cache = self._prep_output(raw)
    def check(self, val, **kwarg):
        ((basedev, base_kwarg),), kwarg = self._get_auto_list(kwarg, op='check')
        raw = self.to_raw(val)
        basedev.check(raw, **base_kwarg)
    def check_funcs(self, start_or_list, stop=None, npoints=None, ret=False):
        """
        Either give a list of point or specify  start, stop and npoints
        These are for the raw values
        When ret is True, it will return points, roundtrip, conv
        where points is the initial list, roundtrip is the list passing
        throught the from/to conversion and conv is the intermediate (from)
        result.
        """
        if isinstance(start_or_list, (list, np.ndarray)):
            points = np.array(start_or_list)
        else:
            points = np.linspace(start_or_list, stop, npoints)
        maxpt = np.abs(points).max()
        conv = np.array([self.from_raw(p) for p in points])
        roundtrip = np.array([self.to_raw(p) for p in conv])
        diff = np.abs(roundtrip - points)
        print 'Largest absolute difference:', diff.max()
        print 'Largest relative difference:', (diff/maxpt).max()
        if ret:
            return points, roundtrip, conv


#######################################################
##    Logical Limit device
#######################################################

@add_to_instruments
class LimitDevice(LogicalDevice):
    """
    This class provides a wrapper around a device that limits the
    value to a user selectable limits.
    """
    def __init__(self, basedev, min=None, max=None, doc='', **extrak):
        if min is None or max is None:
            raise ValueError, 'min and max need to be specified for LimitDevice'
        doc+= 'min,max=%g,%g (initial)'%(min, max)
        super(type(self), self).__init__(basedev=basedev, min=min, max=max, doc=doc, **extrak)
        self._setdev_p = True # needed to enable BaseDevice Check, set (Checking mode)
        self._getdev_p = self._basedev._getdev_p # needed to enable Checking mode of BaseDevice get
    def set_limits(self, min=None, max=None):
        """
           change the limits
           can be called as
           set_limits(0,1) # min=0, max=1
           set_limits(max=2) # min unchanged, max=2
           set_limits(-1) # max unchanged, min=-1
           set_limits(min=-1) # same as above
           set_limits([-4,3]) # min=-4, max=3
        """
        if min is not None and len(min)==2 and max is None:
            self.min = min[0]
            self.max = min[1]
            return
        if min is not None:
            self.min = min
        if max is not None:
            self.max = max
    def _current_config(self, dev_obj=None, options={}):
        head = ['Limiting:: min=%r max=%r basedev=%s'%(self.min, self.max, self._basedev.getfullname())]
        return self._current_config_addbase(head, options=options)
    def _getdev_log(self):
        return self._cached_data[0]
    def _setdev(self, val, **kwarg):
        ((basedev, base_kwarg),), kwarg = self._get_auto_list(kwarg, op='set')
        basedev.set(val, **base_kwarg)
    def check(self, val, **kwarg):
        ((basedev, base_kwarg),), kwarg = self._get_auto_list(kwarg, op='check')
        basedev.check(val, **base_kwarg)
        super(type(self), self).check(val)


#######################################################
##    Logical Copy device
#######################################################

@add_to_instruments
class CopyDevice(LogicalDevice):
    """
       This class provides a wrapper around a device.
       On reading, it returns basedevs[0].get
       On writing it will write to basedev[0], basdev[1] ...
       setget option does nothing here.
       basedevs is a list of dev

       The kwarg of get are the ones of basedevs[0]
       For set and check, the kw argument is a list of
       dictionaries of kwarg for each device.
       When initializing, the devices can be tuple (device, dict)
       where dict will be the default kwarg to pass to the device.
       These can be overriden by the kw argument.
    """
    def __init__(self, basedevs , doc='', **extrak):
        autoget=[False]*len(basedevs)
        autoget[0]=True
        super(CopyDevice, self).__init__(basedevs=basedevs, autoget=autoget, doc=doc, **extrak)
        self._setdev_p = True
        self._getdev_p = True
    def _current_config(self, dev_obj=None, options={}):
        head = ['Copy:: %r'%(self._basedevs)]
        return self._current_config_addbase(head, options=options)
    def _getdev_log(self):
        return self._cached_data[0]
    # Here _setdev and check show 2 different ways of handling the parameters
    # _setdev requires a redefinition of _combine_kwarg
    # note that _get_auto_list always handles the kw paramters itself.
    # If we used the default, _combine_kwarg, we could use either kw or
    # direct paramter to send options to the basedev.
    # i.e. cp.set(1, extra=5) and cp.set(1, kw=[dict(extra=5)]*cp._basedevs_N)
    # would do the same. Here we only allow the second one.
    def _combine_kwarg(self, kwarg_dict, base=None, op='get'):
        if op=='set':
            if kwarg_dict != {}:
                raise TypeError,'Invalid Parameter for CopyDevice.set: %r'%kwarg_dict
            else:
                base_kwarg, kwarg_clean = {}, {}
        base_kwarg, kwarg_clean = super(CopyDevice, self)._combine_kwarg(kwarg_dict, base, op)
        return base_kwarg, kwarg_clean
    def _setdev(self, val, **kwarg): # only allow option kw
        gl, kwarg = self._get_auto_list(kwarg, autoget='all', op='set')
        for dev, base_kwarg in gl:
            dev.set(val, **base_kwarg)
    def check(self, val, kw=None):
        gl, kwarg = self._get_auto_list(dict(kw=kw), autoget='all', op='check')
        for dev, base_kwarg in gl:
            dev.check(val, **base_kwarg)


#######################################################
##    Logical Execute device
#######################################################

@add_to_instruments
class ExecuteDevice(LogicalDevice):
    """
        Performs the get then
        execute some external code and use the returned string has the data
        Only handle get

        The command can contain {filename}, which is replaced by the current filename.
        also available are {root} and {ext} where root is the complete filename
        without the extension and ext is the extension, including
        the separator (.)
        {directory} {basename} where directory is the path to the filename and
        basename is just the filename
        {basenoext} is basename without the extension

        When the executable returns space separated numbers to stdout,
        they can be returned by this device if multi is given as a list
        of the column names.
    """
    def __init__(self, basedev, command, multi=None, doc='', **extrak):
        self._command = command
        doc+= 'command="%s"\n'%(command)
        super(type(self), self).__init__(basedev=basedev, doc=doc, **extrak)
        self._multi = multi
        if multi is not None:
            self._format['multi'] = multi
            self._format['graph'] = range(len(multi))
        self._getdev_p = True
    def getformat(self, **kwarg):
        ((basedev, base_kwarg),), kwarg_clean = self._get_auto_list(kwarg)
        basefmt = basedev.getformat(**base_kwarg)
        self._format['file'] = True
        self._format['bin'] = basefmt['bin']
        return super(type(self), self).getformat(**kwarg)
    def _current_config(self, dev_obj=None, options={}):
        head = ['Execute:: command="%s" basedev=%s'%(self._command, self._basedev.getfullname())]
        return self._current_config_addbase(head, options=options)
    def _getdev_log(self):
        ret = self._cached_data[0]
        command = self._command
        filename = self._basedev._last_filename
        if filename is not None:
            root, ext = os.path.splitext(filename)
            directory, basename = os.path.split(filename)
            basenoext = os.path.splitext(basename)[0]
            command = command.format(filename=filename, root=root, ext=ext,
                                 directory=directory, basename=basename,
                                 basenoext=basenoext)
        if self._multi is None:
            os.system(command)
        else:
            ret = subprocess.check_output(command, shell=True)
            ret = np.fromstring(ret, sep=' ')
        return ret


#######################################################
##    Logical R_Theta device
#######################################################

@add_to_instruments
class RThetaDevice(LogicalDevice):
    """
       This class provides a wrapper around two devices.
       Given offsets for both of them, assuming they
       have the same scale, and if we call their values x,y
       then this devices returns R and theta(deg)
       with R=sqrt(x**2+y**2), theta=angle(x,y)
       It does not allow set to device
       On reading it returns R, theta, raw x ,raw y
       The xoffset, yoffset are used to correct raw_x and raw_y into x,y

       The kwarg of get are applied to both basedevs
       For set and check, the kw argument is a list of
       dictionaries of kwarg for each device.
       When initializing, the devices can be tuple (device, dict)
       where dict will be the default kwarg to pass to the device.
       These can be overriden by the kw argument.
    """
    def __init__(self, baseX, baseY, xoffset=0., yoffset=0., doc='', **extrak):
        super(type(self), self).__init__(basedevs=[baseX, baseY], doc=doc, **extrak)
        self._xoffset = xoffset
        self._yoffset = yoffset
        self._format['multi'] = ['R', 'ThetaDeg', 'raw_x', 'raw_y']
        self._format['graph'] = [0,1]
        self._getdev_p = True
    def _current_config(self, dev_obj=None, options={}):
        head = ['R_Theta_Device:: %r, xoffset=%g, yoffset=%g'%(self._basedevs, self._xoffset, self._yoffset)]
        return self._current_config_addbase(head, options=options)
    def _getdev_log(self):
        raw_x = self._cached_data[0]
        raw_y = self._cached_data[1]
        x = raw_x - self._xoffset
        y = raw_y - self._yoffset
        z = x+1j*y
        R = np.abs(z)
        theta = np.angle(z, deg=True)
        return [R, theta, raw_x, raw_y]

#######################################################
##    Logical PickSome device
#######################################################

@add_to_instruments
class PickSome(LogicalDevice):
    """
       This class provides a wrapper around one device for reading only.
       It allows to take a device that returns many points which are
       usually dumped into a separate file and pick some of those points
       to save in the main file.
    """
    def __init__(self, basedev, selector, multi, doc='', **extrak):
        """
        selector will be used to pick some data. The data returned from this
                 device is: basedev.get()[selector]
                 if a=basedev.get() then the result of a[1,0] is
                 obtained by selector=(1,0) and a[1,:3] by
                 selector=(1,slice(3))
        multi is either an integer that gives the number of data that will be
              returned (the number of columns added to the file)
              or a list with the names of the columns.
        """
        if not isinstance(multi, list):
            multi = ['base-%i'%i for i in range(multi)]
        super(type(self), self).__init__(basedev=basedev, doc=doc, multi=multi, **extrak)
        self._selector = selector
        self._getdev_p = True
    def _current_config(self, dev_obj=None, options={}):
        head = ['PickSome:: %r, selector=%r'%(self._basedev, self._selector)]
        return self._current_config_addbase(head, options=options)
    def _getdev_log(self):
        raw = self._cached_data[0]
        return raw[self._selector]

#######################################################
##    Logical average device
#######################################################

@add_to_instruments
class Average(LogicalDevice):
    """
       This class provides a wrapper around one device for reading only.
       It provides an averaged value over a certain interval.
       It returns the averaged values followed by the std deviations and the number
       of samples used.
       Even in async mode the basedev is called directly multiple times by the get function.
       To use other functions of the basedev it should not lock them out.
       The basedev is not set itself in async mode.
    """
    def __init__(self, basedev, filter_time=5., repeat_time=.1, show_repeats=False, doc='', **extrak):
        """
        filter_time is the length of time to filer in seconds
        repeat_time is the minimum time between readings of the instrument.
                    There will always be at least a 20 ms wait
        show_repeats will count the number of repeats and print them
        """
        super(type(self), self).__init__(basedev=basedev, doc=doc, multi=['avg', 'std'], autoget=False, **extrak)
        self._filter_time = filter_time
        self._repeat_time = repeat_time
        self._show_repeats = show_repeats
        self._getdev_p = True
    #def _combine_kwarg(self, kwarg_dict, base=None, op='get'):
    #    # the base kwarg_clean is made empty and it is used in the call to _getdev
    #    # here we want the parameters to propagate to _getdev
    #    base_kwarg, kwarg_clean = super(Average, self)._combine_kwarg(kwarg_dict, base, op)
    #    return base_kwarg, base_kwarg
    def getformat(self, **kwarg):
        gl, foo = self._get_auto_list(kwarg, autoget='all', op='get')
        dev, base_kwarg  = gl[0]
        base_format = dev.getformat(**base_kwarg)
        base_multi = base_format['multi']
        base_graph = base_format['graph']
        fmt = self._format
        if isinstance(base_multi, list):
            multi = [s+'avg' for s in base_multi] + [s+'std' for s in base_multi]
        else:
            multi = ['avg', 'std']
        multi += ['N']
        fmt.update(multi=multi, graph=base_graph)
        return super(Average, self).getformat(**kwarg)
    def _current_config(self, dev_obj=None, options={}):
        head = ['Average:: %r, filter_time=%r, repeat_time=%r'%(self._basedev, self._filter_time, self._repeat_time)]
        return self._current_config_addbase(head, options=options)
    def _getdev_log(self, **kwarg):
        gl, foo = self._get_auto_list(kwarg, autoget='all', op='get')
        dev, base_kwarg  = gl[0]
        to = time.time()
        vals = [dev.get(**base_kwarg)]
        last = to
        now = to
        while now - to < self._filter_time:
            dt = self._repeat_time - (now-last)
            dt = max(dt, 0.020) # sleep at least 20 ms
            wait(dt)
            last = time.time() # do it here so we remove the time it takes to do the gets
            vals.append(dev.get(**base_kwarg))
            now = time.time()
        vals = np.array(vals)
        if self._show_repeats:
            diff = np.diff(vals, axis=0)
            w = np.where( np.abs(diff) < 1e-10)[-1]
            if len(w) == 0:
                print 'Number of repeats: None'
            else:
                print 'Number of repeats: ', np.bincount(w, minlength=vals.shape[-1])
        avg = vals.mean(axis=0)
        std = vals.std(axis=0, ddof=1)
        N = vals.shape[0]
        if avg.ndim == 0:
            ret = [avg, std]
        else:
            ret = list(avg)+list(std)
        return ret + [N]


#######################################################
##    Logical wrap device
#######################################################

@add_to_instruments
class FunctionWrap(LogicalDevice):
    """
       This class provides a wrapper around functions.
       It is an easy way to turn a function into a device (to use in sweep/record)
    """
    def __init__(self, setfunc=None, getfunc=None, checkfunc=None, getformatfunc=None, use_ret_as_cache=False,
                 basedev=None, basedevs=None, basedev_as_param=False, autoget=False, doc='', **extrak):
        """
        Define at least one of setfunc or getfunc.
        checkfunc is called by a set. If not specified, the default one is used (can handle
        choices or min/max).
        getformatfunc can be defined if necessary. There is a default one.
        use_ret_as_cache: will use the return value from set as the cached value.
        If you define a basedev or a basedevs list, those devices are included in the
        file headers. They are not read by default (autoget=False). If autoget is is set to 'all'
        then the getfunc function can use getcache(local=True) on the basedev(s) devices; otherwise it needs to use get.
        With autoget enable, and basedev_as_param True, then the getfunc function is called with the first argument
        being the list of basedev values.
        """
        super(type(self), self).__init__(doc=doc, basedev=basedev, basedevs=basedevs, autoget=autoget, **extrak)
        self._setdev_p = setfunc
        self._getdev_p = getfunc
        self._checkfunc = checkfunc
        self._use_ret = use_ret_as_cache
        self._getformatfunc = getformatfunc
        self._basedev_as_param = basedev_as_param
    def _current_config(self, dev_obj=None, options={}):
        head = ['FunctionWrap:: set=%r, get=%r, check=%r, getformat=%r, user_ret_as_cache=%r'%(
                self._setdev_p, self._getdev_p, self._checkfunc, self._getformatfunc, self._use_ret)]
        return self._current_config_addbase(head, options=options)
    def _getdev_log(self, **kwarg):
        if not self._getdev_p:
            raise NotImplementedError('This FunctionWrap device does not have a getfunc')
        if self._autoget and self._basedev_as_param:
           return self._getdev_p(self._cached_data, **kwarg)
        else:
            return self._getdev_p(**kwarg)
    def _setdev(self, val, **kwarg):
        if not self._setdev_p:
            raise NotImplementedError('This FunctionWrap device does not have a setfunc')
        ret = self._setdev_p(val, **kwarg)
        if self._use_ret:
            self._set_delayed_cache = ret
    def check(self, val, **kwarg):
        if not self._checkfunc:
            super(FunctionWrap, self).check(val, **kwarg)
        else:
            self._checkfunc(val, **kwarg)
    def getformat(self, **kwarg):
        if not self._getformatfunc:
            return super(FunctionWrap, self).getformat(**kwarg)
        else:
            return self._getformatfunc(**kwarg)

