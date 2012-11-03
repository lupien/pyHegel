# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

import os
import subprocess
import numpy as np
from scipy.optimize import brentq as brentq_rootsolver

from instruments_base import BaseDevice, BaseInstrument, ProxyMethod,\
                        _find_global_name, _get_conf_header

def _asDevice(dev):
    if isinstance(dev, BaseInstrument):
        dev = dev.alias
    return dev

#######################################################
##    Logical Base device
#######################################################

class LogicalDevice(BaseDevice):
    """
       Base device for logical devices.
       Devices can be a device (instrument which will use the alias device)
       or a tuple (device, dict), where dict is the default parameters to pass to get/set/check.
       Need to define instr attribute for getasync and get_xscale (scope)
        also _basedev for default implementation of force_get
             (can be None)
       Need to overwrite force_get method, _current_config
       And may be change getformat
    """
    def __init__(self, basedev=None, basedevs=None, doc='', setget=None, autoinit=None, **kwarg):
        # use either basedev (single one) or basedevs, multiple devices
        #   in the latter _basedev = _basedevs[0]
        # can also leave both blank
        # autoinit defaults to the one from _basedev
        # self.instr set to self._basedev.inst if available
        basedev_orig = basedev
        basedevs_orig = basedevs
        basedev_kwarg={}
        if basedev != None:
            if isinstance(basedev, tuple):
                basedev_kwarg = basedev[1]
                basedev = basedev[0]
            basedev = _asDevice(basedev) # deal with instr.alias
        basedevs_kwarg=[]
        if basedevs != None:
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
        self._basedev_internal = basedev
        self._basedev_kwarg = basedev_kwarg
        self._basedevs = basedevs
        self._basedevs_kwarg = basedevs_kwarg
        # TODO fix the problem here
        #doc = self.__doc__+doc+'\nbasedev=%r\nbasedevs=%r\n'%(basedev, basedevs)
        doc = doc+'\nbasedev=%r\nbasedevs=%r\n'%(basedev_orig, basedevs_orig)
        if basedev:
            if autoinit == None:
                autoinit = basedev._autoinit
            if setget == None:
                setget = basedev._setget
            #kwarg['trig'] = basedev._trig
            #kwarg['delay'] = basedev._delay
            kwarg['redir_async'] = basedev
        if autoinit != None:
            kwarg['autoinit'] = autoinit
        if setget != None:
            kwarg['setget'] = setget
        super(LogicalDevice, self).__init__(doc=doc, **kwarg)
        if self._basedev:
            self.instr = basedev.instr
        fmt = self._format
        if not fmt['header'] and hasattr(self, '_current_config'):
            conf = ProxyMethod(self._current_config)
            fmt['header'] = conf
        self.name = self.__class__.__name__ # this should not be used
    @property
    def _basedev(self):
        # when in async mode, _basdev needs to point to possibly redirected device
        basedev = self._basedev_internal
        basedev_redir = self._do_redir_async()
        alive = False
        if basedev and basedev_redir.instr._async_task:
            alive  = basedev_redir.instr._async_task.is_alive()
        if alive:
            return basedev_redir
        return self._basedev_internal
    def _getclassname(self):
        return self.__class__.__name__
    def getfullname(self):
        gn, cn, p = self._info()
        return gn
    def __repr__(self):
        gn, cn, p = self._info()
        return '<device "%s" (class "%s" at 0x%08x)>'%(gn, cn, p)
    def find_global_name(self):
        return _find_global_name(self)
    def _info(self):
        return self.find_global_name(), self._getclassname(), id(self)
    def perror(self, error_str='', **dic):
        dic.update(name=self.getfullname())
        return ('{name}: '+error_str).format(**dic)
    def force_get(self):
        if self._basedev != None:
            self._basedev.force_get()
    def get(self, *arg, **kwarg):
        ret = super(LogicalDevice, self).get(*arg, **kwarg)
        if self._basedev != None and self._basedev._last_filename:
            self._last_filename = self._basedev._last_filename
        return ret
    def getasync(self, async, **kwarg):
        # same as basename except we keep obj.get as self.get
        obj = self._do_redir_async()
        return obj.instr._get_async(async, self,
                           trig=obj._trig, delay=obj._delay, **kwarg)
    def _combine_kwarg(self, kwarg_dict, base=None):
        if base == None:
            base = self._basedev_kwarg
        kwarg = base.copy()
        kwarg.update(kwarg_dict)
        return kwarg
    def _current_config_addbase(self, head, options=None):
        # When using basedevs, options needs to be a list of dict
        devs = self._basedevs
        kwargs = self._basedevs_kwarg
        if options == None:
            options = {}
        if not devs:
            if self._basedev:
                devs = [self._basedev]
                kwargs = [self._basedev_kwarg]
                options = [options]
            else:
                devs = []
                kwargs = []
                options = []
        if options == {}:
            options = [{}] * self._basedevs_N
        for dev, kwarg, opt in zip(devs, kwargs, options):
            kwarg = kwarg.copy()
            kwarg.update(opt)
            head.append('::'+dev.getfullname())
            frmt = dev.getformat(**kwarg)
            base = _get_conf_header(frmt)
            if base != None:
                head.extend(base)
        return head


#######################################################
##    Logical Scaling device
#######################################################

class ScalingDevice(LogicalDevice):
    """
       This class provides a wrapper around a device.
       On reading, it returns basedev.get()*scale_factor + offset
       On writing it will write basedev.set((val - offset)/scale_factor)
    """
    def __init__(self, basedev, scale_factor, offset=0., doc='', **extrak):
        self._scale = float(scale_factor)
        self._offset = offset
        doc+= 'scale_factor=%g (initial)\noffset=%g'%(scale_factor, offset)
        super(type(self), self).__init__(basedev=basedev, doc=doc, **extrak)
        self._format['multi'] = ['scale', 'raw']
        self._format['graph'] = [0]
    def _current_config(self, dev_obj=None, options={}):
        head = ['Scaling:: fact=%r offset=%r basedev=%s'%(self._scale, self._offset, self._basedev.getfullname())]
        return self._current_config_addbase(head, options=options)
    def conv_fromdev(self, raw):
        return raw * self._scale + self._offset
    def conv_todev(self, val):
        return (val - self._offset) / self._scale
    def _getdev(self, **kwarg):
        kwarg = self._combine_kwarg(kwarg)
        raw = self._basedev.get(**kwarg)
        val = self.conv_fromdev(raw)
        return val, raw
    def _setdev(self, val, **kwarg):
        kwarg = self._combine_kwarg(kwarg)
        self._basedev.set(self.conv_todev(val), **kwarg)
        # read basedev cache, in case the values is changed by setget mode.
        self._cache = self.conv_fromdev(self._basedev.getcache())
    def check(self, val, **kwarg):
        kwarg = self._combine_kwarg(kwarg)
        raw = self.conv_todev(val)
        self._basedev.check(raw, **kwarg)


#######################################################
##    Logical Function device
#######################################################

class FunctionDevice(LogicalDevice):
    """
       This class provides a wrapper around a device.
       On reading, it returns from_raw(basedev.get())
       On writing it will write basedev.set(toraw)
       from_raw is a function
       to_raw is either a function (the inverse of from_raw).
        or it is the interval of possible raw values
        that is used for the function inversion (scipy.optimize.brent)
    """
    def __init__(self, basedev, from_raw, to_raw=[-1e12, 1e12], doc='', **extrak):
        self.from_raw = from_raw
        if isinstance(to_raw, list):
            self._to_raw = to_raw
        else: # assume it is a function
            self.to_raw = to_raw
        super(type(self), self).__init__(basedev=basedev, doc=doc, **extrak)
        self._format['multi'] = ['conv', 'raw']
        self._format['graph'] = [0]
        self._format['header'] = self._current_config
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
    def _getdev(self, **kwarg):
        kwarg = self._combine_kwarg(kwarg)
        raw = self._basedev.get(**kwarg)
        val = self.from_raw(raw)
        return val, raw
    def _setdev(self, val, **kwarg):
        kwarg = self._combine_kwarg(kwarg)
        self._basedev.set(self.to_raw(val), **kwarg)
    def check(self, val, **kwarg):
        kwarg = self._combine_kwarg(kwarg)
        raw = self.to_raw(val)
        self._basedev.check(raw, **kwarg)


#######################################################
##    Logical Limit device
#######################################################

class LimitDevice(LogicalDevice):
    """
    This class provides a wrapper around a device that limits the
    value to a user selectable limits.
    """
    def __init__(self, basedev, min=None, max=None, doc='', **extrak):
        if min==None or max==None:
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
        if min != None and len(min)==2 and max==None:
            self.min = min[0]
            self.max = min[1]
            return
        if min != None:
            self.min = min
        if max != None:
            self.max = max
    def _current_config(self, dev_obj=None, options={}):
        head = ['Limiting:: min=%r max=%r basedev=%s'%(self.min, self.max, self._basedev.getfullname())]
        return self._current_config_addbase(head, options=options)
    def _getdev(self, **kwarg):
        kwarg = self._combine_kwarg(kwarg)
        return self._basedev.get(**kwarg)
    def _setdev(self, val, **kwarg):
        kwarg = self._combine_kwarg(kwarg)
        self._basedev.set(val, **kwarg)
    def check(self, val, **kwarg):
        kwarg = self._combine_kwarg(kwarg)
        self._basedev.check(val, **kwarg)
        super(type(self), self).check(val)


#######################################################
##    Logical Copy device
#######################################################

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
        super(type(self), self).__init__(basedevs=basedevs, doc=doc, **extrak)
    def _current_config(self, dev_obj=None, options={}):
        head = ['Copy:: %r'%(self._basedevs)]
        return self._current_config_addbase(head, options=options.get('kw', None))
    def _getdev(self, **kwarg):
        kwarg = self._combine_kwarg(kwarg, base=self._basedevs_kwarg[0])
        return self._basedevs[0].get(**kwarg)
    def _setdev(self, val, kw=None):
        if kw == None:
            kw = [{}]*self._basedevs_N
        if len(kw) != self._basedevs_N:
            raise ValueError, self.perror('When using kw, it needs to have the correct number of elements. Was %i, should have been %i.'%(len(kw), self._basedevs_N))
        for dev, kwarg, kw_over in zip(self._basedevs, self._basedevs_kwarg, kw):
            kwarg = self._combine_kwarg(kw_over, base=kwarg)
            dev.set(val, **kwarg)
    def check(self, val, kw=None):
        if kw == None:
            kw = [{}]*self._basedevs_N
        if len(kw) != self._basedevs_N:
            raise ValueError, self.perror('When using kw, it needs to have the correct number of elements. Was %i, should have been %i.'%(len(kw), self._basedevs_N))
        for dev, kwarg, kw_over in zip(self._basedevs, self._basedevs_kwarg, kw):
            kwarg = self._combine_kwarg(kw_over, base=kwarg)
            dev.check(val, **kwarg)
    def force_get(self):
        for dev in self._basedevs:
            dev.force_get()


#######################################################
##    Logical Execute device
#######################################################

class ExecuteDevice(LogicalDevice):
    """
        Performs the get then
        execute some external code and use the returned string has the data
        Only handle get

        The command can contain {filename}, which is replaced by the current filename.
        also available are {root} and {ext} where ext is the extension, including
        the separator (.)
        {directory} {basename} where directory is the path to the filename and
        basename is just the filename
        {basenoext} is basename without the extension
    """
    def __init__(self, basedev, command, multi=None, doc='', **extrak):
        self._command = command
        doc+= 'command="%s"\n'%(command)
        super(type(self), self).__init__(basedev=basedev, doc=doc, **extrak)
        self._multi = multi
        if multi != None:
            self._format['multi'] = multi
            self._format['graph'] = [0]
    def getformat(self, **kwarg):
        kwarg_base = self._combine_kwarg(kwarg)
        basefmt = self._basedev.getformat(**kwarg_base)
        self._format['file'] = True
        self._format['bin'] = basefmt['bin']
        return super(type(self), self).getformat(**kwarg)
    def _current_config(self, dev_obj=None, options={}):
        head = ['Execute:: command="%s" basedev=%s'%(self._command, self._basedev.getfullname())]
        return self._current_config_addbase(head, options=options)
    def _getdev(self, filename=None, **kwarg):
        kwarg = self._combine_kwarg(kwarg)
        if filename != None:
            kwarg['filename'] = filename
        ret = self._basedev.get(**kwarg)
        command = self._command
        filename = self._basedev._last_filename
        if filename != None:
            root, ext = os.path.splitext(filename)
            directory, basename = os.path.split(filename)
            basenoext = os.path.splitext(basename)[0]
            command = command.format(filename=filename, root=root, ext=ext,
                                 directory=directory, basename=basename,
                                 basenoext=basenoext)
        if self._multi == None:
            os.system(command)
        else:
            ret = subprocess.check_output(command, shell=True)
            ret = np.fromstring(ret, sep=' ')
        return ret


#######################################################
##    Logical R_Theta device
#######################################################

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
    def __init__(self, basedevs, xoffset=0., yoffset=0., doc='', **extrak):
        self._xoffset = xoffset
        self._yoffset = yoffset
        super(type(self), self).__init__(basedevs=basedevs, doc=doc, **extrak)
        self._format['multi'] = ['R', 'ThetaDeg', 'raw_x', 'raw_y']
        self._format['graph'] = [0,1]
        self._format['header'] = self._current_config
    def _current_config(self, dev_obj=None, options={}):
        head = ['R_Theta_Device:: %r, xoffset=%g, yoffset=%g'%(self._basedevs, self._xoffset, self._yoffset)]
        return self._current_config_addbase(head, options=options.get('kw', None))
    def _getdev(self, **kwarg):
        kwarg = self._combine_kwarg(kwarg, base=self._basedevs_kwarg[0])
        raw_x = self._basedevs[0].get(**kwarg)
        raw_y = self._basedevs[1].get(**kwarg)
        x = raw_x - self._xoffset
        y = raw_y - self._yoffset
        z = x+1j*y
        R = np.abs(z)
        theta = np.angle(z, deg=True)
        return [R, theta, raw_x, raw_y]
    def _setdev(self, val):
        raise ValueError, "This is not allowed"
    def check(self, val):
        raise ValueError, "This is not allowed"
    def force_get(self):
        for dev in self._basedevs:
            dev.force_get()