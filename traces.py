# -*- coding: utf-8 -*-
#
# python-matplotlib-0.99.1.2-4.fc13.i686 QT backend is missing many
# key codes compared to gtk so add missing ones needed for FigureManagerQT

import time

from PyQt4 import QtCore, QtGui, uic
import numpy as np
from matplotlib import pylab, pyplot, ticker, rcParams

# same as in fullmpcanvas.py
# follows new_figure_manager
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_qt4 import FigureManagerQT
from matplotlib.figure import Figure

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

class Trace(FigureManagerQT):
    def __init__(self, width=9.00, height=7.00, dpi=72, time_mode = False):
        self.fig = Figure(figsize=(width,height),dpi=dpi)
        self.canvas = FigureCanvas(self.fig)
        FigureManagerQT.__init__(self,self.canvas,-1)
        self.MainWidget = self.window
        self.setWindowTitle('Trace...')
        self.isclosed = False
        self.ax = self.fig.add_subplot(111)
        self.xs = None
        self.ys = None
        self.legend_strs = None
        self.first_update = True
        self.twinmode = False
        self.time_mode = time_mode
        if time_mode:
            lbls = self.ax.get_xticklabels()
            for l in lbls:
                l.update(dict(rotation=10, size=9))
        self.update()
        # handle status better for twinx (pressing 1 or 2 selects axis)
        self.canvas.mpl_connect('key_press_event', self.mykey_press)
        ######### Add button to toolbar
        self.pause_button = QtGui.QPushButton('Pause')
        self.pause_enabled = False
        self.pause_button.setCheckable(True)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.pause_button)
        self.pause_button.connect(self.pause_button, 
              QtCore.SIGNAL('toggled(bool)'), self.pause_button_press)
        #########
        _figlist.append(self)
        self.window.connect(self.window, QtCore.SIGNAL('destroyed()'),
             self.close_slot)
    def close_slot(self):
        self.isclosed = True
        _figlist.remove(self)
    def pause_button_press(self, state):
        self.pause_enabled = state
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

    def setLim(self, minx, maxx=None):
        try:
            if len(minx)>1:
                 maxx = np.max(minx)
                 minx = np.min(minx)
        except:
            pass
        self.ax.set_xlim(minx, maxx, auto=False)
        self.update()
    def setWindowTitle(self, title):
        self.set_window_title(title)
    def addPoint(self, x, ys):
        if self.time_mode:
            # convert from sec since epoch to matplotlib date format
            x = x/(24.*3600)+pylab.epoch2num(0)
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
            x = x/(24.*3600)+pylab.epoch2num(0)
        self.xs = np.array(x)
        self.ys = np.array(y)
        self.update()
    def setlegend(self, str_lst):
        self.legend_strs = str_lst
        self.update()
    def update(self):
        if self.xs == None:
           self.draw()
           return
        if self.first_update:
           if self.ys.shape[1] == 2:
               self.twinmode = True
               self.ax2 = self.ax.twinx()
           self.crvs = []
           #self.ax.clear()
        x = self.xs
        for i,y in enumerate(self.ys.T):
           if self.twinmode and i == 1:
               ax = self.ax2
               #style = '.-r'
               style = '.-'
               ax._get_lines.color_cycle.next()
           else:
               ax = self.ax
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
              self.crvs.append(plt)
           else:
              self.crvs[i].set_data(x, y)
        if self.first_update:
            self.ax.legend(loc='upper left')
            if self.twinmode:
                self.ax2.legend(loc='upper right')
        self.ax.relim()
        self.ax.autoscale(enable=None)
        if self.twinmode:
            self.ax2.relim()
            self.ax2.autoscale(enable=None)
        self.first_update = False
        self.draw()
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
    x = x/(24.*3600)+pylab.epoch2num(0)
    xrotation = extrak.pop('xrotation', 10)
    xticksize = extrak.pop('xticksize', 9)
    ret = pylab.plot_date(x, *extrap, **extrak)
    ax = ret[0].axes
    # Rotate axes ticks
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
        super(type(self),self).__init__()
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
    start = time.time()
    end = start + sec
    try:
        while not sleeper.finished:
            QtGui.QApplication.instance().processEvents(
                   QtCore.QEventLoop.AllEvents)
            time.sleep(.1)
    except KeyboardInterrupt:
        sleeper.close()
        raise

