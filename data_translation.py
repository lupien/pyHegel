# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:
"""
Created on Tue Aug 28 11:08:58 2012

@author: Christian Lupien
"""

import clr
import instrument
import sys
import numpy as np
from System import Int32, IntPtr
from System.Runtime.InteropServices import Marshal

_datatranslation_dir = r'C:\Program Files (x86)\Data Translation\DotNet\OLClassLib\Framework 2.0 Assemblies (32-bit)'
if _datatranslation_dir not in sys.path:
    sys.path.append(_datatranslation_dir)

import OpenLayers.Base as OlBase
from OpenLayers.Base import OlException
devmgr = OlBase.DeviceMgr.Get()
_assembly_Version = OlBase.Utility.AssemblyVersion.ToString()

card_present = devmgr.HardwareAvailable()
card_list = list(devmgr.GetDeviceNames())

if not card_present:
    raise ValueError, 'No Data Translation Card present!!'
dev = devmgr.GetDevice(card_list[0])
hwinfo = dev.GetHardwareInfo()
dev_info = dict(drv_name=dev.DriverName, drv_version=dev.DriverVersion,
                name=dev.DeviceName, model=dev.BoardModelName,
                version=hwinfo.DeviceId, serial=hwinfo.BoardId)
num_in = dev.GetNumSubsystemElements(OlBase.SubsystemType.AnalogInput)
num_out = dev.GetNumSubsystemElements(OlBase.SubsystemType.AnalogOutput)

if num_in < 1:
    raise ValueError, 'No input available'

ai = dev.AnalogInputSubsystem(0)

if num_out < 1:
    raise ValueError, 'No output available'
# Note that DT9837C actually advertizes 2 output system
# The second one might be used internally for trigger threshold
# But changing it directly does not seem to have any effect.
ao = dev.AnalogOutputSubsystem(0)
# BoardId is year (1 or 2 digits), week (1 or 2 digist), test station (1 digit)
# sequence # (3 digits)

in_supports = dict(single=ai.SupportsSingleValue, continuous=ai.SupportsContinuous,
                   single_ended=ai.SupportsSingleEnded, differential=ai.SupportsDifferential,
                   dc_coupl=ai.SupportsDCCoupling, ac_coupl=ai.SupportsACCoupling,
                   current_src=ai.SupportsInternalExcitationCurrentSrc,
                   adj_gain=ai.SupportsProgrammableGain,
                   bin_enc=ai.SupportsBinaryEncoding, two_compl_enc=ai.SupportsTwosCompEncoding,
                   sync=ai.SupportsSynchronization,
                   simultaneous_start=ai.SupportsSimultaneousStart, simultaneous_SH=ai.SupportsSimultaneousSampleHold,
                   buffering=ai.SupportsBuffering, in_process=ai.SupportsInProcessFlush)
in_info = dict(max_freq=ai.Clock.MaxFrequency, min_freq=ai.Clock.MinFrequency,
               max_single_ch=ai.MaxSingleEndedChannels, fifo=ai.FifoSize,
               Nchan=ai.NumberOfChannels, NGains=ai.NumberOfSupportedGains,
               gains=list(ai.SupportedGains), exc_currents=list(ai.SupportedExcitationCurrentValues),
               resolution=ai.Resolution, volt_range=[ai.VoltageRange.Low, ai.VoltageRange.High])
#ai.Clock.Frequency = in_info['max_freq']
ai.Clock.Frequency = 1000
all_channels = [ai.SupportedChannels[i] for i in range(ai.SupportedChannels.Count)]
c1 = all_channels[0]

class mapping(object):
    def __init__(self, some_type):
        self.names = list(some_type.GetNames(some_type))
        self.values = list(some_type.GetValues(some_type))
    def __getitem__(self, key_val):
        if key_val in self.names:
            return self.values[self.names.index(key_val)]
        else:
            return self.names[self.values.index(key_val)]
coupling_type = mapping(OlBase.CouplingType)
cursrc_type = mapping(OlBase.ExcitationCurrentSource)
dataflow_type = mapping(OlBase.DataFlow)
io_type = mapping(OlBase.IOType)
sync_type = mapping(OlBase.SynchronizationModes)
trig_type = mapping(OlBase.TriggerType)

trig_info = {'level': ai.Trigger.Level, 'type': trig_type[ai.Trigger.TriggerType],
             'threshold_ch': ai.Trigger.ThresholdTriggerChannel}
ref_trig_info = {'level': ai.ReferenceTrigger.Level, 'type': trig_type[ai.ReferenceTrigger.TriggerType],
             'threshold_ch': ai.ReferenceTrigger.ThresholdTriggerChannel,
             'post_count':ai.ReferenceTrigger.PostTriggerScanCount}

# These are changed when doing ai.Config() or starting an acq with ai.GetOneBuffer(c1, length, timeout_ms)
#  timeout_ms can be -1 to disable it.
#c1.ExcitationCurrentSource=cursrc_type['Internal']
#c1.ExcitationCurrentSource=cursrc_type['Disabled']
#c1.Coupling=coupling_type['AC']
#c1.Coupling=coupling_type['DC']

#ai.DataFlow=dataflow_type['SingleValue']
#ai.DataFlow=dataflow_type['Continuous']

all_channels_info = [{'coupling':coupling_type[c.Coupling],
                      'name': c.Name,
                      'current_src':cursrc_type[c.ExcitationCurrentSource],
                      'num':c.PhysicalChannelNumber,
                      'type':io_type[c.IOType]} for c in all_channels]

ai.ChannelList.Clear()
ai.ChannelList.Add(all_channels_info[0]['num'])
#ai.ChannelList.Add(c1.PhysicalChannelNumber)
#ai.ChannelList.Add(OlBase.ChannelListEntry(c1))

#Check current state: ai.IsRunning
# Also ai.State

buffer_state = mapping(OlBase.OlBuffer.BufferState)
sub_state = mapping(OlBase.SubsystemBase.States)

########
ao.DataFlow=dataflow_type['SingleValue']
ao.Config()
ao.SetSingleValueAsVolts(0, 0.)
#ao.SetSingleValueAsVolts(0, -.5)
########

# I don't think there is a way to set the Gain when doing GetOneBuffer
#ai.ChannelList[0].Gain=10

def myHandler(source, args):
    print 'My handler Called!', source, args

# See also System.AssemblyLoadEventHandler which instantiates an delegate
ai.SynchronousBufferDone=True
ai.BufferDoneEvent += myHandler

buf=OlBase.OlBuffer(10000,ai)
ai.BufferQueue.QueueBuffer(buf)
#Trigger starts the acquisition
#ai.Trigger.Level=-.5
#ai.Trigger.TriggerType=trig_type['ThresholdPos']
#ai.Trigger.TriggerType=trig_type['TTLNeg']
#ai.Trigger.TriggerType=trig_type['Software']
#ai.Trigger.ThresholdTriggerChannel=0
# The reference trigger will stop acquisition after ScanCount
# It does not handle TTL
#ai.ReferenceTrigger.Level=-.5
#ai.ReferenceTrigger.TriggerType=trig_type['ThresholdPos']
#ai.ReferenceTrigger.TriggerType=trig_type['Software']
#ai.ReferenceTrigger.ThresholdTriggerChannel=0
#ai.ReferenceTrigger.PostTriggerScanCount=0
#
ai.Config()
ai.Start()

#ai.Stop()
#ai.Abort()

#This tonumpy is much faster than doing
# v=array(list(buf.GetDataAsVolts()))
def tonumpy(buf, num_channel=1):
    fullsize = buf.BufferSizeInSamples
    validsize = buf.ValidSamples
    v=np.ndarray(validsize, dtype=float)
    Marshal.Copy(buf.GetDataAsVolts(), 0, IntPtr.op_Explicit(Int32(v.ctypes.data)), len(v))
    if num_channel != 1:
        v.shape = (-1, num_channel)
        v = v.T
    return v

#plot(array(list(buf.GetDataAsVolts())))

#Events: BufferDoneEvent, DriverRunTimeErrorEvent, QueueDoneEvent, QueueStoppedEvent

# When finished with device:
#ai.Dispose()
#ao.Dispose()
#dev.Dispose()