# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2018-2023  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

#######################################################
##    Rohde & Schwarz instruments
#######################################################

from __future__ import absolute_import, print_function, division

import numpy as np
import scipy
import os.path
import time
import string
import functools

from ..instruments_base import visaInstrument, visaInstrumentAsync,\
                            scpiDevice, MemoryDevice, ReadvalDev, BaseDevice,\
                            ChoiceMultiple, Choice_bool_OnOff, _repr_or_string,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDev, ChoiceDevSwitch, ChoiceIndex,\
                            ChoiceSimpleMap, decode_float32, decode_int8, decode_int16, _decode_block_base,\
                            decode_float64, quoted_string, _fromstr_helper, ProxyMethod, _encode_block,\
                            locked_calling, quoted_list, quoted_dict, decode_complex128, Block_Codec
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

from ..comp2to3 import string_bytes_types

# The usb name can be (rs.idn_usb()):
#    'Rohde & Schwarz GmbH & Co. KG'
register_usb_name('Rohde & Schwarz', 0x0aad)

#######################################################
##    R&S SGMA generator
#######################################################

#@register_instrument('Rohde&Schwarz', 'SGU100A', '3.1.19.26-3.50.124.74')
#@register_instrument('Rohde&Schwarz', 'SGS100A', '3.1.19.26-3.50.124.73')
@register_instrument('Rohde&Schwarz', 'SGU100A', usb_vendor_product=[0x0AAD, 0x00CE])
@register_instrument('Rohde&Schwarz', 'SGS100A', usb_vendor_product=[0x0AAD, 0x0088])
class rs_sgma(visaInstrument):
    """
    This is the driver for an standalone SGU upconverter, SGS source or the combination of both.
    Note that when both are connected together (with PCIe) you should communicate with the SGS.

    For SGU:
    othergenset_func is called with 2 parameters which are the frequency and power (dBm) to
    set on external source.
    Note that for frequency, power(when below 12 GHz) and output_en, for the effect to be
    implemented requires to call apply_settings. This is done automatically for those (except
    for _raw and _request) versions. For other instruction it might be required.
    """
    def __init__(self, visa_addr, othergenset_func=None, override_extension=False, **kwargs):
        self._override_extension = override_extension
        if othergenset_func is None:
            othergenset_func = ProxyMethod(self._internal_othergen)
        self._othergenset = othergenset_func
        super(rs_sgma, self).__init__(visa_addr, **kwargs)

    def init(self, full=False):
        super(rs_sgma, self).init(full)
        if full:
            min, max = self.power_level_dbm._get_dev_min_max()
            offset = self.power_level_offset_db.get()
            min -= offset
            max -= offset
            self._power_level_min = min
            self._power_level_max = max
            self.power_level_dbm._doc = 'Range is affected by offset. With offset=0 it is min=%f, max=%f'%(min, max)

    def _internal_othergen(self, freq, power):
        print("Other gen should be at %r Hz, %r dBm"%(freq, power))

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = ['opt=%s'%self.available_options]
        if self._is_SGS:
            ext = self.conf_extension()
            if ext['connected']:
                opts += ['ext=%s'%ext]
                opts += ['ext_opt="%s"'%self.extension_ask('*opt?')]
            opts += self._conf_helper('output_en', 'freq')
        else:
            if self._override_extension:
                opts += self._conf_helper('rem_opmode')
            opts += self._conf_helper('output_en', 'freq', 'LO_freq', 'LO_power')
        opts += self._conf_helper( 'power_level_dbm', 'power_level_no_offset_dbm', 'power_level_offset_db',
                                  'power_mode', 'power_characteristic', 'power_level_limit_dbm', 'power_alc_state',
                                  'power_attenuator_rf_off_mode', 'power_attenuator_switch_over_offset', 'power_get_peak',
                                  'pulse_mod_en', 'pulse_mod_polarity', 'trigger_mode')
        if self._is_SGS:
            opts += self._conf_helper('ref_output_signal', 'operation_mode', 'LO_source')
        return opts + self._conf_helper(options)

    def apply_settings(self):
        """ For SGU only: This is required after output_en, frequency or amplitude changes """
        if not self._is_SGS:
            self.write('SETTings:APPLy')
        else:
            print('Only useful for SGU devices.')

    def reset_tripped_state(self):
        self.write('OUTPut:PROTection:CLEar')

    def conf_traits(self):
        """ For SGU only: Return a dictionnary of information about all the frequency bands """
        if self._is_SGS:
            print('Only useful for SGU devices.')
            return
        traits_name = ['upper_edge', 'freq_mult', 'bypass_mode_en', 'pulse_modulation_in_LO', 'AM_allowed', 'PM_PhiM_allowed']
        traits_type = [float, int, bool, bool, bool, bool]
        ret = None
        for i in range(int(self.ask('TRAits:COUNt?'))):
            name = traits_name[i]
            conv = traits_type[i]
            data = self.ask('TRAits%i?'%(i+1)).split(',')
            data_conv = [ _fromstr_helper(d, conv) for d in data ]
            if ret is None:
                ret = [{} for j in range(len(data))]
            for d, v in zip(ret, data_conv):
                d[name] = v
        return ret

    def _apply_helper(self, val, dev_obj, **kwargs):
        lo_f = self.LO_freq.get()
        lo_p = self.LO_power.get()
        self._othergenset(lo_f, lo_p)
        self.apply_settings()

    def power_alc_now(self):
        """ Activates ALC only for a short time """
        self.write('POWer:ALC:SONCe')

    def conf_network_settings(self):
        addr = self.ask(':SYSTem:COMMunicate:NETWork:IPADdress?')
        gateway = self.ask(':SYSTem:COMMunicate:NETWork:GATeway?')
        subnet_mask = self.ask(':SYSTem:COMMunicate:NETWork:SUBNet:MASK?')
        addr_mode = self.ask(':SYSTem:COMMunicate:NETWork:IPADdress:MODE?') # either AUTO or STATic
        mac_addr = self.ask(':SYSTem:COMMunicate:NETWork:MACaddress?')
        status_en = bool(int(self.ask(':SYSTem:COMMunicate:NETWork:STATus?')))
        hostname = self.ask(':SYSTem:COMMunicate:NETWork:HOSTname?')
        return dict(address=addr, gateway=gateway, subnet_mask=subnet_mask, addr_mode=addr_mode, mac_addr=mac_addr, status_en=status_en, hostname=hostname)

    def conf_hardware(self):
        # SGS and SGU don't use quoted string in the same way. So quietly remove if needed.
        qs = quoted_string(quiet=True)
        split = lambda s: s.split(',')
        clean = lambda s: list(map(qs, split(s)))
        common_assembly = {}
        rf_assembly = {}
        common_assembly['name'] = clean(self.ask('SYSTem:HARDware:ASSembly1:NAME?'))
        rf_assembly['name'] = clean(self.ask('SYSTem:HARDware:ASSembly2:NAME?'))
        common_assembly['part_number'] = clean(self.ask('SYSTem:HARDware:ASSembly1:PNUMber?'))
        rf_assembly['part_number'] = clean(self.ask('SYSTem:HARDware:ASSembly2:PNUMber?'))
        common_assembly['revision'] = clean(self.ask('SYSTem:HARDware:ASSembly1:REVision?'))
        rf_assembly['revision'] = clean(self.ask('SYSTem:HARDware:ASSembly2:REVision?'))
        common_assembly['serial'] = clean(self.ask('SYSTem:HARDware:ASSembly1:SNUMber?'))
        rf_assembly['serial'] = clean(self.ask('SYSTem:HARDware:ASSembly2:SNUMber?'))
        return dict(common_assembly=common_assembly, rf_assembly=rf_assembly)

    def conf_software(self):
        # SGS and SGU don't use quoted string in the same way. So quietly remove if needed.
        qs = quoted_string(quiet=True)
        split = lambda s: s.split(',')
        clean = lambda s: list(map(qs, split(s)))
        common_assembly = {}
        rf_assembly = {}
        common_assembly['name'] = clean(self.ask('SYSTem:SOFTware:OPTion1:NAME?'))
        rf_assembly['name'] = clean(self.ask('SYSTem:SOFTware:OPTion2:NAME?'))
        common_assembly['description'] = clean(self.ask('SYSTem:SOFTware:OPTion1:DESignation?'))
        rf_assembly['description'] = clean(self.ask('SYSTem:SOFTware:OPTion2:DESignation?'))
        common_assembly['expiration'] = clean(self.ask('SYSTem:SOFTware:OPTion1:EXPiration?'))
        rf_assembly['expiration'] = clean(self.ask('SYSTem:SOFTware:OPTion2:EXPiration?'))
        common_assembly['licenses'] = clean(self.ask('SYSTem:SOFTware:OPTion1:LICenses?'))
        rf_assembly['licenses'] = clean(self.ask('SYSTem:SOFTware:OPTion2:LICenses?'))
        return dict(common_assembly=common_assembly, rf_assembly=rf_assembly)

    def conf_extension(self):
        """ Returns information about the extension module. Only useful on SGS """
        if not self._is_SGS:
            print('Only useful for SGS devices.')
            return
        connected = _fromstr_helper(self.ask('EXTension:REMote:STATe?'), bool)
        name = self.ask('EXTension:INSTruments:NAME?')
        # EXTension:INSTruments:SCAN ...
        interface = self.ask('EXTension:INSTruments:REMote:CHANnel?')
        lan_addr = self.ask('EXTension:INSTruments:REMote:LAN:NAME?')
        serial_no = self.ask('EXTension:INSTruments:REMote:SERial?')
        state_busy = _fromstr_helper(self.ask('EXTension:BUSY?'), bool)
        return dict(connected=connected, name=name, interface=interface, lan_addr=lan_addr, serial_no=serial_no, state_busy=state_busy)

    @locked_calling
    def extension_write(self, command, ch=1):
        if not self._is_SGS:
            print('Only useful for SGS devices.')
            return
        self.write('EXTension:SELect %i'%ch)
        self.write('EXTension:SEND "%s"'%command)

    @locked_calling
    def extension_ask(self, query='', ch=1):
        """ Only useful for SGS device.
            The query is transmitted to the extension.
            you should include the question mark in the query.
            If you think the buffer are unsynchronized, you can just
            do a read with no query.
            Useful queries: SYSTem:ERRor, SYSTem:SERRor
        """
        if not self._is_SGS:
            print('Only useful for SGS devices.')
            return
        self.write('EXTension:SELect %i'%ch)
        return self.ask('EXTension:SEND? "%s"'%query)


    def get_error_state(self):
        """ Return the current error state. Useful to find out if the LO input power is too low
            (red LO IN light on SGU).
            To read the list of errors, call the get_error method.
        """
        return self.ask('SYSTem:SERRor?')

    def startup_completed(self):
        return _fromstr_helper(self.ask('SYSTem:STARtup:COMPlete?'), bool)

    def reset(self):
        """ All instrument settings are reset to their default values (except for network settings ...). """
        # I think all the 2 lines perform the same operation.
        # The manuals also mentions SOURce.PRESet but it does not seem to work.
        self.write('*RST')
        #self.write('SYSTem:PRESet')


    def _power_level_extra_range_check(self, val, dev_obj):
        offset = self.power_level_offset_db.getcache()
        min, max = self._power_level_min, self._power_level_max
        dev_obj._general_check(val, min=min+offset, max=max+offset)

    def _create_devs(self):
        opt = self.ask('*OPT?')
        self.available_options = opt.split(',')
        self._is_SGS = is_SGS = self.idn_split()['model'] == 'SGS100A'
        if not is_SGS:
            rem_opmode = self.ask('REMote:OPMode?')
            if (not self._override_extension) and rem_opmode.upper() == 'EXT': # options are EXTension, STDalone
                raise RuntimeError('Your SGU is currently in EXTENSION mode. You should connect to and use the SGS instead.')
            apply_helper = ProxyMethod(self._apply_helper)
            def l_apply_scpiDevice(*args, **kwargs):
                return scpiDevice(*args, extra_set_after_func=apply_helper, **kwargs)
            if self._override_extension:
                self.rem_opmode = scpiDevice('REMote:OPMode', choices=ChoiceStrings('EXTension', 'STDalone'))
            self.output_en_raw = scpiDevice('OUTPut', str_type=bool)
            self.LO_freq = scpiDevice(getstr='LOSCillator:FREQuency?', str_type=float)
            self.LO_power = scpiDevice(getstr='LOSCillator:POWer?', str_type=float)
            self.freq_request = scpiDevice('FREQuency', str_type=float, auto_min_max=True, doc="See LO_freq and LO_power")
            self.power_level_dbm_raw = scpiDevice('POWer', str_type=float, auto_min_max=True)
        else:
            l_apply_scpiDevice = scpiDevice
            self.ref_output_signal = scpiDevice('CONNector:REFLo:OUTPut', choices=ChoiceStrings('REF', 'LO', 'OFF'))
            self.operation_mode = scpiDevice('OPMode', choices=ChoiceStrings('NORMal', 'BBBYpass'))
            self.LO_source = scpiDevice('LOSCillator:SOURce', choices=ChoiceStrings('INTernal', 'EXTernal'))

        self.output_en = l_apply_scpiDevice('OUTPut', str_type=bool)
        self.output_poweron = scpiDevice('OUTPut:PON', choices=ChoiceStrings('OFF', 'UNCHanged'))
        self.output_same_attenuator_min_dBm = scpiDevice('OUTPut:AFIXed:RANGe:LOWer', str_type=float)
        self.output_same_attenuator_max_dBm = scpiDevice('OUTPut:AFIXed:RANGe:UPPer', str_type=float)
        self.freq = l_apply_scpiDevice('FREQuency', str_type=float, auto_min_max=True)
        self.power_mode = scpiDevice('POWer:LMODe', choices=ChoiceStrings('NORMal', 'LNOISe', 'LDIStortion'))
        self.power_characteristic = scpiDevice('POWer:SCHaracteristic', choices=ChoiceStrings('AUTO', 'UNINterrupted', 'CVSWr', 'USER', 'MONotone'), doc='CVSWr means Constant VSWR.')
        # see init for set power_level_dbm min max
        self.power_level_dbm = l_apply_scpiDevice('POWer', str_type=float,
                extra_check_func=ProxyMethod(self._power_level_extra_range_check))
        self.power_level_no_offset_dbm = l_apply_scpiDevice('POWer:POWer', str_type=float, auto_min_max=True, doc='This bypasses the power offset')
        self.power_level_offset_db = scpiDevice('POWer:OFFSet', str_type=float, auto_min_max=True)
        self.power_level_limit_dbm = scpiDevice('POWer:LIMit', str_type=float, auto_min_max=True)
        self.power_range_max = scpiDevice(getstr='POWer:RANGe:UPPer?', str_type=float, doc='Queries the maximum power in the current level mode')
        self.power_range_min = scpiDevice(getstr='POWer:RANGe:LOWer?', str_type=float, doc='Queries the minimum power in the current level mode')
        self.power_alc_state = scpiDevice('POWer:ALC', choices=ChoiceStrings('OFFTable', 'ONTable', 'ON', redirects={'1':'ON'}))
        self.power_alc_detector_sensitivity = scpiDevice('POWer:ALC:DSENsitivity', choices=ChoiceStrings('OFF', 'LOW', 'MED', 'HIGH'))
        self.power_attenuator_mode = scpiDevice('OUTPut:AMODe', choices=ChoiceStrings('AUTO', 'APASsive', 'FIXed'), doc='APASsive maybe just for SGS')
        self.power_attenuator_rf_off_mode = scpiDevice('POWer:ATTenuation:RFOFf:MODE',
                choices=ChoiceStrings('MAX', 'FIXed', 'FATTenuated', 'UNCHanged'),
                doc="FATTenuated and UNCHanged are probably only for SGS")
        self.power_attenuator_switch_over_offset = scpiDevice('POWer:ATTenuation:SOVer', str_type=float)
        self.power_get_peak = scpiDevice(getstr='POWer:PEP?', str_type=float, doc='This includes the effect of Crest Factor')
        self.pulse_mod_en = scpiDevice('PULM:STATe', str_type=bool)
        self.pulse_mod_polarity = scpiDevice('PULM:POLarity', choices=ChoiceStrings('NORMal', 'INVerted'))
        self.trigger_mode = scpiDevice('CONNector:TRIGger:OMODe',
                choices=ChoiceStrings('SVALid', 'SNValid', 'PVOut', 'PETRigger', 'PEMSource'),
                doc="'PVOut', 'PETRigger', 'PEMSource' parameter only valid with install SGS-K22 option")
        # power_unit does not seem to have any effect
        #self.power_unit = scpiDevice('UNIT:POWer', choices=ChoiceStrings('V', 'DBUV', 'DBM'))

        # TODO handle IQ subsystem if present, Also Memory/Format, Unit:angle
        # Note that the sgma-gui uses a lot of undocumented commands like:
        #   ':GENeric:NSTRING? "IdPSguFirmwarePackage",0,0,0,0'
        # also: 'snam?'
        self.alias = self.freq
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


#######################################################
##    R&S SGMA RTO2014 scope
#######################################################

#@register_instrument('Rohde&Schwarz', 'RTO', '3.70.1.0')
@register_instrument('Rohde&Schwarz', 'RTO', usb_vendor_product=[0x0AAD, 0x0197])
class rs_rto_scope(visaInstrumentAsync):
    """
       This is the driver for the Rohde & Schwarz RT0 2014 Oscilloscope
       Useful devices:
         fetch, readval
         acquire_count    (if not averaging, nor looking at history, you probably want this to be 1, otherwise you
                           still get multiple acquisitions)
         snap_png
    """
    def init(self, full=False):
        self._meas_names_cache = {}
        self.set_format('int16', 'string')
        self.write('FORMat:BORDer  LSBFirst')
        self.write('EXPort:WAVeform:INCXvalues OFF')
        self.write('EXPort:WAVeform:MULTichannel OFF')
        # if using gpib, might require setting it up for large data block termination.
        # However the instrument I have does not habe gpib install so
        # command GPIB:TERMinator does not work
        super(rs_rto_scope, self).init(full)

    def _async_trigger_helper(self):
        self.single_trig()
        self.write('*OPC')

    @locked_calling
    def set_format(self, data=None, bitp=None):
        """ If neither data or bit is given, it returns the current setup (data, bitp).
            data can be: ascii, real, int8 or int16
            bitp can be:
        """
        data_usr = ['ascii', 'real', 'int8', 'int16']
        data_instr = ['ASC,0', 'REAL,32', 'INT,8', 'INT,16']
        bitp_usr = ['dec', 'hex', 'oct', 'bin', 'ascii', 'string']
        bitp_instr = ['DEC', 'HEX', 'OCT', 'BIN', 'ASCII', 'STRG']
        if data:
            if data not in data_usr:
                raise ValueError(self.perror('Invalid parameter for data. Use one of: %s'%data_usr))
            self.write('FORMat %s'%data_instr[data_usr.index(data)])
        if bitp:
            if bitp not in bitp_usr:
                raise ValueError(self.perror('Invalid parameter for bitp. Use one of: %s'%bitp_usr))
            self.write('FORMat:BPATtern %s'%bitp_instr[bitp_usr.index(bitp)])
        if data is bitp is None:
            form = self.ask('FORMat?')
            form = data_usr[data_instr.index(form)]
            bitp = self.ask('FORMat:BPATtern?')
            bitp = bitp_usr[bitp_instr.index(bitp)]
            return form, bitp

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = ['opt=%s'%self.available_options]
        opts += self._conf_helper('timebase_ful_range', 'timebase_pos_offset', 'timebase_reference_pos_percent')
        opts += self._conf_helper('acquire_npoints', 'acquire_resolution', 'acquire_adc_sample_rate', 'sample_rate', 'sample_rate_real',
                                  'acquire_mode', 'acquire_interpolate_method', 'acquire_count', 'acquire_segment_en',
                                  'acquire_restart_mode', 'acquire_restart_time', 'acquire_restart_wfms_count')
        opts += self._conf_helper('channel_multiple_waveforms_en', 'channel_coupling_en')

        def reorg(opts):
            first = True
            for ch_line in opts:
                ch_line_split = [ c.split('=', 1) for c in ch_line]
                names = [n for n, d in ch_line_split]
                data = [d for n, d in ch_line_split]
                if first:
                    data_all = [ [d] for d in data]
                    first = False
                else:
                    for db, d in zip(data_all, data):
                        db.append(d)
            return [n+'=['+','.join(d)+']' for n, d in zip(names, data_all)]

        # Do Channels, Waveforms, Input, Probe
        ch_orig = self.current_channel.get()
        wf_orig = self.current_channel_waveform.get()
        ch_opts = []
        ch_wf_opts = []
        for c in range(1, 5):
            self.current_channel.set(c)
            wf_range =  list(range(1, 4)) if self.channel_multiple_waveforms_en.get() else [1]
            for wf in wf_range:
                self.current_channel_waveform.set(wf)
                ch_wf_opt = ['channel_waveform=C%iW%i'%(c, wf)]
                ch_wf_opt += self._conf_helper('channel_en', 'channel_decimation_type', 'channel_arithmetic_method')
                ch_wf_opts.append(ch_wf_opt)
            ch_opt = self._conf_helper('input_en', 'input_coupling', 'input_ground_en', 'input_invert_en', 'input_bandwidth',
                                       'input_full_range', 'input_position_div', 'input_offset', 'input_power_calc_impedance',
                                       'input_overloaded', 'input_filter_en', 'input_skew_manual_en', 'input_skew_time',
                                       'input_filter_cutoff_freq', 'probe_state', 'probe_type', 'probe_name', 'probe_attenuation')
            ch_opts.append(ch_opt)
        opts += reorg(ch_wf_opts)
        opts += reorg(ch_opts)
        self.current_channel.set(ch_orig)
        self.current_channel_waveform.set(wf_orig)

        # do measurement. Do them all because they can be used (like in math) even if disabled.
        ch_orig = self.current_measurement.get()
        ch_opts = []
        for c in range(1,9):
            self.current_measurement.set(c)
            ch_opt = self._conf_helper('measurement_en', 'measurement_src1', 'measurement_src2', 'measurement_category', 'measurement_main',
                                       'measurement_statistics_en', 'measurement_multiple_max_n')
            ch_opts.append(ch_opt)
        opts += reorg(ch_opts)
        self.current_measurement.set(ch_orig)

        # do generators.
        ch_orig = self.current_generator.get()
        ch_opts = []
        for c in range(1,3):
            if self.generator_en.get(ch=c):
                ch_opt = ['generator_en_ch=%i'%c]
                ch_opt += self._conf_helper('generator_mode', 'generator_function', 'generator_output_load', 'generator_amplitude_vpp',
                                           'generator_offset', 'generator_dc_level', 'generator_inversion', 'generator_frequency',
                                           'generator_pulse_width', 'generator_ramp_symmetry_pct', 'generator_square_duty_cycle_pct',
                                           'generator_noise_en', 'generator_noise_level_pct', 'generator_noise_level_vpp', 'generator_noise_level_dc')
                ch_opts.append(ch_opt)
        if ch_opts != []:
            opts += reorg(ch_opts)
        self.current_generator.set(ch_orig)

        # do Trigger
        chs = ['A'] if self.trigger_sequence_mode.get() == 'aonly' else ['A', 'B', 'R']
        opts += self._conf_helper('trigger_mode', 'trigger_sequence_mode')
        opts += self._conf_helper('trigger_output_en', 'trigger_output_polarity', 'trigger_output_length', 'trigger_output_delay')
        if chs == ['A']:
            opts += self._conf_helper('trigger_holdoff_mode', 'trigger_holdoff_time', 'trigger_holdoff_events', 'trigger_holdoff_random_min',
                                      'trigger_holdoff_random_max', 'trigger_holdoff_auto_time', 'trigger_holdoff_auto_scaling')
        srcs = []
        ch_orig = self.current_trigger.get()
        ch_opts = []
        for c in chs:
            self.current_trigger.set(c)
            ch_opt = ['trigger_ch=%s'%c]
            ch_opt += self._conf_helper('trigger_source', 'trigger_type', 'trigger_level', 'trigger_edge_slope',
                                       'trigger_qualification_en', 'trigger_hysteresis_control', 'trigger_hysteresis_mode',
                                       'trigger_hysteresis_abs_V', 'trigger_hysteresis_rel_percent')
            srcs.append(self.trigger_source.getcache())
            ch_opts.append(ch_opt)
        opts += reorg(ch_opts)
        self.current_trigger.set(ch_orig)
        if 'externanalog' in srcs:
            opts += self._conf_helper('trigger_edge_ext_coupling', 'trigger_edge_ext_filter', 'trigger_edge_ext_filter_highpass',
                                      'trigger_edge_ext_filter_lowpass', 'trigger_edge_ext_gnd_en', 'trigger_edge_ext_slope',
                                      'trigger_hysteresis_ext_reject')

        opts += self._conf_helper('display_remote_update_en', 'roll_is_active', 'trigger_coupling', 'highdef_mode_en',
                                  'highdef_mode_bandwidth', 'highdef_mode_bin_resol')
        if 'B4' in self.available_options:
            opts += self._conf_helper('reference_clock_src', 'reference_clock_ext_freq')
        return opts + self._conf_helper(options)

    @locked_calling
    def display_message(self, message=''):
        """ The message is displayed on the black remote window.
        """
        if message:
            self.display_message_text.set(message)
            self.display_remote_update_en.set(False)
            self.display_message_en.set(True)
        else:
            self.display_message_en.set(False)

    @locked_calling
    def set_time(self, set_time=False):
        """ Reads the UTC time from the instrument or set it from the computer value """
        if set_time:
            now = time.gmtime()
            self.write('SYSTem:DATE %i,%i,%i'%(now.tm_year, now.tm_mon, now.tm_mday))
            self.write('SYSTem:TIME %i,%i,%i'%(now.tm_hour, now.tm_min, now.tm_sec))
        else:
            date_str = self.ask('SYSTem:DATE?')
            time_str = self.ask('SYSTem:TIME?')
            return '%s %s UTC'%(date_str.replace(',', '-'), time_str.replace(',', ':'))

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
    def single_trig(self):
        """
        The same as pressing single
        """
        #self.trig_status.get() # reset trig
        #self._async_last_status_time = 0.
        self.write(':SINGle')
    def clear_sweeps(self):
        self.write('ACQuire:ARESet:IMMediate')
    acquire_restart_now = clear_sweeps

    @locked_calling
    def clear_measurement(self, ch=None):
        if ch is None:
            ch = self.current_measurement.get()
        else:
            self.current_measurement.set(ch)
        self.write('MEASurement{ch}:CLEar'.format(ch=ch))

    def get_file(self, remote_file, local_file=None):
        """ read a remote_file from the instrument. Filename should be a full windows path.
            return the data unless local_file is given, then it saves data in that."""
        s = self.ask('MMEMory:DATA? "%s"'%remote_file, raw=True)
        s = _decode_block_base(s)
        if local_file:
            with open(local_file, 'wb') as f:
                f.write(s)
        else:
            return s

    #def _snap_png_getdev(self, signal_bar=True, dialog=True, white_background=False, color=True, invert_color=False, portrait=False):
    def _snap_png_getdev(self, signal_bar=True, dialog=True, white_background=False, invert_color=False):
        """ For dialog to work, you need to minimize the application on the scope
            or disable remote line: dev.control_remotelocal(all=True)
        """
        def handle_option(val, setup_str, on='ON', off='OFF'):
            if val:
                self.write(setup_str+' '+on)
            else:
                self.write(setup_str+' '+off)
        handle_option(signal_bar, 'HCOPy:ISBA')
        handle_option(dialog, 'HCOPy:SSD')
        handle_option(white_background, 'HCOPy:WBKG')
        handle_option(invert_color, 'HCOPy:DEVice:INVerse')
        #handle_option(portrait, 'HCOPy:PAGE:ORIentation', on='PORTrait', off='LANDscape') # only for dest SYST:COMM:PRIN
        #handle_option(color, 'HCOPy:DEVice:COLor') # only for dest SYST:COMM:PRIN
        #handle_option(cmap_white, 'HCOPy:CMAP:DEFault', on='DEF1', off='DEF4') # only for dest SYST:COMM:PRIN
        self.write('HCOPy:DESTination "MMEM"') # other options: SYST:COMM:PRIN, SYST:COMM:CLIP
        self.write('HCOPy:DEVice:LANGuage PNG') # other options: JPG, BMP, TIFF, PDF

        tmpfile_d = r'C:\TEMP'
        tmpfile_f = 'TempScreenGrab.png'
        tmpfile_p = tmpfile_d + '\\' + tmpfile_f
        self.write('MMEMory:NAME "%s"'%tmpfile_p)
        self.write('HCOPy:IMMediate')
        ret = self.get_file(tmpfile_p)
        self.write('MMEMory:DELete "%s"'%tmpfile_p)
        return ret

    def _timestamp_getdev(self, ch=None, wf=None):
        """
           The timestamp of the current waveform_history_index,
           returns a tuple of unix_timestamp, seconds_fraction
           seconds_fraction has ns resolution
           It is only updated after acquisition is stopped.
        """
        # there is higher resolution than ns but only for relative
        # time between history acq.
        # or with repsect to reference (turn on) but only for the first few minutes
        if ch is None:
            ch = self.current_channel.getcache()
        else:
            self.current_channel.set(ch)
        if self.channel_multiple_waveforms_en.get():
            wf = 1
        elif wf is None:
            wf = self.current_channel_waveform.getcache()
        else:
            self.current_channel_waveform.set(wf)
        # this is local time of latest stopped acquisition
        #self.waveform_history_index.set(0, ch=ch, wf=wf)
        date = self.ask('CHANnel{ch}:WAVeform{wf}:HISTory:TSDate?'.format(ch=ch, wf=wf))
        time_str = self.ask('CHANnel{ch}:WAVeform{wf}:HISTory:TSABsolute?'.format(ch=ch, wf=wf))
        date = list(map(int, date.split(':')))
        hrmn, sec, uni = time_str.split(' ')
        hr, mn = list(map(int, hrmn.split(':')))
        sec, ns = list(map(float, sec.replace('.', '').split(',')))
        datetime = time.mktime( (date[0], date[1], date[2], hr, mn, int(sec), -1, -1, -1) )
        return datetime, ns*1e-9

    def trigger_force(self):
        self.write('TRIGger:FORCe')

    @locked_calling
    def get_status(self):
        """ Reading the status also clears it. This is the event(latch) status."""
        res = {}
        chk_bit = lambda val, bitn: bool((val>>bitn)&1)
        oper = int(self.ask('STATus:OPERation?'))
        res.update(oper_alignement=chk_bit(oper, 0), oper_autoset=chk_bit(oper, 2), oper_wait_trigger=chk_bit(oper, 3), oper_measuring=chk_bit(oper, 4))
        res.update(oper_all=oper)
        quest_cov = int(self.ask('STATus:QUEStionable:COV?'))
        quest_temp = int(self.ask('STATus:QUEStionable:TEMP?'))
        quest_adcs = int(self.ask('STATus:QUEStionable:ADCS?'))
        if 'B4' in self.available_options: # B4 is OCXO option
            quest_freq = int(self.ask('STATus:QUEStionable:FREQ?'))
        else:
            quest_freq = 0
        quest_lim = int(self.ask('STATus:QUEStionable:LIM?'))
        quest_marg = int(self.ask('STATus:QUEStionable:MARG?'))
        quest_lamp = int(self.ask('STATus:QUEStionable:LAMP?'))
        quest_mask = int(self.ask('STATus:QUEStionable:MASK?'))
        quest_pll = int(self.ask('STATus:QUEStionable:PLL?'))
        #quest_zvco = int(self.ask('STATus:QUEStionable:ZVCO?'))
        quest = int(self.ask('STATus:QUEStionable?'))
        res.update(no_alignment_data=chk_bit(quest, 8), temp_warning=chk_bit(quest_temp, 0), temp_error=chk_bit(quest_temp, 1))
        res.update(oven_cold=chk_bit(quest_freq, 0))
        res.update(quest_all=quest, quest_all_temp=quest_temp, quest_all_freq=quest_freq)
        res.update(ch_overload=quest_cov, adcs_clipping=quest_adcs, pll_unlock=quest_pll)
        res.update(limits=quest_lim, margin=quest_marg, low_ampl=quest_lamp, mask=quest_mask)
        return res

    @locked_calling
    def get_status_now(self):
        """ Reading the status. This is the condition(instantenous) status."""
        quest_cov = int(self.ask('STATus:QUEStionable:COV:CONDition?'))
        quest_adcs = int(self.ask('STATus:QUEStionable:ADCS:CONDition?'))
        res = {}
        res.update(ch_overload=quest_cov, adcs_clipping=quest_adcs)
        return res

    @locked_calling
    def list_channels(self):
        cur_ch = self.current_channel.get()
        cur_wf = self.current_channel_waveform.get()
        chl = []
        wf_rg = list(range(1,4)) if self.channel_multiple_waveforms_en.get() else [1]
        for c in range(1,5):
            for w in wf_rg:
                if self.channel_en.get(ch=c, wf=w):
                    chl.append('C%iW%i'%(c, w))
        self.current_channel.set(cur_ch)
        self.current_channel_waveform.set(cur_wf)
        return chl

    def _fetch_ch_helper(self, ch):
        if ch is None:
            ch = self.list_channels()
        if not isinstance(ch, (list)):
            ch = [ch]
        allowed_map = {'C1':'C1W1', 1:'C1W1', 'C2':'C2W1', 2:'C2W1', 'C3':'C3W1', 3:'C3W1', 'C4':'C4W1', 4:'C4W1'}
        ch = [allowed_map.get(c, c) for c in ch]
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
            multi.append('ch_%s'%c)
        fmt = self.fetch._format
        multi = tuple(multi)
        fmt.update(multi=multi, graph=[], xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)

    def _fetch_getdev(self, ch=None, xaxis=True, raw=False, format='int16', history=None):
        """
           Options available: ch, xaxis
            -ch:   a single value or a list of values for the channels to capture
                   a value of None selects all the active ones from C1W1 to C4W3.
                   If obtaining more than one channels, they should have the same xaxis
                   ch can be strings in the C1W1 format or just C1 (for C1W1) or even
                      just the integer 1 (for C1W1)
            -xaxis: Set to True (default) to return the timebase as the first colum
            -raw: Set to true to return the vertical values as raw values (see format), otherwise
                  they are converted to floats. It also turns xaxis off
           -format: can be int8, int16, real or ascii
           -history: use a number 0 - -n with n from acquire_navailable to read a value from history
                     when None (default) it skips turning history on and should read the last acq
                             unless history is already on, in which case it reads the last selected history.
                     when 'all' reads all history from -n to 0
                     Note that history is disabled after every acquisition
        """
        self.set_format(format)
        ch = self._fetch_ch_helper(ch)
        ret = []
        first = True
        cur_ch = self.current_channel.get()
        cur_wf = self.current_channel_waveform.get()
        if history == 'all':
            history = list(range(-self.acquire_navailable.get()+1, 0+1))
        else:
            history = [history]
        N_hist = len(history)
        scales = dict()
        for c in ch:
            cch = int(c[1])
            cwf = int(c[3])
            header = self.waveform_data_header.get(ch=cch, wf=cwf)
            if (not raw) and xaxis and first:
                # this has been tested with 'EXPort:WAVeform:INCXvalues ON'
                one_x = np.linspace(header.x_start, header.x_stop, header.n_sample, endpoint=False)
                if N_hist > 1:
                    ret = [ np.concatenate([one_x]*N_hist)]
                else:
                    ret = [ one_x ]
            full_y = []
            for h in history:
                if h is not None:
                    self.waveform_history_en.set(True)
                    self.waveform_history_index.set(h, ch=cch, wf=cwf)
                else:
                    # Note that history is disabled after every acq
                    # So do not disable it here. Also do not change index since
                    # that can be slow.
                    #self.waveform_history_en.set(False)
                    #self.waveform_history_index.set(0, ch=cch, wf=cwf)
                    pass
                data = self.waveform_data.get()
                if raw or format in ['ascii', 'real']:
                    y = data
                else:
                    scale = scales.get(c, None)
                    if scale is None:
                        gain = self.input_full_range.get()
                        offset_pos = self.input_position_div.get()*gain/10.
                        if format == 'int16':
                            gain /=  253*256.
                        else:
                            gain /=  253
                        offset = self.input_offset.get()
                        scales[c] = dict(gain=gain, offset=offset, offset_pos=offset_pos)
                    else:
                        gain  = scale['gain']
                        offset  = scale['offset']
                        offset_pos  = scale['offset_pos']
                    y = data*gain + offset - offset_pos
                full_y.append(y)
            first = False
            ret.append(np.concatenate(full_y))
        self.current_channel.set(cur_ch)
        self.current_channel_waveform.set(cur_wf)
        ret = np.asarray(ret)
        if ret.shape[0]==1:
           ret=ret[0]
        return ret

    @locked_calling
    def list_meas_channels(self):
        cur_ch = self.current_measurement.get()
        chl = []
        for c in range(1,9):
            if self.measurement_en.get(ch=c):
                chl.append(c)
        self.current_measurement.set(cur_ch)
        return chl

    def _fetch_meas_ch_helper(self, ch):
        if ch is None:
            ch = self.list_meas_channels()
        if not isinstance(ch, (list)):
            ch = [ch]
        return ch

    def _fetch_meas_getformat(self, **kwarg):
        ch = kwarg.get('ch', None)
        graph_orig = kwarg.get('graph', None)
        ch = self._fetch_meas_ch_helper(ch)
        multi = []
        graph = []
        i = 0
        cur_ch = self.current_measurement.get()
        stats_name = ['current', 'peak_pos', 'peak_neg', 'average', 'RMS', 'stddev', 'event_count', 'waveform_count']
        for c in ch:
            base = 'meas%i'%c
            cache_time, meas = self._meas_names_cache.get(c, (0,[]))
            now = time.time()
            if now-cache_time > 5: # recheck after 5s have elapsed
                #print('obtaining proper header')
                self.write('MEASurement%i:ARNames ON'%c)
                data_str = self.ask('MEASurement{ch}:ARES?'.format(ch=c))
                # data_str can look like:
                #  'Low: -3.073122529644e-001,-2.835968379447e-001,-3.112648221344e-001,-3.059553686496e-001,3.059639512935e-001,2.291788675049e-003,12820,12820,Cycle area: 5.632301330503e-008,1.568227029638e-007,-3.299410528221e-008,7.271567316096e-008,8.036486371256e-008,3.422036733522e-008,12820,12820'
                self.write('MEASurement%i:ARNames OFF'%c)
                meas = [ m.split(',')[-1] for m in data_str.split(':')[:-1] ]
                self._meas_names_cache[c] = (now, meas)
            for m in meas:
                base_m = base + '_' + m.replace(' ', '_')
                if self.measurement_statistics_en.get(ch=c):
                    multi += [base_m+'_'+ s for s in stats_name]
                    graph.append(i)
                    i += len(stats_name)
                else:
                    multi.append(base_m)
                    graph.append(i)
                    i += 1
        self.current_measurement.set(cur_ch)
        if graph_orig is not None:
            graph = graph_orig
        fmt = self.fetch_meas._format
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch_meas, **kwarg)

    def _fetch_meas_getdev(self, ch=None):
        """
           Options available: ch, xaxis
            -ch:   a single value or a list of values for the measurment channels to capture
                   They should have the same shape (statistics on/off)
           returns a vector of all the measurements, one after the other.
                   if statistics is on it returns multiple values representing:
                     current, peak_pos, peak_neg, average, RMS, stddev, event_count, waveform_count
        """
        ch = self._fetch_meas_ch_helper(ch)
        ret = []
        for c in ch:
            data_str = self.ask('MEASurement{ch}:ARES?'.format(ch=c))
            data = decode_float64(data_str)
            ret += list(data)
        ret = np.asarray(ret)
        if ret.shape[0]==1:
           ret=ret[0]
        return ret

    def _create_devs(self):
        opt = self.ask('*OPT?')
        self.available_options = opt.split(',')
        self.display_remote_update_en = scpiDevice('SYSTem:DISPlay:UPDate', str_type=bool)
        self.display_message_en = scpiDevice('SYSTem:DISPlay:MESSage:STATe', str_type=bool, doc='The message is in the black remote window')
        self.display_message_text = scpiDevice('SYSTem:DISPlay:MESSage', str_type=quoted_string(fromstr=False), doc='The message is in the black remote window')
        self.timebase_per_div = scpiDevice('TIMebase:SCALe', str_type=float, setget=True, auto_min_max=True)
        self.timebase_ful_range = scpiDevice('TIMebase:RANGe', str_type=float, setget=True, auto_min_max=True)
        self.timebase_pos_offset_limit_en = scpiDevice('TRIGger:OFFSet:LIMited', str_type=bool)
        # TODO: min/max are dependent on scale. Also reading min/max produces the on screen message:
        #          User defined triggr offset restored.
        # TODO: handle the timebase_pos_offset_limit_en True state for limits
        self.timebase_pos_offset = scpiDevice('TIMebase:HORizontal:POSition', str_type=float, setget=True,
                doc="Positive values, move the trigger point to the left (before) the reference position")
        self.timebase_reference_pos_percent = scpiDevice('TIMebase:reference', str_type=float, setget=True, auto_min_max=True)
        self.acquire_keep_constant = scpiDevice('ACQuire:POINts:AUTO', choices=ChoiceStrings('RESolution', 'RECLength'))
        self.acquire_keep_constant_autoadjust_en = scpiDevice('ACQuire:POINts:AADJust', str_type=bool)
        self.acquire_npoints_max = scpiDevice('ACQuire:POINts:MAXimum', str_type=float, setget=True, auto_min_max=True)
        self.acquire_npoints = scpiDevice('ACQuire:POINts', str_type=float, setget=True, auto_min_max=True)
        self.acquire_resolution = scpiDevice('ACQuire:RESolution', str_type=float, setget=True, auto_min_max=True, doc='Time between two acquisition in seconds.')
        self.acquire_adc_sample_rate = scpiDevice(getstr='ACQuire:POINts:ARATe?')
        self.sample_rate = scpiDevice('ACQuire:SRATe', str_type=float, setget=True, auto_min_max=True, doc='This includes points produce by interpolation')
        self.sample_rate_real = scpiDevice('ACQuire:SRReal', str_type=float, setget=True, auto_min_max=True, doc='This does not include interpolated points.')
        self.acquire_mode = scpiDevice('ACQuire:MODE', choices=ChoiceStrings('RTIMe', 'ITIMe'), doc='ITIMe is interpolated time, see acquire_interpolate_method')
        self.acquire_interpolate_method = scpiDevice('ACQuire:INTerpolate', choices=ChoiceStrings('LINear', 'SINX', 'SMHD'), doc='SMHD is sample and hold.')
        self.acquire_count = scpiDevice('ACQuire:COUNt', str_type=int, auto_min_max=True)
        self.acquire_restart_mode = scpiDevice('ACQuire:ARESet:MODE', choices=ChoiceStrings('NONE', 'TIME', 'WFMS'))
        self.acquire_restart_time = scpiDevice('ACQuire:ARESet:TIME', str_type=float, setget=True, auto_min_max=True)
        self.acquire_restart_wfms_count = scpiDevice('ACQuire:ARESet:COUNt', str_type=int, auto_min_max=True)
        self.acquire_segment_en = scpiDevice('ACQuire:SEGMented:STATe', str_type=bool)
        self.acquire_segment_max_en = scpiDevice('ACQuire:SEGMented:MAX', str_type=bool)
        self.acquire_segment_autoreplay_en = scpiDevice('ACQuire:SEGMented:AUToreplay', str_type=bool)
        self.current_channel = MemoryDevice(initval=1, choices = [1, 2, 3, 4])
        self.current_channel_waveform = MemoryDevice(initval=1, choices = [1, 2, 3])
        self.channel_multiple_waveforms_en = scpiDevice('ACQuire:MUWaveform', str_type=bool)
        self.channel_coupling_en = scpiDevice('ACQuire:CDTA', str_type=bool)
        def ChannelWaveform(*args, **kwargs):
            options = kwargs.pop('options', {}).copy()
            options.update(ch=self.current_channel, wf=self.current_channel_waveform)
            app = kwargs.pop('options_apply', ['ch', 'wf'])
            lim = kwargs.pop('options_lim', dict(wf=ChoiceDevDep(self.channel_multiple_waveforms_en,{True:[1,2,3], False:[1]})))
            kwargs.update(options=options, options_apply=app, options_lim=lim)
            return scpiDevice(*args, **kwargs)
        self.channel_en = ChannelWaveform('CHANnel{ch}:WAVeform{wf}', str_type=bool)
        self.channel_decimation_type = ChannelWaveform('CHANnel{ch}:WAVeform{wf}:TYPE', choices=ChoiceStrings('SAMPle', 'PDETect', 'HRESolution', 'RMS'))
        self.channel_arithmetic_method = ChannelWaveform('CHANnel{ch}:WAVeform{wf}:ARIThmetics', choices=ChoiceStrings('OFF', 'ENVelope', 'AVERage'))
        def Channel(*args, **kwargs):
            options = kwargs.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwargs.pop('options_apply', ['ch'])
            kwargs.update(options=options, options_apply=app)
            return scpiDevice(*args, **kwargs)
        self.input_en = Channel('CHANnel{ch}:STATe', str_type=bool)
        self.input_coupling = Channel('CHANnel{ch}:COUPling', choices=ChoiceStrings('DC', 'DCLimit', 'AC'),
                doc='DC is 50 Ohm, DCLimit is 1MOhm, AC is 1MOhm ac coupled.')
        self.input_ground_en = Channel('CHANnel{ch}:GND', str_type=bool)
        self.input_invert_en = Channel('CHANnel{ch}:INVert', str_type=bool)
        #self.input_bandwidth = Channel('CHANnel{ch}:BANDwidth', choices=ChoiceStrings('FULL', 'B200', 'B20', 'B800'))
        self.input_bandwidth = Channel('CHANnel{ch}:BANDwidth', choices=ChoiceStrings('FULL', 'B200', 'B20'))
        # TODO: handle min/max of scale/range/offset (depends on attenuation, coupling ...)
        self.input_scale_per_div = Channel('CHANnel{ch}:SCALe', str_type=float, setget=True)
        self.input_full_range = Channel('CHANnel{ch}:RANGe', str_type=float, setget=True)
        self.input_position_div = Channel('CHANnel{ch}:POSition', str_type=float, setget=True, min=-5, max=5) # auto min max does not work here
        self.input_offset = Channel('CHANnel{ch}:OFFSet', str_type=float, setget=True)
        self.input_power_calc_impedance = Channel('CHANnel{ch}:IMPedance', str_type=float, setget=True, min=0.1, max=100e3) # auto min max does not work here
        # I observe overload when giving 5.3 V dc to 50 Ohm input.
        self.input_overloaded = Channel('CHANnel{ch}:OVERload', str_type=bool, doc='Set value to False to reset the overload status bit.')
        # Can only read header/data of enabled channels/waveforms
        self.waveform_data_header = ChannelWaveform(getstr='CHANnel{ch}:WAVeform{wf}:DATA:HEADer?',
                choices=ChoiceMultiple(['x_start', 'x_stop', 'n_sample', 'n_sample_per_interval'],
                [float, float, int, int]), autoinit=False)
        self.waveform_data = ChannelWaveform(getstr='CHANnel{ch}:WAVeform{wf}:DATA?', str_type=ProxyMethod(self._decode_waveform_data),
                autoinit=False, raw=True, chunk_size=1000*1024)
        # changing en/current seems to modify current for all channels
        #  wai is needed so that a subsequent read obtains the new current channel.
        #  The graphical switch loading probably takes some time so you could process for example
        #  the timestamp before an actual change
        self.waveform_history_en = ChannelWaveform('CHANnel{ch}:WAVeform{wf}:HISTory', str_type=bool)
        self.waveform_history_index = ChannelWaveform('CHANnel{ch}:WAVeform{wf}:HISTory:CURRent {val};*WAI',
                'CHANnel{ch}:WAVeform{wf}:HISTory:CURRent?',
                str_type=int, max=0,
                doc="""
                    The value starts at 0, followed by -1 for previous until -n where n is acquire_count-1
                    (actually acquire_navailable).
                    You can only change the index when history is enabled. It is disabled after every acq.
                    """)
        self.input_filter_en = Channel('CHANnel{ch}:DIGFilter:STATe', str_type=bool)
        self.input_skew_manual_en = Channel('CHANnel{ch}:SKEW:MANual', str_type=bool)
        self.input_skew_time = Channel('CHANnel{ch}:SKEW:TIME', str_type=float, setget=True, min=-100e-9, max=100e-9)
        self.input_filter_cutoff_freq = Channel('CHANnel{ch}:DIGFilter:CUToff', str_type=float, setget=True, min=100e3, max=1e9,
                doc='The same filter is used for channels 1,2 and channels 3,4')
        self.trigger_coupling = scpiDevice('TRIGger:COUPling', choices=ChoiceStrings('OFF', 'RFReject'))
        self.highdef_mode_en = scpiDevice('HDEFinition:STATe', str_type=bool)
        self.highdef_mode_bandwidth = scpiDevice('HDEFinition:BWIDth', str_type=float, setget=True, auto_min_max=True)
        self.highdef_mode_bin_resol = scpiDevice(getstr='HDEFinition:RESolution?', str_type=int)

        # reference_clock option only with option B4 (OCXO)
        if 'B4' in self.available_options:
            # This is untested
            self.reference_clock_src = scpiDevice('SENSe:SOURce', choices=ChoiceStrings('INTernal', 'EXTernal'))
            self.reference_clock_ext_freq = scpiDevice('SENSe:EXTernal:FREQuency', str_type=float, setget=True, auto_min_max=True)

        self.current_trigger = MemoryDevice(initval='A', choices=ChoiceIndex(['A', 'B', 'R'], offset=1))
        def Trigger(*args, **kwargs):
            options = kwargs.pop('options', {}).copy()
            options.update(ch=self.current_trigger)
            app = kwargs.pop('options_apply', ['ch'])
            kwargs.update(options=options, options_apply=app)
            return scpiDevice(*args, **kwargs)
        trig_sources = ['CHAN%i'%i for i in range(1, 5)] + ['EXTernanalog', 'SBUS']
        if 'B1' in self.available_options:
            trig_sources += ['D%i'%i for i in range(16)] + ['LOGIc'] + ['MSOB%i'%i for i in range(1, 5)]
        ch_trig_srcs = ChoiceStrings(*trig_sources)
        self.trigger_source = Trigger('TRIGger{ch}:SOURce', choices=ch_trig_srcs, doc='ExternalAnalog can only use edge trigger')
        ch_trig_types = ChoiceStrings('EDGE', 'GLITch', 'WIDTh', 'RUNT', 'WINDow', 'TIMeout', 'INTerval', 'SLEWrate', 'DATatoclock',
                              'STATe', 'PATTern', 'ANEDge', 'SERPattern', 'NFC', 'TV', 'CDR')
        self.trigger_type = Trigger('TRIGger{ch}:TYPE', choices=ch_trig_types,
                doc='For B trigger only edge is allowed. For R you can use GLITch, WIDTh, RUNT, WINDow, TIMeout, INTerval, SLEWrate.')
        def TriggerSrc(*args, **kwargs):
            options = kwargs.pop('options', {}).copy()
            options.update(src=self.trigger_source)
            app = kwargs.pop('options_apply', ['ch', 'src'])
            conv = kwargs.pop('options_conv',{}).copy()
            # This conversion is only valid for channels 1-4 and external
            conv.update(dict(src=lambda x, xs: str(ch_trig_srcs.index(x)+1)))
            kwargs.update(options=options, options_apply=app, options_conv=conv)
            return Trigger(*args, **kwargs)
        self.trigger_level = TriggerSrc('TRIGger{ch}:LEVel{src}', str_type=float)
        self.trigger_edge_slope = Trigger('TRIGger{ch}:EDGE:SLOPe', choices=ChoiceStrings('POSitive', 'NEGative', 'EITHer'),
                options_lim=dict(src=ch_trig_srcs[:5]))
        self.trigger_edge_ext_coupling = scpiDevice('TRIGger:ANEDge:COUPling', choices=ChoiceStrings('DC', 'DCLimit', 'AC'), doc='Only for EXTernanalog')
        self.trigger_edge_ext_filter = scpiDevice('TRIGger:ANEDge:FILTer', choices=ChoiceStrings('OFF' , 'LFReject', 'RFReject'), doc='Only for EXTernanalog')
        self.trigger_edge_ext_filter_highpass = scpiDevice('TRIGger:ANEDge:CUToff:HIGHpass', choices=ChoiceStrings('KHZ5', 'KHZ50', 'MHZ50'))
        self.trigger_edge_ext_filter_lowpass = scpiDevice('TRIGger:ANEDge:CUToff:LOWPass', choices=ChoiceStrings('KHZ5', 'KHZ50', 'MHZ50'))
        self.trigger_edge_ext_gnd_en = scpiDevice('TRIGger:ANEDge:GND', str_type=bool)
        self.trigger_edge_ext_slope = scpiDevice('TRIGger:ANEDge:SLOPe', choices=ChoiceStrings('POSitive', 'NEGative'))
        self.trigger_qualification_en = Trigger('TRIGger{ch}:QUALify{type}:STATe', str_type=bool, options=dict(type=self.trigger_type),
                options_lim=dict(ch=['A'], type=ch_trig_types[['EDGE', 'GLITch', 'WIDTh', 'RUNT', 'WINDow', 'TIMeout', 'INTerval', 'STATe', 'PATTern']]),
                options_apply=['ch', 'type'], options_conv=dict(type=lambda x, xs: str(ch_trig_types.index(x)+1)), doc='Only for A')
        self.trigger_sequence_mode = scpiDevice('TRIGger:SEQuence:MODE', choices=ChoiceStrings('AONLy', 'ABR'))
        def HoldOff(*args, **kwargs):
            options = kwargs.pop('options', {}).copy()
            options.update(_mode=self.trigger_sequence_mode)
            app = kwargs.pop('options_apply', ['_mode'])
            lims = kwargs.pop('options_lim', {}).copy()
            lims.update(dict(_mode=['aonly']))
            kwargs.update(options=options, options_apply=app, options_lim=lims)
            return scpiDevice(*args, **kwargs)

        # Can use auto_min_max because holdoff does not exist if a-b-r trigger is enabled.
        self.trigger_holdoff_mode = HoldOff('TRIGger:HOLDoff:MODE', choices=ChoiceStrings('TIME', 'EVENts', 'RANDom', 'AUTO', 'OFF'))
        self.trigger_holdoff_time = HoldOff('TRIGger:HOLDoff:TIME', str_type=float, setget=True, min=100e-9, max=10)
        self.trigger_holdoff_events = HoldOff('TRIGger:HOLDoff:EVENts', str_type=int, min=1, max=2147483647)
        self.trigger_holdoff_random_min = HoldOff('TRIGger:HOLDoff:MIN', str_type=float, setget=True, min=100e-9, max=5)
        self.trigger_holdoff_random_max = HoldOff('TRIGger:HOLDoff:MAX', str_type=float, setget=True, min=100e-9, max=10)
        self.trigger_holdoff_auto_time = HoldOff(getstr='TRIGger:HOLDoff:AUTotime?', str_type=float)
        self.trigger_holdoff_auto_scaling = HoldOff('TRIGger:HOLDoff:SCALing', str_type=float, setget=True, min=1e-3, max=1000)

        self.trigger_hysteresis_control = TriggerSrc('TRIGger:LEVel{src}:NOISe', choices=ChoiceStrings('AUTO', 'MANual'))
        self.trigger_hysteresis_mode = TriggerSrc('TRIGger:LEVel{src}:NOISe:MODE', choices=ChoiceStrings('ABS', 'REL'))
        self.trigger_hysteresis_abs_V = TriggerSrc('TRIGger:LEVel{src}:NOISe:ABSolute', str_type=float, setget=True, min=0)
        # abs_div does not seem to work.
        #self.trigger_hysteresis_abs_div = TriggerSrc('TRIGger:LEVel{src}:NOISe:PERDivision', str_type=float, setget=True, min=0, max=5)
        self.trigger_hysteresis_rel_percent = TriggerSrc('TRIGger:LEVel{src}:NOISe:RELative', str_type=float, setget=True, min=0, max=50)
        self.trigger_hysteresis_ext_reject = scpiDevice('TRIGger:ANEDge:NREJect', str_type=bool)
        self.trigger_mode = scpiDevice('TRIGger:MODE', choices=ChoiceStrings('AUTO', 'NORMal', 'FREerun'))
        self.trigger_output_en = scpiDevice('TRIGger:OUT:STATe', str_type=bool)
        self.trigger_output_polarity = scpiDevice('TRIGger:OUT:POLarity', choices=ChoiceStrings('POSitive', 'NEGative'))
        self.trigger_output_length = scpiDevice('TRIGger:OUT:PLENgth', str_type=float, setget=True, auto_min_max=True)
        self.trigger_output_delay = scpiDevice('TRIGger:OUT:DELay', str_type=float, setget=True, auto_min_max=True)
        self.aquisition_number = scpiDevice(getstr='ACQuire:CURRent?', str_type=int)
        self.probe_state = Channel(getstr='PROBe{ch}:SETup:STATe?', choices=ChoiceStrings('DETected', 'NDETected'))
        self.probe_type = Channel(getstr='PROBe{ch}:SETup:TYPE?')
        self.probe_name = Channel(getstr='PROBe{ch}:SETup:NAME?')
        #self.probe_bandwidth = Channel(getstr='PROBe{ch}:SETup:BANDwidth?', str_type=float) # does not work
        self.probe_attenuation = Channel(getstr='PROBe{ch}:SETup:ATTenuation?', str_type=float)

        self.acquire_navailable = scpiDevice(getstr='ACQuire:AVAIlable?', str_type=int)

        self.current_generator = MemoryDevice(initval=1, choices=[1, 2])
        def Gen(*args, **kwargs):
            options = kwargs.pop('options', {}).copy()
            options.update(ch=self.current_generator)
            app = kwargs.pop('options_apply', ['ch'])
            kwargs.update(options=options, options_apply=app)
            return scpiDevice(*args, **kwargs)
        self.generator_en = Gen('WGENerator{ch}', str_type=Choice_bool_OnOff)
        self.generator_mode = Gen('WGENerator{ch}:SOURce', choices=ChoiceStrings('FUNCgen', 'MODulation', 'SWEep', 'ARBGenerator'))
        self.generator_function = Gen('WGENerator{ch}:FUNCtion',
                choices=ChoiceStrings('SINusoid', 'SQUare', 'RAMP', 'DC', 'PULSe', 'SINC', 'CARDiac', 'GAUSs', 'LORNtz', 'EXPRise', 'EXPFall'))
        self.generator_output_load = Gen('WGENerator{ch}:OUTPut', choices=ChoiceStrings('FIFTy', 'HIZ'))
        self.generator_amplitude_vpp = Gen('WGENerator{ch}:VOLTage', str_type=float, setget=True)
        self.generator_offset = Gen('WGENerator{ch}:VOLTage:OFFSet', str_type=float, setget=True)
        self.generator_dc_level = Gen('WGENerator{ch}:VOLTage:OFFSet', str_type=float, setget=True, doc='This is for function DC only')
        self.generator_volt_low = Gen('WGENerator{ch}:VOLTage:LOW', str_type=float, setget=True)
        self.generator_volt_high = Gen('WGENerator{ch}:VOLTage:HIGH', str_type=float, setget=True)
        self.generator_inversion = Gen('WGENerator{ch}:VOLTage:INVersion', str_type=bool)
        self.generator_frequency = Gen('WGENerator{ch}:FREQuency', str_type=float, setget=True)
        self.generator_period = Gen('WGENerator{ch}:PERiod', str_type=float, setget=True)
        self.generator_pulse_width = Gen('WGENerator{ch}:FUNCtion:PULSe', str_type=float, setget=True)
        self.generator_ramp_symmetry_pct = Gen('WGENerator{ch}:FUNCtion:RAMP', str_type=float, setget=True, min=0, max=100)
        self.generator_square_duty_cycle_pct = Gen('WGENerator{ch}:FUNCtion:SQUare:DCYCle', str_type=float, setget=True, min=0, max=100)
        self.generator_noise_en = Gen('WGENerator{ch}:MODulation:NOISe', str_type=bool)
        self.generator_noise_level_pct = Gen('WGENerator{ch}:MODulation:NLPCent', str_type=float, setget=True, min=0, max=100)
        self.generator_noise_level_dc = Gen('WGENerator{ch}:MODulation:NDCLevel', str_type=float, setget=True, doc='This is for function DC only')
        self.generator_noise_level_vpp = Gen(getstr='WGENerator{ch}:MODulation:NLABsolute?', str_type=float)
        # TODO: calculate(mathematics), cursor?, fft
        #  Digital, PatternGen
        self.current_math_channel = MemoryDevice(initval=1, choices=[1, 2, 3, 4])
        def MathChannel(*args, **kwargs):
            options = kwargs.pop('options', {}).copy()
            options.update(mch=self.current_math_channel)
            app = kwargs.pop('options_apply', ['mch'])
            kwargs.update(options=options, options_apply=app)
            return scpiDevice(*args, **kwargs)
        self.fetch_calc = MathChannel(getstr='format real,32; CALCulate:MATH{mch}:DATA?', str_type=decode_float32, trig=True, autoinit=False, multi=tuple(['data']))
        self.fetch_calc_header = MathChannel(getstr='CALCulate:MATH{mch}:DATA:HEADer?',
                choices=ChoiceMultiple(['x_start', 'x_stop', 'n_sample', 'n_sample_per_interval'],
                [float, float, int, int]), autoinit=False)

        self.roll_auto_en = scpiDevice('TIMebase:ROLL:ENABle', choices=ChoiceSimpleMap(dict(AUTO=True, OFF=False), filter=string.upper))
        self.roll_auto_time = scpiDevice('TIMebase:ROLL:MTIMe', str_type=float, setget=True, auto_min_max=True)
        self.roll_is_active = scpiDevice(getstr='TIMebase:ROLL:STATe?', str_type=bool)

        self.current_measurement = MemoryDevice(initval=1, choices=list(range(1,9)))
        def Meas(*args, **kwargs):
            options = kwargs.pop('options', {}).copy()
            options.update(ch=self.current_measurement)
            app = kwargs.pop('options_apply', ['ch'])
            kwargs.update(options=options, options_apply=app)
            return scpiDevice(*args, **kwargs)
        self.measurement_en = Meas('MEASurement{ch}', str_type=bool)
        self.measurement_src1 = Meas('MEASurement{ch}:FSRC', str_type=str)
        self.measurement_src2 = Meas('MEASurement{ch}:SSRC', str_type=str)
        self.measurement_category = Meas('MEASurement{ch}:CATegory', choices=ChoiceStrings('AMPTime', 'JITTer', 'EYEJitter' ,'SPECtrum', 'HISTogram', 'PROTocol'))
        self.measurement_main = Meas('MEASurement{ch}:MAIN', str_type=str)
        self.measurement_additional_en = Meas('MEASurement{ch}:ADDitional {type},{val}', 'MEASurement{ch}:ADDitional? {type}', str_type=bool,
            options=dict(type='no_valid_default'), options_conv=dict(type=lambda v, tostr: str(v)), autoinit=False)
        self.measurement_multiple_en = Meas('MEASurement{ch}:MULTiple', str_type=bool)
        self.measurement_statistics_en = Meas('MEASurement{ch}:STATistics', str_type=bool)
        self.measurement_multiple_max_n = Meas('MEASurement{ch}:MNOMeas', str_type=int, min=2)

        self._devwrap('fetch_meas', autoinit=False, trig=True)
        self._devwrap('fetch', autoinit=False)
        self._devwrap('snap_png', autoinit=False)
        self.snap_png._format['bin']='.png'
        self._devwrap('timestamp', multi=['datetime', 'ns'])
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

    def _decode_waveform_data(self, fromstr):
        form, bitp = self.set_format()
        termination = '\n'
        if form == 'int8':
            ret = decode_int8(fromstr, skip=termination)
        elif form == 'int16':
            ret = decode_int16(fromstr, skip=termination)
        else: # real or ascii
            ret = decode_float32(fromstr, skip=termination)
        return ret

## How to read data:
#  The first 3 are influenced by: EXPort:WAVeform:INCXvalues
#  The first 1 is influenced by: EXPort:WAVeform:MULTichannel
# waveform data: CHANnel<m>[:WAVeform<n>]:DATA[:VALues]?
# math waveform (spectrum, meas, corr): CALCulate:MATH<m>:DATA[:VALues]?
# reference curve: REFCurve<m>:DATA[:VALues]?
# measurement: MEASurement<m>:ARES?
# measurement track: MEASurement<m>:TRACk:DATA[:VALues]?
# measurement track/histogram/long term: EXPort:MEASurement:DATA?
# mso: DIGital<m>:DATA[:VALues]?
# iq: CHANnel<m>:IQ:DATA[:VALues]?
# histogram (from LAYout:HISTogram): EXPort:HISTogram:DATA?

# Timestamps:
#   Note that these timestamps are not updated until acquisition is stopped
#  CHANnel<m>[:WAVeform<n>]:HISTory:CURRent   to select a history time (0, -1, ...)
#   date of current as: '2018:11:02'
#  CHANnel<m>[:WAVeform<n>]:HISTory:TSDate?
#   time of current as: '17:10 55,287.977.169 s' which is 17:10:55.287977169
#  CHANnel<m>[:WAVeform<n>]:HISTory:TSABsolute?
#    time of histrory current vs 0  (which is '0' when current=0)
#  CHANnel<m>[:WAVeform<n>]:HISTory:TSRelative?
#    time with respect to some internal reference (probably last boot): '114837.28797717'
#      31 hours, 53 min, 57.28797717 sec
#  CHANnel<m>[:WAVeform<n>]:HISTory:TSRReference?
#

# Scope does not have line trigger.
#
# To disable High def mode. Press the HD button on upper right.
# High def mode off, the data is still 8 bits (in 16 bit reads, the lower 8 bits are 0)
#  except if mode highres is enable and/or arithmetic average is enabled.
#  the digital filter does not add resolution (stays at 8 bits)
# High def mode on, the data mostly follows the described number of bits (10 bits uses
#  The MSB of 16 bit (the last 4 are zeros)) except the density is not uniform (this could be due to my
#  use of the internal generator
#  Some higher number of bits are not spaced uniformly (the spacing between the 16 bit bins
#  with some data are not uniform for 14 bit (100 MHz)
#   v=get(rs.waveform_data, ch=1)
#   res=histogram(v, bins=arange(-2**15, 2**15))
#   plot(res[0][2**15:40000:1], '.-')


#######################################################
##    R&S ZNB 40 Vector Network Analyzer
#######################################################

quoted_string_znb = functools.partial(quoted_string, fromstr="'")
quoted_list_znb = functools.partial(quoted_list, fromstr="'")
quoted_dict_znb = functools.partial(quoted_dict, quote_char="'", empty='', element_type=[int, None])


#@register_instrument('Rohde-Schwarz', 'ZNB40-2Port', '2.92')
@register_instrument('Rohde-Schwarz', 'ZNB40-2Port', usb_vendor_product=[0x0AAD, 0x01BF])
@register_instrument('Rohde-Schwarz', 'ZNB40-2Port', usb_vendor_product=[0x0AAD, 0x01A2])
class rs_znb_network_analyzer(visaInstrumentAsync):
    """
    This is the driver for the Rohde & Schwarz ZNB40 2 port network analyzer
    Useful devices:
        fetch, readval
        snap_png
    Some methods available:
        abort
        create_measurement
        delete_measurement
        restart_averaging
        phase_unwrap, phase_wrap, phase_flatten
        get_file, send_file
    Other useful devices:
        trace_meas_list_in_ch
        select_trace
        current_channel
        freq_start, freq_stop, freq_cw
        port_power_en
        marker_x, marker_y
        trigger_continuous_all_ch

    Note that almost all devices/commands require a channel.
    It can be specified with the ch option or will use the last specified
    one if left to the default.
    A lot of other commands require a selected trace (per channel)
    The active one can be selected with the trace option or select_trace
    If unspecified, the last one is used.

    If a trace is REMOVED from the instrument, you should perform a get of
    the trace_meas_list_in_ch device to update pyHegel knowledge of the available
    traces (needed when trying to fetch all traces).

    The error message:
        Remote Error -200: Execution error; CALculate1:MARKer1:FUNCtion?
    can be shown when reading markers (if searching is disabled in sowe way).
    It is unavoidable in that condition (to not have the error, just set searching
    to anything other than None)
    """
    def init(self, full=False):
        self.write('FORMat REAL,64') # Other available: ascii and real,32
        self.write('FORMat:BORDer  SWAPped') # LSB first
        # If sending binary data to instrument over GPIB, it requires setting
        # SYSTem:COMMunicate:GPIB:RTERminator
        # to EOI instead of default LFEoi (Line feed OR EOI)
        # However the instrument I have does not habe gpib install so
        # so the command fails. It requires option ZNB-B10
        super(rs_znb_network_analyzer, self).init(full)

    def abort(self):
        self.write('ABORt')

    def trigger_start(self, ch=None, add_opc=True):
        """ ch when None, it triggers all channels """
        if ch is None:
            base = 'INITiate:ALL'
        else:
            self.current_channel.check(ch)
            base = 'INITiate{ch}'.format(ch=ch)
        if add_opc:
            base += ';*OPC'
        self.write(base)
    def _async_trigger_helper(self):
        self.trigger_start()

    def _match_sweep_count_navg(self):
        orig_ch = self.current_channel.get()
        chs = list(self.active_channels_list.get().keys())
        for ch in chs:
            avg_en = self.sweep_average_en.get(ch=ch)
            if avg_en:
                n_avg = self.sweep_average_count.get()
            else:
                n_avg = 1
            self.sweep_count.set(n_avg)
        self.current_channel.set(orig_ch)
    @locked_calling
    def _async_trig(self):
        self.trigger_continuous_all_ch.set(False)
        self._match_sweep_count_navg()
        self.restart_averaging('all')
        # sweep counts needs>=avg count
        # need to restart all averaging
        super(rs_znb_network_analyzer, self)._async_trig()

    @locked_calling
    def restart_averaging(self, ch='all'):
        """
        Restart averaging. Also restarts a sweep.
        ch can be 'all' (default) to restart all of device active_channels_list
        if averaging is enabled.
        ch can be None to use the current_channel
        """
        if ch == 'all':
            orig_ch = self.current_channel.get()
            chs = list(self.active_channels_list.get().keys())
        elif ch is None:
            #sets ch if necessary
            chs = [self.current_channel.get()]
        else:
            chs = [ch]
        for c in chs:
            avg_en = self.sweep_average_en.get(ch=c)
            if avg_en:
                command = 'SENSe{ch}:AVERage:CLEar'.format(ch=c)
                self.write(command)
        if ch == 'all':
            self.current_channel.set(orig_ch)

    @locked_calling
    def delete_channel(self, ch=None):
        if ch is None:
            ch = self.current_channel.get()
        self.write('CONFigure:CHANnel{ch} OFF'.format(ch=ch))

    @locked_calling
    def create_measurement(self, trace, param, ch=None):
        """
        name: any unique, non-empty string. If it already exists, we change its param
              It can be a number, like 1, in which case it is transformed to 'Trc1'
        param: Any S parameter as S11 or any other format allowed (see Analyzer documentation)
        """
        trace_all = list(self.trace_list_all.get().values())
        exist = False
        if not isinstance(trace, string_bytes_types):
            trace = 'Trc%i'%trace
        if trace in trace_all:
            exist = True
        if ch is None:
            ch = self.current_channel.get()
        else:
            self.current_channel.set(ch)
        if ch in self.active_channels_list.get().keys():
            trc_list = list(self.trace_meas_list_in_ch.get().keys())
        else:
            trc_list = []
        if exist and trace not in trc_list:
            raise ValueError('Selected trace is not in the correct channel')
        if trace in trc_list:
            self.select_trace.set(trace)
            self.meas_function.set(param, trace=trace)
        else:
            self.write('CALCulate{ch}:PARameter:SDEFine "{trace}","{param}"'.format(ch=ch, trace=trace, param=param))
        # Update list
        self.trace_meas_list_in_ch.get()

    @locked_calling
    def delete_measurement(self, trace=None, ch=None):
        """ delete a trace
            if trace=None: delete all measurements for ch
            see trace_meas_list_in_ch for the available traces
        """
        if ch is None:
            ch = self.current_channel.get()
        else:
            self.current_channel.set(ch)
        if trace is None:
            self.write('CALCulate{ch}:PARameter:DELete:CALL'.format(ch=ch))
        else:
            self.select_trace.set(trace)
            trace = self.select_trace.get()
            self.write('CALCulate{ch}:PARameter:DELete "{trace}"'.format(ch=ch, trace=trace))
        # Update list
        self.trace_meas_list_in_ch.get()
        self.select_trace.get()

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = ['opt=%s'%self.available_options]
        ch = options.get('ch', None)
        trace = options.get('trace', None)
        mkr = options.get('mkr', None)
        if ch is not None:
            ch_orig = self.current_channel.get()
            self.current_channel.set(ch)
        trace_orig = self.select_trace.get()
        if trace is None:
            # trace might have changed because of channel change
            trace = self.select_trace.get()
        port_orig = self.current_phys_port.get()

        opts += self._conf_helper('active_channels_list', 'current_channel', 'trace_meas_list_in_ch', 'select_trace')
        opts += self._conf_helper('calib_en', 'ext_ref')
        opts += self._conf_helper('freq_start', 'freq_stop', 'freq_center', 'freq_span', 'freq_cw', 'freq_meas_sideband')
        opts += self._conf_helper('bandwidth', 'bandwidth_selectivity', 'sweep_average_en', 'sweep_average_count', 'sweep_average_mode')
        opts += self._conf_helper('sweep_mode', 'sweep_type', 'sweep_linear_mode', 'sweep_time_auto_en', 'sweep_time', 'sweep_detector_time')
        opts += self._conf_helper('sweep_meas_delay', 'sweep_meas_delay_insertion_point', 'npoints', 'sweep_count')
        opts += self._conf_helper('trigger_src', 'trigger_continuous_all_ch', 'trigger_continuous')
        opts += self._conf_helper('calc_deembed_ground_loop_en', 'calc_fixture_simulator_en', 'elec_delay_loss_fixture_after_deembed_en')
        opts += self._conf_helper('marker_search_bandwidth_center_geometric_mean_en')

        def reorg(opts):
            first = True
            for ch_line in opts:
                ch_line_split = [ c.split('=', 1) for c in ch_line]
                names = [n for n, d in ch_line_split]
                data = [d for n, d in ch_line_split]
                if first:
                    data_all = [ [d] for d in data]
                    first = False
                else:
                    for db, d in zip(data_all, data):
                        db.append(d)
            return [n+'=['+','.join(d)+']' for n, d in zip(names, data_all)]

        ports = list(range(1, self.current_phys_port.max+1))
        o_s = []
        for p in ports:
            self.current_phys_port.set(p)
            o = ['phys_port=%i'%p]
            o += self._conf_helper('port_power_en', 'port_power_level_dBm', 'port_gain_control', 'port_impedance', 'port_attenuation', 'port_gain_control')
            o += self._conf_helper('port_power_permant_on_en')
            o += self._conf_helper('calc_deembed_single_end_en', 'calc_embed_single_end_en')
            o += self._conf_helper('elec_delay_loss_fixture_compensation_en', 'elec_delay_time', 'elec_delay_length', 'elec_delay_dielectric_constant')
            o_s.append(o)
        opts += reorg(o_s)
        opts += self._conf_helper('port_power_sweep_end', 'port_power_sweep_end_delay')

        traces = list(self.trace_meas_list_in_ch.get().keys())
        o_s = []
        for t in traces:
            self.select_trace.set(t)
            o = ['trace="%s"'%t]
            o += self._conf_helper('meas_function', 'trace_format', 'trace_unit', 'trace_delay_aperture')
            o += self._conf_helper('meas_function_sweep_type', 'calc_peak_hold_mode')
            o += self._conf_helper('calc_gate_en')
            if 'ZNB-K20' in self.available_options:
                o += self._conf_helper('calc_skew_meas_en', 'calc_risetime_meas_en')
            if 'ZNB-K2' in self.available_options:
                o += self._conf_helper('calc_time_transform_en')
            o += self._conf_helper('calc_math_function', 'calc_math_expression_en', 'calc_math_expression', 'calc_math_expression_wave_unit_en')
            o += self._conf_helper('calc_smoothing_en', 'calc_smoothing_aperture_percent')
            o += self._conf_helper('calib_label', 'calib_power_label', 'marker_default_format', 'marker_coupling_en')
            o_s.append(o)
        opts += reorg(o_s)

        self.select_trace.set(trace)
        if dev_obj in [self.marker_x, self.marker_y]:
            if mkr is not None:
                mkr_orig = self.current_marker.get()
                self.current_marker.set(mkr)
            opts += self._conf_helper('current_marker')
            opts += self._conf_helper('marker_en', 'marker_x', 'marker_format', 'marker_name', 'marker_type', 'marker_mode')
            opts += self._conf_helper('marker_delta_en')
            search_func = self.marker_search_function.get()
            opts += ['marker_search_function=%s'%search_func]
            if search_func != 'invalid_entry':
                tracking = self.marker_search_tracking_en.get()
                opts += ['marker_search_tracking_en=%s'%tracking]
                opts += self._conf_helper('marker_search_bandwidth_mode', 'marker_search_target', 'marker_search_target_format')
                opts += self._conf_helper('marker_search_range_index', 'marker_search_range_start', 'marker_search_range_stop')

        if dev_obj in [self.marker_ref_x, self.marker_ref_y]:
            opts += self._conf_helper('marker_ref_en', 'marker_ref_x', 'marker_ref_name', 'marker_ref_type', 'marker_ref_mode')

        self.select_trace.set(trace_orig)
        if ch is not None:
            self.current_channel.set(ch_orig)
            self.select_trace.get() # update the current trace
        self.current_phys_port.set(port_orig)
        if mkr is not None:
            self.current_marker.set(mkr_orig)
        return opts + self._conf_helper(options)

    @locked_calling
    def set_time(self, set_time=False):
        """ Reads the UTC time from the instrument or set it from the computer value
            setting requires admin right which are not available by default. So it will fail."""
        if set_time:
            now = time.gmtime()
            self.write('SYSTem:DATE %i,%i,%i'%(now.tm_year, now.tm_mon, now.tm_mday))
            self.write('SYSTem:TIME %i,%i,%i'%(now.tm_hour, now.tm_min, now.tm_sec))
        else:
            date_str = self.ask('SYSTem:DATE?')
            time_str = self.ask('SYSTem:TIME?')
            return '%s %s UTC'%(date_str.replace(',', '-'), time_str.replace(',', ':'))

    @locked_calling
    def user_key(self, key_no=None, name=None, all_query=False, reset=False):
        """ Query or set user keys.
            without key_no, returns the key that was last pressed, name (or 0, '')
            With key_no, and no name returns the name of key_no
            with key_no and name, sets the key to name
            with all_query True: returns all key names. (needs to be used on its own)
            with reset: clears all entries and return to default remote tab (go to local, update display)
                        (needs to be used on its own)
        """
        base = 'SYSTem:USER:KEY'
        qs = quoted_string(quote_char="'")
        def parse_response(ans):
            if ans == "0''":
                # No button pressed.
                # Manual says it should be "0,''"
                return 0, ''
            n, t = ans.split(',')
            n = int(n)
            t = qs(t)
            return n, t
        if key_no is not None:
            if key_no not in range(1,9):
                raise ValueError('Invalid key_no. Should be 1-8')
            if name is None:
                return parse_response(self.ask(base+'? %i'%key_no))[1]
            else:
                self.write(base+' %i,"%s"'%(key_no, name))
        else:
            if all_query:
                res = {}
                for i in range(1, 9):
                    n, t = parse_response(self.ask(base+'? %i'%i))
                    res[n] = t
                return res
            elif reset:
                self.write(base+' 0')
            else:
                return parse_response(self.ask(base+'?'))

    @locked_calling
    def get_status(self):
        """ Reading the status also clears it. This is the event(latch) status."""
        # STATus:OPERation is unused
        res = {}
        chk_bit = lambda val, bitn: bool((val>>bitn)&1)
        quest_limit2 = int(self.ask('STATus:QUEStionable:LIMit2?'))
        quest_limit1 = int(self.ask('STATus:QUEStionable:LIMit1?'))
        quest_integrity_hw = int(self.ask('STATus:QUEStionable:INTegrity:HARDware?'))
        quest_integrity = int(self.ask('STATus:QUEStionable:INTegrity?'))
        quest = int(self.ask('STATus:QUEStionable?'))
        res.update(limit1=quest_limit1, limit2=quest_limit2, quest_all=quest)
        res.update(integrity_all=quest_integrity, integrity_hw_all=quest_integrity_hw)
        res.update(ref_clock_fail=chk_bit(quest_integrity_hw, 1))
        res.update(output_power_unlevel=chk_bit(quest_integrity_hw, 2))
        res.update(receiver_overload=chk_bit(quest_integrity_hw, 3))
        res.update(external_switch_problem=chk_bit(quest_integrity_hw, 4))
        res.update(internal_comm_problem=chk_bit(quest_integrity_hw, 6))
        res.update(temperature_too_high=chk_bit(quest_integrity_hw, 7))
        res.update(oven_cold=chk_bit(quest_integrity_hw, 8))
        res.update(unstable_level_control=chk_bit(quest_integrity_hw, 9))
        res.update(external_generator_problem=chk_bit(quest_integrity_hw, 10))
        res.update(external_powermeter_problem=chk_bit(quest_integrity_hw, 11))
        res.update(time_grid_too_close=chk_bit(quest_integrity_hw, 12))
        res.update(dc_meas_overload=chk_bit(quest_integrity_hw, 13))
        res.update(port_power_exceed_limits=chk_bit(quest_integrity_hw, 14))
        res.update(detector_meas_time_too_long=chk_bit(quest_integrity_hw, 15))
        return res

    @locked_calling
    def get_status_now(self):
        """ Reading the status. This is the condition(instantenous) status."""
        quest_integrity_hw = int(self.ask('STATus:QUEStionable:INTegrity:HARDware:CONDition?'))
        res = {}
        res.update(integrity_hw_all=quest_integrity_hw)
        return res

    @locked_calling
    def remote_ls(self, remote_path=None, extra=False, only_files=False):
        """
            if remote_path is None, get catalog of device remote_cwd.
            It list both files and directories unless only_files is True
            returns None for empty and invalid directories.
            It will probably fail if filename have ", " in their name
            If extra is False, only returns file/dir names
            if extra is True: returns tuple of 3 elements
               used_space, free_space, data
               and data is list of tuples (name, file_size)
               where file_size is -1 for directories
        """
        extra_cmd = ""
        if remote_path:
            extra_cmd = ' "%s"'%remote_path
        res = self.ask('MMEMory:CATalog?'+extra_cmd)
        if res == '':
            # Invalid directory name
            return None
        res_s = res.split(', ')[:-1] # remove last element which is extra
        used_space = int(res_s[0]) # by the files
        free_space = int(res_s[1])
        names = res_s[2::3]
        is_dir = res_s[3::3]
        file_size = res_s[4::3]
        if not (len(names) == len(is_dir) == len(file_size)):
            raise RuntimeError(self.perror('remote_ls check error. One of the files probably contains ", "'))
        if (not extra) and (not only_files):
            return names
        is_dir = [x=='<DIR>' for x in is_dir]
        file_size = [-1 if x=='' else int(x) for x in file_size]
        # cross check
        for d,s in zip(is_dir, file_size):
            s = s == -1
            if d != s:
                raise RuntimeError(self.perror('remote_ls cross check failed'))
        if only_files:
            names = [n for n,d in zip(names, is_dir) if not d]
            file_size = [s for s,d in zip(file_size, is_dir) if not d]
        if not extra:
            return names
        return used_space, free_space, list(zip(names, file_size))

    @locked_calling
    def send_file(self, dest_file, local_src_file=None, src_data=None, overwrite=False):
        """
            dest_file: is the file name (absolute or relative to device remote_cwd)
                       you have to use \\ to separate directories
            overwrite: when True will skip testing for the presence of the file on the
                       instrument and proceed to overwrite it without asking confirmation.
            Use one of local_src_file (local filename) or src_data (data string)
        """
        if not overwrite:
            # split seeks both / and \
            directory, filename = os.path.split(dest_file)
            ls = self.remote_ls(directory, only_files=True)
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
        self.write('MMEMory:DATA "%s",%s\n'%(dest_file, data_str), termination=None)

    def get_file(self, remote_file, local_file=None):
        """ read a remote_file from the instrument.
            If not a full path, uses directory from remote_cwd device.
            It requires the use of \\ not / for directory separator.
            return the data unless local_file is given, then it saves data in that.
            Files can be empty or not existing but return empty data.
            Missing files also raise an error (see get_error method).
        """
        s = self.ask('MMEMory:DATA? "%s"'%remote_file, raw=True)
        if len(s) == 0 or s[0] != '#':
            # file is empty or does not exist
            return ''
        s = _decode_block_base(s)
        if local_file:
            with open(local_file, 'wb') as f:
                f.write(s)
        else:
            return s

    def _snap_png_getformat(self, **kwarg):
        pdf = kwarg.get('pdf', False)
        bin = '.pdf' if pdf else '.png'
        fmt = self.snap_png._format
        fmt.update(bin=bin)
        return BaseDevice.getformat(self.snap_png, **kwarg)

    def _snap_png_getdev(self, logo=True, time=True, color=True, portrait=False, pdf=False, window='all'):
        """ logo, time: set to True (default) to show in file
            color: set True (default) to enable color, False for gray
                   for firmware >3 can also use:
                    'user_def', 'dark_background', 'light_background', 'BW_line_styles',
                    'BW_line_solid'
                    BW means black and white
            portrait: set True for portrait orientation, False (default) for Landscape
            pdf: set to True to create pdf file, False (default) for png
            window: can be 'all' (default), 'active', 'hardcopy'
                    for generating output formated:
                        all: all diagrams on one page
                        active: only active diagram
                        hardcopy: screen capture of diagrams. Display needs to be active,
                                  and not in background (windows desktop)
                    all can produce vector graph (in pdf) except for hardcopy
        """
        color_sel = {True: 'ON', # for 3.12 same as PCLBackgrnd = Printer optimized color scheme with light background
                    False: 'OFF', # for 3.12 same as PBWLstyles = Printer optimized black and white with different line styles
                    'user_def': 'UDEFined', 'dark_background':'DBACkground',
                    'light_background':'LBACkground', 'BW_line_styles':'BWLStyles',
                    'BW_line_solid':'BWSolid'}
        def handle_option(val, setup_str, on='1', off='0'):
            if val:
                self.write(setup_str+' '+on)
            else:
                self.write(setup_str+' '+off)
        if window not in ['all', 'active', 'hardcopy']:
            # there is also 'single' and NONE but it just disables hardcopy
            # single produces multiple pages except when saving to file
            #  where only the first page is output.
            raise ValueError(self.snap_png.perror('Invalid window.'))
        if self._firmware_version < 3. and color not in [True, False]:
            raise ValueError(self.snap_png.perror('Invalid color. Use one of %s'%([True, False])))
        elif color not in color_sel:
            raise ValueError(self.snap_png.perror('Invalid color. Use one of %s'%(list(color_sel.keys()))))
        handle_option(logo, 'HCOPy:ITEM:LOGO')
        # marker info is a separate window where the markers information can be moved to
        # when enabling its output, it is added to another page.
        # However, when printing to file directly, only the first page is output.
        # This is the same problem for HCOPy:PAGE:WINDow single
        #handle_option(marker_info, 'HCOPy:ITEM:MLISt')
        handle_option(time, 'HCOPy:ITEM:TIME')
        # Note that for firmware 3.12, the only thing that seems to be affected is the logo.
        self.write('HCOPy:PAGE:COLor '+color_sel[color])
        handle_option(portrait, 'HCOPy:PAGE:ORIentation', on='PORTrait', off='LANDscape')
        self.write('HCOPy:DESTination "MMEM"') # other options: DEFPRT
        self.write('HCOPy:PAGE:WINDow %s'%window)

        tmpfile_d = r'C:\TEMP'
        if pdf:
            # I think the proper filename is the necessary. Language might not do anything.
            self.write('HCOPy:DEVice:LANGuage PDF')
            tmpfile_f = 'TempScreenGrab.pdf'
        else:
            self.write('HCOPy:DEVice:LANGuage PNG')
            tmpfile_f = 'TempScreenGrab.png'
        tmpfile_p = tmpfile_d + '\\' + tmpfile_f
        self.write('MMEMory:NAME "%s"'%tmpfile_p)
        self.write('HCOPy:IMMediate')
        ret = self.get_file(tmpfile_p)
        self.write('MMEMory:DELete "%s"'%tmpfile_p)
        return ret

    def _fetch_getformat(self, **kwarg):
        unit = kwarg.get('unit', 'default')
        xaxis = kwarg.get('xaxis', True)
        ch = kwarg.get('ch', None)
        traces = kwarg.get('traces', None)
        cook = kwarg.get('cook', False)
        cal = kwarg.get('cal', False)
        location = kwarg.get('location', 'sdata')
        if location == 'fdata':
            cook = True
        if cal:
            cook = False
        if ch is not None:
            self.current_channel.set(ch)
        traces, traces_list = self._fetch_traces_helper(traces, cal)
        if xaxis:
            sweeptype = self.sweep_type.getcache()
            choice = self.sweep_type.choices
            if sweeptype in choice[['linear', 'log', 'segment']]:
                multi = 'freq(Hz)'
            elif sweeptype in choice[['power']]:
                multi = 'power(dBm)'
            elif sweeptype in choice[['CW', 'point']]:
                multi = 'time(s)'
            else: # PULSE
                multi = 'pulse' # TODO check this
            multi = [multi]
        else:
            multi = []
        # we don't handle cmplx because it cannot be saved anyway so no header or graph
        for t in traces_list:
            names = None
            if cook:
                f = self.trace_format.get(trace=t)
                if f not in self.trace_format.choices[['POLar', 'SMITh', 'ISMith']]:
                    names = ['cook_val']
            if names is None:
                if unit == 'db_deg':
                    names = ['dB', 'deg']
                else:
                    names = ['real', 'imag']
            if cal:
                basename = '%s_%i_%i_'%t
            elif traces is None:
                basename = "%s_"%t
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
        if traces is None:
            traces_list = self.calc_data_all_list.get()
        else:
            if isinstance(traces, list) or ((not cal) and isinstance(traces, tuple)):
                traces = traces[:] # make a copy so it can be modified without affecting caller. I don't think this is necessary anymore but keep it anyway.
            else:
                traces = [traces]
            traces_list = traces
        return traces, traces_list

    def _fetch_getdev(self, ch=None, traces=None, unit='default', xaxis=True, cook=False, cal=False, location='sdata'):
        """
           options available: traces, unit, mem and xaxis
            -traces: can be a single value or a list of values.
                     The values are strings representing the trace or the trace number.
                     Memory traces also have a name (often like 'Mem1[Trc1]')
                     or when cal is True, tuples like ('DIRECTIVITY', 1, 1)
                     When None (default) selects all data traces (not memory) of the channel.
                     To obtain memory traces, they need to be specified
                     WARNING: when traces is None and averaging is enabled it will always be reduce averaging,
                              instead of the selected one. At least for firmware V2.92
            -unit:   can be 'default' (real, imag)
                       'db_deg' (db, deg) , where phase is unwrapped
                       'cmplx'  (complex number), Note that this cannot be written to file
            -xaxis:  when True(default), the first column of data is the xaxis
            -cal:    when True, traces refers to the calibration curves, cook is
                     unused.
            -cook:   when True (default is False) returns the values from the display format
                     They include the possible effects from trace math(edelay, transforms, gating...)
                     as well as smoothing. When this is selected, unit has no effect unless the format is
                     Smith, Polar or Inverted Smith (in which case both real and imaginary are read and
                     converted appropriately)
            -location: Can be one of 'sdata' (default), 'mdata', 'fdata', 'ncdata', 'ucdata', 'fsidata'
                       note that not all combinations are possible. For example, with traces=None
                       only sdata or fsidata are possible.
                       fdata is the same as cook=True (it is display data and can be 1 or 2 values per stimulus).
                       All others a complex number converted according to unit.
                       mdata includes all calculations (edelay, trace math, ...) (position 3 in Figure 4.1, page 89,
                          of ZNB_ZNBT_UserManual_en_42)
                       sdata includes most calculation (edelay) except trace math (position 2)
                       fsidata includes only calibration (position 1)
                       ncdata only uses factory calibration.
                       ucdata is raw data
        """
        if ch is not None:
            self.current_channel.set(ch)
        else:
            ch = self.current_channel.get()
        if location ==  'fdata':
            cook = True
        if cal:
            cook = False
        if cook:
            location = 'fdata'
        traces, traces_list = self._fetch_traces_helper(traces, cal)
        if xaxis:
            if cal:
                ret = [self.calib_data_xaxis.get()]
            else:
                if traces is None:
                    tr = list(self.trace_meas_list_in_ch.get().keys())[0]
                else:
                    tr = traces[0]
                # get the x axis of the first trace selected
                ret = [self.get_xscale(trace=tr)]
        else:
            ret = []
        data = None
        if traces is None:
            data = self.calc_data_all.get(format=location)
            #data.shape = (len(traces_list), self.npoints.get(), 2)
            data.shape = (len(traces_list), self.npoints.get()*2)
        for i, t in enumerate(traces_list):
            if cal:
                v = self.calib_data.get(eterm=t[0], p1=t[1], p2=t[2])
            elif traces is None:
                v = data[i]
            else:
                v = self.calc_data.get(trace=t, format=location)
            if cook:
                f = self.trace_format.get(trace=t)
                if f not in self.trace_format.choices[['POLar', 'SMITh', 'ISMith']]:
                    ret.append(v)
                    continue
                v = v[0::2] + 1j*v[1::2]
            elif not cal:
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

    def get_xscale(self, ch=None, trace=None):
        return self.x_axis.get(ch=ch, trace=trace)

    def conf_options(self):
        ret = {}
        qs = quoted_string_znb()
        for o in self.available_options:
            desc = qs(self.ask('DIAGnostic:PRODuct:OPTion:INFO? "%s", DESCription'%o))
            type = qs(self.ask('DIAGnostic:PRODuct:OPTion:INFO? "%s", TYPE'%o))
            activation = qs(self.ask('DIAGnostic:PRODuct:OPTion:INFO? "%s", ACTivation'%o))
            expiration = qs(self.ask('DIAGnostic:PRODuct:OPTion:INFO? "%s", EXPiration'%o))
            key = qs(self.ask('DIAGnostic:PRODuct:OPTion:INFO? "%s", KEY'%o))
            data = dict(desc=desc, type=type, activation=activation, expiration=expiration, key=key)
            ret[o] = data
        return ret

    def _help_ch_trace(self, ch=None, trace=None):
        if ch is not None:
            self.current_channel.set(ch)
        else:
            ch = self.current_channel.get()
        if trace is not None:
            self.select_trace.set(trace)
        else:
            trace = self.select_trace.get()
        return ch, trace

    def calc_math_data_to_mem(self, ch=None, trace=None):
        ch, trace = self._help_ch_trace(ch, trace)
        self.write('CALCulate{ch}:MATH:MEMorize'.format(ch=ch))

    def _help_ch_trace_mkr(self, ch=None, trace=None, mkr=None):
        ch, trace = self._help_ch_trace(ch, trace)
        if mkr is None:
            mkr = self.current_marker.get()
        else:
            self.current_marker.set(mkr)
        return ch, trace, mkr

    def marker_send_to(self, dest='center', ch=None, trace=None, mkr=None):
        """ dest can be: 'center', 'start', 'stop', 'span' """
        choices = ChoiceStrings('CENTer', 'SPAN', 'STARt', 'STOP')
        if dest not in choices:
            raise ValueError(self.perror('Invalid dest parameter'))
        ch, trace, mkr = self._help_ch_trace_mkr(ch, trace, mkr)
        self.write('CALCulate{ch}:MARKer{mkr}:FUNCtion:{dest}'.format(ch=ch, mkr=mkr, dest=dest))

    def marker_search_exec(self, func, ch=None, trace=None, mkr=None):
        """ func can be: 'MAXimum', 'MINimum', 'RPEak', 'LPEak', 'NPEak', 'TARGet', 'RTARget', 'LTARget', 'BFILter', 'MMAXimum', 'MMINimum', 'SPRogress'"""
        choices = ChoiceStrings('MAXimum', 'MINimum', 'RPEak', 'LPEak', 'NPEak', 'TARGet', 'RTARget', 'LTARget', 'BFILter', 'MMAXimum', 'MMINimum', 'SPRogress')
        if func not in choices:
            raise ValueError(self.perror('Invalid func parameter'))
        ch, trace, mkr = self._help_ch_trace_mkr(ch, trace, mkr)
        self.write('CALCulate{ch}:MARKer{mkr}:FUNCtion:EXECute {func}'.format(ch=ch, mkr=mkr, func=func))

    def _create_devs(self):
        self._firmware_version = float(self.idn_split()['firmware'])
        opt = self.ask('*OPT?')
        self.available_options = opt.split(',')
        nports = int(self.ask('INSTrument:PORT:COUNt?'))
        # There is a bug. Asking for once twice behaves like True.
        self.display_remote_update_en = scpiDevice('SYSTem:DISPlay:UPDate', choices=ChoiceSimpleMap({'1':True, '0':False, 'ONCE':'once'}))
        self.display_message_text = scpiDevice('SYSTem:USER:DISPlay:TITLe', str_type=quoted_string_znb(), doc='The message is in the black remote window')
        self.remote_cwd = scpiDevice('MMEMory:CDIRectory', str_type=quoted_string_znb(),
                                     doc=r"""
                                          instrument default is C:\\Users\\Public\\Documents\\Rohde-Schwarz\\VNA
                                          You have to use \ (make sure to use raw strings r"" or double them \\)
                                          """)

        self.current_channel = MemoryDevice(1, min=1, max=200)
        self.current_phys_port = MemoryDevice(1, min=1, max=nports)
        self.current_marker = MemoryDevice(1, min=1, max=10)
        self.active_channels_list = scpiDevice(getstr='CONFigure:CHANnel:CATalog?', str_type=quoted_dict_znb())
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.channel_en = devChOption('CONFigure:CHANnel{ch}:MEASure', str_type=bool)
        self.trace_list_in_ch = devChOption(getstr='CONFigure:CHANnel{ch}:TRACe:CATalog?', str_type=quoted_dict_znb())
        self.trace_list_all = scpiDevice(getstr='CONFigure:TRACe:CATalog?', str_type=quoted_dict_znb())
        self.trace_meas_list_in_ch = devChOption(getstr='CALCulate{ch}:PARameter:CATalog?', str_type=quoted_dict(quote_char="'", empty=''))
        # CONFigure:TRACe:WINDow:TRACe? <TraceName>  converts from TraceName to trace number
        # CONFigure:TRACe:WINDow? <TraceName>  finds the trace window (diagram), returns 0 if not displayed
        # windowTrace restarts at 1 for each window
        select_trace_choices = ChoiceDevSwitch(self.trace_meas_list_in_ch,
                                               lambda t: 'Trc%i'%t,
                                               sub_type=quoted_string_znb())
        self.select_trace = devChOption('CALCulate{ch}:PARameter:SELect', autoinit=8,
                                        choices=select_trace_choices, doc="""
                Select the trace using either the trace name (standard ones are 'Trc1')
                which are unique, the trace param like 'S11' which might not be unique
                (in which case the first one is used). A number (like 1) is converted to the format 'Trc1'.
                The actual Trace number are not used.
                You need to select traces that are members of the channel.
                """)

        def devCalcOption(*arg, **kwarg):
            # Use this one everywhere the manual uses <Chn> instead of <Ch>
            options = kwarg.pop('options', {}).copy()
            options.update(trace=self.select_trace)
            app = kwarg.pop('options_apply', ['ch', 'trace'])
            kwarg.update(options=options, options_apply=app)
            return devChOption(*arg, **kwarg)
        # There is a set SENSe{ch}:FUNCtion but the parameters are different than on read.
        # So just to read now.
        # TODO: implement set
        self.meas_function_sweep_type = devCalcOption(getstr='SENSe{ch}:FUNCtion?', str_type=quoted_string_znb())
        self.meas_function = devCalcOption('CALCulate{ch}:PARameter:MEASure {trace},{val}', 'CALCulate{ch}:PARameter:MEASure? {trace}', str_type=quoted_string_znb())

        self.freq_start = devChOption('SENSe{ch}:FREQuency:STARt', str_type=float, setget=True, auto_min_max=True)
        self.freq_stop = devChOption('SENSe{ch}:FREQuency:STOP', str_type=float, setget=True, auto_min_max=True)
        self.freq_center = devChOption('SENSe{ch}:FREQuency:CENTer', str_type=float, setget=True, auto_min_max=True)
        self.freq_span = devChOption('SENSe{ch}:FREQuency:SPAN', str_type=float, setget=True, auto_min_max=True)
        self.freq_cw = devChOption('SENSe{ch}:FREQuency:CW', str_type=float, setget=True, auto_min_max=True)
        self.freq_meas_sideband = devChOption('SENSe{ch}:FREQuency:SBANd', choices=ChoiceStrings('POSitive', 'NEGative', 'AUTO'))
        # This requires option K14 K4
        #self.freq_conversion_mode = devChOption('SENSe{ch}:FREQuency:CONVersion', choices=ChoiceStrings('FUNDamental', 'ARBitrary', 'MIXer'))
        # Phase:mode does not seem to work.
        #self.phase_mode = devChOption('SENSe{ch}:PHASe:MODE', choices=ChoiceStrings('NCOHerent', 'COHerent', 'LNNCoherent', 'LNCoherent'))

        self.bandwidth = devChOption('SENSe{ch}:BANDwidth', str_type=float, setget=True, auto_min_max=True)
        self.bandwidth_selectivity = devChOption('SENSe{ch}:BANDwidth:SELect', choices=ChoiceStrings('NORMal', 'MEDium', 'HIGH'))
        self.sweep_average_en = devChOption('SENSe{ch}:AVERage', str_type=bool)
        self.sweep_average_count = devChOption('SENSe{ch}:AVERage:COUNt', str_type=int, auto_min_max=True)
        self.sweep_average_mode = devChOption('SENSe{ch}:AVERage:MODE', choices=ChoiceStrings('AUTO', 'FLATten', 'REDuce', 'MOVing'),
                                              doc="""
                                                  AUTO: the manual says it selects between FLATten (Linear/db/Phase) and Reduce (others)
                                                        but tests seem to indicate it is always Reduce
                                                  Reduce: Averages real/imaginary
                                                  Flatten: Averages linear amplitude/phase
                                                  Moving: Same as Reduce but only keeps last count in average
                                                  Flatten and Reduce are exponential averages. Starting from a reset they reach
                                                  a stable value after count. But they have exponential memory after that.
                                                  Equivalent python code:
                                                      #let data be in vector v of infinite length that starts with zeroes.
                                                      #new values are given to v[i] for iteration i (starting at 0).
                                                      #The request is for N averages.
                                                      # for reduce/Flatten
                                                      if i<N:
                                                          avg = v[:i+1].mean()
                                                      else:
                                                          avg = (1-1./N)*avg + (1./N)*v[i]
                                                      # for moving:
                                                      if i<N:
                                                          avg = v[:i+1].mean()
                                                      else:
                                                          avg = v[-N:].mean()
                                                  """)
        self.sweep_mode = devChOption('SENSe{ch}:COUPle', choices=ChoiceStrings('ALL', 'AUTO', 'NONE'), doc='ALL is chopped sweep mode, NONE is alternate sweep mode, auto depends on sweep time (chopped for long)')
        self.sweep_type = devChOption('SENSe{ch}:SWEep:TYPE', choices=ChoiceStrings('LINear', 'LOGarithmic', 'POWer', 'CW', 'POINt', 'SEGMent', 'PULSe'))
        self.sweep_linear_mode = devChOption('SENSe{ch}:SWEep:GENeration', choices=ChoiceStrings('STEPped', 'ANALog'))
        self.sweep_time_auto_en = devChOption('SENSe{ch}:SWEep:TIME:AUTO', str_type=bool)
        self.sweep_time = devChOption('SENSe{ch}:SWEep:TIME', str_type=float, setget=True, auto_min_max='max', min=0)
        self.sweep_detector_time = devChOption('SENSe{ch}:SWEep:DETector:TIME', str_type=float, setget=True, auto_min_max=True)
        self.sweep_meas_delay = devChOption('SENSe{ch}:SWEep:DWELl', str_type=float, setget=True, auto_min_max=True)
        self.sweep_meas_delay_insertion_point = devChOption('SENSe{ch}:SWEep:DWELl:IPOint', choices=ChoiceStrings('ALL', 'FIRSt'))
        self.npoints = devChOption('SENSe{ch}:SWEep:POINts', str_type=int, auto_min_max=True)
        self.sweep_count = devChOption('SENSe{ch}:SWEep:COUNt', str_type=int, auto_min_max=True)
        self.sweep_count_current = devCalcOption(getstr='CALCulate{ch}:DATA:NSWeep:COUNt?', str_type=int, autoinit=False)

        def devChPhysOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(port=self.current_phys_port)
            app = kwarg.pop('options_apply', ['ch', 'port'])
            kwarg.update(options=options, options_apply=app)
            return devChOption(*arg, **kwarg)

        self.port_impedance = devChPhysOption('SENSe{ch}:PORT{port}:ZREFerence', str_type=complex, multi=['real', 'imag'])
        self.port_attenuation = devChPhysOption('SENSe{ch}:POWer:ATTenuation {port},{val}', 'SENSe{ch}:POWer:ATTenuation? {port}', str_type=float, min=0, setget=True)
        self.port_gain_control = devChPhysOption('SENSe{ch}:POWer:GAINcontrol:GLOBal', choices=ChoiceStrings('LNOise', 'LTRacenoise', 'LDIStortion', 'AUTO', 'MSNR', 'MANual'))
        self.port_power_level_dBm = devChPhysOption('SOURce{ch}:POWer{port}', str_type=float, setget=True, auto_min_max=True)
        self.port_power_en = devChPhysOption('SOURce{ch}:POWer{port}:STATe', str_type=bool)
        self.port_power_permant_on_en = devChPhysOption('SOURce{ch}:POWer{port}:PERManent', str_type=bool)
        self.port_power_sweep_end = scpiDevice('SOURce:POWer:SWEepend:MODE', choices=ChoiceStrings('AUTO', 'REDuce', 'KEEP'))
        self.port_power_sweep_end_delay = scpiDevice('SOURce:POWer:SWEepend:SDELay', str_type=float, setget=True, auto_min_max=True)

        self.trigger_src = devChOption('TRIGger{ch}:SOURce', choices=ChoiceStrings('IMMediate', 'EXTernal', 'MANual', 'MULTiple'))
        self.trigger_continuous_all_ch = scpiDevice('INITiate:CONTinuous:ALL', str_type=bool)
        self.trigger_continuous = devChOption('INITiate{ch}:CONTinuous', str_type=bool)

        # format could also be SCORr1 - SCORr27 but prefer calib_data for that.
        self.calc_data = devCalcOption(getstr='CALCulate{ch}:DATA? {format}', str_type=decode_float64, options=dict(format='sdata'),
                                       options_lim=dict(format=ChoiceStrings('FDATa', 'SDATa', 'MDATa', 'NCData', 'UCData')),
                                       autoinit=False, trig=True)
        self.x_axis = devCalcOption(getstr='CALCulate{ch}:DATA:STIMulus?', str_type=decode_float64, autoinit=False)
        self.calc_data_all = devChOption(getstr='CALCulate{ch}:DATA:CALL? {format}', str_type=decode_float64, options=dict(format='sdata'),
                                       options_lim=dict(format=ChoiceStrings('SDATa', 'FSIData')),
                                       autoinit=False, trig=True)
        self.calc_data_all_list = devChOption(getstr='CALCulate{ch}:DATA:CALL:CATalog?', str_type=quoted_list_znb(), autoinit=False)

        self.calc_gate_en = devCalcOption('CALCulate{ch}:FILTer:TIME:STATe', str_type=bool)
        if 'ZNB-K20' in self.available_options:
            self.calc_skew_meas_en = devCalcOption('CALCulate{ch}:DTIMe:STATe', str_type=bool)
            self.calc_risetime_meas_en = devCalcOption('CALCulate{ch}:TTIMe:STATe', str_type=bool)
        if 'ZNB-K2' in self.available_options:
            self.calc_time_transform_en = devCalcOption('CALCulate{ch}:TRANsform:TIME:STATe', str_type=bool)
        self.calc_deembed_ground_loop_en = devChOption('CALCulate{ch}:TRANsform:VNETworks:GLOop:DEEMbedding', str_type=bool)
        self.calc_fixture_simulator_en = devChOption('CALCulate{ch}:TRANsform:VNETworks:FSIMulator', str_type=bool)
        self.calc_deembed_single_end_en = devChPhysOption('CALCulate{ch}:TRANsform:VNETworks:SENDed:DEEMbedding{port}', str_type=bool)
        self.calc_embed_single_end_en = devChPhysOption('CALCulate{ch}:TRANsform:VNETworks:SENDed:EMBedding{port}', str_type=bool)
        self.calc_peak_hold_mode = devCalcOption('CALCulate{ch}:PHOLd', choices=ChoiceStrings('MIN', 'MAX', 'OFF'))
        self.calc_math_function = devCalcOption('CALCulate{ch}:MATH:FUNCtion', choices=ChoiceStrings('NORMal', 'ADD', 'SUBTract', 'MULTiply', 'DIVide'))
        self.calc_math_expression = devCalcOption('CALCulate{ch}:MATH:SDEFine', str_type=quoted_string_znb())
        self.calc_math_expression_en = devCalcOption('CALCulate{ch}:MATH:STATe', str_type=bool)
        self.calc_math_expression_wave_unit_en = devCalcOption('CALCulate{ch}:MATH:WUNit', str_type=bool)
        self.calc_smoothing_en = devCalcOption('CALCulate{ch}:SMOothing', str_type=bool)
        self.calc_smoothing_aperture_percent = devCalcOption('CALCulate{ch}:SMOothing:APERture', str_type=float, setget=True, auto_min_max=True)
        # TODO: CALCulate<Chn>:STATistics

        def devChMarkOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_marker)
            app = kwarg.pop('options_apply', ['ch', 'trace', 'mkr'])
            kwarg.update(options=options, options_apply=app)
            return devCalcOption(*arg, **kwarg)

        def adjust_getformat(dev, with_mkr):
            """ the marker_*_y can return 1, 2 or 3 values.
                Could figure out by reading its type, but if default needs to
                find default type from curve, which can be default and depend
                on curve type.
                So short circuit all that craziness by just reading the data.
                The caveat is that we waste a read just for getformat.
                However, if many getformat are requested of a single conf, it will bypass
                that read.
            """
            dev.getformat_orig = dev.getformat
            dev._getformat_last_get = 0, (None, None, None)
            def getformat_new(**kwarg):
                last, last_conf = dev._getformat_last_get
                now = time.time()
                ch = kwarg.get('ch', None)
                trace = kwarg.get('trace', None)
                mkr = kwarg.get('mkr', None)
                same_conf = True
                if ch is not None and last_conf[0] != ch:
                    same_conf = False
                if trace is not None and last_conf[1] != trace:
                    same_conf = False
                if mkr is not None and last_conf[2] != mkr:
                    same_conf = False
                # we keep previous conf unless it is too old or different
                if now-1 > last or not same_conf:
                    get_kwd = dict(ch=ch, trace=trace)
                    if with_mkr:
                        get_kwd['mkr'] = mkr
                    data = dev._getdev(**get_kwd)
                    if isinstance(data, float):
                        N = 1
                    else:
                        N = len(data)
                    if N == 1:
                        multi = False
                    elif N >= 2:
                        multi = ['real', 'imag']
                        if N == 3:
                            multi += ['C_L']
                        elif N > 3:
                            # This should not happen
                            multi += ['extra%i'%i for i in range(1, N-2 +1)]
                    fmt = dev._format
                    fmt.update(multi=multi)
                    dev._getformat_last_get = now, (ch, trace, mkr)
                return dev.getformat_orig(**kwarg)
            dev.getformat = getformat_new
            return dev

        mkr_format_options = ChoiceStrings('DEFault', 'MLINear', 'MLOGarithmic', 'PHASe', 'POLar', 'GDELay', 'REAL', 'IMAGinary',
                'SWR', 'LINPhase', 'LOGPhase', 'IMPedance', 'ADMittance', 'MIMPedance')
        self.marker_default_format = devCalcOption('CALCulate{ch}:MARKer:DEFault:FORMat', choices=mkr_format_options,
                doc='Note that instrument can have this settings at index. In which case it returns an error.')
        self.marker_coupling_en = devCalcOption('CALCulate{ch}:MARKer:COUPled', str_type=bool)
        self.marker_en = devChMarkOption('CALCulate{ch}:MARKer{mkr}', str_type=bool)
        self.marker_x = devChMarkOption('CALCulate{ch}:MARKer{mkr}:X', str_type=float, setget=True, trig=True)
        # empty data is replaced by nan. The instrument also shows an error that seem unavoidable.
        self.marker_y = adjust_getformat(devChMarkOption('CALCulate{ch}:MARKer{mkr}:Y',
                                                         str_type=Block_Codec(sep=',', single_not_array=True, empty=np.nan),
                                                         setget=True, autoinit=False, trig=True), True)
        self.marker_format = devChMarkOption('CALCulate{ch}:MARKer{mkr}:FORMat', choices=mkr_format_options,
                doc='Note that instrument can have this settings at index. In which case it returns an error.')
        self.marker_name = devChMarkOption('CALCulate{ch}:MARKer{mkr}:NAME', str_type=quoted_string_znb())
        self.marker_type = devChMarkOption('CALCulate{ch}:MARKer{mkr}:TYPE', choices=ChoiceStrings('NORMal', 'FIXed', 'ARBitrary'))
        self.marker_mode = devChMarkOption('CALCulate{ch}:MARKer{mkr}:MODE', choices=ChoiceStrings('CONTinuous', 'DISCrete'))
        self.marker_delta_en = devChMarkOption('CALCulate{ch}:MARKer{mkr}:DELTa', str_type=bool)
        # This is undocumented. Also device set to SPRogress returns an empty string.
        #   Both function and tracking_en modify GUI menus: "Marker Search", "Multiple Peak", "Target Search", "Band-filter"
        # They can be changed in a way in the GUI that returns errors or empty strings in remote control
        self.marker_search_function = devChMarkOption('CALCulate{ch}:MARKer{mkr}:FUNCtion', choices=ChoiceStrings('MAXimum', 'MINimum', 'RPEak', 'LPEak', 'NPEak', 'TARGet',
                                                      'RTARget', 'LTARget', 'BFILter', 'MMAXimum', 'MMINimum', 'SPRogress', 'INVALID_ENTRY', redirects={'':'INVALID_ENTRY'}), autoinit=False)
        #self.marker_search_tracking_en = devChMarkOption('CALCulate{ch}:MARKer{mkr}:SEARch:TRACking', str_type=bool)
        self.marker_search_tracking_en = devChMarkOption('CALCulate{ch}:MARKer{mkr}:SEARch:TRACking', choices=ChoiceSimpleMap({'1':True, '0':False, '':'INVALID_ENTRY'}), autoinit=False)
        self.marker_search_target = devChMarkOption('CALCulate{ch}:MARKer{mkr}:TARGet', str_type=float, setget=True)
        self.marker_search_target_format = devChMarkOption('CALCulate{ch}:MARKer{mkr}:SEARch:FORMat', choices=ChoiceStrings('MLINear', 'MLOGarithmic', 'PHASe', 'UPHase',
                                                    'REAL', 'IMAGinary', 'SWR', 'DEFault'))
        self.marker_search_range_index = devChMarkOption('CALCulate{ch}:MARKer{mkr}:FUNCtion:DOMain:USER', str_type=int, min=0, max=10, doc='0 is the full span')
        self.marker_search_range_start = devChMarkOption('CALCulate{ch}:MARKer{mkr}:FUNCtion:DOMain:USER:STARt', str_type=float, setget=True)
        self.marker_search_range_stop = devChMarkOption('CALCulate{ch}:MARKer{mkr}:FUNCtion:DOMain:USER:STOP', str_type=float, setget=True)
        self.marker_search_result = devCalcOption(getstr='CALCulate{ch}:MARKer:FUNCtion:RESult?', choices=ChoiceMultiple(['x', 'y'], float), autoinit=False, trig=True)
        self.marker_ref_en = devCalcOption('CALCulate{ch}:MARKer:REFerence', str_type=bool)
        self.marker_ref_x = devCalcOption('CALCulate{ch}:MARKer:REFerence:X', str_type=float, setget=True)
        self.marker_ref_y = adjust_getformat(devCalcOption('CALCulate{ch}:MARKer:REFerence:Y',
                                                           str_type=Block_Codec(sep=',', single_not_array=True, empty=np.nan),
                                                           setget=True, autoinit=False), False)
        # marker_ref_format seems to be missing
        self.marker_ref_name = devCalcOption('CALCulate{ch}:MARKer:REFerence:NAME', str_type=quoted_string_znb())
        self.marker_ref_type = devCalcOption('CALCulate{ch}:MARKer:REFerence:TYPE', choices=ChoiceStrings('NORMal', 'FIXed', 'ARBitrary'))
        self.marker_ref_mode = devCalcOption('CALCulate{ch}:MARKer:REFerence:MODE', choices=ChoiceStrings('CONTinuous', 'DISCrete'))
        self.marker_search_bandwidth_center_geometric_mean_en = scpiDevice('CALCulate:MARKer:FUNCtion:BWIDth:GMCenter', str_type=bool)
        self.marker_search_bandwidth_mode = devChMarkOption('CALCulate{ch}:MARKer{mkr}:FUNCtion:BWIDth:MODE',
                                                 choices=ChoiceStrings('BPASs', 'BSTop', 'BPRMarker', 'BSRMarker', 'BPABsolute', 'BSABsolute', 'NONE'))
        # on writing can only set one parameter which is bandwidth finding parameter in dB
        self.marker_search_bandwidth_result = devChMarkOption(getstr='CALCulate{ch}:MARKer{mkr}:BWIDth', autoinit=False, trig=True,
                                                       choices=ChoiceMultiple(['bandwidth', 'center', 'quality_3db', 'loss', 'lower', 'upper'], float))

        # MAGNitude is the same as MLOGarithmic, COMPlex the same as POLar
        # LOGarithmic does not seem to exist
        self.trace_format = devCalcOption('CALCulate{ch}:FORMat', choices=ChoiceStrings('MLINear', 'MLOGarithmic',
                                        'PHASe', 'UPHase', 'POLar', 'SMITh', 'ISMith', 'GDELay',
                                        'REAL', 'IMAGinary', 'SWR'))
        self.trace_unit = devCalcOption('CALCulate{ch}:FORMat:WQUType', choices=ChoiceStrings('POWer', 'VOLTage'))
        self.trace_delay_aperture = devCalcOption('CALCulate{ch}:GDAPerture:SCOunt', str_type=int, setget=True, auto_min_max=True)

        self.elec_delay_loss_fixture_after_deembed_en = scpiDevice('SENSe:CORRection:EDELay:VNETwork', str_type=bool)
        self.elec_delay_loss_fixture_compensation_en = devChPhysOption('SENSe{ch}:CORRection:OFFSet{port}:COMPensation', str_type=bool)
        self.elec_delay_time = devChPhysOption('SENSe{ch}:CORRection:EDELay{port}', str_type=float)
        self.elec_delay_dielectric_constant = devChPhysOption('SENSe{ch}:CORRection:EDELay{port}:DIELectric', str_type=float, setget=True, auto_min_max=True)
        self.elec_delay_length = devChPhysOption('SENSe{ch}:CORRection:EDELay{port}:DISTance', str_type=float)

        calib_data_options = dict(eterm='DIRECTIVITY', p1=1, p2=1)
        eterm_options = ChoiceStrings('DIRECTIVITY', 'SRCMATCH', 'REFLTRACK', 'LOADMATCH', 'TRANSTRACK',
                                      'G11', 'G12', 'G21', 'G22',
                                      'H11', 'H12', 'H21', 'H22',
                                      'Q11', 'Q12', 'Q21', 'Q22', 'PREL',
                                      'L1', 'L2', 'LA')
        calib_data_options_lim = dict(eterm=eterm_options, p1=(1,2), p2=(1,2))
        calib_data_options_conv = dict(eterm=lambda val, quoted_val: "'%s'"%val)
        self.calib_data = devChOption(getstr='SENSe{ch}:CORRection:CDATa? {eterm},{p1},{p2}', str_type=lambda x: decode_complex128(x, skip='\n'), autoinit=False, raw=True,
                                      options_conv=calib_data_options_conv, options=calib_data_options, options_lim=calib_data_options_lim,
                                      doc="""
                                         You should specify eterm, p1(source port) and p2(load_port). They default to DIRECTIVITY, 1, 1
                                         The various values for eterm are:
                                           DIRECTIVITY, SRCMATCH, REFLTRACK: require p1
                                           LOADMATCH: requires p2
                                           TRANSTRACK: requires p1, p2
                                           G11, G12, G21, G22: requires p1
                                           H11, H12, H21, H22: requires p2
                                           Q11, Q12, Q21, Q22, PREL: requires p1
                                           L1, L2, LA: requires p1
                                      """)
        self.calib_data_xaxis = devChOption(getstr='SENSe{ch}:CORRection:STIMulus?', str_type=decode_float64, autoinit=False)
        self.calib_en = devChOption('SENSe{ch}:CORRection', str_type=bool)
        self.calib_label = devCalcOption(getstr='SENSe{ch}:CORRection:SSTate?', str_type=quoted_string_znb())
        self.calib_power_label = devCalcOption(getstr='SENSe{ch}:CORRection:PSTate?', str_type=quoted_string_znb())
        # IMEthod does not seem to work.
        #self.calib_interpol_method = devChOption('SENSe{ch}:CORRection:IMEThod', choices=ChoiceStrings('LINear', 'HORDer'))

        self.ext_ref = scpiDevice('ROSCillator:SOURce', choices=ChoiceStrings('INTernal', 'EXTernal'))
        # ext_ref_freq does not work (documentation says so 2018-11)
        #self.ext_ref_freq = scpiDevice('ROSCillator:EXTernal:FREQuency', str_type=float)

        self._devwrap('fetch', autoinit=False, trig=True)
        self._devwrap('snap_png', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

# Data transfer:
#   CALCulate:DATA:ALL?
#     gets all traces (irrespective of channel) form recall set (top tab grouping)
#     Includes both date and memory traces (at least some memory traces).
#     They are in trace number order. Complex numbers present as 2 consecutive numbers.
#     Combining 2 channels with different number of points is ok but cannot be reshaped
#     into a multi-dimensional array.
#   CALCulate:DATA:DALL?
#     same as above except only includes data (not memory)
#   CALCulate<Ch>:DATA:CALL
#     get all traces from channel, even if not being displayed (but included in calibrated measurement)
#     Does not include memory traces. Only options sdate and fisdata are available
#   CALCulate<Ch>:DATA:CALL:CATalog?
#     List traces included in previous
#   CALCulate<Ch>:DATA:CHANnel:ALL?
#     gets all traces of channel.
#     Includes both date and memory traces (at least some memory traces).
#        some memory trace are not included. Probably when more than one memory
#        from a trace was created, only one is downloaded. Which one?
#   CALCulate<Ch>:DATA:CHANnel:DALL?
#     same as above except only includes data (not memory)
#   CALCulate<Chn>:DATA?
#     download active trace of Chn
# Trace types (references to ZNB_ZNBT_UserManual_en_42.pdf):
#   FDATa:  formated trace data (can be 1 value or 2 value per stimulus). Cooked data
#            location 3 in Figure 4.1 of manual (Data Flow), page 90
#   SDATa:  unformated trace data (always complex value), Includes edelay but not trace math
#            location 2 in Figure 4.1 of manual (Data Flow), page 90
#   MDATa:  unformated trace data (always complex value), Includes edelay but and trace math
#            location 3 in Figure 4.1 of manual (Data Flow), page 90
#      These are available ont for CALCulate<Chn>:DATA?
#   NCData: unformated trace data (always complex value), Only includes factory calibration
#   UCData: unformated trace data (always complex value), Uncalibrated data. Only for wave quantity or ratio.
#      This is only for CALCulate<Ch>:DATA:CALL
#   FSIData: unformated trace data (always complex value), Only calibrated, does not include edelay
#            location 1 in Figure 4.1 of manual (Data Flow), page 90
