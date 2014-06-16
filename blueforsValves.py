# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

import socket
import threading
import time
import weakref

from instruments_base import BaseInstrument, MemoryDevice,\
                             dict_improved, locked_calling


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

bluefors_serial = {'0158748E':'BF0312-03',
                   '015572FC':'BF0312-02'}
def get_bluefors_sn():
    lst = get_all_usb() # defined below
    for v,p,s in lst:
        if v == 0x3923 and p == 0x717a:
            return bluefors_serial.get(s, 'Unknown serial #')
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
        if err == None:
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
