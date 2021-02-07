# -*- coding: utf-8 -*-
#####################################################################
# Copyright 2019  Christian Lupien <christian.lupien@usherbrooke.ca>
#
# This code allows communications with a National Instruments
# DataSocket server.
#####################################################################


from __future__ import division, print_function

import numpy as np
import struct
import socket
import datetime
import time
import collections
import threading
import weakref
import sys
import pytz
import calendar # for timegm (the inverse of time.gmtime)
import six
if six.PY2:
    import Queue as queue
else:
    import queue

class ProxyMethod(object):
    def __init__(self, bound_method):
        #self.class_of_method = bound_method.im_class
        self.instance = weakref.proxy(bound_method.__self__)
        self.unbound_func = bound_method.__func__
    def __call__(self, *arg, **kwarg):
        return self.unbound_func(self.instance, *arg, **kwarg)


# This is based on code from https://github.com/coruus/pythonlabtools
#   files: nati_dstp_basics.py, dstp.py and dstp_async.py

def pack_bytes(byte_list):
    try:
        return np.asarray(byte_list,dtype='uint8').tobytes()
    except AttributeError:
        # For older python versions
        return np.asarray(byte_list,dtype='uint8').tostring()

array_type = pack_bytes([0, 8])
composite_type = pack_bytes([1, 8])
ulongint_type = pack_bytes([1, 3])
longint_type = pack_bytes([0, 3])
ushortint_type = pack_bytes([1, 2])
shortint_type = pack_bytes([0, 2])
ubyte_type = pack_bytes([1, 1])
byte_type = pack_bytes([0, 1])
string_type = pack_bytes([0, 9])
double_type = pack_bytes([2, 4])
float_type = pack_bytes([2, 3])
boolean_type = pack_bytes([2, 1])
timestamp_type = pack_bytes([4, 5])
attribute_data_type = pack_bytes([2, 0x40])
attribute_name_type = pack_bytes([3, 0x40])
int64_type = pack_bytes([0, 4])
uint64_type = pack_bytes([1, 4])
complex_type = pack_bytes([1, 5]) # double

class BasePackType(object):
    base_type = None
    def __init__(self, val):
        self.val = val
    def __repr__(self):
        return '%s(%s)'%(self.__class__.__name__, self.val)
    def __eq__(self, other):
        return self.val == other.val

class ULong(BasePackType):
    base_type = ulongint_type

class Short(BasePackType):
    base_type = shortint_type

class UShort(BasePackType):
    base_type = ushortint_type

class Byte(BasePackType):
    base_type = byte_type

class UByte(BasePackType):
    base_type = ubyte_type

class Float(BasePackType):
    base_type = float_type

class Int64(BasePackType):
    base_type = int64_type

class UInt64(BasePackType):
    base_type = int64_type

class TimeStamp(BasePackType):
    base_type = timestamp_type
    def __init__(self, frac, sec):
        self.sec = sec
        self.frac = frac
    @property
    def val(self):
        return self.frac, self.sec
    def __repr__(self):
        return '%s(%s, %s)'%(self.__class__.__name__, self.sec, self.frac)
    def to_str(self):
        return timestamp_to_str(self)
    def to_unix(self):
        return timestamp_to_unix(self)

def get_type(data_type, data_str, no_class=False):
    """ returns a tuple (converted data, next_string_index) """
    fmt = object_format[data_type]
    if fmt is None:
        raise ValueError('This type is not handled')
    L = fmt[0]
    data = struct.unpack(fmt[1], data_str[:L])
    if L%2:
        L+=1
    if data_type == complex_type:
        data = complex(data[0], data[1])
    elif data_type == timestamp_type:
        data = TimeStamp(*data)
    elif fmt[3] is not None and not no_class:
        data = fmt[3](data[0])
    else:
        data = data[0]
    return data, L

_bool_conv = {True: -1, False: 0}

def put_type(data_type, data):
    """ returns the data_str """
    fmt = object_format[data_type]
    if fmt is None:
        raise ValueError('This type is not handled')
    L = fmt[0]
    if data_type == boolean_type:
        data = _bool_conv[data]
    if isinstance(data, complex):
        data = (data.real, data.imag)
    if not isinstance(data, tuple):
        data = (data,)
    data_str = struct.pack(fmt[1], *data)
    if len(data_str)%2:
        data_str += b'\x00'
    return data_str

def get_str(data_str):
    """ returns a tuple (string, next_index) """
    N, i = get_type(ulongint_type, data_str, no_class=True)
    data = data_str[i:i+N]
    i += N + N%2 # need to pad to even
    if len(data_str) < i:
        raise RuntimeError('The string entry is too short.')
    return make_str(data), i

def put_str(data):
    """ returns the data_str """
    data = make_byte(data)
    N = len(data)
    data_str = put_type(ulongint_type, len(data)) + data
    if N%2:
        data_str += b'\000'
    return data_str

def get_array(data_type, data_str, ndim=1):
    # Technically the type could be anything, including a cluster.
    # we don't handle all of them.
    shape = []
    ioff = 0
    for j in range(ndim):
        N, i = get_type(ulongint_type, data_str[ioff:], no_class=True)
        ioff += i
        shape += [N]
    N = 1
    for n in shape:
        N *= n
    if data_type == string_type:
        data = []
        for i in range(N):
            d, i = get_str(data_str[ioff:])
            ioff += i
            data.append(d)
        data = np.array(data)
    else:
        fmt = object_format[data_type]
        if fmt is None:
            raise ValueError('This type is not handled')
        L = N * fmt[0]
        data = np.frombuffer(data_str[ioff:ioff+L], dtype=fmt[2])
        ioff += L
        if ioff%2:
            ioff += 1
    data.shape = shape
    # Note that timestamp will be '|'
    if data.dtype.byteorder not in ['=', '|']: # not native
        data = data.byteswap().newbyteorder()
    return data, ioff

def put_array(data_type, data):
    # Technically the type could be anything, including a cluster.
    # we don't handle all of them.
    if data_type == string_type:
        data_str = b''
        for s in data.flat:
            data_str += put_str(s)
    else:
        fmt = object_format[data_type]
        if fmt is None:
            raise ValueError('This type is not handled')
        if data_type == boolean_type:
            data2 = np.asarray(data, dtype='u1')
            data2[data] = 0xff
            data = data2
        else:
            data = np.asarray(data, dtype=fmt[2])
        data_str = data.tostring()
    if len(data_str)%2:
        data_str += b'\000'
    hdr_string = b''
    for i in data.shape:
        hdr_string += put_type(ulongint_type, i)
    return hdr_string + data_str

def put_attr(key, data):
    # structure is
    #   0x02 0x04 size
    #             0x03 0x40 size
    #                        0x09 string(including it size)
    #             type data
    #
    hdr_sub, data_str_sub = pack_one(data)
    hdr_sub = hdr_sub[4:] # skip the first length field
    hdr_k, data_k = pack_one(key) # k is label
    hdr_k = hdr_k[4:] # skip the first length field
    hdr_full = attribute_name_type + add_length(hdr_k + data_k) + hdr_sub + data_str_sub
    return attribute_data_type + add_length(hdr_full)

def get_attr(data_str):
    # here the string should point after the 0x02 0x04 object
    obj_type, attr_name_str_block, data_str = get_typeobj(data_str)
    if obj_type != attribute_name_type:
        raise RuntimeError('Unexpected format for attribute')
    obj_type, attr_name_string, extra_str = get_typeobj(attr_name_str_block)
    key, i = get_str(attr_name_string)
    if i != len(attr_name_string):
        raise RuntimeError('The is a leftover in attr_name_string')
    extra_str, toread, attrs = do_one_unpack(extra_str)
    if attrs:
        raise RuntimeError('attribute should not contain attributes')
    value = do_read_unpack(toread, extra_str)
    return key, value, data_str

def timestamp_to_str(ts):
    """ return timestamp as localtime string """
    #dt = timestamp_to_datetime(ts)
    #return dt.ctime()
    return time.ctime(timestamp_to_unix(ts))

def timestamp_to_unix(ts):
    """ timestamp is time since Labview epoch which is
        1904-01-01 00:00:00 UTC
        convert it to seconds since unix epoch
        1970-01-01 00:00:00 UTC
    """
    frac = ts.frac/2.**64
    dt = labview_epoch + datetime.timedelta(0, ts.sec)
    dt = timestamp_to_datetime(ts)
    return calendar.timegm(dt.timetuple()) + frac

labview_epoch = datetime.datetime(1904, 1, 1, 0,0,0, tzinfo=pytz.utc)

def timestamp_to_datetime(ts):
    """ timestamp is time since Labview epoch which is
        1904-01-01 00:00:00 UTC
        convert it to python datetime structure (with no timezone info)
    """
    dt = labview_epoch + datetime.timedelta(0, ts.sec+ts.frac/2.**64)
    return dt

timestamp_dtype = np.dtype([('frac', '<u8'), ('sec', '<i8')])

object_format = {
    longint_type: (4, "<l", "<i4", None),
    ulongint_type: (4, "<L", "<u4", ULong),
    ushortint_type: (2, "<H", "<u2", UShort),
    shortint_type: (2, "<h", "<i2", Short),
    int64_type: (8, "<q", "<i8", Int64),
    uint64_type: (8, "<Q", "<u8", UInt64),
    ubyte_type: (1, "<B", "<B", UByte),
    byte_type: (1, "<b", "<b", None),
    double_type: (8, "<d", "<f8", None),
    float_type: (4, "<f", "<f4", Float),
    complex_type: (16, "<dd", "<c16", None),
    string_type:  None,
    array_type: None,
    boolean_type: (1, "<b", "bool", None),
    # https://www.ni.com/en-ca/support/documentation/supplemental/08/labview-timestamp-overview.html
    # shows data as i64, u64 (sec, frac) but talks about most and least significant.
    # It actually seems to be the other way around
    #  u64, i64 (frac, sec)
    timestamp_type: (16, "<Qq", timestamp_dtype, TimeStamp),
    attribute_data_type: None,
    attribute_name_type: None
}

object_packing = {
    np.dtype('i4'): longint_type,
    np.dtype('u4'): ulongint_type,
    np.dtype('i2'): shortint_type,
    np.dtype('u2'): ushortint_type,
    np.dtype('i8'): int64_type,
    np.dtype('u8'): uint64_type,
    np.dtype('c16'): complex_type,
    np.dtype('b'): byte_type,
    np.dtype('B'): ubyte_type,
    np.dtype('f8'): double_type,
    np.dtype('f4'): float_type,
    np.dtype('bool'): boolean_type,
    timestamp_dtype: timestamp_type,
    type(1): longint_type,
#    type(1L): longint_type,
    type(True): boolean_type,
    type(1.): double_type,
    type(1j): complex_type,
    type([]): composite_type,
    type(()): composite_type,
    type(b''): string_type,
    type(u''): string_type,
    type({}): attribute_data_type,
    collections.OrderedDict: attribute_data_type
}

if six.PY2:
    # this does for python2 only the line in object_packing that is commented.:
    # type(1L): longint_type
    object_packing[long] = longint_type

class DataAttr(object):
    def __init__(self, data, attrs):
        self.data = data
        self.attrs = attrs


def add_length(data_str):
    return put_type(ulongint_type, len(data_str)+4) + data_str

def pack_one(data):
    """ Data can be one of the Python base objects (which will be converted to
              int32, string, boolean, double)
        some of the numpy arrays (including dtupe timestamp_dtype
        and object from classes: Int64, UInt64, ULong, Short, UShort, Byte, Float, TimeStamp
    """
    if isinstance(data, BasePackType):
        obj_type = data.base_type
        hdr = add_length(obj_type)
        data_str = put_type(obj_type, data.val)
    elif isinstance(data, np.ndarray):
        if data.dtype.kind in ['S', 'U']:
            obj_type = string_type
        else:
            obj_type = object_packing[data.dtype]
        hdr = add_length(array_type + put_type(ushortint_type, data.ndim) + add_length(obj_type))
        data_str = put_array(obj_type, data)
    elif isinstance(data, DataAttr):
        hdr_a, data_str_a = pack_one(data.attrs)
        hdr_d, data_str_d = pack_one(data.data)
        hdr = hdr_a + hdr_d[4:] # need to skip data hdr length value
        hdr = add_length(hdr)
        data_str = data_str_a + data_str_d
    else:
        obj_type = object_packing[type(data)]
        if obj_type == composite_type:
            N = len(data)
            hdr = composite_type + put_type(ushortint_type, N)
            data_str = b''
            for d in data:
                hdr_sub, data_str_sub = pack_one(d)
                hdr += hdr_sub
                data_str += data_str_sub
            hdr = add_length(hdr)
        elif obj_type == string_type:
            hdr = add_length(obj_type)
            data_str = put_str(data)
        elif obj_type == attribute_data_type:
            hdr = b''
            data_str = b''
            for k, d in data.items():
                hdr += put_attr(k, d)
        else:
            hdr = add_length(obj_type)
            data_str = put_type(obj_type, data)
    return hdr, data_str


def do_pack(data):
     """ This creates the complete packet of data, ready to be sent to the server """
     hdr, data_str = pack_one(data)
     # we need to skip the first length and recalculate it
     out_str = hdr[4:] + data_str
     return add_length(out_str)

def get_length(data_str, check=False):
    data, i = get_type(ulongint_type, data_str, no_class=True)
    return data

def skip_length(data_str, check=False):
    data = get_length(data_str)
    if check:
        if data != len(data_str):
            raise RuntimeError('Data length is the wrong size')
    return data_str[4: data], data_str[data:]

def get_typeobj(data_str, check=False):
    data, data_str = skip_length(data_str, check=check)
    obj_type = data[:2]
    type_str = data[2:]
    return obj_type, type_str, data_str

def do_one_unpack(data_str):
    # data_str should point at the type_str
    obj_type = data_str[:2]
    data_str = data_str[2:]
    attrs = collections.OrderedDict()
    if obj_type == array_type:
        ndim, i = get_type(ushortint_type, data_str, no_class=True)
        subtype, type_str, data_str = get_typeobj(data_str[i:])
        if len(type_str) != 0:
            raise RuntimeError('Type description is too long. It is not handled yet.')
        toread = [(get_array, dict(data_type=subtype, ndim=ndim))]
    elif obj_type == composite_type:
        islist = True
        N, i = get_type(ushortint_type, data_str, no_class=True)
        data_str = data_str[i:]
        toread = []
        toread.append(('start_list', None))
        for j in range(N):
            type_str, data_str = skip_length(data_str)
            ntypes = 0
            while len(type_str):
                type_str, tr, attr = do_one_unpack(type_str)
                if tr:
                    ntypes += 1
                if tr and attr:
                    raise RuntimeError('Expecting either attr or type.')
                if ntypes > 1 or (ntypes and len(type_str)):
                    raise RuntimeError('Expecting only one type and at the end.')
                toread += tr
                attrs.update(attr)
        toread.append(('end_list', None))
    elif obj_type == string_type:
        toread = [(get_str, dict())]
    elif obj_type == attribute_data_type:
        key, value, data_str = get_attr(data_str)
        attrs[key] = value
        toread = []
    else:
        toread = [(get_type, dict(data_type=obj_type))]
    return data_str, toread, attrs


def do_read_unpack(toread, data_str):
    # containers and 'start_list', 'end_list' are to allow simple
    # data (no lists) or list of lists (clusters of clusters)
    containers = [[]]
    current = containers[-1]
    for f, kwargs in toread:
        if f in ['start_list', 'end_list']:
            if f == 'start_list':
                containers.append([])
            elif f == 'end_list':
                last = containers.pop()
                containers[-1].append(last)
            current = containers[-1]
            continue
        kwargs['data_str'] = data_str
        d, i = f(**kwargs)
        if len(data_str) < i:
            raise RuntimeError('Missing data')
        data_str = data_str[i:]
        current.append(d)
    if len(data_str) != 0:
        raise RuntimeError('There is a leftover in unpack')
    return containers[0][0]

def do_unpack(data_str, timestamp=True):
    type_str, data_str = skip_length(data_str, check=True)
    # data_str should be empty here.
    data_str, toread, attrs = do_one_unpack(type_str)
    if timestamp:
        return do_read_unpack(toread, data_str), attrs, time.time()
    else:
        return do_read_unpack(toread, data_str), attrs

NI_encoding = 'latin1'
#NI_encoding = 'UTF8'
def make_byte(s):
    if six.PY3:
        if isinstance(s, bytes):
            return s
        return s.encode(NI_encoding)
    else:
        if isinstance(s, unicode):
            return s.encode(NI_encoding)
    return s

def make_str(s):
    if six.PY3:
        return s.decode(NI_encoding)
    else:
        return s

class DataNotPresent(RuntimeError):
    pass

class Dstp_Client(object):
    def __init__(self, address, variable_path, max_buf_entries=100, quiet_del=False):
        """ variable_path will be the default variable to open/close with
            the proto_open_var, proto_close_var, proto_write vars
            It is not open at object creation.
        """
        self._quiet_del = quiet_del
        self.address = address
        self.variable_path = variable_path
        self._is_variable_open = False
        self._connect_done = False
        self.s = None
        self.s = socket.create_connection((address, 3015), 1.)
        self._internal_seq = 1
        self._thread = None
        self.proto_connect()
        self._read_buffer = queue.Queue(max_buf_entries)
        self._read_replies_buffer = queue.Queue()
        self._read_ack = [0]
        self._read_lasttime = [0.]
        self._max_buf_entries = max_buf_entries
        self._thread_stop = [False]
        self._thread = threading.Thread(target=ProxyMethod(self._threaded_target))
        self._thread.daemon = True
        self._thread.start()

    def empty_replies(self):
        """ This empties the replies buffer and returns all the entries that were found.
            Call this after an error to resynchronnize replies for the next command.
        """
        data = []
        while True:
            try:
                data.append(self._read_replies_buffer.get_nowait())
                self._read_replies_buffer.task_done()
            except queue.Empty:
                break
        return data

    def get_next_reply(self, timeout=1.):
        data = self._read_replies_buffer.get(True, timeout)
        self._read_replies_buffer.task_done()
        return data

    def get_next_data(self, timeout=1.):
        """ return the last next available data waiting timeout (can be 0)
            if nothing is available, returns None
            Otherwise returns: varname, data, attributes, timestamp
            The timestamp is the time the reading was performed.
        """
        if not self._is_variable_open:
            raise RuntimeError('You need to open a variable first. see proto_open_var')
        try:
            if timeout == 0.:
                data = self._read_buffer.get_nowait()
            else:
                data = self._read_buffer.get(True, timeout)
        except queue.Empty:
            data = None
        else:
            self._read_buffer.task_done()
            d, attrs, ts = data
            if len(data) != 3:
                raise RuntimeError('Unexpected data length')
            data = d[1], d[2], attrs, ts
        return data

    def _threaded_target(self):
        read_buffer = self._read_buffer
        read_replies_buffer = self._read_replies_buffer
        thread_stop = self._thread_stop
        read_parse = ProxyMethod(self.read_parse)
        get_next_data = ProxyMethod(self.get_next_data)
        read_ack = self._read_ack
        read_lasttime = self._read_lasttime
        quiet_del = self._quiet_del
        while not thread_stop[0]:
            try:
                data = read_parse()
                d, attrs, ts = data
            except socket.timeout:
                if six.PY2:
                    sys.exc_clear()
                continue
            except Exception as exc:
                if not quiet_del:
                    print('Dstp_Client reading thread termination: %s'%exc)
                break
            if d[0] == 10:
                # received every 11 seconds ...
                read_ack[0] += 1
            elif d[0] == 6:
                # This is new data
                if read_buffer.full():
                    get_next_data(0.)
                read_buffer.put(data)
            else:
                read_replies_buffer.put(data)
            read_lasttime[0] = time.time()
        if not quiet_del:
            print('Thread stopped.')

    def __del__(self):
        if not self._quiet_del:
            print('deleting DataSocket (closing socket)')
        try:
            self.close()
        except Exception as e:
            print('Error during del', e)

    def is_connection_ok(self):
        if not self._thread.isAlive():
            return False
        if time.time() - self._read_lasttime[0] > 60:
            # we should be receiving keepalive packets. If not, the other computer is probably down
            return False
        return True

    def close(self, quiet=False):
        if self.s is None:
            return
        try:
            # if we get an error during close (send fail) then shutdown will proabably fail too so just chain them in one try/except.
            self.proto_close()
            self.s.shutdown(socket.SHUT_RDWR)
        except socket.error as exc:
            if not quiet:
                print('Error while closing proto: %s'%exc)
        self.s.close()
        self.s = None

    def proto_connect(self):
        data_str = do_pack([1, 3]) # the 3 might be a protocol version?
        self.s.sendall(data_str)
        data_str = do_pack([2, 3])
        self.s.sendall(data_str)
        data, attrs, ts = self.read_parse()
        self._connect_done = True
        if data != [9, 3]:
            raise RuntimeError('Connection did not get acknowledged.')

    def proto_open_var(self, var=None, mode="read"):
        """
        mode is one of "read", "write", "bufread", "readwrite", "bufreadwrite"
        You can open multiple var (by specifying it)
         However, the NI datasocket diagnostic program does not behave properly
         with the extra ones (does not add entries for subscriptions...)
        You should close the var before closing the connection.
        Note that only one person is allowed to have write access at a time.
        raise DataNotPresent when the variable is not present and we do not have
           the permission to create it.
        """
        if var is None:
            var = self.variable_path
        var = make_byte(var)
        var_s = make_str(var)
        modes = {"read":3, "write":4, "bufread":11, "readwrite":7, "bufreadwrite":15}
        m = modes[mode]
        data_str = do_pack([4, var, m])
        self.s.sendall(data_str)
        data, attrs, ts = self.get_next_reply()
        if data == [56, var_s] or data == [51, var_s]:
            rootmsg ='Unable to write (somebody else is writing to it?).'
            if data[0] == 51:
                rootmsg = 'Unable to write (we do not have permission to write).'
            if 'read' in mode:
                data, attrs, ts = self.get_next_reply()
                if data != [12, var_s, m]:
                    raise RuntimeError(rootmsg + ' Also reading not enabled (%s).'%data)
                self._is_variable_open = True
                raise RuntimeError(rootmsg + ' However reading is working.')
            else: # write only
                raise RuntimeError(rootmsg)
        elif data == [52, var_s]:
            if 'write' in mode:
                data, attrs, ts = self.get_next_reply()
                if data != [12, var_s, m]:
                    raise RuntimeError('Unable to read (we do not have permission to read). Writing also not permitted (%s).'%data)
                raise RuntimeError('Unable to read (we do not have permission to read). Writing is enabled.')
            else: # pure read
                raise RuntimeError('Unable to read (we do not have permission to read).')
        elif data == [50, var_s]:
            raise DataNotPresent('Unable to access (variable does not exist and we do not have the right to create it).')
        elif data != [12, var_s, m]:
            raise RuntimeError('Unexpected answer to open_var')
        self._is_variable_open = True

    def proto_close_var(self, var=None):
        if var is None:
            var = self.variable_path
        var = make_byte(var)
        data_str = do_pack([5, var])
        self.s.sendall(data_str)

    def proto_close(self):
        if not self._connect_done:
            return
        if self._thread:
            self._thread_stop[0] = True
            if threading.current_thread() != self._thread:
                self._thread.join()
        data_str = do_pack([3])
        self.s.sendall(data_str)
        self._connect_done = False

    def proto_write(self, data, attributes={}, var=None):
        """
        attributes is a dictionnary (key, value pairs)
        The order is kept here (better use Ordereddict then dict)
        and in the datasocket server, but labview reorders them.
        You can change data, type and attributes of a variable at any write
         (However the program that reads it might not be happy about that).
        """
        # there seems to be an initial write of 0 for the data and sequence of 1.
        if var is None:
            var = self.variable_path
        var = make_byte(var)
        var_s = make_str(var)
        if not isinstance(attributes, dict):
            raise ValueError('attributes needs to be a dictionnary.')
        if not isinstance(data, list):
            data_l = [data]
        else:
            data_l = data
        if any(isinstance(i, dict) for i in data_l):
            raise ValueError('data cannot contain a dictionnary. Use the attributes instead.')
        if attributes:
            data = DataAttr(data, attributes)
        seq = ULong(self._internal_seq)
        data_str = do_pack([13, var, data, seq])
        self.s.sendall(data_str)
        self._internal_seq += 1
        data, attrs, ts = self.get_next_reply()
        no_permission = False
        if data == [51, var_s]:
            no_permission = True
            data, attrs, ts = self.get_next_reply()
        if data != [14, seq, 1]:
            if data == [14, seq, 0] and no_permission:
                raise RuntimeError("Failed to write. Probably don't have the permission.")
            else:
                raise RuntimeError('Unexpected answer to write')

    def _read_n(self, n):
        """ read n bytes """
        data_str = b''
        while len(data_str) < n:
            try:
                new_s = self.s.recv(n - len(data_str))
            except socket.error as exc:
                if exc.errno == socket.EINTR:
                    continue
                raise
            if len(new_s) == 0:
                raise RuntimeError('Socket was closed. Receiving end if file.')
            data_str += new_s
        return data_str
    def read_packet(self):
        data_str = self._read_n(4)
        data, i = get_type(ulongint_type, data_str, no_class=True)
        data_str += self._read_n(data-4)
        return data_str
    def read_parse(self):
        return do_unpack(self.read_packet())



test1 = bytes(bytearray.fromhex("28030000010804000600000000030600000000095802000002402200000003401200000000090700000056657273696f6e00000903000000322e340002402800000003401000000000090500000054656d70730004050000000000f8a4a138d9a1d90000000002409e0000000340120000000009070000004d65737361676500000980000000436f70696572206c6f63616c656d656e74206c61206e6f7576656c6c652076657273696f6e20646973706f6e69626c6520737572205c626f625c5265636865726368655c436f6d6d756e5c4c6f67696369656c735c4e6174696f6e616c5f496e737472756d656e74735c4c6563747572652064652064e96269746de87472657302402801000003401600000000090c000000456d706c6163656d656e7473000801000600000000090a000000130000004c61626f205265756c65742044322d3030353500160000004c61626f205461696c6c656665722044322d30303632120000004c61626f2050696f726f2044322d30303636160000004c61626f205461696c6c656665722044322d30303532150000004c61626f205175696c6c69616d2044322d3030343600150000004c61626f20466f75726e6965722044322d3030343200130000004c61626f204475706f6e742044322d3130393000150000004c61626f20486f666865696e7a2044322d3130383400170000004c61626f20542e502e2f4a616e646c2044322d3230303000160000004c69717565662e2048e96c69756d2044322d31303832024030000000034010000000000906000000416c61726d73000801000600000002010b00000000ff00000000000000000000000801000600000002040600000001030d0000000d00000073616d706c65737472696e6731001300000009f544cd2b0fbf3fc2e1f47baeebe83f61eaf1c5e17fc53f4948972bcff8e33f91a0e0c5cfbdd23f000d4a8b90dad33fa711f54a5793d53f0000ca5057a2513f4899f07e4ad3a33f81a062f734ece73f000000000000a83f85eb51b81e05da3f000000000000bc3f000000000000ca3f000000000000ca3f000000000000c43fcdccccccccccc43f0000000000000000000000000000a03f3e000000"))
test2 = bytes(bytearray.fromhex("62000000010804000600000000030600000000090e000000000802000600000000030600000001030d0000000d00000073616d706c65737472696e67310002000000030000000000000000000000000000000000000000000000030000003c000000"))
# to show as hex again:
# test.encode('hex')

# Do do the equivalent of
#  do_unpack(test2) == do_unpack(test2)
# do instead:
#  np.testing.assert_equal(do_unpack(test2, timestamp=False), do_unpack(test2, timestamp=False))
#  np.testing.assert_equal(do_unpack(test1, timestamp=False), do_unpack(test1, timestamp=False))
# To check pack/unpack, do:
#  d, attrs, ts = do_unpack(test2)
#  do_pack([d[0], d[1], DataAttr(d[2], attrs), d[3]]) == test2
#  d, attrs, ts = do_unpack(test1)
#  do_pack([d[0], d[1], DataAttr(d[2], attrs), d[3]]) == test1


# To use:
#  ds = Dstp_Client('liquef', 'flowmeters')
#  ds.proto_open_var()
#  ds.get_next_data() # repeat as needed
#  ds.proto_close_var()
#  ds.close() # or del ds
# Or more complicated
#  ds = Dstp_Client('localhost', 'aa')
#  ds.proto_open_var(mode='bufreadwrite') # open 'aa'
#  ds.proto_open_var('cc', mode='bufreadwrite')
#  ds.proto_write('somedata') # writes 'aa'
#  ds.proto_write('somedata', collection.OrderedDict([('attr1', 1), ('attr2', [1,2,3])]), var='cc')
#  # Note that the write are not locally echoed.
#  # When opened with some read mode, the initial value will be available immediately
#  # When opened without a read mode, nothing will be available.
#  ds.get_next_data() # repeat as needed
#  ds.proto_close_var('cc')
#  ds.proto_close_var()
#  ds.close() # or del ds

# To allow remote connection to the datasocket, use the "datasocket server manager" application
# and change the DefaultWriters and Creators to everyone or add some ip addresses. Then save the settings.
# Note that the changes only work after stopping and restarting the "datasocket server"
#   see: https://knowledge.ni.com/KnowledgeArticleDetails?id=kA00Z000000kKFDSA2&l=en-CA
