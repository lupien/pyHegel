# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:
#
# python-matplotlib-0.99.1.2-4.fc13.i686 QT backend is missing many
# key codes compared to gtk so add missing ones needed for FigureManagerQT

import time

from PyQt4 import QtCore, QtGui
import numpy as np
from matplotlib import pylab, rcParams

# same as in fullmpcanvas.py
# follows new_figure_manager
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt4 import FigureManagerQT
from matplotlib.figure import Figure

# see from mpl_toolkits.axes_grid1 import host_subplot
# matplotlib/Examples/axes_grid/demo_parasite_axes2.py
#from mpl_toolkits.axes_grid1 import host_subplot
from mpl_toolkits.axes_grid1.parasite_axes import host_subplot_class_factory
import mpl_toolkits.axisartist as AA
host_subplot_class = host_subplot_class_factory(AA.Axes)

_figlist = []

# set the timezone for proper display of date/time axis
# to see available ones: import pytz; pytz.all_timezones
pylab.rcParams['timezone']='Canada/Eastern'
#pylab.rc('mathtext', fontset='stixsans')

"""
The figure handles many hot keys. They can be changed using rcParams (keymap...)
They are:
  fullscreen ( default: f)
  home (home, h, r)
  backward (left, backspace, c)
  forward (right, v)
  pan (p)
  zoom (o)
  save (s)
When over an axis:
  grid (g)
  y log/linear (l)
  x log/linear (k, L)
  pan/zoom all axes (a)
  pan/zoom one axis (1-9)
     Added: This also selects the axis used to display values in status bar.

Mouse:
 in pan mode:
   left button: moves
   right button: scales in/out while dragging
 in zoom mode:
   left button: zoom in on rectangle
   right button: zoom out of rectangle
   press x or y while zooming to limit the zooming to the x or y scale

"""


def wait(sec):
    start = time.time()
    end = start + sec
    while time.time() < end:
        dif = end - time.time()
        if dif < .01:
            if dif >0.:
                time.sleep(dif)
            return
        else:
           QtGui.QApplication.instance().processEvents(
               QtCore.QEventLoop.AllEvents, dif*1000)
           dif = end - time.time()
           if dif < 0:
               return
           time.sleep(min(.1, dif))

FigureCanvas.keyvald.update({QtCore.Qt.Key_Left:'left',
        QtCore.Qt.Key_Right:'right',
        QtCore.Qt.Key_Up:'up',
        QtCore.Qt.Key_Down:'down',
        QtCore.Qt.Key_Escape:'escape',
        QtCore.Qt.Key_Home:'home',
        QtCore.Qt.Key_End:'end',
        QtCore.Qt.Key_Backspace:'backspace'})

def get_last_trace():
    return _figlist[-1]

def close_last_trace():
    get_last_trace().window.close()

def time2date(x):
    return x/(24.*3600)+pylab.epoch2num(0)

def get_timezone_shift(x=None):
    """
    returns the timezone shift of x in seconds (UTC - local)
    x should be the time in s since the unix epoch
     (as returned by time.time())
    """
    dt = time.localtime(x)
    if dt.tm_isdst:
        tz = time.altzone
    else:
        tz = time.timezone
    return tz

def time_stripdate(x, first=None):
    """
    takes either first if given or the first element of x
    and returns x minus that first value date (time=0:0:0)
    x, first and return are in seconds.
    x and first are since epoch (time.time())
    """
    if first == None:
        try:
            first = x[0]
        except TypeError:
            first = x
    dt = list(time.localtime(first))
    dt[3]=0 # tm_hour
    dt[4]=0 # tm_min
    dt[5]=0 # tm_sec
    offset = time.mktime(dt)
    return x-offset

class TraceBase(FigureManagerQT, object): # FigureManagerQT is old style class so need object to make it new one (so super works properly for childs)
    # A useful subclass will need at least to include update
    def __init__(self, width=9.00, height=7.00, dpi=72):
        self.fig = Figure(figsize=(width,height),dpi=dpi)
        self.canvas = FigureCanvas(self.fig)
        FigureManagerQT.__init__(self,self.canvas,-1)
        self.MainWidget = self.window
        self.setWindowTitle('Trace...')
        self.isclosed = False
        #########
        _figlist.append(self)
        self.window.connect(self.window, QtCore.SIGNAL('destroyed()'),
             self.close_slot)
    def close_slot(self):
        self.isclosed = True
        _figlist.remove(self)

    def mykey_press(self, event):
        # TODO add a Rescale
        # based on FigureManagerBase.key_press
        all = rcParams['keymap.all_axes']
        if event.inaxes is None:
            return
        if (event.key.isdigit() and event.key!='0') or event.key in all:
              # if it was the axes, where the event was raised
            if not (event.key in all):
                n = int(event.key)-1
            for i, a in enumerate(self.canvas.figure.get_axes()):
                # consider axes, in which the event was raised
                # FIXME: Why only this axes?
                if event.x is not None and event.y is not None \
                       and a.in_axes(event):
                    if event.key in all:
                        a.zorder = 0
                    else:
                        a.zorder = 1 if i==n else 0

    def setWindowTitle(self, title):
        self.set_window_title(title)
    def draw(self):
        if self.isclosed:
            return
        self.canvas.draw()
    def show(self):
        if self.isclosed:
            return
        self.fig.canvas.window().show()
    def hide(self):
        if self.isclosed:
            return
        self.fig.canvas.window().hide()
    def savefig(self,*args,**kwargs):
        self.fig.savefig(*args, **kwargs)


class Trace(TraceBase):
    def __init__(self, width=9.00, height=7.00, dpi=72, time_mode = False):
        super(Trace, self).__init__(width=width, height=height, dpi=dpi)
        ax = host_subplot_class(self.fig, 111)
        self.fig.add_subplot(ax)
        self.axs = [ax]
        self.xs = None
        self.ys = None
        self.xmax = None
        self.xmin = None
        self.legend_strs = None
        self.first_update = True
        self.time_mode = time_mode
        # could also use self.fig.autofmt_xdate()
        ax = self.axs[0]
        tlabels = ax.axis['bottom'].major_ticklabels
        if time_mode:
            tlabels.set_size(9)
            tlabels.set_rotation(10)
            tlabels.set_rotation_mode('default')
            tlabels.set_verticalalignment('top')
        self.update()
        # handle status better for twinx (pressing 1 or 2 selects axis)
        self.canvas.mpl_connect('key_press_event', self.mykey_press)
        ######### Add button to toolbar
        # Pause
        self.pause_button = QtGui.QPushButton('Pause')
        self.pause_enabled = False
        self.pause_button.setCheckable(True)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.pause_button)
        self.pause_button.connect(self.pause_button,
              QtCore.SIGNAL('toggled(bool)'), self.pause_button_press)
        # abort
        self.abort_button = QtGui.QPushButton('Abort')
        self.abort_enabled = False
        self.abort_button.setCheckable(True)
        self.toolbar.addWidget(self.abort_button)
        self.abort_button.connect(self.abort_button,
              QtCore.SIGNAL('toggled(bool)'), self.abort_button_press)
        # Rescale
        self.rescale_button = QtGui.QPushButton('Rescale')
        self.toolbar.addWidget(self.rescale_button)
        self.rescale_button.connect(self.rescale_button,
              QtCore.SIGNAL('clicked()'), self.rescale_button_press)
    def pause_button_press(self, state):
        self.pause_enabled = state
    def abort_button_press(self, state):
        self.abort_enabled = state
    def rescale_button_press(self):
        # TODO tell toolbar that a new set of scales exists
        for i,ax in enumerate(self.axs):
            ax.relim()
            if i==0:
                ax.set_xlim(self.xmin, self.xmax, auto=True)
            ax.set_autoscaley_on(True)
            ax.autoscale(enable=None)
        self.draw()
    def set_xlogscale(self, enable=True):
        s = {True:'log', False:'linear'}
        self.axs[0].set_xscale(s[enable])

    def setLim(self, minx, maxx=None):
        if isinstance(minx, (list, tuple, np.ndarray)):
             maxx = np.max(minx)
             minx = np.min(minx)
        self.xmax = maxx
        self.xmin = minx
        self.axs[0].set_xlim(minx, maxx, auto=False)
        self.update()
    def set_xlabel(self, label):
        self.axs[0].set_xlabel(label)
    def addPoint(self, x, ys):
        if self.time_mode:
            # convert from sec since epoch to matplotlib date format
            x = time2date(x)
        if self.xs == None:
           self.xs = np.array([x])
        else:  self.xs = np.append(self.xs, x)
        if self.ys == None:
           self.ys = np.array([ys])
        else:  self.ys = np.append(self.ys, [ys], axis=0)
        self.update()
    def setPoints(self, x, y):
        if self.time_mode:
            # convert from sec since epoch to matplotlib date format
            x = time2date(x)
        self.xs = np.array(x)
        self.ys = np.array(y.T)
        self.update()
    def setlegend(self, str_lst):
        self.legend_strs = str_lst
        self.update()
    def update(self):
        if self.xs == None:
           self.draw()
           return
        if self.first_update:
            ndim = self.ys.shape[1]
            right = .95-(ndim-1)*.1
            if right < .5:
                right = .5
            #offset = (.95-right)/(ndim-1)
            offset = 50
            self.fig.subplots_adjust(right=right)
            host = self.axs[0]
            # cycle over all extra axes
            for i in range(ndim-1):
                ax = host.twinx()
                new_fixed_axis = ax.get_grid_helper().new_fixed_axis
                ax.axis['right'] = new_fixed_axis(loc='right', axes=ax, offset=(offset*i,0))
                ax.axis['right'].toggle(all=True)
                self.axs.append(ax)
                # add them to figure so selecting axes (press 1, 2, a) works properly
                self.fig.add_axes(ax)
                ax.set_xlim(self.xmin, self.xmax, auto=False)
            self.crvs = []
            #self.ax.clear()
        x = self.xs
        for i,(y,ax) in enumerate(zip(self.ys.T, self.axs)):
           style = '.-'
           if self.first_update:
              try:
                 lbl = self.legend_strs[i]
              except TypeError:
                 lbl = 'data '+str(i)
              if self.time_mode:
                  plt = ax.plot_date(x, y, style, label=lbl)[0]
              else:
                  plt = ax.plot(x, y, style, label=lbl)[0]
              line_color = ax.lines[0].get_color()
              ax.set_ylabel(lbl, color=line_color)
              self.crvs.append(plt)
           else:
              self.crvs[i].set_data(x, y)
        self.axs[0].legend(loc='upper left', bbox_to_anchor=(0, 1.10)).draggable()
        for ax in self.axs:
            ax.relim()
            ax.autoscale(enable=None)
        self.first_update = False
        self.draw()

def lots_pick(n):
    """
    This returns a fucntion that will pick one out of every n point
    """
    return lambda x: x[::n]

def lots_avg(n):
    """
    This returns a fucntion that will return the average of blocks of n points
    """
    return lambda x: x.reshape((-1, n)).mean(axis=1)

class TraceLots(TraceBase):
    # block_size in points
    def __init__(self, filename, width=9.00, height=7.00, dpi=72,
                 block_size=10*1024, dtype=np.uint8, trans=None):
        """
        This class allows the exploration of very large raw (binary) data file.
        The filename has to be provided.
        block_size is the number of points to show at a time
         (the slider will move in increments of half of this)
        dtype is a numpy dtype for the data (uint8, uint16 ...)
        trans is a transformation function on the data.
              The function takes the read data as input and must return
              the data to display.
              See lots_pick and lots_avg as possible functions
        """
        super(TraceLots, self).__init__(width=width, height=height, dpi=dpi)
        self.filename = filename
        self.dtype = dtype
        self.trans = trans
        self.byte_per_point = 1
        if dtype().nbytes == 2:
            self.byte_per_point = 2
        self.block_nbpoints = block_size
        self.block_size = block_size*self.byte_per_point
        self.fh = open(filename, 'rb')
        ax = self.fig.add_subplot(111)
        self.ax = ax
        self.fh.seek(0, 2) # go to end of file
        self.nbpoints = self.fh.tell() / self.byte_per_point
        self.readit() # sets self.vals
        self.mainplot = ax.plot(self.vals)[0]
        self.bar = QtGui.QScrollBar(QtCore.Qt.Horizontal)
        self.bar.setMaximum(self.nbpoints/block_size*2 -1) # every step is half a block size
        self.bar_label = QtGui.QLabel()
        self.central_widget = QtGui.QWidget()
        self.central_layout = QtGui.QVBoxLayout()
        self.central_layout.setContentsMargins(0, 0, 0, 0)
        # The QMainWindow.centralWidget is self.canvas
        self.central_layout.addWidget(self.canvas)
        self.central_layout.addWidget(self.bar)
        self.central_layout.addWidget(self.bar_label)
        self.central_widget.setLayout(self.central_layout)
        self.MainWidget.setCentralWidget(self.central_widget)
        self.bar.connect(self.bar,
              QtCore.SIGNAL('valueChanged(int)'), self.bar_update)
        self.bar_update(0)
    def bar_update(self, val):
        offset = val * self.block_nbpoints /2
        self.bar_label.setText('offest: {:,}'.format(offset))
        self.readit(offset)
        self.update()
    def readit(self, offset=0):
        self.fh.seek(offset*self.byte_per_point)
        vals = np.fromfile(self.fh, dtype=self.dtype, count=self.block_size)
        if self.trans != None:
            vals = self.trans(vals)
        self.vals = vals
    def update(self):
        self.mainplot.set_ydata(self.vals)
        self.draw()


def plot_time(x, *extrap, **extrak):
    """
       The same as plot_date, but takes in the time in sec since epoch
       instead of the matplotlib date format.
       (It can use the result of time.time())
       Added Parameter:
        xrotation: which rotates the x ticks (defautls to 10 deg)
        xticksize: changes x axis thick size (defaults to 9)
    """
    # uses the timezone set by pylab.rcParams['timezone']
    x = time2date(x)
    xrotation = extrak.pop('xrotation', 10)
    xticksize = extrak.pop('xticksize', 9)
    ret = pylab.plot_date(x, *extrap, **extrak)
    ax = ret[0].axes
    # Rotate axes ticks
    # could also use self.fig.autofmt_xdate()
    lbls = ax.get_xticklabels()
    for l in lbls:
        l.update(dict(rotation=xrotation, size=xticksize))
    pylab.draw()
    return ret

class Sleeper(QtGui.QWidget):
    """
       Start sleeper with
        sl=Sleeper()
        sl.start_sleep(1) # 1 min
       Stop by closing:
        sl.close()
    """
    def __init__(self, sleep=1.): # default 1 min
        super(Sleeper, self).__init__()
        self.bar = QtGui.QProgressBar()
        self.bar.setMaximum(1000)
        self.pause_button = QtGui.QPushButton('Pause')
        self.pause_button.setCheckable(True)
        self.skip_button = QtGui.QPushButton('End Pause Now')
        self.elapsed = QtGui.QLabel('0 min')
        self.sleep_length = QtGui.QDoubleSpinBox()
        self.sleep_length.setRange(0.01, 60*24*2) # 2 days max
        self.sleep_length.setDecimals(2)
        self.sleep_length.setKeyboardTracking(False)
        self.sleep_length.setSuffix(' min')
        hboxlay1 = QtGui.QHBoxLayout()
        hboxlay1.addWidget(self.bar)
        hboxlay1.addWidget(self.elapsed)
        hboxlay2 = QtGui.QHBoxLayout()
        hboxlay2.addWidget(self.pause_button)
        hboxlay2.addWidget(self.sleep_length)
        hboxlay2.addStretch()
        hboxlay2.addWidget(self.skip_button)
        vboxlay = QtGui.QVBoxLayout()
        vboxlay.addLayout(hboxlay1)
        vboxlay.addLayout(hboxlay2)
        self.setLayout(vboxlay)
        self.update_timer = QtCore.QTimer(self)
        self.update_timer.setInterval(1000) #ms
        self.start_time = time.time()
        self.pause_length = 0.
        self.finished = True
        self.pause_start = self.start_time
        # start in pause mode
        self.pause_button.setChecked(True)
        self.connect(self.sleep_length, QtCore.SIGNAL('valueChanged(double)'),
                     self.sleep_length_change)
        self.connect(self.update_timer, QtCore.SIGNAL('timeout()'),
                     self.update_elapsed)
        self.connect(self.skip_button, QtCore.SIGNAL('clicked()'),
                     self, QtCore.SLOT('close()'))
        self.connect(self.pause_button, QtCore.SIGNAL('toggled(bool)'),
                     self.pause)
        self.sleep_length.setValue(sleep)
    def sleep_length_change(self, val):
        self.update_elapsed()
    def closeEvent(self, event):
        self.update_timer.stop()
        # Turn on pause in case we ever want to continue the Sleep
        self.pause_button.setChecked(True)
        self.finished = True
        event.accept()
    def update_elapsed(self):
        full = self.sleep_length.value()*60. # in seconds
        val = time.time() - self.start_time - self.pause_length
        if self.pause_button.isChecked():
            val -= time.time()-self.pause_start
        elif val>full:
            self.close()
        self.elapsed.setText('%.2f min'%max((val/60.),0))
        self.bar.setValue(min(int(val/full*1000),1000))
    def start_sleep(self, length=None):
        self.finished = False
        self.start_time = time.time()
        self.pause_length = 0.
        self.pause_start = self.start_time
        self.pause_button.setChecked(False)
        if length != None:
            self.sleep_length.setValue(length)
        self.pause(False)
        # They above two might not have produced a change
        # so now make sure display is updated
        self.update_elapsed()
        self.show()
    def pause(self, checked):
        if checked:
            self.pause_start = time.time()
            self.update_timer.stop()
            self.update_elapsed()
        else:
            self.pause_length += time.time()-self.pause_start
            self.update_elapsed()
            self.update_timer.start()

sleeper = Sleeper()

def sleep(sec):
    sleeper.start_sleep(sec/60.)
    try:
        while not sleeper.finished:
            QtGui.QApplication.instance().processEvents(
                   QtCore.QEventLoop.AllEvents)
            time.sleep(.1)
    except KeyboardInterrupt:
        sleeper.close()
        raise

