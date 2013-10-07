# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

import instruments


conf = dict( yo1 = (instruments.yokogawa_gs200, (10,)),
             yo2 = (instruments.yokogawa_gs200, (13,)),
             yo3 = (instruments.yokogawa_gs200, (9,)),
             #yo4 = (instruments.yokogawa_gs200, (1,)),
             #yo5 = (instruments.yokogawa_gs200, (7,)),
             yo4 = (instruments.yokogawa_gs200, ('USB0::0x0B21::0x0039::91M504009',)),
             yo5 = (instruments.yokogawa_gs200, ('USB0::0x0B21::0x0039::91L622196',)),
             yo6 = (instruments.yokogawa_gs200, ('USB0::0x0B21::0x0039::91KB11653',)),
             yo7 = (instruments.yokogawa_gs200, ('USB0::0x0B21::0x0039::91L620548',)),
             yo8 = (instruments.yokogawa_gs200, ('USB0::0x0B21::0x0039::91K130524',)),
             yo9 = (instruments.yokogawa_gs200, ('USB0::0x0B21::0x0039::91L412844',)),
             yo10 = (instruments.yokogawa_gs200, ('USB0::0x0B21::0x0039::91KB11655',)),
             dmm1 = (instruments.agilent_multi_34410A, (11,)),
             dmm2 = (instruments.agilent_multi_34410A, (22,)),
             dmm3 = (instruments.agilent_multi_34410A, (6,)),
             dmm5 = (instruments.agilent_multi_34410A, ('USB0::0x0957::0x0607::MY47021100',)),
             dmm6 = (instruments.agilent_multi_34410A, ('USB0::0x0957::0x0607::MY47021456',)),
             dmm7 = (instruments.agilent_multi_34410A, ('USB0::0x0957::0x0607::MY47015885',)),
             dmm8 = (instruments.agilent_multi_34410A, ('USB0::0x0957::0x0607::MY47021443',)),
             dmm9 = (instruments.agilent_multi_34410A, ('USB0::0x0957::0x0607::MY47027848',)),
             dmm10 = (instruments.agilent_multi_34410A, ('USB0::0x0957::0x0607::MY47021374',)),
             dmm11 = (instruments.agilent_multi_34410A, ('USB0::0x0957::0x0607::MY47026778',)),
             dmm12 = (instruments.agilent_multi_34410A, ('USB0::0x0957::0x0607::MY47014242',)),
             dmm13 = (instruments.agilent_multi_34410A, ('USB0::0x0957::0x0607::MY47026633',)),
             sr1 = (instruments.sr830_lia, (3,)),
             sr2 = (instruments.sr830_lia, (8,)),
             srnet = (instruments.sr780_analyzer, (24,)),
             tc1 = (instruments.lakeshore_322, (12,)),
             tc2 = (instruments.lakeshore_340, (12,)),
             tc3 = (instruments.lakeshore_370, ('ASRL4',)),
             gen1 = (instruments.agilent_rf_33522A, (10,)),
             gen2 = (instruments.agilent_rf_33522A, (14,)),
             gen5 = (instruments.agilent_rf_33522A, ('USB0::0x0957::0x2307::MY50005306',)),
             bnc1 = (instruments.BNC_rf_845, ('USB0::0x03EB::0xAFFF::141-215330500-0233::0',)),
             bnc2 = (instruments.BNC_rf_845, ('USB0::0x03EB::0xAFFF::141-215330500-0234::0',)),
             bnc3 = (instruments.BNC_rf_845, ('USB0::0x03EB::0xAFFF::141-215330500-0235::0',)),
             bnc4 = (instruments.BNC_rf_845, ('USB0::0x03EB::0xAFFF::141-215330500-0236::0',)),
             rf1 = (instruments.sr384_rf, (16,)),
             rf2 = (instruments.sr384_rf, (27,)),
             foo1 = (instruments.dummy, ()),
             foo2 = (instruments.dummy, ()),
             # EXA is gpib 8
             exa1 = (instruments.agilent_EXA, ('USB::0x0957::0x0B0B::MY51170142',)),
             exa2 = (instruments.agilent_EXA, ('USB::0x0957::0x0B0B::MY52220278',)),
             pxa = (instruments.agilent_EXA, ('USB::0x0957::0x0D0B::MY51380626',)),
             # PNA-L is gpib 16
             pna1 = (instruments.agilent_PNAL, ('USB0::0x0957::0x0118::MY49001395',)),
             ena1 = (instruments.agilent_ENA, ('USB0::2391::4873::MY49203311::0',)),
             pnax = (instruments.agilent_PNAL, ('USB0::0x0957::0x0118::MY52041560',)),
             #ENA E5071C we had as a temporary loan summer 2012
             #ena1 = (instrument.agilent_ENA, ('USB0::0x0957::0x0D09::MY46213332',)),
             # scope is USB only
             s500 = (instruments.infiniiVision_3000, ('USB0::2391::6050::MY51135769::INSTR',)),
             s200 = (instruments.infiniiVision_3000, ('USB0::0x0957::0x1796::MY51135849',)),
             # lecroy scope using TCPIP, using an alias
             lecr = (instruments.lecroy_wavemaster, ('lecroy',)),
             # acq board
             acq1 = (instruments.Acq_Board_Instrument, ('127.0.0.1', 50000)),
             acq2 = (instruments.Acq_Board_Instrument, ('127.0.0.1', 50001)),
             # MXG generator is gpib 19
             mxg1 = (instruments.agilent_rf_MXG, ('USB0::0x0957::0x1F01::MY50140552',)),
             # PSG generator
             psg1 = (instruments.agilent_rf_PSG, (19,)),
             psg2 = (instruments.agilent_rf_PSG, (20,)),
             # Data Translation Box
             dt1 = (instruments.DataTranslation, ()),
             # Agilent attenuator
             att1 = (instruments.agilent_rf_Attenuator, ('USB0::0x0957::0x4C18::MY52200101',)),
             # Power meters
             epm1 = (instruments.agilent_PowerMeter, ('USB0::0x0957::0x5418::MY52290056',)),
             # Arbitratry waveform generator
             awg1 = (instruments.agilent_AWG, ('awg1',)),
             # delay box
             delay1 = (instruments.colby_pdl_100a, (5,))
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
