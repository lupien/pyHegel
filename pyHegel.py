#!/usr/bin/python
# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:
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

def help_pyHegel():
    """
    Available commands:
        set
        get
        getasync
        move
        copy
        spy
        record
        trace
        scope
        _process_filename
        make_dir
        iprint
        ilist
        dlist
        find_all_instruments
        checkmode
        check
        batch
        sleep (gui)
        wait
        load
        task
        top
        kill
    Available instruments:
        sweep
        clock
    """
    print help_pyHegel.__doc__

def reset_pyHegel():
    """
       Resets pyHegel
       You need to reload instruments and reassign to sweep after calling this.

       can be called in ipython command line like:
         /reset_pyNoise
    """
    reload(traces)
    reload(local_config.instrument)
    reload(local_config.acq_board_instrument)
    reload(local_config)
    execfile('pyHegel.py', globals())

# exec in ipython with run -i otherwise
#  this globals will not be the same as the command line globals
#  and default headers will be name_not_found

instrument._globaldict = globals()

class _Clock(instrument.BaseInstrument):
    def _time_getdev(self):
        """ Get UTC time since epoch in seconds """
        return time.time()
    def _create_devs(self):
        self._devwrap('time')
        self.alias = self.time
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
clock = _Clock()

writevec = instrument._writevec

def _getheaders(setdev=None, getdevs=[], root=None, npts=None, extra_conf=None):
    hdrs = []
    graphsel = []
    count = 0
    formats = []
    if extra_conf != None and not isinstance(extra_conf, list):
        extra_conf = [extra_conf]
    elif extra_conf == None:
        extra_conf = []
    if setdev != None:
        hdrs.append(setdev.getfullname())
        count += 1
        extra_conf.append(setdev)

    if extra_conf != None and not isinstance(extra_conf, list):
        extra_conf = [extra_conf]
    for dev in getdevs:
        kwarg = {}
        if isinstance(dev, tuple):
            kwarg = dev[1]
            dev = dev[0]
        dev.force_get()
        hdr = dev.getfullname()
        f = dev.getformat(**kwarg)
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
    for x in extra_conf:
        x.force_get()
        hdr = x.getfullname()
        f = x.getformat(**kwarg)
        f['base_conf'] = instrument._get_conf_header(f)
        f['base_hdr_name'] = hdr
        formats.append(f)
    return hdrs, graphsel, formats

def _dev_filename(root, dev_name, npts, append=False):
    if root==None:
        name = time.strftime('%Y%m%d-%H%M%S.txt')
        root=os.path.join(sweep.path.get(), name)
    if npts == None:
        maxn = 99999
    else:
        maxn = npts-1
    if npts == 1:
        maxn = 1
    root = os.path.abspath(root)
    root, ext = os.path.splitext(root)
    dev_name = dev_name.replace('.', '_')
    if append:
        return root + '_'+ dev_name + ext
    n = int(np.log10(maxn))+1
    return root + '_'+ dev_name+'_%0'+('%ii'%n)+ext

def _readall(devs, formats, i, async=None):
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
        if async != None:
            val = dev.getasync(async=async, **kwarg)
            if async != 3:
                continue
        else:
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
    ret = instrument._writevec_flatten_list(ret)
    return ret

def _readall_async(devs, formats, i):
    try:
        _readall(devs, formats, i, async=0)
        _readall(devs, formats, i, async=1)
        _readall(devs, formats, i, async=2)
        return _readall(devs, formats, i, async=3)
    except KeyboardInterrupt:
        print 'Rewinding async because of keyboard interrupt'
        _readall(devs, formats, i, async=-1)
        raise

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
#              '.ext'/...              All of the change the extension of the file except
#                                      if you use '.ext', then the original extension is kept
#                                      All formats except numpy are straight dump
#                                      No headers are saved in any bin formats
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

# TODO: add a sweep up down.
#       could save in 2 files but display on same trace

class _Sweep(instrument.BaseInstrument):
    # This MemoryDevice will be shared among different instances
    # So there should only be one instance of this class
    #  Doing it this way allows the instr.dev = val syntax
    before = instrument.MemoryDevice()
    beforewait = instrument.MemoryDevice(0.02) # provide a default wait so figures are updated
    after = instrument.MemoryDevice()
    out = instrument.MemoryDevice(doc="""
      This is the list of device to read (get) for each iteration.
      It can be a single device (or an instrument of it has an alias)
      It can be a list of devices like [dev1, dev2, dev3]
      If optional parameters are needed for the device it can be enterred as
      a tuple (dev, devparam) where devparam is a dictionnary of optionnal
      parameters.
      For example you could have (acq1.readval, dict(ch=1, unit='V'))
      or another way (acq1.readval, {'ch':1, 'unit':'V'})
      A additional parameter is:
          graph:  it allows the selection of which column of multi-column
                  data to graph. It should be a list of column index.
    """)
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
    def get_alldevs(self, out=None):
        if out == None:
            out =  self.out.get()
        if out == None or out==[]:
            return []
        elif not isinstance(out, list):
            out = [out]
        return out
    def init(self, full=False):
        self._sweep_trace_num = 0
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('before', 'after', 'beforewait')
    def __repr__(self):
        return '<sweep instrument>'
    def __call__(self, dev, start, stop=None, npts=None, filename='%T.txt', rate=None,
                  close_after=False, title=None, out=None, extra_conf=None,
                  async=False, reset=False):
        """
            Usage:
                To define sweep either
                  set start, stop and npts (then uses linspace internally)
                  or just set start with a list of values
                filename to use
                    use %T: for date time string (20120115-145030)
                        %t: for time string only
                        %D: for date string
                        %02i: for unique 2 digit increment (00, 01 ...)
                              %03i for   3 digits
                rate: unused
                close_after: automatically closes the figure after the sweep when True
                title: string used for window title
                out: list of devices.  (This overrides sweep.out)
                extra_conf: list of devices to dump configuration headers at head
                            of data file. It isdone automatically for sweep device and
                            the out devices. This allows to add other instruments.
                async: When True, enables async mode (waiting on devices is done in
                        parallel instead of consecutivelly.) This saves time.
                reset: After the sweep is completed, the dev is returned to the
                       first value in the sweep list.
        """
        dolinspace = True
        if isinstance(start, (list, np.ndarray)):
            span = np.asarray(start)
            start = min(span)
            stop = max(span)
            npts = len(span)
            dolinspace = False
        try:
           dev.check(start)
           dev.check(stop)
        except ValueError:
           print 'Wrong start or stop values (outside of valid range). Aborting!'
           return
        npts = int(npts)
        if npts < 1:
           raise ValueError, 'npts needs to be at least 1'
        if dolinspace:
            span = np.linspace(start, stop, npts)
        if instrument.CHECKING:
            # For checking only take first and last values
            span = span[[0,-1]]
        devs = self.get_alldevs(out)
        fullpath = None
        if filename != None:
            fullpath = os.path.join(sweep.path.get(), filename)
            fullpath = _process_filename(fullpath)
            filename = os.path.basename(fullpath)
        if extra_conf == None:
            extra_conf = [sweep.out]
        elif not isinstance(extra_conf, list):
            extra_conf = [extra_conf, sweep.out]
        else:
            extra_conf.append(sweep.out)
        hdrs, graphsel, formats = _getheaders(dev, devs, fullpath, npts, extra_conf=extra_conf)
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
            if len(graphsel) == 0:
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
                wait(self.beforewait.get())
                if async:
                    vals = _readall_async(devs, formats, i)
                else:
                    vals = _readall(devs, formats, i)
                self.execafter()
                if f:
                    writevec(f, [iv]+vals+[tme])
                if graph:
                    t.addPoint(iv, gsel([iv]+vals))
                    _checkTracePause(t)
                    if t.abort_enabled:
                        break
        except KeyboardInterrupt:
            print 'Interrupted sweep'
            pass
        if f:
            f.close()
        if graph and close_after:
            t.window.close()
        if reset: # return to first value
            if graph and t.abort_enabled:
                pass
            else:
                dev.set(span[0]) # TODO replace with move

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
def record(devs, interval=1, npoints=None, filename='%T.txt', title=None, extra_conf=None, async=False):
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
    fullpath = None
    if filename != None:
        fullpath = os.path.join(sweep.path.get(), filename)
        fullpath = _process_filename(fullpath)
        filename = os.path.basename(fullpath)
    if title == None:
        title = filename
    if title == None:
        title = str(_record_trace_num)
    _record_trace_num += 1
    t.setWindowTitle('Record: '+title)
    hdrs, graphsel, formats = _getheaders(getdevs=devs, root=fullpath, npts=npoints, extra_conf=extra_conf)
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
            if async:
                vals = _readall_async(devs, formats, i)
            else:
                vals = _readall(devs, formats, i)
            t.addPoint(tme, gsel(vals))
            if f:
                writevec(f, [tme]+vals)
            i += 1
            if npoints == None or i < npoints:
                wait(interval)
            _checkTracePause(t)
            if t.abort_enabled:
                break
    except KeyboardInterrupt:
        # TODO proper file closing in case of error.
        #      on windows sometimes the file stays locked.
        print 'Interrupting record'
        pass
    if f:
        f.close()

def trace(dev, interval=1, title=''):
    """
       same as record(dev, interval, npoints=1000, filename='trace.dat')
    """
    record(dev, interval, npoints=1000, filename='trace.dat', title=title)

def scope(dev, interval=.1, title='', **kwarg):
    """
       For xscale it uses instr.get_xscale
       interval is in s
       title is for the window title
       kwarg is the list of optional parameters to pass to dev
       example:
           scope(acq1.readval, unit='V') # with acq1 in scope mode
    """
    t = traces.Trace()
    t.setWindowTitle('Scope: '+title)
    xscale = dev.instr.get_xscale()
    t.setLim(xscale)
    while True:
        v=dev.get(**kwarg)
        if v.ndim == 1:
            v.shape=(1,-1)
        t.setPoints(xscale, v)
        wait(interval)
        _checkTracePause(t)
        if t.abort_enabled:
            break


_get_filename_i = 0
def _process_filename(filename):
    global _get_filename_i
    localtime = time.localtime()
    datestamp = time.strftime('%Y%m%d', localtime)
    timestamp = time.strftime('%H%M%S', localtime)
    dtstamp = datestamp+'-'+timestamp
    changed = False
    if '%T' in filename:
        filename = filename.replace('%T', dtstamp)
        changed = True
    if '%D' in filename:
        filename = filename.replace('%D', datestamp)
        changed = True
    if '%t' in filename:
        filename = filename.replace('%t', timestamp)
        changed = True
    if re.search(r'%[\d]*i', filename):
        # Note that there is a possible race condition here
        # it is still possible to overwrite a file if it
        # is created between the check and the file creation
        while os.path.exists(filename%_get_filename_i):
           _get_filename_i += 1
        filename = filename % _get_filename_i
        changed = True
    if changed:
        print 'Using filename: '+filename
    return filename


### get overides get the mathplotlib
def get(dev, filename=None, keep=False, **extrap):
    """
       Get a value from device
       When giving it a filename, data will be saved to it
       and the strings uses the following format
                    use %T: for date time string (20120115-145030)
                        %t: for time string only
                        %D: for date string
                        %02i: for unique 2 digit increment (00, 01 ...)
                              %03i for   3 digits
       The path for saving is sweep.path if it is defined otherwise it saves
       in the current directory.
       keep is used to also return the values when saving to a filename
        by default, None is returned in that case.
       extrap are all other keyword arguments and depende on the device.
    """
    if filename != None:
        dev.force_get()
        filename = os.path.join(sweep.path.get(), filename)
        filename = _process_filename(filename)
        extrap.update(filename=filename)
        extrap.update(keep=keep)
    try:
        return dev.get(**extrap)
    except KeyboardInterrupt:
        print 'CTRL-C pressed!!!!!!' 

def getasync(devs, filename=None, **kwarg):
    if filename != None:
        raise ValueError, 'getasync does not currently handle the filename option'
    if not isinstance(devs, list):
        devs = [devs]
    for dev in devs:
        dev.getasync(async=0, **kwarg)
    for dev in devs:
        dev.getasync(async=1, **kwarg)
    for dev in devs:
        dev.getasync(async=2, **kwarg)
    ret = []
    for dev in devs:
        ret.append(dev.getasync(async=3, **kwarg))
    return ret

def make_dir(directory, setsweep=True):
    """
        Creates a directory if it does now already exists
        and changes sweep.path to point there unless
        setsweep is False
    """
    dirname = _process_filename(directory)
    if not os.path.exists(dirname):
        os.makedirs(dirname)
    if setsweep:
        sweep.path.set(dirname)


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

class _Hegel_Task(threading.Thread):
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
    _Hegel_Task(*arg, **kwarg)

def top():
    # All threads count: threading.active_count()
    for t in threading.enumerate():
        if isinstance(t, _Hegel_Task):
            print '%5i %s'%(t.ident, t)

def kill(n):
    # stop thread with number given by top
    for t in threading.enumerate():
        if isinstance(t, _Hegel_Task) and t.ident==n:
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

