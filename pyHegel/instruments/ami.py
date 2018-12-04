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
                            ChoiceStrings, ChoiceIndex, ChoiceLimits, ChoiceDevDep,\
                            make_choice_list, _fromstr_helper,\
                            decode_float64, visa_wrap, locked_calling
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias
from .logical import ScalingDevice


import time
from numpy import sign, abs


#######################################################
##    American Magnetics, Inc. Power Supply
#######################################################

@register_instrument('AMERICAN MAGNETICS INC.', 'MODEL 430')
#@register_instrument('AMERICAN MAGNETICS INC.', 'MODEL 430', '2.01')
class AmericanMagnetics_model430(visaInstrument):
    """
    This is the driver of American Magnetics model 430 magnet controller.
    Useful devices:
        current
        current_magnet
        field_T
        field_kG
        volt
        volt_magnet
        current_target
        field_target_kG
        field_target_T
        ramp_rate_current
        ramp_rate_field_kG
        ramp_rate_field_T
        persistent_switch_en
    Useful methods:
        set_state
        conf_supply
        conf_magnet
        conf_time

    If magnet parameters are changed you should reload this device.
    address in the form:
       tcpip::A5076_Z-AX.local::7180::socket
       port is 7180
    """
    def __init__(self, visa_addr, max_ramp_rate=0.1, min_ramp_rate=1e-4, **kwargs):
        """ Set the max_ramp_rate, min_ramp_rate in A/s
        """
        kwargs['read_termination'] = '\r\n'
        kwargs['skip_id_test'] = True
        self._conf_supply_cache = None
        self._conf_magnet_cache = None
        self._max_ramp_rate = max_ramp_rate
        self._min_ramp_rate = min_ramp_rate
        super(AmericanMagnetics_model430, self).__init__(visa_addr, **kwargs)
        self._extra_create_dev()

    @locked_calling
    def _extra_create_dev(self):
        conf_magnet = self.conf_magnet()
        conf_supply = self.conf_supply()
        scale = conf_magnet['coil_constant']
        if conf_magnet['unit_field'] == 'kG':
            scale /= 10
        max_current = min(conf_magnet['current_limit'], conf_magnet['current_rating'])
        min_current = -max_current if conf_supply['current_min'] != 0 else 0.
        self.current_target.max = max_current
        self.current_target.min = min_current
        max_field = max_current*scale
        min_field = min_current*scale
        self.field_target_T = ScalingDevice(self.current_target, scale, quiet_del=True, max=max_field, min=min_field)
        self.field_target_kG = ScalingDevice(self.current_target, scale*10, quiet_del=True, max=max_field*10, min=min_field*10)
        self.field_T = ScalingDevice(self.current_magnet, scale, quiet_del=True, doc='Field in magnet (even in persistent mode)')
        self.field_kG = ScalingDevice(self.current_magnet, scale*10, quiet_del=True, doc='Field in magnet (even in persistent mode)')

    def init(self, full=False):
        if full:
            if self.read() != 'American Magnetics Model 430 IP Interface':
                raise RuntimeError('Did not receive first expected message from instrument')
            if self.read() != 'Hello.':
                raise RuntimeError('Did not receive second expected message from instrument')

    def _current_config(self, dev_obj=None, options={}):
        opts = self._conf_helper('state', 'current', 'current_magnet', 'field_unit', 'ramp_rate_unit')
        opts += self._conf_helper('persistent_switch_en', 'persistent_mode_active')
        opts += self._conf_helper('quench_detected', 'quench_count', 'rampdown_count')
        opts += ['conf_manget=%s'%self.conf_magnet()]
        opts += ['conf_supply=%s'%self.conf_supply()]
        return opts + self._conf_helper(options)

    def set_state(self, state):
        """ Available states: ['ramp', 'pause', 'incr', 'decr', 'zero'] """
        if state not in ['ramp', 'pause', 'incr', 'decr', 'zero']:
            raise RuntimeError('invalid state')
        self.write(state)

    def conf_time(self, send_computer=False):
        if send_computer:
            lt = time.localtime()
            self.write('SYSTem:TIME:SET %i/%i/%i %i:%i:%i'%(lt.tm_mon, lt.tm_mday, lt.tm_year, lt.tm_hour, lt.tm_min, lt.tm_sec))
        else:
            dt = self.ask('SYSTem:TIME?')
            return dt

    @locked_calling
    def conf_supply(self, use_cache=True):
        if use_cache and self._conf_supply_cache:
            return  self._conf_supply_cache
        type = int(self.ask('SUPPly:TYPE?'))
        type = ['AMI 12100PS', 'AMI 12200PS', 'AMI 4Q05100PS', 'AMI 4Q06125PS', 'AMI 4Q06250PS', # 0-4
                'AMI 4Q12125PS', 'AMI 10100PS', 'AMI 10200PS', 'HP 6260B', 'Kepco BOP 20-5M',  # 5-9
                'Kepco BOP 20-10M', 'Xantrex XFR 7.5-140', 'Custom', 'AMI Model 05100PS-430-601', 'AMI Model 05200PS-430-601', # 10-14
                'AMI Model 05300PS-430-601', 'AMI Model 05400PS-430-601', 'AMI Model 05500PS-430-601'][type]
        volt_min = float(self.ask('SUPPly:VOLTage:MINimum?'))
        volt_max = float(self.ask('SUPPly:VOLTage:MAXimum?'))
        current_min = float(self.ask('SUPPly:CURRent:MINimum?'))
        current_max = float(self.ask('SUPPly:CURRent:MAXimum?'))
        volt_output_mode = int(self.ask('SUPPly:MODE?'))
        volt_output_mode = ['0 to 5', '0 to 10', '-5 to 5', '-10 to 10', '-5 to 0', '0 to 8'][volt_output_mode]
        ret = locals()
        del ret['self']
        self._conf_supply_cache = ret
        return ret

    @locked_calling
    def conf_magnet(self, use_cache=True):
        if use_cache and self._conf_magnet_cache:
            return  self._conf_magnet_cache
        do_bool = lambda x: bool(int(x))
        conv = lambda s: tuple(map(float, s.split(',')))
        stability_pct = float(self.ask('STABility?'))
        current_limit = float(self.ask('CURRent:LIMit?'))
        current_rating = float(self.ask('CURRent:RATING?'))
        persistent_switch_installed = self.persistent_switch_installed.get()
        persistent_switch_current_mA = float(self.ask('PSwitch:CURRent?'))
        persistent_switch_heat_time = float(self.ask('PSwitch:HeatTIME?'))
        persistent_switch_cool_time = float(self.ask('PSwitch:CoolTIME?'))
        persistent_switch_cooling_gain_pct = float(self.ask('PSwitch:CoolingGAIN?'))
        persistent_switch_ramp_rate = self.persistent_switch_ramp_rate.get()
        quench_detect_en = do_bool(self.ask('QUench:DETect?'))
        quench_rate = float(self.ask('QUench:RATE?'))
        absober_installed = do_bool(self.ask('ABsorber?'))
        volt_limit = self.volt_limit.get()
        coil_constant = self.coil_constant.get()
        unit_field = self.field_unit.get()
        ramp_rate_unit = self.ramp_rate_unit.get()
        external_rampdown_en = do_bool(self.ask('RAMPDown:ENABle?'))
        rapmdown_rate_N_segments = int(self.ask('RAMPDown:RATE:SEGments?'))
        rampdown_rate_upper_current = []
        rampdown_rate_upper_field = []
        for i in range(rapmdown_rate_N_segments):
            rampdown_rate_upper_current.append(conv(self.ask('RAMPDown:RATE:CURRent:%i?'%(i+1))))
            #rampdown_rate_upper_field.append(conv(self.ask('RAMPDown:RATE:FIELD:%i?'%(i+1))))
        ret = locals()
        del ret['self']
        del ret['do_bool']
        del ret['conv']
        self._conf_magnet_cache = ret
        return ret

#TODO implement ramp_rate_field_T and ramp_rate_field_kG
#     implement go_to_field and wait (or go_to_current) and handle persistence

    def _create_devs(self):
        self.setpoint = scpiDevice('conf:current:target', 'current:target?', str_type=float)
        self.volt = scpiDevice(getstr='voltage:supply?', str_type=float)
        self.volt_magnet = scpiDevice(getstr='voltage:magnet?', str_type=float, doc='This is the voltage on the magnet if the proper connection are present.')
        self.volt_limit = scpiDevice(getstr='VOLTage:LIMit?', str_type=float)
        self.current = scpiDevice(getstr='current:supply?', str_type=float, doc='This is the current output by the supply. See also current_magnet.')
        self.current_magnet = scpiDevice(getstr='current:magnet?', str_type=float, doc='This is the current in the magnet even when in persistent mode. See also current.')
        self.current_target = scpiDevice('CONFigure:CURRent:TARGet', 'CURRent:TARGet?', str_type=float, setget=True)
        #self.field = scpiDevice(getstr='field:magnet?', str_type=float,
        #                        doc='This is the field in the magnet even when in persistent mode (units are T or kG depending on field_unit device). See also current_magnet')
        self.field_unit = scpiDevice('CONFigure:FIELD:UNITS', 'FIELD:UNITS?', choices=ChoiceIndex(['kG', 'T']))
        #self.field_target = scpiDevice('CONFigure:FIELD:TARGet', 'FIELD:TARGet?', str_type=float, doc='Units are in kG or T depending on field_unit device.')
        self.ramp_rate_unit = scpiDevice('CONFigure:RAMP:RATE:UNITS', 'RAMP:RATE:UNITS?', choices=ChoiceIndex(['sec', 'min']))
        self.coil_constant = scpiDevice(getstr='COILconst?', str_type=float, doc='units are either kG/A or T/A, see field_unit device')
        self.ramp_rate_segment_index = MemoryDevice(1, min=1)
        self.ramp_rate_segment_count = scpiDevice('CONFigure:RAMP:RATE:SEGments', 'RAMP:RATE:SEGments?', str_type=int)
        rmin, rmax = self._min_ramp_rate, self._max_ramp_rate
        rate_lim = ChoiceDevDep(self.ramp_rate_unit, dict(min=ChoiceLimits(min=rmin*60, max=rmax*60), sec=ChoiceLimits(min=rmin, max=rmax)))
        self.ramp_rate_current = scpiDevice('CONFigure:RAMP:RATE:CURRent {index},{val}', 'RAMP:RATE:CURRent:{index}?',
                                            choices=ChoiceMultiple(['rate', 'max_current'], [(float, rate_lim), float]),
                                            options = dict(unit=self.ramp_rate_unit, index=self.ramp_rate_segment_index),
                                            options_apply = ['unit', 'index'],
                                            allow_kw_as_dict=True, allow_missing_dict=True,
                                            allow_val_as_first_dict=True, setget=True)
        self.ramp_rate_field = scpiDevice(getstr='RAMP:RATE:FIELD:1?', choices=ChoiceMultiple(['rate', 'max_field'], [float, float]),
                    doc='Units are kG/s, T/s, kG/min or T/min see ramp_rate_unit and field_unit devices.')
        self.state = scpiDevice(getstr='STATE?', choices=ChoiceIndex(['ramping', 'holding', 'paused', 'ramping_manual_up', 'ramping_manual_down',
                        'zeroing', 'quench', 'at_zero', 'heating_persistent_switch', 'cooling_persistent_switch'], offset=1))
        self.persistent_switch_installed = scpiDevice('PSwitch:INSTalled?', str_type=bool)
        self.persistent_switch_ramp_rate = scpiDevice('CONFigure:PSwitch:PowerSupplyRampRate', 'PSwitch:PowerSupplyRampRate?', str_type=float, doc='Units are always A/s')
        self.persistent_switch_en = scpiDevice('PSwitch', str_type=bool)
        self.persistent_mode_active = scpiDevice(getstr='PERSistent?', str_type=bool)
        self.quench_detected = scpiDevice(getstr='QUench?', str_type=bool)
        self.quench_count = scpiDevice(getstr='QUench:COUNT?', str_type=int)
        self.rampdown_count = scpiDevice(getstr='RAMPDown:COUNT?', str_type=int)
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
        