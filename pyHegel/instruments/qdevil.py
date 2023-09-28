# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2021-2023  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from ..instruments_base import visaInstrument,\
                            scpiDevice, MemoryDevice, ReadvalDev, BaseDevice,\
                            ChoiceBase, ChoiceStrings, ChoiceSimpleMap, _general_check,\
                            decode_float64, locked_calling, visa_wrap, Choice_bool_OnOff,\
                            wait, release_lock_context, mainStatusLine, resource_info

from ..instruments_registry import register_instrument

from ..comp2to3 import string_upper

import numpy as np

#######################################################
##    QDevil QDAC-II
#######################################################

class float_inf(ChoiceBase):
    def __init__(self, min, max):
        self._min = min
        self._max = max
    def __call__(self, input_str):
        return float(input_str)
    def tostr(self, val):
        return repr(val)
    def __repr__(self):
        return 'Limits: %s <= val <= %s or inf'%(self._min, self._max)
    def __contains__(self, val):
        if val == np.inf:
            return True
        else:
            try:
                _general_check(val, min=self._min, max=self._max)
            except ValueError:
                return False
            else:
                return True

# timing for version 5-0.9.26
# using: %timeit get(qd.output_range, ch=1)
#  tcp takes 250 ms, serial takes 16 ms
# also Level and Level:last only return 4 digits after the dot (1e4 resolution)
# like set(qd.level, 1.2345678901), get returned as 1.2346 for both level and level:last
# That is fixed in 7-0.17.5, where they return 1.2345679 (level) and 1.2345655 (level_now)

#@register_instrument('QDevil', 'QDAC-II', '7-0.17.5')
#@register_instrument('QDevil', 'QDAC-II', '5-0.9.26')
@register_instrument('QDevil', 'QDAC-II')
class qdevil_qdac_ii(visaInstrument):
    """
    WARNING: changing range/filters should be done with 0 V output.
    Important devices:
        level
        ramp
        fetch
        output_range
        output_filter
        slew_dc
        measI_range
        measI_nplc
        measI_aperture
    Useful methods:
        level_all
    TCP address format:
        TCPIP::Q310-00012.mshome.net::5025::SOCKET
    """
    def __init__(self, visa_addr, *args, **kwargs):
        kwargs['write_termination'] = '\n'
        kwargs['read_termination'] = '\n'
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == visa_wrap.constants.InterfaceType.asrl:
            kwargs['parity'] = visa_wrap.constants.Parity.none
            kwargs['data_bits'] = 8
            kwargs['baud_rate'] = 921600
        # In case keep alive is needed
#        if  rsrc_info.interface_type == visa_wrap.constants.InterfaceType.tcpip:
#            kwargs['keep_alive'] = 'auto'
#            kwargs['keep_alive_time'] = 15*60 # 15 min.
        super(qdevil_qdac_ii, self).__init__(visa_addr, *args, **kwargs)

    def level_all(self, level=0.):
        self.write('SOURce:VOLTage %s,(@1:24)'%level)

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        #orig_ch = self.current_channel.get()
        levels = []
        ranges = []
        filters = []
        dc_modes = []
        slews = []
        enhs = []
        measI_ranges = []
        measI_apertures = []
        def get_append(quest_base, conv):
            vals_str = self.ask(quest_base+' (@1:24)')
            vals = list(map(conv, vals_str.split(',')))
            return vals
        levels = get_append('SOURce:VOLTage:LAST?', float)
        ranges = get_append('SOURce:RANGe?', self.output_range.choices)
        filters = get_append('SOURce:FILTer?', self.output_filter.choices)
        #enhs = get_append('SOURce:RENHancement?', self.output_resolution_enhencement_en.choices)
        enhs = get_append('SOURce:RENHancement?', bool)
        dc_modes =get_append('SOURce:VOLTage:MODE?', self.dc_mode.choices)
        slews = get_append('SOURce:VOLTage:SLEW?', float)
        measI_ranges = get_append('SENSe:RANGe?', self.measI_range.choices)
        measI_apertures = get_append('SENSe:APERture?', float)
        base = ['level=%r'%levels,
                'output_range=%r'%ranges,
                'output_filter=%r'%filters,
                'output_resolution_enhencement_en=%r'%enhs,
                'dc_mode=%r'%dc_modes,
                'slew_dc=%r'%slews,
                'measI_range=%r'%measI_ranges,
                'measI_aperture=%r'%measI_apertures]
        #self.current_channel.set(orig_ch)
        return base + self._conf_helper('line_freq', 'current_channel', options)

    def _ramp_wait(self):
        # can only do polling
        ch = self.current_channel.get()
        target = self.level.getcache() # level uses setget=True
        with release_lock_context(self):
            with mainStatusLine.new(priority=10, timed=True) as progress:
                while True:
                    now_val = self.level_now.get(ch=ch)
                    #if target == now_val:
                    # firmware 7-0.17.5 dpes not return exactly the same value for level and level_now
                    if abs(round(target - now_val, 4)) < 2e-4:
                        break
                    wait(.05)
                    progress('ramp progress: %s -> %s'%(now_val, target))

    def _ramp_setdev(self, val, ch=None):
        prev_val = self.level.get(ch=ch)
        self.level.set(val)
        if prev_val != val:
            self._ramp_wait()
    def _ramp_getdev(self, ch=None):
        return self.level.get(ch=ch)
    def _ramp_checkdev(self, val, ch=None):
        self.level.check(val, ch=ch)

    def _fetch_getformat(self, chs=None, **kwarg):
        chs = self._fetch_ch_helper(chs)
        headers = ['ch_%i'%ch for ch in chs]
        d = self.fetch._format
        d.update(multi=headers, graph=list(range(len(chs))))
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_ch_helper_check(self, ch):
        if ch not in range(1, 24+1):
            raise ValueError(self.perror('fetch chs not in [1, 24] range'))
    def _fetch_ch_helper(self, chs=None):
        if chs is None:
            chs = [self.current_channel.get()]
        elif isinstance(chs, (list, tuple, np.ndarray)):
            for ch in chs:
                self._fetch_ch_helper_check(ch)
        else:
            self._fetch_ch_helper_check(ch)
            chs = [chs]
        chs = sorted(set(chs)) # remove duplicates and sort
        return chs
    def _fetch_getdev(self, chs=None):
        """ Read the current from the list of channels or
            of the current_channel if chs is None.
            repeats in chs are removed and the list is reorder in ascending order.
        """
        #TODO: This will timeout for long request. Eventually handle this better.
        chs = self._fetch_ch_helper(chs)
        chs_str = ','.join(map(str, chs))
        vals_str = self.ask('READ? (@%s)'%chs_str)
        vals = decode_float64(vals_str)
        return vals

    def _read_limits(self):
        conv = lambda s: list(map(float, s.split(',')))
        low_min = conv(self.ask('SOURce:RANGe:LOW:MINimum? (@1:24)'))
        low_max = conv(self.ask('SOURce:RANGe:LOW:MAXimum? (@1:24)'))
        high_min = conv(self.ask('SOURce:RANGe:HIGH:MINimum? (@1:24)'))
        high_max = conv(self.ask('SOURce:RANGe:HIGH:MAXimum? (@1:24)'))
        return dict(low_min=low_min, low_max=low_max, high_min=high_min, high_max=high_max)

    def _level_ch_helper(self, ch=None):
        if ch is not None:
            self.current_channel.set(ch)
        return self.current_channel.get()
    def _level_getdev(self, ch=None):
        ch = self._level_ch_helper(ch)
        valstr = self.ask('SOURce{ch}:VOLTage:LAST?'.format(ch=ch))
        return float(valstr)
    def _level_checkdev(self, val, ch=None):
        ch = self._level_ch_helper(ch)
        rge = self.output_range.getcache()
        if rge == 10:
            max = self._limits['high_max']
            min = self._limits['high_min']
        else:
            max = self._limits['low_max']
            min = self._limits['low_min']
        self.level._general_check(val, min=min[ch-1], max=max[ch-1])
    def _level_setdev(self, val, ch=None):
        # this was set by checkdev.
        ch = self.current_channel.get()
        self.write('SOURce{ch}:VOLTage {val!r}'.format(ch=ch, val=val))

    @locked_calling
    def temperatures(self):
        """ Returns the 9 temperatures starting with the top row left, then top row middle, ... """
        results = []
        for i in [1, 2, 3]: # upper, middle, lower
            for j in [1, 2, 3]: # left, middle, right
                val_str = self.ask('SYSTem:TEMPerature? %i,%i'%(i, j))
                results.append(float(val_str))
        return results
    def _create_devs(self):
        self._limits = self._read_limits()
        self.current_channel = MemoryDevice(1, choices=list(range(1, 24+1)))
        def devChannelOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        #self.level = devChannelOption('SOURce{ch}:VOLTage', 'SOURce{ch}:VOLTage:LAST?', str_type=float, setget=True)
        self._devwrap('level', setget=True)
        self.level_now = devChannelOption(getstr='SOURce{ch}:VOLTage?', str_type=float)
        range_ch = ChoiceSimpleMap(dict(LOW=2., HIGH=10.), filter=string_upper)
        #TODO we might need to cache all the ranges (not just current_channel) to speed up level check
        self.output_range = devChannelOption('SOURce{ch}:RANGe', choices=range_ch)
        self.output_filter = devChannelOption('SOURce{ch}:FILTer', choices=ChoiceStrings('DC', 'MEDium', 'HIGH'),
                                              doc="""DC is about 10 Hz, medium is about 10 kHz and high is about 230 kHz""")
        # fw 5-0.9.26 does not accept 0/1 for boolean
        # fixed in 7-0.17.5
        #self.output_resolution_enhencement_en = devChannelOption('SOURce{ch}:RENHancement', choices=Choice_bool_OnOff)
        self.output_resolution_enhencement_en = devChannelOption('SOURce{ch}:RENHancement', str_type=bool)
        self.dc_mode = devChannelOption('SOURce{ch}:VOLTage:MODE', choices=ChoiceStrings('FIXed', 'SWEep', 'LIST'))
        self.slew_dc = devChannelOption('SOURce{ch}:VOLTage:SLEW', choices=float_inf(min=20, max=2e7), doc='in V/s')

        self.measI_range =  devChannelOption('SENSe{ch}:RANGe', choices=ChoiceStrings('LOW', 'HIGH'), doc="Low=200 nA, high=10 mA")
        # There is an error here. Setting nplc=1/60. at 60 Hz will return an aperture of 0., fw 5-0.9.26
        self.measI_nplc =  devChannelOption('SENSe{ch}:NPLCycles', str_type=float, min=1/60., max=100.)
        self.measI_aperture =  devChannelOption('SENSe{ch}:APERture', str_type=float, min=0.0003, max=1.)

        # This does now work for fw 5-0.9.26
        #self.ref_source = scpiDevice('SYSTem:CLOCk:SOURce', choices=ChoiceStrings('INTernal', 'INTernal'))
        self.line_freq = scpiDevice('SYSTem:LFRequency', choices=[50, 60])

        self._devwrap('ramp')
        self._devwrap('fetch', autoinit=False)
        #TODO: handle sine, triangle, square, awg and the various triggers
        #self._devwrap('level')
        self.alias = self.level
        super(qdevil_qdac_ii, self)._create_devs()
