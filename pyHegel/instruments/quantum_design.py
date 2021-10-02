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
import sys

from ..instruments_base import BaseInstrument, BaseDevice,\
                            MemoryDevice, locked_calling,\
                            wait, ProxyMethod, wait_on_event

from ..instruments_registry import register_instrument

QDInstrument_LabVIEW_dir = r"C:\QDInstrument_LabVIEW"
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
CommunicationObjectFaultedException = None

_delayed_imports_done = False

def _delayed_imports():
    global _delayed_imports_done
    if not _delayed_imports_done:
        global clr, EnumGetNames, EnumGetValues, QDInstrument, QDInstrumentBase, QDInstrumentFactory, QDTypes, _assembly_Version,\
               CommunicationObjectFaultedException
        try:
            import clr
            from System import Enum
            from System.ServiceModel import CommunicationObjectFaultedException
            EnumGetNames = Enum.GetNames
            EnumGetValues = Enum.GetValues
        except ImportError as exc:
            raise RuntimeError('Unable to import windows clr/System: %s'%exc)
        try:
            if QDInstrument_LabVIEW_dir not in sys.path:
                sys.path.append(QDInstrument_LabVIEW_dir)
            clr.AddReference('QDInstrument')
            import QuantumDesign.QDInstrument as QDInstrument
            from QuantumDesign.QDInstrument import QDInstrumentBase, QDInstrumentFactory
            QDTypes = QDInstrumentBase.QDInstrumentType
            assembly = clr.GetClrType(QDInstrumentBase).Assembly
            _assembly_Version = assembly.GetName().Version.ToString()
        except ImportError as exc:
            raise RuntimeError(
                "Unable to load QuantumDesign Module (QDInstrument.dll). Make sure pythonnet and "
                "QDInstrument.dll is installed and unblocked: %s\n"%exc +
                "The dll should be in the same directory as this module or in %s"%QDInstrument_LabVIEW_dir)
        _delayed_imports_done = True

@register_instrument('Quantum Design', 'PPMS')
class QuantumDesign_PPMS(BaseInstrument):
    def __init__(self, address=None, port=11000, type='ppms', **kwargs):
        """
        address when None is for a local connection. Otherwise it is the
          ip address (dns name) of the server.
        port defaults to 11000.
        type is one of 'ppms',  'versalab', 'dynacool', svsm
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

    def __del__(self):
        try:
            self.close()
        except:
            pass
        super(QuantumDesign_PPMS, self).__del__()

    def close(self):
        """ This closes the connection """
        if self._qd_address is None:
            self._qdinst.Release()
        else:
            self._qdinst.Client.Close()

    def init(self, full=False):
        if self._qd_type == 'ppms':
            # we inistialize the position_speed parameters to the one from the instrument.
            pos, mode, slowdown = self.move_get_last_params()
            self.position_speed.set(slowdown)

    def idn(self):
        return 'Quantum Design,%s,no_serial,no_firmware'%self._qd_type

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        extra = ['AssemblyVersion=%r'%_assembly_Version, 'address=%r'%(self._qd_address,),
                 'qd_type=%s'%self._qd_type]
        base = self._conf_helper('temp', 'field', 'chamber', 'position',
                                 'current_field_approach', 'current_field_mode', 'current_temp_approach',
                                 'current_pos_mode', 'current_pos_axis', 'position_speed',
                                 'field_ramp_wait_after', 'temp_ramp_wait_after',
                                 'field_rate', 'temp_rate', options)
        if self._qd_type == 'ppms':
            base += ['move_config=%s'%self.move_config()]
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
        if self._qd_type == 'ppms':
            if ret != 1: # This is different than the othes, at least on the ppms instrument I tested
                raise RuntimeError('temp set failed: %i'%ret)
        else:
            if ret != 0: # This is fine for a dynacool
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
        if self._qd_type == 'ppms':
            self._move_set(val, mode, speed)
        mode = getattr(QDInstrumentBase.PositionMode, mode)
        ret = self._qdinst.SetPosition(axis, val, speed, mode)
#        if ret != 0:
#            raise RuntimeError('position set failed: %i'%ret)

    def _position_getdev(self, axis=None, mode=None, speed=None):
        # mode, speed are present because of setget
        if axis is None:
            axis = self.current_pos_axis.get()
        if self._qd_type == 'ppms':
            #self.position_last_status.set('Unknown status for ppms pos')
            return self._move_get_pos()
        try:
            ret = self._qdinst.GetPosition(axis, 0., 0) # position and status byref
        except CommunicationObjectFaultedException: # I get this exception on dynacool without the rotator installed.
            ret = (0, -999, 0) # ok, -999 deg, 0=position unknown
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

    def _position_ramp_checkdev(self, val, axis=None, mode=None, speed=None, wait=None):
        self.position.check(val, axis=axis, mode=mode, speed=speed)
    def _position_ramp_setdev(self, val, axis=None, mode=None, speed=None, wait=None):
        """\
            Asks for a position change and then wait for it to be stable.
            Same options as position.
            wait is extra time to wait after Quantum Design says the position is stable.
              if None, uses position_ramp_wait_after
        """
        if wait is None:
            wait = self.position_ramp_wait_after.get()
        self.position.set(val, axis=axis, mode=mode, speed=speed)
        self.wait_for(pos=True, extra_wait=wait)
    def _position_ramp_getdev(self, approach=None, rate=None, wait=None):
        return self.position.get()

    def get_ppms_item(self, index, fast=True):
        """\
        fast, when True (which is the default) returns the current value. When False
          it will fetch an updated value before returning.
        The index is 0-29, 32-61, 64-93.
        You can look at the Log PPMS data Utilities within MultiVu for the index number.
        For example 66 is the helium level on the Advanced items tab.
        The Standard items tab is for 0-29 (Note that MultiVu as reordered them).
        Diagnostic items is 32-61, Advanced items is 64-93.
        For standard items, the order is the one as seen in the gpib documentation manual.
           0: status
           1: Temps
           2: Field
           3: Position
           4-11: User Bridge #1 - 4 Res, Exc
           12: Sig in 1
           13: Sig in 2
           14: Difital in - Aux, Ext
           15-18: User Driver 1,2 Current, Power
           19: Pressure
           20-29: User mapped item
        """
        # This will produce a GPIB call on MultiVu (it is extended vs what the manual explains.)
        #   The call is GETDAT? ind, fast, Page, 0
        #   where ind, page are 2**index, 0 for index <32
        #                       2**(index-32), 1 for 32<index<64
        #                       2**(index-64), 2 for 32<index<64
        # and the gpib reply is ret_index, timestamp, data
        # when the data is available, otherwise
        #         ret_index, timestamp
        # where ret_index is ind + ret_base if data is available or just ret_base.
        #  ret_base is 0 for page=0, 2**30 for page=1 and 2**31 for page=2.
        if index < 0 or index > 93 or index in [30, 31, 62, 63]:
            raise ValueError('Invalid index')
        ret = self._qdinst.GetPPMSItem(index, 0., fast)
        result, val = ret
        return val

    def send_ppms_command(self, command):
        """ Send a gpib command to the PPMS 6000. This is only valid for ppms instrument type """
        if self._qd_type != 'ppms':
            raise RuntimeError(self.perror('This is not a ppms instrument so send_ppms_command does not work.'))
        # The last 2 values are for device and timeout but I think they are ignored (the ppms 6000 gpib address should be 15
        # but any number seems to work).
        # You can implement the same as get_ppms_item with: "$GETONE? 3"
        ret = self._qdinst.SendPPMSCommand(command, 'default_return_message', 'default_err_message', 0, 0.)
        result, ret_string, ret_error = ret
        self._send_ppms_command_last_ret = (result, ret_error)
        # I think result 0 or 1 are not errors. 1 is used when no value is returned
        if result not in [0, 1]:
            raise RuntimeError(self.perror('Error in send_pppms_command: %i: %s')%(result, ret_error))
        return ret_string

    def field_is_stable(self, param_dict=None):
        return self._wait_condition(field=True)

    def temp_is_stable(self, param_dict=None):
        return self._wait_condition(temp=True)

    def position_is_stable(self, param_dict=None):
        return self._wait_condition(pos==True)

    def move_config(self, unit=None, units_per_step=None, range=None, index_switch_en=None):
        """ Either all values are None (default) then it returns the current settings
            or they are all given to set a new value.
            Allowed units are: 'steps', 'deg', 'rad', 'mm', 'cm', 'mils', 'in', 'user'
            This is only for ppms devices.
            """
        units = ['steps', 'deg', 'rad', 'mm', 'cm', 'mils', 'in', 'user']
        if unit == units_per_step == range == index_switch_en == None:
            ret = self.send_ppms_command('MOVECFG?')
            unit, units_per_step, range, index_switch_en = ret.split(',')
            unit = units[int(unit)]
            units_per_step = float(units_per_step)
            range = float(range)
            index_switch_en = bool(int(index_switch_en))
            return dict(unit=unit, units_per_step=units_per_step, range=range, index_switch_en=index_switch_en)
        elif units is None or units_per_step is None or range is None or index_switch_en is None:
            raise ValueError('Either all parameters are None or they all need to be specified.')
        # Now we change the value
        unit = units.index(unit)
        self.send_ppms_command('MOVECFG %i %.8e %.8e %i'%(unit, units_per_step, range, int(index_switch_en)))

    def _move_limits_getdev(self):
        """ This returns position of limit switch and the maximum travel limit.
            This is only for PPMS instruments """
        ret = self.send_ppms_command('MOVELIM?')
        return map(float, ret.split(','))

    # These values are from the multivu GUI in steps unit.
    _move_slowdown = [225, 210, 195, 180, 165, 150, 135, 120, 105, 90, 75, 60, 45, 30, 15]
    def _move_set(self, pos, mode='MoveToPosition', slowdown=225):
        """
           mode options are the ones in self._pos_modes
           slowdown in units of step/s. Allowed values are:
                225, 210, 195, 180, 165, 150, 135, 120, 105, 90, 75, 60, 45, 30, 15
           This is only valid for PPMS instruments.
        """
        if mode not in self._pos_modes:
            raise ValueError(self.perror('Invalid mode'))
        if slowdown not in self._move_slowdown:
            raise ValueError(self.perror('Invalid slowdown value'))
        self.send_ppms_command('MOVE %.8e %i %i'%(pos, self._pos_modes.index(mode), self._move_slowdown.index(slowdown)))

    def move_get_last_params(self):
        """
        This returns the position, mode and slowdown parameter for the last move request.
        This is only valid for PPMS instruments.
        """
        ret = self.send_ppms_command('MOVE?')
        pos, mode, slowdown = ret.split(',')
        pos = float(pos)
        mode = int(mode)
        slowdown = int(slowdown)
        return pos, self._pos_modes[mode], self._move_slowdown[slowdown]

    def _move_get_pos(self):
        return self.get_ppms_item(3)

    def _create_devs(self):
        self.current_field_approach = MemoryDevice(self._field_approaches[0], choices=self._field_approaches)
        self.current_field_mode = MemoryDevice(self._field_modes[0], choices=self._field_modes)
        self.current_temp_approach = MemoryDevice(self._temp_approaches[0], choices=self._temp_approaches)
        self.current_pos_mode = MemoryDevice(self._pos_modes[0], choices=self._pos_modes)
        self.current_pos_axis = MemoryDevice("Horizontal Rotator")
        self.field_ramp_wait_after = MemoryDevice(10., min=0.)
        self.temp_ramp_wait_after = MemoryDevice(10., min=0.)
        self.position_ramp_wait_after = MemoryDevice(10., min=0.)
        self.field_rate = MemoryDevice(100, min=0.1, max=10000, doc='Oe/s')
        self.temp_rate = MemoryDevice(2, min=0.01, max=20, doc='K/min')
        if self._qd_type == 'ppms':
            self.position_speed = MemoryDevice(1., choices=self._move_slowdown, doc='Unis are steps/s.')
        else:
            self.position_speed = MemoryDevice(1., doc="""\
            For dynacool HighRes rotator, speed is .1 to 7 deg/s, values outside
            this range will just use the limit. For lowRes the range is 3 to 30 degrees.
            """)
        self.field_last_status = MemoryDevice('not initialized', doc='This is updated when getting field')
        self.temp_last_status = MemoryDevice('not initialized', doc='This is updated when getting temp')
        self.position_last_status = MemoryDevice('not initialized', doc='This is updated when getting position')
        self._devwrap('field', setget=True, min=-16e4, max=16e4, doc="""\
                      Units are Oe
                      Options:
                          rate      in Oe/s (defaults to field_rate)
                          approach  one of {}, defaults to current_field_approach
                          mode      one of {}, defaults to current_field_mode
                      """.format(self.current_field_approach.choices, self.current_field_mode.choices))
        self._devwrap('temp', setget=True, min=1.7, max=402., doc="""\
                      Units are K
                      Options:
                          rate      in K/min (defaults to temp_rate)
                          approach  one of {}, defaults to current_temp_approach
                      """.format(self.current_field_approach.choices))
        self._devwrap('position', setget=True, doc="""\
                      Options:
                          axis      defaults to current_pos_axis
                          speed      (defaults to position_speed)
                          mode  one of {}, defaults to current_pos_mode
                      """.format(self.current_pos_mode.choices))
        self._devwrap('chamber', setget=True, choices=self._chamber_cmds)
        self._devwrap('field_ramp', setget=True, autoinit=False)
        self._devwrap('temp_ramp', setget=True, autoinit=False)
        self._devwrap('position_ramp', setget=True, autoinit=False)
        if self._qd_type == 'ppms':
            self._devwrap('move_limits', multi=['limit', 'max_travel'])
        # This needs to be last to complete creation
        super(QuantumDesign_PPMS, self)._create_devs()
