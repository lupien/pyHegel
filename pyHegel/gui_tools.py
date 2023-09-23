# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2018-2023  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from __future__ import absolute_import, print_function, division

import time
import sys

from .qt_wrap import QtCore, QtGui
from .qt_wrap import sleep as _sleep

from .instruments_base import mainStatusLine

class Sleeper(QtGui.QWidget):
    """
       Start sleeper with
        sl=Sleeper()
        sl.start_sleep(1) # 1 min
       Stop by closing:
        sl.close()
    """
    def __init__(self, sleep=1.): # default 1 min
        self.duration = None
        super(Sleeper, self).__init__()
        self.bar = QtGui.QProgressBar()
        self.bar.setMaximum(1000)
        self.pause_button = QtGui.QPushButton('Pause')
        self.pause_button.setCheckable(True)
        self.skip_button = QtGui.QPushButton('End Sleep Now')
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
        # setup connections
        self.sleep_length.valueChanged.connect(self.sleep_length_change)
        self.update_timer.timeout.connect(self.update_elapsed)
        # This selects the clicked() instead of clicked(bool)
        # but either one works
        self.skip_button.clicked.connect(self.close)
        self.pause_button.toggled.connect(self.pause)
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
        self.duration = full + self.pause_length
        now = time.time()
        start = self.start_time + self.pause_length
        val = now - start
        if self.pause_button.isChecked():
            val = self.pause_start - start
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
        if length is not None:
            self.sleep_length.setValue(length)
        self.pause(False)
        # They above two might not have produced a change
        # so now make sure display is updated
        self.update_elapsed()
        self.show()
    def pause(self, checked):
        now = time.time()
        if checked:
            self.pause_start = now
            self.update_timer.stop()
            self.update_elapsed()
        else:
            self.pause_length += now-self.pause_start
            self.update_elapsed()
            self.update_timer.start()

class Delay_init(object):
    def __init__(self, object_class, *arg, **kwarg):
        self.object_class = object_class
        self.arg = arg
        self.kwarg = kwarg
        self.obj = None
    def check_init(self):
        if self.obj:
            return
        self.obj = self.object_class(*self.arg, **self.kwarg)
    def __call__(self, *arg, **kwarg):
        return self.obj(*arg, **kwarg)
    def __getattribute__(self, name):
        if name in ['__init__', 'check_init', '__call__', 'object_class', 'arg', 'kwarg', 'obj']:
            return object.__getattribute__(self, name)
        self.check_init()
        return self.obj.__getattribute__(name)

sleeper = Delay_init(Sleeper)
#sleeper = Sleeper()

def sleep(sec, progress_base='GUI Wait', progress_timed=True):
    """
       wait seconds... It has a GUI that allows the wait to be paused.
       After resuming, the wait continues (i.e. total
          wait will be pause+sec)
       See also wait
    """
    to = time.time()
    sleeper.start_sleep(sec/60.)
    try:
        with mainStatusLine.new(priority=100, timed=progress_timed) as progress:
            while not sleeper.finished:
                _sleep(0.1)
                if progress_base is not None:
                    s = progress_base+' %.1f/%.1f'%(time.time()-to, sleeper.duration)
                    if sleeper.pause_button.isChecked():
                        s += ' (paused)'
                    progress(s)
    except KeyboardInterrupt:
        sleeper.close()
        raise

class Quit_Button(QtGui.QPushButton):
    """
        Starts a Button that will exit the application with clicked.
        Use:
            qb = Quit_Button('This is the quit message')
    """
    def __init__(self, text, noshow=False):
        super(Quit_Button, self).__init__(text)
        self.clicked.connect(self.endit)
        if not noshow:
            self.show()
    def endit(v=None):
        sys.exit()
