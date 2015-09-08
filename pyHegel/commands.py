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

#
# All the commands used in pyHegel
#

from __future__ import absolute_import

import ctypes
import os
import time
import re
import string
import sys
import textwrap
import threading
import operator
import numpy as np
import StringIO
from gc import collect as collect_garbage

from . import traces
from . import instruments_registry
from . import instruments
instruments._populate_instruments()
from . import instruments_base
#from . import local_config
from . import util
from . import config

local_config = config.load_local_config()

from .instruments_base import _writevec as writevec, _normalize_usb, _normalize_gpib, _get_visa_idns
from .traces import wait
from .util import _readfile_lastnames, _readfile_lastheaders, _readfile_lasttitles

__all__ = ['collect_garbage', 'traces', 'instruments', 'instruments_base', 'instruments_registry',
           'util', 'help_pyHegel', 'reset_pyHegel', 'clock', 'sweep', 'sweep_multi', 'wait',
           'readfile', '_readfile_lastnames', '_readfile_lastheaders', '_readfile_lasttitles',
           'set', 'move', 'copy', 'spy', 'snap', 'record', 'trace', 'scope',
           '_process_filename', 'get', 'setget', 'getasync', 'make_dir',
           'iprint', 'ilist', 'dlist', 'find_all_instruments', 'checkmode', 'check',
           'batch', 'sleep', 'load', 'load_all_usb', 'load_all_gpib', 'test_gpib_srq_state',
           'task', 'top', 'kill', '_init_pyHegel_globals', '_faster_timer', 'quiet_KeyboardInterrupt']

# not in __all__: local_config _globaldict
#             _Clock _update_sys_path writevec _get_dev_kw _getheaders
#             _dev_filename _readall _readall_async _checkTracePause
#             _itemgetter _write_conf
#             _Sweep _Snap _record_execafter _normalize_usb _normalize_gpib _get_visa_idns
#             _Hegel_Task _quiet_KeyboardInterrupt_Handler
#             _greetings _load_helper _get_extra_confs dump_conf _time_check


#instruments_base._globaldict = globals()
try:
    _globaldict  # keep the previous values (when reloading this file)
except NameError:
    _globaldict = {}
    instruments_base._globaldict = _globaldict

def _init_pyHegel_globals(g=None, show_greet=True):
    """ Call this from main interactive module as
          _init_pyHegel_globals(globals())
        or simply
          _init_pyHegel_globals()
        which will do the same (it uses the caller's frame globals).
        It is necessary for load to modify the correct environment and
        for instruments_base to find the proper names.
        Setting show_greet to False skips displaying the greetings
    """
    global _globaldict
    if g == None:
        from inspect import currentframe
        frame = currentframe()
        try:
            g = frame.f_back.f_globals
        finally:
            del frame # this is to break cyclic references, see inspect doc
    _globaldict = g
    instruments_base._globaldict = g
    if show_greet:
        _greetings()

def _greetings():
    import pyHegel
    print '\n\n---------'
    print textwrap.dedent("""\
            pyHegel {} Copyright (C) {}
            This program comes with ABSOLUTELY NO WARRANTY.
            This is free software, and you are welcome to redistribute it
            under certain conditions.
            See files COPYING and COPYING.LESSER for detail or see
            <http://www.gnu.org/licenses/>.""".format(pyHegel.__version__, pyHegel.__copyright__))
    print '\nFor available commands, type "help_pyHegel()"'
    print '---------\n\n'


def help_pyHegel():
    """
    Available commands:
        set
        get
        getasync
        move
        copy
        spy
        sweep
        sweep_multi
        record
        trace
        snap
        scope
        _process_filename
        use_sweep_path
        make_dir
        readfile
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
        load_all_usb
        load_all_gpib
        task
        top
        kill
        quiet_KeyboardInterrupt
        _faster_timer
        test_gpib_srq_state
        All the commands in util (savefig, merge_pdf, ...)
    Available instruments:
        sweep
        clock
    The scipy.constants are available as C

    You can always stop editing a line or running a command by pressing
    CTRL-C. However, when possible, it is better to stop a sweep or a record
    by using the abort button of the trace.

    Examples of commands in ipython:
        # Remember you can use arrows to explore the history and
        # press tab to see all possible options. For example
        # type "sweep." then press the tab key.
        # these load use information in the local_config file
        load()
        load('yo1 dmm2')
        ;load yo2 dmm2 pna1
        load_all_usb()
        load_all_gpib()
        # or load instruments directly
        yo1 = instruments.yokogawa_gs200('USB0::0x0B21::0x0039::91KB55555')
        # or using the auto loader
        yo1 = instruments.visaAutoLoader('USB0::0x0B21::0x0039::91KB55555')
        # For gpib you can use either the visa address 'GPIB0::3' or for bus 0 just the integer
        dmm2 = instruments.visaAutoLoader(3)
        iprint yo1
        get yo1
        get yo1.range
        # using alias
        set yo1, 0.01
        # now the same but using the device directly instead of through alias
        set yo1.level, 0.01
        iprint dmm1
        dmm1?
        dmm1.fetch?
        get dmm1
        # Note that ipython can automatically insert parentesis so the following
        # two lines produce the same result.
        get dmm1.readval
        get(dmm1.readval)
        v=get(dmm1.readval)
        v2=get(pna1.readval, filename='Test-%T.txt', unit='db_deg')
        make_dir 'C:/data/testdir/%D'
        iprint sweep
        get sweep.path
        sweep yo1, -1,1,11, 'Test-%T.txt', out=dmm1
        sweep yo2, -1,1,11, 'Test-{next_i:02}.txt', out=[dmm1, dmm2, pna1.readval], updown=True, async=True
        # magic functions (don't need quotes)
        pwd
        cd c:/data
        #end session properly so command lines are saved
        quit()
        exit()
        # or type CTRL-D
    """
    print help_pyHegel.__doc__

def reset_pyHegel():
    """
       Resets pyHegel
       You need to reload instruments and readjust the sweep devices (like sweep.path)
       after calling this.

       can be called in ipython command line like:
         /reset_pyNoise
    """
    reload(traces.config)
    reload(traces.qt_wrap)
    reload(traces.kbint_util)
    reload(traces)
    reload(instruments_base.visa_wrap)
    instruments_registry.clean_instruments()
    reload(instruments_registry)
    reload(instruments_base)
    reload(instruments.logical)
    reload(instruments)
    reload(util)
    import pyHegel
    reload(pyHegel)
    reload(sys.modules['pyHegel.commands'])
    from . import main
    reload(main)
    main.reset_start(_globaldict)



def _quiet_KeyboardInterrupt_Handler(self, exc_type, exc_value, traceback, tb_offset=None):
    print '\n ----- KeyboardInterrupt:', exc_value

def quiet_KeyboardInterrupt(quiet=True):
    """
    This function with quiet=True (default) will prevent IPython from showing
    the stack trace when interrupting code with CTRL-C.
    """
    try:
        ip = _globaldict['get_ipython']() # starting with ipython 0.11
    except KeyError:
        ip = _globaldict['_ip'] # for ipython 0.10
    if quiet:
        ip.set_custom_exc((KeyboardInterrupt,), _quiet_KeyboardInterrupt_Handler)
    else:
        ip.set_custom_exc((), None)



def _faster_timer(stop=False, period='min'):
    """
    On windows 7 this allows a better time resolution
    The default seems to be 10 ms. With this I can get 1 ms.
    To return the resolution back to the default,
    either close this application or call with stop=True and
    with the same period setting as the previous (stop=False) call.
    """
    lib = ctypes.windll.winmm
    if period == 'min':
        dat_struct = (ctypes.c_uint*2)()
        lib.timeGetDevCaps(dat_struct, ctypes.sizeof(dat_struct))
        period = dat_struct[0]
        print 'Using minimal period of ', period, ' ms'
    if stop:
        ret = lib.timeEndPeriod(period)
    else:
        ret = lib.timeBeginPeriod(period)
    if ret != 0:
        print 'Error(%i) in setting period'%ret



class _Clock(instruments.BaseInstrument):
    def _time_getdev(self):
        """ Get UTC time since epoch in seconds """
        return time.time()
    def _create_devs(self):
        self._devwrap('time')
        self.alias = self.time
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
clock = _Clock()


def _get_dev_kw(dev, **extra_kw):
    """
    Takes dev as a device or as a tuple of (dev, dict)
    where dict contains options that can be overriden by extra_kw
    returns a tuple of dev, options_dict
    """
    if isinstance(dev, tuple):
        base_kw = dev[1].copy()
        base_kw.update(extra_kw)
        extra_kw = base_kw
        dev = dev[0]
    return dev, extra_kw

def _get_extra_confs(extra_conf):
    if extra_conf is None:
        return []
    if not isinstance(extra_conf, (list, tuple)):
        extra_conf = [extra_conf]
    formats = []
    for x in extra_conf:
        if isinstance(x, basestring):
            f = dict(base_hdr_name='comment', base_conf=x)
        else:
            dev, kwarg = _get_dev_kw(x)
            dev.force_get()
            hdr = dev.getfullname()
            f = dev.getformat(**kwarg)
            f['base_conf'] = instruments_base._get_conf_header(f)
            f['base_hdr_name'] = hdr
        formats.append(f)
    return formats


def _getheaders(setdev=None, getdevs=[], root=None, npts=None, extra_conf=None):
    hdrs = []
    graphsel = []
    count = 0
    formats = []
    if extra_conf != None and not isinstance(extra_conf, list):
        extra_conf = [extra_conf]
    elif extra_conf == None:
        extra_conf = []
    else:
        extra_conf = extra_conf[:] # make a copy so we can change it locally
    if setdev != None:
        if not isinstance(setdev, list):
            setdev = [setdev]
        for s in setdev:
            dev, kwarg = _get_dev_kw(s)
            hdrs.append(dev.getfullname())
            count += 1
            extra_conf.append(s)
    reuse_dict = {}
    for dev in getdevs:
        dev, kwarg = _get_dev_kw(dev)
        reuse = reuse_dict.get(dev,0)
        reuse_dict[dev] = reuse + 1
        dev.force_get()
        hdr = dev.getfullname()
        if reuse > 0:
            hdr += '%i'%(reuse+1)
        f = dev.getformat(**kwarg)
        f['basename'] = _dev_filename(root, hdr, npts, 0, append=f['append'])
        f['base_conf'] = instruments_base._get_conf_header(f)
        f['base_hdr_name'] = hdr
        formats.append(f)
        multi = f['multi']
        graph = f['graph']
        # be careful about type, because True == 1 and False == 0 are both
        # True in python
        #if isinstance(graph, bool) and graph == False:
        if graph is False:
            graph = []
        elif graph is True:
            if isinstance(multi, list):
                graph = range(len(multi))
            else:
                graph = [0]
        elif not isinstance(graph, list):
            graph = [graph]
        graph_list = [ g+count for g in graph]
        graphsel.extend(graph_list)
        if f['file'] != True and isinstance(multi, list):
            hdr_list = [ hdr+'.'+h for h in multi]
            c = len(hdr_list)
            hdrs.extend(hdr_list)
            count += c
        else:
            hdrs.append(hdr)
            count += 1
    formats.extend(_get_extra_confs(extra_conf))
    return hdrs, graphsel, formats

def _dev_filename(root, dev_name, npts, reuse, append=False):
    if root==None:
        name = time.strftime('%Y%m%d-%H%M%S.txt')
        root = use_sweep_path(name)
    if npts == None:
        maxn = 99999
    else:
        maxn = npts-1
    if npts == 1:
        maxn = 1
    root = os.path.abspath(root)
    root, ext = os.path.splitext(root)
    dev_name = dev_name.replace('.', '_')
    if reuse > 0:
        dev_name += '%i'%(reuse+1)
    if append:
        return root + '_'+ dev_name + ext
    n = int(np.log10(maxn))+1
    return root + '_'+ dev_name+'_%0'+('%ii'%n)+ext

def _readall(devs, formats, i, async=None):
    if devs == []:
        return []
    ret = []
    for dev, fmt in zip(devs, formats):
        dev, kwarg = _get_dev_kw(dev)
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
        if isinstance(val, (list, tuple, np.ndarray, dict)):
            if isinstance(val, dict):
                val = val.values()
            if isinstance(fmt['multi'], list):
                ret.extend(val)
            else:
                ret.append(i)
                instruments_base._write_dev(val, filename, format=fmt, first= i==0)
        else:
            ret.append(val)
    ret = instruments_base._writevec_flatten_list(ret)
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
#                ('head1', 'head2')   like multi=True (save to file) but provides headers
#          graph=[1,2]                This selects the values to graph (mostly useful for multi)
#                                     [] means not to show anything.
#                                     It could also be a single value. To show a single element.
#                                     True shows everything, False shows nothing (same as [])
#          graph=True/False           When file is True, This says to graph the return value or not
#                                       TODO implement this.
#                                            also allow to select column to plot in multi files
#                                            use something like traces.TraceWater
#          append=True                Dump the data on a line in the file
#          xaxis=True                 When multi=True or ('col1', 'col2', 'col3', ...)
#                                     means the first column is the xscale
#          xaxis=False                the first column is data and not the xscale
#                                     In both case the get has an override called xaxis
#                                     which can change it.
#          xaxis=None                 Means there is no xscale available.
#          header=['line1', 'line2']  Stuff to dump at head of new file
#                                       it can also be a function that returns the proper list of strings
#                                       the functions defaults to instr._current_config if available
#          bin=False/'.npy'/'.npz'    Dump data in binary form.
#              '.raw'/'.png'           .npy is numpy format, .npz is from numpy.savez_compressed
#              '.ext'/...              All of them change the extension of the file except
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

def _write_conf(f, formats, extra_base=None, **kwarg):
    if extra_base != None:
        extra = dict(base_hdr_name=extra_base, base_conf=[repr(kwarg)])
        formats = formats[:] # make a copy
        formats.append(extra)
    for fmt in formats:
        conf = fmt['base_conf']
        hdr = fmt['base_hdr_name']
        if conf:
            f.write('#'+hdr+':=')
            if isinstance(conf, list):
                for c in conf:
                    f.write(' '+c+';')
            else:
                f.write(' '+conf)
            f.write('\n')

def dump_conf(f, setdevs=None, getdevs=[], extra_conf=None):
    """ This functions dumps the settings of the list of devices and extra_conf
        in the same way sweep and record does.
        You can set a single setdevs, a list of setdevs and/or a list of getdevs.
        Use setdevs for values you set (like in a sweep).
        To write data in the file, including headers, use pyHegel.commands.writevec
        Returns a list of hdrs (which are the name of the devices) that can be used
        to create column headers.
    """
    hdrs, graphsel, formats = _getheaders(setdevs, getdevs, extra_conf=extra_conf)
    _write_conf(f, formats)
    return hdrs


class _time_check(object):
    def __init__(self, delay=10):
        self.last_update = time.time()
        self.delay = delay
    def check(self):
        now = time.time()
        if now > self.last_update + self.delay:
            self.last_update = now
            return True
        return False


class _Sweep(instruments.BaseInstrument):
    # This MemoryDevice will be shared among different instances
    # So there should only be one instance of this class
    #  Doing it this way allows the instr.dev = val syntax
    before = instruments.MemoryDevice(doc="""
      When this is a string (not None), it will be executed after the new values is
      set but BEFORE the out list is read.
      If you only want a delay, you can also change the beforewait device.
      The variables i, v and vv represent the current cycle index, the current set value
      (the last one for multi sweep), and a vector of all set values.
      The variable fwd is forward(True)/reverse(False) state of v.
      """)
    beforewait = instruments.MemoryDevice(0.02, doc="""
      Wait after the new value is set but before the out list is read.
      It occurs immediately after the commands in the before device are executed.
      It defaults to 0.02s which is enough for the GUI to update.
      If you set it to 0 it will be a little faster but the GUI (traces) could
      freeze.

      You can always read a value with get. Or to prevent actually talking to
      the device (and respond faster) you can obtain the cache value with
      dev.getcache()
      """) # provide a default wait so figures are updated
    after = instruments.MemoryDevice(doc="""
      When this is a string (not None), it will be executed AFTER the out list is read
      but before the next values is set.
      The variables i, v and vv represent the current cycle index, the current set value
      (the last one for multi sweep), and a vector of all set values.
      The variable fwd is forward(True)/reverse(False) state of v.
      The variable vars contain all the values read in out. It is a flat list
      that contains all the data to be saved on a row of the main file.
      Note that v and vals[0] can be different for devices that use setget
      (those that perform a get after a set, because the instrument could be
      changing/rounding the value). v is the asked for value.

      You can always read a value with get. Or to prevent actually talking to
      the device (and respond faster) you can obtain the cache value with
      dev.getcache()
      """)
    out = instruments.MemoryDevice(doc="""
      This is the list of device to read (get) for each iteration.
      It can be a single device (or an instrument if it has an alias)
      It can be a list of devices like [dev1, dev2, dev3]
      If optional parameters are needed for a device, it can be enterred as
      a tuple (dev, devparam) where devparam is a dictionnary of optionnal
      parameters.
      For example you could have (acq1.readval, dict(ch=1, unit='V'))
      or another way (acq1.readval, {'ch':1, 'unit':'V'})
      With more than one device that would be:
           [dev1, (dev2, dict(dev2opt1=value1, dev2opt2=value2)), dev3]
      Additional parameter are:
          graph:  it allows the selection of which column of multi-column
                  data to graph. It can be a list of column index.
                  Ex: graph=[0,2,3]
                  would display the first, third and fourth column of this device.
                  It can also be a single index i (which will be the same as [i])
                  It can also True (show all), False (show none, the same as [])
          bin:    To overwrite filesave format/extension can be
                  any extension like '.bin' or false to save as text.
                  with '.npy', it is saved in npy format
                  with '.npz', it is saved using numpy.savez_compressed
    """)
    path = instruments.MemoryDevice('')
    graph = instruments.MemoryDevice(True)
    updown = instruments.MemoryDevice(['Fwd', 'Rev'], doc="""
       This parameter selects the mode used when doing updown sweeps.
       When given a list of 2 strings, these will be included in the filename
       (just before the extension by default). The 2 strings should be different.
       One string can be the empty one: ''

       The parameter can also be None. In that case a single file is saved containing
       both the up and down sweep.
    """)
    next_file_i = instruments.MemoryDevice(0,doc="""
    This number is used, and incremented automatically when {next_i:02} is used (for 00 to 99).
     {next_i:03}  is used for 000 to 999, etc
    """)
    def execbefore(self, i, fwd, v, vv):
        b = self.before.get()
        if b:
            exec b
    def execafter(self, i, fwd, v, vv, vals):
        b = self.after.get()
        if b:
            exec b
    def _fn_insert_updown(self, filename):
        fmtr = string.Formatter()
        present = False
        for txt, name, spec, conv in fmtr.parse(filename):
            if name == 'updown':
                present = True
        if not present:
            base, ext = os.path.splitext(filename)
            filename = base+'{updown}'+ext
        return filename
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
        self._lastnames = []
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('before', 'after', 'beforewait')
    def __repr__(self):
        return '<sweep instrument>'
    def _find_span(self, dev, logspace, start, stop, npts):
        """
        Finds the proper span. Also checks the validity of start/stop values.
        """
        dolinspace = True
        negative = False
        if isinstance(start, (list, np.ndarray)):
            span = np.asarray(start)
            # make start stop extremes for now
            start = np.min(span)
            stop = np.max(span)
            npts = len(span)
            dolinspace = False
        dev_orig = dev
        dev, dev_opt = _get_dev_kw(dev)
        try:
            dev.check(start, **dev_opt)
            dev.check(stop, **dev_opt)
        except ValueError:
            raise ValueError('Wrong start or stop values (outside of valid range) for dev=%s. Aborting!'%dev)
        # now make start stop of list, first and last values
        if not dolinspace:
            start = span[0]
            stop = span[-1]
        npts = int(npts)
        if npts < 1:
            raise ValueError, 'npts needs to be at least 1'
        if dolinspace:
            if logspace:
                if start == 0. or stop == 0.:
                    raise ValueError("Neither start nor stop can be 0. when using logspace for dev=%s."%dev)
                if start < 0.:
                    negative = True
                    start *= -1.
                    stop *= -1.
                if stop < 0:
                    raise ValueError('Both start and stop need to have the same sign when using logspace for dev=%s.'%dev)
                span = np.logspace(np.log10(start), np.log10(stop), npts)
                if negative:
                    span *= -1.
            else:
                span = np.linspace(start, stop, npts)
        if instruments_base.CHECKING:
            # For checking only take first and last values
            span = span[[0,-1]]
        return span, start, stop, npts, dev_orig, dev, dev_opt, negative
    def _get_filenames(self, filename, updown=False, start=None, stop=None, npts=None):
        updown_str = self.updown.getcache()
        updown_same = False
        if updown_str == None:
            updown_str = ['', '']
            updown_same = True
        fullpath = None
        fullpathrev = None
        fwd = True
        self._lastnames = []
        if filename != None:
            basepath = use_sweep_path(filename)
            if updown == True:
                basepath = self._fn_insert_updown(basepath)
            ind = 0
            if updown == -1:
                ind = 1
                fwd = False
            now = time.time()
            with self._lock_instrument:
                # lock to protect manipulation of next_file_i across threads
                fullpath, unique_i = _process_filename(basepath, now=now, start=start, stop=stop, npts=npts, updown=updown_str[ind])
                self._lastnames.append(fullpath)
                if updown == True and not updown_same:
                    ni = self.next_file_i.getcache()-1
                    fullpathrev, unique_i = _process_filename(basepath, now=now, next_i=ni, start_i=unique_i, search=False,
                                                    start=start, stop=stop, npts=npts, updown=updown_str[1])
                    self._lastnames.append(fullpathrev)
            filename = os.path.basename(fullpath)
        return filename, fullpath, fullpathrev, fwd, updown_same
    def _get_extraconf(self, extra_conf):
        if extra_conf == None:
            extra_conf = [sweep.out]
        elif not isinstance(extra_conf, list):
            extra_conf = [extra_conf, sweep.out]
        else:
            extra_conf = extra_conf[:] # make a copy so we don't change the user parameters
            extra_conf.append(sweep.out)
        return extra_conf

    def _init_graph(self, title, filename, hdrs, x_idx, span, graphsel, logspace, negative, title_pre='Sweep: '):
        t = traces.Trace()
        if title == None:
            title = filename
        if title == None:
            title = str(self._sweep_trace_num)
        self._sweep_trace_num += 1
        t.setWindowTitle(title_pre+title)
        if logspace and negative:
            t.setLim(-span)
        else:
            t.setLim(span)
        if len(graphsel) == 0:
            gsel = _itemgetter(x_idx)
        else:
            gsel = _itemgetter(*graphsel)
        hdrs_leg = hdrs[:] #copy
        if logspace and negative:
            hdrs_leg[x_idx] = '- '+hdrs_leg[x_idx]
        t.setlegend(gsel(hdrs_leg))
        t.set_xlabel(hdrs_leg[x_idx])
        if logspace:
            t.set_xlogscale()
        return t, gsel

    def _do_inner_loop(self, iter_info, sets, devs, cformats, fobj, async, trace_obj, negative, gsel, clf=False, printit=False):
        # iter_n is used for filenames and exec_before/after (could depend on separate fwd/rev files)
        # iter_partial between 1 and iter_total: they are both used for progress update.
        #   iter_partial can sometimes be iter_n+1
        # cfwd is True when we are currently doing a forward sweep (uses for exec before/after)
        iter_n, iter_part, iter_total, cfwd = iter_info
        tme = clock.get()
        vv = []
        iv = []
        bwait = 0.
        for dev, dev_opt, v, beforewait, doset in zip(*sets):
            vv.append(v)
            if doset:
                dev.set(v, **dev_opt) # TODO replace with move
                bwait = max(bwait, beforewait)
            iv.append( dev.getcache() )# in case the instrument changed the value
        if printit:
            printit('Sweep part: %3i/%-3i   %s'%(iter_part, iter_total, vv))
        self.execbefore(iter_n, cfwd, v, vv)
        wait(bwait)
        if async:
            vals = _readall_async(devs, cformats, iter_n)
        else:
            vals = _readall(devs, cformats, iter_n)
        self.execafter(iter_n, cfwd, v, vv, iv+vals+[tme])
        if fobj:
            writevec(fobj, iv+vals+[tme])
        if trace_obj is not None:
            giv = iv[-1]
            gvals = gsel(iv+vals)
            if negative: #for when doing negative logspace
                giv = -giv
                ivn = iv[:]
                ivn[-1] = giv
                gvals = gsel(ivn+vals)
            if clf:
                trace_obj.setPoints([giv], np.array([gvals]).T)
            else:
                trace_obj.addPoint(giv, gvals)
            _checkTracePause(trace_obj)
            if trace_obj.abort_enabled:
                return 'break'
        return None


# TODO deal with dev set that return multiple values (like some logical devices)
#      properly handle progress update after a stop with a graph. It seems to
#        get stuck until a collect_garbage is done.
    def __call__(self, dev, start, stop=None, npts=None, filename='%T.txt', rate=None,
                  close_after=False, graph=None, title=None, out=None, extra_conf=None,
                  async=False, reset=False, logspace=False, updown=False, first_wait=None, beforewait=None,
                  progress=True):
        """
            Usage:
                dev is the device to sweep. For more advanced uses (devices with options),
                      see sweep.out documentation.
                To define sweep either
                  set start, stop and npts (then uses linspace internally
                                                       or logspace)
                  or just set start with a list of values

                filename to use
                    use %T: for date time string (20120115-145030)
                        %t: for time string only
                        %D: for date string
                        %02i: for unique 2 digit increment (00, 01 ...)
                              %03i for   3 digits
                              The unicity is only checked for the first file of updown.
                              The search always start at 0.
                              It is kept the same for the second one.
                     Also available are {datetime}, {date}, {time}
                                        {start}, {stop}, {npts}, {updown}
                                        {next_i:02}
                      these use the str.format replacements.
                        {next_i:02}, {next_i:03} is replaced by sweep.next_file_i
                           with the correct number of digit.
                           When used, sweep.next_file_i is auto incremented
                           to the next value
                      The filename, when relative (does not start with / or \)
                      is always combined with the path device.
                      The global variable sweep._lastnames is a list of the last
                      filenames used.
                rate: unused
                close_after: automatically closes the figure after the sweep when True
                graph: If graph is True, a figure is plotter while taking data. When
                       False no figure is created. If graph is None (default) the value
                       from the sweep.graph device is used.
                title: string used for window title
                out: list of devices to read. Can also be a single device.
                     This has the same syntax and overrides sweep.out.
                     See sweep.out documentation for more advanced uses
                     (devices with options).
                extra_conf: list (or a single element) of extra devices to dump configuration
                            headers at head of data file. Instead of a device, it can also be
                            a string that will be dumped as is in the header with a comment:= prefix.
                            (The configuration for the sweep device and all the out
                             devices is automatically inserted).
                async: When True, enables async mode (waiting on devices is done in
                        parallel instead of consecutivelly.) This saves time.
                reset: After the sweep is completed, the dev is returned to the
                       first value in the sweep list if set to True. If a value is given it
                       is set to that value. When False (default) or None the last value of
                       the sweep is kept.
                logspace: When true, the npts between start and stop are separated
                           exponentially (so it for a nice linear spacing on a log scale)
                          It uses np.logspace internally but start and stop stay the
                          complete values contrary to np.logspace that uses the exponents.
                updown: When True, the sweep will be done twice, the second being in reverse.
                        The way the data is saved depends on the updown device.
                        If it is -1, only do the reverse sweep. Filename is not changed by default.
                first_wait: when set to a value is an extra wait time in seconds that is added
                            after setting the first value. Use it when the first value produces
                            a large change that can temporarily overload some instruments
                            like lock-ins.
                beforewait: it is the time to wait between setting the device and starting to
                            read the out devices. When None it uses de sweep.beforewait device value.
                progess: When True, the output will display the iteration status after 10s intervals.
                The time column in the file is seconds since the epoch and represents the time at the
                start of the current point (just before doing the set). See time.ctime to convert it to
                text.
            SEE ALSO the sweep devices: before, after, beforewait, graph.
        """
        span, start, stop, npts, dev_orig, dev, dev_opt, negative = self._find_span(dev, logspace, start, stop, npts)
        filename, fullpath, fullpathrev, fwd, updown_same = self._get_filenames(filename, updown, start, stop, npts)
        if beforewait is None:
            beforewait = self.beforewait.get()
        reset_raw = reset
        if isinstance(reset, bool):
            if reset:
                reset = span[0] # return to first value
            else:
                reset = None
        devs = self.get_alldevs(out)
        extra_conf = self._get_extraconf(extra_conf)
        npts_total = npts
        if updown == True:
            npts_total *= 2
        if updown == True and updown_same:
            npts = 2*npts
        hdrs, graphsel, formats = _getheaders(dev_orig, devs, fullpath, npts, extra_conf=extra_conf)
        if fullpathrev != None:
            hdrsrev, graphselrev, formatsrev = _getheaders(dev_orig, devs, fullpathrev, npts, extra_conf=extra_conf)
        else:
            formatsrev = formats
        # hdrs and graphsel are the same as the rev versions
        if graph is None:
            graph = self.graph.get()
        if graph:
            t, gsel = self._init_graph(title, filename, hdrs, 0, span, graphsel, logspace, negative, title_pre='Sweep: ')
        else:
            t = gsel = None
        try:
            f = None
            frev = None
            if filename != None:
                # Make it unbuffered, windows does not handle line buffer correctly
                f = open(fullpath, 'w', 0)
                _write_conf(f, formats, extra_base='sweep_options', async=async, reset=reset_raw, start=start, stop=stop,
                            updown=updown, beforewait=beforewait, first_wait=first_wait)
                writevec(f, hdrs+['time'], pre_str='#')
                if fullpathrev != None:
                    frev = open(fullpathrev, 'w', 0)
                    _write_conf(frev, formatsrev, extra_base='sweep_options', async=async, reset=reset_raw, start=start, stop=stop,
                                updown=updown, beforewait=beforewait, first_wait=first_wait)
                    writevec(frev, hdrs+['time'], pre_str='#')
                else:
                    frev = f
            ###############################
            # Start of loop
            ###############################
            def iterator():
                iter_partial = 0
                ioffset = 0
                clf = False
                #dev, dev_opt, v, beforewait, doset
                bwait = [beforewait]
                sets = [[dev], [dev_opt], [], [], [True]]
                cycle_list = [(fwd, f, formats)]
                if updown == True:
                    cycle_list = [(True, f, formats), (False, frev, formatsrev)]
                for cfwd, cf, cformats in cycle_list:
                    cycle_span = span
                    if not cfwd: # doing reverse
                        cycle_span = span[::-1]
                    for i,v in enumerate(cycle_span):
                        sets[2] = [v]
                        if iter_partial == 0 and first_wait != None:
                            sets[3] = [beforewait + first_wait]
                        else:
                            sets[3] = bwait
                        iter_partial += 1
                        iter_info = i+ioffset, iter_partial, npts_total, cfwd
                        yield iter_info, cf, cformats, sets, clf
                    if updown_same:
                        ioffset = i + 1

            update_check = _time_check(10) # returns True once every 10s
            if progress:
                progress = instruments_base.mainStatusLine.new()
            for iter_info, cf, cformats, sets, clf in iterator():
                printit = progress if progress and update_check.check() else False
                dobreak = self._do_inner_loop(iter_info, sets, devs, cformats, cf, async, t, negative, gsel, clf, printit)
                if dobreak == 'break':
                    break
        except KeyboardInterrupt:
            (exc_type, exc_value, exc_traceback) = sys.exc_info()
            raise KeyboardInterrupt('Interrupted sweep'), None, exc_traceback
        finally:
            if f:
                f.close()
            if fullpathrev != None and frev:
                frev.close()
        if graph and t.abort_enabled:
            raise KeyboardInterrupt('Aborted sweep')
        elif reset != None:
            dev.set(reset, **dev_opt)
        if graph and close_after:
            t = t.destroy()
            del t

    def sweep_multi(self, dev, start, stop=None, npts=None, filename='%T.txt', rate=None,
                  close_after=False, graph=None, title=None, out=None, extra_conf=None,
                  async=False, reset=False, logspace=False, updown=False, first_wait=None, beforewait=None,
                  progress=True, parallel=False):
        """
        The settings for sweep_multi have the same meaning as for the sweep command (see its documention).
        However, many of the settings now require lists (dev, start, stop, npts, logspace, reset, close_after
        first_wait, beforewait). For a N dimensioanl sweep, the need to be lists with N elements.
        For many of them (not dev or start), if they are scalars, they are upgraded to a list with the
        correct number of elements.
        The first element is the slower changing one, the last one is the fastest (the inner loop one)
        close_after except for the first (which closes the window), makes it clear the data once that
        particular sub sweep is done.
        The actual beforewait time used for an iteration will be the max of all the elements that
        are changed for that iteration. Similarly for first_wait, which is used for the first point and
        every time a sweep without updown jumps from last to first point.
        The graph uses the fastest changing value for the x axis.
        Only a single main file is ever created even when using updown (it does not use the sweep.updown device)

        parallel: when True, all the devs are called for each cycle. All the pts are changed in parallel
            so they need to have the same number of elements.
        """
        multiN = len(dev)
        def mklist(v):
            v = v if isinstance(v, (list, tuple, np.ndarray)) else [v]*multiN
            if len(v) != multiN:
                raise ValueError('A parameter does not have the correct number of elements')
            return v
        logspace = mklist(logspace)
        npts = mklist(npts)
        stop = mklist(stop)
        updown = mklist(updown)
        first_wait = mklist(first_wait)
        if beforewait is None:
            beforewait = self.beforewait.get()
        beforewait = mklist(beforewait)
        fbwait = []
        for b, f in zip(beforewait, first_wait):
            if f is None:
                f = b
            else:
                f = f+b
            fbwait.append(f)
        first_wait = fbwait
        del fbwait
        close_after = mklist(close_after)
        rate = mklist(rate)
        reset_raw = reset
        reset = mklist(reset)
        spanl = []
        startl = []
        stopl = []
        dev_origl = []
        devl = []
        dev_optl = []
        negativel = []
        for idev, ilogspace, istart, istop, inpts in zip(dev, logspace, start, stop, npts):
            span, start, stop, npts, dev_orig, dev, dev_opt, negative = self._find_span(idev, ilogspace, istart, istop, inpts)
            spanl.append(span)
            startl.append(start)
            stopl.append(stop)
            dev_origl.append(dev_orig)
            devl.append(dev)
            dev_optl.append(dev_opt)
            negativel.append(negative)
        def conv_reset(reset, span):
            if isinstance(reset, bool):
                if reset:
                    reset = span[0] # return to first values
                else:
                    reset = None
            return reset
        reset = [conv_reset(r, s) for r, s in zip(reset, spanl)]
        spans = []
        fwdrev = []
        both_updown = []
        data_row_shape = []
        for ud, span in zip(updown, spanl):
            b = False
            L = len(span)
            if ud == True:
                b = True
                span = np.concatenate( (span, span[::-1]) )
                f = [True]*L + [False]*L
                data_row_shape.append(2)
            elif ud == -1:
                span = span[::-1]
                f = [False]*L
            else:
                f = [True]*L
            both_updown.append(b)
            fwdrev.append(f)
            spans.append(span)
            data_row_shape.append(L)
        del spanl
        nptsl = [len(s) for s in spans] # This includes the effect of updown
        if parallel:
            # check all devs have the same number of points
            npts = nptsl[0]
            if any(n != npts for n in nptsl):
                raise ValueError('For parallel, all the npts/updown comnination need to be the same length')
            npts_total = npts
        else:
            npts_total = np.asarray(nptsl).prod()
        # We never use updown filenames in multiN. Everything in one base file.
        # start, stop and npts are the lists
        filename, fullpath, fullpathrev, fwd, updown_same = self._get_filenames(filename, False, startl, stopl, npts_total)
        devs = self.get_alldevs(out)
        extra_conf = self._get_extraconf(extra_conf)
        hdrs, graphsel, formats = _getheaders(dev_origl, devs, fullpath, npts_total, extra_conf=extra_conf)
        if graph is None:
            graph = self.graph.get()
        if graph:
            # We graph using last span
            t, gsel = self._init_graph(title, filename, hdrs, multiN-1, spans[-1], graphsel, logspace[-1], negativel[-1], title_pre='Sweep_multi: ')
        else:
            t = gsel = None
        try:
            f = None
            if filename != None:
                # Make it unbuffered, windows does not handle line buffer correctly
                f = open(fullpath, 'w', 0)
                _write_conf(f, formats, extra_base='sweep_multi_options', async=async, reset=reset_raw, start=start, stop=stop,
                                updown=updown, beforewait=beforewait, first_wait=first_wait, parallel=parallel)
                # This needs to match the line in util.readfile
                read_dims = 'readback numpy shape for line part: '+(', '.join([str(n) for n in data_row_shape]))
                writevec(f, [read_dims], pre_str='#')
                writevec(f, hdrs+['time'], pre_str='#')

            ###############################
            # Start of loop
            ###############################
            if parallel:
                def iterator():
                    #dev, dev_opt, v, beforewait, doset
                    sets = [devl, dev_optl, [], [], [True]*multiN]
                    for i in range(npts_total):
                        vs = []
                        for cfwd, span in zip(fwdrev, spans):
                            vs.append(span[i])
                            fwd = cfwd[i]
                        # fwd is last cfwd
                        sets[2] = vs
                        if i == 0:
                            sets[3] = first_wait
                        else:
                            sets[3] = beforewait
                        iter_info = i, i+1, npts_total, fwd
                        yield iter_info, f, formats, sets, False
            else:
                def js_iterator():
                    """ This increments the last element of js but
                        carries to previous element any carryover above
                        npts
                    """
                    js = [0]*multiN
                    while True:
                        yield js
                        i = multiN -1
                        while i >= 0:
                            js[i] += 1
                            if js[i] >= nptsl[i]:
                                if i == 0:
                                    return # we are done
                                js[i] = 0
                                i -= 1
                            else:
                                break

                def iterator():
                    #dev, dev_opt, v, beforewait, doset
                    sets = [devl, dev_optl, [], [], []]
                    i = 0
                    js = [0]*multiN
                    prev_js = [-1]*multiN
                    for js in js_iterator():
                        doset = []
                        vs = []
                        bwait = []
                        clf = False
                        for k, tmp in enumerate(zip(js, fwdrev, spans)):
                            j, cfwd, span = tmp
                            vs.append(span[j])
                            fwd = cfwd[j]
                            changing =  j != prev_js[k]
                            doset.append(changing)
                            if changing and i != 0 and k+1 < multiN:
                                if close_after[k+1]:
                                    clf = True
                            if changing and j == 0 and not both_updown[k]:
                                bwait.append(first_wait[k])
                            else:
                                bwait.append(beforewait[k])
                        sets[2] = vs
                        sets[4] = doset
                        if i == 0:
                            sets[3] = first_wait
                        else:
                            sets[3] = bwait
                        iter_info = i, i+1, npts_total, fwd
                        yield iter_info, f, formats, sets, clf
                        i += 1
                        prev_js = js[:] # need to make a copy

            update_check = _time_check(10) # returns True once every 10s
            if progress:
                progress = instruments_base.mainStatusLine.new()
            for iter_info, cf, cformats, sets, clf in iterator():
                printit = progress if progress and update_check.check() else False
                dobreak = self._do_inner_loop(iter_info, sets, devs, cformats, cf, async, t, negativel[-1], gsel, clf, printit)
                if dobreak == 'break':
                    break
        except KeyboardInterrupt:
            (exc_type, exc_value, exc_traceback) = sys.exc_info()
            raise KeyboardInterrupt('Interrupted sweep_multi'), None, exc_traceback
        finally:
            if f:
                f.close()
        if graph and t.abort_enabled:
            raise KeyboardInterrupt('Aborted sweep_multi')
        else:
            for dev, dev_opt, r in zip(devl, dev_optl, reset):
                if r is not None:
                    dev.set(r, **dev_opt)
        if graph and close_after[0]:
            t = t.destroy()
            del t


sweep = _Sweep()
sweep_multi = sweep.sweep_multi


def use_sweep_path(filename):
    """
    This functions transforms the filename using sweep.path if necessary
    like the default transformation used in get(filename), readfile, sweep, record...
    """
    filename = os.path.join(sweep.path.get(), filename)
    return filename


def readfile(filename, nojoin=False, prepend=None, getnames=False, getheaders=False, csv='auto', dtype=None):
    global _readfile_lastnames, _readfile_lastheaders, _readfile_lasttitles
    if not nojoin and prepend == None:
        prepend = sweep.path.get()
    return util.readfile(filename, prepend=prepend, getnames=getnames, getheaders=getheaders, csv=csv, dtype=dtype)
readfile.__doc__ = """
    By default the path is joined with sweep.path (unless absolute).
    It uses prepend internally.
    nojoin set to True prevents this. Setting prepend also overrides this.

    """+util.readfile.__doc__



###  set overides set builtin function
def set(dev, *value, **kwarg):
    """
       Change the value of device dev (or the alias for an instrument).
       The options for the device are listed as keyword arguments (**kwarg).
       Example:
           set(yo1, 1) # uses yo1.alias which is yo1.level
           set(yo1.range, 10)
           set(pnax.marker_x, 1e9, mkr=3) # changes marker 3 to 1 GHz

       Note that dev can also be a tuple like in sweep.out
    """
    dev, kwarg = _get_dev_kw(dev, **kwarg)
    dev.set(*value, **kwarg)

def move(dev, value, rate):
    """
       NOT IMPLEMENTED
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
    if not isinstance(devs, list):
        devs = [devs]
    try:
        while True:
            v=[]
            for dev in devs:
                dev, kwarg = _get_dev_kw(dev)
                v.append(dev.get(**kwarg))
            print >>sys.stderr, v
            wait(interval)
    except KeyboardInterrupt:
        print 'Interrupting spy'

class _Snap(object):
    def __init__(self):
        self.filename = None
        self.out = None
        self.async = False
        self.cycle = 0
        self.formats = None
        self._lock_instrument = instruments_base.Lock_Instruments()
        self._lock_extra = instruments_base.Lock_Extra()
    @instruments_base.locked_calling
    def __call__(self, out=None, filename=None, async=None, append=True):
        """
        This command dumps a bunch of values to a file.
        The first call initializes a filename, list of devices
        Subsequent call can have no parameters and the previously selected
        devices will be appended to the filename.
        Changing the device list, will append a new header and change the following calls.
        The filename uses the sweep.path directory.
        Async unset (None) will use the last one async mode (which starts at False)
        With append=True and opening an already existing file, the data is appended
        otherwise the file is truncated

        If needed you can create more than one snap object. They will remember different
        defaults:
            snap1 = _Snap()
            snap2 = _Snap()
            snap1(dev1, 'file1.txt')
            snap2([dev2, dev3], 'file2.txt')
            snap1()
            snap2()
        """
        new_out = False
        new_file = False
        if async == None:
            async = self.async
        else:
            self.async = async
        new_file_mode = 'w'
        if append:
            new_file_mode = 'a'
        if out == None:
            out = self.out
        elif out != self.out:
            new_out = True
            self.out = out
        if out == None:
            raise ValueError, 'Snap. No devices set for out'
        if filename != None:
            filename = use_sweep_path(filename)
            filename, unique_i = _process_filename(filename)
        if filename == None:
            filename = self.filename
        elif filename != self.filename:
            self.filename = filename
            new_file = True
            new_out = True
            self.cycle = 0
        if filename == None:
            raise ValueError, 'Snap. No filename selected'
        if new_file:
            f = open(filename, new_file_mode, 0)
        else:
            f = open(filename, 'a', 0)
        if new_out:
            hdrs, graphsel, formats = _getheaders(getdevs=out, root=filename)
            self.formats = formats
            _write_conf(f, formats, extra_base='snap_options', async=async)
            writevec(f, ['time']+hdrs, pre_str='#')
        else:
            formats = self.formats
        tme = clock.get()
        i = self.cycle
        if async:
            vals = _readall_async(out, formats, i)
        else:
            vals = _readall(out, formats, i)
        self.cycle += 1
        writevec(f, [tme]+vals)
        f.close()

snap = _Snap()

def _record_execafter(command, i, vals):
    exec command


_record_trace_num = 0
def record(devs, interval=1, npoints=None, filename='%T.txt', title=None, extra_conf=None, async=False, after=None):
    """
       record to filename (if not None) the values from devs
         uses sweep.path
       Also display it on a figure
       interval is in seconds
       npoints is max number of points. If None, it will only stop
        on CTRL-C...
       filename, title, extra_conf and async behave the same way as for sweep.
       However filename will not handle the {start}, {stop}, {npts}, {updown} options.

       after is a string to be executed after every iteration.
       The variables i represent the current cycle index.
       The variable vars contain all the values read. It is a flat list
       that contains all the data to be saved on a row of the main file.

       In after, you can always read a value with get. Or to prevent actually talking to
       the device (and respond faster) you can obtain the cache value with
       dev.getcache()
    """
    global _record_trace_num
    # make sure devs is list like
    if not isinstance(devs, list):
        devs = [devs]
    t = traces.Trace(time_mode=True)
    fullpath = None
    if filename != None:
        fullpath = use_sweep_path(filename)
        fullpath, unique_i = _process_filename(fullpath)
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
    try:
        f = None
        if filename != None:
            # Make it unbuffered, windows does not handle line buffer correctly
            f = open(fullpath, 'w', 0)
            _write_conf(f, formats, extra_base='record options', async=async, interval=interval)
            writevec(f, ['time']+hdrs, pre_str='#')
        i=0
        while npoints == None or i < npoints:
            tme = clock.get()
            if async:
                vals = _readall_async(devs, formats, i)
            else:
                vals = _readall(devs, formats, i)
            if after != None:
                _record_execafter(after, i, [tme]+vals)
            t.addPoint(tme, gsel(vals))
            if f:
                writevec(f, [tme]+vals)
            if t.abort_enabled:
                break
            i += 1
            if npoints == None or i < npoints:
                wait(interval)
            _checkTracePause(t)
    except KeyboardInterrupt:
        (exc_type, exc_value, exc_traceback) = sys.exc_info()
        raise KeyboardInterrupt('Interrupted record'), None, exc_traceback
    finally:
        if f:
            f.close()
    if t.abort_enabled:
        raise KeyboardInterrupt('Aborted record')


def trace(devs, interval=1, title=''):
    """
       same as record(devs, interval, npoints=1000, filename='trace.dat')
    """
    record(devs, interval, npoints=1000, filename='trace.dat', title=title)

def scope(dev, interval=.1, title='', **kwarg):
    """
       It uses the x scale if it is returned by dev.
       interval is in s
       title is for the window title
       kwarg is the list of optional parameters to pass to dev
       example:
           scope(acq1.readval, unit='V') # with acq1 in scope mode
    """
    dev, kwarg = _get_dev_kw(dev, **kwarg)
    t = traces.Trace()
    t.setWindowTitle('Scope: '+title)
    fmt = dev.getformat(**kwarg)
    if fmt['xaxis'] == True:
        xscale_en = True
    else:
        xscale_en = False
    initialized = False
    while True:
        v=dev.get(**kwarg)
        if not initialized:
            initialized = True
            if xscale_en:
                xscale = v[0]
            else:
                xscale = np.arange(v.shape[-1])
            t.setLim(xscale)
        if xscale_en:
            v = v[1:]
        if v.ndim == 1:
            v.shape=(1,-1)
        t.setPoints(xscale, v)
        wait(interval)
        _checkTracePause(t)
        if t.abort_enabled:
            break


def _process_filename(filename, now=None, next_i=None, start_i=0, search=True, **kwarg):
    """
    Returns a filename and an integer with the following replacements:
        %T:   Date-time like 20120301-173000 (march 1st, 2012 at 17:30:00)
        %D:   Just the date part like 20120310
        %t:   Just the time part like 173000
        %i, %01i %02i ...:
              Is replaced by the an integer. When search is True (default)
              The integer is automatically
              incremented in order to prevent collision with existing names.
              The first integer tried is start_i. If set to None, it will
              be the same as next_i
              When using the 0n version, n digit are used, with left padding
              of 0: so %02i produces: 00, 01, 02, 03 ... 09, 10, 11 .. 99, 100
                   and %03i would produce 000, 001 ....
              The integer is returned with the filename
    There are also name replacements. All keyword arguments can be used for
    replacement using the string.format syntax.
    Variables always present:
        {datetime}: same as %T
        {date}:     same as %D
        {time}:     same as %t
        {next_i:02}, {next_i:03} is replaced by next_i with the correct number of
                digit. When next_i is None, the value used is sweep.next_file_i
                When used, even if not None, sweep.next_file_i is auto incremented
                to the next value.

    The now parameter can be used to specify the time in sec since the epoch
    to use. Defaults to now.
    """
    # Use lock to prevent threads from incrementing next_file_i
    # incorrectly.
    with sweep._lock_instrument:
        if next_i == None:
            ni = sweep.next_file_i.getcache()
        else:
            ni = next_i
        auto_si = False
        if start_i == None:
            start_i = ni
            auto_si = True
        filename_i = start_i
        localtime = time.localtime(now)
        datestamp = time.strftime('%Y%m%d', localtime)
        timestamp = time.strftime('%H%M%S', localtime)
        dtstamp = datestamp+'-'+timestamp
        kwarg.update(datetime=dtstamp, date=datestamp, time=timestamp, next_i=ni)
        fmtr = string.Formatter()
        ni_present = False
        si_changed = False
        changed = False
        for txt, name, spec, conv in fmtr.parse(filename):
            if name != None:
                changed = True
            if name == 'next_i':
                ni_present = True
        filename = filename.format(**kwarg)
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
            if search:
                while os.path.exists(filename%filename_i):
                    filename_i += 1
            filename = filename % filename_i
            if auto_si:
                ni = filename_i
            changed = True
            si_changed = True
        if changed:
            print 'Using filename: '+filename
        if ni_present or (auto_si and si_changed):
            sweep.next_file_i.set(ni+1)
        return filename, filename_i


### get overides get the mathplotlib
def get(dev, filename=None, extra_conf=None, **kwarg):
    """
       Get a value from device (or the alias for an instrument)
       When giving it a filename, data will be saved to it
       and the strings uses the following format
                    use %T: for date time string (20120115-145030)
                        %t: for time string only
                        %D: for date string
                        %02i: for unique 2 digit increment (00, 01 ...)
                              %03i for   3 digits
       The path for saving is sweep.path if it is defined otherwise it saves
       in the current directory.

       extra_conf behaves like in sweep.

       The options for the device are listed as keyword arguments (**kwarg).
       Example:
            get(dmm1) # uses dmm1.alias which is dmm1.readval
            # use filename and keyword argument unit with value 'db_deg'
            get(pna1.readval, filename='Test-%T.txt', unit='db_deg')
            # you can have multiple keyword arguments
            get(pna1.readval, unit='db_deg', mem=True)

       Note that dev can also be a tuple like in sweep.out
    """
    dev, kwarg = _get_dev_kw(dev, **kwarg)
    if extra_conf:
        formats = _get_extra_confs(extra_conf)
        f = StringIO.StringIO()
        _write_conf(f, formats)
        kwarg['extra_conf'] = f.getvalue()
        f.close()
    if filename != None:
        dev.force_get()
        filename = use_sweep_path(filename)
        filename, unique_i = _process_filename(filename)
        kwarg.update(filename=filename)
    return dev.get(**kwarg)

def setget(dev, val=None, **kwarg):
    """
    Either calls set or get depending on the presence of a value.
    """
    if val == None:
        return get(dev, **kwarg)
    else:
        set(dev, val, **kwarg)

def getasync(devs, filename=None, **kwarg):
    """
    Performs a get of a list of devices (devs), using the async algorithm.
    Mostly useful for testing.
    """
    if filename != None:
        raise ValueError, 'getasync does not currently handle the filename option'
    if not isinstance(devs, list):
        devs = [devs]
    devs_kw = [_get_dev_kw(dev, **kwarg) for dev in devs]
    for dev, kw in devs_kw:
        dev.getasync(async=0, **kw)
    for dev, kw in devs_kw:
        dev.getasync(async=1, **kw)
    for dev, kw in devs_kw:
        dev.getasync(async=2, **kw)
    ret = []
    for dev, kw in devs_kw:
        ret.append(dev.getasync(async=3, **kw))
    return ret

def make_dir(directory, setsweep=True):
    """
        Creates a directory if it does now already exists
        and changes sweep.path to point there unless
        setsweep is False.

        It recognizes the % format string of _process_filename.
        It is often used to set a directory for the day like:
            make_dir('C:/Projets/UnProjet/Data/%D')
    """
    dirname, unique_i = _process_filename(directory)
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
    for name, value in _globaldict.iteritems():
        if name[0] == '_':
            continue
        if isinstance(value, instruments.BaseInstrument):
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
    for name, value in _globaldict.iteritems():
        if name[0] == '_':
            continue
        if isinstance(value, instruments.BaseDevice):
            print name
            lst += name
    #return lst

def find_all_instruments(use_aliases=True):
    """
        Find all VISA instruments that are connected.

        By default it returns the aliases when available.
        To return the non-aliased names set the use_aliases
        parameter to False.

        Note the the aliases are entered with Agilent Connection Expert
        (or National Instruments Measurement and Automation Explorer (MAX))
    """
    return instruments.find_all_instruments(use_aliases)

test_gpib_srq_state = instruments_base.test_gpib_srq_state

def checkmode(state=None):
    """
       Called with no arguments, returns current checking mode state
       With a boolean, sets the check state
    """
    if state == None:
        return instruments_base.CHECKING
    instruments_base.CHECKING = state

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
        execfile(batchfile, _globaldict)
    except IOError:
        execfile(batchfile+'.py', _globaldict)

def sleep(sec):
    """
       wait seconds... It has a GUI that allows the wait to be paused.
       After resuming, the wait continues (i.e. total
          wait will be pause+sec)
       See also wait
    """
    traces.sleep(sec)


def _load_helper(entry):
    # we will accept a single Instrument or any of the lists
    #  (instrument, ), (instrument, arg_tuple), (instrument, arg_tuple, kwarg_dict)
    # and always returns the latter
    if isinstance(entry, instruments_base.BaseInstrument):
        return entry, (), {}
    elif len(entry) == 1:
        return entry[0], (), {}
    elif len(entry) == 2:
        return entry[0], entry[1], {}
    elif len(entry) == 3:
        return entry
    else:
        raise ValueError('The load_config conf entry (%s) is not in an acceptable format'%entry)

# overrides pylab load (which is no longer implemented anyway)
def load(names=None, newnames=None):
    """
       Uses definitions in local_config to open devices by their
       standard names. By default it produces a variable with that
       name in the global space. If newname is given, it is the name used
       for that new instrument.
       names and newnames can be a string or a list of strings
       They can also be a string with multiple names separated by spaces
        Therefore it can be called like this in ipython
          ,load instr1 newname1
          ;load instr1 instr2 instr3 ....

       Call it with no arguments to get a list of currently
       configured devices.
       See the find_all_instruments command to see the instruments available
       via Visa (GPIB or USB) (Can also use the external Visa explorer from
       Agilent or National Instruments). You can load all known usb instruments
       with the load_all_usb function.

       NOTE: You can always load an instrument manually. You just need to initialize
       the instrument class with the proper address. For example you can replace
        ;load dmm1
       with
        dmm1 = instruments.agilent_multi_34410A(11)
       The class names are showed when running load without arguments.
       For GPIB address you can enter just the address as an integer or the
       full visa name like those returned from find_all_instruments()
    """
    if names == None or (isinstance(names, basestring) and names == ''):
        for name, entry in sorted(local_config.conf.items()):
            instr, para, kwargs = _load_helper(entry)
            if kwargs != {}:
                para = '%s, %s'%(para, kwargs)
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
        instr, param, kwargs = _load_helper(local_config.conf[name])
        if newname == None:
            newname = name
        i = instr(*param, **kwargs)
        _globaldict[newname] = i
        #exec 'global '+newname+';'+newname+'=i'

def load_all_usb():
    """
     This will load all USB instruments found with find_all_instruments
     that exist in load. They need to be defined with a full name (USB::1234::5677...)
     and not an alias.
    """
    found_instr = find_all_instruments(False)
    found_usb = [_normalize_usb(instr) for instr in found_instr if instr.upper().startswith('USB')]
    # pick only USB instruments in local_config
    conf_norm = {k:_load_helper(v)[1] for k,v in local_config.conf.iteritems()}
    usb_instr = { _normalize_usb(para[0])[0]:name
                    for name, para in conf_norm.iteritems()
                    if len(para)>0 and isinstance(para[0], basestring) and para[0].upper().startswith('USB')}
    for usb, manuf, model in found_usb:
        try:
            name = usb_instr[usb]
            load(name)
            print '  Loaded: %6s   (%s)'%(name, usb)
        except KeyError:
            guess_manuf = instruments_registry.find_usb_name(manuf)
            guess_model = instruments_registry.find_usb_name(manuf, model)
            extra=''
            try:
                instr_class = instruments_registry.find_usb(manuf, model)
            except KeyError:
                pass
            else:
                extra = ', instruments class=%s'%instr_class.__name__
            print '  Unknown instrument: %s (guess manuf=%s, model=%s%s)'%(usb, guess_manuf, guess_model, extra)

def load_all_gpib(all_ids=True):
    """
     This will load all GPIB instruments found with find_all_instruments
     that exist in load and for which the idn is accepted. They need to be
     defined with a full name (GPIB0::1...) or an integer but not an alias.
     all_ids: when True (default) communicates with all gpib devices to obtain their
              ids. When false, only communicates with devices having a possible
              address match in local_config. However, the missing entry will
              less descriptive (will not show the id).
    """
    def check(instr):
        if isinstance(instr, basestring) and instr.upper().startswith('GPIB'):
            return True
        if isinstance(instr, int):
            if 0 <= instr < 31: # address 31 is untalk command
                return True
        return False
    found_instr = find_all_instruments(False)
    found_gpib = [_normalize_gpib(instr) for instr in found_instr if check(instr)]
    conf_norm = {k:_load_helper(v) for k,v in local_config.conf.iteritems()}
    gpib_instr = { name: (para[0], _normalize_gpib(para[1][0]))
                    for name, para in conf_norm.iteritems()
                    if len(para[1]) >= 1 and check(para[1][0])}
    for instr in found_gpib:
        if all_ids:
            idns = _get_visa_idns(instr)
            id = (idns['vendor'], idns['model'], idns['firmware'])
        else:
            idns = None
        correct_addr = {name: para for name, para in gpib_instr.iteritems()
                            if para[1] == instr}
        not_found = True
        if len(correct_addr):
            if not all_ids:
                idns = _get_visa_idns(instr)
                id = (idns['vendor'], idns['model'], idns['firmware'])
            for name, para in correct_addr.iteritems():
                if instruments_registry.check_instr_id(para[0], id):
                    load(name)
                    print '  Loaded: %6s   (%s)'%(name, instr)
                    not_found = False
                    break
        if not_found:
            if idns is not None:
                extra=''
                try:
                    instr_class = instruments_registry.find_instr(id)
                except KeyError:
                    pass
                else:
                    extra = ', instruments class=%s'%instr_class.__name__
                print '  Unknown instrument: %s (id vendor=%s, model=%s%s)'%(instr, idns['vendor'], idns['model'], extra)
            else:
                print '  Unknown instrument: %s'%(instr)


class _Hegel_Task(threading.Thread):
    def __init__(self, func, args=(), kwargs={}, count=None,
           interval=None, **extra):
        # func can be a function or a callable class instance.
        super(_Hegel_Task, self).__init__(**extra)
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
                break
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
    """
       This starts a pyHegel task.
       task(func, args=(), kwargs={}, count=None, interval=None, **extra)
       where the function func(*args, **kwargs) will be called count time
       (infinitely if the default of None used), separated by interval seconds
       (which defaults to 0).
       The interval sleep can be stopped every 1s.
       extra are keyword arguments to pass to the threading.Thread init function.
    """
    _Hegel_Task(*arg, **kwarg)

def top(all=False):
    """ lists the pyHegel tasks. The first number is the one you
        can use to kill the task.
        If all is True, then all python threading threads are listed
        (not only the pyHegel ones)
    """
    # All threads count: threading.active_count()
    for t in threading.enumerate():
        if all==True or isinstance(t, _Hegel_Task):
            print '%5i %s'%(t.ident, t)

def kill(n, force=False):
    """ Stops thread number n and wait for it to end.
        Only works for pyHegel tasks.
        You can stop wainting by pressing CTRL-C
        when force=True, it sends a KeyboardInterrupt exception to
          the other thread which should stop most python code
          (but will not stop blocking system function like sleep or
          file system read)
    """
    try:
        for t in threading.enumerate():
            if isinstance(t, _Hegel_Task) and t.ident==n:
                if force:
                    from ctypes import c_long, py_object, pythonapi
                    pythonapi.PyThreadState_SetAsyncExc(c_long(n), py_object(KeyboardInterrupt))
                    print 'Interrupting task and waiting'
                else:
                    t.stop()
                    print 'Stopping task and waiting'
                # we use a the context manager because join uses sleep.
                with instruments_base._sleep_signal_context_manager():
                    while t.is_alive():
                        t.join(0.5)
                print 'Stopped task'
    except KeyboardInterrupt:
        print 'Breaking out of kill. Task could still finish...'

# Differences with old version of Hegel
#alias: replaced by assignement instr1=instr2, dev=instr.devx
#forget: replaced by del instr1
#open, close instrument: replaced by object instantation (and load) and deletion
#call: replaced by run or execfile
#no: replaced by pass
# % replaced by #

#var: adds a variable to an instrument
#      maybe the same as: instr.newvar = instruments.MemoryDevice()

