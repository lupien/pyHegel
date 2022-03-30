# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2022-2022  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

import struct

from ..instruments_base import visaInstrument,\
                            scpiDevice, MemoryDevice,\
                            ChoiceStrings, ChoiceMultiple, Choice_bool_OnOff,\
                            decode_float64, ChoiceIndex,\
                            visa_wrap, locked_calling, wait, ProxyMethod
from ..instruments_registry import register_instrument

#######################################################
##    ICEoxford Temperature Control program
#######################################################

# all commands and response are in capitals. The instrument does not accept small caps.
#TODO use _write_test to keep alive the connection if necessary.

class iceoxford_dev(scpiDevice):
    """ handles standard returns and forces lower/upper conversions """
    def __init__(self, *args, **kwargs):
        """ strip_reply can be True(default)/False/'auto' """
        self._strip_reply = kwargs.pop('strip_reply', True)
        self._autoset_val_str = '={val}'
        kwargs['write_func'] = ProxyMethod(self._write_override)
        kwargs['ask_func'] = ProxyMethod(self._ask_override)
        super(iceoxford_dev, self).__init__(*args, **kwargs)
    def _write_override(self, cmd, **kwargs):
        resp = self.instr.ask(cmd.upper(), **kwargs)
        self.instr._handle_std_reply(resp)
    def _ask_override(self, cmd, **kwargs):
        return self.instr.ask(cmd.upper(), **kwargs)
    def _fromstr(self, valstr):
        pre = self._getdev_last_full_cmd[:-1] + '=' # Remove question mark from getstr
        ispre = valstr.startswith(pre.upper())
        strip_reply = self._strip_reply
        if strip_reply is True and not ispre:
            raise RuntimeError(self.perror('Missing header in response.'))
        if strip_reply is True or (strip_reply == 'auto' and ispre):
            valstr = valstr[len(pre):]
        return super(iceoxford_dev, self)._fromstr(valstr.lower())
    #def __del__(self):
    #    print 'Releasing iceoxford dev'

def sensor_return(valstr):
    if valstr == '':
        return 0
    else:
        return int(valstr)

#@register_instrument('ICEoxford', 'ICE_Temperature_Control', '3.0.1.1')
@register_instrument('ICEoxford', 'ICE_Temperature_Control')
class iceoxford_temperature_controller(visaInstrument):
    """
    This is the driver of the ICEoxford temperature controller.
    Connection address will look like (for direct connection):
        tcpip::localhost::6435::SOCKET
    or for indirect connection:
        tcpip::localhost::6340::SOCKET
    Either way, only one connection is functionnal at a time.
    Useful devices:
        t
        s
        temperatures
        pressures
    Useful methods:
        nv_set_values
        heat_sw_set_values
        heater_set_values
    """
    def __init__(self, visa_addr, direct='auto', open_app=False, *args, **kwargs):
        """
        direct when True, connects directly to the ICE Temperature Control program.
               when False, connects through the ICE Remote Comms Service program that needs to be running.
               when auto, it will select it according the the visa_addr ports (True for 6435, False for 6340)
               This option need to match with the visa_addr port.
        open_app when True and when direct is False, will try an start the application before making the connection.
        """
        kwargs['read_termination'] = '\r\n'
        kwargs['write_termination'] = '\r\n'
        if direct not in ['auto', True, False]:
            raise ValueError('Invalid direct value')
        if direct == 'auto':
            port = int(visa_addr.split('::')[2])
            if port == 6435:
                direct = True
            elif port == 6340:
                direct = False
            else:
                raise ValueError('Unknown port so you need to select True or False for direct.')
        self._direct_con = direct
        self._open_app = open_app
        super(iceoxford_temperature_controller, self).__init__(visa_addr, *args, **kwargs)

    def idn(self):
        idn = self.ask('*IDN?')
        model, fw = idn.split(' ')
        return 'ICEoxford,%s,no-serial,%s'%(model, fw)

    def _write_test(self):
        super(iceoxford_temperature_controller, self).write('TESTCONNECT')

    @locked_calling
    def write(self, val, termination='default'):
        if self._direct_con:
            n = len(val)
            val = struct.pack('>q', n) + val +  struct.pack('>lql', 1, 0, 0)
        super(iceoxford_temperature_controller, self).write(val)

    def _handle_std_reply(self, resp, good='OK', bad='ERROR'):
        if resp == good:
            return
        if resp == bad:
            raise RuntimeError(self.perror('The last command failed.'))
        raise RuntimeError(self.perror('The last command had an unexpected reply of: %s'%resp))

    def _current_config(self, dev_obj=None, options={}):
        base = self._conf_helper('field_T', 'field_target_T', 'current_magnet', 'current_target',
                                 'voltage', 'voltage_limit', 'ramp_rate_field_T_min',
                                 'field_trip_T', 'lead_resistance_mOhm', 'magnet_inductance_H',
                                 'persistent_heater_current_mA',
                                 'status', 'psh_time_cool', 'psh_time_heat', 'psh_wait_before')
        base += ['isobus_num=%s'%self._isobus_num]
        return base + self._conf_helper(options)

    def get_error(self):
        raise RuntimeError('This instrument does not return error information')

    def lemon_connect(self):
        """ use when connection is not direct to make Remote comms app connect to main app."""
        resp = self.ask("CONNECT LEMON")
        self._handle_std_reply(resp, good='CONNECTED')

    def lemon_disconnect(self):
        """ use when connection is not direct to make Remote comms app disconnect from main app.
            After this no device will work until lemon_connect is called.
        """
        resp = self.ask("DISCONNECT LEMON")
        self._handle_std_reply(resp)

    def lemon_is_connected(self):
        """ use when connection is not direct to check Remote comms app connection to main app.
        When False, you can use lemon_connect to reestablish the connection.
        """
        resp = self.ask("LEMON CONNECTED?")
        if resp == 'LEMON CONNECTED':
            return True
        if resp == 'LEMON DISCONNECTED':
            return False
        raise RuntimeError(self.perror('Unexepected reply to Lemon connected request: %s'%resp))

    def lemon_open_app(self):
        """ use when connection is not direct to make Remote comms app start main app (or bring it the front)."""
        resp = self.ask("OPEN LEMON")
        self._handle_std_reply(resp)

    def nv_set_values(self):
        resp = self.ask("NV1 SET VALUES")
        self._handle_std_reply(resp)
    def heat_sw_set_values(self):
        resp = self.ask("HEAT SW1 SET VALUES")
        self._handle_std_reply(resp)
    def heater_set_values(self):
        resp = self.ask("HEATER1 SET VALUES")
        self._handle_std_reply(resp)

    def _create_devs(self):
        if self._direct_con:
            try:
                res = self.read()
                if res != 'Connected':
                    raise RuntimeError('Did not receive expected connected response.')
            except visa_wrap.VisaIOError as exc:
                if exc.error_code == visa_wrap.constants.StatusCode.error_timeout:
                    # if this connection is closed before the main one is closed,
                    # it will make the main ICE temperature Control tcp write loop crash
                    # when it tries to send the Connected result to it (when it switches connection)
                    # So lets not force a close here and hope that it will stay in memory long enough (because ipython
                    # keeps the last exception).
                    raise RuntimeError('Expected reception of connected response timed out. Another connection could already be established (only one functionnal at a time).')
                else:
                    raise
        else:
            if not self.lemon_is_connected():
                if self._open_app:
                    self.lemon_open_app()
                    wait(9)
                self.lemon_connect()
        self.system_status = iceoxford_dev(getstr='SYSTEM STATUS?', doc="""Result is either 'ready' or 'in use'""")
        self.nv_mode = iceoxford_dev('NV1 MODE', choices=ChoiceStrings('manual', 'auto'))
        self.nv_manual_out = iceoxford_dev('NV1 MAN OUT', str_type=float)
        self.nv_error_band = iceoxford_dev('NV1 ERROR BAND', str_type=float)
        self.nv_setpoint = iceoxford_dev('NV1 SETPOINT', str_type=float)
        self.nv_ramp = iceoxford_dev('NV1 RAMP', str_type=float)
        self.nv_output = iceoxford_dev(getstr='NV OUTPUT 1?', str_type=float)
        self.nv_pid = iceoxford_dev('NV1 PID', choices=ChoiceMultiple(['p', 'i', 'd'], [float]*3))
        self.heat_sw_mode = iceoxford_dev('HEAT SW1 MODE', choices=ChoiceStrings('manual', 'auto'))
        input_sel = ChoiceStrings('A', 'B', 'C', 'D1', 'D2', 'D3', 'D4', 'D5')
        self.heat_sw_input = iceoxford_dev('HEAT SW1 INPUT', choices=input_sel)
        self.heat_sw_setpoint = iceoxford_dev('HEAT SW1 SETPOINT', str_type=float)
        self.heat_sw_error_band = iceoxford_dev('HEAT SW1 ERROR BAND', str_type=float)
        self.heat_sw_relay_en = iceoxford_dev('HEAT SW1 RELAY', choices=Choice_bool_OnOff)
        self.pressure_dump = iceoxford_dev(getstr='DUMP PRESSURE?', str_type=float)
        self.pressure_sample = iceoxford_dev(getstr='SAMPLE SPACE PRESSURE?', str_type=float)
        self.pressure_circulation = iceoxford_dev(getstr='CIRCULATION PRESSURE?', str_type=float)
        self.pressures_raw = iceoxford_dev(getstr='PRESSURES?', str_type=decode_float64, strip_reply=False,
                                       multi=['dump', 'sample', 'circulation'], autoinit=False)
        self.temperatures_raw = iceoxford_dev(getstr='TEMPS?', str_type=decode_float64, strip_reply=False,
                                          multi=['A', 'B', 'C', 'D1', 'D2', 'D3', 'D4', 'D5'], autoinit=False)
        self.current_ch = MemoryDevice('A', choices=input_sel)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return iceoxford_dev(*arg, **kwarg)
        self.t = devChOption(getstr='TEMPERATURE {ch}?', str_type=float, doc='Temperature. See also s device.')
        self.s = devChOption(getstr='RAW {ch}?', str_type=float, doc='Raw sample unit of temperature sensore. See also t device.')
        self.heater_mode = iceoxford_dev('HEATER1 MODE', choices=ChoiceStrings('manual', 'auto'))
        self.heater_input = iceoxford_dev('HEATER1 CHAN', choices=input_sel)
        self.heater_manual_out = iceoxford_dev('HEATER1 MAN OUT', str_type=float)
        self.heater_setpoint = iceoxford_dev('HEATER1 SETPOINT', str_type=float)
        self.heater_ramp = iceoxford_dev('HEATER1 RAMP', str_type=float)
        self.heater_setpoint_ramp_en = iceoxford_dev('HEATER1 SETPOINT RAMP', choices=Choice_bool_OnOff)
        self.heater_output = iceoxford_dev(getstr='HEATER OUTPUT 1?', str_type=float)
        self.heater_pid = iceoxford_dev('HEATER1 PID', choices=ChoiceMultiple(['p', 'i', 'd'], [float]*3))
        self.heater_range = iceoxford_dev('HEATER1 RANGE', choices=ChoiceStrings('off', 'low', 'medium', 'high'))
        self.sensor_curve = iceoxford_dev('SENSOR {ch} CURVE', str_type=sensor_return, options=dict(ch='A'),
                                          options_lim=dict(ch=ChoiceIndex(['A', 'B', 'C', 'D1', 'D2', 'D3', 'D4', 'D5'], offset=1)))
        super(iceoxford_temperature_controller, self)._create_devs()

# TODO: combine nv settings with nv_set_values
#  do the same for heat_sw_set_values and heater_set_values
#       Handle nv1, nv2, heater1, heater2 (could also do HEAT SW1,2)
#     handle pressures, temperatures (only returning valid values, no NaN)
