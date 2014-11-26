# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

import instruments_base
import instruments_others
import instruments_logical
import instruments_agilent
import acq_board_instrument
import instruments_lecroy
import blueforsValves

try:
    import data_translation
except ImportError, exc:
    # When the module does not load, replace it by a dummy class
    class data_translation(object):
        _exc = exc
        @staticmethod
        def DataTranslation(*argv):
            print exc.extra_info
        @staticmethod
        def find_all_Ol():
            print exc.extra_info

from instruments_base import visaInstrument, visaInstrumentAsync, BaseDevice,\
                            BaseInstrument, MemoryDevice, scpiDevice, find_all_instruments,\
                            sleep

from instruments_others import yokogawa_gs200,\
                                sr830_lia, sr384_rf, sr780_analyzer,\
                                lakeshore_322, lakeshore_340, lakeshore_370,\
                                colby_pdl_100a, BNC_rf_845, MagnetController_SMC, dummy

from instruments_logical import LogicalDevice, ScalingDevice, FunctionDevice,\
                                LimitDevice, CopyDevice, ExecuteDevice,\
                                RThetaDevice, PickSome, Average, FunctionWrap

from instruments_agilent import agilent_rf_33522A, agilent_PowerMeter,\
                                agilent_rf_PSG, agilent_rf_MXG,\
                                agilent_multi_34410A, agilent_rf_Attenuator,\
                                infiniiVision_3000, agilent_EXA,\
                                agilent_PNAL, agilent_ENA, agilent_FieldFox,\
                                agilent_AWG

from acq_board_instrument import Acq_Board_Instrument, HistoSmooth, calc_cumulants

from instruments_lecroy import lecroy_wavemaster

from blueforsValves import bf_valves

DataTranslation = data_translation.DataTranslation
find_all_Ol = data_translation.find_all_Ol
