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

from ..instruments_base import visaInstrument,\
                            BaseDevice, scpiDevice, MemoryDevice, Dict_SubDevice,\
                            ChoiceBase, ChoiceMultiple, ChoiceMultipleDep,\
                            ChoiceStrings, ChoiceIndex,\
                            make_choice_list,\
                            visa_wrap, locked_calling, wait,\
                            resource_info
from ..types import dict_improved
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

from .logical import FunctionDevice, ScalingDevice

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
        self.status_a = scpiDevice(getstr='RDGST? A', str_type=int) #flags 1(0)=invalid, 16(4)=temp underrange,
                               #32(5)=temp overrange, 64(6)=sensor under (<0), 128(7)=sensor overrange
                               # 000 = valid
        self.status_b = scpiDevice(getstr='RDGST? b', str_type=int)
        self.htr = scpiDevice(getstr='HTR?', str_type=float) #heater out in %
        self.sp = scpiDevice(setstr='SETP 1,', getstr='SETP? 1', str_type=float)
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
        self.status_ch = devChOption(getstr='RDGST? {ch}', str_type=int) #flags 1(0)=invalid, 16(4)=temp underrange,
                               #32(5)=temp overrange, 64(6)=sensor under (<0), 128(7)=sensor overrange
                               # 000 = valid
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
class quoted_name(object):
    def __call__(self, read_str):
        # the instruments returns a 15 character string with spaces if unused
        return read_str.rstrip()
    def tostr(self, input_str):
        if '"' in input_str:
            raise ValueError, 'The given string already contains a quote :":'
        return '"'+input_str[:15]+'"'

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
            in_set = []
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
        self.status_ch = devChOption(getstr='RDGST? {ch}', str_type=int) #flags 1(0)=invalid, 16(4)=temp underrange,
                               #32(5)=temp overrange, 64(6)=sensor under (<0), 128(7)=sensor overrange
                               # 000 = valid
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


