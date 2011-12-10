#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Programme principale pour remplacer Hegel
#

import numpy as np
import os
import time
import re
import string
import sys
import threading
import operator
from gc import collect as collect_garbage

import traces
import instrument
import local_config

def reset_pyHegel():
    """
       Resets pyHegel
       You need to reload instruments and reassign to sweep after calling this.

       can be called in ipython command line like:
         /reset_pyNoise
    """
    reload(instrument)
    reload(local_config)
    execfile('pyHegel.py', globals())

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

writevec = instrument._writevec

def _getheaderhelper(dev):
    return dev.instr.header.get()+'.'+dev.name

def getheaders(setdev=None, getdevs=[], root=None, npts=None):
    hdrs = []
    graphsel = []
    count = 0
    formats = []
    if setdev != None:
        hdrs.append(_getheaderhelper(setdev))
        count += 1
    for dev in getdevs:
        kwarg = {}
        if isinstance(dev, tuple):
            kwarg = dev[1]
            dev = dev[0]
        hdr = _getheaderhelper(dev)
        f = dev.getformat(**kwarg).copy()
        f['basename'] = _dev_filename(root, hdr, npts, append=f['append'])
        f['base_conf'] = instrument._get_conf_header(f)
        f['base_hdr_name'] = hdr
        formats.append(f)
        if f['file'] == True or f['multi'] == True:
            hdrs.append(hdr)
            if f['file'] == True and f['graph'] == True:
                graphsel.append(count)
            count += 1
        elif f['multi']: # it is a list of header names
            hdr_list = [ hdr+'.'+h for h in f['multi']]
            c = len(hdr_list)
            hdrs.extend(hdr_list)
            graph_list = [ g+count for g in f['graph']]
            graphsel.extend(graph_list)
            count += c
        else: # file==False and multi==False
            hdrs.append(hdr)
            graphsel.append(count)
            count += 1
    return hdrs, graphsel, formats

def _dev_filename(root, dev_name, npts, append=False):
    if root==None:
        name = time.strftime('%Y%m%d-%H%M%S.txt')
        root=os.path.join(sweep.path.get(), name)
    if npts == None:
        maxn = 99999
    else:
        maxn = npts-1
    root = os.path.abspath(root)
    root, ext = os.path.splitext(root)
    dev_name = dev_name.replace('.', '_')
    if append:
        return root + '_'+ dev_name + ext
    n = int(np.log10(maxn))+1
    return root + '_'+ dev_name+'_%0'+('%ii'%n)+ext


def _readall(devs, formats, i):
    if devs == []:
        return []
    ret = []
    for dev, fmt in zip(devs, formats):
        kwarg={}
        if isinstance(dev, tuple):
            kwarg = dev[1]
            dev = dev[0]
        filename = fmt['basename']
        if not fmt['append']:
             filename = filename % i
        if fmt['file']:
            kwarg['filename']= filename
        val = dev.get(**kwarg)
        if val == None:
            val = i
        if isinstance(val, list) or isinstance(val, tuple) or \
           isinstance(val, np.ndarray):
            if isinstance(fmt['multi'], list):
                ret.extend(val)
            else:
                ret.append(i)
                instrument._write_dev(val, filename, format=fmt, first= i==0)
        else:
            ret.append(val)
    return ret

def _checkTracePause(trace):
    while trace.pause_enabled:
        wait(.1)

#
#    out can be: dev1
#                [dev1, dev2, ..]
#                (dev1, dict(arg1=...))
#                [dev1, (dev2, dict()), ...
#    Also for every dev
#        if dev.get returns a large object and we are not
#        told otherwise, we save it to a standard name
#           filename(-ext)+'inst_dev %02i'+ext
#        we put the point number in the output filename
#        and nothing on the graph
#        otherwise, the device tells us what to do
#        from dev.getformat(dict)
#        which should return a dict containing
#          file=True  (send the filename to device, it will save it)
#                     then device returns None and we output index number instead
#                     or give the number to put in main file. No graphing here
#          multi=False      Says the device only return single values (default)
#          multi=True       Says the device returns many values and we need to save
#                            them to a file
#          multi=['head1', 'head2']   Used when device returns multiple values
#                                     This says so, gives the number of them and their names
#                                     for headers and graphing
#          graph=[1,2]                When using multi, this selects the values to graph
#          graph=True/False           When file is True, This says to graph the return value or not
#          append=True                Dump the data on a line in the file
#          header=['line1', 'line2']  Stuff to dump at head of new file
#                                       it can also be a function that returns the proper list of strings
#          bin=False/'.npy'/'.raw'/'.png' Dump data in binary form. npy is numpy format
#                                      All of the changes the extension of the file except
#                                      if you use 'ext', then the original extension is kept
#
#   Also handle getasync

def _itemgetter(*args):
    # similar to operator.itemgetter except always returns a list
    ig = operator.itemgetter(*args)
    if len(args) == 1:
        return lambda x: [ig(x)]
    return ig

def _write_conf(f, formats):
    for fmt in formats:
        conf = fmt['base_conf']
        hdr = fmt['base_hdr_name']
        if conf:
            f.write('#'+hdr+':=')
            for c in conf:
                f.write(' '+c+';')
            f.write('\n')


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
            exec b
    def execafter(self):
        b = self.after.get()
        if b:
            exec b
    def get_alldevs(self):
        l =  self.out.get()
        if l == None or l==[]:
            return []
        elif not isinstance(l,list):
            l = [l]
        return l
    def init(self, full=False):
        self._sweep_trace_num = 0
    def __repr__(self):
        return '<sweep instrument>'
    def __call__(self, dev, start, stop, npts, filename, rate=None, 
                  close_after=False, title=None):
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
        npts = int(npts)
        if npts < 2:
           raise ValueError, 'npts needs to be at least 2'
        span = np.linspace(start, stop, npts)
        if instrument.CHECKING:
            # For checking only take first and last values
            span = span[[0,-1]]
        devs = self.get_alldevs()
        fullpath = None
        if filename != None:
            fullpath=os.path.join(self.path.get(), filename)
        hdrs, graphsel, formats = getheaders(dev, devs, fullpath, npts)
        graph = self.graph.get()
        if graph:
            t = traces.Trace()
            if title == None:
                title = filename
            if title == None:
                title = str(self._sweep_trace_num)
            self._sweep_trace_num += 1
            t.setWindowTitle('Sweep: '+title)
            t.setLim(span)
            if len(hdrs) == 1:
                gsel = _itemgetter(0)
            else:
                gsel = _itemgetter(*graphsel)
            t.setlegend(gsel(hdrs))
            t.set_xlabel(hdrs[0])
        if filename != None:
            # Make it unbuffered, windows does not handle line buffer correctly
            f = open(fullpath, 'w', 0)
            _write_conf(f, formats)
            writevec(f, hdrs+['time'], pre_str='#')
        else:
            f = None
        #TODO get CTRL-C to work properly
        ###############################
        # Start of loop
        ###############################
        try:
            for i,v in enumerate(span):
                tme = clock.get()
                dev.set(v) # TODO replace with move
                iv = dev.getcache() # in case the instrument changed the value
                self.execbefore()
                wait(self.beforewait)
                vals = _readall(devs, formats, i)
                self.execafter()
                if f:
                    writevec(f, [iv]+vals+[tme])
                if graph:
                    t.addPoint(iv, gsel([iv]+vals))
                    _checkTracePause(t)
        except KeyboardInterrupt:
            print 'Interrupted sweep'
            pass
        if f:
            f.close()
        if graph and close_after:
            t.window.close()

sweep = _Sweep()

wait = traces.wait

###  set overides set builtin function
def set(dev, value, **kwarg):
    """
       Change la valeur de dev
    """
    dev.set(value, **kwarg)

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

_record_trace_num = 0
def record(devs, interval=1, npoints=None, filename=None, title=None):
    """
       record to filename (if not None) the values from devs
         uses sweep.path
       Also display it on a figure
       interval is in seconds
       npoints is max number of points. If None, it will only stop
        on CTRL-C...
    """
    global _record_trace_num
    # make sure devs is list like
    if not isinstance(devs, list):
        devs = [devs]
    t = traces.Trace(time_mode=True)
    if title == None:
        title = filename
    if title == None:
        title = str(_record_trace_num)
    _record_trace_num += 1
    t.setWindowTitle('Record: '+title)
    fullpath = None
    if filename != None:
        fullpath=os.path.join(sweep.path.get(), filename)
    hdrs, graphsel, formats = getheaders(getdevs=devs, root=fullpath, npts=npoints)
    if graphsel == []:
        # nothing selected to graph so pick first dev
        # It probably will be the loop index i
        graphsel=[0]
    gsel = _itemgetter(*graphsel)
    t.setlegend(gsel(hdrs))
    if filename != None:
        # Make it unbuffered, windows does not handle line buffer correctly
        f = open(fullpath, 'w', 0)
        _write_conf(f, formats)
        writevec(f, ['time']+hdrs, pre_str='#')
    else:
        f = None
    try:
        i=0
        while npoints == None or i < npoints:
            tme = clock.get()
            vals = _readall(devs, formats, i)
            t.addPoint(tme, gsel(vals))
            if f:
                writevec(f, [tme]+vals)
            i += 1
            if npoints == None or i < npoints:
                wait(interval)
            _checkTracePause(t)
    except KeyboardInterrupt:
        print 'Interrupting record'
        pass
    if f:
        f.close()

def trace(dev, interval=1, title=''):
    """
       same as record(dev, interval, npoints=1000, filename='trace.dat')
    """
    record(dev, interval, npoints=1000, filename='trace.dat', title=title)


_get_filename_i = 0
### get overides get the mathplotlib
def get(dev, filename=None, **extrap):
    """
       Get a value from device
       if filename is given and contains a %i (or %04i)
       then it will replace the %i with and integer that
       increments to prevent collision.
    """
    global _get_filename_i
    if filename != None:
        if re.search(r'%[\d].i', filename):
            # Note that there is a possible race condition here
            # it is still possible to overwrite a file if it
            # is created between the check and the file creation
            while os.path.exists(filename%_get_filename_i):
               _get_filename_i += 1
            filename = filename % _get_filename_i
            print 'Using filename: '+filename
        extrap.update(filename=filename)
    try:
        return dev.get(**extrap)
    except KeyboardInterrupt:
        print 'CTRL-C pressed!!!!!!' 

def iprint(instrument, force=False):
    """
       Prints the value of all the device inside instrument.
       If force is True, use get instead of getcache for
       all autoinit devices.
    """
    print instrument.iprint(force=force)

def ilist():
    """
       print the list of instruments
        this will not include aliased devices (dev=instr.devx)
        but will include aliased instruments (instr1=instr2)
       see dlist for those

       can be called in ipython command line like:
         /ilist
    """
    lst = []
    for name, value in globals().iteritems():
        if name[0] == '_':
            continue
        if isinstance(value, instrument.BaseInstrument):
            print name
            lst += name
    #return lst

def dlist():
    """
       print the list of devices 
        this will not include instruments
       see ilist for those

       can be called in ipython command line like:
         /dlist
    """
    lst = []
    for name, value in globals().iteritems():
        if name[0] == '_':
            continue
        if isinstance(value, instrument.BaseDevice):
            print name
            lst += name
    #return lst

def find_all_instruments():
    return instrument.find_all_instruments()

def checkmode(state=None):
    """
       Called with no arguments, returns current checking mode state
       With a boolean, sets the check state
    """
    if state == None:
        return instrument.CHECKING
    instrument.CHECKING = state

def check(batchfile):
    """
       Run batch without talking to devices.
       Otherwise it is the same as the batch command
    """
    before = checkmode()
    checkmode(True)
    try:
        batch(batchfile)
    except:
        checkmode(before)
        raise
    checkmode(before)

def batch(batchfile):
    """
       Runs the batch file.
       On ipython command line this can be called
        ;batch long file name with spaces

       It will also try the batch name with .py added if the direct name does
       not work.

       You can also use run -i, but that seems to block the graphic output
         unless the names ends with a .ipy
    """
    try:
        execfile(batchfile)
    except IOError:
        execfile(batchfile+'.py')

def sleep(sec):
    """
       wait seconds... Can be paused.
       After resuming, the wait continues (i.e. total
          wait will be pause+sec)
       See also wait
    """
    traces.sleep(sec)

# overrides pylab load (which is no longer implemented anyway)
def load(names=None, newnames=None):
    """
       Uses definitions in local_config to open devices by there
       standard names. By default it produces a variable with that
       name in the global space. If newname is given, it is the name used
       for that new instrument.
       names and newnames can be a string or a list of strings
       They can alse be a string with multiname names separated by spaces
        Therefore it can be called like this in ipython
          ,load instr1 newname1
          ;load instr1 instr2 instr3 ....

       Called with no arguments to get a list of currently
       configured devices
    """
    if names == None or (isinstance(names, basestring) and names == ''):
        for name, (instr, para) in sorted(local_config.conf.items()):
           instr = instr.__name__
           print '{:>10s}: {:25s} {:s}'.format(name, instr, para)
        return
    if isinstance(names, basestring):
        # this always returns list
        names = names.split(' ')
    if isinstance(newnames, basestring):
        newnames = newnames.split(' ')
    if newnames == None:
        newnames = [None]
    if len(newnames) < len(names):
        newnames = newnames + [None]*(len(names)-len(newnames))
    for name, newname in zip(names, newnames):
        instr, param = local_config.conf[name]
        if newname == None:
            newname = name
        i = instr(*param)
        exec 'global '+newname+';'+newname+'=i'

class Hegel_Task(threading.Thread):
    def __init__(self, func, args=(), kwargs={}, count=None,
           interval=None, **extra):
        # func can be a function or a callable class instance.
        super(type(self), self).__init__(**extra)
        self.args = args
        self.kwargs = kwargs
        self.count = count
        self.interval = interval
        self.func = func
        self.stopit = False
        self.start()
    def run(self):
        i = 0
        while not self.stopit:
            self.func(*self.args, **self.kwargs)
            i += 1
            if self.count != None and i >= self.count:
                break;
            elif self.interval != None:
                #Unblock every 1s
                start_time = time.time()
                diff = 0.
                while diff < self.interval:
                    time.sleep(min(1, self.interval-diff))
                    if self.stopit:
                        break
                    diff = time.time()-start_time
    def stop(self):
        self.stopit = True

def task(*arg, **kwarg):
    Hegel_Task(*arg, **kwarg)

def top():
    # All threads count: threading.active_count()
    for t in threading.enumerate():
        if isinstance(t, Hegel_Task):
            print '%5i %s'%(t.ident, t)

def kill(n):
    # stop thread with number given by top
    for t in threading.enumerate():
        if isinstance(t, Hegel_Task) and t.ident==n:
            print 'Stopping task and waiting'
            t.stop()
            t.join()
            print 'Stopped task'


#alias: replaced by assignement instr1=instr2, dev=instr.devx
#forget: replaced by del instr1
#open, close instrument: replaced by object instantation (and load) and deletion
#call: replaced by run or execfile
#no: replaced by pass
# % replaced by #

# handle locking of devices...

#var: adds a variable to an instrument
#      maybe the same as: instr.newvar = instrument.MemoryDevice()

