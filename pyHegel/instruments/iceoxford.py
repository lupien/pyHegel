# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2022-2023  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

import struct
import types
import time

from ..instruments_base import visaInstrument, BaseDevice,\
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

def cond_proxy(func):
    if isinstance(func, types.MethodType):
        return ProxyMethod(func)
    return func

class iceoxford_dev(scpiDevice):
    """ handles standard returns and forces lower/upper conversions """
    def __init__(self, *args, **kwargs):
        """ strip_reply can be True(default)/False/'auto'
            confirm is the function to set the values
        """
        self._strip_reply = kwargs.pop('strip_reply', True)
        self._confirm_func = cond_proxy(kwargs.pop('confirm', None))
        self._autoset_val_str = '={val}'
        self._noset_last = None
        kwargs['write_func'] = ProxyMethod(self._write_override)
        kwargs['ask_func'] = ProxyMethod(self._ask_override)
        kwargs['extra_set_after_func'] = ProxyMethod(self._after_write)
        super(iceoxford_dev, self).__init__(*args, **kwargs)
    def _after_write(self, val, dev_obj, **kwargs):
        if self._confirm_func is not None and not self._noset_last:
            self._confirm_func()
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
    def check(self, *val, **kwargs):
        self._noset_last = kwargs.pop('noset', False)
        super(iceoxford_dev, self).check(*val, **kwargs)
    #def __del__(self):
    #    print('Releasing iceoxford dev', self._getdev_p)

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
        prep_cooldown
        do_warmup
        finish_warmup
        finish_cooldown
        do_boiloff
        cooldown_fast
    All the nv*, heat_sw* and heater set device automatically call the matching set_values by default.
    To prevent that, call the set with noset=True
    """
    def __init__(self, visa_addr, direct='auto', open_app=False, temps={0:'50k', 1:'4K', 2:'1Kpot'},
                 pressures=[0, 2], *args, **kwargs):
        """
        direct when True, connects directly to the ICE Temperature Control program.
               when False, connects through the ICE Remote Comms Service program that needs to be running.
               when auto, it will select it according the the visa_addr ports (True for 6435, False for 6340)
               This option need to match with the visa_addr port.
        open_app when True and when direct is False, will try an start the application before making the connection.
        temps is a dictionnary of the index as key and name as value to extract from temperatures device
        pressures is a list of the index to extract with pressures device.
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
        self._temps_sel = temps
        self._pressures_sel = pressures
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
            vs = val.split('=', 1)
            if len(vs) == 1:
                vs += ['']
            pre, end = vs
            n_pre = len(pre)
            n_end = len(end)
            end_vals = end.split(',')
            try:
                end_floats = [float(v) for v in end_vals]
            except ValueError:
                end_floats = [0.]
            data =  struct.pack('>l', len(end_floats))
            for v in end_floats:
                data += struct.pack('>d', v)
            val = struct.pack('>q', n_pre) + pre + data + struct.pack('>l', n_end) + end
        super(iceoxford_temperature_controller, self).write(val)

    def _handle_std_reply(self, resp, good='OK', bad='ERROR'):
        if resp == good:
            return
        if resp == bad:
            raise RuntimeError(self.perror('The last command failed.'))
        raise RuntimeError(self.perror('The last command had an unexpected reply of: %s'%resp))

    def _current_config(self, dev_obj=None, options={}):
        base = self._conf_helper('system_status', 'temperatures', 'pressures')
        base += self._conf_helper('current_nv', 'nv_mode', 'nv_setpoint', 'nv_ramp', 'nv_pid', 'nv_error_band', 'nv_output')
        base += self._conf_helper('heat_sw_mode', 'nv_setpoint', 'heat_sw_input', 'heat_sw_setpoint', 'heat_sw_error_band', 'heat_sw_relay_en')
        base += self._conf_helper('current_outch', 'heater_mode', 'heater_input', 'heater_setpoint', 'heater_ramp', 'heater_pid', 'heater_range', 'heater_output')
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

    def nv_set_values(self, ch=None):
        if ch is not None:
            self.current_nv.set(ch)
        ch = self.current_nv.get()
        resp = self.ask("NV{ch} SET VALUES".format(ch=ch))
        self._handle_std_reply(resp)
    def heat_sw_set_values(self):
        resp = self.ask("HEAT SW1 SET VALUES")
        self._handle_std_reply(resp)
    def heater_set_values(self, outch=None):
        if outch is not None:
            self.current_outch.set(outch)
        outch = self.current_outch.get()
        resp = self.ask("HEATER{outch} SET VALUES".format(outch=outch))
        self._handle_std_reply(resp)

    def _temperatures_getformat(self, **kwarg):
        idx = sorted(self._temps_sel.keys())
        multi = [self._temps_sel[i] for i in idx]
        fmt = self.temperatures._format
        fmt.update(multi=multi)
        return BaseDevice.getformat(self.temperatures, **kwarg)
    def _temperatures_getdev(self):
        vals = self.temperatures_raw.get()
        idx = sorted(self._temps_sel.keys())
        return vals[idx]

    def _pressures_getformat(self, **kwarg):
        idx = self._pressures_sel
        titles = ['dump', 'sample', 'circulation']
        multi = [titles[i] for i in idx]
        fmt = self.pressures._format
        fmt.update(multi=multi)
        return BaseDevice.getformat(self.pressures, **kwarg)
    def _pressures_getdev(self):
        vals = self.pressures_raw.get()
        idx = self._pressures_sel
        return vals[idx]

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
        self.current_nv = MemoryDevice(1, choices=[1, 2])
        def devNvOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_nv)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app, confirm=self.nv_set_values)
            return iceoxford_dev(*arg, **kwarg)
        self.nv_mode = devNvOption('NV{ch} MODE', choices=ChoiceStrings('manual', 'auto'))
        self.nv_manual_out = devNvOption('NV{ch} MAN OUT', str_type=float)
        self.nv_error_band = devNvOption('NV{ch} ERROR BAND', str_type=float)
        self.nv_setpoint = devNvOption('NV{ch} SETPOINT', str_type=float)
        self.nv_ramp = devNvOption('NV{ch} RAMP', str_type=float)
        self.nv_output = devNvOption(getstr='NV OUTPUT {ch}?', str_type=float)
        self.nv_pid = devNvOption('NV{ch} PID', choices=ChoiceMultiple(['p', 'i', 'd'], [float]*3), allow_kw_as_dict=True, allow_missing_dict=True)
        devHsOption = lambda *args, **kwargs: iceoxford_dev(*args, confirm=self.heat_sw_set_values, **kwargs)
        self.heat_sw_mode = devHsOption('HEAT SW1 MODE', choices=ChoiceStrings('manual', 'auto'))
        input_sel = ChoiceStrings('A', 'B', 'C', 'D1', 'D2', 'D3', 'D4', 'D5')
        self.heat_sw_input = devHsOption('HEAT SW1 INPUT', choices=input_sel)
        self.heat_sw_setpoint = devHsOption('HEAT SW1 SETPOINT', str_type=float)
        self.heat_sw_error_band = devHsOption('HEAT SW1 ERROR BAND', str_type=float)
        self.heat_sw_relay_en = devHsOption('HEAT SW1 RELAY', choices=Choice_bool_OnOff)
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
        self.current_outch = MemoryDevice(1, choices=[1, 2])
        def devOutOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(outch=self.current_outch)
            app = kwarg.pop('options_apply', ['outch'])
            kwarg.update(options=options, options_apply=app, confirm=self.heater_set_values)
            return iceoxford_dev(*arg, **kwarg)
        self.heater_mode = devOutOption('HEATER{outch} MODE', choices=ChoiceStrings('manual', 'auto'))
        self.heater_input = devOutOption('HEATER{outch} CHAN', choices=input_sel)
        self.heater_manual_out = devOutOption('HEATER{outch} MAN OUT', str_type=float)
        self.heater_setpoint = devOutOption('HEATER{outch} SETPOINT', str_type=float)
        self.heater_ramp = devOutOption('HEATER{outch} RAMP', str_type=float)
        self.heater_setpoint_ramp_en = devOutOption('HEATER{outch} SETPOINT RAMP', choices=Choice_bool_OnOff)
        self.heater_output = devOutOption(getstr='HEATER OUTPUT {outch}?', str_type=float)
        self.heater_pid = devOutOption('HEATER{outch} PID', choices=ChoiceMultiple(['p', 'i', 'd'], [float]*3), allow_kw_as_dict=True, allow_missing_dict=True)
        self.heater_range = devOutOption('HEATER{outch} RANGE', choices=ChoiceStrings('off', 'low', 'medium', 'high'))
        self.sensor_curve = iceoxford_dev('SENSOR {ch} CURVE', str_type=sensor_return, options=dict(ch='A'),
                                          options_lim=dict(ch=ChoiceIndex(['A', 'B', 'C', 'D1', 'D2', 'D3', 'D4', 'D5'], offset=1)))
        self._devwrap('pressures')
        self._devwrap('temperatures')
        super(iceoxford_temperature_controller, self)._create_devs()

    def prep_cooldown(self):
        """ Setup the ICEoxford program so it is ready for a cooldown.
            It adjusts the heaters (off), the needle valve and the heatswitch.
        """
        self.nv_mode.set('auto', noset=True)
        self.nv_setpoint.set(1, noset=True)
        self.nv_ramp.set(100, noset=True)
        #self.nv_pid.set(p=50, i=.2, d=0, noset=True)
        self.nv_pid.set(p=1000, i=0.01, d=0, noset=True)
        self.nv_error_band.set(0.2)
        self.heater_range.set('off', outch=1, noset=True)
        self.heater_input.set('B', noset=True)
        self.heater_mode.set('manual', noset=True)
        self.heater_pid.set(p=10, i=20, d=0, noset=True)
        self.heater_setpoint_ramp_en.set(False)
        self.heater_setpoint.set(.5)
        self.heater_range.set('off', outch=2, noset=True)
        self.heater_input.set('C', noset=True)
        self.heater_mode.set('manual', noset=True)
        self.heater_pid.set(p=100, i=20, d=0, noset=True)
        self.heater_setpoint_ramp_en.set(False)
        self.heater_setpoint.set(.5)
        self.heat_sw_mode.set('auto', noset=True)
        self.heat_sw_input.set('B', noset=True)
        self.heat_sw_setpoint.set(5, noset=True)
        self.heat_sw_error_band.set(.5)

    def _do_warmup_prep(self):
        # heat switch disengaged
        self.heat_sw_relay_en.set(False, noset=True)
        self.heat_sw_mode.set('manual')
        # nv auto, ramp 100 mBar/min, 0.2 mBar error band. Left are Setpoint and PID
        self.nv_mode.set('auto', noset=True)
        self.nv_ramp.set(100, noset=True)
        self.nv_error_band.set(0.2)
        # heater 2, (C, auto, no power, no ramp). Left are SetPoint, PID, power range
        self.heater_range.set('off', outch=2, noset=True)
        self.heater_input.set('C', noset=True)
        self.heater_mode.set('auto', noset=True)
        self.heater_setpoint_ramp_en.set(False)

    def _get_t1k(self):
        temps = self.temperatures.get()
        return temps[2]

    def do_boiloff(self, skip_prep=False):
        """ Boil off the liquid Helium if present.
            The function waits until all the helium is gone
            The skip_prep is an internal option. Do not use it (it skips some settings to save time).
        """
        t1k = self._get_t1k()
        if t1k < 5:
            print("\n!!! Please wait for the Helium to boil off before proceeding !!!\n Starting at: %s\n"%time.ctime())
            if not skip_prep:
                self._do_warmup_prep()
            # might have some liquid, need to boil it off
            #  set nv so that is is going to close (but will open back if something happens)
            self.nv_setpoint.set(1, noset=True)
            self.nv_pid.set(p=1000, i=.1, d=0)
            self.heater_pid.set(p=50, i=50, d=0, noset=True)
            self.heater_setpoint.set(8.)
            self.heater_range.set('medium')
            while True:
                t1k = self._get_t1k()
                Pcirc = self.pressure_circulation.get()
                if t1k > 6 and Pcirc < 3:
                    break
                wait(10)
            self.heater_pid.set(p=50, i=10, d=0)
            self.nv_setpoint.set(5, noset=True)
            self.nv_pid.set(p=1000, i=0.1, d=0)
            i = 0
            # wait until flow > 3 for at least 1 min
            while i < 6:
                Pcirc = self.pressure_circulation.get()
                if Pcirc > 3:
                    i += 1
                else:
                    i = 0
                wait(10)
            self.nv_pid.set(p=1000, i=1, d=0)
            print("\n Boil off finished at:", time.ctime())
        else:
            print("\n Already warm enough. There should be no liquid He present. Boil off skipped.\n")

    def cooldown_fast(self, cooldown_nv_sp=8):
        """ Cool down fast. First set the setpoint and pid you want for both nv and heater2. """
        t1k = self._get_t1k()
        t1ksp = self.heater_setpoint.get(outch=2)
        hr = self.heater_range.get()
        if t1k-2 > t1ksp or (hr == 'off' and t1k > 4.0):
            print("\n!!! Please wait for the temperature to reach the setpoint\n")
            nv_setpoint = self.nv_setpoint.get()
            nv_pid = self.nv_pid.get()
            self.nv_setpoint.set(cooldown_nv_sp, noset=True)
            self.nv_pid.set(p=1000, i=.02, d=0)
            self.heater_range.set('off')
            while self._get_t1k() > t1ksp+1:
                wait(10)
            self.nv_setpoint.set(nv_setpoint, noset=True)
            self.nv_pid.set(nv_pid)
            self.heater_range.set(hr)
        else:
            print("\n !! Fast cooldown skipped because temperature is not above Setpoint by more than 2K\n")

    def do_warmup(self):
        """ Setup the ICEoxford program so it starts the warmup.
            It adjusts the heaters, the needle valve and the heatswitch.
        """
        self._do_warmup_prep()
        self.do_boiloff(skip_prep=True)
        temps = self.temperatures.get()
        t1k = temps[2]
        t4k = temps[1]
        # open nv large enough so that we are far from being close
        # This is to prevent any problem of thermal contraction breaking the needle valve thread.
        self.nv_setpoint.set(5, noset=True)
        self.nv_pid.set(p=1000, i=1, d=0)
        # heater 1, (4K, B)
        self.heater_range.set('off', outch=1, noset=True)
        self.heater_input.set('B', noset=True)
        self.heater_mode.set('auto', noset=True)
        self.heater_setpoint_ramp_en.set(False, noset=True)
        self.heater_ramp.set(0.4, noset=True)
        self.heater_pid.set(p=10, i=20, d=0)
        # Now toggle setpoint and ramp in the proper order.
        self.heater_setpoint.set(t4k)
        self.heater_setpoint_ramp_en.set(True)
        self.heater_range.set('medium')
        self.heater_setpoint.set(285)
        # heater 2, (1K, C)
        self.heater_ramp.set(0.4, outch=2, noset=True)
        self.heater_pid.set(p=10, i=20, d=0)
        # Now toggle setpoint and ramp in the proper order.
        self.heater_setpoint.set(t1k)
        self.heater_setpoint_ramp_en.set(True)
        self.heater_range.set('high')
        self.heater_setpoint.set(295)
        print("\n ***  You can now shut off the compressor.  ***\n")

    def finish_warmup(self):
        """ Setup the ICEoxford program so it stops the warmup.
            It turns off the heaters and adjusts the needle valve before stopping
            the circulation pump.
        """
        self.heater_range.set('off', outch=1, noset=True)
        self.heater_mode.set('manual')
        self.heater_range.set('off', outch=2, noset=True)
        self.heater_mode.set('manual')
        self.nv_mode.set('manual')
        self.nv_manual_out.set(95)

    def finish_cooldown(self):
        """ Setup the ICEoxford program so it stops the cooldown.
            It just makes sure the heatswitch is disabled
        """
        self.heat_sw_relay_en.set(False, noset=True)
        self.heat_sw_mode.set('manual')


# TODO: could handle multiple heat_sw
