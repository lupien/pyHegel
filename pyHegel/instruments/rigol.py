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
                            scpiDevice, MemoryDevice, ReadvalDev, BaseDevice,\
                            ChoiceMultiple, Choice_bool_OnOff, Choice_bool_YesNo, _repr_or_string,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDev, ChoiceDevSwitch, ChoiceIndex,\
                            ChoiceLimits, quoted_string, _fromstr_helper, ProxyMethod, decode_float64
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

register_usb_name('Rigol Technologies', 0x1AB1)

#######################################################
##    Rigol Programmable DC Power Supply DP831A
#######################################################

#@register_instrument('RIGOL TECHNOLOGIES', 'DP831A', '00.01.14')
@register_instrument('RIGOL TECHNOLOGIES', 'DP831A', usb_vendor_product=[0x1AB1, 0x0E11])
class rigol_power_dp831a(visaInstrument):
    """
    This is the driver for the RIGOL programmable DC power supply DP831A.
    Channels 1, 2, 3 are respectively the 8V/5A, +30V/2A and -30V/2A.
    Useful devices:
      voltage, current, output_en
    """
    def _current_config(self, dev_obj=None, options={}):
        chs = self.channel_en_list()
        opts = ['enabled_channels=%r'%chs ]
        cch = self.current_meas_channel.get()
        opt_c = []
        for c in [1, 2, 3]:
            self.current_channel.set(c)
            r = self._conf_helper('output_en', 'current', 'voltage', 'output_mode', 'voltage_protection_en', 'voltage_protection_level', 'voltage_protection_tripped', 'current_protection_en', 'current_protection_level', 'current_protection_tripped', 'output_track_en')
            opt_c.append(r)
        titles =  [ t.split('=', 1)[0] for t in opt_c[0] ]
        data = [ [o.split('=', 1)[1] for o in ol] for ol in opt_c]
        for i, t in enumerate(titles):
            d = '%s=[%s]'%(t, ','.join([data[j][i] for j in range(3)]))
            opts.append(d)
        opts += self._conf_helper('on_off_sync', 'over_temperature_protection_en' , 'track_mode')
        return opts + self._conf_helper(options)

    def _fetch_getformat(self, **kwarg):
        ch = kwarg.get('ch', None)
        select = kwarg.get('select', 'all')
        chs, select = self._fetch_helper(ch, select)
        multi = []
        for c in chs:
            multi.extend(['ch%i_'%c+s for s in select])
        fmt = self.fetch._format
        fmt.update(multi=multi)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_helper(self, ch, select):
        if ch is None:
            ch = self.channel_en_list()
        if not isinstance(ch, (list, tuple, np.ndarray)):
            ch = [ch]
        if len(ch)==0:
            raise RuntimeError(self.perror('No output are enabled/selected for fetch.'))
        if select == 'all':
            select = ['voltage', 'current', 'power']
        if not isinstance(select, (list, tuple, np.ndarray)):
            select = [select]
        for s in select:
            if s not in ['voltage', 'current', 'power']:
                raise ValueError(self.perror('Invalid option for select in fetch'))
        return ch, select
    def _fetch_getdev(self, ch=None, select='all'):
        """ ch can ne a single channel, or a list of channels to read.
                 by default reads all enabled channels
            select can be a single or a list of 'power, voltage, current'
                   the default 'all' is the same as ['voltage', 'current', 'power']
        """
        chs, select = self._fetch_helper(ch, select)
        cch = self.current_meas_channel.get()
        ret = []
        ind = dict(voltage=0, current=1, power=2)
        for c in chs:
            vals = self.meas_all.get(ch=c)
            for s in select:
                ret.append(vals[ind[s]])
        self.current_meas_channel.set(cch)
        return ret

    def channel_en_list(self):
        cch = self.current_channel.getcache()
        ret = [ ch for ch in range(1,4) if self.output_en.get(ch=ch)]
        self.current_channel.setcache(cch)
        return ret

    def current_protection_clear(self, ch=None):
        if ch is None:
            ch = self.current_channel.getcache()
        else:
            self.current_channel.set(ch)
        self.write('CURRent:PROTection:CLEar')
    def voltage_protection_clear(self, ch=None):
        if ch is None:
            ch = self.current_channel.getcache()
        else:
            self.current_channel.set(ch)
        self.write('VOLTage:PROTection:CLEar')

    def get_questionable_status(self):
        def do_ch(ch):
            return dict(voltage_control=bool(ch&1), current_control=bool(ch&2), ovp_tripped=bool(ch&4), ocp_tripped=bool(ch&8))
        ch1 = int(self.ask('STATus:QUEStionable:INSTrument:ISUMmary1?'))
        ch2 = int(self.ask('STATus:QUEStionable:INSTrument:ISUMmary2?'))
        ch3 = int(self.ask('STATus:QUEStionable:INSTrument:ISUMmary3?'))
        # ch_sum = int(self.ask('STATus:QUEStionable:INSTrument?')) # bit 1,2,3 correspond to above ch1,ch2 ch3 summary. (bit 0 is first one)
        other = int(self.ask('STATus:QUEStionable?')) # bit 13 is ch_sum summary
        fan = bool((other>>11)&1)
        temp = bool((other>>4)&1)
        return dict(fan_problem=fan, temperature_problem=temp, ch1=do_ch(ch1), ch2=do_ch(ch2), ch3=do_ch(ch3))

    def _create_devs(self):
        # TODO: add analyzer, delay, Memory, Monitor, output:timer, Preset, Recall, Recorder, Store, Timer, Trigger
        self.current_channel = MemoryDevice(choices=[1, 2, 3], initval=1)
        def devChOption(setstr=None, getstr=None,  **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            if setstr and '{ch}' not in setstr:
                getstr = setstr+'? CH{ch}'
                setstr = setstr+' CH{ch},{val}'
            return scpiDevice(setstr, getstr, **kwarg)
        self.current_meas_channel = MemoryDevice(choices=[1, 2, 3], initval=1)
        def devChMeasOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_meas_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.meas_all = devChMeasOption(getstr='MEASure:ALL? CH{ch}', str_type=decode_float64, autoinit=False,
                multi=['voltage_V', 'current_A', 'power_W'])
        self.meas_current = devChMeasOption(getstr='MEASure:CURRent? CH{ch}', str_type=float, autoinit=False)
        self.meas_voltage = devChMeasOption(getstr='MEASure:VOLTage? CH{ch}', str_type=float, autoinit=False)
        self.meas_power = devChMeasOption(getstr='MEASure:POWEr? CH{ch}', str_type=float, autoinit=False)
        self.output_en = devChOption('OUTPut', choices=Choice_bool_OnOff)
        self.output_mode = devChOption(getstr='OUTPut:MODE? CH{ch}', choices=ChoiceStrings('CC', 'CV', 'UR'))
        # output:ocp, output:ovp are the same as source:current:protection, source:voltage:protection
        chs = [2,3] #for dp831a
        self.output_track_en = devChOption('OUTPut:TRACk', choices=Choice_bool_OnOff, options_lim=dict(ch=chs))
        #self.output_track_en = devChOption('OUTPut:TRACk', choices=Choice_bool_OnOff, options_lim=dict(ch=chs), autoinit=False)
        #self.output_sense_en = devChOption('OUTPut:SENSe', choices=Choice_bool_OnOff)
        lims = [self._get_dev_min_max('SOURce{ch}:CURRent?'.format(ch=i)) for i in range(1,4)]
        current_lims = ChoiceDevDep(self.current_channel, {i+1:ChoiceLimits(min=lims[i][0], max=lims[i][1]) for i in range(3) })
        self.current = devChOption('SOURce{ch}:CURRent', str_type=float, choices=current_lims)
        self.current_protection_level = devChOption('SOURce{ch}:CURRent:PROTection', str_type=float)
        self.current_protection_en = devChOption('SOURce{ch}:CURRent:PROTection:STATe', choices=Choice_bool_OnOff)
        self.current_protection_tripped = devChOption(getstr='SOURce{ch}:CURRent:PROTection:TRIPped?', choices=Choice_bool_YesNo)
        lims = [self._get_dev_min_max('SOURce{ch}:VOLTage?'.format(ch=i)) for i in range(1,4)]
        lims[2] = sorted(lims[2]) # instrument returns min/max incorrectly for the negative channel
        voltage_lims = ChoiceDevDep(self.current_channel, {i+1:ChoiceLimits(min=lims[i][0], max=lims[i][1]) for i in range(3) })
        self.voltage = devChOption('SOURce{ch}:VOLTage', str_type=float, choices=voltage_lims)
        self.voltage_protection_level = devChOption('SOURce{ch}:VOLTage:PROTection', str_type=float)
        self.voltage_protection_en = devChOption('SOURce{ch}:VOLTage:PROTection:STATe', choices=Choice_bool_OnOff)
        self.voltage_protection_tripped = devChOption(getstr='SOURce{ch}:VOLTage:PROTection:TRIPped?', choices=Choice_bool_YesNo)
        self.on_off_sync = scpiDevice('SYSTem:ONOFFSync', choices=Choice_bool_OnOff)
        self.over_temperature_protection_en = scpiDevice('SYSTem:OTP', choices=Choice_bool_OnOff)
        self.track_mode = scpiDevice('SYSTem:TRACKMode', choices=ChoiceStrings('SYNC', 'INDE'))
        self._devwrap('fetch', autoinit=False)
        self.alias = self.voltage
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

