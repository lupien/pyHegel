# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

try:
  import visa
  vpp43 = visa.vpp43
except ImportError:
  print 'Error importing visa. You will have reduced functionality.'
#can list instruments with : 	visa.get_instruments_list()
#     or :                      visa.get_instruments_list(use_aliases=True)

import numpy as np
import string
import functools
import random
import os
import subprocess
import time
import threading
import weakref
from collections import OrderedDict  # this is a subclass of dict
from PyQt4 import QtGui, QtCore
import scipy
from scipy.optimize import brentq as brentq_rootsolver

import traces

_globaldict = dict() # This is set in pynoise.py
CHECKING = False

class ProxyMethod(object):
    def __init__(self, bound_method):
        #self.class_of_method = bound_method.im_class
        self.instance = weakref.proxy(bound_method.im_self)
        self.func_name = bound_method.func_name
    def __call__(self, *arg, **kwarg):
        return getattr(self.instance, self.func_name)(*arg, **kwarg)

def find_all_instruments():
    return visa.get_instruments_list()

def _repr_or_string(val):
    if isinstance(val, basestring):
        return val
    else:
        return repr(val)


def _writevec_flatten_list(vals_list):
    ret = []
    for val in vals_list:
        if isinstance(val, np.ndarray):
            ret.extend(list(val.flatten()))
        else:
            ret.append(val)
    return ret

def _writevec(file_obj, vals_list, pre_str=''):
    vals_list = _writevec_flatten_list(vals_list)
    strs_list = map(_repr_or_string, vals_list)
    file_obj.write(pre_str+string.join(strs_list,'\t')+'\n')


def _get_conf_header_util(header, obj, options):
    if callable(header):
        header = header(obj, options)
    if header: # if either is not None or not ''
        if isinstance(header, basestring):
            header=[header]
    return header

# header or header() can be None, '' or False for no output
# otherwise it can be a single string for a single line or
#  a list of strings. Don't include the comment character or the newline.
def _get_conf_header(format):
    header = format['header']
    obj = format['obj']
    options = format['options']
    return _get_conf_header_util(header, obj, options)

def _replace_ext(filename, newext=None):
    if newext == None:
        return filename
    root, ext = os.path.splitext(filename)
    return root+newext


def _write_dev(val, filename, format=format, first=False):
    append = format['append']
    bin = format['bin']
    dev = format['obj']
    doheader = True
    if bin:
        doheader = False
    if append and not first:
        open_mode = 'a'
        doheader = False
    else:
        open_mode = 'w'
    if bin:
        open_mode += 'b'
        if bin != '.ext':
            filename = _replace_ext(filename, bin)
    f=open(filename, open_mode)
    dev._last_filename = filename
    header = _get_conf_header(format)
    if header and doheader: # if either is not None or not ''
        for h in header:
            f.write('#'+h+'\n')
    if append:
        _writevec(f, val)
    else:
        # we assume val is array like, except for bin where it can also be a string
        #  remember that float64 has 53 bits (~16 digits) of precision
        # for v of shape (2,100) this will output 2 columns and 100 lines
        #  because of .T
        if bin == '.npy':
            np.save(f, val)
        elif bin:
            if isinstance(val, basestring):
                f.write(val)
            else:
                val.tofile(f)
        else:
            # force array so single values and lists also work
            val = np.asarray(val)
            if val.ndim == 0:
                val.shape = (1,)
            np.savetxt(f, val.T, fmt='%.18g', delimiter='\t')
    f.close()


#To implement async get:
#    need multi level get
#    0: is initialization (Telling system what to read and to prepare it if necessary)
#          dmm1 could do :init here if bus/ext trigger
#       Also start one or multiple threads to capture and save data
#         Should turn on a flag saying we are busy
#       Be carefull with locking if more than one thread per instrument
#       setup srq listening in init or here
#         The end of the thread could decide to disable the srq
#    1: is to start the task
#     is trigger step. For dmm1 do trigger, or :init: if trigger is immediate
#       Also setup of producing signal to finish measurment (like *OPC or for dmm1 fetch?) and prevent
#       other level 0: commands
#    2: Check if data has been read
#    3: get cache
# trigger/flags can be per instrument (visa) or device(acq card)
#Enable basic async for any device (like sr830) by allowing a delay before performing mesurement
#Allow to chain one device on completion of another one.

class asyncThread(threading.Thread):
    def __init__(self, operations, detect=None, delay=0., trig=None):
        super(asyncThread, self).__init__()
        self.daemon = True
        self._stop = False
        self._async_delay = delay
        self._async_trig = trig
        self._async_detect = detect
        self._operations = operations
        self.results = []
    def change_delay(self, new_delay):
        self._async_delay = new_delay
    def change_trig(self, new_trig):
        self._async_trig = new_trig
    def change_detect(self, new_detect):
        self._async_detect = new_detect
    def run(self):
        delay = self._async_delay
        if delay and not CHECKING:
            diff = 0.
            start_time = time.time()
            while diff < delay:
               left = delay - diff
               time.sleep(min(left, 0.1))
               if self._stop:
                   break
               diff = time.time() - start_time
        if self._stop:
            return
        if self._async_trig and not CHECKING:
            self._async_trig()
        if self._async_detect != None:
            while not self._async_detect():
               if self._stop:
                   break
        if self._stop:
            return
        for func, kwarg in self._operations:
            self.results.append(func(**kwarg))
    def cancel(self):
        self._stop = True
    def wait(self, timeout=None):
        self.join(timeout)
        return not self.is_alive()

def wait_on_event(task_or_event, check_state = None, max_time=None):
    start_time = time.time()
    while True:
        if task_or_event.wait(0.2):
            return True
        if max_time != None and time.time()-start_time > max_time:
            return False
        if check_state != None and check_state._error_state:
            break
        QtGui.QApplication.instance().processEvents(
             QtCore.QEventLoop.AllEvents, 20) # 20 ms max

class BaseDevice(object):
    """
        ----------------
        All devices provide a get method. 
        Some device also implement set, check methods.
        Both get and set use a cache variable which is accessible
        with getcache, setcache methods
        The gets have no parameters.
        The sets and check have one parameter, which is the value.

        The device dev can be called as
         dev() which is the same as getcache
         dev(val) which is the same as set(val)
    """
    def __init__(self, autoinit=True, doc='', setget=False,
                  min=None, max=None, choices=None, multi=False, graph=[],
                  trig=False, delay=False, redir_async=None):
        # instr and name updated by instrument's _create_devs
        # doc is inserted before the above doc
        # autoinit can be False, True or a number.
        # The number affects the default implementation of force_get:
        # Bigger numbers are initialized first. 0 is not initialized, True is 1
        # setget makes us get the value after setting in
        #  this is usefull for instruments that could change the value
        #  under us.
        self.instr = None
        self.name = 'foo'
        self._cache = None
        self._lastget = None
        self._autoinit = autoinit
        self._setdev_p = None
        self._getdev_p = None
        self._setget = setget
        self._trig = trig
        self._delay = delay
        self._redir_async = redir_async
        self._last_filename = None
        self.min = min
        self.max = max
        self.choices = choices
        self._doc = doc
        # obj is used by _get_conf_header
        self._format = dict(file=False, multi=multi, graph=graph,
                            append=False, header=None, bin=False,
                            options={}, obj=self)
    def __getattribute__(self, name):
        # we override __doc__ so for instances we return the result from _get_docstring
        # But when asking for __doc__ on the class we get the original docstring
        # Note that __doc__ is automatically set for every class (defaults to None)
        #  and it does not refer to its parent __doc__.
        # Also __doc__ is not writable. To make it writable, it needs to be
        # overwritten in a metaclass (cls.__doc__=cls.__doc__ is enough)
        # Another option is to set __doc__ = property(_get_docstring) in all
        # classes (or use a metaclass to do that automatically) but then
        # asking for __doc__ on the class does not return a string but a property object.
        if name == '__doc__':
            return self._get_docstring()
        return super(BaseDevice, self).__getattribute__(name)
    def _get_docstring(self):
        doc_base = BaseDevice.__doc__
        if doc_base == None:
            doc_base = ''
        doc = self._doc
        extra = ''
        if self.choices:
            extra = '\n-------------\n Possible value to set: %s\n'%repr(self.choices)
        elif self.min != None and self.max != None:
            extra = '\n-------------\n Value between %r and %r\n'%(self.min, self.max)
        elif self.min != None:
            extra = '\n-------------\n Value at least %r\n'%(self.min)
        elif self.max != None:
            extra = '\n-------------\n Value at most %r\n'%(self.max)
        return doc + extra + doc_base
    # for cache consistency
    #    get should return the same thing set uses
    def set(self, val, **kwarg):
        self.check(val, **kwarg)
        if not CHECKING:
            self._setdev(val, **kwarg)
            if self._setget:
                val = self.get(**kwarg)
        elif self._setdev_p == None:
            raise NotImplementedError, self.perror('This device does not handle _setdev')
        # only change cache after succesfull _setdev
        self._cache = val
    def get(self, **kwarg):
        if not CHECKING:
            self._last_filename = None
            keep = kwarg.pop('keep', False)
            format = self.getformat(**kwarg)
            kwarg.pop('graph', None) #now remove graph from parameters (was needed by getformat)
            kwarg.pop('bin', None) #same for bin
            if kwarg.get('filename', False) and not format['file']:
                #we did not ask for a filename but got one.
                #since _getdev probably does not understand filename
                #we handle it here
                filename = kwarg.pop('filename')
                ret = self._getdev(**kwarg)
                _write_dev(ret, filename, format=format)
                self._lastget = ret
                if not keep:
                    ret = None
            else:
                ret = self._getdev(**kwarg)
        elif self._getdev_p == None:
            raise NotImplementedError, self.perror('This device does not handle _getdev')
        else:
            ret = self._cache
        self._cache = ret
        return ret
    def getcache(self):
        if self._cache==None and self._autoinit:
           return self.get()
        return self._cache
    def _do_redir_async(self):
        obj = self
        # go through all redirections
        while obj._redir_async:
            obj = obj._redir_async
        return obj
    def getasync(self, async, **kwarg):
        obj = self._do_redir_async()
        return obj.instr._get_async(async, obj,
                           trig=obj._trig, delay=obj._delay, **kwarg)
    def setcache(self, val):
        self._cache = val
    def __call__(self, val=None):
        if val==None:
           return self.getcache()
        else:
           self.set(val)
    def __repr__(self):
        gn, cn, p = self.instr._info()
        return '<device "%s" of %s=(class "%s" at 0x%08x)>'%(self.name, gn, cn, p)
    def __set__(self, instance, val):
        #print instance
        self.set(val)
    def perror(self, error_str='', **dic):
        dic.update(name=self.name, instr=self.instr, gname=self.instr.find_global_name())
        return ('{gname}.{name}: '+error_str).format(**dic)
    # Implement these in a derived class
    def _setdev(self, val):
        raise NotImplementedError, self.perror('This device does not handle _setdev')
    def _getdev(self):
        raise NotImplementedError, self.perror('This device does not handle _getdev')
    def check(self, val):
        if self._setdev_p == None:
            raise NotImplementedError, self.perror('This device does not handle check')
        mintest = maxtest = choicetest = True
        if self.min != None:
            mintest = val >= self.min
        if self.max != None:
            maxtest = val <= self.max
        if self.choices:
            choicetest = val in self.choices
        state = mintest and maxtest and choicetest
        if state == False:
           if not mintest:
               err='below MIN=%r'%self.min
           if not maxtest:
               err='above MAX=%r'%self.max
           if not choicetest:
               err='invalid value(%s): use one of %s'%(val, repr(self.choices))
           raise ValueError, self.perror('Failed check: '+err)
        #return state
    def getformat(self, filename=None, **kwarg): # we need to absorb any filename argument
        # first handle options we don't want saved it 'options'
        graph = kwarg.pop('graph', None)
        self._format['options'] = kwarg
        #now handle the other overides
        bin = kwarg.pop('bin', None)
        # we need to return a copy so changes to dict here and above does not
        # affect the devices dict permanently
        format = self._format.copy()
        if graph != None:
            format['graph'] = graph
        if bin != None:
            format['file'] = False
            format['bin'] = bin
        return format
    def getfullname(self):
        return self.instr.header()+'.'+self.name
    def force_get(self):
        """
        Force a reread of the instrument attached to this device.
        This should be called before saving headers.
        """
        self.instr.force_get()

class wrapDevice(BaseDevice):
    def __init__(self, setdev=None, getdev=None, check=None, getformat=None, **extrak):
        # auto insert documentation if setdev or getdev has one.
        if not extrak.has_key('doc'):
            if setdev != None and setdev.__doc__:
                extrak['doc'] = setdev.__doc__
            elif getdev != None and getdev.__doc__:
                extrak['doc'] = getdev.__doc__
        BaseDevice.__init__(self, **extrak)
        # the methods are unbounded methods.
        self._setdev_p = setdev
        self._getdev_p = getdev
        self._check  = check
        self._getformat  = getformat
    def _setdev(self, val, **kwarg):
        if self._setdev_p != None:
            self._setdev_p(val, **kwarg)
        else:
            raise NotImplementedError, self.perror('This device does not handle _setdev')
    def _getdev(self, **kwarg):
        if self._getdev_p != None:
            return self._getdev_p(**kwarg)
        else:
            raise NotImplementedError, self.perror('This device does not handle _getdev')
    def check(self, val, **kwarg):
        if self._check != None:
            self._check(val, **kwarg)
        else:
            super(wrapDevice, self).check(val)
    def getformat(self, **kwarg):
        if self._getformat != None:
            return self._getformat(**kwarg)
        else:
            return super(wrapDevice, self).getformat(**kwarg)

class cls_wrapDevice(BaseDevice):
    def __init__(self, setdev=None, getdev=None, check=None, getformat=None, **extrak):
        # auto insert documentation if setdev or getdev has one.
        if not extrak.has_key('doc'):
            if setdev != None and setdev.__doc__:
                extrak['doc'] = setdev.__doc__
            elif getdev != None and getdev.__doc__:
                extrak['doc'] = getdev.__doc__
        BaseDevice.__init__(self, **extrak)
        # the methods are unbounded methods.
        self._setdev_p = setdev
        self._getdev_p = getdev
        self._check  = check
        self._getformat  = getformat
    def _setdev(self, val, **kwarg):
        if self._setdev_p != None:
            self._setdev_p(self.instr, val, **kwarg)
        else:
            raise NotImplementedError, self.perror('This device does not handle _setdev')
    def _getdev(self, **kwarg):
        if self._getdev_p != None:
            return self._getdev_p(self.instr, **kwarg)
        else:
            raise NotImplementedError, self.perror('This device does not handle _getdev')
    def check(self, val, **kwarg):
        if self._check != None:
            self._check(self.instr, val, **kwarg)
        else:
            super(cls_wrapDevice, self).check(val)
    def getformat(self, **kwarg):
        if self._getformat != None:
            return self._getformat(self.instr, **kwarg)
        else:
            return super(cls_wrapDevice, self).getformat(self.instr, **kwarg)

def _find_global_name(obj):
    dic = _globaldict
    try:
        return [k for k,v in dic.iteritems() if v is obj and k[0]!='_'][0]
    except IndexError:
        return "name_not_found"

# Using this metaclass, the class method
# _add_class_devs will be executed at class creation.
# Hence added devices will be part of the class and will
# allow the inst.dev=2 syntax 
#   (Since for the device __set__ to work requires the
#    object to be part of the class, not the instance)
class MetaClassInit(type):
    def __init__(cls, name, bases, dct):
        cls._add_class_devs()
        type.__init__(cls, name, bases, dct)
#TODO: maybe override classmethod, automatically call _add_class_devs for all devices...

class BaseInstrument(object):
    __metaclass__ = MetaClassInit
    alias = None
    def __init__(self):
        self.header_val = None
        self._create_devs()
        self._async_list = []
        self._async_level = -1
        self._async_counter = 0
        self.async_delay = 0.
        self._async_delay_check = True
        self._async_task = None
        self._last_force = time.time()
        if not CHECKING:
            self.init(full=True)
    def _async_detect(self):
        return True
    def _async_trig(self):
        pass
    def _get_async(self, async, obj, **kwarg):
        if async == -1: # we reset task
            if self._async_level > 1:
                self._async_task.cancel()
            self._async_level = -1
        if async != 3 and not (async == 2 and self._async_level == -1) and (
          async < self._async_level or async > self._async_level + 1):
            if self._async_level > 1:
                self._async_task.cancel()
            self._async_level = -1
            raise ValueError, 'Async in the wrong order. Reseting order. Try again..'
        if async == 0:  # setup async task
            if self._async_level == -1: # first time through
                self._async_list = []
                self._async_task = asyncThread(self._async_list)
                self._async_level = 0
            delay = kwarg.pop('delay', False)
            if delay:
                if self._async_delay_check and self.async_delay == 0.:
                    print self.perror('***** WARNING You should give a value for async_delay *****')
                self._async_delay_check = False
                self._async_task.change_delay(self.async_delay)
            trig = kwarg.pop('trig', False)
            if trig:
                self._async_task.change_detect(self._async_detect)
                self._async_task.change_trig(self._async_trig)
            self._async_list.append((obj.get, kwarg))
        elif async == 1:  # Start async task (only once)
            if self._async_level == 0: # First time through
                self._async_task.start()
                self._async_level = 1
        elif async == 2:  # Wait for task to finish
            if self._async_level == 1: # First time through (no need to wait for sunsequent calls)
                wait_on_event(self._async_task)
                self._async_level = -1
            self._async_counter = 0
        elif async == 3: # get values
            #return obj.getcache()
            ret = self._async_task.results[self._async_counter]
            self._async_counter += 1
            return ret
    def find_global_name(self):
        return _find_global_name(self)
    @classmethod
    def _cls_devwrap(cls, name):
        # Only use this if the class will be using only one instance
        # Otherwise multiple instances will collide (reuse same wrapper)
        setdev = getdev = check = getformat = None
        for s in dir(cls):
           if s == '_'+name+'_setdev':
              setdev = getattr(cls, s)
           if s == '_'+name+'_getdev':
              getdev = getattr(cls, s)
           if s == '_'+name+'_check':
              check = getattr(cls, s)
           if s == '_'+name+'_getformat':
              check = getattr(cls, s)
        wd = cls_wrapDevice(setdev, getdev, check, getformat)
        setattr(cls, name, wd)
    def _devwrap(self, name, **extrak):
        setdev = getdev = check = getformat = None
        cls = type(self)
        for s in dir(self):
           if s == '_'+name+'_setdev':
              setdev = getattr(cls, s)
           if s == '_'+name+'_getdev':
              getdev = getattr(cls, s)
           if s == '_'+name+'_check':
              check = getattr(cls, s)
           if s == '_'+name+'_getformat':
              getformat = getattr(cls, s)
        wd = cls_wrapDevice(setdev, getdev, check, getformat, **extrak)
        setattr(self, name, wd)
    def devs_iter(self):
        for devname in dir(self):
           obj = getattr(self, devname)
           if devname != 'alias' and isinstance(obj, BaseDevice):
               yield devname, obj
    def _create_devs(self):
        # devices need to be created here (not at class level)
        # because we want each instrument instance to use its own
        # device instance (otherwise they would share the instance data)
        #
        # if instrument had a _current_config function and the device does
        # not specify anything for header in its format string than
        # we assign it.
        self._devwrap('header')
        # need the ProxyMethod to prevent binding which blocks __del__
        if hasattr(self, '_current_config'):
            conf = ProxyMethod(self._current_config)
        else:
            conf = None
        for devname, obj in self.devs_iter():
            obj.instr = weakref.proxy(self)
            obj.name = devname
            if conf and not obj._format['header']:
                obj._format['header'] = conf
#    def _current_config(self, dev_obj, get_options):
#        pass
    def _conf_helper(self, *devnames):
        ret = []
        for devname in devnames:
            if isinstance(devname, dict):
                val = repr(devname)
                devname = 'options'
            else:
                val = _repr_or_string(getattr(self, devname).getcache())
            ret.append('%s=%s'%(devname, val))
        return ret
    def read(self):
        raise NotImplementedError, self.perror('This instrument class does not implement read')
    def write(self, val):
        raise NotImplementedError, self.perror('This instrument class does not implement write')
    def ask(self, question):
        raise NotImplementedError, self.perror('This instrument class does not implement ask')
    def ask_write(self, command):
        """
        Automatically selects between ask or write depending on the presence of a ?
        """
        if '?' in command:
            return self.ask(command)
        else:
            self.write(command)
    def init(self, full=False):
        """ Do instrument initialization (full=True)/reset (full=False) here """
        pass
    # This allows instr.get() ... to be redirected to instr.alias.get()
    def __getattr__(self, name):
        if name in ['get', 'set', 'check', 'getcache', 'setcache', 'instr',
                    'name', 'getformat', 'getasync', 'getfullname']:
            if self.alias == None:
                raise AttributeError, self.perror('This instrument does not have an alias for {nm}', nm=name)
            return getattr(self.alias, name)
        else:
            raise AttributeError, self.perror('{nm} is not an attribute of this instrument', nm=name)
    def __call__(self):
        if self.alias == None:
            raise TypeError, self.perror('This instrument does not have an alias for call')
        return self.alias()
    def force_get(self):
        """
           Rereads all devices that have autoinit=True
           This should be called when a user might have manualy changed some
           settings on an instrument.
           It is limited to once per 2 second.
        """
        if time.time()-self._last_force < 2:
            # less than 2s since last force, skip it
            return
        l = []
        for s, obj in self.devs_iter():
            if obj._autoinit:
                l.append( (float(obj._autoinit), obj) )
        l.sort(reverse=True)
        for flag,obj in l:
            obj.get()
        self._last_force = time.time()
    def iprint(self, force=False):
        if force:
            self.force_get()
        ret = ''
        for s, obj in self.devs_iter():
            if self.alias == obj:
                ret += 'alias = '
            val = obj.getcache()
            ret += s+" = "+repr(val)+"\n"
        return ret
    def _info(self):
        return self.find_global_name(), self.__class__.__name__, id(self)
    def __repr__(self):
        gn, cn, p = self._info()
        return '%s = <"%s" instrument at 0x%08x>'%(gn, cn, p)
    def perror(self, error_str='', **dic):
        dic.update(instr=self, gname=self.find_global_name())
        return ('{gname}: '+error_str).format(**dic)
    def _header_getdev(self):
        if self.header_val == None:
            return self.find_global_name()
        else:
            return self.header_val
    def _header_setdev(self, val):
        self.header_val = val
    @classmethod
    def _add_class_devs(cls):
        pass
    def trigger():
        pass

class MemoryDevice(BaseDevice):
    def __init__(self, initval=None, **kwarg):
        kwarg['autoinit'] = False
        kwarg['setget'] = False
        BaseDevice.__init__(self, **kwarg)
        self._cache = initval
        self._setdev_p = True # needed to enable BaseDevice set in checking mode and also the check function
        self._getdev_p = True # needed to enable BaseDevice get in Checking mode
    def _getdev(self):
        return self._cache
    def _setdev(self, val):
        self._cache = val

class scpiDevice(BaseDevice):
    def __init__(self,setstr=None, getstr=None,  autoinit=True, autoget=True, str_type=None,
                 choices=None, doc='', options={}, options_lim={}, options_apply=[], **kwarg):
        """
           str_type can be float, int, None
           If choices is a subclass of ChoiceBase, then str_Type will be
           set to that object if unset.
           If only getstr is not given and autoget is true and
           a getstr is created by appending '?' to setstr.

           options is a list of optional parameters for get and set.
                  It is a dictionnary, where the keys are the option name
                  and the values are the default value for each option.
                  If the value is a device. Then by default the cache of the
                  device is used.
                  An option like 'ch' can be used in the setstr/getstr parameter
                     as {ch} (see string.format)
           options_lim is the range of values: It can be
                      -None (the default) which means no limit
                      -a tuple of (min, max)
                               either one can be None to be unset
                      -a list of choices (the object needs to handle __contains__)
           options_apply is a list of options that need to be set. In that order when defined.
           By default, autoinit=True is transformed to 10 (higher priority)
           unless options contains another device, then it is set to 1.

        """
        if setstr == None and getstr == None:
            raise ValueError, 'At least one of setstr or getstr needs to be specified'
        if isinstance(choices, ChoiceBase) and str_type == None:
            str_type = choices
        if autoinit == True:
            autoinit = 10
            test = [ True for k,v in options.iteritems() if isinstance(v, BaseDevice)]
            if len(test):
                autoinit = 1
        BaseDevice.__init__(self, doc=doc, autoinit=autoinit, choices=choices, **kwarg)
        self._setdev_p = setstr
        if getstr == None and autoget:
            getstr = setstr+'?'
        self._getdev_p = getstr
        self._options = options
        self._options_lim = options_lim
        self._options_apply = options_apply
        self.type = str_type
        self._option_cache = {}
    def _tostr(self, val):
        # This function converts from val to a str for the command
        t = self.type
        if t == bool: # True= 1 or ON, False= 0 or OFF
            return str(int(bool(val)))
        if t == float or t == int:
            # use repr instead of str to keep full precision
            return repr(val)
        if t == None or (type(t) == type and issubclass(t, basestring)):
            return val
        return t.tostr(val)
    def _fromstr(self, valstr):
        # This function converts from the query result to a value
        t = self.type
        if t == bool: # it is '1' or '2'
            return bool(int(valstr))
        if t == float or t == int:
            return t(valstr)
        if t == None or (type(t) == type and issubclass(t, basestring)):
            return valstr
        return t(valstr)
    def _get_option_values(self, extradict={}):
        opt = self._options.copy()
        d = {k:v.getcache() for k, v in opt.iteritems() if isinstance(v, BaseDevice)}
        opt.update(d)
        opt.update(extradict)
        return opt
    def getcache(self):
        #we need to check if we still are using the same options
        curr_cache = self._get_option_values()
        if self._option_cache != curr_cache:
            self.setcache(None)
        return super(scpiDevice, self).getcache()
    def _check_option(self, option, val):
        if option not in self._options.keys():
                raise KeyError, self.perror('This device does not handle option "%s".'%option)
        lim = self._options_lim.get(option)
        # if no limits were given but this is a device, use the limits from the device.
        # TODO use dev.check (trap error)
        if lim == None and isinstance(self._options[option], BaseDevice):
            dev = self._options[option]
            lim = (dev.min, dev.max)
            if dev.choices != None:
                lim = dev.choices
        if isinstance(lim, tuple):
            if lim[0] != None and val<lim[0]:
                return self.perror('Option "%s" needs to be >= %r, instead it was %r'%(option, lim[0], val))
            if lim[1] != None and val>lim[1]:
                return self.perror('Option "%s" needs to be <= %r, instead it was %r'%(option, lim[1], val))
        elif lim == None:
            pass
        else: # assume we have some list/set/Choice like object
            if val not in lim:
                return self.perror('Option "%s" needs to be one of %r, instead it was %r'%(option, lim, val))
        return None
    def _combine_options(self, **kwarg):
        # get values from devices when needed.
        # The list of correct values could be a subset so push them to kwarg
        # for testing.
        # clean up kwarg by removing all None values
        kwarg = { k:v for k, v in kwarg.iteritems() if v != None}
        for k, v in kwarg.iteritems():
            ck = self._check_option(k, v)
            if ck != None:
                # in case of error, raise it
                raise ValueError, ck
        # Some device need to keep track of current value so we set them
        # if changed
        for k in self._options_apply:
            if k in kwarg.keys():
                v = kwarg[k]
                opt_dev = self._options[k]
                if opt_dev.getcache() != v:
                    opt_dev.set(v)
        # Now get default values and check them if necessary
        options = self._get_option_values(kwarg)
        for k,v in options.iteritems():
            if k not in kwarg:
                ck = self._check_option(k, v)
                if ck != None:
                    # There was an error, returned value not currently valid
                    # so return it instead of dictionnary
                    return ck
        # everything checks out so use those kwarg
        options.update(kwarg)
        self._option_cache = options
        return options
    def _setdev(self, val, **kwarg):
        if self._setdev_p == None:
           raise NotImplementedError, self.perror('This device does not handle _setdev')
        val = self._tostr(val)
        options = self._combine_options(**kwarg)
        if not isinstance(options, dict):
            # There was an error in default options, raise error
            # options is the error string
            raise ValueError, options
        command = self._setdev_p + ' ' + val
        command = command.format(**options)
        self.instr.write(command)
    def _getdev(self, **kwarg):
        if self._getdev_p == None:
           raise NotImplementedError, self.perror('This device does not handle _getdev')
        options = self._combine_options(**kwarg)
        if not isinstance(options, dict):
            # There was an error in default options, so skip asking instrument
            return None
        command = self._getdev_p
        command = command.format(**options)
        ret = self.instr.ask(command)
        return self._fromstr(ret)
    def check(self, val, **kwarg):
        #TODO handle checking of kwarg
        super(scpiDevice, self).check(val)

class ReadvalDev(BaseDevice):
    def __init__(self, dev, autoinit=None, **kwarg):
        self._slave_dev = dev
        if autoinit == None:
            autoinit = dev._autoinit
        super(ReadvalDev,self).__init__(redir_async=dev, autoinit=autoinit, **kwarg)
    def _getdev(self, **kwarg):
        self.instr._async_trig()
        while not self.instr._async_detect():
            pass
        ret = self._slave_dev.get(**kwarg)
        self._last_filename = self._slave_dev._last_filename
        return ret
    def getformat(self, **kwarg):
        return self._slave_dev.getformat(**kwarg)

def _decode_block_header(s):
    """
       Takes a string with the scpi block header
        #niiiiivvvvvvvvvv
        where n gives then number of i and i gives the number of bytes v
       It returns slice, nbytes, nheaders
       i.e. a slice on the str to return the data
       a value for the number of bytes
       and a value for the length of the header
       If the strings does not start with a block format
       returns a full slice (:), nbytes=-1, 0
    """
    if s[0] != '#':
        return slice(None), -1, 0
    nh = int(s[1])
    nbytes = int(s[2:2+nh])
    return slice(2+nh, None), nbytes, 2+nh

def _decode_block_base(s):
    sl, nb, nh = _decode_block_header(s)
    block = s[sl]
    lb = len(block)
    if nb != -1:
        if lb < nb :
            raise IndexError, 'Missing data for decoding. Got %i, expected %i'%(lb, nb)
        elif lb > nb :
            raise IndexError, 'Extra data in for decoding. Got %i ("%s ..."), expected %i'%(lb, block[nb:nb+10], nb)
    return block

def _decode_block(s, t=np.float64, sep=None):
    """
        sep can be None for binaray encoding or ',' for ascii csv encoding
        type can be np.float64 float32 int8 int16 int32 uint8 uint16 ...
              or it can be entered as a string like 'float64'
    """
    block = _decode_block_base(s)
    if sep == None:
        return np.fromstring(block, t)
    return np.fromstring(block, t, sep=sep)

def _decode_block_auto(s, t=np.float64):
    if s[0] == '#':
        sep = None
    else:
        sep = ','
    return _decode_block(s, t, sep=sep)

_decode_float64 = functools.partial(_decode_block_auto, t=np.float64)
_decode_float32 = functools.partial(_decode_block_auto, t=np.float32)
_decode_uint32 = functools.partial(_decode_block_auto, t=np.uint32)
_decode_uint8_bin = functools.partial(_decode_block, t=np.uint8)
_decode_uint16_bin = functools.partial(_decode_block, t=np.uint16)
_decode_complex128 = functools.partial(_decode_block_auto, t=np.complex128)

def _decode_float64_avg(s):
    return _decode_block_auto(s, t=np.float64).mean()

def _decode_float64_std(s):
    return _decode_block_auto(s, t=np.float64).std(ddof=1)

class quoted_string(object):
    def __init__(self, quote_char='"'):
        self._quote_char = quote_char
    def __call__(self, quoted_str):
        quote_char = self._quote_char
        if quote_char == quoted_str[0] and quote_char == quoted_str[-1]:
            return quoted_str[1:-1]
        else:
            print 'Warning, string <%s> does not start and end with <%s>'%(quoted_str, quote_char)
            return quoted_str
    def tostr(self, unquoted_str):
        quote_char = self._quote_char
        if quote_char in unquoted_str:
            raise ValueError, 'The given string already contains a quote :%s:'%quote_char
        return quote_char+unquoted_str+quote_char

class quoted_list(quoted_string):
    def __init__(self, sep=',', **kwarg):
        super(quoted_list,self).__init__(**kwarg)
        self._sep = sep
    def __call__(self, quoted_l):
        unquoted = super(quoted_list,self).__call__(quoted_l)
        return unquoted.split(self._sep)
    def tostr(self, unquoted_l):
        unquoted = string.join(unquoted_l, sep=self._sep)
        return super(quoted_list,self).tostr(unquoted)

class quoted_dict(quoted_list):
    def __init__(self, empty='NO CATALOG', **kwarg):
        super(quoted_dict,self).__init__(**kwarg)
        self._empty = empty
    def __call__(self, quoted_l):
        l = super(quoted_dict,self).__call__(quoted_l)
        if l == [self._empty]:
            return OrderedDict()
        return OrderedDict(zip(l[0::2], l[1::2]))
    def tostr(self, d):
        if d == {}:
            l = [self._empty]
        else:
            l = []
            for k,v in d.iteritems():
                l.extend([k ,v])
        return super(quoted_dict,self).tostr(l)

class ChoiceBase(object):
    pass

class ChoiceStrings(ChoiceBase):
    """
       Initialize the class with a list of strings
        s=ChoiceStrings('Aa', 'Bb', ..)
       then 'A' in s  or 'aa' in s will return True
       irrespective of capitalization.
       The elements need to have the following format:
          ABCdef
       where: ABC is known as the short name and
              abcdef is known has the long name.
       When using in or searching with index method
             both long and short names are looked for
       normalizelong and normalizeshort return the above
         (short is upper, long is lower)
       Long and short name can be the same.
    """
    def __init__(self, *values, **extrap):
        # use **extrap because we can't have keyword arguments after *arg
        self.quotes = extrap.pop('quotes', False)
        if extrap != {}:
            raise TypeError, 'ChoiceStrings only has quotes=False as keyword argument'
        self.values = values
        self.short = [v.translate(None, string.ascii_lowercase).lower() for v in values]
        self.long = [v.lower() for v in values]
        # for short having '', use the long name instead
        # this happens for a string all in lower cap.
        self.short = [s if s!='' else l for s,l in zip(self.short, self.long)]
    def __contains__(self, x): # performs x in y; with y=Choice()
        xl = x.lower()
        inshort = xl in self.short
        inlong = xl in self.long
        return inshort or inlong
    def index(self, value):
        xl = value.lower()
        try:
            return self.short.index(xl)
        except ValueError:
            pass
        return self.long.index(xl)
    def normalizelong(self, x):
        return self.long[self.index(x)]
    def normalizeshort(self, x):
        return self.short[self.index(x)].upper()
    def __call__(self, input_str):
        # this is called by dev._fromstr to convert a string to the needed format
        if self.quotes:
            if input_str[0] != '"' or input_str[-1] != '"':
                raise ValueError, 'The value --%s-- is not quoted properly'%input_str
            return self.normalizelong(input_str[1:-1])
        return self.normalizelong(input_str)
    def tostr(self, input_choice):
        # this is called by dev._tostr to convert a choice to the format needed by instrument
        if self.quotes:
            return '"%s"'%input_choice
        return input_choice  # no need to change. Already a proper string.
    def __repr__(self):
        return repr(self.values)
    def __getitem__(self, index):
        # index can be a single value: return it
        # or it can be a slice or a list, return a new object with only the selected elements
        #   the list can be numbers or strings (which finds number with index)
        if not isinstance(index, (slice, list)):
            return self.values[index]
        if isinstance(index, slice):
            return ChoiceStrings(*self.values[index], quotes=self.quotes)
        # we have a list
        values = []
        for i in index:
            if isinstance(i, basestring):
                i = self.index(i)
            values.append(self.values[i])
        return ChoiceStrings(*values, quotes=self.quotes)

class ChoiceIndex(ChoiceBase):
    """
    Initialize the class with a list of values or a dictionnary
    The instrument uses the index of a list or the key of the dictionnary
    option normalize when true rounds up the float values for better
    comparison. Use it with a list created from a calculation.
    """
    def __init__(self, list_or_dict, offset=0, normalize=False):
        self._normalize = normalize
        self._list_or_dict = list_or_dict
        if isinstance(list_or_dict, np.ndarray):
            list_or_dict = list(list_or_dict)
        if isinstance(list_or_dict, list):
            if self._normalize:
                list_or_dict = [self.normalize_N(v) for v in list_or_dict]
            self.keys = range(offset,offset+len(list_or_dict)) # instrument values
            self.values = list_or_dict           # pyHegel values
            self.dict = dict(zip(self.keys, self.values))
        else: # list_or_dict is dict
            if self._normalize:
                list_or_dict = {k:self.normalize_N(v) for k,v in list_or_dict.iteritems()}
            self.dict = list_or_dict
            self.keys = list_or_dict.keys()
            self.values = list_or_dict.values()
    @staticmethod
    def normalize_N(v):
        """
           This transforms 9.9999999999999991e-06 into 1e-05
           so can compare the result of a calcualtion with the theoretical one
           v can only by a single value
        """
        if abs(v) < 1e-25:
            return 0.
        return float('%.13e'%v)
    def index(self, val):
        if self._normalize:
            val = self.normalize_N(val)
        return self.values.index(val)
    def __getitem__(self, key):
        # negative indices will not work
        return self.dict[key]
    def __call__(self, input_str):
        # this is called by dev._fromstr to convert a string to the needed format
        val = int(input_str)
        return self[val]
    def tostr(self, input_choice):
        # this is called by dev._tostr to convert a choice to the format needed by instrument
        i = self.index(input_choice)
        return str(self.keys[i])
    def __contains__(self, x):
        if self._normalize:
            x = self.normalize_N(x)
        return x in self.values
    def __repr__(self):
        return repr(self.values)

class ChoiceDevDep(ChoiceBase):
    """ This class is a wrapper around a dictionnary of lists
        or other choices.
        The correct list selected from the dictionnary keys, according
        to the current value of dev.
        The keys can be values or and object that handles 'in' testing.
        A default choice can be given with a key of None
    """
    def __init__(self, dev, choices):
        self.choices = choices
        self.dev = dev
    def _get_choice(self):
        val = self.dev.getcache()
        for k, v in self.choices.iteritems():
            if isinstance(k, (tuple, ChoiceBase)) and val in k:
                return v
            elif val == k:
                return v
        return self.choices.get(None, [])
    # call and tostr will only be used if str_typ is set to this class.
    #  This can be done if all the choices are instance of ChoiceBase
    def __call__(self, input_str):
        return self._get_choice()(input_str)
    def tostr(self, input_choice):
        return self._get_choice().tostr(input_choice)
    def __contains__(self, x):
        return x in self._get_choice()
    def __repr__(self):
        return repr(self._get_choice())

class ChoiceDev(ChoiceBase):
    """
     Get the choices from a device
     Wether device return a dict or a list, it should work the same
     For a dict you can use keys or values (when keys fail)
    """
    def __init__(self, dev, sub_type=None):
        self.dev = dev
        self.sub_type = sub_type
    def _get_choices(self):
        return self.dev.getcache()
    # call and tostr will only be used if str_typ is set to this class.
    #  This can be done if all the choices are instance of ChoiceBase
    def __call__(self, input_str):
        if self.sub_type != None:
            input_str = self.sub_type(input_str)
        return input_str
    def tostr(self, input_choice):
        choices = self._get_choices()
        ch = input_choice
        if isinstance(choices, dict):
            if ch not in choices.keys() and ch in choices.values():
                ch = [k for k,v in choices.iteritems() if v == input_choice][0]
        if self.sub_type != None:
            ch = self.sub_type.tostr(ch)
        return ch
    def __contains__(self, x):
        choices = self._get_choices()
        if isinstance(choices, dict):
            if x in choices.keys():
                return True
            choices = choices.values()
        return x in choices
    def __repr__(self):
        return repr(self._get_choices())


def make_choice_list(list_values, start_exponent, end_exponent):
    """
    given list_values=[1,3]
          start_exponent =-6
          stop_expoenent = -3
    produces [1e-6, 3e-6, 1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3]
    """
    powers = np.logspace(start_exponent, end_exponent, end_exponent-start_exponent+1)
    return (powers[:,None] * np.array(list_values)).flatten()

class visaInstrument(BaseInstrument):
    """
        Open visa instrument with a visa address.
        If the address is an integer, it is taken as the
        gpib address of the instrument on the first gpib bus.
        Otherwise use a visa string like:
          'GPIB0::12::INSTR'
          'GPIB::12'
          'USB0::0x0957::0x0118::MY49001395::0::INSTR'
          'USB::0x0957::0x0118::MY49001395'
    """
    def __init__(self, visa_addr):
        # need to initialize visa before calling BaseInstrument init
        # which might require access to device
        if type(visa_addr)==int:
            visa_addr= 'GPIB0::%i::INSTR'%visa_addr
        self.visa_addr = visa_addr
        if not CHECKING:
            self.visa = visa.instrument(visa_addr)
        #self.visa.timeout = 3 # in seconds
        BaseInstrument.__init__(self)
    #######
    ## Could implement some locking here ....
    ## for read, write, ask
    #######
    def read_status_byte(self):
        return vpp43.read_stb(self.visa.vi)
    def control_remotelocal(self, remote=False, local_lockout=False, all=False):
        """
        For all=True:
           remote=True: REN line is asserted -> when instruments are addressed
                                                 they will go remote
           remote=False: REN line is deasserted -> All instruments go local and
                                               will NOT go remote when addressed
                                               This also clears lockout state
        For local_lockout=True:
           remote=True: All instruments on the bus go to local lockout state
                        Also current instrument goes remote.
           remote=False:  Same as all=True, remote=False followed by
                                  all=True, remote=True
        local lockout state means the local button is disabled on the instrument.
        The instrument can be switch for local to remote by gpib interface but
        cannot be switched from remote to local using the instrument local button.
        Not all instruments implement this lockout.

        Otherwise:
           remote=True: only this instrument goes into remote state.
           remote=False: only this instrument goes into local state.
              The instrument keeps its lockout state unchanged.
        """
        # False for both all and local_lockout(first part) should proceed in a same way
        # Here I use a different instruction but I think they both do the same
        # i.e. VI_GPIB_REN_DEASSERT == VI_GPIB_REN_DEASSERT_GTL
        #  possibly they might behave differently on some other bus (gpib, tcp?)
        #  or for instruments that don't conform to proper 488.2 rules
        #  For those reason I keep the 2 different so it can be tested later.
        # Unused state:
        #   VI_GPIB_REN_ASSERT_LLO : lockout only (no addressing)
        if all:
            if remote:
                val = vpp43.VI_GPIB_REN_ASSERT
            else:
                val = vpp43.VI_GPIB_REN_DEASSERT
        elif local_lockout:
            if remote:
                val = vpp43.VI_GPIB_REN_ASSERT_ADDRESS_LLO
            else:
                val = vpp43.VI_GPIB_REN_DEASSERT_GTL
                vpp43.gpib_control_ren(self.visa.vi, val)
                val = vpp43.VI_GPIB_REN_ASSERT
        else:
            if remote:
                val = vpp43.VI_GPIB_REN_ASSERT_ADDRESS
            else:
                val = vpp43.VI_GPIB_REN_ADDRESS_GTL
        vpp43.gpib_control_ren(self.visa.vi, val)
    def read(self):
        return self.visa.read()
    def write(self, val):
        self.visa.write(val)
    def ask(self, question):
        return self.visa.ask(question)
    def idn(self):
        return self.ask('*idn?')
    def _clear(self):
        self.visa.clear()
    @property
    def set_timeout(self):
        return self.visa.timeout
    @set_timeout.setter
    def set_timeout(self, seconds):
        self.visa.timeout = seconds
    def get_error(self):
        return self.ask('SYSTem:ERRor?')
    def _info(self):
        gn, cn, p = BaseInstrument._info(self)
        return gn, cn+'(%s)'%self.visa_addr, p
    def trigger(self):
        # This should produce the hardware GET on gpib
        #  Another option would be to use the *TRG 488.2 command
        self.visa.trigger()

class visaInstrumentAsync(visaInstrument):
    def init(self, full=False):
        # This clears the error state, and status/event flags?
        self.write('*cls')
        if full:
            self.write('*ese 1;*sre 32') # OPC flag
            vpp43.enable_event(self.visa.vi, vpp43.VI_EVENT_SERVICE_REQ,
                               vpp43.VI_QUEUE)
    def _get_esr(self):
        return int(self.ask('*esr?'))
    def _async_detect(self):
        ev_type = context = None
        try:  # for 500 ms
            ev_type, context = vpp43.wait_on_event(self.visa.vi, vpp43.VI_EVENT_SERVICE_REQ, 500)
        except visa.VisaIOError, e:
            if e.error_code != vpp43.VI_ERROR_TMO:
                raise
        if context != None:
            # only reset event flag. We know the bit that is set already (OPC)
            self._get_esr()
            # only reset SRQ flag. We know the bit that is set already
            self.read_status_byte()
            vpp43.close(context)
            return True
        return False
    def _async_trig(self):
        if self._get_esr() & 0x01:
            print 'Unread event byte!'
        while self.read_status_byte() & 0x40:
            print 'Unread status byte!'
        try:
            while True:
                foo = vpp43.wait_on_event(self.visa.vi, vpp43.VI_EVENT_SERVICE_REQ, 0)
                print 'Unread event queue!'
        except:
            pass
        self.write('INITiate;*OPC') # this assume trig_src is immediate for agilent multi

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
        return self._conf_helper('function', 'range', 'level')
    def _create_devs(self):
        #self.level_2 = wrapDevice(self.levelsetdev, self.levelgetdev, self.levelcheck)
        self.function = scpiDevice(':source:function', choices=ChoiceStrings('VOLT', 'CURRent')) # use 'voltage' or 'current'
        # voltage or current means to add V or A in the string (possibly with multiplier)
        self.range = scpiDevice(':source:range', str_type=float, setget=True) # can be a voltage, current, MAX, MIN, UP or DOWN
        #self.level = scpiDevice(':source:level') # can be a voltage, current, MAX, MIN
        self.voltlim = scpiDevice(':source:protection:voltage', str_type=float, setget=True) #voltage, MIN or MAX
        self.currentlim = scpiDevice(':source:protection:current', str_type=float, setget=True) #current, MIN or MAX
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
    _snap_type = {1:'x', 2:'y', 3:'R', 4:'theta', 5:'Aux_in1', 6:'Aux_in2',
                  7:'Aux_in3', 8:'Aux_in4', 9:'Ref_Freq', 10:'Ch1', 11:'Ch2'}
    _filter_slope_v = np.arange(4)+1
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
        return _decode_float64(self.ask('snap? '+string.join(sel,sep=',')))
    def _snap_getformat(self, sel=[1,2], filename=None):
        self._check_snapsel(sel)
        headers = [ self._snap_type[i] for i in sel]
        d = self.snap._format
        d.update(multi=headers, graph=range(len(sel)))
        return BaseDevice.getformat(self.snap, sel=sel)
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
        self.filter_slope = scpiDevice('ofsl', str_type=int, min=0, max=3, doc='0: 6 dB/oct\n1: 12\n2: 18\n3: 24\n')
        self.sync_filter = scpiDevice('sync', str_type=bool)
        self.x = scpiDevice(getstr='outp? 1', str_type=float, delay=True)
        self.y = scpiDevice(getstr='outp? 2', str_type=float, delay=True)
        self.r = scpiDevice(getstr='outp? 3', str_type=float, delay=True)
        self.theta = scpiDevice(getstr='outp? 4', str_type=float, delay=True)
        self.input_conf = scpiDevice('isrc', str_type=int, min=0, max=3, doc='0: A\n1: A-B\n2: I(1MOhm)\n3: I(100 MOhm)\n')
        self.grounded_conf = scpiDevice('ignd', str_type=bool)
        self.dc_coupled_conf = scpiDevice('icpl', str_type=bool)
        self.reserve_mode = scpiDevice('rmod', str_type=int, min=0, max=2, doc='0: High reserve\n1: Normal\n2: Low noise\n')
        self.linefilter_conf = scpiDevice('ilin', str_type=int, min=0, max=3, doc='0: No filters\n1: line notch\n2: 2xline notch:\n3: both line, 2xline notch\n')
        # status: b0=Input/Reserver ovld, b1=Filter ovld, b2=output ovld, b3=unlock,
        # b4=range change (accross 200 HZ, hysteresis), b5=indirect time constant change
        # b6=triggered, b7=unused
        self.status_byte = scpiDevice(getstr='LIAS?', str_type=int)
        self._devwrap('snap', delay=True)
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
        By default time_constant and n_filter are the current ones
        When sec is Truem the input time is in sec, not in time_constants
        """
        if n_filter == None:
            n_filter = self.filter_slope.getcache()
            n_filter = self._filter_slope_v[n_filter]
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
            n_filter = self._filter_slope_v[n_filter]
        if time_constant == None:
            time_constant = self.timeconstant.getcache()
        func = lambda x: self.find_fraction(x, n_filter, time_constant)-frac
        n_time = brentq_rootsolver(func, 0, 100)
        if sec:
            return n_time*time_constant
        else:
            return n_time


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


class agilent_rf_33522A(visaInstrument):
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('ampl1', 'freq1', 'offset1', 'phase1', 'mode1', 'out_en1', 'pulse_width1',
                                 'ampl2', 'freq2', 'offset2', 'phase2', 'mode2', 'out_en2', 'pulse_width2', options)
    def _create_devs(self):
        # voltage unit depends on front panel/remote selection (sourc1:voltage:unit) vpp, vrms, dbm
        self.ampl1 = scpiDevice('SOUR1:VOLT', str_type=float, min=0.001, max=10)
        self.freq1 = scpiDevice('SOUR1:FREQ', str_type=float, min=1e-6, max=30e6)
        self.pulse_width1 = scpiDevice('SOURce1:FUNCtion:PULSe:WIDTh', str_type=float, min=16e-9, max=1e6) # s
        self.offset1 = scpiDevice('SOUR1:VOLT:OFFS', str_type=float, min=-5, max=5)
        self.phase1 = scpiDevice('SOURce1:PHASe', str_type=float, min=-360, max=360) # in deg unless changed by unit:angle
        self.mode1 = scpiDevice('SOUR1:FUNC') # SIN, SQU, RAMP, PULS, PRBS, NOIS, ARB, DC
        self.out_en1 = scpiDevice('OUTPut1', str_type=bool) #OFF,0 or ON,1
        self.ampl2 = scpiDevice('SOUR2:VOLT', str_type=float, min=0.001, max=10)
        self.freq2 = scpiDevice('SOUR2:FREQ', str_type=float, min=1e-6, max=30e6)
        self.pulse_width2 = scpiDevice('SOURce2:FUNCtion:PULSe:WIDTh', str_type=float, min=16e-9, max=1e6) # s
        self.phase2 = scpiDevice('SOURce2:PHASe', str_type=float, min=-360, max=360) # in deg unless changed by unit:angle
        self.offset2 = scpiDevice('SOUR2:VOLT:OFFS', str_type=float, min=-5, max=5)
        self.mode2 = scpiDevice('SOUR2:FUNC') # SIN, SQU, RAMP, PULS, PRBS, NOIS, ARB, DC
        self.out_en2 = scpiDevice('OUTPut2', str_type=bool) #OFF,0 or ON,1
        self.alias = self.freq1
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
    def phase_sync(self):
        self.write('PHASe:SYNChronize')

class agilent_multi_34410A(visaInstrumentAsync):
    def math_clear(self):
        self.write('CALCulate:AVERage:CLEar')
    def _current_config(self, dev_obj=None, options={}):
        mode = self.mode.getcache()
        choices = self.mode.choices
        baselist =('mode', 'trig_src', 'trig_delay', 'trig_count',
                   'sample_count', 'sample_src', 'sample_timer', 'trig_delayauto',
                   'line_freq', 'math_func')
        if mode in choices[['curr:ac', 'volt:ac']]:
            extra = ('bandwidth', 'autorange', 'range',
                     'null_en', 'null_val', 'peak_mode_en')
        elif mode in choices[['volt', 'curr']]:
            extra = ('nplc', 'aperture', 'aperture_en', 'zero', 'autorange', 'range',
                     'null_en', 'null_val', 'peak_mode_en')
            if mode in choices[['volt']]:
                extra += ('voltdc_impedance_autoHigh',)
        elif mode in choices[['cont', 'diode']]:
            extra = ()
        elif mode in choices[['freq', 'period']]:
            extra = ('aperture','null_en', 'null_val',  'freq_period_p_band',
                        'freq_period_autorange', 'freq_period_volt_range')
        elif mode in choices[['res', 'fres']]:
            extra = ('nplc', 'aperture', 'aperture_en', 'autorange', 'range',
                     'null_en', 'null_val', 'res_offset_comp')
            if mode in choices[['res']]:
                extra += ('zero',)
        elif mode in choices[['cap']]:
            extra = ('autorange', 'range', 'null_en', 'null_val')
        elif mode in choices[['temp']]:
            extra = ('nplc', 'aperture', 'aperture_en', 'null_en', 'null_val',
                     'zero', 'temperature_transducer', 'temperature_transducer_subtype')
            t_ch = self.temperature_transducer.choices
            if self.temperature_transducer.getcache() in t_ch[['rtd', 'frtd']]:
                extra += ('temperature_transducer_rtd_ref', 'temperature_transducer_rtd_off')
        return self._conf_helper(*(baselist + extra + (options,)))
    def set_long_avg(self, time, force=False):
        # update mode first, so aperture applies to correctly
        self.mode.get()
        line_period = 1/self.line_freq.getcache()
        if time > 1.:
            width = 10*line_period
            count = round(time/width)
        else:
           count = 1
           width = time
           if not force:
               width = line_period*round(width/line_period)
        self.aperture.set(width)
        self.sample_count.set(count)
    def _create_devs(self):
        # This needs to be last to complete creation
        ch = ChoiceStrings(
          'CURRent:AC', 'VOLTage:AC', 'CAPacitance', 'CONTinuity', 'CURRent', 'VOLTage',
          'DIODe', 'FREQuency', 'PERiod', 'RESistance', 'FRESistance', 'TEMPerature', quotes=True)
        self.mode = scpiDevice('FUNC', choices=ch)
        def devOption(lims, *arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options_lim = kwarg.pop('options_lim', {}).copy()
            options.update(mode=self.mode)
            options_lim.update(mode=lims)
            kwarg.update(options=options)
            kwarg.update(options_lim=options_lim)
            return scpiDevice(*arg, **kwarg)
        # _decode_float64_avg is needed because count points are returned
        # fetch? and read? return sample_count*trig_count data values (comma sep)
        self.fetch = scpiDevice(getstr='FETCh?',str_type=_decode_float64_avg, autoinit=False, trig=True) #You can't ask for fetch after an aperture change. You need to read some data first.
        # autoinit false because it can take too long to readval
        self.readval = scpiDevice(getstr='READ?',str_type=_decode_float64_avg, autoinit=False, redir_async=self.fetch) # similar to INItiate followed by FETCh.
        self.fetch_all = scpiDevice(getstr='FETCh?',str_type=_decode_float64, autoinit=False, trig=True)
        self.fetch_std = scpiDevice(getstr='FETCh?',str_type=_decode_float64_std, autoinit=False, trig=True, doc="""
             Use this to obtain the standard deviation(using ddof=1) of the fetch.
             This will only return something usefull for long time averages where
             count is > 1. This is the case with set_long_avg(time) for time longer
             than 1s.
             (fetch_all needs to have more than one value)
        """)
        self.line_freq = scpiDevice(getstr='SYSTem:LFRequency?', str_type=float) # see also SYST:LFR:ACTual?
        ch_aper = ch[['volt', 'curr', 'res', 'fres', 'temp', 'freq', 'period']]
        ch_aper_nplc = ch[['volt', 'curr', 'res', 'fres', 'temp']]
        aper_max = float(self.ask('volt:aper? max'))
        aper_min = float(self.ask('volt:aper? min'))
        # TODO handle freq, period where valid values are .001, .010, .1, 1 (between .001 and 1 can use setget)
        self.aperture = devOption(ch_aper, '{mode}:APERture', str_type=float, min = aper_min, max = aper_max, setget=True)
        self.aperture_en = devOption(ch_aper_nplc, '{mode}:APERture:ENabled', str_type=bool)
        self.nplc = devOption(ch_aper_nplc, '{mode}:NPLC', str_type=float,
                                   choices=[0.006, 0.02, 0.06, 0.2, 1, 2, 10, 100])
        ch_band = ch[['curr:ac', 'volt:ac']]
        self.bandwidth = devOption(ch_band, '{mode}:BANDwidth', str_type=float,
                                   choices=[3, 20, 200]) # in Hz
        ch_freqperi = ch[['freq', 'per']]
        self.freq_period_p_band = devOption(ch_freqperi, '{mode}:RANGe:LOWer', str_type=float,
                                   choices=[3, 20, 200]) # in Hz
        self.freq_period_autorange = devOption(ch_freqperi, '{mode}:VOLTage:RANGe:AUTO', str_type=bool) # Also use ONCE (immediate autorange, then off)
        self.freq_period_volt_range = devOption(ch_freqperi, '{mode}:VOLTage:RANGe', str_type=float,
                                                choices=[.1, 1., 10., 100., 1000.]) # Setting this disables auto range

        ch_zero = ch[['volt', 'curr', 'res', 'temp']] # same as ch_aper_nplc wihtout fres
        self.zero = devOption(ch_zero, '{mode}:ZERO:AUTO', str_type=bool,
                              doc='Enabling auto zero double the time to take each point (the value and a zero correction is done for each point)') # Also use ONCE (immediate zero, then off)
        ch_range = ch[[0, 1, 2,  4, 5,  9, 10]] # everything except continuity, diode, freq, per and temperature
        self.autorange = devOption(ch_range, '{mode}:RANGE:AUTO', str_type=bool) # Also use ONCE (immediate autorange, then off)
        range_ch = ChoiceDevDep(self.mode, {ch[['volt', 'volt:ac']]:[.1, 1., 10., 100., 1000.],
                                            ch[['curr', 'curr:ac']]:[.1e-3, 1e-3, 1e-2, 1e-1, 1, 3],
                                            ch[['fres', 'res']]:[1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9] }) # in V, A, Ohm
        self.range = devOption(ch_range, '{mode}:RANGe', str_type=float, choices=range_ch) # Setting this disables auto range
        ch_null = ch[[0, 1, 2,  4, 5,  7, 8, 9, 10, 11]] # everything except continuity and diode
        self.null_en = devOption(ch_null, '{mode}:NULL', str_type=bool)
        self.null_val = devOption(ch_null, '{mode}:NULL:VALue', str_type=float)
        self.voltdc_impedance_autoHigh = scpiDevice('VOLTage:IMPedance:AUTO', str_type=bool, doc='When True and V range <= 10V then impedance >10 GO else it is 10 MOhm')
        tch = ChoiceStrings('FRTD', 'RTD', 'FTHermistor', 'THERmistor')
        self.temperature_transducer = scpiDevice('TEMPerature:TRANsducer:TYPE', choices=tch)
        tch_rtd = tch[['frtd', 'rtd']]
        ch_temp_typ = ChoiceDevDep(self.temperature_transducer, {tch_rtd:[85], None:[2252, 5000, 10000]})
        self.temperature_transducer_subtype = scpiDevice('TEMPerature:TRANsducer:{trans}:TYPE',
                                        choices = ch_temp_typ,
                                        options=dict(trans=self.temperature_transducer),
                                        str_type=int)
        self.temperature_transducer_rtd_ref = scpiDevice('TEMPerature:TRANsducer:{trans}:RESistance',
                                        min = 49, max= 2.1e3, str_type=float,
                                        options=dict(trans=self.temperature_transducer),
                                        options_lim=dict(trans=tch_rtd))
        self.temperature_transducer_rtd_off = scpiDevice('TEMPerature:TRANsducer:{trans}:OCOMpensated', str_type=bool,
                                        options=dict(trans=self.temperature_transducer),
                                        options_lim=dict(trans=tch_rtd))

        ch_compens = ch[['res', 'fres']]
        self.res_offset_comp = devOption(ch_compens, '{mode}:OCOMpensated', str_type=bool)
        ch_peak = ch[['volt', 'volt:ac', 'curr', 'curr:ac']]
        self.peak_mode_en = devOption(ch_peak, '{mode}:PEAK:STATe', str_type=bool)
        peak_op = dict(peak=self.peak_mode_en)
        peak_op_lim = dict(peak=[True])
        self.fetch_peaks_ptp = devOption(ch_peak, 'FETCh:{mode}:PTPeak', str_type=float,
                                         doc='Call this after a fetch or readval',
                                         options=peak_op, options_lim=peak_op_lim, autoinit=False, trig=True)
        ch_peak_minmax = ch[['volt', 'curr']]
        self.fetch_peaks_min = devOption(ch_peak_minmax, 'FETCh:{mode}:PEAK:MINimum', str_type=float,
                                         doc='Call this after a fetch or readval',
                                         options=peak_op, options_lim=peak_op_lim, autoinit=False, trig=True)
        self.fetch_peaks_max = devOption(ch_peak_minmax, 'FETCh:{mode}:PEAK:MAXimum', str_type=float,
                                         doc='Call this after a fetch or readval',
                                         options=peak_op, options_lim=peak_op_lim, autoinit=False, trig=True)
        ch = ChoiceStrings('NULL', 'DB', 'DBM', 'AVERage', 'LIMit')
        self.math_func = scpiDevice('CALCulate:FUNCtion', choices=ch)
        self.math_state = scpiDevice('CALCulate:STATe', str_type=bool)
        self.math_avg = scpiDevice(getstr='CALCulate:AVERage:AVERage?', str_type=float, trig=True)
        self.math_count = scpiDevice(getstr='CALCulate:AVERage:COUNt?', str_type=float, trig=True)
        self.math_max = scpiDevice(getstr='CALCulate:AVERage:MAXimum?', str_type=float, trig=True)
        self.math_min = scpiDevice(getstr='CALCulate:AVERage:MINimum?', str_type=float, trig=True)
        self.math_ptp = scpiDevice(getstr='CALCulate:AVERage:PTPeak?', str_type=float, trig=True)
        self.math_sdev = scpiDevice(getstr='CALCulate:AVERage:SDEViation?', str_type=float, trig=True)
        ch = ChoiceStrings('IMMediate', 'BUS', 'EXTernal')
        self.trig_src = scpiDevice('TRIGger:SOURce', choices=ch)
        self.trig_delay = scpiDevice('TRIGger:DELay', str_type=float) # seconds
        self.trig_count = scpiDevice('TRIGger:COUNt', str_type=float)
        self.sample_count = scpiDevice('SAMPle:COUNt', str_type=int)
        ch = ChoiceStrings('IMMediate', 'TIMer')
        self.sample_src = scpiDevice('SAMPle:SOURce', choices=ch)
        self.sample_timer = scpiDevice('SAMPle:TIMer', str_type=float) # seconds
        self.trig_delayauto = scpiDevice('TRIGger:DELay:AUTO', str_type=bool)
        self.alias = self.readval
        super(type(self),self)._create_devs()
        # For INITiate: need to wait for completion of triggered measurement before calling it again
        # for trigger: *trg and visa.trigger seem to do the same. Can only be called after INItiate and 
        #   during measurement.
        # To get completion stats: write('INITiate;*OPC') and check results from *esr? bit 0
        #   enable with *ese 1 then check *stb bit 5 (32) (and clear *ese?)
        # Could also ask for data and look at bit 4 (16) output buffer ready
        #dmm1.mathfunc.set('average');dmm1.math_state.set(True)
        #dmm1.write('*ese 1;*sre 32')
        #dmm1.write('init;*opc')
        #dmm1.read_status_byte()
        #dmm1.ask('*stb?;*esr?')
        #dmm1.math_count.get(); dmm1.math_avg.get() # no need to reset count, init does that
        #visa.vpp43.enable_event(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, visa.vpp43.VI_QUEUE)
        #dmm1.write('init;*opc')
        #dmm1.read_status_byte()
        #visa.vpp43.wait_on_event(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, 10000)
        #dmm1.read_status_byte()
        #dmm1.ask('*stb?;*esr?')
        #  For installing handler (only seems to work with USB not GPIB for NI visa library. Seems to work fine with Agilent IO visa)
        #   def event_handler(vi, event_type, context, use_handle): stb = visa.vpp43.read_stb(vi);  print 'helo 0x%x'%stb, event_type==visa.vpp43.VI_EVENT_SERVICE_REQ, context, use_handle; return visa.vpp43.VI_SUCCESS
        #   def event_handler(vi, event_type, context, use_handle): stb = visa.vpp43.read_stb(vi);  print 'HELLO 0x%x'%stb,vi; return visa.vpp43.VI_SUCCESS
        #   visa.vpp43.install_handler(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, event_handler)
        #   visa.vpp43.enable_event(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, visa.vpp43.VI_HNDLR)
        #   The handler is called for all srq on the bus (not necessarily the instrument we want)
        #     the vi parameter refers to the installed handler, not the actual srq source
        #The wait_on_event seems to be handling only event from src, not affecting the other instruments srq
        # reading the status is not necessary after wait to clear srq (cleared during wait internal handler) for agilent visa
        #  but it is necessary for NI visa (it will receive the SRQ like for agilent but will not transmit
        #      the next ones to the wait queue until acknowledged)
        #      there seems to be some inteligent buffering going on, which is different in agilent and NI visas
        # When wait_on_event timesout, it produces the VisaIOError (VI_ERROR_TMO) exception
        #        the error code is available as VisaIOErrorInstance.error_code




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

class infiniiVision_3000(visaInstrument):
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('source', 'mode', 'preamble', options)
    def _create_devs(self):
        # Note vincent's hegel, uses set to define filename where block data is saved.
        self.snap_png = scpiDevice(getstr=':DISPlay:DATA? PNG, COLor', str_type=_decode_block_base, autoinit=False) # returns block of data(always bin with # header)
        self.snap_png._format['bin']='.png'
        self.inksaver = scpiDevice(':HARDcopy:INKSaver', str_type=bool) # ON, OFF 1 or 0
        # TODO return scaled values, and select channels
        self.data = scpiDevice(getstr=':waveform:DATA?', str_type=_decode_uint8_bin, autoinit=False) # returns block of data (always header# for asci byte and word)
          # also read :WAVeform:PREamble?, which provides, format(byte,word,ascii),
          #  type (Normal, peak, average, HRes), #points, #avg, xincr, xorg, xref, yincr, yorg, yref
          #  xconv = xorg+x*xincr, yconv= (y-yref)*yincr + yorg
        self.format = scpiDevice(':WAVeform:FORMat') # WORD, BYTE, ASC
        self.points = scpiDevice(':WAVeform:POINts') # 100, 250, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000, 2000000, 4000000, 8000000
        self.mode = scpiDevice(':WAVeform:POINts:MODE', choices=ChoiceStrings('NORMal', 'MAXimum', 'RAW'))
        self.preamble = scpiDevice(getstr=':waveform:PREamble?')
        self.source = scpiDevice(':WAVeform:SOURce') # CHAN1, CHAN2, CHAN3, CHAN4
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

class agilent_EXA(visaInstrument):
    def init(self, full=False):
        self.write(':format REAL,64')
        self.write(':format:border swap')
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('bandwidth', 'freq_start', 'freq_stop','average_count', options)
    def _create_devs(self):
        self.bandwidth = scpiDevice(':bandwidth',str_type=float)
        self.mark1x = scpiDevice(':calc:mark1:x',str_type=float)
        self.mark1y = scpiDevice(getstr=':calc:mark1:y?',str_type=float)
        self.average_count = scpiDevice(getstr=':average:count?',str_type=float)
        self.freq_start = scpiDevice(':freq:start', str_type=float, min=10e6, max=12.6e9)
        self.freq_stop = scpiDevice(':freq:stop', str_type=float, min=10e6, max=12.6e9)
        # TODO handle multiple channels
        self.trace1 = scpiDevice(getstr=':trace? trace1', str_type=_decode_float64, multi=True, autoinit=False)
        self.fetch1 = scpiDevice(getstr=':fetch:san1?', autoinit=False)
        self.read1 = scpiDevice(getstr=':read:san1?', autoinit=False)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

class agilent_PNAL(visaInstrumentAsync):
    """
    To use this instrument, the most useful device is probably:
        fetch, readval
    Some commands are available:
        abort
        create_measurement
        delete_measurement
        restart_averaging
        phase_unwrap, phase_wrap, phase_flatten
    Other useful devices:
        channel_list
        current_channel
        select_trace
        select_traceN
        freq_start, freq_stop, freq_cw
        power_dbm_port1, power_dbm_port2
        marker_x, marker_y
        snap_png
        cont_trigger

    Note that almost all devices/commands require a channel.
    It can be specified with the ch option or will use the last specified
    one if left to the default.
    A lot of other commands require a selected trace (per channel)
    The active one can be selected with the trace option or select_trace, select_traceN
    If unspecified, the last one is used.
    """
    def init(self, full=False):
        self.write(':format REAL,64')
        self.write(':format:border swap')
        super(agilent_PNAL, self).init(full=full)
    def _async_trig(self):
        # Not that this waits for one scan but not for the end of averaging
        self.cont_trigger.set(False)
        super(agilent_PNAL, self)._async_trig()
    def abort(self):
        self.write('ABORt')
    def create_measurement(self, name, param, ch=None):
        """
        name: any unique, non-empty string. If it already exists, we change its param
        param: Any S parameter as S11 or S1_1 (second form only for double-digit port numbers S10_1)
               Ratio measurement, any 2 physical receiver separated by / and followed by , and source port
               like A/R1,3
               Non-Ratio measurement: Any receiver followed by , and source port like A,4
               Ratio and non-ratio can also use logical receiver notation
               ADC measurement: ADC receiver, then , then source por like AI1,2
               Balanced measurment: ...
        """
        ch_list = self.channel_list.get(ch=ch)
        ch=self.current_channel.getcache()
        if name in ch_list:
            self.select_trace.set(trace=name)
            command = 'CALCulate{ch}:PARameter:MODify:EXTended "{param}"'.format(ch=ch, param=param)
        else:
            command = 'CALCulate{ch}:PARameter:EXTended "{name}","{param}"'.format(ch=ch, name=name, param=param)
        self.write(command)
    def delete_measurement(self, name=None, ch=None):
        """ delete a measurement.
            if name == None: delete all measurements for ch
            see channel_list for the available measurments
        """
        ch_list = self.channel_list.get(ch=ch)
        ch=self.current_channel.getcache()
        if name != None:
            if name not in ch_list:
                raise ValueError, self.perror('Invalid Trace name')
            command = 'CALCulate{ch}:PARameter:DELete "{name}"'.format(ch=ch, name=name)
        else:
            command = 'CALCulate{ch}:PARameter:DELete:ALL'.format(ch=ch)
        self.write(command)
    def restart_averaging(self, ch=None):
        #sets ch if necessary
        if not self.average_en.get(ch=ch):
            return
        ch=self.current_channel.getcache()
        command = 'SENSe{ch}:AVERage:CLEar'.format(ch=ch)
        self.write(command)
    def _fetch_getformat(self, **kwarg):
        # TODO handle column titles when saving to a file
        fmt = self.fetch._format
        fmt.update(multi=False, graphs=[])
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_getdev(self, ch=None, traces=None, unit='default', mem=False, xaxis=True):
        """
           traces can be a single value or a list of values.
                    The values are strings representing the trace or the trace number
           unit can be default (real, imag)
                       db_deg (db, deg) , where phase is unwrapped
                       cmplx  (complexe number), Note that this cannot be written to file
           mem when True, selects the memory trace instead of the active one.
           xaxis  when True(default), the first column of data is the xaxis
        """
        # this also sets the current channel
        ch_list = self.channel_list.get(ch=ch)
        if traces == None:
            traces = ch_list.values()
        if not isinstance(traces, (tuple, list)):
            traces = [traces]
        getdata = self.calc_sdata
        if mem:
            getdata = self.calc_smem
        if xaxis:
            ret = [self.get_xscale()]
        else:
            ret = []
        for t in traces:
            if not isinstance(t, basestring):
                t = self.traceN_name.get(trace=t)
            v = getdata.get(trace=t)
            if unit == 'db_deg':
                r = 20.*np.log10(np.abs(v))
                theta = np.angle(v, deg=True)
                theta = self.phase_unwrap(theta)
                ret.append(r)
                ret.append(theta)
            elif unit == 'cmplx':
                ret.append(v)
            else:
                ret.append(v.real)
                ret.append(v.imag)
        ret = np.asarray(ret)
        if ret.shape[0]==1:
            ret=ret[0]
        return ret
    @staticmethod
    def phase_unwrap(phase_deg):
        return scipy.rad2deg( scipy.unwrap( scipy.deg2rad(phase_deg) ) )
    @staticmethod
    def phase_wrap(phase_deg):
        return (phase_deg +180.) % 360 - 180.
    @staticmethod
    def phase_flatten(phase_deg, freq, delay=0., ratio=[0,-1]):
        """
           Using an unwrapped phase, this removes a slope.
           if delay is specified, it adds delay*f*360
           If delay is 0. (default) then it uses 2 points
           specified by ratio (defaults to first and last)
           to use to extract slope (delay)
        """
        dp = phase_deg[ratio[1]] - phase_deg[ratio[0]]
        df = freq[ratio[1]] - freq[ratio[0]]
        if delay == 0.:
            delay = -dp/df/360.
            print 'Using delay=', delay
        return phase_deg + delay*freq*360.
    def get_xscale(self):
        return self.x_axis.get()

    def _current_config(self, dev_obj=None, options={}):
        # These all refer to the current channel
        # some like calib_en depend on trace
        return self._conf_helper('freq_cw', 'freq_start', 'freq_stop', 'ext_ref',
                                 'power_dbm_port1', 'power_dbm_port2', 'calib_en',
                                 'npoints', 'sweep_gen', 'sweep_gen_pointsweep',
                                 'sweep_fast_en', 'sweep_time', 'sweep_type',
                                 'bandwidth', 'bandwidth_lf_enh', 'cont_trigger',
                                 'average_count', 'average_mode', 'average_en', options)
    def _create_devs(self):
        self.installed_options = scpiDevice(getstr='*OPT?', str_type=quoted_string())
        self.self_test_results = scpiDevice(getstr='*tst?', str_type=int, doc="""
            Flag bits:
                0=Phase Unlock
                1=Source unleveled
                2=Unused
                3=EEprom write fail
                4=YIG cal failed
                5=Ramp cal failed'""")
        self.current_channel = MemoryDevice(1, min=1, max=200)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.channel_list = devChOption(getstr='CALCulate{ch}:PARameter:CATalog:EXTended?', str_type=quoted_dict(), doc='Note that some , are replaced by _')
        self.select_trace = devChOption('CALCulate{ch}:PARameter:SELect', choices=ChoiceDev(self.channel_list, quoted_string()))
        def devCalcOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(trace=self.select_trace)
            app = kwarg.pop('options_apply', ['ch', 'trace'])
            kwarg.update(options=options, options_apply=app)
            return devChOption(*arg, **kwarg)
        # select_trace needs to be set for most of the calc commands
        #calc:par:TNUMber and WNUMber don't exist for our PNAL
        self.select_trace_N = devCalcOption('CALCulate{ch}:PARameter:MNUMber', str_type=int, min=1, doc='The number is from the Tr1 annotation next to the parameter nane on the PNA screen')
        self.edelay_length = devCalcOption('CALCulate{ch}:CORRection:EDELay:DISTance', str_type=float)
        self.edelay_length_unit = devCalcOption('CALC{ch}:CORR:EDEL:UNIT', choices=ChoiceStrings('METer', 'FEET', 'INCH'))
        self.edelay_length_medium = devCalcOption('CALC{ch}:CORR:EDEL:MEDium', choices=ChoiceStrings('COAX', 'WAVEguide'))
        self.edelay_time = devCalcOption('CALC{ch}:CORR:EDEL', str_type=float, min=-10, max=10, doc='Set delay in seconds')
        self.calib_en = devCalcOption('CALC{ch}:CORR', str_type=bool)
        self.snap_png = scpiDevice(getstr='HCOPy:SDUMp:DATA:FORMat PNG;:HCOPy:SDUMp:DATA?', str_type=_decode_block_base, autoinit=False)
        self.snap_png._format['bin']='.png'
        self.cont_trigger = scpiDevice('INITiate:CONTinuous', str_type=bool)
        self.bandwidth = devChOption('SENSe{ch}:BANDwidth', str_type=float, setget=True) # can obtain min max
        self.bandwidth_lf_enh = devChOption('SENSe{ch}:BANDwidth:TRACk', str_type=bool)
        self.average_count = devChOption('SENSe{ch}:AVERage:COUNt', str_type=int)
        self.average_mode = devChOption('SENSe{ch}:AVERage:MODE', choices=ChoiceStrings('POINt', 'SWEep'))
        self.average_en = devChOption('SENSe{ch}:AVERage', str_type=bool)
        self.coupling_mode = devChOption('SENSe{ch}:COUPle', choices=ChoiceStrings('ALL', 'NONE'), doc='ALL means sweep mode set to chopped (trans and refl measured on same sweep)\nNONE means set to alternate, imporves mixer bounce and isolation but slower')
        self.freq_start = devChOption('SENSe{ch}:FREQuency:STARt', str_type=float, min=10e6, max=40e9)
        self.freq_stop = devChOption('SENSe{ch}:FREQuency:STOP', str_type=float, min=10e6, max=40e9)
        self.freq_cw= devChOption('SENSe{ch}:FREQuency:CW', str_type=float, min=10e6, max=40e9)
        self.ext_ref = scpiDevice(getstr='SENSe:ROSCillator:SOURce?', str_type=str)
        self.npoints = devChOption('SENSe{ch}:SWEep:POINts', str_type=int, min=1)
        self.sweep_gen = devChOption('SENSe{ch}:SWEep:GENeration', choices=ChoiceStrings('STEPped', 'ANALog'))
        self.sweep_gen_pointsweep =devChOption('SENSe{ch}:SWEep:GENeration:POINtsweep', str_type=bool, doc='When true measure rev and fwd at each frequency before stepping')
        self.sweep_fast_en =devChOption('SENSe{ch}:SWEep:SPEed', choices=ChoiceStrings('FAST', 'NORMal'), doc='FAST increases the speed of sweep by almost a factor of 2 at a small cost in data quality')
        self.sweep_time = devChOption('SENSe{ch}:SWEep:TIME', str_type=float, min=0, max=86400.)
        self.sweep_type = devChOption('SENSe{ch}:SWEep:TYPE', choices=ChoiceStrings('LINear', 'LOGarithmic', 'POWer', 'CW', 'SEGMent', 'PHASe'))
        self.x_axis = devChOption(getstr='SENSe{ch}:X?', str_type=_decode_float64, autoinit=False, doc='This gets the default x-axis for the channel (some channels can have multiple x-axis')
        self.calc_x_axis = devCalcOption(getstr='CALC{ch}:X?', str_type=_decode_float64, autoinit=False, doc='Get this x-axis for a particular trace.')
        self.calc_fdata = devCalcOption(getstr='CALC{ch}:DATA? FDATA', str_type=_decode_float64, autoinit=False, trig=True)
        # the f vs s. s is complex data, includes error terms but not equation editor (Except for math?)
        #   the f adds equation editor, trace math, {gating, phase corr (elect delay, offset, port extension), mag offset}, formating and smoothing
        self.calc_sdata = devCalcOption(getstr='CALC{ch}:DATA? SDATA', str_type=_decode_complex128, autoinit=False, trig=True)
        self.calc_fmem = devCalcOption(getstr='CALC{ch}:DATA? FMEM', str_type=_decode_float64, autoinit=False)
        self.calc_smem = devCalcOption(getstr='CALC{ch}:DATA? SMEM', str_type=_decode_complex128, autoinit=False)
        self.current_mkr = MemoryDevice(1, min=1, max=10)
        def devMkrOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_mkr)
            app = kwarg.pop('options_apply', ['ch', 'trace', 'mkr'])
            kwarg.update(options=options, options_apply=app, autoinit=False)
            return devCalcOption(*arg, **kwarg)
        def devMkrEnOption(*arg, **kwarg):
            # This will check if the marker is currently enabled.
            options = kwarg.pop('options', {}).copy()
            options.update(marker_enabled=self.marker_en)
            options_lim = kwarg.pop('options_lim', {}).copy()
            options_lim.update(marker_enabled=[True])
            kwarg.update(options=options, options_lim=options_lim)
            return devMkrOption(*arg, **kwarg)
        self.marker_en = devMkrOption('CALC{ch}:MARKer{mkr}', str_type=bool)
        marker_funcs = ChoiceStrings('MAXimum', 'MINimum', 'RPEak', 'LPEak', 'NPEak', 'TARGet', 'LTARget', 'RTARget', 'COMPression')
        self.marker_trac_func = devMkrEnOption('CALC{ch}:MARKer{mkr}:FUNCtion', choices=marker_funcs)
        # This screws up iprint
        #self.marker_exec = devMkrOption('CALC{ch}:MARKer{mkr}:FUNCTION:EXECute', choices=marker_funcs, autoget=False)
        self.marker_target = devMkrEnOption('CALC{ch}:MARKer{mkr}:TARGet', str_type=float)
        marker_format = ChoiceStrings('DEFault', 'MLINear', 'MLOGarithmic', 'IMPedance', 'ADMittance', 'PHASe', 'IMAGinary', 'REAL',
                                      'POLar', 'GDELay', 'LINPhase', 'LOGPhase', 'KELVin', 'FAHRenheit', 'CELSius')
        self.marker_format = devMkrEnOption('CALC{ch}:MARKer{mkr}:FORMat', choices=marker_format)
        self.marker_trac_en = devMkrEnOption('CALC{ch}:MARKer{mkr}:FUNCtion:TRACking', str_type=bool)
        self.marker_discrete_en = devMkrEnOption('CALC{ch}:MARKer{mkr}:DISCrete', str_type=bool)
        self.marker_x = devMkrEnOption('CALC{ch}:MARKer{mkr}:X', str_type=float, trig=True)
        self.marker_y = devMkrEnOption('CALC{ch}:MARKer{mkr}:Y', str_type=_decode_float64, multi=['real', 'imag'], graph=[0,1], trig=True)
        traceN_options = dict(trace=1)
        traceN_options_lim = dict(trace=(1,None))
        self.traceN_name = scpiDevice(getstr=':SYSTem:MEASurement{trace}:NAME?', str_type=quoted_string(),
                                      options = traceN_options, options_lim = traceN_options_lim)
        self.traceN_window = scpiDevice(getstr=':SYSTem:MEASurement{trace}:WINDow?', str_type=int,
                                      options = traceN_options, options_lim = traceN_options_lim)
        # windowTrace restarts at 1 for each window
        self.traceN_windowTrace = scpiDevice(getstr=':SYSTem:MEASurement{trace}:TRACe?', str_type=int,
                                      options = traceN_options, options_lim = traceN_options_lim)
        # for max min power, ask source:power? max and source:power? min
        self.power_dbm_port1 = devChOption(':SOURce{ch}:POWer1', str_type=float)
        self.power_dbm_port2 = devChOption(':SOURce{ch}:POWer2', str_type=float)
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
# status byte stuff
# There is a bunch of register groups:
#  :status:operation     # 8(256)=averaging, 9(512)=user, 10(1024)=device
#  :status:operation:device  # contains sweep complete 4(16)
#  :status:operation:averaging1 # handles 1 summary of aver2-42(bit0) and traces 1-14 (bit 1:14)
#  :                          2 # handles 1 summary of aver3-42(bit0) and traces 15-28 (bit 1:14)
#  :status:questionable # 9 (512)=inieg, 10(1024)=limit, 11(2048)=define
#  :status:questionable:integrity
#  :status:questionable:limit1
#   ...
#
#  sweep complete and opc give the same information. Note that the status event latches
#   need to be cleared everywhere in order to be reset (STATus:OPERation:AVERaging1, STATus:OPERation:AVERaging2,
#   STATus:OPERation for and average of trace 15-28)
#  Note that average:cond stays True as long as the average count as been reached
#  If average is not enabled, the condition is never set to true
#
# For each group there is
#       :CONDition?   to query instant state
#       [:EVENt]?     To query and reset latch state
#       :NTRansition  To set/query the negative transition latching enable bit flag
#       :PTRansition  To set/query the positive transition latching enable bit flag
#       :ENABle       To set/query the latch to the next level bit flag
#  bit flag can be entered in hex as #Hfff or #hff
#                             oct as #O777 or #o777
#                             bin as #B111 or #b111
#  The connection between condition (instantenous) and event (latch) depends
#  on NTR and PTR. The connection between event (latch) and next level in
#  status hierarchy depends on ENABLE
#
# There are also IEEE status and event groups
# For event: contains *OPC bit, error reports
#       *ESR?    To read and reset the event register (latch)
#       *ESE     To set/query the bit flag that toggles bit 5 of IEEE status
# For IEEE status: contains :operation (bit 7), :questionable (bit 3)
#                           event (bit 5), error (bit 2), message available (bit 4)
#                           Request Service =RQS (bit 6) also MSS (master summary) which
#                                     is instantenous RQS. RQS is latched
#                           Not that first bit is bit 0
# To read error (bit 2): v.ask(':system:error?')
#   that command is ok even without errors
# Message available (bit 4) is 1 after a write be before a read if there was
# a question (?) in the write (i.e. something is waiting to be read)
#
#       the RQS (but not MSS) bit is read and reset by serial poll
#        *STB?   To read (not reset) the IEEE status byte, bit 6 is read as MSS not RQS
#        *SRE    To set/query the bit flag that controls the RQS bit
#                      RQS (bit6) is supposed to be ignored.
# *CLS   is to clear all event registers and empty the error queue.
#
# With both GPIB and USB interface activated. They both have their own status registers
# for STB to OPERATION ...
# They also have their own error queues and most other settings (active measurement for channel,
#   data format) seem to also be independent on the 2 interfaces


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


def _asDevice(dev):
    if isinstance(dev, BaseInstrument):
        dev = dev.alias
    return dev

class LogicalDevice(BaseDevice):
    """
       Base device for logical devices.
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
        if basedev != None:
            basedev = _asDevice(basedev) # deal with instr.alias
        if basedevs != None:
            for i, dev in enumerate(basedevs):
                dev = _asDevice(dev) # deal with instr.alias
                basedevs[i] = dev
            basedev = basedevs[0]
        self._basedev_internal = basedev
        self._basedevs = basedevs
        doc = self.__doc__+doc+'\nbasedev=%r\nbasedevs=%r\n'%(basedev, basedevs)
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
        # whe in async mode, _basdev needs to point to possibly redirected device
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
    def _current_config_addbase(self, head, options={}):
        devs = self._basedevs
        if not devs:
            if self._basedev:
                devs = [self._basedev]
            else:
                devs = []
        for dev in devs:
            head.append('::'+dev.getfullname())
            frmt = dev.getformat()
            base = _get_conf_header_util(frmt['header'], dev, options)
            if base != None:
                head.extend(base)
        return head


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
        raw = self._basedev.get()
        val = self.conv_fromdev(raw)
        return val, raw
    def _setdev(self, val):
        self._basedev.set(self.conv_todev(val))
        # read basedev cache, in case the values is changed by setget mode.
        self._cache = self.conv_fromdev(self._basedev.getcache())
    def check(self, val):
        raw = self.conv_todev(val)
        self._basedev.check(raw)

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
    def _getdev(self):
        raw = self._basedev.get()
        val = self.from_raw(raw)
        return val, raw
    def _setdev(self, val):
        self._basedev.set(self.to_raw(val))
    def check(self, val):
        raw = self.to_raw(val)
        self._basedev.check(raw)


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
        return self._basedev.get()
    def _setdev(self, val):
        self._basedev.set(val)
    def check(self, val):
        self._basedev.check(val)
        super(type(self), self).check(val)


class CopyDevice(LogicalDevice):
    """
       This class provides a wrapper around a device.
       On reading, it returns basedevs[0].get
       On writing it will write to basedev[0], basdev[1] ...
       setget option does nothing here.
       basedevs is a list of dev
    """
    def __init__(self, basedevs , doc='', **extrak):
        super(type(self), self).__init__(basedevs=basedevs, doc=doc, **extrak)
    def _current_config(self, dev_obj=None, options={}):
        head = ['Copy:: %r'%(self._basedevs)]
        return self._current_config_addbase(head, options=options)
    def _getdev(self):
        return self._basedevs[0].get()
    def _setdev(self, val):
        for dev in self._basedevs:
            dev.set(val)
    def check(self, val):
        for dev in self._basedevs:
            dev.check(val)
    def force_get(self):
        for dev in self._basedevs:
            dev.force_get()

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
        basefmt = self._basedev.getformat()
        self._format['file'] = True
        self._format['bin'] = basefmt['bin']
        return super(type(self), self).getformat(**kwarg)
    def _current_config(self, dev_obj=None, options={}):
        head = ['Execute:: command="%s" basedev=%s'%(self._command, self._basedev.getfullname())]
        return self._current_config_addbase(head, options=options)
    def _getdev(self, filename=None):
        kwarg={}
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
