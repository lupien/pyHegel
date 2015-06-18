# -*- coding: utf-8 -*-

"""
 This is and example local_config file. It is loaded if no local_config file is found.
 To make your own one, create a local_config.py and place it in one of the same directories
 where pyHegel.ini can be placed (see pyHegel_default.ini for those locations)
  It is often in the .pyHegel directory under the user home directory.
"""

from __future__ import absolute_import

from pyHegel import instruments
from pyHegel.instruments_registry import register_instrument

# Lets force a new ids and usb product ids onto the agilent multimeter instrument class
register_instrument('Agilent', 'DMM', usb_vendor_product=[0x0957, 0xFFFF])(instruments.agilent_multi_34410A)


conf = dict(
             # Let start with some Yokogawa GS200 DC voltage/current sources
             yo1 = (instruments.yokogawa_gs200, (10,)), # This is gpib address 10
             yo2 = (instruments.yokogawa_gs200, (13,)), # This is gpib address 13
             # The following use the usb visa address. It is unique to that device serial number
             yo4 = (instruments.yokogawa_gs200, ('USB0::0x0B21::0x0039::91M555555',)),
             # Now some Agilent(Keysight) multimeters
             dmm1 = (instruments.agilent_multi_34410A, (11,)), # This is gpib address 11
             # Now using a usb address
             dmm5 = (instruments.agilent_multi_34410A, ('USB0::0x0957::0x0607::MY44444444',)),
             # Now using a lan address (VXI-11 interface)
             # Note that some device might be available in the .local domain
             dmm6 = (instruments.agilent_multi_34410A, ('TCPIP0::192.168.137.143',)),
             dmm7 = (instruments.agilent_multi_34410A, ('TCPIP0::A-34410A-22222.mshome.net',)),
             # A Standford Research Systems SR830 lockin amplifier
             sr1 = (instruments.sr830_lia, (3,)),
             # A Lakeshore Cryotronics 370 AC resistance bridge/temperature controller using a serial port
             # and specifying the still heater resistance and the still heater resistance including the leads.
             tc1 = (instruments.lakeshore_370, ('ASRL1', 120.), dict(still_full_res=136.4)),
        )

usb_manuf = { 0x0957 : ('Agilent', { 0x0607 : 'multimeter',
                                     0x2307 : 'rf_gen',
                                     0x1309 : 'ENA',
                                     0x0B0B : 'EXA',
                                     0x0D0B : 'PXA',
                                     0x0118 : 'PNA',
                                     0x17A2 : 'infiniiVision_500',
                                     0x1796 : 'infiniiVision_200',
                                     0x1F01 : 'MXG',
                                     0x5418 : 'PowerMeter',
                                     0x4C18 : 'RF_attenuator' }),
              0x0B21 : ('Yokogawa',  {0x0039 : 'GS200' }),
              0x03EB : ('BNC', {0xAFFF : 'rf_845'})
            }
