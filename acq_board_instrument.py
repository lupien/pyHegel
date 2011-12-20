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
import weakref
import numpy as np

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
    def _tostr(self, val):
        if val == None:
            raise ValueError, 'acq_bool should not be None'
        return repr(val)

class acq_filename(object):
    def __call__(self, input_str):
        if input_str[0] != '<' or input_str[0] != '>':
            print 'Filename is missing < >'
            return input_str
        return input_str[1:-1]
    def _tostr(self, val):
        return '<'+val+'>'

class acq_device(instrument.scpiDevice):
    def __init__(self, *arg, **kwarg):
        super(type(self), self).__init__(*arg, **kwarg)
        self._event_flag = threading.Event()
        self._event_flag.set()
        self._rcv_val = None
    def getdev(self):
        if self._getdev == None:
           raise NotImplementedError, self.perror('This device does not handle getdev')
        self._event_flag.clear()
        self.instr.write(self._getdev)
        instrument.wait_on_event(self._event_flag, check_state=self.instr)
        return self._fromstr(self._rcv_val)

class dummy_device(object):
    def __init__(self, getstr):
        self._rcv_val = None
        self._event_flag = threading.Event()
        self._getdev = getstr
    def getdev(self, quest_extra=''):
        self._event_flag.clear()
        if quest_extra:
            quest_extra=' '+quest_extra
        self.instr.write(self._getdev + quest_extra)
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
        while not self._stop:
            try:
                r, _, _ = select.select(select_list, [], [], socket_timeout)
                if not bool(r):
                    continue
            except socket.error:
                break
            if bin_mode:
                if len(old_stuff) != 0:
                    new_stuff = acq.s.recv(block_length-len(old_stuff))
                    new_stuff = old_stuff+new_stuff
                    old_stuff = ''
                else:
                    new_stuff = acq.s.recv(block_length)
                total_byte -= len(new_stuff)
                if total_byte < 0:
                    old_stuff = new_stuff[total_byte:]
                    new_stuff = new_stuff[:total_byte]
                if acq.fetch._dump_file != None:
                    acq.fetch._dump_file.write(new_stuff)
                    acq.fetch._rcv_val = None
                else:
                    acq.fetch._rcv_val += new_stuff
                if total_byte <= 0:
                    bin_mode = False
                    acq.fetch._event_flag.set()
                continue
            new_stuff = acq.s.recv(128)
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
                            if obj == acq.board_status or obj == acq.result_available:
                                obj._cache = obj._fromstr(val)
                            if obj == acq.result_available:
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
                        acq.fetch._rcv_val = ''
                        bin_mode = True
                        block_length, total_byte = val.split(' ')
                        block_length = int(block_length)
                        total_byte = int(total_byte)
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
        
        # maximum value
        self.max_sampling_adc8 = 3000
        self.min_sampling_adc8 = 1000
        self.max_sampling_adc14 = 400
        self.min_sampling_adc14 = 20
        self.min_usb_clock_freq = 200
        self.min_nb_Msample = 32
        self.max_nb_Msample = 4294967295
        self.max_nb_tau = 50
        
        # try connect to the server
        self.s.connect((self.host, self.port))
        self._set_timeout = 5

        # status and flag
        self.board_type = None
        self.Get_Board_Type()
        if not self.board_type in ['ADC8', 'ADC14']:
            raise ValueError, 'Invalid board_type'
        self.visa_addr = self.board_type
        self._run_finished = threading.Event() # starts in clear state

        self._listen_thread = Listen_thread(self)
        self._listen_thread.start()     
        
        # init the parent class
        instrument.BaseInstrument.__init__(self)

    def _idn(self):
        # Should be: Manufacturer,Model#,Serial#,firmware
        model = self.board_type
        serial = self.board_serial.getcache()
        return 'Acq card,%s,%s,1.0'%(model, serial)
    def _cls(self):
        """ Clear error buffer and status
        """
        self._error_state = False
        self._errors_list = []
    def _check_error(self):
        if self._error_state:
            raise ValueError, 'Acq Board currently in error state. clear it with _get_error.'
    def _get_error(self):
        if self._errors_list == []:
            self._error_state = False
            return '+0,"No error"'
        return self._errors_list.pop()
    @property
    def _set_timeout(self):
        return self.s.gettimeout()
    @_set_timeout.setter
    def _set_timeout(self, seconds): # can be None
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
                                     'lock_in_square','net_signal_freq')
                                     
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
                    name = obj._getdev[:-1]
                    self._objdict[name] = obj
            for devname, obj in self.dummy_devs_iter():
                name = obj._getdev[:-1]
                obj.instr = weakref.proxy(self)
                self._objdict[name] = obj

        # if full = true do one time
        # get the board type and program state
        self.board_serial.get()
        self.board_status.get()
        self.result_available.get()
        self.tau_vec([0])        

    def fetch_getformat(self, filename=None):
        self.fetch._format.update(file=True)
        return instrument.BaseDevice.getformat(self.fetch)
    def fetch_getdev(self, filename=None, ch=[1]):
        self.fetch._event_flag.clear()
        mode = self.op_mode.getcache()
        self.fetch._dump_file = None
        if mode == 'Acq':
            s = 'DATA:ACQ:DATA?'
            if filename != None:
                s += ' '+filename
            self.write(s)
            instrument.wait_on_event(self.fetch._event_flag, check_state=self)
            if self.fetch._rcv_val == None:
                return None
            if self.board_type == 'ADC14':
                return np.fromstring(self.fetch._rcv_val, np.ushort)
            else:
                return np.fromstring(self.fetch._rcv_val, np.ubyte)
        if mode == 'Hist':
            s = 'DATA:HIST:DATA?'
            if filename != None:
                s += ' '+filename
            self.write(s)
            instrument.wait_on_event(self.fetch._event_flag, check_state=self)
            if self.fetch._rcv_val == None:
                return None
            return np.fromstring(self.fetch._rcv_val, np.uint64)
        if mode == 'Osc':
            s = 'DATA:OSC:DATA?'
            if filename != None:
                s += ' '+filename
            self.write(s)
            instrument.wait_on_event(self.fetch._event_flag, check_state=self)
            if self.fetch._rcv_val == None:
                return None
            if self.board_type == 'ADC14':
                return np.fromstring(self.fetch._rcv_val, np.ushort)
            else:
                return np.fromstring(self.fetch._rcv_val, np.ubyte)
        if mode == 'Spec':
            # TODO prevent ch2 form overwrite ch1 in the file
            if type(ch) != list:
                ch = [ch]
            if 1 in ch:            
                s = 'DATA:SPEC:CH1?'
                if filename != None:
                    s += ' '+filename
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                return np.fromstring(self.fetch._rcv_val, np.float64)
            if 2 in ch:
                s = 'DATA:SPEC:CH2?'
                if filename != None:
                    s += ' '+filename
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                return np.fromstring(self.fetch._rcv_val, np.float64)
        if mode == 'Corr':
            # TODO prevent ch2 form overwrite ch1 in the file
            if type(ch) != list:
                ch = [ch]
            if self.corr_mode.getcache():
                s = 'DATA:CORR:CORR_RESULT?'
                if filename != None:
                    s += ' '+filename
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                return np.fromstring(self.fetch._rcv_val, np.float64)
            if 1 in ch:
                s = 'DATA:CORR:AUTOCORR_CH1_RESULT?'
                if filename != None:
                    s += ' '+filename
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                return np.fromstring(self.fetch._rcv_val, np.float64)
            if 2 in ch:
                s = 'DATA:CORR:AUTOCORR_CH2_RESULT?'
                if filename != None:
                    s += ' '+filename
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                return np.fromstring(self.fetch._rcv_val, np.float64)
                
        if mode == 'Cust':
            # TODO prevent ch2 form overwrite ch1 in the file
            if type(ch) != list:
                ch = [ch]
            if 1 in ch:
                s = 'DATA:CUST:RESULT_DATA1?'
                if filename != None:
                    s += ' '+filename
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                return np.fromstring(self.fetch._rcv_val, np.float64)
            if 2 in ch:
                s = 'DATA:CUST:RESULT_DATA2?'
                if filename != None:
                    s += ' '+filename
                self.write(s)
                instrument.wait_on_event(self.fetch._event_flag, check_state=self)
                if self.fetch._rcv_val == None:
                    return None
                return np.fromstring(self.fetch._rcv_val, np.float64)
            
                

    def readval_getdev(self, **kwarg):
        # TODO may need to check if trigger is already in progress
        self._async_trig()
        while not self._async_detect():
            pass
        return self.fetch.get()
    def readval_getformat(self, **kwarg):
        return self.fetch.getformat(**kwarg)
    # TODO redirect read to fetch when doing async

    def _tau_vec_helper(self, i, val):
        self.write('CONFIG:TAU %r %r'%(i, val))
    def _nb_tau_helper(self, N):
        self.write('CONFIG:NB_TAU %i'%N)
        self.tau_vec.nb_tau = N
    def tau_vec_setdev(self, vals, i=None, append=False):
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
    def tau_vec_getdev(self, force=False, i=None, append=None):
        if not force:
            return self.tau_vec._current_tau_vec
        # we read from device
        N = int(self._tau_nb.getdev())
        self.tau_vec.nb_tau = N
        self.tau_vec._current_tau_vec = []
        for i in range(N):
            ind, val = self._tau_veci.getdev(repr(i)).split(' ')
            if i != int(ind):
                raise ValueError, 'read wrong index. asked for %i, got %s'%(i, ind)
            self.tau_vec._current_tau_vec.append(int(val))
        return self.tau_vec._current_tau_vec

    def tau_vec_check(self, vals, i=None, append=False):
        # i is an index
        try:
            # vals is a vector
            # don't care for i or append
            N = len(vals)
            if N > self.max_nb_tau:
                raise ValueError, 'Too many values in tau_vec.set, max of %i elements'%self.max_nb_tau
            return
        except TypeError:
            pass
        if not np.isreal(vals):
            raise ValueError, 'vals needs to be a number'
        if i != None and not (0 <= i <= self.tau_vec.nb_tau):
            raise ValueError, 'Index is out of range'
        if append and self.tau_vec.nb_tau + 1 >= self.max_nb_tau:
            raise ValueError, 'You can no longer append, reached max'
        if i != None and append:
            raise ValueError, 'Choose either i or append, not both'

        #device member
    def create_devs(self):

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
        
        if self.board_type == 'ADC8':
            self.sampling_rate = acq_device('CONFIG:SAMPLING_RATE', str_type=float,  min=self.min_sampling_adc8, max=self.max_sampling_adc8)
        elif self.board_type == 'ADC14':
            self.sampling_rate = acq_device('CONFIG:SAMPLING_RATE', str_type=float,  min=self.min_sampling_adc14, max=self.max_sampling_adc14)
        
        self.test_mode = acq_device('CONFIG:TEST_MODE', str_type=acq_bool())
        self.clock_source = acq_device('CONFIG:CLOCK_SOURCE', str_type=str, choices=clock_source_str)
        self.nb_Msample = acq_device('CONFIG:NB_MSAMPLE', str_type=int,  min=self.min_nb_Msample, max=self.max_nb_Msample)
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
        self.osc_nb_sample = acq_device('CONFIG:OSC_NB_SAMPLE', str_type=int,  min=1, max= ((8192*1024*1024)-1)) # max 8Go
        self.osc_hori_offset = acq_device('CONFIG:OSC_HORI_OFFSET', str_type=int,  min=0, max= ((8192*1024*1024)-1)) # max 8Go
        self.osc_trig_source = acq_device('CONFIG:OSC_TRIG_SOURCE', str_type=int,  min=1, max=2)
        
        if self.board_type == 'ADC8':
            self.net_signal_freq = acq_device('CONFIG:NET_SIGNAL_FREQ', str_type=float,  min=0, max=375000000)
        elif self.board_type == 'ADC14':
            self.net_signal_freq = acq_device('CONFIG:NET_SIGNAL_FREQ', str_type=float,  min=0, max=50000000)
        
        self.lock_in_square = acq_device('CONFIG:LOCK_IN_SQUARE', str_type=acq_bool()) 
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
        self.result_available = acq_device(getstr='STATUS:RESULT_AVAILABLE?',str_type=acq_bool())
        
        self.format_location = acq_device('CONFIG:FORMAT:LOCATION', str_type=str, choices=format_location_str)
        self.format_type = acq_device('CONFIG:FORMAT:TYPE',str_type=str, choices=format_type_str)
        self.format_block_length = acq_device('CONFIG:FORMAT:BLOCK_LENGTH',str_type = int, min=1, max=4294967296)

        # Results
        #histogram result
        self.hist_m1 = acq_device(getstr = 'DATA:HIST:M1?', str_type = float, autoinit=False, trig=True)
        self.hist_m2 = acq_device(getstr = 'DATA:HIST:M2?', str_type = float, autoinit=False, trig=True)
        self.hist_m3 = acq_device(getstr = 'DATA:HIST:M3?', str_type = float, autoinit=False, trig=True)
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

        self.devwrap('fetch', autoinit=False)
        self.fetch._event_flag = threading.Event()
        self.fetch._rcv_val = None
        self.devwrap('readval', autoinit=False)
        self.devwrap('tau_vec', setget=True)
        self._tau_nb = dummy_device('CONFIG:NB_TAU?')
        self._tau_veci = dummy_device('CONFIG:TAU?')

        # This needs to be last to complete creation
        super(type(self),self).create_devs()
        
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
        
    def set_simple_acq(self,nb_Msample, sampling_rate, chan_mode, chan_nb,clock_source):
        self.op_mode.set('Acq')
        self.sampling_rate.set(sampling_rate)
        self.test_mode.set(False)
        self.clock_source.set(clock_source)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set(chan_mode)
        self.chan_nb.set(chan_nb)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
            
    def set_histogram(self, nb_Msample, sampling_rate, chan_nb, clock_source):
        self.op_mode.set('Hist')
        self.sampling_rate.set(sampling_rate)
        self.test_mode.set(False)
        self.clock_source.set(clock_source)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set('Single')
        self.chan_nb.set(chan_nb)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
    
    def set_correlation(self, nb_Msample, sampling_rate, clock_source):
        self.op_mode.set('Corr')
        self.sampling_rate.set(sampling_rate)
        self.test_mode.set(False)
        self.clock_source.set(clock_source)
        self.nb_Msample.set(nb_Msample)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        self.chan_mode.set('Dual')
        self.chan_nb.set(1)
        self.autocorr_mode.set(False)
        self.corr_mode.set(True)
    
    def set_autocorrelation(self, nb_Msample, sampling_rate, autocorr_single_chan, autocorr_chan_nb, clock_source):
        self.op_mode.set('Corr')
        self.sampling_rate.set(sampling_rate)
        self.test_mode.set(False)
        self.clock_source.set(clock_source)
        self.nb_Msample.set(nb_Msample)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        if autocorr_single_chan:
            self.chan_mode.set('Single')
        else:
            self.chan_mode.set('Dual')
        self.chan_nb.set(autocorr_chan_nb)
        self.autocorr_mode.set(True)
        self.corr_mode.set(False)
        
    def set_auto_and_corr(self, nb_Msample, sampling_rate, autocorr_single_chan, autocorr_chan_nb, clock_source):
        self.op_mode.set('Corr')
        self.sampling_rate.set(sampling_rate)
        self.test_mode.set(False)
        self.clock_source.set(clock_source)
        self.nb_Msample.set(nb_Msample)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        if autocorr_single_chan:
            self.chan_mode.set('Single')
        else:
            self.chan_mode.set('Dual')
        self.chan_nb.set(autocorr_chan_nb)
        self.autocorr_mode.set(True)
        self.corr_mode.set(True)
        
        
    def set_network_analyzer(self, nb_Msample, sampling_rate, signal_freq, lock_in_square, clock_source):
        self.op_mode.set('Net')
        self.sampling_rate.set(sampling_rate)
        self.test_mode.set(False)
        self.clock_source.set(clock_source)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set('Dual')
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        self.net_signal_freq.set(signal_freq)
        self.lock_in_square.set(lock_in_square)
        
    def set_scope(self, nb_sample, sampling_rate, hori_offset, trigger_level, slope, trig_source,chan_mode, chan_nb, clock_source):
        self.op_mode.set('Osc')
        self.sampling_rate.set(sampling_rate)
        self.test_mode.set(False)
        self.clock_source.set(clock_source)
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
        
    def set_spectrum(self,nb_Msample, fft_length, sampling_rate, chan_mode, chan_nb, clock_source):
        self.op_mode.set('Spec')
        self.sampling_rate.set(sampling_rate)
        self.test_mode.set(False)
        self.clock_source.set(clock_source)
        self.nb_Msample.set(nb_Msample)
        self.chan_mode.set(chan_mode)
        self.chan_nb.set(chan_nb)
        self.trigger_invert.set(False)
        self.trigger_edge_en.set(False)
        self.trigger_await.set(False)
        self.trigger_create.set(False)
        self.fft_length.set(fft_length)
        
    def set_custom(self,nb_Msample, sampling_rate, chan_mode, chan_nb, clock_source,cust_param1,cust_param2,cust_param3,cust_param4,cust_user_lib):
        self.op_mode.set('Cust')
        self.test_mode.set(False)
        self.clock_source.set(clock_source)
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
        
        # check if nb_Msample fit the op_mode
        if self.op_mode.getcache() == 'Hist' or self.op_mode.getcache() == 'Corr':
            
            if self.board_type == 'ADC14' and self.op_mode.getcache() == 'Hist':
                quotien = float(self.nb_Msample.getcache())/512
                frac,entier = math.modf(quotien)
            
                if frac != 0.0:
                    new_nb_Msample = int(math.ceil(quotien))*512
                    if new_nb_Msample > (self.max_nb_Msample - 512):
                        new_nb_Msample = self.max_nb_Msample - 512
                        self.nb_Msample.set(new_nb_Msample)
                    raise ValueError, 'Warning nb_Msample must be a multiple of 512 in Hist ADC14, value corrected to nearest possible value : ' + str(new_nb_Msample)
            else:
                quotien = float(self.nb_Msample.getcache())/8192
                frac,entier = math.modf(quotien)
            
                if frac != 0.0:
                    new_nb_Msample = int(math.ceil(quotien))*8192
                    if new_nb_Msample > (self.max_nb_Msample - 8192):
                        new_nb_Msample = self.max_nb_Msample - 8192
                        self.nb_Msample.set(new_nb_Msample)
                    raise ValueError, 'Warning nb_Msample must be a multiple of 8192 in Corr and Hist ADC8, value corrected to nearest possible value : ' + str(new_nb_Msample)
                    
        if self.op_mode.getcache() == 'Net':
            if self.nb_Msample.getcache() > 64:
                self.nb_Msample.set(64)
                raise ValueError, 'Warning nb_Msample must be between 32 and 64 in Net mode, value corrected to nearest possible value : ' + str(self.nb_Msample.getcache())
            
            
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
                    if new_sampling_rate > self.max_sampling_adc8:
                        new_sampling_rate = self.max_sampling_adc8
                    self.sampling_rate.set(new_sampling_rate)
                else:
                    new_sampling_rate = math.ceil(quotien) * 5
                    if new_sampling_rate > self.max_sampling_adc14:
                        new_sampling_rate = self.max_sampling_adc14
                    elif new_sampling_rate < self.min_usb_clock_freq:
                        new_sampling_rate = self.min_usb_clock_freq
                    self.sampling_rate.set(new_sampling_rate)
                raise ValueError, 'Warning sampling_rate not a multiple of 5, value corrected to nearest possible value : ' + str(new_sampling_rate)
                  
        #if in Osc mode check if the sample to sand fit the horizontal offset
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
        
        
            

           
           
