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

import socket
import threading
import time
import weakref
import numpy as np
import datetime
import copy
import os.path
import ssl

from ..instruments_base import BaseInstrument, MemoryDevice,\
                             dict_improved, locked_calling, wait_on_event, FastEvent, wait,\
                             ProxyMethod, BaseDevice, ChoiceBase, KeyError_Choices, ChoiceLimits,\
                             ChoiceSimpleMap,  ChoiceIndex, Dict_SubDevice
from ..instruments_registry import register_instrument
_wait = wait

#######################################################
##    Bluefors Valve
#######################################################


#  the server has a timeout (initially 30s), so the connection is lost
#  when no commands are sent after that interval.
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
                    continue  # skipt wait (we just changed self.last)
            wait = min(self.interval - delta, 5) # wait at most 5s
            time.sleep(wait)
    def cancel(self):
        with self.lck:
            self.stop = True
    def update_time(self):
        # call with lock acquired
        self.last = time.time()
    #def __del__(self):
    #    print 'cleaning up keep_alive thread.'

def makedict(input_str, t=float):
    lst = input_str.split(',')
    lst2 = [v.lstrip().split('=') for v in lst] # strip needed because mgstatus adds spaces after the comma
    return dict_improved([ (k,t(v)) for k,v in lst2])
def booltype(s):
    return bool(int(s))

@register_instrument('BlueFors', 'BF-LD400', '3.5')
class bf_valves(BaseInstrument):
    """
    This instruments communicates with the BlueFors ValveControl program.
    That program needs to be running and to have the remote control server running.

    Useful devices:
        gage
        all_gages
        all_status
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

    This instrument does not have separate read and write methods. Only use ask.
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
        # timeout in s. Can be None which means blocking. None is the default timeout after importing
        #s = socket.socket()
        #s.connect(addr)
        #s.settimeout(timeout)
        s = socket.create_connection(addr, timeout=timeout)
        foo = s.recv(1024)
        if foo != '\x0c':
            raise RuntimeError, 'Did not receive expected signal'
        self._socket = s
        super(bf_valves, self).__init__()
        self._keep_alive = keep_alive(keep_interval, s, self._lock_instrument)
        self._keep_alive.start()

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('idn', 'all_gages', 'all_status', options)
    @locked_calling
    def ask(self, command, expect=None):
        """
        expect is to strip some known string at the start of the answer.
        It can be a string, or a list of possible strings
        """
        command += '\n'
        n = self._socket.send(command)
        self._keep_alive.update_time()
        # check length or use sendall
        if n != len(command):
            raise RuntimeError, 'Data was not completely sent: %i out of %i bytes'%(n, len(command))
        answer = ''
        while len(answer) == 0  or  answer[-1] != '\n':
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
        if isinstance(val, basestring) or val is None:
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
        if val is None:
            return bool(int(self.ask('remote', 'S06')))
        else:
            self.ask('remote %s'%int(val), 'S06')
    def control(self, val=None):
        """
        val is True or False to change, or None to read
        When a connection is in control, another one cannot become in control
        until the first one releases it, Otherwise you get E10: permission denied.
        """
        if val is None:
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
        if gage_num is None:
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
        if gage_num is None:
            return makedict(self.ask('mgstatuscode', 'S12'), self._gage_status_helper) # a list of p1=val, p2=val, ...
        else:
            s = self.ask('mgstatuscode %s'%int(gage_num), 'S10')
            return self._gage_status_helper(s)
    def __del__(self):
        self._keep_alive.cancel()
        if self._socket:
            self.disconnect()
        #print 'bf_valves deleted!'
        super(bf_valves, self).__del__()
    def disconnect(self):
        self._keep_alive.cancel()
        self.ask('exit', 'S01') # S01: bye
        self._socket.shutdown(socket.SHUT_RDWR)
        self._socket.close()
        self._socket = None
    def idn(self):
        serialn = get_bluefors_sn() # see definition below
        # 3.5 is the ValveControl server version number used when this code was first written.
        return "BlueFors,BF-LD400,%s,3.5"%serialn
    _gages_names = ['p%i'%i for i in range(1,7)]
    def _all_gages_getdev(self):
        """
        Returns the values of the flow meter followed by all 6 pressure gages.
        """
        vals = self.gage_val()
        if vals.keys() != self._gages_names:
            raise RuntimeError('The keys is gages_vals are not in the expected format.')
        flow = self.flow()
        return [flow] + vals.values()
    def _gage_getdev(self, p=None):
        """
        when p=0 returns the flow meter
        """
        if p is not None:
            self.current_p.set(p)
        p = self.current_p.getcache()
        if p == 0:
            return self.flow()
        else:
            return self.gage_val(p)
    def _status_sort_key_func(self, x):
        # from (k,v) where k can be 'valve1'
        # return ('valve', 1)
        # could also use regular expressions: ks, ke = re.match(r'(\D+)(\d*)', k).groups()
        k = x[0]
        ks = k.rstrip('0123456789')
        ke = k[len(ks):]
        if ke != '':
            return (ks, int(ke))
        else:
            return (k, )
    def _all_status_getdev(self):
        st = self.status().items()
        st = sorted(st, key=self._status_sort_key_func)
        return dict_improved(st)
    def _create_devs(self):
        self.current_p = MemoryDevice(1, min=0, max=6)
        self._devwrap('all_gages', multi=['flow']+self._gages_names)
        self.alias = self.all_gages
        self.all_gages
        self._devwrap('gage')
        self._devwrap('all_status')
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


###########################################################
#  Code to find usb devices
###########################################################
# another option is to use wmi
# https://github.com/todbot/usbSearch/
# pyusb or pywinusb (uses SetupDi...)
#  https://pypi.python.org/pypi/pywinusb/
# Here we use SetupDi...
# http://stackoverflow.com/questions/13927475/windows-how-to-enumerate-all-connected-usb-devices-device-path
# http://samscode.blogspot.ca/2009/08/setupdi-how-to-enumerate-devices-using.html
# http://samscode.blogspot.ca/2009/09/function-discovery-intro.html

import os

# The bluefors dilution fridges have a National Instrument DAQ card.
# We can use that to identify which one it is.

# usb vendor/product = 0x3923/0x717a or 14627/29050
bluefors_serial = {'0158748E':'BF0312-03',
                   '015873C4':'BF0312-02',
                   '017E7ABE':'BF0215-04',
                   '0149FBE6':'BF1211-01',
                   '01B88CCB':'BF0217-08',
                   '01B88CB8':'BF0217-09',
                   '01E9E2CA':'SO01147.0010'}

def get_bluefors_sn():
    lst = get_all_usb() # defined below
    for v,p,s in lst:
        if v == 0x3923 and p == 0x717a:
            return bluefors_serial.get(s, 'Unknown serial # (%s)'%s)
    return 'No fridge found'

if os.name == 'nt':
    import ctypes
    from ctypes import POINTER, Structure, byref, c_void_p, create_string_buffer, string_at,\
                        sizeof, get_last_error, c_char, GetLastError, WinError, FormatError,\
                        cast, pointer, resize
    from ctypes.wintypes import HANDLE, LPCSTR, LPSTR, DWORD, WORD, BYTE, BOOL

    # Load the SetupAPI
    #setup_api = ctypes.windll.setupapi # can use ctypes.GetLastError, WinError, FormatError
    setup_api = ctypes.WinDLL('setupapi', use_last_error=True) # use get_last_error
    def format_err(err=None):
        if err is None:
            err = get_last_error()
        #return str(WinError(err))
        return "[Error %i] %s"%(err, FormatError(err))

    # For packing we need to find out if we are 32 or 64 bits:
    if sizeof(c_void_p) == 4: # 32 bits
        setup_api_pack = 1
    else: # 64 bits
        setup_api_pack = 8

    # define necessary structures
    class GUID(Structure):
        _fields_ = [("data1", DWORD), ("data2", WORD), ("data3", WORD), ("data4", BYTE*8)]
        def __init__(self, *args, **kwarg):
            if len(args) == 1 and isinstance(args[0], basestring):
                s = args[0].lstrip('{').rstrip('}').replace('-','')
                args = (int(s[:8],16), int(s[8:12],16), int(s[12:16],16), tuple([int(s[16+i*2:16+i*2+2], 16) for i in range(8)]))
            super(GUID, self).__init__(*args, **kwarg)
    # Some GUIDs
    GUID_CLASS_DAQDevice = GUID("{7c797140-f6d8-11cf-9fd6-00a024178a17}")
    GUID_INTERFACE_USB_DEVICE = GUID("{A5DCBF10-6530-11D2-901F-00C04FB951ED}")
    GUID_INTERFACE_COMPORT = GUID('{86E0D1E0-8089-11D0-9CE4-08003E301F73}')

    class SP_DEVINFO_DATA(Structure):
        _pack_ = setup_api_pack
        _fields_ = [('cbSize', DWORD), ('ClassGuid', GUID), ('DevInst', DWORD), ('Reserved', c_void_p)]
    class SP_DEVICE_INTERFACE_DATA(Structure):
        _pack_ = setup_api_pack
        _fields_ = [('cbSize', DWORD), ('InterfaceClassGuid', GUID), ('Flags', DWORD), ('Reserved', c_void_p)]
    class SP_DEVICE_INTERFACE_DETAIL_DATA(Structure):
        _pack_ = setup_api_pack
        _fields_ = [('cbSize', DWORD), ('DevicePath', c_char*1) ]
        def get_string(self):
            """
            instead of using detail_gen, to create a properly sized object,
            you can use ctypes.resize(obj, newsize)
            """
            return string_at(byref(self, self.__class__.DevicePath.offset))
    def detail_gen(size):
        #length = size - sizeof(DWORD)
        length = size - SP_DEVICE_INTERFACE_DETAIL_DATA.DevicePath.offset
        class foo(Structure):
            _pack_ = setup_api_pack
            _fields_ = [('cbSize', DWORD), ('DevicePath', c_char*length) ]
        return foo()
    def detail_gen_subclass(size):
        # This adds fields to the base class
        # You cannot overwrite one (giving the same name just removes access
        # to the old one and adds a new field)
        # Also the new fields are placed after the packing bytes possibly
        # added for the base struct. So the result is not like a concatenation
        # of the _fields_ entries (there can be extra space in between
        # the groups of _fields_)
        length = size - sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA)
        if length <= 0:
            length =1
        class foo(SP_DEVICE_INTERFACE_DETAIL_DATA):
            #_pack_ = setup_api_pack
            _fields_ = [('DevicePathM', c_char*length)]
        return foo()
    # declare setupAPI functions
    # SetupDiGetClassDevsA
    GetClassDevs = setup_api.SetupDiGetClassDevsA
    GetClassDevs.restype = HANDLE
    GetClassDevs.argtypes = [POINTER(GUID), LPCSTR, HANDLE, DWORD]
    DIGCF_DEFAULT = 0x01
    DIGCF_PRESENT = 0x02
    DIGCF_ALLCLASSES = 0x04
    DIGCF_PROFILE = 0x08
    DIGCF_DEVICEINTERFACE = 0x10
    # SetupDiDestroyDeviceInfoList
    DestroyDeviceInfoList = setup_api.SetupDiDestroyDeviceInfoList
    DestroyDeviceInfoList.restype = BOOL
    DestroyDeviceInfoList.argtypes = [HANDLE]
    # SetupDiEnumDeviceInterfaces
    EnumDeviceInterfaces = setup_api.SetupDiEnumDeviceInterfaces
    EnumDeviceInterfaces.restype = BOOL
    EnumDeviceInterfaces.argtypes = [HANDLE, c_void_p, POINTER(GUID), DWORD, POINTER(SP_DEVICE_INTERFACE_DATA)]
    # SetupDiEnumDeviceInfo
    EnumDeviceInfo = setup_api.SetupDiEnumDeviceInfo
    EnumDeviceInfo.restype = BOOL
    EnumDeviceInfo.argtypes = [HANDLE, DWORD, POINTER(SP_DEVINFO_DATA)]
    # SetupDiGetDeviceInstanceIdA
    GetDeviceInstanceId = setup_api.SetupDiGetDeviceInstanceIdA
    GetDeviceInstanceId.restype = BOOL
    GetDeviceInstanceId.argtypes = [HANDLE, POINTER(SP_DEVINFO_DATA), LPSTR, DWORD, POINTER(DWORD)]
    # SetupDiGetDeviceInterfaceDetailA
    GetDeviceInterfaceDetail = setup_api.SetupDiGetDeviceInterfaceDetailA
    GetDeviceInterfaceDetail.restype = BOOL
    #GetDeviceInterfaceDetail.argtypes = [HANDLE, POINTER(SP_DEVICE_INTERFACE_DATA), c_void_p, DWORD, POINTER(DWORD), POINTER(SP_DEVINFO_DATA)]
    GetDeviceInterfaceDetail.argtypes = [HANDLE, POINTER(SP_DEVICE_INTERFACE_DATA), POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA), DWORD, POINTER(DWORD), POINTER(SP_DEVINFO_DATA)]

    # error when Enum are finished
    ERROR_NO_MORE_ITEMS = 259

    # Error return value for GetClassDevs
    INVALID_HANDLE_VALUE = HANDLE(-1).value

    # The returned values look like:
    #    'USB\\VID_3923&PID_717A\\0158748E'
    # which is the same as seen in the Gestionnaire de peripherique entry:
    #     Chemin d'access a l'instance du peripherique
    # suggested calls
    #  get_all_dev_instanceID(None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    #  get_all_dev_instanceID(None, 'PCI', DIGCF_PRESENT | DIGCF_ALLCLASSES)
    #  get_all_dev_instanceID(None, 'USB', DIGCF_PRESENT | DIGCF_ALLCLASSES)
    #  get_all_dev_instanceID(GUID_CLASS_DAQDevice, 'USB', DIGCF_PRESENT)
    #  get_all_dev_instanceID(GUID_INTERFACE_USB_DEVICE, 'USB', DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    def get_all_dev_instanceID(ClassGuid, Enumerator, Flags):
        devinfo = GetClassDevs(ClassGuid, Enumerator, 0, Flags)
        if devinfo == INVALID_HANDLE_VALUE:
            raise RuntimeError, format_err()
        m=0
        dinfo = SP_DEVINFO_DATA()
        dinfo.cbSize = sizeof(SP_DEVINFO_DATA)
        bufsize = DWORD()
        res = []
        while True:
            if not EnumDeviceInfo(devinfo, m, dinfo):
                err = get_last_error()
                if err != ERROR_NO_MORE_ITEMS:
                    DestroyDeviceInfoList(devinfo)
                    raise RuntimeError, 'EnumDeviceInfo '+format_err(err)
                break
            # Find required bufsize
            GetDeviceInstanceId(devinfo, dinfo, None, 0, bufsize)
            buf = create_string_buffer(bufsize.value)
            if not GetDeviceInstanceId(devinfo, dinfo, buf, bufsize, None):
                DestroyDeviceInfoList(devinfo)
                raise RuntimeError, 'GetDeviceInstanceId '+format_err()
            res.append(buf.value)
            #print "m:%i instanceID:%r"%(m, buf.value)
            m += 1
        DestroyDeviceInfoList(devinfo)
        return res
    # suggested calls:
    #  get_all_dev_interface(None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES | DIGCF_DEVICEINTERFACE)
    #  get_all_dev_interface(GUID_INTERFACE_USB_DEVICE, None, DIGCF_PRESENT|DIGCF_DEVICEINTERFACE)
    #  get_all_dev_interface(None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES | DIGCF_DEVICEINTERFACE, search_interface=GUID_INTERFACE_COMPORT)
    # The returned values look like:
    #   '\\\\?\\usb#vid_3923&pid_717a#0158748e#{a5dcbf10-6530-11d2-901f-00c04fb951ed}'
    USE_RESIZE = True
    def get_all_dev_interface(ClassGuid, Enumerator, Flags, search_interface=GUID_INTERFACE_USB_DEVICE):
        if not Flags & DIGCF_DEVICEINTERFACE:
            raise ValueError, "The DIGCF_DEVICEINTERFACE flag is required here."
        devinfo = GetClassDevs(ClassGuid, Enumerator, 0, Flags)
        if devinfo == INVALID_HANDLE_VALUE:
            raise RuntimeError, format_err()
        m=0
        dinter = SP_DEVICE_INTERFACE_DATA()
        dinter.cbSize = sizeof(SP_DEVICE_INTERFACE_DATA)
        bufsize = DWORD()
        res = []
        while True:
            if not EnumDeviceInterfaces(devinfo, None, search_interface, m, dinter):
                err = get_last_error()
                if err != ERROR_NO_MORE_ITEMS:
                    DestroyDeviceInfoList(devinfo)
                    raise RuntimeError, 'EnumDeviceInterface '+format_err(err)
                break
            # Find required bufsize
            GetDeviceInterfaceDetail(devinfo, dinter, None, 0, bufsize, None)
            if USE_RESIZE:
                detail = SP_DEVICE_INTERFACE_DETAIL_DATA()
                resize(detail, bufsize.value)
                detailp = byref(detail)
            else:
                detail = detail_gen(bufsize.value)
                # cast is needed because GetDeviceInterfaceDetail is defined to require
                #  POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA)
                # Instead of a cast the object could also be a subclass
                detailp = cast(pointer(detail), POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA))
            detail.cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA)
            # Note that the last argument could be used to have the SP_DEVINFO_DATA
            # reference of this entry that can be used with GetDeviceInstanceId
            if not GetDeviceInterfaceDetail(devinfo, dinter, detailp, sizeof(detail), None, None):
                DestroyDeviceInfoList(devinfo)
                raise RuntimeError, 'GetDeviceInterfaceDetail '+format_err()
            if USE_RESIZE:
                res.append(detail.get_string())
            else:
                res.append(detail.DevicePath)
            m += 1
        DestroyDeviceInfoList(devinfo)
        return res

    def get_all_usb():
        all_usb = get_all_dev_instanceID(GUID_INTERFACE_USB_DEVICE, None, DIGCF_PRESENT|DIGCF_DEVICEINTERFACE)
        res = []
        for one_usb in all_usb:
            lst = one_usb.split('\\')
            # When serialn contains &, it is a serial number invented by windows.
            # http://rtshiva.com/2009/05/19/usb-specification-and-windows-limitation-on-serial-numbers/
            serialn = lst[2]
            ids = lst[1].split('&')
            vid = ids[0][4:]
            pid = ids[1][4:]
            res.append((int(vid, 16), int(pid, 16), serialn))
        return res

else: # Not windows
    #pyusb requires special permissions to read the serial number
    def get_all_usb_pyusb():
        import usb
        def getstr(dev, index):
            try:
                return usb.util.get_string(dev, 1024, index)
            except usb.USBError:
                return "Not available: Wrong Permissions"
        lst = usb.core.find(find_all=True)
        return [(i.idVendor, i.idProduct, getstr(i, i.iSerialNumber)) for i in lst]

    # This is linux only
    def _read_file(filename):
        with open(filename, 'r') as f:
            line = f.read()
        return line
    def get_all_usb_sysfs():
        import glob
        # the linux usb sysfs path looks like
        # bus-port.port.port ...
        #  and :config.interface
        dl=glob.glob('/sys/bus/usb/devices/[0-9]*-[0-9.]*')
        res = []
        for d in dl:
            if ':' in d:
                break
            try:
                vid = _read_file(d+'/idVendor')
            except IOError:
                break
            try:
                pid = _read_file(d+'/idProduct')
            except IOError:
                break
            try:
                serialn = _read_file(d+'/serial')
            except IOError:
                serialn = 'Unknown'
            res.append((int(vid, 16), int(pid, 16), serialn))
        return res

    get_all_usb = get_all_usb_sysfs


#######################################################
##    Bluefors Temperature controller
#######################################################

# possible protocols:
# - http get/post: are blocking but can reuse a socket
# - websocket: need to open multiple connections to the various variables
# - mqtt: can reuse the socket but is asynchronous. But others mqtt user can produce request which we will receive also

import json
import uuid
import six
if six.PY2:
    import Queue as queue
else:
    import queue


mqtt_loaded = None
try:
    import paho.mqtt.client
except ImportError:
    mqtt_loaded = False
else:
    mqtt_loaded = True

requests_loaded = None
try:
    import requests
except ImportError:
    requests_loaded = False
else:
    requests_loaded = True

websocket_loaded = None
try:
    import websocket
except ImportError:
    websocket_loaded = False
else:
    websocket_loaded = True

class Bf_Dict_Choices(ChoiceBase):
    def __init__(self, fields, required=[], readonly_fields=[]):
        """
        fields is a dictionnary of name:Choices
        required is the list of fields that are required
        Not all the field in the read from instrument dictionnary need to be in fields
         missing values will be passed as is.
        """
        self.fields = fields
        field_names = []
        fmts = []
        for k, v in fields.items():
            field_names.append(k)
            fmts.append(v)
        self.field_names = field_names
        self.fmts_lims = fmts
        self.required = required
        self.readonly_fields = readonly_fields
    def __contains__(self, val_dict):
        for n in self.required:
            if n not in val_dict:
                raise KeyError('missing parameter: %s'%n)
        for k, v in val_dict.items():
            if k not in self.fields:
                raise ValueError('invalid parameter %s'%k)
            if k in self.readonly_fields:
                raise ValueError('parameter %s not allowed in write requests'%k)
            check = v in self.fields[k]
            if not check:
                return False
        return True
    def tostr(self, val):
        # convert to instrument device value
        ret = {}
        for k, v in val.items():
            if k in self.fields:
                ret[k] = self.fields[k].tostr(v)
            else:
                # This is needed for heater_nr, channel_nr
                ret[k] = v
        return ret
    def __call__(self, val):
        # convert from instrument device value
        ret = {}
        for k, v in val.items():
            if k in self.fields:
                ret[k] = self.fields[k](v)
            else:
                ret[k] = v
        return ret
    def __repr__(self):
        r = ''
        first = True
        for k, lims in self.fields.items():
            if k in self.readonly_fields:
                continue
            if not first:
                r += '\n'
            first = False
            r += 'key %s has limits %r'%(k, lims)
        return r

class BfChoiceLimits(ChoiceLimits):
    def tostr(self, val):
        return val
    def __call__(self, val):
        return val

BfChoiceIndex = lambda *args, **kwargs: ChoiceIndex(*args, noconv=True, **kwargs)

class BlueforsDevice(BaseDevice):
    def __init__(self, topic=None, proto=None, readcache=None, readonly=False, predev=None, *args, **kwargs):
        # predev when given is (para_name, mqtt_name, dev)
        self._proto = proto
        self._topic = topic
        self._predev = predev
        self._readcache = readcache
        kwargs['allow_kw_as_dict'] = True
        super(BlueforsDevice, self).__init__(*args, **kwargs)
        if not readonly:
            self._setdev_p = True
        self._getdev_p = True
        self.type = self.choices # needed by Dict_SubDevice

    def _get_docstring(self, added=''):
        added += """\
set/get options for this type of device:
    clean: when True (default) cleans up the return value of the status and datetime fields
           and possible predev field
"""
        header_added = [False]
        def add_header(added):
            if not header_added[0]:
                 added += '---------- Optional Parameters\n'
                 header_added[0] = True
            return added
        if self._predev:
            added = add_header(added)
            para_name, mqtt_name, dev = self._predev
            added += '{name}: has default value {val!r} with possible values between {min} and {max}\n'.format(name=para_name, val=dev, min=dev.min, max=dev.max)
        if self._setdev_p and self.choices:
            added = add_header(added)
            added += repr(self.choices) + '\n'
        return super(BlueforsDevice, self)._get_docstring(added=added)

    def _doprev(self, kwargs, in_get=False):
        predev = self._predev
        if predev is None:
            return kwargs, kwargs.copy(), None
        para_name, mqtt_name, dev = predev
        val = kwargs.pop(para_name, None)
        if in_get and len(kwargs) != 0:
                raise ValueError('Parameter invalid or not allowed in get: %s'%(kwargs.keys()))
        if val is None:
            val = dev.get()
        else:
            dev.set(val)
        kwargs2check = kwargs.copy()
        kwargs[mqtt_name] = val
        return kwargs, kwargs2check, val

    def _doclean(self, response):
        response = copy.deepcopy(response)
        response.pop('status')
        response.pop('datetime')
        if self._predev:
            response.pop(self._predev[1], None)
        if isinstance(self.choices, Bf_Dict_Choices):
            response = self.choices(response)
        return response

    def _setdev(self, val, clean=True):
        if isinstance(self.choices, Bf_Dict_Choices):
            val = self.choices.tostr(val)
        res = self.instr.write(self._topic+'/update', proto=self._proto, _ask=True, **val)
        if clean:
            res = self._doclean(res)
        self._set_delayed_cache = res

    def _getdev(self, clean=True, **kwargs):
        kwargs, kwargs2check, ch = self._doprev(kwargs, in_get=True)
        if self._readcache:
            if self.instr._mqtt_subscriptions[self._topic+'/listen'] != 'DONE':
                raise RuntimeError(self.perror('Caches are not subscribed properly'))
            ret = self.instr._mqtt_listen_buffers[self._readcache]
            if ch is not None:
                ret = ret[ch-1]
        else:
            ret = self.instr.ask(self._topic, proto=self._proto, **kwargs)
        if clean:
            # this does a copy
            ret = self._doclean(ret)
        else:
            # need to do a copy to prevent a user from changing our cache.
            # need deepcopy because some ret have dict inside of dict.
            ret = copy.deepcopy(ret)
        return ret

    def _checkdev(self, val, clean=True, **kwargs):
        if self._predev is not None:
            # need to remove predev for _checkdev (we already checked it.)
            # val will contain all other paramters
            val = val.copy()
            val.update(kwargs)
            val, kwargs2check, ch = self._doprev(val)
            self._check_cache['val'] = val
            self._check_cache['kw'] = val
            sk = dict(clean=clean)
            self._check_cache['kwarg'] = sk
            self._check_cache['set_kwarg'] = sk.copy()
            val = kwargs2check
        super(BlueforsDevice, self)._checkdev(val)

class EmptyChoice(ChoiceBase):
    def __init__(self, field_names=[]):
        self.field_names = field_names
        self.fmts_lims = [None] * len(field_names)

@register_instrument('BlueFors', 'Temperature Controller')
class bf_temperature_controller(BaseInstrument):
    _mqtt_connected = False
    def __init__(self, address, **kwargs):
        if not mqtt_loaded:
            raise RuntimeError('Cannot use bf_temperature_controller because of missing paho.mqtt package. Can be installed with "pip install paho-mqtt"')
        if not requests_loaded:
            raise RuntimeError('Cannot use bf_temperature_controller because of missing requests package. Can be installed with "pip install requests"')
        self._ip_address = address
        self._mqtt_subscriptions = {'channel/measurement/listen':'To do on connect',
                                    'heater/listen': 'To do on connect',
                                    'system/resources/listen':'To do on connect',
                                    'channel/listen':'To do on connect'}
        self._mqtt_listen_buffers = dict(meas=[None]*12, htrs=[None]*4, rsrcs=None, chs=[None]*12, last_junk=None)
        self._mqtt_hash_n = 0
        self._mqtt_sender = unicode('pyHegel_' + uuid.uuid4().hex)
        self._read_last_reply_buffer = queue.Queue(maxsize=1)
        self._read_last_meas_buffer = queue.Queue(maxsize=1)
        self._cals_map = None
        self._mqtt_connect_status = None
        self._mqtt_lock = threading.Lock()
        self._mqtt_subs_event = FastEvent()
        self._mqtt_unsubs_event = FastEvent()
        mqtt = paho.mqtt.client.Client()
        mqtt.on_message = ProxyMethod(self._mqtt_on_message)
        mqtt.on_connect = ProxyMethod(self._mqtt_on_connect)
        mqtt.on_subscribe = ProxyMethod(self._mqtt_on_subscribe)
        mqtt.on_unsubscribe = ProxyMethod(self._mqtt_on_unsubscribe)
        #mqtt.connect_async(address)
        # force a connect. If the server does not exist we will known now.
        mqtt.connect(address) # connect will finish when the loop is started.
        mqtt.loop_start()
        self._requests_session = requests.Session()
        self._websockets_cache = dict()
        self._mqtt_connected = True
        self._mqtt = mqtt
        super(bf_temperature_controller, self).__init__(**kwargs)

    def init(self, full=False):
        with self._mqtt_lock:
            data = self.ask('heaters', proto='get')
            for d in data['data']:
                ch = d['heater_nr']
                d[u'datetime'] = data['datetime']
                d[u'status'] = data['status']
                self._mqtt_listen_buffers['htrs'][ch-1] = d
            data = self.ask('channels', proto='get')
            for d in data['data']:
                d[u'datetime'] = data['datetime']
                d[u'status'] = data['status']
                ch = d['channel_nr']
                self._mqtt_listen_buffers['chs'][ch-1] = d
            #today = datetime.datetime.today()
            today = datetime.datetime.utcnow()
            # get about one 12 hrs worth of data.
            start = (today - datetime.timedelta(hours=12)).isoformat()
            end = (today + datetime.timedelta(seconds=5*60)).isoformat()
            for ch in range(1, 13):
                result = dict(angle=90., magnitude=0., channel_nr=ch, datetime=u'2020-01-01T00:00:00.0', imz=0., rez=0.,
                              temperature=None, resistance=0., reactance=0., settings_nr=1, status=u'OK',
                              status_flags=[], timestamp=1577836800.)
                data = self.get_history_temp(ch=ch, start=start, end=end, raw=True)
                for k, v in data['measurements'].items():
                    if len(v):
                        result[k] = v[-1]
                self._mqtt_listen_buffers['meas'][ch-1] = result
            self.current_ch.set(1)
            self._mqtt_listen_buffers['rsrcs'] = dict(cpu_total=0., disk_usage_data=0, disk_usage_log=0,
                                     memory_free=0, memory_used=0, rtc_battery=0., uptime=0, status=u'OK',
                                     datetime=u'2020-01-01T00:00:00.0')
        all_cals = self.ask('calibration-curves/data', proto='post')
        cals_map = {}
        for d in all_cals['data']:
            cals_map[d['calib_curve_nr']] = dict(serial = d['name'], model=d['sensor_model'])
        self._cals_map = cals_map
        super(bf_temperature_controller, self).init(full=full)

    # locked_calling to protect _mqtt_subscriptions
    def _mqtt_on_connect(self, client, userdata, flags, rc):
        if rc == 3:
            # Connection refused - server unavailable
            self._mqtt_connect_status = 'Connection refused - server unavailable'
            return
        elif rc != 0:
            # some other error
            self._mqtt_connect_status = 'Connection error: %i'%rc
            return
        # no error, everything is fine. Could be here upon a reconnect.
        with self._mqtt_lock:
            for k in self._mqtt_subscriptions:
                if self._mqtt_subscriptions[k] != 'del':
                    self.subscribe(k, _in_connect=True)
        self._mqtt_connect_status = 'Connected'

    def _empty_buffer(self, buf):
        # call with lock acquired
        while not buf.empty():
            buf.get()
    def _get_buffer(self, buf):
        ret = [None]
        def getit(timeout=0.):
            local_ret = ret
            if timeout==0.:
                func = buf.get_nowait
            else:
                func = lambda : buf.get(timeout=timeout)
            try:
                local_ret[0] = func()
                return True
            except queue.Empty:
                return False
        wait_on_event(getit)
        return ret[0]

    def _mqtt_on_message(self, client, userdata, message):
        topic = message.topic
        payload = json.loads(message.payload)
        if 'hash' in payload and 'sender' in payload:
            mid = unicode(self._mqtt_hash_n)
            if payload['hash'] != mid or payload['sender'] != self._mqtt_sender:
                return
            else:
                with self._mqtt_lock:
                    self._empty_buffer(self._read_last_reply_buffer)
                    self._read_last_reply_buffer.put(payload)
        elif topic == 'channel/measurement/listen':
            ch = payload['channel_nr']
            with self._mqtt_lock:
                self._mqtt_listen_buffers['meas'][ch-1] = payload
                self._empty_buffer(self._read_last_meas_buffer)
                self._read_last_meas_buffer.put(payload)
        elif topic == 'system/resources/listen':
            with self._mqtt_lock:
                self._mqtt_listen_buffers['rsrcs'] = payload
        elif topic == 'heater/listen':
            ch = payload['heater_nr']
            with self._mqtt_lock:
                self._mqtt_listen_buffers['htrs'][ch-1] = payload
        elif topic == 'channel/listen':
            ch = payload['channel_nr']
            with self._mqtt_lock:
                self._mqtt_listen_buffers['chs'][ch-1] = payload
        else:
            with self._mqtt_lock:
                self._mqtt_listen_buffers['last_junk'] = (topic, payload)


    def _mqtt_on_subscribe(self, client, userdata, mid, granted_qos):
        with self._mqtt_lock:
            for k, v in self._mqtt_subscriptions.items():
                if v == mid:
                    self._mqtt_subscriptions[k] = 'DONE'
                    self._mqtt_subs_event.set()

    def _mqtt_on_unsubscribe(self, client, userdata, mid):
        with self._mqtt_lock:
            for k, v in self._mqtt_subscriptions.items():
                if v == mid:
                    self._mqtt_subscriptions[k] = 'del'
                    self._mqtt_unsubs_event.set()

    @locked_calling
    def subscribe(self, topic, wait=True, _in_connect=False):
        """\
            subscribe to a topic.
            wait=True will wait for the acknowledgement.
            with wait=False, synchronisation between subscribe/unsubscribe and publish
             could be lost
        """
        # multiple subscribe will be removed by a single unsusbscribe to the topic.
        # but we protect against that anyway (it will be faster)
        if _in_connect:
            # already inside the lock
            result, mid = self._mqtt.subscribe(topic)
            self._mqtt_subscriptions[topic] = mid
            return
        pre_wait = False
        with self._mqtt_lock:
            if topic in self._mqtt_subscriptions:
                state = self._mqtt_subscriptions[topic]
                if state == 'DONE':
                    return
                elif wait:
                    # probably here after a reconnect or a use of subscribe without wait
                    # so we should wait
                    pre_wait = True
        if pre_wait:
            def check(timeout):
                if self._mqtt_subscriptions[topic] in ['DONE', 'del']:
                    return True
                else:
                    _wait(timeout)
                    return False
            wait_on_event(check)
            if self._mqtt_subscriptions[topic] == 'DONE':
                return
        with self._mqtt_lock:
            self._mqtt_subs_event.clear()
            result, mid = self._mqtt.subscribe(topic)
            if result != 0:
                raise RuntimeError('Unable to subscribe to "%s"'%topic)
            self._mqtt_subscriptions[topic] = mid
        if wait:
            wait_on_event(self._mqtt_subs_event)

    @locked_calling
    def unsubscribe(self, topic, wait=True):
        """\
            unsubscribe to a topic.
            wait=True will wait for the acknowledgement.
            with wait=False, synchronisation between subscribe/unsubscribe and publish
             could be lost
        """
        with self._mqtt_lock:
            # save some time
            if topic not in self._mqtt_subscriptions:
                return
            self._mqtt_unsubs_event.clear()
            result, mid = self._mqtt.unsubscribe(topic)
            if result != 0:
                raise RuntimeError('Unable to unsubscribe to "%s"'%topic)
            self._mqtt_subscriptions[topic] = mid
        if wait:
            wait_on_event(self._mqtt_subs_event)

    def publish(self, topic, payload=None, wait=False):
        """\
            publish a payload to a topic.
            wait=True will wait for the acknowledgement.
            with wait=False, synchronisation between subscribe/unsubscribe and publish
             could be lost
        """
        with self._mqtt_lock:
            ret = self._mqtt.publish(topic, json.dumps(payload))
        if wait:
            #TODO implement Event handling insteat of check with wait
            def check(timeout):
                if ret.is_published:
                    return True
                else:
                    _wait(timeout)
                    return False
            wait_on_event(check)
        return ret.mid

    def _websocket_helper(self, topic):
        ws = self._websockets_cache.get(topic, None)
        if ws is None:
            if not websocket_loaded:
                raise RuntimeError('Cannot use ws proto because of missing websocket package. Can be installed with "pip install websocket-client"')
            ws = websocket.create_connection('ws://%s:5002/%s'%(self._ip_address, topic), timeout=10)
            self._websockets_cache[topic] = ws
        return ws

    @locked_calling
    def ask(self, topic, unsub=True, proto='mqtt', **params):
        """ unsub when True, will unsubscribe after every call.
            probably nicer to the server, but will be slower
            proto can be get, post, mqtt, ws (for websocket)
        """
        if topic.endswith('/listen') and proto == 'ws':
            ws = self._websocket_helper(topic)
            ret = ws.recv()
            result = json.loads(ret)
            if result['status'] != 'OK':
                raise RuntimeError('Bad reply: %s'%result)
            return result
        else:
            return self.write(topic, unsub, proto, _ask=True, **params)

    @locked_calling
    def write(self, topic, unsub=True, proto='mqtt', _ask=False, **params):
        """ unsub when True, will unsubscribe after every call.
            probably nicer to the server, but will be slower
            proto can be get, post, mqtt, ws (for websocket)
        """
        if proto == 'mqtt':
            self.subscribe(topic+'/out')
            with self._mqtt_lock:
                params['sender'] = self._mqtt_sender
                self._mqtt_hash_n += 1
                params['hash'] = str(self._mqtt_hash_n)
                self._empty_buffer(self._read_last_reply_buffer)
            self.publish(topic+'/in', params)
            result = self._get_buffer(self._read_last_reply_buffer)
            if unsub:
                self.unsubscribe(topic+'/out')
            if result['status'] != 'OK':
                raise RuntimeError('Bad reply: %s'%result)
        elif proto in ['post', 'get']:
            getpost = self._requests_session.get if proto == 'get' else self._requests_session.post
            req = getpost('http://%s:5001/%s'%(self._ip_address, topic), timeout=10, json=params)
            if not req.ok:
                raise RuntimeError('Bad post/get request (status=%s, message="%s")'%(req.status_code, req.text))
            result = req.json()
        elif proto == 'ws':
            ws = self._websocket_helper(topic)
            ws.send(json.dumps(params))
            ret = ws.recv()
            result = json.loads(ret)
            if result['status'] != 'OK':
                raise RuntimeError('Bad reply: %s'%result)
        else:
            raise ValueError('Invalid proto option.')

        if _ask:
            return result

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        opts = []
        orig_ch = self.current_ch.get()
        for ch in range(1, 9):
            d = self.channel.get(ch=ch)
            d['calib_curve'] = self._cals_map[d['calib_curve_nr']]
            opts.append('ch%i=%r'%(ch, d))
        self.current_ch.set(orig_ch)
        orig_outch = self.current_outch.get()
        for outch in range(1, 5):
            opts.append('outch%i=%r'%(outch, self.heater.get(outch=outch)))
        self.current_outch.set(orig_outch)
        return opts+self._conf_helper('statemachine', options)
    def __del__(self):
        if self._mqtt_connected:
            self.disconnect()
        super(bf_temperature_controller, self).__del__()

    @locked_calling
    def disconnect(self):
        self._requests_session.close()
        self._mqtt.disconnect() # this sends the disconnect
        self._mqtt.loop_stop()  # this will wait for the thread to stop
        self._mqtt_connected = False
        for k, ws in self._websockets_cache.items():
            ws.close()
        self._websockets_cache = []

    def idn(self):
        data = self.ask('system')
        return "BlueFors,Temperature Controller,%s,%s"%(data['serial'], data['software_version'])

    @locked_calling
    def get_history_heater(self, start, end, outch=None, raw=False):
        """\
        Specifiy start/end as strings in the following format:
            YYYY-MM-DD
            YYYY-MM-DD HH:MM
            YYYY-MM-DD HH:MM:SS
            YYYY-MM-DDTHH:MM:SSZ
        if raw is True returns the raw reply from the temperature controller,
        otherwise returns an array of shape 3, n where the 3 columns are time, power, current
        """
        if outch is None:
            outch = self.current_outch.get()
        else:
            self.current_outch.set(outch)
        ret = self.ask('heater/historical-data', proto='post', heater_nr=outch, start_time=start, stop_time=end, fields=['power', 'current'])
        if ret['over_limit']:
            raise RuntimeError('Request was too large.')
        if raw:
            return ret
        else:
            meas = ret['measurements']
            data = np.array([meas['timestamp'], meas['power'], meas['current']])
            return data

    @locked_calling
    def get_history_temp(self, start, end, ch=None, raw=False, full=True):
        """\
        Specifiy start/end as strings in the following format:
            YYYY-MM-DD
            YYYY-MM-DD HH:MM
            YYYY-MM-DD HH:MM:SS
            YYYY-MM-DDTHH:MM:SSZ
        if raw is True returns the raw reply from the temperature controller,
        otherwise returns an array with columns: time, temperature, resistance, reactance, settings_nr
        With full, the raw version will also include rez, imz, magnitude, angle, settings_nr
        """
        if ch is None:
            ch = self.current_ch.get()
        else:
            self.current_ch.set(ch)
        if raw and full:
            # status_flags does not seem to be available (no error but no entry)
            fields = ['temperature', 'resistance', 'reactance', 'rez', 'imz', 'magnitude', 'angle', 'settings_nr']
        else:
            fields = ['temperature', 'resistance', 'reactance', 'settings_nr']
        ret = self.ask('channel/historical-data', proto='post', channel_nr=ch, start_time=start, stop_time=end, fields=fields)
        if ret['over_limit']:
            raise RuntimeError('Request was too large.')
        if raw:
            return ret
        else:
            meas = ret['measurements']
            data = np.array([meas['timestamp'], meas['temperature'], meas['resistance'], meas['reactance'], meas['settings_nr']])
            return data

    _calibration_types =  {-1:'Slot empty', 1:'RT curve', 2:'XT curve (8 Hz)', 3:'XT curve (64 Hz)'}
    _calibration_types_rev = {v:k for k, v in _calibration_types.items()}

    @locked_calling
    def get_calibration(self, curve_no, raw=False):
        """\
        if raw is True returns the raw reply from the temperature controller,
        otherwise returns and dictionary with the data array having the columns: impedances, temperatures
        """
        if curve_no<1 or curve_no>100:
            raise ValueError('curve_no needs to be from 1 to 100.')
        ret = self.ask('calibration-curve', proto='post', calib_curve_nr=curve_no)
        if raw:
            return ret
        else:
            types = self._calibration_types
            result = dict(name=ret['name'], sensor_model=ret['sensor_model'], type=types[ret['type']])
            data = np.array([ret['impedances'], ret['temperatures']])
            if len(data[0]) != len(data[1]) != ret['points']:
                raise RuntimeError('Read the wrong number of points.')
            result['data'] = data
            return result

    @locked_calling
    def set_calibration(self, curve_no, data, force=False):
        """\
        data is either a dictionnary in the same format has get_calibration (with keys name, sensor_model, type, data)
        a filename for a .340 calibration file or
        None which will delete the calibration.
        With force=False (default), an existing curve will not be overwritten.
        For the dictionnary, the data item has dims (2, n) where 2 are the impedances and temperatures
         and the impedances need to be in increasing order.
        """
        if curve_no<1 or curve_no>100:
            raise ValueError('curve_no needs to be from 1 to 100.')
        d = self.get_calibration(curve_no)
        if not force and d['type'] != 'Slot empty':
            raise RuntimeError('The calibration curve_no is already in use. You can use force=True to overwrite (BE CAREFUL)')
        if data is None:
            self.write('calibration-curve/remove', proto='post', calib_curve_nr=curve_no)
        elif isinstance(data, basestring):
            with open(data) as f:
                d = f.read()
            self.write('calibration-curve/file-upload', proto='post', calib_curve_nr=curve_no, file_contents=d)
        else:
            types = self._calibration_types_rev
            d = data['data']
            if d.ndim != 2:
                raise ValueError('Data should have 2 dimensions')
            if d.shape[0] != 2:
                raise ValueError('Data should have a shape of (2, n) with the columns containing impedances and temperatures')
            self.write('calibration-curve/update', proto='post', calib_curve_nr=curve_no,
                        name=data['name'],
                        sensor_model=data['sensor_model'],
                        points=d.shape[1],
                        impedances=list(d[0]),
                        temperatures=list(d[1]),
                        type=types[data['type']])

    def _enabled_chs_getdev(self):
        return [d['channel_nr'] for d in self._mqtt_listen_buffers['chs'] if d['active']]
    def _enabled_outchs_getdev(self):
        return [d['heater_nr'] for d in self._mqtt_listen_buffers['htrs'] if d['active'] and d['relay_mode']==d['relay_status']]

    def _outch_helper(self, outch=None):
        if outch is None:
            outch = self.current_outch.get()
        else:
            self.current_outch.set(outch)
        return outch

    def _heater_relation_getdev(self, outch=None):
        """ returns for heater outch, the temperature relation ch"""
        outch = self._outch_helper(outch)
        for i, d in enumerate(self._mqtt_listen_buffers['chs']):
            if d['coupled_heater_nr'] == outch:
                return i+1
        return 0
    def _heater_relation_checkdev(self, val, outch=None):
        outch = self._outch_helper(outch)
        if val<0 or val>12:
            raise ValueError(self.perror('the relation channel needs to be in 0-12 range.'))
    def _heater_relation_setdev(self, val, outch=None):
        """ sets for heater outch, the temperature relation ch. Make it 0 to disable the relation."""
        outch = self._outch_helper(outch)
        prev_ch = self._heater_relation_getdev(outch)
        self.write('channel/heater/update', proto='post', channel_nr=val, heater_nr=outch)
        # now force update of channels
        orig_ch = self.current_ch.get()
        if prev_ch != 0:
            self.channel.set(ch=prev_ch)
        if val != 0:
            self.channel.set(ch=val)
        self.current_ch.set(orig_ch)

    def _fetch_opt_helper(self, chs=None, outchs=None, temperature=True, resistance=True, reactance=True, settings=False, heater_power=False):
        if temperature or resistance or reactance or settings:
            if chs is None:
                chs = self.enabled_chs.getcache()
            if not isinstance(chs, (list, np.ndarray, tuple)):
                chs = [chs]
            for ch in chs:
                if ch>12 or ch<1:
                    raise ValueError(self.perror('Invalid chs in fetch (needs to be in range 1-12)'))
        else:
            chs = []
        if heater_power:
            if outchs is None:
                outchs = self.enabled_outchs.getcache()
            if not isinstance(outchs, (list, np.ndarray, tuple)):
                outchs = [outchs]
            for outch in outchs:
                if outch>4 or outch<1:
                    raise ValueError(self.perror('Invalid outchs in fetch (needs to be in range 1-4)'))
        else:
            outchs = []
        return chs, outchs

    def _fetch_getformat(self,  **kwarg):
        chs = kwarg.get('chs', None)
        outchs = kwarg.get('chs', None)
        temperature = kwarg.get('temperature', True)
        resistance = kwarg.get('resistance', True)
        reactance = kwarg.get('reactance', True)
        settings = kwarg.get('settings', False)
        heater_power = kwarg.get('heater_power', False)
        chs, outchs = self._fetch_opt_helper(chs, outchs, temperature, resistance, reactance, settings, heater_power)
        multi = []
        graph = []
        i = 0
        for ch in chs:
            if temperature:
                multi.append('ch%i_T'%ch)
                graph.append(i)
                i += 1
            if resistance:
                multi.append('ch%i_R'%ch)
                i += 1
            if reactance:
                multi.append('ch%i_X'%ch)
                i += 1
            if settings:
                multi.append('ch%i_Iexc'%ch)
                multi.append('ch%i_HR'%ch)
                i += 2
        for outch in outchs:
            if heater_power:
                # this should always be True after _fetch_opt_helper
                multi.append('outch%i_P'%outch)
                graph.append(i)
                i += 1
        fmt = self.fetch._format
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch, **kwarg)

    def _fetch_getdev(self, chs=None, outchs=None, temperature=True, resistance=True, reactance=True, settings=False, heater_power=False):
        """\
        chs is the list of temperature channels to read. When None it will default to all active channels.
        outchs is the list of heater outch to read (if heater_power is True). When None it will default to all powered
               up channels (active and active relay condition).
        temperature, resistance, reactance, settings, heater_power speicies what is shown for the selected channels.
        when settings is selected, it adds 2 columns: current_excitation, HR
          where HR will be 1 when in high resitance mode, otherwise it will be 0.
        """
        chs, outchs = self._fetch_opt_helper(chs, outchs, temperature, resistance, reactance, settings, heater_power)
        data = []
        def clean(data):
            return 0 if data is None else data
        for ch in chs:
            d = self._mqtt_listen_buffers['meas'][ch-1]
            if temperature:
                data.append(clean(d['temperature']))
            if resistance:
                data.append(clean(d['resistance']))
            if reactance:
                data.append(clean(d['reactance']))
            if settings:
                st = d['settings_nr']-1
                data.append(self._fetch_current_list[st])
                data.append(self._fetch_current_HR_list[st])
        for outch in outchs:
            d = self._mqtt_listen_buffers['htrs'][outch-1]
            if not d['active']:
                P = 0.
            elif d['relay_mode'] != d['relay_status']:
                P = 0.
            elif d['pid_mode'] == 0: #manual
                P = d['power']
            else:
                # This does not work. There is no way to read the power except to use the historical data right now.
                P = d['power']
            data.append(P)
        return data

    def _heater_pid_getdev(self, outch=None):
        """ on get returns the 3 values [P, I, D], on set accepts a dictionnary or keywords P, I and D. """
        ret = self.heater.get(outch=outch)
        pid = ret['control_algorithm_settings']
        return dict_improved([('P', pid['proportional']), ('I', pid['integral']), ('D', pid['derivative'])])
    def _heater_setcheck_helper(self, PID):
        for k in PID:
            if k not in ['P', 'I', 'D']:
                raise ValueError(self.perror('Invalid parameter for heater_pid. Only P, I or D accepted.'))
        d = {}
        mapping = {'P':'proportional', 'I':'integral', 'D':'derivative'}
        d = {mapping[k]:v for k,v in PID.items()}
        return {'control_algorithm_settings': d}
    def _heater_pid_checkdev(self, PID, outch=None):
        val = self._heater_setcheck_helper(PID)
        self.heater.check(val, outch=outch)
    def _heater_pid_setdev(self, PID, outch=None):
        val = self._heater_setcheck_helper(PID)
        self.heater.set(val, outch=outch)

    def _create_devs(self):
        self.current_ch = MemoryDevice(1, min=1, max=12)
        self.current_outch = MemoryDevice(1, min=1, max=4)
        self.statemachine = BlueforsDevice('statemachine', proto='post', choices=
                                           Bf_Dict_Choices(dict(wait_time=BfChoiceLimits(min=1, max=100), meas_time=BfChoiceLimits(min=5, max=100))))
        relay_mode_ch = BfChoiceIndex(['shorted', 'open'])
        relay_status_ch = BfChoiceIndex(['shorted', 'open'])
        self.relay = BlueforsDevice('heater/relay', proto='post', predev=('outch', 'heater_nr', self.current_outch), choices=
                                    Bf_Dict_Choices(dict(relay_mode=relay_mode_ch, relay_status=relay_status_ch), readonly_fields=['relay_status']))
        # The following 3 need to match
        self._fetch_current_list = [100e-12, 100e-12, 316e-12, 316e-12, 1e-9, 1e-9, 3.16e-9, 3.16e-9, 10e-9, 10e-9,
                                    31.6e-9, 31.6e-9, 100e-9, 100e-9, 316e-9, 316e-9, 1e-6, 1e-6,
                                    3.16e-6, 3.16e-6, 10e-6, 10e-6, 50e-6, 150e-6]
        self._fetch_current_HR_list = [0, 1] *10 + [0, 0]
        current_list = ['100pA LR', '100pA HR', '316pA LR', '316pA HR', '1nA LR', '1nA HR', '3.16nA LR', '3.16nA HR',
                                      '10nA LR', '10nA HR', '31.6nA LR', '31.6nA HR', '100nA LR', '100nA HR', '316nA LR', '316nA HR',
                                      '1uA LR', '1uA HR', '3.16uA LR', '3.16uA HR', '10uA LR', '10uA HR', '50uA 64Hz', '150uA 64Hz']
        all_settings = BfChoiceIndex(current_list + ['50uA 64Hz', '150uA 64Hz'], offset=1)
        self.measurement = BlueforsDevice('channel/measurement', readonly=True, readcache='meas', predev=('ch', 'channel_nr', self.current_ch), choices=
                                          Bf_Dict_Choices(dict(settings_nr=all_settings)))
        self.heater = BlueforsDevice('heater', proto='post', readcache='htrs', predev=('outch', 'heater_nr', self.current_outch), choices=
                                     Bf_Dict_Choices(dict(active=BfChoiceLimits(), control_algorithm=BfChoiceIndex(['default PID algorithm'], offset=1),
                                                          control_algorithm_settings=Bf_Dict_Choices(dict(proportional=BfChoiceLimits(min=0), integral=BfChoiceLimits(min=0), derivative=BfChoiceLimits(min=0))),
                                                          max_power=BfChoiceLimits(min=0), name=BfChoiceLimits(), power=BfChoiceLimits(min=0),
                                                          pid_mode=BfChoiceIndex(['manual', 'pid']), relay_mode=relay_mode_ch, relay_status=relay_status_ch,
                                                          resistance=BfChoiceLimits(min=0), setpoint=BfChoiceLimits(min=0),
                                                          target_temperature=BfChoiceLimits(min=0), target_temperature_shown=BfChoiceLimits()),
                                                     readonly_fields=['relay_status', 'relay_mode']),
                                     doc='options max_power, control_algorithm_settings only apply for pid mode. power is only for manual mode.')
        self.resources = BlueforsDevice('system/resources', readonly=True, readcache='rsrcs')
        self.channel =  BlueforsDevice('channel', proto='post', readcache='chs', predev=('ch', 'channel_nr', self.current_ch), choices=
                                       Bf_Dict_Choices(dict(active=BfChoiceLimits(), calib_curve_nr=BfChoiceLimits(min=1, max=100),
                                                            coupled_heater_nr=BfChoiceLimits(min=0, max=4),
                                                            excitation_mode=BfChoiceIndex(['current', 'Vmax', 'CMN']),
                                                            excitation_current_range=BfChoiceIndex(current_list, offset=1),
                                                            excitation_vmax_range=ChoiceSimpleMap({1:'20uV', 2:'200uV'}),
                                                            excitation_cmn_range=ChoiceSimpleMap({1:'50uA', 2:'150uA'}),
                                                            name=BfChoiceLimits(),
                                                            use_non_default_timeconstants=BfChoiceLimits(), wait_time=BfChoiceLimits(min=1), meas_time=BfChoiceLimits(min=5)),
                                                       readonly_fields=['coupled_heater_nr']))
        self.heater_manual_power = Dict_SubDevice(self.heater, 'power', force_default='slave')
        self.heater_en = Dict_SubDevice(self.heater, 'active', force_default='slave')
        self.heater_setpoint = Dict_SubDevice(self.heater, 'setpoint', force_default='slave')
        self.heater_max_power = Dict_SubDevice(self.heater, 'max_power', force_default='slave')
        self.channel_exc_mode = Dict_SubDevice(self.channel, 'excitation_mode', force_default='slave')
        self.channel_exc_vmax = Dict_SubDevice(self.channel, 'excitation_vmax_range', force_default='slave')
        self.channel_exc_current = Dict_SubDevice(self.channel, 'excitation_current_range', force_default='slave')
        self.channel_en = Dict_SubDevice(self.channel, 'active', force_default='slave')
        self._devwrap('enabled_chs')
        self._devwrap('enabled_outchs')
        self._devwrap('heater_relation')
        self._devwrap('heater_pid', multi=['P', 'I', 'D'], allow_kw_as_dict=True, choices=EmptyChoice( ['P', 'I', 'D']))
        self.heater_pid.type = self.heater_pid.choices # needed for Dict_SubDevice
        self.heater_P = Dict_SubDevice(self.heater_pid, 'P', force_default='slave')
        self.heater_I = Dict_SubDevice(self.heater_pid, 'I', force_default='slave')
        self.heater_D = Dict_SubDevice(self.heater_pid, 'D', force_default='slave')
        self._devwrap('fetch')
        self.alias = self.fetch
        # This needs to be last to complete creation
        super(bf_temperature_controller, self)._create_devs()

# Note that for firmware tc-0.12.1-20210217-181217
#   websocket, http get/post roundtrip is arounf 200 ms. For mqtt it is more like 400 ms for system/device
#   http get for channel/measurement/latest is 13 ms.

# Endpoints:
#   system
#   system/device
#   system/network system/network/update system/network/listen
#   system/reset/listen
#   system/resources/listen
#   statemachine statemachine/update statemachine/listen
#   channels
#   channel  channel/update  channel/listen
#   channel/historical-data
#   channel/measurement/listen
#   channel/heater/update
#   heaters
#   heater  heater/update  heater/listen
#   heater/relay  heater/relay/update  heater/relay/listen
#   heater/historical-data
#   calibration-curves  calibrationcurves/data/
#   calibration-curve calibrationcurve/update/ calibrationcurve/remove calibration-curve/fileupload


#######################################################
##    Bluefors controller
#######################################################

# possible protocols:
# - http get/post: are blocking but can reuse a socket.
#      I use the requests module which pools connections and keeps them open.
# - websocket: need to open multiple connections to the various endpoints, but keeps them open once used

# as of 2022-04-29 (Version 2.0)
#    notifications only works under get (not websocket read) contrary to what frontend API seems to imply

@register_instrument('BlueFors', 'Controller')
class bf_controller(BaseInstrument):
    _mqtt_connected = False
    def __init__(self, address='localhost', port=49099, timeout=3, secure=False, api_key=None, cert=True, **kwargs):
        """
        The api_key is required for https and secure websocket (wss), and not used for http/ws.
           The permissions will be the one for the api_key or the one from the unauthenicated API which ever
           is more permissive. Regular http/ws are allowed everything.
        secure, when True we use the https and wss protocols.
        The https, wss default port is 49098
        cert should be the certificate file (.pem) or directory to verify the connection for https and wss.
            It can be exported from the API configuration page.
            You will need to use one of the domain name or ip address configured in the certificate
            for it to be valid (see certutil on linux/cygwin).
            cert can also be set to False to disable the certification.
            When using a directory, it needs to be in a particular format. Use the linux c_rehash utility.
        """
        if not requests_loaded:
            raise RuntimeError('Cannot use bf_temperature_controller because of missing requests package. Can be installed with "pip install requests"')
        self._ip_address = address
        self._ip_port = port
        self._timeout = timeout
        self._api_key = api_key
        self._secure = secure
        self._requests_session = requests.Session()
        self._websocket_sslopt = dict()
        if cert is not True and cert is not False:
            # make it absolute (if not already) in case the current directory is changed
            cert = os.path.abspath(cert)
            if not os.path.exists(cert):
                raise ValueError('The certificate file does not exists: %s'%cert)
            if os.path.isfile(cert):
                self._websocket_sslopt['ca_certs'] = cert
            else:
                self._websocket_sslopt['ca_cert_path'] = cert
        if cert:
            self._websocket_sslopt['cert_reqs'] = ssl.CERT_REQUIRED
        else:
            self._websocket_sslopt['cert_reqs'] = ssl.CERT_NONE
        self._requests_session.verify = cert
        self._websockets_cache = dict()
        self._last_reply = None
        self._last_sent = None
        super(bf_controller, self).__init__(**kwargs)

    def __del__(self):
        self.disconnect()
        print 'Deleted bf_controller instance'
        super(bf_controller, self).__del__()

    @locked_calling
    def disconnect(self):
        self._requests_session.close()
        for k, ws in self._websockets_cache.items():
            ws.close()
        self._websockets_cache = []

    def _websocket_helper(self, path):
        ws = self._websockets_cache.get(path, None)
        if ws is None:
            if not websocket_loaded:
                raise RuntimeError('Cannot use ws proto because of missing websocket package. Can be installed with "pip install websocket-client"')
            if self._secure:
                url = 'wss://%s:%i/%s'%(self._ip_address, self._ip_port, path)
                if self._api_key is not None:
                    url += '?key=%s'%self._api_key
            else:
                url = 'ws://%s:%i/%s'%(self._ip_address, self._ip_port, path)
            ws = websocket.create_connection(url, timeout=self._timeout, sslopt=self._websocket_sslopt)
            self._websockets_cache[path] = ws
        return ws

    @locked_calling
    def ask(self, path, operation='get', endpoint='values', raw_return=False, raw_request=False, **params):
        """ see documentation for write
        """
        return self.write(path, operation, endpoint, raw_return=raw_return, raw_request=raw_request, _ask=True, **params)

    @locked_calling
    def write(self, path, operation='post', endpoint='values', raw_return=False, raw_request=False, _ask=False, set_val=None, **params):
        """ The path elements can be seperated by . or / and will be converted as needed.
            operation can be get, post (will use http protocol), or read, set, listen, unlisten, status
               (which will us the websocket protocol)
            endpoint can be 'system', 'values', 'resources', 'notifications' or None.
               When None, you should include the requested endpoint as part of the path.
               Not that resources can only be used with get (and the / and . are not changed because an example use
                is to ask for the layout.xml file as the path).
            raw_return when True will bypass returning a dictionnary for the json data and just return the string.
            raw_request when True, prevents the handling of the websocket request. You need to provide all the information
                properly.
            if set_val is given, the correct data dictionnary is built for 'post' and 'set'
            params are the paramters to pass add to the communication. command for ws is added from operation automatically.
              you might be interested in adding 'id' (string of hexadecimal numbers, _ and -) to track commands (only for websocket)
                   'prettyprint=1' to better format the json string (not useful since we turn the json data into a dictionnary),
                   'recursion' (-1 which is default means unlimited, only for get or read where default is 0),
                   'style'(which can be flat(default) or tree, only for get and read),
                   'must_exist' (if 1, not the default, check existence, only for post, set),
                   'wait_response' (if 1, which is the default, waits to make sure to return updated value, only post).
                   'all' is boolean for listen only. If True sends all update at the same time (not waiting for new values).
                   'recursive' if True (not default) listen to all nodes recursively. Also applies to unlisten to stop all child nodes.
            Examples:
              bc = instruments.bf_controller()
              bc.write('mapper.bf.heaters.hs-still', set_val=0)
              bc.ask('', operation='post', data={'mapper.bf.heaters.hs-still':dict(content=dict(value=False))})
              bc.ask('mapper.bf.heaters.hs-still')
              bc.ask('mapper.bf.heaters.hs-still', operation='get', endpoint='values', fields='value;status')
              bc.ask('layout.xml', endpoint='resources')
              bc.ask(None, endpoint='system')
              bc.ask(None, operation='read', endpoint='system')
        """
        if operation not in ['get', 'post', 'read', 'set', 'listen', 'unlisten', 'status']:
            raise ValueError(self.perror('Invalid operation selected.'))
        if endpoint not in ['system', 'values', 'resources', 'notifications', None]:
            raise ValueError(self.perror('Invalid endpoint selected.'))
        if endpoint == 'resources' and operation !='get':
            raise ValueError(self.perror('You can only select get operation with resources endpoint.'))
        if operation in ['post', 'get']:
            if path is None:
                path = ''
            if endpoint != 'resources' and not raw_request:
                data_path = path.replace('/', '.')
                if operation == 'post':
                    path = ''
                else:
                    path = path.replace('.', '/')
            if endpoint is not None:
                path = '%s/%s'%(endpoint, path)
            data = params.pop('data', {})
            if operation == 'post' and set_val is not None:
                data[data_path] = dict(content=dict(value=set_val))
            if self._api_key is not None:
                params['key'] = self._api_key
            get_proto = lambda url, params={}, json={}: self._requests_session.get(url, timeout=self._timeout, params=params)
            getpost = get_proto if operation == 'get' else self._requests_session.post
            if self._secure:
                http_url = 'https://'
            else:
                http_url = 'http://'
            req = getpost(http_url+'%s:%i/%s'%(self._ip_address, self._ip_port, path), params=params, json=dict(data=data))
            self._last_reply = req
            if not req.ok:
                raise RuntimeError('Bad post/get request (status=%s, message="%s")'%(req.status_code, req.text))
            if raw_return or endpoint == 'resources':
                result = req.text
            else:
                result = req.json()
                if 'error' in result:
                    raise RuntimeError('Error in post/get request (result=%s)'%(result))
        else: # websocket
            if endpoint is None:
                endpoint = path
                path = None
            else:
                # without the ending '/' we get a "scheme http is invalid" ValueError exception
                endpoint = 'ws/'+endpoint+'/'
            if not raw_request:
                js_params = {}
                js_params['command'] = operation
                cmd_id = params.pop('id', None)
                if cmd_id is not None:
                    js_params['id'] = cmd_id
                data = params.pop('data', {})
                js_params['data'] = data
                if path is not None:
                    path = path.replace('/', '.')
                    if operation == 'set' and set_val is not None:
                        data['data'] = {path: dict(content=dict(value=set_val))}
                    else:
                        data['target'] = path
                data.update(params)
            else:
                js_params = params
            ws = self._websocket_helper(endpoint)
            req = json.dumps(js_params)
            self._last_sent = req
            ws.send(req)
            ret = ws.recv()
            self._last_reply = ret
            result1 = json.loads(ret)
            if result1['status'] != 'RECEIVED':
                raise RuntimeError('Bad reply: %s'%result1)
            ret2 = ws.recv()
            result2 = json.loads(ret2)
            if result2['status'] != 'SUCCEEDED':
                raise RuntimeError('Bad reply: %s'%result2)
            if raw_return:
                result = ret2
            else:
                result = result2
        if _ask:
            return result

    def list_all_mappers(self, path='mapper',  show_read_only=False, show_type=False, operation='get', endpoint='values', exclude=['mapper.bflegacy', 'driver.bftc.data.calibration_curves.calibration_curve_']):
        """ show_read_only when True, will return a tuple with the second element the read only value of the variables if present
                            when the value is not present, it returns False
            show_type  when True, will add the type information to the tuple.
        """
        ret = self.ask(path, operation, endpoint)
        def check(key):
            for ex in exclude:
                if key.startswith(ex):
                    return False
            return True
        data = ret['data']
        if show_read_only or show_type:
            def gen_result(key, val):
                ret = (key, )
                if show_read_only:
                    cnt = val.get('content', None)
                    if cnt is not None:
                        ret += (cnt.get('read_only', False),)
                    else:
                        ret += (False, )
                if show_type:
                    ret += (val.get('type', 'NoTypeSpecified'),)
                return ret
        else:
            gen_result = lambda key, val: key
        result = [ gen_result(key, val) for key, val in data.items() if check(key)]
        return sorted(result)

    def get_value(self, path, operation='post', endpoint='values', valid=True, raw_val=False, **params):
        """
          valid when True (default) returns the value in latest_valid_value, if False returns the
                value in latest_value
          raw_val when True, skips converting the value according to the type
        """
        js = self.ask(path, operation=operation, endpoint=endpoint, **params)
        latest = 'latest_valid_value' if valid else 'latest_value'
        base = js['data'][path]
        val = base['content'][latest]['value']
        tp = base['type']
        if not raw_val:
            if tp in ['Value.Number.Integer.Enumeration.yesNo', 'Value.Number.Integer.Enumeration.Boolean']:
                val = bool(int(val))
            elif tp.startswith('Value.Number.Float'):
                val = float(val)
            elif tp.startswith('Value.Number.Integer'):
                val = int(val)
        return val

