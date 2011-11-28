# -*- coding: utf-8 -*-
#
# python-matplotlib-0.99.1.2-4.fc13.i686 QT backend is missing many
# key codes compared to gtk so add missing ones needed for FigureManagerQT

import time

from PyQt4 import QtCore, QtGui, uic
import numpy as np
from matplotlib import pylab, pyplot, ticker

# same as in fullmpcanvas.py
# follows new_figure_manager
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_qt4 import FigureManagerQT
from matplotlib.figure import Figure

# set the timezone for proper display of date/time axis
# to see available ones: import pytz; pytz.all_timezones
pylab.rcParams['timezone']='Canada/Eastern'
#pylab.rc('mathtext', fontset='stixsans')

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

class Trace(FigureManagerQT):
    def __init__(self, width=9.00, height=7.00, dpi=72, time_mode = False):
        self.fig = Figure(figsize=(width,height),dpi=dpi)
        self.canvas = FigureCanvas(self.fig)
        FigureManagerQT.__init__(self,self.canvas,-1)
        self.MainWidget = self.window
        self.setWindowTitle('Trace...')
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
        self.canvas.draw()
    def show(self):
        self.fig.canvas.window().show()
    def hide(self):
        self.fig.canvas.window().hide()
    def savefig(self,*args,**kwargs):
        self.fig.savefig(*args, **kwargs)

