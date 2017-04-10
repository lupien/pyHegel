# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2011-2017  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

import numpy as np
import time

from ..instruments_base import visaInstrument, visaInstrumentAsync,\
                            BaseDevice, scpiDevice, MemoryDevice, ReadvalDev,\
                            ChoiceBase, ChoiceLimits, ChoiceStrings, ChoiceDevDep,\
                            locked_calling, visa_wrap
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

#hex(1510) = 0x05E6
register_usb_name('Keithley Instruments Inc.', 0x05E6)

def quote_str(s):
    s = s.replace('"', '""')
    return '"'+s+'"'

class ChoiceMultipleStrings(ChoiceBase):
    """
       Initialize with a list from ChoiceStrings.
       It allows the use of a single value, or a list of those elements.
       'all' can be used to list all entries
    """
    def __init__(self, choice_strings):
        self.choice_strings = choice_strings
    def __contains__(self, x): # performs x in y; with y=Choice()
        if isinstance(x, basestring):
            if x == 'all':
                return True
            x = [x]
        for e in x:
            if e not in self.choice_strings:
                return False
        return True
    def __call__(self, input_str):
        # this is called by dev._fromstr to convert a string to the needed format
        ret = []
        vals = input_str.split(',')
        for v in vals:
            ret.append(self.choice_strings(v.strip()))
        return ret
    def tostr(self, input_choice):
        # this is called by dev._tostr to convert a choice to the format needed by instrument
        if isinstance(input_choice, basestring):
            if input_choice == 'all':
                input_choice = self.choice_strings
            else:
                input_choice = [input_choice]
        vals = []
        for i in input_choice:
            vals.append(self.choice_strings.tostr(i))
        return ','.join(vals)
    def __repr__(self):
        return 'A list (or a single element) from: '+repr(self.choice_strings)
    def __getitem__(self, index):
        # index can be a single value: return it
        # or it can be a slice or a list, return a new object with only the selected elements
        #   the list can be numbers or strings (which finds number with index)
        if not isinstance(index, (slice, list)):
            return self.choice_strings[index]
        return ChoiceMultipleStrings(self.choice_strings[index])

def decode_block_auto(s, t=np.float64):
    if s[0:2] == '#0':
        block = s[2:][:-1] # remove #0 and ending \n
        return np.fromstring(block, t)
    else:
        return np.fromstring(s, t, sep=',')

#######################################################
##    Keithley 245S ourceMeter
#######################################################

# The instrument needs to be in SCPI mode
# There is a read buffer, so multiple questions require multiple read (so you might read old data)
#  to clear buffer, send device clear.

# Code was originally based on agilent.agilent_multi_34410A

#@register_instrument('KEITHLEY INSTRUMENTS INC.', 'MODEL 2450', '1.2.0f')
#@register_instrument('KEITHLEY INSTRUMENTS INC.', 'MODEL 2450', usb_vendor_product=[0x05E6, 0x2450], alias='2450 SMU')
#@register_instrument('KEITHLEY INSTRUMENTS', 'MODEL 2450', '1.6.1a')
@register_instrument('KEITHLEY INSTRUMENTS', 'MODEL 2450', usb_vendor_product=[0x05E6, 0x2450], alias='2450 SMU')
class keithley_2450_smu(visaInstrumentAsync):
    """
    This controls the keithley 2450 SourceMeter source mesure unit.
    Important devices:
     src_level
     readval  same as initiating a measurement, waiting then fetch
     fetch
     meas_autozero_en
     src_readback_en
    Useful method:
     set_long_avg  To setup average time (and triggering mode)
     show_long_avg To see the current averaging settings.
     abort
     sync_time
     clear_system
     meas_autozero_now
     meas_relative_acquire_now
     get_error
     get_eventlog
     data_clear
     data_stats_clear
     set_avg_count   (used internally by set_long_avg)
     data_buffer_delete
     data_buffer_create
    """
    def __init__(self, *args, **kwargs):
        super(keithley_2450_smu, self).__init__(*args, **kwargs)
        self._trig_data = dict(mode='basic', last_block='', count=1, inner_count=1, delay=0, buffer='') # mode can be basic or trig
    def _async_trigger_helper(self):
        mode = self._trig_data['mode']
        if mode == 'trigger':
            if self.trigger_blocks_list.get() != self._trig_data['last_block'] or self.data_current_buffer.get() != self._trig_data['buffer']:
                raise RuntimeError('Trigger code has changed!')
            # self.write('INITiate;*OPC')
            super(keithley_2450_smu, self)._async_trigger_helper()
        else:
            buffer = self._handle_buffer()
            if self.data_fill_mode.getcache() in self.data_fill_mode.choices[['once']] and self.meas_count.getcache()!=1:
                self.data_clear(buffer=buffer)
            else:
                self.data_stats_clear(buffer=buffer)
            self.write('TRACe:TRIGger {buffer};*OPC'.format(buffer=quote_str(buffer)))
    def init(self, full=False):
        # This empties the instrument buffers
        self._dev_clear()
        # default precision seems to be 7: 1.234567 which is not always enough
        #  better to read the data in binary
        self.write('FORMat:ASCii:PRECision DEFault')
        #self.write('FORMat:ASCii:PRECision MAXimum') # max is 16
        #self.write('FORMat:ASCii:PRECision 10')
        #self.write('FORMat ASCii') # This is set for every call
        self.write('FORMat:BORDer SWAPped') # other option is NORMal
        super(keithley_2450_smu, self).init(full=full)
    def abort(self):
        self.write('ABORt')
    def sync_time(self):
        """ Note that the instrument is in UTC time
        """
        t = time.gmtime()
        opts = dict(year=t.tm_year, month=t.tm_mon, day=t.tm_mday, hour=t.tm_hour, min=t.tm_min, sec=t.tm_sec)
        self.write('SYSTEM:TIME {year}, {month}, {day}, {hour}, {min}, {sec}'.format(**opts))
    def _current_config(self, dev_obj=None, options={}):
        src_conf = self._conf_helper('src_mode', 'src_level', 'src_range', 'src_range_auto_en', 'src_protection_level', 'src_protection_tripped',
                                      'src_limit', 'src_limit_tripped',
                                      'src_readback_en', 'src_delay_auto_en', 'src_delay', 'src_high_cap_mode_en')
        meas_conf = self._conf_helper('meas_mode', 'meas_nplc', 'meas_autozero_en', 'meas_four_wire_en',
                                      'meas_autorange_en', 'meas_range', 'meas_autorange_lower_limit', 'meas_autorange_upper_limit',
                                      'meas_filter_en', 'meas_filter_type', 'meas_filter_count',
                                      'meas_offset_comp_en', 'meas_relative_en', 'meas_relative_offset',
                                      'meas_math_en', 'meas_math_operation')
        mode = self._trig_data['mode']
        trig_conf = ['triger_mode=%s'%mode]
        if mode == 'basic':
            trig_conf += self._conf_helper('meas_count')
        else:
            d = self._trig_data
            trig_conf += ['trigger_count=%i'%d['count'], 'trigger_inner_count=%s'%d['inner_count'], 'trig_delay='%d['delay']]
            bl = self.trigger_blocks_list.get()
            bl = bl.replace('\n', r'\n')
            trig_conf +=  ['trigger_blocks_list='+bl]
        base_conf =    self._conf_helper('data_current_buffer', 'data_npoints_storable', 'data_fill_mode',
                                         'route_terminals', 'output_en', 'interlock_ok', 'line_freq', options)
        return src_conf +meas_conf + trig_conf + base_conf

    def _long_avg_helper(self):
        # update mode first, so others instruction apply correctly
        meas_mode = self.meas_mode.get()
        meas_mode_ch = self.meas_mode.choices
        src_mode = self.src_mode.get()
        src_mode_ch = self.src_mode.choices
        if meas_mode in meas_mode_ch[['voltage', 'voltage:dc', 'resistance']] and src_mode in src_mode_ch[['voltage']]:
            same = True
        elif meas_mode in meas_mode_ch[['current', 'current:dc']] and src_mode in src_mode_ch[['current']]:
            same = True
        else:
            same = False
        return same

    @locked_calling
    def set_long_avg(self, time=None, total_time=None, count=None, inner_count=1, delay=0, filter=None, nplc=None, mode=None, buffer=None, limit_time=None):
        """
        nplc as None will use the current value. When nplc<1. The timing measurement are only approximations.
        filter as None will use the current value. Otherwise 0 disables it, >=1 is the count used (a repeat filter). True/False enables/disables it.
        You have to choose one of time, total_time or count
        time is the average time of the measurement only (x3 for autozero, x2 for readback, x4 for both). It uses limit_time to False by default.
            When using 'basic' or 'trigger' with limit_time False it is only an approximation.
            This is similar to the agilent multimeter set_long_avg setting.
        total_time is the full time of the measurement including autozero and readback. It uses limit_time to True by default.
            When using 'basic' or 'trigger' with limit_time False it is only an approximation.
        count is the number of loops (possibly including delay and inner_count loop). It uses limit_time False by default.
            When using 'trigger' with limit_time True, it is only an approximation.
        mode can be 'basic' or 'trigger'. When left as None the choice is taken dependent of limit_time and delay.
        inner_count is only used when delay is non-zero. It is the number of measurements without applying delay. The total count is then inner_count*count.
        delay adds some time between the count loops. It requires mode 'trigger'
        limit_time when None uses above default. Otherwise, under trigger mode and without delay, when set to true it uses an algorithm that limits
        the total measurement time (so count might change between measurements), when False it sets a constant count.

        When count >1 you can obtain usefull statistics from fetch.
        """
        same = self._long_avg_helper()
        if mode not in ['basic', 'trigger', None]:
            raise ValueError(self.perror('Invalid mode'))
        if inner_count < 1:
            raise ValueError(self.perror('Invalid inner_count'))
        buffer = self._handle_buffer(buffer)
        if nplc is not None:
            self.meas_nplc.set(nplc)
        if filter is not None:
            if filter is True:
                self.meas_filter_en.set(True)
            elif filter is False or filter == 0:
                self.meas_filter_en.set(False)
            elif filter < 0:
                raise ValueError(self.perror('Invalid filter'))
            else:
                self.meas_filter_en.set(True)
                self.meas_filter_type.set('REPeat')
                self.meas_filter_count.set(filter)
        if self.meas_filter_en.get() and self.meas_filter_type.get() in self.meas_filter_type.choices[['repeat']]:
            filter = self.meas_filter_count.get()
        else:
            filter = 1
        nplc = self.meas_nplc.get()
        line_period = 1./self.line_freq.get()
        meas_time = line_period * nplc * filter
        if delay == 0:
            inner_count = 1
        else:
            if mode == 'basic':
                raise ValueError(self.perror('You cannot use basic mode with a non-zero delay'))
            mode = 'trigger'
        factor = 1.
        if self.src_readback_en.get() and not same:
            factor += 1
        if self.meas_autozero_en.get():
            factor += 2
        if time is not None and total_time is None and count is None:
            # time
            if time <= 0:
                raise ValueError(self.perror('Invalid time, needs >0'))
            count = int(np.ceil(time/(meas_time*inner_count)))
            total_time = (meas_time*factor*inner_count + delay) * count
            if limit_time is None:
                limit_time is False
        elif time is None and total_time is not None and count is None:
            # total_time
            if total_time <= 0:
                raise ValueError(self.perror('Invalid total_time, needs >0'))
            count = int(np.ceil(total_time/(meas_time*factor*inner_count+delay)))
            time = meas_time*inner_count*count
            if limit_time is None:
                limit_time is True
        elif time is None and total_time is None and count is not None:
            # count
            if count <= 0:
                raise ValueError(self.perror('Invalid count, needs >0'))
            total_time = (meas_time*factor*inner_count + delay) * count
            time = meas_time*inner_count*count
            if limit_time is None:
                limit_time is False
        else:
            raise ValueError(self.perror('Use only one of time, total_time or count'))
        if mode is None:
            if limit_time:
                mode = 'trigger'
            else:
                mode = 'basic'
        total_count = count*inner_count
        if mode == 'basic':
            self._trig_data['mode'] = mode
            self.meas_count.set(count)
        else:
            if delay == 0:
                if limit_time:
                    inner_count='inf'
                    delay = total_time
                else:
                    inner_count = inner_count*count
                    count = 1.
            self.set_avg_count(count=count, inner_count=inner_count, delay=delay)
        size = self.data_npoints_storable.get()
        if size < total_count:
            self.data_npoints_storable.set(total_count*2)

    @locked_calling
    def show_long_avg(self):
        same = self._long_avg_helper()
        nplc = self.meas_nplc.get()
        line_period = 1./self.line_freq.get()
        if self.meas_filter_en.get():
            filter = self.meas_filter_count.get()
            if self.meas_filter_type.get() in self.meas_filter_type.choices[['repeat']]:
                filtern = '%i (repeat)'%filter
            else:
                filtern = '%i (moving)'%filter
                filter = 1
        else:
            filtern = 'off'
            filter = 1
        if nplc < 1.:
            print 'WARNING: nplc is small, timing is very approximative'
        print 'nplc=%f, filter=%s'%(nplc, filtern)
        meas_time = line_period * nplc * filter
        factor = 1.
        if self.src_readback_en.get() and not same:
            factor += 1
        if self.meas_autozero_en.get():
            factor += 2
        mode = self._trig_data['mode']
        if mode == 'basic':
            count = self.meas_count.get()
            time = count*meas_time
            total_time = time*factor
            print 'Mode is %s, count=%i (time=%f, total_time=%f)'%(mode, count, time, total_time)
        else:
            # trigger
            d = self._trig_data
            count = d['count']
            delay = d['delay']
            inner_count = d['inner_count']
            if inner_count == 'inf':
                total_time = delay
                count = int(np.ceil(total_time/(meas_time*factor)))
                time = count*meas_time
                print 'Mode is %s, total_time=%f, limit_time=True (count=%i, time=%f)'%(mode, total_time, count, time)
            else:
                time = count*inner_count*meas_time
                total_time = count*(inner_count*meas_time*factor + delay)
                if delay==0 and count>1:
                    print 'Mode is %s, count=%i, inner_count=%i, delay=%f (total_time=%f, time=%f, total_count=%i, only setupable with set_avg_count)'%(
                        mode, count, inner_count, delay, total_time, time, count*inner_count)
                else:
                    print 'Mode is %s, count=%i, inner_count=%i, delay=%f (total_time=%f, time=%f, total_count=%i)'%(
                        mode, count, inner_count, delay, total_time, time, count*inner_count)
        return time

    def clear_system(self):
        """ Clears event log, including front panel
        """
        self.write('SYSTem:CLEar')
    def user_display(self, line1=None, line2=None, clear=False):
        """ only the first 20 (32) characters are use for line1 (line2) """
        if clear:
            self.write('DISPlay:CLEar')
        # There is no question to read the user line back
        #self.user_display = scpiDevice('DISPlay:USER{line}:TEXT', str_type=quoted_string(), options=dict(line=1), options_lim=dict(line=[1,2]), doc='20 (32) char max for line=1 (2)', autoget=False)
        if line1 is not None:
            self.write('DISPlay:USER{line}:TEXT {val}'.format(line=1, val=quote_str(line1[:20])))
        if line2 is not None:
            self.write('DISPlay:USER{line}:TEXT {val}'.format(line=2, val=quote_str(line2[:32])))
    def meas_autozero_now(self):
        self.write('AZERo:ONCE')
    @locked_calling
    def meas_relative_acquire_now(self, mode=None):
        if mode is not None:
            self.meas_mode.set(mode)
        mode = self.meas_mode.get()
        self.write('{mode}:RELative:ACQuire'.format(mode=mode))
    def get_eventlog(self):
        return self.ask('SYSTem:EVENtlog:NEXT?')
    @locked_calling
    def _handle_buffer(self, buffer=None):
        if buffer is not None:
            self.data_current_buffer.set(buffer)
        return self.data_current_buffer.get()
    @locked_calling
    def data_buffer_delete(self, buffer=None):
        """ This deletes buffer if it does not already exists
        """
        buffer = self._handle_buffer(buffer)
        self.write('TRACe:DELete {buffer}'.format(buffer=quote_str(buffer)))
    style_choices = ChoiceStrings('COMPact', 'STANdard', 'FULL', 'WRITable', 'FULLWRITable')
    @locked_calling
    def data_buffer_create(self, new, buffer=None, size=10000, style='standard', fill='continuous', change_smaller=False):
        """ This creates a new buffer when new is True or modifies it (fill, size) when False
            It will also adjust its size if necessary, and its fill mode.
            Style can be: COMPact  (reduces resolution, more data)
                          STANdard
                          FULL
                          WRITable      (cannot be used for measurement)
                          FULLWRITable  (cannot be used for measurement)
            change_smaller when false, prevents making a buffer smaller.
            fill/size can be None to keep the current one.
            Note that a fill buffer with once will produce an error when trying to start a sequence that will
            go past its end. However it can be reset.
            compact allows to read all entries (some are force to be the same like unit, and range, 1us timestamps
                    with rollover after 1hour, resolution limited to 6.5 digits) except for date.
            Standard has time resolution of 10 ns (either read it as binary or increase default ascii precision)
            I have not seen any difference between full and standard.
            Fullwritable adds an extra value that can be written.
        """
        buffer = self._handle_buffer(buffer)
        if new:
            self.write('TRACe:MAKE {buffer}, {size}, {style}'.format(buffer=quote_str(buffer), size=size, style=style))
        if fill is not None:
            curfill = self.data_fill_mode.get()
            if fill not in self.data_fill_mode.choices[[curfill]]:
                self.data_fill_mode.set(fill)
        if not new and size is not None:
            cursize = self.data_npoints_storable.get()
            if cursize != size:
                if size > cursize or change_smaller:
                    self.data_npoints_storable.set(size)
    @locked_calling
    def data_clear(self, buffer=None):
        """ This clears data and statistics from a data buffer.
        """
        buffer = self._handle_buffer(buffer)
        self.write('TRACe:CLEar {buffer}'.format(buffer=quote_str(buffer)))
    @locked_calling
    def data_stats_clear(self, buffer=None):
        buffer = self._handle_buffer(buffer)
        self.write('TRACe:STATistics:CLEar {buffer}'.format(buffer=quote_str(buffer)))
    def _fetch_helper(self, source=None, data=True, all=False, relative=False, avg=True, std=False, status=False, source_status=False, buffer=None):
        buffer = self._handle_buffer(buffer)
        if source is None:
            source = self.src_readback_en.get()
        bin_to_read = []
        ascii_to_read = []
        if relative:
            bin_to_read.append('relative')
        if source:
            bin_to_read.append('source')
        if data:
            bin_to_read.append('reading')
        if status:
            ascii_to_read.append('status')
        if source_status:
            ascii_to_read.append('sourstatus')
        if bin_to_read == [] and ascii_to_read == []:
            raise ValueError(self.perror('Nothing selected for reading'))
        if all:
            avg = False
            std = False
        elif not (avg or std):
            raise ValueError(self.perror('Nothing selected for reading (neither avg nor std'))
        return buffer, bin_to_read, ascii_to_read, avg, std
    def _fetch_getformat(self, source=None, data=True, all=False, relative=False, avg=True, std=False, status=False, source_status=False, buffer=None, **kwarg):
        buffer, bin_to_read, ascii_to_read, avg, std = self._fetch_helper(source, data, all, relative, avg, std, status, source_status, buffer)
        graph = kwarg.get('graph', None)
        fmt = self.fetch._format
        names = []
        names.extend(bin_to_read)
        names.extend(ascii_to_read)
        if all:
            multi = tuple(names)
            if graph is None:
                graph = []
        else:
            if graph is None:
                graph = True
            multia = [m+'_avg' for m in names]
            multis = [m+'_std' for m in names]
            if avg and std:
                multi = [None]*(2*len(multia))
                multi[::2] = multia
                multi[1::2] = multis
            elif avg:
                multi = multia
            else: # std
                multi = multis
            multi = list(multi)
        fmt.update(multi=multi, graph=graph)
        return BaseDevice.getformat(self.fetch, **kwarg)

    def _fetch_getdev(self, source=None, data=True, all=False, relative=False, avg=True, std=False, status=False, source_status=False, buffer=None, disable_stat=False):
        """
        options (all boolean):
            source: to read the source. When None it is auto enabled depending on readback status.
            data:   to read the measurement
            relative: to read the relative times
            status: to read the measurment status
            source_status: to read the source status
            all:    To return all the entries (overrides avg, and std)
            avg:    To return the avg of all the entries
            std:    To return the standard deviation of all the entries (with ddof=1)
        Other options:
            buffer: to select the buffer to use. None uses the currently active one.
            disable_stat: when only measurement (no source or relative) is requested and "all" is False, the code uses the data_stats_... device by default
                          This can disable them.
        For the meaning of the status bits, see data_fetch_ascii.
        For status and source_status, avg will "or" all the values, std will show any bits that have changed.
        The output is the selected element in the order shown above. With both avg and std, both are returned consecutivelly for element.
        """
        buffer, bin_to_read, ascii_to_read, avg, std = self._fetch_helper(source, data, all, relative, avg, std, status, source_status, buffer)
        npoints = self.data_npoints.get()
        if self._trig_data['mode'] == 'basic':
            toread = self.meas_count.get()
        else:
            d = self._trig_data
            count = d['count']
            inner_count = d['inner_count']
            if inner_count == 'inf':
                toread = npoints
            else:
                toread = count*inner_count
        stat_to_read = []
        if not all and toread > 1 and bin_to_read == ['reading'] and not disable_stat:
            bin_to_read = []
            if avg:
                stat_to_read.append('avg')
            if std:
                stat_to_read.append('std')
        if npoints < toread:
            raise RuntimeError(self.perror('Not enough data is available'))
        data_bin = np.zeros((toread, 0))
        data_asc = np.zeros((toread, 0))
        if toread == 1:
            if len(bin_to_read):
                data_bin = self.data_fetchlast_bin.get(elements=bin_to_read)
                data_bin.shape = (1, len(bin_to_read))
            if len(ascii_to_read):
                data_asc = decode_block_auto(self.data_fetchlast_ascii.get(elements=ascii_to_read), np.int)
                data_asc.shape = (1, len(ascii_to_read))
            data = np.concatenate((data_bin, data_asc), axis=1)
        else:
            size = self.data_npoints_storable.get()
            start = self.data_start.get()
            stop = self.data_stop.get()
            s = stop - toread + 1
            data_bin = np.zeros((toread, len(bin_to_read)))
            if s<1:
                # here size == npoints, start>stop  if size=toread
                if len(bin_to_read):
                    part1 = self.data_fetch_bin.get(start=size-s, stop=size, elements=bin_to_read)
                    part1.shape = (-1, len(bin_to_read))
                    part2 = self.data_fetch_bin.get(start=1, stop=stop, elements=bin_to_read)
                    part2.shape = (-1, len(bin_to_read))
                    data_bin = np.concatenate((part1, part2), axis=0)
                if len(ascii_to_read):
                    part1 = decode_block_auto(self.data_fetch_ascii.get(start=size-s, stop=size, elements=ascii_to_read), np.int)
                    part1.shape = (-1, len(ascii_to_read))
                    part2 = decode_block_auto(self.data_fetch_ascii.get(start=1, stop=stop, elements=ascii_to_read), np.int)
                    part2.shape = (-1, len(ascii_to_read))
                    data_asc = np.concatenate((part1, part2), axis=0)
            else:
                if len(bin_to_read):
                    data_bin = self.data_fetch_bin.get(start=s, stop=stop, elements=bin_to_read)
                    data_bin.shape = (-1, len(bin_to_read))
                if len(ascii_to_read):
                    data_asc = decode_block_auto(self.data_fetch_ascii.get(start=s, stop=stop, elements=ascii_to_read), np.int)
                    data_asc.shape = (-1, len(ascii_to_read))
        data_avg = []
        data_std = []
        if len(stat_to_read):
            if 'avg' in stat_to_read:
                data_avg += [ self.data_stats_avg.get() ]
            if 'std' in stat_to_read:
                data_std += [ self.data_stats_std.get() ]
        if toread == 1:
            if avg:
                if len(bin_to_read):
                    data_avg += list(data_bin[0])
                if len(ascii_to_read):
                    data_avg += list(data_asc[0])
            if std:
                if len(bin_to_read):
                    data_std += [0.]*len(bin_to_read)
                if len(ascii_to_read):
                    data_std += [0.]*len(ascii_to_read)
        else:
            if avg:
                if len(bin_to_read):
                    data_avg += list(data_bin.mean(axis=0))
                if len(ascii_to_read):
                    d = np.bitwise_or.reduce(data_asc, axis=0)
                    data_avg +=  list(d)
            if std:
                if len(bin_to_read):
                    data_std += list(data_bin.std(axis=0, ddof=1))
                if len(ascii_to_read):
                    d = np.bitwise_or.reduce(data_asc ^ data_asc[0], axis=0)
                    data_std +=  list(d)
        if all:
            data = np.concatenate((data_bin, data_asc), axis=1).T
        else:
            data = np.concatenate((data_avg, data_std))
            N = len(bin_to_read)+len(ascii_to_read)
            if len(stat_to_read):
                N += 1
            data.shape = (-1, N)
            data = data.T.flatten()
            if len(data) == 1:
                data = data[0]
        return data

    @locked_calling
    def set_avg_count(self, count=10, inner_count=1, delay=0, buffer=None):
        """
        inner_count can be INF, in which case measurement are countinous in background until next
        measurement. delay can be 0.
        With inner_count not INF the pseudo code is:
           clear buffer
           for i in range(count):
               wait delay
               measure inner_count times
        With inner count == INF the pseudo code is:
           clear buffer
           t = time.now
           while time.now < t+delay:
               measure
        This code is similar to SimpleLoop (but prevents user from changing count/delay which
        cannot be read back)
        """
        #   This routines takes about 2 ms on usb
        # The previous algo2 was
        #  buffer clear
        #  measure inf
        #  delay
        # However that meant it waited before the first data before starting the delay.
        # So could end up with extra wait without data
        buffer = self._handle_buffer(buffer)
        algo = 1
        if isinstance(inner_count, basestring):
            algo = 2
            inner_count = inner_count.lower()
            if inner_count != 'inf':
                raise ValueError(self.perror('Invalid inner_count parameter'))
            if delay <= 0:
                raise ValueError(self.perror('Expecting a delay>0 when using inner_count=="inf"'))
            self.write('TRIGger:TIMer1:CLEar')
            self.write('TRIGger:TIMer1:COUNt 1')
            self.write('TRIGger:TIMer1:DELay {delay}'.format(delay=delay))
            self.write('TRIGger:TIMer1:STARt:GENerate OFF')
            self.write('TRIGger:TIMer1:STARt:SEConds 0')
            self.write('TRIGger:TIMer1:STARt:FRACtional 0')
            self.write('TRIGger:TIMer1:STARt:STIMulus NOTify1')
            self.write('TRIGger:TIMer1:STATe ON')
        else:
            if inner_count <= 0:
                raise ValueError(self.perror('Invalid inner_count parameter'))
            if count <= 0:
                raise ValueError(self.perror('Invalid count'))
            if delay < 0:
                raise ValueError(self.perror('Expecting a delay>=0'))
        line=1
        opts = dict(buffer=quote_str(buffer), count=count, delay=delay, inner_count=inner_count)
        self.write('TRIGger:LOAD "Empty"')
        self.write('TRIGger:BLOCk:BUFFer:CLEar {line}, {buffer}'.format(line=line, **opts))
        line += 1
        target = line
        # Could use 'TRIGger:BLOCk:NOP 2'
        if algo == 1 and delay != 0:
            self.write('TRIGger:BLOCk:DELay:CONStant {line}, {delay}'.format(line=line, **opts))
        else:
            self.write('TRIGger:BLOCk:NOTify {line}, 1'.format(line=line, **opts))
        line += 1
        self.write('TRIGger:BLOCk:MEASure {line}, {buffer}, {inner_count}'.format(line=line, **opts))
        line += 1
        if algo == 1:
            self.write('TRIGger:BLOCk:BRANch:COUNTer {line}, {count}, {target}'.format(line=line, target=target, **opts))
        else:
            self.write('TRIGger:BLOCk:WAIT {line}, TIMer1'.format(line=line, **opts))
        line += 1
        self._trig_data['mode'] = 'trigger'
        self._trig_data['count'] = count
        self._trig_data['inner_count'] = inner_count
        self._trig_data['delay'] = delay
        self._trig_data['last_block'] = self.trigger_blocks_list.get()
        self._trig_data['buffer'] = buffer

    #TODO implement inteligent set level like for yokogawa.
    def _create_devs(self):
        # This needs to be last to complete creation
        self.route_terminals = scpiDevice('ROUTe:TERMinals', choices=ChoiceStrings('FRONt', 'REAR'))
        self.output_en = scpiDevice('OUTPut', str_type=bool)
        self.interlock_ok = scpiDevice(getstr='OUTPut:INTerlock:TRIPped?', str_type=bool)
        self.line_freq = scpiDevice(getstr='SYSTem:LFRequency?', str_type=float)
        src_mode_opt = ChoiceStrings('CURRent', 'VOLTage')
        self.src_mode = scpiDevice('SOURce:FUNCtion', choices=src_mode_opt, autoinit=20)
        meas_mode_opt = ChoiceStrings('CURRent', 'CURRent:DC', 'VOLTage', 'VOLTage:DC', 'RESistance', quotes=True)
        meas_volt = meas_mode_opt[['VOLTage', 'VOLTage:DC']]
        meas_curr = meas_mode_opt[['CURRent', 'CURRent:DC']]
        self.meas_mode = scpiDevice('FUNCtion', choices=meas_mode_opt, autoinit=20)
        def measDevOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mode=self.meas_mode)
            app = kwarg.pop('options_apply', ['mode'])
            options_conv = kwarg.pop('options_conv', {}).copy()
            options_conv.update(dict(mode=lambda val, conv_val: val))
            kwarg.update(options=options, options_apply=app, options_conv=options_conv)
            return scpiDevice(*arg, **kwarg)
        def srcDevOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mode=self.src_mode)
            app = kwarg.pop('options_apply', ['mode'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        limit_conv_d = {src_mode_opt[['current']]:'CURRent:VLIMit', src_mode_opt[['voltage']]:'VOLTage:ILIMit'}
        def limit_conv(val, conv_val):
            for k, v in limit_conv_d.iteritems():
                if val in k:
                    return v
            raise KeyError('Unable to find key in limit_conv')
        #limit_conv = lambda val, conv_val: limit_conv_d[val]
        def srcLimitDevOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mode=self.src_mode)
            app = kwarg.pop('options_apply', ['mode'])
            options_conv = kwarg.pop('options_conv', {}).copy()
            options_conv.update(dict(mode=limit_conv))
            kwarg.update(options=options, options_apply=app, options_conv=options_conv)
            return scpiDevice(*arg, **kwarg)
        self.output_off_mode = srcDevOption('OUTPut:{mode}:SMODe', choices=ChoiceStrings('NORMal', 'HIMpedance', 'ZERO', 'GUARd'),
            doc="""
                 These options select the state of the output when ouput is disabled.
                 In all cases measurement sense is set to 2 wires
                 -himpedance: the output relay disconnects the load
                 -normal: Voltage src set to 0V, current limit to 10% of current range
                 -zero:  Voltage src set to 0V, autorange off, current limit kept the same or 10% of gull scale whichever is greate
                 -guard: Current src set to 0A, voltage limit to 10% of current range
            """)
        self.src_delay = srcDevOption('SOURce:{mode}:DELay', str_type=float, min=0, max=4, setget=True, doc='Extra time in seconds (after settling) between changing source and reading measurement. Changing it disables auto delay.')
        self.src_delay_auto_en = srcDevOption('SOURce:{mode}:DELay:AUTO', str_type=bool)
        self.src_high_cap_mode_en = srcDevOption('SOURce:{mode}:HIGH:CAPacitance', str_type=bool)
        src_level_choices = ChoiceDevDep(self.src_mode, {src_mode_opt[['CURRent']]:ChoiceLimits(-1.05, 1.05), meas_mode_opt[['voltage']]:ChoiceLimits(-210, 210)})
        self.src_level = srcDevOption('SOURce:{mode}', str_type=float, choices=src_level_choices, setget=True)
        #self.src_V_limit = scpiDevice('SOURce:VOLTage:ILIMIt', str_type=float, min=1e-9, max=1.05, setget=True)
        #self.src_I_limit = scpiDevice('SOURce:CURRent:VLIMIt', str_type=float, min=0.02, max=210, setget=True)
        limit_choices = {'VOLTage:ILIMit':ChoiceLimits(1e-9, 1.05), 'CURRent:VLIMit':ChoiceLimits(0.02, 210)}
        self.src_limit = srcLimitDevOption('SOURce:{mode}', str_type=float, choices=limit_choices, setget=True)
        self.src_limit_tripped = srcLimitDevOption(getstr='SOURce:{mode}:TRIPped?', str_type=bool)
        protection_choices = ChoiceStrings('PROT2', 'PROT5', 'PROT10', 'PROT20', 'PROT40', 'PROT60', 'PROT80', 'PROT100', 'PROT120', 'PROT140', 'PROT160', 'PROT180', 'NONE')
        self.src_protection_level =  scpiDevice('SOURce:VOLTage:PROTection', choices=protection_choices)
        self.src_protection_tripped =  scpiDevice(getstr='SOURce:VOLTage:PROTection:TRIPped?', str_type=bool)
        src_range_choices = ChoiceDevDep(self.src_mode, {src_mode_opt[['CURRent']]:ChoiceLimits(-1, 1), meas_mode_opt[['voltage']]:ChoiceLimits(-200, 200)})
        self.src_range = srcDevOption('SOURce:{mode}:RANGe', str_type=float, choices=src_range_choices, setget=True)
        self.src_range_auto_en = srcDevOption('SOURce:{mode}:RANGe:AUTO', str_type=bool)
        self.src_readback_en = srcDevOption('SOURce:{mode}:READ:BACK', str_type=bool)

        self.meas_count = scpiDevice('COUNt', str_type=int, min=1, max=300000)
        self.meas_filter_count = measDevOption('{mode}:AVERage:COUNt', str_type=int, min=1, max=100)
        self.meas_filter_type = measDevOption('{mode}:AVERage:TCONtrol',  choices=ChoiceStrings('REPeat', 'MOVing'),
                                           doc="""
                                                  repeat averaging returns one value for every meas_avg_count taken.
                                                  moving averaging returns meas_avg_count for every meas_avg_count taken.
                                                                            the value is the average of at most (could be less if data is not available) meas_avg_count.
                                                                            So the first result in the buffer had no averaging on it.
                                            """)
        self.meas_filter_en = measDevOption('{mode}:AVERage', str_type=bool)
        self.meas_autozero_en = measDevOption('{mode}:AZERo', str_type=bool, doc='see also the meas_autozero_now method')
        self.meas_nplc = measDevOption('{mode}:NPLCycles', str_type=float, min=0.01, max=10, setget=True)
        self.meas_offset_comp_en = measDevOption('{mode}:OCOMpensated', str_type=bool)
        self.meas_autorange_en = measDevOption('{mode}:RANGe:AUTO', str_type=bool)
        range_choices = ChoiceDevDep(self.meas_mode, {meas_curr:ChoiceLimits(1e-8, 1), meas_volt:ChoiceLimits(.02, 200), meas_mode_opt[['resistance']]:ChoiceLimits(2, 200e6)})
        self.meas_autorange_lower_limit = measDevOption('{mode}:RANGe:AUTO:LLIMit', str_type=float, choices=range_choices, setget=True)
        self.meas_autorange_upper_limit = measDevOption('{mode}:RANGe:AUTO:ULIMit', str_type=float, choices=range_choices, setget=True)
        self.meas_range = measDevOption('{mode}:RANGe', str_type=float, choices=range_choices, setget=True)
        relative_choices = ChoiceDevDep(self.meas_mode, {meas_curr:ChoiceLimits(-1.05, 1.05), meas_volt:ChoiceLimits(-210, 210), meas_mode_opt[['resistance']]:ChoiceLimits(-210e6, 210e6)})
        self.meas_relative_offset = measDevOption('{mode}:RELative', str_type=float, choices=relative_choices, setget=True)
        self.meas_relative_en = measDevOption('{mode}:RELative:STATe', str_type=bool, doc='see also meas_relative_acquire_now')
        self.meas_four_wire_en = measDevOption('{mode}:RSENse', str_type=bool)

        self.meas_math_operation = measDevOption('CALculate:{mode}:MATH:FORMat', choices=ChoiceStrings('MXB', 'PERCent', 'RECiprocal'))
        self.meas_math_en = measDevOption('CALculate:{mode}:MATH:STATe', str_type=bool)

        self.data_current_buffer = MemoryDevice('defbuffer1')
        def dataDevOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(buffer=self.data_current_buffer)
            app = kwarg.pop('options_apply', ['buffer'])
            options_conv = kwarg.pop('options_conv', {}).copy()
            options_conv.update(dict(buffer=lambda val, conv_val: quote_str(val)))
            kwarg.update(options=options, options_apply=app, options_conv=options_conv)
            return scpiDevice(*arg, **kwarg)
        self.data_npoints_storable = dataDevOption('TRACe:POINts {val},{buffer}', 'TRACe:POINts? {buffer}', str_type=int, setget=True)
        self.data_npoints = dataDevOption(getstr='TRACe:ACTUal? {buffer}', str_type=int)
        self.data_start = dataDevOption(getstr='TRACe:ACTUal:STARt? {buffer}', str_type=int)
        self.data_stop = dataDevOption(getstr='TRACe:ACTUal:END? {buffer}', str_type=int)
        self.data_fill_mode = dataDevOption('TRACe:FILL:MODE {val},{buffer}', 'TRACe:FILL:MODE? {buffer}', choices=ChoiceStrings('CONTinuous', 'ONCE'))
        # Note that statistics on a continuous buffer can use more (when wrapped around) or less (when stats are cleared) than data_npoints
        self.data_stats_avg = dataDevOption(getstr='TRACe:STATistics:AVERage? {buffer}', str_type=float)
        self.data_stats_max = dataDevOption(getstr='TRACe:STATistics:MAXimum? {buffer}', str_type=float)
        self.data_stats_min = dataDevOption(getstr='TRACe:STATistics:MINimum? {buffer}', str_type=float)
        self.data_stats_p2p = dataDevOption(getstr='TRACe:STATistics:PK2Pk? {buffer}', str_type=float)
        self.data_stats_std = dataDevOption(getstr='TRACe:STATistics:STDDev? {buffer}', str_type=float,  doc='The instruments does the same as scipy std(ddof=1)')
        ascii_elements = ChoiceStrings('DATE', 'FORMatted', 'FRACtional', 'READing', 'RELative', 'SEConds', 'SOURce', 'SOURFORMatted', 'SOURSTATus', 'SOURUNIT', 'STATus', 'TIME', 'TSTamp', 'UNIT')
        ascii_mult_elem = ChoiceMultipleStrings(ascii_elements)
        self.data_fetch_ascii = dataDevOption(getstr=':FORMat ASCii; :TRACe:DATA? {start}, {stop}, {buffer}, {elements}', options=dict(start=1, stop=2, elements='READing'), options_lim=dict(elements=ascii_mult_elem),
                                              autoget=False,
                                              doc="""
                                              start needs to be less than stop and they need to be less than data_npoints
                                              Status bits are:
                                                               0x001: Questionnable
                                                               0x006: AD converter (always 0 for 2450)
                                                               0x008: front terminal
                                                               0x010: limit2 low
                                                               0x020: limit2 high
                                                               0x040: limit1 low
                                                               0x080: limit1 high
                                                               0x100: First reading in a group
                                              source status bits are:
                                                               0x04:  Overvoltage protection active
                                                               0x08:  Measured source was read (readback)
                                                               0x10:  Overtemperature active
                                                               0x20:  Source level limited
                                                               0x40:  Four wire sense used
                                                               0x80:  Output was on
                                              TSTtmp is composed of date+time+fractional (and has a little more resolution, the same as relative)
                                              Relative is the time in seconds since the first point in the buffer
                                              Seconds is the UTC time in seconds since the unix epoch
                                              For measurement, READing is the float, formatted includes the unit and possibly metric multiplier (p,n,m...)
                                              For source the equivalent entries are: source, sourformatted and sourunit
                                              """)
        bin_mult_elem = ascii_mult_elem[['reading', 'source', 'relative']]
        self.data_fetch_bin = dataDevOption(getstr=':FORMat REAL; :TRACe:DATA? {start}, {stop}, {buffer}, {elements}', options=dict(start=1, stop=2, elements='READing'), options_lim=dict(elements=bin_mult_elem),
                                            str_type=decode_block_auto, doc='see data_fetch_ascii', raw=True, autoget=False)
        self.data_fetchlast_ascii = dataDevOption(getstr=':FORMat ASCii; :FETCh? {buffer}, {elements}', options=dict(elements='READing'), options_lim=dict(elements=ascii_mult_elem), autoget=False,
                                                  doc='same as data_fetch_ascii except reads last value only')
        self.data_fetchlast_bin = dataDevOption(getstr=':FORMat REAL; :FETCh? {buffer}, {elements}', options=dict(elements='READing'), options_lim=dict(elements=bin_mult_elem), autoget=False, raw=True,
                                                  str_type=decode_block_auto, doc='same as data_fetch_bin except reads last value only')
        self.trigger_state = scpiDevice(getstr='TRIGger:STATe?', str_type=str)
        # This takes about 1 ms on usb
        self.trigger_blocks_list = scpiDevice(getstr='TRIGger:BLOCk:LIST?', str_type=str)

        #self.user_display = scpiDevice('DISPlay:USER{line}:TEXT', str_type=quoted_string(), options=dict(line=1), options_lim=dict(line=[1,2]), doc='20 (32) char max for line=1 (2)', autoget=False)

        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        #self.alias = self.readval
        super(type(self),self)._create_devs()

#       Timing test for not using the trigger system:
#         The fastest transfer of data to instrument memory is with
#            autozero off, autorange off, source readback off, nplc = 0.01
#            All filter test were done in repeat mode.
#      NPLC=0.01
#       with count = 6000, filter=off  (got the same result with and without autorange)  --> 6000 pts in buffer
#        %time smu1.data_clear(); smu1._async_trig_cleanup(); smu1.write('trace:trig;*OPC'); smu1.wait_after_trig()
#          takes 1.97s which means 6000/1.97 = 3045 rdgs/s (but about 50% dead time)
#       with count = 60, filter=100 --> 60 pts in buffer
#        %time smu1.data_clear(); smu1._async_trig_cleanup(); smu1.write('trace:trig;*OPC'); smu1.wait_after_trig()
#          takes 2s which means 6000/2 = 3000 rdgs/s (but about 50% dead time)
#       with count = 6000, filter=off, autozero=on:
#        %time smu1.data_clear(); smu1._async_trig_cleanup(); smu1.write('trace:trig;*OPC'); smu1.wait_after_trig()
#          takes 14.2s which means 6000/14.2 = 422 rdgs/s (lots of dead time)
#       with count = 6000, filter=off, source readback enabled
#        %time smu1.data_clear(); smu1._async_trig_cleanup(); smu1.write('trace:trig;*OPC'); smu1.wait_after_trig()
#          takes 6.76s which means 6000/6.76 = 887 rdgs/s (lots of dead time)
#       with count = 6000, filter=off, source readback enabled, autozeron=on (autorange has not big effect for stable signal)
#        %time smu1.data_clear(); smu1._async_trig_cleanup(); smu1.write('trace:trig;*OPC'); smu1.wait_after_trig()
#          takes 18.9s which means 6000/18.9 = 317 rdgs/s (lots of dead time)
#      Now try again but with nplc = 1.0
#                dead time is  (duration-2)/duration  (because it only read data for 2 s here (120* 1.0/60))
#       with count = 120, filter=off, source readback disabled, autozeron=off (autorange same as above)
#          takes 2.04 s which means 120/2.04 = 58.8 rdgs/s (about 2% dead time)
#       with count = 120, filter=off, source readback on, autozeron=off (autorange same as above)
#          takes 4.11 s which means 120/4.11 = 29.2 rdgs/s (about 51% dead time. Readback takes 2 reading (source and measure) for every entry)
#       with count = 120, filter=off, source readback off, autozeron=on (autorange same as above)
#          takes 6.24 s which means 120/6.24 = 19.2 rdgs/s (about 68% dead time. Autozero takes 3 reading for every measurement (measurement, zero, reference))
#       with count = 120, filter=off, source readback on, autozeron=on (autorange same as above)
#          takes 8.32 s which means 120/8.32 = 14.4 rdgs/s (about 76% dead time. Or it looks like 4 readings for every measurement)
#       with count = 2, filter=60, source readback on, autozeron=on (autorange same as above)
#          takes 8.32 s which means 120/8.32 = 14.4 rdgs/s (about 76% dead time. Or it looks like 4 readings for every measurement)
#       with count = 2, filter=60, source readback off, autozeron=off (autorange same as above)
#          takes 2.04 s which means 120/2.04 = 58.8 rdgs/s (about 2% dead time)
#
#
#     Now do tests with trigger system
#      NPLC=0.01
#       with autozero off, readback off  (same as above for autorange)
#         smu1.set_avg_count(delay=0, inner_count=100*60, count=1)
#         %time smu1.run_and_wait()
#           took 1.97s  (like above)
#             with readback: 6.76
#             with readback and autozero: 18.9
#             with autozero: 14.2
#            with inner_count=60 and filter=100
#             took 2.00 s. It seems to add about 0.03s.
#         smu1.set_avg_count(delay=0, inner_count=1, count=6000)
#         %time smu1.run_and_wait()
#           took 2.57s  (slower by 25%),      2335 rdgs/s
#             with readback: 7.42,             808 rdgs/s
#             with readback and autozero: 19.6, 306 rdgs/s
#             with autozero: 14.8,              405 rdgs/s
#         Result: the inner_count is the most efficient and is the same as the count without trigger
#
#       with autozero off, readback off  (same as above for autorange)
#        smu1.set_avg_count(delay=2, inner_count='inf')
#        %time smu1.run_and_wait()
#          took 2.02s, read 5275 rdgs, 2611 rdgs/s   (actual I sometimes get 5200 readings with autorange. maybe it does not always switch properly during my tests)
#             with readback: 1682 rdgs,  833 rdgs/s
#             with readback and autozero: 623 rdgs, 308 rdgs/s
#             with autozero: 826 rdgs, 409 rdgs/s
#        Result is a little less efficient than inner_count, close to outer count
#
#       with filter=100, autozero off, readback off  (same as above for autorange)
#        smu1.set_avg_count(delay=2, inner_count='inf')
#        %time smu1.run_and_wait()
#          took 2.02s, read 60*100 rdgs, 2970 rdgs/s
#             with readback: 2.02s, 17*100 rdgs,  841 rdgs/s
#             with readback and autozero: 2.02s, 6*100 rdgs, 297 rdgs/s
#             with autozero: 2.02s, 8*100 rdgs, 396 rdgs/s
#        Result is similar to above.
#
#      NPLC=1.00
#       with autozero off, readback off  (same as above for autorange)
#         smu1.set_avg_count(delay=0, inner_count=120, count=1)
#         %time smu1.run_and_wait()
#           took 2.04s  (like above)
#             with readback: 4.11
#             with readback and autozero: 8.31
#             with autozero: 6.24
#            with inner_count=2 and filter=60
#             took 2.04 s.
#          Got the same results with: smu1.set_avg_count(delay=0, inner_count=1, count=120)
#            maybe with 0.01s more.
#
#       with autozero off, readback off  (same as above for autorange)
#         smu1.set_avg_count(delay=2, inner_count='inf')
#        %time smu1.run_and_wait()
#          took 2.01s, read 118 rdgs, 58.7 rdgs/s
#             with readback: 2.02s, 58 rdgs,  28.7 rdgs/s
#             with readback and autozero: 2.02s, 28 rdgs, 13.9 rdgs/s
#             with autozero: 2.02s, 38 rdgs, 18.8 rdgs/s
#        Result is a little less efficient than inner_count
#
#       with filter=60, autozero off, readback off  (same as above for autorange)
#        smu1.set_avg_count(delay=2, inner_count='inf')
#        %time smu1.run_and_wait()
#          took 2.02s, read 1*60 rdgs, 39.6 rdgs/s
#             with readback: 3.13s, 1*60 rdgs,  19.2 rdgs/s
#             with readback and autozero: 4.17s, 1*60 rdgs, 14.4 rdgs/s
#             with autozero: 5.13s, 1*60 rdgs, 11.7 rdgs/s
#        Result, the 2s delay is after the first measurement is completed
