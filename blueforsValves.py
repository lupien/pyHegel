# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

# test interface for Bluefors

import socket
import threading
import time
import weakref

# TODO: the server has a timeout (initially 30s), so the connection is lost
#       when no commands are sent after that interval.
# keepalive stuff does not seem to work
#  import socket
#  bf = blueforsValves.bf_valves()
#  bf._socket.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 15*1000, 1*1000)) # windows
#  bf._socket.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE)
#  bf._socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
#    on linux
#  bf._socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE, 15) # default is 7200 (2 hours)
#  bf._socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPINTVL, 1) # default is 75
#  bf._socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPCNT, 9) # default is 9
# instead of keepalive, just sent '\n' every 20 s

class keep_alive(threading.Thread):
    def __init__(self, interval, sckt, lck):
        super(keep_alive, self).__init__()
        self.sckt = weakref.proxy(sckt)
        self.interval = interval
        self.lck = lck
        self.update_time()
        self.stop = False
    def send_keep_alive(self):
        with self.lck:
            self.sckt.send('\n')
            self.update_time()
    def run(self):
        while True:
            with self.lck:
                if self.stop:
                    break
                delta = time.time() - self.last
                if delta >= self.interval:
                    self.send_keep_alive()
                    continue
            time.sleep(self.interval - delta)
    def cancel(self):
        with self.lck:
            self.stop = True
    def update_time(self):
        # call with lock acquired
        self.last = time.time()
    def __del__(self):
        print 'cleaning up keep_alive thread.'

def makedict(input_str, t=float):
    lst = input_str.split(',')
    lst2 = [v.lstrip().split('=') for v in lst] # strip needed because mgstatus adds spaces after the comma
    return { k:t(v) for k,v in lst2 }
def booltype(s):
    return bool(int(s))

class bf_valves(object):
    """
    Useful query methods:
        status
        flow
        gage_val
        gage_status
    Controlling methods:
        turn_on
        turn_off
        switch
    Note that the control methods will only work if remote_en is True
    and this connection is in control. So use the methods
        control
        remote_en
    in that order, and before using any of the controlling methods.
    When the connection is lost (by del or disconnect)
    """
    def __init__(self, addr=('localhost', 1234), timeout=1., keep_interval=20):
        """
        addr is a tupple ip name, port number
        timeout is the time in s to wait for the completion of network connect/send/recv
                to prevent lockups
        keep_interval is the time in s between pings to the server to keep the connection open
                      it should be smaller than the server timeout
        """
        self._socket = None
        self._lock = threading.RLock()
        # timeout in s. Can be None which means blocking. None is the default timeout after importing
        #s = socket.socket()
        #s.connect(addr)
        #s.settimeout(timeout)
        s = socket.create_connection(addr, timeout=timeout)
        foo = s.recv(1024)
        if foo != '\x0c':
            raise RuntimeError, 'Did not receive expected signal'
        self._socket = s
        self._keep_alive = keep_alive(keep_interval, s, self._lock)
        self._keep_alive.start()
    def ask(self, command, expect=None):
        """
        expect is to strip some known string at the start of the answer.
        It can be a string, or a list of possible strings
        """
        command += '\n'
        with self._lock:
            l = self._socket.send(command)
            self._keep_alive.update_time()
        # check length or use sendall
        if l != len(command):
            raise RuntimeError, 'Data was not completely sent: %i out of %i bytes'%(l, len(command))
        answer = ''
        while len(answer)==0 or answer[-1] != '\n':
            answer += self._socket.recv(1024)
        answer = answer[:-2] # remove trailing CR LF
        if answer[0] == 'E':
            raise RuntimeError, 'Error: %s'%answer
        if expect:
            if isinstance(expect, basestring):
                expect = [expect]
            for e in expect:
                e += ': '
                if answer.startswith(e):
                    answer = answer[len(e):]
                    break
            else: # not found
                raise RuntimeError, 'Unexpected reply: %s'%answer
        return answer
    def avail_names(self):
        """
        returns a list of available names for status, turn_on, turn_off and switch
        """
        return self.ask('names', 'S04').split(',')
    def _names_helper(self, val):
        if isinstance(val, basestring) or val == None:
            return val
        return ','.join(val)
    def status(self, valves=None):
        """
        valves can be a string of comma separated name
        or a list of strings of name of object to receive the status.
        If not given, they are all returned in the order of avail_names.
        The return is a dictionnary.
        """
        # the answer is name1=value1,name2=value2 ...
        # when valves=None the answer is in the order of avail_names
        # otherwise it is the order given
        cmd = 'status'
        valves = self._names_helper(valves)
        if valves:
            return makedict(self.ask(cmd+' '+valves, 'S02'), booltype)
        else:
            return makedict(self.ask(cmd, 'S03'), booltype)
    def remote_en(self, val=None):
        """
        val is True or False to change, or None to read
        Remote can only be set if user is in control.
        Remote needs to be enable to be able to change settings.
        It locks out the Hardware interface.
          The remote enabled is deactivated if the connection is lost.
        """
        if val == None:
            return bool(int(self.ask('remote', 'S06')))
        else:
            self.ask('remote %s'%int(val), 'S06')
    def control(self, val=None):
        """
        val is True or False to change, or None to read
        When a connection is in control, another one cannot become in control
        until the first one releases it, Otherwise you get E10: permission denied.
        """
        if val == None:
            return self.ask('control', ['S07', 'S08'])
        else:
            self.ask('control %s'%int(val), ['S07', 'S08'])
    def turn_on(self, valves):
        """
        valves is either a string of comma separated names or a list of names
        of objects to turn on.
        No valves is changed if there is an error in the list
        """
        valves = self._names_helper(valves)
        self.ask('on '+valves, 'S00') # S00: Ok
    def turn_off(self, valves):
        """
        valves is either a string of comma separated names or a list of names
        of objects to turn off.
        No valves is changed if there is an error in the list
        """
        valves = self._names_helper(valves)
        self.ask('off '+valves, 'S00') # S00: Ok
    def switch(self, valves):
        """
        valves is either a string of comma separated names or a list of names
        of objects to toggle.
        No valves is changed if there is an error in the list
        """
        valves = self._names_helper(valves)
        self.ask('switch '+valves, 'S00') # S00: Ok
    def flow(self):
        """
        returns the flow in mmol/s
        """
        return float(self.ask('fmstatus', 'S09'))
    def gage_val(self, gage_num=None):
        """
        gage_num can be None or 1-6 for P1 to P6
        Multiple values are return in a dictionnary
        """
        if gage_num == None:
            return makedict(self.ask('mgstatus', 'S11')) # a list of p1=val, p2=val, ...
        else:
            return float(self.ask('mgstatus %s'%int(gage_num), 'S05'))
    _gage_status_d = {0:'Measurement data okay', 1:'Underrange', 2:'Overrange', 3:'Sensor error',
                      4:'Sensor off', 5:'No sensor', 6:'Identification error'}
    def _gage_status_helper(self, in_str):
        v = int(in_str)
        return v, self._gage_status_d[v]
    def gage_status(self, gage_num=None):
        """
        gage_num can be None or 1-6 for P1 to P6
        returns the pressures in mBar.
        Multiple values are return in a dictionnary
        """
        if gage_num == None:
            return makedict(self.ask('mgstatuscode', 'S12'), self._gage_status_helper) # a list of p1=val, p2=val, ...
        else:
            s = self.ask('mgstatuscode %s'%int(gage_num), 'S10')
            return self._gage_status_helper(s)
    def __del__(self):
        self._keep_alive.cancel()
        if self._socket:
            self.disconnect()
        print 'bf_valves deleted!'
    def disconnect(self):
        self._keep_alive.cancel()
        self.ask('exit', 'S01') # S01: bye
        self._socket.shutdown(socket.SHUT_RDWR)
        self._socket.close()
        self._socket = None
