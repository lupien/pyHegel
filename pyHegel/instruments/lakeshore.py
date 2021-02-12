# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2011-2020  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

import numpy as np
import time
import re


from ..instruments_base import visaInstrument,\
                            BaseDevice, scpiDevice, MemoryDevice, Dict_SubDevice,\
                            ChoiceBase, ChoiceMultiple, ChoiceMultipleDep,\
                            ChoiceStrings, ChoiceIndex, ChoiceDevDep, ChoiceLimits,\
                            make_choice_list, decode_float64, float_as_fixed,\
                            visa_wrap, locked_calling, wait, ProxyMethod,\
                            resource_info, _general_check, release_lock_context,\
                            mainStatusLine
from ..types import dict_improved
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

from .logical import FunctionDevice, ScalingDevice

register_idn_alias('Lake Shore Cryotronics', 'LSCI')

#  These observations are on model 336
# Lakeshore displays random characters for ascii 0-31
# character 127 is a space
# Only 7bit are used (even on tcpip)
# However, gpib does allow above 128.
# in 128-159, it is the same as CP437.
# from 160-180 they are symbols used for the lakeshore display. Some are 2 or 4 character long
#  like setpoint (SP, 168+169) or K/min (175-178). The degree symbol is at the regular 167.
# At and above 180 it is random character again.

class quoted_name(object):
    def __init__(self, length=15):
        self._length = length
        self.fixed_length_on_read = length
    def __call__(self, read_str):
        # the instruments returns a self._length characters string with spaces if unused
        # remove the extra spaces
        return read_str.rstrip()
    def tostr(self, input_str):
        if len(input_str) > self._length:
            print('String "%s" is longer than allowed %i char. It is truncated.')
            input_str = input_str[:self._length]
        for c in input_str:
            # gpib would allow more but to be safe, force it to a valid range.
            if ord(c)<32 or ord(c)>128 or c == '"':
                raise ValueError('Invalid character in string. Only ascii between 32 and 127 are accepted (excluding ")')
        return '"'+input_str+'"'

class dotted_quad(object):
    """ Accepts a string in the correct format, or a list of integers. Returns a string """
    def __call__(self, read_str):
        return read_str
    def tostr(self, input_str):
        if isinstance(input_str, basestring):
            m = re.match(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$', input_str)
            if m is None:
                raise ValueError('Invalid string. Needs to be in 000.000.000.000 format.')
            input_str = [int(i) for i in m.groups()]
        if len(input_str) != 4:
            raise ValueError('Invalid format. Requires 4 integers.')
        for d in input_str:
            if d >255 or d<0:
                raise ValueError('Invalid Integer. Needs to be in range 0-255')
        return '.'.join('%d'%d for d in input_str)


# without these, 1e-12 can be read as 1 by lakeshore
# However since for anything above 1e-4 repr does not use exponent formulation
# it will still work correclty most of the time with just float.

float_fix1 = float_as_fixed('%.1f')
float_fix3 = float_as_fixed('%.3f')
float_fix4 = float_as_fixed('%.4f')
float_fix6 = float_as_fixed('%.6f')

#######################################################
##    Lakeshore 325 Temperature controller
#######################################################

#@register_instrument('LSCI', 'MODEL325', '1.7/1.1')
@register_instrument('LSCI', 'MODEL325')
class lakeshore_325(visaInstrument):
    """
       Temperature controller
       Useful device:
           sa
           sb
           ta
           tb
           status_a
           status_b
           fetch
       s? and t? return the sensor or kelvin value of a certain channel
       status_? returns the status of the channel
       fetch allows to read all channels
    """
    def _fetch_helper(self, ch=None):
        if ch is None:
            ch = self.enabled_list.getcache()
        if not isinstance(ch, (list, ChoiceBase)):
            ch = [ch]
        return ch
    def _fetch_getformat(self, **kwarg):
        ch = kwarg.get('ch', None)
        ch = self._fetch_helper(ch)
        multi = []
        graph = []
        for i, c in enumerate(ch):
            graph.append(2*i)
            multi.extend([c+'_T', c+'_S'])
        fmt = self.fetch._format
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_getdev(self, ch=None):
        """
        reads thermometers temperature and their sensor values.
        option ch: can be a single channel or a list of channels.
                   by default (None), all active channels are used
                   possible channels names are:
                       A, B
        """
        ch = self._fetch_helper(ch)
        ret = []
        for c in ch:
            if c == 'A':
                ret.append(self.ta.get())
                ret.append(self.sa.get())
            elif c == 'B':
                ret.append(self.tb.get())
                ret.append(self.sb.get())
            else:
                raise ValueError("Invalid selection for ch. If it is None, check that enabled_list is a list with 'A' and/or 'B'")
        return ret
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('sp', options)
    def _create_devs(self):
        self.crdg = scpiDevice(getstr='CRDG? A', str_type=float)
        self.enabled_list = MemoryDevice(['A', 'B'])
        self.thermocouple = scpiDevice(getstr='TEMP?', str_type=float)
        self.ta = scpiDevice(getstr='KRDG? A', str_type=float) #in Kelvin
        self.tb = scpiDevice(getstr='KRDG? B', str_type=float) #in Kelvin
        self.sa = scpiDevice(getstr='SRDG? A', str_type=float) #in sensor unit: Ohm, V or mV
        self.sb = scpiDevice(getstr='SRDG? B', str_type=float) #in sensor unit
        self.status_a = scpiDevice(getstr='RDGST? A', str_type=int, doc="""\
                         flags:
                               0      = valid
                               1  (0) = invalid
                               16 (4) = temp underrange
                               32 (5) = temp overrange
                               64 (6) = sensor under (<0)
                               128(7) = sensor overrange
                        """)
        self.status_b = scpiDevice(getstr='RDGST? b', str_type=int, doc="""\
                         flags:
                               0      = valid
                               1  (0) = invalid
                               16 (4) = temp underrange
                               32 (5) = temp overrange
                               64 (6) = sensor under (<0)
                               128(7) = sensor overrange
                        """)
        self.htr = scpiDevice(getstr='HTR?', str_type=float) #heater out in %
        self.sp = scpiDevice(setstr='SETP 1,', getstr='SETP? 1', str_type=float)
        self._devwrap('fetch', autoinit=False)
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

#######################################################
##    Lakeshore 336 Temperature controller
#######################################################

#TODO:       handle set/get timeing.

# Curve entry details.
# - Entries need to be in ascending sensor and be 200 items long or have a 0, 0 entry to finish
# - the entries are not reordered on remote only on the front panel.
# - A curve can be written/read past the 0,0 value but it is not used.
# - Bad entries (not increasing or past 0,0) do not produce errors.
# - Values way out of range are stripped (111.1V on diode is like 11.1V)
# - When changing item 1 or 2, the coefficient (header) is set to positive or negative
#    depending on the temp values of the first 2 points. It can be overriden later with header.

# For ouput configuration
#  analog configures the monitor output mode (and the polarity for closed/zone for 3,4)
#  htrset configure output 1,2
#  outmode configures the control mode for output 1-4
#  warmup configures the warmup output mode
#  changing input_ch in either analog or outmode changes the other one.

# Note that PID, manual, zone should work for all 4 output channels (manual is wrong).
# Zones pid, and other settings are used only when the setpoint changes which upper is being used.
#  once the change is done, parameters like PIDs can be changed and they are not overriden until
#  the setpoint crosses another upper limit. Changing the parameters directly does not update the zone parameters.

#t=t1
#t._read_write_wait, t._write_write_wait = (.05, .05)
#write_wait=0
#while True:
#    t.curve_delete(31, password=t._passwd_check)
#    wait(0)
#    vals = arange(1, 200)
#    t.get_error()
#    rr=[t.curve_data_point.set(ch=31, i=i, sensor=i/100., temp=i/10., password=t._passwd_check) for i in vals]
#    wait(write_wait)
#    hdr, v = t.curve_get(31)
#    wait(.1)
#    err =  t.get_error()
#    wait(.1)
#    i=v.shape[1]+1
#    print all(v == vals/array([[100.],[10]])), err, v.shape, i, t.curve_data_point.get(ch=31, i=i)
#t.curve_delete(31, password=t._passwd_check)

# For serial read_write, write_write of 0., 0.07 seems to work fine.
#   0.05, 0.05 does not work: False Command Error. (2L, 141L) 142 dict_improved(sensor=0.0, temp=0.0)
#   with opc, 0,0 it does not produce errors.
# For gpib 0,0 does not produce errors, even for 0,0
# for tcpip, no errors for noopc, 0,0 with a write_wait of 20s. And no error with opc and 0,0 and write_wait=0.

# reading speed:
#   %time v=[get(t3.t) for i in range(100)]
#   %time v=[t3.ask('krdg? a') for i in range(100)]
#   %time v=[t3.ask('*opc?') for i in range(100)]
# for gpib is 6 ms/read, 100 ms/read for *opc?
# for tcpip is 20 ms/read (*opc is 19)
# for serial it is 6.6ms (krdg is 5.7), 4 ms/read for *opc?
#      however, if loaded with option no_visa_lock=True, both get t and krdg ask take 5.7 ms

# writing speed
# write_test = lambda dev, n: ([dev.write('setp 1,%.2f'%(100+i)) for i in range(n)], dev.ask('*opc?'))
# write_test_noopc = lambda dev, n: ([dev.write('setp 1,%.2f'%(100+i)) for i in range(n)],)
# %time v=write_test(t3, 100)
# for gpib is ~ 3 ms/sample (but varies a lot depending on the 100 and non-monotonically). wait_times set to 0,0
# for tcpip, with noopc I get 6 ms/write (wait time to 0,0), with opc I get 110 ms/write
# for usb, both give about 50ms/write (wait time to 0,0)

# write read test
#def wr_test(n, dev, delay=0., usesetget=False):
#    for i in range(n):
#        v = 200.+i
#        if usesetget:
#           set(dev.setpoint, v, outch=1)
#        else:
#           dev.write('setp 1,%.3f'%v)
#        wait(delay)
#        if usesetget:
#           rd = get(dev.setpoint)
#        else:
#           rd = float(dev.ask('setp? 1'))
#        iseq = '==' if rd == v else '!='
#        print '%.3f %s %.3f'%(v, iseq, rd)
# All tcpip, gpib, usb return lots of != here
# To prevent errors I needed a delay of 85 ms for gpib, 65 ms for tcpip, 80 ms for usb
#   this was using the opc mode for tcpip, serial.

# This device will add at least 100 ms to setget operations to make sure to read back
# an updated value.
scpiDevice_lk = lambda *args, **kwargs: scpiDevice(*args, setget_delay=0.1, **kwargs)

#@register_instrument('LSCI', 'MODEL336', '2.9')
@register_instrument('LSCI', 'MODEL336')
class lakeshore_336(visaInstrument):
    """
       Lakeshore 336 Temperature controller
       Useful device:
           s
           t
           fetch
           status_ch
           current_ch
       s and t return the sensor or kelvin value of a certain channel
       which defaults to current_ch
       status_ch returns the status of ch
       fetch allows to read all active channels

       When using the ethernet adapater, the port is 7777 so the visa address
       will look like:
           tcpip::lsci-336.mshome.net::7777::socket
    """
    _passwd_check = "IknowWhatIamDoing"
    def __init__(self, visa_addr, *args, **kwargs):
        """
        option write_with_opc can have value, True, False, or 'auto' which enables it
          for tcpip and usb connection.
        """
        self._write_with_opc = kwargs.pop('write_with_opc', 'auto')
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == visa_wrap.constants.InterfaceType.asrl:
            baud_rate = kwargs.pop('baud_rate', 57600)
            parity = kwargs.pop('parity', visa_wrap.constants.Parity.odd)
            data_bits = kwargs.pop('data_bits', 7)
            stop_bits = kwargs.pop('stop_bits', visa_wrap.constants.StopBits.one)
            kwargs['baud_rate'] = baud_rate
            kwargs['parity'] = parity
            kwargs['data_bits'] = data_bits
            kwargs['stop_bits'] = stop_bits
            if self._write_with_opc == 'auto':
                self._write_with_opc = True
        elif  rsrc_info.interface_type == visa_wrap.constants.InterfaceType.tcpip:
            term = kwargs.pop('read_termination', '\r\n')
            kwargs['read_termination'] = term
            if self._write_with_opc == 'auto':
                self._write_with_opc = True
        if self._write_with_opc == 'auto':
            self._write_with_opc = False
        # see also the begining of _create_devs for write timings.
        super(lakeshore_336, self).__init__(visa_addr, *args, **kwargs)
    @locked_calling
    def write(self, val, termination='default', opc=None):
        if opc is None:
            opc = self._write_with_opc
        if opc and '?' not in val:
            # This will speed up pure write on tcpip connection (which adds a 100 ms delay)
            # write-read sequence only add a 20 ms delay.
            val = val+';*opc?'
            self.ask(val)
        else:
            super(lakeshore_336, self).write(val, termination=termination)
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        old_ch = self.current_ch.getcache()
        old_crv = self.current_crv.getcache()
        ch = self.enabled_list.getcache()
        ch_list = []
        in_name = []
        in_crv = []
        in_crv_hdr = []
        in_type = []
        in_diode_current = []
        in_filter = []
        in_tlimit = []
        in_t = []
        for c in ch:
            ch_list.append(c)
            in_type.append(self.input_type.get(ch=c))
            crv_i = self.input_crv.get()
            in_crv.append(crv_i)
            in_crv_hdr.append(self.curve_hdr.get(ch=crv_i))
            in_t.append(self.t.get())
            in_name.append(self.input_name.get())
            in_diode_current.append(self.input_diode_current.get())
            in_filter.append(self.input_filter.get())
            in_tlimit.append(self.temperature_limit.get())
        self.current_ch.set(old_ch)
        self.current_crv.set(old_crv)
        base_input = ['current_ch=%r'%ch_list, 'input_name=%r'%in_name, 't=%r'%in_t, 'input_type=%r'%in_type,
                      'input_crv=%r'%in_crv, 'curve_hdr=%r'%in_crv_hdr, 'input_filter=%r'%in_filter,
                      'temperature_limit=%r'%in_tlimit]
        old_ch = self.current_output.get()
        out_confs = []
        out_pid = []
        out_setpoint = []
        out_manual = []
        out_range = []
        for i in range(1, 5):
            cnf = self.conf_output(i)
            out_confs.append(cnf)
            if cnf.mode in ['closed loop PID', 'zone', 'open loop']:
                out_manual.append(self.output_manual_pct.get())
            else:
                out_manual.append(None)
            if cnf.mode in ['closed loop PID', 'zone']:
                out_pid.append(self.pid.get())
                out_setpoint.append(self.setpoint.get())
            else:
                out_pid.append(None)
                out_setpoint.append(None)
            out_range.append(self.output_range.get())
        self.current_output.set(old_ch)
        base_output = ['output_conf=%r'%out_confs, 'pid=%r'%out_pid, 'setpoint=%r'%out_setpoint,
                       'output_manual_pct=%r'%out_manual, 'output_range=%r'%out_range]
        base = base_input + base_output + self._conf_helper(options)
        return base
    def _enabled_list_getdev(self):
        old_ch = self.current_ch.getcache()
        ret = []
        for c in self.current_ch.choices:
            d = self.input_type.get(ch=c)
            if d['type'] != 'disabled':
                ret.append(c)
        self.current_ch.set(old_ch)
        return ret
    def get_oper_status(self, latched=True):
        if latched:
            op = int(self.ask('OPSTR?'))
        else:
            op = int(self.ask('OPST?'))
        st = lambda bit: bool(op&(1<<bit))
        ret = dict(processor_com_err = st(7),
                   calibration_err = st(6),
                   autotune_done = st(5),
                   new_sensor_rdg = st(4),
                   loop1_ramp_done = st(3),
                   loop2_ramp_done = st(2),
                   sensor_overload = st(1),
                   alarming = st(0))
        return ret
    def _get_esr(self):
        return int(self.ask('*esr?'))
    def get_error(self):
        ret = []
        esr = self._get_esr()
        if esr&0x80:
            ret.append('Power on.')
        if esr&0x20:
            ret.append('Command Error.')
        if esr&0x10:
            ret.append('Execution Error.')
        if esr&0x04:
            ret.append('Query Error (output queue full).')
        if esr&0x01:
            ret.append('OPC received.')
        if len(ret) == 0:
            ret = 'No Error.'
        else:
            ret = ' '.join(ret)
        return ret
    def _fetch_helper(self, ch=None):
        if ch is None:
            ch = self.enabled_list.getcache()
        if not isinstance(ch, (list, ChoiceBase)):
            ch = [ch]
        return ch
    def _fetch_getformat(self, **kwarg):
        ch = kwarg.get('ch', None)
        ch = self._fetch_helper(ch)
        multi = []
        graph = []
        old_ch = self.current_ch.getcache()
        for i, c in enumerate(ch):
            name = self.input_name.get(ch=c)
            name = name.strip().replace(' ', '_')
            extra = ''
            if name != '':
                extra = '_'+name
            graph.append(2*i)
            multi.extend([c+extra+'_T', c+extra+'_S'])
        self.current_ch.set(old_ch)
        fmt = self.fetch._format
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_getdev(self, ch=None):
        """
        reads thermometers temperature and their sensor values.
        option ch: can be a single channel or a list of channels.
                   by default (None), all active channels are used
                   possible channels names are:
                       A, B, C, D
        """
        ch = self._fetch_helper(ch)
        ret = []
        all_ts = self.ask('KRDG? 0; SRDG? 0')
        ts,ss = all_ts.split(';')
        ts = [float(v) for v in ts.split(',')]
        ss = [float(v) for v in ss.split(',')]
        ch_ind = dict(A=0, B=1, C=2, D=3)
        for c in ch:
            i = ch_ind[c.upper()]
            ret.append(ts[i])
            ret.append(ss[i])
        return ret
    def alarm_reset(self):
        """ Clears both high and low alarms of all channels """
        self.write('ALMRST')
    def minmax_reset(self):
        """ Clears min/max for all inputs """
        self.write('MNMXRST')
    def output_do_autotune(self, ch, mode):
        """ Starts autotuning a control loop. The output ch needs to be specified.
            mode is one of: 'P', 'PI', 'PID'
            Read the status of autotuning with output_tune_status"""
        mode_opt = dict(p=0, pi=1, pid=2)
        if ch not in self.current_output.choices:
            raise ValueError('Invalid output channel selection')
        mode = mode.lower()
        if mode not in mode_opt:
            raise ValueError("Invalid mode. Should be one of: 'P', 'PI', 'PID'.")
        self.write('ATUNE %i,%i'%(ch, mode_opt[mode]))
    def _check_empty_curve(self, curve):
        pt = self.curve_data_point.get(ch=curve, i=1)
        if pt.sensor == pt.temp == 0.:
            return True
        return False
    def _check_password(self, password, dev=None):
        if dev is not None:
            password = dev._check_cache['kwarg']['password']
        if password != self._passwd_check:
            raise ValueError('Invalid password.')
    @locked_calling
    def do_softcal(self, target_curve, standard, serial_no, t1, s1, t2, s2, t3, s3, password=None):
        """\
        Generates a soft cal using t1, t2, t3 temperatures in K with sensor values s1, s2, s3.
        target_curve should be empty unless force is True.
        standard is one of 'diode', 'pt100', 'pt1000'
         diode is for model 421, 470, 471
        If the curve is not empty, you need to specify the password (same as for curve_delete)
        otherwise it will not work.
        diodes requires points around 4.2, 77 and 305 K (s1 can be anything (suggest 1.6) for a 2 pt softcal valid above 30)
        pt requires points around 77, 305 and 480 K (for 2pt softcal, extrapolate s3)
        """
        if target_curve<21 or target_curve>59:
            raise ValueError("target_curve invalid. It needs to be in the 21-59 range.")
        if standard not in ['diode', 'pt100', 'pt1000']:
            raise ValueError("Invalid standard. It should be one of: 'diode', 'pt100', 'pt1000'")
        standard = dict(diode=1, pt100=6, pt1000=7)[standard]
        conv = quoted_name(10)
        serial_no = conv.tostr(serial_no)
        if not self._check_empty_curve(target_curve):
            print('Curve is already present! Erasing if password is correct.')
            self._check_password(password)
            # no need for delete.
            #self.curve_delete(target_curve, password=password)
        self.write('SCAL %i,%i,%s,%.3f,%.6f,%.3f,%.6f,%.3f,%.6f'%(standard, target_curve, serial_no, t1, s1, t2, s2, t3, s3))
        # This softcal operation seems to take 150 ms (on gpib, usb) using *opc?
    def _output_pct_getdev(self, ch=None):
        """ The output power in percent """
        if ch is not None:
            self.current_output.set(ch)
        ch = self.current_output.getcache()
        if ch <= 2:
            return float(self.ask('HTR? %i'%ch))
        else:
            return float(self.ask('AOUT? %i'%ch))
    @locked_calling
    def curve_get(self, curve):
        """ Returns the curve header, following with the data as an 2xn array with 2 being sensors, temp """
        hdr = self.curve_hdr.get(ch=curve)
        data = []
        for i in range(1, 201):
            d = self.curve_data_point.get(i=i)
            if d.temp == d.sensor == 0:
                break
            data.append([d.sensor, d.temp])
        return hdr, np.array(data).T
    @locked_calling
    def curve_set(self, target_curve, name, serial_no, format, sensors, temps, sp_limit_K=None, password=None):
        """ if targt_curve already exists, you need to enter the proper password (see curve_delete).
            target_curve is the curve to change (21-59)
            name is a 15 character string for the calibration name
            serial_no is a 10 character string for the calibration serial number
            format is one of: 'mv/K', 'V/K', 'Ohm/K', 'log Ohm/K'
            sp_limit_K if not given will be the highest value in temps.
            sensors and temps are the calibration data (sensors needs to be increasing, and there needs to be
            at most 200 points)
        """
        # coefficient will be set with the data automatically.
        if target_curve<21 or target_curve>59:
            raise ValueError("target_curve invalid. It needs to be in the 21-59 range.")
        Nsensors, Ntemps = len(sensors), len(temps)
        if Nsensors != Ntemps:
            raise ValueError('sensors and temps vectors are not the same length.')
        if Nsensors < 2:
            raise ValueError('Not enough data points')
        if Nsensors > 200:
            raise ValueError('too many data points')
        if list(sensors) != sorted(sensors):
            raise ValueError('sensors are not in ascending order.')
        if sp_limit_K is None:
            sp_limit_K = max(temps)
        if not self._check_empty_curve(target_curve):
            print('Curve is already present! Erasing if password is correct.')
            self._check_password(password)
            #self.curve_delete(target_curve, password=password)
        # Curve is either not present or we just checked the proper password, so we no longer need to check for passwords.
        self.curve_hdr.set(ch=target_curve, name=name, serial_no=serial_no, format=format, sp_limit_K=sp_limit_K, password=self._passwd_check)
        for i, (s,t) in enumerate(zip(sensors, temps)):
            self.curve_data_point.set(ch=target_curve, i=i+1, sensor=s, temp=t, password=self._passwd_check)
        if i != 199:
            # since we did not erase the full curve, we need to right the end curve entry
            self.curve_data_point.set(ch=target_curve, i=i+2, sensor=0, temp=0, password=self._passwd_check)

    def curve_delete(self, curve, password=None):
        self._check_password(password)
        if 21 <= curve <= 59:
            self.ask('crvdel %i;*opc?'%curve)
            # seems to take about 120 ms.
        else:
            raise ValueError('Invalid curve number. Needs to be in the 21-59 range.')
    curve_delete.__doc__ = """ will clear one of the curve (21-59). For it to work you need to enter the password: "%s" """%_passwd_check

    @locked_calling
    def conf_zone(self, out_ch, uppers=None, Ps=None, Is=None, Ds=None, manuals=None, ranges=None, inputs=None, rates=None):
        """ when uppers is None, show the zone settings for out_ch.
            Otherwise all the paramters are lists (or arrays) and need to be of the same length <=10.
            uppers are the <= criteria for selecting the other parameters from the setpoint value.
            The last entry applies even for setpoints above uppers (uppers is not used for the last entry.)
        """
        if uppers is None:
            data = dict_improved([('uppers', []), ('Ps', []), ('Is', []), ('Ds', []), ('manuals', []), ('ranges', []), ('inputs', []), ('rates', [])])
            for z in range(10):
                ret = self.output_zone.get(outch=out_ch, zone=z+1)
                if ret.upper == 0:
                    break
                for k in ret:
                    data[k+'s'].append(ret[k])
            return data
        else:
            if len(uppers) != len(Ps) != len(Is) != len(Ds) != len(manuals) != len(ranges) != len(inputs) != len(rates):
                raise ValueError('One of the data is not of the same length as the others')
            if len(uppers) > 10:
                raise ValueError('You need less than 10 data')
            if list(uppers) != sorted(uppers):
                raise ValueError('uppers are not in ascending order.')
            z=-1
            for z, (u, P, I, D, m, r, i, ra) in enumerate(zip(uppers, Ps, Is, Ds, manuals, ranges, inputs, rates)):
                self.output_zone.set(outch=out_ch, zone=z+1, upper=u, P=P, I=I, D=D, manual=m, range=r, input=i, rate=ra)
            if z < 9:
                self.output_zone.set(outch=out_ch, zone=z+2, upper=0, P=50, I=20, D=0, manual=0, range='off', input='none', rate=0)

    @locked_calling
    def conf_output(self, out_ch, mode=None, input_ch=None, powerup_en=None, control=None, percentage=None, units=None, high=None, low=None, bipolar_en=None, ramp_rate=None, ramp_en=None,
                    resistance=None, max_current=None, max_user=None, display_unit=None):
        """
        Configure out_ch
        if mode is None, returns the settings of the out_ch, otherwise
          mode is one of 'off', 'closed loop PID', 'zone', 'open loop', 'monitor out', 'warmup supply'
          monitor out and warmup supply only for out_ch 3 or 4.
        For all modes except 'off', provide input_ch.
        For all modes except 'off', 'monitor out', provide powerup_en.
        if mode is 'warmup supply', also supply control('auto off', 'continuous'), percentage
        if mode is 'monitor out', also supply units('Kelvin', 'Celsius', 'Sensor'), high, low, bipolar_en
        if mode is 'closed loop PID', 'zone', provide, ramp_rate, ramp_en
        if mode is 'closed loop PID', 'zone', 'open loop'
                and out_ch=1,2, also provide resistance, max_current or max_user, display_unit
                and out_ch=3,4, then provide bipolar_en
        """
        if mode is None:
            main = self.output_mode.get(outch=out_ch)
            mode = main.mode
            main = dict(main)
            if mode == 'off':
                main = dict(mode=mode)
            elif mode == 'warmup supply':
                ret = self.output_warmup.get(outch=out_ch)
                main.update(ret)
            elif mode == 'monitor out':
                ret = self.output_analog.get(outch=out_ch)
                main.update(ret)
                main.pop('powerup_en')
            else:
                if mode in ['closed loop PID', 'zone']:
                    ret = self.ramp_control.get(outch=out_ch)
                    main['ramp_rate'] = ret.rate
                    main['ramp_en'] = ret.en
                if out_ch in [1, 2]:
                    ret = self.output_htr_set.get(outch=out_ch)
                    main.update(ret)
                else:
                    ret = self.output_analog.get(outch=out_ch)
                    main['bipolar_en'] = ret.bipolar_en
            return dict_improved(sorted(main.items()))
        elif mode == 'off':
            self.output_mode.set(outch=out_ch, mode=mode)
        else:
            if mode != 'monitor_out':
                if powerup_en is None:
                    raise ValueError('You need to specify powerup_en')
                self.output_mode.set(outch=out_ch, mode=mode, input_ch=input_ch, powerup_en=powerup_en)
            else:
                self.output_mode.set(outch=out_ch, mode=mode, input_ch=input_ch)
            if mode == 'warmup supply':
                self.output_warmup.set(outch=out_ch, control=control, percentage=percentage)
            elif mode == 'monitor out':
                if bipolar_en is None:
                    raise ValueError('You need to specify bipolar_en')
                self.output_analog.set(outch=out_ch, input_ch=input_ch, units=units, high=high, low=low, bipolar_en=bipolar_en)
            else:
                if mode in ['closed loop PID', 'zone']:
                    if ramp_en is None:
                        raise ValueError('You need to specify ramp_en')
                    self.ramp_control.set(outch=out_ch, en=ramp_en, rate=ramp_rate)
                if out_ch in [1, 2]:
                    if max_user is not None:
                        max_current = 0
                    else:
                        max_user = max_current
                    self.output_htr_set.set(outch=out_ch, resistance=resistance, max_current=max_current, max_user=max_user, display_unit=display_unit)
                else:
                    if bipolar_en is None:
                        raise ValueError('You need to specify bipolar_en')
                    self.output_analog.set(outch=out_ch, input_ch=input_ch, bipolar_en=bipolar_en)

    def _create_devs(self):
        if self.visa.is_serial():
            if not self._write_with_opc:
                # we need to set this before any writes.
                # otherwise some write request are lost.
                self._write_write_wait = 0.075
        elif self.visa.is_tcpip():
            # The socket connections seems to buffer all requests, so unlike
            # for serial there are no loss, however, the socket handler in the instrument
            # seems to be delaying all writes byt 110 ms.
            # so to not get too far ahead in pyHegel lets match the delay, unless we use opc.
            if not self._write_with_opc:
                self._write_write_wait = 0.105
        else: #GPIB
            self._write_write_wait = 0.0
        #TODO: handle 3062 option card (adds channels D1 - D5)
        #ch_Base = ChoiceStrings('A', 'B', 'C', 'D', 'D2', 'D3', 'D4', 'D5')
        #ch_Base = ChoiceStrings('A', 'B', 'C', 'D1', 'D2', 'D3', 'D4', 'D5')
        ch_Base = ChoiceStrings('A', 'B', 'C', 'D')
        #ch_sel = ChoiceIndex('none', 'A', 'B', 'C', 'D', 'D2', 'D3', 'D4', 'D5')
        ch_sel = ChoiceIndex(['none', 'A', 'B', 'C', 'D'])
        self.current_ch = MemoryDevice('A', choices=ch_Base)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice_lk(*arg, **kwarg)
        self.t = devChOption(getstr='KRDG? {ch}', str_type=float, doc='Return the temperature in Kelvin for the selected sensor(ch)')
        self.s = devChOption(getstr='SRDG? {ch}', str_type=float, doc='Return the sensor value in Ohm, V(diode), mV (thermocouple), nF (for capacitance)  for the selected sensor(ch)')
        self.thermocouple_block_temp = scpiDevice(getstr='TEMP?', str_type=float)
        self.status_ch = devChOption(getstr='RDGST? {ch}', str_type=int, doc="""\
                         flags:
                               0      = valid
                               1  (0) = invalid
                               16 (4) = temp underrange
                               32 (5) = temp overrange
                               64 (6) = sensor under (<0)
                               128(7) = sensor overrange
                        """)
        self.alarm_conf = devChOption('ALARM {ch},{val}', 'ALARM? {ch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                      choices=ChoiceMultiple(['enabled', 'high_setpoint', 'low_setpoint', 'deadband', 'latch_en', 'audible', 'visible'],
                                                             [bool, float, float_fix6, float_fix6, bool, bool, bool]))
        self.alarm_status = devChOption(getstr='ALARMST? {ch}', choices=ChoiceMultiple(['high', 'low'], [bool, bool]))
        intypes = ChoiceIndex(['disabled', 'diode', 'PTC_RTD', 'NTC_RTD', 'thermocouple', 'capacitance'])
        units = ChoiceIndex({1:'Kelvin', 2:'Celsius', 3:'Sensor'})
        ranges_disabled = ChoiceIndex({0:0})
        ranges_diode = ChoiceIndex({0:2.5, 1:10}) # V
        ranges_PTC = ChoiceIndex(make_choice_list([1, 3], 1, 4)[:-1], normalize=True) # Ohm
        ranges_NTC = ChoiceIndex(make_choice_list([1, 3], 1, 5)[:-1], normalize=True) # Ohm
        type_ranges = ChoiceMultipleDep('type', {'disabled':ranges_disabled, 'diode':ranges_diode, 'PTC_RTD':ranges_PTC, 'NTC_RTD':ranges_NTC})
        self.input_type = devChOption('INTYPE {ch},{val}', 'INTYPE? {ch}',
                                      allow_kw_as_dict=True, allow_missing_dict=True,
                                      choices=ChoiceMultiple(['type', 'autorange_en', 'range', 'compensation_en', 'units'], [intypes, bool, type_ranges, bool, units]))
        self.input_filter = devChOption('FILTER {ch},{val}', 'FILTER? {ch}',
                                      allow_kw_as_dict=True, allow_missing_dict=True,
                                      choices=ChoiceMultiple(['filter_en', 'n_points', 'window'], [bool, (int, (2, 64)), (int, (1,10))]),
                                      doc="""\
                                      This is an exponential filter with time constant T*ln(N/(N-1))
                                      where T is the sampling time (0.1 s) and N is the filter n_points
                                      npoints=8 --> time constant = 0.75 s, equivalent bandwidth = 0.335 Hz
                                      """)
        # The filter is T_i = (1/N)t_i + (1-(1/N))T_(i-1),  where T is the filtered temperature, t is the unfiltered temperature
        self.input_diode_current = devChOption('DIOCUR {ch},{val}', 'DIOCUR? {ch}', choices=ChoiceIndex({0:10e-6, 1:1e-3}), doc=
                """Only valid when input is a diode type. Options are in Amps.
                   Default of instrument is 10 uA (used after every change of sensor type).""")
        self.input_name = devChOption('INNAME {ch},{val}', 'INNAME? {ch}', str_type=quoted_name(15))

        self.input_crv = devChOption('INCRV {ch},{val}', 'INCRV? {ch}', str_type=int)
        self.input_filter = devChOption('FILTER {ch},{val}', 'FILTER? {ch}',
                                      choices=ChoiceMultiple(['filter_en', 'n_points', 'window'], [bool, int, int]))
        self.temperature_limit = devChOption('TLIMIT {ch},{val}', 'TLIMIT? {ch}', str_type=float_fix3)
        self.minmax = devChOption(getstr='MDAT? {ch}', str_type=decode_float64, multi=['min', 'max'])
        self.current_output = MemoryDevice(1, choices=[1, 2, 3, 4])
        def devOutOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(outch=self.current_output)
            app = kwarg.pop('options_apply', ['outch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice_lk(*arg, **kwarg)
        pid_ch = ChoiceMultiple(['P', 'I', 'D'], [(float_fix1, (0.1, 1000)), (float_fix1,(0, 1000)), (float_fix1, (0, 200))])
        self.pid = devOutOption('PID {outch},{val}', 'PID? {outch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                choices=pid_ch, multi=pid_ch.field_names, setget=True,
                                doc="You can use as set(tc.pid, P=21). I is reset rate in mHz. Set I to 0 to turn it off.")
        self.pid_P = Dict_SubDevice(self.pid, 'P', force_default=False)
        self.pid_I = Dict_SubDevice(self.pid, 'I', force_default=False)
        self.pid_D = Dict_SubDevice(self.pid, 'D', force_default=False)
        self.output_manual_pct = devOutOption('MOUT {outch},{val}', 'MOUT? {outch}', str_type=float_fix3, setget=True)
        Hrange = ChoiceIndex(['off', 'low', 'medium', 'high'])
        Hrange2 = ChoiceIndex(['off', 'on'])
        out_choice = ChoiceDevDep(self.current_output, {(1,2): Hrange, (3,4):Hrange2})
        self.output_range = devOutOption('RANGE {outch},{val}', 'RANGE? {outch}',
                                       choices=out_choice)
        self.setpoint = devOutOption(setstr='SETP {outch},{val}', getstr='SETP? {outch}', str_type=float_fix3, setget=True)
        self.ramp_control = devOutOption('RAMP {outch},{val}', 'RAMP? {outch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                       choices=ChoiceMultiple(['en', 'rate'], [bool, (float_fix3,(0.0, 100))]), doc="Activates the sweep mode. rate is in K/min.", setget=True)
        self.ramp_sweeping_status = devOutOption(getstr='RAMPST? {outch}', str_type=bool)
        self.output_tune_status = scpiDevice(getstr='TUNEST?', choices=ChoiceMultiple(['active_tuning', 'outch', 'in_error', 'stage'], [bool, int, bool, int]))
        self.output_mode = devOutOption('OUTMODE {outch},{val}', 'OUTMODE? {outch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                           choices=ChoiceMultiple(['mode', 'input_ch', 'powerup_en'], [
                                               ChoiceIndex(['off', 'closed loop PID', 'zone', 'open loop', 'monitor out', 'warmup supply']), ch_sel, bool]))
        self.output_htr_set = devOutOption('HTRSET {outch},{val}', 'HTRSET? {outch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                           choices=ChoiceMultiple(['resistance', 'max_current', 'max_user', 'display_unit'], [
                                               ChoiceIndex([25, 50], offset=1), ChoiceIndex([0, 0.707, 1, 1.414, 2]), float_fix3, ChoiceIndex(['current', 'power'], offset=1)]),
                                           options_lim=dict(outch=(1,2)), autoinit=False, doc='max_current set to 0 selects the max_user value')
        self.output_warmup = devOutOption('WARMUP {outch},{val}', 'WARMUP? {outch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                          choices=ChoiceMultiple(['control', 'percentage'], [ChoiceIndex(['auto off', 'continuous']), float_fix3]),
                                          options_lim=dict(outch=(3,4)), autoinit=False)
        self.output_analog = devOutOption('ANALOG {outch},{val}', 'ANALOG? {outch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                          choices=ChoiceMultiple(['input_ch', 'units', 'high', 'low', 'bipolar_en'],
                                                                 [ch_sel, units, float_fix3, float_fix3, bool]),
                                          options_lim=dict(outch=(3,4)), autoinit=False)
        self.current_zone = MemoryDevice(1, choices=list(range(1,11)))
        self.output_zone = devOutOption('ZONE {outch},{zone},{val}', 'ZONE? {outch},{zone}', allow_kw_as_dict=True, allow_missing_dict=True,
                                  options=dict(zone=self.current_zone), options_apply=['zone', 'outch'],
                                  choices=ChoiceMultiple(['upper', 'P', 'I', 'D', 'manual', 'range', 'input', 'rate'],
                                                         [float_fix3, (float_fix1, (0.1, 1000)), (float_fix1,(0, 1000)), (float_fix1, (0, 200)), (float_fix3, (0, 100)), out_choice, ch_sel, (float_fix3, (0., 100))]),
                                  doc="rate is in K/min. an input set as 'none' will use the previously assigned sensor. ", autoinit=False)
        self.current_relay = MemoryDevice(1, choices=[1, 2])
        def devRelayOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_relay)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice_lk(*arg, **kwarg)
        self.relay_control = devRelayOption('RELAY {ch},{val}', 'RELAY? {ch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                            choices=ChoiceMultiple(['mode', 'alarm_input_ch', 'alarm_type'],
                                                                   [ChoiceIndex(['off', 'on', 'alarm']), ch_Base, ChoiceIndex(['low', 'high', 'both'])]))
        self.relay_status = devRelayOption(getstr='RELAYST? {ch}', str_type=bool)

        self.display_brightness = scpiDevice_lk('BRIGT', str_type=int, min=1, max=32)
        self.display_leds_en = scpiDevice_lk('LEDS', str_type=bool)
        self.net_conf = scpiDevice_lk('NET', allow_kw_as_dict=True, allow_missing_dict=True,
                                   choices=ChoiceMultiple(['dhcp_en', 'autoip_en', 'static_ip', 'subnet_mask', 'gateway', 'primary_dns', 'secondary_dns', 'pref_hostname', 'pref_domain', 'description'],
                                                                 [bool, bool, dotted_quad(), dotted_quad(), dotted_quad(), dotted_quad(), dotted_quad(), quoted_name(15),quoted_name(64), quoted_name(32)]), autoinit=False)
        self.net_state = scpiDevice(getstr='NETID?', choices=ChoiceMultiple(['lan_status', 'ip_addr', 'subnet_mask', 'gateway', 'primary_dns', 'secondary_dns', 'actual_hostname', 'actual_domain', 'mac_address'],
                                                                            [int, str, str, str, str, str, str, quoted_name(15), quoted_name(32)]),
                                    doc="""\
                                    lan_status:
                                           0: connected using static ip
                                           1: connected using dhcp
                                           2: connected using autoip
                                           3: address not acquired error
                                           4: duplicate initial ip address error
                                           5: duplicate ongoing ip address error
                                           6: cable unplugged
                                           7: module error
                                           8: acquiring address
                                           9: ethernet disabled.""", autoinit=False)
        self.current_crv = MemoryDevice(1, choices=range(1, 60))
        self.curve_hdr = scpiDevice_lk('CRVHDR {ch},{val}', 'CRVHDR? {ch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                    options=dict(ch=self.current_crv, password=None), options_apply=['ch'],
                                    extra_check_func=ProxyMethod(self._check_password),
                                    choices=ChoiceMultiple(['name', 'serial_no', 'format', 'sp_limit_K', 'coefficient'],
                                                           [quoted_name(15), quoted_name(10), ChoiceIndex(['mv/K', 'V/K', 'Ohm/K', 'log Ohm/K'], offset=1), float_fix3, ChoiceIndex(['negative', 'positive'], offset=1)]),
                                                            doc='To perform a set you need to set password to "%s"\n'%self._passwd_check, autoinit=False)
        self.curve_data_point = scpiDevice_lk('CRVPT {ch},{i},{val}', 'CRVPT? {ch},{i}', allow_kw_as_dict=True, allow_missing_dict=True,
                                           extra_check_func=ProxyMethod(self._check_password),
                                           options=dict(ch=self.current_crv, i=1, password=None), options_lim=dict(i=(1,200)), options_apply=['ch'],
                                           doc='To perform a set you need to set password to "%s"\n'%self._passwd_check,
                                           choices=ChoiceMultiple(['sensor', 'temp'], [float_fix6, float_fix6]), autoinit=False)
        self._devwrap('enabled_list')
        self._devwrap('output_pct')
        self._devwrap('fetch', autoinit=False)
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


#######################################################
##    Lakeshore 340 Temperature controller
#######################################################

register_idn_alias('Lake Shore Cryotronics', 'LSCI')

#@register_instrument('LSCI', 'MODEL340', '061407')
@register_instrument('LSCI', 'MODEL340')
class lakeshore_340(visaInstrument):
    """
       Temperature controller used for He3 system
       Useful device:
           s
           t
           fetch
           status_ch
           current_ch
       s and t return the sensor or kelvin value of a certain channel
       which defaults to current_ch
       status_ch returns the status of ch
       fetch allows to read all channels
    """
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        if dev_obj == self.fetch:
            old_ch = self.current_ch.getcache()
            ch = options.get('ch', None)
            ch = self._fetch_helper(ch)
            ch_list = []
            in_set = []
            in_crv = []
            in_type = []
            for c in ch:
                ch_list.append(c)
                in_set.append(self.input_set.get(ch=c))
                in_crv.append(self.input_crv.get())
                in_type.append(self.input_type.get())
            self.current_ch.set(old_ch)
            base = ['current_ch=%r'%ch_list, 'input_set=%r'%in_set,
                    'input_crv=%r'%in_crv, 'input_type=%r'%in_type]
        else:
            base = self._conf_helper('current_ch', 'input_set', 'input_crv', 'input_type')
        base += self._conf_helper('current_loop', 'sp', 'pid', options)
        return base
    def _enabled_list_getdev(self):
        old_ch = self.current_ch.getcache()
        ret = []
        for c in self.current_ch.choices:
            d = self.input_set.get(ch=c)
            if d['enabled']:
                ret.append(c)
        self.current_ch.set(old_ch)
        return ret
    def _fetch_helper(self, ch=None):
        if ch is None:
            ch = self.enabled_list.getcache()
        if not isinstance(ch, (list, ChoiceBase)):
            ch = [ch]
        return ch
    def _fetch_getformat(self, **kwarg):
        ch = kwarg.get('ch', None)
        ch = self._fetch_helper(ch)
        multi = []
        graph = []
        for i, c in enumerate(ch):
            graph.append(2*i)
            multi.extend([c+'_T', c+'_S'])
        fmt = self.fetch._format
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_getdev(self, ch=None):
        """
        reads thermometers temperature and their sensor values.
        option ch: can be a single channel or a list of channels.
                   by default (None), all active channels are used
                   possible channels names are:
                       A, B, C, D, C1, C2, C3, C4, D1, D2, D3, D4
                   (depending on installed options)
        """
        old_ch = self.current_ch.getcache()
        ch = self._fetch_helper(ch)
        ret = []
        for c in ch:
            ret.append(self.t.get(ch=c))
            ret.append(self.s.get())
        self.current_ch.set(old_ch)
        return ret
    def _create_devs(self):
        rev_str = self.ask('rev?')
        conv = ChoiceMultiple(['master_rev_date', 'master_rev_num', 'master_serial_num', 'sw1', 'input_rev_date',
                         'input_rev_num', 'option_id', 'option_rev_date', 'option_rev_num'], fmts=str)
        rev_dic = conv(rev_str)
        ch_Base = ChoiceStrings('A', 'B')
        ch_3462_3464 = ChoiceStrings('A', 'B', 'C', 'D') # 3462=2 other channels, 3464=2 thermocouple
        ch_3468 = ChoiceStrings('A', 'B', 'C1', 'C2', 'C3', 'C4', 'D1', 'D2','D3','D4') # 2 groups of 4, limited rate, limited current sources (10u or 1m)
        ch_3465 = ChoiceStrings('A', 'B', 'C') # single capacitance
        ch_opt = {'3462':ch_3462_3464, '3464':ch_3462_3464, '3468':ch_3468, '3465':ch_3465}
        ch_opt_sel = ch_opt.get(rev_dic['option_id'], ch_Base)
        self.current_ch = MemoryDevice('A', choices=ch_opt_sel)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.t = devChOption(getstr='KRDG? {ch}', str_type=float, doc='Return the temperature in Kelvin for the selected sensor(ch)')
        self.s = devChOption(getstr='SRDG? {ch}', str_type=float, doc='Return the sensor value in Ohm, V(diode), mV (thermocouple), nF (for capacitance)  for the selected sensor(ch)')
        self.status_ch = devChOption(getstr='RDGST? {ch}', str_type=int, doc="""\
                         flags:
                               0      = valid
                               1  (0) = invalid
                               2  (1) = old reading
                               16 (4) = temp underrange
                               32 (5) = temp overrange
                               64 (6) = sensor under (<0)
                               128(7) = sensor overrange
                        """)
        self.input_set = devChOption('INSET {ch},{val}', 'INSET? {ch}', choices=ChoiceMultiple(['enabled', 'compens'],[bool, int]))
        self.input_crv = devChOption('INCRV {ch},{val}', 'INCRV? {ch}', str_type=int)
        self.input_type = devChOption('INTYPE {ch},{val}', 'INTYPE? {ch}',
                                      choices=ChoiceMultiple(['type', 'units', 'coeff', 'exc', 'range']))
        self.input_filter = devChOption('FILTER {ch},{val}', 'FILTER? {ch}',
                                      choices=ChoiceMultiple(['filter_en', 'n_points', 'window'], [bool, int, int]))
        self.current_loop = MemoryDevice(1, choices=[1, 2])
        def devLoopOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(loop=self.current_loop)
            app = kwarg.pop('options_apply', ['loop'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.pid = devLoopOption('PID {loop},{val}', 'PID? {loop}',
                                 choices=ChoiceMultiple(['P', 'I', 'D'], float))
        self.htr = scpiDevice(getstr='HTR?', str_type=float) #heater out in %
        self.sp = devLoopOption(setstr='SETP {loop},{val}', getstr='SETP? {loop}', str_type=float)
        self._devwrap('enabled_list')
        self._devwrap('fetch', autoinit=False)
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

#######################################################
##    Lakeshore 224 Temperature monitor
#######################################################
#@register_instrument('LSCI', 'MODEL224', '1.0')
@register_instrument('LSCI', 'MODEL224')
class lakeshore_224(lakeshore_340):
    """
       Temperature monitor
       Useful device:
           s
           t
           fetch
           status_ch
           current_ch
       s and t return the sensor or kelvin value of a certain channel
       which defaults to current_ch
       status_ch returns the status of ch
       fetch allows to read all channels (which is the alias)

       Note: The device USB is actually a serial to USB port. Therfore it
             shows on the computer as a serial connection (once the driver
             is installed, which could happen automatically.)
    """
    def init(self, full=False):
        if full:
            if self.visa.is_serial():
                self.visa.baud_rate = 57600
                self.visa.parity = visa_wrap.constants.Parity.odd
                self.visa.data_bits = 7
            if self.visa.is_serial():
                self._write_write_wait = 0.100
            else: # GPIB, LAN: This is unchecked but should be ok. Shorter time might be better...
                self._write_write_wait = 0.050
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        if dev_obj == self.fetch:
            old_ch = self.current_ch.getcache()
            ch = options.get('ch', None)
            ch = self._fetch_helper(ch)
            ch_list = []
            in_crv = []
            in_type = []
            in_diode = []
            for c in ch:
                ch_list.append(c)
                in_crv.append(self.input_crv.get(ch=c))
                in_type.append(self.input_type.get())
                in_diode.append(self.input_diode_current.get())
            self.current_ch.set(old_ch)
            base = ['current_ch=%r'%ch_list, 'input_crv=%r'%in_crv, 'input_type=%r'%in_type, 'input_diode_current=%r'%in_diode]
        else:
            base = self._conf_helper('current_ch', 'input_crv', 'input_type', 'input_diode_current')
        base += self._conf_helper(options)
        return base
    def _enabled_list_getdev(self):
        old_ch = self.current_ch.getcache()
        ret = []
        for c in self.current_ch.choices:
            d = self.input_type.get(ch=c)
            if d['type'] != 'disabled':
                ret.append(c)
        self.current_ch.set(old_ch)
        return ret
    def _get_esr(self):
        return int(self.ask('*esr?'))
    def get_error(self):
        esr = self._get_esr()
        ret = ''
        if esr&0x80:
            ret += 'Power on. '
        if esr&0x20:
            ret += 'Command Error. '
        if esr&0x10:
            ret += 'Execution Error. '
        if esr&0x04:
            ret += 'Query Error (output queue full). '
        if esr&0x01:
            ret += 'OPC received.'
        if ret == '':
            ret = 'No Error.'
        return ret
    def _create_devs(self):
        ch_opt_sel = ['A', 'B', 'C1', 'C2', 'C3', 'C4', 'C5', 'D1', 'D2', 'D3', 'D4', 'D5']
        self.current_ch = MemoryDevice('A', choices=ch_opt_sel)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.t = devChOption(getstr='KRDG? {ch}', str_type=float, doc='Return the temperature in Kelvin for the selected sensor(ch)')
        self.s = devChOption(getstr='SRDG? {ch}', str_type=float, doc='Return the sensor value in Ohm, V(diode), mV (thermocouple), nF (for capacitance)  for the selected sensor(ch)')
        self.status_ch = devChOption(getstr='RDGST? {ch}', str_type=int, doc="""\
                         flags:
                               0      = valid
                               1  (0) = invalid
                               16 (4) = temp underrange
                               32 (5) = temp overrange
                               64 (6) = sensor under (<0)
                               128(7) = sensor overrange
                        """)
        self.input_crv = devChOption('INCRV {ch},{val}', 'INCRV? {ch}', str_type=int)
        intypes = ChoiceIndex({0:'disabled', 1:'diode', 2:'PTC_RTD', 3:'NTC_RTD'})
        units = ChoiceIndex({1:'Kelvin', 2:'Celsius', 3:'Sensor'})
        ranges_disabled = ChoiceIndex({0:0})
        ranges_diode = ChoiceIndex({0:2.5, 1:10}) # V
        ranges_PTC = ChoiceIndex(make_choice_list([1, 3], 1, 4)[:-1], normalize=True) # Ohm
        ranges_NTC = ChoiceIndex(make_choice_list([1, 3], 1, 5)[:-1], normalize=True) # Ohm
        type_ranges = ChoiceMultipleDep('type', {'disabled':ranges_disabled, 'diode':ranges_diode, 'PTC_RTD':ranges_PTC, 'NTC_RTD':ranges_NTC})
        self.input_type = devChOption('INTYPE {ch},{val}', 'INTYPE? {ch}',
                                      allow_kw_as_dict=True, allow_missing_dict=True,
                                      choices=ChoiceMultiple(['type', 'autorange_en', 'range', 'compensation_en', 'units'], [intypes, bool, type_ranges, bool, units]))
        self.input_filter = devChOption('FILTER {ch},{val}', 'FILTER? {ch}',
                                      allow_kw_as_dict=True, allow_missing_dict=True,
                                      choices=ChoiceMultiple(['filter_en', 'n_points', 'window'], [bool, int, int]))
        self.input_diode_current = devChOption('DIOCUR {ch},{val}', 'DIOCUR? {ch}', choices=ChoiceIndex({0:10e-6, 1:1e-3}), doc=
                """Only valid when input is a diode type. Options are in Amps.
                   Default of instrument is 10 uA (used after every change of sensor type).""")
        self.input_name = devChOption('INNAME {ch},{val}', 'INNAME? {ch}', str_type=quoted_name())
        self._devwrap('enabled_list')
        self._devwrap('fetch', autoinit=False)
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(lakeshore_340, self)._create_devs()
    def disable_ch(self, ch):
        """
        This method set a channel to disabled.
        Note that the settings of the channel are lost. To reenable use
          input_type with at least options autorange_en (PTC, NTC), range (allways, any value is allowed if autorange is enabled)
                     compensation_en (PTC, NTC)
          input_crv
          input_diode_current (for diodes if want 1 mA)
        """
        self.input_type.set(ch=ch, type='disabled', range=0)

#######################################################
##    Lakeshore 370 Temperature controller
#######################################################

#@register_instrument('LSCI', 'MODEL370', '04102008')
@register_instrument('LSCI', 'MODEL370')
class lakeshore_370(visaInstrument):
    """
       Temperature controller used for dilu system
       Useful device:
           s
           t
           fetch
           status_ch
           current_ch
           pid
           still
           still_raw
       s and t return the sensor(Ohm) or kelvin value of a certain channel
       which defaults to current_ch
       status_ch returns the status of ch
       fetch allows to read all channels

       Notes about T control:
           - the htr values is either in W (assuming the resistance is correctly
           programmed) or % of current full scale. Therefore we have
           W = ((%/100)*Ifullscale)**2 * Rheater
           - The feedback formula is:
               Iheater = Imax * P * [e + I integral(e dt) + D de/dt]
               with e = 2*log10(Rmeas/Rsetpoint)
                 at least for sensors calibrated as log scale
           - Therefore increasing currrent scale by x3.16 (power by x10)
             would require decreasing P by x3.16
       Notes about timing:
           - takes 10 readings / s, has a 200 ms hardware input filter
           - the digital filter is a linear average
           - Hardware settling time is about 1s, 2-3s for range change
             (scan channel change)
           - Time to a stable reading after channel change:
               max(hardware_settling, pause) + digital_filter
             so if pause it too small, it will take hardware settling time
             to get first reading used for the filter. Otherwise it will be
             the pause time (pause and hardware settling don't add)
           - When under PID control:
               The control channel is measured between all the other channels
               (toggles between control channel and non control channels).
               channel switch time is the same but the dwell times are changed
               about 5s for control and 1s for others (non-control).
               These are fixed (see  Manual 4.11.8.1 Reading Sequence p 4-23)
               There does not seem to be a way to change these dwell times.
    """
    def __init__(self, visa_addr, still_res=120., still_full_res=136.4, scanner=True, **kwarg):
        """
        still_res is the still heater resistance
        still_full_res is the still heater resistance with the wire resistance
                       included (the 2 wire resistance seen from outside the fridge)
        They are both used fot the still device
        scanner set it to True to force scanner use, False to disable it and 'auto' to
                automatically check for it. 'auto' only works for newer model 372 not 370.
        """
        self._still_res = still_res
        self._still_full_res = still_full_res
        self._scanner_present = scanner
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == visa_wrap.constants.InterfaceType.asrl:
            kwarg['parity'] = visa_wrap.constants.Parity.odd
            kwarg['data_bits'] = 7
        super(lakeshore_370, self).__init__(visa_addr, **kwarg)
        self._data_valid_last_ch = 0
        self._data_valid_last_t = 0.
        self._data_valid_last_start = 0., [0, False]
    def _get_esr(self):
        return int(self.ask('*esr?'))
    def get_error(self):
        esr = self._get_esr()
        ret = ''
        if esr&0x80:
            ret += 'Power on. '
        if esr&0x20:
            ret += 'Command Error. '
        if esr&0x10:
            ret += 'Execution Error. '
        if esr&0x04:
            ret += 'Query Error (output queue full). '
        if esr&0x01:
            ret += 'OPC received.'
        if ret == '':
            ret = 'No Error.'
        return ret
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        if dev_obj == self.fetch:
            old_ch = self.current_ch.getcache()
            ch = options.get('ch', None)
            ch = self._fetch_helper(ch)
            ch_list = []
            in_set = []
            in_filter = []
            in_meas = []
            for c in ch:
                ch_list.append(c)
                in_set.append(self.input_set.get(ch=c))
                in_filter.append(self.input_filter.get())
                in_meas.append(self.input_meas.get())
            self.current_ch.set(old_ch)
            base = ['current_ch=%r'%ch_list, 'input_set=%r'%in_set,
                    'input_filter=%r'%in_filter, 'input_meas=%r'%in_meas]
        else:
            base = self._conf_helper('current_ch', 'input_set', 'input_filter', 'input_meas')
        base += self._conf_helper('sp', 'pid', 'manual_out_raw', 'still', 'heater_range',
                                  'control_mode', 'control_setup', 'control_ramp', options)
        return base
    def _enabled_list_getdev(self):
        old_ch = self.current_ch.getcache()
        ret = []
        for c in self.current_ch.choices:
            d = self.input_set.get(ch=c)
            if d['enabled']:
                ret.append(c)
        self.current_ch.set(old_ch)
        return ret
    def _fetch_helper(self, ch=None):
        if ch is None:
            ch = self.enabled_list.getcache()
        if not isinstance(ch, (list, ChoiceBase)):
            ch = [ch]
        return ch
    def _fetch_getformat(self, **kwarg):
        ch = kwarg.get('ch', None)
        ch = self._fetch_helper(ch)
        multi = []
        graph = []
        for i, c in enumerate(ch):
            graph.append(2*i)
            multi.extend([str(c)+'_T', str(c)+'_S'])
        fmt = self.fetch._format
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch, **kwarg)
    @locked_calling
    def _data_valid_start(self):
        """ returns channel and autoscan_en """
        to = time.time()
        if to - self._data_valid_last_start[0] < 0.02:
            # nothing has changed since last call so speedup by reusing result
            return self._data_valid_last_start[1]
        # the only way to clear the status when using serial is with *cls
        # and it is faster to also ask a question (less wait time later)
        result = self.ask('*cls;scan?').split(',')
        ret = int(result[0]), bool(int(result[1]))
        self._data_valid_last_start = time.time(), ret
        return ret
    def _data_valid(self):
        """
        waits until we have valid data
        returns the current scan channel when done
        """
        with self._lock_instrument: # protect object variables
            to = time.time()
            start_ch, foo = self._data_valid_start()
            if to-self._data_valid_last_t < 1. and self._data_valid_last_ch == start_ch:
                # we should still be having good data, skip the wait
                self._data_valid_last_t = to
                return start_ch
        while not self.read_status_byte()&4:
            wait(.02)
        after_ch, foo = self._data_valid_start()
        tf = time.time()
        if tf-to > 1.: # we waited after a channel change
            ch = after_ch
        else:  # the channel is the same or it got changed just after our wait.
            ch = start_ch
        with self._lock_instrument: # protect object variables
            self._data_valid_last_t = tf
            self._data_valid_last_ch = ch
        return ch
    def _fetch_getdev(self, ch=None, lastval=False, wait_new=False):
        """
        Optional parameter:
            ch: To select which channels to read. Default to all the enabled
                ones. Otherwise ch=4 selects only channel 4 and
                ch=[3,5] selects channels 3 and 5.
          lastval: When enabled, and when scanning, waits and picks the last value
                   read from that channel before switching
          wait_new: only returns values the are fresh. If a channel is never scanned
                    it will hang
        lastval and wait_new do something only when scanning is enabled.
        You can enable both at the same time.

        For each channels, two values are returned. The tempereture in Kelvin
        and the sensor value in Ohm.
        """
        old_ch = self.current_ch.getcache()
        ch = self._fetch_helper(ch)
        nmeas = len(ch) # the number of measures to do
        ret = [None] * nmeas*2
        ich = list(enumerate(ch)) # this makes a list of (i,c)
        ch2i = {c:i for i,c in ich} # maps channel # to index
        # for lastval only:
        # We assume the scanning is slower than getting all the values
        # so we first get all channel except the active one.
        # This should be ok since the first seconds after a channel change
        # returns the previous value and the sequence order is not too critical
        # since we have seconds to read all other channels
        if lastval or wait_new:
            # use _data_valid_start here because it can save some time over
            # self.scan.get()
            start_scan_ch, autoscan_en = self._data_valid_start()
            current_ch = start_scan_ch
            if not autoscan_en:
                lastval = False
                wait_new = False
        if lastval or wait_new:
            # They both introduce delays so we unlock to allow other threads
            # to use this device. The reset of the code has been checked to
            # be thread safe
            # TODO better unlockin/locking: This way, if the code is interrupted
            #             by KeyboardInterrupt it will produce an unlocking
            #             error in the previous with handler (the re-acquire)
            #             is not performed.
            self._lock_release()
        skip = False
        indx = 0
        while nmeas != 0:
            if wait_new and lastval:
                while True:
                    ch, foo = self._data_valid_start()
                    if ch == current_ch: # we wait until the channel changes
                        wait(.2)
                    else:
                        break
                if current_ch not in ch2i:
                    current_ch = ch
                    continue
                i, c = ch2i[current_ch], current_ch
                current_ch = ch
                # In PID control we will repeat the control channel multiple times
                # So check that. We will return the last one only
                if ret[i*2] is None:
                    nmeas -= 1
            elif wait_new: # only
                while True:
                    current_ch = self._data_valid()
                    if current_ch not in ch2i: # we want valid data for this channel
                        wait(.5)
                    else:
                        i, c = ch2i.pop(current_ch), current_ch
                        nmeas -= 1
                        break
            else: # lastval only or nothing
                i, c = ich[indx]
                indx += 1
                nmeas -= 1
                if lastval and c == start_scan_ch:
                    skip = True
                    continue
            ret[i*2] = self.t.get(ch=c)
            ret[i*2+1] = self.s.get(ch=c) # repeating channels means we don't need the lock
        if skip and lastval:
            while True:
                ch, foo = self._data_valid_start()
                if ch != start_scan_ch:
                    break
                wait(.1)
            i = ch2i[start_scan_ch]
            ret[i*2] = self.t.get(ch=start_scan_ch)
            ret[i*2+1] = self.s.get(ch=start_scan_ch)
        if lastval or wait_new:
            # we need to reacquire the lock before leaving
            self._lock_acquire()
        self.current_ch.set(old_ch)
        return ret
    def _htr_getdev(self):
        """Always in W, using control_setup heater_Ohms if necessary."""
        csetup = self.control_setup.getcache()
        htr = self.htr_raw.get()
        if csetup.output_display == 'power':
            return htr
        else:
            rng = self.heater_range.get()
            return (htr/100.*rng)**2 * csetup.heater_Ohms
    def _create_devs(self):
        if self.visa.is_serial():
            # we need to set this before any writes.
            self._write_write_wait = 0.100
            #self.visa.term_chars = '\r\n'
            self.write('*ESE 255') # needed for get_error
            self.write('*sre 4') # neede for _data_valid
        else: # GPIB
            self._write_write_wait = 0.050
        if self._scanner_present == 'auto':
            # DOUT always returns 00 when a scanner is present.
            scanner = False
            prev_dout = int(self.ask('DOUT?'))
            if prev_dout == 0:
                self.write('DOUT 01')
                dout = int(self.ask('DOUT?'))
                if dout != 0:
                    # bring it back
                    self.write('DOUT 00')
                else:
                    scanner = True
            self._scanner_present = scanner
        if self._scanner_present:
            ch_opt_sel = range(1, 17)
        else:
            ch_opt_sel = range(1, 2)
        self.current_ch = MemoryDevice(1, choices=ch_opt_sel)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.t = devChOption(getstr='RDGK? {ch}', str_type=float, doc='Return the temperature in Kelvin for the selected sensor(ch)')
        self.s = devChOption(getstr='RDGR? {ch}', str_type=float, doc='Return the sensor value in Ohm for the selected sensor(ch)')
        self.status_ch = devChOption(getstr='RDGST? {ch}', str_type=int, doc="""\
                         flags:
                               0      = valid
                               1  (0) = CS OVL
                               2  (1) = VCM OVL
                               4  (2) = VMIX OVL
                               8  (3) = VDIF OVL
                               16 (4) = R overrange
                               32 (5) = R underrange
                               64 (6) = T overrange
                               128(7) = T underrange
                        """)
        self.status_ch = devChOption(getstr='RDGST? {ch}', str_type=int) #flags 1(0)=CS OVL, 2(1)=VCM OVL, 4(2)=VMIX OVL, 8(3)=VDIF OVL
                               #16(4)=R. OVER, 32(5)=R. UNDER, 64(6)=T. OVER, 128(7)=T. UNDER
                               # 000 = valid
        tempco = ChoiceIndex({1:'negative', 2:'positive'})
        self.input_set = devChOption('INSET {ch},{val}', 'INSET? {ch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                     choices=ChoiceMultiple(['enabled', 'dwell', 'pause', 'curvno', 'tempco'],
                                                       [bool, (int, (1, 200)), (int, (3, 200)), (int, (0, 20)), tempco]))
        self.input_filter = devChOption('FILTER {ch},{val}', 'FILTER? {ch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                      choices=ChoiceMultiple(['filter_en', 'settle_time', 'window'], [bool, (int, (1, 200)), (int, (1, 80))]))
        res_ranges = ChoiceIndex(make_choice_list([2, 6.32], -3, 7), offset=1, normalize=True)
        cur_ranges = ChoiceIndex(make_choice_list([1, 3.16], -12, -2), offset=1, normalize=True)
        volt_ranges = ChoiceIndex(make_choice_list([2, 6.32], -6, -1), offset=1, normalize=True)
        curvolt_ranges = ChoiceMultipleDep('exc_mode', {'voltage':volt_ranges, 'current':cur_ranges})
        self.input_meas = devChOption('RDGRNG {ch},{val}', 'RDGRNG? {ch}', allow_kw_as_dict=True, allow_missing_dict=True,
                                     choices=ChoiceMultiple(['exc_mode', 'exc_range', 'range', 'autorange_en', 'excitation_disabled'],
                                                       [ChoiceIndex(['voltage', 'current']), curvolt_ranges, res_ranges, bool, bool]))
        # scan returns the channel currently being read
        #  it is the channel that flashes, not necessarily the one after scan on the
        #  display (they differ when temperature control is enabled, the instrument goes back
        #  to the control channel after all readings. This command follows that.)
        self.scan = scpiDevice('SCAN', allow_kw_as_dict=True, allow_missing_dict=True,
                               choices=ChoiceMultiple(['ch', 'autoscan_en'], [int, bool]))
        #self.current_loop = MemoryDevice(1, choices=[1, 2])
        #def devLoopOption(*arg, **kwarg):
        #    options = kwarg.pop('options', {}).copy()
        #    options.update(loop=self.current_loop)
        #    app = kwarg.pop('options_apply', ['loop'])
        #    kwarg.update(options=options, options_apply=app)
        #    return scpiDevice(*arg, **kwarg)
        #self.pid = scpiDevice('PID', choices=ChoiceMultiple(['P', 'I', 'D'], float))
        pid_ch = ChoiceMultiple(['P', 'I', 'D'], [(float, (0.001, 1000)), (float,(0, 10000)), (float, (0, 2500))])
        self.pid = scpiDevice('PID', allow_kw_as_dict=True, allow_missing_dict=True, choices=pid_ch, multi=pid_ch.field_names, doc="You can use as set(tc3.pid, P=21)")
        self.pid_P = Dict_SubDevice(self.pid, 'P', force_default=False)
        self.pid_I = Dict_SubDevice(self.pid, 'I', force_default=False)
        self.pid_D = Dict_SubDevice(self.pid, 'D', force_default=False)
        self.manual_out_raw = scpiDevice('MOUT', str_type=float,
                                  doc='manual heater output in % of Imax or in W depending on control_setup output_display option')
        self.htr_raw = scpiDevice(getstr='HTR?', str_type=float,
                                  doc='heater output in % of Imax or in W depending on control_setup output_display option')
        self._devwrap('htr')
        cmodes = ChoiceIndex({1:'pid', 2:'zone', 3:'open_loop', 4:'off'})
        self.control_mode = scpiDevice('CMODE', choices=cmodes)
        # heater range of 0 means off
        htrrng_dict = {0:0., 1:31.6e-6, 2:100e-6, 3:316e-6,
                       4:1.e-3, 5:3.16e-3, 6:10e-3, 7:31.6e-3, 8:100e-3}
        htrrng = ChoiceIndex(htrrng_dict)
        self.heater_range = scpiDevice('HTRRNG', choices=htrrng)
        csetup_htrrng_dict = htrrng_dict.copy()
        del csetup_htrrng_dict[0]
        csetup_htrrng = ChoiceIndex(csetup_htrrng_dict)
        csetup = ChoiceMultiple(['channel','filter_en', 'units', 'delay', 'output_display',
                           'heater_limit', 'heater_Ohms'],
                          [(int, (1, 16)), bool, ChoiceIndex({1:'kelvin', 2:'ohm'}), (int, (1, 255)),
                           ChoiceIndex({1:'current', 2:'power'}), csetup_htrrng, (float, (1, 1e5))])
        self.control_setup = scpiDevice('CSET', choices=csetup, allow_kw_as_dict=True, allow_missing_dict=True)
        self.control_setup_heater_limit = Dict_SubDevice(self.control_setup, 'heater_limit', force_default=False)
        self.control_ramp = scpiDevice('RAMP', allow_kw_as_dict=True, allow_missing_dict=True,
                                       choices=ChoiceMultiple(['en', 'rate'], [bool, (float,(0.001, 10))]), doc="Activates the sweep mode. rate is in K/min.", setget=True)
        self.ramp_sweeping = devChOption(getstr='RAMPST?', str_type=bool)
        self.sp = scpiDevice('SETP', str_type=float)
        self.still_raw = scpiDevice('STILL', str_type=float)
        self._devwrap('enabled_list')
        self._devwrap('fetch', autoinit=False)
        self.alias = self.fetch

        Rfull = self._still_full_res
        Rhtr = self._still_res
        htr_from_raw = lambda x:  (x/10./Rfull)**2 * Rhtr*1e3 # x is % of 10V scale so x/10 is volt
        htr_to_raw = lambda p:    np.sqrt(p*1e-3/Rhtr)*Rfull*10.  # p is in mW
        self.still = FunctionDevice(self.still_raw, htr_from_raw, htr_to_raw, quiet_del=True, doc='still power in mW')

        # This needs to be last to complete creation
        super(lakeshore_370, self)._create_devs()

#######################################################
##    Lakeshore 372 Temperature controller
#######################################################

#@register_instrument('LSCI', 'MODEL372', '1.3')
@register_instrument('LSCI', 'MODEL372')
class lakeshore_372(lakeshore_370):
    def __init__(self, visa_addr, *args, **kwargs):
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == visa_wrap.constants.InterfaceType.asrl:
            baud_rate = kwargs.pop('baud_rate', 57600)
            kwargs['baud_rate'] = baud_rate
        scanner = kwargs.pop('scanner', 'auto')
        super(lakeshore_372, self).__init__(visa_addr, *args, scanner=scanner, **kwargs)


#######################################################
##    Lakeshore 625 Magnet controller
#######################################################

# Test timings:
#  gpib does not seem to need extra waits.
#  serial writes requires more than 50 ms of wait or to use opc.
#       without opc, 60 ms is not enough. 75 ms is probably enough.
#     with opc, the writes last about 50 ms and seem stable

# Timing test:
#def rep(dev, n):
#    for i in range(1, n+1):
#        v = 0.
#        for j in range(i):
#            v = .1 + j/100.
#            dev.write('setv %.4f'%v)
#        last = float(dev.ask('setv?'))
#        iseq = '==' if abs(last - v)<1e-5 else '!='
#        print '%.4f %s %.4f'%(v, iseq, last)
#write_test = lambda dev, n: ([dev.write('setv %.3f'%((100+i)/100.)) for i in range(n)], dev.ask('*opc?'))
#def wr_test(n, dev, delay=0., usesetget=False):
#    for i in range(n):
#        v = 100.+i
#        v = (100.+i)/100.
#        if usesetget:
#            set(dev.compliance_voltage, v)
#        else:
#            dev.write('setv %.4f'%v)
#        wait(delay)
#        if usesetget:
#            rd = get(dev.compliance_voltage)
#        else:
#            rd = float(dev.ask('setv?'))
#        iseq = '==' if rd == v else '!='
#        print '%.3f %s %.3f'%(v, iseq, rd)


#@register_instrument('LSCI', 'MODEL625', '1.3/1.1')
@register_instrument('LSCI', 'MODEL625')
class lakeshore_625(visaInstrument):
    """\
    Lakeshore 625 Magnet controller.
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
        target_current
        field_target_kG
        field_target_T
        ramp_rate_current
        ramp_rate_field_kG
        ramp_rate_field_T
    Useful methods:
        conf_ramp_segments

    If magnet parameters are changed (coil_constant, limits) you should reload this device.

    Note that the pause button on the instrument remembers the previous target when the ramping light flashes.
    It will return to that target when pressed again even if new target have been given remotely,
    """
    _passwd_check = "IknowWhatIamDoing"
    def __init__(self, visa_addr, max_ramp_rate=None, *args, **kwargs):
        """
        option write_with_opc can have value, True, False, or 'auto' which enables it
          for serial connection.
        The instrument can handle 9600, 19200, 38400 or 57600 for serial baud_rate.
        Set the max_ramp_rate in A/s
        """
        self._write_with_opc = kwargs.pop('write_with_opc', 'auto')
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == visa_wrap.constants.InterfaceType.asrl:
            baud_rate = kwargs.pop('baud_rate', 9600)
            parity = kwargs.pop('parity', visa_wrap.constants.Parity.odd)
            data_bits = kwargs.pop('data_bits', 7)
            stop_bits = kwargs.pop('stop_bits', visa_wrap.constants.StopBits.one)
            kwargs['baud_rate'] = baud_rate
            kwargs['parity'] = parity
            kwargs['data_bits'] = data_bits
            kwargs['stop_bits'] = stop_bits
            if self._write_with_opc == 'auto':
                self._write_with_opc = True
        if self._write_with_opc == 'auto':
            self._write_with_opc = False
        # see also the beginning of _create_devs for write timings.
        self._coil_constant = 0. # always in T/A
        self._max_ramp_rate = max_ramp_rate
        self._orig_target_cache = None
        self._last_state = None
        super(lakeshore_625, self).__init__(visa_addr, *args, **kwargs)
        self._extra_create_dev()

    @locked_calling
    def write(self, val, termination='default', opc=None):
        if opc is None:
            opc = self._write_with_opc
        if opc and '?' not in val:
            # This will speed up pure write on tcpip connection (which adds a 100 ms delay)
            # write-read sequence only add a 20 ms delay.
            val = val+';*opc?'
            self.ask(val)
        else:
            super(lakeshore_625, self).write(val, termination=termination)
    def _current_config(self, dev_obj=None, options={}):
        base = self._conf_helper('coil_constant', 'field_T', 'field_target_T', 'compliance_voltage', 'ramp_rate_current', 'ramp_rate_unit',
                                 'last_persistent_current', 'field', 'current', 'voltage', 'voltage_remote', 'persistent_conf', 'limits',
                                 'quench_conf', 'ramp_rate_current_persistent', 'trig_current', 'external_prog_mode', 'ramp_segment_en')
        base += ['get_persistent_status=%r'%self.get_persistent_status(), 'get_oper_status=%r'%self.get_oper_status(latched=False),
                 'get_error_status=%r'%self.get_error_status(latched=False)]
        if self.ramp_segment_en.getcache():
            base += ['conf_ramp_segments=%r'%self.conf_ramp_segments()]
        return base + self._conf_helper(options)
    def clear_errors(self):
        """ Clears the operational and persistent switch heater errors"""
        self.write('ERCL')
    def get_oper_status(self, latched=True):
        if latched:
            op = int(self.ask('OPSTR?'))
        else:
            op = int(self.ask('OPST?'))
        st = lambda bit: bool(op&(1<<bit))
        ret = dict_improved(psh_stable = st(2),
                   ramp_done = st(1),
                   in_compliance = st(0))
        return ret
    def get_error_status(self, latched=True):
        """Returns the hardware, operational and persistent switch error status"""
        if latched:
            vals = self.ask('ERSTR?')
        else:
            vals = self.ask('ERST?')
        hw_err, oper_err, psh_err = [int(v, 10) for v in vals.split(',')]
        st = lambda err, bit: bool(err&(1<<bit))
        ret = dict_improved(hw_dac_not_responding = st(hw_err, 5),
                   hw_output_control_failure = st(hw_err, 4),
                   hw_output_over_voltage = st(hw_err, 3),
                   hw_output_over_current = st(hw_err, 2),
                   hw_low_line_voltage = st(hw_err, 1),
                   hw_temperature_fault = st(hw_err, 0),
                   magnet_discharge_crowbar = st(oper_err, 6),
                   magnet_quench_detected = st(oper_err, 5),
                   remote_inhibit_detected = st(oper_err, 4),
                   temperature_high = st(oper_err, 3),
                   high_line_voltage = st(oper_err, 2),
                   external_prog_too_high = st(oper_err, 1),
                   calibration_error = st(oper_err, 0),
                   psh_short = st(psh_err, 1),
                   psh_open = st(psh_err, 0))
        return ret
    def _get_esr(self):
        return int(self.ask('*esr?'))
    def get_error(self):
        """ see also get_error_status """
        ret = []
        esr = self._get_esr()
        if esr&0x80:
            ret.append('Power on.')
        if esr&0x20:
            ret.append('Command Error.')
        if esr&0x10:
            ret.append('Execution Error.')
        if esr&0x04:
            ret.append('Query Error (output queue full).')
        if esr&0x01:
            ret.append('OPC received.')
        if len(ret) == 0:
            ret = 'No Error.'
        else:
            ret = ' '.join(ret)
        return ret
    def set_persistent(self, enable, force=False, password=None):
        if enable:
            if force and self._check_password(password=password):
                self.write('PSH 99')
            else:
                self.write('PSH 1')
        else:
            self.write('PSH 0')
    def get_persistent_status(self):
        st = self.persistent_status.get()
        return ['off', 'on', 'warming', 'cooling'][st]
    @locked_calling
    def stop(self):
        """This stops the current ramp within a few seconds."""
        # the stop commands does not seem to always work (at least for small ramp rates)
        # So do it manually
        if self._get_states() == 'ramping':
            #self.write('STOP')
            cur = self.current.get()
            self.target_current.set(cur)
            self._ramping_helper('ramping', ['paused'], extra_wait=0)
    def _check_password(self, password, dev=None):
        if dev is not None:
            password = dev._check_cache['kwarg']['password']
        if password != self._passwd_check:
            raise ValueError('Invalid password.')
    def conf_ramp_segments(self, currents=None, rates=None):
        """ when currents is None, show the ramp segments.
            Otherwise all the parameters are lists (or arrays) and need to be of the same length <=5.
            currents are the <= criteria for selecting the other parameters from the effective target_current
            value (considering it ramps).
            currents need to be in increasing order (otherwise entries will be skipped). The last entry
            is used for targets above the currents value (the last currents value is unused).
            If the first entry current is 0, it is used for all targets.
        """
        if currents is None:
            data = dict_improved([('currents', []), ('rates', [])])
            for z in range(5):
                ret = self.ramp_segment_para.get(segment=z+1)
                if ret.current == 0 and z != 0:
                    break
                for k in ret:
                    data[k+'s'].append(ret[k])
                if ret.current == 0:
                    break
            return data
        else:
            if len(currents) != len(rates):
                raise ValueError('One of the data is not of the same length as the others')
            if len(currents) > 5:
                raise ValueError('You need less than 5 data')
            if list(currents) != sorted(currents):
                raise ValueError('currents are not in ascending order.')
            z=-1
            for z, (c, r) in enumerate(zip(currents, rates)):
                self.ramp_segment_para.set(segment=z+1, current=c, rate=r)
            if z < 4 and c!= 0:
                self.ramp_segment_para.set(segment=z+2, current=0, rate=0.001)
    def _current_magnet_getdev(self):
        ps_installed = self.persistent_conf.getcache().psh_present
        if ps_installed and self.get_persistent_status() != 'on':
            return self.last_persistent_current.get()
        else:
            return self.current.get()
    def _ramp_rate_current_unit_helper(self, unit=None):
        if unit is not None:
            self.ramp_rate_unit.set(unit)
        unit = self.ramp_rate_unit.get()
        factor = dict(min=60., s=1.)[unit]
        return factor
    def _ramp_rate_current_getdev(self, unit=None):
        factor = self._ramp_rate_current_unit_helper(unit)
        rate = self.ramp_rate_current_raw.get()
        return rate*factor
    def _ramp_rate_current_checkdev(self, rate, unit=None):
        factor = self._ramp_rate_current_unit_helper(unit)
        BaseDevice._checkdev(self.ramp_rate_current, rate)
    def _ramp_rate_current_setdev(self, rate, unit=None):
        """ unit can be 'min' or 's' for A/min or A/s """
        # check already changed the unit
        factor = self._ramp_rate_current_unit_helper()
        self.ramp_rate_current_raw.set(rate/factor)

    def _ramp_rate_field_T_getdev(self, unit=None):
        factor = self._ramp_rate_current_unit_helper(unit)
        rate = self.ramp_rate_current_raw.get()
        return rate*factor * self._coil_constant
    def _ramp_rate_field_T_checkdev(self, rate, unit=None):
        factor = self._ramp_rate_current_unit_helper(unit)
        BaseDevice._checkdev(self.ramp_rate_field_T, rate)
    def _ramp_rate_field_T_setdev(self, rate, unit=None):
        """ unit can be 'min' or 's' for T/min or T/s """
        # check already changed the unit
        factor = self._ramp_rate_current_unit_helper()
        self.ramp_rate_current_raw.set(rate/factor/self._coil_constant)

    def _ramp_rate_field_kG_getdev(self, unit=None):
        factor = self._ramp_rate_current_unit_helper(unit)
        rate = self.ramp_rate_current_raw.get()
        return rate*factor * self._coil_constant*10
    def _ramp_rate_field_kG_checkdev(self, rate, unit=None):
        factor = self._ramp_rate_current_unit_helper(unit)
        BaseDevice._checkdev(self.ramp_rate_field_kG, rate)
    def _ramp_rate_field_kG_setdev(self, rate, unit=None):
        """ unit can be 'min' or 's' for kG/min or kG/s """
        # check already changed the unit
        factor = self._ramp_rate_current_unit_helper()
        self.ramp_rate_current_raw.set(rate/factor/self._coil_constant/10)


    @locked_calling
    def _extra_create_dev(self):
        d = self.coil_constant.get()
        if d.units == 'T/A':
            scaleT = d.constant
        else:
            scaleT = d.constant/10.
        self._coil_constant = scaleT
        scalekG = scaleT*10
        d = self.limits.get()
        max_current = d.current
        max_rate = d.ramp
        min_current = -max_current
        self.target_current.max = max_current
        self.target_current.min = min_current
        max_fieldT = max_current*scaleT
        min_fieldT = min_current*scaleT
        max_fieldkG = max_fieldT*10
        min_fieldkG = min_fieldT*10
        self.field_target_T = ScalingDevice(self.target_current, scaleT, quiet_del=True, max=max_fieldT, min=min_fieldT)
        self.field_target_kG = ScalingDevice(self.target_current, scalekG, quiet_del=True, max=max_fieldkG, min=min_fieldkG)
        self.field_T = ScalingDevice(self.current_magnet, scaleT, quiet_del=True, doc='Field in magnet (even in persistent mode)')
        self.field_kG = ScalingDevice(self.current_magnet, scalekG, quiet_del=True, doc='Field in magnet (even in persistent mode)')
        rmin, rmax = .0001, self._max_ramp_rate
        if rmax is None:
            rmax = max_rate
        self.ramp_rate_current.choices.choices['min'].min = rmin*60
        self.ramp_rate_current.choices.choices['min'].max = rmax*60
        self.ramp_rate_current.choices.choices['s'].min = rmin
        self.ramp_rate_current.choices.choices['s'].max = rmax
        self.ramp_rate_field_T.choices.choices['min'].min = rmin*scaleT*60
        self.ramp_rate_field_T.choices.choices['min'].max = rmax*scaleT*60
        self.ramp_rate_field_T.choices.choices['s'].min = rmin*scaleT
        self.ramp_rate_field_T.choices.choices['s'].max = rmax*scaleT
        self.ramp_rate_field_kG.choices.choices['min'].min = rmin*scalekG*60
        self.ramp_rate_field_kG.choices.choices['min'].max = rmax*scalekG*60
        self.ramp_rate_field_kG.choices.choices['s'].min = rmin*scalekG
        self.ramp_rate_field_kG.choices.choices['s'].max = rmax*scalekG
        self.ramp_current.max = max_current
        self.ramp_current.min = min_current
        self.ramp_field_T = ScalingDevice(self.ramp_current, scaleT, quiet_del=True, max=max_fieldT, min=min_fieldT, doc='Same options as ramp_current')
        self.ramp_field_kG = ScalingDevice(self.ramp_current, scalekG, quiet_del=True, max=max_fieldkG, min=min_fieldkG, doc='Same optiosn as ramp_current')
        self.alias = self.field_T
        self._create_devs_helper() # to get logical devices return proper name (not name_not_found)

    def _get_states(self):
        errors = self.get_error_status(latched=False)
        pers = self.get_persistent_status()
        oper = self.get_oper_status(latched=False)
        for k, v in errors.items():
            # for any error we say we are quenched to stop the ramp.
            if v:
                return 'quench'
        if oper.psh_stable or pers in ['on', 'off']:
            return {False:'ramping', True:'paused'}[oper.ramp_done]
        return pers # so either warming or cooling

    def is_ramping(self, param_dict=None):
        """ Returns True when the magnet is ramping the field. Can be used for the sequencer. """
        return self._get_states() in ['ramping']
    def is_stable(self, param_dict=None):
        """ Returns True when the magnet is not ramping nor changing the heat switch. Can be used for the sequencer. """
        return self._get_states() in ['paused']

    def _ramping_helper(self, stay_states, end_states=None, extra_wait=None):
        wait(0.2) # wait some time to allow previous change to affect the _get_states results.
        to = time.time()
        switch_time = self.persistent_conf.getcache().delay
        if stay_states == 'cooling':
            prog_base = 'Magnet Cooling switch: {time}/%.1f'%switch_time
        elif stay_states == 'warming':
            prog_base = 'Magnet Heating switch: {time}/%.1f'%switch_time
        else: # ramping
            prog_base = 'Magnet Ramping {current:.3f}/%.3f A'%self.target_current.getcache()
        if isinstance(stay_states, basestring):
            stay_states = [stay_states]
        with release_lock_context(self):
            with mainStatusLine.new(priority=10, timed=True) as progress:
                while self._get_states() in stay_states:
                    wait(.1)
                    progress(prog_base.format(current=self.current.get(), time=time.time()-to))
            if self._get_states() == 'quench':
                raise RuntimeError(self.perror('The magnet QUENCHED!!! (or some other error, see get_error_status'))
            if extra_wait:
                wait(extra_wait, progress_base='Magnet wait')
        if end_states is not None:
            if isinstance(end_states, basestring):
                end_states = [end_states]
            if self._get_states() not in end_states:
                raise RuntimeError(self.perror('The magnet state did not change to %s as expected'%end_states))

    @locked_calling
    def do_persistent(self, to_pers, quiet=True, extra_wait=None):
        """
        This function goes in/out of persistent mode.
        to_pers to True to go into persistent mode (turn persistent switch off, ramp to zero and leave magnet energized)
                   False to go out of persistent mode (reenergize leads and turn persistent switch on)
        It returns the previous state of the persistent switch.
        """
        def print_if(s):
            if not quiet:
                print s
        if not self.persistent_conf.getcache().psh_present:
            return True
        state = self._get_states()
        if state in ['cooling', 'warming']:
            raise RuntimeError(self.perror('persistent switch is currently changing state. Wait.'))
        if state in ['ramping']:
            raise RuntimeError(self.perror('Magnet is ramping. Stop that before changing the persistent state.'))
        if state in ['quench']:
            raise RuntimeError(self.perror('The magnet QUENCHED!!! (or some other error, see get_error_status'))
        orig_switch_en = self.get_persistent_status()
        if orig_switch_en not in ['on', 'off']:
            raise RuntimeError(self.perror('persistent switch is currently changing state. Wait.'))
        orig_switch_en = orig_switch_en == 'on'
        # we are in pause state
        if to_pers:
            if orig_switch_en:
                # switch is active
                print_if('Turning persistent switch off and waiting for cooling...')
                self.set_persistent(False)
                self._ramping_helper('cooling', 'paused')
            print_if('Ramping to zero ...')
            self.target_current.set(0.)
            self._ramping_helper('ramping', 'paused', extra_wait)
        else: # go out of persistence
            if not orig_switch_en:
                # This is the same as self.last_persistent_current.get()
                tmp_target = self.current_magnet.get()
                print_if('Ramping to previous target ...')
                self.target_current.set(tmp_target)
                # The ramp is fast but still wait and extra 5 s for stability before pausing.
                self._ramping_helper('ramping', 'paused', 5.)
                print_if('Turning persistent switch on and waiting for heating...')
                self.set_persistent(True)
                self._ramping_helper('warming', 'paused', extra_wait)
        return orig_switch_en

    def _do_ramp(self, current_target, wait, no_wait_end=False):
        self.target_current.set(current_target)
        if no_wait_end:
            return
        self._ramping_helper('ramping', ['paused'], wait)

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
                print s
        ps_installed = self.persistent_conf.getcache().psh_present
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
        # All the options are there to absorb the parameters on setget.
        return self.current_magnet.get()

    def _create_devs(self):
        if self.visa.is_serial():
            if not self._write_with_opc:
                # we need to set this before any writes.
                # otherwise some write request are lost.
                self._write_write_wait = 0.075
        else: #GPIB
            self._write_write_wait = 0.0
        # This instrument does not require the scpiDevice_lk that adds extra time between set and get.
        #scpiDev = scpiDevice_lk
        scpiDev = scpiDevice
        self.ramp_wait_after = MemoryDevice(10., min=0.)
        self.persistent_wait_before = MemoryDevice(30., min=30., doc='This time is used to wait after a ramp but before turning persistent off')
        self.ramp_rate_unit = MemoryDevice('min', choices=['min', 's'])
        def scpiDev_prot(*args, **kwargs):
            options = kwargs.pop('options', {}).copy()
            options.update(password=None)
            doc = kwargs.pop('doc', "")
            doc += '\nTo perform a set you need to set password to "%s"\n'%self._passwd_check
            kwargs.update(options=options, extra_check_func=ProxyMethod(self._check_password))
            return scpiDevice(*args, **kwargs)

        self.display = scpiDev('DISP', choices=ChoiceMultiple(['mode', 'volt_sense_display_en', 'brightness_pct'], [ChoiceIndex(['current', 'field']), bool, ChoiceIndex([0, 25, 75, 100])]))
        self.coil_constant = scpiDev_prot('FLDS', choices=ChoiceMultiple(['units', 'constant'], [ChoiceIndex(['T/A', 'kG/A']), float_fix6]))
        self.limits = scpiDev_prot('LIMIT', choices=ChoiceMultiple(['current', 'voltage', 'ramp'],
                                                                   [(float_fix4, (0, 60.1)), (float_fix4, (0.1, 5)), (float_fix4, (0.0001, 99.999))]),
                                     allow_kw_as_dict=True, allow_missing_dict=True,
                                     doc='rate in A/s')
        self.persistent_status = scpiDev(getstr='PSH?', str_type=int, doc="""\
                                0= heater off
                                1= heater on
                                2= heater warming
                                3= heater cooling
                                """)
        self.last_persistent_current = scpiDev(getstr='PSHIS?', str_type=float)
        self.field = scpiDev(getstr='RDGF?', str_type=float, doc='unit are T or kG depending on coil_constant')
        self.current = scpiDev(getstr='RDGI?', str_type=float)
        self.voltage = scpiDev(getstr='RDGV?', str_type=float)
        self.voltage_remote = scpiDev(getstr='RDGRV?', str_type=float)
        self.persistent_conf = scpiDev_prot('PSHS', choices=ChoiceMultiple(['psh_present', 'current_mA', 'delay'], [bool, (int, (10, 125)), (int, (5, 100))]))
        self.quench_conf = scpiDev_prot('QNCH', choices=ChoiceMultiple(['quench_detect_en', 'rate'], [bool, (float_fix4, (0.01, 10))]))
        self.ramp_rate_current_raw = scpiDev('RATE', str_type=float_fix4, doc='rate in A/s', min=0.0001, max=99.999)
        self.ramp_rate_current_persistent = scpiDev('RATEP', choices=ChoiceMultiple(['use_pers_rate_en', 'rate'], [bool, (float_fix4, (0.0001, 99.999))]), doc='rate in A/s')
        self.target_field_raw = scpiDev('SETF', str_type=float, doc='unit are T or kG depending on coil_constant', setget=True)
        self.target_current = scpiDev('SETI', str_type=float_fix4, min=-60.1, max=60.1, setget=True)
        self.compliance_voltage = scpiDev('SETV', str_type=float_fix4, min=0.1, max=5)
        self.trig_current = scpiDev('TRIG', str_type=float_fix4, min=-60.1, max=60.1)
        self.external_prog_mode = scpiDev('XPGM', choices=ChoiceIndex(['internal', 'external', 'sum']))
        self.current_segment = MemoryDevice(1, choices=list(range(1, 6)))
        self.ramp_segment_en = scpiDev('RSEG', str_type=bool)
        self.ramp_segment_para = scpiDev('RSEGS {segment},{val}', 'RSEGS? {segment}', allow_kw_as_dict=True, allow_missing_dict=True,
                                         choices=ChoiceMultiple(['current', 'rate'], [(float_fix4, (0, 60.1)), (float_fix4, (0.0001, 99.999))]), doc='rate in A/s',
                                         options=dict(segment=self.current_segment), options_apply=['segment'], autoinit=False)
        rate_A_lim = ChoiceDevDep(self.ramp_rate_unit, dict(min=ChoiceLimits(min=0, max=0), s=ChoiceLimits(min=0, max=0)))
        rate_T_lim = ChoiceDevDep(self.ramp_rate_unit, dict(min=ChoiceLimits(min=0, max=0), s=ChoiceLimits(min=0, max=0)))
        rate_kG_lim = ChoiceDevDep(self.ramp_rate_unit, dict(min=ChoiceLimits(min=0, max=0), s=ChoiceLimits(min=0, max=0)))
        self._devwrap('ramp_rate_current', choices=rate_A_lim)
        self._devwrap('ramp_rate_field_T', choices=rate_T_lim, autoinit=False)
        self._devwrap('ramp_rate_field_kG', choices=rate_kG_lim, autoinit=False)
        self._devwrap('current_magnet')
        self._devwrap('ramp_current', autoinit=False, setget=True)
        # This needs to be last to complete creation
        super(lakeshore_625, self)._create_devs()
