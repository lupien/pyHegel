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
    """
    This instrument controls the fast acquisition cards (Ulraview 8 and 14bit)
    To use, first make sure the data acquisition server is started
      Ctrl_Carte_Acquisition.exe
    Then this instrument can be loaded. This instrument requires an ip address
    (can be a dns name) and a port number since the communication with
    the server is through a network connection. If running pyHegel on the
    same machine, this can be localhost (127.0.0.1), port 50000

    Once loaded, an acquisition mode needs to be selected. See the methods
        set_histogram
        set_scope
        set_simple_acq
        set_spectrum
        set_network_analyzer
        set_correlation, set_autocorrelation, set_auto_and_corr
        set_custom
    You can set the clock_source/sampling_rate with any of them or you can
    use set_clock_source. It needs to be done at least once.
    The set_ command while set a bunch of devices on this instrument automatically.
    This can also be done manually but is not recommanded (unless you know what
    you are doing).

    Then you can start an acquisition using either run or run_and_wait
    And finally you can obtain the data.
    See the individual modes for the data available.
    Most of them return data through fetch, see fetch for all the options.
    Instead of fetch you can use readval which is the same as
    run_and_wait followed by a fetch.

    In case of trouble, you might need to read the error values.
    see get_error for data. When all the error message are read, the error state
    is cleared.

    If you want to reload this instrument, you first need to delete it (example:
    del acq1) otherwise loading will fail since server only accepts one
    connection at a time.

    To obtain a proper x scale for graphs, use get_xdata

    Other methods available: stop, disconnect, shutdown_server, convert_bin2v
                             idn, cls, wait_after_trig, wait_after_trig
    and attribute: board_type
    """
    
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
            self._min_hist_Msample = 8192
            self._min_corr_Msample = 8192
            self._min_acq_Msample = 32
            self._max_acq_Msample = 8192
            self._min_net_Msample = 32
            self._max_net_Msample = 128
            self._clock_internal_freq = 2000
            self._volt_range = 0.700
            self._bit_resolution = 2**8
        else: # ADC14
            self._max_sampling = 400
            self._min_sampling = 20
            self._max_Msample = 2147479552
            self._min_hist_Msample = 4096
            self._min_corr_Msample = 4096
            self._min_acq_Msample = 16
            self._max_acq_Msample = 4096
            self._min_net_Msample = 16
            self._max_net_Msample = 64
            self._clock_internal_freq = 400
            self._volt_range = 0.750
            self._bit_resolution = 2**14
        self._min_usb_clock_freq = 200 # TODO check this, I think it should be 137.5 MHz
        self._max_nb_Msample_all = 4294967295 # TODO clean up min max nb_Msample
        self._max_nb_tau = 50

        self.visa_addr = self.board_type
        self._run_finished = threading.Event() # starts in clear state

        self._listen_thread = Listen_thread(self)
        self._listen_thread.start()     
        
        # init the parent class
        instrument.BaseInstrument.__init__(self)

    def idn(self):
        """
        Return a identification string similar to *idn of scpi instruments.
        """
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
        """
        The errors are on a stack. This pops and shows the last one.
        Execute this multiple times to clear the error state (or use cls).
        When no errors are present, this returns: +0,"No error"
        """
        if self._errors_list == []:
            self._error_state = False
            return '+0,"No error"'
        return self._errors_list.pop()
    @property
    def set_timeout(self):
        """
        Change the socket timeout.
        """
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
        #self._run_finished.clear() # now in run itself
        self.run()
    def _async_detect(self):
        return instrument.wait_on_event(self._run_finished, check_state=self, max_time=.5)
    def wait_after_trig(self):
        """
        waits until the run is finished
        """
        return instrument.wait_on_event(self._run_finished, check_state=self)
    def run_and_wait(self):
        """
        This performs a run and waits for it to finish.
        See run for more details.
        """
        self._async_trig()
        self.wait_after_trig()

    def _current_config(self, dev_obj=None, options={}):
        if self.op_mode.getcache() == 'Acq':
            return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                     'chan_nb','chan_mode', options)
                                     
        if self.op_mode.getcache() == 'Hist':
            return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                     'chan_nb', 'decimation', options)
                                     
        if self.op_mode.getcache() == 'Corr':
            return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                     'autocorr_mode', 'corr_mode','autocorr_single_chan',
                                     'chan_mode','chan_nb', 'tau_vec', options)
                           
        if self.op_mode.getcache() == 'Net':
            return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                     'lock_in_square','net_signal_freq','nb_harm', options)
                                     
        if self.op_mode.getcache() == 'Osc':
            return self._conf_helper('op_mode', 'sampling_rate', 'clock_source','osc_nb_sample',
                                     'osc_hori_offset', 'osc_trigger_level', 'osc_slope', 'osc_trig_source',
                                     'osc_trig_mode', 'chan_mode','chan_nb', options)
        
        if self.op_mode.getcache() == 'Spec':
             return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                      'chan_mode','chan_nb','fft_length', options)
                                     
        if self.op_mode.getcache() == 'Cust':
             return self._conf_helper('op_mode', 'nb_Msample', 'sampling_rate', 'clock_source',
                                      'chan_mode','chan_nb','cust_param1','cust_param2','cust_param3',
                                      'cust_param4', options)
                                     

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
        """
        Converts bin/bit values to a voltage
        off: when true (default), removes the zero offset
             which is needed for raw values.
        auto_inv: when true (default) corrects for the inversion
                  the 14bit cards does on data. This is needed for
                  raw values.
        """
        vrange = self._volt_range
        resolution = self._bit_resolution
        offset = resolution/2.
        if self.board_type == 'ADC14':
            sign = -1.
        else: # 8bit
            sign = +1.
        if off == False:
            offset = 0.
        if auto_inv == False:
            sign = 1.
        return (bin - offset)*sign*vrange/resolution

    def _fetch_get_ch_corr(self, ch=None):
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
        return ch
    def _fetch_getformat(self, filename=None, **kwarg):
        fmt = self.fetch._format
        fmt.update(file=False)
        fmt.update(bin=False)
        fmt.update(multi=False, graphs=[])
        mode = self.op_mode.getcache()
        if mode == 'Acq':
            #if self.nb_Msample.getcache() > 64:
            #    fmt.update(file=True)
            #fmt.update(bin='.npy')
            fmt.update(file=True)
        if mode == 'Corr':
            ch = kwarg.get('ch')
            ch = self._fetch_get_ch_corr(ch)
            nbtau = len(self.tau_vec.getcache())
            headers = ['ch%i-%i'%(c,i)  for c in ch  for i in range(nbtau)]
            graphs = [(i*nbtau) for i in range(len(ch))]
            fmt.update(multi=headers, graph=graphs)
        return instrument.BaseDevice.getformat(self.fetch, **kwarg)

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
                       local/remote is selected by format_location device
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
                     For sweep/record the data will be merged into main data and
                     only first tau will be traced
               Custom: returns whatever the custom code should return
                       which depends on loaded custom dll

            The actual transfer of data is controlled by the devices
             format_location
             format_type
             format_block_length
            Their default are usually ok.
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
            ch = self._fetch_get_ch_corr(ch) # always returns a list
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
                return self.convert_bin2v(self.convert_bin2v(ret, off=False),off=False)
            else:
                return ret

        if mode == 'Cust':
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
        """
        Readval performs the same thing as run_and_wait() followed by fetch.
        For the arguments, see fetch.
        Use this for sweep with async off, or with get to automatically
        start the acquisition before fetching the data.
        """
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
        """
        This device is used to change the list of tau.
        There is a max of 50.
        You can give it a list of values, which then replaces the previous list.
        You can change an element i by
         set(acq1.tau_vec, 5, i=3)
        which changes the 4th element to be 5
        You can also append a single value to the list with the optional
        argument: append=True
        """
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
        """
           hist_ms has optionnal parameter m=[1,2,3,4,5]
           It specifies which of the moment to obtain and returns
           a list of the selected ones. By default, all are selected.
        """
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
        osc_trigmode_str = ['Normal','Auto']
        format_location_str = ['Local','Remote']
        format_type_str = ['Default','ASCII','NPZ']
        
        #device init
        # Configuration
        self.op_mode = acq_device('CONFIG:OP_MODE', str_type=str, choices=op_mode_str)

        self.sampling_rate = acq_device('CONFIG:SAMPLING_RATE', str_type=float,  min=self._min_sampling, max=self._max_sampling)

        self.decimation = acq_device('CONFIG:DECIMATION', str_type=int, min=1, max=1024, doc='Skip over points for analysis. It is not used for all modes.')
        self.acq_verbose = acq_device('CONFIG:ACQ_VERBOSE', str_type=acq_bool(), doc='Increase verbosity of server when True')
        self.test_mode = acq_device('CONFIG:TEST_MODE', str_type=acq_bool())
        self.clock_source = acq_device('CONFIG:CLOCK_SOURCE', str_type=str, choices=clock_source_str)
        self.nb_Msample = acq_device('CONFIG:NB_MSAMPLE', str_type=int,  min=self._min_acq_Msample, max=self._max_nb_Msample_all)
        self.chan_mode = acq_device('CONFIG:CHAN_MODE', str_type=str, choices=chan_mode_str)
        self.chan_nb = acq_device('CONFIG:CHAN_NB', str_type=int,  min=1, max=2)
        self.trigger_invert = acq_device('CONFIG:TRIGGER_INVERT', str_type=acq_bool())
        self.trigger_edge_en = acq_device('CONFIG:TRIGGER_EDGE_EN', str_type=acq_bool())
        self.trigger_await = acq_device('CONFIG:TRIGGER_AWAIT', str_type=acq_bool())
        self.trigger_create = acq_device('CONFIG:TRIGGER_CREATE', str_type=acq_bool())
        
        volt_range = self._volt_range/2
        self.osc_trigger_level = acq_device('CONFIG:OSC_TRIGGER_LEVEL', str_type=float,
                                            min=-volt_range, max=volt_range)
        
        self.osc_slope = acq_device('CONFIG:OSC_SLOPE', str_type=str, choices=osc_slope_str) 
        self.osc_nb_sample = acq_device('CONFIG:OSC_NB_SAMPLE', str_type=int,  min=1, max= ((16*1024*1024)-1)) # max 16MB
        self.osc_hori_offset = acq_device('CONFIG:OSC_HORI_OFFSET', str_type=int,  min=-(8*1024*1024), max= ((8*1024*1024)-1)) # max 8MB
        self.osc_trig_source = acq_device('CONFIG:OSC_TRIG_SOURCE', str_type=int,  min=1, max=2)
        self.osc_trig_mode = acq_device('CONFIG:OSC_TRIG_MODE', str_type=str, choices=osc_trigmode_str)
        
        if self.board_type == 'ADC8':
            self.net_signal_freq = acq_device('CONFIG:NET_SIGNAL_FREQ', str_type=float,  min=0, max=375000000)
        elif self.board_type == 'ADC14':
            self.net_signal_freq = acq_device('CONFIG:NET_SIGNAL_FREQ', str_type=float,  min=0, max=50000000)
        
        self.lock_in_square = acq_device('CONFIG:LOCK_IN_SQUARE', str_type=acq_bool())
        self.nb_harm = acq_device('CONFIG:NB_HARM',str_type=int, min=1, max=100)
        self.autocorr_mode = acq_device('CONFIG:AUTOCORR_MODE', str_type=acq_bool())
        self.corr_mode = acq_device('CONFIG:CORR_MODE', str_type=acq_bool())
        self.autocorr_single_chan = acq_device('CONFIG:AUTOCORR_SINGLE_CHAN', str_type=acq_bool())
        self.fft_length = acq_device('CONFIG:FFT_LENGTH', str_type=int, min=64, max=2**20)
        self.cust_param1 = acq_device('CONFIG:CUST_PARAM1', str_type=float)
        self.cust_param2 = acq_device('CONFIG:CUST_PARAM2', str_type=float)
        self.cust_param3 = acq_device('CONFIG:CUST_PARAM3', str_type=float)
        self.cust_param4 = acq_device('CONFIG:CUST_PARAM4', str_type=float)
        self.cust_user_lib = acq_device('CONFIG:CUST_USER_LIB', str_type=acq_filename())
        self.board_serial = acq_device(getstr='CONFIG:BOARD_SERIAL?',str_type=int, doc='The serial number of the aquisition card.')
        self.board_status = acq_device(getstr='STATUS:STATE?',str_type=str, doc='The current status of the acquisition card. Can be Idle, Running, Transferring')
        self.partial_status = acq_device(getstr='STATUS:PARTIAL?',str_type=instrument._decode_uint32)
        self.result_available = acq_device(getstr='STATUS:RESULT_AVAILABLE?',str_type=acq_bool(), doc='Is True when results are available from the card (after run completes)')
        
        self.format_location = acq_device('CONFIG:FORMAT:LOCATION', str_type=str, choices=format_location_str, doc='Select between sending the data through the network socket (Remote), or letting the server save it (Local)')
        self.format_type = acq_device('CONFIG:FORMAT:TYPE',str_type=str, choices=format_type_str, doc='Select saving format when in Local. Only implemented one is Default')
        self.format_block_length = acq_device('CONFIG:FORMAT:BLOCK_LENGTH',str_type = int, min=1, max=4294967296, doc='Size of blocks used in Remote transmission')

        # Results
        #histogram result
        self.hist_m1 = acq_device(getstr = 'DATA:HIST:M1?', str_type = float, autoinit=False, trig=True)
        self.hist_m2 = acq_device(getstr = 'DATA:HIST:M2?', str_type = float, autoinit=False, trig=True)
        self.hist_m3 = acq_device(getstr = 'DATA:HIST:M3?', str_type = float, autoinit=False, trig=True)
        self.hist_m4 = acq_device(getstr = 'DATA:HIST:M4?', str_type = float, autoinit=False, trig=True)
        self.hist_m5 = acq_device(getstr = 'DATA:HIST:M5?', str_type = float, autoinit=False, trig=True)
        self._devwrap('hist_ms', autoinit=False, trig=True)
        
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

    def force_get(self):
        # Since user cannot change change values except without using this program
        # the cache are always up to date and this is not needed.
        pass

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
        """
        Ask the server to stop acquiring data
        """
        self.write('STOP')

    def disconnect(self):
        """
        Tell server that we are disconnecting.
        This allows someone else to disconnect.

        deleting the instrument should also disconnect.
          del acq1
        """
        self.write('DISCONNECT')

    def shutdown_server(self):
        """
        This ask the server to shutdown. The server program should end.
        """
        self.write('SHUTDOWN')

    def get_xscale(self):
        """
           returns a vector of values for use use as xscale
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
            N = self._bit_resolution
            return self.convert_bin2v(np.arange(N))
        elif mode == 'Corr':
            return np.array(self.tau_vec.getcache())*1./rate

    def _check_clock(self, sampling_rate, clock_source, checkNone=False):
        if checkNone:
            if sampling_rate == None:
                raise ValueError, 'sampling_rate or clock_source are missing (None)'
        if clock_source == 'Internal':
            if sampling_rate != None and sampling_rate != self._clock_internal_freq:
                raise ValueError, 'Sampling rate needs to be %f for internal or leave it unspecified in set_ mode fucntions'%self._clock_internal_freq
        elif clock_source == 'External':
            if sampling_rate == None:
                raise ValueError, 'Sampling rate needs to be specified for external'
        elif clock_source == 'USB':
            #check if clock freq is a multiple of 5 Mhz when in USB clock mode
            # TODO check that this is what should be done
            #      I think the resolution is better at lower frequency
            #       10 for clock 2200-4400 (Useless for ADC8)
            #       5 for clock 1100-2200 (2200-4400 ADC8 sample rate, steps of 10)
            #       2.5 for clock 550-1100 (1100-2200 ADC8 sample, steps of 10)
            #       1.25 for clock 275-550 (550-1100 ADC8 sample, steps of 2.5)
            #                               275-550 ADC14 sample, steps of 1.25
            #       0.625 for clock 137.5-275 (137.5-275 ADC14 sample, steps of 0.625)
            if sampling_rate != None:
                if self.board_type == 'ADC8': #8bit makes sampling rate double of clock frequency
                    factor = 2
                else:
                    factor = 1
                clock_step = 5.
                clock_freq = sampling_rate/factor
                if clock_freq < self._min_usb_clock_freq:
                    raise ValueError, 'sampling_rate too low for USB clock, minimum is %f'%(self._min_usb_clock_freq*factor)
                quotien = clock_freq/clock_step
                frac,entier = math.modf(quotien)
                if frac != 0:
                    raise ValueError, 'Warning sampling_rate not a multiple of %f, which is needed for USB clock'%(clock_step*factor)
        else:
            raise ValueError, 'Invalid clock_source'

    def set_clock_source(self, sampling_rate=None, clock_source=None):
        """
        Use this at least once per loaded instrument to set
        both the clock_source ('Internal', 'External', 'USB')
        and the sampling rate.
        The sampling rate is needed for 'External' and optional otherwise
         (the maximum one is used)

        Note that for external with an 8bit card, the sampling_rate should be
        twice(x2) the clock source frequency.
        """
        if sampling_rate==None and clock_source==None:
            return
        clock_max = self._max_sampling
        if clock_source==None and self._clock_src_init_done:
            clock_source = self.clock_source.getcache()
        self._check_clock(sampling_rate, clock_source)
        if clock_source == 'Internal':
            self.sampling_rate.set(self._clock_internal_freq)
        elif clock_source == 'External':
            self.sampling_rate.set(sampling_rate)
        elif clock_source == 'USB':
            if sampling_rate == None:
                sampling_rate = clock_max
                print 'Using the max sampling rate of', clock_max
            self.sampling_rate.set(sampling_rate)
        else:
            return
        self.clock_source.set(clock_source)
        self._clock_src_init_done = True

    def _set_mode_defaults(self):
        self.test_mode.set(False)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)

    def set_simple_acq(self,nb_Msample='min', chan_mode='Single', chan_nb=1, sampling_rate=None, clock_source=None):
        """
        Activates the simple acquisition mode which simply captures nb_Msample
        samples.
        Set sampling_rate anc clock_source, or reuse the previous ones by
        default (see set_clock_source).
        chan_mode can be 'Dual' or 'Single' (default). In dual nb_Msample
        represents the total of both channels.
        When in single mode, set chan_nb to select which channel either 1 or 2.
        """
        self.op_mode.set('Acq')
        if nb_Msample=='min':
            nb_Msample = self._min_acq_Msample
            print 'Using ', nb_Msample, 'nb_Msample'
        self.set_clock_source(sampling_rate, clock_source)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set(chan_mode)
        self.chan_nb.set(chan_nb)
        self._set_mode_defaults()
            
    def set_histogram(self, nb_Msample='min', chan_nb=1, sampling_rate=None, clock_source=None, decimation=1):
        """
        Activates the histogram mode.

        Get the data either from
          hist_m1, hist_m2, hist_m3, hist_m4, hist_m5
        which return the moments of the last acquisition
          hist_ms (any combination of the above)
        or fetch (readval) to capture the full histogram.

        Set sampling_rate anc clock_source, or reuse the previous ones by
        default (see set_clock_source).
        nb_MSample: set the number of samples used for histogram (uses min by default)
        chan_nb:    select the channel to acquire for the histogram,
                    either 1(default) or 2
        decimation: only analyze one of every decimation point
                    can be 1, 2, 4, n*4  for 8bit
                    can be 1, 2, n*2  for 14bit
                     for n any integer >= 1
        """
        self.op_mode.set('Hist')
        if nb_Msample=='min':
            nb_Msample = self._min_hist_Msample
            print 'Using ', nb_Msample, 'nb_Msample'
        self.set_clock_source(sampling_rate, clock_source)
        self.decimation.set(decimation)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set('Single')
        self.chan_nb.set(chan_nb)
        self._set_mode_defaults()
    
    def set_correlation(self, nb_Msample='min', sampling_rate=None, clock_source=None):
        """
        Activates the cross correlation mode. This reads both ch1 and ch2
        and calculates the cross correlation.
          correl = sum[(xi-xavg)(yj-yavg)], for x=ch1, y=ch2
          j=i+tau
        See tau_vec to set a vector of time displacement between x and y.
        Get data with fetch(readval)

        Set sampling_rate anc clock_source, or reuse the previous ones by
        default (see set_clock_source).
        nb_MSample: set the number of samples used for histogram (uses min by default)
                    This number includes both channels.
        """
        self.op_mode.set('Corr')
        if nb_Msample=='min':
            nb_Msample = self._min_corr_Msample
            print 'Using ', nb_Msample, 'nb_Msample'
        self.set_clock_source(sampling_rate, clock_source)
        self.nb_Msample.set(nb_Msample)
        self._set_mode_defaults()
        self.chan_mode.set('Dual')
        self.chan_nb.set(1)
        self.autocorr_mode.set(False)
        self.corr_mode.set(True)
    
    def set_autocorrelation(self, nb_Msample='min', autocorr_single_chan=True,
                            autocorr_chan_nb=1, sampling_rate=None, clock_source=None):
        """
        Activates the auto-correlation mode.
          auto_correl = sum[(xi-xavg)(xj-xavg)], for x=ch1 or ch2
          j=i+tau
        See tau_vec to set a vector of time displacement between x and y.
        Get data with fetch(readval)

        Set sampling_rate anc clock_source, or reuse the previous ones by
        default (see set_clock_source).
        nb_MSample: set the number of samples used for histogram (uses min by default)
                    This number includes both channels, if both are read.
        autocorr_single_chan: When True, only one channel is read and analyzed
                              otherwise both are read and analyzed.

        autocorr_chan_nb: channel number to read and analyze when in single
                          mode. Either 1 (default) or 2.
        """
        self.op_mode.set('Corr')
        if nb_Msample=='min':
            nb_Msample = self._min_corr_Msample
            print 'Using ', nb_Msample, 'nb_Msample'
        self.set_clock_source(sampling_rate, clock_source)
        self.nb_Msample.set(nb_Msample)
        self._set_mode_defaults()
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
        """
        Activates the cross-auto-correlation mode.
        It will calculate both the cross-correlation and
        the auto-correlation. Both channel are always read.
        The cross correlation is always analyzed.
        At least one auto-correlation is analyzed but tau=0 for all of them.
        Get data with fetch(readval)

        See tau_vec to set a vector of time displacement between x and y.
        Set sampling_rate anc clock_source, or reuse the previous ones by
        default (see set_clock_source).
        nb_MSample: set the number of samples used for histogram (uses min by default)
                    This number includes both channels.
        autocorr_single_chan: When True, only one channel is analyzed for
                              autocorrelation otherwise both are analyzed.
        autocorr_chan_nb: channel number to analyze when in single
                          mode. Either 1 (default) or 2.
        """
        self.op_mode.set('Corr')
        if nb_Msample=='min':
            nb_Msample = self._min_corr_Msample
            print 'Using ', nb_Msample, 'nb_Msample'
        self.set_clock_source(sampling_rate, clock_source)
        self.nb_Msample.set(nb_Msample)
        self._set_mode_defaults()
        self.chan_mode.set('Dual')
        self.autocorr_single_chan.set(autocorr_single_chan)    
        self.chan_nb.set(autocorr_chan_nb)
        self.autocorr_mode.set(True)
        self.corr_mode.set(True)
        
        
    def set_network_analyzer(self, signal_freq, nb_Msample='min', nb_harm=1,
                             lock_in_square=False, sampling_rate=None, clock_source=None):
        """
        Activates the network analyzer mode.
        It performs like a lock-in amplifier.
        Both channels are used.
         ch1 is used as the reference signal.
         ch2 is used as the measured signal.
        WARNING: before running, make sure the net_signal_freq is set properly
          (close to the value of the reference signal), otherwise the analysis
          will fail. To do sweeps, you will probably be interested in the
          instrument.CopyDevice device.

        Get the data from one of (for the first harmonic only)
            net_ch1_ampl, net_ch1_phase, net_ch1_real, net_ch1_imag
            net_ch2_ampl, net_ch2_phase, net_ch2_real, net_ch2_imag
            net_ch1_freq or net_ch2_freq (both are the same)
            net_phase_diff, net_att
        or get data for all harmonics using fetch (readval)

        Set sampling_rate and clock_source, or reuse the previous ones by
        default (see set_clock_source).
        signal_freq: initial value for net_signal_freq
        nb_MSample: set the number of samples used for histogram (uses min by default)
                    This number includes both channels.
        nb_harm:  the number of harmonics to analyze, defaults to 1.
        lock_in_square: when True, squares the signal before doing the lock-in
                        analysis.
        """
        self.op_mode.set('Net')
        if nb_Msample=='min':
            nb_Msample = self._min_net_Msample
            print 'Using ', nb_Msample, 'nb_Msample'
        self.set_clock_source(sampling_rate, clock_source)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set('Dual')
        self._set_mode_defaults()
        self.net_signal_freq.set(signal_freq)
        self.lock_in_square.set(lock_in_square)
        self.nb_harm.set(nb_harm)
        
    def set_scope(self, nb_sample=1024, hori_offset=0, trigger_level=0., slope='Rising',
                  trig_source=1, trig_mode='Auto', chan_mode='Single', chan_nb=1, sampling_rate=None, clock_source=None):
        """
        Activates the oscilloscope mode.
        Get nb_sample (1024 by default).
        WARNING: if the acquisition card can't find a trigger, it will hang.

        hori_offset:  delay in time_steps (integer) between trigger and data.
        trigger_level: Voltage used for trigger (default=0.0).
        slope: the trigger slope. Either 'Rising' (default) or 'Falling'.
        trig_source: The channel used for finding a trigger. Either 1 (default)
                     or 2.
        trig_mode: Either 'Auto'  (default) or 'Normal'
                   In 'Normal' the cards might wait forever for a trigger.
                   To stop it see stop methode.
                   In 'Auto' if a trigger is not seen the first section of data is
                   returned.
        chan_mode: Either 'Single' (default) or 'Dual'.
                   In dual, both channels are read.
        chanb_nb: Channel to read when in 'Single' mode. Either 1 (default) or 2.

        Get data from fetch (readval). Can also use the scope command.

        Set sampling_rate and clock_source, or reuse the previous ones by
        default (see set_clock_source).
        """
        self.op_mode.set('Osc')
        self.set_clock_source(sampling_rate, clock_source)
        self.nb_Msample.set(32)
        self.chan_mode.set(chan_mode)
        self.chan_nb.set(chan_nb)
        self._set_mode_defaults()
        self.osc_nb_sample.set(nb_sample)
        self.osc_hori_offset.set(hori_offset)
        self.osc_trigger_level.set(trigger_level)
        self.osc_slope.set(slope)
        self.osc_trig_source(trig_source)
        self.osc_trig_mode(trig_mode)
        
    def set_spectrum(self,nb_Msample='min', fft_length=1024, chan_mode='Single',
                     chan_nb=1, sampling_rate=None, clock_source=None):
        """
        Activates the spectrum analyzer mode (FFT).

        nb_MSample: set the number of samples used for histogram (uses min by default)
                    This number includes both channels, if both are read.
        fft_length: The number of points used for calculating the FFT.
                    Needs to be a power of 2. defaults to 1024
        chan_mode: Either 'Single' (default) or 'Dual'.
                   In dual, both channels are read.
        chanb_nb: Channel to read when in 'Single' mode. Either 1 (default) or 2.

        Get data from fetch (readval) or from custom_result1-4

        Set sampling_rate and clock_source, or reuse the previous ones by
        default (see set_clock_source).
        """
        self.op_mode.set('Spec')
        if nb_Msample=='min':
            nb_Msample = self._min_acq_Msample
            print 'Using ', nb_Msample, 'nb_Msample'
        self.set_clock_source(sampling_rate, clock_source)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set(chan_mode)
        self.chan_nb.set(chan_nb)
        self._set_mode_defaults()
        self.fft_length.set(fft_length)

    def set_custom(self, cust_user_lib, cust_param1, cust_param2, cust_param3, cust_param4,
                   nb_Msample='min',  chan_mode='Single', chan_nb=1, sampling_rate=None, clock_source=None):
        """
        Activates the custom mode.

        cust_user_lib: the dll file to load into the acquisition server program
        cust_param1-4: the parameters passed to the custom code. All are floats.
        nb_MSample: set the number of samples used for histogram (uses min by default)
                    This number includes both channels, if both are read.
        fft_length: The number of points used for calculating the FFT.
                    Needs to be a power of 2. defaults to 1024
        chan_mode: Either 'Single' (default) or 'Dual'.
                   In dual, both channels are read.
        chanb_nb: Channel to read when in 'Single' mode. Either 1 (default) or 2.

        Get data from fetch (readval).

        Set sampling_rate and clock_source, or reuse the previous ones by
        default (see set_clock_source).
        """
        self.op_mode.set('Cust')
        if nb_Msample=='min':
            nb_Msample = self._min_acq_Msample
            print 'Using ', nb_Msample, 'nb_Msample'
        self.set_clock_source(sampling_rate, clock_source)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set(chan_mode)
        self.chan_nb.set(chan_nb)
        self._set_mode_defaults()
        self.cust_param1.set(cust_param1)
        self.cust_param2.set(cust_param2)
        self.cust_param3.set(cust_param3)
        self.cust_param4.set(cust_param4)
        self.cust_user_lib.set(cust_user_lib)
        
    def run(self):
        """
        This function checks the validity of the current configuration.
        If valid, it starts the acquisition/analysis.
        """
        # check if the configuration are ok
        
        #check if board is Idle
        if self.board_status.getcache() == 'Running':
            raise ValueError, 'ERROR Board already Running'

        #check clock settings are valid
        if not self._clock_src_init_done:
            raise ValueError, 'Clock unitialized, you need to set it at least once, see set_clock_source'
        self._check_clock(self.sampling_rate.getcache(),
                                self.clock_source.getcache(), checkNone=True)

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

        # TODO clean up use of 256, 4096 ...
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
                 raise ValueError, 'Warning nb_Msample must be inferior or equal to %i in Acq %s, value corrected to %i'%(new_nb_Msample,self.board_type,new_nb_Msample)
    
        #if in Osc mode check if the sample to send fit the horizontal offset
        if self.op_mode.getcache() == 'Osc':
            nb_sample = self.osc_nb_sample.getcache()
            if self.osc_hori_offset() > nb_sample:
                self.osc_hori_offset.set(nb_sample)
                raise ValueError, 'Warning osc_hori_offset larger than nb_Sample. corrected to nearest possible value : ' + str(nb_sample)
        
        # check if the fft length is a power of 2 and if the nb_Msample fit too
        if self.op_mode.getcache() == 'Spec':
            pwr2 = math.log(self.fft_length.getcache(), 2)
            frac,entier = math.modf(pwr2)
            if frac != 0:
                new_fft_length = 2**math.ceil(pwr2)
                self.fft_length.set(new_fft_length)
                raise ValueError, 'Warning fft_length not a power of 2, value corrected to nearest possible value : ' + str(new_fft_length)

        self.write('STATUS:CONFIG_OK True')
        self._run_finished.clear()
        self.write('RUN')
