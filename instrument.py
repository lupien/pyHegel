# -*- coding: utf-8 -*-
#

try:
  import visa
  vpp43 = visa.vpp43
except ImportError:
  print 'Error importing visa. You will have reduced functionality.'
#can list instruments with : 	visa.get_instruments_list()
#     or :                      visa.get_instruments_list(use_aliases=True)

import numpy as np
import random
import time
import traces

_globaldict = dict() # This is set in pynoise.py
CHECKING = False

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
    def __init__(self, autoinit=True, doc='', setget=False):
        # instr and name updated by instrument's create_devs
        # doc is inserted before the above doc
        # setget makes us get the value after setting in
        #  this is usefull for instruments that could change the value
        #  under us.
        self.instr = None
        self.name = 'foo'
        self._cache = None
        self._autoinit = autoinit
        self.__doc__ = doc+BaseDevice.__doc__
        self._setdev = None
        self._getdev = None
        self._setget = setget
    # for cache consistency
    #    get should return the same thing set uses
    def set(self, val):
        self.check(val)
        if not CHECKING:
            self.setdev(val)
            if self._setget:
                val = self.get()
        elif self._setdev == None:
            raise NotImplementedError, self.perror('This device does not handle setdev')
        # only change cache after succesfull setdev
        self._cache = val
    def get(self):
        if not CHECKING:
            ret = self.getdev()
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
        pass

class wrapDevice(BaseDevice):
    def __init__(self, setdev=None, getdev=None, check=None, *extrap, **extrak):
        BaseDevice.__init__(self, *extrap, **extrak)
        # the methods are unbounded methods.
        self._setdev = setdev
        self._getdev = getdev
        self._check  = check
    def setdev(self, val):
        if self._setdev != None:
            self._setdev(val)
        else:
            raise NotImplementedError, self.perror('This device does not handle setdev')
    def getdev(self):
        if self._getdev != None:
            return self._getdev()
        else:
            raise NotImplementedError, self.perror('This device does not handle getdev')
    def check(self, val):
        if self._check != None:
            self._check(val)

class cls_wrapDevice(BaseDevice):
    def __init__(self, setdev=None, getdev=None, check=None, *extrap, **extrak):
        BaseDevice.__init__(self, *extrap, **extrak)
        # the methods are unbounded methods.
        self._setdev = setdev
        self._getdev = getdev
        self._check  = check
    def setdev(self, val):
        if self._setdev != None:
            self._setdev(self.instr, val)
        else:
            raise NotImplementedError, self.perror('This device does not handle setdev')
    def getdev(self):
        if self._getdev != None:
            return self._getdev(self.instr)
        else:
            raise NotImplementedError, self.perror('This device does not handle getdev')
    def check(self, val):
        if self._check != None:
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
        if not CHECKING:
            self.init(full=True)
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
        setdev = getdev = check = None
        for s in dir(cls):
           if s == name+'_setdev':
              setdev = getattr(cls, s)
           if s == name+'_getdev':
              getdev = getattr(cls, s)
           if s == name+'_check':
              check = getattr(cls, s)
        wd = cls_wrapDevice(setdev, getdev, check)
        setattr(cls, name, wd)
    def devwrap(self, name, *extrap, **extrak):
        setdev = getdev = check = None
        for s in dir(self):
           if s == name+'_setdev':
              setdev = getattr(self, s)
           if s == name+'_getdev':
              getdev = getattr(self, s)
           if s == name+'_check':
              check = getattr(self, s)
        wd = wrapDevice(setdev, getdev, check, *extrap, **extrak)
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
        self.devwrap('header')
        for devname, obj in self.devs_iter():
            obj.instr = self
            obj.name = devname
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
        if name in ['get', 'set', 'check', 'getcache', 'setcache', 'instr', 'name']:
            if self.alias == None:
                raise AttributeError, self.perror('This instrument does not have an alias for {nm}', nm=name)
            return getattr(self.alias, name)
        else:
            raise AttributeError, self.perror('{nm} is not an attribute of this instrument', nm=name)
    def __call__(self):
        if self.alias == None:
            raise TypeError, self.perror('This instrument does not have an alias for call')
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
    def trig():
        pass

class MemoryDevice(BaseDevice):
    def __init__(self, initval=None, *extrap,**extrak):
        BaseDevice.__init__(self, *extrap, **extrak)
        self._cache = initval
    def get(self):
        return self._cache
    def set(self, val):
        self._cache = val
    # we redefine setdev, getdev so CHECKING on device works.
    # but because we have redefined set and get above. 
    # they sould never be called
    def setdev(self, val): pass
    def getdev(self, val): pass
    # Can override check member

class scpiDevice(BaseDevice):
    def __init__(self, setstr=None, getstr=None, autoget=True, str_type=None,
                  min=None, max=None, doc=None, *extrap, **extrak):
        """
           str_type can be float, int, None
        """
        if setstr == None and getstr == None:
           raise ValueError, 'At least one of setstr or getstr needs to be specified'
        BaseDevice.__init__(self, *extrap, **extrak)
        self._setdev = setstr
        if getstr == None and autoget:
            getstr = setstr+'?'
        self._getdev = getstr
        self.type = str_type
        self.min = min
        self.max = max
        self.__doc__ = doc
    # TODO: these redefinition will prevent check from detecting a problem
    #       with a non existing device
    def setdev(self, val):
        if self._setdev == None:
           raise NotImplementedError, self.perror('This device does not handle setdev')
        if self.type != None:
           # use repr instead of str to keep full precision
           val = repr(val)
        self.instr.write(self.setstr+' '+val)
    def getdev(self):
        if self._getdev == None:
           raise NotImplementedError, self.perror('This device does not handle getdev')
        ret = self.instr.ask(self.getstr)
        if self.type != None:
           # here we assume self.type can convert a string
           ret = self.type(ret)
        return ret
    def check(self, val):
        if self.setstr == None:
           raise NotImplementedError, self.perror('This device does not handle check')
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
        else:
           state = True
        if state == False:
           raise ValueError, self.perror('Values is out of bounds')
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
    def _info(self):
        gn, cn, p = BaseInstrument._info(self)
        return gn, cn+'(%s)'%self.visa_addr, p

# use like:
# yo1 = yokogawa_gs200('GPIB0::12::INSTR')
#   or
# yo1 = yokogawa_gs200('GPIB::12')
#   or
# yo1 = yokogawa_gs200(12)
#'USB0::0x0957::0x0118::MY49001395::0::INSTR'
class yokogawa_gs200(visaInstrument):
    # case insensitive
    multipliers = ['YO', 'ZE', 'EX', 'PE', 'T', 'G', 'MA', 'K', 'M', 'U', 'N', 'P',
                   'F', 'A', 'Z', 'Y']
    multvals    = [1e24, 1e21, 1e18, 1e15, 1e12, 1e9, 1e6, 1e3, 1e-3, 1e-6, 1e-9, 1e-12,
                   1e-15, 1e-18, 1e-21, 1e-24]
    def init(self, full=False):
        # clear event register, extended event register and error queue
        self.write('*cls')
    def create_devs(self):
        #self.level_2 = wrapDevice(self.levelsetdev, self.levelgetdev, self.levelcheck)
        self.function = scpiDevice(':source:function') # use 'voltage' or 'current'
        # voltage or current means to add V or A in the string (possibly with multiplier)
        self.range = scpiDevice(':source:range', str_type=float, setget=True) # can be a voltage, current, MAX, MIN, UP or DOWN
        self.level = scpiDevice(':source:level') # can be a voltage, current, MAX, MIN
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
    def init(self, full=False):
        # This empties the instrument buffers
        self.visa.clear()
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
        # This needs to be last to complete creation
        super(type(self),self).create_devs()

class sr384_rf(visaInstrument):
    # This instruments needs to be on local state or to pass through local state
    #  after a local_lockout to actually turn off the local key.
    # allowed units: amp: dBm, rms, Vpp; freq: GHz, MHz, kHz, Hz; Time: ns, us, ms, s
    def init(self, full=False):
        # This clears the error state
        self.write('*cls')
        pass
    def create_devs(self):
        self.freq = scpiDevice('freq',str_type=float)
        self.offset_low = scpiDevice('ofsl',str_type=float) #volts
        self.amp_lf_dbm = scpiDevice('ampl',str_type=float)
        self.amp_rf_dbm = scpiDevice('ampr',str_type=float)
        self.amp_hf_dbm = scpiDevice('amph',str_type=float) # doubler
        self.en_lf = scpiDevice('enbl') # 0 is off, 1 is on, read value depends on freq
        self.en_rf = scpiDevice('enbr') # 0 is off, 1 is on, read value depends on freq
        self.en_hf = scpiDevice('enbh') # 0 is off, 1 is on, read value depends on freq
        self.phase = scpiDevice('phas',str_type=float, min=-360, max=360) # deg, only change by 360
        self.mod_en = scpiDevice('modl') # 0 is off, 1 is on
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
        self.out_en1 = scpiDevice('OUTPut1') #OFF,0 or ON,1
        self.ampl2 = scpiDevice('SOUR2:VOLT', str_type=float, min=0.001, max=10)
        self.freq2 = scpiDevice('SOUR2:FREQ', str_type=float, min=1e-6, max=30e6)
        self.phase2 = scpiDevice('SOURce2:PHASe', str_type=float, min=-360, max=360) # in deg unless changed by unit:angle
        self.offset2 = scpiDevice('SOUR2:VOLT:OFFS', str_type=float, min=-5, max=5)
        self.mode2 = scpiDevice('SOUR2:FUNC') # SIN, SQU, RAMP, PULS, PRBS, NOIS, ARB, DC
        self.out_en2 = scpiDevice('OUTPut2') #OFF,0 or ON,1
        self.phase_sync = scpiDevice('PHASe:SYNChronize', autoget=False)
        self.alias = self.freq1
        # This needs to be last to complete creation
        super(type(self),self).create_devs()
    def phase_sync(self):
        self.write('PHASe:SYNChronize')

class agilent_multi_34410A(visaInstrument):
    def create_devs(self):
        # This needs to be last to complete creation
        self.mode = scpiDevice('FUNC') # CURR:AC, VOLT:AC, CAP, CONT, CURR, VOLT, DIOD, FREQ, PER, RES, FRES
        self.readval = scpiDevice(getstr='READ?',str_type=float) # similar to INItiate followed by FETCh (TODO verify init forces immediate restart)
        self.fetchval = scpiDevice(getstr='FETCh?',str_type=float)
        self.volt_nplc = scpiDevice('VOLTage:NPLC', str_type=float) # DC 0.006, 0.02, 0.06, 0.2, 1, 2, 10, 100
        self.volt_aperture = scpiDevice('VOLTage:APERture', str_type=float) # DC in seconds (max~1?TODO check), also MIN, MAX, DEF
        self.volt_aperture_en = scpiDevice('VOLTage:APERture:ENabled') # TODO: check if question only
        self.current_aperture = scpiDevice('CURRent:APERture', str_type=float) # DC in seconds
        self.res_aperture = scpiDevice('RESistance:APERture', str_type=float)
        self.four_res_aperture = scpiDevice('FRESistance:APERture', str_type=float)
        self.alias = self.readval
        super(type(self),self).create_devs()

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
        self.snap = scpiDevice(getstr=':DISPlay:DATA? PNG, COLor', autoinit=False) # returns block of data
        self.inksaver = scpiDevice(':HARDcopy:INKSaver') # ON, OFF 1 or 0
        self.data = scpiDevice(getstr=':waveform:DATA?', autoinit=False) # returns block of data
          # also read :WAVeform:PREamble?, which provides, format(byte,word,ascii),
          #  type (Normal, peak, average, HRes), #points, #avg, xincr, xorg, xref, yincr, yorg, yref
          #  xconv = xorg+x*xincr, yconv= (y-yref)*yincr + yorg
        self.format = scpiDevice(':WAVeform:FORMat') # WORD, BYTE, ASC
        self.points = scpiDevice(':WAVeform:POINts') # 100, 250, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000, 2000000, 4000000, 8000000
        self.mode = scpiDevice(':WAVeform:MODE') # NORM, MAX, RAW
        self.preamble = scpiDevice(getstr=':waveform:PREamble?')
        self.source = scpiDevice(':WAVeform:SOURce') # CHAN1, CHAN2, CHAN3, CHAN4
        # This needs to be last to complete creation
        super(type(self),self).create_devs()

class agilent_EXA(visaInstrument):
    def init(self, full=False):
        self.write(':format REAL,64')
        self.write(':format:border swap')
    def create_devs(self):
        self.bandwith = scpiDevice(':bandwidth',str_type=float)
        self.mark1x = scpiDevice(':calc:mark1:x',str_type=float)
        self.mark1y = scpiDevice(getstr=':calc:mark1:y?',str_type=float)
        self.average_count = scpiDevice(getstr=':average:count?',str_type=float)
        self.freq_start = scpiDevice(':freq:start', str_type=float, min=10e6, max=12.6e9)
        self.freq_stop = scpiDevice(':freq:stop', str_type=float, min=10e6, max=12.6e9)
        self.trace1 = scpiDevice(getstr=':trace? trace1', autoinit=False)
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
        self.devwrap('rand', doc='This returns a random value. There is not set.')
        self.devwrap('incr')
        self.alias = self.current
        # This needs to be last to complete creation
        super(type(self),self).create_devs()
