# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2021-2023  Pierre Fevrier                                        #
#                      Christian Lupien <christian.lupien@usherbrooke.ca>    #
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
import numpy
import time

from ..instruments_base import visaInstrument, scpiDevice, ChoiceStrings, BaseDevice, \
                               visaInstrumentAsync, locked_calling, wait, ChoiceMultiple
from ..instruments_registry import register_instrument
from .logical import FunctionWrap

@register_instrument('Thorlabs', 'PM100A', alias='PM100A Power Meter')
class thorlabs_power_meter(visaInstrumentAsync):
    """
    To load the instrument: th1 = instruments.thorlabs_power_meter('USB0::0x1313::0x8079::P1005280::INSTR')
    This controls the power meter console from Thorlabs
    Most useful devices:
        fetch, readval
    Devices to change usefull settings:
        average
        wavelength
        diameter
        response_AW
        response_VW
        ...
    """

    def init(self, full=False):
        # clear event register, extended event register and error queue
        self.clear()

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):

        config = ['sensor_idn', 'average', 'user_attenuation', 'zero_adjust_magnitude','wavelength', 'diameter', 'configuration','adapter','filter']
        adapter  = self.adapter.get()
        #adapter can be 'PHOTodiode', 'THERmal', 'PYRo' or None
        if str(adapter).lower() == 'thermal':
            config += ['th_accelerator_state', 'th_accelerator_time', 'response_VW']
        elif str(adapter).lower() == 'thermal':
            config += ['response_AW']
        config += ["current_range", "current_auto_range", "current_delta_mode", "current_delta_reference"]
        config += ["power_range", "power_auto_range", "power_delta_mode", "power_delta_reference"]
        #I dont know why the device voltage_delta_reference times out
        config += ["voltage_range", "voltage_auto_range", "voltage_delta_mode"]

        config += [options]
        return self._conf_helper(*config)

    def zero_adjust(self):
        """
            Performs a zero adjustment routine
            """
        try:
            self.write(':SENse:CORRection:COLLect:ZERO')  # Initiate the zero adjustment routine
        except KeyboardInterrupt:
            self.write(':SENse:CORRection:COLLect:ZERO:ABORt')

    def _create_devs(self):

        self.sensor_idn = scpiDevice(getstr='SYSTem:SENSor:IDN?',
                                     doc='Query info about the connected sensor', autoinit=True)
        self.line_frequency = scpiDevice('SYSTem:LFRequency', str_type=int,
                                         doc='Sets the instrument\'s line frequency setting to 50 or 60Hz',
                                         autoinit=True)
        self.beeper_state = scpiDevice('SYSTem:BEEPer:STATe', str_type=bool,
                                       doc='Activate/deactivate the beeper', autoinit=False)
        self.display_brightness = scpiDevice(':DISPlay:BRIGhtness', str_type=float,
                                             doc='set-get the display birghtness.', setget=True, autoinit=False)
        # -------------
        # SENSe subsystem
        # -------------

        self.average = scpiDevice(':SENSe:AVERage:COUNt', str_type=int,
                                  doc='set-get the averaging rate (1 sample takes approx 3ms)', setget=True,
                                  autoinit=True)

        # CORRection, everithing about power correction
        # {MIN, MAX, DEF, numeric value [nm]}
        self.user_attenuation = scpiDevice(':SENSe:CORRection', str_type=float,
                                           doc='set-get the current user attenuation for power correction', setget=True,
                                           autoinit=True)

        self.zero_adjust_magnitude = scpiDevice(getstr=':SENSe:CORRection:COLLect:ZERO:MAGNitude?',
                                                doc='get the magnitude obtained after the zero adjustment routine',
                                                autoinit=False)

        # {MIN, MAX, DEF, numeric value [nm]}
        self.wavelength = scpiDevice(':SENSe:CORRection:WAVelength', str_type=float,
                                     doc='set-get the current wavelength for power correction', setget=True,
                                     autoinit=True)
        # {MIN, MAX, DEF, numeric value [nm]}
        self.diameter = scpiDevice(':SENSe:CORRection:BEAMdiameter', str_type=float,
                                   doc='set-get the beam diameter in mm',
                                   setget=True, autoinit=True)

        # POWer, everything about power/current or power/voltage conversion

        # TODO: choose wich one to call as a function of the connected sensor
        self.response_AW = scpiDevice(':SENse:CORR:POW:RESPonse', str_type=float,
                                      doc='set-get the photodiode response value in A/W', setget=True, autoinit=True)

        self.response_VW = scpiDevice(':SENse:CORR:POW:THERmopile:RESPonse', str_type=float,
                                      doc='set-get the thermopile response value in V/W', setget=True, autoinit=True)

        # CURRent, eveything about current biasing the photodiode (?)

        self.current_auto_range = scpiDevice(':SENSe:CURRent:RANGe:AUTO', str_type=bool,
                                             doc='Switches the auto-ranging function on and off', setget=True,
                                             autoinit=True)
        self.current_range = scpiDevice(':SENSe:CURRent:RANGe', str_type=float,
                                        doc='Sets the current range in A', setget=True,
                                        autoinit=True)

        self.current_delta_reference = scpiDevice(':SENSe:CURRent:REF', str_type=float,
                                                  doc='current delta reference value in A', setget=True)
        self.current_delta_mode = scpiDevice(':SENSe:CURRent:REF:STATe', str_type=bool,
                                             doc='Switches to delta mode (current mode)', setget=True)

        # POWer

        self.power_auto_range = scpiDevice(':SENSe:POW:RANGe:AUTO', str_type=bool,
                                           doc='Switches the power auto-ranging function on and off', setget=True,
                                           autoinit=True)
        self.power_range = scpiDevice(':SENSe:POW:RANGe', str_type=float,
                                      doc='Sets the power range in W', setget=True,
                                      autoinit=True)

        self.power_delta_reference = scpiDevice(':SENSe:POW:REF', str_type=float,
                                                doc='power delta reference value in W', setget=True)
        self.power_delta_mode = scpiDevice(':SENSe:POW:REF:STATe', str_type=bool,
                                           doc='Switches to delta mode (power mode)', setget=True)

        # VOLTage

        self.voltage_auto_range = scpiDevice(':SENSe:VOLT:RANGe:AUTO', str_type=bool,
                                           doc='Switches the power auto-ranging function on and off', setget=True,
                                           autoinit=True)
        self.voltage_range = scpiDevice(':SENSe:VOLT:RANGe', str_type=float,
                                      doc='Sets the voltage range in V', setget=True,
                                      autoinit=True)

        #I dont know why this times out
        self.voltage_delta_reference = scpiDevice(':SENSe:VOLT:REF', str_type=float,
                                                doc='voltage delta reference value in V', setget=True,autoinit=False)
        self.voltage_delta_mode = scpiDevice(':SENSe:VOLT:REF:STATe', str_type=bool,
                                           doc='Switches to delta mode (voltage mode)', setget=True)
        # -------------
        # INPUTS
        # -------------

        self.filter = scpiDevice(':INPut:FILTer', str_type=bool,
                                 doc='set-get the bandwidth of the photodiode input stage (True or False)', setget=True,
                                 autoinit=True)

        #Only avalaible with connected thermal sensor
        self.th_accelerator_state = scpiDevice(':INPut:THERmopile:ACCelerator', str_type=bool,
                                               doc='set-get thermopile accelerator state (True or False), only avalaible with connected thermal sensor', setget=True,
                                               autoinit=False)

        # Only avalaible with connected thermal sensor
        self.th_accelerator_time = scpiDevice(':INPut:THERmopile:ACCelerator:TAU', str_type=bool,
                                              doc='set-get thermopile time constant tau_(0-63%) in s, only avalaible with connected thermal sensor', setget=True,
                                              autoinit=False)

        self.adapter = scpiDevice(':INPut:ADAPter', choices=ChoiceStrings('PHOTodiode', 'THERmal', 'PYRo'),
                                  doc='set-get default sensor adapter type', setget=True, autoinit=True)

        # -------------
        # CONFIGURATION
        # -------------

        self.configuration = scpiDevice(setstr=':CONF:{val}', getstr='CONF?',
                                        choices=ChoiceStrings('POW', 'CURR', 'VOLT', 'PDEN', 'TEMP'),
                                        doc='set-get the current measurement configuration', setget=True,
                                        autoinit=True)

        # -------------
        # MEASUREMENTS
        # -------------

        self.fetch = scpiDevice(getstr='FETCh?', str_type=float, autoinit=False, trig=True)
        self.readval = scpiDevice(getstr='READ?', str_type=float, autoinit=False, trig=True)
        self.alias = self.readval

        super(thorlabs_power_meter, self)._create_devs()

# Source/dest id:
HOST = 0x01
MOTHER_BOARD = 0x11
BAY_0 = 0x21
BAY_1 = 0x22
GENERIC_USB = 0x50

def encodeAPT(id, param1=0, param2=0, dest_byte=GENERIC_USB, source_byte=HOST, data=None):
    if data:
        dest_data = dest_byte | 0x80
        data_length = len(data)
        return struct.pack('<HHcc{0:d}s'.format(data_length), id, data_length, chr(dest_data), chr(source_byte), data)
    else:
        return struct.pack('<Hcccc', id, chr(param1), chr(param2), chr(dest_byte), chr(source_byte))


def decodeAPT(message):
    return message


class APTDevice(BaseDevice):
    def __init__(self, set_id=None, req_id=None, get_id=None, get_fmt=None, get_names=['chan_id', 'data'], get_types=None, get_by_default='data', autoinit=True, doc='', **kwarg):
        if get_types is None:
            get_types = [float]*len(get_names)
        if set_id is None and req_id is None:
            raise ValueError('At least one of set_id or req_id needs to be specified')
        BaseDevice.__init__(self, doc=doc, autoinit=autoinit, choices=ChoiceMultiple(get_names,get_types), get_has_check=True, multi=get_names,allow_kw_as_dict=True, allow_missing_dict=True, **kwarg)
        self._reqdev_p = req_id
        self._getdev_p = req_id
        self._setdev_p = set_id
        self.get_fmt = get_fmt
        self.get_names = get_names
        self.get_by_default = get_by_default

    def _setdev(self, val, **kwarg):
        if self._setdev_p is None:
            raise NotImplementedError(self.perror('This device does not handle _setdev'))

        #print(val,kwarg)
        data = struct.pack('<'+self.get_fmt,*[val[k] for k in self.get_names])
        message = encodeAPT(self._setdev_p, data=data)
        self.instr.write(message)


    def _getdev(self, **kwarg):
        id = self._reqdev_p
        question = encodeAPT(id, data='')
        data = self.instr.ask(question)
        ret = struct.unpack('<6s'+self.get_fmt, data)

        #if not isinstance(c, (list, tuple, np.ndarray)):
        #    c=[c]
        if "data" in kwarg.keys():
            if kwarg['data'] == 'all':
                return [ret[1+k] for k,n in enumerate(self.get_names)]
            to_return = [(k,n) for k,n in enumerate(self.get_names) if n in kwarg['data']]
            if len(to_return) > 1:
                return [ret[1+k] for (k, n) in to_return]
            elif len(to_return) ==1:
                return ret[1+to_return[0][0]]
            else:
                raise ValueError('the data requested by get not found in the specified data structure')
        else:
            #k = next(i for i, v in enumerate(self.get_names) if v == self.get_by_default)
            #return ret[1::]
            return {k:ret[1 + n] for n, k in enumerate(self.get_names)}


@register_instrument('Thorlabs', 'KDC101', alias='KDC101 Rotation stage')
class ThorlabsKDC101(visaInstrument):
    """
    Controller Thorlabs KDC101 for the rotating stage
    To load the instrument: th = instruments.ThorlabsKDC101()
    Most useful devices:
        angle
        enc_counter
        pos_counter
    Devices to change parameters:
        vel_params
        jog_params
        home_params
    Useful commands:
        move_jog
        move_abs
        move_rel
        go_home
        stop
        deg_to_inc
        inc_to_deg
    """
    def __init__(self, visa_addr='ASRL3::INSTR', *arg, **kwarg):
        skip_id_test = kwarg.pop('skip_id_test', True)
        baud_rate = kwarg.pop('baud_rate', 115200)
        write_termination = kwarg.pop('write_termination', '')
        kwarg['skip_id_test'] = skip_id_test
        kwarg['baud_rate'] = baud_rate
        kwarg['write_termination'] = write_termination
        super(ThorlabsKDC101, self).__init__(visa_addr, *arg, **kwarg)
        self._suspend_endofmove_msgs()

        self.enc_count_per_deg = kwarg.pop('enc_count_per_deg', 1919.6418578623391)
        #self.resume_endofmove_msgs()

    def idn(self):
        rep = self.ask(encodeAPT(0x0005))
        # Bytes from 24 to 84 are for internal use only
        part_a = struct.unpack('<l8sH4s', rep[6:24])
        part_b = struct.unpack('<3H', rep[84::])
        return part_a, part_b


    def write(self, val, termination=''):
        # some checks to prevent the controller from being bricked
        if ord(val[4]) != GENERIC_USB and ord(val[4]) != GENERIC_USB | 0x80:
            raise Exception("Not a valid APT command!")
        super(ThorlabsKDC101, self).write(val)

    def read(self, raw=False, count=None, chunk_size=None):
        # First we try to read the header, if the dest byte is 0x01 (HOST), no data packet to follow, if 0x81 (HOST logic OR'd with 0x80 )
        header = super(ThorlabsKDC101, self).read(count=6)
        if header[4] == HOST:
            return header
        elif header[4] == HOST | 0x80:
            count, = struct.unpack('<H', header[2:4])
            return header + super(ThorlabsKDC101, self).read(count=count)

    def _wait_for_endofmove(self, timeout_ms=60000):
        time_0 = time.time()
        new_time = time_0
        flag = False
        while(new_time-time_0 < timeout_ms/1000):
            bytes = self.ask_status_bytes()
            data, = struct.unpack('I', bytes)
            is_mov_fwd = bool(data & 0x00000010)
            is_mov_rev = bool(data & 0x00000020)
            if not is_mov_fwd and not is_mov_rev:
                flag = True
                break
            wait(0.2)
            new_time = time.time()


        #old_timeout = self.visa.timeout
        #self.visa.timeout = timeout_ms
        #try:
        #    resp = self.read()
        #except VI_ERROR_TMO:
        #    raise
        #self.visa.timeout = old_timeout

    def ask_status_bytes(self):
        message = encodeAPT(0x0429)
        self.write(message)
        res = self.read()
        return res[8::]




    def _suspend_endofmove_msgs(self):
        message = encodeAPT(0x046B)
        self.write(message)

    def _resume_endofmove_msgs(self):
        message = encodeAPT(0x046C)
        self.write(message)

    def vel_to_apt(self, vel):
        """
        Convert angular velocity (deg/s) to APT velocity
        """
        T = 2048./(6e6)
        vel_apt = self.enc_count_per_deg *T*65536*vel
        return int(numpy.around(vel_apt))

    def acc_to_apt(self, acceleration):
        """
        Convert angular acceleration (deg/s^2) to APT acceleration
        """
        T = 2048. / (6e6)
        acc_apt = self.enc_count_per_deg * T**2 * 65536 * acceleration
        return int(numpy.around(acc_apt))

    def deg_to_inc(self, deg):
        # Depend on the stages, auto-detection?
        return int(numpy.around(self.enc_count_per_deg * deg))

    def inc_to_deg(self, inc):
        return inc / self.enc_count_per_deg

    def move_rel(self, angle):
        """
        angle in deg
        """
        data = struct.pack('<Hi', 1, int(self.deg_to_inc(angle)))
        message = encodeAPT(0x0448, data=data)
        self.write(message)
        self._wait_for_endofmove()

    # Fonction a utiliser pour le "set angle"
    def move_abs(self, angle):
        """
        angle in deg
        """
        data = struct.pack('<Hi', 1, int(self.deg_to_inc(angle)))
        message = encodeAPT(0x0453, data=data)
        self.write(message)
        self._wait_for_endofmove()

    def move_jog(self, direction='fwrd'):
        """
        direction: 'fwrd' or 'rev'
        """
        if direction == 'rev':
            dire = 0x02
        else:
            dire = 0x01
        message = encodeAPT(0x046A, param1=1, param2=dire)
        self.write(message)
        self._wait_for_endofmove()

    def stop(self, immediate=False):
        """
        Stops any type of motor move (relative, absolute, homing or move at velocity). With immediate = True, abrupt stope, else strop the controller (profiled) manner.
        """
        if immediate:
            stop_mode = 0x01
        else:
            stop_mode = 0x02
        message = encodeAPT(0x0465, param1=1, param2=stop_mode)
        self.write(message)

    def continous_rotation(self, velocity = None, direction = 'fwrd'):
        """
        start a continous rotation, velocity must be positive and in deg/s
        """
        data = None
        if velocity is None and direction == 'fwrd':
            data = encodeAPT(0x0457, 1, 1)
        elif velocity is None and direction == 'rev':
            data = encodeAPT(0x0457,1,2)
        if velocity is not None:
            self.vel_params.set(max_velocity=self.vel_to_apt(abs(velocity)))
            data = encodeAPT(0x0457,1,int(1.5+0.5*numpy.sign(velocity)))
        if data is not None:
            self.write(data, termination='')

    def go_home(self):
        """
        Initiate a homing procedure
        """
        data = encodeAPT(0x0443, 1, 0)
        self.write(data, termination='')
        self._wait_for_endofmove()

    def get_angle(self):
        """
        Return the current angle in deg
        """
        rep = self.ask(encodeAPT(0x0411, 1, 0))
        return self.inc_to_deg(rep)

    def identify(self):
        data = encodeAPT(0x0223, 0, 0)
        self.write(data)

    def _create_devs(self):

        self.pos_counter = APTDevice(req_id=0x0411, get_fmt='Hi', get_names=['chan_id', 'counter'], get_by_default='counter', autoinit=False, trig=True)
        self.enc_counter = APTDevice(req_id=0x040A, get_fmt='Hi', get_names=['chan_id', 'counter'], get_by_default='counter', autoinit=False, trig=True)

        self.vel_params = APTDevice(set_id=0x0413, req_id=0x0414, get_id=0x0415,get_fmt='HLLL', get_names=['chan_id','min_velocity','acceleration','max_velocity'],
                                    get_by_default='max_velocity', autoinit=False, trig=False, doc = 'velocity parameters, positions, velocities and accelerations are in apt format')
        self.home_params = APTDevice(set_id=0x0440, req_id=0x0441, get_id=0x0442,get_fmt='HHHLI', get_names=['chan_id','home_dir','lim_switch','home_vel','offset_dist'],
                                     get_by_default='home_vel',autoinit=False,trig=True, doc = 'homing parameters, positions, velocities and accelerations are in apt format')
        self.jog_params = APTDevice(set_id=0x0416, req_id=0x0417, get_id=0x0418,get_fmt='HHllllH', get_names=['chan_id', 'jog_mode', 'jog_step_size', 'jog_min_velocity', 'jog_acceleration', 'jog_max_velocity', 'stop_mode']
                                    , get_by_default='jog_step_size', autoinit=False, trig=True, doc = 'jog parameters, positions, velocities and accelerations are in apt format')

        def scaled_get():
            return self.inc_to_deg(self.pos_counter.get()['counter'])
        self.angle = FunctionWrap(
            setfunc=self.move_abs,
            getfunc=scaled_get,
            autoinit=False
        )

        super(ThorlabsKDC101, self)._create_devs()
