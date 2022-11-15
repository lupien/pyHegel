# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2011-2015  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from ..instruments_base import visaInstrument, BaseDevice,\
                            scpiDevice, MemoryDevice,\
                            _repr_or_string, ChoiceStrings, ChoiceIndex,\
                            decode_float32, locked_calling,\
                            _retry_wait, Block_Codec, _delayed_signal_context_manager,\
                            _sleep_signal_context_manager, FastEvent, ProxyMethod
from ..instruments_registry import register_instrument

#######################################################
##   Windfreak SynthHD Pro v2
#######################################################

class WFscpiDevice(scpiDevice):
    _autoset_val_str = '{val}'

"""
C) Control Channel (A(0) or B(1))  0
f) RF Frequency Now (MHz) 10000.00000000, 9997.00000000
W) RF Power (dBm) -30.000, -19.500
V) Amp Calibration success? 1
Z) Temperature Comp (0=none, 1=on set, 2=1sec, 3=10sec) 3, 3
a) VGA DAC Setting (0=min, 4000=max) 305, 615
~) RF Phase Step (0=minimum, 360.0=maximum) 0.0000, 0.0000
h) RF High(1) or Low(0) Power 0, 0
E) PLL Chip En On(1) or Off(0) 0, 0
U) PLL charge pump current 5, 5
b) REF Doubler On(1) or Off(0) 0, 0
i) Channel spacing (Hz) 100.000, 100.000
x) Reference (external=0, int 27MHz=1, int 10MHz=2) 1
*) PLL reference frequency (MHz) 27.00000000
l) Sweep lower frequency (MHz) 1000.00000000, 1000.00000000
u) Sweep upper frequency (MHz) 5000.00000000, 5000.00000000
s) Sweep step size (MHz/%) 200.00000000, 200.00000000
t) Sweep step time (mS) 1.000, 1.000
[) Sweep amplitude low (dBm) 0.000, 0.000
]) Sweep amplitude high (dBm) 0.000, 0.000
^) Sweep direction (up=1 / down=0) 1, 1
k) Sweep differential seperation (MHz) 1.00000000
n) Sweep differential: (0=off, 1=ChA-DiffFreq, 2=ChA+DiffFreq)  0
X) Sweep type (lin=0 / tab=1 / %=2) 0, 0
g) Sweep run (on=1 / off=0) 0
c) Sweep set continuous mode 0
w) Enable trigger: (0=software, 1=sweep, 2=step, 3=hold all, ..) 0
Y) Trigger Polarity (active low=0 / active high=1) 0
F) AM step time (uS) 0
q) AM # of cycle repetitions 65
A) AM Run Continuous (on=1 / off=0) 0
P) Pulse On time (uS) 1, 1
O) Pulse Off time (uS) 10, 10
R) Pulse # of repetitions 10, 10
:) Pulse Invert signal (on=1 / off=0) 0, 0
G) Pulse Run one burst
j) Pulse continuous mode 0
<) FM Frequency (Hz) 20000, 1000
>) FM Deviation (Hz) 20000000, 100000
,) FM # of repetitions 100, 100
;) FM Type (sinusoid=0 / chirp=1) 0, 0
/) FM continuous mode 0
p) Phase lock status (lock=1 / unlock=0) 0, 0
I) Trigger digital status (high=1 / low=0) 1
z) Temperature in degrees C 28.625
m) Automatic communication mode (UART=1 / USB=0) 0
T) Send test message to both USB and UART
v) Show version (0=FW, 1=HW, 2=Model) 3.25, 2.06
+) Model Type
-) Serial Number 1230
e) Write all settings to eeprom
?) help
Cal datecode YYWW 2232
"""

@register_instrument('Windfreak', 'SynthHD HDPRO')
class Windfreak_SynthHDProV2(visaInstrument):
    """
    This is the driver for the Windfreak SynthHDPro v2 generators
    In case there is an error, use the read method to make sure there are no left overs
    in the buffer (use empty_buffer method)
    """
    def __init__(self,*args, **kwargs):
        """ Ro is the impedance used in power conversions. see unit option in fetch """
        kwargs['write_termination'] = ''
        kwargs['read_termination'] = '\n'
        self._empty_data = []
        super(Windfreak_SynthHDProV2, self).__init__(*args, **kwargs)

    @locked_calling
    def show_all_commands(self):
        self.write('?')
        res = ''
        while True:
            r = self.read()
            if r.startswith('EOM'):
                break
            res += r+'\n'
        print res

    def empty_buffer(self):
        self._empty_data =[]
        while True:
            try:
                s = self.read()
                self._empty_data.append(s)
            except:
                return
    def idn(self):
        model = self.ask('+').split(' ')[1] #  'WFT SynthHD 1230'
        serial = self.ask('-')
        fw = self.ask('v0').split(' ')[-1] # Firmware Version 3.25
        hw = self.ask('v1').split(' ')[-1] # Hardware Version 2.06
        model2 =  self.ask('v2')  # 'HDPRO'
        firmware = 'fw:%s_hw:%s'%(fw, hw)
        return 'Windfreak,%s,%s,%s'%(model+' '+model2, serial, firmware)

    def get_error(self):
        return NotImplementedError(self.perror('This device does not implement get_error'))

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        base_end = self._conf_helper('current_channel', '', options)
        return base_end

    def _rf_output_en_checkdev(self, val, ch=None):
        return BaseDevice._checkdev(self.rf_output_en, val)
    def _rf_output_en_getdev(self, ch=None):
        if ch is not None:
            self.current_channel.set(ch)
        r = self.ask('E?')
        r = bool(int(r))
        return r
    def _rf_output_en_setdev(self, val, ch=None):
        if ch is not None:
            self.current_channel.set(ch)
        if val:
            self.write('E1r1h1') # PLL on, Power to output stage on, mute off
        else:
            self.write('E0r0h0')

    def write_to_eeprom(self):
        """
        save all settings to EEPROM, to be there upon next power up
        """
        self.write('e')

    def _create_devs(self):
        self.current_channel = WFscpiDevice('C', str_type=int, choices=[0, 1])
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return WFscpiDevice(*arg, **kwarg)
        self.freq_MHz = devChOption('f', str_type=float, setget=True)
        self.rf_level_dBm = devChOption('W', str_type=float, setget=True)
        self.rf_output_en = devChOption('W', str_type=float, setget=True)
        self.amp_calib_succes = WFscpiDevice(getstr='V', str_type=bool)
        self.temp_compensation = devChOption('Z', choices=ChoiceIndex(['none', 'on_set', '1sec', '10sec']))
        self.pll_locked = devChOption(getstr='p', str_type=bool)
        self.ref_src = WFscpiDevice('x', choices=ChoiceIndex(['ext', 'int_27MHz', 'int_10MHz']))
        self.ref_ext_freq = WFscpiDevice('*', str_type=float, setget=True)
        self.temperature_C = WFscpiDevice(getstr='z', str_type=float)
        self.trig_connection = WFscpiDevice('w', choices=
                                            ChoiceIndex(['none', 'trig_full_sweep', 'trig_single_step', 'trig_stop_all', 'trig_RF_on_off', 'remove_interrupts', 'reserved1', 'reserved2', 'ext_am_mod', 'ext_fm_mod']))
        self._devwrap('rf_output_en')
        # This needs to be last to complete creation
        super(Windfreak_SynthHDProV2, self)._create_devs()
