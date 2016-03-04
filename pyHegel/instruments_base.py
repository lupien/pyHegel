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

import numpy as np
import string
import functools
import ctypes
import hashlib
import os
import signal
import sys
import time
import inspect
import thread
import threading
import weakref
from collections import OrderedDict  # this is a subclass of dict
from .qt_wrap import processEvents
from .kbint_util import sleep, _sleep_signal_context_manager, _delayed_signal_context_manager

from . import visa_wrap
from . import instruments_registry
from .types import dict_improved

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
    _globaldict = {} # This is set in pyHegel _init_pyHegel_globals (from pyHegel.commands)

class _CHECKING():
    def __init__(self):
        self.state = False
    def get(self):
        return self.state
    def set(self, state):
        if not isinstance(state, bool):
            raise ValueError('The state needs to be a boolean')
        self.state = state
    def __call__(self, state=None):
        """
           Called with no arguments, returns current checking mode state
           With a boolean, sets the check state
        """
        if state is None:
            return self.get()
        else:
            self.set(state)

CHECKING = _CHECKING()

###################
###  New exceptions
class InvalidArgument(ValueError):
    pass

class InvalidAutoArgument(InvalidArgument):
    pass

class KeyError_Choices (KeyError):
    pass

class Runtime_Get_Para_Checked(Exception):
    """
    This exception is to be used to mark the end of parameter checking in a get function
    """
    pass

def get_para_checked(*val):
    """
       This function should be called in a _getdev after the parameters have been
       checked for validity. When in CHECKING only mode, this will skip the rest of
       the function.
       you should call this with one parameter (passed to exception) or no parameters
       When a parameter is given, it will be used as the get value (and cached)
    """
    if CHECKING():
        raise Runtime_Get_Para_Checked(*val)

###################

class ProxyMethod(object):
    def __init__(self, bound_method):
        #self.class_of_method = bound_method.im_class
        self.instance = weakref.proxy(bound_method.im_self)
        self.func_name = bound_method.func_name
    def __call__(self, *arg, **kwarg):
        return getattr(self.instance, self.func_name)(*arg, **kwarg)

#######################################################
##    Have a status line active
#######################################################

class time_check(object):
    def __init__(self, delay=10):
        self.delay = delay
        self.restart()
    def restart(self):
        self.last_update = time.time()
    def check(self):
        now = time.time()
        if now >= self.last_update + self.delay:
            self.last_update = now
            return True
        return False
    def __call__(self):
        return self.check()

class UserStatusLine(object):
    """
    The is the object created by MainStatusLine.new
    You should not create it directly.
    To use, just call the object with the new string.
    If the new string is not empty, the status line is also output.
    You can force an output using the method output.
    The timed, when True or a time in s (True is equivalent to 10s),
    makes the screen update slower than that time.
    """
    def __init__(self, main, handle, timed=False):
        self.main = main
        self.handle = handle
        if timed is not None and timed is not False:
            if timed is True:
                self._time_check = time_check()
            else:
                self._time_check = time_check(timed)
        else:
            self._time_check = None
    @property
    def delay(self):
        if self._time_check is not None:
            return self._time_check.delay
        return 0
    @delay.setter
    def delay(self, d):
        if self._time_check is not None:
            self._time_check.delay = d
    def restart_time(self):
        if self._time_check is not None:
            self._time_check.restart()
    def check_time(self):
        if self._time_check is not None:
            return self._time_check()
        return True
    def __del__(self):
        self.main.delete(self.handle)
    def __call__(self, new_status=''):
        self.main.change(self.handle, new_status)
        do_update = self.check_time()
        if new_status != '' and do_update:
            self.main.output()
    def output(self):
        self.main.output()

class MainStatusLine(object):
    """
    This class provides a tools for combining multiple strings in a status line.
    The status line the next line on the console which we keep rewriting (using
    a carriage return). To use, create a new user object (it will properly clean
    itself on deletion) using a single instance of this class (so should use:
    mainStatusLine.new()). You can select the priority you want for the status.
    Larger priority will show before lower ones. You can also put a limit to the
    update rate with timed (which is passed to UserStatusLine).
    For information on using the user object see UserStatusLine
    """
    def __init__(self):
        self.last_handle = 0
        self.users = {}
    def new(self, priority=1, timed=False):
        handle = self.last_handle + 1
        self.last_handle = handle
        self.users[handle] = [priority, '']
        return UserStatusLine(self, handle, timed)
        # higher priority shows before lower ones
    def delete(self, handle):
        del self.users[handle]
    def change(self, handle, new_status):
        self.users[handle][1] = new_status
    def output(self):
        entries = self.users.values()
        entries = sorted(entries, key=lambda x: x[0], reverse=True) # sort on decreasing priority only
        outstr = ' '.join([e[1] for e in entries if e[1] != '']) # join the non-empty status
        outstr = outstr if len(outstr)<=72 else outstr[:69]+'...'
        sys.stdout.write('\r%-72s'%outstr)
        sys.stdout.flush()

mainStatusLine = MainStatusLine()

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

def test_gpib_srq_state(bus=0):
    """ Test the state of the gpib bus SRQ line.
        It should normally be False unless an instrument is in the process of communicating.
        If it is ever True and stays that way, it will prevent further use of the line by
        any other device.
        It can be caused by an instrument on the bus that is not openned in any session but
        that is activating the srq line. Either open that device and clear it or turn it off.
    """
    return rsrc_mngr.get_gpib_intfc_srq_state()

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
        elif isinstance(val, (list, tuple)):
            ret.extend(val)
        else:
            ret.append(val)
    return ret

def _writevec(file_obj, vals_list, pre_str=''):
    """ write a line of data in the open file_obj.
    vals_list is a list of values or strings, or of np.ndarray which
    are flatten. Any value that is not a base_string is converted
    to a string use repr.
    The columns in the file are separated by tabs.
    pre_str is prepended to every line. Can use '#' when adding comments.
    """
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
    if newext is None:
        return filename
    root, ext = os.path.splitext(filename)
    return root+newext


def _write_dev(val, filename, format=format, first=False):
    append = format['append']
    bin = format['bin']
    dev = format['obj']
    multi = format['multi']
    extra_conf = format['extra_conf']
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
        if extra_conf: # not None or ''
            # extra_conf should be a complete string including # and new lines
            f.write(extra_conf)
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
    def __init__(self, operations, lock_instrument, lock_extra, init_ops, detect=None, delay=0., trig=None, cleanup=None):
        super(asyncThread, self).__init__()
        self.daemon = True
        self._stop = False
        self._async_delay = delay
        self._async_trig = trig
        self._async_detect = detect
        self._async_cleanup = cleanup
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
    def change_cleanup(self, new_cleanup):
        self._async_cleanup = new_cleanup
    def replace_result(self, val, index=None):
        if index is None:
            index = self._replace_index
            self._replace_index += 1
        self.results[index] = val
    @locked_calling
    def run(self):
        #t0 = time.time()
        for f, args, kwargs in self._init_ops:
            f(*args, **kwargs)
        delay = self._async_delay
        if delay and not CHECKING():
            func = lambda: self._stop
            _retry_wait(func, timeout=delay, delay=0.1)
        if self._stop:
            return
        try:
            if self._async_trig and not CHECKING():
                self._async_trig()
            #print 'Thread ready to detect ', time.time()-t0
            if self._async_detect is not None:
                while not self._async_detect():
                    if self._stop:
                        break
            if self._stop:
                return
        finally:
            if self._async_cleanup and not CHECKING():
                self._async_cleanup()
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
        if max_time is not None:
            check_time = max_time - (time.time()-start_time)
            check_time = max(0., check_time) # make sure it is positive
            check_time = min(check_time, 0.2) # and smaller than 0.2 s
        else:
            check_time = 0.2
        if docheck(check_time):
            return True
        if max_time is not None and time.time()-start_time > max_time:
            return False
        if check_state is not None and check_state._error_state:
            break
        with _delayed_signal_context_manager():
            # processEvents is for the current Thread.
            # if a thread does not have and event loop, this does nothing (not an error)
            processEvents(max_time_ms = 20)

def _general_check(val, min=None, max=None, choices=None, lims=None, msg_src=None):
   # self is use for perror
    if lims is not None:
        if isinstance(lims, tuple):
            min, max = lims
        else:
            choices = lims
    mintest = maxtest = choicetest = True
    if min is not None:
        mintest = val >= min
    if max is not None:
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
        if msg_src is None:
            err = 'Failed check: '+err
        else:
            err = 'Failed check for %s: '%msg_src + err
        d = dict(val=val, choices=repr(choices))
        raise ValueError(err.format(**d), d)


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
                  allow_missing_dict=False, get_has_check=False,
                  min=None, max=None, choices=None, multi=False, graph=True,
                  trig=False, redir_async=None):
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
        # get_has_check, make it true if the _getdev produces the Runtime_Get_Para_Checked
        #  exception (calls _get_para_checked). This is needed for proper CHECKING mode
        #  or if executing the get has not side effect.
        self.instr = None
        self.name = 'foo'
        # Use thread local data to keep the last_filename and a version of cache
        self._local_data = threading.local()
        self._cache = None
        self._set_delayed_cache = None
        self._check_cache = {}
        self._autoinit = autoinit
        self._setdev_p = None
        self._getdev_p = None
        self._setget = setget
        self._trig = trig
        self._redir_async = redir_async
        self._last_filename = None
        self.min = min
        self.max = max
        self.choices = choices
        self._allow_kw_as_dict = allow_kw_as_dict
        self._allow_missing_dict = allow_missing_dict
        self._get_has_check = get_has_check
        self._doc = doc
        # obj is used by _get_conf_header and _write_dev
        self._format = dict(file=False, multi=multi, xaxis=None, graph=graph,
                            append=False, header=None, bin=False, extra_conf=None,
                            options={}, obj=self)

    @property
    def _last_filename(self):
        try:
            return self._local_data.last_filename
        except AttributeError:
            return None
    @_last_filename.setter
    def _last_filename(self, filename):
        self._local_data.last_filename = filename

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
        if doc_base is None:
            doc_base = ''
        doc = self._doc
        extra = ''
        if self.choices:
            extra = '\n-------------\n Possible value to set: %s\n'%repr(self.choices)
        elif self.min is not None and self.max is not None:
            extra = '\n-------------\n Value between %r and %r\n'%(self.min, self.max)
        elif self.min is not None:
            extra = '\n-------------\n Value at least %r\n'%(self.min)
        elif self.max is not None:
            extra = '\n-------------\n Value at most %r\n'%(self.max)
        return doc + added + extra + doc_base
    # for cache consistency
    #    get should return the same thing set uses
    @locked_calling_dev
    def set(self, *val, **kwarg):
        if not CHECKING():
            # So when checking, self.check will be seen as in a check instead
            # of a set.
            self._check_cache['in_set'] = True
        self.check(*val, **kwarg)
        if self._check_cache:
            val = self._check_cache['val']
            kwarg = self._check_cache['kwarg']
            set_kwarg = self._check_cache['set_kwarg']
        else:
            val = val[0]
            set_kwarg = kwarg
        if not CHECKING():
            self._set_delayed_cache = None  # used in logical devices
            self._setdev(val, **set_kwarg)
            if self._setget:
                val = self.get(**kwarg)
            elif self._set_delayed_cache is not None:
                val = self._set_delayed_cache
        # only change cache after succesfull _setdev
        self.setcache(val)
    def _get_para_checked(self, *val):
        get_para_checked(*val)
    @locked_calling_dev
    def get(self, **kwarg):
        if self._getdev_p is None:
            raise NotImplementedError, self.perror('This device does not handle _getdev')
        if not CHECKING() or self._get_has_check:
            self._last_filename = None
            format = self.getformat(**kwarg)
            kwarg.pop('graph', None) #now remove graph from parameters (was needed by getformat)
            kwarg.pop('bin', None) #same for bin
            kwarg.pop('extra_conf', None)
            to_finish = False
            if kwarg.get('filename', False) and not format['file']:
                #we did not ask for a filename but got one.
                #since _getdev probably does not understand filename
                #we handle it here
                filename = kwarg.pop('filename')
                to_finish = True
            try:
                ret = self._getdev(**kwarg)
            except Runtime_Get_Para_Checked as e:
                if len(e.args) == 1:
                    ret = e.args[0]
                elif len(e.args) > 1:
                    ret = e.args
                else:
                    ret = self.getcache()
            if to_finish:
                _write_dev(ret, filename, format=format)
                if format['bin']:
                    ret = None
        else:
            ret = self.getcache()
        self.setcache(ret)
        return ret
    #@locked_calling_dev
    def getcache(self, local=False):
        """
        With local=True, returns thread local _cache. If it does not exist yet,
            returns None. Use this for the data from a last fetch if another
            thread is also doing fetches. (For example between after a get to make sure
            getcache obtains the result from the current thread (unless they are protected with a lock))
        With local=False (default), returns the main _cache which is shared between threads
            (but not process). When the value is None and autoinit is set, it will
            return the result of get. Use this if another thread might be changing the cached value
            and you want the last one. However if another thread is changing values,
            or the user changed the values on the instrument maually (using the front panel),
            than you better do get instead of getcache to really get the up to date value.
        """
        if local:
            try:
                return self._local_data.cache
            except AttributeError:
                return None
        # local is False
        with self.instr._lock_instrument: # only local data, so don't need _lock_extra
            if self._cache is None and self._autoinit and not CHECKING():
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
                           trig=obj._trig, **kwarg)
        # now make sure obj._cache and self._cache are the same
        else: # async == 3 and self != obj:
            # async thread is finished, so lock should be available
            with self.instr._lock_instrument: # only local data, so don't need _lock_extra
                #_get_async blocks if it is not in the correct thread and is not
                #complete. Here we just keep the lock until setcache is complete
                # so setcache does not have to wait for a lock.
                ret = obj.instr._get_async(async, obj, **kwarg)
                self.setcache(ret)
                self._last_filename = obj._last_filename
        if async == 3:
            # update the obj local thread cache data.
            obj._local_data.cache = ret
        return ret
    #@locked_calling_dev
    def setcache(self, val, nolock=False):
        if nolock == True:
            self._cache = val
        else:
            with self.instr._lock_instrument: # only local data, so don't need _lock_extra
                self._cache = val
        self._local_data.cache = val # thread local, requires no lock
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
    def _setdev(self, val, **kwarg):
        raise NotImplementedError, self.perror('This device does not handle _setdev')
    def _getdev(self, **kwarg):
        raise NotImplementedError, self.perror('This device does not handle _getdev')
    def _general_check(self, val, min=None, max=None, choices=None, lims=None, msg_src=None, str_return=False):
        # This wraps the _general_check function to wrap the error message with perror
        # with str_return, it either returns a error string or None instead of producting an exception
        try:
            _general_check(val, min, max, choices, lims, msg_src)
        except (ValueError, KeyError) as e:
            new_message = self.perror(e.args[0])
            # new_message = self.perror(e.args[0],**e.args[1])
            if str_return:
                return new_message
            raise e.__class__(new_message)
    def _pre_check(self, *val, **kwarg):
        # This cleans up *val and **kwarg to handle _allow_kw_as_dict
        #  It returns a single val and a cleaned up kwarg.
        # This will also always create a new _check_cache with at least the keys
        #   fnct_set, val, kwarg, fnct_str, set_kwarg
        #   in_set should be removed (so check after a set should work)
        #  kwarg should contain all the keyword (except for the _allow_kw_as_dict)
        #    that are needed for get
        #  set_kwarg are the kwarg passed to setdev
        #  Note that the returned kwarg is a copy so you can pop values out of it
        #  without modifying _check_cache['kwarg']
        in_set = self._check_cache.get('in_set', False)
        fnct_str = 'set' if in_set else 'check'
        self._check_cache = {'fnct_set':  in_set, 'fnct_str': fnct_str}
        if self._setdev_p is None:
            raise NotImplementedError, self.perror('This device does not handle %s'%fnct_str)
        nval = len(val)
        if nval == 1:
            val = val[0]
        elif nval == 0:
            val = None
        else:
            raise RuntimeError(self.perror('%s can only have one positional parameter'%fnct_str))
        if self._allow_kw_as_dict:
            if val is None:
                val = dict()
                for k in kwarg.keys():
                    if k in self.choices.field_names:
                        val[k] = kwarg.pop(k)
        elif nval == 0: # this permits to set a value to None
                raise RuntimeError(self.perror('%s requires a value.'%fnct_str))
        self._check_cache['val'] = val
        self._check_cache['kwarg'] = kwarg
        self._check_cache['set_kwarg'] = kwarg.copy()
        return val, kwarg.copy()
    def _set_missing_dict_helper(self, val, _allow=None, **kwarg):
        """
            This will replace missing values if necessary.
            _allow can be None (which uses self._allow_missing_dict)
                  or it can be False, True (which uses get) or 'cache'
                  which uses the cache
                  Actually using False is an error
            it returns the possibly update val
        """
        if _allow is None:
            _allow = self._allow_missing_dict
        if _allow == 'cache':
            old_val = self.getcache()
        elif _allow is True:
            old_val = self.get(**kwarg)
        else:
            raise ValueError(self.perror('Called _set_missing_dict_helper with _allow=False'))
        old_val.update(val)
        return old_val
    def _checkdev(self, val):
        # This default _checkdev handles a general check with _allow_missing_dict
        # but no extra kwarg. The caller should have tested and removed them
        try:
            self._general_check(val, self.min, self.max, self.choices)
        except KeyError_Choices:
            # need to catch the exception instead of always filling all the variables
            # some device might accept partial entries
            # they could override _set_missing_dict_helper to only add some entries.
            if not self._allow_missing_dict:
                raise
            kwarg = self._check_cache['kwarg']
            val = self._set_missing_dict_helper(val, **kwarg)
            self._check_cache['val'] = val
            self._general_check(val, self.min, self.max, self.choices)
    @locked_calling_dev
    def check(self, *val, **kwarg):
        # This raises an exception if set does not work (_setdev_p is None)
        val, kwarg = self._pre_check(*val, **kwarg)
        self._checkdev(val, **kwarg)
    def getformat(self, filename=None, **kwarg): # we need to absorb any filename argument
        # This function should not communicate with the instrument.
        # first handle options we don't want saved in 'options'
        graph = kwarg.pop('graph', None)
        extra_conf = kwarg.pop('extra_conf', None)
        self._format['options'] = kwarg
        #now handle the other overides
        bin = kwarg.pop('bin', None)
        xaxis = kwarg.pop('xaxis', None)
        # we need to return a copy so changes to dict here and above does not
        # affect the devices dict permanently
        format = self._format.copy()
        if graph is not None:
            format['graph'] = graph
        if bin is not None:
            format['file'] = False
            format['bin'] = bin
        if xaxis is not None and format['xaxis'] is not None:
            format['xaxis'] = xaxis
        format['extra_conf'] = extra_conf
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
    def __init__(self, setdev=None, getdev=None, checkdev=None, getformat=None, **extrak):
        # auto insert documentation if setdev or getdev has one.
        if not extrak.has_key('doc'):
            if setdev is not None and setdev.__doc__:
                extrak['doc'] = setdev.__doc__
            elif getdev is not None and getdev.__doc__:
                extrak['doc'] = getdev.__doc__
        BaseDevice.__init__(self, **extrak)
        # the methods are unbounded methods.
        self._setdev_p = setdev
        self._getdev_p = getdev
        self._checkdev_p  = checkdev
        self._getformat  = getformat
    def _setdev(self, val, **kwarg):
        self._setdev_p(val, **kwarg)
    def _getdev(self, **kwarg):
        return self._getdev_p(**kwarg)
    def _checkdev(self, val, **kwarg):
        if self._checkdev_p is not None:
            self._checkdev_p(val, **kwarg)
        else:
            super(wrapDevice, self)._checkdev(val, **kwarg)
    def getformat(self, **kwarg):
        if self._getformat is not None:
            return self._getformat(**kwarg)
        else:
            return super(wrapDevice, self).getformat(**kwarg)

class cls_wrapDevice(BaseDevice):
    def __init__(self, setdev=None, getdev=None, checkdev=None, getformat=None, **extrak):
        # auto insert documentation if setdev or getdev has one.
        if not extrak.has_key('doc'):
            if setdev is not None and setdev.__doc__:
                extrak['doc'] = setdev.__doc__
            elif getdev is not None and getdev.__doc__:
                extrak['doc'] = getdev.__doc__
        BaseDevice.__init__(self, **extrak)
        # the methods are unbounded methods.
        self._setdev_p = setdev
        self._getdev_p = getdev
        self._checkdev_p  = checkdev
        self._getformat  = getformat
    def _setdev(self, val, **kwarg):
        self._setdev_p(self.instr, val, **kwarg)
    def _getdev(self, **kwarg):
        return self._getdev_p(self.instr, **kwarg)
    def _checkdev(self, val, **kwarg):
        if self._checkdev_p is not None:
            self._checkdev_p(self.instr, val, **kwarg)
        else:
            super(cls_wrapDevice, self)._checkdev(val, **kwarg)
    def getformat(self, **kwarg):
        if self._getformat is not None:
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

# Async behavior changed 2015-06-03
# Before, the device would select either trig or delay
#   trig would use triggering, delay would use async_delay
#   If multiple device used both, they would both be turned on
#   and run_and_wait would only ever use trig, never async_delay
#   That was never really used and did not provide flexibility
#   like for devices that can sometimes need one or the other
#   or making run_and_wait behave like async for delay
# Now, to improve the situation, I removed the option of
#   delay for devices. Device can only say they need triggerring
#   or not. They also use it when then need a delay.
#   async_delay is always respected for every and all devices,
#   and for both async and run_and_wait. It is used before the trig
#   For the wait option in a trig, we use async_wait device.
#   Finally the selection of whether to use a trigger or
#   a delay is left to _async_trig and _async_detect.
#   They both use information from _async_mode which should be
#   set by _async_select which is called in the async thread (init_list)
#   and by ReadvalDev

class BaseInstrument(object):
    __metaclass__ = MetaClassInit
    alias = None
    def __init__(self, quiet_delete=False):
        self._quiet_delete = quiet_delete
        self.header_val = None
        self._lock_instrument = Lock_Instruments()
        if not hasattr(self, '_lock_extra'):
            # don't overwrite what is assigned in subclasses
            self._lock_extra = Lock_Extra()
        self._async_mode = 'wait'
        self._create_devs()
        self._async_local_data = threading.local()
        self._async_wait_check = True
        # The _async_statusLinecan be used in _async_detect to update the user
        # on the progress.
        self._async_statusLine = mainStatusLine.new(timed=True)
        self._last_force = time.time()
        self.init(full=True)
    def __del__(self):
        if not self._quiet_delete:
            print 'Destroying '+repr(self)
    def _async_select(self, devs):
        """ It receives a list of devices to help decide how to wait.
            The list entries can be in the form (dev, option_dict) or just dev
        """
        pass
    def _async_detect(self, max_time=.5): # subclasses should only call this if they need async_wait
        data = self._get_async_local_data()
        cur = time.time()
        left = data.async_wait - (cur - data.async_wait_start)
        if left <= 0.:
            return True
        if left <= max_time:
            sleep(left)
            return True
        sleep(max_time)
        return False
    @locked_calling
    def _async_trig(self): # subclasses can always call this
        self._async_statusLine.restart_time()
        data = self._get_async_local_data()
        if self._async_mode.startswith('wait'):
            self._async_wait_check_helper()
        data = self._get_async_local_data()
        data.async_wait_start = time.time()
        data.async_wait = self.async_wait.getcache()
    def _async_cleanup_after(self): # subclasses overides should call this. Called unconditionnaly after async/run_and_wait
        self._async_statusLine('')
    def _async_wait_check_helper(self):
        if self._async_wait_check and self.async_wait.getcache() == 0.:
            print self.perror('***** WARNING You should give a value for async_wait *****')
            self._async_wait_check = False
    @locked_calling
    def wait_after_trig(self):
        """
        waits until the triggered event is finished
        """
        try:
            ret = wait_on_event(self._async_detect)
        finally:
            self._async_cleanup_after()
        return ret
    # Always make sure that asyncThread run behaves in the same way
    @locked_calling
    def run_and_wait(self):
        """
        This initiate a trigger and waits for it to finish.
        """
        sleep(self.async_delay.getcache())
        try:
            self._async_trig()
            self.wait_after_trig()
        finally: # in case we were stopped because of KeyboardInterrupt or something else.
            self._async_cleanup_after()
    def _get_async_local_data(self):
        d = self._async_local_data
        try:
            d.async_level
        except AttributeError:
            d.async_list = []
            d.async_select_list = []
            d.async_list_init = []
            d.async_level = -1
            d.async_counter = 0
            d.async_task = None
            d.async_wait_start = 0.
            d.async_wait = 0.
        return d
    def _under_async_setup(self, task):
        self._async_running_task = task
    def _under_async(self):
        try:
            return self._async_running_task.is_alive()
        except AttributeError:
            return False
    def _get_async(self, async, obj, trig=False, **kwarg):
        # get_async should note change anything about the instrument until
        # we run the asyncThread. Should only change local thread data.
        # we are not protected by a lock until that.
        data = self._get_async_local_data()
        if async == -1: # we reset task
            if data.async_level > 1:
                data.async_task.cancel()
            data.async_level = -1
        if async != 3 and not (async == 2 and data.async_level == -1) and (
          async < data.async_level or async > data.async_level + 1):
            if data.async_level > 1:
                data.async_task.cancel()
            data.async_level = -1
            raise ValueError, 'Async in the wrong order. Reseting order. Try again..'
        if async == 0:  # setup async task
            if data.async_level == -1: # first time through
                data.async_list = []
                data.async_select_list = []
                data.async_list_init = [(self._async_select, (data.async_select_list, ), {})]
                delay = self.async_delay.getcache()
                data.async_task = asyncThread(data.async_list, self._lock_instrument, self._lock_extra, data.async_list_init, delay=delay)
                data.async_list_init.append((self._under_async_setup, (data.async_task,), {}))
                data.async_level = 0
            if trig:
                data.async_task.change_detect(self._async_detect)
                data.async_task.change_trig(self._async_trig)
                data.async_task.change_cleanup(self._async_cleanup_after)
            data.async_list.append((obj.get, kwarg))
            data.async_list.append((lambda: obj._last_filename, {}))
            data.async_select_list.append((obj, kwarg))
        elif async == 1:  # Start async task (only once)
            #print 'async', async, 'self', self, 'time', time.time()
            if data.async_level == 0: # First time through
                data.async_task.start()
                data.async_level = 1
        elif async == 2:  # Wait for task to finish
            #print 'async', async, 'self', self, 'time', time.time()
            if data.async_level == 1: # First time through (no need to wait for subsequent calls)
                wait_on_event(data.async_task)
                data.async_level = -1
            data.async_counter = 0
        elif async == 3: # get values
            #print 'async', async, 'self', self, 'time', time.time()
            #return obj.getcache()
            ret = data.async_task.results[data.async_counter]
            # Need to copy the _last_filename item because it is thread local
            self._last_filename = data.async_task.results[data.async_counter+1]
            data.async_counter += 2
            if data.async_counter == len(data.async_task.results):
                # delete task so that instrument can be deleted
                del data.async_task
                del data.async_list
                del data.async_select_list
                del data.async_list_init
                del self._async_running_task
            return ret
    def find_global_name(self):
        return _find_global_name(self)
    @classmethod
    def _cls_devwrap(cls, name):
        # Only use this if the class will be using only one instance
        # Otherwise multiple instances will collide (reuse same wrapper)
        setdev = getdev = checkdev = getformat = None
        for s in dir(cls):
            if s == '_'+name+'_setdev':
                setdev = getattr(cls, s)
            if s == '_'+name+'_getdev':
                getdev = getattr(cls, s)
            if s == '_'+name+'_checkdev':
                checkdev = getattr(cls, s)
            if s == '_'+name+'_getformat':
                getformat = getattr(cls, s)
        wd = cls_wrapDevice(setdev, getdev, checkdev, getformat)
        setattr(cls, name, wd)
    def _getdev_para_checked(self, *val):
        """
           This function should be called in a _getdev (devwrap with get_has_check option enabled)
           after the parameters have been
           checked for validity. When in CHECKING only mode, this will skip the rest of
           the function.
           you should call this with one parameter (passed to exception) or no parameters
           When a parameter is given, it will be used as the get value (and cached)
        """
        get_para_checked(*val)
    def _devwrap(self, name, **extrak):
        setdev = getdev = checkdev = getformat = None
        cls = type(self)
        for s in dir(self):
            if s == '_'+name+'_setdev':
                setdev = getattr(cls, s)
            if s == '_'+name+'_getdev':
                getdev = getattr(cls, s)
            if s == '_'+name+'_checkdev':
                checkdev = getattr(cls, s)
            if s == '_'+name+'_getformat':
                getformat = getattr(cls, s)
        wd = cls_wrapDevice(setdev, getdev, checkdev, getformat, **extrak)
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
            if once and obj.instr is not None:
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
            "In seconds. This is the delay before the trigger in async and run_and_wait.")
        self.async_wait = MemoryDevice(0., doc=
            "In seconds. This is the wait time after a trig for devices that don't use a real trig/detect sequence.")
        self._devwrap('header')
        self._create_devs_helper()
#    def _current_config(self, dev_obj, get_options):
#        pass
    def _conf_helper(self, *devnames, **kwarg):
        """
        The positional arguments are either device name strings or a dictionnary.
        When given a dictionnary, it will be shown as options.
        no_default: when True, skips adding some default entries (like idn)
                    It can only be a kwarg.
                    if not given, it behaves as True unless one of the options
                    is a dictionnary, the it behaves as False.
                    So for the default use of _conf_helper were only one the
                    calls includes the options dictionnary (and there is always
                    one), then there is no need to specify this values. The
                    default behavior is correct.
        """
        ret = []
        no_default = kwarg.pop('no_default', None)
        if len(kwarg):
            raise InvalidArgument('Invalid keyword arguments %s'%kwarg)
        if no_default is None:
            no_default = True
            for devname in devnames[::-1]: # start from the end
                if isinstance(devname, dict):
                    no_default = False
        # by default we will append
        add_to = lambda base, x: base.append(x)
        if isinstance(devnames[-1], dict):
            # unless last item is a dict then we insert before it
            add_to = lambda base, x: base.insert(-1, x)
        if not no_default:
            async_delay = self.async_delay.getcache()
            if async_delay != 0:
                devnames = list(devnames) # need to convert from tuple to a mutable list
                add_to(devnames, 'async_delay')
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
        if not no_default:
            add_to(ret, 'idn="%s"'%self.idn())
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
        # Your function should try and not interfere with another thread/process
        # already using the instrument (if it is allowed). So it should only set things
        # to values that should not change afterwards, or reset things that are protected
        # with locks
        pass
    # This allows instr.get() ... to be redirected to instr.alias.get()
    def __getattr__(self, name):
        if name in ['get', 'set', 'check', 'getcache', 'setcache', 'instr',
                    'name', 'getformat', 'getasync', 'getfullname']:
            if self.alias is None:
                raise AttributeError, self.perror('This instrument does not have an alias for {nm}', nm=name)
            return getattr(self.alias, name)
        else:
            raise AttributeError, self.perror('{nm} is not an attribute of this instrument', nm=name)
    def __call__(self):
        if self.alias is None:
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
        return "Undefined identification,X,0,0"
    def idn_split(self):
        idn = self.idn()
        parts = idn.split(',', 4) # There could be , in serial firmware revision
        # I also use lstrip because some device put a space after the comma.
        return dict(vendor=parts[0], model=parts[1].lstrip(), serial=parts[2].lstrip(), firmware=parts[3].lstrip())
    def _info(self):
        return self.find_global_name(), self.__class__.__name__, id(self)
    def __repr__(self):
        gn, cn, p = self._info()
        return '%s = <"%s" instrument at 0x%08x>'%(gn, cn, p)
    def perror(self, error_str='', **dic):
        dic.update(instr=self, gname=self.find_global_name())
        return ('{gname}: '+error_str).format(**dic)
    def _header_getdev(self):
        if self.header_val is None:
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
        kwarg['get_has_check'] = True
        BaseDevice.__init__(self, **kwarg)
        self.setcache(initval, nolock=True)
        self._setdev_p = True # needed to enable BaseDevice set in checking mode and also the check function
        self._getdev_p = True # needed to enable BaseDevice get in Checking mode
        if self.choices is not None and isinstance(self.choices, ChoiceBase):
            self.type = self.choices
        else:
            self.type = type(initval)
    def _getdev(self):
        self._get_para_checked()  # This is not necessary, since in CHECKING we will read the cache anyway
                                  # but place it here as an example and to test the code.
        return self.getcache()
    def _setdev(self, val):
        self.setcache(val)
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
    if t is None or (type(t) == type and issubclass(t, basestring)):
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
    if t is None or (type(t) == type and issubclass(t, basestring)):
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
        if setstr is None and getstr is None:
            raise ValueError, 'At least one of setstr or getstr needs to be specified'
        if setstr is not None and getstr is None and autoget == False:
            # we don't have get, so we remove autoinit to prevent problems with cache and force_get (iprint)
            autoinit = False
        if isinstance(choices, ChoiceBase) and str_type is None:
            str_type = choices
        if autoinit == True:
            autoinit = 10
            test = [ True for k,v in options.iteritems() if isinstance(v, BaseDevice)]
            if len(test):
                autoinit = 1
        BaseDevice.__init__(self, doc=doc, autoinit=autoinit, choices=choices, get_has_check=True, **kwarg)
        self._setdev_p = setstr
        if setstr is not None:
            fmtr = string.Formatter()
            val_present = False
            for txt, name, spec, conv in fmtr.parse(setstr):
                if name == 'val':
                    val_present = True
                    autoget = False
            if not val_present:
                self._setdev_p = setstr + self._autoset_val_str
        self._getdev_cache = False
        if getstr is None:
            if autoget:
                getstr = setstr+'?'
            elif get_cached_init is not None:
                self.setcache(get_cached_init, nolock=True)
                self._getdev_cache = True
                getstr = True
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
                    if lim is not None:
                        if basedev:
                            added += '        current choices (above device): '
                        else:
                            added += '        current choices: '
                        if isinstance(lim, tuple):
                            if lim[0] is None and lim[1] is None:
                                added += 'any value allowed'
                            else:
                                if lim[0] is not None:
                                    added += '%r <= '%lim[0]
                                added += '%s'%optname
                                if lim[1] is not None:
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
    def getcache(self, local=False):
        if local:
            return super(scpiDevice, self).getcache(local=True)
        #we need to check if we still are using the same options
        curr_cache = self._get_option_values()
        if self._option_cache != curr_cache:
            self.setcache(None)
        return super(scpiDevice, self).getcache()
    def _check_option(self, option, val):
        """
        Checks the option with value val
          If it is not an option, raise an KeyError
          If it is not within min/max or choices for this option, returns an error string
          If everything is fine, return None
        """
        if option not in self._options.keys():
            raise KeyError, self.perror('This device does not handle option "%s".'%option)
        lim = self._options_lim.get(option)
        # if no limits were given but this is a device, use the limits from the device.
        # TODO use dev.check (trap error)
        if lim is None and isinstance(self._options[option], BaseDevice):
            dev = self._options[option]
            lim = (dev.min, dev.max)
            if dev.choices is not None:
                lim = dev.choices
        return self._general_check(val, lims=lim, msg_src='Option "%s"'%option, str_return=True)
    def _combine_options(self, **kwarg):
        # get values from devices when needed.
        # The list of correct values could be a subset so push them to kwarg
        # for testing.
        # clean up kwarg by removing all None values
        kwarg = { k:v for k, v in kwarg.iteritems() if v is not None}
        for k, v in kwarg.iteritems():
            ck = self._check_option(k, v)
            if ck is not None:
                # in case of error, raise it
                raise InvalidArgument(ck)
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
                if ck is not None:
                    # There was an error, returned value not currently valid
                    # so return it instead of dictionnary
                    raise InvalidAutoArgument(ck)
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
    def _setdev(self, val):
        # We only reach here if self._setdev_p is not None
        val = self._tostr(val)
        options = self._check_cache['options']
        command = self._setdev_p
        command = command.format(val=val, **options)
        self.instr.write(command, **self._ask_write_opt)
    def _getdev(self, **kwarg):
        if self._getdev_cache:
            if kwarg == {}:
                return self.getcache()
            else:
                raise SyntaxError, self.perror('This device does not handle _getdev with optional arguments')
        try:
            options = self._combine_options(**kwarg)
        except InvalidAutoArgument:
            self.setcache(None)
            raise
        command = self._getdev_p
        command = command.format(**options)
        self._get_para_checked()
        ret = self.instr.ask(command, self._raw, **self._ask_write_opt)
        return self._fromstr(ret)
    def _checkdev(self, val, **kwarg):
        options = self._combine_options(**kwarg)
        # all kwarg have been tested
        self._check_cache['set_kwarg'] = {}
        self._check_cache['options'] = options
        super(scpiDevice, self)._checkdev(val)

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
        if autoinit is None:
            autoinit = dev._autoinit
        super(ReadvalDev,self).__init__(redir_async=dev, autoinit=autoinit, get_has_check=True, **kwarg)
        self._getdev_p = True
    def _getdev(self, **kwarg):
        self.instr._async_select([(self._slave_dev, kwarg)])
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
    if sep is None:
        return np.fromstring(block, t)
    return np.fromstring(block, t, sep=sep)

def _encode_block(v, sep=None):
    """
    Encodes the iterable v (array, list ...)
    into either a scpi binary block (including header) when sep=None (default)
    or into a sep separated string. Often sep is ',' for scpi
    """
    if sep is not None:
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
        if self._element_type is not None:
            lst = [_fromstr_helper(elem, self._element_type) for elem in lst]
        return lst
    def tostr(self, unquoted_l):
        if self._element_type is not None:
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
        if filter is not None:
            for x in self.keys:
                if filter(x) != x:
                    raise ValueError, "The input dict has at least one key where filter(key)!=key."
    def __contains__(self, x):
        return x in self.values
    def __call__(self, input_key):
        if self.filter is not None:
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
        if sub_type is None, it calls the to/from str of the selected value of
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
     sub_type=None (default) is the same as sub_type=str (i.e. no conversion).
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
            raise ValueError('Invalid number of parameters in class %s'%self.__class__.__name__)
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
        if fromdict is None:
            fromdict = kwarg
        ret = []
        for k, fmt in zip(self.field_names, self.fmts_type):
            v = fromdict[k]
            ret.append(_tostr_helper(v, fmt))
        ret = self.sep.join(ret)
        return ret
    def __contains__(self, x): # performs x in y; with y=Choice(). Used for check
        # Returns True if everything is fine.
        # Otherwise raise a ValueError, a KeyError or a KeyError_Choices (for missing values)
        xorig = x
        x = x.copy() # make sure we don't change incoming dict
        for k, fmt, lims in zip(self.field_names, self.fmts_type, self.fmts_lims):
            if isinstance(fmt, ChoiceMultipleDep):
                fmt.set_current_vals(xorig)
            try:
                val = x.pop(k) # generates KeyError if k not in x
            except KeyError:
                raise KeyError_Choices('key %s is missing'%k)
            _general_check(val, lims=lims, msg_src='key %s'%k)
        if x != {}:
            raise KeyError('The following keys in the dictionnary are incorrect: %r'%x.keys())
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
        if sub_type is None, it calls the to/from str of the selected value of
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
    Use this to gain access to a single/multiple element of a device returning a dictionary
    from ChoiceMultiple.
    """
    def __init__(self, subdevice, key, force_default=False, **kwarg):
        """
        This device and the subdevice need to be part of the same instrument
        (otherwise async will not work properly)
        Here we will only modify the value of key in dictionary.
        key can be a single value, or a list of values (in which case set/get will work
        on a list)
        force_default, set the default value of force used in check/set.
            It can be True, False or 'slave' which means to let the subdevice handle the
            insertion of the missing parameters
        """
        self._subdevice = subdevice
        self._sub_key = key
        self._force_default = force_default
        subtype = self._subdevice.type
        self._single_key = False
        if not isinstance(key, list):
            key = [key]
            self._single_key = True
            multi = False
        else:
            multi = key
        self._sub_key = key
        lims = []
        for k in key:
            if k not in subtype.field_names:
                raise IndexError, "The key '%s' is not present in the subdevice"%k
            lims.append( subtype.fmts_lims[subtype.field_names.index(k)] )
        self._sub_lims = lims
        setget = subdevice._setget
        autoinit = subdevice._autoinit
        trig = subdevice._trig
        get_has_check = True
        super(Dict_SubDevice, self).__init__(
                setget=setget, autoinit=autoinit, trig=trig, multi=multi, get_has_check=get_has_check, **kwarg)
        self._setdev_p = subdevice._setdev_p # needed to enable BaseDevice set in checking mode and also the check function
        self._getdev_p = True # needed to enable BaseDevice get in Checking mode
    def _get_docstring(self, added=''):
        # we don't include options starting with _
        if self._single_key:
            added = """
                    This device set/get the '%s' dictionnary element of a subdevice.
                    It uses the same options as that subdevice (%s)
                    """%(self._sub_key[0], self._subdevice)
        else:
            added = """
                    This device set/get the '%s' dictionnary elements of a subdevice.
                    It uses the same options as that subdevice (%s)
                    """%(self._sub_key, self._subdevice)
        return super(Dict_SubDevice, self)._get_docstring(added=added)
    def setcache(self, val, nolock=False):
        if nolock:
            # no handled because getcache can lock
            raise ValueError('Dict_SubDevice setcache does not handle nolock=True')
        vals = self._subdevice.getcache()
        if vals is not None:
            vals = vals.copy()
            if self._single_key:
                val = [val]
            if len(self._sub_key) != len(val):
                raise ValueError('This Dict_SubDevice requires %i elements'%len(self._sub_key))
            for k, v in zip(self._sub_key, val):
                vals[k] = v
        self._subdevice.setcache(vals)
    def getcache(self, local=False):
        if local:
            vals = self._subdevice.getcache(local=True)
        else:
            vals = self._subdevice.getcache()
        if vals is None:
            ret = None
        else:
            ret = [vals[k] for k in self._sub_key]
            if self._single_key:
                ret = ret[0]
        # Lets set the _cache variable anyway but it should never
        # be used. _cache should always be accessed with getcache and this will
        # bypass the value we set here.
        super(Dict_SubDevice, self).setcache(ret)
        return ret
    def _force_helper(self, force):
        if force is None:
            force = self._force_default
        return force
    def _checkdev(self, val, force=None, **kwarg):
        if self._single_key:
            val = [val]
        self._check_cache['cooked_val'] = val
        if len(self._sub_key) != len(val):
            raise ValueError(self.perror('This Dict_SubDevice requires %i elements'%len(self._sub_key)))
        # Lets check the parameters individually, in order to help the user with
        # a more descriptive message.
        for i, limv in enumerate(zip(self._sub_lims, val)):
            lim, v = limv
            msg_src = None
            if not self._single_key:
                msg_src = 'element %i'%i
            self._general_check(v, lims=lim, msg_src=msg_src)
        force = self._force_helper(force)
        allow = {True:True, False:'cache', 'slave':False}[force]
        self._check_cache['allow'] = allow
        op = self._check_cache['fnct_str']
        # otherwise, the check will be done by set in _setdev below
        if op == 'check':
            # we need to complete the test as much as possible
            vals = {k:v for k, v in zip(self._sub_key, val)}
            if allow:
                vals = self._subdevice._set_missing_dict_helper(vals, _allow=allow, **kwarg)
            self._subdevice.check(vals, **kwarg)
    def _getdev(self, **kwarg):
        vals = self._subdevice.get(**kwarg)
        if vals is None: # When checking and value not initialized
            ret = [0] * len(self._sub_key)
        else:
            ret = [vals[k] for k in self._sub_key]
        if self._single_key:
            ret = ret[0]
        return ret
    def _setdev(self, val, force=None, **kwarg):
        """
        force when True, it make sure to obtain the
         subdevice value with get.
              when False, it uses getcache.
        The default is in self._force_default
        """
        val = self._check_cache['cooked_val']
        if self._single_key:
            val = [val]
        allow = self._check_cache['allow']
        vals = {k:v for k, v in zip(self._sub_key, val)}
        if allow:
            vals = self._subdevice._set_missing_dict_helper(vals, _allow=allow, **kwarg)
        self._subdevice.set(vals, **kwarg)


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
            if not CHECKING():
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
        if not CHECKING():
            self._vi.unlock() # could produce VI_ERROR_SESN_NLOCKED
        else:
            if self._count < 1:
                raise visa_wrap.VisaIOError(visa_wrap.constants.VI_ERROR_SESN_NLOCKED)
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
          'USB0::0x0957::0x0118::MY49012345::0::INSTR'
          'USB::0x0957::0x0118::MY49012345'
    """
    def __init__(self, visa_addr, skip_id_test=False, quiet_delete=False, **kwarg):
        # need to initialize visa before calling BaseInstrument init
        # which might require access to device
        if isinstance(visa_addr, int):
            visa_addr = _normalize_gpib(visa_addr)
        self.visa_addr = visa_addr
        if not CHECKING():
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
        BaseInstrument.__init__(self, quiet_delete=quiet_delete)
        if not CHECKING():
            if not skip_id_test:
                idns = self.idn_split()
                if not instruments_registry.check_instr_id(self.__class__, idns['vendor'], idns['model'], idns['firmware']):
                    print 'WARNING: this particular instrument idn is not attached to this class: operations might misbehave.'
                    #print self.__class__, idns
    def __del__(self):
        #print 'Destroying '+repr(self)
        # no need to call self.visa.close()
        # because self.visa does that when it is deleted
        super(visaInstrument, self).__del__()
    # Do NOT enable locked_calling for read_status_byte, otherwise we get a hang
    # when instrument is on gpib using agilent visa. But do use lock visa
    # otherwise read_stb could fail because of lock held in another thread/process
    # The locked_calling problem is that the handler runs in a separate thread,
    # appart from the main locked thread (when using getasync)
    #@locked_calling
    def read_status_byte(self):
        # since on serial visa does the *stb? request for us
        # might as well be explicit and therefore handle the rw_wait properly
        # and do the locking.
        if CHECKING():
            return 0
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
        if CHECKING():
            return
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
        if CHECKING():
            return ''
        if raw:
            ret = self.visa.read_raw()
        else:
            ret = self.visa.read()
        self._last_rw_time.read_time = time.time()
        return ret
    @locked_calling
    def write(self, val):
        self._do_wr_wait()
        if not CHECKING():
            self.visa.write(val)
        else:
            if not isinstance(val, basestring):
                raise ValueError(self.perror('The write val is not a string.'))
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
    def idn_usb(self):
        """ Returns the usb names attached to the vendor/product ids and the serial number
            The return is a tuple (vendor, product, serial)
        """
        if CHECKING():
            return ('vendor', 'product', 'serial')
        vendor = self.visa.get_visa_attribute(visa_wrap.constants.VI_ATTR_MANF_NAME)
        product = self.visa.get_visa_attribute(visa_wrap.constants.VI_ATTR_MODEL_NAME)
        serial = self.visa.get_visa_attribute(visa_wrap.constants.VI_ATTR_USB_SERIAL_NUM)
        return (vendor, product, serial)
    @locked_calling
    def factory_reset(self):
        """
        This returns the instrument to a known state.
        Use CAREFULLY!
        """
        self.write('*RST')
        self.force_get()
    @locked_calling
    def clear(self):
        """
        This sends the *cls 488.2 command that should clear the status/event/
        errors (but not change the enable registers.)
        It also cleans up any buffered status byte.
        """
        self.write('*cls')
        #some device buffer status byte so clear them
        while self.read_status_byte()&0x40:
            pass
    @locked_calling
    def _dev_clear(self):
        """ This is the device clear instruction. For some devices it will
            clear the output buffers.
            (it should reset the interface state, but not change the state of
             status/event registers, errors states. See clear for that.)
        """
        if CHECKING():
            return
        self.visa.clear()
    @property
    def set_timeout(self):
        if CHECKING():
            return None
        timeout_ms = self.visa.timeout
        if timeout_ms is None:
            return None
        else:
            return timeout_ms/1000. # return in seconds
    @set_timeout.setter
    def set_timeout(self, seconds):
        if seconds is None:
            val = None
        else:
            val = int(seconds*1000.)
        if CHECKING():
            return
        self.visa.timeout = val
    def get_error(self):
        return self.ask('SYSTem:ERRor?')
    def _info(self):
        gn, cn, p = BaseInstrument._info(self)
        return gn, cn+'(%s)'%self.visa_addr, p
    @locked_calling
    def trigger(self):
        # This should produce the hardware GET on gpib
        #  Another option would be to use the *TRG 488.2 command
        if CHECKING():
            return
        self.visa.trigger()


#######################################################
##    VISA Async Instrument
#######################################################

# Note about async:
#  only one thread/process will have access to the device at a time
#   others are waiting for a lock
#  I only enable events (Queue or handlers) when I am about to use them
#  and disable them when I am done waiting.
#  wait_after_trig, run_and_wait and run in async should properly cleanup.
#  In case where the cleanup is not done properly, it would leave
#  some events/status in buffers and should be cleaned up on the
#  next run.

#   For agilent gpib, all device on bus will receive a handler/queue event.
#    I use the handler (only one should be enabled, If not then only one will have
#    the lock, the others will be waiting on read_status_byte: so only the important one
#    will actually reset the srq.)
#   For NI gpib, only the device that has SRQ on will receive the handler/queue event.
#    handlers are called within the gpib notify callback. All handlers
#    across all process are called. If one of the callback is slow, it only affects that process
#    thread. While in the callback, it does not add other events.
#    However queued events are only produced when waiting for the events,
#    they are not generated otherwise (for queued events, the driver does not setup
#    a notify callback). It is possible to loose events if the read_status
#    occurs between ibwait (which is every 1ms). However, again, the status read is protected
#    by the lock, and only one thread should be running anyway.
#    Note also that the auto serial poll is not jammed if the device holding the line SRQ is
#    not open. The driver will just keep autoprobing (during ibwait requests) and update the
#    device status so it can still find out if the device is requesting service.

class visaInstrumentAsync(visaInstrument):
    def __init__(self, visa_addr, poll=False):
        # poll can be True (for always polling) 'not_gpib' for polling for lan and usb but
        # use the regular technique for gpib
        # the _async_sre_flag should match an entry somewhere (like in init)
        self._async_sre_flag = 0x20 #=32 which is standard event status byte (contains OPC)
        self._async_last_status = 0
        self._async_last_status_time = 0
        self._async_last_esr = 0
        self._async_do_cleanup = False
        super(visaInstrumentAsync, self).__init__(visa_addr)
        self._async_mode = 'srq'
        if CHECKING():
            is_gpib = False
            is_agilent = False
            self._async_polling = True
            self._RQS_status = -1
            return
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
            if not CHECKING():
                self._handler_userval = self.visa.install_visa_handler(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                                  self._proxy_handler, 0)
        else:
            self._RQS_status = -1
            if self.visa.is_usb() and not self.visa.resource_manager.is_agilent():
                # For some weird reason, for National Instruments visalib on usb
                # the service request are queued by default until I enable/disable the service
                # just disabling does not work (says it is already disabled)
                # this with NI visa 14.0.0f0
                self.visa.enable_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                                        visa_wrap.constants.VI_QUEUE)
                self.visa.disable_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                                        visa_wrap.constants.VI_QUEUE)
    def __del__(self):
        if self._RQS_status != -1:
            # Not absolutely necessary, but lets be nice
            self.visa.disable_event(visa_wrap.constants.VI_ALL_ENABLED_EVENTS,
                                    visa_wrap.constants.VI_ALL_MECH)
            # only necessary to keep handlers list in sync
            # the actual handler is removed when the visa is deleted (vi closed)
            self.visa.uninstall_visa_handler(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                                  self._proxy_handler, self._handler_userval)
        super(visaInstrumentAsync, self).__del__()
    def init(self, full=False):
        # This clears the error state, and status/event flags?
        self.clear()
        if full:
            self.write('*ese 1;*sre 32') # OPC flag
    def _RQS_handler(self, vi, event_type, context, userHandle):
        # For Agilent visalib (auto serial poll is off):
        # Reading the status will clear the service request of this instrument
        # if the SRQ line is still active, another call to the handler will occur
        # after a short delay (30 ms I think) everytime a read_status_byte is done
        # on the bus (and SRQ is still active).
        # For agilent visa, the SRQ status is queried every 30ms. So
        # you we might have to wait that time after the hardware signal is active
        # before this handler is called.
        # Because of locking, this only succeeds if we are owning the lock
        # (so we are the ones waiting for data or nobody is.)
        # Remember that we are called when any instrument on the gpib bus
        # requests service (not only for this instrument)
        status = self.read_status_byte()
        #if status&0x40 and status & self._async_sre_flag:
        #if status & self._async_sre_flag:
        if status&0x40:
            self._RQS_status = status
            self._async_last_status = status
            self._async_last_status_time = time.time()
            #sleep(0.01) # give some time for other handlers to run
            self._RQS_done.set()
            #print 'Got it', vi
        return visa_wrap.constants.VI_SUCCESS
    def _get_esr(self):
        if CHECKING():
            return 0
        return int(self.ask('*esr?'))
    def  _async_detect_poll_func(self):
        if CHECKING():
            status = 0x40
        else:
            status = self.read_status_byte()
        if status & 0x40:
            self._async_last_status = status
            self._async_last_esr = self._get_esr()
            return True
        return False
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        """
        handles _async_mode of 'wait' (only wait delay), 'srq' (only detects srq)
                               'wait+srq' (wait followed by srq, so minimum of wait)
            all the options starting with wait will warn once if async_wait is 0.
            If you don't want the warning, replace 'wait' with '_wait' in the above strings.
        """
        if self._async_mode not in ['wait', '_wait', 'wait+srq', '_wait+srq', 'srq']:
            raise RuntimeError('Invalid async_mode selected')
        if self._async_mode in ['wait', '_wait']:
            return super(visaInstrumentAsync, self)._async_detect(max_time)
        ret = False
        if self._async_mode in ['wait+srq', '_wait+srq']:
            if not super(visaInstrumentAsync, self)._async_detect(max_time):
                return False
        if self._async_polling:
            if _retry_wait(self._async_detect_poll_func, max_time, delay=0.05):
                ret = True
        elif self._RQS_status == -1:
            # On National Instrument (NI) visa
            #  the timeout actually used seems to be 16*ceil(max_time*1000/16) in ms.
            wait_resp = self.visa.wait_on_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                                                int(max_time*1000), capture_timeout=True)
            # context in wait_resp will be closed automatically
            #if wait_resp.context is not None:
            if not wait_resp.timed_out:
                # only reset event flag. We know the bit that is set already (OPC)
                self._async_last_esr = self._get_esr()
                # only reset SRQ flag. We know the bit that is set already
                self._async_last_status = self.read_status_byte()
                ret = True
        else:
            if self._RQS_done.wait(max_time):
                #we assume status only had bit 0x20(event) and 0x40(RQS) set
                #and event only has OPC set
                # status has already been reset. Now reset event flag.
                self._async_last_esr = self._get_esr()
                self._RQS_done.clear() # so that we can detect the next SRQ if needed without  _doing async_trig (_async_trig_cleanup)
                ret = True
        return ret
    def _async_cleanup_after(self):
        super(visaInstrumentAsync, self)._async_cleanup_after()
        if self._async_do_cleanup:
            self.visa.disable_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ, visa_wrap.constants.VI_ALL_MECH)
            self._async_do_cleanup = False
    def _async_trigger_helper(self):
        self.write('INITiate;*OPC') # this assume trig_src is immediate for agilent multi
    def _async_trig_cleanup(self):
        if not self._async_polling:
            self._async_do_cleanup = True
            if self._RQS_status != -1:
                self.visa.enable_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                               visa_wrap.constants.VI_HNDLR)
            else:
                self.visa.enable_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                               visa_wrap.constants.VI_QUEUE)
        # We detect the end of acquisition using *OPC and status byte.
        if self._get_esr() & 0x01:
            print 'Unread event byte!'
        # A while loop is needed when National Instrument (NI) gpib autopoll is active
        # This is the default when using the NI Visa.
        while self.read_status_byte() & 0x40: # This is SRQ bit
            if self.visa.is_usb() and not self.visa.resource_manager.is_agilent():
                # National instruments visa buffers usb status bytes
                # so it is normal to hab left overs
                pass
            else:
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
        super(visaInstrumentAsync, self)._async_trig()
        if 'srq' in self._async_mode:
            self._async_trig_cleanup()
            self._async_trigger_helper()



def _normalize_usb(usb_resrc):
    usb_resrc = usb_resrc.upper() # make sure it is all upercase
    split = usb_resrc.split('::')
    if split[-1] == 'INSTR':
        del split[-1]
    if len(split) != 5:
        split.append('0')
    usbn, manuf, model, serial, interfaceN = split
    manuf = int(manuf, base=0)
    model = int(model, base=0)
    interfaceN = int(interfaceN, base=0)
    return 'USB0::0x%04X::0x%04X::%s::%i'%(manuf, model, serial, interfaceN), manuf, model

def _normalize_gpib(gpib_resrc):
    if isinstance(gpib_resrc, basestring):
        gpib_resrc = gpib_resrc.upper()
        split = gpib_resrc.split('::')
        bus = 0
        # split[0] is 'GPIB'
        if len(split[0]) > 4:
            bus = int(split[0][4:])
        if split[-1] == 'INSTR':
            del split[-1]
        prim = int(split[1])
        ret = 'GPIB%i::%i'%(bus, prim)
        if len(split) > 2:
            sec = int(split[2])
            ret += '::%i'%sec
        return ret+'::INSTR'
    elif isinstance(gpib_resrc, int):
        return 'GPIB0::%i::INSTR'%gpib_resrc
    else:
        raise TypeError('the address is not in an acceptable type.')


def _get_visa_idns(visa_addr, *args, **kwargs):
    vi = visaInstrument(visa_addr, *args, skip_id_test=True, quiet_delete=True, **kwargs)
    idns = vi.idn_split()
    del vi
    return idns


class visaAutoLoader(visaInstrument):
    """
    You can use this class to automatically select the proper class to load
    according to the idn returned by the instrument and the info in the registry.
    It returns another class (it is a factory class).
    Provide it at least a visa address.
    For usb devices it will try the usb registry first. Otherwise, like for all
    other device it will open it with visaInstrument first to read the idn then
    properly load it with the correct class.
    if skip_usb is set to True, then the usb search is skipped
    """
    def __new__(cls, visa_addr, skip_usb=False, *args, **kwargs):
        if not skip_usb and isinstance(visa_addr, basestring) and visa_addr.upper().startswith('USB'):
            usb, manuf, model = _normalize_usb(visa_addr)
            try:
                cls = instruments_registry.find_usb(manuf, model)
            except KeyError:
                pass
            else:
                print 'Autoloading(USB) using instruments class "%s"'%cls.__name__
                return cls(visa_addr, *args, **kwargs)
        idns = _get_visa_idns(visa_addr, *args, **kwargs)
        try:
            cls = instruments_registry.find_instr(idns['vendor'], idns['model'], idns['firmware'])
        except KeyError:
            idn = '{vendor},{model},{firmware}'.format(**idns)
            raise RuntimeError('Could not find an instrument for: %s (%s)'%(visa_addr, idn))
        else:
            print 'Autoloading using instruments class "%s"'%cls.__name__
            return cls(visa_addr, *args, **kwargs)
