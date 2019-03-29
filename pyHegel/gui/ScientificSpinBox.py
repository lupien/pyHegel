#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2018-2018  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from __future__ import print_function, division

__all__ = ['PyScientificSpinBox']

from PyQt5 import QtGui, QtCore, QtWidgets
from PyQt5.QtWidgets import QDoubleSpinBox, QAbstractSpinBox, QAction, QActionGroup, QMenu, QApplication, QMessageBox, \
                            QStyleOptionSpinBox, QSpinBox, QWidgetAction
from PyQt5.QtGui import QValidator, QDoubleValidator, QKeySequence
from PyQt5.QtCore import pyqtSlot, pyqtSignal, pyqtProperty, Q_ENUMS, Q_FLAGS, QTimer, QSize, QEvent
from enum import Enum

import re
import numpy as np
import weakref

# from https://www.jdreaver.com/posts/2014-07-28-scientific-notation-spin-box-pyside.html

units = dict(Y=1e24, Z=1e21, E=1e18, P=1e15, T=1e12, G=1e9, M=1e6, k=1e3, h=1e2, da=1e1,
             b=1.,
             d=1e-1, c=1e-2, m=1e-3, n=1e-9, p=1e-12, f=1e-15, a=1e-18, z=1e-21, y=1e-24)
units.update( {u'µ':1e-6} )
units_alias = dict(u=u'µ')

units_possible = '|'.join(list(units.keys()) + list(units_alias.keys()))
units_inverse = { np.round(np.log10(v)):k for k, v in units.items()}

# Regular expression to find floats. Match groups are the whole string, the
# whole coefficient, the decimal part of the coefficient, and the exponent
# part.

#_float_re = re.compile(r'^ *(?P<pre>.*?) *(?P<fullnum>(?P<mantissa>[+-]?(\d+(\.\d*)?|\.\d+))(?P<exponent>[eE][+-]?\d+)?) *(?P<unit>%s)? *(?P<post>.*?)$'%units_possible)
_float_re = re.compile(r'^ *(?P<fullnum>(?P<mantissa>[+-]? *?(\d[\d ]*(\.[\d ]*)?|\.[\d ]+))(?P<exponent>[eE] *[+-]? *\d+)?|nan|[+-]?inf) *(?P<unit>%s)? *$'%units_possible)

MAX_PRECISION = 50
MAX_FIXED_EXP = 308

class FloatValidator(QValidator):
    def __init__(self):
        self.prefix = ''
        self.suffix = ''

    def clean_suffix_prefix(self, text, pos=None):
        prefix = self.prefix
        suffix = self.suffix
        if prefix and text.startswith(prefix):
            text = text[len(prefix):]
            if pos is not None:
                pos -= len(prefix)
        if suffix and text.endswith(suffix):
            text = text[:-len(suffix)]
        if pos is not None:
            pos = min(pos, len(text))
            return text, pos
        return text

    def valid_float_string(self, string):
        string = self.clean_suffix_prefix(string)
        match = _float_re.search(string)
        if match and match.groupdict()['fullnum'].replace(' ', ''): # not just spaces
            return True
        return False

    def validate(self, string, position):
        #print( 'Validating ', string, position)
        if self.valid_float_string(string):
            return self.Acceptable, string, position
        #return self.Invalid, string, position
        return self.Intermediate, string, position

    def fixup(self, text):
        return text

    def _handle_unit(self, match):
        number = match.groupdict()['fullnum']
        unit = match.groupdict()['unit']
        val = float(number.replace(' ', ''))
        scale = None
        if unit:
            unit = units_alias.get(unit, unit)
            scale = units[unit]
            val *= scale
        else:
            exp =  match.groupdict()['exponent']
            if exp and exp[0] == 'e':
                scale = 10.**int(exp[1:].replace(' ', ''))
        return val, unit, scale

    def find_increment(self, string, position):
        string, pos = self.clean_suffix_prefix(string, position)
        match = _float_re.search(string)
        if match:
            val, unit, scale = self._handle_unit(match)
            mantissa = match.groupdict()['mantissa']
            pos -= string.find(mantissa)
            if mantissa[0] in ['+', '-']:
                mantissa = mantissa[1:]
                pos -= 1
            m = mantissa.replace(' ', '')
            if pos >= len(mantissa):
                pos = len(m)
            elif pos >= 0:
                pos -= mantissa.count(' ', 0, pos)
            if m[pos -1] == '.':
                pos -= 1
            if pos <= 0:
                m = '0' + m
                pos = 1
            if '.' in m:
                m1, m2 = m.split('.')
                m = '0'*len(m1) + '.' + '0'*len(m2)
            else:
                m = '0'*len(m)
            # do equivalent of: m[pos-1] = '1'
            m = m[:pos-1] + '1' + m[pos:]
            if scale is not None:
                incr = float(m)*scale
            else:
                incr = float(m)
            if val != 0:
                val_scale = 10.**np.floor(np.log10(np.abs(val)))
                log_incr = incr/val_scale
            else:
                log_incr = None
            return incr, log_incr
        return None

    def valueFromText(self, text):
        text = self.clean_suffix_prefix(text)
        match = _float_re.search(text)
        val, unit, scale = self._handle_unit(match)
        return val, unit, scale

class PyScientificSpinBox(QDoubleSpinBox):
    # This is emited like valueChanged, but not when using setValue_quiet and not within valueChange_gui_time
    valueChanged_gui = pyqtSignal(float)

    # For PyQt < 5.11: only a class with attributes using integer can be made an enum
    #                  (so simple object subclass)
    #        from 5.11: Enum class can also be used. (also Q_ENUMS, Q_FLAGS are depracated for Q_ENUM and Q_FLAG)
    # Version can be obtain as:
    #   import PyQt5.QtCore
    #   PyQt5.QtCore.PYQT_VERSION_STR
    #class Sci_Mode(Enum):
    class Sci_Mode(object):
        ENG_UNIT, ENG, SCI = range(3)
    Q_ENUMS(Sci_Mode)
    class Enabled_Controls(object):
        none = 0x00
        minimum = 0x01
        maximum = 0x02
        min_increment = 0x04
        precision = 0x08
        display_mode = 0x10
        log_increment_mode = 0x20
        fixed_exponent = 0x40
        all = 0x7f
        minmax = 0x03
        no_minmax = all & ~minmax
    Q_FLAGS(Enabled_Controls)

    def __init__(self, *args, **kwargs):
        """ display_mode can be any of the Sci_Mode enum: ENG_UNIT (default), ENG or SCI
            To have a unit, set the suffix.
            keyboardTracking is disabled by default.
            accelerated is enabled by default
            decimals is overriden and redirected to precision.
            A new signal, valueChanged_gui, is emitted when the value is updated but at a restricted rate,
                 valueChange_gui_time, and also when pressing enter. It is not emitted when using
                 setValue_quiet
            option disable_context_menu can be used to disable the context menu. It is False by default.
            enabled_controls property can be used to disable some entries in the context_menu
        """
        self._initializing = True
        self._in_setValue_quiet = False
        key_track = kwargs.pop('keyboardTracking', False)
        kwargs['keyboardTracking'] = key_track
        # need to handle min/max before decimal
        self._disable_context_menu = kwargs.pop('disable_context_menu', False)
        maximum = kwargs.pop('maximum', np.inf)
        minimum = kwargs.pop('minimum', -np.inf)
        accelerated = kwargs.pop('accelerated', True)
        decimals = kwargs.pop('decimals', 5)
        precision = kwargs.pop('precision', decimals)
        self.text_formatter = Format_Float()
        self.text_formatter.precision = precision
        self.validator = FloatValidator()
        self._min_increment = 1e-15
        self._log_increment_mode = False
        self._log_increment = 0.01
        self._display_mode = self.Sci_Mode.ENG_UNIT
        self._enabled_controls = self.Enabled_Controls.all
        self._last_enabled_controls = None
        self._valueChange_timer = QTimer()
        self._valueChange_timer.setInterval(100) # ms
        # We override decimals. This should set the parent value.
        kwargs['decimals'] = 1000 # this get adjusted to max double  precision (323)
        kwargs['accelerated'] = accelerated
        kwargs['minimum'] = minimum
        kwargs['maximum'] = maximum
        # Note that this will call all properties that are left in kwargs
        super(PyScientificSpinBox, self).__init__(*args, **kwargs)
        # decimals is used when changing min/max, on setValue and on converting value to Text (internally, it is overriden here)
        #super(PyScientificSpinBox, self).setDecimals(1000) # this get adjusted to max double  precision (323)
        # make sure parent class decimals is set properly
        if super(PyScientificSpinBox, self).decimals() < 323:
            raise RuntimeError('Unexpected parent decimals value.')
        # The suffix/prefix change in the above QDoubleSpinBox.__init__ did not call our override
        # lets update them now
        self.setSuffix(self.suffix())
        self.setPrefix(self.prefix())
        # pyqt5 5.6 on windows (at least) QAction requires the parent value.
        self.copyAction = QAction('&Copy', None, shortcut=QKeySequence(QKeySequence.Copy), triggered=self.handle_copy)
        self.pasteAction = QAction('&Paste', None, shortcut=QKeySequence(QKeySequence.Paste), triggered=self.handle_paste)
        self.addActions(( self.copyAction, self.pasteAction))
        self._create_menu_init()
        self.clipboard = QApplication.instance().clipboard()
        self._last_valueChanged_gui = self.value()
        self._current_valueChanged_gui = self._last_valueChanged_gui
        self.valueChanged.connect(self._valueChanged_helper)
        self._valueChange_timer.timeout.connect(self._do_valueChanged_gui_emit)
        self._last_focus_reason_mouse = False
        self.lineEdit().installEventFilter(self)
        self.text_is_being_changed_state = False
        self.lineEdit().textEdited.connect(self.text_is_being_changed)
        self._last_key_pressed_is_enter = False
        self.editingFinished.connect(self.editFinished_slot)
        self._in_config_menu = False
        self._initializing = False

    def _create_menu_init(self):
        if self._disable_context_menu:
            return
        # pyqt5 5.6 on windows (at least) QAction requires the parent value.
        self.accel_action = QAction('&Acceleration', None, checkable=True, checked=self.isAccelerated(), triggered=self.setAccelerated)
        self.log_increment_mode_action = QAction('&Log increment', None, checkable=True, checked=self.log_increment_mode, triggered=self.log_increment_mode_change)
        self.help_action = QAction('&Help', None, triggered=self.help_dialog)
        self.stepUpAction = QAction('Step &up', None)
        self.stepUpAction.triggered.connect(self.stepUp)
        self.stepDownAction = QAction('Step &down', None)
        self.stepDownAction.triggered.connect(self.stepDown)
        self.display_mode_grp = QActionGroup(None)
        self.display_mode_eng_unit = QAction('Engineering with &units', None, checkable=True)
        self.display_mode_eng = QAction('&Engineering', None, checkable=True)
        self.display_mode_sci = QAction('&Scientific', None, checkable=True)
        self.display_mode_option = {self.Sci_Mode.ENG_UNIT: self.display_mode_eng_unit,
                                    self.Sci_Mode.ENG: self.display_mode_eng,
                                    self.Sci_Mode.SCI: self.display_mode_sci}
        self.display_mode_grp.addAction(self.display_mode_eng_unit)
        self.display_mode_grp.addAction(self.display_mode_eng)
        self.display_mode_grp.addAction(self.display_mode_sci)
        self.display_mode_grp.triggered.connect(self.handle_display_mode)
        # fixed exponent
        self.fixed_exponent_menu = submenu = QMenu('&Fixed exponent')
        self.fixed_exponent_group = subgroup = QActionGroup(None)
        self.fixed_exponent_actions = actions = {}
        for i in range(-15, 9+1, 3)[::-1]:
            if i == 0:
                act = QAction('%i: %s'%(i, ''), None, checkable=True)
            else:
                act = QAction('%i: %s'%(i, units_inverse[i]), None, checkable=True)
            submenu.addAction(act)
            subgroup.addAction(act)
            actions[i] = act
        act = QAction('&Custom', None, checkable=True)
        submenu.addAction(act)
        subgroup.addAction(act)
        actions['custom'] = act
        self.fixed_exponent_custom_action = QWidgetAction(None)
        self.fixed_exponent_custom_widget = QSpinBox(value=0, minimum=-MAX_FIXED_EXP, maximum=MAX_FIXED_EXP)
        self.fixed_exponent_custom_action.setDefaultWidget(self.fixed_exponent_custom_widget)
        submenu.addAction(self.fixed_exponent_custom_action)
        submenu.addSeparator()
        act = QAction('&Disabled', None, checkable=True)
        submenu.addAction(act)
        subgroup.addAction(act)
        actions['disabled'] = act
        subgroup.triggered.connect(self.handle_fixed_exponent)
        self.fixed_exponent_custom_widget.valueChanged.connect(self.handle_fixed_exponent)
        # precision
        self.precision_menu = submenu = QMenu('&Precision')
        self.precision_group = subgroup = QActionGroup(None)
        self.precision_actions = actions = {}
        for i in range(0,10):
            act = QAction('&%i'%i, None, checkable=True)
            submenu.addAction(act)
            subgroup.addAction(act)
            actions[i] = act
        act = QAction('&Custom', None, checkable=True)
        submenu.addAction(act)
        subgroup.addAction(act)
        actions['custom'] = act
        self.precision_custom_action = QWidgetAction(None)
        self.precision_custom_widget = QSpinBox(value=0, minimum=0, maximum=MAX_PRECISION)
        self.precision_custom_action.setDefaultWidget(self.precision_custom_widget)
        submenu.addAction(self.precision_custom_action)
        subgroup.triggered.connect(self.handle_precision)
        self.precision_custom_widget.valueChanged.connect(self.handle_precision)
        # min, max, min_increment
        self.min_custom_action = QWidgetAction(None)
        self.min_custom_widget = PyScientificSpinBox(prefix='min: ', disable_context_menu=True)
        self.min_custom_action.setDefaultWidget(self.min_custom_widget)
        self.min_custom_widget.valueChanged.connect(self.handle_min_custom_widget)
        self.max_custom_action = QWidgetAction(None)
        self.max_custom_widget = PyScientificSpinBox(prefix='max: ', disable_context_menu=True)
        self.max_custom_action.setDefaultWidget(self.max_custom_widget)
        self.max_custom_widget.valueChanged.connect(self.handle_max_custom_widget)
        self.min_incr_custom_action = QWidgetAction(None)
        self.min_incr_custom_widget = PyScientificSpinBox(prefix='min incr: ', disable_context_menu=True)
        self.min_incr_custom_action.setDefaultWidget(self.min_incr_custom_widget)
        self.min_incr_custom_widget.valueChanged.connect(self.handle_min_incr_custom_widget)
        self.display_mode_sep = QAction('Display mode', None)
        self.display_mode_sep.setSeparator(True)

    def text_is_being_changed(self):
        self.text_is_being_changed_state = True

    def _create_menu(self):
        ec = self.enabled_controls
        EC = self.Enabled_Controls
        if ec == self._last_enabled_controls:
            return self.modified_context_menu
        self._last_enabled_controls = ec
        #self.modified_context_menu = menu = self.lineEdit().createStandardContextMenu()
        self.modified_context_menu = menu = QMenu('Main Menu')
        menu.addActions(( self.copyAction, self.pasteAction ))
        menu.addSeparator()
        menu.addActions(( self.stepUpAction, self.stepDownAction ))
        menu.addSeparator()
        if ec & EC.display_mode:
            menu.addActions(( self.display_mode_sep, self.display_mode_eng_unit, self.display_mode_eng, self.display_mode_sci ))
            menu.addSeparator()
        menu.addAction(self.accel_action)
        if ec & EC.log_increment_mode:
            menu.addAction(self.log_increment_mode_action)
        if ec & EC.fixed_exponent:
            menu.addMenu(self.fixed_exponent_menu)
        if ec & EC.precision:
            menu.addMenu(self.precision_menu)
        menu.addActions( (self.min_custom_action, self.max_custom_action, self.min_incr_custom_action))
        self.min_custom_action.setEnabled(ec & EC.minimum)
        self.max_custom_action.setEnabled(ec & EC.maximum)
        self.min_incr_custom_action.setEnabled(ec & EC.min_increment)
        menu.addSeparator()
        menu.addAction(self.help_action)
        return menu

    #def __del__(self):
    #    print('Deleting up PyScientificSpinBox')

    def pyqtConfigure(self, **kwargs):
        # this is necessary to override pyqtConfigure decimals
        # otherwise it calls the parent one directly.
        decimals = kwargs.pop('decimals', None)
        if decimals is not None:
            self.setDecimals(decimals)
        # same thing for suffix/prefix
        prefix = kwargs.pop('prefix', None)
        if prefix is not None:
            self.setPrefix(prefix)
        suffix = kwargs.pop('suffix', None)
        if suffix is not None:
            self.setSuffix(suffix)
        if len(kwargs):
            super(PyScientificSpinBox, self).pyqtConfigure(**kwargs)

    def get_config(self):
        """ The return value can by used in pyqtConfigure.
        """
        return dict(display_mode=self.display_mode,
                    precision=self.precision,
                    min_increment=self.min_increment,
                    minimum=self.minimum(),
                    maximum=self.maximum(),
                    log_increment_mode=self.log_increment_mode,
                    log_increment=self.log_increment,
                    fixed_exponent=self.fixed_exponent,
                    suffix=self.suffix(),
                    prefix=self.prefix(),
                    singleStep=self.singleStep(),
                    accelerated=self.isAccelerated(),
                    wrapping=self.wrapping(),
                    keyboardTracking=self.keyboardTracking())

    def force_update(self):
        val = self.value()
        self.setValue(val)
        self.selectAll()

    def decimals(self):
        return self.precision
    def setDecimals(self, val):
        self.precision = val

    @pyqtProperty(Enabled_Controls)
    def enabled_controls(self):
        return self._enabled_controls
    @enabled_controls.setter
    def enabled_controls(self, val):
        self._enabled_controls = val

    @pyqtProperty(Sci_Mode)
    #@pyqtProperty(int)
    def display_mode(self):
        return self._display_mode
    @display_mode.setter
    def display_mode(self, val):
        self._display_mode = val
        self.force_update()
        self.updateGeometry()

    @pyqtProperty(int)
    def min_increment(self):
        return self._min_increment
    @min_increment.setter
    def min_increment(self, val):
        self._min_increment = val
        if self.singleStep() < val:
            self.setSingleStep(val)

    @pyqtProperty(int)
    def precision(self):
        return self.text_formatter.precision
    @precision.setter
    def precision(self, val):
        val = min(max(val, 0), MAX_PRECISION)
        self.text_formatter.precision = val
        self.force_update()
        self.updateGeometry()

    @pyqtProperty(bool)
    def log_increment_mode(self):
        return self._log_increment_mode
    @log_increment_mode.setter
    def log_increment_mode(self, val):
        self._log_increment_mode = val

    @pyqtProperty(float)
    def log_increment(self):
        return self._log_increment
    @log_increment.setter
    def log_increment(self, val):
        self._log_increment = val

    @pyqtProperty(int)
    def fixed_exponent(self):
        """ 9999 disables fixed exponent mode """
        val = self.text_formatter.fixed_exponent
        if val is None:
            return 9999
        return val
    @fixed_exponent.setter
    def fixed_exponent(self, val):
        if val == 9999:
            val = None
        else:
            # keep within -308 to 308: MAX_FIXED_EXP = 308
            val = max(val, -MAX_FIXED_EXP)
            val = min(val, MAX_FIXED_EXP)
        self.text_formatter.fixed_exponent = val
        self.force_update()
        self.updateGeometry()

    @pyqtProperty(float)
    def valueChange_gui_time(self):
        return self._valueChange_timer.interval()/1e3
    @valueChange_gui_time.setter
    def valueChange_gui_time(self, val):
        val = int(val*1e3)
        if val <= 0:
            self._valueChange_timer.stop()
        self._valueChange_timer.setInterval(val)

    def keyPressEvent(self, event):
        key = event.key()
        self._last_key_pressed_is_enter = False
        if event.matches(QKeySequence.Copy):
            #print('doing copy')
            self.copyAction.trigger()
        elif event.matches(QKeySequence.Paste):
            #print('doing paste')
            self.pasteAction.trigger()
        elif key == QtCore.Qt.Key_Escape:
            if self.text_is_being_changed_state:
                #print('doing escape')
                self.setValue(self.value())
            else:
                #print('letting escape propagate')
                event.ignore()
        else:
            if key in [QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return]:
                self._last_key_pressed_is_enter = True
            super(PyScientificSpinBox, self).keyPressEvent(event)

    # Can't seem to do the same thing (stop short timer) for wheelEvent
    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat() and event.key() in [QtCore.Qt.Key_Up, QtCore.Qt.Key_Down, QtCore.Qt.Key_PageUp, QtCore.Qt.Key_PageDown]:
            self._valueChange_timer.stop()
            self._do_valueChanged_gui_emit()
        super(PyScientificSpinBox, self).keyReleaseEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._valueChange_timer.stop()
            self._do_valueChanged_gui_emit()
        super(PyScientificSpinBox, self).mouseReleaseEvent(event)

    def mousePressEvent(self, event):
        self._last_focus_reason_mouse = False
        super(PyScientificSpinBox, self).mousePressEvent(event)

    def focusInEvent(self, event):
        if event.reason() == QtCore.Qt.MouseFocusReason:
            self._last_focus_reason_mouse = True
        l = self.lineEdit()
        super(PyScientificSpinBox, self).focusInEvent(event)
        # Using tab to activate widget already does this.
        # It is necessary so that pressing the up/down buttons directly from another widget
        # does not increment before the unit (because position is 0, selection is False)
        self.selectAll()

    def editFinished_slot(self):
        self.text_is_being_changed_state = False
        if self._last_key_pressed_is_enter:
            self._last_key_pressed_is_enter = False
            self._do_valueChanged_gui_emit(force=True)

    def eventFilter(self, watched_obj, event):
        if event.type() == QEvent.MouseButtonPress and self._last_focus_reason_mouse:
            self._last_focus_reason_mouse = False
            return True
        return False

    def handle_copy(self):
        #print('handling copy')
        self.clipboard.setText('%r'%self.value())

    def handle_paste(self):
        #print('handling paste')
        text = self.clipboard.text()
        # let user decide if it is ok by pressing ok (not esc)
        self.lineEdit().setText(text)
        self.text_is_being_changed_state = True
        # update value immediately
        #try:
        #    self.setValue(float(text))
        #except ValueError: # maybe text is not pure number (contains units)
        #    self.lineEdit().setText(text)
        #    self.interpretText()

    def handle_display_mode(self, action):
        if self._in_config_menu:
            return
        mode = [k for k,v in self.display_mode_option.items() if v == action][0]
        self.display_mode = mode

    def handle_fixed_exponent(self, action_or_val):
        if self._in_config_menu:
            return
        if isinstance(action_or_val, QAction):
            enable = False
            action = [k for k,v in self.fixed_exponent_actions.items() if v == action_or_val][0]
            if action == 'disabled':
                self.fixed_exponent = 9999
            elif action == 'custom':
                enable = True
                self.fixed_exponent = self.fixed_exponent_custom_widget.value()
            else:
                self.fixed_exponent = action
            self.fixed_exponent_custom_action.setEnabled(enable)
        else:
            self.fixed_exponent = action_or_val

    def handle_precision(self, action_or_val):
        if self._in_config_menu:
            return
        if isinstance(action_or_val, QAction):
            enable = False
            action = [k for k,v in self.precision_actions.items() if v == action_or_val][0]
            if action == 'custom':
                enable = True
                self.precision = self.precision_custom_widget.value()
            else:
                self.precision = action
            self.precision_custom_action.setEnabled(enable)
        else:
            self.precision = action_or_val

    def handle_min_custom_widget(self, val):
        if self._in_config_menu:
            return
        self.setMinimum(val)
    def handle_max_custom_widget(self, val):
        if self._in_config_menu:
            return
        self.setMaximum(val)
    def handle_min_incr_custom_widget(self, val):
        if self._in_config_menu:
            return
        self.min_increment = val

    def setSuffix(self, string):
        self.validator.suffix = string
        super(PyScientificSpinBox, self).setSuffix(string)
        self.updateGeometry()

    def setPrefix(self, string):
        self.validator.prefix = string
        super(PyScientificSpinBox, self).setPrefix(string)
        self.updateGeometry()

    def contextMenuEvent(self, event):
        if self._disable_context_menu:
            return
        self._in_config_menu = True
        menu = self._create_menu()
        se = self.stepEnabled()
        self.stepUpAction.setEnabled(se & QAbstractSpinBox.StepUpEnabled)
        self.stepDownAction.setEnabled(se & QAbstractSpinBox.StepDownEnabled)
        mode = self.display_mode
        self.display_mode_option[mode].setChecked(True)
        self.log_increment_mode_action.setChecked(self.log_increment_mode)
        self.accel_action.setChecked(self.isAccelerated())
        # fixed_exponent
        fe = self.fixed_exponent
        if fe == 9999:
            fe = 'disabled'
        action = self.fixed_exponent_actions.get(fe, None)
        fe_action_custom = self.fixed_exponent_actions['custom']
        if fe_action_custom.isChecked() or action is None:
            action = fe_action_custom
            self.fixed_exponent_custom_action.setEnabled(True)
            self.fixed_exponent_custom_widget.setValue(fe)
        else:
            self.fixed_exponent_custom_action.setEnabled(False)
        action.setChecked(True)
        # precision
        prec = self.precision
        action = self.precision_actions.get(prec, None)
        prec_action_custom = self.precision_actions['custom']
        if prec_action_custom.isChecked() or action is None:
            action = prec_action_custom
            self.precision_custom_action.setEnabled(True)
            self.precision_custom_widget.setValue(prec)
        else:
            self.precision_custom_action.setEnabled(False)
        action.setChecked(True)
        #min
        conf = self.get_config()
        del conf['prefix'], conf['maximum'], conf['minimum'], conf['min_increment']
        conf['keyboardTracking'] = False
        self.min_custom_widget.pyqtConfigure(value=self.minimum(), **conf)
        self.max_custom_widget.pyqtConfigure(value=self.maximum(), **conf)
        self.min_incr_custom_widget.pyqtConfigure(value=self.min_increment, minimum=0.,**conf)
        self._in_config_menu = False
        menu.exec_(event.globalPos())

    def validate(self, text, position):
        if self._initializing:
            return QValidator.Invalid, text, position
        return self.validator.validate(text, position)

    def fixup(self, text):
        return self.validator.fixup(text)

    def valueFromText(self, text):
        val, unit, scale = self.validator.valueFromText(text)
        if unit:
            if val == 0:
                self.text_formatter.decode_eng(scale) # update last_exp
        return val

    def textFromValue(self, value, tmp=False):
        #mode = self.display_mode_grp.checkedAction()
        mode = self.display_mode
        fmt = self.text_formatter
        fmt_func_d = {self.Sci_Mode.ENG_UNIT: fmt.to_eng_unit,
                      self.Sci_Mode.ENG: fmt.to_eng,
                      self.Sci_Mode.SCI: fmt.to_float}
        suffix = self.suffix()
        ret = fmt_func_d[mode](value, suffix, tmp)
        return ret

    # this is needed because setAccelerated is not a slot, which makes
    # using it connect block deletes. wrapping it in python makes it work properly.
    def setAccelerated(self, val):
        if self._in_config_menu:
            return
        super(PyScientificSpinBox, self).setAccelerated(val)

    def log_increment_mode_change(self, val):
        if self._in_config_menu:
            return
        self.log_increment_mode = val

    def setSingleStep_bounded(self, incr):
        incr = max(incr, self.min_increment)
        self.setSingleStep(incr)

    @pyqtSlot(int)
    def stepBy(self, steps):
        pos = self.lineEdit().cursorPosition()
        if not self.lineEdit().hasSelectedText():
            text = self.lineEdit().text()
            special = self.specialValueText()
            if not (special and special == text):
                incr, log_incr = self.validator.find_increment(text, pos)
                self.setSingleStep_bounded(incr)
                if log_incr is not None:
                    self.log_increment = log_incr
        if self.log_increment_mode:
            #frac = self._adapative_step_frac
            #frac = .01
            frac = self.log_increment
            frac_exp = np.floor(np.log10(frac))
            cval = self.value()
            step_dir  = np.sign(steps)
            val_dir = np.sign(cval)
            min_increment = self.min_increment
            for i in range(np.abs(steps)):
                cval = self.value()
                val_dir = np.sign(cval)
                abs_cval = np.abs(cval)
                abs_increase = val_dir == step_dir
                if cval == 0:
                    incr = min_increment
                elif abs_cval < min_increment:
                    if abs_increase:
                        incr = min_increment - cval
                    else:
                        #incr = abs_cval
                        self.setValue(0)
                        continue
                else:
                    incr = abs_cval*frac
                    cval_exp = np.log10(abs_cval)
                    incr_exp = np.floor(cval_exp+frac_exp)
                    incr = 10.**incr_exp
                    if not abs_increase:
                        incr_1 = 10.**(incr_exp -1)
                        if np.log10(np.abs(cval)-incr_1) < np.floor(cval_exp):
                            incr = incr_1
                self.setSingleStep_bounded(incr)
                super(PyScientificSpinBox, self).stepBy(step_dir)
        else:
            super(PyScientificSpinBox, self).stepBy(steps)

    def _do_valueChanged_gui_emit(self, val=None, force=False):
        if val is None:
            val = self._current_valueChanged_gui
        if val != self._last_valueChanged_gui or force:
            self._last_valueChanged_gui = val
            self.valueChanged_gui.emit(val)
        else:
            self._valueChange_timer.stop()

    @pyqtSlot(float)
    def _valueChanged_helper(self, val):
        if not self._in_setValue_quiet:
            self._current_valueChanged_gui = val
            if not self._valueChange_timer.isActive():
                self._do_valueChanged_gui_emit(val)
                if self.valueChange_gui_time > 0:
                    self._valueChange_timer.start()

    def setValue_quiet(self, val):
        self._in_setValue_quiet = True
        self.setValue(val)
        self._in_setValue_quiet = False

    def _sizeHint_helper(self, minimum=False):
        self.ensurePolished()
        # code from widgets/qabstractspinbox.cpp
        fm = self.fontMetrics() # migth need a copy
        try:
            fmw = fm.horizontalAdvance
        except AttributeError:
            fmw = fm.width
        h = self.lineEdit().sizeHint().height()
        w = 0
        if minimum:
            fixedContent = self.prefix() + " "
        else:
            fixedContent = self.prefix() + self.suffix() + " "
        val = -988.888e-99
        if self.fixed_exponent != 9999:
            if self.maximum() != np.inf:
                val = self.maximum()
            else:
                val = -999888. * 10.**self.fixed_exponent
        s = self.textFromValue(val, tmp=True)
        s += fixedContent
        w = fmw(s)
        special = self.specialValueText()
        if special:
            w = max(w, fmw(special))
        w += 2 # cursor blinking space
        hint = QSize(w, h)
        opt = QStyleOptionSpinBox()
        self.initStyleOption(opt)
        style = self.style()
        hint = style.sizeFromContents(style.CT_SpinBox, opt, QSize(w, h), self)
        qapp = QApplication.instance()
        hint = hint.expandedTo(qapp.globalStrut())
        return hint

    def minimumSizeHint(self):
        return self._sizeHint_helper(minimum=True)
    def sizeHint(self):
        return self._sizeHint_helper()


   # Observations from QDoubleSpinBox code:
   #  minimumSizeHint is the same as SizeHint less the space for suffix
   #  sizeHint
   #     # internal commands is space of prefix+suffix+max(min, max, special)+graphical elements
   #     # note that text is limited to 18 char.
   # sizeHint is recalculated and advertised when calling setSuffix (doubleSpinBox.setPrefix seems to only update text)
   #  aslo setMinimum, setMaximum, setRange all update the geometry
   # setSpecialValueText, setValue, setSingleStep and setSuffix all update the text

    help_text = u"""
For entry you can use scientific entry (like 1e-3) or units. You can add spaces.
The available units are (they are case sensitive):
     Y(1e24), Z, E, P, T, G, M, k(1e3), h(100), da(10), d(0.1), c, m, µ, n, p, f, a, z, y(1e-24)
you can use u instead of µ, and b for no unit (1)

The arrows, or the mouse wheel steps the value.
Page up/down steps the value 10 times faster. Using the CTRL key also goes 10 times faster but only for wheel events.
If you change the cursor position (left/right keys or mouse click) before stepping, the number
to the left of the cursor is incremented by 1.
Adapatative option will increase in a logarithmic way.
Acceleration is a speed up of the steps when pressing the GUI button.
"""
    def help_dialog(self):
        dialog = QMessageBox.information(self, 'Entry Help', self.help_text)

class Format_Float(object):
    def __init__(self, precision=14, last_exponent=0, fixed_exponent=None):
        """ precision means the number of points after the decimal point
        """
        self.precision = precision
        self.last_exponent = last_exponent
        self.fixed_exponent = fixed_exponent

    def pre_decode(self, value):
        fmt = '{:^%i}'%(self.precision+6)
        conv = lambda x: fmt.format(x)
        if np.isnan(value):
            return conv('nan'), 0
        if value == np.inf:
            return conv('+inf'), 0
        if value == -np.inf:
            return conv('-inf'), 0
    def decode_eng(self, value, tmp=False):
        ret = self.pre_decode(value)
        if ret:
            return ret
        fmt = '%.{}f'.format(self.precision)
        exp_fix_round = None
        if self.fixed_exponent is not None:
            exp_fix_round = self.fixed_exponent//3 *3
        if value == 0:
            if exp_fix_round is not None:
                return fmt%0, exp_fix_round
            return fmt%0, self.last_exponent
        exp = np.log10(np.abs(value))
        exp_round = exp//3 *3
        #exp_round = (exp-0.00000001)//3 *3 # this make 1000 stay 1000 instead of 1e3
        if not tmp:
            self.last_exponent = exp_round
        if exp_fix_round is not None:
            exp_round = exp_fix_round
        value = value/10**exp_round
        value_str = fmt%value
        return value_str, exp_round

    def to_eng(self, value, suffix, tmp=False):
        string, exp_round = self.decode_eng(value, tmp)
        if exp_round != 0:
            string += 'e%i'%exp_round
        if suffix:
            string += ' '
        return string

    def to_eng_unit(self, value, suffix, tmp=False):
        string, exp_round = self.decode_eng(value, tmp)
        if exp_round != 0:
            try:
                string += ' %s'%units_inverse[exp_round]
            except KeyError: # outside of usual units
                return self.to_eng(value, suffix, tmp)
        elif suffix:
            string += ' '
        return string

    def to_float(self, value, suffix, tmp=False):
        """Modified form of the 'g' format specifier."""
        self.decode_eng(value, tmp) # to update last_exponent
        ret = self.pre_decode(value)
        if ret:
            return ret[0]
        fmt = '%.{}fe%i'.format(self.precision)
        if suffix:
            fmt += ' '
        exp_fixed = None
        if self.fixed_exponent is not None:
            exp_fixed = self.fixed_exponent
        if value == 0:
            if exp_fixed is not None:
                return fmt%(0, exp_fixed)
            return fmt%(0,0)
        exp = np.log10(np.abs(value)) if exp_fixed is None else exp_fixed
        exp_round = exp//1
        value = value/10**exp_round
        return fmt%(value, exp_round)

if __name__ == "__main__":
    QWidget = QtWidgets.QWidget
    QHBoxLayout = QtWidgets.QHBoxLayout
    # When run under ipython with QApplication already started, don't run event loop.
    qApp = QApplication.instance()
    if qApp is None:
        do_exec = True
        qApp = QApplication([' '])
        _qApp = qApp # So it does not get erased upon reload
    else:
        try:
            do_exec
        except NameError:
            do_exec = False

    main_widget = QWidget()
    spin1 = PyScientificSpinBox(suffix='V')
    spin2 = PyScientificSpinBox(suffix='V')
    layout = QHBoxLayout()
    layout.addWidget(spin1)
    layout.addStretch(1)
    layout.addWidget(spin2)
    main_widget.setLayout(layout)

    main_widget.show()

    if do_exec:
        qApp.exec_()

