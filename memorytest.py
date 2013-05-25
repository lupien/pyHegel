# -*- coding: utf-8 -*-

"""
    Memory tests: test response of memory to
                  multiple calls to figure() or trace
                  see test_plot function
    Requires psutil module
    To use, in pyHegel environment:
        run -i memorytest
        test_plot() # or change some of the options
"""

import gc
import psutil
import os
import sys
from PyQt4 import QtGui, QtCore
import traces
from pylab import close, figure, plot, clf, gcf, draw
from numpy import arange
from numpy.random import randn


def get_memory():
    pid = os.getpid()
    p = psutil.Process(pid)
    inf = p.get_memory_info()
    #ext = p.get_ext_memory_info()
    rss = inf.rss # resident size (includes shared)
    #rss = ext.wset
    vms = inf.vms # virtual private memory (excludes shared)
    #vms = ext.pagefile # the same as private
    #vms2 = (ext.paged_pool + ext.nonpaged_pool)
    vms /= 1024.**2 # in MiB
    rss /= 1024.**2 # in MiB
    #vms2 /= 1024.**2 # in MiB
    return (rss, vms)

def do_close(fig, trace):
    if trace == 'new' or trace == True:
        fig.destroy()
    elif trace == 'old':
        fig.window.close()
    else:
        close()

def test_plot(n=100, m=100000, trace='new', newfig=True, proc_time_ms=20, drawit=True,
              closeit=True, close_before=True, collect=True, sendpost=False):
    """
       This will create a plot or a traces.Trace (if trace=True) with m data points.
       multiple times (n times).
       Using the defaults should not cause a memory leak. If it does we have a
       problem (again).
       Running with trace=True, should cause a problem (which is fixed with trace='new')
       n:     number of repeats
       m:     number of data points per graph
       trace: if True (default) uses traces.Trace,
              when False uses figure, clf and plot
       newfig: wether to use a new figure for each iteration or
               to reuse the same one (when False)
       drawit: When True, forces a call to draw to update the plot.
               Only usefull for plot, since traces always does that
               call internally.
               Now that draw produces the data then calls the widget update which
               queues a paintEvent.
       closeit: When True, 'old' or 'new', the figure/trace gets closed (like pressing
                the close button on the window). In theory this should clear the memory.
                Obviously, turning this off will not release any memory so
                it can quickly produces a memory error (with default n,m)
                when using a 32 bit python.
                'new' or True selects the new way of closing the traces.Trace window.
                'old' is the old one which was causing a memory leak.
       close_before: When True, the close is done before running processEvents
                     When False, it is after.
                     When closeit is False, this has no effect.
       collect:  When True, calls the python garbage collector before the start
                 of the next iteration
       sendpost: When True, will call sendpost with DeferredDelete just after
                 processEvents is called (and only if that is enabled) to
                 handle the deleteLater events caused by closing a window
                 (as long as the windows has the Qt::WA_DeleteOnClose flag).
                 When disabled the DeferredDelete are not handled by
                 processEvents, so the Widget is only deleted if python deletes
                 it or when we return to the main event loop (when the function
                 terminates if called from the console.)
       proc_time_ms: the number of milliseconds to use for
                     processEvents. This empties the event queue and is called
                     as long as new event show up and the duration is less
                     than proc_time_ms.
                     Therefore the actual time can be shorter (event 0) if
                     no events are pending. And longer if emptying the queue
                     takes a long time (try:
                         foo=plot(randn(1000000)); to=time.time(); QtGui.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 20); print time.time()-to)
                     Use a negative value (like -1) to disable this call.
                     Without this call, no widget update will happen (no paint
                     no response to mouse, ...)
    """
    if not collect:
        print 'auto collect enable: ', gc.isenabled(), ' thesholds: ', gc.get_threshold()
    for i in range(n):
        if newfig:
            if trace:
                f=traces.Trace()
            else:
                f=figure()
        else:
            f=gcf()
            clf()
        if trace:
            f.setPoints(arange(m),randn(1,m))
        else:
            plot(randn(m))
        if drawit:
            if trace:
                pass
            else:
                draw()
        if close_before and closeit:
            do_close(f, trace)
        if proc_time_ms>=0:
            QtGui.QApplication.processEvents(QtCore.QEventLoop.AllEvents, proc_time_ms)
            if sendpost:
                QtGui.QApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        if not close_before and closeit:
            do_close(f, trace)
        print 'i=%03i'%i,'memory(rss: %.3f, vms: %.3f)'%get_memory(), 'garbage:', gc.get_count(),
        if trace:
            # refecount -1 for the temporary. So if it is 1, the next del will really remove it
            # from memory
            print 'Traces len',len(traces._figlist), 'ref_count', sys.getrefcount(f)-1,
        del f
        if collect:
            print 'Collecting:', gc.collect()
        else:
            print

#close() calls:
# f.canvas.manager.toolbar.destroy() # this does not seem necessary to me, I did some tests without it
                                     # and it seemed to work fine.
# f.canvas.manager.window.close()
#  if widget has Qt::WA_DeleteOnClose, then accepted close causes delete
# and does a garbage collection

#draw_if_interactive calls f.canvas.draw_idle
# which starts a 0 length timer to call draw
# which is called at next event processing (either processEvents or eventLoop)
#   note processEvents does sendPostedEvents internally
#   (which handles QtEvents) but also handles system (Windows, X)
#   interactions. sendEvents internally uses notify
#   which calls the necessary filters and propagates the event.

#draw() calls f.canvas.draw() which calls
#          FigureCanvasAgg.draw() and then f.canvas.update()
