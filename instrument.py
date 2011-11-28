# -*- coding: utf-8 -*-
#

try:
  import visa
except ImportError:
  print 'Error importing visa. You will have reduced functionality.'
import numpy as np
import random
import time
import traces

_globaldict = dict() # This is set in pynoise.py

class BaseDevice(object):
    def __init__(self):
        # instr and name updated by instrument's create_devs
        self.instr = None
        self.name = 'foo'
        self._cache = None
    # for cache consistency
    #    get should return the same thing set uses
    def set(self, val):
        self.setdev(val)
        # only change cache after succesfull setdev
        self._cache = val
    def get(self):
        ret = self.getdev()
        self._cache = ret
        return ret
    def getcache(self):
        if self._cache==None:
           return self.get()
        return self._cache
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

    # Implement these in a derived class
    def setdev(self, val):
        raise NotImplementedError
    def getdev(self):
        raise NotImplementedError
    def check(self, val):
        pass

class wrapDevice(BaseDevice):
    def __init__(self, setdev=None, getdev=None, check=None):
        BaseDevice.__init__(self)
        # the methods are unbounded methods.
        self._setdev = setdev
        self._getdev = getdev
        self._check  = check
    def setdev(self, val):
        self._setdev(self.instr, val)
    def getdev(self):
        return self._getdev(self.instr)
    def check(self, val):
        self._check(self.instr, val)


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
        self.init(full=True)
    def find_global_name(self):
        dic = _globaldict
        try:
            return [k for k,v in dic.iteritems() if v == self and k[0]!='_'][0]
        except IndexError:
            return "name_not_found"
    @classmethod
    def devwrap(cls, name):
        setdev = getdev = check = None
        for s in dir(cls):
           if s == name+'_setdev':
              setdev = getattr(cls, s)
           if s == name+'_getdev':
              getdev = getattr(cls, s)
           if s == name+'_check':
              check = getattr(cls, s)
        wd = wrapDevice(setdev, getdev, check)
        setattr(cls, name, wd)
    def devs_iter(self):
        for devname in dir(self):
           obj = getattr(self, devname)
           if devname != 'alias' and isinstance(obj, BaseDevice):
               yield devname, obj
    def create_devs(self):
        for devname, obj in self.devs_iter():
            obj.instr = self
            obj.name = devname
    def read(self):
        raise NotImplementedError
    def write(self, val):
        raise NotImplementedError
    def ask(self, question):
        raise NotImplementedError
    def init(self, full=False):
        """ Do instrument initialization (full=True)/reset (full=False) here """
        pass
    # This allows instr.get() ... to be redirected to instr.alias.get()
    def __getattr__(self, name):
        if self.alias == None:
            raise AttributeError
        if name in ['get', 'set', 'check', 'getcache', 'setcache', 'instr', 'name']:
            return getattr(self.alias, name)
    def __call__(self):
        if self.alias == None:
            raise TypeError
        return self.alias()
    def iprint(self):
        ret = ''
        for s, obj in self.devs_iter():
            if self.alias == obj:
                ret += 'alias = '
            ret += s+" = "+repr(obj.getcache())+"\n"
        return ret
    def _info(self):
        return self.find_global_name(), self.__class__.__name__, id(self)
    def __repr__(self):
        gn, cn, p = self._info()
        return '%s = <"%s" instrument at 0x%08x>'%(gn, cn, p)
    def header_getdev(self):
        if self.header_val == None:
            return self.find_global_name()
        else:
            return self.header_val
    def header_setdev(self, val):
        self.header_val = val
    @classmethod
    def add_class_devs(cls):
        cls.devwrap('header')
    def trig():
        pass

class MemoryDevice(BaseDevice):
    def __init__(self, initval=None):
        BaseDevice.__init__(self)
        self._cache = initval
    def get(self):
        return self._cache
    def set(self, val):
        self._cache = val
    # Can override check member

class scpiDevice(BaseDevice):
    def __init__(self, setstr=None, getstr=None, autoget=True, str_type=None, min=None, max=None, doc=None):
        """
           str_type can be float, int, None
        """
        BaseDevice.__init__(self)
        if setstr == None and getstr == None:
           raise ValueError
        self.setstr = setstr
        if getstr == None and autoget:
            getstr = setstr+'?'
        self.getstr = getstr
        self.type = str_type
        self.min = min
        self.max = max
        self.__doc__ = doc
    def setdev(self, val):
        if self.setstr == None:
           raise NotImplementedError
        if self.type != None:
           # use repr instead of str to keep full precision
           val = repr(val)
        self.instr.write(self.setstr+' '+val)
    def getdev(self):
        if self.getstr == None:
           raise NotImplementedError
        ret = self.instr.ask(self.getstr)
        if self.type != None:
           # here we assume self.type can convert a string
           ret = self.type(ret)
        return ret
    def check(self, val):
        if self.setstr == None:
           raise NotImplementedError
        if self.type == float or self.type == int:
           if self.min != None:
              mintest = val >= self.min
           else:
              mintest = True
           if self.max != None:
              maxtest = val <= self.max
           else:
              maxtest = True
        state = mintest and maxtest
        if state == False:
           raise ValueError
        #return state

def _decodeblock(str):
   if str[0]!='#':
       return
   nh = int(str[1])
   nbytes = int(str[2:2+nh])
   blk = str[2+nh:]
   if len(blk) != nbytes:
       print "Missing data"
       return
   # we assume real 64, swap
   data = np.fromstring(blk,'float64')
   return data

def _decode(str):
   if str[0]=='#':
      v = _decodeblock(str)
   else:
      v = np.fromstring(str, 'float64', sep=',')
   return v


class visaInstrument(BaseInstrument):
    def __init__(self, visa_addr):
        # need to initialize visa before calling BaseInstrument init
        # which might require access to device
        if type(visa_addr)==int:
            visa_addr= 'GPIB0::%i::INSTR'%visa_addr
        self.visa_addr = visa_addr
        self.visa = visa.instrument(visa_addr)
        BaseInstrument.__init__(self)
    #######
    ## Could implement some locking here ....
    ## for read, write, ask
    #######
    def read(self):
        return self.visa.read()
    def write(self, val):
        self.visa.write(val)
    def ask(self, question):
        return self.visa.ask(question)
    def idn(self):
        return self.ask('*idn?')
    def _info(self):
        gn, cn, p = BaseInstrument._info()
        return gn, cn+'(%s)'%self.visa_addr, p

# use like:
# yo1 = yokogawa('GPIB0::12::INSTR')
#   or
# yo1 = yokogawa('GPIB::12')
#   or
# yo1 = yokogawa(12)
#'USB0::0x0957::0x0118::MY49001395::0::INSTR'
class yokogawa(visaInstrument):
    # case insensitive
    multipliers = ['YO', 'ZE', 'EX', 'PE', 'T', 'G', 'MA', 'K', 'M', 'U', 'N', 'P',
                   'F', 'A', 'Z', 'Y']
    multvals    = [1e24, 1e21, 1e18, 1e15, 1e12, 1e9, 1e6, 1e3, 1e-3, 1e-6, 1e-9, 1e-12,
                   1e-15, 1e-18, 1e-21, 1e-24]
    function = scpiDevice(':source:function') # use 'voltage' or 'current'
    # voltage or current means to add V or A in the string (possibly with multiplier)
    range = scpiDevice(':source:range', str_type=float) # can be a voltage, current, MAX, MIN, UP or DOWN
    level = scpiDevice(':source:level') # can be a voltage, current, MAX, MIN
    voltlim = scpiDevice(':source:protection:voltage', str_type=float) #voltage, MIN or MAX
    currentlim = scpiDevice(':source:protection:current', str_type=float) #current, MIN or MAX
    def init(self, full=False):
        # clear event register, extended event register and error queue
        self.write('*cls')
    def create_devs(self):
        #self.level_2 = wrapDevice(self.levelsetdev, self.levelgetdev, self.levelcheck)
        self.devwrap('level')
        self.alias = self.level
    def level_check(self, val):
        rnge = 1.2*self.range.getcache()
        if self.function.getcache()=='CURR' and rnge>.2:
            rnge = .2
        if abs(val) > rnge:
           raise ValueError
    def level_getdev(self):
        return float(self.ask(':source:level?'))
    def level_setdev(self, val):
        self.levelcheck(val)
        self.write(':source:level '+repr(val))

class lia(visaInstrument):
    freq = scpiDevice('freq', str_type=float)
    sens = scpiDevice('sens', str_type=int)
    oauxi1 = scpiDevice(getstr='oaux? 1', str_type=float)
    srclvl = scpiDevice('slvl', str_type=float, min=0.004, max=5.)
    harm = scpiDevice('harm', str_type=int)
    phase = scpiDevice('phas', str_type=float)
    timeconstant = scpiDevice('oflt', str_type=int)
    x = scpiDevice(getstr='outp? 1', str_type=float)
    y = scpiDevice(getstr='outp? 2', str_type=float)
    r = scpiDevice(getstr='outp? 3', str_type=float)
    theta = scpiDevice(getstr='outp? 4', str_type=float)
    xy = scpiDevice(getstr='snap? 1,2')
    def init(self, full=False):
        # This empties the instrument buffers
        self.visa.clear()

class dummy(BaseInstrument):
    volt = MemoryDevice(0.)
    current = MemoryDevice(1.)
    alias = current
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
    @classmethod
    def add_class_devs(cls):
        cls.devwrap('rand')
        cls.devwrap('incr')
    #freq = scpiDevice('freq', str_type=float)
