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
    #v.write(':format ascii') # default
    v.write(':format REAL,64')
    v.write(':format:border swap')
    return v


def gettrace(visaobj, n):
    """ get trace n from visa obj
        This only returns  the y data. It does not contain x
    """
    str = visaobj.ask(':trace? trace%d'%n)
    return decode(str)

def generalget(visaobj, n, ask):
    str = visaobj.ask(ask%n)
    z = decode(str)
    z.shape=(-1,2)
    z=z.T
    return z

def fetch0(visaobj):
   """ fetch trace 0 which is a bunch of data
   """
   str = visaobj.ask(':fetch:san0?')
   v = decode(str)
   d = dict(margin=v[0]==1,
            Ndb=v[4], avgcount=int(v[5]), npoints=int(v[6]),
            markers=v[10:22])
   return d

def fetch(visaobj, n):
    """ fetch trace n from visa obj
        This returns both x and y
        It does not initiate a read but waits the end of
		the sweep if it is scanning
    """
    return generalget(visaobj, n, ':fetch:san%d?')

def read(visaobj, n):
    """ fetch trace n from visa obj
        This returns both x and y
        It initiates a read (:init:san or :initiate:restart) which blocks other scpi until
		completion than fetches
    """
    return generalget(visaobj, n, ':read:san%d?')


if __name__ == "__main__":
    print visa.get_instruments_list()
    #v=visa.instrument('USB0::0x0957::0x0B0B::MY51170142::0::INSTR')
    v=init('USB0::0x0957::0x0B0B::MY51170142::0::INSTR')
    t=S.gettrace(v, 2)
    plot(t)

    x,y = fetch(v,3)
    plot(x,y)
    xy = fetch(v,2)
    np.savetxt('xy.txt',xy.T)
    np.savetxt('xy300.txt',xy300.T,delimiter='\t')
    xy300=S.fetch(v,2)
    xy77=S.fetch(v,4)
    x=xy77[0]
    y77=xy77[1]
    y300=xy300[1]
    Y=10.**((y300-y77)/10.)
    nf=Y/(Y-1) * (1 - 77./290.)
    plot(x,10*log10(nf))
    
    
    v.ask(':detector:trace1?')
    v.ask(':trace2:type?')
    v.ask(':bandwidth?')
    v.ask(':bandwidth:video?')
    v.write(':calc:mark1:max') # calls a peak search
    v.ask(':calc:mark1:x?')
    v.ask(':calc:mark1:y?')
    v.ask(':average:count?')
    v.ask(':average:type?')
    v.ask(':freq:start?')
    v.ask(':freq:stop?')
    v.ask(':input:coupling?')
    v.ask(':power:gain?')
    v.ask(':power:gain:band?')
    v.ask(':unit:power?')
    v.ask(':power:attenuation?')
    v.ask(':power:attenuation:auto?')
    v.ask(':sweep:points?')
    v.ask(':freq:span?') # returns 0 in zero span mode --> xscale is then time
    v.write(':calibration:rf')
    
# status byte stuff
# There is a bunch of register groups:
#  :status:operation
#  :status:questionable
#  :status:questionable:power
#  :status:questionable:frequency
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
#def event_handler(vi, event_type, context, use_handle):
#    stb = visa.vpp43.read_stb(vi) # This is necessary for gpib, otherwise RQS line is kept active
#                                  # so no more events can be received until read_stb is done
#                                  # It does not seem to be necessary for USB device
#    print 'helo 0x%x'%stb, event_type==visa.vpp43.VI_EVENT_SERVICE_REQ, context, use_handle
#    return visa.vpp43.VI_SUCCESS
#visa.vpp43.install_handler(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, event_handler)
# USB as event visa.vpp43.VI_EVENT_USB_INTR but it depends on device and will not
#  work for SRQ
#visa.vpp43.enable_event(v.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, visa.vpp43.VI_HNDLR)
#v.write(':status:operation:enable #h8')
#v.ask(':status:operation?')
#v.write('*sre %d'%(0x80+0x40))
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
# They also have their own error queues
# Things like :Format affect both at the same time
#
# Reading only returns values from the last request
# so: v.ask('*stb?;:bandwidth?') returns '196;1.000000000E+05'
# but v.write('*stb?');v.write(':bandwidth?');v.read() only returns '1.000000000E+05'




