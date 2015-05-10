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


"""
Wrapper to handle various combinations of PyQt4(api1 and 2), PyQt5 and PySide
You should import this after the Qt library has been loaded (by ipython
and/or matplotlib). Then it will use the previously loaded one.
Only one of the possible Qt librairies should be loaded.
If none are loaded, a default set is tried in order.
"""

# PySide is very similar to PyQt4 api2
# inspired by ipython IPython/external/qt_loaders.py (ipython 2.4.1)

# The difference between api1 and 2 is that for 2, QVariants and QStrings
# are automatically transformed and are not used in python.
# So for code to be portable, do not use QStrings or QVariants.

# for compatibility, use QtCore.Signal, QtCore.Slot instead of
#  QtCore.pyqtSignal, QtCore.pyqtSlot

# Only use new style slot/signal
# so no SIGNAL or SLOT functions
# this requiers PyQt4 >v4.5


# Warning: the original release of ipython 2.4.1 contains a bug
# causing problems loading PyQt4
#  see: https://github.com/ipython/ipython/commit/5f275fe135362d5b6cca79d004f8fa272eec24d2
#  mainly change IPython/external/qt_loaders.py line 60-63 to be
#    elif api == QT_API_PYQT5:
#        ID.forbid('PySide')
#        ID.forbid('PyQt4')
#    else:   # There are three other possibilities, all representing PyQt4
#        ID.forbid('PyQt5')
#        ID.forbid('PySide')
#  instead of
#    elif api == QT_API_PYQT:
#        ID.forbid('PySide')
#        ID.forbid('PyQt5')
#    else:
#        ID.forbid('PyQt4')
#        ID.forbid('PySide')

import sip
import sys
import types

def load_Qt4():
    from PyQt4 import QtGui, QtCore

    # Alias PyQt-specific functions for PySide compatibility.
    QtCore.Signal = QtCore.pyqtSignal
    QtCore.Slot = QtCore.pyqtSlot

    version = sip.getapi('QString')
    api = 'pyqt4' if version == 1 else 'pyqt4v2'

    return QtCore, QtGui, api


def load_Qt5():
    from PyQt4 import QtGui, QtCore, QtWidgets

    # Alias PyQt-specific functions for PySide compatibility.
    QtCore.Signal = QtCore.pyqtSignal
    QtCore.Slot = QtCore.pyqtSlot

    # Join QtGui and QtWidgets for Qt4 compatibility.
    QtGuiCompat = types.ModuleType('QtGuiCompat')
    QtGuiCompat.__dict__.update(QtGui.__dict__)
    QtGuiCompat.__dict__.update(QtWidgets.__dict__)

    return QtCore, QtGuiCompat, 'pyqt5'


def load_Side():
    from PySide import QtGui, QtCore
    return QtCore, QtGui, 'pyside'


def processEvents(events_flags=None, max_time_ms=None):
    """
    events=None means all events
    timeout_ms=None means
    """
    if events_flags is None and max_time_ms is None:
        QtGui.QApplication.processEvents()
    else:
        if events_flags is None:
            events_flags = QtCore.QEventLoop.AllEvents
        if max_time_ms is None: # process all events_flags events
            QtGui.QApplication.processEvents(events_flags)
        else:
            QtGui.QApplication.processEvents(events_flags, max_time_ms)

def check_qt(base):
    if base in sys.modules:
        return True
    # need to check also for QtCore and QtGui since IPython
    # removes the base (to make its import forbid work IPython/external/qt_loaders.py)
    if base+'.QtCore' in sys.modules:
        return True
    if base+'.QtGui' in sys.modules:
        return True
    return False

def load_qt():
    if check_qt('PyQt5'):
        ret = load_Qt5()
    elif check_qt('PyQt4'):
        ret = load_Qt4()
    elif check_qt('PyQt4'):
        ret = load_Side()
    else: # Nothing loaded yet, lets try Qt4, Side then Qt5
        try:
            ret = load_Qt4()
        except ImportError:
            try:
                ret = load_Side()
            except ImportError:
                ret = load_Qt5()
    return ret


QtCore, QtGui, api = load_qt()

