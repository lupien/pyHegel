# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2011-2023  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from ..instruments_base import visaInstrument, visaInstrumentAsync, BaseInstrument,\
                            scpiDevice, MemoryDevice, Dict_SubDevice, ReadvalDev,\
                            ChoiceBase, ChoiceMultiple, ChoiceMultipleDep, ChoiceSimpleMap,\
                            ChoiceStrings, ChoiceIndex, ChoiceLimits, ChoiceDevDep,\
                            make_choice_list, _fromstr_helper,\
                            decode_float64, visa_wrap, locked_calling, BaseDevice, mainStatusLine,\
                            wait, release_lock_context, resource_info
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias
from .logical import ScalingDevice
from ..types import dict_improved


import time
import numpy as np
from numpy import sign, abs, sqrt, sin, cos, pi, arctan2
from scipy.optimize import brentq

from ..comp2to3 import string_bytes_types

#######################################################
##    American Magnetics, Inc. Power Supply
#######################################################

# Firmware 2.59
#   Added
#      port 7185 (without hello stuff)
#      CONFigure:LOCK:INDuctance, LOCK:INDuctance?
#      CONFigure:LOCK:OPLimit, LOCK:OPLimit?
#      *LED? #documentation rev9 for this is wrong. it is a integer (with bit field?)
#     CONFigure:STABility:MODE, CONFigure:STABility:RESistor, STABility:MODE?, STABility:RESistor?
#     CONFigure:INDuctance, INDuctance?, INDuctance:SENSe?
#     CONFigure:PSwitch:TRANsition, PSwitch:TRANsition?
#     CONFigure:OPLimit:MODE, CONFigure:OPLimit:ICSLOPE, CONFigure:OPLimit:ICOFFSET, CONFigure:OPLimit:TMAX, CONFigure:OPLimit:TSCALE, CONFigure:OPLimit:TOFFSET
#     OPLimit:IC?, OPLimit:TEMP?, OPLimit:MODE?, OPLimit:ICSLOPE?, OPLimit:ICOFFSET?, OPLimit:TMAX?, OPLimit:TSCALE?, OPLimit:TOFFSET?
#     QUenchFile?, QUenchBackup?
#
#   Removed
#      INDuctance?
#      CONFigure:CURRent:RATING, CURRent:RATING?
#      CONFigure:LOCK:CURRent:RATING, LOCK:CURRent:RATING? # Note this is wrong in rev9 of the manual (it is present but does not work)

@register_instrument('AMERICAN MAGNETICS INC.', 'MODEL 430')
#@register_instrument('AMERICAN MAGNETICS INC.', 'MODEL 430', '2.59')
#@register_instrument('AMERICAN MAGNETICS INC.', 'MODEL 430', '2.01')
class AmericanMagnetics_model430(visaInstrument):
    """
    This is the driver of American Magnetics model 430 magnet controller.
    Useful devices:
        ramp_current
        ramp_field_T
        ramp_field_kG
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
        conf_ramp_rates

    If magnet parameters are changed you should reload this device.
    address in the form:
       tcpip::A5076_Z-AX.local::7180::socket
       port is 7180 or 7185 (with firmware >=2.59)
    """
    def __init__(self, visa_addr, max_ramp_rate=0.1, min_ramp_rate=1e-4, **kwargs):
        """ Set the max_ramp_rate, min_ramp_rate in A/s
        """
        kwargs['read_termination'] = '\r\n'
        kwargs['skip_id_test'] = True
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == visa_wrap.constants.InterfaceType.asrl:
            kwargs['baud_rate'] = 115200
            self._port = None
        else:
            self._port =  int(resource_info(visa_addr).resource_name.split('::')[2])
            if self._port not in [7180, 7185]:
                self.perror('Invalid port number in visa_addr (either 7180 or 7185).')
        self._conf_supply_cache = None
        self._conf_magnet_cache = None
        self._coil_constant = 0. # always in T/A
        self._max_ramp_rate = max_ramp_rate
        self._min_ramp_rate = min_ramp_rate
        self._orig_target_cache = None
        self._last_state = None
        super(AmericanMagnetics_model430, self).__init__(visa_addr, **kwargs)
        self._extra_create_dev()
        # Because labber locks it, but we don't need it, unlock it so the user can
        # change units from the instrument front panel.
        self.write('CONFigure:LOCK:FIELD:UNITS 0')

    @locked_calling
    def _extra_create_dev(self):
        conf_magnet = self.conf_magnet()
        conf_supply = self.conf_supply()
        self._coil_constant = scaleT = conf_magnet['coil_constant']
        scalekG = scaleT*10
        if not self._new_firmware:
            max_current = min(conf_magnet['current_limit'], conf_magnet['current_rating'])
        else:
            max_current = conf_magnet['current_limit']
        min_current = -max_current if conf_supply['current_min'] != 0 else 0.
        self.current_target.max = max_current
        self.current_target.min = min_current
        max_fieldT = max_current*scaleT
        min_fieldT = min_current*scaleT
        max_fieldkG = max_fieldT*10
        min_fieldkG = min_fieldT*10
        self.field_target_T = ScalingDevice(self.current_target, scaleT, quiet_del=True, max=max_fieldT, min=min_fieldT)
        self.field_target_kG = ScalingDevice(self.current_target, scalekG, quiet_del=True, max=max_fieldkG, min=min_fieldkG)
        self.field_T = ScalingDevice(self.current_magnet, scaleT, quiet_del=True, doc='Field in magnet (even in persistent mode)')
        self.field_kG = ScalingDevice(self.current_magnet, scalekG, quiet_del=True, doc='Field in magnet (even in persistent mode)')
        rmin, rmax = self._min_ramp_rate, self._max_ramp_rate
        self.ramp_rate_field_T.choices.fmts_lims[0].choices['min'].min = rmin*scaleT*60
        self.ramp_rate_field_T.choices.fmts_lims[0].choices['min'].max = rmax*scaleT*60
        self.ramp_rate_field_T.choices.fmts_lims[0].choices['sec'].min = rmin*scaleT
        self.ramp_rate_field_T.choices.fmts_lims[0].choices['sec'].max = rmax*scaleT
        self.ramp_rate_field_kG.choices.fmts_lims[0].choices['min'].min = rmin*scalekG*60
        self.ramp_rate_field_kG.choices.fmts_lims[0].choices['min'].max = rmax*scalekG*60
        self.ramp_rate_field_kG.choices.fmts_lims[0].choices['sec'].min = rmin*scalekG
        self.ramp_rate_field_kG.choices.fmts_lims[0].choices['sec'].max = rmax*scalekG
        self.ramp_current.max = max_current
        self.ramp_current.min = min_current
        self.ramp_field_T = ScalingDevice(self.ramp_current, scaleT, quiet_del=True, max=max_fieldT, min=min_fieldT, doc="See ramp_current for options")
        self.ramp_field_kG = ScalingDevice(self.ramp_current, scalekG, quiet_del=True, max=max_fieldkG, min=min_fieldkG, doc="See ramp_current for options")
        max_current = round(max_current+0.01, 1) # instruments returns a rounded value to one decimal. +0.01 is to deal for unknown of instrument rounding algorithm
        self.ramp_rate_current.choices.fmts_lims[1] = (1e-4, max_current)
        self.ramp_rate_field_T.choices.fmts_lims[1] = (1e-4*scaleT, max_current*scaleT)
        self.ramp_rate_field_kG.choices.fmts_lims[1] = (1e-4*scalekG*10, max_current*scalekG)
        self._create_devs_helper() # to get logical devices return proper name (not name_not_found)

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = self._conf_helper('state', 'current', 'current_magnet')
        opts += self._conf_helper('field_T', 'field_kG')
        opts += self._conf_helper('volt', 'volt_magnet')
        opts += self._conf_helper('ramp_rate_unit', 'ramp_rate_segment_count')
        ramps = self.conf_ramp_rates()
        opts += ['ramp_rate_currents=%s'%ramps]
        opts += self._conf_helper('ramp_wait_after', 'persistent_switch_en', 'persistent_mode_active', 'persistent_wait_before')
        opts += self._conf_helper('quench_detected', 'quench_count', 'rampdown_count', 'field_unit')
        opts += ['conf_manget=%s'%self.conf_magnet()]
        opts += ['conf_supply=%s'%self.conf_supply()]
        return opts + self._conf_helper(options)

    def set_state(self, state):
        """ Available states: ['ramp', 'pause', 'incr', 'decr', 'zero'] """
        if state not in ['ramp', 'pause', 'incr', 'decr', 'zero']:
            raise RuntimeError('invalid state')
        self.write(state)
        self._last_state = state

    def conf_ramp_rates(self, ramp_unit=None, field=None):
        """ By default returns ramps in default ramp_unit (sec or min)
            and in current (so A/s or A/min).
            if field is T or kG, use those field units instead
        """
        if ramp_unit is not None:
            self.ramp_rate_unit.set(ramp_unit)
        scale = 1.
        if field is not None:
            if field not in ['kG', 'T']:
                raise ValueError(self.perror("field should be either 'kG' or 'T' or None"))
            scale = self._coil_constant
            if field == 'kG':
                scale *= 10.
        N = self.ramp_rate_segment_count.getcache()
        i_orig = self.ramp_rate_segment_index.get()
        ramps = []
        for i in range(N):
            self.ramp_rate_segment_index.set(i+1)
            r = self.ramp_rate_current.getcache()
            ramps.append((r['rate']*scale, r['max_current']*scale))
        self.ramp_rate_segment_index.set(i_orig)
        return ramps

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
        del ret['use_cache']
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
        if not self._new_firmware:
            current_rating = float(self.ask('CURRent:RATING?'))
            quench_rate = float(self.ask('QUench:RATE?'))
        else:
            stability_mode = ['auto', 'manual', 'test'][int(self.ask('STABility:MODE?'))]
            stability_resistor_installed = do_bool(self.ask('STABility:RESistor?'))
            persistent_switch_transition_mode = ['timer', 'voltage'][int(self.ask('PSwitch:TRANsition?'))]
            inductance = float(self.ask('INDuctance?'))
            quench_rate = int(self.ask('QUench:RATE?'))
            #  Oplimit not active
            #op_limit_mode = ['off', 'on_entry', 'cont_f(T)'][int(self.ask('OPLimit:MODE?'))]
            #op_limit_ic_slope = float(self.ask('OPLimit:ICSLOPE?'))
            #op_limit_ic_offset = float(self.ask('OPLimit:ICOFFSET?'))
            #op_limit_t_max = float(self.ask('OPLimit:TMAX?'))
            #op_limit_t_scale = float(self.ask('OPLimit:TSCALE?'))
            #op_limit_t_offset = float(self.ask('OPLimit:TOFFSET?'))
        persistent_switch_installed = self.persistent_switch_installed.get()
        persistent_switch_current_mA = float(self.ask('PSwitch:CURRent?'))
        persistent_switch_heat_time = float(self.ask('PSwitch:HeatTIME?'))
        persistent_switch_cool_time = float(self.ask('PSwitch:CoolTIME?'))
        persistent_switch_cooling_gain_pct = float(self.ask('PSwitch:CoolingGAIN?'))
        persistent_switch_ramp_rate = self.persistent_switch_ramp_rate.get()
        quench_detect = ['off', 'current', 'temperature', 'both'][int(self.ask('QUench:DETect?'))] # only off, current for old firmware
        absober_installed = do_bool(self.ask('ABsorber?'))
        volt_limit = self.volt_limit.get()
        coil_constant = float(self.ask('COILconst?')) # this is either kG or T
        unit_field = self.field_unit.get()
        if unit_field not in ['kG', 'T']:
            raise RuntimeError(self.perror('Unexepected unit'))
        if unit_field == 'kG':
            coil_constant /= 10.
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
        del ret['unit_field']
        del ret['use_cache']
        self._conf_magnet_cache = ret
        return ret

    def _led_state_getdev(self):
        val = int(self.ask('*LED?'))
        ret = {}
        ret['shift'] = bool(val&(1<<0))
        ret['at_target'] = bool(val&(1<<1))
        ret['persistent'] = bool(val&(1<<2))
        ret['energized'] = bool(val&(1<<3))
        ret['quenched'] = bool(val&(1<<4))
        return ret

    def _ramp_rate_field_checkdev_helper(self, unit=None, index=None):
        if unit not in ['sec', 'min', None]:
            raise ValueError(self.perror("Invalid unit, should be 'sec' or 'min' or None"))
        if unit is not None:
            # set unit here (don't use setcache otherwise ramp_rate_current.set will not do the unit set internally)
            # It will not be repeated in ramp_rate_current.set because the value is only set if different than the cache
            self.ramp_rate_unit.set(unit)
        if not (index is None or index >= 1):
            raise ValueError(self.perror("Invalid index, should be >=1 or None"))

    def _ramp_current_field_conv(self, dict_in, scale):
        return dict_improved([('rate', dict_in['rate']*scale), ('max_field', dict_in['max_current']*scale)])

    def  _ramp_rate_field_T_checkdev(self, val, unit=None, index=None):
        self._ramp_rate_field_checkdev_helper(unit, index)
        BaseDevice._checkdev(self.ramp_rate_field_T, val)
    def _ramp_rate_field_T_setdev(self, val, unit=None, index=None):
        """ Same options as ramp_rate_current but requires a dictionnary with rate and max_field (instead of max_current)
        """
        scale = self._coil_constant
        nval = dict(rate=val['rate']/scale, max_current=val['max_field']/scale)
        self.ramp_rate_current.set(nval, unit=unit, index=index)
        rval = self._ramp_current_field_conv(self.ramp_rate_current.getcache(), scale)
        self.ramp_rate_field_T._set_delayed_cache = rval
    def _ramp_rate_field_T_getdev(self, unit=None, index=None):
        val = self.ramp_rate_current.get(unit=unit, index=index)
        scale = self._coil_constant
        return self._ramp_current_field_conv(val, scale)

    def  _ramp_rate_field_kG_checkdev(self, val, unit=None, index=None):
        self._ramp_rate_field_checkdev_helper(unit, index)
        BaseDevice._checkdev(self.ramp_rate_field_kG, val)
    def _ramp_rate_field_kG_setdev(self, val, unit=None, index=None):
        """ Same options as ramp_rate_current but requires a dictionnary with rate and max_field (instead of max_current)
        """
        scale = self._coil_constant*10
        nval = dict(rate=val['rate']/scale, max_current=val['max_field']/scale)
        self.ramp_rate_current.set(nval, unit=unit, index=index)
        rval = self._ramp_current_field_conv(self.ramp_rate_current.getcache(), scale)
        self.ramp_rate_field_kG._set_delayed_cache = rval
    def _ramp_rate_field_kG_getdev(self, unit=None, index=None):
        val = self.ramp_rate_current.get(unit=unit, index=index)
        scale = self._coil_constant*10
        return self._ramp_current_field_conv(val, scale)

    def is_ramping(self, param_dict=None):
        """ Returns True when the magnet is ramping the field. Can be used for the sequencer. """
        return self.state.get() in ['ramping', 'ramping_manual_up', 'ramping_manual_down', 'zeroing']
    def is_stable(self, param_dict=None):
        """ Returns True when the magnet is not ramping nor changing the heat switch. Can be used for the sequencer. """
        return self.state.get() in ['paused', 'at_zero', 'holding']

    def _ramping_helper(self, stay_states, end_states=None, extra_wait=None):
        conf = self.conf_magnet()
        to = time.time()
        if stay_states == 'cooling_persistent_switch':
            prog_base = 'Magnet Cooling switch: {time}/%.1f'%conf['persistent_switch_cool_time']
        elif stay_states == 'heating_persistent_switch':
            prog_base = 'Magnet Heating switch: {time}/%.1f'%conf['persistent_switch_heat_time']
        elif self._last_state == 'ramp':
            prog_base = 'Magnet Ramping {current:.3f}/%.3f A'%self.current_target.getcache()
        else: # zeroing field
            prog_base = 'Magnet Ramping {current:.3f}/0 A'
        if isinstance(stay_states, string_bytes_types):
            stay_states = [stay_states]
        with release_lock_context(self):
            with mainStatusLine.new(priority=10, timed=True) as progress:
                while self.state.get() in stay_states:
                    #print(self.state.getcache(), self.current.get(), self.current_magnet.get(), self.current_target.getcache(), self.persistent_switch_en.get())
                    wait(.1)
                    progress(prog_base.format(current=self.current.get(), time=time.time()-to))
            if self.state.get() == 'quench':
                raise RuntimeError(self.perror('The magnet QUENCHED!!!'))
            if extra_wait:
                wait(extra_wait, progress_base='Magnet wait')
        if end_states is not None:
            if isinstance(end_states, string_bytes_types):
                end_states = [end_states]
            if self.state.get() not in end_states:
                raise RuntimeError(self.perror('The magnet state did not change to %s as expected'%end_states))

    @locked_calling
    def do_persistent(self, to_pers, quiet=True, extra_wait=None):
        """
        This function goes in/out of persistent mode.
        to_pers to True to go into peristent mode (turn persistent switch off, ramp to zero and leave magnet energized)
                   False to go out of persistent mode (reenergize leads and turn persistent switch on)
        It returns the previous state of the persistent switch.
        """
        # The instruments hardware user interface for the switch does exactly this algorithm:
        #   going off persistent: ramps to recorded current (changes target temporarily to recorded one)
        #                         then turns heat switch on
        #   going persistent:   turn heat swithc off, ramps to zero
        def print_if(s):
            if not quiet:
                print(s)
        if not self.persistent_switch_installed.getcache():
            return True
        state = self.state.get()
        if state in ['cooling_persistent_switch', 'heating_persistent_switch']:
            raise RuntimeError(self.perror('persistent switch is currently changing state. Wait.'))
        if state in  ['ramping', 'zeroing', 'ramping_manual_up', 'ramping_manual_down']:
            raise RuntimeError(self.perror('Magnet is ramping. Stop that before changing the persistent state.'))
        orig_switch_en = self.persistent_switch_en.get()
        self.set_state('pause')
        if to_pers:
            if orig_switch_en:
                # switch is active
                print_if('Turning persistent switch off and waiting for cooling...')
                self.persistent_switch_en.set(False)
                self._ramping_helper('cooling_persistent_switch', 'paused')
            print_if('Ramping to zero ...')
            self.set_state('zero')
            # This ramp is fast, no extra wait necessary, but user might want the delay.
            self._ramping_helper('zeroing', 'at_zero', extra_wait)
        else: # go out of persistence
            if not orig_switch_en:
                orig_target = self.current_target.get()
                self._orig_target_cache = orig_target
                tmp_target = self.current_magnet.get()
                print_if('Ramping to previous target ...')
                self.current_target.set(tmp_target)
                self.set_state('ramp')
                # The ramp is fast but still wait and extra 5 s for stability before pausing.
                self._ramping_helper('ramping', 'holding', 5.)
                self.set_state('pause')
                self.current_target.set(orig_target)
                self._orig_target_cache = None
                print_if('Turning persistent switch on and waiting for heating...')
                self.persistent_switch_en.set(True)
                self._ramping_helper('heating_persistent_switch', 'paused', extra_wait)
        return orig_switch_en

    def _do_ramp(self, current_target, wait, no_wait_end=False):
        if current_target == 0:
            self.set_state('zero')
        else:
            self.set_state('pause')
            self.current_target.set(current_target)
            self.set_state('ramp')
        if no_wait_end:
            return
        self._ramping_helper(['zeroing', 'ramping'], ['at_zero', 'holding'], wait)

    def _ramp_current_checkdev(self, val, return_persistent='auto', wait=None, quiet=True, no_wait_end=False):
        if return_persistent not in [True, False, 'auto']:
            raise ValueError(self.perror("Invalid return_persistent option. Should be True, False or 'auto'"))
        BaseDevice._checkdev(self.ramp_current, val)

    def _ramp_current_setdev(self, val, return_persistent='auto', wait=None, quiet=True, no_wait_end=False):
        """ Goes to the requested setpoint and then waits until it is reached.
            After the instrument says we have reached the setpoint, we wait for the
            duration set by ramp_wait_after (in s).
            return_persistent can be True (always), False (never) or 'auto' (the default)
                              which returns to state from start of ramp.
            wait can be used to set a wait time (in s) after the ramp. It overrides ramp_wait_after.
            no_wait_end when True, will skip waiting for the ramp to finish and return immediately after
                      starting the ramp. Useful for record sequence. This will not work when changing sign.
            When going to persistence it waits persistent_wait_before before cooling the switch.

            When using get, returns the magnet current.
        """
        def print_if(s):
            if not quiet:
                print(s)
        ps_installed = self.persistent_switch_installed.getcache()
        if wait is None:
            wait = self.ramp_wait_after.getcache()
        if ps_installed:
            # Go out of persistent (turn persistent switch on)
            prev_switch_en = self.do_persistent(to_pers=False, quiet=quiet)
            # Now change the field
            print_if('Ramping...')
            if return_persistent == True or (return_persistent == 'auto' and not prev_switch_en):
                self._do_ramp(val, self.persistent_wait_before.getcache(), no_wait_end)
                if no_wait_end:
                    return
                self.do_persistent(to_pers=True, quiet=quiet, extra_wait=wait)
            else:
                self._do_ramp(val, wait, no_wait_end)
        else: # no persistent switch installed
            print_if('Ramping...')
            self._do_ramp(val, wait, no_wait_end)

    def _ramp_current_getdev(self, return_persistent='auto', wait=None, quiet=True, no_wait_end=False):
        return self.current_magnet.get()

    def _create_devs(self):
        if self._port == 7180:
            if self.read() != 'American Magnetics Model 430 IP Interface':
                raise RuntimeError('Did not receive first expected message from instrument')
            if self.read() != 'Hello.':
                raise RuntimeError('Did not receive second expected message from instrument')
        fw_version = float(self.idn_split()['firmware'])
        self._new_firmware = True if fw_version >= 2.59 else False
        self.ramp_wait_after = MemoryDevice(10., min=0.)
        self.persistent_wait_before = MemoryDevice(30., min=30., doc='This time is used to wait after a ramp but before turning persistent off')
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
        #self.coil_constant = scpiDevice(getstr='COILconst?', str_type=float, doc='units are either kG/A or T/A, see field_unit device')
        self.ramp_rate_segment_index = MemoryDevice(1, min=1)
        self.ramp_rate_segment_count = scpiDevice('CONFigure:RAMP:RATE:SEGments', 'RAMP:RATE:SEGments?', str_type=int)
        rmin, rmax = self._min_ramp_rate, self._max_ramp_rate
        rate_lim = ChoiceDevDep(self.ramp_rate_unit, dict(min=ChoiceLimits(min=rmin*60, max=rmax*60), sec=ChoiceLimits(min=rmin, max=rmax)))
        self.ramp_rate_current = scpiDevice('CONFigure:RAMP:RATE:CURRent {index},{val}', 'RAMP:RATE:CURRent:{index}?',
                                            choices=ChoiceMultiple(['rate', 'max_current'], [(float, rate_lim), (float, (1e-4, None))]),
                                            options = dict(unit=self.ramp_rate_unit, index=self.ramp_rate_segment_index),
                                            options_apply = ['unit', 'index'],
                                            allow_kw_as_dict=True, allow_missing_dict=True,
                                            allow_val_as_first_dict=True, setget=True,
                                            doc="""
                                                When using segments, max_rate needs to be larger (not equal or smaller) than for previous index.
                                                However it can be larger than subsequent index.
                                                """)
        #self.ramp_rate_field = scpiDevice(getstr='RAMP:RATE:FIELD:1?', choices=ChoiceMultiple(['rate', 'max_field'], [float, float]),
        #            doc='Units are kG/s, T/s, kG/min or T/min see ramp_rate_unit and field_unit devices.')
        self.state = scpiDevice(getstr='STATE?', choices=ChoiceIndex(['ramping', 'holding', 'paused', 'ramping_manual_up', 'ramping_manual_down',
                        'zeroing', 'quench', 'at_zero', 'heating_persistent_switch', 'cooling_persistent_switch', 'ext_rampdown_active'], offset=1))
        self.persistent_switch_installed = scpiDevice('PSwitch:INSTalled?', str_type=bool)
        self.persistent_switch_ramp_rate = scpiDevice('CONFigure:PSwitch:PowerSupplyRampRate', 'PSwitch:PowerSupplyRampRate?', str_type=float, doc='Units are always A/s')
        self.persistent_switch_en = scpiDevice('PSwitch', str_type=bool)
        self.persistent_mode_active = scpiDevice(getstr='PERSistent?', str_type=bool,
                                                 doc='This is the same as the front panel persistent LED. Shows if magnet is energized and persistent.')
        self.quench_detected = scpiDevice(getstr='QUench?', str_type=bool)
        self.quench_count = scpiDevice(getstr='QUench:COUNT?', str_type=int)
        self.rampdown_count = scpiDevice(getstr='RAMPDown:COUNT?', str_type=int)
        rate_T_lim = ChoiceDevDep(self.ramp_rate_unit, dict(min=ChoiceLimits(min=0, max=0), sec=ChoiceLimits(min=0, max=0)))
        rate_kG_lim = ChoiceDevDep(self.ramp_rate_unit, dict(min=ChoiceLimits(min=0, max=0), sec=ChoiceLimits(min=0, max=0)))
        # These work almost like ramp_rate_current, except when getting the cache, it does not check if
        # the unit or index sources have changed. So can't you use them for conf_ramp_rates.
        self._devwrap('ramp_rate_field_T',
                      choices=ChoiceMultiple(['rate', 'max_field'], [(float, rate_T_lim), (float, (0, None))]),
                      allow_kw_as_dict=True, allow_missing_dict=True, allow_val_as_first_dict=True)
        self._devwrap('ramp_rate_field_kG',
                      choices=ChoiceMultiple(['rate', 'max_field'], [(float, rate_kG_lim), (float, (0, None))]),
                      allow_kw_as_dict=True, allow_missing_dict=True, allow_val_as_first_dict=True)
        self._devwrap('ramp_current', autoinit=False)
        if self._new_firmware:
            self._devwrap('led_state')
            #self.op_limit_ic = scpiDevice(getstr='OPLimit:IC?', str_type=float)
            #self.op_limit_temp = scpiDevice(getstr='OPLimit:TEMP?', str_type=float)

        # This needs to be last to complete creation
        super(AmericanMagnetics_model430, self)._create_devs()

# Master AMI current limit: CURR:LIM:AMI_MASTER?
#  to change it (dangerous procedure): CONF:CURR:LIM:AMI_MASTER

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
        super(MagnetSimul, self)._create_devs()


#######################################################
##    American Magnetics, Inc. Vector magnet
#######################################################

def length(self, xyz):
    return sqrt(xyz[0]**2 + xyz[1]**2 + xyz[2]**2)

def to_cartesian(self, rtp, deg=True):
    r, t, p = rtp
    if deg:
        t = t*pi/180
        p = p*pi/180
    x = r * sin(t) * cos(p)
    y = r * sin(t) * sin(p)
    z = r * cos(t)
    return np.array([x, y, z])

def to_spherical(self, xyz, deg=True, no_phi=False):
    x, y, z = xyz
    r = length(xyz)
    if no_phi:
        if no_phi == 'xz' and approx_equal(y, 0.):
            xy = x
            p = z*0.
        if no_phi == 'yz' and approx_equal(x, 0.):
            xy = y
            p = z*0. + pi/2
        else:
            raise ValueError('Asking for no_phi, but data has x and y ! =0')
    else:
        xy = sqrt(x**2 + y**2)
        p = arctan2(y, x)
    t = arctan2(xy, z)
    if deg:
        t *= 180/pi
        p *= 180/pi
    return np.array([r, t, p])

_Abs_Tol = 1e-6
def approx_equal(v1, v2):
    return np.allclose(v1, v2, atol=_Abs_Tol, rtol=1e-8)

def normalize(v1):
    # v1 is arrays of dimension (3, ...) where 3 is for x,y,z
    v1_length = length(v1)
    v1_length1 = np.where(v1_length < _Abs_Tol, 1., v1_length)
    norm = np.where(v1_length < _Abs_Tol, v1*0., v1/v1_length1)
    return norm


#@register_instrument('AMERICAN MAGNETICS INC.', 'VECTOR')
@register_instrument('AMERICAN MAGNETICS INC.', 'VECTOR', '1.0')
class AmericanMagnetics_vector(BaseInstrument):
    def __init__(self, magnet_x=None, magnet_y=None, magnet_z=None, max_vector_field=1, **kwargs):
        """
        magnet_x, y and z are AmericanMagnetics_model430 instruments (or for testing only MagnetSimul)
                 They can be left as None if only some magnets are being used (the others are assumed to be
                 at 0 Tesla. You should always load all powered on power supply otherwise you could
                 produce an unacceptable condition.
        max_vector_field is the maximum field when more than one magnet is on.
        With this instrument, fields are always Tesla. Rates are always T/min
        """
        if magnet_x == magnet_y == magnet_z == None:
            raise ValueError('At least one of the magnet needs to be specified.')
        # TODO could also check for same address. Not required because it is not possible to open the same magnet twice right now.
        if magnet_x is not None and magnet_x in ( magnet_y, magnet_z):
            raise ValueError('Two magnets are the same..')
        if magnet_y is not None and magnet_y in ( magnet_x, magnet_z):
            raise ValueError('Two magnets are the same..')
        self._magnet_x = magnet_x
        self._magnet_y = magnet_y
        self._magnet_z = magnet_z
        self._magnets = [magnet_x, magnet_y, magnet_z]
        self._magnets_name = ['x', 'y', 'z']
        self._max_vector_field = max_vector_field
        self._magnets_enable = [False]*3
        mnmx = dict(min_field=[None]*3, max_field=[None]*3,
                min_field_global=np.nan, max_field_global=np.nan,
                min_rate_global=np.nan, max_rate_global=np.nan)
        current_rate = [np.nan]*3
        def adjust_mnmx1(func, base, val, index=None):
            if index is not None:
                mnmx[base][i] = val
            s = base+'_global'
            mnmx[s] = func(mnmx[s], val)
        for i, (magnet, name) in enumerate(zip(self._magnets, self._magnets_name)):
            if magnet:
                self._magnets_enable[i] = True
                if not isinstance(magnet, (AmericanMagnetics_model430, MagnetSimul)):
                    raise ValueError('magnet%s_ is of the wrong type (should be AmericanMagnetics_model430)'%name)
                if magnet.ramp_rate_segment_count.get() > 1:
                    raise ValueError('magnet%s_ should only have one ramp_rate segment.'%name)
                adjust_mnmx1(max, 'min_field', magnet.field_target_T.min, i)
                adjust_mnmx1(min, 'max_field', magnet.field_target_T.max, i)
                adjust_mnmx1(max, 'min_rate', magnet.ramp_rate_field_T.choices.fmts_lims[0].choices['min'].min)
                adjust_mnmx1(min, 'max_rate', magnet.ramp_rate_field_T.choices.fmts_lims[0].choices['min'].max)
                current_rate[i] = magnet.ramp_rate_field_T.get(unit='min')
        self._magnets_lims = dict_improved(mnmx)
        super(AmericanMagnetics_vector, self).__init__(**kwargs)
        min_current_rate = min(current_rate)
        if max(np.array(current_rate)/min_current_rate) > 1.001:
            # only change ramp_rate if difference is larger than 1.001
            self.ramp_rate.set(min_current_rate)

    def _ramp_rate_check(self, val):
        for magnet in self._magnets:
            if magnet:
                magnet.ramp_rate_filed_T.check(val, unit='min')
    def _ramp_rate_setdev(self, val):
        for magnet in self._magnets:
            if magnet:
                magnet.ramp_rate_filed_T.set(val, unit='min')
    def _ramp_rate_getdev(self, val):
        for magnet in self._magnets:
            if magnet:
                # return first value
                return magnet.ramp_rate_filed_T.get(val)[0]

    def _field_getformat(self, unit='rect'):
        pass
    def _field_getdev(self, unit='rect'):
        pass

    # actually need to set different rates to go in a straight line.

    def _clean_up(self, xyz):
        xyz = np.where(np.abs(xyz) < _Abs_Tol, 0)
        return xyz
    def _check(self, xyz):
        #xyz = self._clean_up(xyz)
        all_zeros = [ np.all(f==0.) for f in xyz ]
        for f, enable in zip(xyz, self._magnets_enable):
            if not enable and np.any(f != 0.):
                raise ValueError(self.perror('Request of an invalid field'))
        mg_lims = self._magnets_lims
        if np.sum(all_zeros) == 2:
            i = all_zeros.index(False)
            mn, mx = mg_lims.min_field[i], mg_lims.max_field[i]
            if np.any(xyz[i] > mx) or np.any(xyz[i] < mn):
                raise ValueError(self.perror('Requested field bigger than axis min/max'))
        else:
            r = self._length(xyz)
            if r > self._max_vector_field:
                raise ValueError(self.perror('Requested field bigger than max_vector_field'))

    def _calculate_sequence(self, start, stop, only_rotation=False):
        # TODO use max_error to calculate a sequence between the 2 points.
        # Find the points and the rates that will satisfy the requirement.
        # Here find the theoretical path.
        # Later we will have to check the real path using the real ramp_rate to check we stay within the error.
        # Also decice if start is real field or starting target.
        start = self._clean_up(start)
        stop = self._clean_up(stop)
        self._check(stop)
        max_error = self.max_error.get()
        if only_rotation:
            start_rtp = to_spherical(start)
            r = start_rtp[0]
            stop_rtp = to_spherical(stop)
            if approx_equal(r, stop_rtp[0]):
                raise ValueError(self.perror('Requested a pure rotation, but start/stop change the magnitude.'))
            th_phi = self._find_rotation_sequence(r, start_rtp[1:], stop_rtp[1:], max_error)
            all_points_rtp = np.concatenate( (np.full((len(th_phi), 1), r), th_phi), axis=1)
            all_points = np.concatenate( (start, to_cartesian(all_points_rtp.T)), axis=1)
        else:
            all_points = np.array([start, stop]).T
        dif = np.diff(all_points)
        max_ramp_rate = self.ramp_rate.get()
        ramp_time = np.max(dif, axis=0, keep_dims=True)/max_ramp_rate
        ramp_rates = dif/ramp_time
        return all_points, dif, ramp_rates, max_error


    def _rotation_max_error_internal(xyz_start, xyz_end, r):
        L = length(xyz_end - xyz_start)
        return r - sqrt(r**2 - (L/2.)**2)

    def _rotation_max_error_xyz(self, xyz_start, xyz_end):
        r_start = length(xyz_start)
        r_end = length(xyz_end)
        if not approx_equal(r_start, r_end):
            raise ValueError('_rotation_max_error_xyz needs both vector to be the same length')
        return self._rotation_max_error_internal(xyz_start, xyz_end, r_start)

    def _rotation_max_error(self, r, th_phi_start, th_phi_end):
        # r is the same for start and end.
        # The max distance is exactly between start and end
        # It is between the circle radius (r) and the midpoint (of a triangle)
        xyz_start = to_cartesian([r]+list(th_phi_start), deg=True)
        xyz_end = to_cartesian([r]+list(th_phi_end), deg=True)
        return self._rotation_max_error_internal(xyz_start, xyz_end, abs(r))

    def _find_rotation_sequence(self, r, th_phi_start, th_phi_end, max_error, shortest=False):
        if shortest:
            # normalize the start/end
            th_phi_start = to_spherical(to_cartesian([r]+list(th_phi_start)))
            th_phi_end = to_spherical(to_cartesian([r]+list(th_phi_end)))
        th_phi_diff = th_phi_end - th_phi_start
        th_phi_diff = (th_phi_diff + 360) % 720 - 360 #  keep th_phi between -360 and +360 def
        if shortest:
            # we limit to +- 180 deg
            th_phi_diff += np.where(th_phi_diff > 180, -360, 0)
            th_phi_diff += np.where(th_phi_diff < 180, +360, 0)
        half = False
        if np.any(abs(th_phi_diff)>180):
            th_phi_diff = th_phi_diff/2
            half = True
        th_phi_end = th_phi_start + th_phi_diff
        error = self._rotation_max_error(r, th_phi_start, th_phi_end)
        N = 1
        if error > max_error:
            # we minimize the rotation_max_error
            xyz_start = to_cartesian([r]+list(th_phi_start))
            xyz_end = to_cartesian([r]+list(th_phi_end))
            unit1 = normalize(xyz_start)
            unit2 = normalize(xyz_end)
            unit12 = np.dot(unit1, unit2)
            rot_angle = np.arccos(unit12)
            unit_perp = normalize(unit2 - unit1*unit12)
            froot = lambda x: self._rotation_max_error_xyz([r,0,0], [r*cos(rot_angle*x), r*sin(rot_angle*x),0]) - max_error
            root, sol = brentq(froot, 0., 1., xtol=1e-6, maxiter=1000, full_output=True, disp=False)
            if not sol.converged:
                raise RuntimeError('Something went wrong finding the rotation sequence. (%r)'%sol)
            x = sol.root
            N = np.ceil(1./x)
        if half:
            N *= 2
        steps = np.arange(1, N+1)/N
        th_phi = th_phi_start + th_phi_diff * steps[:, None]
        # rt = rot_angle * steps
        # xyz_s = r*(unit1*cos(rt) + unit_perp*sin(rt))
        return th_phi

    def _ramp_it_helper(self, target, last=False):
        if last:
            print('Last ramp')
        print('Going to:', target)
        
        
    def _ramp_it_rtp(self, start, stop, only_rotation=True):
        """ only_rotation can be True, False or 'auto'
              in which case it will be True if r is unchanged between start/stop.
        """
        if approx_equal(start[0], stop(0)):
            if only_rotation == 'auto':
                only_rotation = True
        elif only_rotation == True:
                raise ValueError('Request for rotation but r is changing.')
        if only_rotation == 'auto':
            only_rotation = False
        start_xyz = to_cartesian(start)
        stop_xyz = to_cartesian(stop)
        self._ramp_it_xyz(start_xyz, stop, only_rotation)

    def _line_max_error(self, dif, rate):
        dif_pos = abs(dif)
        t_first = min(dif_pos/rate)
        delta = length(real_rate*t_first - dif_pos)
        return delta


    def _ramp_it_xyz(self, start, stop, only_rotation=False):
        all_points, difs, ramp_rates, max_error = self._calculate_sequence(start, stop, only_rotation)
        N = len(difs)
        for i, (point, dif, rate) in enumerate(zip(all_points[1:], difs, ramp_rates)):
            is_last = i == N-1
            # set ramp rate (making sure it is accepted)
            # get real ramp rate
            real_rate = np.array([1.,1.,1.])
            delta = self._line_max_error(dif, real_rate)
            if delta > max_error:
                start = all_points[i]
                N2 = np.ceil(delta/max_error)
                dif_n = dif/N2
                targets = start + dif_n*np.arange(1, N2+1)[:, None]
                prev = start
                for j, target in enumerate(targets):
                    is_last2 = is_last and j == N2 - 1
                    self.ramp_it_helper(target, is_last2)
                    print('Iter i,j=%i,%i  error=%.8f'%(i,j, self._line_max_error(target-prev, real_rate)))
                    prev = target
            else:
                self.ramp_it_helper(point, is_last)
                print('Iter i=%i  error=%.8f'%(i, self._line_max_error(point-all_points[0], real_rate)))
            if only_rotation:
                print('rotation error=%.8f'%(self._rotation_max_error_xyz(all_points[0], point)))

        
    def _create_devs(self):
        self.max_error = MemoryDevice(1e-3, min=1e-6, max=1e3)
        self.ramp_rate = MemoryDevice(1e-3, min=1e-6, max=1, doc='In unit of T/min')
        self._devwrap('ramp_rate')
        # This needs to be last to complete creation
        super(AmericanMagnetics_vector, self)._create_devs()


