# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2018-2018  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from __future__ import absolute_import

import numpy as np
import scipy
import os.path
import time
import string

from ..instruments_base import visaInstrument, visaInstrumentAsync,\
                            scpiDevice, MemoryDevice, ReadvalDev, BaseDevice,\
                            ChoiceMultiple, Choice_bool_OnOff, _repr_or_string,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDev, ChoiceDevSwitch, ChoiceIndex,\
                            ChoiceSimpleMap, decode_float32, decode_int8, decode_int16, _decode_block_base,\
                            decode_float64, quoted_string, _fromstr_helper, ProxyMethod
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias


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
        print "Other gen should be at %r Hz, %r dBm"%(freq, power)

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
            print 'Only useful for SGU devices.'

    def reset_tripped_state(self):
        self.write('OUTPut:PROTection:CLEar')

    def conf_traits(self):
        """ For SGU only: Return a dictionnary of information about all the frequency bands """
        if self._is_SGS:
            print 'Only useful for SGU devices.'
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

    def _apply_helper(self, val, dev_obj):
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
        clean = lambda s: map(qs, split(s))
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
        clean = lambda s: map(qs, split(s))
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
            print 'Only useful for SGS devices.'
            return
        connected = _fromstr_helper(self.ask('EXTension:REMote:STATe?'), bool)
        name = self.ask('EXTension:INSTruments:NAME?')
        # EXTension:INSTruments:SCAN ...
        interface = self.ask('EXTension:INSTruments:REMote:CHANnel?')
        lan_addr = self.ask('EXTension:INSTruments:REMote:LAN:NAME?')
        serial_no = self.ask('EXTension:INSTruments:REMote:SERial?')
        state_busy = _fromstr_helper(self.ask('EXTension:BUSY?'), bool)
        return dict(connected=connected, interface=interface, lan_addr=lan_addr, serial_no=serial_no, state_busy=state_busy)

    def extension_write(self, command, ch=1):
        if not self._is_SGS:
            print 'Only useful for SGS devices.'
            return
        self.write('EXTension:SELect %i'%ch)
        self.write('EXTension:SEND "%s"'%command)
    def extension_ask(self, query='', ch=1):
        """ Only useful for SGS device.
            The query is transmitted to the extension.
            you should include the question mark in the query.
            If you think the buffer are unsynchronized, you can just
            do a read with no query.
            Useful queries: SYSTem:ERRor, SYSTem:SERRor
        """
        if not self._is_SGS:
            print 'Only useful for SGS devices.'
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

    def _current_config(self, dev_obj=None, options={}):
        opts = ['opt=%s'%self.available_options]
        opts += self._conf_helper('timebase_ful_range', 'timebase_pos_offset', 'timebase_reference_pos_percent')
        opts += self._conf_helper('acquire_npoints', 'acquire_resolution', 'acquire_adc_sample_rate', 'sample_rate', 'sample_rate_real',
                                  'acquire_mode', 'acquire_interpolate_method', 'acquire_count', 'acquire_segment_en',
                                  'acquire_restart_mode', 'acquire_restart_time', 'acquire_restart_wfms_count')
        opts += self._conf_helper('channel_multiple_waveforms_en', 'channel_coupling_en')

        def reorg(opts):
            first = True
            date_all = []
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
            wf_range =  range(1, 4) if self.channel_multiple_waveforms_en.get() else [1]
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
        date = map(int, date.split(':'))
        hrmn, sec, uni = time_str.split(' ')
        hr, mn = map(int, hrmn.split(':'))
        sec, ns = map(float, sec.replace('.', '').split(','))
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
        wf_rg = range(1,4) if self.channel_multiple_waveforms_en.get() else [1]
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
        ch = map(lambda c: allowed_map.get(c, c), ch)
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
        """
        self.set_format(format)
        ch = self._fetch_ch_helper(ch)
        ret = []
        first = True
        cur_ch = self.current_channel.get()
        cur_wf = self.current_channel_waveform.get()
        for c in ch:
            cch = int(c[1])
            cwf = int(c[3])
            if history is not None:
                self.waveform_history_en.set(True)
                self.waveform_history_index.set(history, ch=cch, wf=cwf)
            header = self.waveform_data_header.get(ch=cch, wf=cwf)
            if (not raw) and xaxis and first:
                # this has been tested with 'EXPort:WAVeform:INCXvalues ON'
                ret = [ np.linspace(header.x_start, header.x_stop, header.n_sample, endpoint=False) ]
                first = False
            data = self.waveform_data.get()
            if raw or format in ['ascii', 'real']:
                y = data
            else:
                gain = self.input_full_range.get()
                offset_pos = self.input_position_div.get()*gain/10.
                if format == 'int16':
                    gain /=  253*256.
                else:
                    gain /=  253
                offset = self.input_offset.get()
                y = data*gain + offset - offset_pos
            ret.append(y)
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
                #print 'obtaining proper header'
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

        self.roll_auto_en = scpiDevice('TIMebase:ROLL:ENABle', choices=ChoiceSimpleMap(dict(AUTO=True, OFF=False), filter=string.upper))
        self.roll_auto_time = scpiDevice('TIMebase:ROLL:MTIMe', str_type=float, setget=True, auto_min_max=True)
        self.roll_is_active = scpiDevice(getstr='TIMebase:ROLL:STATe?', str_type=bool)

        self.current_measurement = MemoryDevice(initval=1, choices=range(1,9))
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
