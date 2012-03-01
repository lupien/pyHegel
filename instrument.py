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
from PyQt4 import QtGui, QtCore
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
                  min=None, max=None, choices=None, multi=False,
                  trig=False, delay=False, redir_async=None):
        # instr and name updated by instrument's _create_devs
        # doc is inserted before the above doc
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
        if choices:
            doc+='-------------\n Possible value to set: %s'%repr(choices)
        self.__doc__ = doc+BaseDevice.__doc__
        # obj is used by _get_conf_header
        self._format = dict(file=False, multi=multi, graph=[],
                            append=False, header=None, bin=False,
                            options={}, obj=self)
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
        for s, obj in self.devs_iter():
            if obj._autoinit:
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
    def __init__(self, initval=None, **extrak):
        BaseDevice.__init__(self, **extrak)
        self._cache = initval
        self._setdev_p = True # needed to enable BaseDevice Check
    def get(self):
        return self._cache
    def set(self, val):
        self._cache = val

class scpiDevice(BaseDevice):
    def __init__(self, setstr=None, getstr=None, autoget=True, str_type=None,
                  doc='', **extrak):
        """
           str_type can be float, int, None
        """
        if setstr == None and getstr == None:
           raise ValueError, 'At least one of setstr or getstr needs to be specified'
        BaseDevice.__init__(self, doc=doc, **extrak)
        self._setdev_p = setstr
        if getstr == None and autoget:
            getstr = setstr+'?'
        self._getdev_p = getstr
        self.type = str_type
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
    def _setdev(self, val):
        if self._setdev_p == None:
           raise NotImplementedError, self.perror('This device does not handle _setdev')
        val = self._tostr(val)
        self.instr.write(self._setdev_p+' '+val)
    def _getdev(self):
        if self._getdev_p == None:
           raise NotImplementedError, self.perror('This device does not handle _getdev')
        ret = self.instr.ask(self._getdev_p)
        return self._fromstr(ret)

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

def _decode_float64_avg(s):
    return _decode_block_auto(s, t=np.float64).mean()

def _decode_float64_std(s):
    return _decode_block_auto(s, t=np.float64).std(ddof=1)

class ChoiceStrings(object):
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

class ChoiceIndex(object):
    """
    Initialize the class with a list of values or a dictionnary
    The instrument uses the index of a list or the key of the dictionnary
    """
    def __init__(self, list_or_dict, offset=0):
        self._list_or_dict = list_or_dict
        if isinstance(list_or_dict, list):
            self.keys = range(offset,offset+len(list_or_dict)) # instrument values
            self.values = list_or_dict           # pyHegel values
            self.dict = dict(zip(self.keys, self.values))
        else: # list_or_dict is dict
            self.dict = list_or_dict
            self.keys = list_or_dict.keys()
            self.values = list_or_dict.values()
        try:
            self.values_arr = np.array(self.values)
        except:
            self.values_arr = None
    def index(self, val):
        try:
            return self.values.index(val)
        except ValueError:
            if self.values_arr != None:
                pass # TODO implement finding value approximately for floats
    def __call__(self, input_str):
        # this is called by dev._fromstr to convert a string to the needed format
        val = int(input_str)
        return self.dict[val]
    def tostr(self, input_choice):
        # this is called by dev._tostr to convert a choice to the format needed by instrument
        i = self.index(input_choice)
        return self.keys[i]
    def __contains__(self, x):
        return x in self.values
    def __repr__(self):
        return repr(self.values)

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
    _timeconstant_v = (np.logspace(-6,3,10)[:,None]*np.array([10.,30])).flatten() #s
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
                                 'input_conf', 'grounded_conf', 'dc_coupled_conf', 'linefilter_conf')
    def _create_devs(self):
        self.freq = scpiDevice('freq', str_type=float, setget=True, min=0.001, max=102e3)
        self.sens = scpiDevice('sens', str_type=int, min=0, max=26) #0: 2 nV/fA, 1:5, 2:10, 3:20 ... (1,2,5) ... 26: 1 V/uA
        self.oauxi1 = scpiDevice(getstr='oaux? 1', str_type=float, setget=True)
        self.srclvl = scpiDevice('slvl', str_type=float, min=0.004, max=5., setget=True)
        self.harm = scpiDevice('harm', str_type=int, min=1, max=19999)
        self.phase = scpiDevice('phas', str_type=float, min=-360., max=729.90, setget=True)
        self.timeconstant = scpiDevice('oflt', str_type=int, min=0, max=19) # 0: 10 us, 1: 30, 2: 100 ... (1, 3) ... 19: 30 ks
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
            time_constant = self._timeconstant_v[time_constant]
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
            time_constant = self._timeconstant_v[time_constant]
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
                                 'phase', 'mod_en')
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
                                 'ampl2', 'freq2', 'offset2', 'phase2', 'mode2', 'out_en2', 'pulse_width2')
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

#TODO: handle multiconf stuff VOLT, CURR nlpc ...
class agilent_multi_34410A(visaInstrument):
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
        self.write('INITiate;*OPC') # this assume trig_src is immediate
    def math_clear(self):
        self.write('CALCulate:AVERage:CLEar')
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('mode', 'volt_nplc', 'volt_aperture',
                                 'volt_aperture_en', 'zero', 'autorange',
                                 'trig_src', 'trig_delay', 'trig_count',
                                 'sample_count', 'sample_src', 'sample_timer',
                                 'trig_delayauto', 'line_freq')
    def set_long_avg(self, time, force=False):
        line_period = 1/self.line_freq.getcache()
        if time > 1.:
            width = 10*line_period
            count = round(time/width)
        else:
           count = 1
           width = time
           if not force:
               width = line_period*round(width/line_period)
        self.volt_aperture.set(width)
        self.sample_count.set(count)
    def _create_devs(self):
        # This needs to be last to complete creation
        ch = ChoiceStrings(
          'CURRent:AC', 'VOLTage:AC', 'CAPacitance', 'CONTinuity', 'CURRent', 'VOLTage',
          'DIODe', 'FREQuency', 'PERiod', 'RESistance', 'FRESistance', 'TEMPerature', quotes=True)
        self.mode = scpiDevice('FUNC', str_type=ch, choices=ch)
        # _decode_float64_avg is needed because count points are returned
        # fetch? and read? return sample_count*trig_count data values (comma sep)
        self.fetch = scpiDevice(getstr='FETCh?',str_type=_decode_float64_avg, autoinit=False, trig=True) #You can't ask for fetch after an aperture change. You need to read some data first.
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
        self.volt_nplc = scpiDevice('VOLTage:NPLC', str_type=float, choices=[0.006, 0.02, 0.06, 0.2, 1, 2, 10, 100]) # DC
        self.volt_aperture = scpiDevice('VOLTage:APERture', str_type=float) # DC, in seconds (max~1s), also MIN, MAX, DEF
        self.volt_aperture_en = scpiDevice('VOLTage:APERture:ENabled', str_type=bool)
        self.current_aperture = scpiDevice('CURRent:APERture', str_type=float) # DC, in seconds
        self.res_aperture = scpiDevice('RESistance:APERture', str_type=float)
        self.four_res_aperture = scpiDevice('FRESistance:APERture', str_type=float)
        # Auto zero doubles the time to take each point
        self.zero = scpiDevice('VOLTage:ZERO:AUTO', str_type=bool) # Also use ONCE (immediate zero, then off)
        self.autorange = scpiDevice('VOLTage:RANGE:AUTO', str_type=bool) # Also use ONCE (immediate zero, then off)
        self.range = scpiDevice('VOLTage:RANGE', str_type=float, choices=[.1, 1., 10., 100., 1000.]) # Setting this disables auto range
        self.null_en = scpiDevice('VOLTage:NULL', str_type=bool)
        self.null_val = scpiDevice('VOLTage:NULL:VALue', str_type=float)
        ch = ChoiceStrings('NULL', 'DB', 'DBM', 'AVERage', 'LIMit')
        self.math_func = scpiDevice('CALCulate:FUNCtion', str_type=ch, choices=ch)
        self.math_state = scpiDevice('CALCulate:STATe', str_type=bool)
        self.math_avg = scpiDevice(getstr='CALCulate:AVERage:AVERage?', str_type=float, trig=True)
        self.math_count = scpiDevice(getstr='CALCulate:AVERage:COUNt?', str_type=float)
        self.math_max = scpiDevice(getstr='CALCulate:AVERage:MAXimum?', str_type=float)
        self.math_min = scpiDevice(getstr='CALCulate:AVERage:MINimum?', str_type=float)
        self.math_ptp = scpiDevice(getstr='CALCulate:AVERage:PTPeak?', str_type=float)
        self.math_sdev = scpiDevice(getstr='CALCulate:AVERage:SDEViation?', str_type=float)
        ch = ChoiceStrings('IMMediate', 'BUS', 'EXTernal')
        self.trig_src = scpiDevice('TRIGger:SOURce', str_type=ch, choices=ch)
        self.trig_delay = scpiDevice('TRIGger:DELay', str_type=float) # seconds
        self.trig_count = scpiDevice('TRIGger:COUNt', str_type=float)
        self.sample_count = scpiDevice('SAMPle:COUNt', str_type=int)
        ch = ChoiceStrings('IMMediate', 'TIMer')
        self.sample_src = scpiDevice('SAMPle:SOURce', str_type=ch, choices=ch)
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
        # in [sense:] subsystem:
        #  VOLTage:AC:BANDwidth, CURRent:AC:BANDwidth
        #  (VOLTage:AC, VOLTage[:DC], CURRent:AC, CURRent[:DC], RESistance, FRESistance, FREQuency, PERiod, TEMPerature, CAPacitance):NULL
        #  :RANGe (all except Temperature)
        #  :NLPC, APERture:ENABled (only VOLTage[:DC], CURRent[:DC], RES, FRES, TEMP)
        #  :APERture (only VOLTage[:DC], CURRent[:DC], RES, FRES, FREQ, PERiod, TEMP)
        # IMPedance:AUTO (VOLTage[:DC])
        # ZERO:AUTO ((VOLTage[:DC], CURRent[:DC], RES, TEMP)
        # OCOMpensated (RES and FRES)
        #  FRES and RES parameters are the same.




class lakeshore_322(visaInstrument):
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('sp')
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
        return self._conf_helper('source', 'mode', 'preamble')
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
        return self._conf_helper('bandwidth', 'freq_start', 'freq_stop','average_count')
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

class agilent_PNAL(visaInstrument):
    def init(self, full=False):
        self.write(':format REAL,64')
        self.write(':format:border swap')
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('bandwidth', 'freq_start', 'freq_stop','average_count')
    def _create_devs(self):
        self.bandwidth = scpiDevice(':sense1:bandwidth',str_type=float)
        self.average_count = scpiDevice(getstr=':sense:average:count?',str_type=int)
        self.freq_start = scpiDevice(':sense:freq:start', str_type=float, min=10e6, max=40e9)
        self.freq_stop = scpiDevice(':sense:freq:stop', str_type=float, min=10e6, max=40e9)
        self.freq_cw= scpiDevice(':sense:freq:cw', str_type=float, min=10e6, max=40e9)
        self.x1 = scpiDevice(getstr=':sense1:X?', autoinit=False)
        self.curx1 = scpiDevice(getstr=':calc1:X?', autoinit=False)
        self.cur_data = scpiDevice(getstr=':calc1:data? fdata', autoinit=False)
        self.cur_cplxdata = scpiDevice(getstr=':calc1:data? sdata', autoinit=False)
        self.select_m = scpiDevice(':calc1:par:mnum', autoinit=False)
        self.select_i = scpiDevice(':calc1:par:sel', autoinit=False)
        self.select_w = scpiDevice(getstr=':syst:meas1:window?', autoinit=False)
        self.select_t = scpiDevice(getstr=':syst:meas1:trace?', autoinit=False)
        # for max min power, ask source:power? max and source:power? min
        self.power_dbm_port1 = scpiDevice(':SOURce1:POWer1?', str_type=float, autoinit=False)
        self.power_dbm_port2 = scpiDevice(':SOURce1:POWer1?', str_type=float, autoinit=False)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

class dummy(BaseInstrument):
    def init(self, full=False):
        self.incr_val = 0
        self.wait = .1
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('volt', 'current', 'other')
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
    def __init__(self, basedev=None, basedevs=None, doc='', setget=None, autoinit=None, **extrak):
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
                extrak['autoinit'] = basedev._autoinit
            if setget == None:
                extrak['setget'] = basedev._setget
            #extrak['trig'] = basedev._trig
            #extrak['delay'] = basedev._delay
            extrak['redir_async'] = basedev
        super(LogicalDevice, self).__init__(doc=doc, **extrak)
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
