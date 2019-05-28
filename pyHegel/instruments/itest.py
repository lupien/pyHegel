# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2011-2018  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from ..instruments_base import visaInstrument, visaInstrumentAsync, BaseInstrument,\
                            scpiDevice, MemoryDevice, Dict_SubDevice, ReadvalDev,\
                            ChoiceBase, ChoiceMultiple, ChoiceMultipleDep, ChoiceSimpleMap,\
                            ChoiceStrings, ChoiceIndex, ChoiceLimits, _general_check,\
                            make_choice_list, _tostr_helper, _fromstr_helper, ProxyMethod,\
                            decode_float64, quoted_string, scaled_float, visa_wrap, locked_calling,\
                            wait, release_lock_context, mainStatusLine, resource_info

from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

import time

import math

#######################################################
##    iTest Bilt system 12V 200mA remote source module BE2102
#######################################################

# Observations:
#  when turning the output on:
#   device ramps voltage from 0V to target
#  when turning output off, relays open and voltage drops to 0 immediately
#    The relay actually shorts the ouput to ground.
#  Need to have output off to change range/filter
#  With output off there is not ramping.
#  Ramping with fast, it changes the voltage every 1 ms, with slow it is every 2ms
#   It takes a few smaller steps when getting close to the target value. The first few steps are also
#    a little smaller
#   Even for single steps mode (trig 2)  it does a few steps to round the transition
#   slow hardware filter seems to have T(10-90%) of 1.5 ms  (single step; 6ms including all internal steps)
#   fast hardware filter seems to have T(10-90%) of 120 us (single step)

#  Turn off instruments with output on can produce a large glitch on output.
#  It produces one on power on also.

#  The remote sma grounds are all the same. They float with respect to the mainframe.
#  They seem to be the same as the remote box also.

#  When on remote sense off, the remote connection (SMA) are open (no signal)
#  Even with remote sense True, if output_en is False, meas_out does not see the signal
#   on the connectors. It reads 0. (There are many cmos switches. Only one relay for the output.)
#  The input impedance on the remote sense connectors seems to be >50 MOhm most of the time.

class range_type(object):
    def __call__(self, input_str):
        # the string is something like 1.2,1 or  12,2 (range in volt, range index)
        return float(input_str.split(',')[0])
    def tostr(self, val):
        return '%f'%val

class Choice_float_extra(ChoiceLimits):
    def __init__(self, others, min=None, max=None, str_type=float):
        """ others are a dictionary of special input values (strings) to pyHegel return values
        """
        self.others = others
        super(Choice_float_extra, self).__init__(min, max, str_type)
    def __call__(self, input_str):
        if input_str in self.others:
            return self.others[input_str]
        return super(Choice_float_extra, self).__call__(input_str)
    def tostr(self, val):
        if val in self.others.values():
            return [k for k,v in self.others.items() if v==val][0]
        return super(Choice_float_extra, self).tostr(val)
    def __repr__(self):
        extra = ' Also can use one of %s'%self.others.values()
        return super(Choice_float_extra, self).__repr__() + extra
    def __contains__(self, val):
        if val in self.others.values():
            return True
        return super(Choice_float_extra, self).__contains__(val)


@register_instrument('ITEST', '2102')
#@register_instrument('ITEST', '2102', 'firmware_version???')
class iTest_be2102(visaInstrument):
    """
    Load with slot set to the module slot (1-13 or 1-5).
    Important devices:
        range_auto_en
        range
        level
        slope
        filter_fast_en
        output_en
        meas_out
    Useful methods:
        idn_all
        config_addresses
        config_calibration
        trig
    TCP address format:
        TCPIP::192.168.150.112::5025::SOCKET
    """
    def __init__(self, visa_addr, slot, *args, **kwargs):
        self._slot = slot
        if slot<1 or slot>13:
            raise ValueError('Slot needs to be a value within 1-13 (or 1-5).')
        self._pre = 'i%i'%self._slot # full command name is: Inst
        kwargs['write_termination'] = '\n'
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type != visa_wrap.constants.InterfaceType.gpib:
            # Needed for all but gpib.
            # serial behaves likes this anyway (because VI_ATTR_ASRL_END_IN attribute is set
            #   to use the END_TERMCHAR which is \n)
            kwargs['read_termination'] = '\n'
        kwargs['keep_alive'] = 'auto'
        kwargs['keep_alive_time'] = 15*60 # 15 min. The instrument seems to timeout after 25 min when using a socket
        super(iTest_be2102, self).__init__(visa_addr, *args, **kwargs)

    def idn_remote(self):
        # here it is something like:
        #   2102,"ITEST BR2102C/HEAD 12V 200mA DC-SOURCE/SN03-018 LC1830 VL235"
        return self.ask(self._pre+';REMOte:idn?')
    def idn_slots(self):
        ret = self.ask('Inst:List?').split(';')
        ret = [v.split(',') for v in ret]
        return [(int(v[0]), v[1]) for v in ret]
    def idn_system(self):
        # here it is something like:
        #   "VM 4.6.04 ARM I"
        return self.ask('SYSTem:VERSion?')
    def idn_local(self):
        # here it is something like:
        #  module reference, description, SN Serial number, LCcalibration date, DC date code, VL software review
        #   2102,"ITEST BE2102C/REMOTE 12V 200mA DC-SOURCE/SN03-012 VL438"
        return self.ask(self._pre+';*idn?')
    def idn(self):
        return dict(local=self.idn_local(), remote=self.idn_remote(), system=self.idn_system(), slots=self.idn_slots())
    def idn_split(self):
        #   2102,"ITEST BE2102C/REMOTE 12V 200mA DC-SOURCE/SN03-012 VL438"
        idn = self.idn()['local']
        parts_idn = idn.split(',', 2)
        pp = parts_idn[1].strip('"').split('/')
        vm = pp[0].split(' ')
        sf = pp[2].split(' ')
        return dict(vendor=vm[0], model=parts_idn[0], serial=sf[0], firmware=sf[-1])

    def trig(self):
        self.write(self._pre+'TRIGger:IN:INITiate')

    def alarm_clear(self):
        self.write(self._pre+'LIM:CLEar')

    def sync_time(self, sync=False):
        """ Sends the computer time to the instrument, when sync is True
            Otherwise just reads and display the current time
        """
        if sync:
            lt = time.localtime()
            # jj,mm,aa,h,mm,ss
            self.write('SYSTem:TIMe %i,%i,%i,%i,%i,%i'%(lt[2], lt[1], lt[0]-2000, lt[3], lt[4], lt[5]))
        ret = self.ask('SYSTem:TIMe?')
        jj, mm, aa, hh, m, ss = [ int(s) for s in ret.split(',')]
        return '%i-%02i-%02i %02i:%02i:%02i'%(aa+2000, mm, jj, hh, m, ss)

#    def disable_over_voltage_protection(self):
#        self.write('SYSTem : OVERPROT off')

    def config_addresses(self, serial_id=None, serial_baud=None, gpib=None, tcp_addr=None, tcp_route=None, tcp_mask=None):
        """ Always returns a dictionnary containing all the settings.
            Can also change the various values.
            Not that tcp values should be given as a string with 4 numbers separated by dots, like:
                  '1.2.3.4'
        """
        # TODO: SYSTem:ETHernet:ROUTe? does not work
        if serial_id is not None:
            if serial_id<=0 or serial_id>=0xff:
                raise ValueError(self.perror('serial_id should be between 1 and 254 (0xfe)'))
            self.write('SYSTem:SERial:ID %x'%serial_id)
        if serial_baud is not None:
            if serial_baud not in [19200, 38400, 56000, 125, 208]:
                raise ValueError(self.perror('serial_baud should be one of 19200, 38400, 56000, 125, 208 (125 and 208 are 125k and 208k)'))
            self.write('SYSTem:SERial:BAUD %i'%serial_baud)
        if gpib is not None:
            if gpib<=0 or gpib>=31:
                raise ValueError(self.perror('gpib should be between in the range 1-30'))
            self.write('SYSTem:GPIB:ADDRess %i'%gpib)
        if tcp_addr is not None:
            self.write('SYSTem:ETHernet:ADDRess %s'%tcp_addr.replace('.', ','))
        if tcp_mask is not None:
            self.write('SYSTem:ETHernet:MASK %s'%tcp_mask.replace('.', ','))
        if tcp_route is not None:
            self.write('SYSTem:ETHernet:ROUT %s'%tcp_route.replace('.', ','))
        # in current firmware VL438, LC1830 VL235 ROUTe does not work, only ROUT
        result = self.ask(':SYSTem:SERial:ID?; BAUD?; :SYSTem:GPIB:ADDRess?; :SYSTem:ETHernet:ADDRess?; MASK?; MAC?; ROUT?')
        result_blocks = result.split(';')
        res_dict = {}
        res_dict['serial_id'] = int(result_blocks[0], 16)
        res_dict['serial_baud'] = int(result_blocks[1])
        res_dict['gpib'] = int(result_blocks[2])
        res_dict['tcp_addr'] = result_blocks[3].replace(',', '.')
        res_dict['tcp_mask'] = result_blocks[4].replace(',', '.')
        res_dict['tcp_mac'] = ':'.join(['%02X'%int(n, 16) for n in result_blocks[5].split(',')])
        res_dict['tcp_route'] = result_blocks[6].replace(',', '.')
        return res_dict

    def config_calibration(self, gain1=None, offset1=None, gain2=None, offset2=None):
        """ Always returns a dictionnary containing all the settings.
            Can also change the various values.
        """
        pre = self._pre + ';'
        if gain1 is not None:
            self.write(pre+'CALibration:GAIN 1,%r'%gain1)
        if offset1 is not None:
            self.write(pre+'CALibration:OFFset 1,%r'%offset1)
        if gain2 is not None:
            self.write(pre+'CALibration:GAIN 2,%r'%gain2)
        if offset2 is not None:
            self.write(pre+'CALibration:OFFset 2,%r'%offset2)
        result = self.ask(pre+'CALibration:GAIN1?; OFFset1?; GAIN2?; OFFset2?')
        return dict(zip(['gain1', 'offset1', 'gain2', 'offset2'], result.split(';')))

    def _extra_check_output_en(self, val, dev_obj):
        if self.output_en.getcache():
            raise RuntimeError(dev_obj.perror('dev cannot be changed while output is enabled.'))

    def _extra_check_level(self, val, dev_obj):
        #max_volt = 12
        max_volt = max(self.range.choices)
        curr_range = self.range.getcache()
        auto_range = self.range_auto_en.getcache()
        output_en = self.output_en.getcache()
        rg_min, rg_max = -curr_range, +curr_range
        if (not output_en) and auto_range:
            rg_min, rg_max = -max_volt, max_volt
        dev_obj._general_check(val, min=rg_min, max=rg_max)

    def _conf_helper(self, *devnames, **kwarg):
        ret = super(iTest_be2102, self)._conf_helper(*devnames, **kwarg)
        no_default, add_to = self._conf_helper_cache
        if not no_default:
            add_to(ret, 'slot="%s"'%self._slot)
        return ret

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        base = self._conf_helper('output_en', 'level', 'range', 'range_auto_en', 'slope', 'filter_fast_en',
                                 'remote_sense_en', 'saturation_pos', 'saturation_neg', 'temp_ready_status',
                                 'ready_treshold', 'ready_inv_polarity_en', 'alarm_status', 'delay_start', 'delay_stop')
        trig_mode = self.trigger_mode.getcache()
        if trig_mode == 'OFF':
            base += self._conf_helper('trigger_mode')
        elif trig_mode == 'TRIG':
            base += self._conf_helper('trigger_mode', 'trigger_delay')
        elif trig_mode == 'STAIR':
            base += self._conf_helper('trigger_mode', 'trigger_delay', 'step_amplitude', 'step_width')
        else:
            base += self._conf_helper('trigger_mode', 'trigger_delay', 'step_amplitude')
        return base + self._conf_helper('module_name', 'module_channels_indep',
                                 'system_power', 'system_power_max', 'system_name', options)

    #def _output_en_getdev(self):
    #    return _fromstr_helper(self.ask(self._pre+';OUTPut?'), bool)
    #def _output_en_setdev(self, val):
    #    if val and self.range_auto_en.getcache():
    #        # This is to update the cache so level check works correctly
    #        self.range.get()
    #    self.write((self._pre+';OUTPut %s'%_tostr_helper(val, bool)))
    def _output_en_extraset(self, val, dev_obj):
        if val and self.range_auto_en.getcache():
            # This is to update the cache so level check works correctly
            self.range.get()
        if self.output_en.get() and not val:
            # we go from on to off, ramp down
            self.level.set(0)
            self._ramp_wait()
    def _range_auto_en_extraset(self, val, dev_obj):
        # This is to update the cache so level check works correctly
        self.range.get()

    def _ramp_wait(self):
        # can only do polling
        if not self.output_en.get():
            # ramping_fraction only works with output enabled
            return
        prev_f = -1
        with release_lock_context(self):
            with mainStatusLine.new(priority=10, timed=True) as progress:
                while True:
                    f = self.ramping_fraction.get()
                    if f == 1 or math.isnan(f):
                        # f is nan when asking for a ramp to the same value as before (i.e.
                        #  being at -1 and going to -1), except for 0.
                        break
                    if f == 0 == prev_f:
                        # f stays at 0 when output is off or asking to go to 0 when already at 0
                        break
                    prev_f = f
                    wait(.05)
                    progress('ramp progress: %.3f'%f)

    def _ramp_setdev(self, val):
        prev_val = self.level.get()
        self.level.set(val)
        if prev_val != val:
            self._ramp_wait()
    def _ramp_getdev(self):
        return self.level.get()
    def _ramp_checkdev(self, val):
        self.level.check(val)

    def _create_devs(self):
        pre = self._pre + ';'
        # No need for setget. The instruments returns the set value with 8 significant digits
        self.module_name = scpiDevice(pre+'NAMe', str_type=quoted_string())
        self.module_channels_indep = scpiDevice(getstr=pre+'IMC?', str_type=bool)
        extra_check_level = ProxyMethod(self._extra_check_level)
        self.level = scpiDevice(pre+'VOLTage', str_type=float, extra_check_func=extra_check_level)

        range_list = map(float, self.ask(pre+'VOLTage:RANGe:LIST?').split(','))
        extra_check_output_en = ProxyMethod(self._extra_check_output_en)
        range_doc = """
        The range can only be changed when the output is disabled.
        Changing to a smaller range than the current level will reset the level to 0V (pyHegel cache not updated).
        """
        self.range = scpiDevice(pre+'VOLTage:RANGe', str_type=range_type(), choices=range_list, doc=range_doc, extra_check_func=extra_check_output_en)
        self._devwrap('ramp')
        range_auto_en_extra_set = ProxyMethod(self._range_auto_en_extraset)
        self.range_auto_en = scpiDevice(pre+'VOLTage:RANGe:AUTO', str_type=bool, extra_set_func=range_auto_en_extra_set)
        self.slope =  scpiDevice(pre+'VOLTage:SLOPe', str_type=scaled_float(1e3), doc='in V/s', min=1.2e-3, max=1e3)
        self.remote_sense_en =  scpiDevice(pre+'VOLTage:REMote', str_type=bool)
        # STATE seems to do the same as output but has more options: ),0,OFF ;1 ON ; 2 WARNING ; 3,ALARm
        #self.output_en =  scpiDevice(pre+'OUTPut', str_type=bool)
        #self._devwrap('output_en')
        output_en_extra_set = ProxyMethod(self._output_en_extraset)
        self.output_en = scpiDevice(pre+'OUTPut', str_type=bool, extra_set_func=output_en_extra_set)
        self.filter_fast_en = scpiDevice(pre+'VOLTage:FILter', str_type=bool, extra_check_func=extra_check_output_en, doc='slow is 100ms, fast is 10ms')
        self.temp_ready_status = scpiDevice(getstr=pre+'TEMPerature:STATus?', str_type=bool)
        self.meas_out = scpiDevice(getstr=pre+'MEASure:VOLTage?', str_type=float)
        self.meas_out_minmax = scpiDevice(getstr=pre+'MMX:VOLTage?', str_type=decode_float64, doc='get the minimum/maximum measurements since the last call', multi=['min', 'max'])
        self.ramping_fraction = scpiDevice(getstr=pre+'VOLTage:STATus?', str_type=float)
        self.saturation_pos = scpiDevice(pre+'VOLTage:SAT:POS', choices=Choice_float_extra(dict(MAX=999), min=0, max=12), doc='999 is used to turn of checking')
        self.saturation_neg = scpiDevice(pre+'VOLTage:SAT:NEG', choices=Choice_float_extra(dict(MIN=-999), min=-12, max=0), doc='-999 is used to turn of checking')
        self.delay_start = scpiDevice(pre+'STARt:DELay', str_type=float, min=10e-3, max=60)
        self.delay_stop = scpiDevice(pre+'STOP:DELay', str_type=float, min=0, max=50e-3)
        self.trigger_mode = scpiDevice(pre+'TRIGger:IN', choices=ChoiceIndex(['OFF', 'TRIG', 'STAIR', 'STEP', 'AUTO']))
        self.trigger_delay = scpiDevice(pre+'TRIGger:IN:DELay', str_type=float, min=0, max=60)
        self.step_amplitude = scpiDevice(pre+'VOLTage:STep:AMPLitude', str_type=float, min=1.2e-6, max=12)
        self.step_width = scpiDevice(pre+'VOLTage:STep:WIDth', str_type=float, min=5e-3, max=60e3, doc='Used for trig mode STEP')

        self.ready_reached = scpiDevice(getstr=pre+'TRIGger:READY?', str_type=bool)
        self.ready_treshold =  scpiDevice(pre+'TRIGger:READY:AMPLitude', str_type=float, min=1.2e-6, max=12)
        self.ready_inv_polarity_en =  scpiDevice(pre+'TRIGger:READY:POLarity', str_type=bool)

        alarm_status_ch = ChoiceIndex({0:'OK', 5:'Halt', 6:'Syst ', 7:'Temperature fail', 8:'Over'})
        self.alarm_status = scpiDevice(getstr=pre+'LIM:FAIL?', choices=alarm_status_ch,
                                       doc='You will need to use the alarm_clear method if the result is not OK before turning the output back on.')
        fkey_doc = """
        You can program the front panel F1/F2 keys (if present).
        A program example is (To ramp all voltages to 0V):
            "i1;volt 0; i2;volt 0; i3;volt 0; i4;volt 0"
        """
        self._program_f1_key = scpiDevice('SYSTem:KEY:DEF 1,{val}', 'SYSTem:KEY:DEF? 1', str_type=quoted_string(), doc=fkey_doc)
        self._program_f2_key = scpiDevice('SYSTem:KEY:DEF 1,{val}', 'SYSTem:KEY:DEF? 1', str_type=quoted_string(), doc=fkey_doc)
        self.system_power = scpiDevice(getstr='SYSTem:POWer?', choices=ChoiceMultiple(['volt_pos_25', 'power_pos_25_pct', 'volt_neg_25', 'power_neg_25_pct'], float))
        self.system_power_max = scpiDevice(getstr='SYSTem:POWer:MAX?', choices=ChoiceMultiple(['max_power_pos_25', 'max_power_neg_25'], float))
        self.system_name = scpiDevice('SYSTem:NAME', str_type=quoted_string())
        #self._devwrap('level')
        self.alias = self.level
        super(type(self),self)._create_devs()



#######################################################
##    iTest Bilt system 12V 15mA 4 ch source module BE2142
#######################################################

@register_instrument('ITEST', '2141')
@register_instrument('ITEST', '2142')
#@register_instrument('ITEST', '214x', 'firmware_version???')
class iTest_be214x(visaInstrument):
    """
    Load with slot set to the module slot (1-13 or 1-5).
    Important devices:
        range_auto_en
        range
        level
        slope
        output_en
        meas_out
    Useful methods:
        idn_all
        config_addresses
        trig
    TCP address format:
        TCPIP::192.168.150.145::5025::SOCKET
    """
    def __init__(self, visa_addr, slot, *args, **kwargs):
        self._slot = slot
        if slot<1 or slot>13:
            raise ValueError('Slot needs to be a value within 1-13 (or 1-5).')
        self._pre = 'i%i'%self._slot # full command name is: Inst
        kwargs['write_termination'] = '\n'
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type != visa_wrap.constants.InterfaceType.gpib:
            # Needed for all but gpib.
            # serial behaves likes this anyway (because VI_ATTR_ASRL_END_IN attribute is set
            #   to use the END_TERMCHAR which is \n)
            kwargs['read_termination'] = '\n'
        kwargs['keep_alive'] = 'auto'
        kwargs['keep_alive_time'] = 15*60 # 15 min. The instrument seems to timeout after 25 min when using a socket
        super(iTest_be214x, self).__init__(visa_addr, *args, **kwargs)

    def idn_remote(self):
        # here it is something like:
        #   2102,"ITEST BR2102C/HEAD 12V 200mA DC-SOURCE/SN03-018 LC1830 VL235"
        return self.ask(self._pre+';REMOte:idn?')
    def idn_slots(self):
        ret = self.ask('Inst:List?').split(';')
        ret = [v.split(',') for v in ret]
        return [(int(v[0]), v[1]) for v in ret]
    def idn_system(self):
        # here it is something like:
        #   "VM 4.6.04 ARM I"
        return self.ask('SYSTem:VERSion?')
    def idn_local(self):
        # here it is something like:
        #  module reference, description, SN Serial number, LCcalibration date, DC date code, VL software review
        #   2102,"ITEST BE2102C/REMOTE 12V 200mA DC-SOURCE/SN03-012 VL438"
        return self.ask(self._pre+';*idn?')
    def idn(self):
        return dict(local=self.idn_local(), remote=self.idn_remote(), system=self.idn_system(), slots=self.idn_slots())
    def idn_split(self):
        #   2102,"ITEST BE2102C/REMOTE 12V 200mA DC-SOURCE/SN03-012 VL438"
        idn = self.idn()['local']
        parts_idn = idn.split(',', 2)
        pp = parts_idn[1].strip('"').split('/')
        vm = pp[0].split(' ')
        sf = pp[2].split(' ')
        return dict(vendor=vm[0], model=parts_idn[0], serial=sf[0], firmware=sf[-1])

    def trig_all(self):
        self.write(self._pre+'TRIGger:INput:INITiate:ALL')

    def trig(self, ch=None):
        if ch is not None:
            self.current_channel.set(ch)
        ch = self.current_channel.get()
        self.write(self._pre+'C%i;TRIGger:INput:INITiate'%ch)

    def alarm_clear(self, ch=None):
        if ch is not None:
            self.current_channel.set(ch)
        ch = self.current_channel.get()
        self.write(self._pre+'C%i;LIM:CLEar'%ch)

    def sync_time(self, sync=False):
        """ Sends the computer time to the instrument, when sync is True
            Otherwise just reads and display the current time
        """
        if sync:
            lt = time.localtime()
            # jj,mm,aa,h,mm,ss
            self.write('SYSTem:TIMe %i,%i,%i,%i,%i,%i'%(lt[2], lt[1], lt[0]-2000, lt[3], lt[4], lt[5]))
        ret = self.ask('SYSTem:TIMe?')
        jj, mm, aa, hh, m, ss = [ int(s) for s in ret.split(',')]
        return '%i-%02i-%02i %02i:%02i:%02i'%(aa+2000, mm, jj, hh, m, ss)

#    def disable_over_voltage_protection(self):
#        self.write('SYSTem : OVERPROT off')

    def config_addresses(self, serial_id=None, serial_baud=None, gpib=None, tcp_addr=None, tcp_route=None, tcp_mask=None):
        """ Always returns a dictionnary containing all the settings.
            Can also change the various values.
            Not that tcp values should be given as a string with 4 numbers separated by dots, like:
                  '1.2.3.4'
        """
        # TODO: SYSTem:ETHernet:ROUTe? does not work
        if serial_id is not None:
            if serial_id<=0 or serial_id>=0xff:
                raise ValueError(self.perror('serial_id should be between 1 and 254 (0xfe)'))
            self.write('SYSTem:SERial:ID %x'%serial_id)
        if serial_baud is not None:
            if serial_baud not in [19200, 38400, 56000, 125, 208]:
                raise ValueError(self.perror('serial_baud should be one of 19200, 38400, 56000, 125, 208 (125 and 208 are 125k and 208k)'))
            self.write('SYSTem:SERial:BAUD %i'%serial_baud)
        if gpib is not None:
            if gpib<=0 or gpib>=31:
                raise ValueError(self.perror('gpib should be between in the range 1-30'))
            self.write('SYSTem:GPIB:ADDRess %i'%gpib)
        if tcp_addr is not None:
            self.write('SYSTem:ETHernet:ADDRess %s'%tcp_addr.replace('.', ','))
        if tcp_mask is not None:
            self.write('SYSTem:ETHernet:MASK %s'%tcp_mask.replace('.', ','))
        if tcp_route is not None:
            self.write('SYSTem:ETHernet:ROUT %s'%tcp_route.replace('.', ','))
        # in current firmware VL438, LC1830 VL235 ROUTe does not work, only ROUT
        result = self.ask(':SYSTem:SERial:ID?; BAUD?; :SYSTem:GPIB:ADDRess?; :SYSTem:ETHernet:ADDRess?; MASK?; MAC?; ROUT?')
        result_blocks = result.split(';')
        res_dict = {}
        res_dict['serial_id'] = int(result_blocks[0], 16)
        res_dict['serial_baud'] = int(result_blocks[1])
        res_dict['gpib'] = int(result_blocks[2])
        res_dict['tcp_addr'] = result_blocks[3].replace(',', '.')
        res_dict['tcp_mask'] = result_blocks[4].replace(',', '.')
        res_dict['tcp_mac'] = ':'.join(['%02X'%int(n, 16) for n in result_blocks[5].split(',')])
        res_dict['tcp_route'] = result_blocks[6].replace(',', '.')
        return res_dict

    def _extra_check_output_en(self, val, dev_obj):
        if self.output_en.getcache():
            raise RuntimeError(dev_obj.perror('dev cannot be changed while output is enabled.'))

    def _extra_check_level(self, val, dev_obj):
        #max_volt = 12
        max_volt = max(self.range.choices)
        curr_range = self.range.getcache()
        auto_range = self.range_auto_en.getcache()
        output_en = self.output_en.getcache()
        rg_min, rg_max = -curr_range, +curr_range
        if (not output_en) and auto_range:
            rg_min, rg_max = -max_volt, max_volt
        dev_obj._general_check(val, min=rg_min, max=rg_max)

    def _conf_helper(self, *devnames, **kwarg):
        ret = super(iTest_be214x, self)._conf_helper(*devnames, **kwarg)
        no_default, add_to = self._conf_helper_cache
        if not no_default:
            add_to(ret, 'slot="%s"'%self._slot)
        return ret

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        orig_ch = self.current_channel.get()
        base = []
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
        for ch in range(1, 4+1):
            self.current_channel.set(ch)
            base1 = self._conf_helper('output_en', 'level', 'range', 'range_auto_en', 'slope',
                                 'saturation_pos', 'saturation_neg',
                                 'ready_treshold', 'alarm_status', 'delay_start', 'delay_stop', 'halt_en')
            base1 += self._conf_helper('trigger_mode', 'trigger_edge_falling_en', 'trigger_delay', 'step_amplitude', 'step_width')
            if hasattr(self, 'current_limit_en'):
                base1 += self._conf_helper('current_limit_en', 'current_limit_lower', 'current_limit_upper', 'current_limit_delay')
            base.append(base1)

        self.current_channel.set(orig_ch)
        base_conf = reorg(base)
        return base_conf + self._conf_helper('current_channel', 'trigger_out_inv_polarity_en', 'module_name', 'module_channels_indep',
                                 'system_power', 'system_power_max', 'system_name', options)

    #def _output_en_getdev(self):
    #    return _fromstr_helper(self.ask(self._pre+';OUTPut?'), bool)
    #def _output_en_setdev(self, val):
    #    if val and self.range_auto_en.getcache():
    #        # This is to update the cache so level check works correctly
    #        self.range.get()
    #    self.write((self._pre+';OUTPut %s'%_tostr_helper(val, bool)))
    def _output_en_extraset(self, val, dev_obj):
        if val and self.range_auto_en.getcache():
            # This is to update the cache so level check works correctly
            self.range.get()
        if self.output_en.get() and not val:
            # we go from on to off, ramp down
            self.level.set(0)
            self._ramp_wait()
    def _range_auto_en_extraset(self, val, dev_obj):
        # This is to update the cache so level check works correctly
        self.range.get()

    def _ramp_wait(self):
        # can only do polling
        if not self.output_en.get():
            # ramping_fraction only works with output enabled
            # otherwise status ramping_fraction always returns 0
            return
        # necessary wait because after set level and trig, sometimes ramping_fraction begins by returning 1.
        #  2 ms might be enough ...
        wait(.010)
        ch = self.current_channel.get()
        with release_lock_context(self):
            with mainStatusLine.new(priority=10, timed=True) as progress:
                while True:
                    f = self.ramping_fraction.get(ch=ch)
                    if f == 1: # ramp finished
                        break
                    wait(.05)
                    progress('ramp progress: %.3f'%f)

    def _ramp_setdev(self, val, ch=None, trig=True):
        prev_val = self.level.get(ch=ch)
        self.level.set(val, trig=trig)
        if prev_val != val:
            self._ramp_wait()
    def _ramp_getdev(self, ch=None):
        return self.level.get(ch=ch)
    def _ramp_checkdev(self, val, ch=None, trig=True):
        self.level.check(val, ch=ch)

    def _extra_set_level(self, val, dev_obj, **kwargs):
        if dev_obj == self.output_en:
            if not val:
                # ramp down will trigger if necessary
                return
            delay = self.delay_start.get()
            wait(delay + 0.05) # needs to wait before trig after output_en True
        if kwargs.pop('trig', False):
            self.trig()
        if dev_obj == self.output_en:
            self._ramp_wait()

    def _create_devs(self):
        pre = self._pre + ';'
        pre_ch = self._pre + ';C{ch};' # the actual command is Channel
        model_name = self.ask(pre+'*idn?').split(',')[0]
        if len(model_name) != 4 or not model_name.startswith('214') or model_name[3] not in ['1', '2']:
            self.perror('Unable to detect a valid model_number (2141 or 2142). Will disable current reading.')
        enable_current = True if model_name[3] == '2' else False
        # Changing slot with i1 resets the selected channel to 1
        # so always set the channel after changing slot
        # Different tcp connection keep their own copy of slot/channel
        self.current_channel = MemoryDevice(1, choices=[1, 2, 3, 4])
        def devChannelOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            if len(arg):
                arg = list(arg)
                arg[0] = pre_ch + arg[0]
                if len(arg)>1:
                    arg[1] = pre_ch + arg[1]
            setstr = kwarg.pop('setstr', None)
            getstr = kwarg.pop('getstr', None)
            if setstr is not None:
                kwarg['setstr'] = pre_ch + setstr
            if getstr is not None:
                kwarg['getstr'] = pre_ch + getstr
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        # _decode_float64_avg is needed because count points are returned
        # No need for setget. The instruments returns the set value with 8 significant digits
        # But for time in ms which are stored in integers (they use scaled_float(1e-3)), do use setget.
        self.module_name = scpiDevice(pre+'NAMe', str_type=quoted_string())
        self.module_channels_indep = scpiDevice(getstr=pre+'IMC?', str_type=bool)
        extra_check_level = ProxyMethod(self._extra_check_level)
        extra_set_level = ProxyMethod(self._extra_set_level)
        self.level = devChannelOption('VOLTage', str_type=float, extra_check_func=extra_check_level,
                extra_set_after_func=extra_set_level,
                options=dict(trig=True), options_conv=dict(trig=lambda v,s:v))

        # Technically VOLTage:RANGe:LIST? is addressed to a specific channel, however they all return the same result (from email).
        #  email refers to Mathieu PANEL <m.panel@itest.fr>, Re: Fwd: problèmes avec BE2142, 2019-05-28
        range_list = map(float, self.ask(pre+'VOLTage:RANGe:LIST?').split(','))
        extra_check_output_en = ProxyMethod(self._extra_check_output_en)
        range_doc = """
        The range can only be changed when the output is disabled.
        Changing to a smaller range than the current level will reset the level to 0V (pyHegel cache not updated).
        """
        self.range = devChannelOption('VOLTage:RANGe', str_type=range_type(), choices=range_list, doc=range_doc, extra_check_func=extra_check_output_en)
        self._devwrap('ramp')
        range_auto_en_extra_set = ProxyMethod(self._range_auto_en_extraset)
        self.range_auto_en = devChannelOption('VOLTage:RANGe:AUTO', str_type=bool, extra_set_func=range_auto_en_extra_set)
        self.slope =  devChannelOption('VOLTage:SLOPe', str_type=scaled_float(1e3), doc='in V/s', min=1.2e-3, max=1e2)
        output_en_extra_set = ProxyMethod(self._output_en_extraset)
        self.output_en = devChannelOption('OUTPut', str_type=bool, extra_set_func=output_en_extra_set,
                extra_set_after_func=extra_set_level,
                options=dict(trig=True), options_conv=dict(trig=lambda v,s:v))
        self.meas_out_volt = devChannelOption(getstr='MEASure:VOLTage?', str_type=float)
        if enable_current:
            self.meas_out_current = devChannelOption(getstr='MEASure:CURRent?', str_type=float)
        self.meas_out_minmax = devChannelOption(getstr='MMX:VOLTage?', str_type=decode_float64, doc='get the minimum/maximum measurements since the last call', multi=['min', 'max'])
        self.ramping_fraction = devChannelOption(getstr='VOLTage:STATus?', str_type=float)
        self.saturation_pos = devChannelOption('VOLTage:SAT:POS', choices=Choice_float_extra(dict(MAX=999), min=0, max=12), doc='999 is used to turn of checking')
        self.saturation_neg = devChannelOption('VOLTage:SAT:NEG', choices=Choice_float_extra(dict(MIN=-999), min=-12, max=0), doc='-999 is used to turn of checking')
        self.delay_start = devChannelOption('STARt:DELay', str_type=scaled_float(1e-3), min=10e-3, max=60, setget=True)
        self.delay_stop = devChannelOption('STOP:DELay', str_type=scaled_float(1e-3), min=0, max=50e-3, setget=True)
        self.trigger_mode = devChannelOption('TRIGger:Input', choices=ChoiceIndex(['OFF', 'TRIG', 'STAIR', 'STEP', 'AUTO']), doc='OFF/TRIG are the same as EXP/RAMP in the manual')
        # Trigger source cannot be changed according to manual rev 1.5 (and email)
        #self.trigger_source = scpiDevice(pre+'TRIGger:Input:SOURce', choices=ChoiceIndex(['chassis', 'module', 'both']))
        self.trigger_delay = devChannelOption('TRIGger:INput:DELay', str_type=scaled_float(1e-3), min=0, max=60, setget=True)
        self.trigger_edge_falling_en = scpiDevice(pre+'TRIGger:INput:EDGE', str_type=bool)
        self.step_amplitude = devChannelOption('VOLTage:STep:AMPLitude', str_type=float, min=1.2e-6, max=12)
        self.step_width = devChannelOption('VOLTage:STep:WIDth', str_type=scaled_float(1e-3), min=5e-3, max=60, setget=True, doc='Used for trig mode STEP')

        self.ready_reached = devChannelOption(getstr='TRIGger:READY?', str_type=bool)
        self.ready_treshold =  devChannelOption('TRIGger:READY:AMPLitude', str_type=float, min=1.2e-6, max=1)
        self.trigger_out_inv_polarity_en =  scpiDevice(pre+'TRIGger:OUT:POLarity', str_type=bool, doc='This is for the output ttl (5V) signal')

        alarm_status_ch = ChoiceIndex({0:'OK', 3:'I_low_limit', 4:'I_high_limit', 11:'Halt', 12:'Syst ', 17:'Temperature fail', 18:'Over'})
        self.alarm_status = devChannelOption(getstr='LIMit:FAIL?', choices=alarm_status_ch,
                                       doc='You will need to use the alarm_clear method if the result is not OK before turning the output back on.')
        if enable_current:
            self.current_limit_en = devChannelOption('LIMit:STATe', str_type=bool)
            self.current_limit_upper = devChannelOption('LIMit:CURRent:UPPer', str_type=float)
            self.current_limit_lower = devChannelOption('LIMit:CURRent:LOWer', str_type=float)
            self.current_limit_delay = devChannelOption('LIMit:DELay', str_type=scaled_float(1e-3), min=0, max=60, setget=True)
        self.halt_en = devChannelOption('HALT:STATe', str_type=bool, doc="To be effective requires the use of the safety stop interlock (remove internal jumper).")
        fkey_doc = """
        You can program the front panel F1/F2 keys (if present).
        A program example is (To ramp all voltages to 0V):
            "i1;volt 0; i2;volt 0; i3;volt 0; i4;volt 0"
        """
        self._program_f1_key = scpiDevice('SYSTem:KEY:DEF 1,{val}', 'SYSTem:KEY:DEF? 1', str_type=quoted_string(), doc=fkey_doc)
        self._program_f2_key = scpiDevice('SYSTem:KEY:DEF 1,{val}', 'SYSTem:KEY:DEF? 1', str_type=quoted_string(), doc=fkey_doc)
        self.system_power = scpiDevice(getstr='SYSTem:POWer?', choices=ChoiceMultiple(['volt_pos_25', 'power_pos_25_pct', 'volt_neg_25', 'power_neg_25_pct'], float))
        self.system_power_max = scpiDevice(getstr='SYSTem:POWer:MAX?', choices=ChoiceMultiple(['max_power_pos_25', 'max_power_neg_25'], float))
        self.system_name = scpiDevice('SYSTem:NAME', str_type=quoted_string())
        #self._devwrap('level')
        self.alias = self.level
        super(type(self),self)._create_devs()

# observations:
#   OFF trigger_mode is a jump, not a ramp like for BE2102
# There is also an internal limit that turns off all 4 inputs if one goes above 20 mA (from email)

