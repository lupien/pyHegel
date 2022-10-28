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
import os.path
import threading
import time
import weakref
import socket
import select

from ..instruments_base import BaseInstrument,\
                            BaseDevice, scpiDevice, MemoryDevice, ReadvalDev,\
                            _repr_or_string, ChoiceStrings,\
                            decode_float32, locked_calling,\
                            _retry_wait, Block_Codec, _delayed_signal_context_manager,\
                            _sleep_signal_context_manager, FastEvent, ProxyMethod
from ..instruments_registry import register_instrument

#register_usb_name('Agilent Technologies', 0x0957)

#######################################################
##   Signal Hound SM200C signal analyzer
#######################################################

class TimeoutError(RuntimeError):
    pass

class SignalHound_SM200C_listen_thread(threading.Thread):
    def __init__(self, control, keep_alive=0):
        super(SignalHound_SM200C_listen_thread, self).__init__()
        self.control = control
        self._stop = False
        self._last_entry = None
        self._last_10 = []
        self._lock = threading.Lock()
        self.data_available_event = FastEvent()
        self.daemon = True # This will allow python to exit
        self.control.set_timeout = .2
        self.keep_alive = keep_alive
        self._last_comm = time.time()

    def __del__(self):
        print 'deleting SignalHound_SM200C_listen_thread'

    def cancel(self):
        self._stop = True

    def run(self):
        # This print is needed on anaconda 2019.10 on windows 10 to prevent
        #  a windows error exeption when later trying to print in the thread (status_line)
        # Doing a print at the beginning of the thread fixes that problem.
        print 'Listen Thread started'
        readers = [self.control._socket]
        while True:
            if self._stop:
                return
            if len(self.control._read_extra):
                rs = readers
            else:
                rs, ws, xs = select.select(readers, [],  [], .1) # timeout of .1 s
            if rs != []:
                data = self.control._read()
                self.put_data(data)
            now = time.time()
            if self.keep_alive != 0 and (self._last_comm + self.keep_alive) < now:
                self.send_keep_alive()

    def send_keep_alive(self):
        self.control.write('') # sends just a newline.

    def keep_alive_update(self):
        self._last_comm = time.time()

    def put_data(self, data):
        with self._lock:
            now = time.time()
            entry = (data, now)
            self._last_entry = entry
            last10  = self._last_10
            last10.insert(0, entry)
            if len(last10) > 10:
                del last10[10]
            self.data_available_event.set()

    def get_last(self):
        with self._lock:
            ret = self._last_entry
            if ret is None:
                ret = ('', -1)
            self._last_entry = None
            self._last_entry_time = None
            self.data_available_event.clear()
        return ret

    def get_next(self, timeout=None):
        if timeout is None or timeout == 'infinite':
            while not self.data_available_event.wait(1):
                return self.get_last()
        if self.data_available_event.wait(timeout):
            return self.get_last()
        else:
            return ('', -2)

    def wait(self, timeout=None):
        # we use a the context manager because join uses sleep.
        with _sleep_signal_context_manager():
            self.join(timeout)
        return not self.is_alive()



# Tried using visaInstrument, but implementing the listen thread made everything slow
# because visa write has to wait for the visa read to end.
# So this new version uses sockets directly

#@register_instrument('SignalHound', 'SM200C', '8.8.6')
@register_instrument('SignalHound', 'SM200C')
class SignalHound_SM200C(BaseInstrument):
    """
    This is the driver for the SignalHound SM200C spectrum analyzer
    To use readval, you should make shure that cont_trigger is False (readval turns it off)
    otherwise your first readval might use old data.
    Readval (or async or run_and_wait) will repeat as many time as the largest average cnt
    for updating curves that have average type, or even Min/Max types if trace_reset_mnmx_en
    is True.
    Also Note that trace average can be more averaged than the selected count if another trace
    averages more. For example if trace1 asks for 2 and trace2 asks for 50, than trace1
    will be averaged more like 6 (at least for verision 3.7.2 of Spike software.)
    Useful devices:
        fetch, readval
        marker_y
        freq_start, freq_stop, freq_center, freq_span
        bw_res, bw_video, bw_res_auto, bw_video_auto, sweep_time
        cont_trigger
        snap_png
    Some methods available:
        trace_clear
        connect, disconnect, is_active
        preset_save, preset_load
        recalibrate
        marker_do
    Other useful devices:
        current_trace
        current_mkr
        marker_x
        trace_reset_mnmx_en
    A lot of other commands require a selected trace or a mkr
    see current_trace, current_mkr
    """
    def __init__(self, addr='localhost', port=5025, Ro=50., timeout=1.,*args, **kwargs):
        """ Ro is the impedance used in power conversions. see unit option in fetch """
        self.Ro = Ro
        self._socket = None
        self._helper_thread = None
        self._connect_socket(addr, port, timeout)
        s = weakref.proxy(self)
        self._helper_thread = SignalHound_SM200C_listen_thread(s)
        self._helper_thread.start()
        self.read_timeout = 3.
        self._read_extra = ''
        self._chunk_size = 2**16
        self._async_last_response = None
        self._async_max_count = 0
        self._async_current_count = 0
        super(SignalHound_SM200C, self).__init__(*args, **kwargs)
        self._async_mode = 'opc'

    def _connect_socket(self, addr='localhost', port=5025, timeout=1):
        self._socket = socket.create_connection((addr, port), timeout=timeout)

    def __del__(self):
        self._close_helper_thread()
        self._disconnect_socket()
        super(SignalHound_SM200C, self).__del__()

    def _disconnect_socket(self):
        if self._socket is not None:
            self._socket.shutdown(socket.SHUT_RDWR)
            self._socket.close()
            self._socket = None

    def _close_helper_thread(self):
        if self._helper_thread is not None:
            self._helper_thread.cancel()
            self._helper_thread.wait(.5)
            self._helper_thread = None

    def _keep_alive_update(self):
        if self._helper_thread is not None:
            self._helper_thread.keep_alive_update()

    @locked_calling
    def write(self, val, termination='default'):
        if termination == 'default':
            termination = '\n'
        self._socket.send(val+termination)
        self._keep_alive_update()

    @locked_calling
    def ask(self, question, raw=None, chunk_size=None):
        """
        Does write then read.
        raw is unsed here (it is there to match scpiDevice calls)
        """
        # we prevent CTRL-C from breaking between write and read using context manager
        with _delayed_signal_context_manager():
            self.write(question)
            ret = self.read(chunk_size=chunk_size)
        return ret

    def _read_block(self, min_size=1, chunk_size=None):
        if chunk_size is None:
            chunk_size = self._chunk_size
        max_size = max(min_size, chunk_size)
        N = chunk_size
        data = bytearray(max_size)
        cnt = 0
        while cnt < min_size:
            N = min(max_size-cnt, chunk_size)
            new_data = self._socket.recv(N)
            self._keep_alive_update()
            n = len(new_data)
            if n == 0:
                raise TimeoutError(self.perror('Read_block timeout'))
            data[cnt:cnt+n] = new_data
            cnt += n
        return data[:cnt]

    def _read_n_or_nl(self, count=None, chunk_size=None):
        """ if count is None, read until newline. remove newline """
        term = '\n'
        if count is None:
            data = self._read_extra
            while term not in data:
                data += self._read_block(chunk_size=chunk_size)
            data, rest = data.split(term, 1)
            self._read_extra = rest
            return bytes(data)
        else:
            data = bytearray(count)
            d = self._read_extra
            self._read_extra = ''
            n = 0
            while n < count:
                left = count - n
                ld = len(d)
                if ld >= left:
                    data[n:n+left] = d[:left]
                    self._read_extra = d[left:]
                    break
                data[n:n+ld] = d
                n += ld
                d = self._read_block(left-ld, chunk_size=chunk_size)
            return bytes(data)

    def _read(self, chunk_size=None):
        term = '\n'
        read_f = lambda x=None: self._read_n_or_nl(x, chunk_size=chunk_size)
        data = read_f(1)
        if data.startswith(b'#'):
            cnt = read_f(1)
            data += cnt
            N = read_f(int(cnt))
            data += N
            data += read_f(int(N)+1)
            if data[-1] != term:
                raise RuntimeError(self.perror('Did not receive expected termination character.'))
            data = bytes(data[:-1]) # remove newline and convert to byte string
        else:
            data += read_f()
        return data

    @locked_calling
    def read(self, timeout=None, chunk_size=None):
        """ timeout can be 'infinite' """
        if self._helper_thread is None:
            return self._read(chunk_size=chunk_size)
        else:
            if timeout is None:
                timeout = self.read_timeout
            ret = self._helper_thread.get_next(timeout)[0]
            if ret == '':
                raise TimeoutError(self.perror('read timeout'))
            return ret

    def wait_after_trig(self, no_exc=False):
        try:
            super(SignalHound_SM200C, self).wait_after_trig()
        except Exception:
            if not no_exc:
                raise

    def _async_trig_init(self, avg_count=0):
        self._async_last_response = None
        self._async_max_count = avg_count
        self._async_current_count = 0

    def _async_trig_helper(self):
        self.write('INITiate;*OPC?')

    @locked_calling
    def _async_trig(self):
        orig_trace = self.current_trace.get()
        max_count = 0
        reset_mnmx = self.trace_reset_mnmx_en.get()
        for t in range(1, 6+1):
            if not self.trace_updating.get(trace=t):
                continue
            typ = self.trace_type.get().lower()
            if typ == 'average':
                self.trace_clear()
                count = self.trace_average_count.get()
                max_count = max(count, max_count)
            elif reset_mnmx and typ not in ['off', 'write']:
                self.trace_clear()
                count = self.trace_average_count.get()
                max_count = max(count, max_count)
        self._async_trig_init(max_count)
        self.current_trace.set(orig_trace)
        self.cont_trigger.set(False)
        super(SignalHound_SM200C, self)._async_trig()
        #self.trace_clear('all')
        self._async_trig_helper()

    def _async_detect(self, max_time=.5): # 0.5 s max by default
        try:
            ret = self.read(timeout=max_time)
        except TimeoutError:
            return False
        if ret != '1':
            raise RuntimeError(self.perror('unexpected return from async_detect'))
        self._async_current_count += 1
        if self._async_current_count < self._async_max_count:
            self._async_trig_helper()
            return False
        self._async_last_response = ret
        return True

    def init(self, full=False):
        self.write(':FORMat:TRACe REAL') # 32bit floating little endian
        #self.write(':FORMat:TRACe ASCii')
        #self.write(':FORMat:IQ BINary') # 16bit integer
        #self.write(':FORMat:IQ ASCii')
        super(SignalHound_SM200C, self).init(full=full)

    def idn(self):
        return self.ask('*idn?')

    @locked_calling
    def reset_poweron(self):
        """
        This returns the instrument to a known state.
        Use CAREFULLY!
        """
        self._async_trig_init()
        self.write('*RST;*OPC?')
        self.wait_after_trig(no_exc=True)
        if self._async_last_response != '1':
            raise RuntimeError(self.perror('Error after reset.'))
        self.init(True)
        self.force_get()

    def get_error(self):
        return self.ask('SYSTem:ERRor?')

    def preset_save(self, filename_or_num):
        """ saves a preset.
            provide either a number 1-9 or a filename.
            The filename should have .ini as an extension. """
        if filename_or_num in range(1, 9+1):
            self.write('*SAV %d'%filename_or_num)
        else:
            self.write(':SYSTem:PRESet:SAVE "%s"'%filename_or_num)

    def preset_load(self, filename_or_num):
        """ load a preset.
            provide either a number 1-9, a filename or None.
            The filename should have .ini as an extension.
            if filename is None, it will load the default preset.
            It can take 6-20 s to load a preset (especially the default one).
        """
        if filename_or_num is None:
            self._async_trig_init()
            self.write(':SYSTem:PRESet?')
            self.wait_after_trig(no_exc=True)
            if self._async_last_response != '1':
                raise RuntimeError(self.perror('Error loading preset.'))
        elif filename_or_num in range(1, 9+1):
            self.write('*RCL %d'%filename_or_num)
        else:
            self.write(':SYSTem:PRESet:LOAD "%s"'%filename_or_num)

    def disconnect(self):
        self._async_trig_init()
        self.write(':SYSTem:DEVice:DISConnect?')
        self.wait_after_trig(no_exc=True)
        if self._async_last_response != '1':
            raise RuntimeError(self.perror('Error disconnecting.'))

    def connect(self, name=None):
        """ connect to device called name.
            if name is None (the default), list available names.
            This will only work if you are disconnected (is_active is False)
        """
        if self.is_active.get():
            if name is None:
                return []
            else:
                raise RuntimeError('Already connected')
        if name is None:
            l = self.ask(':SYSTem:DEVice:LIST?')
            return l.split(',')
        else:
            self._async_last_response = None
            self.write(':SYSTem:DEVice:CONnect? %s'%name)
            self.wait_after_trig(no_exc=True)
            ret = bool(int(self._async_last_response))
            if not ret:
                raise RuntimeError(self.perror('Was unable to connect'))

    def _snap_png_getdev(self, filename=None):
        """ Without a filename, get will use the quick save.
            You should use a full path for the filename.
            It is saved by the Spike software so uses its default directory
            which is probably C:\Program Files\Signal Hound\Spike\
            The Quick file save defaults to %USERPROFILE%\Documents\SignalHound
        """
        if filename is None:
            self.write(':SYSTem:IMAGe:SAVe:QUICk')
        else:
            f = os.path.abspath(filename)
            self.write(':SYSTem:IMAGe:SAVe "%s"'%f)

    def recalibrate(self):
        self.write(':INSTrument:RECALibrate')

    @locked_calling
    def trace_clear(self, trace=None):
        """ Clears the trace, or all traces if you ask 'all' """
        if trace == 'all':
            self.write(':TRACe:CLEar:ALL')
            return
        if trace is not None:
            self.current_trace.set(trace)
        self.write(':TRACe:CLEar')

    def _current_config_trace_helper(self, traces=None):
        # traces needs to be a list or None
        just_one = False
        if not isinstance(traces, (list)):
            just_one = True
            traces = [traces]
        trace_conf = ['current_trace', 'trace_type', 'trace_updating', 'trace_displaying',
                      'trace_average_count', 'trace_xstart', 'trace_xincrement', 'trace_npoints']
        ret = []
        if traces[0] is not None:
            old_trace = self.current_trace.get()
        for t in traces:
            if t is not None:
                self.current_trace.set(t)
            tret = []
            for n in trace_conf:
                # follows _conf_helper
                val = _repr_or_string(getattr(self, n).getcache())
                tret.append(val)
            if ret == []:
                ret = tret
            else:
                ret = [old+', '+new for old, new in zip(ret, tret)]
        if traces[0] is not None:
            self.current_trace.set(old_trace)
        if just_one:
            ret = [n+'='+v for n, v in zip(trace_conf, ret)]
        else:
            ret = [n+'=['+v+']' for n, v in zip(trace_conf, ret)]
        return ret

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        extra = []
        base_conf = self._conf_helper('instrument_mode', 'cont_trigger', 'ref_oscillator',
                                      'freq_start', 'freq_center', 'freq_stop', 'freq_span',
                                      'bw_res', 'bw_res_auto', 'bw_video', 'bw_video_auto', 'bw_res_shape',
                                      'rf_level_dBm', 'rf_level_offset_dB', 'rf_attenuation_auto', 'rf_attenuation_index',
                                      'rf_preamp_en', 'rf_preamp_auto', 'rf_preselector_en', 'rf_spur_reject_en',
                                      'sweep_time', 'sweep_detector_function', 'sweep_detector_units', 'trace_reset_mnmx_en',
                                      'trace_math_en', 'trace_math_first', 'trace_math_second', 'trace_math_result', 'trace_math_offset',
                                      'trace_math_operation',
                                      'system_temperature', 'system_voltage', 'system_current', 'current_device')
        base_conf += ['system_version=%r'%self.system_version]
        base_end = self._conf_helper(options)
        # trace
        if dev_obj in [self.readval, self.fetch]:
            traces_opt = self._fetch_traces_helper(options.get('traces'), options.get('updating'))
            extra = self._current_config_trace_helper(traces_opt)
        elif dev_obj in [self.get_trace]:
            extra = self._current_config_trace_helper()
        # marker dependent
        if dev_obj in [self.marker_x, self.marker_y]:
            orig_mkr = self.current_mkr.get()
            extra = self._conf_helper('current_mkr', 'marker_en', 'marker_trace', 'marker_mode', 'marker_update_en',
                                      'marker_delta_en', 'marker_peak_search_tracking_en', 'marker_x', 'marker_y',
                                      'marker_peak_excursion', 'marker_peak_threshold', 'marker_channel_power_width', 'marker_ndb_offset', 'marker_ndb_left', 'marker_ndb_right')
            self.current_mkr.set(orig_mkr)
            extra += self._current_config_trace_helper(self.marker_trace.getcache())
        return extra+base_conf+base_end

    @locked_calling
    def marker_do(self, function, mkr=None):
        """ available functions: 'find_max', 'find_next_max', 'find_max_left', 'find_max_right', 'find_min'
                                 'set_center', 'set_rf_level'
        """
        if mkr is not None:
            self.current_marker.set(mkr)
        cmds = dict(find_max=':CALCulate:MARKer:MAXimum',
                    find_next_max=':CALCulate:MARKer:MAXimum:NEXT',
                    find_max_left=':CALCulate:MARKer:MAXimum:LEFT',
                    find_max_right=':CALCulate:MARKer:MAXimum:RIGHt',
                    find_min=':CALCulate:MARKer:MINimum',
                    set_center=':CALCulate:MARKer[:SET]:CENTer',
                    set_rf_level=':CALCulate:MARKer[:SET]:RLEVel')
        if function not in cmds:
            raise ValueError(self.perror('Invalid option. Use one of: %r'%cmds))
        self.write(cmds[function])
    @locked_calling
    def get_xscale(self, trace=None):
        """
        Returns the currently active x scale. It uses cached values so make sure
        they are up to date.
        This scale is recalculated but produces the same values (within floating
        point errors) as the instrument.
        """
        if trace is not None:
            self.current_trace.set(trace)
        start = self.trace_xstart.getcache()
        inc = self.trace_xincrement.getcache()
        N = self.trace_npoints.getcache()
        return np.arange(N)*inc + start
    def _create_devs(self):
        self.system_version = self.ask(':SYSTem:VERsion?')
        if self.idn_split()['model']=='SM200C':
            minfreq = 100e3
            maxfreq = 20.1e9
        else:
            minfreq = 100e3
            maxfreq = 43.5e9
        # This does not work as of 2022-10-14
        #self.display_title = scpiDevice(':DISPlay:ANNotation:TITLe', str_type=quoted_string)
        self.system_temperature = scpiDevice(getstr=':SYSTem:TEMPerature?', str_type=float)
        self.system_voltage = scpiDevice(getstr=':SYSTem:VOLTage?', str_type=float)
        self.system_current = scpiDevice(getstr=':SYSTem:CURRent?', str_type=float)
        self.is_active = scpiDevice(getstr=':SYSTem:DEVice:ACTive?', str_type=bool)
        self.current_device = scpiDevice(getstr=':SYSTem:DEVice:CURRent?')
        self.cont_trigger = scpiDevice('INITiate:CONTinuous', str_type=bool)
        self.instrument_mode = scpiDevice(':INSTrument', choices=ChoiceStrings('SA', 'RTSA', 'ZS', 'HARMonics', 'NA', 'PNoise', 'DDEMod', 'EMI', 'ADEMod', 'IH', 'SEMask', 'WLAN', 'BLE', 'LTE', 'IDLE'))
        self.ref_oscillator = scpiDevice(':ROSCillator:SOURce', choices=ChoiceStrings('INTernal', 'EXTernal', 'OUTput'))
        self.freq_start = scpiDevice(':FREQuency:STARt', str_type=float, min=minfreq, max=maxfreq-10., setget=True)
        self.freq_stop = scpiDevice(':FREQuency:STOP', str_type=float, min=minfreq, max=maxfreq, setget=True)
        self.freq_center = scpiDevice(':FREQuency:CENTer', str_type=float, min=minfreq, max=maxfreq, setget=True)
        self.freq_span = scpiDevice(':FREQuency:SPAN', str_type=float, min=0., max=maxfreq-minfreq, setget=True)
        self.rf_level_dBm =  scpiDevice(':POWer:RLEVel', str_type=float, setget=True)
        self.rf_level_offset_dB =  scpiDevice(':POWer:RLEVel:OFFSet', str_type=float, setget=True)
        self.rf_attenuation_index = scpiDevice(':POWer:ATTenuation', str_type=int)
        self.rf_attenuation_auto = scpiDevice(':POWer:ATTenuation:AUTO', str_type=bool)
        self.rf_preamp_en = scpiDevice(':POWer:PREAMP', str_type=bool)
        self.rf_preamp_auto = scpiDevice(':POWer:PREAMP:AUTO', str_type=bool)
        self.rf_preselector_en = scpiDevice(':POWer:MW:PRESelector', str_type=bool, doc='Only for SM200A instruments')
        self.rf_spur_reject_en = scpiDevice(':POWer:SPURReject', str_type=bool)
        self.bw_res = scpiDevice(':BANDwidth', str_type=float, min=.1, setget=True)
        self.bw_res_auto = scpiDevice(':BANDwidth:AUTO', str_type=bool)
        self.bw_video = scpiDevice(':BANDwidth:VIDeo', str_type=float, min=.1)
        self.bw_video_auto = scpiDevice(':BANDwidth:VIDeo:AUTO', str_type=bool)
        self.bw_res_shape = scpiDevice(':BANDwidth:SHAPe', choices=ChoiceStrings('GAUSsian', 'FLATtop', 'NUTTall'))

        self.sweep_time = scpiDevice(':SWEep:TIME', str_type=float, min=1e-6, setget=True)
        self.sweep_detector_function = scpiDevice(':SWEep:DETector:FUNCtion', choices=ChoiceStrings('AVERage', 'MINMAX', 'MIN', 'MAX'),
                                                  doc="""
                                                  Note that MINMAX returns the same data as MAX (but display is different).
                                                  To see the difference between the options requires a long sweep time.
                                                  """)
        self.sweep_detector_units = scpiDevice(':SWEep:DETector:UNITs', choices=ChoiceStrings('POWer', 'SAMPle', 'VOLTage', 'LOG'),
                                               doc="""
                                               Sample overrides detector_function.
                                               Other options work for average detector function.
                                               They require a video bandwidth smaller than the resolution bandwidth or a long sweep time.
                                               """)

        self.current_mkr = scpiDevice(':CALCulate:MARKer:SELect', str_type=int, min=1, max=9)
        def devMkrOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_mkr)
            app = kwarg.pop('options_apply', ['mkr'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.marker_en = devMkrOption(':CALCulate:MARKer:STATe', str_type=bool)
        self.marker_trace = devMkrOption(':CALCulate:MARKer:TRACe', str_type=int, min=1, max=6)
        self.marker_mode = devMkrOption(':CALCulate:MARKer:MODE', choices=ChoiceStrings('POSition', 'NOISE', 'CHPower', 'NDB'))
        self.marker_update_en = devMkrOption(':CALCulate:MARKer:UPDate', str_type=bool)
        self.marker_delta_en = devMkrOption(':CALCulate:MARKer:DELTa', str_type=bool)
        self.marker_peak_search_tracking_en = devMkrOption(':CALCulate:MARKer:PKTRack', str_type=bool)
        self.marker_x = devMkrOption(':CALCulate:MARKer:X', str_type=float, trig=True)
        self.marker_y = devMkrOption(getstr=':CALCulate:MARKer:Y?', str_type=float, trig=True)
        self.marker_peak_excursion = devMkrOption(':CALCulate:MARKer:PEAK:EXCursion', str_type=float, setget=True)
        self.marker_peak_threshold = devMkrOption(':CALCulate:MARKer:PEAK:THReshold', str_type=float, setget=True)
        self.marker_channel_power_width = devMkrOption(':CALCulate:MARKer:CHPower:WIDth', str_type=float, setget=True)
        self.marker_ndb_offset = devMkrOption(':CALCulate:MARKer:NDB', str_type=float, setget=True)
        self.marker_ndb_left = devMkrOption(getstr=':CALCulate:MARKer:NDB:RLEFt?', str_type=float, trig=True)
        self.marker_ndb_right = devMkrOption(getstr=':CALCulate:MARKer:NDB:RRIGht?', str_type=float, trig=True)
        self.marker_ndb_width = devMkrOption(getstr=':CALCulate:MARKer:NDB:BANDwidth?', str_type=float, trig=True)
        self.trace_math_en = scpiDevice(':CALCulate:MATH', str_type=bool)
        self.trace_math_first = scpiDevice(':CALCulate:MATH:FIRST', str_type=int, min=1, max=6)
        self.trace_math_second = scpiDevice(':CALCulate:MATH:SECond', str_type=int, min=1, max=6)
        self.trace_math_result = scpiDevice(':CALCulate:MATH:RESult', str_type=int, min=1, max=6)
        self.trace_math_offset = scpiDevice(':CALCulate:MATH:OFFSet', str_type=float, setget=True)
        self.trace_math_operation = scpiDevice(':CALCulate:MATH:OP',  choices=ChoiceStrings('PDIFF', 'PSUM', 'LOFFset', 'LDIFF'))

        self.trace_reset_mnmx_en = MemoryDevice(True, choices=[True, False])
        self.current_trace = scpiDevice(':TRACe:SELect', str_type=int, min=1, max=6)
        def devTraceOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(trace=self.current_trace)
            app = kwarg.pop('options_apply', ['trace'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.trace_type = devTraceOption(':TRACe:TYPE', choices=ChoiceStrings('OFF', 'WRITe', 'AVERage', 'MAXHold', 'MINHold', 'MINMAX'),
                                         doc="Note that MINMAX returns the same data as MAXHold (but display is different).")
        self.trace_average_count = devTraceOption(':TRACe:AVERage:COUNt', str_type=int, min=2)
        self.trace_average_current = devTraceOption(getstr=':TRACe:AVERage:CURRent?', str_type=int)
        self.trace_updating = devTraceOption(':TRACe:UPDate', str_type=bool)
        self.trace_displaying = devTraceOption(':TRACe:DISPlay', str_type=bool)
        self.trace_npoints = devTraceOption(getstr=':TRACe:POINts?', str_type=int)
        self.trace_xstart = devTraceOption(getstr=':TRACe:XSTARt?', str_type=float)
        self.trace_xincrement = devTraceOption(getstr=':TRACe:XINCrement?', str_type=float)
        self.get_trace = devTraceOption(getstr=':TRACe?', str_type=decode_float32, autoinit=False, trig=True)
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        self._devwrap('snap_png', autoinit=False, trig=True)
        self.snap_png._format['file'] = True
        self.snap_png._format['bin'] = '.png'
        # This needs to be last to complete creation
        super(SignalHound_SM200C, self)._create_devs()

#TODO make this function work.
    def _noise_eq_bw_getdev(self):
        """
        Using the bw_res and bw_res_shape this estimates the bandwith
        necessary to convert the data into power density.

        For gaussian filters the error in the estimate compared to the marker
        result is at most 0.06 dB (1.4% error) at 4 MHz (DB3),
        otherwise it is mostly within 0.01 dB (0.23%)
        For Flattop filters the error is at most -0.45 dB at 8 MHz (11%),
        otherwise it is mostly 0.040 - 0.050 (0.92-1.12%), centered around
        0.045 dB (1.0% offset) for bw below 120 kHz. (EXA N9010A, MY51170142)
        The correction means the equivalent bandwidth used for markers is
        1% greater than the selected value of the flat bandwidth. To correct
        for this, you can substract the noise density by 0.045 dB (or divide by
        1.010 if linear power scale).

        To see this errors, or to obtain the same factor as for the markers,
        set the instrument in the following way:
            -select resolution bandwidth (range, type ...)
            -setup a trace (assume units are dB...)
            -on trace put 2 markers at the same position
            -First marker shows just the raw value
            -Second marker setup to show noise (either noise or band density function)
            -Set band span for second marker to 0 (or the a single bin)
            -Then the bandwith used for marker calculation is
             10**((marker1-marker2)/10)
        You can see both by enabling the marker table. Note that for the function
        results the Y and function column should be the same here, but when the
        band span is larger they will be different. The Y value is the value of
        the function when the sweep has reached the marker position so it uses
        old values after the marker and so is not a valid result. You should
        consider the function result as the proper one. That is the value
        returned by marker_y devce in that case.

        The band power function is the integral of the band density over the
        selected band span (a span of 0 is the same as a span of one bin).
        So when band span is one bin:
            band_power(dBm)-band_density(dBm) = 10*log10(bin_width(Hz))
            bin_width = (freq_stop-freq_start)/(npoints-1)

        The distinction between the noise function and the band density function
        is that the noise function tries to apply correction for non-ideal
        detectors (peak, negative peak) or wrong averaging (volt, log Pow).
        The correction is calculated assuming the incoming signal is purely noise,
        and considers the video bandwidth.
        The band density function makes no such assumption and will return
        incorrect values for wrong detector/averaging. The best result is normally
        obtained with averaging detector in RMS mode.
        """
        return 1.
        #bw = self.bw_res.get()
        bw_mode = self.bw_res_shape.get()
        if bw_mode in self.bw_res_shape.choices[['gaussian']]:
            # The filters are always the same. They are defined for db3
            # but they are reported differently in the other modes.
            # We need the noise one.
            # In theory:
            #  The 3dB full width is 2*sqrt(log(2))*sigma
            #  The 6dB full width is sqrt(2) times 3dB
            #  The noise width is sqrt(pi)/(2*sqrt(log(2))) times 3dB (and is equivalent bw for power: from integral of V**2)
            #  The impulse width is sqrt(2) times noise (and is equivalent bw for amplitude: from integral of V)
            # In practice we use the noise and it is probably related to the
            # 3dB by some calibration. The conversion factor between 3dB and noise returned by
            # the instrument is not a constant (it is ~1.065).
            old_gaus_type = self.bw_res_gaussian_type.get()
            self.bw_res_gaussian_type.set('noise')
            bw = self.bw_res.get()
            self.bw_res_gaussian_type.set(old_gaus_type)
            # get the bw_res cache back to the correct value
            self.bw_res.get()
        else: # flat
            # Normally the equivalent noise bandwidth of a flat filter
            # is the bw of the filter. However, in practice, it could be different.
            bw = self.bw_res.get()
            # TODO maybe decide to apply the correction
            #bw *= 1.01
        return bw
    def _fetch_getformat(self, **kwarg):
        unit = kwarg.get('unit', 'default')
        xaxis = kwarg.get('xaxis', True)
        traces = kwarg.get('traces', None)
        updating = kwarg.get('updating', True)
        traces = self._fetch_traces_helper(traces, updating)
        if xaxis:
            multi = ['freq(Hz)']
        else:
            multi = []
        for t in traces:
            multi.append('trace%i'%t)
        fmt = self.fetch._format
        multi = tuple(multi)
        fmt.update(multi=multi, graph=[], xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_traces_helper(self, traces, updating=True):
        """
        When updating is True, only updating trace are selected when
        traces=None. Otherwise all visible traces are selected.
        """
        if isinstance(traces, (tuple, list)):
            pass
        elif traces is not None:
            traces = [traces]
        else: # traces is None
            traces = []
            old_trace = self.current_trace.get()
            for t in range(1, 6+1):
                if self.trace_type.get(trace=t).lower() == 'off':
                    continue
                if updating and self.trace_updating.get():
                    traces.append(t)
                elif not updating and self.trace_displaying.get():
                    traces.append(t)
            self.current_trace.set(old_trace)
        return traces
    def _convert_unit(self, v, from_unit, to_unit, bw):
        Ro = self.Ro
        if to_unit == 'default':
            return v
        from_unit = from_unit.upper()
        db_list = ['DBM', 'DBMV', 'DBMA', 'DBUV', 'DBUA', 'DBUVM', 'DBUAM', 'DBPT', 'DBG']
        db_ref = [1e-3, 2e-8, 5e-5, 2e-14, 5e-11, 0, 0, 0, 0] # in W
        if from_unit in db_list:
            in_db = True
            i = db_list.index(from_unit)
            in_ref = db_ref[i]
            if in_ref == 0:
                raise ValueError, self.perror("Don't know how to convert from antenna unit %s"%from_unit)
        else: # V, W and A
            in_db = False
            # convert to W
            if from_unit == 'V':
                v = v**2 / Ro
            elif from_unit == 'A':
                v = v**2 * Ro
        to_db_list = ['dBm', 'dBm_Hz']
        to_lin_list = ['W', 'W_Hz', 'V', 'V_Hz', 'V2', 'V2_Hz']
        if to_unit not in to_db_list+to_lin_list:
            raise ValueError, self.perror("Invalid conversion unit: %s"%to_unit)
        if not to_unit.endswith('_Hz'):
            bw = 0
        if to_unit in to_db_list:
            if in_db:
                v = v + 10*np.log10(in_ref/1e-3)
            else: # in is in W
                v = 10.*np.log10(v/1e-3)
            if bw:
                v -= 10*np.log10(bw)
        else: # W, V and V2 and _Hz variants
            if in_db:
                v = in_ref*10.**(v/10.)
            if to_unit in ['V', 'V_Hz']:
                bw = np.sqrt(bw)
                v = np.sqrt(v*Ro)
            elif to_unit in ['V2', 'V2_Hz']:
                v = v*Ro
            if bw:
                v /= bw
        return v
    def _fetch_getdev(self, traces=None, updating=True, unit='default', xaxis=True):
        """
         Available options: traces, updating, unit, xaxis
           -traces:  can be a single value or a list of values.
                     The values are integer representing the trace number (1-6)
           -updating: is used when traces is None. When True (default) only updating traces
                      are fetched. Otherwise all visible traces are fetched.
           -unit: can be default (whatever the instrument gives) or
                       'dBm'    for dBm
                       'W'      for Watt
                       'V'      for Volt
                       'V2'     for Volt**2
                       'dBm_Hz' for noise density
                       'W_Hz'   for W/Hz
                       'V_Hz'   for V/sqrt(Hz)
                       'V2_Hz'  for V**2/Hz
                 It can be a single value or a vector the same length as traces
                 See noise_eq_bw device for information about the
                 bandwidth used for _Hz unit conversion.
            -xaxis:  when True(default), the first column of data is the xaxis

           This version of fetch assumes all the data have the same x-scale (should be the
           case when they are all updating).
        """
        traces = self._fetch_traces_helper(traces, updating)
        orig_trace = self.current_trace.get()
        self.current_trace.set(traces[0])
        if xaxis:
            ret = [self.get_xscale()]
        else:
            ret = []
        if not isinstance(unit, (list, tuple)):
            unit = [unit]*len(traces)
        base_unit = 'dBm'
        #noise_bw = self.noise_eq_bw.get()
        noise_bw = self._noise_eq_bw_getdev()
        for t, u in zip(traces, unit):
            v = self.get_trace.get(trace=t)
            v = self._convert_unit(v, base_unit, u, noise_bw)
            ret.append(v)
        self.current_trace.set(orig_trace)
        ret = np.asarray(ret)
        if ret.shape[0]==1:
            ret=ret[0]
        return ret

# TODO: :SENSe:CORRection:PATHloss[1-8]:*
