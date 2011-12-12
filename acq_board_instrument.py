# -*- coding: utf-8 -*-
"""
Created on Fri Dec 09 13:39:09 2011

@author: blas2310
"""

# system import
import socket
import select
import threading

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
        instrument.wait_on_event(self._event_flag)
        return self._fromstr(self._rcv_val)

class Listen_thread(threading.Thread):
    def __init__(self, acq_instr):
        super(type(self), self).__init__()
        self.daemon = True
        self._stop = False
        self.acq_instr = acq_instr
    def run(self):
        select_list = [self.acq_instr.s]
        socket_timeout = 0.1
        old_stuff = ''
        while not self._stop:
            try:
                r, _, _ = select.select(select_list, [], [], socket_timeout)
                if not bool(r):
                    continue
            except socket.error:
                break
            new_stuff = self.acq_instr.s.recv(128)
            old_stuff += new_stuff
            trames = old_stuff.split('\n')
            old_stuff = trames.pop()
            for trame in trames:
                if trame[0] != '@':
                    continue
                trame = trame[1:]
                head, val = trame.split(' ', 1)
                obj = self.acq_instr._objdict[head]
                obj._rcv_val = val
                obj._event_flag.set()
    def cancel(self):
        self._stop = True
    def wait(self, timeout=None):
        self.join(timeout)
        return not self.is_alive()


class Acq_Board_Instrument(instrument.visaInstrument):
    
    def __init__(self, ip_adress, port_nb):
        self._listen_thread = None
        # init the server member
        self.host = ip_adress
        self.port = port_nb
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # try connect to the server
        self.s.connect((self.host, self.port))

        # status and flag
        self.board_type = None
        self.Get_Board_Type()
        if not self.board_type in ['ADC8', 'ADC14']:
            raise ValueError, 'Invalid board_type'
        self.visa_addr = self.board_type

        self._listen_thread = Listen_thread(self)
        self._listen_thread.start()     
        
        # init the parent class
        instrument.BaseInstrument.__init__(self)

    def _set_timeout(self):
        pass
    def __del__(self):
        if self._listen_thread:
            self._listen_thread.cancel()
            self._listen_thread.wait()
        self.s.close()
        
    def init(self,full = False):
        if full == True:
            self._objdict = {}
            for devname, obj in self.devs_iter():
                if isinstance(obj, acq_device):
                    name = obj._getdev[:-1]
                    self._objdict[name] = obj
        # if full = true do one time
        # get the board type and porgram state
        self.board_serial.get()
        self.board_status.get()
        self.result_available.get()        
        
        #device member
    def create_devs(self):

        # choices string and number
        op_mode_str = ['Acq', 'Corr', 'Cust', 'Hist', 'Net', 'Osc', 'Spec']
        clock_source_str = ['Internal', 'External', 'USB']
        chan_mode_str = ['Single','Dual']
        osc_slope_str = ['Rising','Falling']
        
        #device init
        # Configuration
        self.op_mode = acq_device('CONFIG:OP_MODE', str_type=str, choices=op_mode_str)
        
        if self.board_type == 'ADC8':
            self.sampling_rate = acq_device('CONFIG:SAMPLING_RATE', str_type=float,  min=1000, max=3000)
        elif self.board_type == 'ADC14':
            self.sampling_rate = acq_device('CONFIG:SAMPLING_RATE', str_type=float,  min=20, max=400)
        
        self.test_mode = acq_device('CONFIG:TEST_MODE', str_type=acq_bool())
        self.clock_source = acq_device('CONFIG:CLOCK_SOURCE', str_type=str, choices=clock_source_str)
        self.nb_Msample = acq_device('CONFIG:NB_MSAMPLE', str_type=int,  min=32, max=65535)
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
            self.net_signal_freq = acq_device('CONFIG:SIGNAL_FREQ', str_type=float,  min=0, max=375000000)
        elif self.board_type == 'ADC14':
            self.net_signal_freq = acq_device('CONFIG:SIGNAL_FREQ', str_type=float,  min=0, max=50000000)
        
        self.lock_in_square = acq_device('CONFIG:LOCK_IN_SQUARE', str_type=bool) 
        self.nb_tau = acq_device('CONFIG:NB_TAU', str_type=int,  min=0, max=50)
        self.autocorr_mode = acq_device('CONFIG:AUTOCORR_MODE', str_type=acq_bool())
        self.corr_mode = acq_device('CONFIG:CORR_MODE', str_type=acq_bool())
        self.autocorr_single_chan = acq_device('CONFIG:AUTOCORR_SINGLE_CHAN', str_type=acq_bool())
        self.fft_length = acq_device('CONFIG:FFT_LENGTH', str_type=int)
        self.cust_param1 = acq_device('CONFIG:CUST_PARAM1', str_type=float)
        self.cust_param2 = acq_device('CONFIG:CUST_PARAM2', str_type=float)
        self.cust_param3 = acq_device('CONFIG:CUST_PARAM3', str_type=float)
        self.cust_param4 = acq_device('CONFIG:CUST_PARAM4', str_type=float)
        self.cust_user_lib = acq_device('CONFIG:CUST_USER_LIB', str_type=str)
        self.board_serial = acq_device(getstr='CONFIG:BOARD_SERIAL?',str_type=int)
        self.board_status = acq_device(getstr='STATUS:STATE?',str_type=str)
        self.result_available = acq_device(getstr='STATUS:RESULT_AVAILABLE?',str_type=acq_bool())
        
        # Results
        self.hist_m1 = acq_device(getstr = 'DATA:HIST:M1?', str_type = float, autoinit=False)
        self.hist_m2 = acq_device(getstr = 'DATA:HIST:M2?', str_type = float, autoinit=False)
        self.hist_m3 = acq_device(getstr = 'DATA:HIST:M3?', str_type = float, autoinit=False)
        # TODO histogram raw data
        
        #TODO correlation result
        #TODO 
        
        self.custom_result1 = acq_device(getstr = 'DATA:CUST:RESULT1?',str_type = float, autoinit=False)
        self.custom_result2 = acq_device(getstr = 'DATA:CUST:RESULT2?',str_type = float, autoinit=False)
        self.custom_result3 = acq_device(getstr = 'DATA:CUST:RESULT3?',str_type = float, autoinit=False)
        self.custom_result4 = acq_device(getstr = 'DATA:CUST:RESULT4?',str_type = float, autoinit=False)
        
        # This needs to be last to complete creation
        super(type(self),self).create_devs()
        
    #class methode     
    def write(self, val):
        val = '@' + val + '\n'
        self.s.send(val)

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
        self.cust_param1.set(10.0)
        
        
    def run(self):
        # check if the configuration are ok
        self.write('STATUS:CONFIG_OK True')
        self.write('RUN')
        
        
            

           
           
