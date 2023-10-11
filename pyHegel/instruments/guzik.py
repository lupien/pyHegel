# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2018-2023  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from __future__ import absolute_import, print_function, division

import numpy as np
import sys
import ctypes
import os
import time
import gc

from ctypes import c_long, c_int, c_uint, c_uint64, c_ubyte, POINTER, byref, create_string_buffer, Structure, Array, pointer

from ..instruments_base import visaInstrument, visaInstrumentAsync, BaseInstrument,\
                            scpiDevice, MemoryDevice, ReadvalDev, BaseDevice,\
                            ChoiceMultiple, Choice_bool_OnOff, _repr_or_string,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDev, ChoiceDevSwitch, ChoiceIndex,\
                            ChoiceSimpleMap, decode_float32, decode_int8, decode_int16, _decode_block_base,\
                            decode_float64, quoted_string, _fromstr_helper, ProxyMethod, _encode_block,\
                            locked_calling, quoted_list, quoted_dict, decode_complex128, Block_Codec,\
                            dict_improved
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

def add_environ_path(path):
    current_paths = os.environ['PATH']
    if path not in current_paths.split(os.pathsep):
        if not current_paths.endswith(os.pathsep):
            current_paths += os.pathsep
        os.environ['PATH'] = current_paths + path

_SDK = None

#######################################################
##    Guzik ADP7104
#######################################################

new_data_c_func = ctypes.CFUNCTYPE(None, c_int)
class PostProcess(object):
    """ Release is always called before init.
        Normal sequence is
         init -> reset ->
            new_data_array
              new_data
              new_data
                ...
              new_data (all of array ready)
            new_data_array ()
              new_data
              new_data
                ...
              new_data (all of array ready)
             ...
          complete
         Then back to reset -> new_data_array
         or release.
         For chaining to work, This object needs to call the
         chain periodically with new_data_array and new_data
    """
    def init(self, Nsamples, Nch=1, chain=None):
        """ Init stage. Use it to reserve memory """
        self.Nsamples = Nsamples
        self.Nch = Nch
        self.chain = chain
        if self.chain:
            self.chain.init(Nsamples, Nch)
        self._new_data_func = new_data_c_func(self.get_counter_func_address)
    def get_counter_func_address(self):
        """ This is used when chaining. It is the address of a C function that
            takes an int64 as a parameter to perform in pure C what
            new_data does in python
        """
        return -1
    def stop(self):
        """ Call this to stop an calculation. Only returns once the calculation are
        really stopped."""
        if self.chain:
            self.chain.stop()
    def reset(self):
        """ Reset stage. Use it to initialize memory for a new acq """
        if self.chain:
            self.chain.reset()
    def new_data(self, sample_count_ready):
        """ call this to update the sample count (per ch) of available data """
        self._new_data_func(sample_count_ready)
    def check_in_progress(self):
        """ returns how many inputs samples have been completed """
        pass
    def check_out_progress(self):
        """ returns how many output samples have been completed """
        pass
    def check_is_done(self):
        """ returns when current calculation is done """
        if self.chain:
            return self.chain.check_is_done()
        return self.check_in_progress() == self.Nsamples
    def new_data_array(self, data, sample_count_ready=0):
        """ This is called when a new array of data is available """
        self.new_data(sample_count_ready)
    def complete(self):
        """ This is called at the end of the calulculation to
            return the results
        """
        if self.chain:
            return self.chain.complete()
    def release(self):
        """ This is called to relase the memory """
        if self.chain:
            self.chain.release()
    def current_config(self):
        """ Return a list of strings representing the configuration """
        opts = []
        if self.chain:
            opts += self.chain.current_config()
        return opts

def pp(o, align=20, base='', nmax=None):
    """ prints a ctypes structure (or a dictionnary from ppdict) recursivelly """
    fmt = '%%-%is %%s'%align
    dicts = (dict, dict_improved)
    if isinstance(o, list) and (len(o) == 0 or (len(o)>0 and not isinstance(o[0], (Structure, list)+dicts))):
        print(fmt%(base, o))
        return
    elif isinstance(o, (Array, list)):
        if nmax is None:
            nmax = len(o)
        for i in range(nmax):
            pp(o[i], align, base+'[%i]'%i)
        return
    if len(base):
        base += '.'
    if isinstance(o, dicts):
        elements = list(o.keys())
        get_val = lambda o, k: o[k]
    else:
        elements = o.__slots__
        get_val = lambda o,s: getattr(o, s)
    for s in elements:
        v = get_val(o, s)
        n = base+s
        if isinstance(v, (Structure, list)+dicts):
            pp(v, align, n)
        else:
            if isinstance(v, Array) and len(v) < 100:
                if isinstance(v[0], Array):
                    try:
                        # This works for array of strings
                        v = [ e.value for e in v ]
                    except AttributeError:
                        v = [ e[:] for e in v ]
                else:
                    v = v[:]
            print(fmt%(n, v))

def ppdict(o, nmax=None):
    """ Takes the returned Structure or Array and turn it into dicts and lists """
    if isinstance(o, Array):
        if nmax is None:
            nmax = len(o)
        return [ppdict(o[i]) for i in range(nmax)]
    ret = dict_improved()
    for s in o.__slots__:
        v = getattr(o, s)
        if isinstance(v, Structure):
            ret[s] = ppdict(v)
        else:
            if isinstance(v, Array) and len(v) < 100:
                if isinstance(v[0], Array):
                    try:
                        # This works for array of strings
                        v = [ e.value for e in v ]
                    except AttributeError:
                        v = [ e[:] for e in v ]
                else:
                    v = v[:]
            ret[s] = v
    return ret

GiS = 2.**30

def get_memory():
    try:
        import psutil
    except ImportError:
        print('Unable to find the computer memory size. Requires the psutil module. using 128 GiB')
        return 128*GiS
    return psutil.virtual_memory().total

#@register_instrument('Guzik', 'ADP7104 ADC 64GS', '446034')
@register_instrument('Guzik', 'ADP7104 ADC 64GS')
class guzik_adp7104(BaseInstrument):
    """
    This is the driver for the Guzik acquisition system (ADP7104, 4 channels, 32 GS/s (2ch), 10 GHz (2ch))
    To use this instrument, the most useful device is probably:
        fetch
    Some methods are available:
        config
        conv_scale
        close
        get_error
        print_timestamps
        print_structure
    """
    def __init__(self, sdk_path=r'C:\Codes\Guzik', lib_path=r'C:\Program Files\Keysight\GSA1 Toolkit Latest\x64'):
        global _SDK
        if sdk_path not in sys.path:
            sys.path.append(sdk_path)
        add_environ_path(lib_path)
        import gsa_sdk_h
        self._gsasdk = gsa_sdk_h
        super(guzik_adp7104, self).__init__()
        SDK = self._gsasdk
        _SDK = SDK
        self._computer_memsize = get_memory()
        libversion = SDK.BSTR()
        SDK.GSA_FullLibVersionGet(byref(libversion))
        full_lib_version = ''
        for i in libversion:
            if i == 0:
                break
            full_lib_version += chr(i)
        self._gsa_sys_cfg = SDK.GSA_SYS_CFG(version=SDK.GSA_SDK_VERSION)
        print('Starting instrument initialization. This could take some time (20s)...')
        if SDK.GSA_SysInit(self._gsa_sys_cfg) != SDK.GSA_TRUE:
            raise RuntimeError(self.perror('Initialization problem!'))
        print('Finished instrument initialization.')
        c_n_avail_analyzer = ctypes.c_int()
        def check_error(func_call_result, error_message='Error!'):
            if func_call_result == SDK.GSA_FALSE:
                raise RuntimeError(self.perror(error_message))
        check_error(SDK.GSA_ReadChNumberGet(ctypes.byref(c_n_avail_analyzer)),
            'Initialization problem. Unable to get number of available channels')
        if c_n_avail_analyzer.value != 1:
            raise RuntimeError(self.perror('Current code only handles one Guzik card on the system.'))
        board_index = 0 # needs to be <c_n_avail_analyzer
        self._board_index = board_index
        self._gsa_data_arg = None
        serial_no = create_string_buffer(SDK.GSA_READ_CH_ID_LENGTH)
        pxi_addr = create_string_buffer(SDK.GSA_READ_CH_ID_LENGTH)
        brd_arg = SDK.GSA_BRD_LIST_ARG(version=SDK.GSA_SDK_VERSION)
        brd_arg_rc = SDK.GSA_BRD_LIST_ARG(version=SDK.GSA_SDK_VERSION)
        check_error(SDK.GSA_BoardsListGetInfo(brd_arg), 'Board list info error')
        check_error(SDK.GSA_RCBoardsListGetInfo(board_index, brd_arg_rc), 'RC board list info error')
        brd_arg.brd_max = brd_arg.brd_num
        brd_arg.gpu_max = brd_arg.gpu_num
        brd_arg_rc.brd_max = brd_arg_rc.brd_num
        brd_info = (SDK.GSA_BRD_INFO*brd_arg.brd_num)()
        brd_gpu = (SDK.GSA_GPU_INFO*brd_arg.gpu_num)()
        brd_info_rc = (SDK.GSA_BRD_INFO*brd_arg_rc.brd_num)()
        check_error(SDK.GSA_BoardsListGet(brd_arg, brd_info, brd_gpu), 'Board list error')
        check_error(SDK.GSA_RCBoardsListGet(board_index, brd_arg_rc, brd_info_rc), 'RC board list error')
        check_error(SDK.GSA_ReadChStringIdGet(SDK.String(serial_no), board_index, SDK.GSA_READ_CH_ID_SERIAL_NO),
                    'Error getting serial number')
        serial_no = serial_no.value
        check_error(SDK.GSA_ReadChStringIdGet(SDK.String(pxi_addr), board_index, SDK.GSA_READ_CH_ID_PXI_LEGACY),
                    'Error getting pxi_addr')
        pxi_addr = pxi_addr.value
        frame_slot = c_int()
        check_error(SDK.GSA_ReadChSlotGet(board_index, byref(frame_slot)), 'Error getting frame_slot number')
        frame_slot = frame_slot.value
        chs_info = SDK.GSA_READ_CH_INFO_RES(version=SDK.GSA_SDK_VERSION)
        check_error(SDK.GSA_ReadChInfoGet(board_index, chs_info), 'Error getting channel info')
        self._conf_general = dict_improved(board_index=board_index, serial_no=serial_no, pxi_addr=pxi_addr, frame_slot=frame_slot,
                                  brd_info=ppdict(brd_info),
                                  brd_info_rc=ppdict(brd_info_rc),
                                  brd_gpu= ppdict(brd_gpu),
                                  chs_info=ppdict(chs_info),
                                  full_lib_version=full_lib_version)
        self.config(1)

    @staticmethod
    def print_structure(struct):
        pp(struct)

    def print_timestamps(self):
        Nch = self._gsa_Nch
        res_arr = self._gsa_data_res_arr
        for j in range(Nch):
            res = res_arr[j]
            print('Channel %s'%res.common.used_input_label)
            n = res.common.timestamps_len
            ts = self._gsa_data_res_ts[j]
            tf = self._gsa_data_res_tf[j]
            to = ts[0]+tf[0]*1e-15
            print('Start time: ', time.ctime(to), ' + %i fs'%tf[0])
            for i in range(n):
                t = (ts[i] - ts[0]) + (tf[i]-tf[0])*1e-15
                print('Delta= %.15f s'%t)

    def _destroy_op(self):
        SDK = self._gsasdk
        arg = self._gsa_data_arg
        if arg is None:
            return
        if arg.hdr.op_handle != 0:
            arg.hdr.op_command = SDK.GSA_OP_DESTROY
            Nch = self._gsa_Nch
            res_arr = self._gsa_data_res_arr
            if SDK.GSA_Data_Multi(arg, Nch, res_arr) == SDK.GSA_FALSE:
                raise RuntimeError(self.perror('Unable to destroy op.'))
        self._gsa_data = None
        self._gsa_data_arg = None
        self._gsa_data_res_tf = None
        self._gsa_data_res_ts = None
        # free previous data memory
        self.fetch.setcache(None)
        # Finally make sure memory is released.
        # Note that at least for numpy 1.16.5, python 2.7.16, ctypes 1.1.0
        #  ndarray.ctypes creates a loop from ctypes.cast. To clean that requires a collect.
        gc.collect()

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = ['config=%s'%self.config()]
        opts += ['full_lib_version=%r'%self._conf_general.full_lib_version]
        opts += self._conf_helper(options)
        return opts

    def _read_ext_ref_state(self, board_num=0, src=-1, freq=0):
        """
        src = -1 (to return currently active channel), 0 for internal (200 MHz),
               2 for 1 GHz, 3 for Sync clock
        freq is the freq in MHz used for Sync clock entry
        Note that the ext_ref_state is updated only after an acquisition is complete, not after
              the config method.
        """
        SDK =  self._gsasdk
        if src == 2:
            freq = 1000 # This is needed when src=2 otherwise it does as if src == -1
        elif src == 2:
            freq = 200 # This might not be required but do it anyway.
        arg = SDK.GSA_READ_CH_CLOCK_INFO_ARG(version=SDK.GSA_SDK_VERSION, rc_idx=board_num, clk_src=src, freq=freq)
        res = SDK.GSA_READ_CH_CLOCK_INFO_RES()
        if SDK.GSA_ReadChClockSourceInfo(arg, res) == SDK.GSA_FALSE:
            raise RuntimeError(self.perror('Unable to read ext_ref_state'))
        to_bool = lambda x: x != SDK.GSA_FALSE
        to_same = lambda x: x
        to_src = lambda x: {0:'internal', 2:'ext_1GHz', 3:'sync_clock'}.get(x, x)
        conv = {'is_active':to_bool, 'is_connected':to_bool, 'is_locked':to_bool, 'clk_src':to_src, 'freq_MHz':to_same}
        return {k:conv[k](getattr(res, k)) for k,t in res._fields_}

    def _read_config(self):
        SDK = self._gsasdk
        channels = self._gsa_data_arg.common.input_labels_list
        #gain_db = self._gsa_data_arg.common.gain_dB
        bits_16 =(True if self._gsa_data_arg.common.data_type == SDK.GSA_DATA_TYPE_INT15BIT else False)
        bits_n = self.last_data_format()
        n_S_ch = self._gsa_data_res_arr[0].common.data_len
        Nch = self._gsa_Nch
        conv_offset = []
        conv_resolution=[]
        res_arr = self._gsa_data_res_arr
        low_pass_filter_MHz = []
        high_pass_filter_MHz = []
        gain_dB = []
        offset = []
        for i in range(Nch):
            conv_offset.append(res_arr[i].common.data_offset)
            conv_resolution.append(res_arr[i].common.ampl_resolution*1e-3)
            low_pass_filter_MHz.append(res_arr[i].common.used_lpf_cutoff_frq_MHz)
            high_pass_filter_MHz.append(res_arr[i].common.used_hpf_cutoff_frq_MHz)
            gain_dB.append(res_arr[i].common.used_input_gain_dB)
            offset.append(res_arr[i].common.ampl_offset_mV/1e3)
        sampling_period_ns = self._gsa_conf_ch.sampling_period_ns
        sampling_rate_GSs = 1./sampling_period_ns
        analog_bandwidth_MHz = self._gsa_conf_ch.analog_bandwidth_MHz
        equalizer_en =  self._gsa_data_arg.common.equ_state != SDK.GSA_EQU_OFF
        equalizer_mode =  self._gsa_data_arg.common.equ_state
        ref_clock = self._read_ext_ref_state()
        ret = locals()
        del ret['i'], ret['res_arr'], ret['self'], ret['SDK']
        return ret

    def config(self, channels=None, n_S_ch=1024, bits_16=True, gain_dB=0., offset=0., equalizer_en=True, force_slower_sampling=False, ext_ref='default', _hdr_func=None):
        """
        if channels is None, it returns information about the current config.
        channels needs be a list of integer that represent the channels (1-4).
        It can also be a single integer
        bits_16 when False, returns 8 bit data.
        n_S_ch is the number of Sample per ch to read.
        gain_dB is the gain in dB (can be a list). Range is probably (-22 to 32).
              see gz.print_structure(gz._gsa_conf_ch) to confirm.
        offset is the input offset to use (in V) (can be a list)
        equalizer_en when False turns off the FPGA equalizer.
        ext_ref can be 'default' which stays the same, 'int' (200 MHz), 'ext' for 1 GHz,
            or one of the allowed sync_clock frequency in MHz.
            Note that the change is only seen (like acqusition header) after a new acquisition.
        force_slower_sampling, when True will make single channel (or 1,3 or 2,4 pairs) sample
                 at 16 GS/s instead of 32 GS/s (it will also decrease the bandwith to 6.5 GHz from 10 GHz)
        To free the memory, delete any user variable that remembers a previous result,
        then call config with a new size. You might also need to call collect_garbage().
        _hdr_func if given is a func passed with the data_arg structure before it gets used, so it
        can be modified (useful when testing new parameter not already programmed)
        """
        if channels is None:
            return self._read_config()
        if not isinstance(channels, (np.ndarray, list, tuple)):
            channels = [channels]
        channels = sorted(set(channels)) # Make list of unique values and sorted.
        if not all([1<=c<=4 for c in channels]):
            raise ValueError(self.perror('Invalid channel number. Needs to be a number from 1 to 4.'))
        Nch = len(channels)
        if Nch == 0:
            raise RuntimeError(self.perror('Invalid number of channels'))
        if n_S_ch > 52.5*GiS:
            # This is only for 1 channels or 2 interleaved (1,3 or 2,3, or 2,4 or 1,4)
            # There is 64 GiB of ECC memory with 15/16 used. The 10 bit of a sample
            # is packed as 7 words of 10 bits into 72 bits of ECC (8 words of 9 bits)
            # So the packing is 7 samples (70 bits) into 8 words (72 bits)
            # 64/16.*15*7/8 = 52.5
            raise RuntimeError(self.perror('Maximum hardware request is 52.5 GiS'))
        S2B = 2 if bits_16 else 1
        if n_S_ch*Nch*S2B > (self._computer_memsize -  5*GiS):
            raise RuntimeError(self.perror('You are requesting more memory than is available (with a reserve of 5 GiB)'))
        self._destroy_op()
        self._gsa_Nch = Nch
        channels_list = ','.join(['CH%i'%i for i in channels])
        conf = c_long()
        SDK = self._gsasdk
        board_index = self._board_index
        if SDK.GSA_ReadChBestConfigGet(board_index, SDK.GSA_READ_CH_INP1, channels_list, byref(conf)) == SDK.GSA_FALSE:
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
        res_arr = (SDK.GSA_Data_RES*4)() # array of 4 RES
        if SDK.GSA_Data_Multi_Info(arg, Nch, res_arr, None) == SDK.GSA_FALSE:
            raise RuntimeError(self.perror('Unable to initialize acq structures.'))
        arg.common.rc_idx = 0
        arg.common.rc_conf = conf
        arg.common.input_labels_list = channels_list
        arg.common.acq_len = int(n_S_ch)
        #arg.common.acq_time_ns = 1000
        arg.common.sectors_num = 1
        #arg.common.sector_time_ns = 1000
        #arg.common.acq_timeout = 0 # in us. -1 for infinite
        arg.common.acq_adjust_up = SDK.GSA_TRUE
        arg.common.trigger_mode = SDK.GSA_DP_TRIGGER_MODE_IMMEDIATE
        if isinstance(gain_dB, (list, tuple, np.ndarray)):
            if len(gain_dB) != Nch:
                raise ValueError(self.perror('Incorrect number of gain_db elements'))
            for i, g in enumerate(gain_dB):
                arg.common.input_gains_dB[i] = g
        else:
            arg.common.gain_dB = gain_dB
        if isinstance(offset, (list, tuple, np.ndarray)):
            if len(offset) != Nch:
                raise ValueError(self.perror('Incorrect number of offset elements'))
            for i, off in enumerate(offset):
                arg.common.input_offsets_mV[i] = off*1e3
        else:
            arg.common.offset_mV = offset*1e3
        if not equalizer_en:
            arg.common.equ_state = SDK.GSA_EQU_OFF
        ts = [np.zeros(10, np.uint) for i in range(4)]
        tf = [np.zeros(10, np.uint64) for i in range(4)]
        self._gsa_data_res_ts = ts # timestamp in seconds
        self._gsa_data_res_tf = tf # timestamp in femtoseconds
        def set_addr(np_object, ct):
            # This used to work
            #return np_object.ctypes.data_as(POINTER(ct))
            # Now we need (otherwise some pointers are left and we need to collect_garbage)
            return pointer(ct.from_address(np_object.ctypes.data))
        for i in range(4):
            res_arr[i].common.timestamp_seconds.size = len(ts[i])
            #res_arr[i].common.timestamp_seconds.arr = ts[i].ctypes.data_as(POINTER(c_uint))
            res_arr[i].common.timestamp_seconds.arr = set_addr(ts[i], c_uint)
            res_arr[i].common.timestamp_femtoseconds.size = len(tf[i])
            #res_arr[i].common.timestamp_femtoseconds.arr = tf[i].ctypes.data_as(POINTER(c_uint64))
            res_arr[i].common.timestamp_femtoseconds.arr = set_addr(tf[i], c_uint64)
        if bits_16:
            arg.common.data_type = SDK.GSA_DATA_TYPE_INT15BIT
        else:
            arg.common.data_type = SDK.GSA_DATA_TYPE_SHIFTED8BIT
        arg.hdr.op_command = SDK.GSA_OP_CONFIGURE
        if force_slower_sampling:
            # other decimation can be entered but it will only decimate by 2
            # when sampling is at 32 GSa/s.
            # Other decimation are possible, but require an extra license.
            arg.common.decimation_factor = 2
        if ext_ref != 'default':
            if ext_ref == 'int':
                arg.common.ref_clock_source = 0
            elif ext_ref == 'ext':
                arg.common.ref_clock_source = 2
            else:
                arg.common.ref_clock_source = 3
                arg.common.ref_clock_freqMHz = ext_ref
        if _hdr_func is not None:
            _hdr_func(arg)
        if SDK.GSA_Data_Multi(arg, Nch, res_arr) == SDK.GSA_FALSE:
            raise RuntimeError(self.perror('Unable to finish initializing acq structure.'))
        self._gsa_data_arg = arg
        self._gsa_data_res_arr = res_arr
        N = res_arr[0].common.data_len
        for i in range(Nch):
            if res_arr[i].common.data_len != N:
                # if we see this exception then the algo below will need to change.
                raise RuntimeError(self.perror('Some channels are not expecting the same data length.'))
        if Nch > 1:
            dims = (Nch, N)
        else:
            dims = N
        if bits_16:
            dtype = np.int16
        else:
            dtype = np.uint8
        data = np.empty(dims, dtype)
        #data[...] = 1
        #print('data init done!')
        data_2d = data if Nch>1 else data.reshape((1, -1))
        for i in range(Nch):
            #res_arr[i].common.data.arr = data_2d[i].ctypes.data_as(POINTER(c_ubyte))
            res_arr[i].common.data.arr = set_addr(data_2d[i], c_ubyte)
            res_arr[i].common.data.size = data_2d[i].nbytes
        self._gsa_data = data
        # These are to try to obtain the res_arr[i].common.ampl_resolution
        #  (and offset) updated
        #   PREPARE is not enough. IMMEDIATE works but acts like a finish (does a full transfer)
        #   could try to adjust data/array size but instead will contact guzik to find
        #   a better way.
        #arg.hdr.op_command = SDK.GSA_OP_PREPARE
        #if SDK.GSA_Data_Multi(arg, Nch, res_arr) == SDK.GSA_FALSE:
        #    raise RuntimeError(self.perror('Unable to finish preparing acq structure.'))
        #arg.hdr.op_command = SDK.GSA_OP_IMMEDIATE_FINISH
        #if SDK.GSA_Data_Multi(arg, Nch, res_arr) == SDK.GSA_FALSE:
        #    raise RuntimeError(self.perror('Unable to force finish for acq structure.'))

    def last_equ_overflow(self):
        SDK = self._gsasdk
        over = [res.common.equ_overflow == SDK.GSA_TRUE for res in self._gsa_data_res_arr]
        if self._gsa_Nch == 1:
            return over[0]
        return over[:self._gsa_Nch]
    def last_data_format(self):
        """ obtains the data format for the last results. It can be:
              8: for shifted 8 bit (uint8)
              10: for shifted 10 bit (uint16 with only using lower 10 bits)
              16: for int 15bit (int16, using full 16 bits (except when equalizer is off, then it can be 15 lower bits))
             It could also be 0 for the default setting (like before an acquisition).
        """
        SDK = self._gsasdk
        conv = {SDK.GSA_DATA_TYPE_DEFAULT:0,
                SDK.GSA_DATA_TYPE_SHIFTED8BIT:8,
                SDK.GSA_DATA_TYPE_SHIFTED10BIT:10,
                SDK.GSA_DATA_TYPE_INT15BIT:16}
        fmt =  [res.common.data_type for res in self._gsa_data_res_arr]
        f = fmt[0]
        for i in range(self._gsa_Nch):
            if fmt[i] != f:
                raise RuntimeError(self.perror('Unexpected data format. They are not all the same.'))
        return conv[f]

    @staticmethod
    def conv_scale(data, res):
        return (data-res.common.data_offset)*(res.common.ampl_resolution*1e-3)

    def _fetch_getdev(self, raw=True):
        """
        options:
            raw: when True (default) it will return the integer. When False, converts to volts.
            bin (see get documentation)
        """
        SDK = self._gsasdk
        arg = self._gsa_data_arg
        res_arr = self._gsa_data_res_arr
        Nch = self._gsa_Nch
        arg.hdr.op_command = SDK.GSA_OP_FINISH
        if SDK.GSA_Data_Multi(arg, Nch, res_arr) == SDK.GSA_FALSE:
            raise RuntimeError(self.perror('Had a problem reading data.'))
        data = self._gsa_data
        if not raw:
            if Nch == 1:
                data = self.conv_scale(data, res_arr[0])
            else:
                data = np.array([self.conv_scale(data[i], res_arr[i]) for i in range(Nch)])
        return data

    def __del__(self):
        self.close()
        super(guzik_adp7104, self).__del__()

    def close(self):
        self._destroy_op()
        SDK = self._gsasdk
        SDK.GSA_SysDone(self._gsa_sys_cfg)

    def idn(self):
        return 'Guzik,%s,%s,%i'%(self._conf_general.brd_info_rc[0].name,
                                       self._conf_general.serial_no,
                                       self._conf_general.chs_info.version)

    def get_error(self, basic=False, printit=True):
        SDK = self._gsasdk
        s = ctypes.create_string_buffer(SDK.GSA_ERROR_MAX_BUFFER_LENGTH)
        if basic:
            ret = SDK.GSA_ErrorHandleStr(SDK.GSA_ERR_PRINT_BASIC, SDK.String(s), len(s))
        else:
            ret = SDK.GSA_ErrorHandleStr(SDK.GSA_ERR_PRINT_FULL, SDK.String(s), len(s))
        if ret == SDK.GSA_TRUE: # = -1
            if printit:
                print(s.value)
            else:
                return s.value
        else:
            if printit:
                print('No errors')
            else:
                return None

    def _create_devs(self):
        self._devwrap('fetch', autoinit=False)
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(guzik_adp7104, self)._create_devs()

# Tests results:
#gz = instruments.guzik_adp7104()
#gz.config(1,1e9, bits_16=True)
#%timeit v=get(gz.fetch)
## 1 loop, best of 3: 1.47 s per loop
#gz.config(1,1e9, bits_16=False)
#%timeit v=get(gz.fetch)
## 1 loop, best of 3: 1.26 s per loop
#gz.config([1,3],1e9, bits_16=False)
#%timeit v=get(gz.fetch)
## 1 loop, best of 3: 1.29 s per loop
#gz.config([1,3],1e9, bits_16=True)
#%timeit v=get(gz.fetch)
## 1 loop, best of 3: 2.35 s per loop
