# -*- coding: utf-8 -*-
#
import visa

import numpy as np

def decodeblock(str):
   if str[0]!='#':
       return
   nh = int(str[1])
   nbytes = int(str[2:2+nh])
   blk = str[2+nh:]
   if len(blk) != nbytes:
       print "Missing data"
       return
   # we assume real 64, swap
   data = np.fromstring(blk,'float64')
   return data
   
def decode(str):
   if str[0]=='#':
      v = decodeblock(str)
   else:
      v = fromstring(str, 'float64', sep=',')
   return v


def init(visastr):
    v=visa.instrument(visastr)
    v.write(':format REAL,64')
    v.write(':format:border swap')
    return v

def getx(visaobj, channel=1):
    """ get the x scale values for channel n (1 by default)
    """
    str = visaobj.ask(':sense%d:X?'%channel)
    return decode(str)

def getxcur(visaobj, channel=1):
    """ get the x scale values for the current measurement
        for channel n (1 by default)
    """
    str = visaobj.ask(':calc%d:X?'%channel)
    return decode(str)

def getdata(visaobj, channel=1):
    """ get the y scale values for the current measurement
        for channel n (1 by default)
        This is after equation-math-gating-formating and is in 
        display unit
    """
    str = visaobj.ask(':calc%d:data? fdata'%channel)
    return decode(str)

def getCdata(visaobj, channel=1):
    """ get the complex y scale values for the current measurement
        for channel n (1 by default)
        This is after correction but before equation ... (see getdata)
        and is complex ratio of Volts.
    """
    str = visaobj.ask(':calc%d:data? sdata'%channel)
    
    z = decode(str)
    z.shape=(-1,2)
    z= z[:,0]+1j*z[:,1]
    return z

def generalget(visaobj, n, ask):
    str = visaobj.ask(ask%n)
    z = decodeblock(str)
    z.shape=(-1,2)
    z=z.T
    return z

def sel(visaobj, n, channel=1):
    """ Select measurement number n
        for channel m (1 by default)
        returns measurement name, window and trace number (on that window)
        
        This will only work if the requested measurement is within the
        channel
        Note: I think measurement # and the trace # seen on the display
              are the same thing.
    """
    visaobj.write(':calc%d:par:mnum %d'%(channel, n))
    return visaobj.ask(':calc%d:par:sel?'%channel), \
            visaobj.ask(':syst:meas%d:window?'%n),  \
            visaobj.ask(':syst:meas%d:trace?'%n)

if __name__ == "__main__":
    print visa.get_instruments_list()
    #v=visa.instrument('USB0::0x0957::0x0118::MY49001395')
    #v.write(':format ascii') # default
    #v.ask('calc:par:cat?')
    #v.write('calc:par:sel CH1_S11_1')
    #x2=v.ask(':calc:data? fdata')
    #z=fromstring(x2, 'float64', sep=',')
    #plot(z[::2],z[1::2])
    v=init('USB0::0x0957::0x0118::MY49001395::0::INSTR')
    sel(v, 1)
    xx= getx(v)
    y=getdata(v)

    plot(xx,y)
    yc=getCdata(v)
    plot(xx,degree(yc, deg=True))
    plot(xx, 20*log(abs(yc)))
    
    v.ask(':syst:active:channel?')
    v.ask(':syst:active:measurement?')
    v.ask(':syst:channels:cat?')
    v.ask(':syst:meas1:name?')
    v.ask(':syst:meas2:name?')
    v.ask(':syst:meas2:trace?')
    v.ask(':syst:meas2:window?')
    v.ask(':output?') # Rf power on
    v.ask(':source:power1?')
    v.ask(':sense:average?')
    v.ask(':sense:average:count?')
    v.ask(':sense:average:mode?')
    v.ask(':sense1:bandwidth?')
    v.ask(':sense1:class:name?')
    v.ask(':sense1:correction?')
    v.ask('calc1:par:cat?')  # get list of measurements
    v.ask('calc1:par:mnum?') # get/set current measurement number
    v.ask('calc:par:sel?') # get/set current measurement name
    v.ask(':calc1:correction:state?') # for current measurement
    v.ask(':sense:freq:start?')
    v.ask(':sense:freq:stop?')
    v.ask(':sense:freq:cw?')
    v.ask(':sense:roscillator:source?') # check if ref 10MHz is ext or int
    v.ask(':sense:sweep:points?')
    v.ask(':sense:sweep:type?') # LIN LOG POW CW SEGment PHASe
    v.ask(':calc:format?') 
    v.ask(':calc:format:unit? MLOG')
    v.ask(':calc1:marker1:x?')
    v.ask(':calc1:marker1:y?')
    
    
# status byte stuff
# There is a bunch of register groups:
#  :status:operation
#  :status:operation:device  # contains sweep complete
#  :status:operation:averaging1
#  :status:questionable
#  :status:questionable:integrity
#  :status:questionable:limit1
#   ...
# For each group there is 
#       :CONDition?   to query instant state
#       [:EVENt]?     To query and reset latch state
#       :NTRansition  To set/query the negative transition latching enable bit flag
#       :PTRansition  To set/query the positive transition latching enable bit flag
#       :ENABle       To set/query the latch to the next level bit flag
#  bit flag can be entered in hex as #Hfff or #hff
#                             oct as #O777 or #o777
#                             bin as #B111 or #b111
#  The connection between condition (instantenous) and event (latch) depends
#  on NTR and PTR. The connection between event (latch) and next level in 
#  status hierarchy depends on ENABLE
#
# There are also IEEE status and event groups
# For event: contains *OPC bit, error reports
#       *ESR?    To read and reset the event register (latch)
#       *ESE     To set/query the bit flag that toggles bit 5 of IEEE status
# For IEEE status: contains :operation (bit 7), :questionable (bit 3)
#                           event (bit 5), error (bit 2), message available (bit 4)
#                           Request Service =RQS (bit 6) also MSS (master summary) which
#                                     is instantenous RQS. RQS is latched
#                           Not that first bit is bit 0
# To read error (bit 2): v.ask(':system:error?')
#   that command is ok even without errors
# Message available (bit 4) is 1 after a write be before a read if there was 
# a question (?) in the write (i.e. something is waiting to be read)
#
#       the RQS (but not MSS) bit is read and reset by serial poll
#        *STB?   To read (not reset) the IEEE status byte, bit 6 is read as MSS not RQS
#        *SRE    To set/query the bit flag that controls the RQS bit
#                      RQS (bit6) is supposed to be ignored.
# *CLS   is to clear all event registers and empty the error queue.
#
# To read the status byte: visa.vpp43.read_stb(v.vi)
#visa.vpp43.enable_event(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, visa.vpp43.VI_QUEUE)
#visa.vpp43.wait_on_event(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, 2000)
def event_handler(vi, event_type, context, use_handle):
    stb = visa.vpp43.read_stb(vi) # This is necessary for gpib, otherwise RQS line is kept active
                                  # so no more events can be received until read_stb is done
                                  # It does not seem to be necessary for USB device
    print 'helo 0x%x'%stb, event_type==visa.vpp43.VI_EVENT_SERVICE_REQ, context, use_handle
    return visa.vpp43.VI_SUCCESS
#visa.vpp43.install_handler(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, event_handler)
# USB as event visa.vpp43.VI_EVENT_USB_INTR but it depends on device and will not
#  work for SRQ
#visa.vpp43.enable_event(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, visa.vpp43.VI_HNDLR)
#v.write(':status:operation:enable 1024')
#v.ask(':status:operation?;:status:operation:device?')
#v.write('*sre %d'%(0x80))
#out_event_type, out_context = visa.vpp43.wait_on_event(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, 5000)
#out_event_type==visa.vpp43.VI_EVENT_SERVICE_REQ
#visa.vpp43.read_stb(v.vi)
#v.ask('*stb?')
#out_event_type, out_context = visa.vpp43.wait_on_event(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, visa.vpp43.VI_TMO_IMMEDIATE)
#visa.vpp43.close(out_context) # close for wait, don't close for handler
#visa.vpp43.disable_event(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, visa.vpp43.VI_HNDLR)
#visa.vpp43.uninstall_handler(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, event_handler)
#   but that fails when user_handle is empty so can use instead
#uh=visa.vpp43.install_handler(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, event_handler,1)
#visa.vpp43.uninstall_handler(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, event_handler,uh)
#
#For synchronisation can use *WAI, *OPC or *OPC?
#
# With both GPIB and USB interface activated. They both have their own status registers
# for STB to OPERATION ...
# They also have their own error queues and most other settings (active measurement for channel,
#   data format) seem to also be independent on the 2 interfaces
#
# Reading only returns values from the last request
# so: v.ask('*stb?;:bandwidth?') returns '196;1.000000000E+05'
# but v.write('*stb?');v.write(':bandwidth?');v.read() only returns '1.000000000E+05'
#  It also produces and error in the log of: -410 = Query Interrupted





