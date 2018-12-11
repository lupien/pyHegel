# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2018-2018  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

#######################################################
##    Rohde & Schwarz instruments
#######################################################

from __future__ import absolute_import

import numpy as np
import sys
import ctypes
from ctypes import c_long, c_int, c_uint, c_uint64, c_ubyte, POINTER, byref, create_string_buffer
import os

from ..instruments_base import visaInstrument, visaInstrumentAsync, BaseInstrument,\
                            scpiDevice, MemoryDevice, ReadvalDev, BaseDevice,\
                            ChoiceMultiple, Choice_bool_OnOff, _repr_or_string,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDev, ChoiceDevSwitch, ChoiceIndex,\
                            ChoiceSimpleMap, decode_float32, decode_int8, decode_int16, _decode_block_base,\
                            decode_float64, quoted_string, _fromstr_helper, ProxyMethod, _encode_block,\
                            locked_calling, quoted_list, quoted_dict, decode_complex128, Block_Codec
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

def add_environ_path(path):
    current_paths = os.environ['PATH']
    if path not in current_paths.split(os.pathsep):
        if not current_paths.endswith(os.pathsep):
            current_paths += os.pathsep
        os.environ['PATH'] = current_paths + path

#######################################################
##    Guzik ADP7104
#######################################################

@register_instrument('Guzik', 'ADP7104', '1.0')
class guzik_adp7104(BaseInstrument):
    """
    This is the driver for the Guzik acquisition system (ADP7104, 4 channels, 32 GS/s (2ch), 10 GHz (2ch))
    """
    def __init__(self, sdk_path=r'C:\Codes\Guzik', lib_path=r'C:\Program Files\Keysight\GSA1 Toolkit 460A7KREL127\x64'):
        if sdk_path not in sys.path:
            sys.path.append(sdk_path)
        add_environ_path(lib_path)
        import gsa_sdk_h
        self._gsasdk = gsa_sdk_h
        super(guzik_adp7104, self).__init__()
        SDK = self._gsasdk
        self._gsa_sys_cfg = SDK.GSA_SYS_CFG(version=SDK.GSA_SDK_VERSION)
        if SDK.GSA_SysInit(self._gsa_sys_cfg) != SDK.GSA_TRUE:
            raise RuntimeError(self.perror('Initialization problem!'))
        ci = ctypes.c_int()
        if SDK.GSA_ReadChNumberGet(ctypes.byref(ci)) == SDK.GSA_FALSE:
            raise RuntimeError(self.perror('Initialization problem. Unable to get number of available channels'))
        if ci.value != 1:
            raise RuntimeError(self.perror('Current code only handles one Guzik card on the system.'))
        self.config(1)

    def config(self, channels, n_S_ch=1024, bits_16=True, gain=0.):
        """
        channels needs be a list of integer that represent the channels (1-4).
        It can also be a single integer
        bits_16 when False, returns 8 bit data.
        n_S_ch is the number of Sample per ch to read.
        """
        if not isinstance(channels, (np.ndarray, list, tuple)):
            channels = [channels]
        for c in channels:
            if c>4 or c<1:
                raise ValueError(self.perror('Invalid channel number. Needs to be a number from 1 to 4.'))
        Nch = len(channels)
        cs = ','.join(['CH%i'%i for i in channels])
        conf = c_long()
        SDK = self._gsasdk
        if SDK.GSA_ReadChBestConfigGet(0, SDK.GSA_READ_CH_INP1, cs, byref(conf)) == SDK.GSA_FALSE:
            raise RuntimeError(self.perror('Unable to obtain best config.'))
        self._gsa_conf = conf.value
        # now obtain the conf
        chrarg = SDK.GSA_READ_CH_CFG_INFO_ARG(version=SDK.GSA_SDK_VERSION, rc_conf=conf)
        chrres = SDK.GSA_READ_CH_CFG_INFO_RES()
        if SDK.GSA_ReadChCfgInfoGet(chrarg, chrres) == SDK.GSA_FALSE:
            raise RuntimeError(self.perror('Unable to read best config.'))
        self._gsa_conf_ch = chrres
        # Now setup acquisition
        hdr_default = SDK.GSA_ARG_HDR(version=SDK.GSA_SDK_VERSION)
        arg = SDK.GSA_Data_ARG(hdr=hdr_default)
        res = SDK.GSA_Data_RES()
        if SDK.GSA_Data_Info(arg, res) == SDK.GSA_FALSE:
            raise RuntimeError(self.perror('Unable to initialize acq structure.'))
        arg.common.rc_idx = 0
        arg.common.rc_conf = conf
        arg.common.acq_len = n_S_ch
        #arg.common.acq_time_ns = 1000
        arg.common.sectors_num = 1
        #arg.common.sector_time_ns = 1000
        #arg.common.acq_timeout = 0 # in us. -1 for infinite
        arg.common.acq_adjust_up = SDK.GSA_TRUE
        arg.common.trigger_mode = SDK.GSA_DP_TRIGGER_MODE_IMMEDIATE
        arg.common.gain_dB = gain
        ts = np.zeros(10, np.uint)
        tf = np.zeros(10, np.uint64)
        self._gsa_data_res_ts = ts # timestamp in seconds
        self._gsa_data_res_ts = tf # timestamp in femtoseconds
        res.common.timestamp_seconds.size = len(ts)
        res.common.timestamp_seconds.arr = ts.ctypes.data_as(POINTER(c_uint))
        res.common.timestamp_femtoseconds.size = len(tf)
        res.common.timestamp_femtoseconds.arr = tf.ctypes.data_as(POINTER(c_uint64))
        if bits_16:
            arg.common.data_type = SDK.GSA_DATA_TYPE_INT15BIT
        else:
            arg.common.data_type = SDK.GSA_DATA_TYPE_SHIFTED8BIT
        arg.hdr.op_command = SDK.GSA_OP_CONFIGURE
        if SDK.GSA_Data(arg, res) == SDK.GSA_FALSE:
            raise RuntimeError(self.perror('Unable to finish initializing acq structure.'))
        self._gsa_data_arg = arg
        self._gsa_data_res = res
        self._gsa_data = None # free previous data memory
        N = res.common.data_len
        if bits_16:
            data = np.empty(N, np.int16)
        else:
            data = np.empty(N, np.uint8)
        res.common.data.arr = data.ctypes.data_as(POINTER(c_ubyte))
        res.common.data.size = N
        self._gsa_data = data

    def _fetch_getdev(self):
        SDK = self._gsasdk
        arg = self._gsa_data_arg
        res = self._gsa_data_res
        arg.hdr.op_command = SDK.GSA_OP_FINISH
        if SDK.GSA_Data(arg, res) == SDK.GSA_FALSE:
            raise RuntimeError(self.perror('Had a problem reading data.'))
        return self._gsa_data

    def close(self):
        SDK = self._gsasdk
        SDK.GSA_SysDone(self._gsa_sys_cfg)

    def idn(self):
        return 'Guzik,ADP7104,00000,1.0'

    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('loop1', options)

    def get_error(self, basic=False, printit=True):
        SDK = self._gsasdk
        s = ctypes.create_string_buffer(SDK.GSA_ERROR_MAX_BUFFER_LENGTH)
        if basic:
            ret = SDK.GSA_ErrorHandleStr(SDK.GSA_ERR_PRINT_BASIC, SDK.String(s), len(s))
        else:
            ret = SDK.GSA_ErrorHandleStr(SDK.GSA_ERR_PRINT_FULL, SDK.String(s), len(s))
        if ret == SDK.GSA_TRUE: # = -1
            if printit:
                print s.value
            else:
                return s.value
        else:
            if printit:
                print 'No errors'
            else:
                return None

    def _create_devs(self):
        self.loop1 = MemoryDevice(0.)
        self._devwrap('fetch')
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
