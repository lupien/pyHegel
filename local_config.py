import instrument
import acq_board_instrument

try:
    import data_translation
except ImportError, exc:
    class data_translation(object):
        _exc = exc
        @staticmethod
        def DataTranslation(*argv):
            print exc.extra_info


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
             tc2 = (instrument.lakeshore_340, (12,)),
             tc3 = (instrument.lakeshore_370, ('COM4',)),
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
             ena1 = (instrument.agilent_ENA, ('USB0::0x0957::0x0D09::MY46213332',)),
             # scope is USB only
             s500 = (instrument.infiniiVision_3000, ('USB0::2391::6050::MY51135769::INSTR',)),
             s200 = (instrument.infiniiVision_3000, ('USB0::0x0957::0x1796::MY51135849',)),
             # acq board
             acq1 = (acq_board_instrument.Acq_Board_Instrument, ('127.0.0.1', 50000)),
             acq2 = (acq_board_instrument.Acq_Board_Instrument, ('127.0.0.1', 50001)),
             # MXG generator is gpib 19
             mxg1 = (instrument.agilent_rf_MXG, ('USB0::0x0957::0x1F01::MY50140552',)),
             # Data Translation Box
             dt1 = (data_translation.DataTranslation, ()),
             # Agilent attenuator
             att1 = (instrument.agilent_rf_Attenuator, ('USB0::0x0957::0x4C18::MY52200101',))
        )
