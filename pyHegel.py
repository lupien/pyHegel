#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Programme principale pour remplacer Hegel
#

import numpy as np
import os
import time
import string
import sys

import traces
import instrument
import local_config

_figlist = []

# exec in ipython with run -i otherwise
#  this globals will not be the same as the command line globals
#  and default headers will be name_not_found

instrument._globaldict = globals()

class _Clock(instrument.BaseInstrument):
    def time_getdev(self):
        """ Get UTC time since epoch in seconds """
        return time.time()
    def create_devs(self):
        self.devwrap('time')
        self.alias = self.time
        # This needs to be last to complete creation
        super(type(self),self).create_devs()
clock = _Clock()

def writevec(file_obj, vals_list, pre_str=''):
     strs_list = map(repr, vals_list)
     file_obj.write(pre_str+string.join(strs_list,'\t')+'\n')

def getheaders(devs):
    return [dev.instr.header.get()+'.'+dev.name for dev in devs]

class _Sweep(instrument.BaseInstrument):
    # This MemoryDevice will be shared among different instances
    # So there should only be one instance of this class
    #  Doing it this way allows the instr.dev = val syntax
    before = instrument.MemoryDevice()
    beforewait = 0.02 # provide a default wait so figures are updated
    after = instrument.MemoryDevice()
    out = instrument.MemoryDevice()
    path = instrument.MemoryDevice('')
    graph = instrument.MemoryDevice(True)
    def execbefore(self):
        b = self.before.get()
        if b:
            exec(b)
    def execafter(self):
        b = self.after.get()
        if b:
            exec(b)
    def get_alldevs(self):
        l =  self.out.get()
        if l == None or l==[]:
            return []
        elif not isinstance(l,list):
            l = [l]
        return l
    def readall(self):
        # will will just try to add .get
        #  this will work for the alias as well
        l = self.get_alldevs()
        if l == []:
            return []
        ret = []
        for dev in l:
            ret.append(dev.get())
        return ret
    def __repr__(self):
        return '<sweep instrument>'
    def __call__(self, dev, start, stop, npts, filename, rate=None):
        """
            routine pour faire un sweep
             dev est l'objet a varier
            ....
        """
        try:
           dev.check(start)
           dev.check(stop)
        except ValueError:
           print 'Wrong start or stop values. Aborting!'
           return
        span = np.linspace(start, stop, npts)
        graph = self.graph.get()
        if graph:
            t = traces.Trace()
            _figlist.append(t) # TODO: handle removal from figlist
            t.setLim(span)
        if filename != None:
            fullpath=os.path.join(self.path.get(), filename)
            # Make it unbuffered, windows does not handle line buffer correctly
            f = open(fullpath, 'w', 0)
            hdrs = getheaders([dev]+self.get_alldevs())
            writevec(f, hdrs+['time'], pre_str='#')
            if graph:
                i = 1
                if len(hdrs) == 1:
                    i = 0
                t.setlegend(hdrs[i:])
        else:
            f = None
        #TODO get CTRL-C to work properly
        try:
            for i in span:
                tme = clock.get()
                dev.set(i) # TODO replace with move
                self.execbefore()
                wait(self.beforewait)
                vals=self.readall()
                self.execafter()
                if f:
                    writevec(f, [i]+vals+[tme])
                if graph:
                    #in case nothing is read, do a stupid linear graph
                    if vals == []:
                        vals = [i]
                    t.addPoint(i, vals)
        except KeyboardInterrupt:
            print 'Interrupted sweep'
            pass
        if f:
            f.close()

sweep = _Sweep()

wait = traces.wait

###  set overides set builtin function
def set(dev, value):
    """
       Change la valeur de dev
    """
    dev.set(value)

def move(dev, value, rate):
    """
       Change the value of dev at a particular rate (val/s)
    """
    dev.move(value, rate)

### copy overrides copy builtin
def copy(from_meter, to_src):
    """
       set to_src to value read from from_meter
    """
    val = get(from_meter)
    set(to_src, val)

def spy(devs, interval=1):
    """
       dev is read every interval seconds and displayed on screen
       CTRL-C to stop
    """
    # make sure devs is list like
    try:
       dev = devs[0]
    except TypeError:
       devs = [devs]
    try:
        while True:
            v=[]
            for dev in devs:
                v.append(dev.get())
            print >>sys.stderr, v
            wait(interval)
    except KeyboardInterrupt:
        print 'Interrupting spy'
        pass

def record(devs, interval=1, npoints=None, filename=None):
    """
       record to filename (if not None) the values from devs
         uses sweep.path
       Also display it on a figure
       interval is in seconds
       npoints is max number of points. If None, it will only stop
        on CTRL-C...
    """
    # make sure devs is list like
    try:
       dev = devs[0]
    except TypeError:
       devs = [devs]
    t = traces.Trace(time_mode=True)
    _figlist.append(t) # TODO: handle removal from figlist
    if filename != None:
        fullpath=os.path.join(sweep.path.get(), filename)
        # Make it unbuffered, windows does not handle line buffer correctly
        f = open(fullpath, 'w', 0)
        hdrs = getheaders(devs)
        writevec(f, ['time']+hdrs, pre_str='#')
        t.setlegend(hdrs)
    else:
        f = None
    try:
        i=0
        while not (npoints <= i): # this also works for npoints=None
            vals=[]
            tme = clock.get()
            for dev in devs:
                vals.append(dev.get())
            t.addPoint(tme, vals)
            if f:
                writevec(f, [tme]+vals)
            i += 1
            if not (npoints <= i):
                wait(interval)
    except KeyboardInterrupt:
        print 'Interrupting spy'
        pass
    if f:
        f.close()

def trace(dev, interval=1):
    """
       same as record(dev, interval, npoints=1000, filename='trace.dat')
    """
    record(dev, interval, npoints=1000, filename='trace.dat')

### get overides get the mathplotlib
def get(dev):
    """
       Obtien la valeur de get
    """
    try:
       return dev.get()
    except KeyboardInterrupt:
       print 'CTRL-C pressed!!!!!!' 

def iprint(instrument):
    print instrument.iprint()

def ilist():
    """
       print the list of instruments
        this will not include aliased devices (dev=instr,devx)
        but will include aliased instruments (instr1=instr2)
    """
    lst = []
    for name, value in globals().iteritems():
        if name[0] == '_':
            continue
        if isinstance(value, instrument.BaseInstrument):
            print name
            lst += name
    #return lst

def check(batch):
    """
       Run batch without talking to devices.
    """
    raise NotImplementedError

def sleep(sec):
    """
       wait seconds... Can be paused.
       After resuming, the wait continues (i.e. total
          wait will be pause+sec)
       See also wait
    """
    raise NotImplementedError

# overrides pylab load (which is no longer implemented anyway)
def load(names, newnames=None):
    """
       Uses definitions in local_config to open devices by there
       standard names. By default it produces a variable with that
       name in the global space. If newname is given, it is the name used
       for that new instrument.
       names and newnames can be a string or a list of strings
    """
    if isinstance(names, basestring):
        names = [names]
        newnames = [newnames]
    if newnames == None:
        newnames = [None]
    if len(newnames) < len(names):
        newnames = newnames + [None]*(len(names)-len(newnames))
    for name, newname in zip(names, newnames):
        instr, param = local_config.conf[name]
        if newname == None:
            newname = name
        i = instr(*param)
        exec('global '+newname+';'+newname+'=i')

#alias: replaced by assignement instr1=instr2, dev=instr.devx
#forget: replaced by del instr1
#open, close instrument: replaced by object instantation and deletion
#call: replaced by run or execfile
#no: replaced by pass
# % replaced by #

# To implement
#top: list task
#task(action, interval, count, start_delay=0)
# handle locking of devices...
# some wait to stop tasks

#var: adds a variable to an instrument
#      maybe the same as: instr.newvar = instrument.MemoryDevice()

