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

import numpy as np
import string
import functools
import ctypes
import hashlib
import os
import signal
import time
import inspect
import thread
import threading
import weakref
from collections import OrderedDict  # this is a subclass of dict
from qt_wrap import processEvents
from kbint_util import sleep, _sleep_signal_context_manager, _delayed_signal_context_manager

import visa_wrap

rsrc_mngr = None

def _load_resource_manager(path=None):
    global rsrc_mngr
    rsrc_mngr = None
    rsrc_mngr = visa_wrap.get_resource_manager(path)

try:
    _load_resource_manager()
except ImportError as exc:
    print 'Error loading visa resource manager. You will have reduced functionality.'

try:
    _globaldict # keep the previous values (when reloading this file)
except NameError:
    _globaldict = {} # This is set in pyHegel _init_pyHegel_globals (from pyHegel_cmds)

CHECKING = False

###################
###  New exceptions
class InvalidArgument(ValueError):
    pass

class InvalidAutoArgument(InvalidArgument):
    pass
###################

class ProxyMethod(object):
    def __init__(self, bound_method):
        #self.class_of_method = bound_method.im_class
        self.instance = weakref.proxy(bound_method.im_self)
        self.func_name = bound_method.func_name
    def __call__(self, *arg, **kwarg):
        return getattr(self.instance, self.func_name)(*arg, **kwarg)

#######################################################
##    find_all_instruments function (for VISA)
#######################################################

#can list instruments with : 	visa.get_instruments_list()
#     or :                      visa.get_instruments_list(use_aliases=True)
# Based on visa.get_instruments_list
def find_all_instruments(use_aliases=True):
    """Get a list of all connected devices.

    Parameters:
    use_aliases -- if True, return an alias name for the device if it has one.
        Otherwise, always return the standard resource name like "GPIB::10".

    Return value:
    A list of strings with the names of all connected devices, ready for being
    used to open each of them.

    """
    return rsrc_mngr.get_instrument_list(use_aliases)

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
    file_obj.write(pre_str+'\t'.join(strs_list)+'\n')


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
    multi = format['multi']
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
    if doheader: # if either is not None or not ''
        if header:
            for h in header:
                f.write('#'+h+'\n')
        if isinstance(multi, tuple):
            _writevec(f, multi, pre_str='#')
    if append:
        _writevec(f, val)
    else:
        # we assume val is array like, except for bin where it can also be a string
        #  remember that float64 has 53 bits (~16 digits) of precision
        # for v of shape (2,100) this will output 2 columns and 100 lines
        #  because of .T
        if bin == '.npy':
            np.save(f, val)
        elif bin =='.npz':
            np.savez_compressed(f, val)
        elif bin:
            if isinstance(val, basestring):
                f.write(val)
            else:
                val.tofile(f)
        else:
            # force array so single values and lists also work
            val = np.atleast_1d(val)
            np.savetxt(f, val.T, fmt='%.18g', delimiter='\t')
    f.close()


def _retry_wait(func, timeout, delay=0.01):
    """
    this calls func() and stops when the return value is True
    or timeout seconds have passed.
    delay is the sleep duration between attempts.
    """
    endtime = time.time() + timeout
    ret = False
    while True:
        ret = func()
        if ret:
            break
        remaining = endtime - time.time()
        if remaining <= 0:
            break
        delay = min(delay, remaining)
        sleep(delay)
    return ret


class Lock_Extra(object):
    def acquire(self):
        return False
    __enter__ = acquire
    def release(self):
        pass
    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.release()
    def is_owned(self):
        return False
    def force_release(self):
        pass


class Lock_Instruments(threading._RLock):
    """
    This is similar to threading.RLock (reentrant lock)
    except acquire always waits in a non-blocking state.
    Therefore you can press CTRL-C to stop the wait.
    However if the other threads does not release the lock for long
    enough, we might never be able to acquire it.
    """
    def acquire_timeout(self, timeout):
        func = lambda : super(Lock_Instruments, self).acquire(blocking=0)
        return _retry_wait(func, timeout, delay=0.001)
    def acquire(self):
        return wait_on_event(self.acquire_timeout)
    __enter__ = acquire
    def is_owned(self):
        return self._is_owned()
    def force_release(self):
        n = 0
        try:
            while True:
                self.release()
                n += 1
        except RuntimeError as exc:
            if exc.message != "cannot release un-acquired lock":
                raise
        if n:
            print 'Released Intrument lock', n, 'time(s)'
        else:
            print 'Instrument lock was not held'
        try:
            self._RLock__block.release()
        except thread.error as exc:
            if exc.message != 'release unlocked lock':
                raise
        else:
            print 'Inner lock was still locked, now released.'


# Use this as a decorator
def locked_calling(func, extra=''):
    """ This function is to be used as a decorator on a class method.
        It will wrap func with
          with self._lock_instrument, self._lock_extra:
        Only use on method in classes derived from BaseInstrument
    """
    argspec = inspect.getargspec(func)
    (args, varargs, varkw, defaults) = argspec
    def_arg = inspect.formatargspec(*argspec) # this is: (self, arg1, arg2, kw1=1, kw2=5, *arg, *kwarg)
    use_arg = inspect.formatargspec(*argspec, formatvalue=lambda name: '') # this is: (self, arg1, arg2, kw1, kw2, *arg, *kwarg)
    selfname = args[0]+extra
    def_str = """
@functools.wraps(func)
def locked_call_wrapper{def_arg}:
        " locked_call_wrapper is a wrapper that executes func with the instrument locked."
        with {self}._lock_instrument, {self}._lock_extra:
            return func{use_arg}
    """.format(def_arg=def_arg, use_arg=use_arg, self=selfname)
    lcl = locals()
    lcl.update(functools=functools)
    #code = compile(def_str, inspect.getsourcefile(func), 'exec')
    #exec(code, lcl)
    exec(def_str, lcl)
    ### only for ipython 0.12
    ### This makes newfunc?? show the correct function def (including decorator)
    ### note that for doc, ipython tests for getdoc method
    locked_call_wrapper.__wrapped__ = func
    return locked_call_wrapper

def locked_calling_dev(func):
    """ Same as locked_calling, but for a BaseDevice subclass. """
    return locked_calling(func, extra='.instr')


# Taken from python threading 2.7.2
class FastEvent(threading._Event):
    def __init__(self, verbose=None):
        threading._Verbose.__init__(self, verbose)
        self._Event__cond = FastCondition(threading.Lock())
        self._Event__flag = False

class FastCondition(threading._Condition):
    def wait(self, timeout=None):
        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")
        waiter = threading._allocate_lock()
        waiter.acquire()
        self._Condition__waiters.append(waiter)
        saved_state = self._release_save()
        try:    # restore state no matter what (e.g., KeyboardInterrupt)
            if timeout is None:
                waiter.acquire()
                if __debug__:
                    self._note("%s.wait(): got it", self)
            else:
                # Balancing act:  We can't afford a pure busy loop, so we
                # have to sleep; but if we sleep the whole timeout time,
                # we'll be unresponsive.
                func = lambda : waiter.acquire(0)
                gotit = _retry_wait(func, timeout, delay=0.01)
                if not gotit:
                    if __debug__:
                        self._note("%s.wait(%s): timed out", self, timeout)
                    try:
                        self._Condition__waiters.remove(waiter)
                    except ValueError:
                        pass
                else:
                    if __debug__:
                        self._note("%s.wait(%s): got it", self, timeout)
        finally:
            self._acquire_restore(saved_state)

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
    def __init__(self, operations, lock_instrument, lock_extra, init_ops, detect=None, delay=0., trig=None):
        super(asyncThread, self).__init__()
        self.daemon = True
        self._stop = False
        self._async_delay = delay
        self._async_trig = trig
        self._async_detect = detect
        self._operations = operations
        self._lock_instrument = lock_instrument
        self._lock_extra = lock_extra
        self._init_ops = init_ops # a list of (func, args, kwargs)
        self.results = []
        self._replace_index = 0
    def add_init_op(self, func, *args, **kwargs):
        self._init_ops.append((func, args, kwargs))
    def change_delay(self, new_delay):
        self._async_delay = new_delay
    def change_trig(self, new_trig):
        self._async_trig = new_trig
    def change_detect(self, new_detect):
        self._async_detect = new_detect
    def replace_result(self, val, index=None):
        if index == None:
            index = self._replace_index
            self._replace_index += 1
        self.results[index] = val
    @locked_calling
    def run(self):
        #t0 = time.time()
        for f, args, kwargs in self._init_ops:
            f(*args, **kwargs)
        delay = self._async_delay
        if delay and not CHECKING:
            func = lambda: self._stop
            _retry_wait(func, timeout=delay, delay=0.1)
        if self._stop:
            return
        if self._async_trig and not CHECKING:
            self._async_trig()
        #print 'Thread ready to detect ', time.time()-t0
        if self._async_detect != None:
            while not self._async_detect():
                if self._stop:
                    break
        if self._stop:
            return
        #print 'Thread ready to read ', time.time()-t0
        for func, kwarg in self._operations:
            self.results.append(func(**kwarg))
        #print 'Thread finished in ', time.time()-t0
    def cancel(self):
        self._stop = True
    def wait(self, timeout=None):
        # we use a the context manager because join uses sleep.
        with _sleep_signal_context_manager():
            self.join(timeout)
        return not self.is_alive()


# For proper KeyboardInterrupt handling, the docheck function should
# be internally protected with _sleep_signal_context_manager
# This is the case for FastEvent and any function using sleep instead of time.sleep

def wait_on_event(task_or_event_or_func, check_state = None, max_time=None):
    # task_or_event_or_func either needs to have a wait attribute with a parameter of
    # seconds. Or it should be a function accepting a parameter of time in s.
    # check_state allows to break the loop if check_state._error_state
    # becomes True
    # Note that Event.wait (actually threading.Condition.wait)
    # tries to wait for 1ms then for 2ms more then 4, 8, 16, 32 and then in blocks
    # of 50 ms. If the wait would be longer than what is left, the wait is just
    # what is left. However, on windows 7 (at least), the wait ends up being
    # rounded to: 1, 2, 4 and 8->10ms, 16->20ms, 32-> 40ms
    # therefore, using Event.wait can produce times of 10, 20, 30, 40, 60, 100, 150
    # 200 ms ...
    # Can use FastEvent.wait instead of Event.wait to be faster
    start_time = time.time()
    try: # should work for task (threading.Thread) and event (threading.Event)
        docheck = task_or_event_or_func.wait
    except AttributeError: # just consider it a function
        docheck = task_or_event_or_func
    while True:
        if docheck(0.2):
            return True
        if max_time != None and time.time()-start_time > max_time:
            return False
        if check_state != None and check_state._error_state:
            break
        with _delayed_signal_context_manager():
            # processEvents is for the current Thread.
            # if a thread does not have and event loop, this does nothing (not an error)
            processEvents(max_time_ms = 20)

def _general_check(val, min=None, max=None, choices=None ,lims=None):
   # self is use for perror
    if lims != None:
        if isinstance(lims, tuple):
            min, max = lims
        else:
            choices = lims
    mintest = maxtest = choicetest = True
    if min != None:
        mintest = val >= min
    if max != None:
        maxtest = val <= max
    if choices:
        choicetest = val in choices
    state = mintest and maxtest and choicetest
    if state == False:
        if not mintest:
            err='{val!s} is below MIN=%r'%min
        if not maxtest:
            err='{val!s} is above MAX=%r'%max
        if not choicetest:
            err='invalid value({val!s}): use one of {choices!s}'
        raise ValueError('Failed check: '+err, dict(val=val, choices=repr(choices)))


#######################################################
##    Base device
#######################################################

class BaseDevice(object):
    """
        ---------------- General device documentation
        All devices provide a get method.
        Some device also implement set, check methods.
        Users should not call the get/set methods directly bus instead
        should use the pyHegel set/get functions.
        Both get and set use a cache variable which is accessible
        with getcache, setcache methods
        The gets have no positional parameters.
        The sets and check have one positional parameter, which is the value.
        They can have multiple keyword parameters
    """
    def __init__(self, autoinit=True, doc='', setget=False, allow_kw_as_dict=False,
                  allow_missing_dict=False,
                  min=None, max=None, choices=None, multi=False, graph=True,
                  trig=False, delay=False, redir_async=None):
        # instr and name updated by instrument's _create_devs
        # doc is inserted before the above doc
        # autoinit can be False, True or a number.
        # The number affects the default implementation of force_get:
        # Bigger numbers are initialized first. 0 is not initialized, True is 1
        # setget makes us get the value after setting it
        #  this is usefull for instruments that could change the value
        #  under us.
        # allow_kw_as_dict allows the conversion of kw to a dict. There needs to be
        # a choices.field_names list of values (like with ChoiceMultiple)
        # allow_missing_dict, will fill the missing elements of dict with values
        #  from a get
        self.instr = None
        self.name = 'foo'
        self._cache = None
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
        self._allow_kw_as_dict = allow_kw_as_dict
        self._allow_missing_dict = allow_missing_dict
        self._doc = doc
        # obj is used by _get_conf_header and _write_dev
        self._format = dict(file=False, multi=multi, xaxis=None, graph=graph,
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
    def _get_docstring(self, added=''):
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
        return doc + added + extra + doc_base
    # for cache consistency
    #    get should return the same thing set uses
    @locked_calling_dev
    def set(self, *val, **kwarg):
        nval = len(val)
        if nval == 1:
            val = val[0]
        elif nval == 0:
            val = None
        else:
            raise RuntimeError(self.perror('set can only have one positional parameter'))
        if self._allow_kw_as_dict:
            if val == None:
                val = dict()
                for k in kwarg.keys():
                    if k in self.choices.field_names:
                        val[k] = kwarg.pop(k)
        elif nval == 0: # this permits to set a value to None
                raise RuntimeError(self.perror('set requires a value.'))
        try:
            self.check(val, **kwarg)
        except KeyError_Choices:
            if not self._allow_missing_dict:
                raise
            old_val = self.get(**kwarg)
            old_val.update(val)
            val = old_val
            self.check(val, **kwarg)
        if not CHECKING:
            self._setdev(val, **kwarg)
            if self._setget:
                val = self.get(**kwarg)
        elif self._setdev_p == None:
            raise NotImplementedError, self.perror('This device does not handle _setdev')
        # only change cache after succesfull _setdev
        self._cache = val
    @locked_calling_dev
    def get(self, **kwarg):
        if not CHECKING:
            self._last_filename = None
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
                if format['bin']:
                    ret = None
            else:
                ret = self._getdev(**kwarg)
        elif self._getdev_p == None:
            raise NotImplementedError, self.perror('This device does not handle _getdev')
        else:
            ret = self._cache
        self._cache = ret
        return ret
    #@locked_calling_dev
    def getcache(self):
        with self.instr._lock_instrument: # only local data, so don't need _lock_extra
            if self._cache==None and self._autoinit:
                # This can fail, but getcache should not care for
                #InvalidAutoArgument exceptions
                try:
                    return self.get()
                except InvalidAutoArgument:
                    self._cache = None
            return self._cache
    def _do_redir_async(self):
        obj = self
        # go through all redirections
        while obj._redir_async:
            obj = obj._redir_async
        return obj
    def getasync(self, async, **kwarg):
        obj = self._do_redir_async()
        if async != 3 or self == obj:
            ret = obj.instr._get_async(async, obj,
                           trig=obj._trig, delay=obj._delay, **kwarg)
        # now make sure obj._cache and self._cache are the same
        else: # async == 3 and self != obj:
            # async thread is finished, so lock should be available
            with self.instr._lock_instrument: # only local data, so don't need _lock_extra
                #_get_async blocks if it is not in the correct thread and is not
                #complete. Here we just keep the lock until setcache is complete
                # so setcache does not have to wait for a lock.
                ret = obj.instr._get_async(async, obj,
                               trig=obj._trig, delay=obj._delay, **kwarg)
                self.setcache(ret)
                self._last_filename = obj._last_filename
        return ret
    #@locked_calling_dev
    def setcache(self, val):
        with self.instr._lock_instrument: # only local data, so don't need _lock_extra
            self._cache = val
    def __call__(self, val=None):
        raise SyntaxError, """Do NOT call a device directly, like instr.dev().
        Instead use set/get on the device or
        functions that use set/get like sweep or record."""
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
        try:
            _general_check(val, self.min, self.max, self.choices)
        except ValueError as e:
            raise ValueError(self.perror(e.args[0],**e.args[1]))
    def getformat(self, filename=None, **kwarg): # we need to absorb any filename argument
        # first handle options we don't want saved in 'options'
        graph = kwarg.pop('graph', None)
        self._format['options'] = kwarg
        #now handle the other overides
        bin = kwarg.pop('bin', None)
        xaxis = kwarg.pop('xaxis', None)
        # we need to return a copy so changes to dict here and above does not
        # affect the devices dict permanently
        format = self._format.copy()
        if graph != None:
            format['graph'] = graph
        if bin != None:
            format['file'] = False
            format['bin'] = bin
        if xaxis != None and format['xaxis'] != None:
            format['xaxis'] = xaxis
        return format
    def getfullname(self):
        return self.instr.header.getcache()+'.'+self.name
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
            return super(cls_wrapDevice, self).getformat(**kwarg)

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


#######################################################
##    Base Instrument
#######################################################

class BaseInstrument(object):
    __metaclass__ = MetaClassInit
    alias = None
    def __init__(self):
        self.header_val = None
        self._lock_instrument = Lock_Instruments()
        if not hasattr(self, '_lock_extra'):
            # don't overwrite what is assigned in subclasses
            self._lock_extra = Lock_Extra()
        self._create_devs()
        self._async_list = []
        self._async_list_init = []
        self._async_level = -1
        self._async_counter = 0
        self._async_delay_check = True
        self._async_task = None
        self._async_current_calling_thread = None
        self._last_force = time.time()
        if not CHECKING:
            self.init(full=True)
    def __del__(self):
        print 'Destroying '+repr(self)
    def _async_detect(self, max_time=.5):
        return True
    def _async_trig(self):
        pass
    # TODO replace _async_block stuff with using thread local data instead?
    def _get_async_block(self):
        # This only runs if we are in the same thread as previous calls to async
        # otherwise we wait for the other async to terminate.
        # So if we break a running async, we should be able to restart it in
        # the same thread but another thread might hang waiting for us.
        # This is done so that we can block an async without holding the lock
        # since the lock needs to be held by async_thread. But we need to
        # protect the whole async block
        # In case the thread the was interrupted cannot be restarted,
        # it might be necessary to set _async_current_calling_thread=None
        current_thread = threading.current_thread()
        while True:
            if self._async_current_calling_thread == current_thread:
                return
            else:
                with self._lock_instrument:
                    if self._async_current_calling_thread == None:
                        self._async_current_calling_thread = current_thread
                        return
            # wait for another thread to give up
            sleep(0.02)
            with _delayed_signal_context_manager():
                # processEvents is for the current Thread.
                # if a thread does not have and event loop, this does nothing (not an error)
                processEvents(max_time_ms = 20)
    def _get_async(self, async, obj, delay=False, trig=False, **kwarg):
        self._get_async_block()
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
                self._async_list_init = []
                self._async_task = asyncThread(self._async_list, self._lock_instrument, self._lock_extra, self._async_list_init)
                self._async_level = 0
            if delay:
                if self._async_delay_check and self.async_delay.getcache() == 0.:
                    print self.perror('***** WARNING You should give a value for async_delay *****')
                self._async_delay_check = False
                self._async_task.change_delay(self.async_delay.getcache())
            if trig:
                self._async_task.change_detect(self._async_detect)
                self._async_task.change_trig(self._async_trig)
            self._async_list.append((obj.get, kwarg))
        elif async == 1:  # Start async task (only once)
            #print 'async', async, 'self', self, 'time', time.time()
            if self._async_level == 0: # First time through
                self._async_task.start()
                self._async_level = 1
        elif async == 2:  # Wait for task to finish
            #print 'async', async, 'self', self, 'time', time.time()
            if self._async_level == 1: # First time through (no need to wait for subsequent calls)
                wait_on_event(self._async_task)
                self._async_level = -1
            self._async_counter = 0
        elif async == 3: # get values
            #print 'async', async, 'self', self, 'time', time.time()
            #return obj.getcache()
            ret = self._async_task.results[self._async_counter]
            self._async_counter += 1
            if self._async_counter == len(self._async_task.results):
                # delete task so that instrument can be deleted
                del self._async_task
                self._async_current_calling_thread = None
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
    def _create_devs_helper(self, once=False):
        """
        Users can call this function after creating new device for an instrument
        that already exists. It will properly initialize the new devices.
        The user might call it with once=True.
        """
        # if instrument had a _current_config function and the device does
        # not specify anything for header in its format string than
        # we assign it.
        #
        # need the ProxyMethod to prevent binding which blocks __del__
        if hasattr(self, '_current_config'):
            conf = ProxyMethod(self._current_config)
        else:
            conf = None
        for devname, obj in self.devs_iter():
            if once and obj.instr != None:
                continue
            obj.instr = weakref.proxy(self)
            obj.name = devname
            if conf and not obj._format['header']:
                obj._format['header'] = conf
    def _create_devs(self):
        # devices need to be created here (not at class level)
        # because we want each instrument instance to use its own
        # device instance (otherwise they would share the instance data)
        self.async_delay = MemoryDevice(0., doc=
            "In seconds. Used in async mode for devices that don't start/wait (run_and_wait) functions.")
        self._devwrap('header')
        self._create_devs_helper()
#    def _current_config(self, dev_obj, get_options):
#        pass
    def _conf_helper(self, *devnames):
        ret = []
        for devname in devnames:
            if isinstance(devname, dict):
                val = repr(devname)
                devname = 'options'
            else:
                try:
                    val = _repr_or_string(getattr(self, devname).getcache())
                except AttributeError:
                    val = _repr_or_string(getattr(self, devname)())
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
    @locked_calling
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
            try:
                obj.get()
            except InvalidAutoArgument:
                pass
        self._last_force = time.time()
    @locked_calling
    def iprint(self, force=False):
        poptions = np.get_printoptions()
        if force:
            self.force_get()
        ret = ''
        np.set_printoptions(threshold=50)
        for s, obj in self.devs_iter():
            if self.alias == obj:
                ret += 'alias = '
            val = obj.getcache()
            ret += s+" = "+repr(val)+"\n"
        np.set_printoptions(**poptions)
        return ret
    def idn(self):
        """
        This method should return a string that uniquely identify the instrument.
        For scpi it is often: <company name>,<model number>,<serial number>,<firmware revision>
        """
        return "Undefined identification"
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
    def trigger(self):
        pass
    def lock_force_release(self):
        self._lock_instrument.force_release()
        self._lock_extra.force_release()
    def lock_is_owned(self):
        return self._lock_instrument.is_owned() or self._lock_extra.is_owned()
    def _lock_acquire(self):
        self._lock_instrument.acquire()
        self._lock_extra.acquire()
    def _lock_release(self):
        self._lock_instrument.release()
        self._lock_extra.release()


#######################################################
##    Memory device
#######################################################

class MemoryDevice(BaseDevice):
    def __init__(self, initval=None, **kwarg):
        """
        Provides _tostr and _fromstr using the choices functions if
        choices are given. Otherwise it uses the type of initval.
        autoinit and setget are disabled internally (they are useless for a Memory device.)
        """
        kwarg['autoinit'] = False
        kwarg['setget'] = False
        BaseDevice.__init__(self, **kwarg)
        self._cache = initval
        self._setdev_p = True # needed to enable BaseDevice set in checking mode and also the check function
        self._getdev_p = True # needed to enable BaseDevice get in Checking mode
        if self.choices != None and isinstance(self.choices, ChoiceBase):
            self.type = self.choices
        else:
            self.type = type(initval)
    def _getdev(self):
        return self._cache
    def _setdev(self, val):
        self._cache = val
    def _tostr(self, val):
        # This function converts from val to a str for the command
        t = self.type
        return _tostr_helper(val, t)
    def _fromstr(self, valstr):
        # This function converts from the query result to a value
        t = self.type
        return _fromstr_helper(valstr, t)

def _tostr_helper(val, t):
    # This function converts from val to a str for the command
    if t == bool: # True= 1 or ON, False= 0 or OFF
        return str(int(bool(val)))
    if t == float or t == int:
        # use repr instead of str to keep full precision
        return repr(val)
    if t == None or (type(t) == type and issubclass(t, basestring)):
        return val
    return t.tostr(val)

def _fromstr_helper(valstr, t):
    # This function converts from the query result to a value
    if t == bool: # it is '0' or '1'
        return bool(int(valstr))
    #if t == bool: # it is '0' or '1' or ON or OFF
        #try:
        #    return bool(int(valstr))
        #except ValueError:
        #    if valstr.upper() == 'ON':
        #        return True
        #    elif valstr.upper() == 'OFF':
        #        return False
        #    else:
        #        raise
    if t == float or t == int:
        return t(valstr)
    if t == None or (type(t) == type and issubclass(t, basestring)):
        return valstr
    return t(valstr)


#######################################################
##    SCPI device
#######################################################

class scpiDevice(BaseDevice):
    _autoset_val_str = ' {val}'
    def __init__(self,setstr=None, getstr=None, raw=False, autoinit=True, autoget=True, get_cached_init=None,
                 str_type=None, choices=None, doc='',
                 options={}, options_lim={}, options_apply=[], options_conv={},
                 ask_write_opt={}, **kwarg):
        """
           str_type can be float, int, None
           If choices is a subclass of ChoiceBase, then str_Type will be
           set to that object if unset.
           If only getstr is not given and autoget is true
           a getstr is created by appending '?' to setstr.
           If autoget is false and there is no getstr, autoinit is set to False.
           When autoget is false, if get_cached_init is not None, then
           the cache is used instead of get and is initialized to the value of
           get_cached_init. You probably should initialize it during the instrument
           init.
           raw when True will use read_raw instead of the default raw (in get)

           options is a list of optional parameters for get and set.
                  It is a dictionnary, where the keys are the option name
                  and the values are the default value for each option.
                  If the value is a device. Then by default the cache of the
                  device is used.
                  An option like 'ch' can be used in the setstr/getstr parameter
                     as {ch} (see string.format)
                  For the setstr string you can use {val} to specify the position of the
                  value, otherwise ' {val}' is automatically appended. Note that if specify
                  {val} in the setstr, autoget is disabled.
           options_lim is dict of the range of values: It can be
                      -None (the default) which means no limit
                      -a tuple of (min, max)
                               either one can be None to be unset
                      -a list of choices (the object needs to handle __contains__)
           options_conv is a dict of functions to convert the value to a useful format.
                      the functions receives 2 parameters (val, _tostr(val))
           options_apply is a list of options that need to be set. In that order when defined.
           By default, autoinit=True is transformed to 10 (higher priority)
           unless options contains another device, then it is set to 1.
           ask_write_options are options passed to the ask and write methods

        """
        if setstr == None and getstr == None:
            raise ValueError, 'At least one of setstr or getstr needs to be specified'
        if setstr != None and getstr == None and autoget == False:
            # we don't have get, so we remove autoinit to prevent problems with cache and force_get (iprint)
            autoinit = False
        if isinstance(choices, ChoiceBase) and str_type == None:
            str_type = choices
        if autoinit == True:
            autoinit = 10
            test = [ True for k,v in options.iteritems() if isinstance(v, BaseDevice)]
            if len(test):
                autoinit = 1
        BaseDevice.__init__(self, doc=doc, autoinit=autoinit, choices=choices, **kwarg)
        self._setdev_p = setstr
        if setstr != None:
            fmtr = string.Formatter()
            val_present = False
            for txt, name, spec, conv in fmtr.parse(setstr):
                if name == 'val':
                    val_present = True
                    autoget = False
            if not val_present:
                self._setdev_p = setstr + self._autoset_val_str
        self._getdev_cache = False
        if getstr == None:
            if autoget:
                getstr = setstr+'?'
            elif get_cached_init != None:
                self._cache = get_cached_init
                self._getdev_cache = True
        self._getdev_p = getstr
        self._options = options
        self._options_lim = options_lim
        self._options_apply = options_apply
        self._options_conv = options_conv
        self._ask_write_opt = ask_write_opt
        self.type = str_type
        self._raw = raw
        self._option_cache = {}
    def _get_docstring(self, added=''):
        # we don't include options starting with _
        if len(self._options) > 0:
            added += '---------- Optional Parameters\n'
            for optname, optval in self._options.iteritems():
                basedev = False
                if isinstance(optval, BaseDevice):
                    basedev = True
                if optname[0] != '_':
                    added += '{optname}: has default value {optval!r}\n'.format(optname=optname, optval=optval)
                    lim = self._options_lim.get(optname, None)
                    if lim != None:
                        if basedev:
                            added += '        current choices (above device): '
                        else:
                            added += '        current choices: '
                        if isinstance(lim, tuple):
                            if lim[0] == None and lim[1] == None:
                                added += 'any value allowed'
                            else:
                                if lim[0] != None:
                                    added += '%r <= '%lim[0]
                                added += '%s'%optname
                                if lim[1] != None:
                                    added += ' <= %r'%lim[1]
                        else:
                            added += repr(lim)
                        added += '\n'
        return super(scpiDevice, self)._get_docstring(added=added)
    def _tostr(self, val):
        # This function converts from val to a str for the command
        t = self.type
        return _tostr_helper(val, t)
    def _fromstr(self, valstr):
        # This function converts from the query result to a value
        t = self.type
        return _fromstr_helper(valstr, t)
    def _get_option_values(self, extradict={}):
        opt = self._options.copy()
        d = {k:v.getcache() for k, v in opt.iteritems() if isinstance(v, BaseDevice)}
        opt.update(d)
        opt.update(extradict)
        return opt
    @locked_calling_dev
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
                raise InvalidArgument, ck
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
                    raise InvalidAutoArgument, ck
        # everything checks out so use those kwarg
        options.update(kwarg)
        self._option_cache = options.copy()
        for k in options.iterkeys():
            val = options[k]
            option_dev  = self._options[k]
            if isinstance(option_dev, BaseDevice):
                try:
                    tostr_val = option_dev._tostr(val)
                except AttributeError:
                    # Some devices like BaseDevice, cls_WrapDevice don't have _tostr
                    tostr_val = repr(val)
            else:
                tostr_val = repr(val)
            try:
                conv = self._options_conv[k]
                options[k] = conv(val, tostr_val)
            except KeyError:
                options[k] = tostr_val
        return options
    def _setdev(self, val, **kwarg):
        if self._setdev_p == None:
            raise NotImplementedError, self.perror('This device does not handle _setdev')
        val = self._tostr(val)
        options = self._combine_options(**kwarg)
        command = self._setdev_p
        command = command.format(val=val, **options)
        self.instr.write(command, **self._ask_write_opt)
    def _getdev(self, **kwarg):
        if self._getdev_p == None:
            if self._getdev_cache:
                if kwarg == {}:
                    return self.getcache()
                else:
                    raise SyntaxError, self.perror('This device does not handle _getdev with optional arguments')
            raise NotImplementedError, self.perror('This device does not handle _getdev')
        try:
            options = self._combine_options(**kwarg)
        except InvalidAutoArgument:
            self.setcache(None)
            raise
        command = self._getdev_p
        command = command.format(**options)
        ret = self.instr.ask(command, self._raw, **self._ask_write_opt)
        return self._fromstr(ret)
    def check(self, val, **kwarg):
        #TODO handle checking of kwarg
        super(scpiDevice, self).check(val)


#######################################################
##    Readval device
#######################################################

class ReadvalDev(BaseDevice):
    """
    This devices behaves like doing a run_and_wait followed by
    a fetch.
    When in async mode, it simply does the fetch.
    It has the same parameters as the fetch device, so look for the
    documentation of fetch.
    """
    def __init__(self, dev, autoinit=None, **kwarg):
        self._slave_dev = dev
        if autoinit == None:
            autoinit = dev._autoinit
        super(ReadvalDev,self).__init__(redir_async=dev, autoinit=autoinit, **kwarg)
    def _getdev(self, **kwarg):
        self.instr.run_and_wait()
        ret = self._slave_dev.get(**kwarg)
        self._last_filename = self._slave_dev._last_filename
        return ret
    def getformat(self, **kwarg):
        d = self._slave_dev.getformat(**kwarg)
        d['obj'] = self
        return d

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
            if lb-nb == 1 and (s[-1] in '\r\n'):
                return block[:-1]
            elif lb-nb == 2 and s[-2:] == '\r\n':
                return block[:-2]
            raise IndexError, 'Extra data in for decoding. Got %i ("%s ..."), expected %i'%(lb, block[nb:nb+10], nb)
    return block

def _encode_block_base(s):
    """
    This inserts the scpi block header before the string start.
    see _decode_block_header for the description of the header
    """
    N = len(s)
    N_as_string = str(N)
    header = '#%i'%len(N_as_string) + N_as_string
    return header+s

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

def _encode_block(v, sep=None):
    """
    Encodes the iterable v (array, list ...)
    into either a scpi binary block (including header) when sep=None (default)
    or into a sep separated string. Often sep is ',' for scpi
    """
    if sep != None:
        return ','.join(map(repr, v))
    s = v.tostring()
    return _encode_block_base(s)

def _decode_block_auto(s, t=np.float64):
    if s[0] == '#':
        sep = None
    else:
        sep = ','
    return _decode_block(s, t, sep=sep)

class Block_Codec(object):
    def __init__(self, dtype=np.float64, sep=None):
        self._dtype = dtype
        self._sep = sep
    def __call__(self, input_str):
        return _decode_block(input_str, self._dtype, self._sep)
    def tostr(self, array):
        if array.dtype != self._dtype:
            array = array.astype(self._dtype)
        return _encode_block(array, self._sep)

class Block_Codec_Raw(object):
    def __init__(self, dtype=np.float64, sep=None):
        self._dtype = dtype
    def __call__(self, input_str):
        return np.fromstring(input_str, self._dtype)
    def tostr(self, array):
        return array.tostring()

decode_float64 = functools.partial(_decode_block_auto, t=np.float64)
decode_float32 = functools.partial(_decode_block_auto, t=np.float32)
decode_uint32 = functools.partial(_decode_block_auto, t=np.uint32)
decode_uint8_bin = functools.partial(_decode_block, t=np.uint8)
decode_uint16_bin = functools.partial(_decode_block, t=np.uint16)
decode_complex128 = functools.partial(_decode_block_auto, t=np.complex128)

def decode_float64_2col(s):
    v = _decode_block_auto(s, t=np.float64)
    v.shape = (-1,2)
    return v.T

def decode_float64_avg(s):
    return _decode_block_auto(s, t=np.float64).mean()

def decode_float64_std(s):
    return _decode_block_auto(s, t=np.float64).std(ddof=1)

def decode_float64_meanstd(s):
    data = _decode_block_auto(s, t=np.float64)
    return data.std(ddof=1)/np.sqrt(len(data))

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
    def __init__(self, sep=',', element_type=None, **kwarg):
        super(quoted_list,self).__init__(**kwarg)
        self._sep = sep
        self._element_type = element_type
    def __call__(self, quoted_l):
        unquoted = super(quoted_list,self).__call__(quoted_l)
        lst = unquoted.split(self._sep)
        if self._element_type != None:
            lst = [_fromstr_helper(elem, self._element_type) for elem in lst]
        return lst
    def tostr(self, unquoted_l):
        if self._element_type != None:
           unquoted_l = [_tostr_helper(elem, self._element_type) for elem in unquoted_l]
        unquoted = self._sep.join(unquoted_l)
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

# NOTE: a choice function tostr and __call__ (fromstr)
#       is used when not specifying the str_type to scpi_device
#       and when it is used as an option device for scpi_device (to obtain
#       the string replacement for the command/question)
#       Therefore even if you override the functions (by defining str_type)
#       they could still be used if they are within options.
#       Therefore it is recommended to make them work all the time
#       (this might require passing in a type during __init__)
#       See ChoiceDevDep for example

class ChoiceBase(object):
    def __call__(self, input_str):
        raise NotImplementedError, 'ChoiceBase subclass should overwrite __call__'
    def tostr(self, val):
        raise NotImplementedError, 'ChoiceBase subclass should overwrite __tostr__'
    def __repr__(self):
        raise NotImplementedError, 'ChoiceBase subclass should overwrite __repr__'
    def __contains__(self, val):
        raise NotImplementedError, 'ChoiceBase subclass should overwrite __contains__'

class ChoiceStrings(ChoiceBase):
    """
       Initialize the class with a list of strings
        s=ChoiceStrings('Aa', 'Bb', ..)
       then 'A' in s  or 'aa' in s will return True
       irrespective of capitalization.
       if no_short=True option is given, then only the long names are allowed
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
    def __init__(self, *values, **kwarg):
        # use **kwarg because we can't have keyword arguments after *arg
        self.quotes = kwarg.pop('quotes', False)
        no_short = kwarg.pop('no_short', False)
        if kwarg != {}:
            raise TypeError, 'ChoiceStrings only has quotes=False and no_short=False as keyword arguments'
        self.values = values
        self.long = [v.lower() for v in values]
        if no_short:
            self.short = self.long
        else:
            self.short = [v.translate(None, string.ascii_lowercase).lower() for v in values]
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

class ChoiceSimpleMap(ChoiceBase):
    """
    Given a dictionnary where keys are what is used on the instrument, and
    the values are what are used on the python side.
    filter, when given, is a function applied to the input from the instrument.
    It can be used to normalize the input entries
    """
    def __init__(self, input_dict, filter=None):
        self.dict = input_dict
        self.keys = input_dict.keys()
        self.values = input_dict.values()
        self.filter = filter
        if filter != None:
            for x in self.keys:
                if filter(x) != x:
                    raise ValueError, "The input dict has at least one key where filter(key)!=key."
    def __contains__(self, x):
        return x in self.values
    def __call__(self, input_key):
        if self.filter != None:
            input_key = self.filter(input_key)
        return self.dict[input_key]
    def tostr(self, input_choice):
        return self.keys[self.values.index(input_choice)]
    def __repr__(self):
        return repr(self.values)

Choice_bool_OnOff = ChoiceSimpleMap(dict(ON=True, OFF=False), filter=string.upper)

class ChoiceIndex(ChoiceBase):
    """
    Initialize the class with a list of values or a dictionnary
    The instrument uses the index of a list or the key of the dictionnary
    which needs to be integers. If you want a dictionnary with keys that
    are strings see ChoiceSimpleMap.
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
           v can only be a single value
           Anything with +-1e-25 becomes 0.
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
    """ This class selects options from a dictionnary of lists
        or instances of ChoiceBase, based on the value of dev (match to the
        dictionnary keys).
        The keys can be values or and object that handles 'in' testing.
        A default choice can be given with a key of None
        sub_type is used to provide the proper from/to str converters.
        Works the same as str_type from scpi_device.
        if sub_type==None, it calls the to/from str of the selected value of
        the dictionnary (which should be an instance of ChoiceBase).
    """
    def __init__(self, dev, choices, sub_type=None):
        self.choices = choices
        self.dev = dev
        self.sub_type = sub_type
    def _get_choice(self):
        val = self.dev.getcache()
        for k, v in self.choices.iteritems():
            if isinstance(k, (tuple, ChoiceBase)) and val in k:
                return v
            elif val == k:
                return v
        return self.choices.get(None, [])
    def __call__(self, input_str):
        if self.sub_type:
            return _fromstr_helper(input_str, self.sub_type)
        else:
            return self._get_choice()(input_str)
    def tostr(self, input_choice):
        if self.sub_type:
            return _tostr_helper(input_choice, self.sub_type)
        else:
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

     Indexing with one of the allowed values returns the value for list
     or the key/value pair for dict.
     For a list also using an integer is allowed, and it picks the nth value.

     sub_type is used to provide the proper from/to str converters.
     Works the same as str_type from scpi_device.
     sub_type==None (default) is the same as sub_type=str (i.e. no conversion).
     The tostr converter uses the key of the dict.
    """
    def __init__(self, dev, sub_type=None):
        self.dev = dev
        self.sub_type = sub_type
    def _get_choices(self):
        return self.dev.getcache()
    def __call__(self, input_str):
        return _fromstr_helper(input_str, self.sub_type)
    def tostr(self, input_choice):
        choices = self._get_choices()
        ch = self[input_choice]
        if isinstance(choices, dict):
            ch = ch[0]
        return _tostr_helper(ch, self.sub_type)
    def __contains__(self, x):
        choices = self._get_choices()
        if isinstance(choices, dict):
            if x in choices.keys():
                return True
            choices = choices.values()
        return x in choices
    def __getitem__(self, key):
        choices = self._get_choices()
        if key not in self and isinstance(choices, list): # key might be an integer
            return choices[key]
        if key in self:
            if isinstance(choices, dict):
                if key not in choices.keys() and key in choices.values():
                    key = [k for k,v in choices.iteritems() if v == key][0]
                return key, choices[key]
            else:
                return key
        raise IndexError, 'Invalid index. choose among: %r'%choices
    def __repr__(self):
        return repr(self._get_choices())

class ChoiceDevSwitch(ChoiceDev):
    """
    Same as ChoiceDev but the value for set/check can also
    be something other (a type different than in_base_type),
    in which case the other_conv function should convert it to the in_base_type.
    """
    def __init__(self, dev, other_conv, sub_type=None, in_base_type=basestring):
        self.other_conv = other_conv
        self.in_base_type = in_base_type
        super(ChoiceDevSwitch, self).__init__(dev, sub_type=sub_type)
    def cleanup_entry(self, x):
        if not isinstance(x, self.in_base_type):
            x = self.other_conv(x)
        return x
    def __getitem__(self, input_choice):
        input_choice = self.cleanup_entry(input_choice)
        return super(ChoiceDevSwitch, self).__getitem__(input_choice)
    def __contains__(self, input_choice):
        input_choice = self.cleanup_entry(input_choice)
        return super(ChoiceDevSwitch, self).__contains__(input_choice)

def make_choice_list(list_values, start_exponent, end_exponent):
    """
    given list_values=[1,3]
          start_exponent =-6
          stop_expoenent = -3
    produces [1e-6, 3e-6, 1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3]
    """
    powers = np.logspace(start_exponent, end_exponent, end_exponent-start_exponent+1)
    return (powers[:,None] * np.array(list_values)).flatten()

class dict_improved(OrderedDict):
    """
    This adds to the basic dict/OrderedDict syntax:
        -getting/setting/deleting with numerical indexing (obj[0])
                or with slices obj[1:3] or with list of index
                obj[[2,1,3]]. can also use list of keys (obj[['key1', 'key2']])
        -getting a regular dict/OrderedDict copy (as_dict)
        -getting/setting/deleting as attributes (obj.key)
        -adding new elements to the dict as attribute (obj.newkey=val)
         (could already do obj['newkey']=val)
    Note that it can be initialized like dict(a=1, b=2) but the order is not
    conserved: dict_improved(a=1, b=2) is not exactly the same as
    dict_improved(b=1, a=2). So to recreate a dict, use the output from repr_raw
    not from str.
    show_all method shows all the entry, one per line by default.
    the option _freeze=True prevents adding/removing elements to the dict (defaults to False).
    the option _allow_overwrite=True (the default) allows overwritting existing attributes
      (the original attribute is saved as oldname_orig)
    """
    def __init__(self, *arg, **kwarg):
        freeze = kwarg.pop('_freeze', False)
        allow_overwrite = kwarg.pop('_allow_overwrite', True)
        #self._known_keys = []
        super(dict_improved, self).__setattr__('_known_keys', [])
        super(dict_improved, self).__setattr__('_dict_improved__init_complete', False)
        super(dict_improved, self).__setattr__('_freeze', freeze)
        super(dict_improved, self).__setattr__('_allow_overwrite', allow_overwrite)
        # Now check the entries
        tmp = OrderedDict(*arg, **kwarg)
        for key in tmp.keys():
            if not isinstance(key, basestring):
                raise TypeError, "You can only use strings as keys."
        # input is ok so create the object
        super(dict_improved, self).__init__(*arg, **kwarg)
        self._dict_improved__init_complete = True
    def _set_freeze(self, val):
        """
        Change the freeze state. val is True or False
        This works even when _allow_overwrite is True
        """
        super(dict_improved, self).__setattr__('_freeze', val)
    def __getattribute__(self, name):
        known = super(dict_improved, self).__getattribute__("_known_keys")
        if name in known:
            return self[name]
        else:
            return super(dict_improved, self).__getattribute__(name)
    def _setattribute_helper(self, name):
        # Check to see if use indexing (returns True) or the parent call (returns False)
        if not self._dict_improved__init_complete:
            # during init, we use parent call
            return False
        if name in self._known_keys:
            return True
        if hasattr(self, name):
            # not in known but already exists
            if self._freeze:
                # This allows changing the value directly
                return False
            if self._allow_overwrite:
                return True
        # not known and does not exist
        return True # should add it or raise an exception
    def __setattr__(self, name, value):
        if self._setattribute_helper(name):
            self[name] = value
        else:
            super(dict_improved, self).__setattr__(name, value)
    def __delattr__(self, name):
        if name in self._known_keys:
            del self[name]
        else:
            super(dict_improved, self).__delattr__(name)
    def __getitem__(self, key):
        if isinstance(key, list):
            return [self[k] for k in key]
        if not isinstance(key, basestring):
            # assume we are using an integer index
            key = self.keys()[key]
            if isinstance(key, list): # it was a slice
                return self[key]
        return super(dict_improved, self).__getitem__(key)
    def __delitem__(self, key):
        if isinstance(key, list):
            for k in key:
                del self[k]
            return
        if not isinstance(key, basestring):
            # assume we are using an integer index
            key = self.keys()[key]
            if isinstance(key, list): # it was a slice
                del self[key]
                return
        if self._freeze and key in self._known_keys:
            raise RuntimeError, "Modifying keys of dictionnary not allowed for this object."
        super(dict_improved, self).__delitem__(key)
        self._known_keys.remove(key)
        delattr(self, key)
    def __setitem__(self, key, value):
        if isinstance(key, list):
            if len(key) != len(value):
                raise RuntimeError('keys and values are not the same length.')
            for k,v in zip(key, value):
                self[k] = v
            return
        if not isinstance(key, basestring):
            # assume we are using an integer index
            key = self.keys()[key]
            if isinstance(key, list): # it was a slice
                self[key] = value
                return
        if self._dict_improved__init_complete and self._freeze and key not in self._known_keys:
            raise RuntimeError, "Modifying keys of dictionnary not allowed for this object."
        if key not in self._known_keys:
            if hasattr(self, key):
                if not self._allow_overwrite:
                    raise RuntimeError, "Replacing existing attributes not allowed for this object."
                super(dict_improved, self).__setattr__(key+'_orig', getattr(self, key))
            # add entry so tab completion sees it
            super(dict_improved, self).__setattr__(key, 'Should never see this')
            self._known_keys.append(key)
        super(dict_improved, self).__setitem__(key, value)
    def clear(self):
        if self._freeze:
            raise RuntimeError, "Modifying keys of dictionnary not allowed for this object."
        keys = self._known_keys
        del self._known_keys[:]
        for k in keys:
            delattr(self, k)
        super(dict_improved, self).clear()
    def as_dict(self, order=False):
        """
        Returns a copy in a regular dict (order=False)
        or an ordered dict copy (order=True, same as copy method).
        """
        if order:
            return OrderedDict(self)
        else:
            return dict(self)
    def show_all(self, multiline=True, show=True):
        strs = ['%s=%r'%(k, v) for k,v in self.items()]
        if multiline:
            ret = '%s(\n  %s\n)'%(self.__class__.__name__, '\n  '.join(strs))
        else:
            ret = '%s(%s)'%(self.__class__.__name__, ', '.join(strs))
        if show:
            print ret
        else:
            return ret
    def __repr__(self):
        # could use numpy.get_printoptions()['threshold']
        """ This is a simplified view of the data. Using it to recreate
            the structure would necessarily keep the order.
            Use the repr_raw method output for that."""
        return self.show_all(multiline=False, show=False)
    def repr_raw(self):
        return super(dict_improved, self).__repr__()

class KeyError_Choices (KeyError):
    pass

class ChoiceMultiple(ChoiceBase):
    def __init__(self, field_names, fmts=int, sep=','):
        """
        This handles scpi commands that return a list of options like
         1,2,On,1.34
        We convert it into a dictionary to name and acces the individual
        parameters.
        fmts can be a single converter or a list of converters
        the same length as field_names
        A converter is either a type or a (type, lims) tuple
        where lims can be a tuple (min, max) with either one being None
        or a list/object of choices.
        Not that if you use a ChoiceBase object, you only need to specify
        it as the type. It is automatically used as a choice also.
        If one element of a list can affect the choices for a subsequent one,
        see ChoiceMultipleDev
        """
        self.field_names = field_names
        if not isinstance(fmts, (list, np.ndarray)):
            fmts = [fmts]*len(field_names)
        fmts_type = []
        fmts_lims = []
        for f in fmts:
            if not isinstance(f, tuple):
                if isinstance(f, ChoiceBase):
                    f = (f,f)
                else:
                    f = (f, None)
            fmts_type.append(f[0])
            fmts_lims.append(f[1])
        self.fmts_type = fmts_type
        self.fmts_lims = fmts_lims
        self.sep = sep
    def __call__(self, fromstr):
        v_base = fromstr.split(self.sep)
        if len(v_base) != len(self.field_names):
            raise ValueError, 'Invalid number of parameters in class dict_str'
        v_conv = []
        names = []
        for k, val, fmt in zip(self.field_names, v_base, self.fmts_type):
            if isinstance(fmt, ChoiceMultipleDep):
                fmt.set_current_vals(dict(zip(names, v_conv)))
            v_conv.append(_fromstr_helper(val, fmt))
            names.append(k)
        return dict_improved(zip(self.field_names, v_conv), _freeze=True)
    def tostr(self, fromdict=None, **kwarg):
        # we assume check (__contains__) was called so we don't need to
        # do fmt.set_current_vals again or check validity if dictionnary keys
        if fromdict == None:
            fromdict = kwarg
        ret = []
        for k, fmt in zip(self.field_names, self.fmts_type):
            v = fromdict[k]
            ret.append(_tostr_helper(v, fmt))
        ret = self.sep.join(ret)
        return ret
    def __contains__(self, x): # performs x in y; with y=Choice(). Used for check
        xorig = x
        x = x.copy() # make sure we don't change incoming dict
        for k, fmt, lims in zip(self.field_names, self.fmts_type, self.fmts_lims):
            try:
                if isinstance(fmt, ChoiceMultipleDep):
                    fmt.set_current_vals(xorig)
                val = x.pop(k) # generates KeyError if k not in x
                _general_check(val, lims=lims)
            except ValueError as e:
                raise ValueError('for key %s: '%k + e.args[0], e.args[1])
            except KeyError as e:
                raise KeyError_Choices('key %s not found'%k)
        if x != {}:
            raise KeyError_Choices('The following keys in the dictionnary are incorrect: %r'%x.keys())
        return True
    def __repr__(self):
        r = ''
        first = True
        for k, lims in zip(self.field_names, self.fmts_lims):
            if not first:
                r += '\n'
            first = False
            r += 'key %s has limits %r'%(k, lims)
        return r

class ChoiceMultipleDep(ChoiceBase):
    """ This class selects options from a dictionnary of lists
        or instances of ChoiceBase, based on the value of key (match to the
        dictionnary keys). It is similar to ChoiceDevDep but selects on
        a ChoiceMultiple element instead of a device.
        It can only be used as a type for a ChoiceMultiple element.
        The dictionnary keys can be values or and object that handles 'in' testing.
        A default choice can be given with a key of None

        sub_type is used to provide the proper from/to str converters.
        Works the same as str_type from scpi_device.
        if sub_type==None, it calls the to/from str of the selected value of
        the dictionnary (which should be an instance of ChoiceBase).

        Note that the dependent option currently requires the key to come before.
        i.e. if the base is {'a':1, 'B':2} then 'B' can depend on 'a' but not
        the reverse (the problem is with ChoiceMultiple __contains__, __call__
        and tostr).
    """
    def __init__(self, key, choices, sub_type=None):
        self.choices = choices
        self.key = key
        self.all_vals = {key:None}
        self.sub_type = sub_type
    def set_current_vals(self, all_vals):
        self.all_vals = all_vals
    def _get_choice(self):
        val = self.all_vals[self.key]
        for k, v in self.choices.iteritems():
            if isinstance(k, (tuple, ChoiceBase)) and val in k:
                return v
            elif val == k:
                return v
        return self.choices.get(None, [])
    def __call__(self, input_str):
        if self.sub_type:
            return _fromstr_helper(input_str, self.sub_type)
        else:
            return self._get_choice()(input_str)
    def tostr(self, input_choice):
        if self.sub_type:
            return _tostr_helper(input_choice, self.sub_type)
        else:
            return self._get_choice().tostr(input_choice)
    def __contains__(self, x):
        return x in self._get_choice()
    def __repr__(self):
        return repr(self.choices)


class Dict_SubDevice(BaseDevice):
    """
    Use this to gain access to a single element of a device returning a dictionary
    from dict_str.
    """
    def __init__(self, subdevice, key, force_default=False, **kwarg):
        """
        This device and the subdevice need to be part of the same instrument
        (otherwise async will not work properly)
        The subdice needs to return a dictionary (use dict_str).
        Here we will only modify the value of key in dictionary.
        force_default, set the default value of force used in check/set.
        """
        self._subdevice = subdevice
        self._sub_key = key
        self._force_default = force_default
        subtype = self._subdevice.type
        if key not in subtype.field_names:
            raise IndexError, 'The key is not present in the subdevice'
        lims = subtype.fmts_lims[subtype.field_names.index(key)]
        min = max = choices = None
        if lims == None:
            pass
        elif isinstance(lims, tuple):
            min, max = lims
        else:
            choices = lims
        setget = subdevice._setget
        autoinit = subdevice._autoinit
        trig = subdevice._trig
        delay = subdevice._delay
        # TODO find a way to point to the proper subdevice in doc string
        doc = """This device set/get the '%s' dictionnary element of device.
                 It uses the same options as that subdevice:
              """%(key)
        super(Dict_SubDevice, self).__init__(min=min, max=max, choices=choices, doc=doc,
                setget=setget, autoinit=autoinit, trig=trig, delay=delay, **kwarg)
        self._setdev_p = True # needed to enable BaseDevice set in checking mode and also the check function
        self._getdev_p = True # needed to enable BaseDevice get in Checking mode
    def getcache(self):
        vals = self._subdevice.getcache()
        if vals == None:
            ret = None
        else:
            ret = vals[self._sub_key]
        self._cache = ret
        return ret
    def _getdev(self, **kwarg):
        vals = self._subdevice.get(**kwarg)
        return vals[self._sub_key]
    def _setdev(self, val, force=None, **kwarg):
        """
        force when True, it make sure to obtain the
         subdevice value with get.
              when False, it uses getcache.
        The default is in self._force_default
        """
        if force == None:
            force = self._force_default
        if force:
            vals = self._subdevice.get(**kwarg)
        else:
            vals = self._subdevice.getcache()
        vals = vals.copy()
        vals[self._sub_key] = val
        self._subdevice.set(vals)



class Lock_Visa(object):
    """
    This handles the locking of the visa session.
    Once locked, this prevents any other visa session (same process or not) to
    the same instrument from communicating with it.
    It is a reentrant lock (release the same number of times as acquire
    to fully unlock).
    """
    def __init__(self, vi):
        self._vi = vi
        self._count = 0
    def _visa_lock(self, timeout=0.001):
        """
        It returns True if the lock was acquired before timeout, otherwise it
        returns False
        """
        timeout = max(int(timeout/1e-3),1) # convert from seconds to milliseconds
        try:
            self._vi.lock_excl(timeout)
        except visa_wrap.VisaIOError as exc:
            if exc.error_code == visa_wrap.constants.VI_ERROR_TMO:
                # This is for Agilent IO visa library
                return False
            elif exc.error_code == visa_wrap.constants.VI_ERROR_RSRC_LOCKED:
                # This is for National Instruments visa library
                return False
            else:
                raise
        else:
            # we have lock
            self._count += 1
            return True
    def release(self):
        self._vi.unlock() # could produce VI_ERROR_SESN_NLOCKED
        self._count -= 1
    def acquire(self):
        return wait_on_event(self._visa_lock)
    __enter__ = acquire
    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.release()
    def is_owned(self):
        return self._count != 0
    def force_release(self):
        n = 0
        expect = self._count
        try:
            while True:
                self.release()
                n += 1
        except visa_wrap.VisaIOError as exc:
            if exc.error_code != visa_wrap.constants.VI_ERROR_SESN_NLOCKED:
                raise
        if n:
            print 'Released Visa lock', n, 'time(s) (expected %i releases)'%expect
        else:
            print 'Visa lock was not held (expected %i releases)'%expect
        self._count = 0


#######################################################
##    VISA Instrument
#######################################################
_SharedStructure_debug = False
class _SharedStructure(object):
    """
    This shares a single ctype object across multiple processes.
    Access it with the data attribute.
    If the data attribute has members, accessing it directly on this object will be forwared
    to the data object.
    Should only use this if the memory access are protected with locks (between process).
    Visa can do that (otherwise have a look at multiprocessing.synchronize._multiprocessing.SemLock)
    """
    def __init__(self, somectype, tagname):
        import mmap
        self._tagname = tagname
        counter_type = ctypes.c_int32
        counter_size = ctypes.sizeof(ctypes.c_int32)
        size = counter_size + ctypes.sizeof(somectype)
        if os.name != 'nt':
            # we assume posix like. on linux need python-posix_ipc package (fedora)
            import posix_ipc
            self._shared_obj = posix_ipc.SharedMemory(tagname, posix_ipc.O_CREAT, size=size)
            self.buffer = mmap.mmap(self._shared_obj.fd, size)
            self._shared_obj.close_fd()
        else: # for windows
            self.buffer = mmap.mmap(-1, size, tagname=tagname)
        self._counter = counter_type.from_buffer(self.buffer, 0)
        self.data = somectype.from_buffer(self.buffer, counter_size)
        self._add_count()
        if _SharedStructure_debug:
            print 'There are now %i users of %r'%(self._get_count(), tagname)
    def __getattr__(self, name):
        return getattr(self.data, name)
    def __setattr__(self, name, value):
        try:
            data = object.__getattribute__(self, 'data')
            if hasattr(data, name):
                setattr(self.data, name, value)
                return
        except AttributeError:
            pass
        object.__setattr__(self, name, value)
    def _get_count(self):
        return self._counter.value
    def _add_count(self):
        self._counter.value += 1
    def _dec_count(self):
        self._counter.value -= 1
    def __del__(self):
        self._dec_count()
        count = self._get_count()
        if _SharedStructure_debug:
            print 'Cleaned up mmap, counter now %i'%self._get_count()
        self.buffer.close()
        if count == 0 and os.name != 'nt':
            self._shared_obj.unlink()

class _LastTime(ctypes.Structure):
    _fields_ = [('write_time', ctypes.c_double),
                ('read_time', ctypes.c_double)]

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
    def __init__(self, visa_addr, **kwarg):
        # need to initialize visa before calling BaseInstrument init
        # which might require access to device
        if type(visa_addr)==int:
            visa_addr= 'GPIB0::%i::INSTR'%visa_addr
        self.visa_addr = visa_addr
        if not CHECKING:
            self.visa = rsrc_mngr.open_resource(visa_addr, **kwarg)
            self._lock_extra = Lock_Visa(self.visa)
        #self.visa.timeout = 3 # in seconds
        # use 2.9 because I was getting 3.0 rounded to 10s timeouts on some visa lib configuration
        #     2.9 seemed to be rounded up to 3s instead
        self.set_timeout = 2.9 # in seconds
        to = time.time()
        self._last_rw_time = _LastTime(to, to) # When wait time are not 0, it will be replaced
        self._write_write_wait = 0.
        self._read_write_wait = 0.
        BaseInstrument.__init__(self)
    def __del__(self):
        #print 'Destroying '+repr(self)
        # no need to call self.visa.close()
        # because self.visa does that when it is deleted
        super(visaInstrument, self).__del__()
    # Do NOT enable locked_calling for read_status_byte, otherwise we get a hang
    # when instrument is on gpib using agilent visa. But do use lock visa
    # otherwise read_stb could fail because of lock held in another thread/process
    #@locked_calling
    def read_status_byte(self):
        # since on serial visa does the *stb? request for us
        # might as well be explicit and therefore handle the rw_wait properly
        if self.visa.is_serial():
            return int(self.ask('*stb?'))
        else:
            with self._lock_extra:
                return self.visa.read_stb()
    @locked_calling
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
        cnsts = visa_wrap.constants
        if all:
            if remote:
                val = cnsts.VI_GPIB_REN_ASSERT
            else:
                val = cnsts.VI_GPIB_REN_DEASSERT
        elif local_lockout:
            if remote:
                val = cnsts.VI_GPIB_REN_ASSERT_ADDRESS_LLO
            else:
                val = cnsts.VI_GPIB_REN_DEASSERT_GTL
                self.visa.control_ren(val)
                val = cnsts.VI_GPIB_REN_ASSERT
        else:
            if remote:
                val = cnsts.VI_GPIB_REN_ASSERT_ADDRESS
            else:
                val = cnsts.VI_GPIB_REN_ADDRESS_GTL
        self.visa.control_ren(val)
    def _do_wr_wait(self):
        if self._last_rw_time.read_time > self._last_rw_time.write_time:
            # last operation was a read
            last_time = self._last_rw_time.read_time
            wait_time = self._read_write_wait
        else: # last operation was a write
            last_time = self._last_rw_time.write_time
            wait_time = self._write_write_wait
        if wait_time == 0.:
            return
        if not isinstance(self._last_rw_time, _SharedStructure):
            # The timeout needs to work across process, So we now share the last time values
            tagname = 'pyHegel-' + self.__class__.__name__ + '-' + hashlib.sha1(self.visa_addr).hexdigest()
            old = self._last_rw_time
            self._last_rw_time = _SharedStructure(_LastTime, tagname)
            self._last_rw_time.read_time = old.read_time
            self._last_rw_time.write_time = old.write_time
        cur_time = time.time()
        delta = (last_time+wait_time) - cur_time
        if delta >0:
            sleep(delta)
    @locked_calling
    def read(self, raw=False):
        if raw:
            ret = self.visa.read_raw()
        else:
            ret = self.visa.read()
        self._last_rw_time.read_time = time.time()
        return ret
    @locked_calling
    def write(self, val):
        self._do_wr_wait()
        self.visa.write(val)
        self._last_rw_time.write_time = time.time()
    @locked_calling
    def ask(self, question, raw=False):
        """
        Does write then read.
        With raw=True, replaces read with a read_raw.
        This is needed when dealing with binary data. The
        base read strips newlines from the end always.
        """
        # we prevent CTRL-C from breaking between write and read using context manager
        with _delayed_signal_context_manager():
            self.write(question)
            ret = self.read(raw)
        return ret
    def idn(self):
        return self.ask('*idn?')
    def factory_reset(self):
        """
        This returns the instrument to a known state.
        Use CAREFULLY!
        """
        self.write('*RST')
        self.force_get()
    def _clear(self):
        self.visa.clear()
    @property
    def set_timeout(self):
        timeout_ms = self.visa.timeout
        if timeout_ms is None:
            return None
        else:
            return timeout_ms/1000. # return in seconds
    @set_timeout.setter
    def set_timeout(self, seconds):
        if seconds is None:
            self.visa.timeout = None
        else:
            self.visa.timeout = int(seconds*1000.)
    def get_error(self):
        return self.ask('SYSTem:ERRor?')
    def _info(self):
        gn, cn, p = BaseInstrument._info(self)
        return gn, cn+'(%s)'%self.visa_addr, p
    def trigger(self):
        # This should produce the hardware GET on gpib
        #  Another option would be to use the *TRG 488.2 command
        self.visa.trigger()


#######################################################
##    VISA Async Instrument
#######################################################

#TODO improve service request event handling.
#     right now, for usb, lan I miss event when another process generates OPC
#       for usb on NI visa lib I also need to read a miss status byte
#     For gpib agilent, all device on bus will receive a handler/queue event
#       I use the handler. Since I read the status byte in my handler, that
#       would normally screw up other process (they could miss the event).
#       However since my read_status_byte is protected by a lock, only
#       the device that is really waiting will cleanup. The others will be locked,
#       until the processing is complete.
#
#     For NI gpib, only the device that has SRQ on will receive the handler/queue event
#       my handler are called within the gpib notify callback. All handlers
#       across all process are called.
#       However queued events are only produced when waiting for the events,
#       they are not generated otherwise (for queued events, the driver does not setup
#       a notify callback). It is possible to loose events if the serial the the status read
#       occurs between ibwait (which is every 1ms). However, again, the status read is protected
#       by the lock.
#
#     I should have a tool to check the state of the srq line, in case it is hung.
#     I can't find a way to clear the SRQ of all devices on the bus (IFC, clear don't work)

class visaInstrumentAsync(visaInstrument):
    def __init__(self, visa_addr, poll=False):
        # poll can be True (for always polling) 'not_gpib' for polling for lan and usb but
        # use the regular technique for gpib
        # the _async_sre_flag should match an entry somewhere (like in init)
        self._async_sre_flag = 0x20 #=32 which is standard event status byte (contains OPC)
        self._async_last_status = 0
        self._async_last_status_time = 0
        self._async_last_esr = 0
        super(visaInstrumentAsync, self).__init__(visa_addr)
        is_gpib = self.visa.is_gpib()
        is_agilent = rsrc_mngr.is_agilent()
        self._async_polling = False
        if poll == True or (poll == 'not_gpib' and not is_gpib):
            self._async_polling = True
            self._RQS_status = -1
        elif is_gpib and is_agilent:
            # Note that the agilent visa using a NI usb gpib adapter (at least)
            # disables the autopoll settings of NI
            # Hence a SRQ on the bus produces events for all devices on the bus.
            # If those events are not read, the buffer eventually fills up.
            # This is a problem when using more than one visaInstrumentAsync
            # To avoid that problem, I use a handler in that case.
            self._RQS_status = 0  #-1: no handler, 0 not ready, other is status byte
            self._RQS_done = FastEvent()  #starts in clear state
            self._proxy_handler = ProxyMethod(self._RQS_handler)
            # _handler_userval is the ctype object representing the user value (0 here)
            # It is needed for uninstall
            self._handler_userval = self.visa.install_visa_handler(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                                  self._proxy_handler, 0)
            self.visa.enable_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                               visa_wrap.constants.VI_HNDLR)
        else:
            self._RQS_status = -1
            self.visa.enable_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                               visa_wrap.constants.VI_QUEUE)
    def __del__(self):
        if self._RQS_status != -1:
            # only necessary to keep handlers list in sync
            # the actual handler is removed when the visa is deleted (vi closed)
            self.visa.uninstall_handler(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                                  self._proxy_handler, self._handler_userval)
        super(visaInstrumentAsync, self).__del__()
    def init(self, full=False):
        # This clears the error state, and status/event flags?
        self.write('*cls')
        if full:
            self.write('*ese 1;*sre 32') # OPC flag
    def _RQS_handler(self, vi, event_type, context, userHandle):
        # When NI autopoll is off:
        # Reading the status will clear the service request of this instrument
        # if the SRQ line is still active, another call to the handler will occur
        # after a short delay (30 ms I think) everytime a read_status_byte is done
        # on the bus (and SRQ is still active).
        # For agilent visa, the SRQ status is queried every 30ms. So
        # you we might have to wait that time after the hardware signal is active
        # before this handler is called.
        status = self.read_status_byte()
        # If multiple session talk to the same instrument
        # only one of them will see the RQS flag. So to have a chance
        # of more than one, look at other flag instead (which is not immediately
        # reset)
        # TODO, handle this better?
        #if status&0x40:
        if status & self._async_sre_flag:
            self._RQS_status = status
            self._async_last_status = status
            self._async_last_status_time = time.time()
            sleep(0.01) # give some time for other handlers to run
            self._RQS_done.set()
            #print 'Got it', vi
        return visa_wrap.constants.VI_SUCCESS
    def _get_esr(self):
        return int(self.ask('*esr?'))
    def  _async_detect_poll_func(self):
        status = self.read_status_byte()
        if status & 0x40:
            self._async_last_status = status
            self._async_last_esr = self._get_esr()
            return True
        return False
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        if self._async_polling:
            if _retry_wait(self._async_detect_poll_func, max_time, delay=0.05):
                return True
        elif self._RQS_status == -1:
            # On National Instrument (NI) visa
            #  the timeout actually used seems to be 16*ceil(max_time*1000/16) in ms.
            wait_resp = self.visa.wait_on_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                                                int(max_time*1000), capture_timeout=True)
            # context in wait_resp will be closed automatically
            #if wait_resp.context != None:
            if not wait_resp.timed_out:
                # only reset event flag. We know the bit that is set already (OPC)
                self._async_last_esr = self._get_esr()
                # only reset SRQ flag. We know the bit that is set already
                self._async_last_status = self.read_status_byte()
                return True
        else:
            if self._RQS_done.wait(max_time):
                #we assume status only had bit 0x20(event) and 0x40(RQS) set
                #and event only has OPC set
                # status has already been reset. Now reset event flag.
                self._async_last_esr = self._get_esr()
                self._RQS_done.clear() # so that we can detect the next SRQ if needed without  _doing async_trig (_async_trig_cleanup)
                return True
        return False
    @locked_calling
    def wait_after_trig(self):
        """
        waits until the triggered event is finished
        """
        return wait_on_event(self._async_detect)
    @locked_calling
    def run_and_wait(self):
        """
        This initiate a trigger and waits for it to finish.
        """
        self._async_trig()
        self.wait_after_trig()
    def _async_trigger_helper(self):
        self.write('INITiate;*OPC') # this assume trig_src is immediate for agilent multi
    def _async_trig_cleanup(self):
        # We detect the end of acquisition using *OPC and status byte.
        if self._get_esr() & 0x01:
            print 'Unread event byte!'
        # A while loop is needed when National Instrument (NI) gpib autopoll is active
        # This is the default when using the NI Visa.
        while self.read_status_byte() & 0x40: # This is SRQ bit
            print 'Unread status byte!'
        if self._async_polling:
            pass
        elif self._RQS_status != -1:
            self._RQS_status = 0
            self._RQS_done.clear()
        else:
            # could use self.visa.discard_events(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
            #                                    visa_wrap.constans.VI_QUEUE)
            n = 0
            try:
                while True:
                    self.visa.wait_on_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ, 0)
                    n += 1
            except visa_wrap.VisaIOError as exc:
                if exc.error_code == visa_wrap.constants.VI_ERROR_TMO:
                    pass
                else:
                    raise
            if n>0:
                print 'Unread(%i) event queue!'%n
        self._async_last_status = 0
        self._async_last_esr = 0
    @locked_calling
    def _async_trig(self):
        self._async_trig_cleanup()
        self._async_trigger_helper()
