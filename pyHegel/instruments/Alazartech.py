# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2022-2023  Antoine Cornillot                                     #
#                      Christian Lupien <christian.lupien@usherbrooke.ca>    #
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
import sys
import ctypes
import os
import time

import time

from pyHegel.util import readfile

from scipy import signal
from scipy.fftpack import rfft, rfftfreq
from scipy.ndimage import uniform_filter1d

from ctypes import c_uint8, c_uint16, c_long, c_int, c_uint, c_uint64, c_ubyte, POINTER, byref, create_string_buffer, Structure, Array

from ..instruments_base import BaseInstrument, scpiDevice, ChoiceIndex,\
                            wait_on_event, BaseDevice, MemoryDevice, ReadvalDev,\
                            _retry_wait, locked_calling, CHECKING
from ..instruments_registry import register_instrument, add_to_instruments

ats = None
_delayed_imports_done = False

def _delayed_imports():
    """
    If _delayed_imports_done is False, imports atsatpi.py file as the global variable ats and set _delayed_imports_done to True - to never do the import again  
    """
    global _delayed_imports_done
    if not _delayed_imports_done:
        global ats
        try:
            ats_directory=r'C:\Codes\Alazartech9462\atsapi'
            if ats_directory not in sys.path:
                sys.path.append(ats_directory)
            import atsapi as ats
            print("import_ats")
        except ImportError as exc:
            raise RuntimeError(
                "Unable to load atsapi Module. Make sure Alazartech SDKis installed: %s"%exc)

        _delayed_imports_done = True


def get_alazartech_device(id):
    """
    Takes the device id defined by Alazartech and returns the name of the device

    Input:
        - id (Int): device id defined by Alazartech in atsapi
    Output:
        - DeviceName (String): Name of the device
    """
    device_list={1:"ATS850",
                2:"ATS310",
                3:"ATS330",
                4:"ATS855",
                5:"ATS315",
                6:"ATS335",
                7:"ATS460",
                8:"ATS860",
                9:"ATS660",
                10:"ATS665",
                11:"ATS9462",
                13:"ATS9870",
                14:"ATS9350",
                15:"ATS9325",
                16:"ATS9440",
                18:"ATS9351",
                21:"ATS9850",
                22:"ATS9625",
                24:"ATS9626",
                25:"ATS9360",
                26:"AXI9870",
                27:"ATS9370",
                29:"ATS9373",
                30:"ATS9416",
                31:"ATS9637",
                32:"ATS9120",
                33:"ATS9371",
                34:"ATS9130",
                35:"ATS9352",
                36:"ATS9453",
                37:"ATS9146",
                40:"ATS9437",
                41:"ATS9618",
                42:"ATS9358",
                44:"ATS9353",
                45:"ATS9872",
                47:"ATS9628"}
    return device_list[id]


def get_board_info(board):
    """
    Returns the properties of an Alazartech Board
    
    Input:
        - board (ats.Board): board entity
    Output:
        - BoardInfos (dic): Contains (see ATS-SDK Guide)
            - Kind: Name of the Device
            - PCBrevision: PCB Hardware revision number (Major Version Number, Minor Version Number)
            - CPLDrevision: CPLD Hardware revision number (Major Version Number, Minor Version Number)
            - FPGAversion: FPGA version
            - MemorySize: Total size of the on-board memory in samples
            - BitsPerSample: Bits Per Sample
            - Status: 1: At least one trigger timeout occured, 
                      2: At least one channel A sample was out of range during last acquisition
                      4: At least one channel B sample was out of range during last acquisition
                      8: PLL is locked (ATS660 only)
    """
    revision = board.getBoardRevision()
    cpld = board.getCPLDVersion()
    fpga = board.getFPGAVersion()
    channel = board.getChannelInfo()
    bytesPerSample = (channel[1].value + 7) // 8

    c_sample_type = ctypes.c_uint8
    sample_type = np.uint8
    zero_value = 128.
    if bytesPerSample > 1:
        c_sample_type = ctypes.c_uint16
        sample_type = np.uint16
        zero_value = 32768.

    return {"Kind":get_alazartech_device(board.getBoardKind()),
            "PCBrevision":(revision[0].value,revision[1].value),
            "CPLDversion":(cpld[0].value,cpld[1].value),
            "FPGAversion":(fpga[0].value,fpga[1].value), 
            "MemorySize":channel[0].value,
            "BitsPerSample":channel[1].value,
            "BytesPerSample":bytesPerSample,
            "C_sample_type":c_sample_type,
            "Sample_type":sample_type,
            "Zero_value":zero_value,
            "Status":board.getStatus()}


@add_to_instruments
def find_all_Alazartech(display=True):
    """
    Returns the number of systems of boards, the number of boards detected, a description of the systems of boards

    Output:
        - systemsCount (Int): Number of systems detected. A system is composed of boards connected together
        - boardsCount (Int): Number of boards detected.
        - systems (Dic{Int:(Int, Dic)}): Dictionary listing all the systems : For each system id number, we associate
                                         a tuple with the number of boards contained in the system, and a dictionary 
                                         associating to each board number its infos.
    """
    _delayed_imports()

    systemsCount = ats.numOfSystems()
    boardsCount = ats.boardsFound()
    systems = {}
    sdk = ats.getSDKVersion()
    driver = ats.getDriverVersion()
    for i in range(1, systemsCount+1):
        boardsCountinSystem = ats.boardsInSystemBySystemID(i)
        boardsDic = {}

        for j in range(1, boardsCountinSystem+1):
            boardinSystem = ats.Board(i, j)
            boardsDic[j] = get_board_info(boardinSystem)

        systems[i] = (boardsCountinSystem, boardsDic)
    
    if display:
        print("SDK Version", (sdk[0].value, sdk[1].value, sdk[2].value))
        print("Driver Version", (driver[0].value, driver[1].value, driver[2].value))
        print(boardsCount, " Alazartech cards found in ", systemsCount, " systems :")
        print("systemId: (nbCards, cardId) :", systems)
        print("Use ATSBoard(systemId, cardId) to configure specific card")

    return systemsCount, boardsCount, systems


def convert_clock_type(clock, justcheck=False):
    """
    Convert the clock type in a code understoodable by the board
    Possible clock types:
        - "INT": INTERNAL, only certain sampling can be realized
        - "EXT": EXTERNAL, sampling is realized by an external clock
        - "slow_EXT": sampling is realized by an external clock with sampling rate below 1MHz
        - "fast_EXT": sampling is realized by an external clock with sampling rate above 1MHz
        - "EXT_10MHz": by using an external clock at 10MHz, sampling rate (for ATS9462) between 150MHz and 180MHz can be realized(1MHz step) 
    
    Input:
        - clock (String): One of the possible clock types
        - justcheck (Boolean): If True, just checks if the clock value is in the dictionary, nothing is output
    Output:
        - ats_clock (Int): An hexadecimal understoodable by the Card describing the clock type   
    """
    _delayed_imports()
    clock_dic = {"INT":ats.INTERNAL_CLOCK,
                 "EXT":ats.EXTERNAL_CLOCK,
                 "slow_EXT":ats.SLOW_EXTERNAL_CLOCK,
                 "fast_EXT":ats.FAST_EXTERNAL_CLOCK,
                 "EXT_10MHz":ats.EXTERNAL_CLOCK_10MHz_REF}
    if clock in clock_dic.keys():
        if not justcheck:
            return clock_dic[clock]
    else:
        raise ValueError("""Possible clocks : "INT" (internal clock, take only certain values),\n 
            "EXT" (external clock),\n
            "fast_EXT" (1MHz<f_ext"),\n
            "slow_EXT" (f_ext<1MHz),\n
            "EXT_10MHz" (generate clock 150MHz<f_ext<180MHz from 10MHz signal)""") 


def convert_sample_rate(sample_rate, board_kind, clock, justcheck=False):
    """
        Translates an input sample rate (a number) in an hexadecimal form understoodable by the acquisition card.
        Possible sample rates:
            - in INT clock mode: For all boards: [1e3, 2e3, 5e3, 10e3, 20e3, 50e3, 100e3, 200e3, 500e3, 1e6, 2e6, 5e6, 10e6, 20e6, 25e6, 50e6, 100e6,
              125e6, 160e6, 180e6, 200e6, 250e6, 400e6, 500e6, 800e6, 1e9, 1.2e9, 1.5e9, 1.6e9, 1.8e9, 2e9, 2.4e9, 3e9, 3.6e9, 4e9]
                                For ATS9462: sample_rate < 180MS/s
            - in EXT_10MHz mode: (ATS9462) sample rate betweem 150 MS/s and 180MS/s
                                  (see ATS-SDK for other boards)
            - in EXT, slow_EXT, fast_EXT: sample rate is defined by the user

        Input:
            - sample_rate (Int): Sample rate you want to convert
            - board_kind (String): name of the board
            - clock (String): type of the clock
            - justcheck (boolean): If True, just checks if the clock value is in the dictionary, nothing is output
        Output:
            - converted_sample_rate (hexadecimal): Sample rate understoodable by the Alazartech card (see atsapi.py)
    """
    _delayed_imports()
    sample_rate_dic={1e3:ats.SAMPLE_RATE_1KSPS,
                     2e3:ats.SAMPLE_RATE_2KSPS,
                     5e3:ats.SAMPLE_RATE_5KSPS,
                     10e3:ats.SAMPLE_RATE_10KSPS,
                     20e3:ats.SAMPLE_RATE_20KSPS,
                     50e3:ats.SAMPLE_RATE_50KSPS,
                     100e3:ats.SAMPLE_RATE_100KSPS,
                     200e3:ats.SAMPLE_RATE_200KSPS,
                     500e3:ats.SAMPLE_RATE_500KSPS,
                     1e6:ats.SAMPLE_RATE_1MSPS,
                     2e6:ats.SAMPLE_RATE_2MSPS,
                     5e6:ats.SAMPLE_RATE_5MSPS,
                     10e6:ats.SAMPLE_RATE_10MSPS,
                     20e6:ats.SAMPLE_RATE_20MSPS,
                     25e6:ats.SAMPLE_RATE_25MSPS,
                     50e6:ats.SAMPLE_RATE_50MSPS,
                     100e6:ats.SAMPLE_RATE_100MSPS,
                     125e6:ats.SAMPLE_RATE_125MSPS,
                     160e6:ats.SAMPLE_RATE_160MSPS,
                     180e6:ats.SAMPLE_RATE_180MSPS,
                     200e6:ats.SAMPLE_RATE_200MSPS,
                     250e6:ats.SAMPLE_RATE_250MSPS,
                     400e6:ats.SAMPLE_RATE_400MSPS,
                     500e6:ats.SAMPLE_RATE_500MSPS,
                     800e6:ats.SAMPLE_RATE_800MSPS, 
                     1000e6:ats.SAMPLE_RATE_1000MSPS,
                     1200e6:ats.SAMPLE_RATE_1200MSPS,
                     1500e6:ats.SAMPLE_RATE_1500MSPS,
                     1600e6:ats.SAMPLE_RATE_1600MSPS,
                     1800e6:ats.SAMPLE_RATE_1800MSPS,
                     2000e6:ats.SAMPLE_RATE_2000MSPS,
                     24000e6:ats.SAMPLE_RATE_2400MSPS,
                     30000e6:ats.SAMPLE_RATE_3000MSPS,
                     3600e6:ats.SAMPLE_RATE_3600MSPS,
                     4000e6:ats.SAMPLE_RATE_4000MSPS}
    convert_clock_type(clock, justcheck=True)
    if board_kind == "ATS9462":
        if sample_rate>180e6 :
            raise ValueError("ATS9462 : Sample rate < 180 MS/s")
    
    if clock == "INT":
        if not sample_rate in sample_rate_dic.keys():
            raise ValueError("Possible values for sample rate (Internal clock): 1e3, 2e3, 5e3, 10e3, 20e3, 50e3, 100e3, 200e3, 500e3, 1e6, 2e6, 5e6, 10e6, 20e6, 25e6, 50e6, 100e6, 125e6, 160e6, 180e6, 200e6, 250e6, 400e6, 500e6, 800e6, 1e9, 1.2e9, 1.5e9, 1.6e9, 1.8e9, 2e9, 2.4e9, 3e9, 3.6e9, 4e9")
    
        if not justcheck:
            return sample_rate_dic[sample_rate]
    else:
        if clock == "EXT_10MHz":
            if board_kind == "ATS9462" and sample_rate<150e6:
                raise ValueError("EXT_10MHz: sample rate between 150 MS/s and 180 MS/s (1MS/s step)")
            if not justcheck:
                return int(sample_rate)
        else:
            if not justcheck:
                return ats.SAMPLE_RATE_USER_DEF


def convert_impedance(impedance, justcheck=False):
    """
    Translate an impedance (in Ohm) into an hexadecimal understoodable by Alazartech devices.
    Possible values (in Ohm):
        - 10**6
        - 50
        - 75
        - 300

    Input:
        - impedance: impedance value in Ohm
    Output:
        - ats_impedance: Hexadecimal understoodable by the Alazartech card.
    """
    impedance_dict = {1e6: ats.IMPEDANCE_1M_OHM,
                      50: ats.IMPEDANCE_50_OHM,
                      75: ats.IMPEDANCE_75_OHM,
                      300: ats.IMPEDANCE_300_OHM}
    if not impedance in impedance_dict.keys():
        raise ValueError("Possible impedance values: 50, 75, 300, 1e6")
    else:
        return impedance_dict[impedance]


def convert_input_range(acquisition_mode, input_range, board_kind, justcheck=False):
    """
        Translate an input range (in mV) into an hexadecimal understoodable by Alazartech devices.
        If the acquisition mode is in 
            -"pm" mode, input range is [-input_range; input_range]
            Possible values (in mV): [20, 40, 50, 80, 100, 125, 200, 250, 400, 500, 800, 1000, 2000, 2500, 4000, 5000, 8000, 1e4, 1.6e4, 2e4, 4e4]
            -"0p" mode, input range is [0; input_range]
            Possible values (in mV): [40, 80, 100, 160, 200, 250, 400, 500, 800, 1000, 1600, 2000, 2500, 4000, 5000, 8000, 1e4, 1.6e4, 2e4, 3.2e4, 8e4]
            -"0m" mode, input range is [-input_range; 0]
            Possible values (in mV): [40, 80, 100, 160, 200, 250, 400, 500, 800, 1000, 1600, 2000, 2500, 4000, 5000, 8000, 1e4, 1.6e4, 2e4, 3.2e4, 8e4]
        ATS9462:
            - "pm": Input range should be between +/-200mV and +/-16V
            - "0p" or "0m": Input range should be between 400mV and 32V
        See ATS-SDK-Guide for other cards

        Input:
            - acquisition_mode (String): Defines the acquisition window
            - input_range (Int): Input range in mV
            - board_kind (String): Name of the Alazartech Device
            - justcheck (boolean): If True, just checks if acquisition_mode and input_range are correct, nothing is output
        Output:
            converted_input_range (hexadecimal): Input range understoodable by the Alazartech card (see atsapi.py)
    """
    _delayed_imports()
    input_range_dic={"pm":{20:ats.INPUT_RANGE_PM_20_MV,
                            40:ats.INPUT_RANGE_PM_40_MV,
                            50:ats.INPUT_RANGE_PM_50_MV,
                            80:ats.INPUT_RANGE_PM_80_MV,
                            100:ats.INPUT_RANGE_PM_100_MV,
                            125:ats.INPUT_RANGE_PM_125_MV,
                            200:ats.INPUT_RANGE_PM_200_MV,
                            250:ats.INPUT_RANGE_PM_250_MV,
                            400:ats.INPUT_RANGE_PM_400_MV,
                            500:ats.INPUT_RANGE_PM_500_MV,
                            800:ats.INPUT_RANGE_PM_800_MV,
                            1000:ats.INPUT_RANGE_PM_1_V,
                            1250:ats.INPUT_RANGE_PM_1_V_25,
                            2000:ats.INPUT_RANGE_PM_2_V,
                            2500:ats.INPUT_RANGE_PM_2_V_5,
                            4000:ats.INPUT_RANGE_PM_4_V,
                            5000:ats.INPUT_RANGE_PM_5_V,
                            8000:ats.INPUT_RANGE_PM_8_V,
                            1e4:ats.INPUT_RANGE_PM_10_V,
                            1.6e4:ats.INPUT_RANGE_PM_16_V,
                            2e4:ats.INPUT_RANGE_PM_20_V,
                            4e4:ats.INPUT_RANGE_PM_40_V},
                     "0p":{40:ats.INPUT_RANGE_0_TO_40_MV,
                            80:ats.INPUT_RANGE_0_TO_80_MV,
                            100:ats.INPUT_RANGE_0_TO_100_MV,
                            160:ats.INPUT_RANGE_0_TO_160_MV,
                            200:ats.INPUT_RANGE_0_TO_200_MV,
                            250:ats.INPUT_RANGE_0_TO_250_MV,
                            400:ats.INPUT_RANGE_0_TO_400_MV,
                            500:ats.INPUT_RANGE_0_TO_500_MV,
                            800:ats.INPUT_RANGE_0_TO_800_MV,
                            1000:ats.INPUT_RANGE_0_TO_1_V,
                            1600:ats.INPUT_RANGE_0_TO_1600_MV,
                            2000:ats.INPUT_RANGE_0_TO_2_V,
                            2500:ats.INPUT_RANGE_0_TO_2_V_5,
                            4000:ats.INPUT_RANGE_0_TO_4_V,
                            5000:ats.INPUT_RANGE_0_TO_5_V,
                            8000:ats.INPUT_RANGE_0_TO_8_V,
                            1e4:ats.INPUT_RANGE_0_TO_10_V,
                            1.6e4:ats.INPUT_RANGE_0_TO_16_V,
                            2e4:ats.INPUT_RANGE_0_TO_20_V,
                            3.2e4:ats.INPUT_RANGE_0_TO_32_V,
                            8e4:ats.INPUT_RANGE_0_TO_80_V},
                     "0m":{40:ats.INPUT_RANGE_0_TO_MINUS_40_MV,
                            80:ats.INPUT_RANGE_0_TO_MINUS_80_MV,
                            100:ats.INPUT_RANGE_0_TO_MINUS_100_MV,
                            160:ats.INPUT_RANGE_0_TO_MINUS_160_MV,
                            200:ats.INPUT_RANGE_0_TO_MINUS_200_MV,
                            250:ats.INPUT_RANGE_0_TO_MINUS_250_MV,
                            400:ats.INPUT_RANGE_0_TO_MINUS_400_MV,
                            500:ats.INPUT_RANGE_0_TO_MINUS_500_MV,
                            800:ats.INPUT_RANGE_0_TO_MINUS_800_MV,
                            1000:ats.INPUT_RANGE_0_TO_MINUS_1_V,
                            1600:ats.INPUT_RANGE_0_TO_MINUS_1600_MV,
                            2000:ats.INPUT_RANGE_0_TO_MINUS_2_V,
                            2500:ats.INPUT_RANGE_0_TO_MINUS_2_V_5,
                            4000:ats.INPUT_RANGE_0_TO_MINUS_4_V,
                            5000:ats.INPUT_RANGE_0_TO_MINUS_5_V,
                            8000:ats.INPUT_RANGE_0_TO_MINUS_8_V,
                            1e4:ats.INPUT_RANGE_0_TO_MINUS_10_V,
                            1.6e4:ats.INPUT_RANGE_0_TO_MINUS_16_V,
                            2e4:ats.INPUT_RANGE_0_TO_MINUS_20_V,
                            3.2e4:ats.INPUT_RANGE_0_TO_MINUS_32_V,
                            8e4:ats.INPUT_RANGE_0_TO_MINUS_80_V}}
    if not acquisition_mode in input_range_dic.keys():
        raise ValueError("""Possible modes: 'pm'(-value to + value), '0p'(0 to +value), '0m'(-value to 0)""")
    if board_kind=="ATS9462":
        if acquisition_mode == "pm":
            if 200 > input_range or 16000 < input_range :
                raise ValueError("ATS9462: Input range should be between +/-200mV and +/-16V")
        else:
            if 400 > input_range or 32000 < input_range:
                raise ValueError("ATS9462: Input range should be between 400mV and 32V")    
    if input_range in input_range_dic[acquisition_mode].keys():
        if not justcheck:
            return input_range_dic[acquisition_mode][input_range]
    else:
        if acquisition_mode == "pm":    
            raise ValueError("Possible values (pm mode, in mV): 20, 40, 50, 80, 100, 125, 200, 250, 400, 500, 800, 1000, 2000, 2500, 4000, 5000, 8000, 1e4, 2e4, 1.6e4, 2e4, 4e4")
        else:
            raise ValueError("Possible values (0p and 0m modes, in mV): 40, 80, 100, 160, 200, 250, 400, 500, 800, 1000, 1600, 2000, 2500, 4000, 5000, 8000, 1e4, 1.6e4, 2e4, 3.2e4, 8e4")


def convert_trigger_channel(trigger_channel, justcheck=False):
    """
    Translate the name of a channel on which to trigger into an hexadecimal understoodable by AlazarTech devices.
    Accepted channels are:
        - "A": channel A
        - "B": channel B
        - "ext": External channel
        - "": No channel

    Input:
        - trigger_channel (String): Name of the channel on which to trigger
        - justcheck (boolean): If True, just checks if trigger_channel is in the dictionary, nothing is output
    Output:
        converted_trigger_channel (hexadecimal): Input range understoodable by the Alazartech card (see atsapi.py)
    """
    _delayed_imports()
    trigger_channel_dic={"A":ats.TRIG_CHAN_A,
                         "B":ats.TRIG_CHAN_B,
                         "ext":ats.TRIG_EXTERNAL,
                         "":ats.TRIG_DISABLE}
    if trigger_channel in trigger_channel_dic.keys():
        if not justcheck:
            return trigger_channel_dic[trigger_channel]
    else:
        raise ValueError("""Possible channels : A, B, ext, '' """)


def convert_ext_trigger(range_ext_trigger, justcheck=False):
    """
    Translate the range (in V) of the external trigger into an hexadecimal understoodable by AlazarTech devices.
    Accepted ranges are:
        - 5: 5V
        - 2.5: 2.5V
        - 1: 1V
        - "TTL"

    Input:
        - range_ext_trigger (Float or String): Value of the range
        - justcheck (boolean): If True, just checks if trigger_channel is in the dictionary, nothing is output
    Output:
        converted_range_ext_trig (hexadecimal): range understoodable by the Alazartech card (see atsapi.py)
    """
    _delayed_imports()
    ext_trigger_dic={5:ats.ETR_5V,
                         1:ats.ETR_1V,
                         "TTL":ats.ETR_TTL,
                         2.5:ats.ETR_2V5}
    if range_ext_trigger in ext_trigger_dic.keys():
        if not justcheck:
            return ext_trigger_dic[range_ext_trigger]
    else:
        raise ValueError("""Possible channels : 5, 2.5, 1, 'TTL' """)


def convert_trigger_slope(trigger_slope, justcheck=False):
    """
    Translate the name of the trigger slope into a variable understoodable by the Alazartech card.
    Accepted channels are:
        - "ascend": when the signal goes from below the trigger to higher values
        - "descend": when the signal goes from higher values than the trigger to lower values.

    Input:
        - trigger_slope (String): Name of the slope type
        - justcheck (boolean): If True, just checks if trigger_slope is in the dictionary, nothing is output
    Output:
        converted_trigger_slope (hexadecimal): Slope understoodable by the Alazartech card (see atsapi.py)
    """
    _delayed_imports()
    trigger_slope_dic={"ascend":ats.TRIGGER_SLOPE_POSITIVE,
                         "descend":ats.TRIGGER_SLOPE_NEGATIVE}
    if trigger_slope in trigger_slope_dic.keys():
        if not justcheck:
            return trigger_slope_dic[trigger_slope]
    else:
        raise ValueError("""Possible trigger slopes: ascend, descend """)


def convert_trigger_level(trigger_level, input_range, justcheck=False):
    """
    Converts a trigger level in mV in a number between 0 and 255 understoodable by the board.
    For the board : 0 (255) is the minimum (maximum) value of the screen, 128 is the value in the middle of the screen (0 in pm mode)

    Input:
        - trigger_level (int): level (in mV) used to trigger
        - input_range (int): input range of the screen (in mV)
    """
    _delayed_imports()
    if abs(trigger_level)>input_range:
        raise ValueError("trigger level higher than input range")
    if not justcheck:
        return 128 + int(127 * float(trigger_level) / float(input_range))


def convert_active_channels(active_channels, board_kind, justcheck=False):
    """
    Takes a list of active channels amd returns an hexadecimal understoodable by Alazartech devices.
    active channels are channels that have to be measured.
    Possible Channels : A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P
    ATS9462, Possible Channels : A, B
    
    Input:
        - active_channels (List[String]): List of Channels
        - board_kind (String): Name of the board
        - justcheck (Boolean): If True, just checks if all the channels are in the dictionary, nothing is output
    Ouput:
        - channel_mask (Int): Hexadecimal describing the list of channels for the Alazartech Device  
    """
    _delayed_imports()

    channels_dic = {"A":ats.CHANNEL_A,
                    "B":ats.CHANNEL_B,
                    "C":ats.CHANNEL_C,
                    "D":ats.CHANNEL_D,
                    "E":ats.CHANNEL_E,
                    "F":ats.CHANNEL_F, 
                    "G":ats.CHANNEL_G, 
                    "H":ats.CHANNEL_H, 
                    "I":ats.CHANNEL_I, 
                    "J":ats.CHANNEL_J, 
                    "K":ats.CHANNEL_K, 
                    "L":ats.CHANNEL_L, 
                    "M":ats.CHANNEL_M, 
                    "N":ats.CHANNEL_N, 
                    "O":ats.CHANNEL_O,
                    "P":ats.CHANNEL_P}
    if board_kind == "ATS9462":
        channels = {"A":ats.CHANNEL_A, "B":ats.CHANNEL_B}
    
    channel_mask = 0
    try:
        for channel in active_channels:
            channel_mask |= channels[channel]

    except:
        if board_kind == "ATS9462":
            raise ValueError("""ATS9462, Possible Channels : A, B""")
        else:
            raise ValueError("""Possible Channels : A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P""")

    if not justcheck:
        return channel_mask


def convert_trigger_mode(trigger_mode, justcheck=False):
    """
    Translates the trigger mode into an hexadecimal understoodable by AlazarTech devices.
    Accepted trigger modes are:
        - "Traditional": (Unadvised) Acquires multiple records, one per trigger event. Supports low trigger repeat rates
        - "NPT": Acquires multiple records, one per trigger event, only post-trigger samples are possible. Supports high trigger repetition rates
        - "Continuous": Acquires a single gapless record. Doesn't wait for a trigger event. 
        - "Triggered": Acquires a single gaples record. Waits for a trigger event to occur.

    Input:
        - trigger_mode (String): Name of the trigger mode
        - justcheck (boolean): If True, just checks if trigger_mode is in the dictionary, nothing is output
    Output:
        converted_trigger_mode (hexadecimal): Trigger_mode understoodable by the Alazartech card (see atsapi.py)
    """
    trigger_mode_dic = {"Traditional":ats.ADMA_TRADITIONAL_MODE,
                        "NPT":ats.ADMA_NPT,
                        "Continuous":ats.ADMA_CONTINUOUS_MODE,
                        "Triggered":ats.ADMA_TRIGGERED_STREAMING}
    if trigger_mode not in trigger_mode_dic.keys():
        raise ValueError("""4 Possible modes : Traditional, NPT, Continuous, Triggered""")
    if not justcheck:
        return trigger_mode_dic[trigger_mode]


def convert_aux_io(aux_io_mode, aux_io_param, justcheck=False):
    """
    Defines the AUX I/O input/output
    Changing the AUX I/O connection means the board has to be reconfigured before next acquisition.

    Accepted modes are:
        - "AUX_OUT_TRIGGER": Outputs a signal that is high whenever data is being acquired
                             to on-board memory, and low otherwise. 
                             aux_io_param is ignored in this mode.
        - "AUX_IN_TRIGGER_ENABLE": Uses the edge of a pulse to the AUX I/O connector as an 
                                   AutoDMA trigger enable signal (different than an external trigger signal, see ATS-SDK-Guide).
                                   aux_io_param is either 0 ("ascend") or 1 ("descend")
        - "AUX_OUT_PACER": Output the sample clock divided by the value passed to the parameter argument
                           of AlazarConfigureAuxIO(). aux_io_param must be greater than 2.
        - "AUX_OUT_SERIAL_DATA": Use the AUX I/O connector as a general purpose digital output.
                                 aux_io_param specifies the TTL output level. 
                                 0 means TTL low whereas 1 means TTL high level.
        - "AUX_IN_AUXILIARY": Configure the AUX connector as a digital input.
                              aux_io_param is either 0 ("low") or 1 ("high") 
    
    Input:
        - aux_io_mode (String): Name of the Aux I/O connection
        - aux_io_param (Int): parameter for the connection

    Output:
        - ats_aux_io_mode (String): Name of the Aux I/O connection
        - ats_aux_io_param (Int): parameter for the connection
    """
    aux_io_modes = {"AUX_OUT_TRIGGER":ats.AUX_OUT_TRIGGER,
                    "AUX_IN_TRIGGER_ENABLE":ats.AUX_IN_TRIGGER_ENABLE,
                    "AUX_OUT_PACER":ats.AUX_OUT_PACER,
                    "AUX_OUT_SERIAL_DATA":ats.AUX_OUT_SERIAL_DATA,
                    "AUX_IN_AUXILIARY":ats.AUX_IN_AUXILIARY}
    modes_with_binary_param = ["AUX_IN_TRIGGER_ENABLE", "AUX_OUT_SERIAL_DATA", "AUX_IN_AUXILIARY"]
    if aux_io_mode not in aux_io_modes.keys():
        raise ValueError("""5 Possible Aux I/O modes: AUX_OUT_TRIGGER, AUX_IN_TRIGGER_ENABLE, AUX_OUT_PACER, AUX_OUT_SERIAL_DATA, AUX_IN_AUXILIARY""")
    aux_io_param_type = type(aux_io_param)
    if aux_io_param_type != int and aux_io_param_type != float :
        raise ValueError("""Aux I/O param should be int or float""")   
    else:
        ats_aux_io_mode = aux_io_modes[aux_io_mode]
        if aux_io_mode in modes_with_binary_param :
            if aux_io_param not in [0, 1]:
                aux_io_param = 0
                print("Incompatible aux_io_mode and aux_io_param, latter changed to 0")
            if aux_io_mode == "AUX_IN_TRIGGER_ENABLE":
                aux_io_param += 1
        elif aux_io_mode=="AUX_OUT_PACER":
            if aux_io_param < 2:
                aux_io_param = 2
                print("Incompatible aux_io_mode and aux_io_param, latter changed to 2")
    if not justcheck:
        return aux_io_modes[aux_io_mode], aux_io_param 


def convert_window_function(window_function_name, samplesPerWindow):
    """
    Returns an array to be used to "window" an acquisition before fft.
    See each function here : https://docs.scipy.org/doc/scipy/reference/signal.windows.html

    Input:
        - window_function_name (String): Name of the function to use 
        - samplesPerWindow (int): number of samples in the returned array

    Output:
        - window_function (Array): 1D array of samplesPerWindow points 
    """
    if window_function_name == "hanning":
        return signal.windows.hann(samplesPerWindow)
    if window_function_name == "hamming":
        return signal.windows.hamming(samplesPerWindow)
    if window_function_name == "blackman":
        return signal.windows.blackman(samplesPerWindow)
    if window_function_name == "bartlett":
        return signal.windows.bartlett(samplesPerWindow)
    if window_function_name == "kaiser":
        return signal.windows.kaiser(samplesPerWindow)
    if window_function_name == "flattop":
        return signal.windows.flattop(samplesPerWindow)
    if window_function_name == "uniform":
        return np.ones(samplesPerWindow)
    else:
        raise ValueError("Not a registered window function")


@register_instrument('AlazarTech9462', 'S902252')
class ATSBoard(BaseInstrument):
    def __init__(self,
                 systemId=1,
                 cardId=1, **kwarg):
        # import ats if not done
        _delayed_imports()
        
        # Defines systemId and CardId
        self.systemId = systemId
        self.cardId = cardId

        # Detect all Alazartech cards
        all_ATS = find_all_Alazartech(display=False)
        # Extract information about the wanted board
        try:
            board_info = all_ATS[2][self.systemId][1][self.cardId]
            self.board_info = board_info

        except:
                raise IndexError('The device requested is not there.')
        # Board
        board = ats.Board(systemId, cardId)
        self._board = board
        # board is configured if no parameters were changed since last run of ConfigureBoard
        self._boardConfigured = False
        self._initialized = False

        self.buffers = []
        self.data = {"t":[], "A":[], "B":[]}
        self.channel_count = 2

        self._NPTbuffersPerAcquisition = 1
        self._TRIGbuffersPerRecord = 1

        self._TRIGsamplesPerBuffer = 1
        self._NPTsamplesPerRecord = 1
        
        self._NPTrecordsPerBuffer = 1

        self.was_continuous = False

        super(ATSBoard, self).__init__(**kwarg)


    def idn(self):
        """
        Returns information about the type of card used, and the PCB, CPLD, FPGA versions
        """
        return "Kind: "+self.board_info["Kind"]+", PCBrevision: "+self.board_info["PCBrevision"]+", CPLDversion:"+self.board_info["CPLDversion"]+",FPGAversion: "+self.board_info["FPGAversion"]

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        """
        Returns the header at the beginning of any file saving data acquired using the acquisition card   
        """
        extra = ['Alazartech_type: '+self.board_info["Kind"],
                 "PCBrevision: "+str(self.board_info["PCBrevision"]),
                 "CPLDversion:"+str(self.board_info["CPLDversion"]),
                 "FPGAversion: "+str(self.board_info["FPGAversion"])]
        base = self._conf_helper('trigger_mode',
                                 'acquisition_length_sec',
                                 'samples_per_record',
                                 'sample_rate',
                                 'clock_type',
                                 'acquisition_mode', 
                                 'input_range',
                                 'trigger_channel_1', 
                                 'trigger_level_1',
                                 'trigger_slope_1',
                                 'trigger_channel_2', 
                                 'trigger_level_2',
                                 'trigger_slope_2',
                                 'bw_limited_a',
                                 'bw_limited_b',
                                 'trigger_delay',
                                 'active_channels')
        header = ["acquisition_number\ttime_in_s\t"]
        
        for channel in self.active_channels.get():
            header[0] += channel + "\t"

        if self.trigger_mode.get()=="NPT":
            read_dims = ['readback numpy shape for line part: '+(', '.join([str(self.nbwindows.get()), str(self.samples_per_record.get())]))]
            return extra+base+read_dims+header
        # else:
        #     read_dims = ['readback numpy shape for line part: '+(', '.join(["1", str(self.samples_per_record.get())]))]
        return extra+base+header

    def _psd_end_freq_checkdev(self, val):
        self._psd_end_freq.check(val)

    def _psd_end_freq_setdev(self, val):
        if val <= self._ext_sample_rate.get()/2.:
            span = float(self._psd_span.get())
            if val - span < 0:
                raise ValueError("fmin below 0")
            else:
                self._psd_end_freq.set(val)
                self._psd_center_freq.set(val-span/2.)
                self._psd_start_freq.set(val-span)
        else:
            raise ValueError("fmax too high, increase sample_rate")
    
    def _psd_end_freq_getdev(self):
        """
        Defines the maximum frequency at which to show PSD/FFT.
        Must be below sample_rate/2 (Shannon criterium).
        Must be greater than span (otherwise minimum frequency would be below 0)
        Modifying this maximum frequency modifies the minimum frequency and the center frequency at which to show FFT/PSD:
            - Minimum frequency set to psd_end_freq-span
            - Center frequency set to psd_end_freq-span/2

        Input:
            - psd_end_freq (float): Maximum frequency at which to compute PSD/FFT
        """
        return self._psd_end_freq.get()


    def _psd_start_freq_checkdev(self, val):
        self._psd_start_freq.check(val)

    def _psd_start_freq_setdev(self, val):
        self.psd_end_freq.set(val+self._psd_span.get())
    
    def _psd_start_freq_getdev(self):
        """
        Defines the minimum frequency at which to show PSD/FFT.
        Must be below sample_rate/2 - span (Shannon criterium).
        Must be greater than 0
        Modifying this maximum frequency modifies the center frequency and the maximum frequency at which to show FFT/PSD:
            - Center frequency set to psd_start_freq + span/2
            - Maximum frequency set to psd_start_freq + span

        Input:
            - psd_start_freq (float): Minimum frequency at which to show PSD/FFT
        """
        return self._psd_start_freq.get()


    def _psd_center_freq_checkdev(self, val):
        self._psd_center_freq.check(val)

    def _psd_center_freq_setdev(self, val):
        self.psd_end_freq.set(val+float(self._psd_span.get())/2)
    
    def _psd_center_freq_getdev(self):
        """
        Defines the center frequency at which to show PSD/FFT.
        Must be below sample_rate/2 - span/2 (Shannon criterium).
        Must be greater than span/2
        Modifying this center frequency modifies the minimum frequency and the maximum frequency at which to show FFT/PSD:
            - Minimum frequency set to psd_center_freq - span/2
            - Maximum frequency set to psd_center_freq + span/2

        Input:
            - psd_center_freq (float): Center frequency at which to show PSD/FFT
        """
        return self._psd_center_freq.get()


    def _psd_span_checkdev(self, val):
        self._psd_span.check(val)

    def _psd_span_setdev(self, val):
        if val > self._ext_sample_rate.get()/2:
            raise ValueError("span too big, increase sample_rate")
        elif val <= 0:
            raise ValueError("span should be strictly greater than 0")
        else:
            self._psd_span.set(val)
            self.psd_end_freq.set(val)

    def _psd_span_getdev(self):
        """
        Defines the frequency range at which to show PSD/FFT.
        Must be below sample_rate/2 (Shannon criterium).
        Must be strictly greater than 0.
        Modifying this frequeny range modifies the minimum, center and maximum frequency at which to show FFT/PSD:
            - Minimum frequency set to 0
            - Center frequency set to span/2
            - Maximum frequency set to span

        Input:
            - psd_span (float): Frequency range at which to show PSD/FFT
        """
        return self._psd_span.get()


    def _samples_per_record_checkdev(self, val):
        self._samples_per_record.check(val)

    def _samples_per_record_setdev(self, val):
        self._samples_per_record.set(val)
        self._acquisition_length_sec.set(float(val)/self._ext_sample_rate.get())
        self._psd_fft_lines.set(val)
        self._psd_linewidth.set(1./self._acquisition_length_sec.get())
        self.psd_span.set(self._ext_sample_rate.get()/2.)

    def _samples_per_record_getdev(self):
        """
        Changing the number of samples per record changes the duration of the acquisition (acquisition = samples_per_record/sample_rate)
        It also impacts the computation of the FFT/PSD:
            - number of points for which FFT/PSD is computed always equals samples_per_record
            - frequency difference two frequencies at which FFT/PSD is computed always equals 1/acquisition
            - span of frequencies shown is set to sample_rate/2 (shannon), setting the start frequency to 0, the end frequency to sample_rate/2 and the center frequency to sample_rate/4.
        
        Input:
            - samples_per_record (int): Number of samples taken after each trigger. 
        """
        return self._samples_per_record.get()


    def _acquisition_length_sec_checkdev(self, val):
        self._acquisition_length_sec.check(val)

    def _acquisition_length_sec_setdev(self, val):
        self.samples_per_record.set(int(float(val)*self._ext_sample_rate.get()))

    def _acquisition_length_sec_getdev(self):
        """
        Changing the duration of an acquisition changes the number of samples per record (samples_per_record = sample_rate * acquisition)
        It also impacts the computation of the FFT/PSD:
            - number of points for which FFT/PSD is computed always equals samples_per_record
            - frequency difference two frequencies at which FFT/PSD is computed always equals 1/acquisition
            - span of frequencies shown is set to sample_rate/2 (shannon), setting the start frequency to 0, the end frequency to sample_rate/2 and the center frequency to sample_rate/4.
        
        Input:
            - acquisition_length_sec (float): Duration of an acquisition after a trigger (in s).
        """
        return self._acquisition_length_sec.get()


    def _psd_linewidth_checkdev(self, val):
        self._psd_linewidth.check(val)

    def _psd_linewidth_setdev(self, val):
        self.acquisition_length_sec.set(1./float(val))
    
    def _psd_linewidth_getdev(self):
        """
        Difference between two frequencies at which the FFT/PSD is computed.
        Changing the linewidth changes the length of the acquisition, as linewidth = 1/acquisition
        Changing the duration of an acquisition changes the number of samples per record (samples_per_record = sample_rate * acquisition)
        It also impacts the computation of the FFT/PSD:
            - number of points for which FFT/PSD is computed always equals samples_per_record
            - frequency difference two frequencies at which FFT/PSD is computed always equals 1/acquisition
            - span of frequencies shown is set to sample_rate/2 (shannon), setting the start frequency to 0, the end frequency to sample_rate/2 and the center frequency to sample_rate/4.

        Input:
            - linewidth (float): Difference between two frequencies at which the FFT/PSD is computed.

        """
        return self._psd_linewidth.get()


    def _psd_fft_lines_checkdev(self, val):
        self._psd_fft_lines.check(val)

    def _psd_fft_lines_setdev(self, val):
        self.samples_per_record.set(val)
    
    def _psd_fft_lines_getdev(self):
        """
        Number of points at which the FFT/PSD is computed
        Always equal to samples_per_record.
        Changing the number of samples per record changes the duration of the acquisition (acquisition = samples_per_record/sample_rate)
        It also impacts the computation of the FFT/PSD:
            - frequency difference two frequencies at which FFT/PSD is computed always equals 1/acquisition
            - span of frequencies shown is set to sample_rate/2 (shannon), setting the start frequency to 0, the end frequency to sample_rate/2 and the center frequency to sample_rate/4.

        Input:
            - acquisition_length_sec (float): Duration of an acquisition after a trigger (in s).
        """
        return self._psd_fft_lines.get()


    def _sample_rate_checkdev(self, val):
        convert_sample_rate(val, self.board_info["Kind"], self._ext_clock_type.get(), justcheck=True)

    def _sample_rate_setdev(self, val):
        self._ext_sample_rate.set(val)
        self._ats_sample_rate.set(convert_sample_rate(val,
                                                      self.board_info["Kind"],
                                                      self._ext_clock_type.get()))
        self.acquisition_length_sec.set(self.acquisition_length_sec.get())
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account") 

    def _sample_rate_getdev(self):
        """
        Changing the sample rate doesn't change the duration of the acquistion, but it changes the number of samples per record.
        Changing the sampling rate means the board has to be reconfigured before next acquisition.
        Changing the sample rate impacts the computation of the FFT/PSD:
            - number of points for which FFT/PSD is computed always equals samples_per_record
            - frequency difference two frequencies at which FFT/PSD is computed always equals 1/acquisition
            - span of frequencies shown is set to sample_rate/2 (shannon), setting the start frequency to 0, the end frequency to sample_rate/2 and the center frequency to sample_rate/4.
        
        Possible sampling rates:
            - in INT clock mode: For all boards: [1e3, 2e3, 5e3, 10e3, 20e3, 50e3, 100e3, 200e3, 500e3, 1e6, 2e6, 5e6, 10e6, 20e6, 25e6, 50e6, 100e6,
              125e6, 160e6, 180e6, 200e6, 250e6, 400e6, 500e6, 800e6, 1e9, 1.2e9, 1.5e9, 1.6e9, 1.8e9, 2e9, 2.4e9, 3e9, 3.6e9, 4e9]
                                For ATS9462: sample_rate < 180MS/s
            - in EXT_10MHz clock mode: (ATS9462) sample rate betweem 150 MS/s and 180MS/s
                                  (see ATS-SDK for other boards)
            - in EXT, slow_EXT, fast_EXT clock modes: sample rate is defined by the user
        
        Clock modes is stored in device clock_type
        
        Input:
            - sample_rate (int): Number of Samples Per Second
        """
        return self._ext_sample_rate.get()


    def _clock_typecheckdev(self, val):
        convert_clock_type(val, justcheck=True)

    def _clock_type_setdev(self, val):
        self._ext_clock_type.set(val)
        self._ats_clock_type.set(convert_clock_type(val))
        self.sample_rate.set(self.sample_rate.get())
        self._boardConfigured = False    
        print("Run ConfigureBoard to take modification into account")    
    
    def _clock_type_getdev(self):
        """
        Changing the clock type changes the sample rate.
        Changing the clock type means the board has to be reconfigured before next acquisition.

        Possible clock types:
        - "INT": INTERNAL, only certain sampling can be realized
        - "EXT": EXTERNAL, sampling is realized by an external clock
        - "slow_EXT": sampling is realized by an external clock with sampling rate below 1MHz
        - "fast_EXT": sampling is realized by an external clock with sampling rate above 1MHz
        - "EXT_10MHz": by using an external clock at 10MHz, sampling rate (for ATS9462) between 150MHz and 180MHz can be realized(1MHz step) 
        
        Input:
            - clock_type (String): Name of the clock type
        """
        return self._ext_clock_type.get()


    def _input_range_checkdev(self, val):
        convert_input_range(self._acquisition_mode.get(), val, self.board_info["Kind"], justcheck=True)

    def _input_range_setdev(self, val):
        self._ext_input_range.set(val)
        self._ats_input_range.set(convert_input_range(self._acquisition_mode.get(), val, self.board_info["Kind"]))
        self._ats_trigger_level_1.set(convert_trigger_level(self.trigger_level_1.get(), val))
        self._ats_trigger_level_2.set(convert_trigger_level(self.trigger_level_2.get(), val))
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _input_range_getdev(self):
        """
        Defines the input range of the screen.
        Changing the input range means the board has to be reconfigured before next acquisition.

        If the acquisition mode is in:
            -"pm" mode, input range is [-input_range; input_range]
            Possible values (in mV): [20, 40, 50, 80, 100, 125, 200, 250, 400, 500, 800, 1000, 2000, 2500, 4000, 5000, 8000, 1e4, 2e4, 1.6e4, 2e4, 4e4]
            -"0p" mode, input range is [0; input_range]
            Possible values (in mV): [40, 80, 100, 160, 200, 250, 400, 500, 800, 1000, 1600, 2000, 2500, 4000, 5000, 8000, 1e4, 1.6e4, 2e4, 3.2e4, 8e4]
            -"0m" mode, input range is [-input_range; 0]
            Possible values (in mV): [40, 80, 100, 160, 200, 250, 400, 500, 800, 1000, 1600, 2000, 2500, 4000, 5000, 8000, 1e4, 1.6e4, 2e4, 3.2e4, 8e4]
        Acquisition mode is defined by device acquisition_mode.
        
        ATS9462:
            - "pm": Input range should be between +/-200mV and +/-16V
            - "0p" or "0m": Input range should be between 400mV and 32V
        See ATS-SDK-Guide for other cards

        Input:
            - input_range (int): Input range in mV
        """
        return self._ext_input_range.get()


    def _acquisition_mode_checkdev(self, val):
        self._acquisition_mode.check(val)
    
    def _acquisition_mode_setdev(self, val):
        self._acquisition_mode.set(val)
        self.input_range.set(self.input_range.get())
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _acquisition_mode_getdev(self):
        """
        Changing acquisition_mode changes input_range
        Changing the acquisition_mode means the board has to be reconfigured before next acquisition.

        If the acquisition mode is in:
            -"pm" mode, input range is [-input_range; input_range]
            Possible values (in mV): [20, 40, 50, 80, 100, 125, 200, 250, 400, 500, 800, 1000, 2000, 2500, 4000, 5000, 8000, 1e4, 2e4, 1.6e4, 2e4, 4e4]
            -"0p" mode, input range is [0; input_range]
            Possible values (in mV): [40, 80, 100, 160, 200, 250, 400, 500, 800, 1000, 1600, 2000, 2500, 4000, 5000, 8000, 1e4, 1.6e4, 2e4, 3.2e4, 8e4]
            -"0m" mode, input range is [-input_range; 0]
            Possible values (in mV): [40, 80, 100, 160, 200, 250, 400, 500, 800, 1000, 1600, 2000, 2500, 4000, 5000, 8000, 1e4, 1.6e4, 2e4, 3.2e4, 8e4]
        Acquisition mode is defined by device acquisition_mode.
        
        ATS9462:
            - "pm": Input range should be between +/-200mV and +/-16V
            - "0p" or "0m": Input range should be between 400mV and 32V
        See ATS-SDK-Guide for other cards

        Input:
            - acquisition_mode (String): Defines the acquisition window
        """
        return self._acquisition_mode.get()        


    def _impedance_checkdev(self, val):
        convert_impedance(val, justcheck=True)

    def _impedance_setdev(self, val):
        self._ext_impedance.set(val)
        self._ats_impedance.set(convert_impedance(val))
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _impedance_getdev(self):
        """
        Defines the impedance (in Ohm).
        Possible values (in Ohm):
            - 10**6
            - 50
            - 75
            - 300

        Input:
            - impedance: impedance value in Ohm
       """
        return self._ext_impedance.get()


    def range_ext_trigger_checkdev(self, val):
        convert_ext_trigger(val, justcheck=True)

    def range_ext_trigger_setdev(self, val):
        self._ext_range_ext_trigger.set(val)
        self._ats_range_ext_trigger.set(convert_ext_trigger(val))
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _range_ext_trigger_getdev(self):
        """
        Defines the range of the external trigger
        Changing the range of external trigger means the board has to be reconfigured before next acquisition.

        Accepted ranges are:
            - 5: 5V
            - 2.5: 2.5V
            - 1: 1V
            - "TTL"

        Input:
            - range_ext_trigger (Float or String): Range of the external trigger
        """
        return self._ext_range_ext_trigger.get()


    def _trigger_channel_1_checkdev(self, val):
        convert_trigger_channel(val, justcheck=True)

    def _trigger_channel_1_setdev(self, val):
        self._ext_trigger_channel_1.set(val)
        self._ats_trigger_channel_1.set(convert_trigger_channel(val))
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _trigger_channel_1_getdev(self):
        """
        Defines the port to trigger on channel 1
        Changing the port to trigger on channel 1 means the board has to be reconfigured before next acquisition.

        Accepted channels are:
            - "A": channel A
            - "B": channel B
            - "ext": External channel
            - "": No channel

        Input:
            - trigger_channel_1 (String): Name of the port on which to trigger
        """
        return self._ext_trigger_channel_1.get()


    def _trigger_channel_2_checkdev(self, val):
        convert_trigger_channel(val, justcheck=True)

    def _trigger_channel_2_setdev(self, val):
        self._ext_trigger_channel_2.set(val)
        self._ats_trigger_channel_2.set(convert_trigger_channel(val))
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _trigger_channel_2_getdev(self):
        """
        Defines the port to trigger on channel 2
        Changing the port to trigger on channel 2 means the board has to be reconfigured before next acquisition.

        Accepted channels are:
            - "A": channel A
            - "B": channel B
            - "ext": External channel
            - "": No channel

        Input:
            - trigger_channel_2 (String): Name of the port on which to trigger
        """
        return self._ext_trigger_channel_2.get()


    def _trigger_level_1_checkdev(self, val):
        convert_trigger_level(val, self._ext_input_range, justcheck=True)

    def _trigger_level_1_setdev(self, val):
        self._ext_trigger_level_1.set(val)
        if self._ext_trigger_channel_1.get()=="ext":
            self._ats_trigger_level_1.set(convert_trigger_level(val, self._ext_range_ext_trigger.get()*1000))
        else:
            self._ats_trigger_level_1.set(convert_trigger_level(val, self._ext_input_range.get()))
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _trigger_level_1_getdev(self):
        """
        Defines the trigger level on channel 1 in mV
        Changing the level to trigger on channel 1 means the board has to be reconfigured before next acquisition.
        Absolute value of trigger level should not be bigger than the input range
        
        Input:
            - trigger_level_1 (int): level (in mV) used to trigger
        """
        return self._ext_trigger_level_1.get()


    def _trigger_level_2_checkdev(self, val):
        convert_trigger_level(val, self._ext_input_range.get(), justcheck=True)

    def _trigger_level_2_setdev(self, val):
        self._ext_trigger_level_2.set(val)
        if self._ext_trigger_channel_2.get()=="ext":
            self._ats_trigger_level_2.set(convert_trigger_level(val, self._ext_range_ext_trigger.get()*1000))
        else:
            self._ats_trigger_level_2.set(convert_trigger_level(val, self._ext_input_range.get()))
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _trigger_level_2_getdev(self):
        """
        Defines the trigger level on channel 2 in mV
        Changing the level to trigger on channel 2 means the board has to be reconfigured before next acquisition.
        Absolute value of trigger level should not be bigger than the input range
        
        Input:
            - trigger_level_2 (int): level (in mV) used to trigger
        """
        return self._ext_trigger_level_2.get()


    def _trigger_slope_1_checkdev(self, val):
        convert_trigger_slope(val, justcheck=True)

    def _trigger_slope_1_setdev(self, val):
        self._ext_trigger_slope_1.set(val)
        self._ats_trigger_slope_1.set(convert_trigger_slope(val))
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _trigger_slope_1_getdev(self):
        """
        Defines the slope of the trigger for channel 1
        Changing the trigger slope on channel 1 means the board has to be reconfigured before next acquisition.

        Accepted channels are:
            - "ascend": Crosses the trigger level from down to up
            - "descend": Crosses the trigger level from up to down

        Input:
            - trigger_slope_1 (String): Name of the trigger slope
        """
        return self._ext_trigger_slope_1.get()


    def _trigger_slope_2_checkdev(self, val):
        convert_trigger_slope(val, justcheck=True)

    def _trigger_slope_2_setdev(self, val):
        self._ext_trigger_slope_2.set(val)
        self._ats_trigger_slope_2.set(convert_trigger_slope(val))
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _trigger_slope_2_getdev(self):
        """
        Defines the slope of the trigger for channel 2
        Changing the trigger slope on channel 2 means the board has to be reconfigured before next acquisition.

        Accepted channels are:
            - "ascend": Crosses the trigger level from down to up
            - "descend": Crosses the trigger level from up to down

        Input:
            - trigger_slope_2 (String): Name of the trigger slope
        """
        return self._ext_trigger_slope_2.get()


    def _active_channels_checkdev(self, val):
        convert_active_channels(val, self.board_info["Kind"], justcheck=True)

    def _active_channels_setdev(self, val):
        self._ext_active_channels.set(val)
        self._ats_active_channels.set(convert_active_channels(val, self.board_info["Kind"]))
        self._initialized = False

    def _active_channels_getdev(self):
        """
        Active channels are channels to be measured.
        Possible Channels : A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P
        ATS9462, Possible Channels : A, B
    
        Input:
            - active_channels (List[String]): List of Channels be measured
        """
        return self._ext_active_channels.get()


    def _trigger_mode_checkdev(self, val):
        convert_trigger_mode(val, justcheck=True)

    def _trigger_mode_setdev(self, val):
        self._ext_trigger_mode.set(val)
        self._ats_trigger_mode.set(convert_trigger_mode(val))

    def _trigger_mode_getdev(self):
        """
        Accepted trigger modes are:
            - "Traditional": (Unadvised) Acquires multiple records, one per trigger event. Supports low trigger repeat rates
            - "NPT": Acquires multiple records, one per trigger event, only post-trigger samples are possible. Supports high trigger repetition rates
            - "Continuous": Acquires a single gapless record. Doesn't wait for a trigger event. 
            - "Triggered": Acquires a single gaples record. Waits for a trigger event to occur.

        Input:
            - trigger_mode (String): Name of the trigger mode
        """
        return self._ext_trigger_mode.get()

    def _aux_io_mode_checkdev(self, val):
        convert_aux_io(val, self._ext_aux_io_param.get(), justcheck=True)

    def _aux_io_mode_setdev(self, val):
        self._ext_aux_io_mode.set(val)
        self._ats_aux_io_mode.set(convert_aux_io(val, self.aux_io_param.get())[0])
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _aux_io_mode_getdev(self):
        """
        Defines the AUX I/O input/output
        Changing the AUX I/O connection means the board has to be reconfigured before next acquisition.

        Accepted modes are:
            - "AUX_OUT_TRIGGER": Outputs a signal that is high whenever data is being acquired
                                 to on-board memory, and low otherwise. 
                                 aux_io_param is ignored in this mode.
            - "AUX_IN_TRIGGER_ENABLE": Uses the edge of a pulse to the AUX I/O connector as an 
                                       AutoDMA trigger enable signal (different than an external trigger signal, see ATS-SDK-Guide).
                                       aux_io_param is either 0 ("ascend") or 1 ("descend")
            - "AUX_OUT_PACER": Output the sample clock divided by the value passed to the parameter argument
                               of AlazarConfigureAuxIO(). aux_io_param must be greater than 2.
            - "AUX_OUT_SERIAL_DATA": Use the AUX I/O connector as a general purpose digital output.
                                     aux_io_param specifies the TTL output level. 
                                     0 means TTL low whereas 1 means TTL high level.
            - "AUX_IN_AUXILIARY": Configure the AUX connector as a digital input.
                                  Second parameter is either "high" or "low" 

        Input:
            - trigger_channel_2 (String): Name of the port on which to trigger
        """
        return self._ext_aux_io_mode.get()

    def _aux_io_param_checkdev(self, val):
        convert_aux_io(self._ext_aux_io_mode.get(), val, justcheck=True)

    def _aux_io_param_setdev(self, val):
        self._ext_aux_io_param.set(val)
        self._ats_aux_io_param.set(convert_aux_io(self._ext_aux_io_mode.get(), val)[1])
        self._boardConfigured = False
        print("Run ConfigureBoard to take modification into account")

    def _aux_io_param_getdev(self):
        """
        Defines the AUX I/O input/output parameter
        Changing the parameter of the AUX I/O connection means the board has to be reconfigured before next acquisition.

        Function of the modes, the param should be:
            - "AUX_OUT_TRIGGER": aux_io_param is ignored in this mode.
            - "AUX_IN_TRIGGER_ENABLE": aux_io_param is either 0 ("ascend") or 1 ("descend")
            - "AUX_OUT_PACER": aux_io_param must be greater than 2.
            - "AUX_OUT_SERIAL_DATA": aux_io_param specifies the TTL output level. 
                                     0 means TTL low whereas 1 means TTL high level.
            - "AUX_IN_AUXILIARY": Configure the AUX connector as a digital input.
                                  Second parameter is either 0 ("low") or 1 ("high") 

        Input:
            - aux_io_param (String): Name of the parameter of the AUX I/O connection
        """
        return self._ext_aux_io_param.get()


    def ConfigureBoard(self):
        """
        Configures the Board
        Should be run before any Acquisition
        """
        # Board is configured only if no parameters have been changed since last configuration
        if ((not self._boardConfigured or self.inmemory["trigger_delay"]!=self.trigger_delay.get())
                                       or self.inmemory["bw_a"]!=self.bw_limited_a.get()) or self.inmemory["bw_b"]!=self.bw_limited_b.get():

            # Decimation depends on the clock type
            if self.clock_type.get()=="EXT_10MHz":
                decimation = 9
            else:
                decimation = 0
            
            # Generate the sample rate
            self._board.setCaptureClock(self._ats_clock_type.get(),
                                        self._ats_sample_rate.get(),
                                        ats.CLOCK_EDGE_RISING,
                                        int(decimation))
            
            # Defines acquisition window on channel A
            self._board.inputControlEx(ats.CHANNEL_A,
                                       ats.DC_COUPLING,
                                       self._ats_input_range.get(),
                                       self._ats_impedance.get())
            
            # TODO: Select channel A bandwidth limit as required.
            self._board.setBWLimit(ats.CHANNEL_A,
                                   self.bw_limited_a.get())
            
            
            # Defines acquisition on window channel B
            self._board.inputControlEx(ats.CHANNEL_B,
                                       ats.DC_COUPLING,
                                       self._ats_input_range.get(),
                                       self._ats_impedance.get())
            
            # TODO: Select channel B bandwidth limit as required.
            self._board.setBWLimit(ats.CHANNEL_B,
                                   self.bw_limited_b.get())
            
            # TODO: Select trigger inputs and levels as required.
            trig_op = self.trigger_to_use.get()
            if trig_op=="1":
                ats_trig_op = ats.TRIG_ENGINE_OP_J
                self.trigger_channel_2.set("")
            elif trig_op=="2":
                ats_trig_op = ats.TRIG_ENGINE_OP_K
                self.trigger_channel_1.set("")
            elif trig_op=="1or2":
                ats_trig_op = ats.TRIG_ENGINE_OP_J_OR_K

            self.trigger_level_1.set(self._ext_trigger_level_1.get())
            self.trigger_level_2.set(self._ext_trigger_level_2.get())

            self._board.setTriggerOperation(ats_trig_op,
                                            ats.TRIG_ENGINE_J,
                                            self._ats_trigger_channel_1.get(),
                                            self._ats_trigger_slope_1.get(),
                                            self._ats_trigger_level_1.get(),
                                            ats.TRIG_ENGINE_K,
                                            self._ats_trigger_channel_2.get(),
                                            self._ats_trigger_slope_2.get(),
                                            self._ats_trigger_level_2.get())

            # TODO: Select external trigger parameters as required.
            self._board.setExternalTrigger(ats.DC_COUPLING,
                                           ats.ETR_5V)

            # TODO: Set trigger delay as required.
            triggerDelay_samples = int(self.trigger_delay.get() * self._ext_sample_rate.get() + 0.5)
            self._board.setTriggerDelay(triggerDelay_samples)

            # TODO: Set trigger timeout as required.
            #
            # NOTE: The board will wait for a for this amount of time for a
            # trigger event.  If a trigger event does not arrive, then the
            # board will automatically trigger. Set the trigger timeout value
            # to 0 to force the board to wait forever for a trigger event.
            #
            # IMPORTANT: The trigger timeout value should be set to zero after
            # appropriate trigger parameters have been determined, otherwise
            # the board may trigger if the timeout interval expires before a
            # hardware trigger event arrives.
            self._board.setTriggerTimeOut(0)

            # Configure AUX I/O connector as required
            self._board.configureAuxIO(self._ats_aux_io_mode.get(),
                                       self._ats_aux_io_param.get())

            self._board.setParameter(0, # U8 -- channel Id (not used)
                                     ats.SET_DATA_FORMAT, # U32 -- parameter to set
                                     0) # long -- value (0 = unsigned, 1 = signed));

            # Update the informations of the board
            self.board_info = get_board_info(self._board)

            # Board is now considered as configured:
            self.inmemory = {"trigger_delay":self.trigger_delay.get(),
                             "bw_a":self.bw_limited_a.get(),
                             "bw_b":self.bw_limited_b.get()}
            self._boardConfigured = True


    def _async_trig(self):
        """
        """
        # Configure board
        self.ConfigureBoard()
        
        # Get acquisition mode
        trig_mode = self.trigger_mode.get()
        
        # Get channels to measure
        channels = self._ext_active_channels.get()
        channel_count = len(channels)
        self.channel_count = channel_count

        # Maximum Number of Samples in Memory and number of bytes per sample
        memorySize_samples = self.board_info["MemorySize"]
        bytesPerSample = self.board_info["BytesPerSample"]  # bytes per sample
        # No pre-trigger samples in NPT modes (arbitrarily set to 0 for the other modes)
        preTriggerSamples = 0
        # C Sample Type 
        c_sample_type = self.board_info["C_sample_type"]
        # TODO: Select number of DMA buffers to allocate
        buffer_count = self.buffer_count.get()
        self.buffers = []
        
        if trig_mode == "Triggered" or trig_mode == "Continuous" or trig_mode=="Traditional":
            print(trig_mode)
            # Triggered Streaming AutoDMA:
            # Acquire a single gapless record spanning one or more DMA buffers
            # Waits for the trigger event before acquiring the record
            # Define the number of DMA buffers for acquisition taking into account the max size of a buffer
            wanted_SamplesPerRecord = self.samples_per_record.get()  # samples per record asked by the user
            max_SamplesPerBuffer = self.max_bytes_per_buffer.get() / bytesPerSample / channel_count
            buffersPerRecord =  int(wanted_SamplesPerRecord/max_SamplesPerBuffer) + 1  # number of DMA buffers to use
            self._TRIGbuffersPerRecord = buffersPerRecord
            # Define number of samples per buffer
            samplesPerBuffer = int(wanted_SamplesPerRecord/buffersPerRecord)
            self._TRIGsamplesPerBuffer = samplesPerBuffer
            bytesPerBuffer =  bytesPerSample * samplesPerBuffer * channel_count

            # Update the number of samples
            samplesPerRecord = samplesPerBuffer * buffersPerRecord
            output_info = [self.psd_span.get(), self.psd_end_freq.get()]
            self.samples_per_record.set(samplesPerRecord)
            try:
                self.psd_span.set(output_info[0])
                self.psd_end_freq.set(output_info[1])
            except:
                print("Warning: Change in psd_samples_per_record induced psd_span and psd_end_freq are no longer valid. psd_span and psd_end_freq set to sample_rate/2")

            # Create DMA buffers of size bytesPerBuffer
            # An application should supply at least two buffers to a board
            # This allows the board to fill one buffer while the application consumes the other.
            # Acquisition continues indefinitely as long as application consume buffers faster than the board can fill them
            # Board continues to acquire data until it fills is on-board memory (aborts acquisition and reports a buffer overflow error).
            # Play on buffer_count and timeout to make it happen
            for i in range(buffer_count):
                self.buffers.append(ats.DMABuffer(self._board.handle, c_sample_type, bytesPerBuffer))

            # Configure the board to make a Triggered Streaming AutoDMA acquisition
            self._board.beforeAsyncRead(self._ats_active_channels.get(),  # enabled channels
                                        0,  # No Pre-Trigger Samples
                                        samplesPerBuffer,  # samplesPerRecord = samplesPerBuffer bc 1 records per Buffer
                                        1,  # 1 records per Buffer
                                        0x7FFFFFFF, # infinite number of buffers per trigger
                                        ats.ADMA_EXTERNAL_STARTCAPTURE | self._ats_trigger_mode.get())
            if trig_mode == "Continuous":
                self.was_continuous = True

        elif trig_mode == "NPT":
            print(trig_mode)

            # TODO: Select the number of samples per record.
            postTriggerSamples = int(self.samples_per_record.get()/128) * 128
            self.samples_per_record.set(postTriggerSamples)
            print("NPT Trigger Mode : samples_per_record have to be multiple of 128. Set to :", postTriggerSamples)
            
            nbtriggers = self.nbwindows.get()

            # TODO: Select the number of buffers per acquisition.
            recordsPerBuffer = int(np.sqrt(nbtriggers))
            self._NPTrecordsPerBuffer = recordsPerBuffer
            
            # TODO: Select the number of records per DMA buffer.
            if recordsPerBuffer**2 == nbtriggers:
                buffersPerAcquisition = recordsPerBuffer
            else:
                buffersPerAcquisition = recordsPerBuffer + 1

            self._NPTbuffersPerAcquisition = buffersPerAcquisition
            recordsPerAcquisition = buffersPerAcquisition * recordsPerBuffer
            self.nbwindows.set(recordsPerAcquisition)
            print("Number of triggers should be a square. nbwindows set to :", recordsPerAcquisition)
            
            # Compute the number of bytes per record and per buffer

            samplesPerRecord = preTriggerSamples + postTriggerSamples
            self._NPTsamplesPerRecord = samplesPerRecord
            bytesPerRecord = bytesPerSample * samplesPerRecord
            bytesPerBuffer = bytesPerRecord * recordsPerBuffer * channel_count

            # Allocate DMA buffers
            for i in range(buffer_count):
                self.buffers.append(ats.DMABuffer(self._board.handle, c_sample_type, bytesPerBuffer))
            
            # Set the record size
            self._board.setRecordSize(preTriggerSamples, postTriggerSamples)

            # Configure the board to make an NPT AutoDMA acquisition
            self._board.beforeAsyncRead(self._ats_active_channels.get(),
                                        -preTriggerSamples,
                                        samplesPerRecord,
                                        recordsPerBuffer,
                                        recordsPerAcquisition,
                                        ats.ADMA_EXTERNAL_STARTCAPTURE | ats.ADMA_NPT)
            
        # Make buffers available to be filled by the board
        for buffer in self.buffers:
            self._board.postAsyncBuffer(buffer.addr, buffer.size_bytes)  # Done by calling postAsyncBuffer

        # Initialize data
        self.data = {"t":np.linspace(0, self.acquisition_length_sec.get(), samplesPerRecord),
                     "A":np.array([]),
                     "B":np.array([])}
        self._initialized = True
        print(self._initialized)
        self._board.startCapture()  # Arms the board to start the acquisition


    
    def get_data(self, data, active_channels, nbsamples, nbwindows):
        """
        Take a data dictionary {"t":[], "A":[], "B":[]}
        Returns an array composed of "t" in first column, followed by the active channels
        The returned array can be registered in a file with get

        Input:
            - data (Dict[String:Array]): Output of a readval/fetch
            - active_channels (List[String]): channels to be measured
        Output:
            - returned_data (Array): 2D arrays containing data  
        """
        returned_data_sample_number = []
        returned_data_time = []
        for i in range(nbwindows):
            returned_data_sample_number = np.concatenate((returned_data_sample_number, i*np.ones(nbsamples)), axis=0) 
            returned_data_time = np.concatenate((returned_data_time, data["t"]), axis=0)
        returned_data = [data[channel] for channel in active_channels]
        return [returned_data_sample_number, returned_data_time] + returned_data
    

    def get_screen_shift(self):
        """
        Returns the shift of the screen.
        If mode is "pm", the values are shifted by one time the zero value.
        If mode is "0p", there is no need to shift the values.
        If mode is "0m", values should be shifted by two times the zero value.
        
        Output:
            - screen_size (int): Size of the recording window
        """
        # If "pm" mode, screen_size = 2 * input_range
        acq_mode = self.acquisition_mode.get()
        if acq_mode=="pm": 
            return 1
        
        elif acq_mode=="0p":      
            return 0
        else:
            return 2


    def _readval_getdev(self):
        """
        Realizes a new trigger. Number of samples is possibly modified to take into account the maximum size of the buffers. We try
        Acquisition:
            - fills the "t" array of dictionnary data with samples_per_records samples between 0 and acquisition_length_sec.
            - fills the active_channels of data with samples_per_records number of samples.
        It first configures the board.
        The acquisition is a single trigger on the channels to be measured, defined in active_channels 
        
        Output:
            - data (Array): 2D array of size (len(active_channels)+1, samples_per_record)
        """
        print(self._initialized)
        print("Was Continuous", self.was_continuous)
        if self.trigger_mode.get()!="Triggered":
            self.trigger_mode.set("Triggered")
            self._initialized=False

        if self.was_continuous:
            _delayed_imports_done = False
            _delayed_imports()
            self._boardConfigured = False
            self._initialized = False
            self.was_continuous = False

        if not self._initialized:
            self._async_trig()
        # Get parameters for loop
        buffersPerRecord = self._TRIGbuffersPerRecord
        buffer_count = self.buffer_count.get()
        channels = self.active_channels.get()
        channel_count = self.channel_count
        samplesPerBuffer = self._TRIGsamplesPerBuffer
        screen_size = self.input_range.get()  # Size of the screen
        screen_shift = self.get_screen_shift()
        sample_type = self.board_info["Sample_type"]  # output data type
        zero_value = self.board_info["Zero_value"]  # zero for the output data
        timeout = self.timeout.get()  # timeout

        try:
            buffersCompleted = 0
            bytesTransferred = 0

            while buffersCompleted < buffersPerRecord:
                # Wait for the buffer at the head of the list of available
                # buffers to be filled by the board.
                buffer = self.buffers[buffersCompleted % buffer_count]
                self._board.waitAsyncBufferComplete(buffer.addr, timeout_ms=timeout)
                received_data = np.frombuffer(buffer.buffer, dtype=sample_type)
                for i in range(channel_count):
                    self.data[channels[i]] = np.concatenate((self.data[channels[i]], (received_data[i*samplesPerBuffer:(i+1)*samplesPerBuffer]-screen_shift*zero_value)/zero_value*screen_size), axis=0)
                buffersCompleted += 1
                bytesTransferred += buffer.size_bytes

                # Add the buffer to the end of the list of available buffers.
                self._board.postAsyncBuffer(buffer.addr, buffer.size_bytes)
        finally:
            self._board.abortAsyncRead()
            self._initialized = False

        return self.get_data(self.data, self.active_channels.get(), self.samples_per_record.get(), 1)


    def _readval_all_getdev(self):
        """
        Realizes multiple triggers:
            - fills the "t" array of dictionnary data with samples_per_records samples between 0 and acquisition_length_sec.
            - fills the active_channels of data with nbwindows records of samples_per_records number of samples.
        It first configures the board.
        The acquisition performs nbwindows triggers without reloading the data (see NPT trigger mode in ATS-SDK guide)
        That is faster than performing nbwindows times readval.
        
        Limitations:
            - Number of samples per record should be a multiple of 128.
            - To be faster and avoid overflow erros, triggers are span over multiple buffers, it is better if nbwindows is a square. 
              If nbwindows is not a square, it is set to int(sqrt(n))*(int(sqrt(n))+1) 

        Output:
            - data (Array): 2D array of size (nbwindows*len(active_channels)+1, samples_per_record)
                            1st line is time, nbwindows next lines are first active channel, and so on 
        """
        t0=time.time()
        print(self._initialized)
        if self.trigger_mode.get()!="NPT":
            self.trigger_mode.set("NPT")
            self._initialized=False

        if self.was_continuous:
            _delayed_imports_done = False
            _delayed_imports()
            self._boardConfigured = False
            self._initialized = False
            self.was_continuous = False

        if not self._initialized:
            print("Launched")
            self._async_trig()

        buffersPerAcquisition = self._NPTbuffersPerAcquisition
        buffer_count = self.buffer_count.get()
        channels = self.active_channels.get()
        channel_count = self.channel_count
        samplesPerBuffer = self._NPTsamplesPerRecord
        recordsPerBuffer = self._NPTrecordsPerBuffer
        samplesPerRecord = self._NPTsamplesPerRecord
        timeout = self.timeout.get()
        screen_size = self.input_range.get()  # Size of the screen
        screen_shift = self.get_screen_shift()
        zero_value = self.board_info["Zero_value"]  # zero for the output data
        sample_type = self.board_info["Sample_type"]  # output data type
        t1 = time.time()
        print(t1-t0)
        try:
            buffersCompleted = 0
            bytesTransferred = 0
            while buffersCompleted < buffersPerAcquisition:
                # Wait for the buffer at the head of the list of available
                # buffers to be filled by the board.
                buffer = self.buffers[buffersCompleted % buffer_count]
                self._board.waitAsyncBufferComplete(buffer.addr, timeout_ms=timeout)
                buffersCompleted += 1
                print(buffersCompleted)
                bytesTransferred += buffer.size_bytes
                received_data = np.frombuffer(buffer.buffer, dtype=sample_type)
                for i in range(recordsPerBuffer):
                    for j in range(channel_count):
                        self.data[channels[j]] = np.concatenate((self.data[channels[j]], (received_data[(2*j+i)*samplesPerRecord:(2*j+i+1)*samplesPerRecord]-zero_value*screen_shift)/zero_value*screen_size))
  
                # Add the buffer to the end of the list of available buffers.
                self._board.postAsyncBuffer(buffer.addr, buffer.size_bytes)
        finally:
            self._board.abortAsyncRead()
            self._initialized = False
        return self.get_data(self.data, self.active_channels.get(), self.samples_per_record.get(), self.nbwindows.get())
    
        # # TODO: Select the number of samples per record.
        # samplesPerRecord = self.samples_per_record.get()  # samples per record asked by the user
        # wanted_nbRecords = self.nbwindows.get()

        # # TODO: Select the number of buffers per acquisition.
        # buffersPerAcquisition = int(np.sqrt(wanted_nbRecords))
        
        # # TODO: Select the number of records per DMA buffer.
        # recordsPerBuffer = buffersPerAcquisition

        # max_SamplesPerBuffer = self.max_bytes_per_buffer.get() / bytesPerSample / channel_count 
        
        # if samplesPerRecord > max_SamplesPerBuffer:
        #     print("Warning : Number of samples per Record > Max Advised Number of samples per Buffer")
        #     recordsPerBuffer = 1
        #     buffersPerAcquisition = wanted_nbRecords
        
        # elif samplesPerRecord * recordsPerBuffer > max_SamplesPerBuffer:
        #     recordsPerBuffer = int(max_SamplesPerBuffer / samplesPerRecord)
        #     buffersPerAcquisition = int(wanted_nbRecords / recordsPerBuffer)
        
        # if recordsPerBuffer * buffersPerAcquisition < wanted_nbRecords:
        #     buffersPerAcquisition = buffersPerAcquisition + 1
        #     self.nbwindows.set(buffersPerAcquisition * recordsPerBuffer)
        #     print("Warning : Number of records set to ", self.nbwindows.get())


    def _fetch_getdev(self):
        """
        Performs a new trigger if one of the active_channels doesn't contain samples_per_record samples

        Output:
            - data (Array): 2D arrays of size (len(active_channels)+1, samples_per_record)
        """
        # Check if all the channels to record contain samples_per_record elements
        dataFILLED = True
        channels = self.active_channels.get()
        bufferSize = self.samples_per_record.get()
        # for each channel
        for channel in channels:
            if len(self.data[channel])<bufferSize:  # if one doesn't have enough data
                dataFILLED=False
                break

        if not dataFILLED: 
            self.trigger_mode.set("Triggered")
            self.readval.get()  # Then update self.data (get new values)
        return self.get_data(self.data, self.active_channels.get(), self.samples_per_record.get(), 1)  # Return data in a shape that can be registered in a file 


    def _fetch_all_getdev(self):
        """
        Performs nbwindows triggers without reloading the data (see NPT trigger mode in ATS-SDK guide)
        That is faster than performing nbwindows times readval.
        Triggers only one channel, defined by current_channel.
        Returns a 2D array with first line time and other nbwindows columns are the result of each trigger.
        
        Limitations:
            - Number of samples per record should be a multiple of 128.
            - To be faster and avoid overflow erros, triggers are span over multiple buffers, it is better if nbwindows is a square. 
        
        Output:
            - data (Array): 2D array of size (nbwindows+1, samples_per_record)
        """
        self.active_channels.set([self.current_channel.get()])  # Only current_channel is active
        return self.readval_all.get()


    def make_average(self, signals):
        """
        Returns the average of a 2D array of size (nbwindows+1, samples_per_record).
        First line is time. nbwindows represent the number of signals to average. 
        See output of device fetch_all.

        Input:
            - signals (Array): 2D array of size (nbwindows+1, samples_per_record)

        Output:
            - average_signal (Array): 2D array of size (2, samples_per_record)
        """
        nbRecords = len(signals[2])
        return [signals[1][0], sum(signals[2], axis=0) / nbRecords]
    

    def _average_getdev(self):
        """
        Realizes multiple triggers with fetch_all, and average them.
        You can average the output of fetch_all by directly using the make_average function
        
        Output:
            - data (Array): 2D array of size (2, samples_per_record)
        """
        signals = self.fetch_all.get()
        nbwindows = self.nbwindows.get()
        nbsamples = self.samples_per_record.get() 
        return self.make_average([np.reshape(signals[0], (nbwindows, nbsamples)),
                                  np.reshape(signals[1], (nbwindows, nbsamples)),
                                  np.reshape(signals[2], (nbwindows, nbsamples))])


    def _continuous_read_getdev(self):
        """
        Records a single continuous acquisition immediatly after calling the function.
        Uses readval function in continuous mode.
        Mode is set back to triggered after the acquisition  
        
        Output:
            - data (Array): 2D array of size (len(active_channels)+1, samples_per_record)
        """
        print(self._initialized)
        if self.trigger_mode.get()!="Continuous":
            self.trigger_mode.set("Continuous")
            self._initialized = False

        if not self._initialized:
            self._async_trig()
        # Get parameters for loop
        buffersPerRecord = self._TRIGbuffersPerRecord
        buffer_count = self.buffer_count.get()
        channel_count = self.channel_count
        channels = self.active_channels.get()
        samplesPerBuffer = self._TRIGsamplesPerBuffer
        screen_size = self.input_range.get()  # Size of the screen
        screen_shift = self.get_screen_shift()
        sample_type = self.board_info["Sample_type"]  # output data type
        zero_value = self.board_info["Zero_value"]  # zero for the output data
        timeout = self.timeout.get()  # timeout

        try:
            buffersCompleted = 0
            bytesTransferred = 0

            while buffersCompleted < buffersPerRecord:
                # Wait for the buffer at the head of the list of available
                # buffers to be filled by the board.
                buffer = self.buffers[buffersCompleted % buffer_count]
                self._board.waitAsyncBufferComplete(buffer.addr, timeout_ms=timeout)
                received_data = np.frombuffer(buffer.buffer, dtype=sample_type)
                for i in range(channel_count):
                    self.data[channels[i]] = np.concatenate((self.data[channels[i]], (received_data[i*samplesPerBuffer:(i+1)*samplesPerBuffer]-screen_shift*zero_value)/zero_value*screen_size), axis=0)
                buffersCompleted += 1
                bytesTransferred += buffer.size_bytes

                # Add the buffer to the end of the list of available buffers.
                self._board.postAsyncBuffer(buffer.addr, buffer.size_bytes)
        finally:
            self._board.abortAsyncRead()
            self._initialized = False

        return self.get_data(self.data, self.active_channels.get(), self.samples_per_record.get(), 1)


    # def make_fft(self, data):
    #     """
    #     Returns the fft of a signal having the format of the result of a continuous acquisition on one channel with continuous_read
    #     FFT is returned in units defined in psd_units. If units are not "V" or "dBV", they are set to "V".
    #     FFT is returned between psd_start_freq and psd_end_freq.

    #     Input:
    #         - signal (Array): A 2D array of size (2, samples_per_record)

    #     Output:
    #         - fft (List[Array]): first element is frequency axis, second element is fft 
    #     """
    #     # Perform FFT
    #     nfft = self.psd_fft_lines.get()  # number of frequency points computed for the FFT
    #     yf = rfft(data[2]*1e-3, n=nfft)  # FFT data
    #     xf = rfftfreq(nfft, 1/self.sample_rate.get())  # frequencies data
        
    #     # Return a sub-part of the FFT: xf in [psd_start_freq; psd_end_freq]
    #     xfbegin = np.searchsorted(xf, self.psd_start_freq.get())  # index in xf related to first element above psd_start_freq
    #     xfend = np.searchsorted(xf, self.psd_end_freq.get(), side="right")  # index in xf related to first element below psd_end_freq
        
    #     # Return FFT in correct units
    #     units = self.psd_units.get()
        
    #     # If the units are not FFT units
    #     # Set them to V
    #     if not units in self.get_fft:
    #         print("FFT units not defined, set to V")
    #         self.psd_units.set("V")
    #         units = "V"

    #     if units == "V":
    #         # FFT naturally computed in V
    #         return [xf[xfbegin:xfend], yf[xfbegin:xfend]]
    #     else:
    #         # FFT in dB
    #         return [xf[xfbegin:xfend], 10*np.log10(np.abs(yf[xfbegin:xfend]))]


    # def _fft_getdev(self):
    #     """
    #     Records a single continuous acquisition on one channel with continuous_read (on current_channel) before performing FFT on it
    #     The fft of any signal can be computed by calling make_fft

    #     Output:
    #         - fft (List[Array]): first element is frequency axis, second element is fft 
    #     """
    #     # Acquire signal on current_channel
    #     self.active_channels.set([self.current_channel.get()])
    #     data = self.continuous_read.get()

    #     # Perform fft
    #     return self.make_fft(data)


    def make_psd(self, data):
        """
        Returns the psd of a signal having the format of the result of a continuous acquisition on one channel with continuous_read.
            - If units are FFT units, run make_fft instead.
            - If units are in "V**2", computes the Power Spectrum.
            - If units are in "V**2/Hz" or "V/sqrt(Hz)", computes the PSD.
        Power Spectrum and Power Spectral Density are performed using Welch's method 
        (See more on https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html)
            - Power Spectrum: cuts the sample in nbwindows segment, multiply each segment by a window function, perform |FFT|**2 on each segment and take the average
            - PSD: divide Power Spectrum by bandwith
        Warning: psd_fft_lines must be inferior or equal to the number of points per segment
        If this condition is not fulfilled, psd_fft_lines automatically set equal to number of points per segment  
        The result is output with frequencies between psd_start_freq and psd_end_freq

        Input:
            - signal (Array): A 2D array of size (2, samples_per_record)

        Output:
            - psd (List[Array]): first element is frequency axis, second element is psd 
        """        
        # Depending on the units, perform FFT or PSD
        units = self.psd_units.get()
        
        # if units in self.get_fft:
            # If FFT units, perform FFT
            # return self.make_fft(data)
        if units == "V**2" or units in self.get_fft:
            # If "V**2", compute Power Spectrum
            scaling = "spectrum"
        else:
            # If "V**2/Hz" or "V/sqrt(Hz)", compute PSD
            scaling = "density"

        # Power Spectrum: cuts the sample in nbwindows segment, multiply each segment by a window function, perform |FFT|**2 on each segment and take the average
        # PSD: divide Power Spectrum by bandwith
        # Define number of points per segment and number of points taken for PSD 
        nperseg = int(self.samples_per_record.get()/self.nbwindows.get())  # number of points per segment
        nfft = self.psd_fft_lines.get()  # number of points for the FFT
        if nfft > nperseg:  # nfft should be smaller or equal than nperseg
            # If nfft greater than nperseg
            # nfft set equal to nperseg
            nfft = nperseg
            print("More FFT points than points per window, psd_fft_lines set to: ", nperseg) 

        # Perform PSD/Power Spectrum
        # psd[0]: frequencies, psd[1]: PSD
        psd = signal.welch(data[2]*1e-3,
                            fs=self.sample_rate.get(),  # sample rate
                            window=convert_window_function(self.window_function.get(), nperseg),  # window function
                            nperseg=nperseg,  # number of points per segment
                            noverlap=None,  # set to nperseg//2
                            nfft=nfft,  # number of points for the FFT
                            detrend='constant',
                            return_onesided=True,  # Return only positive frequencies
                            scaling=scaling,  # units: spectrum or density
                            axis=- 1)
        # Display PSD only between psd_start_freq and psd_end_freq
        xfbegin = np.searchsorted(psd[0], self.psd_start_freq.get())  # detect first frequency >= psd_start_freq  
        xfend = np.searchsorted(psd[0], self.psd_end_freq.get(), side="right")  # detect first frequency <= psd_end_freq
        # PSD in V**2/Hz
        if units == "V/sqrt(Hz)":
            # Take the square root if units are V/sqrt(Hz)
            return [psd[0][xfbegin:xfend], np.sqrt(psd[1][xfbegin:xfend])]
        elif units=="V":
            return [psd[0][xfbegin:xfend], np.sqrt(psd[1][xfbegin:xfend])]
        elif units=="dBV":
            return [psd[0][xfbegin:xfend], 10*np.log10(np.sqrt(psd[1][xfbegin:xfend]))]
        
        return [psd[0][xfbegin:xfend], psd[1][xfbegin:xfend]]


    def _psd_getdev(self):
        """
        Records a single continuous acquisition on one channel with continuous_read (on current_channel)
        PSD/FFT is computed by calling make_psd (if units are FFT units, make_fft is caller instead)

        Output:
            - psd (List[Array]): first element is frequency axis, second element is psd 
        """
        # Acquire signal on current_channel
        self.active_channels.set([self.current_channel.get()])
        data = self.continuous_read.get()
        # Perform psd
        return self.make_psd(data)


    def smooth_curve(self, data, sliding_mean_points):
        """
        Smooth the curve of any signal output by readval or fetch by performing a sliding mean operation
        If sliding_mean_points is 0 then the signal is unchanged
        
        Input:
            - data (Array): 2D array of size (2, samples_per_record)
            - sliding_mean_points (int): Number of points taken to smooth the curve 
                                         (for point j, mean is performed over points [j-sliding_mean_points/2; j+sliding_mean_points/2]) 
        
        Ouput:
            - smoothed_signal (Array): 2D array of size (2, samples_per_record)
        """
        if sliding_mean_points == 0:
            return data
        elif sliding_mean_points < 0:
            raise ValueError("Number of Points for Sliding Mean Should Be >= 0")

        return [data[0], uniform_filter1d(data[1], size=sliding_mean_points)]


    def detection_threshold(self, data, trigger_level_descend, trigger_level_ascend):
        """
        Detects all the times at which a signal goes above trigger_level_ascend or below triger_level_descend           
        
        Input:
            - data (Array): 2D array of size (2, samples_per_record)
            - trigger_level_descend (float): Value for which to trigger if previous value is above and current value is below  
            - trigger_level_ascend (float): Value for which to trigger if previous value is below and current value is above

        
        Ouput:
            - triggers [Array, Array]: List of times at which trigger_level_descend was triggered, List of times at which trigger_level_ascend was triggered 
        """        
        trigger_descend = data[1] > trigger_level_descend  # True if value of signal is above trigger_level_descend, False otherwise 
        trigger_ascend = data[1] < trigger_level_ascend  # True if value of signal is below trigger_level_ascend, False otherwise
        
        has_trigger_descend = trigger_descend[:-1] > trigger_descend[1:]  # True if signal is above trigger_level_descend at time t and below at time t+dt  
        has_trigger_ascend = trigger_ascend[:-1] > trigger_ascend[1:]  # True if signal is below trigger_level_ascend at time t and above at time t+dt 
        
        triggers_index_descend = np.nonzero(has_trigger_descend)  # get indices at which trigger_level_descend was triggered
        triggers_index_ascend = np.nonzero(has_trigger_ascend)  # get indices at which trigger_level_ascend was triggered
        
        return [data[0][triggers_index_descend], data[0][triggers_index_ascend]]  # times at which triggers took place
        # trigger_descend = data[1] > trigger_level_descend  # True if value of signal is above trigger_level_descend, False otherwise 
        # trigger_ascend = data[1] > trigger_level_ascend  # True if value of signal is above trigger_level_ascend, False otherwise
        # n = len(trigger_descend)
        # yth = np.zeros(n)
        # for i in range(1, n):
        #     if yth[i-1]:
        #         yth[i] = trigger_descend[i]
        #     else:
        #         yth[i] = trigger_ascend[i]

        # has_trigger = yth[:-1] != yth[1:]  # True if signal is above trigger_level_descend at time t and below at time t+dt  
        
        # triggers_index = np.nonzero(has_trigger)  # get indices at which trigger_level_descend was triggered
        
        # return data[0][triggers_index] # times at which triggers took place  


    def get_data_threshold(self, n, max_length_threshold, detected_threshold_descend, detected_threshold_ascend):
        returned_data_sample_number = [i*np.ones(max_length_detected_threshold) for i in range(n)]
        returned_data_threshold_descend = [np.concatenate((detected_threshold_descend[i], -1*np.ones(max_length_threshold-len(detected_threshold_descend[i]))), axis=0) for i in range(n)]
        returned_data_threshold_ascend = [np.concatenate((detected_threshold_ascend[i], -1*np.ones(max_length_threshold-len(detected_threshold_ascend[i]))), axis=0) for i in range(n)]
        
        return [returned_data_sample_number, returned_data_threshold_descend, returned_data_threshold_ascend]


    def _rabi_getdev(self):
        """
        Acquires nbwindows signals.
        For each signal, smooth the curve using a sliding mean and detect the trigger_level_descend and trigger_level_ascend.
        If you don't want to smooth the curve, set sliding_mean_points to 0

        Output:
            - detected threshold List(Array): List of 2*nbwindows Array. 
                                              Index 2*n contains times at which trigger_level_descend was triggered for acquisition number n
                                              Index 2*n+1 contains times at which trigger_level_ascend was triggered for acquisition number n
        """
        # Acquisition
        data = self.fetch_all.get()
        # Detecting the thresholds
        detected_threshold_descend = []
        detected_threshold_ascend = []
        nbwindows = self.nbwindows.get()
        nbsamples = self.samples_per_record.get()
        new_data = [np.reshape(data[1], (nbwindows, nbsamples)),
                    np.reshape(data[2], (nbwindows, nbsamples))]
        trigger_level_descend = self.trigger_level_descend.get()
        trigger_level_ascend = self.trigger_level_ascend.get()
        nbpoints_sliding_mean = self.sliding_mean_points.get()
        max_length_detected_threshold = 0

        for i in range(0, n):
            # For each signal acquired
            # Detect the thresholds on the smoothed curve
            thresholds = self.detection_threshold(self.smooth_curve([new_data[1][i], data[2][i]],
                                                                     nbpoints_sliding_mean),
                                                  trigger_level_descend,
                                                  trigger_level_ascend)
            max_length_detected_threshold = max(max_length_detected_threshold,
                                                max(len(detected_threshold[0]),
                                                    len(detected_threshold[1])))
            detected_threshold_descend.append(thresholds[0])
            detected_threshold_ascend.append(thresholds[1])

        return get_data_threshold(n, detected_threshold_ascend, detected_threshold_descend)


    def _create_devs(self):
        # To perform an acquisition
        self.timeout = MemoryDevice(10000, get_has_check=True, autoinit=True, doc=
            "In milliseconds. Maximum time to wait for a DMA buffer to be filled during an acquisition.")
        self.max_bytes_per_buffer = MemoryDevice(16e6, get_has_check=True, autoinit=True, doc=
            "Max Bytes per DMA buffer during an acquisition. Alazartech doc says it should be 16MB for optimal performances.")
        self.buffer_count = MemoryDevice(4, get_has_check=True, autoinit=True, doc=
            "Number of DMA buffer per acquisition. Alazartech doc says it should be greater than 2 for optimal performances.")
        
        # To perform fft, psd or average
        self.current_channel = MemoryDevice("A", autoinit=True, choices=["A", "B"], doc=
            "Channel to trigger in fetch_all, average, fft, psd, rabi")
        self.nbwindows = MemoryDevice(100, autoinit=True, doc=
            "Number of acquisition realized in readval_all, fetch_all, average, rabi and number of windows used to perform fft, psd")
        self.window_function = MemoryDevice("hanning", autoinit=True, choices=["hanning",
                                                                               "hamming",
                                                                               "blackman",
                                                                               "bartlett",
                                                                               "kaiser",
                                                                               "flattop",
                                                                               "uniform"])
        self.psd_units = MemoryDevice("V**2/Hz", autoinit=True, choices=["V",
                                                                         "dBV",
                                                                         "V**2",
                                                                         "V**2/Hz",
                                                                         "V/sqrt(Hz)"], doc=
            """Units for PSD/FFT : 
            - Perform FFT if unit is 'V' or 'dBV'.
            - Perform Power Spectrum if unit is 'V**2'.
            - Perform Power Spectral Density if unit is 'V**2/Hz' or 'V/sqrt(Hz)'""")
        # self.rms = ["Vrms", "dBVrms", "Vrms**2", "Vrms**2/Hz"]
        self.get_fft = ["V", "dBV"]
        self._acquisition_length_sec = MemoryDevice(5e-3, get_has_check=True, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._samples_per_record = MemoryDevice(50000, get_has_check=True, autoinit=True, doc=
            "In memory device. Do not modify.")
        
        self._ext_sample_rate = MemoryDevice(10e6, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_sample_rate = MemoryDevice(convert_sample_rate(10e6, self.board_info["Kind"], "INT"), autoinit=True, doc=
            "In memory device. Do not modify.")
        
        self._psd_fft_lines = MemoryDevice(50000, get_has_check=True, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._psd_linewidth = MemoryDevice(200, get_has_check=True, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._psd_span = MemoryDevice(5000000, get_has_check=True, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._psd_start_freq = MemoryDevice(0, get_has_check=True, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._psd_center_freq = MemoryDevice(2500000, get_has_check=True, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._psd_end_freq = MemoryDevice(5000000, get_has_check=True, autoinit=True, doc=
            "In memory device. Do not modify.")
        
        self._devwrap("psd_start_freq", autoinit=True, setget=True)
        self._devwrap("psd_center_freq", autoinit=True, setget=True)
        self._devwrap("psd_end_freq", autoinit=True, setget=True)
        self._devwrap("acquisition_length_sec", autoinit=True, setget=True)
        self._devwrap("samples_per_record", autoinit=True, setget=True)
        self._devwrap("psd_span", autoinit=True, setget=True)
        self._devwrap("psd_linewidth", autoinit=True, setget=True)
        self._devwrap("psd_fft_lines", autoinit=True, setget=True)


        self._ext_clock_type = MemoryDevice("INT", autoinit="INT", choices=["INT", "EXT", "fast_EXT", "slow_EXT", "EXT_10MHz"], doc=
            "In memory device. Do not modify.")
        self._ats_clock_type = MemoryDevice(ats.INTERNAL_CLOCK, autoinit=True, doc=
            "In memory device. Do not modify.")

        self._devwrap("sample_rate", setget=True, autoinit=True)
        self._devwrap("clock_type", autoinit=True)

        self._acquisition_mode = MemoryDevice("pm", choices=["pm", "0m", "0p"], autoinit=True, doc=
            "In memory device. Do not modify.")

        self._ext_input_range = MemoryDevice(2000, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_input_range = MemoryDevice(convert_input_range("pm", 2000, self.board_info["Kind"]), autoinit=True, doc=
            "In memory device. Do not modify.")
        self._devwrap("input_range", setget=True, autoinit=True)

        self._devwrap("acquisition_mode", setget=True, autoinit=True)

        self.trigger_to_use = MemoryDevice("1", autoinit=True, choices=["1", "2", "1or2"], doc=
            """Defines the trigger operation: either use only trigger 1 "1", or trigger 2 "2", or the first occuring trigger between both "1or2" """)

        self._ext_range_ext_trigger = MemoryDevice(5, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_range_ext_trigger = MemoryDevice(convert_ext_trigger(5), autoinit=True, doc=
            "In memory device. Do not modify.")

        self._ext_trigger_channel_1 = MemoryDevice("ext", autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ext_trigger_channel_2 = MemoryDevice("", autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_trigger_channel_1 = MemoryDevice(convert_trigger_channel("ext"), autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_trigger_channel_2 = MemoryDevice(convert_trigger_channel(""), autoinit=True, doc=
            "In memory device. Do not modify.")

        self._ext_trigger_level_1 = MemoryDevice(10., autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ext_trigger_level_2 = MemoryDevice(10., autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_trigger_level_1 = MemoryDevice(convert_trigger_level(10., 400), autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_trigger_level_2 = MemoryDevice(convert_trigger_level(10., 400), autoinit=True, doc=
            "In memory device. Do not modify.")

        self._ext_trigger_slope_1 = MemoryDevice("ascend", autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ext_trigger_slope_2 = MemoryDevice("ascend", autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_trigger_slope_1 = MemoryDevice(convert_trigger_slope("ascend"), autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_trigger_slope_2 = MemoryDevice(convert_trigger_slope("ascend"), autoinit=True, doc=
            "In memory device. Do not modify.")

        self._devwrap("trigger_channel_1", setget=True, autoinit=True)
        self._devwrap("trigger_channel_2", setget=True, autoinit=True)
        self._devwrap("trigger_level_1", setget=True, autoinit=True)
        self._devwrap("trigger_level_2", setget=True, autoinit=True)
        self._devwrap("trigger_slope_1", setget=True, autoinit=True)
        self._devwrap("trigger_slope_2", setget=True, autoinit=True)

        self.bw_limited_a = MemoryDevice(0, autoinit=True, doc=
            "Channel A bandwidth limit")
        self.bw_limited_b = MemoryDevice(0, autoinit=True, doc=
            "Channel B bandwidth limit")
        self.trigger_delay = MemoryDevice(0, get_has_check=True, autoinit=True, doc=
            "Delay before trigger")

        self._ext_impedance = MemoryDevice(1e6, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_impedance = MemoryDevice(convert_impedance(1e6), autoinit=True, doc=
            "In memory device. Do not modify.")
        self._devwrap("impedance", autoinit=True)

        self._ext_active_channels = MemoryDevice(["A", "B"], autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_active_channels = MemoryDevice(ats.CHANNEL_A | ats.CHANNEL_B, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._devwrap("active_channels", autoinit=True)

        self._ext_trigger_mode = MemoryDevice("Triggered", autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_trigger_mode = MemoryDevice(ats.ADMA_TRIGGERED_STREAMING, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._devwrap("trigger_mode", setget=True, autoinit=True)

        self._ext_aux_io_mode = MemoryDevice("AUX_OUT_TRIGGER", autoinit=True, choices=["AUX_OUT_TRIGGER", "AUX_IN_TRIGGER_ENABLE", "AUX_OUT_PACER", "AUX_OUT_SERIAL_DATA", "AUX_IN_AUXILIARY"], doc=
            "In memory device. Do not modify.")
        self._ats_aux_io_mode = MemoryDevice(ats.AUX_OUT_TRIGGER, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ext_aux_io_param = MemoryDevice(0, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._ats_aux_io_param = MemoryDevice(0, autoinit=True, doc=
            "In memory device. Do not modify.")
        self._devwrap("aux_io_mode", setget=True, autoinit=True)
        self._devwrap("aux_io_param", setget=True, autoinit=True)

        self.inmemory = {"trigger_delay":0,
                         "bw_a":0,
                         "bw_b":0}

        # For Rabi experiment
        self.trigger_level_descend = MemoryDevice(0, autoinit=True, get_has_check=True, doc=
            "Level to detect for descending signal when calling rabi device")
        self.trigger_level_ascend = MemoryDevice(0, autoinit=True, get_has_check=True, doc=
            "Level to detect for ascending signal when calling rabi device")
        self.sliding_mean_points = MemoryDevice(0, autoinit=True, get_has_check=True, doc=
            "Number of points used to smooth the signal before detecting the trigger_level_ascend and trigger_level_descend in rabi")

        self._devwrap("readval", autoinit=False)
        self._devwrap("readval_all", autoinit=False)
        self._devwrap("fetch", autoinit=False)
        self._devwrap("fetch_all", autoinit=False)
        self._devwrap("average", autoinit=False)
        self._devwrap("continuous_read", autoinit=False)
        self._devwrap("fft", autoinit=False)
        self._devwrap("psd", autoinit=False)
        self._devwrap("rabi", autoinit=False)
        super(ATSBoard, self)._create_devs()
