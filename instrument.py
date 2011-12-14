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
import time
import threading
from PyQt4 import QtGui, QtCore

import traces

_globaldict = dict() # This is set in pynoise.py
CHECKING = False

def find_all_instruments():
    return visa.get_instruments_list()

def _repr_or_string(val):
    if isinstance(val, basestring):
        return val
    else:
        return repr(val)

def _writevec(file_obj, vals_list, pre_str=''):
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

def _write_dev(val, filename, format=format, first=False):
    append = format['append']
    bin = format['bin']
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
            filename = os.path.splitext(filename)[0]+bin
    f=open(filename, open_mode)
    header = _get_conf_header(format)
    if header and doheader: # if either is not None or not ''
        for h in header:
            f.write('#'+h+'\n')
    if append:
        _writevec(f, val)
    else:
        # we assume val is array like, except for bin where it can also be a string
        #  remember that float64 has 53 bits (~16 digits) of precision
        # for v of shape (100,2) this will output 2 columns and 100 lines
        if bin == '.npy':
            np.save(f, val)
        elif bin:
            if isinstance(val, basestring):
                f.write(val)
            else:
                val.tofile(f)
        else:
            np.savetxt(f, val, fmt='%.18g')
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
        super(type(self), self).__init__()
        self.daemon = True
        self._stop = False
        self._async_delay = delay
        self._async_trig = trig
        self._async_detect = detect
        self._operations = operations
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
            func(**kwarg)
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
        All devices provide get, set, check method
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
                  trig=False, delay=False):
        # instr and name updated by instrument's create_devs
        # doc is inserted before the above doc
        # setget makes us get the value after setting in
        #  this is usefull for instruments that could change the value
        #  under us.
        self.instr = None
        self.name = 'foo'
        self._cache = None
        self._lastget = None
        self._autoinit = autoinit
        self._setdev = None
        self._getdev = None
        self._setget = setget
        self._trig = trig
        self._delay = delay
        self.min = min
        self.max = max
        self.choices = choices
        if choices:
            doc+='-------------\n Possible value to set: %s'%repr(choices)
        self.__doc__ = doc+BaseDevice.__doc__
        self._format = dict(file=False, multi=multi, graph=[],
                            append=False, header=None, bin=False,
                            options={}, obj=self)
    # for cache consistency
    #    get should return the same thing set uses
    def set(self, val, **kwarg):
        self.check(val, **kwarg)
        if not CHECKING:
            self.setdev(val, **kwarg)
            if self._setget:
                val = self.get(**kwarg)
        elif self._setdev == None:
            raise NotImplementedError, self.perror('This device does not handle setdev')
        # only change cache after succesfull setdev
        self._cache = val
    def get(self, **kwarg):
        if not CHECKING:
            format = self.getformat(**kwarg)
            if kwarg.get('filename', False) and not format['file']:
                #we did not ask for a filename but got one.
                #since getdev probably does not understand filename
                #we handle it here
                filename = kwarg.pop('filename')
                ret = self.getdev(**kwarg)
                _write_dev(ret, filename, format=format)
                self._lastget = ret
                ret = None
            else:
                ret = self.getdev(**kwarg)
        elif self._getdev == None:
            raise NotImplementedError, self.perror('This device does not handle getdev')
        else:
            ret = self._cache
        self._cache = ret
        return ret
    def getcache(self):
        if self._cache==None and self._autoinit:
           return self.get()
        return self._cache
    def getasync(self, async, **kwarg):
        return self.instr._get_async(async, self,
                           trig=self._trig, delay=self._delay, **kwarg)
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
    def setdev(self, val):
        raise NotImplementedError, self.perror('This device does not handle setdev')
    def getdev(self):
        raise NotImplementedError, self.perror('This device does not handle getdev')
    def check(self, val):
        if self._setdev == None:
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
               err='invalid MIN'
           if not maxtest:
               err='invalid MAX'
           if not choicetest:
               err='invalid value(%s): use one of %s'%(val, repr(self.choices))
           raise ValueError, self.perror('Failed check: '+err)
        #return state
    def getformat(self, filename=None, **kwarg): # we need to absorb any filename argument
        self._format['options'] = kwarg
        return self._format

class wrapDevice(BaseDevice):
    def __init__(self, setdev=None, getdev=None, check=None, getformat=None, **extrak):
        BaseDevice.__init__(self, **extrak)
        # the methods are unbounded methods.
        self._setdev = setdev
        self._getdev = getdev
        self._check  = check
        self._getformat  = getformat
    def setdev(self, val, **kwarg):
        if self._setdev != None:
            self._setdev(val, **kwarg)
        else:
            raise NotImplementedError, self.perror('This device does not handle setdev')
    def getdev(self, **kwarg):
        if self._getdev != None:
            return self._getdev(**kwarg)
        else:
            raise NotImplementedError, self.perror('This device does not handle getdev')
    def check(self, val, **kwarg):
        if self._check != None:
            self._check(val, **kwarg)
        else:
            super(type(self), self).check(val)
    def getformat(self, **kwarg):
        if self._getformat != None:
            return self._getformat(**kwarg)
        else:
            return super(type(self), self).getformat(**kwarg)

class cls_wrapDevice(BaseDevice):
    def __init__(self, setdev=None, getdev=None, check=None, getformat=None, **extrak):
        BaseDevice.__init__(self, **extrak)
        # the methods are unbounded methods.
        self._setdev = setdev
        self._getdev = getdev
        self._check  = check
        self._getformat  = getformat
    def setdev(self, val, **kwarg):
        if self._setdev != None:
            self._setdev(self.instr, val, **kwarg)
        else:
            raise NotImplementedError, self.perror('This device does not handle setdev')
    def getdev(self, **kwarg):
        if self._getdev != None:
            return self._getdev(self.instr, **kwarg)
        else:
            raise NotImplementedError, self.perror('This device does not handle getdev')
    def check(self, val):
        if self._check != None:
            self._check(self.instr, val)
        else:
            super(type(self), self).check(val)
    def getformat(self, **kwarg):
        if self._getformat != None:
            return self._getformat(self.instr, **kwarg)
        else:
            return super(type(self), self).getformat(self.instr, **kwarg)

# Using this metaclass, the class method
# add_class_devs will be executed at class creation.
# Hence added devices will be part of the class and will
# allow the inst.dev=2 syntax 
#   (Since for the device __set__ to work requires the
#    object to be part of the class, not the instance)
class MetaClassInit(type):
    def __init__(cls, name, bases, dct):
        cls.add_class_devs()
        type.__init__(cls, name, bases, dct)
#TODO: maybe override classmethod, automatically call add_class_devs for all devices...

class BaseInstrument(object):
    __metaclass__ = MetaClassInit
    alias = None
    def __init__(self):
        self.header_val = None
        self.create_devs()
        self._async_list = []
        self._async_level = -1
        self.async_delay = 0.
        self._async_task = None
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
            raise ValueError, 'Async in the wrong order'
        if async == 0:  # setup async task
            if self._async_level == -1: # first time through
                self._async_list = []
                self._async_task = asyncThread(self._async_list)
                self._async_level = 0
            delay = kwarg.pop('delay', False)
            if delay:
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
        elif async == 3: # get values
            return obj.getcache()
    def find_global_name(self):
        dic = _globaldict
        try:
            return [k for k,v in dic.iteritems() if v is self and k[0]!='_'][0]
        except IndexError:
            return "name_not_found"
    @classmethod
    def cls_devwrap(cls, name):
        # Only use this if the class will be using only one instance
        # Otherwise multiple instances will collide (reuse same wrapper)
        setdev = getdev = check = getformat = None
        for s in dir(cls):
           if s == name+'_setdev':
              setdev = getattr(cls, s)
           if s == name+'_getdev':
              getdev = getattr(cls, s)
           if s == name+'_check':
              check = getattr(cls, s)
           if s == name+'_getformat':
              check = getattr(cls, s)
        wd = cls_wrapDevice(setdev, getdev, check, getformat)
        setattr(cls, name, wd)
    def devwrap(self, name, **extrak):
        setdev = getdev = check = getformat = None
        for s in dir(self):
           if s == name+'_setdev':
              setdev = getattr(self, s)
           if s == name+'_getdev':
              getdev = getattr(self, s)
           if s == name+'_check':
              check = getattr(self, s)
           if s == name+'_getformat':
              getformat = getattr(self, s)
        wd = wrapDevice(setdev, getdev, check, getformat, **extrak)
        setattr(self, name, wd)
    def devs_iter(self):
        for devname in dir(self):
           obj = getattr(self, devname)
           if devname != 'alias' and isinstance(obj, BaseDevice):
               yield devname, obj
    def create_devs(self):
        # devices need to be created here (not at class level)
        # because we want each instrument instance to use its own
        # device instance (otherwise they would share the instance data)
        #
        # if instrument had a _current_config function and the device does
        # not specify anything for header in its format string than
        # we assign it.
        self.devwrap('header')
        if hasattr(self, '_current_config'):
            conf = self._current_config
        else:
            conf = None
        for devname, obj in self.devs_iter():
            obj.instr = self
            obj.name = devname
            if conf and not obj._format['header']:
                obj._format['header'] = conf
#    def _current_config(self, dev_obj, get_options):
#        pass
    def _conf_helper(self, *devnames):
        ret = []
        for devname in devnames:
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
        if name in ['get', 'set', 'check', 'getcache', 'setcache', 'instr', 'name', 'getformat', 'getasync']:
            if self.alias == None:
                raise AttributeError, self.perror('This instrument does not have an alias for {nm}', nm=name)
            return getattr(self.alias, name)
        else:
            raise AttributeError, self.perror('{nm} is not an attribute of this instrument', nm=name)
    def __call__(self):
        if self.alias == None:
            raise TypeError, self.perror('This instrument does not have an alias for call')
        return self.alias()
    def iprint(self, force=False):
        ret = ''
        for s, obj in self.devs_iter():
            if self.alias == obj:
                ret += 'alias = '
            if force and obj._autoinit:
                val = obj.get()
            else:
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
    def header_getdev(self):
        if self.header_val == None:
            return self.find_global_name()
        else:
            return self.header_val
    def header_setdev(self, val):
        self.header_val = val
    @classmethod
    def add_class_devs(cls):
        pass
    def trigger():
        pass

class MemoryDevice(BaseDevice):
    def __init__(self, initval=None, **extrak):
        BaseDevice.__init__(self, **extrak)
        self._cache = initval
        self._setdev = True # needed to enable BaseDevice Check
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
        self._setdev = setstr
        if getstr == None and autoget:
            getstr = setstr+'?'
        self._getdev = getstr
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
        return t._tostr(val)
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
    def setdev(self, val):
        if self._setdev == None:
           raise NotImplementedError, self.perror('This device does not handle setdev')
        val = self._tostr(val)
        self.instr.write(self._setdev+' '+val)
    def getdev(self):
        if self._getdev == None:
           raise NotImplementedError, self.perror('This device does not handle getdev')
        ret = self.instr.ask(self._getdev)
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
_decode_uint8_bin = functools.partial(_decode_block, t=np.uint8)
_decode_uint16_bin = functools.partial(_decode_block, t=np.uint16)

class ChoiceStrings(object):
    """
       Initialize the class with a list of strings
        s=ChoiceStrings('Aa', 'Bb', ..)
       then 'A' in s  or 'aa' in s will return True
       irrespective of capitalization.
       The elements need to have the following format:
          ABCdef
       where: ABC is known has the short name and
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
        self.short = [v.rstrip(string.ascii_lowercase).lower() for v in values]
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
    def _tostr(self, input_choice):
        # this is called by dev._tostr to convert a choice to the format needed by instrument
        if self.quotes:
            return '"%s"'%input_choice
        return input_choice  # no need to change. Already a proper string.
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
    def _idn(self):
        return self.ask('*idn?')
    def _clear(self):
        self.visa.clear()
    @property
    def _set_timeout(self):
        return self.visa.timeout
    @_set_timeout.setter
    def _set_timeout(self, seconds):
        self.visa.timeout = seconds
    def _get_error(self):
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
    def create_devs(self):
        #self.level_2 = wrapDevice(self.levelsetdev, self.levelgetdev, self.levelcheck)
        self.function = scpiDevice(':source:function', choices=ChoiceStrings('VOLT', 'CURRent')) # use 'voltage' or 'current'
        # voltage or current means to add V or A in the string (possibly with multiplier)
        self.range = scpiDevice(':source:range', str_type=float, setget=True) # can be a voltage, current, MAX, MIN, UP or DOWN
        #self.level = scpiDevice(':source:level') # can be a voltage, current, MAX, MIN
        self.voltlim = scpiDevice(':source:protection:voltage', str_type=float, setget=True) #voltage, MIN or MAX
        self.currentlim = scpiDevice(':source:protection:current', str_type=float, setget=True) #current, MIN or MAX
        self.devwrap('level', setget=True)
        self.alias = self.level
        # This needs to be last to complete creation
        super(type(self),self).create_devs()
    def level_check(self, val):
        rnge = 1.2*self.range.getcache()
        if self.function.getcache()=='CURR' and rnge>.2:
            rnge = .2
        if abs(val) > rnge:
           raise ValueError, self.perror('level is invalid')
    def level_getdev(self):
        return float(self.ask(':source:level?'))
    def level_setdev(self, val):
        # used %.6e instead of repr
        # repr sometimes sends 0.010999999999999999
        # which the yokogawa understands as 0.010 instead of 0.011
        self.write(':source:level %.6e'%val)

class sr830_lia(visaInstrument):
    _snap_type = {1:'x', 2:'y', 3:'R', 4:'theta', 5:'Aux_in1', 6:'Aux_in2',
                  7:'Aux_in3', 8:'Aux_in4', 9:'Ref_Freq', 10:'Ch1', 11:'Ch2'}
    def init(self, full=False):
        # This empties the instrument buffers
        self._clear()
    def _check_snapsel(self,sel):
        if not (2 <= len(sel) <= 6):
            raise ValueError, 'snap sel needs at least 2 and no more thant 6 elements'
    def snap_getdev(self, sel=[1,2]):
        # sel must be a list
        self._check_snapsel(sel)
        sel = map(str, sel)
        return _decode_float64(self.ask('snap? '+string.join(sel,sep=',')))
    def snap_getformat(self, sel=[1,2], filename=None):
        self._check_snapsel(sel)
        headers = [ self._snap_type[i] for i in sel]
        d = self.snap._format
        d.update(multi=headers, graph=range(len(sel)))
        return BaseDevice.getformat(self.snap, sel=sel)
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('freq', 'sens', 'srclvl', 'harm', 'phase', 'timeconstant')
    def create_devs(self):
        self.freq = scpiDevice('freq', str_type=float)
        self.sens = scpiDevice('sens', str_type=int)
        self.oauxi1 = scpiDevice(getstr='oaux? 1', str_type=float)
        self.srclvl = scpiDevice('slvl', str_type=float, min=0.004, max=5.)
        self.harm = scpiDevice('harm', str_type=int)
        self.phase = scpiDevice('phas', str_type=float)
        self.timeconstant = scpiDevice('oflt', str_type=int)
        self.x = scpiDevice(getstr='outp? 1', str_type=float)
        self.y = scpiDevice(getstr='outp? 2', str_type=float)
        self.r = scpiDevice(getstr='outp? 3', str_type=float)
        self.theta = scpiDevice(getstr='outp? 4', str_type=float)
        self.xy = scpiDevice(getstr='snap? 1,2')
        self.devwrap('snap')
        self.alias = self.snap
        # This needs to be last to complete creation
        super(type(self),self).create_devs()

class sr384_rf(visaInstrument):
    # This instruments needs to be on local state or to pass through local state
    #  after a local_lockout to actually turn off the local key.
    # allowed units: amp: dBm, rms, Vpp; freq: GHz, MHz, kHz, Hz; Time: ns, us, ms, s
    def init(self, full=False):
        # This clears the error state
        self.write('*cls')
    def create_devs(self):
        self.freq = scpiDevice('freq',str_type=float)
        self.offset_low = scpiDevice('ofsl',str_type=float) #volts
        self.amp_lf_dbm = scpiDevice('ampl',str_type=float)
        self.amp_rf_dbm = scpiDevice('ampr',str_type=float)
        self.amp_hf_dbm = scpiDevice('amph',str_type=float) # doubler
        self.en_lf = scpiDevice('enbl', str_type=bool) # 0 is off, 1 is on, read value depends on freq
        self.en_rf = scpiDevice('enbr', str_type=bool) # 0 is off, 1 is on, read value depends on freq
        self.en_hf = scpiDevice('enbh', str_type=bool) # 0 is off, 1 is on, read value depends on freq
        self.phase = scpiDevice('phas',str_type=float, min=-360, max=360) # deg, only change by 360
        self.mod_en = scpiDevice('modl', str_type=bool) # 0 is off, 1 is on
        # This needs to be last to complete creation
        super(type(self),self).create_devs()

class agilent_rf_33522A(visaInstrument):
    def create_devs(self):
        # voltage unit depends on front panel/remote selection (sourc1:voltage:unit) vpp, vrms, dbm
        self.ampl1 = scpiDevice('SOUR1:VOLT', str_type=float, min=0.001, max=10)
        self.freq1 = scpiDevice('SOUR1:FREQ', str_type=float, min=1e-6, max=30e6)
        self.offset1 = scpiDevice('SOUR1:VOLT:OFFS', str_type=float, min=-5, max=5)
        self.phase1 = scpiDevice('SOURce1:PHASe', str_type=float, min=-360, max=360) # in deg unless changed by unit:angle
        self.mode1 = scpiDevice('SOUR1:FUNC') # SIN, SQU, RAMP, PULS, PRBS, NOIS, ARB, DC
        self.out_en1 = scpiDevice('OUTPut1', str_type=bool) #OFF,0 or ON,1
        self.ampl2 = scpiDevice('SOUR2:VOLT', str_type=float, min=0.001, max=10)
        self.freq2 = scpiDevice('SOUR2:FREQ', str_type=float, min=1e-6, max=30e6)
        self.phase2 = scpiDevice('SOURce2:PHASe', str_type=float, min=-360, max=360) # in deg unless changed by unit:angle
        self.offset2 = scpiDevice('SOUR2:VOLT:OFFS', str_type=float, min=-5, max=5)
        self.mode2 = scpiDevice('SOUR2:FUNC') # SIN, SQU, RAMP, PULS, PRBS, NOIS, ARB, DC
        self.out_en2 = scpiDevice('OUTPut2', str_type=bool) #OFF,0 or ON,1
        self.alias = self.freq1
        # This needs to be last to complete creation
        super(type(self),self).create_devs()
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
        self.aperture.set(width)
        self.sample_count.set(count)
    def create_devs(self):
        # This needs to be last to complete creation
        # fetch and read return sample_count*trig_count data values (comma sep)
        ch = ChoiceStrings(
          'CURRent:AC', 'VOLTage:AC', 'CAPacitance', 'CONTinuity', 'CURRent', 'VOLTage',
          'DIODe', 'FREQuency', 'PERiod', 'RESistance', 'FRESistance', 'TEMPerature', quotes=True)
        self.mode = scpiDevice('FUNC', str_type=ch, choices=ch)
        self.readval = scpiDevice(getstr='READ?',str_type=float) # similar to INItiate followed by FETCh.
        # TODO make readval redirect to fetchval for async mode
        # handle avg, stats when in multiple points mode.
        self.fetchval = scpiDevice(getstr='FETCh?',str_type=_decode_float64, autoinit=False, trig=True) #You can't ask for fetch after an aperture change. You need to read some data first.
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
        super(type(self),self).create_devs()
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
    def create_devs(self):
        self.crdg = scpiDevice(getstr='CRDG?', str_type=float)
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
        super(type(self),self).create_devs()

class infiniiVision_3000(visaInstrument):
    def create_devs(self):
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
        super(type(self),self).create_devs()

class agilent_EXA(visaInstrument):
    def init(self, full=False):
        self.write(':format REAL,64')
        self.write(':format:border swap')
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('bandwidth', 'freq_start', 'freq_stop','average_count')
    def create_devs(self):
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
        super(type(self),self).create_devs()

class agilent_PNAL(visaInstrument):
    def init(self, full=False):
        self.write(':format REAL,64')
        self.write(':format:border swap')
    def create_devs(self):
        self.bandwith = scpiDevice(':sense1:bandwidth',str_type=float)
        self.average_count = scpiDevice(getstr=':sense:average:count?',str_type=int)
        self.freq_start = scpiDevice(':sense:freq:start', str_type=float, min=10e6, max=40e9)
        self.freq_stop = scpiDevice(':sense:freq:stop', str_type=float, min=10e6, max=40e9)
        self.x1 = scpiDevice(getstr=':sense1:X?')
        self.curx1 = scpiDevice(getstr=':calc1:X?', autoinit=False)
        self.cur_data = scpiDevice(getstr=':calc1:data? fdata', autoinit=False)
        self.cur_cplxdata = scpiDevice(getstr=':calc1:data? sdata', autoinit=False)
        self.select_m = scpiDevice(':calc1:par:mnum')
        self.select_i = scpiDevice(':calc1:par:sel')
        self.select_w = scpiDevice(getstr=':syst:meas1:window?')
        self.select_t = scpiDevice(getstr=':syst:meas1:trace?')
        # This needs to be last to complete creation
        super(type(self),self).create_devs()

class dummy(BaseInstrument):
    def init(self, full=False):
        self.incr_val = 0
        self.wait = .1
    def incr_getdev(self):
        ret = self.incr_val
        self.incr_val += 1
        traces.wait(self.wait)
        return ret
    def incr_setdev(self, val):
        self.incr_val = val
    #incr3 = wrapDevice(incr_setdev, incr_getdev)
    #incr2 = wrapDevice(getdev=incr_getdev)
    def rand_getdev(self):
        traces.wait(self.wait)
        return random.normalvariate(0,1.)
    def create_devs(self):
        self.volt = MemoryDevice(0., doc='This is a memory voltage, a float')
        self.current = MemoryDevice(1., doc='This is a memory current, a float')
        self.other = MemoryDevice(autoinit=False, doc='This takes a boolean')
        #self.freq = scpiDevice('freq', str_type=float)
        self.devwrap('rand', doc='This returns a random value. There is not set.', delay=True)
        self.devwrap('incr')
        self.alias = self.current
        # This needs to be last to complete creation
        super(type(self),self).create_devs()

class ScalingDevice(BaseDevice):
    """
       This class provides a wrapper around a device.
       On reading, it returns basedev.get()*scale_factor + offset
       On writing it will write basedev.set((val - offset)/scale_factor)
       setget option does nothing here.
    """
    def __init__(self, basedev, scale_factor, offset=0., doc='', autoinit=None, **extrak):
        if isinstance(basedev, BaseInstrument):
            basedev = basedev.alias
        self._basedev = basedev
        self._scale = float(scale_factor)
        self._offset = offset
        doc+= self.__doc__+doc+'basedev=%s\nscale_factor=%g (initial)\noffset=%g'%(
               repr(basedev), scale_factor, offset)
        if autoinit == None:
            autoinit = basedev._autoinit
        BaseDevice.__init__(self, autoinit=autoinit, doc=doc, **extrak)
        self.instr = basedev.instr
        self.name = basedev.name
        self._format['multi'] = ['scale', 'raw']
        self._format['graph'] = [0]
        self._format['header'] = self._current_config
    def _current_config(self, dev_obj=None, options={}):
        ret = ['Scaling:: fact=%r offset=%r'%(self._scale, self._offset)]
        frmt = self._basedev.getformat()
        base = _get_conf_header_util(frmt['header'], dev_obj, options)
        if base != None:
            ret.extend(base)
        return ret
    def get(self):
        raw = self._basedev.get()
        val = raw * self._scale + self._offset
        self._cache = val, raw
        return val, raw
    def set(self, val):
        self._basedev.set((val - self._offset) / self._scale)
        # read basedev cache, in case the values is changed by setget mode.
        self._cache = self._basedev.getcache() * self._scale + self._offset
    def check(self, val):
        self._basedev.check((val - self._offset) / self._scale)

