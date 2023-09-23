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

from ..instruments_base import visaInstrument, BaseDevice,\
                            scpiDevice, MemoryDevice,\
                            _repr_or_string, ChoiceStrings, ChoiceIndex, float_as_fixed,\
                            decode_float32, locked_calling, wait,\
                            _retry_wait, Block_Codec, _delayed_signal_context_manager,\
                            _sleep_signal_context_manager, FastEvent, ProxyMethod, visa_wrap,\
                            resource_info
from ..instruments_registry import register_instrument

float_fix2 = float_as_fixed('%.2f')

#@register_instrument('Mini-Circuits', 'RCDAT-18G-63', 'J2-ID91')
@register_instrument('Mini-Circuits', 'RCDAT-18G-63')
class minicircuit_RCDAT(visaInstrument):
    """
    This is the driver for the Mini-Circuits step attenuator.
    This currently handles only the lan connection or serial connection, not USB.
    lan connection address example: 'tcpip::MCL70018.mshome.net::23::socket'
    Useful devices:
        attenuation
    """
    def __init__(self, visa_addr, *args, **kwargs):
        cnsts = visa_wrap.constants
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == cnsts.InterfaceType.asrl:
            #baud_rate = kwargs.pop('baud_rate', 115200)
            baud_rate = kwargs.pop('baud_rate', 9600)
            parity = kwargs.pop('parity', cnsts.Parity.none)
            data_bits = kwargs.pop('data_bits', 8)
            stop_bits = kwargs.pop('stop_bits', cnsts.StopBits.one)
            kwargs['baud_rate'] = baud_rate
            kwargs['parity'] = parity
            kwargs['data_bits'] = data_bits
            kwargs['stop_bits'] = stop_bits
            kwargs['write_termination'] = '\r'
            kwargs['read_termination'] = '\r'
        else: # tcpip
            kwargs['write_termination'] = '\r\n'
            kwargs['read_termination'] = '\r\n'
        super(minicircuit_RCDAT, self).__init__(visa_addr, *args, **kwargs)

    def idn(self):
        model = self.ask(':MN?')
        if model.startswith('MN='):
            model = model[3:]
        serial = self.ask(':SN?')
        if serial.startswith('SN='):
            serial = serial[3:]
        fw = self.ask(':firmware?')
        return 'Mini-Circuits,%s,%s,%s'%(model, serial, fw)

    def get_error(self):
        return NotImplementedError(self.perror('This device does not implement get_error'))

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('attenuation', options)

    def _create_devs(self):
        self.attenuation = scpiDevice(':setatt:{val}', ':att?', str_type=float_fix2, setget=True, min=0, max=63.25)
        self.alias = self.attenuation
        # This needs to be last to complete creation
        super(minicircuit_RCDAT, self)._create_devs()

"""
#USB interface would work as follows:
#Assuming mcl_RUDAT_NET45.dll is in the path
import clr
clr.AddReference('mcl_RUDAT_NET45')
from mcl_RUDAT_NET45 import USB_RUDAT
def check(res):
    if res[0] == 0:
        raise RuntimeError('Failed')
    else:
        return res[1]
att2 = USB_RUDAT()
check(att2.Get_Available_SN_List('')).split(' ') # returns [u'12212070018']
check(att2.Get_Available_Address_List('')).split(' ') # returns [u'255']

# all the connect return 0 for failure, 1 for success and 2 if the connection was already active
att2.Connect()
# or
att2.ConnectByAddress()
# or
att2.Connect('12212070018')
# or
att2.ConnectByAddress(255)

att2.GetUSBConnectionStatus() # returns 1

check(att2.Send_SCPI(':MN?', ''))
check(att2.Send_SCPI(':sn?', ''))
check(att2.Send_SCPI(':firmware?', ''))
# Note that the att2.Read_Att does not seem to work
#  nor does att2.SetAttenuation seem to work
#  so use SCPI instead
check(att2.Send_SCPI(':att?', ''))
Check(att2.Send_SCPI(':setatt:12', ''))

att2.Disconnect()
att2.GetUSBConnectionStatus() # returns 0
"""