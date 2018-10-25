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

from ..instruments_base import visaInstrument, visaInstrumentAsync,\
                            scpiDevice, MemoryDevice, ReadvalDev,\
                            ChoiceMultiple, Choice_bool_OnOff, _repr_or_string,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDev, ChoiceDevSwitch, ChoiceIndex,\
                            quoted_string, _fromstr_helper, ProxyMethod
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias


register_usb_name('Rohde & Schwarz', 0x0aad)

#######################################################
##    R&S SGMA generator
#######################################################
class apply_scpiDevice(scpiDevice):
    def __init__(self, apply_func, *args, **kwargs):
        """
        subdevice should probably be a proxy
        apply_func should probably be a proxy
        """
        super(apply_scpiDevice, self).__init__(*args, **kwargs)
        self._apply_func = apply_func
    def _setdev(self, val, **kwargs):
        super(apply_scpiDevice, self)._setdev(val, **kwargs)
        self._apply_func()

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

    def _apply_helper(self):
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
    def startup_complete(self):
        return _fromstr_helper(self.ask('SYSTem:STARtup:COMPlete?'), bool)
    def reset(self):
        """ All instrument settings are reset to their default values (except for network settings ...). """
        # I think all the 2 lines perform the same operation.
        # The manuals also mentions SOURce.PRESet but it does not seem to work.
        self.write('*RST')
        #self.write('SYSTem:PRESet')

    def _get_min_max(self, command):
        min = self.ask(command+'? min')
        max = self.ask(command+'? max')
        return min, max

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
                return apply_scpiDevice(apply_helper, *args, **kwargs)
            if self._override_extension:
                self.rem_opmode = scpiDevice('REMote:OPMode', choices=ChoiceStrings('EXTension', 'STDalone'))
            self.output_en_raw = scpiDevice('OUTPut', str_type=bool)
            self.LO_freq = scpiDevice(getstr='LOSCillator:FREQuency?', str_type=float)
            self.LO_power = scpiDevice(getstr='LOSCillator:POWer?', str_type=float)
            min, max = self._get_min_max('FREQuency')
            self.freq_request = scpiDevice('FREQuency', str_type=float, min=min, max=max, doc="See LO_freq and LO_power")
            self.power_level_dbm_raw = scpiDevice('POWer', str_type=float, min=-120, max=25)
        else:
            l_apply_scpiDevice = scpiDevice
            self.ref_output_signal = scpiDevice('CONNector:REFLo:OUTPut', choices=ChoiceStrings('REF', 'LO', 'OFF'))
            self.operation_mode = scpiDevice('OPMode', choices=ChoiceStrings('NORMal', 'BBBYpass'))
            self.LO_source = scpiDevice('LOSCillator:SOURce', choices=ChoiceStrings('INTernal', 'EXTernal'))

        self.output_en = l_apply_scpiDevice('OUTPut', str_type=bool)
        self.output_poweron = scpiDevice('OUTPut:PON', choices=ChoiceStrings('OFF', 'UNCHanged'))
        self.output_same_attenuator_min_dBm = scpiDevice('OUTPut:AFIXed:RANGe:LOWer', str_type=float)
        self.output_same_attenuator_max_dBm = scpiDevice('OUTPut:AFIXed:RANGe:UPPer', str_type=float)
        self.freq = l_apply_scpiDevice('FREQuency', str_type=float, min=1e6, max=40e9)
        self.power_mode = scpiDevice('POWer:LMODe', choices=ChoiceStrings('NORMal', 'LNOISe', 'LDIStortion'))
        self.power_characteristic = scpiDevice('POWer:SCHaracteristic', choices=ChoiceStrings('AUTO', 'UNINterrupted', 'CVSWr', 'USER', 'MONotone'), doc='CVSWr means Constant VSWR.')
        # TODO: handle proper min, max. POWer limits depend on POWER:offset
        #   for example I have -20,+25 for 0 offset and -10, 35 for 10 offset.
        #min, max = self._get_min_max('POWer') # These limits
        min, max = -120, 125
        self.power_level_dbm = l_apply_scpiDevice('POWer', str_type=float, min=min, max=max)
        min, max = self._get_min_max('POWer:POWer')
        self.power_level_no_offset_dbm = scpiDevice('POWer:POWer', str_type=float, min=min, max=max, doc='This bypasses the power offset')
        self.power_level_offset_db = scpiDevice('POWer:OFFSet', str_type=float, min=-100, max=100)
        self.power_level_limit_dbm = scpiDevice('POWer:LIMit', str_type=float, min=-300, max=30)
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

