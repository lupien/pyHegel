import instrument
import acq_board_instrument

conf = dict( yo1 = (instrument.yokogawa_gs200, (10,)),
             yo2 = (instrument.yokogawa_gs200, (13,)),
             yo3 = (instrument.yokogawa_gs200, (9,)),
             yo4 = (instrument.yokogawa_gs200, (1,)),
             yo5 = (instrument.yokogawa_gs200, (7,)),
             dmm1 = (instrument.agilent_multi_34410A, (11,)),
             dmm2 = (instrument.agilent_multi_34410A, (22,)),
             dmm3 = (instrument.agilent_multi_34410A, (6,)),
             sr1 = (instrument.sr830_lia, (3,)),
             sr2 = (instrument.sr830_lia, (8,)),
             tc1 = (instrument.lakeshore_322, (12,)),
             gen1 = (instrument.agilent_rf_33522A, (10,)),
             gen2 = (instrument.agilent_rf_33522A, (14,)),
             rf1 = (instrument.sr384_rf, (16,)),
             rf2 = (instrument.sr384_rf, (27,)),
             foo1 = (instrument.dummy, ()),
             foo2 = (instrument.dummy, ()),
             # EXA is gpib 8
             exa1 = (instrument.agilent_EXA, ('USB::0x0957::0x0B0B::MY51170142',)),
             # PNA-L is gpib 16
             pna1 = (instrument.agilent_PNAL, ('USB0::0x0957::0x0118::MY49001395',)),
             # scope is USB only
             s500 = (instrument.infiniiVision_3000, ('USB0::2391::6050::MY51135769::INSTR',)),
             s200 = (instrument.infiniiVision_3000, ('USB0::0x0957::0x1796::MY51135849',)),
             # acq board
             acq1 = (acq_board_instrument.Acq_Board_Instrument, ('127.0.0.1', 50000))
        )
