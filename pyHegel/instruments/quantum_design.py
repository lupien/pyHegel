# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2021-2021  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from __future__ import absolute_import

import os.path

from ..instruments_base import BaseInstrument, BaseDevice,\
                            MemoryDevice, locked_calling,\
                            wait, ProxyMethod, wait_on_event

from ..instruments_registry import register_instrument

clr = None
Int32 = None
Int64 = None
IntPtr = None
EnumGetNames = None
EnumGetValues = None
QDInstrument = None
QDInstrumentBase = None
QDInstrumentFactory = None
QDTypes = None
_assembly_Version = None

_delayed_imports_done = False

def _delayed_imports():
    global _delayed_imports_done
    if not _delayed_imports_done:
        global clr, EnumGetNames, EnumGetValues, QDInstrument, QDInstrumentBase, QDInstrumentFactory, QDTypes, _assembly_Version
        try:
            import clr
            from System import Enum
            EnumGetNames = Enum.GetNames
            EnumGetValues = Enum.GetValues
        except ImportError as exc:
            raise RuntimeError('Unable to import windows clr/System: %s'%exc)
        try:
#            _datatranslation_dir = r'C:\Program Files (x86)\Data Translation\DotNet\OLClassLib\Framework 2.0 Assemblies'
#            if not os.path.isdir(_datatranslation_dir):
#                # Version 6.1.0 has a slightly different directory name:
#                _datatranslation_dir += ' (32-bit)'
#            if _datatranslation_dir not in sys.path:
#                sys.path.append(_datatranslation_dir)
            clr.AddReference('QDInstrument')
            import QuantumDesign.QDInstrument as QDInstrument
            from QuantumDesign.QDInstrument import QDInstrumentBase, QDInstrumentFactory
            QDTypes = QDInstrumentBase.QDInstrumentType
            assembly = clr.GetClrType(QDInstrumentBase).Assembly
            _assembly_Version = assembly.GetName().Version.ToString()
        except ImportError as exc:
            raise RuntimeError(
                "Unable to load QuantumDesign Module (QDInstrument.dll). Make sure pythonnet and "
                "QDInstrument.dll is installed and unblocked: %s"%exc)
        _delayed_imports_done = True

@register_instrument('Quantum Design', 'PPMS')
class QuantumDesign_PPMS(BaseInstrument):
    def __init__(self, address=None, port=11000, type='ppms', **kwargs):
        """
        address when None is for a local connection. Otherwise it is the
          ip address (dns name) of the server.
        port defaults to 11000.
        type is one of 'ppms',  'versalab', 'dynacool', svsm
        To initialize a device, give it the device name as returned
        by find_all_Ol(), or the integer to use as an index in that
        list (defaults to 0).
        Only one process at a time can access this type of instrument.
        """
        _delayed_imports()
        types_map = dict(ppms=QDTypes.PPMS, versalab=QDTypes.VersaLab, dynacool=QDTypes.DynaCool,
                         svsm=QDTypes.SVSM)
        t = types_map[type]
        self._qd_type = type
        if address is None:
            inst = QDInstrumentFactory.GetQDInstrument(t, False, '', 0)
            self._qd_address = None
        else:
            inst = QDInstrumentFactory.GetQDInstrument(t, True, address, port)
            self._qd_address = (address, port)
        self._qdinst = inst
        make_dict = lambda enum: dict(zip(EnumGetValues(enum), EnumGetNames(enum)))
        self._temp_approaches = list(EnumGetNames(QDInstrumentBase.TemperatureApproach))
        self._field_approaches = list(EnumGetNames(QDInstrumentBase.FieldApproach))
        self._field_modes = list(EnumGetNames(QDInstrumentBase.FieldMode))
        self._pos_modes = list(EnumGetNames(QDInstrumentBase.PositionMode))
        self._chamber_cmds = list(EnumGetNames(QDInstrumentBase.ChamberCommand))
        self._temp_status = make_dict(QDInstrumentBase.TemperatureStatus) # or could use QDInstrumentBase.TemperatureStatusString
        self._field_status = make_dict(QDInstrumentBase.FieldStatus) # or could use QDInstrumentBase.FieldStatusString
        self._chamber_status = make_dict(QDInstrumentBase.ChamberStatus)
        self._pos_status = make_dict(QDInstrumentBase.PositionStatus)
        super(QuantumDesign_PPMS, self).__init__(**kwargs)

    def idn(self):
        return 'Quantum Design,%s,no_serial,no_firmware'%self._qd_type

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        extra = ['AssemblyVersion=%r'%_assembly_Version, 'address=%r'%self._qd_address,
                 'qd_type=%s'%self._qd_type]
        base = self._conf_helper('temp', 'field', 'chamber', 'position', options)
        return extra+base

    def _temp_checkdev(self, val, approach=None, rate=None):
        if approach is not None:
            self.current_temp_approach.check(approach)
        if rate is not None:
            self.temp_rate.check(rate)
        BaseDevice._checkdev(self.temp, val)

    def _temp_setdev(self, val, approach=None, rate=None):
        if approach is not None:
            self.current_temp_approach.set(approach)
        approach = self.current_temp_approach.get()
        if rate is not None:
            self.temp_rate.set(rate)
        rate = self.temp_rate.get()
        approach = getattr(QDInstrumentBase.TemperatureApproach, approach)
        ret = self._qdinst.SetTemperature(val, rate, approach)
        if ret != 1: # This is different than the othes, at least on the instrument I tested
            raise RuntimeError('temp set failed: %i'%ret)

    def _temp_getdev(self, approach=None, rate=None):
        # approach, rate are present because of setget
        ret = self._qdinst.GetTemperature(0., 0) # temperature and status byref
        result, temp, status = ret
        if result != 0:
            raise RuntimeError('temp get failed: %i'%result)
        status_s = self._temp_status[status]
        self.temp_last_status.set(status_s)
        return temp

    def _field_checkdev(self, val, approach=None, mode=None, rate=None):
        if approach is not None:
            self.current_field_approach.check(approach)
        if mode is not None:
            self.current_field_mode.check(mode)
        if rate is not None:
            self.field_rate.check(rate)
        BaseDevice._checkdev(self.field, val)

    def _field_setdev(self, val, approach=None, mode=None, rate=None):
        if approach is not None:
            self.current_field_approach.set(approach)
        approach = self.current_field_approach.get()
        if mode is not None:
            self.current_field_mode.set(mode)
        mode = self.current_field_mode.get()
        if rate is not None:
            self.field_rate.set(rate)
        rate = self.field_rate.get()
        approach = getattr(QDInstrumentBase.FieldApproach, approach)
        mode = getattr(QDInstrumentBase.FieldMode, mode)
        ret = self._qdinst.SetField(val, rate, approach, mode)
        if ret != 0:
            raise RuntimeError('field set failed: %i'%ret)

    def _field_getdev(self, approach=None, mode=None, rate=None):
        # approach, mode, rate are present because of setget
        ret = self._qdinst.GetField(0., 0) # temperature and status byref
        result, field, status = ret
        if result != 0:
            raise RuntimeError('field get failed: %i'%result)
        status_s = self._field_status[status]
        self.field_last_status.set(status_s)
        return field

    def _chamber_setdev(self, cmd):
        cmd = getattr(QDInstrumentBase.ChamberCommand, cmd)
        ret = self._qdinst.SetChamber(cmd)
        if ret != 1: # like temp set
            raise RuntimeError('chamber set failed: %i'%ret)

    def _chamber_getdev(self):
        ret = self._qdinst.GetChamber(0) # temperature and status byref
        result, status = ret
        if result != 0:
            raise RuntimeError('chamber get failed: %i'%result)
        status_s = self._chamber_status[status]
        return status_s
# Note that chamber command and status do not match
    def _position_checkdev(self, val, axis=None, mode=None, speed=None):
        if axis is not None:
            self.current_pos_axis.check(axis)
        if mode is not None:
            self.current_pos_mode.check(mode)
        if speed is not None:
            self.position_speed.check(speed)
        BaseDevice._checkdev(self.position, val)

    def _position_setdev(self, val, axis=None, mode=None, speed=None):
        if axis is not None:
            self.current_pos_axis.set(axis)
        axis = self.current_pos_axis.get()
        if mode is not None:
            self.current_pos_mode.set(mode)
        mode = self.current_pos_mode.get()
        if speed is not None:
            self.position_speed.set(speed)
        speed = self.position_speed.get()
        mode = getattr(QDInstrumentBase.PositionMode, mode)
        ret = self._qdinst.SetPosition(axis, val, speed, mode)
        if ret != 0:
            raise RuntimeError('position set failed: %i'%ret)

    def _position_getdev(self, axis=None, mode=None, speed=None):
        # mode, speed are present because of setget
        if axis is None:
            axis = self.current_pos_axis.get()
        ret = self._qdinst.GetPosition(axis, 0., 0) # temperature and status byref
        result, pos, status = ret
        if result != 0:
            raise RuntimeError('position get failed: %i'%result)
        status_s = self._pos_status[status]
        self.position_last_status.set(status_s)
        return pos

    def _wait_condition(self, temp=False, field=False, pos=False, chamber=False):
        # returns True when the paramters have finished changing.
        if not any([temp, field, pos, chamber]):
            raise ValueError('One of the parameters needs to be True')
        return self._qdinst.WaitConditionReached(temp, field, pos, chamber)

#   The WaitFor does somewhat like the Labview WaitFor does.
#   it waits 2 s than loops for timeout time check like _wait_condition
#   Then it finish with the delay time
#   It cannot be interrupted and it always returns 0.
#     The last 2 parameters are delay, timeout
#   So instead write my own.

    def wait_for(self, temp=False, field=False, pos=False, chamber=False, extra_wait=0., check_timeout=None, pre_check_timeout=60., exc_on_timeout=True):
        """\
            during the pre_check_timeout waits to get the check parameters to return False
            (It sometimes takes a long time for the field sweep to start)
            The checks during check_timeout time (if None, it nevers gives up)
            Then once the check is passed, waits the extra_wait.
            If it times out during check_timeout, it can continue with the wait or raise an exception
             depending on value of exc_on_timeout
        """
        if not any([temp, field, pos, chamber]):
            raise ValueError('One of the parameters needs to be True')
        def pre_check(timeout):
            if not self._wait_condition(temp, field, pos, chamber):
                return True
            else:
                wait(timeout)
                return False
        wait_on_event(pre_check, max_time=pre_check_timeout, progress_base='QD pre wait')
        def check(timeout):
            if self._wait_condition(temp, field, pos, chamber):
                return True
            else:
                wait(timeout)
                return False
        completed = wait_on_event(check, max_time=check_timeout, progress_base='QD stability wait')
        if not completed and exc_on_timeout:
            raise RuntimeError(self.perror('We timed out while waiting for a stability.'))
        wait(extra_wait, progress_base='QD extra wait')

    def _field_ramp_checkdev(self, val, approach=None, mode=None, rate=None, wait=None):
        self.field.check(val, approach=approach, mode=mode, rate=rate)
    def _field_ramp_setdev(self, val, approach=None, mode=None, rate=None, wait=None):
        """\
            Asks for a field change and then wait for it to be stable.
            Same options as field.
            wait is extra time to wait after Quantum Design says the field is stable.
              if None, uses field_ramp_wait_after
        """
        if wait is None:
            wait = self.field_ramp_wait_after.get()
        self.field.set(val, approach=approach, mode=mode, rate=rate)
        self.wait_for(field=True, extra_wait=wait)
    def _field_ramp_getdev(self, approach=None, mode=None, rate=None, wait=None):
        return self.field.get()

    def _temp_ramp_checkdev(self, val, approach=None, rate=None, wait=None):
        self.temp.check(val, approach=approach, rate=rate)
    def _temp_ramp_setdev(self, val, approach=None, rate=None, wait=None):
        """\
            Asks for a temperature change and then wait for it to be stable.
            Same options as temp.
            wait is extra time to wait after Quantum Design says the temperature is stable.
              if None, uses temp_ramp_wait_after
        """
        if wait is None:
            wait = self.temp_ramp_wait_after.get()
        self.temp.set(val, approach=approach, rate=rate)
        self.wait_for(temp=True, extra_wait=wait)
    def _temp_ramp_getdev(self, approach=None, rate=None, wait=None):
        return self.temp.get()

    def get_ppms_item(self, index, fast=True):
        ret = self._qdinst.GetPPMSItem(index, 0., fast)
        result, val = ret
        return val

    def field_is_stable(self):
        return self._wait_condition(field=True)

    def temp_is_stable(self):
        return self._wait_condition(temp=True)

    def _create_devs(self):
        self.current_field_approach = MemoryDevice(self._field_approaches[0], choices=self._field_approaches)
        self.current_field_mode = MemoryDevice(self._field_modes[0], choices=self._field_modes)
        self.current_temp_approach = MemoryDevice(self._temp_approaches[0], choices=self._temp_approaches)
        self.current_pos_mode = MemoryDevice(self._pos_modes[0], choices=self._pos_modes)
        self.current_pos_axis = MemoryDevice("Horizontal Rotator")
        self.field_ramp_wait_after = MemoryDevice(10., min=0.)
        self.temp_ramp_wait_after = MemoryDevice(10., min=0.)
        self.field_rate = MemoryDevice(100, min=0.1, max=10000, doc='Oe/s')
        self.temp_rate = MemoryDevice(2, min=0.01, max=20, doc='K/min')
        self.position_speed = MemoryDevice(1.)
        self.field_last_status = MemoryDevice('not initialized', doc='This is updated when getting field')
        self.temp_last_status = MemoryDevice('not initialized', doc='This is updated when getting temp')
        self.position_last_status = MemoryDevice('not initialized', doc='This is updated when getting position')
        self._devwrap('field', setget=True, min=-16e4, max=16e4, doc='Units are Oe, rate is Oe/s')
        self._devwrap('temp', setget=True, min=1.7, max=402.)
        self._devwrap('position', setget=True, autoinit=False)
        self._devwrap('chamber', setget=True, choices=self._chamber_cmds)
        self._devwrap('field_ramp', setget=True, autoinit=False)
        self._devwrap('temp_ramp', setget=True, autoinit=False)
        # This needs to be last to complete creation
        super(QuantumDesign_PPMS, self)._create_devs()

#TODO: check position stuff