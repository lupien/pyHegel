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

import numpy as np
import scipy
import os.path

from ..instruments_base import visaInstrument, visaInstrumentAsync,\
                            BaseDevice, scpiDevice, MemoryDevice, ReadvalDev,\
                            ChoiceMultiple, Choice_bool_OnOff, _repr_or_string,\
                            quoted_string, quoted_list, quoted_dict, ChoiceLimits,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDev, ChoiceDevSwitch, ChoiceIndex,\
                            decode_float64, decode_float64_avg, decode_float64_meanstd,\
                            decode_uint16_bin, _decode_block_base, _decode_block_auto, decode_float64_2col,\
                            decode_complex128, sleep, locked_calling, visa_wrap, _encode_block,\
                            ChoiceSimple, _retry_wait, Block_Codec, ChoiceSimpleMap, ProxyMethod
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

from ..comp2to3 import fb

register_usb_name('Agilent Technologies', 0x0957)
register_usb_name('Keysight Technologies', 0x2A8D)

#######################################################
##    Agilent RF 33522A generator
#######################################################

#@register_instrument('Agilent Technologies', '33522A', '1.10-1.19-1.01-45-00')
#@register_instrument('Agilent Technologies', '33522A', '1.11-1.19-1.01-46-00')
#@register_instrument('Agilent Technologies', '33522A', '1.12-1.19-1.01-50-00')
#@register_instrument('Agilent Technologies', '33522A', '2.01-1.19-2.00-52-00')
@register_instrument('Agilent Technologies', '33522B', usb_vendor_product=[0x0957, 0x2C07], skip_add=True)
@register_instrument('Agilent Technologies', '33522A', usb_vendor_product=[0x0957, 0x2307], alias='33522A RF generator')
class agilent_rf_33522A(visaInstrument):
    """
    New code should use the unumbered devices (numbered device are there for compatibility.)
    The devices
    """
    def init(self, full=False):
        # This should depend on the endian type of the machine. Here we assume intel which is LSB.
        self.write('FORMat:BORDer SWAPped') # This is LSB
        super(agilent_rf_33522A, self).init(full=full)
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = ['opt=%s'%self.available_options]
        opts += self._conf_helper('ref_oscillator_current_state', 'coupled_ampl_en', 'coupled_freq_en')
        if self.coupled_freq_en.getcache():
            opts += self._conf_helper('coupled_freq_mode')
            if self.coupled_freq_mode.getcache().upper().startswith('OFF'):
                opts += self._conf_helper('coupled_freq_offset')
            else:
                opts += self._conf_helper('coupled_freq_ratio')
        curr_ch = self.current_ch.getcache()
        ch = options.get('ch', None)
        if ch is not None:
            self.current_ch.set(ch)
        opts += self._conf_helper('current_ch', 'out_en', 'ampl', 'ampl_autorange_en', 'ampl_unit', 'offset',
                                  'volt_limit_low', 'volt_limit_high', 'volt_limit_en', 'out_load_ohm', 'out_polarity',
                                  'freq', 'freq_mode', 'phase', 'mode', 'noise_bw', 'pulse_width',
                                  'mod_am_en', 'mod_am_depth_pct', 'mod_am_dssc_en', 'mod_am_src', 'mod_am_int_func', 'mod_am_int_freq',
                                  'mod_fm_en', 'mod_phase_en', 'arb_filter', 'arb_sample_rate', 'arb_advance', 'arb_wave_seq')
        self.current_ch.set(curr_ch)
        return opts + self._conf_helper(options)
    def _create_devs(self):
        opt = self.ask('*OPT?')
        opt = opt.split(',')
        if opt[0] == '010':
            tb = 'oven'
        else:
            tb = 'standard'
        if opt[1] == '002':
            extmem = True
        else:
            extmem = False
        if opt[2] == '400':
            gpib_avail = True
        else:
            gpib_avail = False
        self.available_options = {'time_base': tb}
        self.available_options['extended_mem'] = extmem
        self.available_options['gpib_installed'] = gpib_avail
        self.ref_oscillator = scpiDevice('ROSCillator:SOURce', choices=ChoiceStrings('INTernal', 'EXTernal'))
        # This is a weird one. It does not use 0 or 1 like most others. It only accepts ON or OFF
        self.ref_oscillator_auto_en = scpiDevice('ROSCillator:SOURce:AUTO', choices=Choice_bool_OnOff)
        self.ref_oscillator_current_state = scpiDevice(getstr='ROSCillator:SOURce:CURRent?', choices=ChoiceStrings('INTernal', 'EXTernal'))
        # new interface
        self.current_ch = MemoryDevice(1, min=1, max=2)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.coupled_ampl_en = devChOption('SOURce{ch}:VOLTage:COUPle', str_type=bool)
        self.ampl = devChOption('SOURce{ch}:VOLTage', str_type=float, setget=True, doc="""Minimum is 1 mVpp. Maximum = 10 Vpp. See ampl_unit device for unit type (Vrms, Vpp or dBm)""")
        self.ampl_autorange_en = devChOption('SOURce{ch}:VOLTage:RANGe:AUTO', str_type=bool, doc="When False, disables the automatic attenuator change.")
        self.offset = devChOption('SOURce{ch}:VOLTage:OFFSet', str_type=float, setget=True, doc="""Minimum is -5 V, Maximum = 5 V (but can be smaller because of ampl).""")
        self.ampl_unit = devChOption('SOURce{ch}:VOLTage:UNIT', choices=ChoiceStrings('VPP', 'VRMS', 'DBM'))
        self.volt_limit_low = devChOption('SOURce{ch}:VOLTage:LIMit:LOW', str_type=float, setget=True, doc="""Output will not go below this voltage, if limit is enabled.""")
        self.volt_limit_high = devChOption('SOURce{ch}:VOLTage:LIMit:HIGH', str_type=float, setget=True, doc="""Output will not go above this voltage, if limit is enabled.""")
        self.volt_limit_en = devChOption('SOURce{ch}:VOLTage:LIMit:STATe', str_type=bool)
        self.coupled_freq_en = devChOption('SOURce{ch}:FREQuency:COUPle', str_type=bool)
        self.coupled_freq_mode = devChOption('SOURce{ch}:FREQuency:COUPle:MODE', choices=ChoiceStrings('OFFSet', 'RATio'))
        self.coupled_freq_offset = devChOption('SOURce{ch}:FREQuency:COUPle:OFFSet', str_type=float, setget=True)
        self.coupled_freq_ratio = devChOption('SOURce{ch}:FREQuency:COUPle:RATio', str_type=float, setget=True)
        self.freq = devChOption('SOURce{ch}:FREQuency', str_type=float, setget=True, min=1e-6, max=30e6)
        # TODO handle sweep and list
        self.freq_mode = devChOption('SOURce{ch}:FREQuency:MODE', choices=ChoiceStrings('CW','LIST','SWEep','FIXed'), doc='CW and FIXED are the same. SWEep and List are not handled currently.')
        self.phase = devChOption('SOURce{ch}:PHASe', str_type=float, setget=True, min=-360, max=360, doc='Angle in degrees')
        self.mode = devChOption('SOURce{ch}:FUNCtion', choices=ChoiceStrings('SINusoid', 'SQUare', 'RAMP', 'PULSe', 'PRBS', 'NOISe', 'ARB', 'DC'))
        self.noise_bw = devChOption('SOURce{ch}:FUNCtion:NOISe:BANDwidth', str_type=float, setget=True, min=0.001, max=30e6)
        self.pulse_width = devChOption('SOURce{ch}:FUNCtion:PULSe:WIDTh', str_type=float, min=16e-9, max=1e6) # s
        self.out_en = devChOption('OUTPut{ch}', str_type=bool)
        self.out_load_ohm = devChOption('OUTPut{ch}:LOAD', str_type=float, setget=True, min=1, doc="max is 10 kOhm. For High impedance (INFinity) use 9.9e37")
        self.out_polarity = devChOption('OUTPut{ch}:POLarity', choices=ChoiceStrings('NORMal', 'INVerted'))

        self.arb_filter = devChOption('SOURce{ch}:FUNCtion:ARBitrary:FILTer', choices=ChoiceStrings('OFF', 'NORMal', 'STEP'))
        self.arb_advance = devChOption('SOURce{ch}:FUNCtion:ARBitrary:ADVance', choices=ChoiceStrings('TRIGger', 'SRATe'))
        self.arb_sample_rate = devChOption('SOURce{ch}:FUNCtion:ARBitrary:SRATe', str_type=float, setget=True)
        # with firmware 5.02, it needs to can be r"int:\builtin/exp_fall.arb"
        #  The first \ is required, otherwise there is no error (no beep) but the waveform is not displayed properly on the instrument
        #   but is seems to be loaded.
        # Also it will possibly crash (lock up) the instrument (it was like that also in firmware 1.11) when pressing
        # some controls while in this state.
        # force the fix
        class fixed_quoted_string(quoted_string):
            def tostr(self, unquoted_str):
                fixed = unquoted_str.replace('/', '\\') # could limit to first element only
                return super(fixed_quoted_string, self).tostr(fixed)
        self.arb_wave_seq = devChOption('SOURce{ch}:FUNCtion:ARBitrary', str_type=fixed_quoted_string(), doc=
            r"""
                Select one of the loaded file (.arb, .barb or .seq) to use.
                Filename needs to be either the name given for arb_send_data or
                the absolute name like: int:/builtin/exp_fall.arb
            """)
        self.arb_npoints = devChOption(getstr="SOURce{ch}:DATA:ATTRibute:POINts?", str_type=int)
        self.arb_loaded_files = devChOption(getstr="SOURce{ch}:DATA:VOLatile:CATalog?", str_type=quoted_list(sep='","'))
        self.arb_free_space = devChOption(getstr="SOURce{ch}:DATA:VOLatile:FREE?", str_type=int, doc='free space available in number of points (internally allocated in blocks of 128 points.)')

        # Modulations parameters  TODO  missing modulations are BPSK FSKey PWM
        self.mod_am_en = devChOption('SOURce{ch}:AM:STATe', str_type=bool)
        self.mod_am_depth_pct = devChOption('SOURce{ch}:AM:DEPTh', str_type=float, min=0, max=120, setget=True)
        self.mod_am_dssc_en = devChOption('SOURce{ch}:AM:DSSC', str_type=bool, doc="DSSC = Double Sideband Suppressed Carrier")
        self.mod_am_src = devChOption('SOURce{ch}:AM:SOURce', choices=ChoiceStrings('INTernal', 'EXTernal', 'CH1', 'CH2'), doc='External input is +- 5V')
        self.mod_am_int_func = devChOption('SOURce{ch}:AM:INTernal:FUNCtion', choices=ChoiceStrings('SINusoid', 'SQUare', 'RAMP', 'NRAMp', 'TRIangle', 'NOISe', 'PRBS', 'ARB'))
        self.mod_am_int_freq = devChOption('SOURce{ch}:AM:INTernal:FREQuency', str_type=float, min=1e-6, setget=True)

        self.mod_fm_en = devChOption('SOURce{ch}:FM:STATe', str_type=bool)
        self.mod_phase_en = devChOption('SOURce{ch}:PM:STATe', str_type=bool)

        # Older interface
        # voltage unit depends on front panel/remote selection (sourc1:voltage:unit) vpp, vrms, dbm
        self.ampl1 = scpiDevice('SOUR1:VOLT', str_type=float, min=0.001, max=10)
        self.freq1 = scpiDevice('SOUR1:FREQ', str_type=float, min=1e-6, max=30e6)
        self.pulse_width1 = scpiDevice('SOURce1:FUNCtion:PULSe:WIDTh', str_type=float, min=16e-9, max=1e6) # s
        self.offset1 = scpiDevice('SOUR1:VOLT:OFFS', str_type=float, min=-5, max=5)
        self.phase1 = scpiDevice('SOURce1:PHASe', str_type=float, min=-360, max=360) # in deg unless changed by unit:angle
        self.mode1 = scpiDevice('SOUR1:FUNC') # SIN, SQU, RAMP, PULS, PRBS, NOIS, ARB, DC
        self.out_en1 = scpiDevice('OUTPut1', str_type=bool) #OFF,0 or ON,1
        self.ampl2 = scpiDevice('SOUR2:VOLT', str_type=float, min=0.001, max=10)
        self.freq2 = scpiDevice('SOUR2:FREQ', str_type=float, min=1e-6, max=30e6)
        self.pulse_width2 = scpiDevice('SOURce2:FUNCtion:PULSe:WIDTh', str_type=float, min=16e-9, max=1e6) # s
        self.phase2 = scpiDevice('SOURce2:PHASe', str_type=float, min=-360, max=360) # in deg unless changed by unit:angle
        self.offset2 = scpiDevice('SOUR2:VOLT:OFFS', str_type=float, min=-5, max=5)
        self.mode2 = scpiDevice('SOUR2:FUNC') # SIN, SQU, RAMP, PULS, PRBS, NOIS, ARB, DC
        self.out_en2 = scpiDevice('OUTPut2', str_type=bool) #OFF,0 or ON,1

        self.remote_cwd = scpiDevice('MMEMory:CDIRectory', str_type=quoted_string(),
                             doc=r"""
                                  instrument default is INT:/
                                  Available drives are INT or USB.
                                  You can use / (if you are using \, make sure to use raw string r"" or
                                  double them \\)
                                  """)

        self.alias = self.freq
        # This needs to be last to complete creation
        super(agilent_rf_33522A, self)._create_devs()
    def arb_sync(self):
        self.write('FUNCtion:ARBitrary:SYNChronize')
    def phase_sync(self):
        self.write('PHASe:SYNChronize')
    @locked_calling
    def phase_ref(self, ch=None):
        if ch is not None:
            self.current_ch.set(ch)
        ch=self.current_ch.getcache()
        self.write('SOURce{ch}:PHASe:REFerence'.format(ch=ch))
    def get_file(self, remote_file, local_file=None):
        """
            Obtain the file remote_file from the analyzer and save it
            on this computer as local_file if given, otherwise returns the data
        """
        s = self.ask('MMEMory:UPLoad? "%s"'%remote_file, raw=True)
        s = _decode_block_base(s)
        if local_file:
            with open(local_file, 'wb') as f:
                f.write(s)
        else:
            return s
    def remote_ls(self, remote_path=None, show_space=False, show_size=False):
        """
            if remote_path is None, get catalog of device remote_cwd.
            Directories are show with an ending /
            returns None for empty and invalid directories.
            The drives are called INT: and USB:.
            if show_space is enable, it returns
               file_list, used, free
            if show_size is enabled, file_list are tuples of name, size
        """
        extra = ""
        if remote_path:
            extra = ' "%s"'%remote_path
        res = self.ask('MMEMory:CATalog?'+extra)
        p = res.split(',', 2)
        used = int(p[0])
        free = int(p[1])
        if len(p) <= 2:
            return None
        # Here I presume no " or , can show up inside the filename.
        lst = p[2].strip('"').rstrip('"').split('","')
        outlst = []
        for l in lst:
            fname, ftype, fsize = l.rsplit(',', 2)
            fsize = int(fsize)
            if ftype == 'FOLD':
                fname += '/'
            if show_size:
                outlst.append((fname, fsize))
            else:
                outlst.append(fname)
        if show_space:
            return outlst, used, free
        return outlst

    @locked_calling
    def send_file(self, dest_file, local_src_file=None, src_data=None, overwrite=False):
        """
            dest_file: is the file name (absolute or relative to device remote_cwd)
                       you can use / to separate directories
            overwrite: when True will skip testing for the presence of the file on the
                       instrument and proceed to overwrite it without asking confirmation.
            Use one of local_src_file (local filename) or src_data (data string)
        """
        if not overwrite:
            # split seeks both / and \
            directory, filename = os.path.split(dest_file)
            ls = self.remote_ls(directory)
            if ls:
                ls = [s.lower() for s in ls]
                if filename.lower() in ls:
                    raise RuntimeError('Destination file already exists. Will not overwrite.')
        if src_data is local_src_file is None:
            raise ValueError('You need to specify one of local_src_file or src_data')
        if src_data and local_src_file:
            raise ValueError('You need to specify only one of local_src_file or src_data')
        if local_src_file:
            with open(local_src_file, 'rb') as f:
                src_data = f.read()
        data_str = _encode_block(src_data)
        # manually add terminiation to prevent warning if data already ends with termination
        self.write('MMEMory:DOWNload:FNAMe "%s"'%dest_file)
        self.write(b'MMEMory:DOWNload:DATA %s\n'%data_str, termination=None)
    @locked_calling
    def arb_load_file(self, filename, ch=None, clear=False, load=True):
        """
        Load a file (.arb, .barb or .seq) on the device into the channel.
             If file is already loaded, this will fail unless clear=True.
        clear when True erases all loaded files from the channel volatile memory.
        load  when True (default), it activates the data as the current waveform
        Note that int:/builtin/exp_rise.arb is always loaded, it is the default curve after a clear
            so it can never be loaded directly.
        """
        if ch is not None:
            self.current_ch.set(ch)
        ch=self.current_ch.getcache()
        if clear:
            self.write('SOURce{ch}:DATA:VOLatile:CLEar'.format(ch=ch))
        self.write('MMEMory:LOAD:DATA{ch} "{filename}"'.format(ch=ch, filename=filename))
        if load:
            self.arb_wave_seq.set(filename)
    @locked_calling
    def arb_save_file(self, filename, ch=None):
        """Save a file (.arb, .barb or .seq) on the device from the channel"""
        if ch is not None:
            self.current_ch.set(ch)
        ch=self.current_ch.getcache()
        self.write('MMEMory:STORe:DATA{ch} "{filename}"'.format(ch=ch, filename=filename))
    # TODO add send sequence: SOURce{ch}:DATA:SEQuence
    @locked_calling
    def arb_send_data(self, name, data, ch=None, clear=False, load=True, floats=None, csv=False):
        """
        name is needed to be used with arb_load_file (a string of up to 12 characters, no extension needed).
             If name already exists, this will fail unless clear=True.
        data can be a numpy array of float32 (from -1.0 to 1.0) or of int16 (from -32768 to 32767)
              It can also be a string (bytes), but then floats needs to be specified.
              There needs to be at least 8 data points.
        clear when True erases all loaded files from the channel volatile memory.
               (same as clear_volatile_mem)
        floats when True/False, overrides the type detection. It is necessary when providing a string for the data.
               True for floats, False for int16.
        load  when True (default), it activates the data as the current waveform.
              Note that this will change the amplitude/offset to 100 mVpp/0.
              To load it yourself use the arb_wave_seq device.
        csv when True, the the input data should be a string with comma separated values. floats needs to be specified.
        """
        if ch is not None:
            self.current_ch.set(ch)
        ch=self.current_ch.getcache()
        if isinstance(data, bytes):
            if floats is None:
                raise ValueError('floats needs to be specified (True/False')
        elif data.dtype == np.float32 or data.dtype == np.int16:
            if floats is None:
                floats = True if data.dtype == np.float32 else False
        else:
            if floats is None:
                raise ValueError('Unknown data type and floats is not specified')
            print('Unknown data type in arb_send_data. Trying anyway...')
        if csv:
            data_str = data
        else:
            data_str = _encode_block(data)
        if clear:
            self.clear_volatile_mem()
        if floats:
            scpi_path_base = 'SOURce{ch}:DATA:ARBitrary'
        else:
            scpi_path_base = 'SOURce{ch}:DATA:ARBitrary:DAC'
        self.write(fb( (scpi_path_base + ' {name},').format(ch=ch, name=name)) + data_str + b'\n', termination=None)
        if load:
            self.arb_wave_seq.set(name)

    @locked_calling
    def clear_volatile_mem(self, ch=None):
        if ch is not None:
            self.current_ch.set(ch)
        ch=self.current_ch.getcache()
        self.write('SOURce{ch}:DATA:VOLatile:CLEar'.format(ch=ch))

#######################################################
##    Agilent EPM power meter
#######################################################

#@register_instrument('Agilent Technologies', 'N1913A', 'A1.01.07')
@register_instrument('Agilent Technologies', 'N1913A', usb_vendor_product=[0x0957, 0x5418], alias='N1913A EPM power meter')
class agilent_PowerMeter(visaInstrumentAsync):
    """
    This instrument is for Agilent N1913A EPM seris power meter with a N8487A
    average power sensor.

    Get data with readval (force read of new data) or fetch (gets possibly old data)
    Note that only the upper display upper line is read.

    gain_ch_{dB,en} applies a correction to the channel data.
    gain_{dB,en} applies a correction to the display (measurement menu)
                 (goes with relative menu)
    cset1_en is for manual sensor calibration (cannot be turn on for our sensor
             because it already provides a calibration, see th CF percent value on the
             display that depends on frequency. It is 100% at 50 MHz)
    cset2_en is a second manual calibration (called FDO table in channel/offsets)
             to compensate for the circuit used. It also depends on the frequency.
             You can read this correction value with freq_offset
    """
    # As of (firmware A1.01.07) the relative value cannot be read.
    # The instrument has 4 display position (top upper, top lower, ...)
    #  1=upper window upper meas, 2=lower upper, 3=upper lower, 4=lower lower
    # They are not necessarily active on the display but they are all used for
    # average calculation and can all be used for reading data.
    def __init__(self, visa_addr):
        # The SRQ for this intrument only works on gpib
        # for lan or usb we need to revert to polling.
        # That is because the read_status_byte seems to always return 0
        # in those cases. So we use *stb? and polling instead.
        self._status_use_stb = False # Used for init
        super(agilent_PowerMeter, self).__init__(visa_addr, poll='not_gpib')
        if self._async_polling:
            self._status_use_stb = True
    def read_status_byte(self):
        if self._status_use_stb:
            return int(self.ask('*STB?'))
        else:
            return super(agilent_PowerMeter, self).read_status_byte()
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('range', 'range_auto_en', 'unit',
                                 'gain_en', 'hold_mode', 'relative_en', 'average_en',
                                 'average_cnt', 'average_cnt_auto', 'average_step_detection',
                                 'cset1_en', 'cset2_en', 'trig_src',
                                 'sensor_calib_date', 'sensor_type', 'sensor_serialno',
                                 'linear_corr_type', 'meas_rate',
                                 'gain_ch_dB', 'gain_ch_en',
                                 'duty_cycle_percent', 'duty_cycle_en',
                                 'freq', 'freq_offset', 'freq_offset_unit',
                                 options)
    @locked_calling
    def _async_trig(self):
        self.trig_delay_en.set(True)
        self.cont_trigger.set(False)
        super(agilent_PowerMeter, self)._async_trig()
    def set_relative(self):
        self.write('CALCulate1:RELative:AUTO ONCE')
    def _create_devs(self):
        # voltage unit depends on front panel/remote selection (sourc1:voltage:unit) vpp, vrms, dbm
        self.range = scpiDevice('SENSe:POWer:AC:RANGe', str_type=int, min=0, max=1)
        self.config = scpiDevice('CONFigure1')
        #self.resolution = scpiDevice('CONFig1 DEF,{val}', str_type=int, min=1, max=4)
        self.resolution = scpiDevice('DISPlay:WINDow1:NUMeric1:RESolution', str_type=int, min=1, max=4)
        self.range_auto_en = scpiDevice('SENSe:POWer:AC:RANGe:AUTO', str_type=bool)
        self.unit = scpiDevice('UNIT:POWer', choices=ChoiceStrings('DBM', 'W'))
        self.gain_dB = scpiDevice('CALCulate1:GAIN', str_type=float, min=-100, max=100)
        self.gain_en = scpiDevice('CALCulate1:GAIN:STATe', str_type=bool)
        self.hold_mode = scpiDevice('CALCulate1:HOLD:STAT', choices=ChoiceStrings('OFF', 'MIN', 'MAX'))
        self.relative_en = scpiDevice('CALCulate1:RELative:STATe', str_type=bool)
        #SENSE subsystem
        self.average_cnt = scpiDevice('AVERage:COUNt', str_type=int, min=1, max=1024)
        self.average_cnt_auto = scpiDevice('AVERage:COUNt:AUTO', str_type=bool)
        self.average_step_detection = scpiDevice('AVERage:SDETect', str_type=bool)
        self.average_en = scpiDevice('AVERage', str_type=bool)
        #self.gain_factor_pct = scpiDevice('CORRection:CFACtor', str_type=float, min=1., max=150.)
        self.cset1_en = scpiDevice('CORRection:CSET1:STATe', str_type=bool)
        self.cset2_en = scpiDevice('CORRection:CSET2:STATe', str_type=bool)
        self.freq = scpiDevice('FREQuency', str_type=float, min=1e3, max=1e12)
        self.freq_offset = scpiDevice(getstr='CORRection:FDOFfset?', str_type=float)
        self.freq_offset_unit = scpiDevice('CORRection:FDOFfset:UNIT', choices=ChoiceStrings('PCT', 'DB'))
        self.duty_cycle_percent = scpiDevice('CORRection:DCYCle', str_type=float, min=.001, max=99.999)
        self.duty_cycle_en = scpiDevice('CORRection:DCYCle:STATe', str_type=bool)
        self.gain_ch_dB = scpiDevice('CORRection:GAIN2', str_type=float, min=-100, max=100)
        self.gain_ch_en = scpiDevice('CORRection:GAIN2:STATe', str_type=bool)
        self.meas_rate = scpiDevice('MRATe', choices=ChoiceStrings('NORMal', 'DOUBle', 'FAST'))
        self.linear_corr_type = scpiDevice('V2P', choices=ChoiceStrings('ATYPe', 'DTYPe'))
        self.sensor_calib_date = scpiDevice(getstr='SERVice:SENSor:CDATe?')
        self.sensor_calib_place = scpiDevice(getstr='SERVice:SENSor:CPLace?')
        self.sensor_type = scpiDevice(getstr='SERVice:SENSor:TYPE?')
        self.sensor_serialno = scpiDevice(getstr='SERVice:SENSor:SNUMber?')
        self.raw_reading = scpiDevice(getstr='SERVice:SENSor:RADC?', autoinit=False, trig=True)
        #TRIGGER block
        self.trig_src = scpiDevice('TRIGger:SOURce', choices=ChoiceStrings('BUS', 'EXTernal', 'HOLD', 'IMMediate'))
        self.trig_delay_en = scpiDevice('TRIGger:DELay:AUTO', str_type=bool)
        self.cont_trigger = scpiDevice('INITiate:CONTinuous', str_type=bool)
        #READ, FETCH
        self.fetch = scpiDevice(getstr='FETCh?',str_type=float, autoinit=False, trig=True) #You need to read some data first.
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval
        # This needs to be last to complete creation
        super(agilent_PowerMeter, self)._create_devs()


#######################################################
##    Agilent PSG generator
#######################################################

#@register_instrument('Agilent Technologies', 'E8257D', 'C.06.16')
@register_instrument('Agilent Technologies', 'E8257D', alias='E8257D PSG Generator')
class agilent_rf_PSG(visaInstrument):
    """
    This controls a PSG signal generetor
    Most useful devices:
        ampl
        ampl_unit
        rf_en
        mod_en
        freq_cw
    The alc devices refer to automatic level (amplitude) control.
    Available methods:
        phase_sync
    """
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        # TODO Get the proper config
        gen = self._conf_helper('oscillator_source', 'rf_en', 'ampl', 'ampl_unit', 'amp_flatness_corr_en',
                                 'ampl_offset_db', 'ampl_reference_dbm', 'ampl_reference_en',
                                 'ampl_protection', 'ampl_mode', 'ampl_start', 'ampl_stop',
                                 'alc_en', 'alc_source', 'alc_bw', 'alc_bw_auto_en',
                                 'attenuation_db', 'attenuation_auto_en', 'amp_flatness_corr_en',
                                 'output_blanking_en', 'output_blanking_auto_en',
                                 'freq_mode', 'freq_cw', 'freq_start', 'freq_stop',
                                 'freq_multiplier', 'freq_offset', 'freq_offset_en', 'freq_reference', 'freq_reference_en',
                                 'status_freq', 'status_power', 'status_base', 'status_mod', 'status_cal')
        if self._installed_mod:
            gen += self._conf_helper('phase', 'mod_en', 'mod_am_en', 'mod_fm_en', 'mod_phase_en',
                                 'mod_am_freq', 'mod_am_shape', 'mod_am_depth', 'mod_am_noise_type')
        if self._installed_lbfilter:
            gen +=  self._conf_helper('low_band_filter')
        if self._installed_pulse:
            gen += self._conf_helper('mod_pulse_en', 'mod_pulse_period', 'mod_pulse_width')
        return gen + ['installed_options=%s'%self.installed_options] + self._conf_helper(options)
    def _create_devs(self):
        self.installed_options = self.ask('*OPT?')
        inst = self.installed_options.split(',')
        self._installed_mod = True if 'UNT' in inst else False # AM, FM, Phase ad lf_out
        self._installed_lbfilter = True if '1EH' in inst or '521' in inst else False
        self._installed_pulse = True if 'UNU' in inst or 'UNW' in inst else False

        self.oscillator_source = scpiDevice(getstr=':ROSCillator:SOURce?', str_type=str)
        self.rf_en = scpiDevice(':OUTPut', str_type=bool)
        self.ampl = scpiDevice(':POWer', str_type=float, doc='unit depends on device ampl_unit', setget=True)
        self.ampl_unit = scpiDevice(':UNIT:POWer', choices=ChoiceStrings('DBM', 'DBUV', 'DBUVEMF', 'V', 'VEMF', 'DB'),
                                    doc='Note that EMF are 2x above the base unit (power arriving at infinite impedance load)')
        # unit:volt:type affects volt scale like power:alc:search:ref:level, which are not user changeable
        self.ampl_offset_db = scpiDevice(':POWer:OFFset', str_type=float, min=-200, max=+200)
        self.ampl_reference_dbm = scpiDevice(':POWer:REFerence', str_type=float, doc='This value is always in dBm')
        self.ampl_reference_en = scpiDevice(':POWer:REFerence:STATe', str_type=bool)
        self.ampl_mode = scpiDevice(':POWer:MODE', choices=ChoiceStrings('FIXed', 'LIST'))
        #self.ampl_optimize_lownoise = scpiDevice(':POWer:NOISe', str_type=bool)
        self.ampl_protection = scpiDevice(':POWer:PROTection', str_type=bool, doc='When enabled, sets the attenuation to maximum when performing a power search. Could decrease the life of the attenuator.')
        self.ampl_start = scpiDevice(':POWer:STARt', str_type=float, doc='unit depends on device ampl_unit', setget=True)
        self.ampl_stop = scpiDevice(':POWer:STOP', str_type=float, doc='unit depends on device ampl_unit', setget=True)
        # TODO handle the search stuff for when alc is off
        self.alc_en = scpiDevice(':POWer:ALC', str_type=bool)
        self.alc_source = scpiDevice(':POWer:ALC:SOURce', choices=ChoiceStrings('INTernal', 'DIODe'))
        # The alc_bw don't seem to have a front panel control. It might not do anything for the
        # generator N5183A we used.
        self.alc_bw = scpiDevice(':POWer:ALC:BANDwidth', str_type=float)
        self.alc_bw_auto_en = scpiDevice(':POWer:ALC:BANDwidth:AUTO', str_type=bool)
        self.attenuation_db = scpiDevice(':POWer:ATTenuation', str_type=float, min=0, max=15, setget=True)
        self.attenuation_auto_en = scpiDevice(':POWer:ATTenuation:AUTO', str_type=bool)
        self.amp_flatness_corr_en = scpiDevice(':CORRection', str_type=bool)
        self.output_blanking_en = scpiDevice(':OUTPut:BLANKing:STATe', str_type=bool)
        self.output_blanking_auto_en = scpiDevice(':OUTPut:BLANKing:AUTO', str_type=bool)
        self.freq_mode = scpiDevice(':FREQuency:MODE', choices=ChoiceStrings('CW', 'FIXed', 'LIST'), doc='CW and FIXed are the same, LIST means sweeping')
        minfreq = float(self.ask(':FREQ? min'))
        maxfreq = float(self.ask(':FREQ? max'))
        self.freq_cw = scpiDevice(':FREQuency', str_type=float, min=minfreq, max=maxfreq)
        self.freq_center = scpiDevice('FREQuency:CENTer', str_type=float, min=minfreq, max=maxfreq)
        self.freq_start = scpiDevice('FREQuency:STARt', str_type=float, min=minfreq, max=maxfreq)
        self.freq_stop = scpiDevice('FREQuency:STOP', str_type=float, min=minfreq, max=maxfreq)
        # TODO SPAN range is probably something else
        self.freq_span = scpiDevice('FREQuency:SPAN', str_type=float, min=0, max=maxfreq)
        self.freq_multiplier = scpiDevice(':FREQuency:MULTiplier', str_type=float, min=-1000, max=1000, doc='The range is -1000 to -0.001 and 0.001 to 1000')
        self.freq_offset = scpiDevice(':FREQuency:OFFSet', str_type=float, min=-200e9, max=200e9)
        self.freq_offset_en = scpiDevice(':FREQuency:OFFSet:STATe', str_type=bool)
        self.freq_reference = scpiDevice(':FREQuency:REFerence', str_type=float, min=0, max=maxfreq)
        self.freq_reference_en = scpiDevice(':FREQuency:REFerence:STATe', str_type=bool)
        self.phase = scpiDevice(':PHASe', str_type=float, min=-3.14, max=3.14, doc='Adjust phase arounf ref. In rad.')
        # TODO handle the marker stuff
        if self._installed_lbfilter:
            self.low_band_filter = scpiDevice('LBFilter', str_type=bool)
        if self._installed_mod:
            # mod_en might also be required for pure _installed _pulse.
            self.mod_en = scpiDevice(':OUTPut:MODulation:STATe', str_type=bool)
            self.mod_am_en = scpiDevice(':AM:STATe', str_type=bool)
            self.mod_am_freq = scpiDevice(':AM:INTernal:FREQuency', str_type=float, min=0.5, max = 1e6, setget=True, doc="Frequency of the modulation. From 0 to 1MHz if mod_am_shape is 'sine'; 0 to 100KHz else.")
            self.mod_am_depth = scpiDevice(':AM:DEPTh:LINear', str_type=float, min=0, max = 100, setget=True, doc='Modulation depth in percent')
            self.mod_am_shape = scpiDevice(':AM:INTernal:FUNCtion:SHAPe', choices=ChoiceStrings('SINE', 'SQUare', 'TRIangle', 'NOISe'), doc="Shape of the modulation")
            self.mod_am_noise_type = scpiDevice(':AM:INTernal:FUNCtion:NOISE', choices=ChoiceStrings('GAUSsian','UNIForm'), doc="The noise profile used if mod_am_shape is set to 'noise'")
            self.mod_fm_en = scpiDevice(':FM:STATe', str_type=bool)
            self.mod_phase_en = scpiDevice(':PM:STATe', str_type=bool)
        if self._installed_pulse:
            self.mod_pulse_en = scpiDevice(':PULM:STATe', str_type=bool)
            self.mod_pulse_period = scpiDevice(':PULM:INTernal:PERiod', str_type=float, min=10e-9, max = 42, setget=True, doc="Pulse period in s.")
            self.mod_pulse_width = scpiDevice(':PULM:INTernal:PWIDth', str_type=float, min=10e-9, max = 42-20e-9, setget=True, doc="Pulse width duration in s.")
        self.status_power = scpiDevice(getstr='STATus:QUEStionable:POWer:CONDition?', str_type=int, doc="""\
            bit 0 (1): Reverse protection tripped
                1 (2): Unleveled
                2 (4): IQ mod Overdrive
                3 (8): lowband detector fault
            """)
        self.status_freq = scpiDevice(getstr='STATus:QUEStionable:FREQuency:CONDition?', str_type=int, doc="""\
            bit 0 (1): Synth unlocked
                1 (2): 10 MHz ref unlocked
                2 (4): 1 GHz ref unlocked
                3 (8): baseband unlocked
                5 (32): Sampler loop unlocked
                6 (64): YO loop unlocked
            """)
        self.status_mod = scpiDevice(getstr='STATus:QUEStionable:MODulation:CONDition?', str_type=int, doc="""\
            bit 0 (1): Modulation 1 undermod
                1 (2): Modulation 1 overmod
                2 (4): Modulation 2 undermod
                3 (8): Modulation 2 overmod
                4 (16): Modulation uncalibrated
            """)
        self.status_cal = scpiDevice(getstr='STATus:QUEStionable:CALibration:CONDition?', str_type=int, doc=u"""\
            bit 0 (1): I/Q calibration failure
                1 (2): DCFM/DCΦM Zero Failure
            """)
        self.status_base = scpiDevice(getstr='STATus:QUEStionable:CONDition?', str_type=int, doc="""\
            bit 3 (8):  power summary bit
                4 (16): oven cold
                5 (32): frequency summary bit
                7 (128): modulation summary bit
                8 (256): calibration summary bit
                9 (512): Self test error
            """)
        self.alias = self.freq_cw
        # This needs to be last to complete creation
        super(agilent_rf_PSG, self)._create_devs()
    def phase_sync(self):
        """
        Sets the current output phase as a zero reference.
        """
        self.write('PHASe:REFerence')


#######################################################
##    Agilent MXG generator
#######################################################

#@register_instrument('Agilent Technologies', 'N5183A', 'A.01.70')
@register_instrument('Agilent Technologies', 'N5183A', usb_vendor_product=[0x0957, 0x1F01], alias='N5183A MXG Generator')
class agilent_rf_MXG(agilent_rf_PSG):
    """
    This controls a MXG signal generetor
    Most useful devices:
        ampl
        ampl_unit
        rf_en
        mod_en
        freq_cw
    The alc devices refer to automatic level (amplitude) control.
    Available methods:
        phase_sync
    """
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        # TODO Get the proper config
        return self._conf_helper('oscillator_source', 'rf_en', 'ampl', 'ampl_unit', 'amp_flatness_corr_en',
                                 'ampl_offset_db', 'ampl_reference_dbm', 'ampl_reference_en', 'ampl_min_lim',
                                 'ampl_protection', 'ampl_mode', 'ampl_start', 'ampl_stop', 'ampl_user_max', 'ampl_user_max_en',
                                 'alc_en', 'alc_source', 'alc_bw', 'alc_bw_auto_en',
                                 'attenuation_db', 'attenuation_auto_en', 'amp_flatness_corr_en',
                                 'output_blanking_en', 'output_blanking_auto_en',
                                 'freq_mode', 'freq_cw', 'freq_low_spurs_en', 'freq_start', 'freq_stop',
                                 'freq_multiplier', 'freq_offset', 'freq_offset_en', 'freq_reference', 'freq_reference_en',
                                 'phase', 'mod_en', 'mod_am_en', 'mod_fm_en', 'mod_phase_en', 'mod_pulse_en', options)
    def _create_devs(self):
        self.ampl_min_lim = scpiDevice(':POWer:MINimum:LIMit', choices=ChoiceStrings('LOW', 'HIGH'))
        self.ampl_user_max = scpiDevice(':POWer:USER:MAX', str_type=float, doc='unit depends on device ampl_unit', setget=True)
        self.ampl_user_max_en = scpiDevice(':POWer:USER:ENABle', str_type=bool)
        self.freq_low_spurs_en = scpiDevice(':FREQuency:LSPurs:STATe', str_type=bool)
        # This needs to be last to complete creation
        super(agilent_rf_MXG, self)._create_devs()
    def phase_sync(self):
        """
        Sets the current output phase as a zero reference.
        """
        self.write('PHASe:REFerence')


#######################################################
##    Agilent multimeter
#######################################################

#@register_instrument('Agilent Technologies', '34410A', '2.35-2.35-0.09-46-09')
#@register_instrument('Keysight Technologies', '34465A', 'A.03.00-02.40-03.00-00.52-04-01')
@register_instrument('Keysight Technologies', '34465A', usb_vendor_product=[0x2A8D, 0x0101], alias='34465A multimeter')
@register_instrument('Agilent Technologies', '34410A', usb_vendor_product=[0x0957, 0x0607], alias='34410A multimeter')
class agilent_multi_34410A(visaInstrumentAsync):
    """
    This controls the agilent digital multimeters (both 34410A and 34465A).
    Note that most of the devices requires a proper selection of the
    mode first. They can behave differently in various mode.

    Important devices:
     readval  (default alias), same as initiating a measurement, waiting then fetch
     fetch
     fetch_all   (returns more than one value when count >1)
     fetch_std   (returns the standard deviation when count >1)
     mode
     aperture
     aperture_en
     nplc
     sample_count
     range
     autorange
     zero
    Useful method:
     set_long_avg  To average for even longer than 1s (controls aperture and sample_count)
     show_long_avg To see the current averaging settings.

    Do NOT use the mode parameter of devices (like fetch) when creating
    files (sweep, trace, ...) because the headers in the file might be incorrect.
    Set it first.

    """
    #def _async_trigger_helper(self):
    #    if hasattr(self, 'init_resets_ptp'):
    #        if self.init_resets_ptp.get():
    #            self.write('DATA2:CLEar;:INITiate;*OPC')
    #            return
    #    self.write('INITiate;*OPC') # this assume trig_src is immediate for agilent multi
    def math_clear(self):
        self.write('CALCulate:CLEar')
    def math_stat_clear(self):
        self.write('CALCulate:AVERage:CLEar')
    def math_histogram_clear(self):
        self.write('CALCulate:TRANsform:HISTogram:CLEar')
    @locked_calling
    def _current_config(self, dev_obj=None, options={}, show_removed=False):
        m = self._model
        mode = self.mode.getcache()
        choices = self.mode.choices
        baselist =('mode', 'trig_src', 'trig_delay', 'trig_count',
                   'sample_count', 'sample_pretrigger_count', 'sample_src', 'sample_timer', 'trig_delayauto',
                   'line_freq', 'math_func',
                   'math_stat_en', 'math_limit_en', 'math_histogram_en', 'math_scale_en', 'math_trend_chart_en',
                   'math_smooth_en')
        math_extra = ()
        model_new = m['model_new']
        if m['model_65_70'] and self.math_smooth_en.getcache():
            math_extra += ('math_smooth_response',)
        if model_new and self.math_scale_en.getcache():
            math_extra += ('math_scale_func', 'math_scale_auto_ref_en', 'math_scale_dbm_ref_res', 'math_scale_db_ref_dbm',
                           'math_scale_gain', 'math_scale_offset', 'math_scale_scale_ref', 'math_scale_unit_en', 'math_scale_unit')
        if model_new and self.math_histogram_en.getcache():
            math_extra += ('math_histogram_range_auto_en', 'math_histogram_range_lower', 'math_histogram_range_upper', 'math_histogram_npoints')
        if mode in choices[['curr:ac', 'volt:ac']]:
            extra = ('bandwidth', 'autorange', 'range',
                     'null_en', 'null_val', 'peak_mode_en', 'secondary_meas')
            if mode in choices[['curr:ac']]:
                extra += ('range_current_terminal', 'current_switch_mode')
        elif mode in choices[['volt', 'curr']]:
            extra = ('nplc', 'aperture', 'aperture_en', 'zero', 'autorange', 'range',
                     'null_en', 'null_val', 'peak_mode_en', 'secondary_meas')
            if mode in choices[['volt']]:
                extra += ('voltdc_impedance_autoHigh',)
            elif mode in choices[['curr']]:
                extra += ('range_current_terminal', 'current_switch_mode')
        elif m['model_new'] and mode in choices[['volt:ratio']]:
            extra = ('nplc', 'aperture', 'aperture_en', 'zero', 'autorange', 'range',
                     'secondary_meas', 'voltdc_impedance_autoHigh')
        elif mode in choices[['cont', 'diode']]:
            extra = ()
        elif mode in choices[['freq', 'period']]:
            extra = ('aperture','null_en', 'null_val',  'freq_period_p_band',
                        'freq_period_autorange', 'freq_period_volt_range', 'secondary_meas')
            # 3.0 firmware seems to be in error:
            #  freq_period_timeout_auto_en does not work for period (but doc says it should)
            if mode in choices[['freq']]:
                extra += ('freq_period_timeout_auto_en',)
        elif mode in choices[['res', 'fres']]:
            extra = ('nplc', 'aperture', 'aperture_en', 'autorange', 'range', 'res_low_power_en',
                     'null_en', 'null_val', 'res_offset_comp', 'secondary_meas')
            if mode in choices[['res']]:
                extra += ('zero',)
        elif mode in choices[['cap']]:
            extra = ('autorange', 'range', 'null_en', 'null_val', 'secondary_meas')
        elif mode in choices[['temp']]:
            extra = ('nplc', 'aperture', 'aperture_en', 'null_en', 'null_val',
                     'zero', 'temperature_transducer', 'temperature_transducer_subtype',
                     'secondary_meas',  'temperature_unit')
            t_ch = self.temperature_transducer.choices
            transducer = self.temperature_transducer.getcache()
            if transducer in t_ch[['rtd', 'frtd']]:
                extra += ('temperature_transducer_rtd_ref', 'temperature_transducer_rtd_off',
                          'temperature_transducer_low_power_en')
            elif transducer in t_ch[['ther', 'fth']]:
                extra += ('temperature_transducer_low_power_en',)
            elif transducer in t_ch[['tc']]:
                extra += ('temperature_tcouple_check_en', 'temperature_tcouple_ref_temp', 'temperature_tcouple_offset',
                          'temperature_tcouple_ref_type')
        full_list = [v for v in baselist + math_extra + extra if hasattr(self, v)]
        if show_removed:
            removed_list = [v for v in baselist + math_extra + extra if not hasattr(self, v)]
            print(removed_list)
        ret = self._conf_helper(*full_list)
        ret += ['installed_options=%s'%m['options']]
        ret += self._conf_helper(options)
        return ret
    @locked_calling
    def set_long_avg(self, time, force=False):
        """
        Select a time in seconds.
        It will change the aperture accordingly (and round it to the nearest nplc
        unless force=True).
        If time is greater than 1 s, an alternative mode
        with a smaller aperture (10 nplc) and a repeat count is used. That
        mode also waits trig_delay between each count.
        In that mode, you can use fetch_std to return the statistical error
        on the measurement.
        """
        # update mode first, so aperture applies to correctly
        self.mode.get()
        line_period = 1./self.line_freq.getcache()
        if time > 1.:
            width = 10*line_period
            count = round(time/width)
            self.sample_src.set('immediate')
        else:
            count = 1
            width = time
            if not force:
                width = line_period*round(width/line_period)
        self.aperture.set(width)
        self.sample_count.set(count)
    @locked_calling
    def show_long_avg(self):
        # update mode first, so aperture applies to correctly
        self.mode.get()
        count = self.sample_count.get()
        aper_en = self.aperture_en.get()
        if aper_en:
            width = self.aperture.get()
            width_str = 'aperture=%g'%width
        else:
            line_period = 1./self.line_freq.getcache()
            nplc = self.nplc.get()
            width = nplc * line_period
            width_str = 'nplc=%g'%nplc
        count_str = ''
        if count > 1:
            count_str = ', sample_count=%i'%count
        width = width*count
        print('The full avg time is %f s (%s%s)'%(width, width_str, count_str))
        return width
    def _ptp_clear(self):
        self.write('DATA2:CLEar')
    def _secondary_fetch_getformat(self, **kwarg):
        ptp = self.secondary_meas.getcache() in ChoiceStrings('PTPeak')
        ratio = self.mode.getcache() in self.mode.choices[['volt:ratio']]
        if ptp:
            multi = ['peak_min', 'peak_max', 'peak_ptp']
        elif ratio:
            multi = ['main_V', 'sense_V']
        else:
            multi = False
        fmt = self.fetch._format
        fmt.update(multi=multi)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _secondary_fetch_getdev(self):
        ret = decode_float64(self.ask('DATA2?'))
        if len(ret) == 1:
            ret = ret[0]
        return ret
    def options(self):
        # Call after model variable is set
        m = self._model
        if m['model_new']:
            val = self.ask('SYSTem:LICense:CATalog?')
            qs = quoted_string()
            ret =  [qs(v) for v in val.split(',')]
            if ret == ['']:
                ret = []
            if 'DIG' not in ret and m['model_65_70'] and float(m['firmware']) >= 3.0:
                ret += ['DIG']
        else:
            ret = []
        return ret
    def _create_devs(self):
        idn_split = self.idn_split()
        model = idn_split['model']
        model_n = model[:5]
        model_new = model.startswith('3446') or model.startswith('3447')
        model_65_70 = model_new and model_n in ['34465', '34470']
        firmware = idn_split['firmware'].split('-')[0]
        if model_new:
            firmware = firmware.split('.', 1)[1]
        self._model = dict(model=model, model_n=model_n, model_new=model_new, model_65_70=model_65_70, firmware=firmware)
        options = self.options()
        model_DIG = 'DIG' in options
        self._model['model_DIG'] = model_DIG
        self._model['options'] = options
        # This needs to be last to complete creation
        mode_list = [ 'CURRent:AC', 'VOLTage:AC', 'CAPacitance', 'CONTinuity', 'CURRent', 'VOLTage',
          'DIODe', 'FREQuency', 'PERiod', 'RESistance', 'FRESistance', 'TEMPerature']
        if model_new:
            mode_list += ['VOLTage:RATio']
        mode_ch = ChoiceStrings(*mode_list, quotes=True)
        self.mode = scpiDevice('FUNC', choices=mode_ch)
        def devOption(lims, *arg, **kwarg):
            skip_ratio_conv = kwarg.pop('skip_ratio_conv', False)
            options = kwarg.pop('options', {}).copy()
            options_lim = kwarg.pop('options_lim', {}).copy()
            options_conv = kwarg.pop('options_conv', {}).copy()
            options.update(mode=self.mode)
            options_lim.update(mode=lims)
            def mode_conv(val, quoted_val):
                if model_new and not skip_ratio_conv:
                    if val in mode_ch[['volt:ratio']]:
                        val='volt'
                return val
            options_conv.update(mode=mode_conv)
            kwarg.update(options=options)
            kwarg.update(options_lim=options_lim)
            kwarg.update(options_conv=options_conv)
            return scpiDevice(*arg, **kwarg)
        # _decode_float64_avg is needed because count points are returned
        # fetch? and read? return sample_count*trig_count data values (comma sep)
        self.fetch = scpiDevice(getstr='FETCh?',str_type=decode_float64_avg, autoinit=False, trig=True) #You can't ask for fetch after an aperture change. You need to read some data first.
        # autoinit false because it can take too long to readval
        #self.readval = scpiDevice(getstr='READ?',str_type=_decode_float64_avg, autoinit=False, redir_async=self.fetch) # similar to INItiate followed by FETCh.
        self.fetch_all = scpiDevice(getstr='FETCh?',str_type=decode_float64, autoinit=False, trig=True)
        self.fetch_std = scpiDevice(getstr='FETCh?',str_type=decode_float64_meanstd, autoinit=False, trig=True, doc="""
             Use this to obtain the standard deviation(using ddof=1) of the fetch.
             It is the standard deviation of the mean (it decreases when the averaging is longer).
             This will only return something usefull for long time averages where
             count is > 1. This is the case with set_long_avg(time) for time longer
             than 1s.
             (fetch_all needs to have more than one value)
        """)
        self.line_freq = scpiDevice(getstr='SYSTem:LFRequency?', str_type=float) # see also SYST:LFR:ACTual?
        ch_aper_list = ['volt', 'curr', 'res', 'fres', 'temp', 'freq', 'period']
        ch_aper_nplc_list = ['volt', 'curr', 'res', 'fres', 'temp']
        ch_zero_list = ['volt', 'curr', 'res', 'temp']
        ch_range_list = ['curr:ac', 'volt:ac', 'cap', 'curr', 'volt', 'res', 'fres'] # everything except continuity, diode, freq, per and temperature
        ch_volt = mode_ch[['volt', 'volt:ac']]
        ch_current = mode_ch[['curr', 'curr:ac']]
        ch_null_list = ['curr:ac', 'volt:ac', 'cap', 'curr', 'volt', 'freq', 'per', 'res', 'fres', 'temp'] # everything except continuity and diode
        if model_new:
            ch_aper_list += ['volt:ratio']
            ch_aper_nplc_list += ['volt:ratio']
            ch_zero_list += ['volt:ratio']
            ch_volt = mode_ch[['volt', 'volt:ac', 'volt:ratio']]
            ch_range_list = ['curr:ac', 'volt:ac', 'curr', 'volt', 'res', 'fres', 'volt:ratio']
            ch_null_list = ['curr:ac', 'volt:ac', 'curr', 'volt', 'freq', 'per', 'res', 'fres', 'temp']
            ch_sec_list = ['curr:ac', 'volt:ac', 'curr', 'volt', 'volt:ratio', 'cap', 'freq', 'per', 'res', 'fres', 'temp']
            if model_65_70:
                ch_range_list += ['cap']
                ch_null_list += ['cap']
            ch_sec = mode_ch[ch_sec_list]
        ch_range = mode_ch[ch_range_list]
        ch_null = mode_ch[ch_null_list]
        ch_aper = mode_ch[ch_aper_list]
        ch_aper_nplc = mode_ch[ch_aper_nplc_list]
        aper_max = float(self.ask('volt:aper? max'))
        aper_min = float(self.ask('volt:aper? min'))
        # TODO handle freq, period where valid values are .001, .010, .1, 1 (between .001 and 1 can use setget)
        self.aperture = devOption(ch_aper, '{mode}:APERture', str_type=float, min = aper_min, max = aper_max, setget=True)
        self.aperture_en = devOption(ch_aper_nplc, '{mode}:APERture:ENabled', str_type=bool)
        if not model_new:
            nplc_list = [0.006, 0.02, 0.06, 0.2, 1, 2, 10, 100]
        else:
            if model_n in ['34460', '34461']:
                nplc_list = [0.02, 0.2, 1, 10, 100]
            else:
                if model_DIG:
                    nplc_list = [0.001, 0.002, 0.006, 0.02, 0.06, 0.2, 1, 10, 100]
                else:
                    nplc_list = [0.02, 0.06, 0.2, 1, 10, 100]
        self.nplc = devOption(ch_aper_nplc, '{mode}:NPLC', str_type=float,
                                   choices=nplc_list)
        ch_band = mode_ch[['curr:ac', 'volt:ac']]
        self.bandwidth = devOption(ch_band, '{mode}:BANDwidth', str_type=float,
                                   choices=[3, 20, 200]) # in Hz
        ch_freqperi = mode_ch[['freq', 'per']]
        self.freq_period_p_band = devOption(ch_freqperi, '{mode}:RANGe:LOWer', str_type=float,
                                   choices=[3, 20, 200]) # in Hz
        self.freq_period_autorange = devOption(ch_freqperi, '{mode}:VOLTage:RANGe:AUTO', str_type=bool) # Also use ONCE (immediate autorange, then off)
        self.freq_period_volt_range = devOption(ch_freqperi, '{mode}:VOLTage:RANGe', str_type=float,
                                                choices=[.1, 1., 10., 100., 1000.]) # Setting this disables auto range
        if model_new:
            # 3.0 firmware seem to have an error (not the same as documentation
            #self.freq_period_timeout_auto_en = devOption(ch_freqperi, '{mode}:TIMeout:AUTO', str_type=bool)
            self.freq_period_timeout_auto_en = devOption(mode_ch[['freq']], '{mode}:TIMeout:AUTO', str_type=bool)

        ch_zero = mode_ch[ch_zero_list] # same as ch_aper_nplc wihtout fres
        self.zero = devOption(ch_zero, '{mode}:ZERO:AUTO', str_type=bool,
                              doc='Enabling auto zero double the time to take each point (the value and a zero correction is done for each point)') # Also use ONCE (immediate zero, then off)
        self.autorange = devOption(ch_range, '{mode}:RANGE:AUTO', str_type=bool) # Also use ONCE (immediate autorange, then off)
        current_list = [.1e-3, 1e-3, 1e-2, 1e-1, 1, 3]
        range_dict = {ch_volt:[.1, 1., 10., 100., 1000.],
                      ch_current:current_list,
                      mode_ch[['fres', 'res']]:[1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9] } # in V, A, Ohm
        if model_65_70:
            current_list = [1e-6, 10e-6] + current_list
            range_dict[mode_ch[['cap']]] = [1e-9, 10e-9, 100e-9, 1e-6, 10e-6, 100e-6]
            self.current_switch_mode = scpiDevice('CURRent:SWITch:MODE', choices=ChoiceStrings('FAST', 'CONTinuous'))
        if not model_new:
            range_dict[mode_ch[['cap']]] = [1e-9, 10e-9, 100e-9, 1e-6, 10e-6]
        range_ch = ChoiceDevDep(self.mode, range_dict)
        if model_new and model_n not in ['34460']:
            self.range_current_terminal = devOption(ch_current, '{mode}:TERMinals', str_type=float, choices=[3, 10])
        self.range = devOption(ch_range, '{mode}:RANGe', str_type=float, choices=range_ch) # Setting this disables auto range
        self.null_en = devOption(ch_null, '{mode}:NULL', str_type=bool)
        self.null_val = devOption(ch_null, '{mode}:NULL:VALue', str_type=float)
        self.voltdc_impedance_autoHigh = scpiDevice('VOLTage:IMPedance:AUTO', str_type=bool, doc='When True and V range <= 10V then impedance >10 GO else it is 10 MOhm')
        tch_list = ['FRTD', 'RTD', 'FTHermistor', 'THERmistor']
        if model_65_70:
            tch_list += ['TCouple']
        tch = ChoiceStrings(*tch_list)
        self.temperature_transducer = scpiDevice('TEMPerature:TRANsducer:TYPE', choices=tch)
        tch_rtd = tch[['frtd', 'rtd']]
        tch_therm = tch[['fth', 'ther']]
        tch_rtd_therm = tch[['fth', 'ther', 'frtd', 'rtd']]
        type_dict = {tch_rtd:ChoiceSimple([85], str_type=int), tch_therm:ChoiceSimple([2252, 5000, 10000], str_type=int)}
        if model_65_70:
            type_dict[tch[['tcouple']]] = ChoiceStrings(*list('EJKNRT'))
        ch_temp_typ = ChoiceDevDep(self.temperature_transducer, type_dict)
        self.temperature_transducer_subtype = scpiDevice('TEMPerature:TRANsducer:{trans}:TYPE',
                                        choices = ch_temp_typ,
                                        options=dict(trans=self.temperature_transducer))
        self.temperature_transducer_rtd_ref = scpiDevice('TEMPerature:TRANsducer:{trans}:RESistance',
                                        min = 49, max= 2.1e3, str_type=float,
                                        options=dict(trans=self.temperature_transducer),
                                        options_lim=dict(trans=tch_rtd))
        self.temperature_transducer_rtd_off = scpiDevice('TEMPerature:TRANsducer:{trans}:OCOMpensated', str_type=bool,
                                        options=dict(trans=self.temperature_transducer),
                                        options_lim=dict(trans=tch_rtd))
        self.temperature_unit = scpiDevice('UNIT:TEMPerature', choices=ChoiceStrings('C', 'F', 'K'))

        if model_65_70:
            self.temperature_tcouple_check_en = scpiDevice('TEMPerature:TRANsducer:TCouple:CHECk', str_type=bool)
            self.temperature_tcouple_ref_temp = scpiDevice('TEMPerature:TRANsducer:TCouple:RJUNction', str_type=float, min=-20, max=80, setget=True)
            self.temperature_tcouple_offset = scpiDevice('TEMPerature:TRANsducer:TCouple:RJUNction:OFFSet:ADJust', str_type=float, min=-20, max=20, setget=True)
            self.temperature_tcouple_ref_type = scpiDevice('TEMPerature:TRANsducer:TCouple:RJUNction:TYPE', choices=ChoiceStrings('INTernal', 'FIXed'))
            self.temperature_transducer_low_power_en = scpiDevice('TEMPerature:TRANsducer:{trans}:POWer:LIMit', str_type=bool,
                                                    options=dict(trans=self.temperature_transducer),
                                                    options_lim=dict(trans=tch_rtd_therm))

        ch_compens = mode_ch[['res', 'fres']]
        if model_65_70 or not model_new:
            self.res_offset_comp = devOption(ch_compens, '{mode}:OCOMpensated', str_type=bool)
        if model_65_70:
            self.res_low_power_en = devOption(ch_compens, '{mode}:POWer:LIMit', str_type=bool)
        if not model_new:
            ch_peak = mode_ch[['volt', 'volt:ac', 'curr', 'curr:ac']]
            self.peak_mode_en = devOption(ch_peak, '{mode}:PEAK:STATe', str_type=bool)
            peak_op = dict(peak=self.peak_mode_en)
            peak_op_lim = dict(peak=[True])
            self.fetch_peaks_ptp = devOption(ch_peak, 'FETCh:{mode}:PTPeak', str_type=float,
                                         doc='Call this after a fetch or readval',
                                         options=peak_op, options_lim=peak_op_lim, autoinit=False, trig=True)
            ch_peak_minmax = mode_ch[['volt', 'curr']]
            self.fetch_peaks_min = devOption(ch_peak_minmax, 'FETCh:{mode}:PEAK:MINimum', str_type=float,
                                         doc='Call this after a fetch or readval',
                                         options=peak_op, options_lim=peak_op_lim, autoinit=False, trig=True)
            self.fetch_peaks_max = devOption(ch_peak_minmax, 'FETCh:{mode}:PEAK:MAXimum', str_type=float,
                                         doc='Call this after a fetch or readval',
                                         options=peak_op, options_lim=peak_op_lim, autoinit=False, trig=True)
        if model_new:
            # The Multi-34465/DMM_34465A_to_34410A_Differences_5992-0774EN.pdf
            # document says that peak detection measurement is no longer cumulative and now requires
            # a reset but that is not what I observed.
            #self.init_resets_ptp = MemoryDevice(True, choices=[True, False], doc='This controls when ptp')
            base_ch = ['OFF']
            if model_65_70:
                base_ch += ['CALCulate:DATA']
            sec_dict = {mode_ch[['volt']]: ChoiceStrings(*(base_ch+['VOLTage:AC', 'PTPeak'])),
                        mode_ch[['volt:ratio']]: ChoiceStrings(*(base_ch+['SENSe:DATA'])),
                        mode_ch[['volt:ac']]: ChoiceStrings(*(base_ch+['FREQuency', 'VOLTage'])),
                        mode_ch[['current']]: ChoiceStrings(*(base_ch+['CURRent:AC', 'PTPeak'])),
                        mode_ch[['current:ac']]: ChoiceStrings(*(base_ch+['FREQuency', 'CURRent'])),
                        mode_ch[['per']]: ChoiceStrings(*(base_ch+['FREQuency', 'VOLTage:AC'])),
                        mode_ch[['freq']]: ChoiceStrings(*(base_ch+['PERiod', 'VOLTage:AC'])),
                        mode_ch[['temp']]: ChoiceStrings(*(base_ch+['SENSe:DATA'])),
                        mode_ch[['fres', 'res']]: ChoiceStrings(*base_ch)
                        }
            if model_65_70:
                sec_dict[mode_ch[['cap']]] = ChoiceStrings(*base_ch)
            self.secondary_meas = devOption(ch_sec, '{mode}:SECondary', choices=ChoiceDevDep(self.mode, sec_dict),
                str_type=quoted_string(), skip_ratio_conv=True,
                doc="""
                    Note that Calculate:data (if available) returns the values before any math operation
                    The volt/current AC/DC options only work on the front panel. They do not work remotely.
                    Sense:data is raw sensor value.
                    """)
                    #For PTPeak, see init_resets_ptp device to decide when resets are done (or use ptp_clear func).
            self.ptp_clear = ProxyMethod(self._ptp_clear)
            self._devwrap('secondary_fetch', autoinit=False, trig=True)

        if not model_new:
            ch = ChoiceStrings('NULL', 'DB', 'DBM', 'AVERage', 'LIMit')
            self.math_func = scpiDevice('CALCulate:FUNCtion', choices=ch)
            self.math_state = scpiDevice('CALCulate:STATe', str_type=bool)
        else:
            self.math_stat_en = scpiDevice('CALCulate:AVERage', str_type=bool)
            self.math_limit_en = scpiDevice('CALCulate:LIMit', str_type=bool)
            self.math_histogram_en = scpiDevice('CALCulate:TRANsform:HISTogram', str_type=bool)
            self.math_scale_en = scpiDevice('CALCulate:SCALe', str_type=bool)
            self.math_trend_chart_en = scpiDevice('CALCulate:TCHart', str_type=bool)
            if model_65_70:
                self.math_smooth_en = scpiDevice('CALCulate:SMOothing', str_type=bool)
                self.math_smooth_response = scpiDevice('CALCulate:SMOothing:RESPonse', choices=ChoiceStrings('SLOW', 'MEDium', 'FAST'))
            ch = ChoiceStrings('DB', 'DBM')
            if model_65_70:
                ch = ChoiceStrings('DB', 'DBM', 'PCT', 'SCALe')
                self.math_scale_gain = scpiDevice('CALCulate:SCALe:GAIN', str_type=float, setget=True)
                self.math_scale_offset = scpiDevice('CALCulate:SCALe:OFFSet', str_type=float, setget=True)
                self.math_scale_scale_ref = scpiDevice('CALCulate:SCALe:REFerence', str_type=float, setget=True)
                self.math_scale_unit_en = scpiDevice('CALCulate:SCALe:UNIT:STATe', str_type=bool)
                self.math_scale_unit = scpiDevice('CALCulate:SCALe:UNIT', str_type=quoted_string(), setget=True)
            self.math_scale_func = scpiDevice('CALCulate:SCALe:FUNCtion', choices=ch)
            self.math_histogram_range_auto_en = scpiDevice('CALCulate:TRANsform:HISTogram:RANGe:AUTO', str_type=bool)
            self.math_histogram_range_lower = scpiDevice('CALCulate:TRANsform:HISTogram:RANGe:LOWer', str_type=float, setget=True)
            self.math_histogram_range_upper = scpiDevice('CALCulate:TRANsform:HISTogram:RANGe:UPPer', str_type=float, setget=True)
            self.math_histogram_npoints = scpiDevice('CALCulate:TRANsform:HISTogram:POINts', str_type=int, choices=[10, 20, 40, 100, 200, 400])
            self.math_histogram_fetch = scpiDevice(getstr='CALCulate:TRANsform:HISTogram:ALL?', str_type=decode_float64,
                    autoinit=False, trig=True, multi=True)
            self.math_histogram_count = scpiDevice(getstr='CALCulate:TRANsform:HISTogram:COUNt?', str_type=int, autoinit=False, trig=True)
        self.math_avg = scpiDevice(getstr='CALCulate:AVERage:AVERage?', str_type=float, trig=True)
        self.math_count = scpiDevice(getstr='CALCulate:AVERage:COUNt?', str_type=float, trig=True)
        self.math_max = scpiDevice(getstr='CALCulate:AVERage:MAXimum?', str_type=float, trig=True)
        self.math_min = scpiDevice(getstr='CALCulate:AVERage:MINimum?', str_type=float, trig=True)
        self.math_ptp = scpiDevice(getstr='CALCulate:AVERage:PTPeak?', str_type=float, trig=True)
        self.math_sdev = scpiDevice(getstr='CALCulate:AVERage:SDEViation?', str_type=float, trig=True)
        if model_new:
            self.math_scale_auto_ref_en = scpiDevice('CALCulate:SCALe:REFerence:AUTO', str_type=bool)
            self.math_scale_dbm_ref_res = scpiDevice('CALCulate:SCALe:DBM:REFerence', str_type=float,
                        choices=[50, 75, 93, 110, 124, 125, 135, 150, 250, 300, 500, 600, 800, 900, 1000, 1200, 8000])
            self.math_scale_db_ref_dbm = scpiDevice('CALCulate:SCALe:DB:REFerence', str_type=float, min=-200, max=200)
        else:
            self.math_scale_dbm_ref_res = scpiDevice('CALCulate:DBM:REFerence', str_type=float,
                        choices=[50, 75, 93, 110, 124, 125, 135, 150, 250, 300, 500, 600, 800, 900, 1000, 1200, 8000])
            self.math_scale_db_ref_dbm = scpiDevice('CALCulate:DB:REFerence', str_type=float, min=-200, max=200)
        ch = ChoiceStrings('IMMediate', 'BUS', 'EXTernal')
        if model_DIG:
            ch = ChoiceStrings('IMMediate', 'BUS', 'EXTernal', 'INTernal')
        self.trig_src = scpiDevice('TRIGger:SOURce', choices=ch)
        self.trig_delay = scpiDevice('TRIGger:DELay', str_type=float, min=0) # seconds
        self.trig_count = scpiDevice('TRIGger:COUNt', str_type=float, min=1) # The instruments uses float.
        self.sample_count = scpiDevice('SAMPle:COUNt', str_type=int, min=1)
        ch = ChoiceStrings('IMMediate', 'TIMer')
        self.sample_src = scpiDevice('SAMPle:SOURce', choices=ch)
        self.sample_timer = scpiDevice('SAMPle:TIMer', str_type=float) # seconds
        if model_65_70:
            self.sample_pretrigger_count = scpiDevice('SAMPle:COUNt:PRETrigger', str_type=int, min=0)
        self.trig_delayauto = scpiDevice('TRIGger:DELay:AUTO', str_type=bool)
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval
        super(agilent_multi_34410A, self)._create_devs()
        # For INITiate: need to wait for completion of triggered measurement before calling it again
        # for trigger: *trg and visa.trigger seem to do the same. Can only be called after INItiate and
        #   during measurement.
        # To get completion stats: write('INITiate;*OPC') and check results from *esr? bit 0
        #   enable with *ese 1 then check *stb bit 5 (32) (and clear *ese?)
        # Could also ask for data and look at bit 4 (16) output buffer ready
        #dmm1.mathfunc.set('average');dmm1.math_state.set(True)
        #dmm1.write('*ese 1;*sre 32')
        #dmm1.write('init;*opc')
        #dmm1.read_status_byte()
        #dmm1.ask('*stb?;*esr?')
        #dmm1.math_count.get(); dmm1.math_avg.get() # no need to reset count, init does that
        #visa.vpp43.enable_event(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, visa.vpp43.VI_QUEUE)
        #dmm1.write('init;*opc')
        #dmm1.read_status_byte()
        #visa.vpp43.wait_on_event(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, 10000)
        #dmm1.read_status_byte()
        #dmm1.ask('*stb?;*esr?')
        #  For installing handler (only seems to work with USB not GPIB for NI visa library. Seems to work fine with Agilent IO visa)
        #   def event_handler(vi, event_type, context, use_handle): stb = visa.vpp43.read_stb(vi);  print('helo 0x%x'%stb, event_type==visa.vpp43.VI_EVENT_SERVICE_REQ, context, use_handle); return visa.vpp43.VI_SUCCESS
        #   def event_handler(vi, event_type, context, use_handle): stb = visa.vpp43.read_stb(vi);  print('HELLO 0x%x'%stb,vi); return visa.vpp43.VI_SUCCESS
        #   visa.vpp43.install_handler(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, event_handler)
        #   visa.vpp43.enable_event(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, visa.vpp43.VI_HNDLR)
        #   The handler is called for all srq on the bus (not necessarily the instrument we want)
        #     the vi parameter refers to the installed handler, not the actual srq source
        #The wait_on_event seems to be handling only event from src, not affecting the other instruments srq
        # reading the status is not necessary after wait to clear srq (cleared during wait internal handler) for agilent visa
        #  but it is necessary for NI visa (it will receive the SRQ like for agilent but will not transmit
        #      the next ones to the wait queue until acknowledged)
        #      there seems to be some inteligent buffering going on, which is different in agilent and NI visas
        # When wait_on_event timesout, it produces the VisaIOError (VI_ERROR_TMO) exception
        #        the error code is available as VisaIOErrorInstance.error_code


#######################################################
##    Agilent RF attenuator
#######################################################

register_idn_alias('Agilent Technologies', 'AGILENT TECHNOLOGIES')

#@register_instrument('AGILENT TECHNOLOGIES', 'J7211C', 'A.00.04')
@register_instrument('AGILENT TECHNOLOGIES', 'J7211C', usb_vendor_product=[0x0957, 0x4C18], alias='J7211C RF attenuator')
class agilent_rf_Attenuator(visaInstrument):
    """
    This controls an Agilent Attenuation Control Unit
    Use att_level_dB to get or change the attenuation level.
    Use cal_att_level_dB to obtain the calibrated attenuation.
    Note that the attenuation for 0dB is not included for the
    other calibration levels.
    """
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('att_level_dB', 'cal_att_level_dB', 'current_freq_Hz',
                                 'relative_en', 'relative_ref_dB', options)
    def _att_level_dB_getdev(self):
        return int(self.ask('ATTenuation?'))
    def _att_level_dB_setdev(self, val):
        val = int(val)
        self.write('ATTenuation %i'%val)
        sleep(0.02)
    def _create_devs(self):
        self.relative_en = scpiDevice('RELative', str_type=bool)
        self.relative_ref_dB = scpiDevice('REFerence', str_type=float)
        # TODO implement RELative:LEVel  (only when relative is enabled)
        self.current_freq_Hz = MemoryDevice(1e9, min=0, max=26.5e9)
        self._devwrap('att_level_dB', min=0, max=101)
        #self.att_level_dB = scpiDevice('ATTenuation', str_type=int, min=0, max=101)
        self.alias = self.att_level_dB
        self.cal_att_level_dB = scpiDevice(getstr='CORRection? {att},{freq}', str_type=float,
                                           options=dict(att=self.att_level_dB, freq=self.current_freq_Hz),
                                           options_apply=['freq'])
        # This needs to be last to complete creation
        super(agilent_rf_Attenuator, self)._create_devs()


#######################################################
##    Agilent infiniiVision Scopes
#######################################################

#@register_instrument('AGILENT TECHNOLOGIES', 'MSO-X 3054A', '02.37.2014052001', usb_vendor_product=[0x0957, 0x17a2])
#@register_instrument('AGILENT TECHNOLOGIES', 'DSO-X 2024A', '01.10.2011031600', usb_vendor_product=[0x0957, 0x1796])
#@register_instrument('AGILENT TECHNOLOGIES', 'DSO-X 3054A', '01.10.2011031600', usb_vendor_product=[0x0957, 0x17a2])
@register_instrument('KEYSIGHT TECHNOLOGIES', 'DSO-X 3014T', usb_vendor_product=[0x2A8D, 0x1768], skip_add=True)
@register_instrument('KEYSIGHT TECHNOLOGIES', 'DSO-X 3024T', usb_vendor_product=[0x2A8D, 0x1766], skip_add=True)
@register_instrument('AGILENT TECHNOLOGIES', 'MSO-X 3054A', usb_vendor_product=[0x0957, 0x1796], skip_add=True)
@register_instrument('AGILENT TECHNOLOGIES', 'DSO-X 2024A', usb_vendor_product=[0x0957, 0x1796], skip_add=True)
@register_instrument('AGILENT TECHNOLOGIES', 'DSO-X 3054A', usb_vendor_product=[0x0957, 0x17a2])
class infiniiVision_3000(visaInstrumentAsync):
    """
     To use this instrument, the most useful devices are probably:
       fetch  (only works in the main timebase mode, not for roll or XY or zoom.
               Also it does not works badly when in Run State. Avoid it if possible.)
       readval (press run/stop on scope to terminate it, or use clear_dev method.
                You probably want to start in the stop mode, or use the skip_force_get option
                of get)
       snap_png
       use_single_trig  (note that single mode requires a trigger, it cannot use auto trigger mode
                         only normal mode)
     With use_single_trig set to True, the display will update during acquisition but
         the overall operation takes a little longer.
     See also the setup_trig_detection method.
     Be warned that fetch (preamble and waveform_count), resets the current acquistion
     and waits for the next one when the scope is running (a firmware bug?). Therefore
     trying to get with a filename will probably fail if the capture is long, and might
     do double trig otherwise. When the scope is stopped, there is no problem.
     If no trigger comes or the acquisition is long, the commands will time out and put
     the instrument in a blocked state. To recover use the clear_dev method.
     Another way is to start an acq with single_trig, check the acq with is_running
     and then fetch it.
     When performing a sweep/record with this device, the header in the main save file will
         include preamble information from the last acquisition, not for the ones of the sweep
         but the header in the scope files should be correct.
    It is faster to save the data in .npy format, but there will not be any headers.
    """
    def __init__(self, visa_addr, poll='force_handler'):
        super(infiniiVision_3000, self).__init__(visa_addr, poll)
    def init(self, full=False):
        self.write(':WAVeform:FORMat WORD') # can be WORD BYTE or ASCii
        self.write(':WAVeform:BYTeorder LSBFirst') # can be LSBFirst pr MSBFirst
        self.write(':WAVeform:UNSigned ON') # ON,1 or OFF,0
        super(infiniiVision_3000, self).init(full=full)
    # This is commented out because triggering on the trig status does not work
    # properly (see below in _async_trigger_helper)
#    def _async_trig_cleanup(self):
#        # reset trig_status
#        self.trig_status.get()
#        super(infiniiVision_3000, self)._async_trig_cleanup()
    def _async_trigger_helper(self):
        self.write('*sre 32')
        if self.use_single_trig.get():
            # triggering on *sre 1 does not work since
            #  it when it returns, the acquisition is not fully complete so
            #  that asking for the preamble starts a new acquisition.
            #self.write('*sre 1')
            self.single_trig(skip_trig_status=True)
        else:
            # need to make sure it is stopped before starting,
            # otherwise it sometimes stays long enough in run at end of acq
            # to cause another trig when reading headers.
            if self.is_running():
                self.stop_trig()
                #sleep(.1)
            self.digitize()
        self.write('*OPC')
        #self.write(':DIGitize;*OPC')
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        if self.is_running():
            # This is to prevent preamble, scal and count below from timing out
            # if it acq is long. But it means we get date from the previous scan.
            self.stop_trig()
        orig_src = self.source.getcache()
        orig_ch = self.current_channel.get()
        opts = []
        for ch in self.find_all_active_channels():
            mode = self.points_mode.get(src='Channel%i'%ch)
            scale = self.channel_range.get(ch=ch)
            preamble = self.preamble.get()
            count = self.waveform_count.get()
            opts += ['ch%i=%r'%(ch, dict(mode=mode, preamble=preamble, scale=scale, count=count))]
        self.current_channel.set(orig_ch)
        self.source.set(orig_src)
        opts += self._conf_helper('timebase_mode', 'timebase_pos', 'timebase_range', 'timebase_reference', 'timebase_reference_custom', 'timebase_scale',
                                 'acq_type', 'acq_mode', 'average_count', 'acq_samplerate', 'acq_npoints')
        if self._touchscreen:
            opts += self._conf_helper('acq_digitizer_en', 'acq_antialias_mode')
        return opts + self._conf_helper(options)
    def clear_dev(self):
        self.visa.instr.clear()
    def setup_trig_detection(self):
        """ This setups trig detection. Only use this on one thread and not with readval (run_and_wait).
            Undo its effect with reset_trig_detection (readval will also undo it)
            After calling this use:
              s.single_trig()
              get(s.trig_status) # when True there was a trig event
              get(s.lasttrig_time) # if not 0. then it is the last trig time
            The trig time accuracy is probably within 100 ms.
            Note that at least for DSOX3014T (but probably all of them),
            the trig state seem to only be transferred to the SRQ line at the end of
            the acquisition. Therefore the lasttrig_time is actually the time at the end of
            the acquisition.
        """
        # lets presume we were started with poll='force_handler'
        self.write('*sre 1')
        self.visa.enable_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ,
                               visa_wrap.constants.VI_HNDLR)
    def reset_trig_detection(self):
        self.visa.disable_event(visa_wrap.constants.VI_EVENT_SERVICE_REQ, visa_wrap.constants.VI_ALL_MECH)
        self.write('*sre 32')
    def digitize(self):
        """
        Starts an acquisition
        """
        self.write(':DIGitize')
    def run_trig(self):
        """
        The same as pressing run
        """
        self.write(':RUN')
    def stop_trig(self):
        """
        The same as pressing stop
        """
        self.write(':STOP')
    def single_trig(self, skip_trig_status=False):
        """
        The same as pressing single
        """
        if not skip_trig_status:
            self.trig_status.get() # reset trig
        self._async_last_status_time = 0.
        self.write(':SINGle')
    def is_running(self):
        status = int(self.ask('OPERegister:condition?'))
        # OPERregister[:event]? is a latch of 0-> from OPERegister:condition?
        # it goes through OPEE (mask) to affect OPER bit7 (128) of *STB
        # OPER has bits 11(Overload), 9(masks), 5(arm, see AER?), 3(run state)
        run_state = 8 # 2**3
        return bool(status&run_state)
    def _lasttrig_time_getdev(self):
        return self._async_last_status_time
    def _fetch_ch_helper(self, ch):
        if ch is None:
            ch = self.find_all_active_channels()
        if not isinstance(ch, (list)):
            ch = [ch]
        return ch
    def _fetch_getformat(self, **kwarg):
        xaxis = kwarg.get('xaxis', True)
        ch = kwarg.get('ch', None)
        ch = self._fetch_ch_helper(ch)
        if xaxis:
            multi = ['time(s)']
        else:
            multi = []
        for c in ch:
            multi.append('ch%i'%c)
        fmt = self.fetch._format
        multi = tuple(multi)
        fmt.update(multi=multi, graph=[], xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_getdev(self, ch=None, xaxis=True):
        """
           Options available: ch, xaxis
            -ch:    a single value or a list of values for the channels to capture
                    a value of None selects all the active ones.(1-4)
            -xaxis: Set to True (default) to return the timebase as the first column
        """
        ch = self._fetch_ch_helper(ch)
        if ch is None:
            ch = self.find_all_active_channels()
        if not isinstance(ch, (list)):
            ch = [ch]
        ret = []
        first = True
        for c in ch:
            self.source.set('chan%i'%c)
            pream = self.preamble.get()
            data = self.data.get()*1. # make it floats
            data_real = (data - pream['yref']) * pream['yinc'] + pream['yorig']
            if xaxis and first:
                first = False
                ret = [(np.arange(pream['points'])- pream['xref']) * pream['xinc'] + pream['xorig']]
            ret.append(data_real)
        ret = np.asarray(ret)
        if ret.shape[0]==1:
            ret=ret[0]
        return ret
    @locked_calling
    def find_all_active_channels(self):
        orig_ch = self.current_channel.get()
        ret = []
        for i in range(1,5):
            if self.channel_display.get(ch=i):
                ret.append(i)
        self.current_channel.set(orig_ch)
        return ret
    def _create_devs(self):
        touchscreen = False
        if self.idn_split()['model'].lower().endswith('t'):
            touchscreen = True
        self._touchscreen = touchscreen
        self.use_single_trig = MemoryDevice(False, choices=[True, False], doc="Use either Run/stop (when False) or single_trig when True")
        self.snap_png = scpiDevice(getstr=':DISPlay:DATA? PNG, COLor', raw=True, str_type=_decode_block_base, autoinit=False, doc="Use like this: get(s500.snap_png, filename='testname.png')\nThe .png extensions is optional. It will be added if necessary.")
        self.snap_png._format['bin']='.png'
        self.inksaver = scpiDevice(':HARDcopy:INKSaver', str_type=bool, doc='This control whether the graticule colors are inverted or not.') # ON, OFF 1 or 0
         # :waveform:DATA? returns block of data (always header# for asci byte and word)
         # with chunk_size = 1024*1024 it seems to lower the frequency of transfer error that lock up
         # the communication to the scope (requiring a power cycle; clear_dev is not sufficient,
         #  writing to the scope still works but reading always times out.)
         #  The default is 20*1024, which requires multiple visa read requests and
         #  and one of them (often in the 70's) would hang (as seen with io monitor).
         # The above observation were with either NI or Keysight visa lib and with the
         #   DSO-X 3014T,MY61500174,07.50.2021102830
        self.data = scpiDevice(getstr=':waveform:DATA?', raw=True, str_type=decode_uint16_bin, autoinit=False, chunk_size=1024*1024)
          # also read :WAVeform:PREamble?, which provides, format(byte,word,ascii),
          #  type (Normal, peak, average, HRes), #points, #avg, xincr, xorg, xref, yincr, yorg, yref
          #  xconv = xorg+x*xincr, yconv= (y-yref)*yincr + yorg
        self.source = scpiDevice(':WAVeform:SOURce', choices=ChoiceStrings('CHANnel1', 'CHANnel2', 'CHANnel3', 'CHANnel4'), doc='This is the source channel for the waveform devices (points*, preamble, waveform_count)')
        def devSrcOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(src=self.source)
            app = kwarg.pop('options_apply', ['src'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.points = devSrcOption(':WAVeform:POINts', str_type=int, autoinit=False, doc='Do not use when in run state.') # 100, 250, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000, 2000000, 4000000, 8000000
        self.points_max_possible = devSrcOption(getstr=':WAVeform:POINts? MAX', str_type=int, autoinit=False)
        self.points_mode = devSrcOption(':WAVeform:POINts:MODE', choices=ChoiceStrings('NORMal', 'MAXimum', 'RAW'))
        self.preamble = devSrcOption(getstr=':waveform:PREamble?', choices=ChoiceMultiple(['format', 'type', 'points', 'count', 'xinc', 'xorig', 'xref', 'yinc', 'yorig', 'yref'],[int, int, int, int, float, float, int, float, float, int]), autoinit=False)
        self.waveform_count = devSrcOption(getstr=':WAVeform:COUNt?', str_type=int, autoinit=False)
        self.acq_type = scpiDevice(':ACQuire:TYPE', choices=ChoiceStrings('NORMal', 'AVERage', 'HRESolution', 'PEAK'))
        self.acq_mode= scpiDevice(':ACQuire:MODE', choices=ChoiceStrings('RTIM', 'SEGM'))
        self.average_count = scpiDevice(':ACQuire:COUNt', str_type=int, min=2, max=65536)
        if touchscreen:
            self.acq_digitizer_en = scpiDevice(':ACQuire:DIGitizer', str_type=bool)
            self.acq_antialias_mode = scpiDevice(':ACQuire:DAALias', choices=ChoiceStrings('DISable', 'AUTO'))
        self.acq_samplerate = scpiDevice(':ACQuire:SRATe', str_type=float, setget=True)
        self.acq_npoints = scpiDevice(':ACQuire:POINts', str_type=int, setget=True)
        self.current_channel = MemoryDevice(1, min=1, max=4)
        self.trig_status = scpiDevice(getstr=':TER?', str_type=bool, autoinit=False, doc="This returns True after the instrument has been triggered. It also resets the trig state.")
        def devChannelOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.channel_display = devChannelOption('CHANnel{ch}:DISPlay', str_type=bool)
        self.channel_range = devChannelOption('CHANnel{ch}:RANGe', str_type=float, setget=True)
        self.channel_scale = devChannelOption('CHANnel{ch}:SCALe', str_type=float, setget=True)
        self.timebase_mode= scpiDevice(':TIMebase:MODE', choices=ChoiceStrings('MAIN', 'WINDow', 'XY', 'ROLL'))
        self.timebase_pos= scpiDevice(':TIMebase:POSition', str_type=float) # in seconds from trigger to display ref
        self.timebase_range= scpiDevice(':TIMebase:RANGe', str_type=float) # in seconds, full scale
        self.timebase_reference= scpiDevice(':TIMebase:REFerence', choices=ChoiceStrings('LEFT', 'CENTer', 'RIGHt', 'CUSTom'))
        self.timebase_reference_custom = scpiDevice(':TIMebase:REFerence:LOCation', str_type=float, min=0, max=1., setget=True)
        self.timebase_scale= scpiDevice(':TIMebase:SCALe', str_type=float) # in seconds, per div
        #TODO: add a bunch of CHANNEL commands, Then MARKER and MEASure, TRIGger
        self._devwrap('fetch', autoinit=False, trig=True)
        self._devwrap('lasttrig_time', trig=False)
        self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(infiniiVision_3000, self)._create_devs()


#######################################################
##    Agilent EXA signal analyzer
#######################################################

#@register_instrument('Agilent Technologies', 'N9010A', 'A.12.13')
@register_instrument('Agilent Technologies', 'N9010A', usb_vendor_product=[0x0957, 0x0B0B], alias='N9010A EXA', skip_add=True)
#@register_instrument('Agilent Technologies', 'N9030A', 'A.12.13')
@register_instrument('Keysight Technologies', 'N9030A', usb_vendor_product=[0x2A8D, 0x0D0B], alias='N9030A PXA', skip_add=True)
# We have an updated PXA to windows 10. The usb vendor changed to 0x2A8D, but ht idn still says Agilent.
# The usb, is registered with the alias so the previous and next line makes all possible combinations.
#@register_instrument('Agilent Technologies', 'N9030A', 'A.26.10', usb_vendor_product=[0x2A8D, 0x0D0B], alias='N9030A PXA', skip_add=True)
@register_instrument('Agilent Technologies', 'N9030A', usb_vendor_product=[0x0957, 0x0D0B], alias='N9030A PXA')
class agilent_EXA(visaInstrument):
    """
    This is a factory function that calls the proper classe, either
      agilent_EXA_mode_SA
    or
     agilent_EXA_mode_noise_figure
    with mode parameter at default of 'auto', it will select upon the current instrument mode.
    Otherwise use one of 'SA' or 'NF'
    """
    def __new__(cls, *args, **kwargs):
        mode = kwargs.pop('mode', 'auto')
        instance = super(agilent_EXA, cls).__new__(cls)
        instance.__init__(*args, **kwargs)
        if mode != 'auto':
            instance.instrument_mode.set(mode)
        actual_mode = instance.instrument_mode.get()
        kwargs['skip_id_test'] = True
        if actual_mode == 'sa':
            use_cls = agilent_EXA_mode_SA
        elif actual_mode == 'nfig':
            use_cls = agilent_EXA_mode_noise_figure
        else:
            raise NotImplementedError('The EXA/PXA requested mode (%s) is not implemented'%mode)
        return use_cls(*args, **kwargs)

    def _create_devs(self):
        ql = quoted_list(sep=', ')
        instrument_mode_list = ql(self.ask(':INSTrument:CATalog?'))
        # the list is name number, make it only name
        instrument_mode_list = [i.split(' ')[0] for i in instrument_mode_list]
        self.instrument_mode = scpiDevice(':INSTrument', choices=ChoiceStrings(*instrument_mode_list))
        # This needs to be last to complete creation
        super(agilent_EXA, self)._create_devs()

class agilent_EXA_mode_base(visaInstrumentAsync):
    def init(self, full=False):
        self.Ro = 50
        self.write(':format REAL,64')
        self.write(':format:border swap')
        super(agilent_EXA_mode_base, self).init(full=full)
    @locked_calling
    def _async_trig(self):
        self.cont_trigger.set(False)
        super(agilent_EXA_mode_base, self)._async_trig()
    def abort(self):
        self.write('ABORt')
    def restart_averaging(self):
        command = ':AVERage:CLEar'
        self.write(command)
    def user_reset(self):
        self.write('SYSTem:PRESet:USER')
    @locked_calling
    def do_alignememt(self, mode='all'):
        # could add external_mixer
        """ mode should be one of 'all', 'not_RF', 'only_RF'. 'expired'
            Returns True upon success.
        """
        if mode not in ['all', 'not_RF', 'only_RF', 'expired']: # , 'external_mixer']:
            raise ValueError('Invalid alignement mode')
        cmd = dict(all=':CALibration:ALL?',
                   not_RF=':CALibration:NRF?',
                   only_RF=':CALibration:RF?',
                   expired=':CALibration:EXPired?',
                   external_mixer=':CALibration:EMIXer?')[mode]
        self.write(cmd)
        _retry_wait(lambda: self.read_status_byte()&0x10,
                    -10*60, delay=.1, progress_base='Alignemnt wait')
        # let's assume the instrument output buffer is empty
        #while not self.read_status_byte()&0x10: # MAV (Message available)
        #    sleep(.5)
        if int(self.read()) == 0:
            return True
        # returns is 1 when there is a failure.
        return False
    def status_operation(self):
        oper = int(self.ask(':STATus:OPERation:CONDition?'))
        chk_bit = lambda bitn: bool((oper>>bitn)&1)
        res = {}
        res.update(calibrating=chk_bit(0), settling=chk_bit(1), sweeping=chk_bit(3), measuring=chk_bit(4),
                   wait_trig=chk_bit(5), wait_arm=chk_bit(6), paused=chk_bit(8), src_sweeping=chk_bit(9),
                   dc_coupled=chk_bit(10), src_wait_trig=chk_bit(12))
        res.update(all=oper)
        return res

    @locked_calling
    def status_questionable(self, latched=False):
        """
        If latched is True, The latched values are read and they are also reset.
        """
        if latched:
            term = ':EVENt?'
        else:
            term = ':CONDition?'
        res = {}
        chk_bit = lambda val, bitn: bool((val>>bitn)&1)
        cal_needed = int(self.ask('STATus:QUEStionable:CALibration:EXTended:NEEDed'+term))
        cal_skipped = int(self.ask('STATus:QUEStionable:CALibration:SKIPped'+term))
        cal_fail = int(self.ask('STATus:QUEStionable:CALibration:EXTended:FAILure'+term))
        cal = int(self.ask('STATus:QUEStionable:CALibration'+term))
        freq = int(self.ask('STATus:QUEStionable:FREQuency'+term))
        integ_signal = int(self.ask('STATus:QUEStionable:INTegrity:SIGNal'+term))
        integ_uncal = int(self.ask('STATus:QUEStionable:INTegrity:UNCalibrated'+term))
        integ = int(self.ask('STATus:QUEStionable:INTegrity'+term))
        power = int(self.ask('STATus:QUEStionable:POWer'+term))
        temp = int(self.ask('STATus:QUEStionable:TEMPerature'+term))
        res.update(temp_all=temp, temp_oven_cold=chk_bit(temp, 0))
        res.update(power_all=power, power_RPP_tripped=chk_bit(power, 0),
                   power_src_unlevel=chk_bit(power, 1),
                   power_src_LO_unlevel=chk_bit(power, 2),
                   power_LO_unlevel=chk_bit(power, 3))
        res.update(freq_all=freq)
        res.update(integ_all=integ, integ_signal=integ_signal, integ_uncal=integ_uncal)
        res.update(cal_all=cal, cal_needed=cal_needed, cal_failed=cal_fail, cal_skipped=cal_skipped)
        failed = cal_fail or cal&0xfc
        res.update(cal_rf_skipped=chk_bit(cal_skipped, 0),
                   cal_align_rf_needed=chk_bit(cal, 12),
                   cal_align_all_needed=chk_bit(cal, 14), cal_some_fail=failed)
        return res

    def _current_config_base_helper(self):
        base_pre = self._conf_helper('instrument_mode', 'meas_mode', 'cont_trigger', 'calibration_auto', 'calibration_auto_mode',
                                     'ext_ref', 'ext_ref_mode', 'input_coupling')
        base_post = self._conf_helper('output_analog', 'auxif_sel', 'installed_options', 'installed_options_appmode')
        base_post += ['status_operation=%r'%self.status_operation(), 'status_questionable=%r'%self.status_questionable()]
        return base_pre, base_post

    def _create_devs_pre(self):
        # call this in subclass at start of _create_devs
        self.installed_options = scpiDevice(getstr='*OPT?', str_type=quoted_string())
        self.installed_options_appmode = scpiDevice(getstr=':SYSTem:APPLication:OPTion?', str_type=quoted_string())
        ql = quoted_list(sep=', ')
        instrument_mode_list = ql(self.ask(':INSTrument:CATalog?'))
        # the list is name number, make it only name
        instrument_mode_list = [i.split(' ')[0] for i in instrument_mode_list]
        self.instrument_mode = scpiDevice(':INSTrument', choices=ChoiceStrings(*instrument_mode_list))
        # This list depends on instrument mode: These are measurement type
        self.meas_mode_list = scpiDevice(getstr=':CONFigure:CATalog?', str_type=ql)
        # From the list: SAN=SANalyzer
        self.meas_mode = scpiDevice(':CONFigure:{val}:NDEFault', ':CONFigure?')
        return
    def _create_devs(self):
        self.cont_trigger = scpiDevice('INITiate:CONTinuous', str_type=bool)
        self.calibration_auto = scpiDevice(':CALibration:AUTO', choices=ChoiceStrings('ON', 'PARTial', 'OFF'))
        self.calibration_auto_mode = scpiDevice(':CALibration:AUTO:MODE', choices=ChoiceStrings('ALL', 'NRF'))
        self.output_analog = scpiDevice(':OUTPut:ANALog', choices=ChoiceStrings('OFF', 'SVIDeo', 'LOGVideo', 'LINVideo', 'DAUDio'))
        self.auxif_sel = scpiDevice(':OUTPut:AUX', choices=ChoiceStrings('SIF', 'OFF')) # others could be AIF and LOGVideo if options are installed
        self.ext_ref = scpiDevice(getstr=':ROSCillator:SOURce?', str_type=str)
        self.ext_ref_mode = scpiDevice(':ROSCillator:SOURce:TYPE', choices=ChoiceStrings('INTernal', 'EXTernal', 'SENSe'))
        self.input_coupling = scpiDevice(':INPut:COUPling', choices=ChoiceStrings('AC', 'DC'))

        #following http://www.mathworks.com/matlabcentral/fileexchange/30791-taking-a-screenshot-of-an-agilent-signal-analyzer-over-a-tcpip-connection
        #note that because of *OPC?, the returned string is 1;#....
        self.snap_png = scpiDevice(getstr=r':MMEMory:STORe:SCReen "C:\TEMP\SCREEN.PNG";*OPC?;:MMEMory:DATA? "C:\TEMP\SCREEN.PNG"',
                                   raw=True, str_type=lambda x:_decode_block_base(x[2:]), autoinit=False)
        self.snap_png._format['bin']='.png'
        # This needs to be last to complete creation
        super(agilent_EXA_mode_base, self)._create_devs()

class agilent_EXA_mode_SA(agilent_EXA_mode_base):
    """
    To use this instrument, the most useful devices are probably:
        fetch, readval
        marker_x, marker_y
        snap_png
    Some commands are available:
        abort
    A lot of other commands require a selected trace or a mkr
    see current_trace, current_mkr
    They are both memory device on the computer. They are not changeable from
    the hardware itself.

    Note about fetch_base and get_trace. They both return the same y data
    The units are given by y_unit and it is not affected by y offset.
    get_trace is immediate, fetch_base waits for the end of the current sweep
    if needed (including averaging).
    fetch_base includes the correct x scale. It can be different from the currently active
    x scale when not updating. x-scales are affected by freq offset.
    """
    def _current_config_trace_helper(self, traces=None):
        # traces needs to be a list or None
        just_one = False
        if not isinstance(traces, (list)):
            just_one = True
            traces = [traces]
        trace_conf = ['current_trace', 'trace_type', 'trace_updating', 'trace_displaying',
                                      'trace_detector', 'trace_detector_auto']
        ret = []
        for t in traces:
            if t is not None:
                self.current_trace.set(t)
            tret = []
            for n in trace_conf:
                # follows _conf_helper
                val = _repr_or_string(getattr(self, n).getcache())
                tret.append(val)
            if ret == []:
                ret = tret
            else:
                ret = [old+', '+new for old, new in zip(ret, tret)]
        if just_one:
            ret = [n+'='+v for n, v in zip(trace_conf, ret)]
        else:
            ret = [n+'=['+v+']' for n, v in zip(trace_conf, ret)]
        return ret
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        # Assume SA instrument mode, SAN measurement (config)
        if 'trace' in options:
            self.current_trace.set(options['trace'])
        if 'mkr' in options:
            self.current_mkr.set(options['mkr'])
        extra = []
        base_pre, base_post = self._current_config_base_helper()
        base_conf = self._conf_helper('attenuation_db', 'attenuation_auto', 'y_unit', 'uW_path_bypass',
                                 'preamp_en', 'preamp_band',
                                 'freq_span', 'freq_start', 'freq_center', 'freq_stop', 'freq_offset',
                                 'gain_correction_db', 'sweep_time', 'sweep_time_auto',
                                 'sweep_time_rule', 'sweep_time_rule_auto', 'sweep_type', 'sweep_type_auto', 'sweep_type_rule',
                                 'sweep_type_rule_auto', 'sweep_fft_width', 'sweep_fft_width_auto', 'sweep_npoints',
                                 'bw_res', 'bw_res_auto', 'bw_video', 'bw_video_auto', 'bw_video_auto_ratio', 'bw_video_auto_ratio_auto',
                                 'bw_res_span', 'bw_res_span_auto', 'bw_res_shape', 'bw_res_gaussian_type', 'noise_eq_bw',
                                 'average_en', 'average_count', 'average_type', 'average_type_auto', options)
        # trace
        if dev_obj in [self.readval, self.fetch]:
            traces_opt = self._fetch_traces_helper(options.get('traces'), options.get('updating'))
            extra = self._current_config_trace_helper(traces_opt)
        elif dev_obj in [self.fetch_base, self.get_trace]:
            extra = self._current_config_trace_helper()
        # marker dependent
        if dev_obj in [self.marker_x, self.marker_y, self.marker_z]:
            extra = self._conf_helper('current_mkr', 'marker_mode', 'marker_x_unit', 'marker_x_unit_auto', 'marker_ref', 'marker_trace',
                                      'marker_x', 'marker_y', 'marker_z', 'marker_trace',
                                      'marker_function', 'marker_function_band_span', 'marker_function_band_left',
                                      'marker_function_band_right', 'peak_search_continuous')
            old_trace = self.current_trace.get()
            extra += self._current_config_trace_helper(self.marker_trace.getcache())
            self.current_trace.set(old_trace)
        return base_pre+extra+base_conf+base_post
    def _noise_eq_bw_getdev(self):
        """
        Using the bw_res and bw_res_shape this estimates the bandwith
        necessary to convert the data into power density.

        For gaussian filters the error in the estimate compared to the marker
        result is at most 0.06 dB (1.4% error) at 4 MHz (DB3),
        otherwise it is mostly within 0.01 dB (0.23%)
        For Flattop filters the error is at most -0.45 dB at 8 MHz (11%),
        otherwise it is mostly 0.040 - 0.050 (0.92-1.12%), centered around
        0.045 dB (1.0% offset) for bw below 120 kHz. (EXA N9010A, MY51170142)
        The correction means the equivalent bandwidth used for markers is
        1% greater than the selected value of the flat bandwidth. To correct
        for this, you can substract the noise density by 0.045 dB (or divide by
        1.010 if linear power scale).

        To see this errors, or to obtain the same factor as for the markers,
        set the instrument in the following way:
            -select resolution bandwidth (range, type ...)
            -setup a trace (assume units are dB...)
            -on trace put 2 markers at the same position
            -First marker shows just the raw value
            -Second marker setup to show noise (either noise or band density function)
            -Set band span for second marker to 0 (or the a single bin)
            -Then the bandwith used for marker calculation is
             10**((marker1-marker2)/10)
        You can see both by enabling the marker table. Note that for the function
        results the Y and function column should be the same here, but when the
        band span is larger they will be different. The Y value is the value of
        the function when the sweep has reached the marker position so it uses
        old values after the marker and so is not a valid result. You should
        consider the function result as the proper one. That is the value
        returned by marker_y devce in that case.

        The band power function is the integral of the band density over the
        selected band span (a span of 0 is the same as a span of one bin).
        So when band span is one bin:
            band_power(dBm)-band_density(dBm) = 10*log10(bin_width(Hz))
            bin_width = (freq_stop-freq_start)/(npoints-1)

        The distinction between the noise function and the band density function
        is that the noise function tries to apply correction for non-ideal
        detectors (peak, negative peak) or wrong averaging (volt, log Pow).
        The correction is calculated assuming the incoming signal is purely noise,
        and considers the video bandwidth.
        The band density function makes no such assumption and will return
        incorrect values for wrong detector/averaging. The best result is normally
        obtained with averaging detector in RMS mode.
        """
        #bw = self.bw_res.get()
        bw_mode = self.bw_res_shape.get()
        if bw_mode in self.bw_res_shape.choices[['gaussian']]:
            # The filters are always the same. They are defined for db3
            # but they are reported differently in the other modes.
            # We need the noise one.
            # In theory:
            #  The 3dB full width is 2*sqrt(log(2))*sigma
            #  The 6dB full width is sqrt(2) times 3dB
            #  The noise width is sqrt(pi)/(2*sqrt(log(2))) times 3dB (and is equivalent bw for power: from integral of V**2)
            #  The impulse width is sqrt(2) times noise (and is equivalent bw for amplitude: from integral of V)
            # In practice we use the noise and it is probably related to the
            # 3dB by some calibration. The conversion factor between 3dB and noise returned by
            # the instrument is not a constant (it is ~1.065).
            old_gaus_type = self.bw_res_gaussian_type.get()
            self.bw_res_gaussian_type.set('noise')
            bw = self.bw_res.get()
            self.bw_res_gaussian_type.set(old_gaus_type)
            # get the bw_res cache back to the correct value
            self.bw_res.get()
        else: # flat
            # Normally the equivalent noise bandwidth of a flat filter
            # is the bw of the filter. However, in practice, it could be different.
            bw = self.bw_res.get()
            # TODO maybe decide to apply the correction
            #bw *= 1.01
        return bw
    def _fetch_getformat(self, **kwarg):
        unit = kwarg.get('unit', 'default')
        xaxis = kwarg.get('xaxis', True)
        traces = kwarg.get('traces', None)
        updating = kwarg.get('updating', True)
        traces = self._fetch_traces_helper(traces, updating)
        if xaxis:
            zero_span = self.freq_span.get() == 0
            if zero_span:
                multi = 'time(s)'
            else:
                multi = 'freq(Hz)'
            multi = [multi]
        else:
            multi = []
        for t in traces:
            multi.append('trace%i'%t)
        fmt = self.fetch._format
        multi = tuple(multi)
        fmt.update(multi=multi, graph=[], xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_traces_helper(self, traces, updating=True):
        """
        When updating is True, only updating trace are selected when
        traces=None. Otherwise all visible traces are selected.
        """
        if isinstance(traces, (tuple, list)):
            pass
        elif traces is not None:
            traces = [traces]
        else: # traces is None
            traces = []
            old_trace = self.current_trace.get()
            for t in range(1,7):
                if updating and self.trace_updating.get(trace=t):
                    traces.append(t)
                elif not updating and self.trace_displaying.get(trace=t):
                    traces.append(t)
            self.current_trace.set(old_trace)
        return traces
    def _convert_unit(self, v, from_unit, to_unit, bw):
        Ro = self.Ro
        if to_unit == 'default':
            return v
        from_unit = from_unit.upper()
        db_list = ['DBM', 'DBMV', 'DBMA', 'DBUV', 'DBUA', 'DBUVM', 'DBUAM', 'DBPT', 'DBG']
        db_ref = [1e-3, 2e-8, 5e-5, 2e-14, 5e-11, 0, 0, 0, 0] # in W
        if from_unit in db_list:
            in_db = True
            i = db_list.index(from_unit)
            in_ref = db_ref[i]
            if in_ref == 0:
                raise ValueError(self.perror("Don't know how to convert from antenna unit %s"%from_unit))
        else: # V, W and A
            in_db = False
            # convert to W
            if from_unit == 'V':
                v = v**2 / Ro
            elif from_unit == 'A':
                v = v**2 * Ro
        to_db_list = ['dBm', 'dBm_Hz']
        to_lin_list = ['W', 'W_Hz', 'V', 'V_Hz', 'V2', 'V2_Hz']
        if to_unit not in to_db_list+to_lin_list:
            raise ValueError(self.perror("Invalid conversion unit: %s"%to_unit))
        if not to_unit.endswith('_Hz'):
            bw = 0
        if to_unit in to_db_list:
            if in_db:
                v = v + 10*np.log10(in_ref/1e-3)
            else: # in is in W
                v = 10.*np.log10(v/1e-3)
            if bw:
                v -= 10*np.log10(bw)
        else: # W, V and V2 and _Hz variants
            if in_db:
                v = in_ref*10.**(v/10.)
            if to_unit in ['V', 'V_Hz']:
                bw = np.sqrt(bw)
                v = np.sqrt(v*Ro)
            elif to_unit in ['V2', 'V2_Hz']:
                v = v*Ro
            if bw:
                v /= bw
        return v
    def _fetch_getdev(self, traces=None, updating=True, unit='default', xaxis=True):
        """
         Available options: traces, updating, unit, xaxis
           -traces:  can be a single value or a list of values.
                     The values are integer representing the trace number (1-6)
           -updating: is used when traces is None. When True (default) only updating traces
                      are fetched. Otherwise all visible traces are fetched.
           -unit: can be default (whatever the instrument gives) or
                       'dBm'    for dBm
                       'W'      for Watt
                       'V'      for Volt
                       'V2'     for Volt**2
                       'dBm_Hz' for noise density
                       'W_Hz'   for W/Hz
                       'V_Hz'   for V/sqrt(Hz)
                       'V2_Hz'  for V**2/Hz
                 It can be a single value or a vector the same length as traces
                 See noise_eq_bw device for information about the
                 bandwidth used for _Hz unit conversion.
            -xaxis:  when True(default), the first column of data is the xaxis

           This version of fetch uses get_trace instead of fetch_base so it never
           block. It assumes all the data have the same x-scale (should be the
           case when they are all updating).
        """
        traces = self._fetch_traces_helper(traces, updating)
        if xaxis:
            ret = [self.get_xscale()]
        else:
            ret = []
        if not isinstance(unit, (list, tuple)):
            unit = [unit]*len(traces)
        base_unit = self.y_unit.get()
        noise_bw = self.noise_eq_bw.get()
        for t, u in zip(traces, unit):
            v = self.get_trace.get(trace=t)
            v = self._convert_unit(v, base_unit, u, noise_bw)
            ret.append(v)
        ret = np.asarray(ret)
        if ret.shape[0]==1:
            ret=ret[0]
        return ret
    def peak_search(self, mkr=None, next=False):
        """
        next can be True (same as finding next)
        left  to find the left
        right to find the next peak to the right
        """
        if mkr is None:
            mkr = self.current_mkr.getcache()
        if mkr<1 or mkr>12:
            raise ValueError(self.perror('mkr need to be between 1 and 12'))
        if next == True:
            next = ':NEXT'
        elif next:
            next = ':'+next
        else:
            next = ''
        self.write('CALCulate:MARKer{mkr}:MAXimum'.format(mkr=mkr)+next)
    def marker_to_center_freq(self, mkr=None):
        if mkr is None:
            mkr = self.current_mkr.getcache()
        if mkr<1 or mkr>12:
            raise ValueError(self.perror('mkr need to be between 1 and 12'))
        self.write('CALCulate:MARKer{mkr}:CENTer'.format(mkr=mkr))
    @locked_calling
    def get_xscale(self):
        """
        Returns the currently active x scale. It uses cached values so make sure
        they are up to date.
        This scale is recalculated but produces the same values (within floating
        point errors) as the instrument.
        """
        zero_span = self.freq_span.get() == 0
        if zero_span:
            offset = start = 0
            stop = self.sweep_time.get()
        else:
            start = self.freq_start.get()
            stop = self.freq_stop.get()
            offset = self.freq_offset.get()
        npts = self.sweep_npoints.get()
        return np.linspace(start+offset, stop+offset, npts)
    def _create_devs(self):
        self._create_devs_pre()
        self.attenuation_db = scpiDevice(':POWer:ATTenuation', str_type=float, setget=True)
        self.attenuation_auto = scpiDevice(':POWer:ATTenuation:AUTO', str_type=bool)
        self.correction_impedance = scpiDevice('CORRection:IMPedance', str_type=float, choices=[50, 75])
        self.y_unit = scpiDevice('UNIT:POWer', choices=ChoiceStrings('DBM', 'DBMV', 'DBMA', 'DBUV', 'DBUA', 'DBUVM', 'DBUAM', 'DBPT', 'DBG', 'V', 'W', 'A'))
        self.uW_path_bypass = scpiDevice(':POWer:MW:PATH', choices=ChoiceStrings('STD', 'LNPath', 'MPBypass', 'FULL'))
        self.preamp_en = scpiDevice(':POWer:GAIN', str_type=bool)
        self.preamp_band = scpiDevice(':POWer:GAIN:BAND', choices=ChoiceStrings('LOW', 'FULL'))
        minfreq = float(self.ask(':FREQ:START? min'))
        maxfreq = float(self.ask(':FREQ:STOP? max'))
        self.freq_start = scpiDevice(':FREQuency:STARt', str_type=float, min=minfreq, max=maxfreq-10.)
        self.freq_center = scpiDevice(':FREQuency:CENTer', str_type=float, min=minfreq, max=maxfreq)
        self.freq_stop = scpiDevice(':FREQuency:STOP', str_type=float, min=minfreq, max=maxfreq)
        self.freq_offset = scpiDevice(':FREQuency:OFFset', str_type=float, min=-500e-9, max=500e9)
        self.gain_correction_db = scpiDevice(':CORREction:SA:GAIN', str_type=float)
        self.sweep_time = scpiDevice(':SWEep:TIME', str_type=float, min=1e-6, max=6000) # in sweep: 1ms-4000s, in zero span: 1us-6000s
        self.sweep_time_auto = scpiDevice(':SWEep:TIME:AUTO', str_type=bool)
        self.sweep_time_rule = scpiDevice(':SWEep:TIME:AUTO:RULes', choices=ChoiceStrings('NORMal', 'ACCuracy', 'SRESponse'))
        self.sweep_time_rule_auto = scpiDevice(':SWEep:TIME:AUTO:RULes:AUTO', str_type=bool)
        self.sweep_type = scpiDevice(':SWEep:TYPE', choices=ChoiceStrings('FFT', 'SWEep'))
        self.sweep_type_auto = scpiDevice(':SWEep:TYPE:AUTO', str_type=bool)
        self.sweep_type_rule = scpiDevice(':SWEep:TYPE:AUTO:RULes', choices=ChoiceStrings('SPEed', 'DRANge'))
        self.sweep_type_rule_auto = scpiDevice(':SWEep:TYPE:AUTO:RULes:AUTO', str_type=bool)
        self.sweep_fft_width = scpiDevice(':SWEep:FFT:WIDTh', str_type=float)
        self.sweep_fft_width_auto = scpiDevice(':SWEep:FFT:WIDTh:AUTO', str_type=bool)
        self.sweep_npoints = scpiDevice(':SWEep:POINts', str_type=int, min=1, max=40001)
        # For SAN measurement
        # available bandwidths gaussian db3:
        #   b = around(logspace(0,1,25),1)[:-1]; b[-2]-=.1; b[10:17] +=.1
        #   r = (b*10**arange(7)[:,None]).ravel()
        #   rgaus = append(r[:-12], [4e6,5e6, 6e6, 8e6])
        # and flat:
        #   rflat = append(r[11:-35], [3.9e5, 4.3e5, 5.1e5, 6.2e5, 7.5e5, 1e6, 1.5e6, 3e6, 4e6, 5e6, 6e6, 8e6])
        self.bw_res = scpiDevice(':BANDwidth', str_type=float, min=1, max=8e6, setget=True)
        self.bw_res_auto = scpiDevice(':BANDwidth:AUTO', str_type=bool)
        self.bw_video = scpiDevice(':BANDwidth:VIDeo', str_type=float, min=1, max=50e6)
        self.bw_video_auto = scpiDevice(':BANDwidth:VIDeo:AUTO', str_type=bool)
        self.bw_video_auto_ratio = scpiDevice(':BANDwidth:VIDeo:RATio', str_type=float, min=1e-5, max=3e6)
        self.bw_video_auto_ratio_auto = scpiDevice(':BANDwidth:VIDeo:RATio:AUTO', str_type=bool)
        self.bw_res_span = scpiDevice(':FREQuency:SPAN:BANDwidth:RATio', str_type=float, min=2, max=10000)
        self.bw_res_span_auto = scpiDevice(':FREQuency:SPAN:BANDwidth:RATio:AUTO', str_type=bool)
        self.bw_res_shape = scpiDevice(':BANDwidth:SHAPe', choices=ChoiceStrings('GAUSsian', 'FLATtop'))
        self.bw_res_gaussian_type = scpiDevice(':BANDwidth:TYPE', choices=ChoiceStrings('DB3', 'DB6', 'IMPulse', 'NOISe'))
        self.average_count = scpiDevice(':AVERage:COUNt',str_type=int, min=1, max=10000)
        self.average_type = scpiDevice(':AVERage:TYPE', choices=ChoiceStrings('RMS', 'LOG', 'SCALar'))
        self.average_type_auto = scpiDevice(':AVERage:TYPE:AUTO', str_type=bool)
        self.average_en = scpiDevice(':AVERage', str_type=bool)
        self.freq_span = scpiDevice(':FREQuency:SPAN', str_type=float, min=0, doc='You can select 0 span, otherwise minimum span is 10 Hz')
        # Trace dependent
        self.current_trace = MemoryDevice(1, min=1, max=6)
        def devTraceOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(trace=self.current_trace)
            app = kwarg.pop('options_apply', ['trace'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        # trace 0 is special, The others are 1-6 and return x,y pairs
        # trace 0:  margin/limit fail, F, F, F, N dB points result, current avg count, npoints sweep, F, F, F , Mkr1xy, Mkr2xy, .., Mkr12xy
        self.fetch_base = devTraceOption(getstr=':FETCh:{measurement}{trace}?', raw=True,
                                         str_type=decode_float64_2col, autoinit=False, trig=True, options=dict(measurement=self.meas_mode))
        self.fetch0_base = scpiDevice(getstr=':FETCh:{measurement}0?', str_type=str, autoinit=False, trig=True, options=dict(measurement=self.meas_mode))
        self.trace_type = devTraceOption(':TRACe{trace}:TYPE', choices=ChoiceStrings('WRITe', 'AVERage', 'MAXHold', 'MINHold'))
        self.trace_updating = devTraceOption(':TRACe{trace}:UPDate', str_type=bool)
        self.trace_displaying = devTraceOption(':TRACe{trace}:DISPlay', str_type=bool)
        self.trace_detector = devTraceOption(':DETector:TRACe{trace}', choices=ChoiceStrings('AVERage', 'NEGative', 'NORMal', 'POSitive', 'SAMPle', 'QPEak', 'EAVerage', 'RAVerage'))
        self.trace_detector_auto = devTraceOption(':DETector:TRACe{trace}:AUTO', str_type=bool)
        self.get_trace = devTraceOption(getstr=':TRACe? TRACE{trace}', raw=True, str_type=decode_float64, autoinit=False, trig=True)
        # TODO implement trace math, ADC dither, swept IF gain FFT IF gain
        # marker dependent
        self.current_mkr = MemoryDevice(1, min=1, max=12)
        def devMkrOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_mkr)
            app = kwarg.pop('options_apply', ['mkr'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.marker_mode = devMkrOption(':CALCulate:MARKer{mkr}:MODE', choices=ChoiceStrings('POSition', 'DELTa', 'FIXed', 'OFF'))
        self.marker_x = devMkrOption(':CALCulate:MARKer{mkr}:X', str_type=float, trig=True)
        self.marker_x_unit = devMkrOption(':CALCulate:MARKer{mkr}:X:READout', choices=ChoiceStrings('FREQuency', 'TIME', 'ITIMe', 'PERiod'))
        self.marker_x_unit_auto = devMkrOption(':CALCulate:MARKer{mkr}:X:READout:AUTO', str_type=bool)
        self.marker_y = devMkrOption(':CALCulate:MARKer{mkr}:Y', str_type=float, trig=True)
        self.marker_z = devMkrOption(':CALCulate:MARKer{mkr}:Z', str_type=float, trig=True) # for spectrogram mode
        self.marker_ref = devMkrOption(':CALCulate:MARKer{mkr}:REFerence', str_type=int, min=1, max=12)
        self.marker_trace = devMkrOption(':CALCulate:MARKer{mkr}:TRACe', str_type=int, min=1, max=6)
        self.marker_function = devMkrOption(':CALCulate:MARKer{mkr}:FUNCtion', choices=ChoiceStrings('NOISe', 'BPOWer', 'BDENsity', 'OFF'))
        self.marker_function_band_span = devMkrOption(':CALCulate:MARKer{mkr}:FUNCtion:BAND:SPAN', str_type=float, min=0)
        self.marker_function_band_left = devMkrOption(':CALCulate:MARKer{mkr}:FUNCtion:BAND:LEFT', str_type=float, min=0)
        self.marker_function_band_right = devMkrOption(':CALCulate:MARKer{mkr}:FUNCtion:BAND:RIGHt', str_type=float, min=0)
        self.peak_search_continuous = devMkrOption(':CALCulate:MARKer{mkr}:CPSearch', str_type=bool)

        self.noise_source_type = scpiDevice(':SOURce:NOISe:TYPE', choices=ChoiceStrings('NORMal', 'SNS'))
        self.noise_source_en = scpiDevice(':SOURce:NOISe', str_type=bool)
        self.noise_source_sns_attached = scpiDevice(getstr='SOURce:NOISe:SNS:ATTached?', str_type=bool)

        # initial hack for list sweep measurement
        self.fetch_list = scpiDevice(getstr=':FETCh:LIST?', str_type=decode_float64, autoinit=False, trig=True)

        self._devwrap('noise_eq_bw', autoinit=.5) # This should be initialized after the devices it depends on (if it uses getcache)
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(agilent_EXA_mode_SA, self)._create_devs()
# status byte stuff
# There is a bunch of register groups:
#  :status:operation
#  :status:questionable
#  :status:questionable:power
#  :status:questionable:frequency
# ALSO see comments below agilent_PNAL


class agilent_EXA_mode_noise_figure(agilent_EXA_mode_base):
    """
    To use this instrument, the most useful devices are probably:
        readval
        marker_x, marker_y
        snap_png
    Some commands are available:
        abort
        do_user_cal
        conf_enr
    The marker devices require a selected mkr
    see current_mkr
    They are both memory device on the computer. They are not changeable from
    the hardware itself.

    Note that there is a fetch device. However, if data is currently being taken, it will wait
      for a fully new set of data before returning. It could therefore timeout. You can use it
      when you are sure the sweep will be fast or is terminated. Otherwise use readval.
    """
    def init(self, full=False):
        # When this is on, marker_y returns 2 values (nfigure, gain) instead of the attached graph.
        self.write(':CALCulate:MARKer:COMPatible OFF')
        super(agilent_EXA_mode_noise_figure, self).init(full=full)
    def _async_trigger_helper(self):
        self.write('INITiate:NFIGure;*OPC') # this assume trig_src is immediate for agilent multi
    def _current_config_trace_helper(self, traces=None):
        # traces needs to be a list or None
        just_one = False
        if not isinstance(traces, (list)):
            just_one = True
            traces = [traces]
        trace_conf = ['current_trace', 'trace_type', 'trace_updating', 'trace_displaying',
                                      'trace_detector', 'trace_detector_auto']
        ret = []
        for t in traces:
            if t is not None:
                self.current_trace.set(t)
            tret = []
            for n in trace_conf:
                # follows _conf_helper
                val = _repr_or_string(getattr(self, n).getcache())
                tret.append(val)
            if ret == []:
                ret = tret
            else:
                ret = [old+', '+new for old, new in zip(ret, tret)]
        if just_one:
            ret = [n+'='+v for n, v in zip(trace_conf, ret)]
        else:
            ret = [n+'=['+v+']' for n, v in zip(trace_conf, ret)]
        return ret

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        extra = []
        base_pre, base_post = self._current_config_base_helper()
        base_conf = self._conf_helper('attenuation_db', 'preamp_en', 'preamp_auto_en', 'freq_mode')
        freq_mode = self.freq_mode.getcache()
        freq_mode_ch = self.freq_mode.choices
        if freq_mode in freq_mode_ch[['swept']]:
            base_conf += self._conf_helper('freq_span', 'freq_start', 'freq_center', 'freq_stop', 'sweep_npoints')
        elif freq_mode in freq_mode_ch[['fixed']]:
            base_conf += self._conf_helper('freq_fixed')
        base_conf += self._conf_helper('meas_time_auto', 'meas_time',
                                 'bw_res',  'bw_res_auto', 'average_en', 'average_count')
        base_conf += self._conf_helper('corr_enr_mode', 'corr_enr_common_table_en', 'corr_enr_pref',
                                       'corr_enr_sns_autoload_en' , 'corr_enr_src_state', 'corr_enr_sns_attached',
                                       'corr_tcold_mode', 'corr_tcold_user', 'corr_tcold_use_sns_en')
        if self.corr_enr_mode.getcache() in self.corr_enr_mode.choices[['spot']]:
            base_conf += self._conf_helper('corr_enr_spot_mode', 'corr_enr_spot_db', 'corr_enr_spot_thot')
        else:
            base_conf += self._conf_helper('corr_enr_id_meas',  'corr_enr_serial_meas', 'corr_enr_id_cal', 'corr_enr_serial_cal')
        base_conf += self._conf_helper('cal_en', 'cal_type', 'cal_user_min_attenuation', 'cal_user_max_attenuation',
                                       'cal_status',
                                       'noise_source_settling',
                                       'loss_before_mode', 'loss_before_dB', 'loss_before_temp',
                                       'loss_after_mode', 'loss_after_dB', 'loss_after_temp',
                                       'trace1_detector', 'trace2_detector')

        # marker dependent
        if dev_obj in [self.marker_x, self.marker_y]:
            orig_mrk = self.current_mkr.get()
            if 'mkr' in options:
                self.current_mkr.set(options['mkr'])
            extra = self._conf_helper('current_mkr', 'marker_mode', 'marker_x', 'marker_y', 'marker_ref', 'marker_trace',
                                      'peak_search_continuous')
            self.current_mkr.set(orig_mrk)
        return base_pre+extra+base_conf+base_post + self._conf_helper(options)

    def _fetch_getformat(self, **kwarg):
        xaxis = kwarg.get('xaxis', True)
        traces = kwarg.get('traces', None)
        traces, fixed = self._fetch_traces_helper(traces)
        if xaxis and not fixed:
            multi = ['freq(Hz)']
        else:
            multi = []
        for t in traces:
            multi.append(t)
        fmt = self.fetch._format
        if not fixed:
            multi = tuple(multi)
            graph = []
        else:
            graph = list(range(len(traces)))
        fmt.update(multi=multi, graph=graph, xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_traces_helper(self, traces):
        if isinstance(traces, (tuple, list)):
            pass
        elif traces is not None:
            traces = [traces]
        else: # traces is None
            trace2local = {'NFIGure':'nfigure', 'NFACtor':'nfactor', 'GAIN':'gain', 'YFACtor':'yfactor', 'TEFFective':'teff', 'PHOT':'phot', 'PCOLd':'pcold'}
            ch = self.trace1_detector.choices
            def conv(trace):
                for k, v in trace2local.items():
                    if trace in ch[[k]]:
                        return v
            traces = [conv(self.trace1_detector.getcache()), conv(self.trace2_detector.getcache())]
        for t in traces:
            if t not in ['tcold', 'nfigure', 'nfactor', 'gain', 'teff',
                         'phot', 'pcold',
                         'nfigure_uncorr', 'nfactor_uncorr', 'yfactor', 'teff_uncorr',
                         'phot_uncorr', 'pcold_uncorr']:
                raise ValueError(self.perror('Invalid traces option'))
        if self.freq_mode.getcache() in self.freq_mode.choices[['fixed']]:
            fixed = True
        else:
            fixed = False
        return traces, fixed
    def _fetch_getdev(self, traces=None, xaxis=True):
        """
         Available options: traces, updating, unit, xaxis
           -traces:  can be a single value or a list of values.
                     Possible values are:
                         'tcold', 'nfigure', 'nfactor', 'gain', 'teff',
                         'phot', 'pcold',
                         'nfigure_uncorr', 'nfactor_uncorr', 'yfactor', 'teff_uncorr',
                         'phot_uncorr', 'pcold_uncorr'
                    The units are either linear (for nfactor), dB, or K
                        (for phot/pcold it is dB from –173.88 dBm/Hz)
                    nfactor is the linear version of nfigure (which is in dB)
                    teff is the noise temperature.
                    When it is None (default), it will select the displayed traces format.
            -xaxis:  when True(default), the first column of data is the xaxis
                    This does not apply to freq_mode fixed
        """
        traces, fixed = self._fetch_traces_helper(traces)
        base = 'FETCh:NFIGure:'
        # could also use this. It always returns a single value (the last one for sweep or list).
        # For fixed mode, the non-scalar request also returns a single value
        #base = 'FETCh:NFIGure:SCALar:'
        tables = {'tcold': 'TCOLd',
                  'nfigure': 'CORRected:NFIGure',
                  'nfactor': 'CORRected:NFACtor',
                  'gain': 'CORRected:GAIN',
                  'teff': 'CORRected:TEFFective',
                  'phot': 'CORRected:PHOT',
                  'pcold': 'CORRected:PCOLd',
                  'nfigure_uncorr': 'UNCorrected:NFIGure',
                  'nfactor_uncorr': 'UNCorrected:NFACtor',
                  'yfactor': 'UNCorrected:YFACtor',
                  'teff_uncorr': 'UNCorrected:TEFFective',
                  'phot_uncorr': 'UNCorrected:PHOT',
                  'pcold_uncorr': 'UNCorrected:PCOLd'
                }
        if xaxis and not fixed:
            ret = [self.get_xscale()]
        else:
            ret = []
        for trace in traces:
            quest = base + tables[trace] + '?'
            res = self.ask(quest, raw=True)
            ret.append(_decode_block_auto(res))
        ret = np.asarray(ret)
        if fixed:
            ret = ret.ravel()
        if ret.shape[0]==1:
            ret=ret[0]
        return ret
    def peak_search(self, mkr=None, next=False):
        """
        next can be True (same as finding next)
           'left'  to find the left
           'right' to find the next peak to the right
        """
        if mkr is None:
            mkr = self.current_mkr.getcache()
        if mkr<1 or mkr>4:
            raise ValueError(self.perror('mkr need to be between 1 and 4'))
        if next not in [False, True, 'left', 'right']:
            raise ValueError('Invalid next value')
        if next == True:
            next = ':NEXT'
        elif next:
            next = ':'+next
        else:
            next = ''
        self.write('CALCulate:NFIGure:MARKer{mkr}:MAXimum'.format(mkr=mkr)+next)
    @locked_calling
    def get_xscale(self):
        """
        Returns the currently active x scale.
        This scale can be recalculated but produces the same values (within floating
        point errors) as the instrument.
        """
        mode = self.freq_mode.get()
        if mode == 'swept':
            start = self.freq_start.get()
            stop = self.freq_stop.get()
            npts = self.sweep_npoints.get()
            x = np.linspace(start, stop, npts)
        elif mode == 'list':
            x = self.freq_list.get()
        else: # mode  == 'fixed'
            x = np.array([self.freq_fixed.get()])
        return x

    def set_corr_tcold_from_sns(self):
        self.write('NFIGure:CORRection:TCOLd:USER:SET')

    @locked_calling
    def do_user_cal(self, min=None, max=None):
        """ Do a calibration. If selected, min and max will change the calibration attenuation min, max.
            Before doing the calibration, connect the noise source for calibration.
            You should also have loaded the enr table.
        """
        if min is not None:
            self.cal_user_min_attenuation.set(min)
        if max is not None:
            self.cal_user_min_attenuation.set(max)
        self.write('NFIGure:CALibration:INITiate; *OPC?')
        _retry_wait(lambda: self.read_status_byte()&0x10,
                    -10*60, delay=.1, progress_base='Calibration wait')
        self.read()

    @locked_calling
    def conf_enr(self, meas_id=None, meas_serial=None, meas_data=None, cal_id=None, cal_serial=None, cal_data=None):
        """\
            With no parameters, return the current config.
            with only the meas entry set, enable corr_enr_common_table_en
            The data should be an array of 2xN, where N is from 2 to 501.
        """
        if meas_id is meas_serial is meas_data is cal_id is cal_serial is cal_data is None:
            data = _decode_block_auto(self.ask('NFIGure:CORRection:ENR:MEASurement:TABLe:DATA?'))
            data.shape = (-1, 2)
            res = dict(meas_id=self.corr_enr_id_meas.get(),
                       meas_serial=self.corr_enr_serial_meas.get(),
                       meas_data=data.T)
            if not self.corr_enr_common_table_en.get():
                data = _decode_block_auto(self.ask('NFIGure:CORRection:ENR:CALibration:TABLe:DATA?'))
                data.shape = (-1, 2)
                res2 = dict(cal_id=self.corr_enr_id_cal.get(),
                           cal_serial=self.corr_enr_serial_cal.get(),
                           cal_data=data.T)
                res.update(res2)
            return res
        if cal_data is None:
            self.corr_enr_common_table_en.set(True)
        else:
            self.corr_enr_common_table_en.set(False)
        if meas_id is not None:
            self.corr_enr_id_meas.set(meas_id)
        if meas_serial is not None:
            self.corr_enr_serial_meas.set(meas_serial)
        if cal_id is not None:
            self.corr_enr_id_cal.set(cal_id)
        if cal_serial is not None:
            self.corr_enr_serial_cal.set(cal_serial)
        if meas_data is not None:
            self.write('NFIGure:CORRection:ENR:MEASurement:TABLe:DATA {}'.format(_encode_block(meas_data.T.ravel(), sep=',')))
        if cal_data is not None:
            self.write('NFIGure:CORRection:ENR:CALibration:TABLe:DATA {}'.format(_encode_block(cal_data.T.ravel(), sep=',')))

    def do_preselector_optimize(self):
        self.write('NFIGure:PRESelector:OPTimize;*OPC?')
        _retry_wait(lambda: self.read_status_byte()&0x10,
                    -10*60, delay=.1, progress_base='Preselector optimization wait')
        self.read()

    def _create_devs(self):
        self._create_devs_pre()
        self.attenuation_db = scpiDevice(':NFIGure:POWer:ATTenuation', str_type=float, setget=True)
        self.preamp_en = scpiDevice(':NFIGure:POWer:GAIN', str_type=bool)
        self.preamp_auto_en = scpiDevice(':NFIGure:POWer:GAIN:AUTO', str_type=bool)
        self.freq_mode = scpiDevice('NFIGure:FREQuency:MODE', choices=ChoiceStrings('SWEPt', 'FIXed', 'LIST'))
        self.freq_start = scpiDevice('NFIGure:FREQuency:STARt', str_type=float)
        self.freq_center = scpiDevice('NFIGure:FREQuency:CENTer', str_type=float)
        self.freq_span = scpiDevice('NFIGure:FREQuency:SPAN', str_type=float, min=0, doc='You can select 0 span, otherwise minimum span is 10 Hz')
        self.freq_stop = scpiDevice('NFIGure:FREQuency:STOP', str_type=float)
        self.freq_fixed = scpiDevice('NFIGure:FREQuency:FIXed', str_type=float)
        self.freq_list = scpiDevice('NFIGure:FREQuency:LIST:DATA', str_type=Block_Codec(sep=','))
        self.meas_time = scpiDevice('NFIGure:SWEep:TIME', str_type=float, min=1e-6, max=6000) # in sweep: 1ms-4000s, in zero span: 1us-6000s
        self.meas_time_auto = scpiDevice('NFIGure:SWEep:TIME:AUTO', str_type=bool)
        self.sweep_npoints = scpiDevice('NFIGure:SWEep:POINts', str_type=int, min=2, max=501)
        self.bw_res = scpiDevice('NFIGure:BANDwidth', str_type=float, min=1, max=8e6, setget=True)
        self.bw_res_auto = scpiDevice('NFIGure:BANDwidth:AUTO', str_type=bool)
        self.average_count = scpiDevice('NFIGure:AVERage:COUNt',str_type=int, min=1, max=10000)
        self.average_en = scpiDevice('NFIGure:AVERage', str_type=bool)
        self.corr_enr_mode = scpiDevice('NFIGure:CORRection:ENR:MODE', choices=ChoiceStrings('TABLe', 'SPOT'))
        self.corr_enr_common_table_en = scpiDevice('NFIGure:CORRection:ENR:COMMon', str_type=bool)
        self.corr_enr_id_meas = scpiDevice('NFIGure:CORRection:ENR:MEASurement:TABLe:ID:DATA', str_type=quoted_string())
        self.corr_enr_id_cal = scpiDevice('NFIGure:CORRection:ENR:CALibration:TABLe:ID:DATA', str_type=quoted_string())
        self.corr_enr_serial_meas = scpiDevice('NFIGure:CORRection:ENR:MEASurement:TABLe:SERial:DATA', str_type=quoted_string())
        self.corr_enr_serial_cal = scpiDevice('NFIGure:CORRection:ENR:CALibration:TABLe:SERial:DATA', str_type=quoted_string())
        self.corr_enr_pref = scpiDevice('NFIGure:CORRection:ENR:PREFerence', choices=ChoiceStrings('NORMal', 'SNS'))
        self.corr_enr_sns_autoload_en = scpiDevice('NFIGure:CORRection:ENR:AUTO', str_type=bool)
        self.corr_enr_src_state = scpiDevice('SOURce:NFIGure:NOISe:STATe', choices=ChoiceStrings('NORMal', 'ON', 'OFF'))
        self.corr_enr_sns_attached = scpiDevice(getstr='NFIGure:CORRection:ENR:SNS:ATTached?', str_type=bool)
        self.corr_enr_spot_mode = scpiDevice('NFIGure:CORRection:SPOT:MODE', choices=ChoiceStrings('ENR', 'THOT'))
        self.corr_enr_spot_db = scpiDevice('NFIGure:CORRection:ENR:SPOT', str_type=float, min=-17, max=50)
        self.corr_enr_spot_thot = scpiDevice('NFIGure:CORRection:ENR:THOT', str_type=float, min=0, max=29650000)
        self.corr_tcold_mode = scpiDevice('NFIGure:CORRection:TCOLd', choices=ChoiceStrings('USER', 'DEFault'), doc='Default is 296.50 K')
        self.corr_tcold_user = scpiDevice('NFIGure:CORRection:TCOLd:USER:VALue', str_type=float, min=0, max=29650000)
        self.corr_tcold_use_sns_en = scpiDevice('NFIGure:CORRection:TCOLd:SNS', str_type=bool)
        self.cal_en = scpiDevice('NFIGure:CALibration:STATe', str_type=bool)
        self.cal_type = scpiDevice('NFIGure:CALibration:TYPE', choices=ChoiceStrings('USER', 'INTernal'))
        self.cal_user_min_attenuation = scpiDevice('NFIGure:CALibration:USER:ATTenuation:MINimum', str_type=float, min=0, max=40)
        self.cal_user_max_attenuation = scpiDevice('NFIGure:CALibration:USER:ATTenuation:MAXimum', str_type=float, min=0, max=40)
        self.cal_status = scpiDevice(getstr='NFIG:CAL:COND?', doc='Returns either CAL, UNCAL, INTERPCAL or INTCAL for fully calibrated, not calibrated, interpolated calibration or internal calibration.')
        self.noise_source_settling = scpiDevice('NFIGure:NSSTime', str_type=float, min=0, max=5.)
        self.loss_before_mode = scpiDevice('NFIGure:CORRection:LOSS:BEFore:MODE', choices=ChoiceStrings('OFF', 'FIXed', 'TABLe'))
        self.loss_before_dB = scpiDevice('NFIGure:CORRection:LOSS:BEFore:VALue', str_type=float, min=-100, max=100)
        self.loss_before_table = scpiDevice(':NFIGure:CORRection:LOSS:BEFore:TABLe:DATA', str_type=Block_Codec(sep=','), autoinit=False, doc='The data is an array of freq1, loss1, freq2, loss2, ....')
        self.loss_before_temp = scpiDevice('NFIGure:CORRection:TEMPerature:BEFore', str_type=float, min=0, max=29650000)
        self.loss_after_mode = scpiDevice('NFIGure:CORRection:LOSS:AFTer:MODE', choices=ChoiceStrings('OFF', 'FIXed', 'TABLe'))
        self.loss_after_dB = scpiDevice('NFIGure:CORRection:LOSS:AFTer:VALue', str_type=float, min=-100, max=100)
        self.loss_after_table = scpiDevice('NFIGure:CORRection:LOSS:AFTer:TABLe:DATA', str_type=Block_Codec(sep=','), autoinit=False, doc='The data is an array of freq1, loss1, freq2, loss2, ....')
        self.loss_after_temp = scpiDevice('NFIGure:CORRection:TEMPerature:AFTer', str_type=float, min=0, max=29650000)

        trace_ch = ChoiceStrings('NFIGure', 'NFACtor', 'GAIN', 'YFACtor', 'TEFFective', 'PHOT', 'PCOLd')
        self.trace1_detector = scpiDevice(':DISPlay:NFIGure:DATA:TRACe1', choices=trace_ch)
        self.trace2_detector = scpiDevice(':DISPlay:NFIGure:DATA:TRACe2', choices=trace_ch)
        # marker dependent
        self.current_mkr = MemoryDevice(1, min=1, max=4)
        def devMkrOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_mkr)
            app = kwarg.pop('options_apply', ['mkr'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.marker_mode = devMkrOption(':CALCulate:NFIGure:MARKer{mkr}:MODE', choices=ChoiceStrings('POSition', 'DELTa', 'OFF'))
        self.marker_x = devMkrOption(':CALCulate:NFIGure:MARKer{mkr}:X', str_type=float, trig=True)
        self.marker_y = devMkrOption(':CALCulate:NFIGure:MARKer{mkr}:Y', str_type=float, trig=True)
        self.marker_ref = devMkrOption(':CALCulate:NFIGure:MARKer{mkr}:REFerence', str_type=int, min=1, max=4)
        self.marker_trace = devMkrOption(':CALCulate:NFIGure:MARKer{mkr}:TRACe', choices=ChoiceSimpleMap(dict(TRAC1=1, TRAC2=2), filter=string_upper))
        self.peak_search_continuous = devMkrOption('CALCulate:NFIGure:MARKer{mkr}:CPEak', str_type=bool)
        self.peak_search_type = scpiDevice(':CALCulate:NFIGure:MARKer:SEARch:TYPE', choices=ChoiceStrings('MINimum', 'MAXimum', 'PTPeak'))
        self.marker_coupled_en = scpiDevice(':CALCulate:NFIGure:MARKer:COUPle', str_type=bool)

        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval
        # This needs to be last to complete creation
        super(agilent_EXA_mode_noise_figure, self)._create_devs()


#######################################################
##    Agilent PNA-L network analyzer
#######################################################

#@register_instrument('Keysight Technologies', 'M9803A', 'A.15.20.07')
#@register_instrument('Keysight Technologies', 'N5244B', 'A.13.95.09')
#@register_instrument('Agilent Technologies', 'N5244A', 'A.09.50.13')
#@register_instrument('Agilent Technologies', 'N5230C', 'A.09.20.08')
@register_instrument('Keysight Technologies', 'P9374A', alias='P9374A USB VNA')
@register_instrument('Keysight Technologies', 'M9803A', alias='M9803A PXIe VNA')
@register_instrument('Keysight Technologies', 'N5244B', usb_vendor_product=[0x2A8D, 0x2B01], alias='N5244B PNAX')
@register_instrument('Agilent Technologies', 'N5244A', usb_vendor_product=[0x0957, 0x0118], alias='N5244A PNAX')
@register_instrument('Agilent Technologies', 'N5230C', usb_vendor_product=[0x0957, 0x0118], alias='N5230C PNA-L')
class agilent_PNAL(visaInstrumentAsync):
    """
    To use this instrument, the most useful device is probably:
        fetch, readval
    Some commands are available:
        abort
        create_measurement
        delete_measurement
        restart_averaging
        phase_unwrap, phase_wrap, phase_flatten
        get_file
    Other useful devices:
        channel_list
        current_channel
        select_trace
        select_traceN
        freq_start, freq_stop, freq_cw
        power_en
        power_dbm_port1, power_dbm_port2
        marker_x, marker_y
        snap_png
        cont_trigger

    Note that almost all devices/commands require a channel.
    It can be specified with the ch option or will use the last specified
    one if left to the default.
    A lot of other commands require a selected trace (per channel)
    The active one can be selected with the trace option or select_trace, select_traceN
    If unspecified, the last one is used.

    If a trace is REMOVED from the instrument, you should perform a get of
    the channel_list device to update pyHegel knowledge of the available
    traces (needed when trying to fetch all traces).
    """
    def init(self, full=False):
        self.write(':format REAL,64')
        self.write(':format:border swap')
        if self.select_trace.get() == '':
            # The newer firmware does not have a trace selected from the start
            # So pick one.
            lst = self.channel_list.getcache()
            self.select_trace.set(list(lst.keys())[0])
        super(agilent_PNAL, self).init(full=full)
    @locked_calling
    def _async_trig(self):
        # we don't use the STATus:OPERation:AVERaging1? status
        # because for n averages they turn on after the n-1 average.
        # Also it is a complex job to figure out which traces to keep track of
        # Here we will assume that _async_trigger_helper ('INITiate;*OPC')
        # starts all the channels (global triggering). It also does a single
        # iteration of an average.
        # We will just count the correct number of repeats to do.
        ch_orig = self.current_channel.getcache()
        ch_list = self.active_channels_list.getcache()
        reps = 1
        for ch in ch_list:
            if self.average_en.get(ch=ch):
                self.restart_averaging(ch) # so instrument displays shows the restart
                count = self.average_count.get()
                reps = max(reps, count)
        self.current_channel.set(ch_orig)
        self._trig_reps_total = reps
        self._trig_reps_current = 0
        self.cont_trigger.set(False)
        super(agilent_PNAL, self)._async_trig()
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        ret = super(agilent_PNAL, self)._async_detect(max_time)
        if not ret:
            # This cycle is not finished
            return ret
        if not self._async_last_esr&1:
            # At least HiSlip on M9046A on Keysight IO 18.2.27313.1 I think it times out (~20s) and returns and event
            # even if none was there (Wireshark does not show the SRQ)
            return False
        # cycle is finished
        self._trig_reps_current += 1
        if self._trig_reps_current < self._trig_reps_total:
            self._async_trigger_helper()
            return False
        return True
    def abort(self):
        self.write('ABORt')
    @locked_calling
    def create_measurement(self, name, param, ch=None):
        """
        name: any unique, non-empty string. If it already exists, we change its param
        param: Any S parameter as S11 or S1_1 (second form only for double-digit port numbers S10_1)
               Ratio measurement, any 2 physical receiver separated by / and followed by , and source port
               like A/R1,3
               Non-Ratio measurement: Any receiver followed by , and source port like A,4
               Ratio and non-ratio can also use logical receiver notation
               ADC measurement: ADC receiver, then , then source por like AI1,2
               Balanced measurment: ...
        """
        ch_list = self.channel_list.get(ch=ch)
        ch=self.current_channel.getcache()
        if name in ch_list:
            self.select_trace.set(name)
            command = 'CALCulate{ch}:PARameter:MODify:EXTended "{param}"'.format(ch=ch, param=param)
        else:
            command = 'CALCulate{ch}:PARameter:EXTended "{name}","{param}"'.format(ch=ch, name=name, param=param)
        self.write(command)
    @locked_calling
    def delete_measurement(self, name=None, ch=None):
        """ delete a measurement.
            if name=None: delete all measurements for ch
            see channel_list for the available measurments
        """
        ch_list = self.channel_list.get(ch=ch)
        ch=self.current_channel.getcache()
        if name is not None:
            if name not in ch_list:
                raise ValueError(self.perror('Invalid Trace name'))
            command = 'CALCulate{ch}:PARameter:DELete "{name}"'.format(ch=ch, name=name)
        else:
            command = 'CALCulate{ch}:PARameter:DELete:ALL'.format(ch=ch)
        self.write(command)
    @locked_calling
    def restart_averaging(self, ch=None):
        #sets ch if necessary
        if not self.average_en.get(ch=ch):
            return
        ch=self.current_channel.getcache()
        command = 'SENSe{ch}:AVERage:CLEar'.format(ch=ch)
        self.write(command)
    def get_file(self, remote_file, local_file=None):
        """
            Obtain the file remote_file from the analyzer and save it
            on this computer as local_file if given, otherwise returns the data
        """
        s = self.ask('MMEMory:TRANsfer? "%s"'%remote_file, raw=True)
        s = _decode_block_base(s)
        if local_file:
            with open(local_file, 'wb') as f:
                f.write(s)
        else:
            return s
    def remote_ls(self, remote_path=None):
        """
            if remote_path is None, get catalog of device remote_cwd.
            It only list files (not directories).
            returns None for empty and invalid directories.
        """
        extra = ""
        if remote_path:
            extra = ' "%s"'%remote_path
        res = self.ask('MMEMory:CATalog?'+extra)
        res = quoted_string()(res)
        if res == 'NO CATALOG':
            return None
        else:
            return res.split(',')
    def send_file(self, dest_file, local_src_file=None, src_data=None, overwrite=False):
        """
            dest_file: is the file name (absolute or relative to device remote_cwd)
                       you can use / to separate directories
            overwrite: when True will skip testing for the presence of the file on the
                       instrument and proceed to overwrite it without asking confirmation.
            Use one of local_src_file (local filename) or src_data (data string)
            Maximum file size is 20 MB.
        """
        if not overwrite:
            # split seeks both / and \
            directory, filename = os.path.split(dest_file)
            ls = self.remote_ls(directory)
            if ls:
                ls = [s.lower() for s in ls]
                if filename.lower() in ls:
                    raise RuntimeError('Destination file already exists. Will not overwrite.')
        if src_data is local_src_file is None:
            raise ValueError('You need to specify one of local_src_file or src_data')
        if src_data and local_src_file:
            raise ValueError('You need to specify only one of local_src_file or src_data')
        if local_src_file:
            with open(local_src_file, 'rb') as f:
                src_data = f.read()
        data_str = _encode_block(src_data)
        # manually add terminiation to prevent warning if data already ends with termination
        self.write('MMEMory:TRANsfer "%s",%s\n'%(dest_file, data_str), termination=None)

    def _fetch_getformat(self, **kwarg):
        unit = kwarg.get('unit', 'default')
        xaxis = kwarg.get('xaxis', True)
        ch = kwarg.get('ch', None)
        traces = kwarg.get('traces', None)
        cook = kwarg.get('cook', False)
        cal = kwarg.get('cal', False)
        if cal:
            cook = False
        if ch is not None:
            self.current_channel.set(ch)
        traces = self._fetch_traces_helper(traces, cal)
        if xaxis:
            sweeptype = self.sweep_type.getcache()
            choice = self.sweep_type.choices
            if sweeptype in choice[['linear', 'log', 'segment']]:
                multi = 'freq(Hz)'
            elif sweeptype in choice[['power']]:
                multi = 'power(dBm)'
            elif sweeptype in choice[['CW']]:
                multi = 'time(s)'
            else: # PHASe
                multi = 'deg' # TODO check this
            multi = [multi]
        else:
            multi = []
        # we don't handle cmplx because it cannot be saved anyway so no header or graph
        for t in traces:
            names = None
            if cook:
                f = self.trace_format.get(trace=t)
                if f not in self.trace_format.choices[['POLar', 'SMITh', 'SADMittance']]:
                    names = ['cook_val']
            if names is None:
                if unit == 'db_deg':
                    names = ['dB', 'deg']
                else:
                    names = ['real', 'imag']
            if cal:
                if isinstance(t, tuple):
                    basename = '%s_%i_%i_'%t
                else:
                    basename = t+'_'
            else:
                name, param = self.select_trace.choices[t]
                basename = "%s=%s_"%(name, param)
            multi.extend( [basename+n for n in names])
        fmt = self.fetch._format
        multi = tuple(multi)
        fmt.update(multi=multi, graph=[], xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_traces_helper(self, traces, cal=False):
        # assume ch is selected
        if cal:
            ch_list = self.calib_data_name_list.get()
        else:
            ch_list = self.channel_list.getcache()
        if isinstance(traces, list) or ((not cal) and isinstance(traces, tuple)):
            traces = traces[:] # make a copy so it can be modified without affecting caller. I don't think this is necessary anymore but keep it anyway.
        elif traces is not None:
            traces = [traces]
        else: # traces is None
            if cal:
                traces = ch_list
            else:
                traces = list(ch_list.keys())
        return traces
    def _fetch_getdev(self, ch=None, traces=None, unit='default', mem=False, xaxis=True, cook=False, cal=False):
        """
           options available: traces, unit, mem and xaxis
            -traces: can be a single value or a list of values.
                     The values are strings representing the trace or the trace number
                     or when cal is True, calibration names like 'Directivity(1,1)'
                     or tuples like ('EDIR', 1, 1)
            -unit:   can be 'default' (real, imag)
                       'db_deg' (db, deg) , where phase is unwrapped
                       'cmplx'  (complexe number), Note that this cannot be written to file
            -mem:    when True, selects the memory trace instead of the active one.
            -xaxis:  when True(default), the first column of data is the xaxis
            -cal:    when True, traces refers to the calibration curves, mem and cook are
                     unused.
            -cook:   when True (default is False) returns the values from the display format
                     They include the possible effects from trace math(edelay, transforms, gating...)
                     as well as smoothing. When this is selected, unit has no effect unless the format is
                     Smith, Polar or Inverted Smith (in which case both real and imaginary are read and
                     converted appropriately)
                     Note that not all the necessary settings are saved in the file headers.
            If you try to read  from ch=200 (for example the ecal viewer), you probably need cook=True.
        """
        if ch is not None:
            self.current_channel.set(ch)
        if cal:
            cook = False
        traces = self._fetch_traces_helper(traces, cal)
        if cook:
            getdata = self.calc_fdata
        else:
            getdata = self.calc_sdata
        if mem:
            if cook:
                getdata = self.calc_fmem
            else:
                getdata = self.calc_smem
        if xaxis:
            if cal:
                ret = [self.calib_freq.get()]
            else:
                # get the x axis of the first trace selected
                self.select_trace.set(traces[0])
                ret = [self.calc_x_axis.get()]
        else:
            ret = []
        for t in traces:
            if cal:
                if isinstance(t, tuple):
                    v = self.calib_data.get(eterm=t[0], p1=t[1], p2=t[2])
                else:
                    v = self.calib_data_name.get(eterm=t)
            else:
                v = getdata.get(trace=t)
            if cook:
                f = self.trace_format.get(trace=t)
                if f not in self.trace_format.choices[['POLar', 'SMITh', 'SADMittance']]:
                    # This next check is required for ENA1 at least
                    if v.size == 2*self.npoints.get():
                        if not np.all(v[1::2] == 0):
                            print(self.perror("WARNING: Discarding non-null data"))
                        v = v[::2]
                    ret.append(v)
                    continue
                v = v[0::2] + 1j*v[1::2]
            if unit == 'db_deg':
                r = 20.*np.log10(np.abs(v))
                theta = np.angle(v, deg=True)
                theta = self.phase_unwrap(theta)
                ret.append(r)
                ret.append(theta)
            elif unit == 'cmplx':
                ret.append(v)
            else:
                ret.append(v.real)
                ret.append(v.imag)
        ret = np.asarray(ret)
        if ret.shape[0]==1:
            ret=ret[0]
        return ret
    @staticmethod
    def phase_unwrap(phase_deg):
        return scipy.rad2deg( scipy.unwrap( scipy.deg2rad(phase_deg) ) )
    @staticmethod
    def phase_wrap(phase_deg):
        return (phase_deg +180.) % 360 - 180.
    @staticmethod
    def phase_flatten(phase_deg, freq, delay=0., ratio=[0,-1]):
        """
           Using an unwrapped phase, this removes a slope.
           if delay is specified, it adds delay*f*360
           If delay is 0. (default) then it uses 2 points
           specified by ratio (defaults to first and last)
           to use to extract slope (delay)
        """
        dp = phase_deg[ratio[1]] - phase_deg[ratio[0]]
        df = freq[ratio[1]] - freq[ratio[0]]
        if delay == 0.:
            delay = -dp/df/360.
            print('Using delay=', delay)
        return phase_deg + delay*freq*360.
    def get_xscale(self):
        return self.x_axis.get()

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        # These all refer to the current channel
        # calib_en depends on trace
        if 'ch' in options:
            self.current_channel.set(options['ch'])
        if 'trace' in options:
            self.select_trace.set(options['trace'])
        if 'mkr' in options:
            self.current_mkr.set(options['mkr'])
        extra = []
        if dev_obj in [self.marker_x, self.marker_y]:
            # Cannot get cache of marker_x while getting marker_x (end up getting an old cache)
            if dev_obj == self.marker_x:
                mxy = 'marker_y'
            else:
                mxy = 'marker_x'
            extra = self._conf_helper('current_mkr', 'marker_format', 'trace_format', 'marker_trac_func', 'marker_trac_en',
                              mxy, 'marker_discrete_en', 'marker_target')
        cook = False
        if dev_obj in [self.readval, self.fetch]:
            cal = options.get('cal', False)
            cook = options.get('cook', False)
            if cal:
                cook = False
            traces_opt = self._fetch_traces_helper(options.get('traces'), cal)
            cal_en = []
            traces = []
            fmts = []
            for t in traces_opt:
                if cal:
                    cal_en.append('Unknown')
                    if isinstance(t, tuple):
                        traces.append('%s_%i_%i'%t)
                    else:
                        traces.append(t)
                else:
                    cal_en.append(self.calib_en.get(trace=t))
                    name, param = self.select_trace.choices[t]
                    traces.append(name+'='+param)
                if cook:
                    fmts.append(self.trace_format.get())
        elif dev_obj == self.snap_png:
            traces = cal_en='Unknown'
        else:
            t=self.select_trace.getcache()
            cal_en = self.calib_en.get()
            name, param = self.select_trace.choices[t]
            traces = name+'='+param
        extra += ['calib_en=%r'%cal_en, 'selected_trace=%r'%traces]
        if cook:
            extra += ['trace_format=%r'%fmts]
        base = self._conf_helper('current_channel', 'freq_cw', 'freq_start', 'freq_stop', 'ext_ref',
                                 'power_en', 'power_couple',
                                 'power_slope', 'power_slope_en',
                                 'power_dbm_port1', 'power_dbm_port2',
                                 'power_mode_port1', 'power_mode_port2',
                                 'npoints', 'sweep_gen', 'sweep_gen_pointsweep',
                                 'sweep_fast_en', 'sweep_time', 'sweep_type',
                                 'bandwidth', 'bandwidth_lf_enh', 'cont_trigger',
                                 'average_count', 'average_mode', 'average_en', options)
        return extra+base
    def _create_devs(self):
        autominmax = False
        if self.idn_split()['model'].upper().startswith('M980'):
            autominmax = True
        self.installed_options = scpiDevice(getstr='*OPT?', str_type=quoted_string())
        self.self_test_results = scpiDevice(getstr='*tst?', str_type=int, doc="""
            Flag bits:
                0=Phase Unlock
                1=Source unleveled
                2=Unused
                3=EEprom write fail
                4=YIG cal failed
                5=Ramp cal failed""")
        self.current_channel = MemoryDevice(1, min=1, max=200)
        self.active_channels_list = scpiDevice(getstr='SYSTem:CHANnels:CATalog?', str_type=quoted_list(element_type=int))
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.channel_list = devChOption(getstr='CALCulate{ch}:PARameter:CATalog:EXTended?', str_type=quoted_dict(protect_sep=('(',')')),
                                        autoinit=10, doc='Note that some "," are replaced by "_"')
        traceN_options = dict(trace=1)
        traceN_options_lim = dict(trace=(1,None))
        # The instrument complains that MEASurement12 is too long (for 2 digit trace)
        # so use just MEAS instead
        # I think it must be a limit of 12 characters for every scpi element (between :)
        # make autoinit=False because the default of trace=1 might not exist
        self.traceN_name = scpiDevice(getstr=':SYSTem:MEAS{trace}:NAME?', str_type=quoted_string(), autoinit=False,
                                      options = traceN_options, options_lim = traceN_options_lim)
        self.traceN_window = scpiDevice(getstr=':SYSTem:MEAS{trace}:WINDow?', str_type=int, autoinit=False,
                                      options = traceN_options, options_lim = traceN_options_lim)
        # windowTrace restarts at 1 for each window
        self.traceN_windowTrace = scpiDevice(getstr=':SYSTem:MEAS{trace}:TRACe?', str_type=int, autoinit=False,
                                      options = traceN_options, options_lim = traceN_options_lim)
        traceN_name_func = self.traceN_name
        select_trace_choices = ChoiceDevSwitch(self.channel_list,
                                               lambda t: traceN_name_func.get(trace=t),
                                               sub_type=quoted_string())
        self.select_trace = devChOption('CALCulate{ch}:PARameter:SELect', autoinit=8,
                                        choices=select_trace_choices, doc="""
                Select the trace using either the trace name (standard ones are 'CH1_S11_1')
                which are unique, the trace param like 'S11' which might not be unique
                (in which case the first one is used), or even the trace number
                which are also unique.""")
        def devCalcOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(trace=self.select_trace)
            app = kwarg.pop('options_apply', ['ch', 'trace'])
            kwarg.update(options=options, options_apply=app)
            return devChOption(*arg, **kwarg)
        # select_trace needs to be set for most of the calc commands
        #calc:par:TNUMber and WNUMber don't exist for our PNAL
        # since select_trace handles the number here we make it only a get
        # but MNUMber could also be a set.
        self.select_trace_N = devCalcOption(getstr='CALCulate{ch}:PARameter:MNUMber?', str_type=int, doc='The number is from the Tr1 annotation next to the parameter nane on the PNA screen')
        self.edelay_length = devCalcOption('CALCulate{ch}:CORRection:EDELay:DISTance', str_type=float)
        self.edelay_length_unit = devCalcOption('CALC{ch}:CORR:EDEL:UNIT', choices=ChoiceStrings('METer', 'FEET', 'INCH'))
        self.edelay_length_medium = devCalcOption('CALC{ch}:CORR:EDEL:MEDium', choices=ChoiceStrings('COAX', 'WAVEguide'))
        self.edelay_time = devCalcOption('CALC{ch}:CORR:EDEL', str_type=float, min=-10, max=10, doc='Set delay in seconds')
        # at least for PXIe VNA, add: PPHase, IMPedance, VOLT, COMPlex
        data_format = ChoiceStrings('MLINear', 'MLOGarithmic', 'PHASe', 'UPHase', 'IMAGinary', 'REAL', 'POLar', 'SMITh', 'SADMittance', 'SWR', 'GDELay', 'KELVin', 'FAHRenheit', 'CELSius', 'PPHase', 'IMPedance', 'VOLT', 'COMPlex')
        self.trace_format = devCalcOption('CALCulate{ch}:FORMat', choices=data_format) # needed when marker_format is 'DEF'
        self.calib_en = devCalcOption('CALC{ch}:CORR', str_type=bool)
        calib_data_options = dict(eterm='EDIR', p1=1, p2=1)
        eterm_options = ChoiceStrings('EDIR', 'ESRM', 'ERFT', 'ELDM', 'ETRT', 'EXTLK', 'ERSPT', 'ERSPI')
        calib_data_options_lim = dict(eterm=eterm_options, p1=(1,4), p2=(1,4))
        calib_data_options_conv = dict(eterm=lambda val, quoted_val: val)
        self.calib_data = devChOption(getstr='SENSe{ch}:CORRection:CSET:DATA? {eterm},{p1},{p2}', str_type=decode_complex128, autoinit=False, raw=True,
                                      options_conv=calib_data_options_conv, options=calib_data_options, options_lim=calib_data_options_lim,
                                      doc="""
                                         You should specify eterm, p1 and p2. They default to EDIR, 1, 1
                                         The various values for eterm are:
                                           EDIR:  directivity
                                           ESRM:  source match
                                           ERFT:  reflection tracking
                                           ELDM:  load match
                                           ETRT:  transmission tracking
                                           EXTLK: crosstalk
                                           ERSPT: response tracking
                                           ERSPI: response isolation
                                         p1 is the measured port when used (otherwise needs to be any valid number)
                                         p2 is the source port when used (otherwise needs to be any valid number)
                                      """)
        self.calib_data_name = devChOption(getstr='SENSe{ch}:CORRection:CSET:ETERm? {eterm}', str_type=decode_complex128, autoinit=False,
                                           options=dict(eterm='Directivity(1,1)'), raw=True,
                                           doc="The eterm should be specified and is the name used in the cal viewer. see calib_data_name_list device")
        self.calib_data_name_list = devChOption(getstr='SENSe{ch}:CORRection:CSET:ETERm:CATalog?',
                                                str_type=quoted_list(protect_sep=('(', ')')), autoinit=False)
        self.calib_current_name = devChOption(getstr='SENSe{ch}:CORRection:CSET:NAME?', str_type=quoted_string(), autoinit=False)
        self.calib_current_desc = devChOption(getstr='SENSe{ch}:CORRection:CSET:DESCription?', str_type=quoted_string(), autoinit=False)
        self.calib_list = scpiDevice(getstr='SENSe:CORRection:CSET:CATalog? NAME', str_type=quoted_list(), autoinit=False)
        self.calib_freq = devChOption(getstr='SENSe{ch}:CORRection:CSET:STIMulus?', str_type=decode_float64, autoinit=False)
        self.snap_png = scpiDevice(getstr='HCOPy:SDUMp:DATA:FORMat PNG;:HCOPy:SDUMp:DATA?', raw=True, str_type=_decode_block_base, autoinit=False)
        self.snap_png._format['bin']='.png'
        self.cont_trigger = scpiDevice('INITiate:CONTinuous', str_type=bool)
        self.bandwidth = devChOption('SENSe{ch}:BANDwidth', str_type=float, setget=True) # can obtain min max
        self.bandwidth_lf_enh = devChOption('SENSe{ch}:BANDwidth:TRACk', str_type=bool)
        self.average_count = devChOption('SENSe{ch}:AVERage:COUNt', str_type=int)
        self.average_mode = devChOption('SENSe{ch}:AVERage:MODE', choices=ChoiceStrings('POINt', 'SWEep'))
        self.average_en = devChOption('SENSe{ch}:AVERage', str_type=bool)
        self.coupling_mode = devChOption('SENSe{ch}:COUPle', choices=ChoiceStrings('ALL', 'NONE'), doc='ALL means sweep mode set to chopped (trans and refl measured on same sweep)\nNONE means set to alternate, imporves mixer bounce and isolation but slower')
        self.freq_start = devChOption('SENSe{ch}:FREQuency:STARt', str_type=float, min=10e6, max=40e9, auto_min_max=autominmax)
        self.freq_stop = devChOption('SENSe{ch}:FREQuency:STOP', str_type=float, min=10e6, max=40e9, auto_min_max=autominmax)
        self.freq_center = devChOption('SENSe{ch}:FREQuency:CENTer', str_type=float, min=10e6, max=40e9, auto_min_max=autominmax)
        self.freq_span = devChOption('SENSe{ch}:FREQuency:SPAN', str_type=float, min=0, max=40e9, auto_min_max=autominmax)
        self.freq_cw= devChOption('SENSe{ch}:FREQuency:CW', str_type=float, min=10e6, max=40e9, auto_min_max=autominmax)
        self.ext_ref = scpiDevice(getstr='SENSe:ROSCillator:SOURce?', str_type=str)
        self.npoints = devChOption('SENSe{ch}:SWEep:POINts', str_type=int, min=1)
        self.sweep_gen = devChOption('SENSe{ch}:SWEep:GENeration', choices=ChoiceStrings('STEPped', 'ANALog'))
        self.sweep_gen_pointsweep =devChOption('SENSe{ch}:SWEep:GENeration:POINtsweep', str_type=bool, doc='When true measure rev and fwd at each frequency before stepping')
        self.sweep_fast_en =devChOption('SENSe{ch}:SWEep:SPEed', choices=ChoiceStrings('FAST', 'NORMal'), doc='FAST increases the speed of sweep by almost a factor of 2 at a small cost in data quality')
        self.sweep_time = devChOption('SENSe{ch}:SWEep:TIME', str_type=float, min=0, max=86400., setget=True)
        self.sweep_type = devChOption('SENSe{ch}:SWEep:TYPE', choices=ChoiceStrings('LINear', 'LOGarithmic', 'POWer', 'CW', 'SEGMent', 'PHASe'))
        self.x_axis = devChOption(getstr='SENSe{ch}:X?', raw=True, str_type=decode_float64, autoinit=False, doc='This gets the default x-axis for the channel (some channels can have multiple x-axis')
        self.calc_x_axis = devCalcOption(getstr='CALC{ch}:X?', raw=True, str_type=decode_float64, autoinit=False, doc='Get this x-axis for a particular trace.')
        self.calc_fdata = devCalcOption(getstr='CALC{ch}:DATA? FDATA', raw=True, str_type=decode_float64, autoinit=False, trig=True)
        # the f vs s. s is complex data, includes error terms but not equation editor (Except for math?)
        #   the f adds equation editor, trace math, {gating, phase corr (elect delay, offset, port extension), mag offset}, formating and smoothing
        self.calc_sdata = devCalcOption(getstr='CALC{ch}:DATA? SDATA', raw=True, str_type=decode_complex128, autoinit=False, trig=True)
        self.calc_fmem = devCalcOption(getstr='CALC{ch}:DATA? FMEM', raw=True, str_type=decode_float64, autoinit=False)
        self.calc_smem = devCalcOption(getstr='CALC{ch}:DATA? SMEM', raw=True, str_type=decode_complex128, autoinit=False)
        self.current_mkr = MemoryDevice(1, min=1, max=15) # was 10, now 15 for PXIe VNA
        def devMkrOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_mkr)
            app = kwarg.pop('options_apply', ['ch', 'trace', 'mkr'])
            kwarg.update(options=options, options_apply=app)
            return devCalcOption(*arg, **kwarg)
        def devMkrEnOption(*arg, **kwarg):
            # This will check if the marker is currently enabled.
            options = kwarg.pop('options', {}).copy()
            options.update(_marker_enabled=self.marker_en)
            options_lim = kwarg.pop('options_lim', {}).copy()
            options_lim.update(_marker_enabled=[True])
            kwarg.update(options=options, options_lim=options_lim)
            return devMkrOption(*arg, **kwarg)
        self.marker_en = devMkrOption('CALC{ch}:MARKer{mkr}', str_type=bool, autoinit=5)
        marker_funcs = ChoiceStrings('NONE', 'MAXimum', 'MINimum', 'RPEak', 'LPEak', 'NPEak', 'TARGet', 'LTARget', 'RTARget', 'COMPression')
        self.marker_trac_func = devMkrEnOption('CALC{ch}:MARKer{mkr}:FUNCtion', choices=marker_funcs)
        # This is set only
        self.marker_exec = devMkrOption('CALC{ch}:MARKer{mkr}:FUNCTION:EXECute', choices=marker_funcs, autoget=False)
        self.marker_target = devMkrEnOption('CALC{ch}:MARKer{mkr}:TARGet', str_type=float)
        marker_format = ChoiceStrings('DEFault', 'MLINear', 'MLOGarithmic', 'IMPedance', 'ADMittance', 'PHASe', 'IMAGinary', 'REAL',
                                      'POLar', 'GDELay', 'LINPhase', 'LOGPhase', 'KELVin', 'FAHRenheit', 'CELSius')
        self.marker_format = devMkrEnOption('CALC{ch}:MARKer{mkr}:FORMat', choices=marker_format)
        self.marker_trac_en = devMkrEnOption('CALC{ch}:MARKer{mkr}:FUNCtion:TRACking', str_type=bool)
        self.marker_discrete_en = devMkrEnOption('CALC{ch}:MARKer{mkr}:DISCrete', str_type=bool)
        self.marker_x = devMkrEnOption('CALC{ch}:MARKer{mkr}:X', str_type=float, trig=True)
        self.marker_y = devMkrEnOption('CALC{ch}:MARKer{mkr}:Y', str_type=decode_float64, multi=['val1', 'val2'], graph=[0,1], trig=True)
        self.power_en = scpiDevice('OUTPut', str_type=bool)
        self.power_couple = devChOption(':SOURce{ch}:POWer:COUPle', str_type=bool)
        self.power_slope = devChOption(':SOURce{ch}:POWer:SLOPe', str_type=float, min=-2, max=2)
        self.power_slope_en = devChOption(':SOURce{ch}:POWer:SLOPe:STATe', str_type=bool)
        # for max min power, ask source:power? max and source:power? min
        self.power_dbm_port1 = devChOption(':SOURce{ch}:POWer1', str_type=float)
        self.power_dbm_port2 = devChOption(':SOURce{ch}:POWer2', str_type=float)
        self.power_mode_port1 = devChOption(':SOURce{ch}:POWer1:MODE', choices=ChoiceStrings('AUTO', 'ON', 'OFF'))
        self.power_mode_port2 = devChOption(':SOURce{ch}:POWer2:MODE', choices=ChoiceStrings('AUTO', 'ON', 'OFF'))
        self.remote_cwd = scpiDevice('MMEMory:CDIRectory', str_type=quoted_string(), autoinit=False,
                                     doc=r"""
                                          instrument default is C:/Program Files/Agilent/Network Analyzer/Documents
                                          You can use / (if you are using \, make sure to use raw string r"" or
                                          double them \\)
                                          """)
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(agilent_PNAL, self)._create_devs()

register_usb_name('PNA network analyser', 0x0957, 0x0118)

# status byte stuff
# There is a bunch of register groups:
#  :status:operation     # 8(256)=averaging, 9(512)=user, 10(1024)=device
#  :status:operation:device  # contains sweep complete 4(16)
#  :status:operation:averaging1 # handles 1 summary of aver2-42(bit0) and traces 1-14 (bit 1:14)
#  :                          2 # handles 1 summary of aver3-42(bit0) and traces 15-28 (bit 1:14)
#  :status:questionable # 9 (512)=inieg, 10(1024)=limit, 11(2048)=define
#  :status:questionable:integrity
#  :status:questionable:limit1
#   ...
#
#  sweep complete and opc give the same information. Note that the status event latches
#   need to be cleared everywhere in order to be reset (STATus:OPERation:AVERaging1, STATus:OPERation:AVERaging2,
#   STATus:OPERation for and average of trace 15-28)
#  Note that average:cond stays True as long as the average count as been reached
#  If average is not enabled, the condition is never set to true
#
# For each group there is
#       :CONDition?   to query instant state
#       [:EVENt]?     To query and reset latch state
#       :NTRansition  To set/query the negative transition latching enable bit flag
#       :PTRansition  To set/query the positive transition latching enable bit flag
#       :ENABle       To set/query the latch to the next level bit flag
#  bit flag can be entered in hex as #Hfff or #hff
#                             oct as #O777 or #o777
#                             bin as #B111 or #b111
#  The connection between condition (instantenous) and event (latch) depends
#  on NTR and PTR. The connection between event (latch) and next level in
#  status hierarchy depends on ENABLE
#
# There are also IEEE status and event groups
# For event: contains *OPC bit, error reports
#       *ESR?    To read and reset the event register (latch)
#       *ESE     To set/query the bit flag that toggles bit 5 of IEEE status
# For IEEE status: contains :operation (bit 7), :questionable (bit 3)
#                           event (bit 5), error (bit 2), message available (bit 4)
#                           Request Service =RQS (bit 6) also MSS (master summary) which
#                                     is instantenous RQS. RQS is latched
#                           Not that first bit is bit 0
# To read error (bit 2): v.ask(':system:error?')
#   that command is ok even without errors
# Message available (bit 4) is 1 after a write be before a read if there was
# a question (?) in the write (i.e. something is waiting to be read)
#
#       the RQS (but not MSS) bit is read and reset by serial poll
#        *STB?   To read (not reset) the IEEE status byte, bit 6 is read as MSS not RQS
#        *SRE    To set/query the bit flag that controls the RQS bit
#                      RQS (bit6) is supposed to be ignored.
# *CLS   is to clear all event registers and empty the error queue.
#
# With both GPIB and USB interface activated. They both have their own status registers
# for STB to OPERATION ...
# They also have their own error queues and most other settings (active measurement for channel,
#   data format) seem to also be independent on the 2 interfaces


#######################################################
##    Agilent ENA network analyzer
#######################################################

#@register_instrument('Agilent Technologies', 'E5061B', 'A.02.09')
@register_instrument('Agilent Technologies', 'E5061B', usb_vendor_product=[0x0957, 0x1309], alias='E5061B ENA')
class agilent_ENA(agilent_PNAL):
    """
    To use this instrument, the most useful device is probably:
        fetch, readval  : Note that for the ENA the traces must be the trace number (cannot be a string)
    Some commands are available:
        abort
        reset_trig: to return to continuous internal trig (use this after readval, will restart
                    the automatic refresh on the instrument display)
        restart_averaging
        phase_unwrap, phase_wrap, phase_flatten
    Other useful devices:
        channel_list
        current_channel
        select_trace
        freq_start, freq_stop, freq_cw
        power_en
        power_dbm_port1, power_dbm_port2
        bias_en, bias_level, bias_port
        marker_x, marker_y
        cont_trigger
        trig_source
    method:
        load_segment

    Note that almost all devices/commands require a channel.
    It can be specified with the ch option or will use the last specified
    one if left to the default.
    A lot of other commands require a selected trace (per channel)
    The active one can be selected with the trace option or select_trace, select_traceN
    If unspecified, the last one is used.
    """
    def init(self, full=False):
        self.write(':format:data REAL')
        self.write(':format:border swap')
        self.reset_trig()
        # skip agilent_PNAL, go directly to its parent.
        super(agilent_PNAL, self).init(full=full)
    def reset_trig(self):
        self.trig_source.set('INTernal')
        self.cont_trigger.set(True)
    @locked_calling
    def _async_trig(self):
        self.cont_trigger.set(False)
        # we bypass the agilent_PNAL _async_trig (our parent) and go to its parent
        super(agilent_PNAL, self)._async_trig()
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        # we bypass the agilent_PNAL _async_detect (our parent) and go to its parent
        return super(agilent_PNAL, self)._async_detect(max_time)
    def _async_trigger_helper(self):
        self.trig_source.set('BUS')
        self.average_triggering_en.set(True)
        self.write(':TRIGger:POINt OFF')
        self.initiate()
        self.write(':TRIGger:SINGle;*OPC')
        #self.trig_source.set('INTernal')
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        # These all refer to the current channel
        # calib_en depends on trace
        if 'ch' in options:
            self.current_channel.set(options['ch'])
        if 'trace' in options:
            self.select_trace.set(options['trace'])
        if 'mkr' in options:
            self.current_mkr.set(options['mkr'])
        extra = []
        if dev_obj in [self.marker_x, self.marker_y]:
            # Cannot get cache of marker_x while getting marker_x (end up getting an old cache)
            if dev_obj == self.marker_x:
                mxy = 'marker_y'
            else:
                mxy = 'marker_x'
            extra = self._conf_helper('current_mkr', 'marker_trac_func', 'trace_format', 'marker_trac_en', mxy,
                              'marker_discrete_en', 'marker_target')
        cook = False
        if dev_obj in [self.readval, self.fetch]:
            cook = options.get('cook', False)
            traces_opt = self._fetch_traces_helper(options.get('traces'))
            traces = []
            fmts = []
            for t in traces_opt:
                name, param = self.select_trace.choices[t]
                traces.append(name+'='+param)
                if cook:
                    fmts.append(self.trace_format.get())
        else:
            traces_opt = self._fetch_traces_helper(None) # get all traces
            name, param = self.select_trace.choices[self.select_trace.getcache()]
            traces = name+'='+param
        extra += ['selected_trace=%r'%traces]
        if cook:
            extra += ['trace_format=%r'%fmts]
        if self._is_E5071C:
            base = self._conf_helper('current_channel',
                                 'calib_en', 'freq_cw', 'freq_start', 'freq_stop', 'ext_ref',
                                 'power_en', 'power_couple',
                                 'power_slope', 'power_slope_en',
                                 'power_dbm_port1', 'power_dbm_port2',
                                 'power_dbm_port3', 'power_dbm_port4',
                                 'bias_en', 'bias_level', 'bias_port',
                                 'npoints', 'sweep_gen',
                                 'sweep_time', 'sweep_type',
                                 'bandwidth', 'bandwidth_auto_en', 'bandwidth_auto_limit', 'cont_trigger',
                                 'average_count', 'average_en', options)
        else:
            base = self._conf_helper('current_channel',
                                 'calib_en', 'freq_cw', 'freq_start', 'freq_stop', 'ext_ref',
                                 'power_en', 'power_couple',
                                 'power_slope', 'power_slope_en',
                                 'power_dbm_port1', 'power_dbm_port2',
                                 'bias_en', 'bias_level', 'bias_port',
                                 'npoints',
                                 'sweep_time', 'sweep_type',
                                 'bandwidth', 'bandwidth_auto_en', 'bandwidth_auto_limit', 'cont_trigger',
                                 'average_count', 'average_en', options)
        return extra+base
    def _fetch_traces_helper(self, traces, cal=False):
        if cal:
            raise NotImplementedError('cal=True is not implemented for ena1')
        count = self.select_trace_count.getcache()
        trace_orig = self.select_trace.getcache()
        all_tr = list(range(1,count+1))
        # First create the necessary entries, so that select_trace works
        self.select_trace.choices = {i:('%i'%i, 'empty') for i in all_tr}
        # Now fill them properly (trace_meas, uses select_trace and needs to access them)
        self.select_trace.choices = {i:('%i'%i, self.trace_meas.get(trace=i)) for i in all_tr}
        self.select_trace.set(trace_orig)
        if isinstance(traces, (tuple, list)):
            traces = traces[:] # make a copy so it can be modified without affecting caller. I don't think this is necessary anymore but keep it anyway.
        elif traces is not None:
            traces = [traces]
        else: # traces is None
            traces = all_tr
        return traces
    @locked_calling
    def initiate(self):
        """ Enables the current channel for triggering purposes """
        ch = self.current_channel.getcache()
        self.write('INITiate%i'%ch)
    def load_segment(self, filename):
        """ To load from the instrument disk a file describing the
            segments to use.
            Make sure to select the table shape (start/stop or center/span,
            power or no power, etc...) to be the same as the content of the file
            before loading, otherwise the load will fail or be wrong.
            Ex:
                ena1.load_segment('d:/Segments/SEGM100MHz.csv')
            You can use either forward or backslash (but be careful with
            backslash, might need r'd:\\test.csv' or double them 'd:\\\\test.csv')
        """
        self.write('MMEMory:LOAD:SEGMent "%s"'%filename)
    def _create_devs(self):
        idn = self.idn()
        self._is_E5071C = 'E5071C' in idn.split(',')[1]
        self.create_measurement = None
        self.delete_measurement = None
        self.installed_options = scpiDevice(getstr='*OPT?', str_type=str)
        self.current_channel = MemoryDevice(1, min=1, max=160)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        # Either: CALCulate{ch}:PARameter{tr}:SELect (write only)
        #         CALCulate{ch}:PARemeter:COUNt
        # select_trace is needed by PNAL:fetch so we cannot rename it to current_trace.
        self.select_trace = MemoryDevice(1, min=1, max=16)
        #self.select_trace = devChOption('CALCulate{ch}:PARameter{val}:SELect', autoinit=8, autoget=False, str_type=int, min=1, max=16)
        self.select_trace_count = devChOption('CALCulate{ch}:PARameter:COUNt', str_type=int)
        def devCalcOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(trace=self.select_trace)
            app = kwarg.pop('options_apply', ['ch', 'trace'])
            kwarg.update(options=options, options_apply=app)
            return devChOption(*arg, **kwarg)
        # select_trace needs to be set for most of the calc commands
        self.trace_meas = devCalcOption('CALCulate{ch}:PARameter{trace}:DEFine')
        data_format = ChoiceStrings('MLINear', 'MLOGarithmic', 'PHASe', 'UPHase', 'PPHase', 'IMAGinary', 'REAL', 'POLar', 'PLINear', 'PLOGarithmic', 'SMITh', 'SADMittance', 'SLINear', 'SCOMplex', 'SLOGarithmic', 'SWR', 'GDELay')
        self.trace_format = devCalcOption('CALCulate{ch}:FORMat', choices=data_format) # needed when marker_format is 'DEF'
        self.calib_en = devChOption('SENSe{ch}:CORRection:STATe', str_type=bool)
        self.cont_trigger = devChOption('INITiate{ch}:CONTinuous', str_type=bool)
        self.bandwidth = devChOption('SENSe{ch}:BANDwidth', str_type=float, setget=True) # can obtain min max
        self.bandwidth_auto_en = devChOption('SENSe{ch}:BWAuto', str_type=bool)
        self.bandwidth_auto_limit = devChOption('SENSe{ch}:BWAuto:LIMit', str_type=float, setget=True)
        self.average_count = devChOption('SENSe{ch}:AVERage:COUNt', str_type=int)
        self.average_en = devChOption('SENSe{ch}:AVERage', str_type=bool)
        self.average_triggering_en = devChOption('TRIGger:AVERage', str_type=bool)
        self.freq_start = devChOption('SENSe{ch}:FREQuency:STARt', str_type=float, min=5, max=3e9)
        self.freq_stop = devChOption('SENSe{ch}:FREQuency:STOP', str_type=float, min=5, max=3e9)
        self.freq_cw= devChOption('SENSe{ch}:FREQuency:CW', str_type=float, min=5, max=3e9)
        self.ext_ref = scpiDevice(getstr='SENSe:ROSCillator:SOURce?', str_type=str)
        self.npoints = devChOption('SENSe{ch}:SWEep:POINts', str_type=int, min=2, max=20001)
        if self._is_E5071C:
            self.sweep_gen = devChOption('SENSe{ch}:SWEep:GENeration', choices=ChoiceStrings('STEPped', 'ANALog', 'FSTepped', 'FANalog'))
        self.sweep_time = devChOption('SENSe{ch}:SWEep:TIME', str_type=float, min=0, max=86400.)
        self.sweep_type = devChOption('SENSe{ch}:SWEep:TYPE', choices=ChoiceStrings('LINear', 'LOGarithmic', 'POWer', 'SEGMent'))
        self.calc_x_axis = devCalcOption(getstr='CALC{ch}:TRACe{trace}:DATA:XAXIs?', raw=True, str_type=decode_float64, autoinit=False, doc='Get this x-axis for a particular trace.')
        self.calc_fdata = devCalcOption(getstr='CALC{ch}:TRACe{trace}:DATA:FDATa?', raw=True, str_type=decode_float64, autoinit=False, trig=True)
        # the f vs s. s is complex data, includes error terms but not equation editor (Except for math?)
        #   the f adds equation editor, trace math, {gating, phase corr (elect delay, offset, port extension), mag offset}, formating and smoothing
        self.calc_sdata = devCalcOption(getstr='CALC{ch}:TRACe{trace}:DATA:SDATa?', raw=True, str_type=decode_complex128, autoinit=False, trig=True)
        self.calc_fmem = devCalcOption(getstr='CALC{ch}:TRACe{trace}:DATA:FMEMory?', raw=True, str_type=decode_float64, autoinit=False)
        self.calc_smem = devCalcOption(getstr='CALC{ch}:TRACe{trace}:DATA:SMEMory?', raw=True, str_type=decode_complex128, autoinit=False)
        self.current_mkr = MemoryDevice(1, min=1, max=10)
        def devMkrOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_mkr)
            app = kwarg.pop('options_apply', ['ch', 'trace', 'mkr'])
            kwarg.update(options=options, options_apply=app)
            return devCalcOption(*arg, **kwarg)
        def devMkrEnOption(*arg, **kwarg):
            # This will check if the marker is currently enabled.
            options = kwarg.pop('options', {}).copy()
            options.update(_marker_enabled=self.marker_en)
            options_lim = kwarg.pop('options_lim', {}).copy()
            options_lim.update(_marker_enabled=[True])
            kwarg.update(options=options, options_lim=options_lim)
            return devMkrOption(*arg, **kwarg)
        self.marker_en = devMkrOption('CALC{ch}:TRACe{trace}:MARKer{mkr}', str_type=bool, autoinit=5)
        marker_funcs = ChoiceStrings('MAXimum', 'MINimum', 'PEAK', 'RPEak', 'LPEak', 'TARGet', 'LTARget', 'RTARget')
        self.marker_trac_func = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:FUNCtion', 'CALC{ch}:MARKer{mkr}:FUNCtion:TYPE?', choices=marker_funcs)
        # This is set only
        self.marker_exec = devMkrOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:FUNCTION:EXECute', choices=marker_funcs, autoget=False)
        self.marker_target = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:FUNCtion:TARGet', str_type=float)
        self.marker_trac_en = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:FUNCtion:TRACking', str_type=bool)
        self.marker_discrete_en = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:DISCrete', str_type=bool)
        self.marker_x = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:X', str_type=float, trig=True)
        self.marker_y = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:Y', str_type=decode_float64, multi=['val1', 'val2'], graph=[0,1], trig=True)
        self.bias_en = scpiDevice('SOURce:BIAS:ENABle', str_type=bool)
        self.bias_level = scpiDevice('SOURce:BIAS:VOLTage', str_type=float, min=-40, max=40, doc="In volt.", setget=True)
        self.bias_port = scpiDevice('SOURce:BIAS:PORT', choices=ChoiceStrings('LFOut', 'P1'))
        self.power_en = scpiDevice('OUTPut', str_type=bool)
        self.power_couple = devChOption(':SOURce{ch}:POWer:PORT:COUPle', str_type=bool)
        self.power_slope = devChOption(':SOURce{ch}:POWer:SLOPe', str_type=float, min=-2, max=2)
        self.power_slope_en = devChOption(':SOURce{ch}:POWer:SLOPe:STATe', str_type=bool)
        # for max min power, ask source:power? max and source:power? min
        self.power_dbm_port1 = devChOption(':SOURce{ch}:POWer:PORT1', str_type=float)
        self.power_dbm_port2 = devChOption(':SOURce{ch}:POWer:PORT2', str_type=float)
        if self._is_E5071C:
            self.power_dbm_port3 = devChOption(':SOURce{ch}:POWer:PORT3', str_type=float)
            self.power_dbm_port4 = devChOption(':SOURce{ch}:POWer:PORT4', str_type=float)
        self.trig_source = scpiDevice(':TRIGger:SOURce',
                                      choices=ChoiceStrings('INTernal', 'EXTernal', 'MANual', 'BUS'))
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(agilent_PNAL, self)._create_devs()

#######################################################
##    Agilent FieldFox network analyzer
#######################################################

#@register_instrument('Agilent Technologies', 'N9916A', 'A.07.29,2014-02-20.14:09')
@register_instrument('Agilent Technologies', 'N9916A', alias='N9916A FieldFox')
class agilent_FieldFox(agilent_PNAL):
    """
    The output is turned off when the device is in hold state (set cont_trig off to go in hold state).
    The instrument does not output sine waves (they are square waves, especially at lower frequencies were
    it is high passed square waves.)
    To use this instrument, the most useful device are probably:
        fetch, readval
    Some commands are available:
        abort
        reset_trig: to return to continuous internal trig (use this after readval, will restart
                    the automatic refresh on the instrument display)
        restart_averaging
        phase_unwrap, phase_wrap, phase_flatten
    Other useful devices:
        channel_list
        select_trace
        freq_start, freq_stop
        power_dbm_port1
        marker_x, marker_y
        cont_trigger
        trig_source
        snap_png
        bias_en, bias_volt, bias_src_state

    A lot of other commands require a selected trace (per channel)
    The active one can be selected with the trace option or select_trace
    If unspecified, the last one is used.
    """
    def init(self, full=False):
        self.write(':format REAL,64')
        self.write(':format:border NORMal')
        self.reset_trig()
        # skip agilent_PNAL, go directly to its parent.
        super(agilent_PNAL, self).init(full=full)
    def reset_trig(self):
        #self.trig_source.set('INTernal')
        self.cont_trigger.set(True)
    @locked_calling
    def _async_trig(self):
        # similar to PNAL version
        # Here we will assume that _async_trigger_helper ('INITiate;*OPC')
        # does a single iteration of an average.
        # We will just count the correct number of repeats to do (_async_detect)
        reps = 1
        if self.average_mode.get() in self.average_mode.choices[['sweep']]:
            reps = self.average_count.get()
            if reps>1:
                self.restart_averaging()
        else:
            reps = 1
        self._trig_reps_total = reps
        self._trig_reps_current = 0
        self.cont_trigger.set(False)
        super(agilent_PNAL, self)._async_trig()
    #def _async_detect(self, max_time=.5): # 0.5 s max by default
    #    return super(agilent_PNAL, self)._async_detect(max_time)
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        # These all refer to the current channel
        # calib_en depends on trace
        if 'trace' in options:
            self.select_trace.set(options['trace'])
        if 'mkr' in options:
            self.current_mkr.set(options['mkr'])
        extra = []
        if dev_obj in [self.marker_x, self.marker_y]:
            # Cannot get cache of marker_x while getting marker_x (end up getting an old cache)
            if dev_obj == self.marker_x:
                mxy = 'marker_y'
            else:
                mxy = 'marker_x'
            extra = self._conf_helper('current_mkr', 'marker_en', mxy,
                              'marker_data_mem_sel', 'marker_format', 'trace_format')
        cook = False
        if dev_obj in [self.readval, self.fetch]:
            cook = options.get('cook', False)
            traces_opt = self._fetch_traces_helper(options.get('traces'))
            traces = []
            fmts = []
            for t in traces_opt:
                name, param = self.select_trace.choices[t]
                traces.append("%s=%s"%(name,param))
                if cook:
                    fmts.append(self.trace_format.get())
        else:
            traces_opt = self._fetch_traces_helper(None) # get all traces
            name, param = self.select_trace.choices[self.select_trace.getcache()]
            traces = "%s=%s"%(name,param)
        extra += ['selected_trace=%r'%traces]
        if cook:
            extra += ['trace_format=%r'%fmts]
        base = self._conf_helper('installed_options', 'current_mode',
                                 'bias_en', 'bias_volt', 'bias_src_state', 'bias_volt_meas', 'bias_curr_meas',
                                 'power_mode_port1', 'power_dbm_port1',
                                 'calib_en', 'freq_start', 'freq_stop', 'ext_ref',
                                 'npoints', 'sweep_time',
                                 'bandwidth', 'cont_trigger', 'trig_source',
                                 'average_count', 'average_mode', options)
        return extra+base
    def restart_averaging(self):
        command = 'SENSe:AVERage:CLEar'
        self.write(command)
    def _channel_list_getdev(self):
        """ returns the list of available channels """
        #return list(range(1, self.select_trace_count.getcache() +1))
        lst = list(range(1, self.select_trace_count.get() +1))
        return {k:self.trace_meas.get(trace=k) for k in lst}
    def get_file(self, remote_file, local_file=None):
        """
            Obtain the file remote_file from the analyzer and save it
            on this computer as local_file if given.
        """
        s = self.ask('MMEMory:DATA? "%s"'%remote_file, raw=True)
        s = _decode_block_base(s)
        if local_file:
            with open(local_file, 'wb') as f:
                f.write(s)
        else:
            return s
    def _snap_png_getdev(self):
        tmpfile_d = '[INTERNAL]:'
        tmpfile_f = 'TempScreenGrab.png'
        tmpfile_p = tmpfile_d + '\\' + tmpfile_f
        prevdir = self.ask('MMEMory:CDIRectory?')
        self.write('MMEMory:CDIRectory "%s"'%tmpfile_d)
        self.write('MMEMory:STORe:IMAGe "%s"'%tmpfile_f)
        self.write('MMEMory:CDIRectory %s'%prevdir)
        ret = self.get_file(tmpfile_p)
        self.write('MMEMory:DELete "%s"'%tmpfile_p)
        return ret
    def _bias_en_setdev(self, val):
        if val:
            self.write('SYSTem:VVS:ENABle ON')
        else:
            self.write('SYSTem:VVS:ENABle OFF')
        #self._bias_en.set(val)
    def _bias_en_getdev(self):
        state = self.bias_src_state.get()
        if state.lower() == 'on':
            return True
        return False # for OFF and Tripped
    def _fetch_getdev(self, traces=None, unit='default', mem=False, xaxis=True):
        """
           options available: traces, unit, mem and xaxis
            -traces: can be a single value or a list of values.
                     The values are strings representing the trace or the trace number
            -unit:   can be 'default' (real, imag)
                       'db_deg' (db, deg) , where phase is unwrapped
                       'cmplx'  (complexe number), Note that this cannot be written to file
            -mem:    when True, selects the memory trace instead of the active one.
            -xaxis:  when True(default), the first column of data is the xaxis
        """
        return super(agilent_FieldFox, self)._fetch_getdev(ch=None, traces=traces, unit=unit, mem=mem, xaxis=xaxis)
    def _create_devs(self):
        # Similar commands to ENA or PNAL but without channels
        self.installed_options = scpiDevice(getstr='*OPT?', str_type=quoted_string())
        self.available_modes = scpiDevice(getstr='INSTrument:CATalog?', str_type=quoted_list(sep='","'))
        # INSTRUMENT only accepts the upper version CAT and NA (not cat or na)
        if self.ask('INSTrument?') != '"NA"':
            raise ValueError("This instruments only works if the FieldFox is in NA (network analyzer) mode. Not it SA or CAT mode.")
        self.current_mode = scpiDevice('INSTrument', choices=['CAT', 'NA'], str_type=quoted_string())
        self.ext_ref = scpiDevice(getstr='SENSe:ROSCillator:SOURce?', str_type=str)
        self.cont_trigger = scpiDevice('INITiate:CONTinuous', str_type=bool)
       # Here we only handle the NA mode
        # DC bias (option 309)
        #self._bias_en = scpiDevice('SYSTem:VVS:ENABle', str_type=bool, autoget=False)
        self._devwrap('bias_en')
        self.bias_volt = scpiDevice('SYSTem:VVS:VOLTage', str_type=float, min=1., max=32., setget=True)
        self.bias_volt_meas = scpiDevice(getstr='SYSTem:VVS:MVOLtage?', str_type=float)
        self.bias_curr_meas = scpiDevice(getstr='SYSTem:VVS:CURRent?', str_type=float)
        self.bias_src_state = scpiDevice(getstr='SYSTem:VVS?', doc="can be on, off or tripped. To clear toggle the enable.")
        # end of Bias
        #self.power_en = scpiDevice('SOURce:ENABle', str_type=bool)
        self.power_dbm_port1 = scpiDevice(':SOURce:POWer', str_type=float, min=-45., max=3., setget=True, doc="""
                       Note that the power set by this device is not leveled. The instrument can
                       produce warnings of unlevel for high power/high frequency.
                       If you want a leveled high power, use power_mode_port1 device with 'HIGH' instead""")
        self.power_mode_port1 = scpiDevice('SOURce:POWer:ALC', choices=ChoiceStrings('HIGH', 'LOW', 'MAN'))
        #tmpfile = r'"[INTERNAL]:\TempScreenGrab.png"'
        #self.snap_png = scpiDevice(getstr='MMEMory:STORe:IMAGe %s;:MMEMory:DATA? %s;:MMEMory:DELete %s'%(tmpfile,tmpfile,tmpfile),
        #                           raw=True, str_type=_decode_block_base, autoinit=False)
        self._devwrap('snap_png', autoinit=False)
        self.snap_png._format['bin']='.png'
        self.freq_start = scpiDevice('SENSe:FREQuency:STARt', str_type=float, min=30e3, max=14e9)
        self.freq_stop = scpiDevice('SENSe:FREQuency:STOP', str_type=float, min=30e3, max=14e9)
        self.freq_center = scpiDevice('SENSe:FREQuency:CENTer', str_type=float, min=30e3, max=14e9)
        self.freq_span = scpiDevice('SENSe:FREQuency:SPAN', str_type=float, min=0, max=14e9-30e3)
        self.x_axis = scpiDevice(getstr='SENSe:FREQuency:DATA?', raw=True, str_type=decode_float64, autoinit=False)
        self.calc_x_axis = self.x_axis # needed by fetch
        self.npoints = scpiDevice('SENSe:SWEep:POINts', str_type=int, min=2, max=10001)
        self.sweep_time = scpiDevice('SENSe:SWEep:TIME', str_type=float, min=0, max=100., doc='This changes the minimum sweep time, it can be longer.')
        self.bandwidth = scpiDevice('SENSe:BWID', str_type=float, min=10., max=30e3, setget=True, doc="only certain values are available")
        self.average_count = scpiDevice('SENSe:AVERage:COUNt', str_type=int, min=1, max=100, doc='count of 1 disables averaging')
        self.average_mode = scpiDevice('SENSe:AVERage:MODE', choices=ChoiceStrings('POINt', 'SWEep'))
        self.calib_en = scpiDevice('SENSe:CORRection:STATe', str_type=bool)
        # needed by PNAL fetch
        class sweep_type_C(object):
            def getcache(self):
                return 'linear'
            choices = ChoiceStrings('LINear', 'LOGarithmic', 'POWer', 'CW', 'SEGMent', 'PHASe')
        self.sweep_type = sweep_type_C()
        self.select_trace_count = scpiDevice('CALCulate:PARameter:COUNt', str_type=int, min=1, max=4)
        # select_trace needs to be set for most of the calc commands
        self._devwrap('channel_list', autoinit=8)
        select_trace_choices = ChoiceDev(self.channel_list, sub_type=int)
        select_trace_choices2 = ChoiceDevDep(self.select_trace_count, {1:[1], 2:[1,2], 3:[1,2,3], 4:[1,2,3,4]})
        # select_trace is needed by PNAL:fetch so we cannot rename it to current_trace.
        self.select_trace = MemoryDevice(1, choices=select_trace_choices)
        self.select_trace1 = scpiDevice('CALCulate:PARameter{val}:SELect', autoinit=8, autoget=False,
                                        choices=select_trace_choices, doc="""
                Select the trace using the trace number (1-4).""")
        self.select_trace2 = scpiDevice('CALCulate:PARameter{val}:SELect', autoinit=8, autoget=False,
                                        choices=select_trace_choices2, doc="""
                Select the trace using the trace number (1-4).""")
        #self.select_trace3 = scpiDevice('CALCulate:PARameter{val}:SELect', autoinit=8, str_type=int, min=1, max=4,  autoget=False,
        #                                 doc="""Select the trace using the trace number (1-4).""")
        #self.select_trace4 = scpiDevice('CALCulate:PARameter{val}:SELect', autoinit=False, autoget=False, get_cached_init=1,
        #                                choices=select_trace_choices2, str_type=int)
        def devCalcOption(*arg, **kwarg):
            extra='CALCulate:PARameter{trace}:SELect;:'
            if len(arg):
                arg = list(arg) # arg was a tuple
                arg[0] = extra+arg[0]
            if 'getstr' in kwarg:
                gs = extra + kwarg['getstr']
                kwarg.update(getstr=gs)
            options = kwarg.pop('options', {}).copy()
            options.update(trace=self.select_trace)
            app = kwarg.pop('options_apply', ['trace'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)

        self.edelay_time = devCalcOption('CALCulate:CORRection:EDELay:TIME', str_type=float, doc='delay in seconds')
        self.edelay_rel_vel = scpiDevice('SENSe:CORRection:RVELocity:COAX', str_type=float, min=0, max=1, doc='.66 = polyethylene dielectric, .7= PTFE dielectric, 1.0=Air')
        self.edelay_length_medium = scpiDevice('SENSe:CORRection:MEDium', choices=ChoiceStrings('COAX', 'WAVeguide'))

        # select_trace needs to be set for most of the calc commands
        #calc:par:TNUMber and WNUMber don't exist for our PNAL
        # since select_trace handles the number here we make it only a get
        # but MNUMber could also be a set.
        #self.select_trace_N = devCalcOption(getstr='CALCulate{ch}:PARameter:MNUMber?', str_type=int, doc='The number is from the Tr1 annotation next to the parameter nane on the PNA screen')
        self.calc_fdata = devCalcOption(getstr='CALCulate:DATA:FDATa?', raw=True, str_type=decode_float64, autoinit=False, trig=True)
        # the f vs s. s is complex data, includes error terms but not equation editor (Except for math?)
        #   the f adds equation editor, trace math, {gating, phase corr (elect delay, offset, port extension), mag offset}, formating and smoothing
        self.calc_sdata = devCalcOption(getstr='CALCulate:DATA:SDATa?', raw=True, str_type=decode_complex128, autoinit=False, trig=True)
        self.calc_fmem = devCalcOption(getstr='CALCulate:DATA:FMEM?', raw=True, str_type=decode_float64, autoinit=False)
        self.calc_smem = devCalcOption(getstr='CALCulate:DATA:SMEM?', raw=True, str_type=decode_complex128, autoinit=False)
        self.current_mkr = MemoryDevice(1, min=1, max=6)
        self.marker_coupling_en = devCalcOption('CALC:MARKer:COUPled', str_type=bool)
        def devMkrOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_mkr)
            app = kwarg.pop('options_apply', ['trace', 'mkr'])
            kwarg.update(options=options, options_apply=app)
            return devCalcOption(*arg, **kwarg)
        maker_en_choices = ChoiceStrings('OFF', 'NORM', 'DELT')
        self.marker_en = devMkrOption('CALC:MARKer{mkr}', choices=maker_en_choices, autoinit=5)
        def devMkrEnOption(*arg, **kwarg):
            # This will check if the marker is currently enabled.
            options = kwarg.pop('options', {}).copy()
            options.update(_marker_enabled=self.marker_en)
            options_lim = kwarg.pop('options_lim', {}).copy()
            options_lim.update(_marker_enabled=maker_en_choices[1:])
            kwarg.update(options=options, options_lim=options_lim)
            return devMkrOption(*arg, **kwarg)
        data_format = ChoiceStrings('MLOGarithmic', 'MLINear', 'SWR', 'PHASe', 'UPHase', 'SMITh', 'POLar', 'GDELay')
        self.trace_format = devCalcOption('CALCulate:FORMat', choices=data_format) # needed when marker_format is 'DEF'
        marker_format = ChoiceStrings('DEF', 'IMPedance', 'PHASe', 'IMAGinary', 'REAL', 'MAGPhase', 'ZMAGnitude')
        self.marker_format = devCalcOption('CALC:MARKer:FORMat', choices=marker_format, doc="The format applies to all marker from one trace")
        self.marker_x = devMkrOption('CALC:MARKer{mkr}:X', str_type=float, trig=True)
        self.marker_y = devMkrEnOption(getstr='CALC:MARKer{mkr}:Y?', str_type=decode_float64, multi=['val1', 'val2'], graph=[0,1], trig=True)
        self.marker_data_mem_sel = devMkrOption('CALC:MARKer{mkr}:TRACe', choices=ChoiceIndex(['auto', 'data', 'mem']))
        # TODO smoothing affects marker data so does edelay ...

        self.create_measurement = None
        self.delete_measurement = None
        #self.trace_meas = devCalcOption('CALCulate:PARameter{trace}:DEFine',
        #                                choices=ChoiceStrings('S11', 'S12', 'S21', 'S22', 'A', 'B', 'R1', 'R2'))
        #self.trace_meas = scpiDevice('CALCulate:PARameter{trace}:DEFine', options=dict(trace=self.select_trace), options_lim=dict(trace=(1,4)),
        #                                choices=ChoiceStrings('S11', 'S12', 'S21', 'S22', 'A', 'B', 'R1', 'R2'))
        self.trace_meas = scpiDevice('CALCulate:PARameter{trace}:DEFine', options=dict(trace=1), options_lim=dict(trace=(1,4)),
                                        doc="trace always defaults to 1 and does not change select_trace.",
                                        choices=ChoiceStrings('S11', 'S12', 'S21', 'S22', 'A', 'B', 'R1', 'R2'))
        self.trig_source = scpiDevice('TRIGger:SOURce', choices=ChoiceStrings('INTernal', 'EXTernal'))
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(agilent_PNAL, self)._create_devs()


#######################################################
##    Agilent M8190A Arbitrary Waveform Generator
#######################################################

#@register_instrument('Agilent Technologies', 'M8190A', '5.0.14.0-2')
@register_instrument('Agilent Technologies', 'M8190A', alias='M8190A AWG')
class agilent_AWG(visaInstrumentAsync):
    """
    This is to control the M8190A Arbitrary Waveform Generator.
    It has 2 independent channels that can be coupled (for start/stop)
    and each channel can be with 12 bit @ 12 GS/s max of 2 GS or 14 bit @ 8 GS/s
    max of 1.5 GS.
    For the binary files:
     DAC values are signed. The data is in the most significant bits,
      so bits 15-2 in 14 bit mode and 15-4 in 12 bit mode (then bits 3 and 2 are
      don't care). Bit 1 is the sequence marker, bit 0 is the sample marker.
     Data needs to be in blocks (or vectors). Only the sequence marker of the first
     sample in a vector is used.
     The vector length is 48 samples in 14 bits mode and 64 in 12 bits mode.
     The smallest common multiple of 48 and 64 is 192.
     The minimum length is 5 vectors (240 samples in 14 bits, 320 for 12 bits)

    The voltage amplitude can be set with either volt_amplitude, volt_offset
    or volt_high, volt_low (volt_ampl is peak to peak amplitude)
    There is one sampling frequency for both channels.
    Many options depend on the channel.

    If something looks like it is not working, you might be creating errors so
    first check the get_error function return.
    """
    def init(self, full=False):
        self.write(':format:border swap')
        # initialize async stuff
        super(agilent_AWG, self).init(full=full)
        self._async_trigger_helper_string = '*OPC'
    def _async_trigger_helper(self):
        self.write(self._async_trigger_helper_string)
        #self._async_trigger_helper_string = '*OPC'
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        orig_ch = self.current_channel.getcache()
        ch_list = ['current_channel', 'freq_source', 'cont_trigger', 'gate_mode_en', 'output_en',
                                'delay_coarse', 'delay_fine', 'volt_ampl', 'volt_offset',
                                'sample_marker_volt_ampl', 'sample_marker_volt_offset',
                                'sync_marker_volt_ampl', 'sync_marker_volt_offset',
                                'dac_format', 'differential_offset', 'speed_mode',
                                'advance_mode', 'repeat_count', 'marker_en', 'segment_list']
        self.current_channel.set(1)
        ch1 = self._conf_helper(*ch_list)
        self.current_channel.set(2)
        ch2 = self._conf_helper(*ch_list)
        self.current_channel.set(orig_ch)
        return ch1+ch2+self._conf_helper('coupled_en', 'freq_sampling', 'freq_ext',
                                         'ref_source', 'ref_freq', options)
    def _create_devs(self):
        self.current_channel = MemoryDevice(1, min=1, max=2)
        self.coupled_en = scpiDevice(':INSTrument:COUPle:STATe', str_type=bool)
        self.freq_sampling = scpiDevice(':FREQuency:RASTer', str_type=float)
        self.freq_ext = scpiDevice(':FREQuency:RASTer:EXTernal', str_type=float)
        self.ref_source = scpiDevice(':ROSCillator:SOURce', choices=ChoiceStrings('AXI', 'EXTernal'))
        self.ref_freq = scpiDevice(':ROSCillator:FREQuency', str_type=float)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.freq_source = devChOption(':FREQuency:RASTer:SOURce{ch}', choices=ChoiceStrings('INTernal', 'EXTernal'))
        self.cont_trigger = devChOption(':INITiate:CONTinuous{ch}', str_type=bool)
        self.gate_mode_en = devChOption(':INITiate:GATE{ch}', str_type=bool, doc=
            """
            When cont_trigger is False, selects between gate or trigger mode of triggering.
            Under gating mode, the segment repeating is started after the rising edge
            of the gating signal. When the falling edge is detected, repeat_count
            segments are produced and then stops.
            """)
        #self.arming_mode = devChOption(':INITiate:CONTinuous{ch}:ENABle', choices=ChoiceStrings('SELF', 'ARMed'))
        self.output_en = devChOption(':OUTPut{ch}', str_type=bool)
        self.delay_coarse = devChOption(':ARM:CDELay{ch}', str_type=float, min=0, max=10e-9)
        self.delay_fine = devChOption(':ARM:DELay{ch}', str_type=float, min=0, max=150e-12, doc='max delay is 60e-12 between 2.5 and 6.25 GS/s and 30e-12 above 6.25 GS/s')
        self.volt_ampl = devChOption(':VOLTage{ch}', str_type=float, min=.35, max=0.7)
        self.volt_offset = devChOption(':VOLTage{ch}:OFFSet', str_type=float, min=-.02, max=0.02)
        self.volt_high = devChOption(':VOLTage{ch}:HIGH', str_type=float, min=.155, max=.37)
        self.volt_low = devChOption(':VOLTage{ch}:LOW', str_type=float, min=-0.37, max=0.155)
        self.sample_marker_volt_ampl = devChOption(':MARKer{ch}:SAMPle:VOLTage:AMPLitude', str_type=float, min=0., max=2.25)
        self.sample_marker_volt_offset = devChOption(':MARKer{ch}:SAMPle:VOLTage:OFFSet', str_type=float, min=-0.5, max=1.75)
        self.sample_marker_volt_high = devChOption(':MARKer{ch}:SAMPle:VOLTage:HIGH', str_type=float, min=0.5, max=1.75)
        self.sample_marker_volt_low = devChOption(':MARKer{ch}:SAMPle:VOLTage:LOW', str_type=float, min=-0.5, max=1.75)
        self.sync_marker_volt_ampl = devChOption(':MARKer{ch}:SYNC:VOLTage:AMPLitude', str_type=float, min=0., max=2.25)
        self.sync_marker_volt_offset = devChOption(':MARKer{ch}:SYNC:VOLTage:OFFSet', str_type=float, min=-0.5, max=1.75)
        self.sync_marker_volt_high = devChOption(':MARKer{ch}:SYNC:VOLTage:HIGH', str_type=float, min=0.5, max=1.75)
        self.sync_marker_volt_low = devChOption(':MARKer{ch}:SYNC:VOLTage:LOW', str_type=float, min=-0.5, max=1.75)
        self.dac_format = devChOption(':DAC:FORMat', choices=ChoiceStrings('RZ', 'DNRZ', 'NRZ', 'DOUBlet'), doc=
            """ RZ:      Return to zero (DAC A, DAC B=0) (first half of time step, second half)
                NRZ:     Non return to zero (DAC A, DAC A)
                DNRZ:    double NRZ (DAC A, DAC B=A)
                Doublet: (DAC A, DAC B=-A)
            """)
        self.differential_offset = devChOption(':OUTPut{ch}:DIOFfset', str_type=int, doc='An integer to fix DAC offset between direct and its complement output.')
        #self.func_mode = devChOption(':FUNCtion{ch}:MODE', choices=ChoiceStrings('ARBitrary', 'STSequence', 'STSCenario'))
        self.advance_mode = devChOption(':TRACE{ch}:ADVance', choices=ChoiceStrings('AUTO', 'CONDitional', 'REPeat', 'SINGle'), doc=
            """
            This setting only works for cont_trigger False and gate_mode_en False
            AUTO:   Every trig event produces repeat_count segments
            REPEAT: A trig event produces repeat_count segments.
                    Then need the advance event to enable next trig.
            SINGLE: A trig event produces the first segment.
                    Then N-1 advance event to produce the N-1 repeats of the segment.
                    (for N=repeat_count)
            COND:   A trig event starts a continous repeat of the segment.
            """)
        self.repeat_count = devChOption(':TRACE{ch}:COUNt', str_type=int)
        self.marker_en = devChOption(':TRACE{ch}:MARKer', str_type=bool)
        speed_choices = ChoiceStrings('WSPeed', 'WPRecision')
        self.speed_mode = devChOption(':TRACe{ch}:DWIDth', choices=speed_choices, doc=
            """
                wspeed:     speed mode, 12 bits, 12 GS/s max
                wprecision: precision mode, 14 bits, 8 GS/s max
                See also: speed_mode_both
            """) # SKIP all the interpolation modes (INTX3, X12 ...) because needs option DUC
        self.speed_mode_both = scpiDevice(':TRACe1:DWIDth {val};:TRACe2:DWIDth {val}', ':TRACe1:DWIDth?', choices=speed_choices, doc=
            """
                Same as speed_mode except it changes both channel at the same time.
                This is needed when both channel use the internal sample clock.
                Using get returns the result for channel 1.
            """)
        # TODO implement loading of data using the TRACE{ch}:DEFine 1, length, init_val
        #   and TRACE{ch}:DATA 1,offset (scpi has limit of 999999999 bytes 0.999 GB)
        # read with TRACE{ch}:DATA? 1,offset,length  (returns ascii, length needs to be multiple of 48 or 64)
        #   Getting trace data this way seems very slow.
        self.segment_list = devChOption(getstr=':TRACE{ch}:CATalog?', doc='Returns a list of segment id, length')
        # This needs to be last to complete creation
        super(agilent_AWG, self)._create_devs()

    @locked_calling
    def run(self, enable=True, ch=None):
        """
        When channels are coupled, both are affected.
        """
        if ch is not None:
            self.current_channel.set(ch)
        ch = self.current_channel.getcache()
        if enable:
            self.ask(':INITiate:IMMediate%i;*OPC?'%ch)
        else:
            self.ask(':ABORt%i;*OPC?'%ch)
    @locked_calling
    def set_length(self, sample_length, ch=None, init_val=None):
        """
        init_val is the DAC value to use for initialization. No initialization by default.
        """
        # TODO should check the lenght is valid
        if ch is not None:
            self.current_channel.set(ch)
        ch = self.current_channel.getcache()
        extra=''
        if init_val is not None:
            extra=',{init}'
        self.write((':TRACe{ch}:DELete:ALL;:TRACe{ch}:DEFine 1,{L}'+extra).format(ch=ch, L=sample_length, init=init_val))
    @locked_calling
    def load_file(self, filename, ch=None, fill=False):
        """
        filename needs to be a file in the correct binary format.
        fill when True will pad the data with 0 to the correct length
             when an integer (not 0), will pad the data with that DAC value,
             when false, will copy (repeat) the data multiple times to obtain
             the correct length.
             Note that with padding enabled, the segment length stays the same
             length as defined (so it can be shorted than the file; the data is truncated).
             Use the set_length function to change it.
             With fill disabled (False): the segment length is adjusted
        The vector length is 48 samples in 14 bits mode and 64 in 12 bits mode.
        The minimum length is 5 vectors (240 samples in 14 bits, 320 for 12 bits)
        This command will wait for the transfer to finish before returning.
        If the output is running when calling load_file, it will be temporarilly
        stopped during loading.

        Here is an example to produce the file and load it:
          t=linspace(0,10*pi,192*100+1)[:-1]
          y=sin(t)**7
          yy=array(y*(2**15-1), dtype=int16)&np.array(0xfffc, dtype=int16)
          yy.tofile('awgtest1.bin')
          awg1.load_file('awgtest1.bin')
        """
        # The newer firmware as fixed the problem with using a non-zero fill.
        if fill==False:
            padding='ALENgth'
        elif fill==True:
            padding='FILL'
        else:
            padding='FILL,%i'%fill
        if ch is not None:
            self.current_channel.set(ch)
        ch = self.current_channel.getcache()
        # Make sure filename is reachable. Make it absolute.
        filename = os.path.abspath(filename)
        self.write(':TRACe{ch}:IQIMPort 1,"{f}",BIN,BOTH,ON,{p}'.format(ch=ch, f=filename, p=padding))
        #self._async_trigger_helper_string = ':TRACe{ch}:IQIMPort 1,"{f}",BIN,BOTH,ON,{p};*OPC'.format(ch=ch, f=filename, p=padding)
        self.run_and_wait()


#######################################################
##    Agilent E3631A power supplpy
#######################################################

#@register_instrument('HEWLETT-PACKARD', 'E3631A', '2.1-5.0-1.0')
@register_instrument('HEWLETT-PACKARD', 'E3631A', alias='E3631A')
class agilent_power_supply_E363x(visaInstrument):
    """
    This is to control a E363x power supply.
    Useful devices:
      output_en
      volt_level
      volt_measured
      current_level
      current_measured
    Note that the volt and current devices need a channel or use the current_ch.
    Changing the output level can take a while depending on connected load impedance.
    Output off means the volt level becomes 0, the current level is 0.05. It is not a relay.
    """
    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        orig_ch = self.current_ch.getcache()
        ch_list = ['current_ch', 'volt_level', 'current_level', 'volt_measured', 'current_measured', 'status']
        res = []
        for c in ['P6V', 'P25V', 'N25V']:
            self.current_ch.set(c)
            self.status.setcache(None)
            res.extend(self._conf_helper(*ch_list))
        self.current_ch.set(orig_ch)
        return res+self._conf_helper('output_en', 'output_track_en', options)
    def show_text(self, str=None):
        if str is None:
            self.write('DISPlay:TEXT:CLEar')
        else:
            self.write('DISPlay:TEXT "%s"'%str)
    def _status_getdev(self, ch=None):
        """
        returns the status of the ch. ch=None uses the curren default
        Status can be 'CC', 'CV' for current or voltage control
                      'OFF' when not enable or 'FAIL' for a hardware failure
        """
        if ch is None:
            ch = self.current_ch.getcache()
        response_dict = {0:'OFF', 1:'CC', 2:'CV', 3:'FAIL'}
        name2num = dict(P6V=1, P25V=2, N25V=3)
        n = name2num[ch.upper()]
        ret = self.ask('STATus:QUEStionable:INSTrument:ISUMmary%d:CONDition?'%n)
        ret = response_dict[int(ret)]
        return ret
    def _create_devs(self):
        ch_choices = ChoiceStrings('P6V', 'P25V', 'N25V')
        self.current_ch =  scpiDevice('INSTrument:SELect', choices=ch_choices)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        volt_limits = ChoiceDevDep(self.current_ch, {ch_choices[[0]]:ChoiceLimits(min=0, max=6.18),
                                                     ch_choices[[1]]:ChoiceLimits(min=0, max=25.75),
                                                     ch_choices[[2]]:ChoiceLimits(min=-25.75, max=0),})
        curr_limits = ChoiceDevDep(self.current_ch, {ch_choices[[0]]:ChoiceLimits(min=0, max=5.15),
                                                     ch_choices[[1]]:ChoiceLimits(min=0, max=1.03),
                                                     ch_choices[[2]]:ChoiceLimits(min=0, max=1.03),})
        self.volt_level = devChOption('VOLTage', str_type=float, choices=volt_limits, setget=True) # SOURce:VOLTage:LEVel:IMMediate:AMPLitude
        self.current_level = devChOption('CURRent', str_type=float, choices=curr_limits, setget=True)
        #self.volt_measured = devChOption(getstr='MEASure:VOLTage? {ch}', str_type=float) # this does the same as changing current_ch
        self.volt_measured = devChOption(getstr='MEASure:VOLTage?', str_type=float)
        self.current_measured = devChOption(getstr='MEASure:CURRent?', str_type=float)
        self.output_en = scpiDevice('OUTput', str_type=bool, setget=True) # setget just makes sure the ouput has been changed before returning
        self.output_track_en = scpiDevice('OUTput:TRACk', str_type=bool, doc='Output tracking will make P25V match N25V and vice versa')
        self._devwrap('status')
        super(agilent_power_supply_E363x, self)._create_devs()
