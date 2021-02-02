import struct

from pyHegel.instruments_base import visaInstrument, scpiDevice, ChoiceStrings, BaseDevice, ChoiceBase, \
    visaInstrumentAsync, ReadvalDev, decode_float64_avg
from pyHegel.instruments_registry import register_instrument

#Message id (non exhaustive)
MGMSG_MOD_IDENTIFY = 0x0223
MGMSG_MOD_SET_CHANENABLESTATE = 0x0210
MGMSG_MOD_REQ_CHANENABLESTATE = 0x0211
MGMSG_MOD_GET_CHANENABLESTATE = 0x0212
MGMSG_HW_START_UPDATEMSGS = 0x0011
MGMSG_HW_STOP_UPDATEMSGS = 0x0012
MGMSG_HW_REQ_INFO = 0x0005 # Sent to request hardware information from the controller
MGMSG_HW_GET_INFO = 0x0006
MGMSG_RACK_REQ_BAYUSED = 0x0060 # Sent to determine whether the specified bay in the controller is occupied.
MGMSG_RACK_GET_BAYUSED = 0x0061

MGMSG_MOT_MOVE_HOME = 0x0443 # Sent to start a home move sequence on the specified motor channel (in accordance with the home parameters above).
MGMSG_MOT_MOVE_HOMED = 0x0444 # No response on initial message, but upon completion of home sequence controller sends a "homing completed" message

MGMSG_MOT_MOVE_RELATIVE = 0x0448
MGMSG_MOT_MOVE_COMPLETED = 0x0464
MGMSG_MOT_MOVE_ABSOLUTE = 0x0453

MGMSG_MOT_MOVE_STOP = 0x0465 # Sent to stop any type of motor move (relative, absolute, homing or move at velocity) on the specified motor channel.
MGMSG_MOT_MOVE_STOPPED = 0x0466
#Source/dest id:
HOST = 0x01
MOTHER_BOARD = 0x11
BAY_0 = 0x21
BAY_1 = 0x22
GENERIC_USB = 0x50

#To load the instrument: th1 = instruments.thorlabs_power_meter('USB0::0x1313::0x8079::P1005280::INSTR')
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
        self.line_frequency= scpiDevice('SYSTem:LFRequency', str_type=int,
                                  doc='Sets the instrument\'s line frequency setting to 50 or 60Hz', autoinit=True)
        self.beeper_state = scpiDevice('SYSTem:BEEPer:STATe', str_type=bool,
                                  doc='Activate/deactivate the beeper', autoinit=False)
        self.display_brightness = scpiDevice(':DISPlay:BRIGhtness', str_type=float,
                                  doc='set-get the display birghtness.', setget=True, autoinit=False)
        # -------------
        # SENSe subsystem
        # -------------

        self.average = scpiDevice(':SENse:AVERage:COUNt', str_type=int,
                                  doc='set-get the averaging rate (1 sample takes approx 3ms)', setget=True, autoinit=True)

        # CORRection, everithing about power correction
        # {MIN, MAX, DEF, numeric value [nm]}
        self.user_attenuation = scpiDevice(':SENse:CORRection', str_type=float,
                                           doc='set-get the current user attenuation for power correction', setget=True, autoinit=False)
        self.zero_adjust = scpiDevice(':SENse:CORRection', str_type=float,
                                      doc='set-get the current user attenuation for power correction', setget=True, autoinit=False)



        self.zero_adjust_magnitude = scpiDevice(':SENse:CORRection:COLLect:ZERO:MAGNitude?', str_type=float,
                                                doc='get the magnitude obtained after the zero adjustment routine', autoinit=False)

        # {MIN, MAX, DEF, numeric value [nm]}
        self.wavelength = scpiDevice(':SENse:CORRection:WAVelength', str_type=float,
                                     doc='set-get the current wavelength for power correction', setget=True, autoinit=False)
        # {MIN, MAX, DEF, numeric value [nm]}
        self.diameter = scpiDevice(':SENse:CORRection:BEAMdiameter', str_type=float, doc='set-get the beam diameter',
                                   setget=True, autoinit=False)

        # POWer, everything about power/current or power/voltage conversion

        self.response_AW = scpiDevice(':SENse:POW:RESPonse', str_type=float,
                                      doc='set-get the photodiode response value in A/W', setget=True, autoinit=False)

        self.response_VW = scpiDevice(':SENse:POW:THERmopile:RESPonse', str_type=float,
                                      doc='set-get the thermopile response value in V/W', setget=True, autoinit=False)

        self.response_VJ = scpiDevice(':SENse:ENERgy', str_type=float,
                                      doc='set-get the pyro-detector response value in V/J', setget=True, autoinit=False)

        # CURRent, eveything about current biasing the photodiode (?)

        self.current_auto_range = scpiDevice(':SENSe:CURRent:RANGe:AUTO', str_type=bool, doc='Switches the auto-ranging function on and off', setget=True, autoinit=True)
        self.current_range = scpiDevice(':SENSe:CURRent:RANGe', str_type=float,
                                             doc='Sets the current range in A', setget=True,
                                             autoinit=True)
        self.delta_reference = scpiDevice(':SENSe:CURRent:REF', str_type=float, doc='delta reference value in A', setget=True)
        self.delta_mode = scpiDevice(':SENSe:CURRent:REF:STATe', str_type=bool, doc='Switches to delta mode', setget=True)


        # ENERgy

        # FREQuency

        # POWer

        # VOLTage

        # PEAKdetector

        # -------------
        # INPUTS
        # -------------

        self.filter = scpiDevice(':INPut:FILTer', choices=ChoiceStrings('ON', 'OFF'),
                                      doc='set-get the bandwidth of the photodiode input stage (ON or OFF)', setget=True, autoinit=False)

        self.th_accelerator_state = scpiDevice(':INPut:THERmopile:ACCelerator', choices=ChoiceStrings('ON', 'OFF'),
                                      doc='set-get thermopile accelerator state (ON or OFF)', setget=True, autoinit=False)

        self.th_accelerator_time = scpiDevice(':INPut:THERmopile:ACCelerator:TAU', str_type=bool,
                                      doc='set-get thermopile time constant tau_(0-63%) in s', setget=True, autoinit=False)

        self.adapter = scpiDevice(':INPut:ADAPter', choices=ChoiceStrings('PHOTodiode', 'THERmal', 'PYRo'),
                                      doc='set-get default sensor adapter type', setget=True, autoinit=False)

        # -------------
        # MEASUREMENTS
        # -------------

        self.fetch = scpiDevice(getstr='FETCh?', str_type=float, autoinit=False, trig=True)
        self.readval = scpiDevice(getstr='READ?', str_type=float, autoinit=False, trig=True)
        self.alias = self.readval



        super(thorlabs_power_meter, self)._create_devs()


def encodeAPT(id, param1=0, param2=0, data_length=None, dest_byte=GENERIC_USB, source_byte=HOST):
    if data_length:

        return struct.pack('HHcc', id, data_length, chr(dest_byte), chr(source_byte))
    else:
        return struct.pack('Hcccc', id, chr(param1), chr(param2), chr(dest_byte), chr(source_byte))

def decodeAPT(message):
        pass

class thAPTDevice(BaseDevice):
    # SET -> REQUEST -> GET pattern:
    # SET command is used by the host to set some parameter.
    # If then the host requires some information from the sub-module, then it may send a REQUEST for this information
    # and the sub-module responds with the GET part of the command
    # In all messages, where a parameter is longer than a single character,
    # the bytes are encoded in the Intel format, least significant byte first.

    def __init__(self,set_id = None, get_id=None, raw=False, chunk_size=None, autoinit=True, autoget=True, get_cached_init=None,
                 str_type=None, choices=None, doc='',
                 auto_min_max=False,
                 options={}, options_lim={}, options_apply=[], options_conv={},
                 extra_check_func=None, extra_set_func=None, extra_set_after_func=None,
                 ask_write_opt={}, **kwarg):
        if set_id is None and get_id is None:
            raise ValueError, 'At least one message id (for get or set) needs to be specified'
        if set_id is not None and get_id is None and autoget == False:
            # we don't have get, so we remove autoinit to prevent problems with cache and force_get (iprint)
            autoinit = False
        if isinstance(choices, ChoiceBase) and str_type is None:
            str_type = choices
        if autoinit == True:
            autoinit = 10
            test = [ True for k,v in options.iteritems() if isinstance(v, BaseDevice)]
            if len(test):
                autoinit = 1
        BaseDevice.__init__(self, doc=doc, autoinit=autoinit, choices=choices, get_has_check=True, **kwarg)



    def _setdev(self, val):
        # We only reach here if self._setdev_p is not None
        # TODO: probably a lot of things, must check scpiDevice for hints
        command = self._setdev_p
        self.instr.write(command, **self._ask_write_opt)

    def _getdev(self, **kwarg):
        command = self._getdev_p
        ret = self.instr.ask(command, raw=self._raw, chunk_size=self._chunk_size, **self._ask_write_opt)
        val = ret #TODO extract value from byte array
        return self._fromstr(val)



    def _checkdev(self, **kwarg):
        # APT submodules sends "status update messages" automatically every 100ms
        # showing among other things the position of the stage the controller is connected to

        # The base read strips newlines from the end always.
        self.instr.read(raw=True, chunk_size=None)
        pass


@register_instrument('Thorlabs', 'KDC101', alias='KDC101 Rotation stage')
class thorlabs_KDC101(visaInstrument):

    def init(self, full=False):
        # clear event register, extended event register and error queue
        self.clear()

    def _create_devs(self):
        # should create a set of instrument for each bay connected to the motherboard

        #relative rotation
        self.angle_rel = thAPTDevice()
        #absolute rotation (with homing?)
        self.angle_abs = thAPTDevice()