# -*- coding: utf-8 -*-
#

try:
  import visa
except ImportError:
  print 'Error importing visa. You will have reduced functionality.'
import numpy as np
import random
import time

class BaseInstrument(object):
    alias = None
    def __init__(self):
        self.create_devs()
        self.init(full=True)
    def devwrap(self, name):
        setdev = getdev = check = None
        for s in dir(self):
           if s == name+'setdev':
              setdev = getattr(self, s)
           if s == name+'getdev':
              getdev = getattr(self, s)
           if s == name+'check':
              check = getattr(self, s)
        setattr(self, name, wrapDevice(setdev, getdev, check))
    def create_devs(self):
        pass
    def read(self):
        raise NotImplementedError
    def write(self, val):
        raise NotImplementedError
    def ask(self, question):
        raise NotImplementedError
    def init(self, full=False):
        """ Do instrument initialization (full=True)/reset (full=False) here """
        pass
    # These could probably be replaced by a single getattribute ...
    def get(self):
        if self.alias != None:
           return self.alias.get()
    def getcache(self):
        if self.alias != None:
           return self.alias.getcache()
    def set(self, val):
        if self.alias != None:
           self.alias.set(val)
    def setcache(self, val):
        if self.alias != None:
           self.alias.setcache(val)
    def check(self, val):
        if self.alias != None:
           self.alias.check(val)
    # this should handle print statements ...
    def __repr__(self):
        ret = ''
        for s in dir(self):
           obj = getattr(self, s)
           if s != 'alias' and isinstance(obj, BaseDevice):
               if self.alias == obj:
                   ret += 'alias = '
               ret += s+" = "+repr(obj.getcache())+"\n"
        return ret
    def trig():
        pass

class BaseDevice(object):
    def __init__(self, parent=None):
        self.instr = parent
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

    #TODO: this should allow assignement: instr.dev = val
    #but it does not work because the device object needs to be
    #assigned in the class, not the instance as is currently the case
    # It does work for sweep
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
    def __init__(self, parent, setstr=None, getstr=None, autoget=True, str_type=None, min=None, max=None, doc=None):
        """
           str_type can be float, int, None
        """
        BaseDevice.__init__(self, parent)
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
           # user repr instead of str to keep full precision
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

class wrapDevice(BaseDevice):
    def __init__(self, setdev=None, getdev=None, check=None):
        self.setdev = setdev
        self.getdev = getdev
        self.check  = check
        BaseDevice.__init__(self)

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
    def __repr__(self):
        ret = 'visa_addr='+self.visa_addr+'\n'
        ret += BaseInstrument.__repr__(self)
        return ret


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
    def init(self, full=False):
        # clear event register, extended event register and error queue
        self.write('*cls')
    def create_devs(self):
        self.function = scpiDevice(self, ':source:function') # use 'voltage' or 'current'
        # voltage or current means to add V or A in the string (possibly with multiplier)
        self.range = scpiDevice(self, ':source:range', str_type=float) # can be a voltage, current, MAX, MIN, UP or DOWN
        self.level = scpiDevice(self, ':source:level') # can be a voltage, current, MAX, MIN
        self.voltlim = scpiDevice(self, ':source:protection:voltage', str_type=float) #voltage, MIN or MAX
        self.currentlim = scpiDevice(self, ':source:protection:current', str_type=float) #current, MIN or MAX
        #self.level_2 = wrapDevice(self.levelsetdev, self.levelgetdev, self.levelcheck)
        self.devwrap('level')
        self.alias = self.level
    def levelcheck(self, val):
        rnge = 1.2*self.range.getcache()
        if self.function.getcache()=='CURR' and rnge>.2:
            rnge = .2
        if abs(val) > rnge:
           raise ValueError
    def levelgetdev(self):
        return float(self.ask(':source:level?'))
    def levelsetdev(self, val):
        self.levelcheck(val)
        self.write(':source:level '+repr(val))

class lia(visaInstrument):
    def init(self, full=False):
        # This empties the instrument buffers
        self.visa.clear()
    def create_devs(self):
        self.freq = scpiDevice(self, 'freq', str_type=float)
        self.sens = scpiDevice(self, 'sens', str_type=int)
        self.oauxi1 = scpiDevice(self, getstr='oaux? 1', str_type=float)
        self.srclvl = scpiDevice(self, 'slvl', str_type=float, min=0.004, max=5.)
        self.harm = scpiDevice(self, 'harm', str_type=int)
        self.phase = scpiDevice(self, 'phas', str_type=float)
        self.timeconstant = scpiDevice(self, 'oflt', str_type=int)
        self.x = scpiDevice(self, getstr='outp? 1', str_type=float)
        self.y = scpiDevice(self, getstr='outp? 2', str_type=float)
        self.r = scpiDevice(self, getstr='outp? 3', str_type=float)
        self.theta = scpiDevice(self, getstr='outp? 4', str_type=float)
        self.xy = scpiDevice(self, getstr='snap? 1,2')

class dummy(BaseInstrument):
    volt = MemoryDevice(0.)
    current = MemoryDevice(1.)
    alias = current
    def init(self, full=False):
        self.incr_val = 0
        self.wait = .1
    def incrgetdev(self):
        ret = self.incr_val
        self.incr_val += 1
        time.sleep(self.wait)
        return ret
    def randgetdev(self):
        time.sleep(self.wait)
        return random.normalvariate(0,1.)
    def create_devs(self):
        self.devwrap('incr')
        self.devwrap('rand')

