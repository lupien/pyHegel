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

import os.path
import sys
import numpy as np


from ..instruments_base import BaseInstrument, scpiDevice, ChoiceIndex,\
                            wait_on_event, BaseDevice, MemoryDevice, ReadvalDev,\
                            _retry_wait, locked_calling, CHECKING

from ..instruments_registry import register_instrument, add_to_instruments

clr = None
Int32 = None
Int64 = None
IntPtr = None
Marshal = None
OlBase = None
OlException = None
_assembly_Version = None

_delayed_imports_done = False

def _delayed_imports():
    global _delayed_imports_done
    if not _delayed_imports_done:
        global clr, Int32, Int64, IntPtr, Marshal, OlBase, OlException
        try:
            import clr
            from System import Int32, Int64, IntPtr
            from System.Runtime.InteropServices import Marshal
        except ImportError as exc:
            raise RuntimeError('Unable to import windows clr/System: %s'%exc)
        try:
            _datatranslation_dir = r'C:\Program Files (x86)\Data Translation\DotNet\OLClassLib\Framework 2.0 Assemblies'
            if not os.path.isdir(_datatranslation_dir):
                # Version 6.1.0 has a slightly different directory name:
                _datatranslation_dir += ' (32-bit)'
            if _datatranslation_dir not in sys.path:
                sys.path.append(_datatranslation_dir)
            import OpenLayers.Base as OlBase
            from OpenLayers.Base import OlException
            _assembly_Version = OlBase.Utility.AssemblyVersion.ToString()
        except ImportError as exc:
            raise RuntimeError(
                "Unable to load data_translation Module. Make sure pythonnet and "
                "Data Translation Omni software are installed: %s"%exc)
        _delayed_imports_done = True

@add_to_instruments
def find_all_Ol():
    """
    This returns a list of all the connected Data Translation boxes.
    (Ol stands for OpenLayer which is the protocol it uses.)
    Every entry in the returned list is a tuple with the device
    name followed by a dictionnary of information.
    """
    _delayed_imports()
    devmgr = OlBase.DeviceMgr.Get()
    card_present = devmgr.HardwareAvailable()
    ret = []
    if not card_present:
        return ret
    card_list = list(devmgr.GetDeviceNames())
    for c in card_list:
        dev = devmgr.GetDevice(c)
        hwinfo = dev.GetHardwareInfo()
        # BoardId is year (1 or 2 digits), week (1 or 2 digist), test station (1 digit)
        # sequence # (3 digits)
        dev_info = dict(drv_name=dev.DriverName, drv_version=dev.DriverVersion,
            name=dev.DeviceName, model=dev.BoardModelName,
            version=hwinfo.DeviceId, serial=hwinfo.BoardId)
        dev.Dispose()
        ret.append((c, dev_info))
    return ret

class Ol_Device(scpiDevice):
    """
    This device is for all OpenLayer object properties
    """
    def __init__(self, setstr=None, getstr=None, autoget=True, **kwarg):
        if getstr is None and autoget and setstr is not None:
            if '{val}' not in setstr:
                getstr = setstr
                setstr = setstr+'={val}'
            else:
                getstr = setstr.replace('={val}', '')
        super(Ol_Device, self).__init__(setstr=setstr, getstr=getstr, autoget=autoget, **kwarg)

class Ol_ChoiceIndex(ChoiceIndex):
    def __init__(self, OlDataType, normalize=False):
        names = list(OlDataType.GetNames(OlDataType))
        values = list(OlDataType.GetValues(OlDataType))
        d = dict(zip(names, values))
        super(Ol_ChoiceIndex, self).__init__(d, normalize=normalize)
    def __getitem__(self, key_val):
        """ For a key this returns the value. For value it returns the corresponding key.
            It checks for keys First. This should be ok as long as keys and values
            don't have overlap (integers vs strings)
        """
        if key_val in self.dict:
            return super(Ol_ChoiceIndex, self).__getitem__(key_val)
        else:
            return self.keys[self.index(key_val)]


#######################################################
##    DataTranslation instrument
#######################################################

#@register_instrument('Data Translation', 'DT9847-3-1', 7.0.0.12)
@register_instrument('Data Translation', 'DT9847-3-1')
#@register_instrument('Data Translation', 'DT9837-C', '6.7.4.28')
@register_instrument('Data Translation', 'DT9837-C')
class DataTranslation(BaseInstrument):
    def __init__(self, dev_name=0):
        """
        To initialize a device, give it the device name as returned
        by find_all_Ol(), or the integer to use as an index in that
        list (defaults to 0).
        Only one process at a time can access this type of instrument.
        """
        _delayed_imports()
        devmgr = OlBase.DeviceMgr.Get()
        all_Ol = find_all_Ol()
        if CHECKING():
            raise RuntimeError('You cannot load DataTranslation in checking mode')
        try:
            name, info = all_Ol[dev_name]
        except TypeError:
            all_names = [n for n,i in all_Ol]
            try:
                name, info = all_Ol[all_names.index(dev_name)]
            except ValueError:
                raise IndexError, 'The device requested is not there. dev_name string not found'
        except IndexError:
            raise IndexError, 'The device requested is not there. dev_name too large (or no box detected).'
        self._name = name
        self.info = info
        dev = devmgr.GetDevice(name)
        self._dev = dev
        self._idn_string = 'Data Translation,%s,%s,%s'%(dev.BoardModelName, dev.GetHardwareInfo().BoardId, dev.DriverVersion)
        self._num_in = dev.GetNumSubsystemElements(OlBase.SubsystemType.AnalogInput)
        if self._num_in < 1:
            raise ValueError, 'No input available for ', name
        self._coupling_type = Ol_ChoiceIndex(OlBase.CouplingType)
        self._cursrc_type = Ol_ChoiceIndex(OlBase.ExcitationCurrentSource)
        self._dataflow_type = Ol_ChoiceIndex(OlBase.DataFlow)
        self._io_type = Ol_ChoiceIndex(OlBase.IOType)
        self._sync_type = Ol_ChoiceIndex(OlBase.SynchronizationModes)
        self._trig_type = Ol_ChoiceIndex(OlBase.TriggerType)
        self._buffer_state = Ol_ChoiceIndex(OlBase.OlBuffer.BufferState)
        self._sub_state = Ol_ChoiceIndex(OlBase.SubsystemBase.States)

        # We hard code the first element here. TODO check _num_in
        ai = dev.AnalogInputSubsystem(0)
        self._analog_in = ai
        in_supports = dict(single=ai.SupportsSingleValue, continuous=ai.SupportsContinuous,
                   single_ended=ai.SupportsSingleEnded, differential=ai.SupportsDifferential,
                   dc_coupl=ai.SupportsDCCoupling, ac_coupl=ai.SupportsACCoupling,
                   current_src=ai.SupportsInternalExcitationCurrentSrc,
                   adj_gain=ai.SupportsProgrammableGain,
                   bin_enc=ai.SupportsBinaryEncoding, two_compl_enc=ai.SupportsTwosCompEncoding,
                   sync=ai.SupportsSynchronization,
                   simultaneous_start=ai.SupportsSimultaneousStart, simultaneous_SH=ai.SupportsSimultaneousSampleHold,
                   buffering=ai.SupportsBuffering, in_process=ai.SupportsInProcessFlush)
        self.in_supports = in_supports
        in_info = dict(max_freq=ai.Clock.MaxFrequency, min_freq=ai.Clock.MinFrequency,
               max_single_ch=ai.MaxSingleEndedChannels, fifo=ai.FifoSize,
               Nchan=ai.NumberOfChannels, NGains=ai.NumberOfSupportedGains,
               gains=list(ai.SupportedGains), exc_currents=list(ai.SupportedExcitationCurrentValues),
               resolution=ai.Resolution, volt_range=[ai.VoltageRange.Low, ai.VoltageRange.High])
        self.in_info = in_info
        self.in_trig_info = {'level': ai.Trigger.Level,
                             'type': self._trig_type[ai.Trigger.TriggerType],
                             'threshold_ch': ai.Trigger.ThresholdTriggerChannel}
        self.in_ref_trig_info = {'level': ai.ReferenceTrigger.Level,
                                 'type': self._trig_type[ai.ReferenceTrigger.TriggerType],
                                 'threshold_ch': ai.ReferenceTrigger.ThresholdTriggerChannel,
                                 'post_count':ai.ReferenceTrigger.PostTriggerScanCount}
        all_channels = [ai.SupportedChannels[i] for i in range(ai.SupportedChannels.Count)]
        self.all_channels = all_channels
        self._update_all_channels_info(init=True)
        # Note that DT9837C actually advertizes 2 output system
        # The second one might be used internally for trigger threshold
        # But changing it directly does not seem to have any effect.
        self._num_out = dev.GetNumSubsystemElements(OlBase.SubsystemType.AnalogOutput)
        if self._num_out < 1:
            raise ValueError, 'No output available for ', name
        # We hard code the first element here. TODO check _num_in
        ao = dev.AnalogOutputSubsystem(0)
        self._analog_out = ao
        # TODO: Here I assume a single Channel and make it work in single mode
        ao.DataFlow=self._dataflow_type['SingleValue']
        ao.Config()
        #Make sure ai is in continuous mode
        ai.DataFlow=self._dataflow_type['Continuous']
        self._inbuffer = None
        # See also System.AssemblyLoadEventHandler which instantiates an delegate
        ai.SynchronousBufferDone = True
        #TODO: figure out why this causes a crash
        #ai.BufferDoneEvent += self._delegate_handler

        # init the parent class
        BaseInstrument.__init__(self)
        self._async_mode = 'acq_run'

    def idn(self):
        return self._idn_string
    def _update_all_channels_info(self, init=False):
        if CHECKING():
            # Note that all_channels_info coupling and current_src key will not
            # be updated properly. This will affect file headers when under checking
            return
        if init:
            gain = 1.
            self.all_channels_info = [{'coupling':self._coupling_type[c.Coupling],
                      'name': c.Name, 'gain': gain,
                      'current_src':self._cursrc_type[c.ExcitationCurrentSource],
                      'num':c.PhysicalChannelNumber,
                      'type':self._io_type[c.IOType]} for c in self.all_channels]
        else:
            for info, ch in zip(self.all_channels_info, self.all_channels):
                info['coupling'] = self._coupling_type[ch.Coupling]
                info['current_src'] = self._cursrc_type[ch.ExcitationCurrentSource]
    def __del__(self):
        print 'Deleting DataTranslation', self
        try:
            self._inbuffer.Dispose()
        except AttributeError:
            pass
        try:
            self._analog_out.Dispose()
        except AttributeError:
            pass
        try:
            self._analog_in.Dispose()
        except AttributeError:
            pass
        try:
            self._dev.Dispose()
        except AttributeError:
            pass
    def init(self,full = False):
        if full:
            self.output.set(0.)
    @locked_calling
    def _output_setdev(self, val):
        self._analog_out.SetSingleValueAsVolts(0, val)
    @locked_calling
    def write(self, string):
        if CHECKING():
            return
        exec('self.'+string)
    @locked_calling
    def ask(self, string, raw=False, chunk_size=None):
        # raw, chunk_size is not used here but is needed by scpiDevice methods
        if CHECKING():
            return ''
        return eval('self.'+string)
    @locked_calling
    def _async_trig(self):
        super(DataTranslation, self)._async_trig()
        self.run()
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        if CHECKING():
            return True
        func = lambda: not self._analog_in.IsRunning
        return _retry_wait(func, timeout=max_time, delay=0.05)
        # Also ai.State
        #return instrument.wait_on_event(self._run_finished, check_state=self, max_time=max_time)
    @locked_calling
    def abort(self):
        if CHECKING():
            return
        self._analog_in.Abort()
    def _clean_channel_list(self):
        clist = self.channel_list.getcache()
        clist = list(set(clist)) # use set to remove duplicates
        clist.sort() # order in place
        self.channel_list.set(clist)
        return clist
    @staticmethod
    def _delegate_handler(source, args):
        print 'My handler Called!', source, args
    @locked_calling
    def run(self):
        clist = self._clean_channel_list()
        if len(clist) == 0:
            raise ValueError, 'You need to have at least one channel selected (see channel_list)'
        if CHECKING():
            return
        self._analog_in.ChannelList.Clear()
        for i,c in enumerate(clist):
            #self._analog_in.ChannelList.Add(self.all_channels[c].PhysicalChannelNumber)
            self._analog_in.ChannelList.Add(self.all_channels_info[c]['num'])
            self._analog_in.ChannelList[i].Gain = self.all_channels_info[c]['gain']
            #self._analog_in.ChannelList.Add(OlBase.ChannelListEntry(self.all_channels[c])
        self._analog_in.Config()
        wanted_size = int(self.nb_samples.getcache() * len(clist))
        if self._inbuffer is not None:
            if self._inbuffer.BufferSizeInSamples != wanted_size:
                #print 'Erasing bnuffer'
                self._inbuffer.Dispose()
                self._inbuffer = None
        if self._inbuffer is None:
            self._inbuffer = OlBase.OlBuffer(wanted_size, self._analog_in)
        self._analog_in.BufferQueue.QueueBuffer(self._inbuffer)
        self._analog_in.Start()

    @locked_calling
    def _current_config(self, dev_obj=None, options={}):
        self._update_all_channels_info()
        extra = ['AssemblyVersion=%r'%_assembly_Version, 'boxname=%r'%self._name,
                 'cardinfo=%r'%self.info, 'all_channel_info=%r'%self.all_channels_info]
        base = self._conf_helper('nb_samples', 'in_clock', 'channel_list',
                                 'in_trig_mode', 'in_trig_level', 'in_trig_threshold_ch',
                                 'in_reftrig_mode', 'in_reftrig_level', 'in_reftrig_threshold_ch',
                                 'in_reftrig_count', 'output', options)
        return extra+base
    def _fetch_getformat(self, **kwarg):
        clist = self._clean_channel_list()
        #unit = kwarg.get('unit', 'default')
        #xaxis = kwarg.get('xaxis', True)
        #ch = kwarg.get('ch', None)
        multi = []
        for c in clist:
            multi.append(self.all_channels_info[c]['name'])
        fmt = self.fetch._format
        if self.nb_samples.getcache() == 1:
            fmt.update(multi=multi, graph=range(len(clist)))
        else:
            fmt.update(multi=tuple(multi), graph=[])
        #fmt.update(multi=multi, graph=[], xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_getdev(self):
        clist = self._clean_channel_list()
        if self._inbuffer is None:
            return None
        #This conversion is much faster than doing
        # v=array(list(buf.GetDataAsVolts()))
        buf = self._inbuffer
        fullsize = buf.BufferSizeInSamples
        validsize = buf.ValidSamples
        v=np.ndarray(validsize, dtype=float)
        Marshal.Copy(buf.GetDataAsVolts(), 0, IntPtr.op_Explicit(Int64(v.ctypes.data)), len(v))
        num_channel = len(clist)
        if num_channel != 1 and self.nb_samples.getcache() != 1:
            v.shape = (-1, num_channel)
            v = v.T
        return v
    def _create_devs(self):
        self.nb_samples = MemoryDevice(1024, min=1, max=1024*1024*100)
        self.in_clock = Ol_Device('_analog_in.Clock.Frequency', str_type = float, setget=True,
                               min=self.in_info['min_freq'], max=self.in_info['max_freq'])
        self.channel_list = MemoryDevice([0])
        self.in_current_ch = MemoryDevice(0,min=0, max=self.in_info['Nchan'])
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.in_current_ch)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return Ol_Device(*arg, **kwarg)
        # These are changed when doing ai.Config() or starting an acq with ai.GetOneBuffer(c1, length, timeout_ms)
        #  timeout_ms can be -1 to disable it.
        self.coupling = devChOption('all_channels[{ch}].Coupling', choices=self._coupling_type)
        self.exc_current_src = devChOption('all_channels[{ch}].ExcitationCurrentSource', choices=self._cursrc_type)
        # I don't think there is a way to set the Gain when doing GetOneBuffer
        self.gain = devChOption('all_channels_info[{ch}]["gain"]', str_type=float, choices=self.in_info['gains'])
        #Trigger starts the acquisition
        self.in_trig_mode = Ol_Device('_analog_in.Trigger.TriggerType', choices=self._trig_type)
        self.in_trig_level =  Ol_Device('_analog_in.Trigger.Level',
                                              str_type=float,
                                              min=self.in_info['volt_range'][0], max=self.in_info['volt_range'][1])
        self.in_trig_threshold_ch = Ol_Device('_analog_in.Trigger.ThresholdTriggerChannel',
                                              str_type=int,
                                              min=0, max=self.in_info['Nchan'])
        # The reference trigger will stop acquisition after ScanCount
        # It does not handle TTL
        self.in_reftrig_mode = Ol_Device('_analog_in.ReferenceTrigger.TriggerType', choices=self._trig_type)
        self.in_reftrig_level =  Ol_Device('_analog_in.ReferenceTrigger.Level',
                                              str_type=float,
                                              min=self.in_info['volt_range'][0], max=self.in_info['volt_range'][1])
        self.in_reftrig_threshold_ch = Ol_Device('_analog_in.ReferenceTrigger.ThresholdTriggerChannel',
                                              str_type=int,
                                              min=0, max=self.in_info['Nchan'])
        self.in_reftrig_count = Ol_Device('_analog_in.ReferenceTrigger.PostTriggerScanCount',
                                              str_type=int, min=0)
        self._devwrap('output', autoinit=False)
        self._devwrap('fetch', autoinit=False, trig=True)

        self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
    def force_get(self):
        # Since user cannot change change values except without using this program
        # the cache are always up to date and this is not needed.
        pass
    @locked_calling
    def set_simple_acq(self, nb_samples=1024, channel_list=[0], clock=None):
        """
        nb_sample is the number of samples per channel to acquire
        channel_list is either a single channel number (0 based)
                     a list of channel numbers or None which means all
                     available channels
        clock can be 'min', 'max'(default) or any number in between.
              if it is None, it will keep the current clock.
        You can also set the trig variables (trig_level, trig_mode, trig_ref_src)
        """
        self.nb_samples.set(nb_samples)
        if clock == 'max':
            clock = self.in_clock.max
            print 'Clock set to', clock, 'Hz'
        elif clock == 'min':
            clock = self.in_clock.min
            print 'Clock set to', clock, 'Hz'
        if clock is not None:
            self.in_clock.set(clock)
        if channel_list is None:
            channel_list = range(self.in_info['Nchan'])
        if type(channel_list) != list:
            channel_list = [channel_list]
        self.channel_list.set(channel_list)


# TODO: Handle x scales

#Events: BufferDoneEvent, DriverRunTimeErrorEvent, QueueDoneEvent, QueueStoppedEvent
