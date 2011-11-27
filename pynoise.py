#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Programme principale pour remplacer Hegel
#

import numpy as np
import os
from time import sleep
import string

import traces
import instrument

_figlist = []
instrument._globaldict = globals()

class _Sweep(instrument.BaseInstrument):
    before = instrument.MemoryDevice()
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
    def readall(self):
        # will will just try to add .get
        #  this will work for the alias as well
        l = self.out.get()
        if l == None or l==[]:
            return []
        elif not isinstance(l,list):
            l = [l]
        ret = []
        for dev in l:
            ret.append(dev.get())
        return ret
    def __repr__(self):
        return '<sweep instrument>'
    def __call__(self, dev, start, stop, npts, rate=None, filename=None):
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
            # Make it unbuffered
            f = open(fullpath, 'w', 0)
        else:
            f = None
        #TODO get CTRL-C to work properly
        try:
            for i in span:
                dev.set(i) # TODO replace with move
                self.execbefore()
                vals=self.readall()
                self.execafter()
                vals = [i]+vals
                strs = map(repr,vals)
                if f:
                    f.write(string.join(strs,'\t')+'\n')
                if graph:
                    t.addPoint(i, vals)
        except KeyboardInterrupt:
            print 'in here'
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

def spy(dev, interval=1):
    """
       dev is read every interval seconds and displayed on screen
       CTRL-C to stop
    """
    raise NotImplementedError

def record(dev, interval=1, npoints=None, filename=None):
    """
       record to filename (if not None) the values from dev
       Also display it on a figure
       interval is in seconds
       npoints is max number of points. If None, it will only stop
        on CTRL-C...
    """
    raise NotImplementedError

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

