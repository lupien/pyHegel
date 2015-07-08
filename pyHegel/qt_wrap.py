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
# If no selection is done for a signal (emit, connect) then the default one is used
# (the one listed in the documentation). Otherwise, select them in the following way:
#  obj.signal1[int]  # for signal1(int)
#  obj.signal2[str, int] # for signal2(QString, int)
#  obj.signal3[()] # for signal3()
# Note that all the overload signals act separatelly. emitting one does nothing
# for the others. So code should emit all the overloaded signals together.

# Note that Qt (C++) allows a signal to connect to a slot with any number of parameters
# less than or equal than the signal (they don't have to be parameters with default
# values). Signal with parameter that have default values will have multiple signatures.
# For example sig(int x=1), will have signatures sig(int) and sig().
# A connection can be made to an invalid slot (wrong parameter signature), in which case the code
# shows an error on the console during run time at connect time (but code still runs)
#
# Under PyQt4 or PySide conecting a builtin slot with the wrong parameters
# produces a caught exception at call time.
# During emit, PyQt4,5 produces an exception for wrong parameters
# while PySide will silently converts them (I have seen str converted to float(0.))
# at least for PyQt4-4.11.3-1.fc21.x86_64
#              python-qt5-5.4.1-1.fc21.x86_64
#              python-pyside-1.2.2-2.fc21.x86_64
#              qt-4.8.6-28.fc21.x86_64
# test like this:
# # one of the following 3 lines
# from PyQt4 import QtGui, QtCore; Signal = QtCore.pyqtSignal
# from PySide import QtGui, QtCore; Signal = QtCore.Signal
# from PyQt5 import QtCore, QtWidgets as QtGui; Signal = QtCore.pyqtSignal
#
# qapp = QtGui.QApplication([])
# class C(QtGui.QDoubleSpinBox):
#     tests = Signal([int], [float], [str], [QtCore.QObject], [])
# c=C()
# # These always work
# c.tests.emit(1)
# c.tests.emit(1.) # emits an integer
# c.tests[int].emit(1)
# c.tests[float].emit(5.5)
# c.tests[str].emit('hello')
# c.tests[()].emit()
# c.tests[QtCore.QObject].emit(c)
# # These should probably fail but do not
# c.tests[int].emit('hello')
# c.tests[int].emit(None)
# c.tests[int].emit([])
# c.tests[int].emit({})
# c.tests[int].emit(object())
# c.tests[str].emit(None) # This fails but only on PyQt4
# # These fail on PyQt4 and PyQt5 but not PySide
# c.tests[str].emit(5)
# c.tests[float].emit('hello')
# # These fail on all (wrong number of arguments)
# c.tests[int].emit(1,2)
# c.tests[int].emit()
# c.tests[()].emit(1)


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

from __future__ import absolute_import

import sip
import sys
import types

def fix_ipython_241():
    """
    IPython 2.4.1 has a bug that prevents
     import PyQt4
    from working.
    This function monkey patches over the problem.
    """
    try:
        sys.modules['IPython.external.qt_loaders']
    except KeyError:
        # ipython not loaded. No need to fix anything
        return
    import IPython
    if IPython.__version__ != '2.4.1':
        return
    from IPython.external.qt_loaders import ID, loaded_api
    id_forb = ID._ImportDenier__forbidden
    if loaded_api() == 'pyqtv1' and 'PyQt4' in id_forb:
        print 'fixing IPython 2.4.1 import denier'
        id_forb.remove('PyQt4')
        ID.forbid('PyQt5')
        # need to reimport so that from import work
        # otherwise from PyQt4 import QtCore, QtGui fail because
        # they look imported (are present in sys.module) but the
        # name is not present in the PyQt4 package
        import PyQt4
        PyQt4.QtGui = sys.modules['PyQt4.QtGui']
        PyQt4.QtCore = sys.modules['PyQt4.QtCore']
        PyQt4.QtSvg = sys.modules['PyQt4.QtSvg']


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
        fix_ipython_241()
        return True
    if base+'.QtGui' in sys.modules:
        fix_ipython_241()
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

