import struct
from time import sleep


from pyHegel.instruments_base import visaInstrument, scpiDevice, ChoiceStrings, BaseDevice, ChoiceBase, \
    visaInstrumentAsync, ReadvalDev, decode_float64_avg, BaseInstrument, locked_calling
from pyHegel.instruments_registry import register_instrument

# Message id (non exhaustive)
MGMSG_MOD_IDENTIFY = 0x0223
MGMSG_MOD_SET_CHANENABLESTATE = 0x0210
MGMSG_MOD_REQ_CHANENABLESTATE = 0x0211
MGMSG_MOD_GET_CHANENABLESTATE = 0x0212
MGMSG_HW_START_UPDATEMSGS = 0x0011
MGMSG_HW_STOP_UPDATEMSGS = 0x0012
MGMSG_HW_REQ_INFO = 0x0005  # Sent to request hardware information from the controller
MGMSG_HW_GET_INFO = 0x0006
MGMSG_RACK_REQ_BAYUSED = 0x0060  # Sent to determine whether the specified bay in the controller is occupied.
MGMSG_RACK_GET_BAYUSED = 0x0061

MGMSG_MOT_MOVE_HOME = 0x0443  # Sent to start a home move sequence on the specified motor channel (in accordance with the home parameters above).
MGMSG_MOT_MOVE_HOMED = 0x0444  # No response on initial message, but upon completion of home sequence controller sends a "homing completed" message

MGMSG_MOT_MOVE_RELATIVE = 0x0448
MGMSG_MOT_MOVE_COMPLETED = 0x0464
MGMSG_MOT_MOVE_ABSOLUTE = 0x0453

MGMSG_MOT_MOVE_STOP = 0x0465  # Sent to stop any type of motor move (relative, absolute, homing or move at velocity) on the specified motor channel.
MGMSG_MOT_MOVE_STOPPED = 0x0466
# Source/dest id:
HOST = 0x01
MOTHER_BOARD = 0x11
BAY_0 = 0x21
BAY_1 = 0x22
GENERIC_USB = 0x50


# To load the instrument: th1 = instruments.thorlabs_power_meter('USB0::0x1313::0x8079::P1005280::INSTR')
@register_instrument('Thorlabs', 'PM100A', alias='PM100A Power Meter')
class thorlabs_power_meter(visaInstrumentAsync):
    """
    This controls the power meter console from Thorlabs
    Most useful devices:

    """

    def init(self, full=False):
        # clear event register, extended event register and error queue
        self.clear()

    # @locked_calling
    # def _current_config(self, dev_obj=None, options={}):
    #    return self._conf_helper('function', 'range', 'level', 'output_en', options)

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
                                      doc='set-get the thermopile response value in V/W', setget=True, autoinit=False)

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
                                                doc='power delta reference value in A', setget=True)
        self.power_delta_mode = scpiDevice(':SENSe:POW:REF:STATe', str_type=bool,
                                           doc='Switches to delta mode (power mode)', setget=True)

        # VOLTage

        # -------------
        # INPUTS
        # -------------

        self.filter = scpiDevice(':INPut:FILTer', choices=ChoiceStrings('ON', 'OFF'),
                                 doc='set-get the bandwidth of the photodiode input stage (ON or OFF)', setget=True,
                                 autoinit=False)

        self.th_accelerator_state = scpiDevice(':INPut:THERmopile:ACCelerator', choices=ChoiceStrings('ON', 'OFF'),
                                               doc='set-get thermopile accelerator state (ON or OFF)', setget=True,
                                               autoinit=False)

        self.th_accelerator_time = scpiDevice(':INPut:THERmopile:ACCelerator:TAU', str_type=bool,
                                              doc='set-get thermopile time constant tau_(0-63%) in s', setget=True,
                                              autoinit=False)

        self.adapter = scpiDevice(':INPut:ADAPter', choices=ChoiceStrings('PHOTodiode', 'THERmal', 'PYRo'),
                                  doc='set-get default sensor adapter type', setget=True, autoinit=False)

        # -------------
        # CONFIGURATION
        # -------------

        self.configuration = scpiDevice(setstr=':CONF:{val}', getstr='CONF?',
                                        choices=ChoiceStrings('POW', 'CURR', 'VOLT', 'PDEN', 'TEMP'),
                                        doc='set-get the current measurement configuration', setget=True,
                                        autoinit=False)

        # -------------
        # MEASUREMENTS
        # -------------

        self.fetch = scpiDevice(getstr='FETCh?', str_type=float, autoinit=False, trig=True)
        self.readval = scpiDevice(getstr='READ?', str_type=float, autoinit=False, trig=True)
        self.alias = self.readval

        super(thorlabs_power_meter, self)._create_devs()




def encodeAPT(id, param1=0, param2=0, dest_byte=GENERIC_USB, source_byte=HOST, data=None):
    if data:
        data_length = len(data)
        return struct.pack('<HHcc{0:d}s'.format(data_length), id, data_length, chr(dest_byte), chr(source_byte),data)
    else:
        return struct.pack('<Hcccc', id, chr(param1), chr(param2), chr(dest_byte), chr(source_byte))


def decodeAPT(message):
    return message

class APTDevice(BaseDevice):
    def __init__(self,setstr=None, reqstr=None, getstr=None, get_fmt=None, autoinit=True, choices=None, doc='', **kwarg):
        if setstr is None and reqstr is None:
            raise ValueError, 'At least one of setstr or reqstr needs to be specified'
        BaseDevice.__init__(self, doc=doc, autoinit=autoinit, choices=choices, get_has_check=True, **kwarg)
        self._getdev_p = reqstr
        self.get_fmt = get_fmt

    def _getdev(self, **kwarg):

        question = self._getdev_p
        data = self.instr.ask(question)

        ret = struct.unpack(self.get_fmt, data)

        return ret[2]

# th = instruments.ThorlabsKDC101('ASRL3::INSTR', skip_id_test=True, baud_rate=115200, write_termination='')
@register_instrument('Thorlabs', 'KDC101', alias='KDC101 Rotation stage')
class ThorlabsKDC101(visaInstrument):


    def do_set_Position(self, pos):
        num = int(pos * 1920)
        byte1 = num % 256
        byte2 = int(num / 256) % 256
        byte3 = int(num / 256 / 256) % 256
        byte4 = int(num / 256 / 256 / 256) % 256
        str = '\x53\x04\x06\x00\x80\x01\x01\x00' + chr(byte1) + chr(byte2) + chr(byte3) + chr(byte4)
        self.instr.write(str)

    def move(self, n_incr):
        data = struct.pack('<Hi', 1, int(n_incr))
        message = encodeAPT(0x0448, data=data)
        self.write(message)

    def stop(self, immediate = False):
        if immediate:
            stop_mode = 0x01
        else:
            stop_mode = 0x02
        message = encodeAPT(0x0465, param1=1, param2=stop_mode)
        self.write(message)

    def go_home(self):
        data = encodeAPT(0x0443, 1, 0)
        self.write(data, termination='')

    def identify(self):
        data = encodeAPT(0x0223, 0, 0)
        self.write(data)

    def _create_devs(self):

        self.pos_counter = APTDevice(reqstr="\x11\x04\x01\x00\x50\x01", get_fmt='6sHi', autoinit=False, trig=True)
        self.enc_counter = APTDevice(reqstr="\x0A\x04\x01\x00\x50\x01", get_fmt='6sHi', autoinit=False, trig=True)

        super(ThorlabsKDC101, self)._create_devs()