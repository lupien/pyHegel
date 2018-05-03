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

from __future__ import absolute_import

from ..instruments_base import visaInstrument, visaInstrumentAsync, BaseInstrument,\
                            scpiDevice, MemoryDevice, Dict_SubDevice, ReadvalDev,\
                            ChoiceBase, ChoiceMultiple, ChoiceMultipleDep, ChoiceSimpleMap,\
                            ChoiceStrings, ChoiceIndex,\
                            make_choice_list, _fromstr_helper,\
                            decode_float64, visa_wrap, locked_calling
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias
import time
from numpy import sign, abs


#######################################################
##    American Magnetics, Inc. Power Supply
#######################################################

@register_instrument('AMERICAN MAGNETICS INC.', 'MODEL 430')
#@register_instrument('AMERICAN MAGNETICS INC.', 'MODEL 430', '2.01')
class AmericanMagnetics_model430(visaInstrument):
    """
    TODO
    address in the form:
       tcpip::A5076_Z-AX.local::7180::socket
       port is 7180
    """
    def __init__(self, *args, **kwargs):
        kwargs['read_termination'] = '\r\n'
        kwargs['skip_id_test'] = True
        super(AmericanMagnetics_model430, self).__init__(*args, **kwargs)
    def init(self, full=False):
        if full:
            if self.read() != 'American Magnetics Model 430 IP Interface':
                raise RuntimeError('Did not receive first expected message from instrument')
            if self.read() != 'Hello.':
                raise RuntimeError('Did not receive second expected message from instrument')
    def set_state(self, state):
        """ Available states: ['ramp', 'pause', 'incr', 'decr', 'zero'] """
        if state not in ['ramp', 'pause', 'incr', 'decr', 'zero']:
            raise RuntimeError('invalid state')
        self.write(state)
    def _create_devs(self):
        self.setpoint = scpiDevice('conf:current:target', 'current:target?', str_type=float)
        self.volt = scpiDevice(getstr='voltage:supply?', str_type=float)
        self.volt_magnet = scpiDevice(getstr='voltage:magnet?', str_type=float)
        self.current = scpiDevice(getstr='current:supply?', str_type=float)
        self.current_magnet = scpiDevice(getstr='current:magnet?', str_type=float)
        self.field = scpiDevice(getstr='field:magnet?', str_type=float)
        #self.field_unit_tesla_en = scpiDevice('CONFigure:FIELD:UNITS', 'FIELD:UNITS?', str_type=bool)
        self.field_unit = scpiDevice('CONFigure:FIELD:UNITS', 'FIELD:UNITS?', choices=ChoiceIndex(['kG', 'T']))
        self.ramp_rate_unit = scpiDevice('CONFigure:RAMP:RATE:UNITS', 'RAMP:RATE:UNITS?', choices=ChoiceIndex(['sec', 'min']))
        self.coil_constant = scpiDevice(getstr='COILconst?', str_type=float, doc='units are either kG/A or T/A, see field_unit device')
        self.ramp_rate_current = scpiDevice(getstr='RAMP:RATE:CURRent:1?', choices=ChoiceMultiple(['rate', 'max_current'], [float, float]),
                    doc='Units are A/s or A/min see ramp_rate_unit device.')
        self.ramp_rate_field = scpiDevice(getstr='RAMP:RATE:FIELD:1?', choices=ChoiceMultiple(['rate', 'max_field'], [float, float]),
                    doc='Units are kG/s, T/s, kG/min or T/min see ramp_rate_unit and field_unit devices.')
        #self.state = scpiDevice(getstr='STATE?', str_type=int)
        self.state = scpiDevice(getstr='STATE?', choices=ChoiceIndex(['ramping', 'holding', 'paused', 'ramping_manual_up', 'ramping_manual_down',
                        'zeroing', 'quench', 'at_zero', 'heating_persistent_switch', 'cooling_persistent_switch'],offset=1))
        self.persistent_switch_en = scpiDevice(getstr='PERSistent?', str_type=bool)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

@register_instrument('pyHegel_Instrument', 'magnet_simul', '1.0')
class MagnetSimul(BaseInstrument):
    """
    TODO
    """
    def __init__(self, max_field=5., max_rate=0.184*0.0779, field_A_const=0.0779):
        """ field in T, current in A, time in s """
        self._last_field = (0, time.time())
        self._max_field = abs(max_field)
        self._max_rate = abs(max_rate)
        self._field_A_const = field_A_const
        super(MagnetSimul, self).__init__(self)
    def _current_getdev(self):
        return self.field.get()/self._field_A_const
    def _rate_current_getdev(self):
        return self.rate.get()/self._field_A_const
    def _field_getdev(self):
        now = time.time()
        f, last = self._last_field
        mode = self.mode.get()
        if mode == 'hold':
            new_f = f
        elif mode == 'ramp':
            sp = self.field_setpoint.get()
            direction = sign(sp - f)
            new_f = f + direction*self.rate.get()*(now-last)
            if (new_f-sp)*direction > 0:
                new_f = sp
            if abs(new_f) > self._max_field:
                new_f = sign(new_f)*self._max_field
        else:
            raise RuntimeError("Invalid mode")
        self._last_field = (new_f, now)
        return new_f
    def _create_devs(self):
        self.field_setpoint = MemoryDevice(0., min=-self._max_field, max=self._max_field)
        #self.field = MemoryDevice(0.)
        self.rate = MemoryDevice(self._max_rate, min=0., max=self._max_rate)
        self.mode = MemoryDevice('hold', choices=['hold', 'ramp'])
        self._devwrap('current')
        self._devwrap('rate_current')
        self._devwrap('field')
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
        