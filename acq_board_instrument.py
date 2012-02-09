# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:
"""
Created on Fri Dec 09 13:39:09 2011

@author: blas2310
"""

# system import
import socket
import select
import threading
import math
import os
import weakref
import matplotlib.pyplot as plt
import numpy as np
import sys

# user made import
import instrument

class acq_bool(object):
    def __call__(self, input_str):
        if input_str == 'False':
            return False
        elif input_str == 'True':
            return True
        else:
            return None
    def tostr(self, val):
        if val == None:
            raise ValueError, 'acq_bool should not be None'
        return repr(val)

class acq_filename(object):
    def __call__(self, input_str):
        if input_str[0] != '<' or input_str[0] != '>':
            print 'Filename is missing < >'
            return input_str
        return input_str[1:-1]
    def tostr(self, val):
        return '<'+val+'>'

class acq_device(instrument.scpiDevice):
    def __init__(self, *arg, **kwarg):
        super(type(self), self).__init__(*arg, **kwarg)
        self._event_flag = threading.Event()
        self._event_flag.set()
        self._rcv_val = None
    def _getdev(self):
        if self._getdev_p == None:
           raise NotImplementedError, self.perror('This device does not handle _getdev')
        self._event_flag.clear()
        self.instr.write(self._getdev_p)
        instrument.wait_on_event(self._event_flag, check_state=self.instr)
        return self._fromstr(self._rcv_val)

class dummy_device(object):
    def __init__(self, getstr):
        self._rcv_val = None
        self._event_flag = threading.Event()
        self._getdev_p = getstr
    def _getdev(self, quest_extra=''):
        self._event_flag.clear()
        if quest_extra:
            quest_extra=' '+quest_extra
        self.instr.write(self._getdev_p + quest_extra)
        instrument.wait_on_event(self._event_flag, check_state=self.instr)
        return self._rcv_val

# TODO: there is still a problem with acq.disconnect
#        the listen thread is not terminated properly
#        it crashes on the next connect (when object gets deleted)
class Listen_thread(threading.Thread):
    def __init__(self, acq_instr):
        super(type(self), self).__init__()
        self.daemon = True
        self._stop = False
        self.acq_instr = weakref.proxy(acq_instr)
    def run(self):
        select_list = [self.acq_instr.s]
        socket_timeout = 0.1
        old_stuff = ''
        bin_mode = False
        block_length = 0
        total_byte = 0
        acq = self.acq_instr
        rcv_ptr = 0
        while not self._stop:
            if bin_mode and len(old_stuff) > 0:
                pass
            else:
                try:
                    r, _, _ = select.select(select_list, [], [], socket_timeout)
                    if not bool(r):
                        continue
                except socket.error:
                    break
            #print 'Listen Available:',
            if bin_mode:
                if len(old_stuff) != 0:
                    next_readlen = block_length-len(old_stuff)
                    new_stuff = old_stuff
                    old_stuff = ''
                else:
                    new_stuff = acq.s.recv(next_readlen)
                    next_readlen = block_length
                #print 'BIN',repr(new_stuff)
                total_byte -= len(new_stuff)
                if total_byte < 0:
                    old_stuff = new_stuff[total_byte:]
                    new_stuff = new_stuff[:total_byte]
                if acq.fetch._dump_file != None:
                    acq.fetch._dump_file.write(new_stuff)
                    acq.fetch._rcv_val = None
                else:
                    acq.fetch._rcv_val[rcv_ptr:]=new_stuff
                    rcv_ptr+=len(new_stuff)
                if total_byte <= 0:
                    if acq.fetch._dump_file == None:
                        acq.fetch._rcv_val = bytes(acq.fetch._rcv_val)
                    bin_mode = False
                    acq.fetch._event_flag.set()
                    new_stuff = ''
                else:
                    continue
            else:
                new_stuff = acq.s.recv(128)
            #print repr(new_stuff)
            old_stuff += new_stuff
            trames = old_stuff.split('\n', 1)
            old_stuff = trames.pop()
            while trames != []:
                trame = trames[0]
                if trame[0] != '@' and trame[0] != '#':
                    continue
                if trame[0] == '@':
                    trame = trame[1:]
                    head, val = trame.split(' ', 1)
                    if head.startswith('ERROR:'):
                        if head == 'ERROR:STD':
                            acq._errors_list.append('STD: '+val)
                            print 'Error: ', val
                        elif head == 'ERROR:CRITICAL':
                            acq._errors_list.append('CRITICAL: '+val)
                            acq._error_state = True
                            print '!!!!!!!!!!!\n!!!!!CRITICAL ERROR!!!!!: ', val,'\n!!!!!!!!!!!!!'
                        else:
                            acq._errors_list.append('Unknown: '+val)
                            print 'Unkown error', head, val
                    else:
                        obj = acq._objdict.get(head, None)
                        if obj == None:
                            acq._errors_list.append('Unknown @'+head+' val:'+val)
                            print 'Listen Thread: unknown @header:',head, 'val=', val
                        else:
                            obj._rcv_val = val
                            obj._event_flag.set()
                            # update _cache for STATUS result
                            if obj == acq.board_status or obj == acq.result_available or \
                                      obj == acq.partial_status:
                                obj._cache = obj._fromstr(val)
                            if obj == acq.partial_status:
                                partial_L, partial_v = obj._cache
                                sys.stdout.write('\rPartial %3i/%-3i     '%(partial_v,partial_L))
                            if obj == acq.result_available:
                                # run is finished for any result_available status received
                                # wether True or False
                                acq._run_finished.set()
                else: # trame[0]=='#'
                    trame = trame[1:]
                    head, val = trame.split(' ', 1)
                    location, typ, val = val.split(' ', 2)
                    if location == 'Local':
                        filename = val
                        acq.fetch._rcv_val = None
                        acq.fetch._event_flag.set()
                    else: # location == 'Remote'
                        bin_mode = True
                        rcv_ptr = 0
                        block_length, total_byte = val.split(' ')
                        next_readlen = block_length = int(block_length)
                        total_byte = int(total_byte)
                        acq.fetch._rcv_val = bytearray(total_byte)
                        break;
                trames = old_stuff.split('\n', 1)
                old_stuff = trames.pop()
        print 'Thread Ending....'

    def cancel(self):
        self._stop = True
    def wait(self, timeout=None):
        self.join(timeout)
        return not self.is_alive()


# TODO: Add CHECKING verification in init and instrument write/read.
class Acq_Board_Instrument(instrument.visaInstrument):
    
    def __init__(self, ip_adress, port_nb):
        self._listen_thread = None
        self._errors_list = []
        self._error_state = False
        
        # init the server member
        self.host = ip_adress
        self.port = port_nb
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # clock initialization
        self._clock_src_init_done = False
        
        # try connect to the server
        self.s.connect((self.host, self.port))
        self.set_timeout = 5

        # status and flag
        self.board_type = None
        self.Get_Board_Type()
        if not self.board_type in ['ADC8', 'ADC14']:
            raise ValueError, 'Invalid board_type'

        # maximum value
        if self.board_type == 'ADC8':
            self._max_sampling = 3000
            self._min_sampling = 1000
            self._min_nb_Msample = 32
            self._max_nb_Msample = 4294967295
            self._max_Msample = 4294959104
            self._min_acq_Msample = 32
            self._max_acq_Msample = 8192
            self._min_net_Msample = 32
            self._max_net_Msample = 128
        else: # ADC14
            self._max_sampling = 400
            self._min_sampling = 20
            self._max_Msample = 2147479552
            self._min_acq_Msample = 16
            self._max_acq_Msample = 4096
            self._min_net_Msample = 16
            self._max_net_Msample = 64
        self._min_usb_clock_freq = 200
        self._min_nb_Msample_all = 32
        self._max_nb_Msample_all = 4294967295
        self._max_nb_tau = 50

        self.visa_addr = self.board_type
        self._run_finished = threading.Event() # starts in clear state

        self._listen_thread = Listen_thread(self)
        self._listen_thread.start()     
        
        # init the parent class
        instrument.BaseInstrument.__init__(self)

    def idn(self):
        # Should be: Manufacturer,Model#,Serial#,firmware
        model = self.board_type
        serial = self.board_serial.getcache()
        return 'Acq card,%s,%s,1.0'%(model, serial)
    def cls(self):
        """ Clear error buffer and status
        """
        self._error_state = False
        self._errors_list = []
    def _check_error(self):
        if self._error_state:
            raise ValueError, 'Acq Board currently in error state. clear it with _get_error.'
    def get_error(self):
        if self._errors_list == []:
            self._error_state = False
            return '+0,"No error"'
        return self._errors_list.pop()
    @property
    def set_timeout(self):
        return self.s.gettimeout()
    @set_timeout.setter
    def set_timeout(self, seconds): # can be None
        self.s.settimeout(seconds)
    def __del__(self):
        print 'deleting acq1'
        # TODO  find a proper way to shut down connection
        # self.shutdown() (stop thread then send shutdown...)
        if self._listen_thread:
            self._listen_thread.cancel()
            self._listen_thread.wait()
        self.s.close()

    def _async_trig(self):
        self._run_finished.clear()
        self.run()
    def _async_detect(self):
        return instrument.wait_on_event(self._run_finished, check_state=self, max_time=.5)
    def wait_after_trig(self):
        return instrument.wait_on_event(self._run_finished, check_state=self)
    def run_and_wait(self):
        self._async_trig()
        self.wait_after_trig()

    def _current_config(self, dev_obj=None, options={}):
        if self.op_mode.getcache() == 'Acq':
            return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                     'chan_nb','chan_mode')
                                     
        if self.op_mode.getcache() == 'Hist':
            return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                     'chan_nb')
                                     
        if self.op_mode.getcache() == 'Corr':
            return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                     'autocorr_mode', 'corr_mode','autocorr_single_chan',
                                     'chan_mode','chan_nb',)
                           
        if self.op_mode.getcache() == 'Net':
            return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                     'lock_in_square','net_signal_freq','nb_harm')
                                     
        if self.op_mode.getcache() == 'Osc':
            return self._conf_helper('op_mode', 'sampling_rate', 'clock_source','osc_nb_sample',
                                     'osc_hori_offset', 'osc_trigger_level', 'osc_slope', 'osc_trig_source',
                                     'chan_mode','chan_nb')
        
        if self.op_mode.getcache() == 'Spec':
             return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                      'chan_mode','chan_nb','fft_length')
                                     
        if self.op_mode.getcache() == 'Cust':
             return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                      'chan_mode','chan_nb','cust_param1','cust_param2','cust_param3',
                                      'cust_param4') 
                                     

    def dummy_devs_iter(self):
        for devname in dir(self):
           obj = getattr(self, devname)
           if isinstance(obj, dummy_device):
               yield devname, obj

    def init(self,full = False):
        if full == True:
            self._objdict = {}
            for devname, obj in self.devs_iter():
                if isinstance(obj, acq_device):
                    name = obj._getdev_p[:-1]
                    self._objdict[name] = obj
            for devname, obj in self.dummy_devs_iter():
                name = obj._getdev_p[:-1]
                obj.instr = weakref.proxy(self)
                self._objdict[name] = obj

        # if full = true do one time
        # get the board type and program state
        self.board_serial.get()
        self.board_status.get()
        self.result_available.get()
        self.tau_vec([0])

    def convert_bin2v(self, bin, off=True, auto_inv=True):
        if self.board_type == 'ADC14':
            vrange = 0.750
            resolution = 2.**14
            offset = 2.**13
            sign = -1.
        else: # 8bit
            vrange = 0.700
            resolution = 2.**8
            offset = 2.**7
            sign = +1.
        if off == False:
            offset = 0.
        if auto_inv == False:
            sign = 1.
        return (bin - offset)*sign*vrange/resolution

    def _fetch_getformat(self, filename=None, ch=[1], unit='default'):
        fmt = self.fetch._format
        fmt.update(file=False)
        fmt.update(bin=False)
        mode = self.op_mode.getcache()
        if mode == 'Acq':
            #if self.nb_Msample.getcache() > 64:
            #    fmt.update(file=True)
            #fmt.update(bin='.npy')
            fmt.update(file=True)
        return instrument.BaseDevice.getformat(self.fetch)

    def _fetch_filename_helper(self, filename, extra=None, newext=None):
        filestr=''
        location = self.format_location()
        tofilename = acq_filename().tostr
        if location == 'Local':
            if filename == None:
                raise ValueError, 'A filename is needed'
            root, ext = os.path.splitext(filename)
            if extra != None:
                root = root + '_' + extra
            if newext != None:
                ext = newext
            filename = root + ext
            filestr = ' ' + tofilename(filename)
        return filestr


    def _fetch_getdev(self, filename=None, ch=None, unit='default'):
        """
           fetch is used to obtain possibly large data sets.
           It should only be called after performing an acquisition (run),
           otherwise the data is unavailable, and it will hang (press CTRL-C to abort).
           Changing acq mode (with one of the set commands) also looses the data and
           requires a run.

           Possible optional parameters are
            -filename  used for dumping the data directly to a file
                       In local mode, the saving will be done by data acquisition server
                        (so filename location should be accessible by it)
                       In remote mode, the saving is done by python but only
                       for Acq mode (in a streaming way, to avoid memory problems).
                       Otherwise it is discarded.
                       For multiple channels, the filename is modified to include
                       and identifier for the channel.
                       The extension is always changed to .bin
            -unit      to change the output format
                       unknown units are treated as 'default'
            -ch        to select which channel to read (can be a list)

           Behavior according to modes:
               Acq:  ch as no effect here
                     By default the data is return as unsigned integers
                      (char for 8bit, short for 14bit).
                     It can be in volts for unit='V'
                     When in 'Single' mode, it is a 1D vector of the selected
                     channel.
                     When in 'Dual' mode, it is a 2D vector (2,N)
                      where [0,:] is ch1 and [1,:] is ch2
               Osc:  Same as for Acq

               Hist: by default returns a vector of uint64 of size
                     256 (8bit) or 16384 (14bit). These bins contain the count
                     of events in that binary code from the ADC.
                     When unit='rate', the return vector is the count rate
                     in count/s as floats.

               For all the following, ch can select which channels to return
               To select one channel: ch=1 or ch=[1]
                 Then the return values form a 1D vector
               To select multiple channels: ch=[1,2]
                 Then the return values form a 2D vector, where
                 the first dimension is the channel number sorted
                 (so ch=[1,2] or ch=[2,1] should return the exact same vector)
               Note asking for a channel that was not measured will probably fail.

               Net: by default, returns the various harmonics of ch=2,
                    as a complex number in V (peak).
                    unit='amplitude' returns abs(result)
                    unit='angle' returns angle(result, deg=True)
                    unit='real' returns result.real
                    unit='imag' returns result.imag
               Spec: by default, returns amplitudes in Volts of
                        ch=[1,2] in Dual or of the selected channel in Single
                    unit='V2' returns the V^2
                    unit='V/sHz' returns V/sqrt(bin BW), BW=bandwidth
                    unit='W' returns the power in W assuming R0=50 Ohms
                    unit='W/Hz' returns power/(bin BW)
                    unit='dBm' returns W converted to dBm
                    unit='dBm/Hz' returns W/Hz converted to dBm
               Corr: by default, returns the bit^2 of the correlation.
                    unit='V2' returns it in V^2
                      The selectable channels are:
                          ch=0 for cross-correlation between ch1 and ch2,
                          ch=1 for auto-correlation of ch1
                          ch=2 for auto-correlation of ch2
                      by default for set_correlation it is ch=0
                                 for set_autocorrelation not in single_chan mode
                                  is ch=[1,2] otherwise it is the selected channel
                                 for set_auto_and_corr not in single_chan mode it is
                                     ch=[0,1,2] otherwise it is
                                     either ch=[0,1] or ch=[0,2] depending
                                     on selected channel
               Custom: returns whatever the custom code should return
                       which depends on loaded custom dll
        """
        mode = self.op_mode.getcache()
        location = self.format_location()
        # All saving by server or by dump_file is binary so change ext
        if filename != None:
            filename = instrument._replace_ext(filename, '.bin')
        filestr= self._fetch_filename_helper(filename)
        self.fetch._dump_file = None
        if not self.result_available.getcache():
            raise ValueError, 'Error result not available\n' 

        if mode == 'Acq':
            self.fetch._event_flag.clear()
            if location == 'Remote' and filename != None:
                self.fetch._dump_file = open(filename, 'wb')
            s = 'DATA:ACQ:DATA?'+filestr
            self.write(s)
            instrument.wait_on_event(self.fetch._event_flag, check_state=self)
            if self.fetch._dump_file != None:
                self.fetch._dump_file.close()
            if self.fetch._rcv_val == None:
                return None
            if self.board_type == 'ADC14':
                ret = np.fromstring(self.fetch._rcv_val, np.ushort)
            else:
                ret = np.fromstring(self.fetch._rcv_val, np.ubyte)
            if self.chan_mode.getcache() == 'Dual':
                ret.shape=(-1,2)
                ret = ret.T
            if unit == 'V':
                return self.convert_bin2v(ret)
            else:
                return ret

        if mode == 'Hist':
            self.fetch._event_flag.clear()
            s = 'DATA:HIST:DATA?'+filestr
            self.write(s)
            instrument.wait_on_event(self.fetch._event_flag, check_state=self)
            if self.fetch._rcv_val == None:
                return None
            ret = np.fromstring(self.fetch._rcv_val, np.uint64)
            if unit == 'rate':
                return ret*1./self.nb_Msample.getcache()* \
                        self.sampling_rate.getcache()*self.decimation.getcache()
            else:
                return ret

        if mode == 'Net':
            if ch == None:
                ch = 2
            if type(ch) != list:
                ch = [ch]
            ret = []
            if 1 in ch: 
                self.fetch._event_flag.clear()
                filestr = self._fetch_filename_helper(filename,'1')
                s = 'DATA:NET:HARM_CH1?'+filestr
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                ret.append(np.fromstring(self.fetch._rcv_val, np.complex128))
            if 2 in ch:
                self.fetch._event_flag.clear()
                filestr = self._fetch_filename_helper(filename,'2')
                s = 'DATA:NET:HARM_CH2?'+filestr
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                ret.append(np.fromstring(self.fetch._rcv_val, np.complex128))
            ret = np.asarray(ret)
            if ret.shape[0]==1:
                ret=ret[0]
            if unit == 'amplitude':
                return np.abs(ret)
            if unit == 'angle':
                return np.angle(ret, deg=True)
            if unit == 'real':
                return ret.real
            if unit == 'imag':
                return ret.imag
            else:
                return ret

        if mode == 'Osc':
            self.fetch._event_flag.clear()
            s = 'DATA:OSC:DATA?'+filestr
            self.write(s)
            instrument.wait_on_event(self.fetch._event_flag, check_state=self)
            if self.fetch._rcv_val == None:
                return None
            if self.board_type == 'ADC14':
                ret = np.fromstring(self.fetch._rcv_val, np.ushort)
            else:
                ret = np.fromstring(self.fetch._rcv_val, np.ubyte)
            if self.chan_mode.getcache() == 'Dual':
                ret.shape=(-1,2)
                ret = ret.T
            if unit == 'V':
                return self.convert_bin2v(ret)
            else:
                return ret

        if mode == 'Spec':
            # TODO prevent ch2 form overwrite ch1 in the file
            if ch == None:
                if self.chan_mode.getcache() == 'Dual':
                    ch = [1,2]
                else:
                    ch = self.chan_nb.getcache()
            if type(ch) != list:
                ch = [ch]
            ret = []
            if 1 in ch:            
                self.fetch._event_flag.clear()
                filestr = self._fetch_filename_helper(filename,'1')
                s = 'DATA:SPEC:CH1?'+filestr
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                ret.append(np.fromstring(self.fetch._rcv_val, np.float64))
            if 2 in ch:
                self.fetch._event_flag.clear()
                filestr = self._fetch_filename_helper(filename,'2')
                s = 'DATA:SPEC:CH2?'+filestr
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                ret.append(np.fromstring(self.fetch._rcv_val, np.float64))
            ret = np.asarray(ret)
            if ret.shape[0]==1:
                ret=ret[0]
            V = ret
            xscale = self.get_xscale()
            bin_width = xscale[1]-xscale[0]
            if unit == 'V2':
                return V*V
            elif unit == 'V/sHz':
                return V/np.sqrt(bin_width)
            elif unit == 'W':
                return V*V/50.
            elif unit == 'W/Hz':
                return V*V/50./bin_width
            elif unit == 'dBm':
                return 10*np.log10(V*V/50./1e-3)
            elif unit == 'dBm/Hz':
                return 10*np.log10(V*V/50./1e-3/bin_width)
            else:
                return V

        if mode == 'Corr':
            # TODO prevent ch2 form overwrite ch1 in the file
            if ch == None:
                ch = []
                if self.corr_mode.getcache():
                    ch.append(0)
                if self.autocorr_mode.getcache():
                    if self.autocorr_single_chan.getcache():
                        ch.append(self.chan_nb.getcache())
                    else:
                        ch.extend([1,2])
            if type(ch) != list:
                ch = [ch]
            ret = []
            if 0 in ch:
                self.fetch._event_flag.clear()
                filestr = self._fetch_filename_helper(filename,'corr')
                s = 'DATA:CORR:CORR_RESULT?'+filestr
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                ret.append(np.fromstring(self.fetch._rcv_val, np.float64))
            if 1 in ch:
                self.fetch._event_flag.clear()
                filestr = self._fetch_filename_helper(filename,'auto1')
                s = 'DATA:CORR:AUTOCORR_CH1_RESULT?'+filestr
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                ret.append(np.fromstring(self.fetch._rcv_val, np.float64))
            if 2 in ch:
                self.fetch._event_flag.clear()
                filestr = self._fetch_filename_helper(filename,'auto2')
                s = 'DATA:CORR:AUTOCORR_CH2_RESULT?'+filestr
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                ret.append(np.fromstring(self.fetch._rcv_val, np.float64))
            ret = np.asarray(ret)
            if ret.shape[0]==1:
                ret=ret[0]
            if unit == 'V2':
                return self.convert(self.convert_bin2v(ret, off=False),off=False)
            else:
                return ret

        if mode == 'Cust':
            # TODO prevent ch2 form overwrite ch1 in the file
            if ch == None:
                ch = 1
            if type(ch) != list:
                ch = [ch]
            ret = []
            if 1 in ch:
                self.fetch._event_flag.clear()
                filestr = self._fetch_filename_helper(filename,'1')
                s = 'DATA:CUST:RESULT_DATA1?'+filestr
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                ret.append(np.fromstring(self.fetch._rcv_val, np.float64))
            if 2 in ch:
                self.fetch._event_flag.clear()
                filestr = self._fetch_filename_helper(filename,'2')
                s = 'DATA:CUST:RESULT_DATA2?'+filestr
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                ret.append(np.fromstring(self.fetch._rcv_val, np.float64))
            ret = np.asarray(ret)
            if ret.shape[0]==1:
                ret=ret[0]
            return ret


    def _readval_getdev(self, **kwarg):
        # TODO may need to check if trigger is already in progress
        self._async_trig()
        while not self._async_detect():
            pass
        return self.fetch._getdev(**kwarg)
    def _readval_getformat(self, **kwarg):
        return self.fetch.getformat(**kwarg)
    # TODO redirect read to fetch when doing async

    def _tau_vec_helper(self, i, val):
        self.write('CONFIG:TAU %r %r'%(i, val))
    def _nb_tau_helper(self, N):
        self.write('CONFIG:NB_TAU %i'%N)
        self.tau_vec.nb_tau = N
    def _tau_vec_setdev(self, vals, i=None, append=False):
        # for the _cache to maintain coherency, this dev needs setget
        # check has made sure the parameter make sense so we proceed
      
        try:
            # vals is a vector
            # don't care for i or append
            N = len(vals)
            self._nb_tau_helper(N)
            for i, val in enumerate(vals):
                self._tau_vec_helper(i, val)
            self.tau_vec._current_tau_vec = list(vals)
            return
        except TypeError:
            pass
        if i != None:
            self._tau_vec_helper(i, vals)
            self.tau_vec._current_tau_vec[i] = vals
        else: # append
            i = N = self.tau_vec.nb_tau
            N += 1
            self._nb_tau_helper(N)
            self._tau_vec_helper(i, vals)
            self.tau_vec._current_tau_vec.append(vals)
    def _tau_vec_getdev(self, force=False, i=None, append=None):
        if not force:
            return self.tau_vec._current_tau_vec
        # we read from device
        N = int(self._tau_nb._getdev())
        self.tau_vec.nb_tau = N
        self.tau_vec._current_tau_vec = []
        for i in range(N):
            ind, val = self._tau_veci._getdev(repr(i)).split(' ')
            if i != int(ind):
                raise ValueError, 'read wrong index. asked for %i, got %s'%(i, ind)
            self.tau_vec._current_tau_vec.append(int(val))
        return self.tau_vec._current_tau_vec

    def _tau_vec_check(self, vals, i=None, append=False):
        # i is an index
        try:
            # vals is a vector
            # don't care for i or append
            N = len(vals)
            if N > self._max_nb_tau:
                raise ValueError, 'Too many values in tau_vec.set, max of %i elements'%self._max_nb_tau
            return
        except TypeError:
            pass
        if not np.isreal(vals):
            raise ValueError, 'vals needs to be a number'
        if i != None and not (0 <= i <= self.tau_vec.nb_tau):
            raise ValueError, 'Index is out of range'
        if append and self.tau_vec.nb_tau + 1 >= self._max_nb_tau:
            raise ValueError, 'You can no longer append, reached max'
        if i != None and append:
            raise ValueError, 'Choose either i or append, not both'

    def _hist_ms_getformat(self, filename=None, m=[1,2,3,4,5]):
        if not isinstance(m, (list, tuple, set, np.ndarray)):
            m=[m]
        m=sorted(set(m)) # removes duplicates, and sort
        if min(m)<1 or max(m)>5:
            raise ValueError, 'Selector out of range, should be 1-5'
        fmt = self.hist_ms._format
        headers = [ 'm%i'%i for i in m]
        fmt.update(multi=headers, graph=range(len(headers)))
        return instrument.BaseDevice.getformat(self.hist_ms, m=m)
    def _hist_ms_getdev(self, m=[1,2,3,4,5]):
        if not isinstance(m, (list, tuple, np.ndarray)):
            m=[m]
        ret = []
        if 1 in m:
            ret.append(self.hist_m1.get())
        if 2 in m:
            ret.append(self.hist_m2.get())
        if 3 in m:
            ret.append(self.hist_m3.get())
        if 4 in m:
            ret.append(self.hist_m4.get())
        if 5 in m:
            ret.append(self.hist_m5.get())
        return ret

        #device member
    def _create_devs(self):

        # choices string and number
        op_mode_str = ['Null', 'Acq', 'Corr', 'Cust', 'Hist', 'Net', 'Osc', 'Spec']
        clock_source_str = ['Internal', 'External', 'USB']
        chan_mode_str = ['Single','Dual']
        osc_slope_str = ['Rising','Falling']
        format_location_str = ['Local','Remote']
        format_type_str = ['Default','ASCII','NPZ']
        
        #device init
        # Configuration
        self.op_mode = acq_device('CONFIG:OP_MODE', str_type=str, choices=op_mode_str)

        self.sampling_rate = acq_device('CONFIG:SAMPLING_RATE', str_type=float,  min=self._min_sampling, max=self._max_sampling)

        self.decimation = acq_device('CONFIG:DECIMATION', str_type=int, min=1, max=1024)
        self.acq_verbose = acq_device('CONFIG:ACQ_VERBOSE', str_type=acq_bool())
        self.test_mode = acq_device('CONFIG:TEST_MODE', str_type=acq_bool())
        self.clock_source = acq_device('CONFIG:CLOCK_SOURCE', str_type=str, choices=clock_source_str)
        self.nb_Msample = acq_device('CONFIG:NB_MSAMPLE', str_type=int,  min=self._min_nb_Msample_all, max=self._max_nb_Msample_all)
        self.chan_mode = acq_device('CONFIG:CHAN_MODE', str_type=str, choices=chan_mode_str)
        self.chan_nb = acq_device('CONFIG:CHAN_NB', str_type=int,  min=1, max=2)
        self.trigger_invert = acq_device('CONFIG:TRIGGER_INVERT', str_type=acq_bool())
        self.trigger_edge_en = acq_device('CONFIG:TRIGGER_EDGE_EN', str_type=acq_bool())
        self.trigger_await = acq_device('CONFIG:TRIGGER_AWAIT', str_type=acq_bool())
        self.trigger_create = acq_device('CONFIG:TRIGGER_CREATE', str_type=acq_bool())
        
        if self.board_type == 'ADC8':
            self.osc_trigger_level = acq_device('CONFIG:OSC_TRIGGER_LEVEL', str_type=float,  min=-0.35, max=0.35)
        elif self.board_type == 'ADC14':
            self.osc_trigger_level = acq_device('CONFIG:OSC_TRIGGER_LEVEL', str_type=float,  min=-0.375, max=0.375)
        
        self.osc_slope = acq_device('CONFIG:OSC_SLOPE', str_type=str, choices=osc_slope_str) 
        self.osc_nb_sample = acq_device('CONFIG:OSC_NB_SAMPLE', str_type=int,  min=1, max= ((16*1024*1024)-1)) # max 16MB
        self.osc_hori_offset = acq_device('CONFIG:OSC_HORI_OFFSET', str_type=int,  min=-(8*1024*1024), max= ((8*1024*1024)-1)) # max 8MB
        self.osc_trig_source = acq_device('CONFIG:OSC_TRIG_SOURCE', str_type=int,  min=1, max=2)
        
        if self.board_type == 'ADC8':
            self.net_signal_freq = acq_device('CONFIG:NET_SIGNAL_FREQ', str_type=float,  min=0, max=375000000)
        elif self.board_type == 'ADC14':
            self.net_signal_freq = acq_device('CONFIG:NET_SIGNAL_FREQ', str_type=float,  min=0, max=50000000)
        
        self.lock_in_square = acq_device('CONFIG:LOCK_IN_SQUARE', str_type=acq_bool())
        self.nb_harm = acq_device('CONFIG:NB_HARM',str_type=int, min=1, max=100)
        self.autocorr_mode = acq_device('CONFIG:AUTOCORR_MODE', str_type=acq_bool())
        self.corr_mode = acq_device('CONFIG:CORR_MODE', str_type=acq_bool())
        self.autocorr_single_chan = acq_device('CONFIG:AUTOCORR_SINGLE_CHAN', str_type=acq_bool())
        self.fft_length = acq_device('CONFIG:FFT_LENGTH', str_type=int)
        self.cust_param1 = acq_device('CONFIG:CUST_PARAM1', str_type=float)
        self.cust_param2 = acq_device('CONFIG:CUST_PARAM2', str_type=float)
        self.cust_param3 = acq_device('CONFIG:CUST_PARAM3', str_type=float)
        self.cust_param4 = acq_device('CONFIG:CUST_PARAM4', str_type=float)
        self.cust_user_lib = acq_device('CONFIG:CUST_USER_LIB', str_type=acq_filename())
        self.board_serial = acq_device(getstr='CONFIG:BOARD_SERIAL?',str_type=int)
        self.board_status = acq_device(getstr='STATUS:STATE?',str_type=str)
        self.partial_status = acq_device(getstr='STATUS:PARTIAL?',str_type=instrument._decode_uint32)
        self.result_available = acq_device(getstr='STATUS:RESULT_AVAILABLE?',str_type=acq_bool())
        
        self.format_location = acq_device('CONFIG:FORMAT:LOCATION', str_type=str, choices=format_location_str)
        self.format_type = acq_device('CONFIG:FORMAT:TYPE',str_type=str, choices=format_type_str)
        self.format_block_length = acq_device('CONFIG:FORMAT:BLOCK_LENGTH',str_type = int, min=1, max=4294967296)

        # Results
        #histogram result
        self.hist_m1 = acq_device(getstr = 'DATA:HIST:M1?', str_type = float, autoinit=False, trig=True)
        self.hist_m2 = acq_device(getstr = 'DATA:HIST:M2?', str_type = float, autoinit=False, trig=True)
        self.hist_m3 = acq_device(getstr = 'DATA:HIST:M3?', str_type = float, autoinit=False, trig=True)
        self.hist_m4 = acq_device(getstr = 'DATA:HIST:M4?', str_type = float, autoinit=False, trig=True)
        self.hist_m5 = acq_device(getstr = 'DATA:HIST:M5?', str_type = float, autoinit=False, trig=True)
        docstr="""
           hist_ms has optionnal parameter m=[1,2,3,4,5]
           It specifies which of the moment to obtain and returns
           a list of the selected ones. By default, all are selected.
        """
        self._devwrap('hist_ms', autoinit=False, trig=True, doc=docstr)
        # TODO histogram raw data
        
        #TODO correlation result
        #TODO 
        
        # network analyzer result
        self.custom_result1 = acq_device(getstr = 'DATA:CUST:RESULT1?',str_type = float, autoinit=False, trig=True)
        self.custom_result2 = acq_device(getstr = 'DATA:CUST:RESULT2?',str_type = float, autoinit=False, trig=True)
        self.custom_result3 = acq_device(getstr = 'DATA:CUST:RESULT3?',str_type = float, autoinit=False, trig=True)
        self.custom_result4 = acq_device(getstr = 'DATA:CUST:RESULT4?',str_type = float, autoinit=False, trig=True)
        
        self.net_ch1_freq = acq_device(getstr = 'DATA:NET:CH1_FREQ?',str_type = float, autoinit=False, trig=True)
        self.net_ch2_freq = acq_device(getstr = 'DATA:NET:CH2_FREQ?',str_type = float, autoinit=False, trig=True)
        self.net_ch1_ampl = acq_device(getstr = 'DATA:NET:CH1_AMPL?',str_type = float, autoinit=False, trig=True)
        self.net_ch2_ampl = acq_device(getstr = 'DATA:NET:CH2_AMPL?',str_type = float, autoinit=False, trig=True)
        self.net_ch1_phase = acq_device(getstr = 'DATA:NET:CH1_PHASE?',str_type = float, autoinit=False, trig=True)
        self.net_ch2_phase = acq_device(getstr = 'DATA:NET:CH2_PHASE?',str_type = float, autoinit=False, trig=True)
        self.net_ch1_real = acq_device(getstr = 'DATA:NET:CH1_REAL?',str_type = float, autoinit=False, trig=True)
        self.net_ch2_real = acq_device(getstr = 'DATA:NET:CH2_REAL?',str_type = float, autoinit=False, trig=True)
        self.net_ch1_imag = acq_device(getstr = 'DATA:NET:CH1_IMAG?',str_type = float, autoinit=False, trig=True)
        self.net_ch2_imag = acq_device(getstr = 'DATA:NET:CH2_IMAG?',str_type = float, autoinit=False, trig=True)
        self.net_att = acq_device(getstr = 'DATA:NET:ATT?',str_type = float, autoinit=False, trig=True)
        self.net_phase_diff = acq_device(getstr = 'DATA:NET:PHASE_DIFF?',str_type = float, autoinit=False, trig=True)

        self._devwrap('fetch', autoinit=False)
        self.fetch._event_flag = threading.Event()
        self.fetch._rcv_val = None
        self._devwrap('readval', autoinit=False)
        self._devwrap('tau_vec', setget=True)
        self._tau_nb = dummy_device('CONFIG:NB_TAU?')
        self._tau_veci = dummy_device('CONFIG:TAU?')

        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
        
    #class methode     
    def write(self, val):
        self._check_error()
        val = '@' + val + '\n'
        self.s.send(val)

    # only use read, ask before starting listen thread.
    def read(self):
        return self.s.recv(128)

    def ask(self, quest):
        self.write(quest)
        return self.read()
        
    def Get_Board_Type(self):
       res = self.ask('CONFIG:BOARD_TYPE?')
       if res[0] != '@' or res[-1] != '\n':
           raise ValueError, 'Wrong format for Get Board_Type'
       res = res[1:-1]
       base, val = res.split(' ', 1)
       if base == 'CONFIG:BOARD_TYPE':
           self.board_type = val
       elif base == 'ERROR:CRITICAL':
           raise ValueError, 'Critical Error:'+val
       else:
           raise ValueError, 'Unknow problem:'+base+' :: '+val
           
           
    def stop(self):
        self.write('STOP')

    def disconnect(self):
        self.write('DISCONNECT')

    def shutdown_server(self):
        self.write('SHUTDOWN')

    def get_xscale(self):
        """
           returns a vector of for use use as xscale
           It can be the frequency data to match the amplitudes
            returned in spectrum modes.
           or the x scales for histograms in volts, etc...
           Requires a proper sampling rate to be set.
        """
        mode = self.op_mode.getcache()
        rate = self.sampling_rate.getcache()*1e6
        if mode == 'Spec':
            N = self.fft_length.getcache()
            period = 1./rate * N
            df = 1./period
            freq = df*np.arange(N/2+1)
            return freq
        elif mode == 'Osc':
            N = self.osc_nb_sample.getcache()
            return 1./rate*np.arange(N)
        elif mode == 'Hist':
            if self.board_type == 'ADC14':
                N = 2**14
            else: # ADC8
                N = 2**8
            return self.convert_bin2v(np.arange(N))
        elif mode == 'Corr':
            return np.array(self.tau_vec.getcache())*1./rate


    def set_clock_source_helper(self, sampling_rate=None, clock_source=None):
        clock_max = self._max_sampling
        if self.board_type == 'ADC8':
            clock_int = 2000
            usb_en = True
        else:
            clock_int = 400
            usb_en = False
        if clock_source==None and self._clock_src_init_done:
            clock_source = self.clock_source.getcache()
        if clock_source == 'Internal':
            if sampling_rate != None and sampling_rate != clock_int:
                raise ValueError, 'Sampling rate needs to be %f for internal or leave it unspecified'
            self.sampling_rate.set(clock_int)
        elif clock_source == 'External':
            if sampling_rate == None:
                raise ValueError, 'Sampling rate needs to be specified for external'
            self.sampling_rate.set(sampling_rate)
        elif clock_source == 'USB':
            if not usb_en:
                raise ValueError, 'USB clock mode not allowed with this card'
            if sampling_rate == None:
                sampling_rate = clock_max
                print 'Using the max sampling rate of', clock_max
            self.sampling_rate.set(sampling_rate)
        else:
            return
        self.clock_source.set(clock_source)
        self._clock_src_init_done = True

    def set_simple_acq(self,nb_Msample='min', chan_mode='Single', chan_nb=1, sampling_rate=None, clock_source=None):
        """
        Activates the simple acquisition mode which simply captures nb_Msample samples.
        Set sampling_rate anc clock_source, or reuse the previous ones by default (see set_clock_source_helper)
        chan_mode can be 'Dual' or 'Single' (default). In dual nb_Msample represents the total of both channels.
        When in single mode, set chan_nb to select which channel either 1 or 2.
        """
        self.op_mode.set('Acq')
        if nb_Msample=='min':
            nb_Msample = self._min_acq_Msample
            print 'Using ', nb_Msample, 'nb_Msample'
        self.set_clock_source_helper(sampling_rate, clock_source)
        self.test_mode.set(False)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set(chan_mode)
        self.chan_nb.set(chan_nb)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
            
    def set_histogram(self, nb_Msample='min', chan_nb=1, sampling_rate=None, clock_source=None, decimation=1):
        self.op_mode.set('Hist')
        self.set_clock_source_helper(sampling_rate, clock_source)
        self.decimation.set(decimation)
        self.test_mode.set(False)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set('Single')
        self.chan_nb.set(chan_nb)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
    
    def set_correlation(self, nb_Msample='min', sampling_rate=None, clock_source=None):
        """
        
        """
        self.op_mode.set('Corr')
        self.set_clock_source_helper(sampling_rate, clock_source)
        self.test_mode.set(False)
        self.nb_Msample.set(nb_Msample)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        self.chan_mode.set('Dual')
        self.chan_nb.set(1)
        self.autocorr_mode.set(False)
        self.corr_mode.set(True)
    
    def set_autocorrelation(self, nb_Msample='min', autocorr_single_chan=True,
                            autocorr_chan_nb=1, sampling_rate=None, clock_source=None):
        self.op_mode.set('Corr')
        self.set_clock_source_helper(sampling_rate, clock_source)
        self.test_mode.set(False)
        self.nb_Msample.set(nb_Msample)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        if autocorr_single_chan:
            self.chan_mode.set('Single')
        else:
            self.chan_mode.set('Dual')
        self.autocorr_single_chan.set(autocorr_single_chan)     
        self.chan_nb.set(autocorr_chan_nb)
        self.autocorr_mode.set(True)
        self.corr_mode.set(False)
        
    def set_auto_and_corr(self, nb_Msample='min', autocorr_single_chan=False,
                          autocorr_chan_nb=1, sampling_rate=None, clock_source=None):
        self.op_mode.set('Corr')
        self.set_clock_source_helper(sampling_rate, clock_source)
        self.test_mode.set(False)
        self.nb_Msample.set(nb_Msample)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        self.chan_mode.set('Dual')
        self.autocorr_single_chan.set(autocorr_single_chan)    
        self.chan_nb.set(autocorr_chan_nb)
        self.autocorr_mode.set(True)
        self.corr_mode.set(True)
        
        
    def set_network_analyzer(self, signal_freq, nb_Msample='min', nb_harm=1,
                             lock_in_square=False, sampling_rate=None, clock_source=None):
        self.op_mode.set('Net')
        self.set_clock_source_helper(sampling_rate, clock_source)
        self.test_mode.set(False)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set('Dual')
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        self.net_signal_freq.set(signal_freq)
        self.lock_in_square.set(lock_in_square)
        self.nb_harm.set(nb_harm)
        
    def set_scope(self, nb_sample=1024, hori_offset=0, trigger_level=0., slope='Rising',
                  trig_source=1,chan_mode='Single', chan_nb=1, sampling_rate=None, clock_source=None):
        self.op_mode.set('Osc')
        self.set_clock_source_helper(sampling_rate, clock_source)
        self.test_mode.set(False)
        self.nb_Msample.set(32)
        self.chan_mode.set(chan_mode)
        self.chan_nb.set(chan_nb)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        self.osc_nb_sample.set(nb_sample)
        self.osc_hori_offset.set(hori_offset)
        self.osc_trigger_level.set(trigger_level)
        self.osc_slope.set(slope)
        self.osc_trig_source(trig_source)
        
    def set_spectrum(self,nb_Msample='min', fft_length=1024, chan_mode='Single',
                     chan_nb=1, sampling_rate=None, clock_source=None):
        self.op_mode.set('Spec')
        self.set_clock_source_helper(sampling_rate, clock_source)
        self.test_mode.set(False)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set(chan_mode)
        self.chan_nb.set(chan_nb)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        self.fft_length.set(fft_length)

    def set_custom(self, cust_user_lib, cust_param1, cust_param2, cust_param3, cust_param4,
                   nb_Msample='min',  chan_mode='Single', chan_nb=1, sampling_rate=None, clock_source=None):
        self.op_mode.set('Cust')
        self.set_clock_source_helper(sampling_rate, clock_source)
        self.test_mode.set(False)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set(chan_mode)
        self.chan_nb.set(chan_nb)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        self.cust_param1.set(cust_param1)
        self.cust_param2.set(cust_param2)
        self.cust_param3.set(cust_param3)
        self.cust_param4.set(cust_param4)
        self.cust_user_lib.set(cust_user_lib)
        
    def run(self):
        # check if the configuration are ok
        
        #check if board is Idle
        if self.board_status.getcache() == 'Running':
            raise ValueError, 'ERROR Board already Running'

        if not self._clock_src_init_done:
            raise ValueError, 'Clock unitialized, you need to set it at least once, see set_clock_source_helper'
        # check if nb_Msample fit the op_mode
        if self.op_mode.getcache() == 'Acq':
            if self.nb_Msample.getcache() < self._min_acq_Msample:
                 new_nb_Msample = self._min_acq_Msample
                 self.nb_Msample.set(new_nb_Msample)
                 raise ValueError, 'Warning nb_Msample must be superior or equal to %i in Acq %s, value corrected to %i'%(new_nb_Msample,self.board_type,new_nb_Msample)
            if self.nb_Msample.getcache() > self._max_acq_Msample:
                 new_nb_Msample = self._max_acq_Msample
                 self.nb_Msample.set(new_nb_Msample)
                 raise ValueError, 'Warning nb_Msample must be inferior or equal to %i in Acq %s, value corrected to %i'%(new_nb_Msample,self.board_type,new_nb_Msample)
        
        if self.op_mode.getcache() == 'Hist' and self.board_type == 'ADC14':
            quotien = float(self.nb_Msample.getcache())/256
            frac,entier = math.modf(quotien)
            if frac != 0.0:
                new_nb_Msample = int(math.ceil(quotien))*256
                if new_nb_Msample > self._max_Msample:
                    new_nb_Msample = self._max_Msample
                self.nb_Msample.set(new_nb_Msample)
                raise ValueError, 'Warning nb_Msample must be a multiple of 256 in Hist ADC14, value corrected to nearest possible value : ' + str(new_nb_Msample)
            decimation = self.decimation.getcache()
            if decimation != 1 and decimation % 2 ==1:
                raise ValueError, 'Decimation can only be 1 or a multiple of 2 for Hist ADC14'

        if self.op_mode.getcache() == 'Hist' and self.board_type == 'ADC8':
            decimation = self.decimation.getcache()
            if decimation != 1 and decimation != 2 and decimation % 4 != 0:
                raise ValueError, 'Decimation can only be 1, 2 or a multiple of 4 for Hist ADC8'
        
        
        if self.op_mode.getcache() == 'Corr' and self.board_type == 'ADC14':
            quotien = float(self.nb_Msample.getcache())/4096
            frac,entier = math.modf(quotien)
            if frac != 0.0:
                new_nb_Msample = int(math.ceil(quotien))*4096
                if new_nb_Msample > self._max_Msample:
                    new_nb_Msample = self._max_Msample
                self.nb_Msample.set(new_nb_Msample)
                raise ValueError, 'Warning nb_Msample must be a multiple of 4096 in Corr ADC14, value corrected to nearest possible value : ' + str(new_nb_Msample)


        if (self.op_mode.getcache() == 'Hist' or self.op_mode.getcache() == 'Corr') and self.board_type == 'ADC8':
            quotien = float(self.nb_Msample.getcache())/8192
            frac,entier = math.modf(quotien)
            if frac != 0.0:
                new_nb_Msample = int(math.ceil(quotien))*8192
                if new_nb_Msample > self._max_Msample:
                    new_nb_Msample = self._max_Msample
                self.nb_Msample.set(new_nb_Msample)
                raise ValueError, 'Warning nb_Msample must be a multiple of 8192 in Hist or Corr ADC8, value corrected to nearest possible value : ' + str(new_nb_Msample)
        
        
        if self.op_mode.getcache() == 'Net':
            if self.nb_Msample.getcache() < self._min_net_Msample:
                 new_nb_Msample = self._min_net_Msample
                 self.nb_Msample.set(new_nb_Msample)
                 raise ValueError, 'Warning nb_Msample must be superior or equal to %i in Acq %s, value corrected to %i'%(new_nb_Msample,self.board_type,new_nb_Msample)
            if self.nb_Msample.getcache() > self._max_net_Msample:
                 new_nb_Msample = self._max_net_Msample
                 self.nb_Msample.set(new_nb_Msample)
                 raise ValueError, 'Warning nb_Msample must be inferior to 64 in net ADC14, value corrected to 128'
    
        #check if clock freq is a multiple of 5 Mhz when in USB clock mode
        if self.clock_source.getcache() == 'USB':
            if self.board_type == 'ADC8':
                clock_freq = self.sampling_rate.getcache()/2
            else:
                clock_freq = self.sampling_rate.getcache()
                
            quotien = clock_freq/5.0
            
            frac,entier = math.modf(quotien)
            
            if frac != 0.0:
                if self.board_type == 'ADC8':
                    new_sampling_rate =  2* math.ceil(quotien) * 5
                    if new_sampling_rate > self._max_sampling:
                        new_sampling_rate = self._max_sampling
                    self.sampling_rate.set(new_sampling_rate)
                else:
                    new_sampling_rate = math.ceil(quotien) * 5
                    if new_sampling_rate > self._max_sampling:
                        new_sampling_rate = self._max_sampling
                    elif new_sampling_rate < self._min_usb_clock_freq:
                        new_sampling_rate = self._min_usb_clock_freq
                    self.sampling_rate.set(new_sampling_rate)
                raise ValueError, 'Warning sampling_rate not a multiple of 5, value corrected to nearest possible value : ' + str(new_sampling_rate)
                  
        #if in Osc mode check if the sample to send fit the horizontal offset
        if self.op_mode.getcache() == 'Osc':
            if self.osc_hori_offset() > self.osc_nb_sample():
                self.osc_hori_offset.set(self.osc_nb_sample.getcache())
        
        # check if the fft length is a power of 2 and if the nb_Msample fit too
        """
        if self.op_mode.getcache() == 'Spec':
            
            pwr2 = math.log(float(self.fft_length.getcache()),2)
            
            frac,entier = math.modf(pwr2)
            
            if frac != 0:
                new_fft_length = 2**math.ceil(pwr2)
                self.fft_length.set(new_fft_length)
                raise ValueError, 'Warning fft_length not a power of 2, value corrected to nearest possible value : ' + str(new_fft_length)
            else:
                new_fft_length = self.fft_length
            
           quotien =  self.nb_Msample.getcache() / new_fft_length
           frac,entier = math.modf(quotien)
           
           if frac != 0
               new_nb_Msamples = math.ceil(quotien) * new_fft_length
        """
                
        self.write('STATUS:CONFIG_OK True')
        self.write('RUN')
        
        
            

           
           
