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

"""
Code to communicate with the Cryomech compressor
"""

import datetime
import os
import serial
import sys
import time
import win32com.client
# Result from C:\Python27\Lib\site-packages\win32com\client\makepy.py -i "SMDP_SVR 1.0 Type Library"
#SMDP_SVR 1.0 Type Library
# {59B51FF9-6181-41E6-9662-146ECA120832}, lcid=0, major=1, minor=0
# # Use these commands in Python code to auto generate .py support
from win32com.client import gencache
gencache.EnsureModule('{59B51FF9-6181-41E6-9662-146ECA120832}', 0, 1, 0)


def do_escape(message):
    ret = ''
    esc = '\x07'
    for c in message:
        if c == '\x02':
            ret += esc+'0'
        elif c == '\r':
            ret += esc+'1'
        elif c == '\07':
            ret += esc+'2'
        else:
            ret += c
    return ret

def undo_escape(message):
    ret = ''
    esc = '\x07'
    in_esc = False
    for c in message:
        if c == esc and not in_esc:
            in_esc = True
            continue
        if in_esc:
            in_esc = False
            if c == '0':
                c = '\02'
            elif c == '1':
                c = '\r'
            elif c == '2':
                c = '\07'
            else:
                raise ValueError, 'Invalid escape character: %r'%c
        ret += c
    return ret


class Cryomech(object):
    """
    Communicate with the ask method
    """
    HASHES = dict(code_sum=0x2b0d, mem_loss=0x801a, cpu_temp=0x3574, batt_ok=0xa37a,
              batt_low=0x0b8b, comp_minutes=0x454c, motor_curr_A=0x638b,
              temp_tenth_degC_vec4=0x0d8f, temp_tenth_degC_min_vec4=0x6e58,
              temp_tenth_degC_max_vec4=0x8a1c, reset_minmax=0xd3db,
              temp_err_any=0x6e2d,
              pressure_tenth_psi_vec2=0xaa50,
              pressure_tenth_psi_min_vec2=0x5e0b, pressure_tenth_psi_max_vec2=0x7a62,
              pressure_err_any=0xf82b,
              pressure_tenth_psi_avg_low_side=0xbb94,
              pressure_tenth_psi_avg_high_side=0x7e90,
              pressure_tenth_psi_avg_delta=0x319c,
              pressure_tenth_psi_deriv_high_side=0x66fa, # AC coupled pressure
              rmt_in_comp_start_state=0xbaf7,
              rmt_in_comp_stop_state=0x3d85,
              rmt_in_comp_interlock=0xb15a,
              rmt_in_slvl=0x95e3,
              start_compressor_1=0xd501,
              stop_compressor_0=0xc598,
              compressor_state=0x5f95,
              error_code_status=0x65a4,
              #test_bad=0x1234, # this returns a packet with rsp=3 and no data
              diodes_uV=0x8eea,
              diodes_temp_cK_vec2=0x5813,
              diodes_err_vec2=0xd644,
              diodes_custom_cal=0x9965)
    #temp_tenth_degC*, [0] input water, [1] ouput water, [2] helium, [3] oil
    #pressure_tenth_psi*, [0] high side, [1] low side
    #rmt_in_slvl, changes start to level sensitive (instead of rising edge) and
    # disables stop
    def __init__(self, com_port_N, addr=0x10, do_timestamp=True, baudrate=115200,
                 timeout=0.5, active_x=False):
        """
        When active_x is enabled, it uses the SMDP_SVR COM module,
        otherwise it communicates directly to the device.
        Remark on reuletlab3 at least the active_x module seems to loose
        communication rather quickly (~30 get_all at baudrate=115200).
        Cause is unknown but might be due to speed/multicore of machine
        since the SMDP_SVR.exe is a multithreaded app. It think it is the one
        corrupting the data.
        """
        self.active_x = active_x
        self.addr=addr
        if active_x:
            self.com_obj = win32com.client.Dispatch('SMDP_SVR.ProtEngine')
            co = self.com_obj
            co.Baud = baudrate
            co.ComPortNo=com_port_N
            co.DoPacketStamp=do_timestamp
            co.TimeoutMS=max(1,int(timeout*1000))
            # The syscon protocol is different (older? No checksum?)
            co.Protocol=win32com.client.constants.PROT0_SMDP
            ## other properties available
            ## see _prop_map_get_
            ## for constants see: co.win32com.client.constants.__dicts__ after
            #co.LastTransTimeSec
            #co.NumInstances
            #co.Build
            co.Open() # makes it implicit, otherwise it is implicit in first DoTransaction
        else:
            port = 'com%i'%com_port_N
            self._serialno = 0x10
            self.do_timestamp = do_timestamp
            self.dev = serial.Serial(port, baudrate=baudrate, bytesize=serial.EIGHTBITS,
                                     parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                                     timeout=timeout)
    def __del__(self):
        if self.active_x:
            self.com_obj.Close()
        else:
            self.dev.close()
        print 'device erased!'
    def flush(self):
        if self.active_x:
            pass
        else:
            self.dev.flushInput()
    def smdp_read_serial(self):
        # Needs timeout to be defined otherwise it will block
        ret = ''
        started = False
        while True:
            r=self.dev.read()
            if r=='':
                raise ValueError, 'timedout while reading. current string %r'%ret
            ret += r
            if r == '\r':
                if started:
                    return ret
                else:
                    raise ValueError, 'Invalid input sequence: %r'%ret
            if r == '\x02':
                if started:
                    raise ValueError, 'Received multiple start. current string %r'%ret
                started = True
                ret = r
    def _incr_serialno(self):
        # serialno can be 0x10 to 0xff
        n = self._serialno
        n = (n+1)%256
        self._serialno = max(0x10, n)
    def calc_chksum(self, message, cmd_rsp=0, serialno=None):
        if serialno==None:
            serialno=0
        sum = self.addr+cmd_rsp+serialno
        for c in message:
            sum += ord(c)
        sum %= 256
        return sum
    def smdp_base(self, message):
        chksum_base = 0x30
        extra = ''
        serialno = None
        if self.do_timestamp:
            serialno = self._serialno
            if serialno < 0x10 or serialno > 0xff:
                raise ValueError, 'Serial out of range (%i)'%serialno
            chksum_base = 0x40
            extra = chr(serialno)
        chksum = self.calc_chksum(message, serialno=serialno)
        chk1 = chksum_base+(chksum>>4)
        chk2 = chksum_base+(chksum&0xf)
        stx = '\x02'
        cr = '\r'
        return stx+chr(self.addr)+do_escape(message)+extra+chr(chk1)+chr(chk2)+cr
    def smdp_cmd(self, cmd, message=''):
        """
         cmd = 3: Sycon product id string
         cmd = 4: Software version string
         cmd = 5: reset
         cmd = 6: Acknowledge PowerFail
         cmd = 7: Protocol stack version string
         cmd 8-15, user
        """
        return self.smdp_base(chr(cmd<<4)+message)
    def cryo_readdict_messsage(self, dict_hash, index=0):
        message = 'c'+chr(dict_hash>>8) + chr(dict_hash&0xff)+chr(index)
        cmd = 8
        return (cmd, message)
    def cryo_writedict_messsage(self, dict_hash, value, index=0):
        message = 'a'+chr(dict_hash>>8) + chr(dict_hash&0xff)+chr(index) +\
                  chr((value>>24)&0xff) + chr((value>>16)&0xff) +\
                  chr((value>>8)&0xff) + chr(value&0xff)
        cmd = 8
        return (cmd, message)
    def push_button(self, button):
        """
        button is one of 'service', 'select', 'inc', 'dec', 'cancel'
        returns ask(9)
        """
        keydict = dict(service=0x40, select=0x08, inc=0x04, dec=0x80, cancel=0x20)
        val = keydict[button]
        self.ask(10, val)
        time.sleep(.1)
        self.ask(10, 0) # release button so it can be pressed again
        return self.ask(9)
    def compressor_start(self):
        self.ask('start_compressor_1', val=1)
    def compressor_stop(self):
        self.ask('stop_compressor_0', val=0)
    def reset_minmax(self):
        self.ask('reset_minmax', val=1)
    def ask(self, question, index=0, val=None):
        """ questions:
              3: Product ID
              4: Software version
              5: Reset slave
              6: Acknowledge power fail
              7: Protocol stack version
              9: Obtain compressor display
              10: push a button
                   index: Select=0x08, Service=0x40, inc=0x04, dec=0x80, cancel=0x20
              14: Get errors
                   index 0-0x1a
            when val is given, the value will be changed
        """
        if question in (3, 4, 5, 6, 7, 9):
            cmd = question
            message = ''
        elif question == 10:
            cmd = 0xa
            if index&0x13:
                raise ValueError, 'Invalid button to push'
            message = chr(index)
        elif question == 14:
            if index<0 or index>0x1a:
                raise ValueError, 'index out of 0-0x1a range'
            cmd = 0xe
            message = '\x4d\x00'+chr(index)
        elif isinstance(question, basestring):
            if val == None:
                cmd, message = self.cryo_readdict_messsage(self.HASHES[question], index=index)
            else:
                cmd, message = self.cryo_writedict_messsage(self.HASHES[question], val, index=index)
        else:
            raise ValueError, 'Unknown command'
        if self.active_x:
            response, RSPFflag = self.com_obj.DoTransaction(self.addr, cmd-1, message)
            # encode to mbcs means to use the default windows encoding.
            # so undo the conversion from 8bit to unicode done by windows
            # Hopefully this will be the correct conversion
            answer = self.smdp_parse_message(cmd, response.encode('mbcs'))
            answer.update(powerfail=RSPFflag)
        else:
            self.dev.write(self.smdp_cmd(cmd, message))
            response = self.smdp_read_serial()
            answer = self.smdp_parse_input(response)
            self._incr_serialno()
        return answer
    def smdp_parse_input(self, message):
        if message == '':
            raise ValueError, 'Empty message'
        stx = '\x02'
        cr = '\r'
        if len(message) < 6 or message[0] != stx or message[-1] != cr:
            raise ValueError, 'Invalid message: %r'%message
        chk1=ord(message[-3])
        chk2=ord(message[-2])
        addr=ord(message[1])
        cmd_rsp=ord(message[2])
        message = message[3:-3] # remove stx and cr delimiters and addr, cmd and checksums
        if (chk1>>4) != (chk2>>4) or (chk1>>4) not in (0x3, 0x4):
            raise ValueError,'Invalid chk sums %i,%i. %r'%(chk1,chk2, message)
        chksum = ((chk1&0x0f)<<4) + (chk2&0x0f)
        serialno = None
        if (chk1>>4) == 0x4:
            serialno = ord(message[-1])
            message = message[:-1] # remove serial from message
            if serialno != self._serialno:
                raise ValueError, 'Invalid serial number (%i), excected %i'%(serialno, self._serialno)
        message = undo_escape(message)
        calc_sum = self.calc_chksum(message, cmd_rsp, serialno)
        if calc_sum != chksum:
            raise ValueError, 'checksum error. message=%i, calc=%i'%(chksum, calc_sum)
        cmd = cmd_rsp>>4
        rsp = cmd_rsp&0x07
        if rsp not in (1, 6):
            errors = ['rsp=0, not permitted on reply',
                      'OK',
                      'cmd not valid',
                      'syntax error in data field',
                      'data range error',
                      'inhibited',
                      'Obsolete command (nop)',
                      'Reserved']
            raise ValueError, 'return code not OK, instead rsp=%i: %s'%(rsp, errors[rsp])
        powerfail = ((cmd_rsp&0x08) != 0)
        ret = self.smdp_parse_message(cmd, message)
        ret.update(powerfail=powerfail, serialno=serialno, chksum=chksum, addr=addr, rsp=rsp)
        return ret
    def smdp_parse_message(self, cmd, message):
        dict_hash = index = None
        if cmd in (3, 4, 6, 7, 9, 0xa):
            data = message
        elif cmd == 0xe:
            # TODO figure out proper time conversion (dayligth stuff and days offset)
            t = (ord(message[1])<<24) + (ord(message[2])<<16) + (ord(message[3])<<8) + ord(message[4])
            t += 939186000 # an epoch of 1999-10-6 0:0:0 in terms of python time Epoch
            tstr = time.ctime(t)
            data = dict(error=ord(message[0]), time=tstr, time_int=t)
        elif cmd == 8 and len(message)==8 and message[0]=='c':
            dict_hash = (ord(message[1])<<8) + ord(message[2])
            index = ord(message[3])
            data = (ord(message[4])<<24) + (ord(message[5])<<16) + (ord(message[6])<<8) + (ord(message[7]))
            if dict_hash not in self.HASHES.values():
                raise ValueError, 'Unknow hash %0x, index=%i, data=%i'%(dict_hash, index, data)
            else:
                for k,v in self.HASHES.iteritems():
                    if dict_hash == v:
                        dict_hash = k
                        break
        elif cmd == 8 and len(message)==0:
            data = message
        else:
            raise ValueError, 'Unknown command (%i): data=%r'%(cmd, message)
        return dict(data=data, index=index, dict_hash=dict_hash, cmd=cmd)
    def get_all(self):
        lask = lambda q: self.ask(q)['data']
        laski = lambda q, i: self.ask(q, index=i)['data']
        panel = lask(9)
        compressor_on = bool(lask('compressor_state'))
        err_code_status = lask('error_code_status')
        temp_water_in = laski('temp_tenth_degC_vec4', 0)/10.
        temp_water_out = laski('temp_tenth_degC_vec4', 1)/10.
        temp_He = laski('temp_tenth_degC_vec4', 2)/10.
        temp_oil = laski('temp_tenth_degC_vec4', 3)/10.
        temp_water_in_min = laski('temp_tenth_degC_min_vec4', 0)/10.
        temp_water_out_min = laski('temp_tenth_degC_min_vec4', 1)/10.
        temp_He_min = laski('temp_tenth_degC_min_vec4', 2)/10.
        temp_oil_min = laski('temp_tenth_degC_min_vec4', 3)/10.
        temp_water_in_max = laski('temp_tenth_degC_max_vec4', 0)/10.
        temp_water_out_max = laski('temp_tenth_degC_max_vec4', 1)/10.
        temp_He_max = laski('temp_tenth_degC_max_vec4', 2)/10.
        temp_oil_max = laski('temp_tenth_degC_max_vec4', 3)/10.
        motor_current = lask('motor_curr_A')
        pressure_high = laski('pressure_tenth_psi_vec2', 0)/10.
        pressure_low = laski('pressure_tenth_psi_vec2', 1)/10.
        pressure_high_min = laski('pressure_tenth_psi_min_vec2', 0)/10.
        pressure_low_min = laski('pressure_tenth_psi_min_vec2', 1)/10.
        pressure_high_max = laski('pressure_tenth_psi_max_vec2', 0)/10.
        pressure_low_max = laski('pressure_tenth_psi_max_vec2', 1)/10.
        pressure_high_avg = lask('pressure_tenth_psi_avg_high_side')/10.
        pressure_low_avg = lask('pressure_tenth_psi_avg_low_side')/10.
        pressure_delta_avg = lask('pressure_tenth_psi_avg_delta')/10.
        pressure_deriv = lask('pressure_tenth_psi_deriv_high_side')/10.
        vals = locals().copy()
        del vals['lask']
        del vals['laski']
        del vals['self']
        return vals


def get_startofweek(time_tuple):
    d = datetime.date(time_tuple.tm_year, time_tuple.tm_mon, time_tuple.tm_mday)
    day = d.weekday() # monday=0 .. sunday=6
    day_offset = (day+1)%7 # days to remove to return the previous sunday
    d = d - datetime.timedelta(day_offset)
    return d.timetuple()[:3] # year, month, day

def time_to_str(seconds):
    t = time.localtime(seconds)
    s = time.strftime('%Y-%m-%d %H:%M:%S  %a', t)
    tzoff = time.altzone if t.tm_isdst else time.timezone
    tzoff = -tzoff # ISO 8601 is reverse of offsets
    sign = '+'
    if tzoff<0:
        tzoff = -tzoff
        sign = '-'
    tzoff_hour = tzoff/3600
    tzoff_min  = (tzoff/60)%60
    return s+'  %s%02d%02d'%(sign, tzoff_hour, tzoff_min)

def do_log(com_obj, path, wait=5*60.):
    """
    The data from the cryomech compressor is logged to a file
    path/2013/Cryomech-Log-20130407.txt
    every wait seconds (defaults every 5 minute)
    The year and date are changed as necessary. The date is
    only changed once a week (starts on sunday).
    The year directory is created as needed.
    Every times the day changes, the minmax are reset
    """
    param = ['compressor_on', 'err_code_status', 'motor_current',
             'temp_water_in_min', 'temp_water_in', 'temp_water_in_max',
             'temp_water_out_min', 'temp_water_out', 'temp_water_out_max',
             'temp_He_min', 'temp_He', 'temp_He_max',
             'temp_oil_min', 'temp_oil', 'temp_oil_max',
             'pressure_low_min', 'pressure_low', 'pressure_low_avg', 'pressure_low_max',
             'pressure_high_min', 'pressure_high', 'pressure_high_avg', 'pressure_high_max',
             'pressure_delta_avg', 'pressure_deriv']
    header = '# Temps in C, pressures in psi\n#'+'\t'.join(['time']+param)+'\n'
    orig_time = time.time()
    prev_time = time.localtime(orig_time)
    last_stamp = 0
    while True:
        try:
            t = time.time()
            cur_time = time.localtime(t)
            data = com_obj.get_all()
            data['compressor_on'] = int(data['compressor_on'])
            if cur_time.tm_mday != prev_time.tm_mday:
                # new day
                com_obj.reset_minmax()
            prev_time = cur_time
            y, m, d = get_startofweek(cur_time)
            filename = 'Cryomech-Log-%04i%02i%02i.txt'%(y, m, d)
            directory = '%04i'%y
            subpath = os.path.join(path, directory)
            if not os.path.exists(subpath):
                os.mkdir(subpath)
            filename = os.path.join(subpath, filename)
            if not os.path.exists(filename):
                with open(filename, 'w') as f:
                    f.write(header)
            data_lst = [repr(t)]
            data_lst += [repr(data[p]) for p in param]
            with open(filename, 'a') as f:
                if t-last_stamp > 3*3600: # every 3 hours
                    last_stamp = t
                    f.write('# '+time_to_str(t)+'\n')
                f.write('\t'.join(data_lst)+'\n')
            # lets try and space all points by same amount
            wait_done = (time.time()-orig_time)%wait
            wait_left = max(0.1, wait-wait_done) # at least 0.1 s
            time.sleep(wait_left)
        except ValueError as exc:
            print 'Problem', exc
            com_obj.flush()
            time.sleep(30)


#ob = Cryomech(5)
#do_log(ob, 'C:/Bluefors/Log-files/Cryomech')
