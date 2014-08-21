# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

import os
import subprocess
import numpy as np
from scipy.optimize import brentq as brentq_rootsolver
import weakref
import time

from instruments_base import BaseDevice, BaseInstrument, ProxyMethod,\
                        _find_global_name, _get_conf_header, locked_calling_dev
from traces import wait

def _asDevice(dev):
    if isinstance(dev, BaseInstrument):
        dev = dev.alias
        if dev == None:
            raise ValueError, 'We required a device, but the given instrument has no alias'
    return dev

class _LogicalInstrument(BaseInstrument):
    """
        This is only used to handle async mode properly.
        It is not fully functionnal (no create_devs ...)
        We also use it for force_get
    """
    def __init__(self, device, **kwarg):
        super(_LogicalInstrument, self).__init__(**kwarg)
        self.log_device = weakref.proxy(device)
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

       autoget can be 'all', then all basedev or basedevs are get automatically in get and
       getasync. (use self._cached_data in logical _getdev). For a single basedev in can
       be True or False. For Basedevs it can be a list of True or False.
       force_get always forces all subdevice unless it is overriden.

       To pass extra parameters to basedev or basedevs, you can often just list them for
       set, get, check and they will be passed on (default _combine_kwarg) or
       you can use option kw with a dict (basedev) or a list of dict (basedevs).
    """
    def __init__(self, basedev=None, basedevs=None, autoget='all', doc='', setget=None, autoinit=None, **kwarg):
        # use either basedev (single one) or basedevs, multiple devices
        #   in the latter _basedev = _basedevs[0]
        # can also leave both blank
        # autoinit defaults to the one from _basedev
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
        self._basedev = basedev
        self._basedev_kwarg = basedev_kwarg
        self._basedevs = basedevs
        self._basedevs_kwarg = basedevs_kwarg
        self._cached_data = []
        self._autoget = self._autoget_normalize(autoget)
        # TODO fix the problem here
        #doc = self.__doc__+doc+'\nbasedev=%r\nbasedevs=%r\n'%(basedev, basedevs)
        doc = doc+'\nbasedev=%r\nbasedevs=%r\n'%(basedev_orig, basedevs_orig)
        if basedev:
            if autoinit == None:
                autoinit = basedev._autoinit
            if setget == None:
                setget = basedev._setget
        if autoinit != None:
            kwarg['autoinit'] = autoinit
        if setget != None:
            kwarg['setget'] = setget
        super(LogicalDevice, self).__init__(doc=doc, trig=True, **kwarg)
        self.instr = _LogicalInstrument(self)
        fmt = self._format
        if not fmt['header'] and hasattr(self, '_current_config'):
            conf = ProxyMethod(self._current_config)
            fmt['header'] = conf
        # Remove the reference to self. This allows del to work
        # Not a problem since our _current_config method already
        # knows self.
        fmt['obj'] = None
        self.name = self.__class__.__name__ # this should not be used
    def __del__(self):
        print 'Deleting logical device:', self
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
    def _get_auto_list(self, kwarg={}, autoget=None, op='get'):
        kwarg = kwarg.copy() # just to be safe. It is probably unecessary.
        kw = kwarg.pop('kw', None)
        devs=[]
        kwargs=[]
        kwarg_clean = {}
        if autoget == None:
            autoget = self._autoget
        autoget = self._autoget_normalize(autoget)
        if not self._basedevs and self._basedev != None:
            if autoget:
                devs = [self._basedev]
                base_kwarg, kwarg_clean = self._combine_kwarg(kwarg, self._basedev_kwarg, op)
                if kw == None:
                    kw = {}
                if not isinstance(kw, dict):
                    raise ValueError, "kw option needs to be a dictionnary"
                base_kwarg.update(kw)
                kwargs = [base_kwarg]
        else:
            if kw == None:
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
    @locked_calling_dev
    def get(self, **kwarg):
        # when not doing async, get all basedevs
        # when doing async, the basedevs are obtained automatically
        task = getattr(self.instr, '_async_task', None) # tasks are deleted when async is done
        if not (task and task.is_alive()):
            gl, kwarg = self._get_auto_list(kwarg)
            self._cached_data = []
            for dev, base_kwarg in gl:
                self._cached_data.append(dev.get(**base_kwarg))
            ret = super(LogicalDevice, self).get(**kwarg)
            if self._basedev != None and self._basedev._last_filename:
                self._last_filename = self._basedev._last_filename
        else: # in async_task, we don't know data yet so return something temporary
            ret = 'To be replaced' # in getasync
        return ret
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        return True # No need to wait
    def getasync(self, async, **kwarg):
        gl, kwarg = self._get_auto_list(kwarg)
        if async == 3:
            self._cached_data = []
            for dev, base_kwarg in gl:
                self._cached_data.append(dev.getasync(async, **base_kwarg))
            ret = super(LogicalDevice, self).get(**kwarg)
            # replace data with correct one
            self.instr._async_task.replace_result(ret)
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
        if base == None:
            base = self._basedev_kwarg
        base_kwarg = base.copy()
        kwarg_clean = {}
        base_kwarg.update(kwarg_dict)
        return base_kwarg, kwarg_clean
    def _current_config_addbase(self, head, options=None):
        if options==None:
            options={}
        gl, kwarg = self._get_auto_list(options, autoget='all', op='get') # pick op='get' here but we don't really know (could be 'set' or 'check')
        for dev, base_kwarg in gl:
            head.append('::'+dev.getfullname())
            frmt = dev.getformat(**base_kwarg)
            base = _get_conf_header(frmt)
            if base != None:
                head.extend(base)
        head.append('::other_options=%r'%kwarg)
        return head
    def _get_xscale(self):
        self._basedev.get_xscale()


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
    def _getdev(self):
        raw = self._cached_data[0]
        val = self.conv_fromdev(raw)
        return val, raw
    def _setdev(self, val, **kwarg):
        ((basedev, base_kwarg),), kwarg = self._get_auto_list(kwarg, op='set')
        basedev.set(self.conv_todev(val), **base_kwarg)
        # read basedev cache, in case the values is changed by setget mode.
        self._cache = self.conv_fromdev(self._basedev.getcache())
    def check(self, val, **kwarg):
        ((basedev, base_kwarg),), kwarg = self._get_auto_list(kwarg, op='check')
        raw = self.conv_todev(val)
        basedev.check(raw, **base_kwarg)


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
    def _getdev(self):
        raw = self._cached_data[0]
        val = self.from_raw(raw)
        return val, raw
    def _setdev(self, val, **kwarg):
        ((basedev, base_kwarg),), kwarg = self._get_auto_list(kwarg, op='set')
        basedev.set(self.to_raw(val), **base_kwarg)
    def check(self, val, **kwarg):
        ((basedev, base_kwarg),), kwarg = self._get_auto_list(kwarg, op='check')
        raw = self.to_raw(val)
        basedev.check(raw, **base_kwarg)


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
    def _getdev(self):
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
    def _current_config(self, dev_obj=None, options={}):
        head = ['Copy:: %r'%(self._basedevs)]
        return self._current_config_addbase(head, options=options)
    def _getdev(self):
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
        if multi != None:
            self._format['multi'] = multi
            self._format['graph'] = range(len(multi))
    def getformat(self, **kwarg):
        ((basedev, base_kwarg),), kwarg_clean = self._get_auto_list(kwarg)
        basefmt = basedev.getformat(**base_kwarg)
        self._format['file'] = True
        self._format['bin'] = basefmt['bin']
        return super(type(self), self).getformat(**kwarg)
    def _current_config(self, dev_obj=None, options={}):
        head = ['Execute:: command="%s" basedev=%s'%(self._command, self._basedev.getfullname())]
        return self._current_config_addbase(head, options=options)
    def _getdev(self):
        ret = self._cached_data[0]
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
    def __init__(self, baseX, baseY, xoffset=0., yoffset=0., doc='', **extrak):
        super(type(self), self).__init__(basedevs=[baseX, baseY], doc=doc, **extrak)
        self._xoffset = xoffset
        self._yoffset = yoffset
        self._format['multi'] = ['R', 'ThetaDeg', 'raw_x', 'raw_y']
        self._format['graph'] = [0,1]
    def _current_config(self, dev_obj=None, options={}):
        head = ['R_Theta_Device:: %r, xoffset=%g, yoffset=%g'%(self._basedevs, self._xoffset, self._yoffset)]
        return self._current_config_addbase(head, options=options)
    def _getdev(self):
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
    def _current_config(self, dev_obj=None, options={}):
        head = ['PickSome:: %r, selector=%r'%(self._basedev, self._selector)]
        return self._current_config_addbase(head, options=options)
    def _getdev(self):
        raw = self._cached_data[0]
        return raw[self._selector]

#######################################################
##    Logical average device
#######################################################

class Average(LogicalDevice):
    """
       This class provides a wrapper around one device for reading only.
       It provides an averaged value over a certain interval.
       It returns the averaged values followed by the std deviations and the number
       of samples used.
    """
    def __init__(self, basedev, filter_time=5., repeat_time=.1, doc='', **extrak):
        """
        filter_time is the length of time to filer in seconds
        repeat_time is the minimum time between readings of the instrument.
                    There will always be at least a 20 ms wait
        """
        super(type(self), self).__init__(basedev=basedev, doc=doc, multi=['avg', 'std'], autoget=False, **extrak)
        self._filter_time = filter_time
        self._repeat_time = repeat_time
    def getformat(self, **kwarg):
        kwarg_base = kwarg
        kwarg, foo = self._combine_kwarg(kwarg)
        base_format = self._basedev.getformat(**kwarg)
        base_multi = base_format['multi']
        base_graph = base_format['graph']
        fmt = self._format
        if isinstance(base_multi, list):
            multi = [s+'avg' for s in base_multi] + [s+'std' for s in base_multi]
        else:
            multi = ['avg', 'std']
        multi += ['N']
        fmt.update(multi=multi, graph=base_graph)
        return super(Average, self).getformat(**kwarg_base)
    def _current_config(self, dev_obj=None, options={}):
        head = ['Average:: %r, filter_time=%r, repeat_time=%r'%(self._basedev, self._filter_time, self._repeat_time)]
        return self._current_config_addbase(head, options=options)
    def _getdev(self, **kwarg):
        kwarg, foo = self._combine_kwarg(kwarg)
        to = time.time()
        vals = [self._basedev.get(**kwarg)]
        last = to
        now = to
        while now - to < self._filter_time:
            dt = self._repeat_time - (now-last)
            dt = max(dt, 0.020) # sleep at least 20 ms
            wait(dt)
            last = time.time() # do it here so we remove the time it takes to do the gets
            vals.append(self._basedev.get(**kwarg))
            now = time.time()
        vals = np.array(vals)
        avg = vals.mean(axis=0)
        std = vals.std(axis=0, ddof=1)
        N = vals.shape[0]
        if avg.ndim == 0:
            ret = [avg, std, N]
        else:
            ret = list(avg)+list(std)
        return ret + [N]
