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

import numpy as np
from collections import OrderedDict, namedtuple
from ctypes import c_float, c_double, c_int8, c_int16, c_int32, c_char

from ..instruments_base import visaInstrumentAsync, visaInstrument,\
                            BaseDevice, scpiDevice, MemoryDevice, ReadvalDev,\
                            ChoiceBase, _general_check, _fromstr_helper, _tostr_helper,\
                            ChoiceStrings, ChoiceMultiple, ChoiceMultipleDep, Dict_SubDevice,\
                            _decode_block_base, make_choice_list,\
                            sleep, locked_calling
from ..instruments_registry import register_instrument

from ..types import StructureImproved

_ChoiceStrings = ChoiceStrings

class ChoiceStrings(_ChoiceStrings):
    def __init__(self, *arg, **kwarg):
        kwarg.update(no_short=True)
        super(ChoiceStrings, self).__init__(*arg, **kwarg)

class lecroy_dict(ChoiceBase):
    def __init__(self, field_names, fmts=int, sep=',', required=None, repeats=None):
        """
        This handles commands that return a list of options like
           opt1,5,opt2,34,opt3,DC
        On reading, they will probably all be present.
        On writing, it is not necessary to give all. Values not given are not
        changed by lecroy instrument.
        field_names is a list of ('SN', 'dict_name'), where SN is the shortname
        used to communicate with the instrument, dict_name is the name
        used for the pyHegel dictionnary. It can also be a list of strings, in
        which case it is used as both SN and dict_name
        'SN' can be '', in which case it should be the first elements of the list.
        and is not named. There can be more than one.
        'SN' are compared in a case insensitive way.
        required is to set the number of required '' parameters. By default
        all of them are, otherwise tell it a number.
        repeats select the '' which will be vectors containing the extra data.
        It can be a single value (index of field_names to repeat) or a (start, stop)
        pair, where stop is included.

        fmts can be a single converter or a list of converters
        the same length as field_names
        A converter is either a type or a (type, lims) tuple
        where lims can be a tuple (min, max) with either one being None
        or a list/object of choices.
        Not that if you use a ChoiceBase object, you only need to specify
        it as the type. It is automatically used as a choice also.

        Based on ChoiceMultiple
        """
        def make_tuple(val):
            if isinstance(val, basestring):
                return (val, val)
            else:
                return val
        field_names = map(make_tuple, field_names)
        self.field_names_sn = [sn.lower() for sn,dn in field_names]
        cnt = 0
        maxlen = len(field_names)
        while cnt<maxlen and self.field_names_sn[cnt] == '':
            cnt += 1
        self.nosn_cnt = cnt
        if '' in self.field_names_sn[cnt:]:
            raise ValueError,'Only the first SNs can be the empty string'
        if len(set(self.field_names_sn[cnt:])) != len(self.field_names_sn[cnt:]):
            raise ValueError,'There is a duplicated SN which is not allowed'
        self.field_names_dn = [dn.lower() for sn,dn in field_names]
        self.field_names = self.field_names_dn # needed for Dict_SubDevice
        if len(set(self.field_names_dn)) != len(self.field_names_dn):
            raise ValueError,'There is a duplicated dict_name which is not allowed'
        if not isinstance(fmts, (list, np.ndarray)):
            fmts = [fmts]*len(field_names)
        fmts_type = []
        fmts_lims = []
        for f in fmts:
            if not isinstance(f, tuple):
                if isinstance(f, ChoiceBase):
                    f = (f,f)
                else:
                    f = (f, None)
            fmts_type.append(f[0])
            fmts_lims.append(f[1])
        self.fmts_type = fmts_type
        self.fmts_lims = fmts_lims
        self.sep = sep
        if required is None:
            required = cnt
        self.required = required
        if repeats is not None:
            if not isinstance(repeats, (tuple, list)):
                repeats = (repeats, repeats)
        else:
            repeats = (-1, -2)
        self.repeats = repeats
    def __call__(self, fromstr):
        v_base = fromstr.split(self.sep)
        if len(v_base) < self.required:
            raise ValueError, 'Returned result (%s) is too short.'%fromstr
        names = []
        fmts = []
        vals = []
        maxlen = len(v_base)
        cnt = min(maxlen, self.nosn_cnt)
        cycle = 0
        N = self.repeats[1]+1-self.repeats[0]
        full_elem = 2*len(self.field_names) - self.nosn_cnt
        if N!=0:
            Ncycles = (len(v_base) - (full_elem-N))/N
            if Ncycles < 1:
                Ncycles = 1
        else:
            Ncycles = 0
        cnt = cnt-N+Ncycles*N
        for i in range(cnt):
            j = i - N*cycle
            if j>=self.repeats[0] and j<=self.repeats[1] and cycle<Ncycles:
                if cycle != 0:
                    vals[j].append(v_base[i])
                else:
                    names.append(self.field_names_dn[j])
                    fmts.append(self.fmts_type[j])
                    vals.append([v_base[i]])
            else:
                names.append(self.field_names_dn[j])
                fmts.append(self.fmts_type[j])
                vals.append(v_base[i])
            if j == self.repeats[1]:
                cycle += 1
        v_base = v_base[cnt:]
        vals.extend(v_base[1::2])
        for n in v_base[::2]:
            i = self.field_names_sn.index(n.lower())
            names.append(self.field_names_dn[i])
            fmts.append(self.fmts_type[i])
        v_conv = []
        v_names = []
        for k, val, fmt in zip(names, vals, fmts):
            if isinstance(fmt, ChoiceMultipleDep):
                fmt.set_current_vals(dict(zip(v_names, v_conv)))
            if isinstance(val, list):
                v_conv.append(map(lambda v: _fromstr_helper(v, fmt), val))
            else:
                v_conv.append(_fromstr_helper(val, fmt))
            v_names.append(k)
        return OrderedDict(zip(names, v_conv))
    # TODO handle repeats for tostr
    def tostr(self, fromdict=None, **kwarg):
        # we assume check (__contains__) was called so we don't need to
        # do fmt.set_current_vals again
        if fromdict is None:
            fromdict = kwarg
        fromdict = fromdict.copy() # don't change incomning argument
        ret = []
        for i in range(self.nosn_cnt):
            key = self.field_names_dn[i]
            try:
                val = fromdict.pop(key)
            except KeyError:
                if i < self.required:
                    raise KeyError, 'The field with key "%s" is always required'%key
                else:
                    break
            s = _tostr_helper(val, self.fmts_type[i])
            ret.append(s)
        for k,v in fromdict.iteritems():
            i = self.field_names_dn.index(k)
            fmt = self.fmts_type[i]
            name = self.field_names_sn[i]
            ret.append(name + self.sep + _tostr_helper(v, fmt))
        ret = self.sep.join(ret)
        return ret
    def __contains__(self, x): # performs x in y; with y=Choice(). Used for check
        for i in range(self.required):
            key = self.field_names_dn[i]
            if key not in x:
                raise KeyError, 'The field with key "%s" is always required'%key
        for k, v in x.iteritems():
            i = self.field_names_dn.index(k)
            fmt = self.fmts_type[i]
            lims = self.fmts_lims[i]
            try:
                if isinstance(fmt, ChoiceMultipleDep):
                    fmt.set_current_vals(x)
                _general_check(x[k], lims=lims)
            except ValueError as e:
                raise ValueError('for key %s: '%k + e.args[0], e.args[1])
        return True
    def __repr__(self):
        r = ''
        first = True
        for k, lims in zip(self.field_names_dn, self.fmts_lims):
            if not first:
                r += '\n'
            first = False
            r += 'key %s has limits %r'%(k, lims)
        return r


"""
Unimplemented commands that could be interesting

     ACQUISITION — TO CONTROL WAVEFORM CAPTURE
  ASET AUTO_SETUP Adjusts vertical, timebase and trigger parameters for signal display.
  COMB COMBINE_CHANNELS Controls the channel interleaving function.
SEQ SEQUENCE Controls the sequence mode of acquisition.
*TRG *TRG Executes an ARM command.
WAIT WAIT Prevents new command analysis until current acquisition completion.
     CURSOR — TO PERFORM MEASUREMENTS
  CRMS CURSOR_MEASURE Specifies the type of cursor or parameter measurement for display.
  CRST CURSOR_SET Allows positioning of any cursor.
  CRVA? CURSOR_VALUE? Returns the values measured by the specified cursors for a given trace.
  CRS CURSORS Sets the cursor type.
  PACU PARAMETER_CUSTOM Controls parameters with customizable qualifiers.
  PF PASS_FAIL Sets up the Pass / Fail system.
  PFDO PASS_FAIL_DO Defines outcome and actions for the Pass/Fail system.
  PECS PER_CURSOR_SET Positions one of the six independent cursors.
      DISPLAY — TO DISPLAY WAVEFORMS
  HMAG HOR_MAGNIFY Horizontally expands the selected expansion trace.
  HPOS HOR_POSITION Horizontally positions the intensified zone’s center on the source trace.
  PERS PERSIST Enables or disables the Persistence Display mode.
  PECL PERSIST_COLOR Controls color rendering method of persistence traces.
  PELT PERSIST_LAST Shows the last trace drawn in a persistence data map.
  PESA PERSIST_SAT Sets the color saturation level in persistence.
  PESU PERSIST_SETUP Selects display persistence duration in Persistence mode.
  VMAG VERT_MAGNIFY Vertically expands the specified trace.
  VPOS VERT_POSITION Adjusts the vertical position of the specified trace.
      FUNCTION — TO PERFORM WAVEFORM MATHEMATICAL OPERATIONS
  CLM CLEAR_MEMORY Clears the specified memory.
     MISCELLANEOUS
  COUT CAL_OUTPUT Sets the type of signal put out at the CAL connector.
  *TST? *TST? Performs internal self-test.
      SAVE/RECALL SETUP — TO PRESERVE AND RESTORE FRONT PANEL SETTINGS
  PNSU PANEL_SETUP Complements the *SAV/*RST commands.
  *RCL *RCL Recalls one of five non-volatile panel setups.
  RCPN RECALL_PANEL Recalls a front panel setup from mass storage.
  *RST *RST Initiates a device reset.
  *SAV *SAV Stores the current state in non-volatile internal memory.
  STPN STORE_PANEL Stores the complete front panel setup on a mass-storage file.
      STATUS — TO OBTAIN STATUS INFORMATION AND SET UP SERVICE REQUESTS
ALST? ALL_STATUS? Reads and clears the contents of all (but one) of the status registers.
*CLS *CLS Clears all the status data registers.
CMR? CMR? Reads and clears the contents of the CoMmand error Register (CMR).
DDR? DDR? Reads and clears the Device-Dependent error Register (DDR).
*ESE *ESE Sets the standard Event Status Enable (ESE) register.
*ESR? *ESR? Reads and clears the Event Status Register (ESR).
EXR? EXR? Reads and clears the EXecution error Register (EXR).
INE INE Sets the INternal state change Enable register (INE).
INR? INR? Reads and clears the INternal state change Register (INR).
IST? IST? Individual STatus reads the current state of IEEE 488.
*OPC *OPC Sets to true the OPC bit (0) in the Event Status Register (ESR).
*PRE *PRE Sets the PaRallel poll Enable register (PRE).
*SRE *SRE Sets the Service Request Enable register (SRE).
*STB? *STB? Reads the contents of IEEE 488.
  *WAI *WAI WAIt to continue (required by IEEE 488)
     WAVEFORM TRANSFER — TO PRESERVE AND RESTORE WAVEFORMS
  STO STORE Stores a trace in one of the internal memories M1–4 or mass storage.
  STST STORE_SETUP Sets up waveform storage
"""

# get structure with print osc.ask('TeMPLate?')

class time_stamp(StructureImproved):
    _fields_=[("seconds", c_double),
              ("minutes", c_int8),
              ("hours", c_int8),
              ("days", c_int8),
              ("months", c_int8),
              ("year", c_int16),
              ("unused", c_int16)]
    def __repr__(self):
        return '%04d-%02d-%02d %02d:%02d:%018.15f'%(self.year, self.months,
                                              self.days, self.hours,
                                              self.minutes, self.seconds)

class WAVEDESC(StructureImproved):
    _pack_ = 2
    _fields_ = [("DESCRIPTOR_NAME", c_char*16),
              ("TEMPLATE_NAME", c_char*16),
              ("COMM_TYPE", c_int16),
              ("COMM_ORDER", c_int16),
              ("WAVE_DESCRIPTOR", c_int32),
              ("USER_TEXT", c_int32),
              ("RES_DESC1", c_int32),
              ("TRIGTIME_ARRAY", c_int32),
              ("RIS_TIME_ARRAY", c_int32),
              ("RES_ARRAY1", c_int32),
              ("WAVE_ARRAY_1", c_int32),
              ("WAVE_ARRAY_2", c_int32),
              ("RES_ARRAY2", c_int32),
              ("RES_ARRAY3", c_int32),
              ("INSTRUMENT_NAME", c_char*16),
              ("INSTRUMENT_NUMBER", c_int32),
              ("TRACE_LABEL", c_char*16),
              ("RESERVED1", c_int16),
              ("RESERVED2", c_int16),
              ("WAVE_ARRAY_COUNT", c_int32),
              ("PNTS_PER_SCREEN", c_int32),
              ("FIRST_VALID_PNT", c_int32),
              ("LAST_VALID_PNT", c_int32),
              ("FIRST_POINT", c_int32),
              ("SPARSING_FACTOR", c_int32),
              ("SEGMENT_INDEX", c_int32),
              ("SUBARRAY_COUNT", c_int32),
              ("SWEEPS_PER_ACQ", c_int32),
              ("POINTS_PER_PAIR", c_int16),
              ("PAIR_OFFSET", c_int16),
              ("VERTICAL_GAIN", c_float),
              ("VERTICAL_OFFSET", c_float),
              ("MAX_VALUE", c_float),
              ("MIN_VALUE", c_float),
              ("NOMINAL_BITS", c_int16),
              ("NOM_SUBARRAY_COUNT", c_int16),
              ("HORIZ_INTERVAL", c_float),
              ("HORIZ_OFFSET", c_double),
              ("PIXEL_OFFSET", c_double),
              ("VERTUNIT", c_char*48),
              ("HORUNIT", c_char*48),
              ("HORIZ_UNCERTAINTY", c_float),
              ("TRIGGER_TIME", time_stamp),
              ("ACQ_DURATION", c_float),
              ("RECORD_TYPE", c_int16),
              ("PROCESSING_DONE", c_int16),
              ("RESERVED5", c_int16),
              ("RIS_SWEEPS", c_int16),
              ("TIMEBASE", c_int16),
              ("VERT_COUPLING", c_int16),
              ("PROBE_ATT", c_float),
              ("FIXED_VERT_GAIN", c_int16),
              ("BANDWIDTH_LIMIT", c_int16),
              ("VERTICAL_VERNIER", c_float),
              ("ACQ_VERT_OFFSET", c_float),
              ("WAVE_SOURCE", c_int16)]

    def listall(self):
        return [(name, getattr(self,name)) for name, t in self._fields_]

class USERTEXT(StructureImproved):
    _fields_ = [("TEXT", c_char*160)]

class TRIGTIME(StructureImproved):
    _fields_ = [("TRIGGER_TIME", c_double),
              ("TRIGGER_OFFSET", c_double)]

class RISTIME(StructureImproved):
    _fields_ = [("RIS_OFFSET", c_double)]

# The structure has an int which is the 0 based index into the following lists
#  chosen by remote command COMM_FORMAT
_COMM_TYPE_opt = ['byte', 'word']
_COMM_ORDER_opt = ['HI_first_big-endian', 'LO_first_little-endian']

_RECORD_TYPE_opt = ['single_sweep', 'interleaved', 'histogram', 'graph',
                    'filter_coefficient', 'complex', 'extrema', 'sequence_obsolete',
                    'centered_RIS', 'peak_detect']

_PROCESSING_DONE_opt = ['no_processing', 'fir_filter', 'interpolated', 'sparsed',
                        'autoscaled', 'no_result', 'rolling', 'cumulative']

# s/div
_TIMEBASE_opt = make_choice_list([1, 2, 5], -12, 3)
_TIMEBASE_opt_extra = {100:'external'}

# V/div
_FIXED_VERT_GAIN_opt = make_choice_list([1,2,5],-6,3)[:-2]

_BANDWIDTH_LIMIT_opt = ['off', 'on']

_WAVE_SOURCE_opt = ['C1', 'C2', 'C3', 'C4']
_WAVE_SOURCE_opt_extra = {9:'unknown'}


class _conv_stripUnit(object):
    def __init__(self, typ):
        self.typ = typ
    def __call__(self, fromstr):
        return _fromstr_helper(fromstr.split(' ',1)[0], self.typ)
    def tostr(self, val):
        return _tostr_helper(val, self.typ)
float_stripUnit = _conv_stripUnit(float)

class _conv_undef(object):
    def __init__(self, typ=float, undef_val=np.NaN, undef_str='UNDEF'):
        self.typ = typ
        self.undef_val = undef_val
        self.undef_str = undef_str
    def __call__(self, fromstr):
        if self.undef_str == fromstr:
            return self.undef_val
        return _fromstr_helper(fromstr, self.typ)
    def tostr(self, val):
        if val == self.undef_val:
            return self.undef_str
        return _tostr_helper(val, self.typ)
float_undef = _conv_undef()

class _conv_upper(object):
    def __init__(self, typ):
        self.typ = typ
    def __call__(self, fromstr):
        return _fromstr_helper(fromstr, self.typ)
    def tostr(self, val):
        return _tostr_helper(val, self.typ).upper()
str_upper = _conv_upper(str)

class ChoiceDict(ChoiceBase):
    """
    Assigns python values to instrument strings
     choices_dict={true:'ON', false:'OFF'}
    Use a dictionnary that can be reversed (values are not mutable)
    normalize to compare internally in smallcaps
    """
    def __init__(self, choices_dict, normalize=True):
        self.choices_dict = choices_dict
        self.normalize = normalize
        if normalize:
            conv = lambda s: s.lower()
        else:
            conv = lambda s: s
        self.rev_choices = {conv(v):k for k,v in choices_dict.iteritems()}
    def __call__(self, input_str):
        if self.normalize:
            input_str = input_str.lower()
        return self.rev_choices[input_str]
    def tostr(self, val):
        return self.choices_dict[val]
    def __repr__(self):
        return repr(self.choices_dict.keys())
    def __contains__(self, val):
        return val in self.choices_dict.keys()

bool_lecroy = ChoiceDict({True:'ON', False:'OFF'})
bool_lecroy_vbs = ChoiceDict({True:'1', False:'0'})

waveformdataType = namedtuple('waveformdataType', 'header data1 data2 trigtime ristime usertext')
class waveformdata(object):
    def __init__(self, return_only_header=False):
        self.return_only_header = return_only_header
    def __call__(self, inputstr):
        ds =inputstr.split(',', 1) # strip DESC, TEXT, TIME, DAT1, DAT2, ALL
        fullblock = _decode_block_base(ds[1])
        header = WAVEDESC.from_buffer_copy(fullblock)
        if self.return_only_header:
            return header
        ptr = header.WAVE_DESCRIPTOR
        w = header.USER_TEXT
        usertext = fullblock[ptr:ptr+w]
        ptr += w
        w = header.RES_DESC1
        if header.RES_DESC1 or header.RES_ARRAY1 or header.RES_ARRAY2 or header.RES_ARRAY3:
            raise ValueError, 'At least one reserved data arrays has non-zero size.'
        ptr += w
        w = header.TRIGTIME_ARRAY
        trigtime = fullblock[ptr:ptr+w]
        ptr += w
        w = header.RIS_TIME_ARRAY
        ristime = fullblock[ptr:ptr+w]
        ptr += w
        w = header.RES_ARRAY1
        ptr += w
        w = header.WAVE_ARRAY_1
        data1 = fullblock[ptr:ptr+w]
        ptr += w
        w = header.WAVE_ARRAY_2
        data2 = fullblock[ptr:ptr+w]
        data_type = [np.int8, np.int16][header.COMM_TYPE]
        if data1:
            data1 = np.fromstring(data1, data_type)
        if data2:
            data2 = np.fromstring(data1, data_type)
        if trigtime:
            trigtime = np.fromstring(trigtime, [('trig_time', np.float64), ('time_offset', np.float64)])
        if ristime:
            ristime = np.fromstring(ristime, np.float64)
        return waveformdataType(header, data1, data2, trigtime, ristime, usertext)
    def tostr(self, val):
        pass

class lecroy_vbs_scpi(scpiDevice):
    def __init__(self, setstr=None, getstr=None, autoget=True, write_quotes=True, *arg, **kwarg):
        if getstr is None and autoget:
            getstr = setstr
            if write_quotes:
                setstr = setstr+'="{val}"'
            else:
                setstr = setstr+'={val}'
        kwarg.update(ask_write_opt=dict(use_vbs=True))
        super(lecroy_vbs_scpi,self).__init__(setstr, getstr, *arg, autoget=autoget, **kwarg)

#######################################################
##    LeCroy WaveMaster 820Zi-A
#######################################################

#@register_instrument('LECROY', 'WM820ZI-A', '7.2.1', alias='WM820ZI-A WaveMaster scope')
#@register_instrument('LECROY', 'WM820ZI-A', '7.8.0', alias='WM820ZI-A WaveMaster scope')
@register_instrument('LECROY', 'WM820ZI-A', alias='WM820ZI-A WaveMaster scope')
class lecroy_wavemaster(visaInstrumentAsync):
    """
    This instrument controls a LeCroy WaveMaster 820Zi-A
     To use this instrument, the most useful devices are probably:
       fetch
       readval
       snap_png
    To use sweep or record (or run_and_wait method) you shoud use the
      set_trigmode method first.
    When the processing stage on the scope takes a long time, it might produces
    timeout on some devices. To avoid those you can increase the timeout by setting
    the set_timeout attribute (which is in seconds).
    To work properly, make sure the instrument is set to use LXI(VXI11) as remote
    and not TCPIP(VICP).
    """
    def __init__(self, visa_addr):
        # BUG: The SRQ for this intrument does not work
        # as of version 7.2.1.0
        # SRQ still does not work in version 7.8.0 (The instruments never connects to this application
        # open Interrupt channel port)
        self._trigmode_mode = None
        self._trigmode_avgn = None
        super(lecroy_wavemaster, self).__init__(visa_addr, poll=True)
        response = self.ask('Reference_CLocK?')
        if response in  ['WARNING : CURRENT REMOTE CONTROL INTERFACE IS TCPIP',
                         'WARNING : CURRENT REMOTE CONTROL INTERFACE IS LSIB',
                         'WARNING : CURRENT REMOTE CONTROL INTERFACE IS OFF']:
            raise RuntimeError('Make sure to set Utilities Setup/Remote to LXI(VXI11)')
    def init(self, full=False):
        self.write('Comm_ORDer LO') # can be LO or HI: LO=LSB first
        self.write('Comm_ForMaT DEF9,WORD,BIN') #DEF9=IEEE 488.2 block data, WORD (default is BYTE)
        self.write('Comm_HeaDeR OFF') #can be OFF, SHORT, LONG. OFF removes command echo and units
        super(lecroy_wavemaster, self).init(full=full)
    def _current_config(self, dev_obj=None, options={}):
        ch_info = []
        orig_ch = self.current_channel.getcache()
        orig_ich = self.current_input_channel.getcache()
        orig_tch = self.current_trig_channel.getcache()
        orig_fch = self.current_func_channel.getcache()
        for ch in ['C%i'%i for i in range(1,5)]:
            self.current_input_channel.set(ch)
            self.current_channel.set(ch)
            self.current_trig_channel.set(ch)
            xx =self._conf_helper('trace_en', 'input_sel', 'input_invert', 'volts_div', 'attenuation',
                                  'coupling', 'offset', 'offset_constant_mode',
                                  'input_enh_resol', 'input_deskew', 'input_avg', 'interpolation')
            # TODO, also deal with trigger channels LINE, EX, EX10, ...
            xx +=self._conf_helper('trig_coupling', 'trig_level', 'trig_slope')
            ch_info.append(ch+'=<'+','.join(xx)+'>')
        # TODO also find a way to do this for F9-F12 and Z5-Z12
        for ch in ['F%i'%i for i in range(1,9)] + ['Z%i'%i for i in range(1,5)]:
            self.current_channel.set(ch)
            self.current_func_channel.set(ch)
            xx =self._conf_helper('trace_en', 'function_def')
            ch_info.append(ch+'=<'+','.join(xx)+'>')
        self.current_func_channel.set(orig_fch)
        self.current_trig_channel.set(orig_tch)
        self.current_input_channel.set(orig_ich)
        self.current_channel.set(orig_ch)
        para_mode_type = self.parameter_mode_type.get()
        para_info = self._conf_helper('parameter_mode')
        if para_mode_type != 'off':
            para_info += self._conf_helper('parameter_stat_params')
            para_info += 'Pn_en=%s'%[self.trace_enV.get(ch='P%i'%i) for i in range(1,13)]
        base = self._conf_helper('RIS_mode_en', 'reference_clock', 'sample_clock',
                                 'max_rate_memory', 'sample_rate', 'sample_rate_used',
                                 'bandwith_limit',
                                 'trig_select', 'trig_pos_s', 'time_div', 'trig_pattern',
                                 'lecroy_options', 'memory_size', options)
        return ch_info + base
    def arm_acquisition(self):
        """ This arms the oscilloscope """
        self.write('ARM_acquisition')
    def force_trigger(self):
        """
        Starts an acquisition
        """
        self.write('FoRce_TRigger')
    def stop_trig(self):
        """
        The same as pressing stop
        """
        self.write('STOP')
    def single_trig(self):
        """
        The same as pressing single
        """
        self.trig_mode.set('STOP')
        self.arm_acquisition()
        self.force_trigger()
    @locked_calling
    def find_all_active_channels(self):
        orig_ch = self.current_channel.get()
        ret = []
        for c in ['C1', 'C2', 'C3', 'C4']:
            if self.trace_en.get(ch=c):
                ret.append(c)
        self.current_channel.set(orig_ch)
        return ret
    def _fetch_ch_helper(self, ch):
        if ch is None:
            ch = self.find_all_active_channels()
        if not isinstance(ch, (list)):
            ch = [ch]
        return ch
    def _fetch_getformat(self, **kwarg):
        xaxis = kwarg.get('xaxis', True)
        ch = kwarg.get('ch', None)
        ch = self._fetch_ch_helper(ch)
        if xaxis:
            multi = ['time(s)']
        else:
            multi = []
        for c in ch:
            multi.append('ch_%s'%c)
        fmt = self.fetch._format
        multi = tuple(multi)
        fmt.update(multi=multi, graph=[], xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_getdev(self, ch=None, xaxis=True, raw=False):
        """
           Options available: ch, xaxis
            -ch:    a single value or a list of values for the channels to capture
                    a value of None selects all the active ones from C1 to C4.
                    If obtaining more than one channels, they should have the same xaxis
            -xaxis: Set to True (default) to return the timebase as the first colum
            -raw: Set to true to return the vertical values as raw integers, otherwise
                  they are converted floats
        """
        # TODO handle complex ffts...
        ch = self._fetch_ch_helper(ch)
        ret = []
        first = True
        for c in ch:
            data = self.data.get(ch=c)
            header = data.header
            if xaxis and first:
                first = False
                ret = [header.HORIZ_INTERVAL*np.arange(header.WAVE_ARRAY_COUNT) + header.HORIZ_OFFSET]
            if raw:
                y = data.data1
            else:
                y = data.data1*header.VERTICAL_GAIN - header.VERTICAL_OFFSET
            ret.append(y)
        ret = np.asarray(ret)
        if ret.shape[0]==1:
            ret=ret[0]
        return ret
    def vbs_write(self, command):
        """
        This allows sending automation commands like
         'app.Acquisition.C1.VerScale=0.5'
         'app.Acquisition.C1.VerScale = 0.5'
        see also vbs_ask
        """
        self.write("VBS '%s'"%command)
    def vbs_ask(self, command):
        """
        This allows reading of automation values like
         'app.Acquisition.C1.VerScale'
        see also vbs_write
        """
        return self.ask("VBS? 'Return=%s'"%command)
    def write(self, command, use_vbs=False):
        if use_vbs:
            self.vbs_write(command)
        else:
            super(lecroy_wavemaster, self).write(command)
    def ask(self, command, raw=False, use_vbs=False):
        if use_vbs:
            return self.vbs_ask(command)
        else:
            return super(lecroy_wavemaster, self).ask(command, raw=raw)
    def _snap_png_getdev(self, area='dso', white_back=False):
        """
        Use like this: get(wave.snap_png, filename='testname.png')
        The .png extensions is optional. It will be added if necessary.
          Note that we use the hardcoded file: D:\\HARDCOPY\\__pyhegel__.png
          so multiple simultaneous calls could conflict between them.
        Options:
            area: can be 'dso' for scope window (Default).
                         'grid' for only the results part
                         'full' for the full desktop view.
            white_back: set to True to replace the black background with white.
        """
        # DEST can be PRINTER, CLIPBOARD, EMAIL, FILE, REMOTE
        # DEV can be PSD BMP BMPCOMP JPEG PNG TIFF
        # FORMAT can be LANDSCAPE PORTRAIT  # mostly for PRINTER dest
        # BCKG can be BLACK WHITE
        # AREA can be GRIDAREAONLY, DSOWINDOW, FULLSCREEN
        # PRINTER to give printer name for PRINTER dest only
        # DIR/FILE for dir and file for FILE dest only. Note that file is autoincremented
        oldsetup = self.ask('HardCopy_SetUp?')
        #print oldsetup
        cmd = 'HardCopy_SetUp DEST,"FILE",DEV,{dev}, BCKG,{bckg}, DIR,"{dir}", FILE,"{file}", AREA,{area}'
        dirname = r'D:\HARDCOPY'
        filename = '__pyHegel__.png'
        fullpath = dirname+ '\\' +filename
        area = {'dso':'DSOWINDOW', 'full':'FULLSCREEN', 'grid':'GRIDAREAONLY'}[area]
        if white_back:
            back = 'WHITE'
        else:
            back = 'BLACK'
        # first erase the file
        self.vbs_write('app.SaveRecall.Utilities.Filename = "%s"'%fullpath)
        self.vbs_write('app.SaveRecall.Utilities.DeleteFile')
        # Now set it up, and dump it
        self.write(cmd.format(dev='PNG', bckg=back, dir=dirname, file=filename, area=area))
        self.write('SCreen_DumP')
        # TODO wait for completion: *INR bit 1
        self.write('HardCopy_SetUp '+oldsetup)
        # Download the file
        data = self.ask("TRansfer_FiLe? DISK,HDD,FILE,'%s'"%fullpath, raw=True)
        #print 'CRC, A%sA'%data[-9:-1]
        return _decode_block_base(data)[:-8] # remove CRC at end of data block
    def force_cal(self):
        self.ask('*cal?')
    def clear_sweeps(self):
        """ This restarts cummalive processing functions like averages, histogram, persistence"""
        self.write('CLear_SWeeps')
    def reset_function(self, ch):
        """ This resets the calculation on a particular channel F1-F12. ch is the number"""
        self.write('F%i:Function_ReSeT'%ch)
    def delete_parameter(self, ch):
        """ This deletes the custom setup for P1-P12. ch is the number, or 'all' to delete all channels"""
        if ch=='all':
            self.write('PArameter_CLr')
        else:
            self.write('PArameter_DeLete %i'%ch)
    def buzz(self):
        self.write('BUZZer BEEP')
    def histo_auto_range(self, ch=None):
        """ Adjust the range and center of an histogram. For F1-F12 """
        if ch is None:
            ch = self.current_channel.getcache()
        self.write('%s:Find_Ctr_Range'%ch)
    def message(self, msg=''):
        """ Will show msg on the message field at bottom of instrument. Not message clears line."""
        self.write('MeSsaGe "%s"'%msg)
    def get_error(self):
        errors = self.ask('Comm_HeLP_Log? CLR').strip('"').splitlines()
        #if errors == []:
        #    errors = ['No errors']
        return errors
    def _inspect(self, ch='C1', info='wavedesc', data_fmt=None, do_print=True):
        """
        Inspect the data structures returned from channel ch.
        when do_print=True (default) the result is displayed on the screen
        otherwise the result is returned as a string.
        info can be:
            'wavedesc': default. This shows all the structure info
            any of the wavedesc field names: only shows that field
            'data_array_1': shows the data_array_1
            'data_array_2': shows the data_array_2
            'simple': shows data_array_1
            'dual': shows both data_array 1 and 2
            'ristime':  shows the ristime array
            'trigtime': show the trigtime array
        data_fmt is only usefull for data arrays and can be 'byte', 'word', or 'float'
        """
        extra = ''
        if data_fmt is not None:
            extra = ',' + data_fmt
        ret = self.ask('%s:INSPect? %s%s'%(ch, info, extra))
        if do_print:
            print ret
        else:
            return ret
    _trigmodes = ['Normal', 'Auto', 'NormalStop', 'AutoStop', 'Single', 'SingleForce']
    def set_trigmode(self, mode='Single', avgn=1, ch='auto', quiet=False):
        if mode not in self._trigmodes+['Stop', 'SingleForce_noClear']:
            raise ValueError('Invalid mode used.')
        avgn = int(avgn)
        if avgn < 1:
            raise ValueError('Invalid avgn (<1)')
        if avgn > 1:
            self._async_detect_acqn_find_ch(ch=ch) # this overrides _trigmode_mode and avgn
        self._trigmode_mode = mode
        self._trigmode_avgn = avgn
        if not quiet:
            if avgn > 1:
                ch = self._trigmode_avgn_ch
                print 'mode is %s, avgn is %i, acqn channel is %s'%(mode, avgn, ch)
            else:
                print 'mode is %s, avgn is %i'%(mode, avgn)
    set_trigmode.__doc__ =         """
        mode: one of %s
              where for all modes except Normal and Auto the acquisition is stopped before transferring
              Note that when the scope is processing, stopping or transferring data is delayed until the
              processing is done. So if processing is long (and especially if acquisition is short) you
              should probably use Single to prevent timeouts.
              SingleForce will start a single acquisition and force the trigger (so in a way
              it is the Single equivalent of Auto, if auto never gets a trigger)
        avgn: the number of averages to wait for. The acquisition will wait until
              this many acquisition have been performed.
        ch:   The channel to use to detect the acquisition number (for averaging).
              can be 'auto' or any of C1-C4, F1-F12, Z1-Z12, P1-P12
              With auto, it tries and picks the first channel it thinks will work
              among C1-C4, F1-F12, Z1-Z12, P12-P1 in that order and if they are enabled.
              Only applies when avgn>2
              And it will perform 2 acquisition to check find or check the channel
              actually works for getting the acquisition number.
              Note that for Ps to work properly, you need to choose a proper function.
              Functions like freq can return multiple result on a single curve (and could
              accidently screw up the detection code). Function like npoints should work
              as long as they apply on a non averaged curve (for average curve the parameter
              statistics don't update properly.)
        """% _trigmodes
    def _async_trigger_helper_rearm(self):
        self.arm_acquisition()
        if self._trigmode_mode.startswith('SingleForce'):
            self.force_trigger()
    def _async_trigger_helper(self):
        mode = self._trigmode_mode
        if self._trigmode_mode is None or self._trigmode_avgn is None:
            print 'set_trigmode was not executed. Using default values.'
            self.set_trigmode(quiet=False)
        mode = self._trigmode_mode
        clearit = True
        noclear_str = '_noClear'
        if mode.endswith(noclear_str):
            mode = mode[:-len(noclear_str)]
            clearit = False
        if mode == 'Stop':
            self.stop_trig()
        if clearit:
        #if mode != 'SingleForce_noClear':
            self.clear_sweeps() # This resets averages and restart the current acquisition
        #self._async_detect_acqn_find_ch()
        # Here we assume that wait will only return when all the acquisition and calculation is done
        if mode in ['Single', 'SingleForce']:
            self._async_trigger_helper_rearm()
        elif mode in ['Auto', 'AutoStop']:
            self.trig_mode.set('AUTO')
        elif mode in ['Normal', 'NormalStop']:
            self.trig_mode.set('NORM')
        # There is a wait with a timeout. Don't use it here
        # If a wait is started after a clear_sweep it makes the
        # scope wait during the trigger/acquisition before doing any other
        # operation (read/write). After a triggers comes in, it will no longer
        # wait for triggers....
        # But the timeout is uncessary. Just physically pressing the stop button
        # makes it go back (sending the stop command won't work)
        #  to have the remote stop command work, does require setting a timeout
        #  however I don't know how long it should be.
        # Wait only seems to work with Single and on the first trigger of Normal/auto
        #  after clear_sweeps
        # make wait timeout after 10 min
        # match this entry with the one in _async_detect
        self.write('WAIT 600;*OPC')
        #self.ask("vbs? 'app.WaitUntilIdle 30'") # This not any better, only blocks during processing (also limited by visa timeout)
    def _async_detect_acqn_find_ch(self, ch='auto'):
        self._trigmode_mode = 'Stop'
        self._trigmode_avgn = 1
        self.run_and_wait()
        self._trigmode_mode = 'SingleForce_noClear'
        self._trigmode_avgn = 1
        self.run_and_wait()
        self.run_and_wait()
        sleep(1)
        ch = ch.upper()
        channels = ['C%i'%i for i in range(1,5)] +\
                     ['F%i'%i for i in range(1,13)] +\
                     ['Z%i'%i for i in range(1,13)]
        channelsP = ['P%i'%i for i in range(1,13)]
        if ch != 'AUTO':
            if ch not in channels and ch not in channelsP:
                raise ValueError('Invalid choice of ch for acquisition number detection')
            if self._async_detect_acqn(ch=ch) != 2:
                raise RuntimeError('Selected ch for acquisition detection is not usable (it does not seem to be incremented)')
            self._trigmode_avgn_ch = ch
            return
        # we have auto mode, try the channels
        for ch in channels:
            # only channels that have averaging turned on will return
            # 0 after clear and increase afterwards, otherwise they return always 1
            # BUG: Also some channels, when not displayed, behave weirdly. It is like they sometimes cause
            #  a trigger/clear. So only check enable channels
            if self.trace_enV.get(ch=ch) and self._async_detect_acqn(ch=ch) == 2:
                self._trigmode_avgn_ch = ch
                return
        if self.parameter_mode_type.get() != 'off':
            para_l = self.parameter_stat_all_data.get(stat='sweeps')[::-1]
            for i, p in enumerate(para_l):
                if p == 2:
                    self._trigmode_avgn_ch = 'P%i'%(12-i)
                    return
        raise RuntimeError('Could not find a ch to use for acquisition number detection')
    def _async_detect_acqn(self, ch=None):
        # Note that C,F and Z channels that can't count, always return 1 (even after a clear sweep)
        if ch is None:
            ch = self._trigmode_avgn_ch
        if not isinstance(ch, basestring) or len(ch) < 2:
            raise RuntimeError('The channel used for async detect of acquisition number is invalid')
        if ch[0] in ['C', 'F', 'Z']:
            return self.data_header.get(ch=ch).SWEEPS_PER_ACQ
        elif ch[0] == 'P':
            return self.parameter_stat_ch.get(ch=int(ch[1:]))['sweeps']
        else:
            raise RuntimeError('The channel used for async detect of acquisition number is invalid')
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        ret = super(lecroy_wavemaster, self)._async_detect(max_time)
        if not ret:
            # This cycle is not finished
            return ret
        # cycle is finished, check acquisition numbers
        avgn = self._trigmode_avgn
        mode = self._trigmode_mode
        if avgn > 1:
            n = self._async_detect_acqn()
            if n < avgn:
                if mode in ['Single', 'SingleForce', 'SingleForce_noClear']:
                    self._async_trigger_helper_rearm()
                self._async_statusLine('scope iter %i of %i'%(n, avgn))
                # TODO find a wait arround this WAIT. Here it does absolutelly nothing
                #  and *OPC returns quickly (for AUTO and NORM). For Single it works fine.
                self.write('WAIT;*OPC')
                return False
        if mode in ['AutoStop', 'NormalStop']:
            self.stop_trig()
            # Note that this does not stop processing.
            # The stop will occur after processing.
            # To pause/restart processing use
            #   self.write('app.ProcessingResume', use_vbs=True)
            #   self.write('app.ProcessingResume', use_vbs=True)
        return True
    def _trace_enV_getdev(self, ch=None):
        # BUG: This device is needed because trace_en currently only works on
        # C1-C4, F1-F8, Z1-Z4, M1-M4
        # This version works on all of them
        if ch is None:
            ch = self.current_channel.getcache()
        sel = dict(C='Acquisition', F='Math', Z='Zoom', P='Measure')
        section = sel[ch[0]]
        ret = self.ask('app.{section}.{ch}.View'.format(section=section, ch=ch), use_vbs=True)
        return bool(int(ret))
    def _create_devs(self):
        self._devwrap('snap_png', autoinit=False)
        self.snap_png._format['bin']='.png'
        self.autocal_en = scpiDevice('Auto_CALibrate', choices=bool_lecroy)
        self.display_en = scpiDevice('DISPlay', choices=bool_lecroy)
        self.lecroy_options = scpiDevice(getstr='*OPT?')
        self.reference_clock = scpiDevice('Reference_CLocK', choices=_ChoiceStrings('INTernal', 'EXTernal'))
        self.sample_clock = scpiDevice('Sample_ClocK', choices=_ChoiceStrings('INTernal', 'ECL', 'L0V', 'TTL'))
        self.RIS_mode_en = scpiDevice('InterLeaVeD', choices=bool_lecroy)
        para_type = ChoiceStrings('CUST', 'HPAR', 'VPAR', 'OFF')
        para_readout = ChoiceStrings('STAT', 'HISTICON', 'BOTH', 'OFF')
        para_mode_ch = lecroy_dict([('', 'type'), ('','readout')], [para_type, para_readout], required=1)
        self.max_rate_memory = lecroy_vbs_scpi('app.Acquisition.Horizontal.Maximize', choices=ChoiceStrings('SetMaximumMemory', 'FixedSampleRate'))
        self.sample_rate = lecroy_vbs_scpi('app.Acquisition.Horizontal.SampleRate', str_type=float, setget=True)
        self.sample_rate_used = lecroy_vbs_scpi(getstr='app.Acquisition.Horizontal.SamplingRate', str_type=float, doc='Returns 1S/s when using an external sample clock')
        self.parameter_mode = scpiDevice('PARaMeter', choices=para_mode_ch)
        self.parameter_mode_type = Dict_SubDevice(self.parameter_mode, 'type')
        channels = ['C%i'%i for i in range(1,5)] +\
                   ['M%i'%i for i in range(1,5)] +\
                   ['F%i'%i for i in range(1,9)] +\
                   ['Z%i'%i for i in range(1,5)]
        channelsF = ['C%i'%i for i in range(1,5)] +\
                   ['M%i'%i for i in range(1,13)] +\
                   ['F%i'%i for i in range(1,13)] +\
                   ['Z%i'%i for i in range(1,13)]
        channelsIn = ['C%i'%i for i in range(1,5)]
        channelsTrig = channelsIn + ['EX', 'EX10', 'EX5', 'LINE']
        channelsFunc = ['F%i'%i for i in range(1,9)] +\
                       ['Z%i'%i for i in range(1,5)]
        # also XY, math(ET, SpecAn, Spectro, SpecWindow), trigger(EX, EX10, EX5, LINE)
        self.current_channel = MemoryDevice('C1', choices=channelsF)
        self.current_input_channel = MemoryDevice('C1', choices=ChoiceStrings('C1', 'C2', 'C3', 'C4'))
        self.current_trig_channel = MemoryDevice('C1', choices=channelsTrig)
        self.current_func_channel = MemoryDevice('F1', choices=channelsFunc)
        #self.points = scpiDevice(':WAVeform:POINts', str_type=int) # 100, 250, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000, 2000000, 4000000, 8000000
        #self.waveform_count = scpiDevice(getstr=':WAVeform:COUNt?', str_type=int)
        #self.average_count = scpiDevice(':ACQuire:COUNt', str_type=int, min=2, max=65536)
        #self.acq_samplerate = scpiDevice(getstr=':ACQuire:SRATe?', str_type=float)
        #self.acq_npoints = scpiDevice(getstr=':ACQuire:POINts?', str_type=int)
        def devChannelBaseOption(ch_base, *arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=ch_base)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        devChannelOption = lambda *arg, **kwarg: devChannelBaseOption(self.current_channel, *arg, **kwarg)
        devChannelInOption = lambda *arg, **kwarg: devChannelBaseOption(self.current_input_channel, *arg, **kwarg)
        devChannelTrigOption = lambda *arg, **kwarg: devChannelBaseOption(self.current_trig_channel, *arg, **kwarg)
        devChannelFuncOption = lambda *arg, **kwarg: devChannelBaseOption(self.current_func_channel, *arg, **kwarg)
        self.data = devChannelOption(getstr='{ch}:WaveForm? ALL', str_type=waveformdata(), autoinit=False, trig=True, raw=True)
        self.data_header = devChannelOption(getstr='{ch}:WaveForm? DESC', str_type=waveformdata(return_only_header=True), autoinit=False, trig=True, raw=True)
        data_setup_ch = lecroy_dict([('SP', 'steps'), ('NP', 'maxpnts'), ('FP', 'first'), ('SN', 'segment_n')], [int]*4)
        self.data_setup = scpiDevice('WaveForm_SetUp', choices=data_setup_ch, doc="""
             steps of 0,1 is all, otherwise is every n pnts.
             maxpnts=0 means all
             first is 0 bases index of first point returned
             segment_n selects segment to return or all segements if set to 0""")
        self.trace_en = devChannelOption('{ch}:TRAce', choices=bool_lecroy)
        # TODO only channelsIn
        def lecChannelOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_input_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return lecroy_vbs_scpi(*arg, **kwarg)
        self.interpolation = lecChannelOption('app.Acquisition.{ch}.InterpolateType', choices=ChoiceStrings('LINEAR', 'SINXX'))
        self.input_sel = lecChannelOption('app.Acquisition.{ch}.ActiveInput', choices=ChoiceStrings('INPUTA', 'INPUTB'))
        self.input_avg = lecChannelOption('app.Acquisition.{ch}.AverageSweeps', str_type=int)
        self.input_deskew = lecChannelOption('app.Acquisition.{ch}.Deskew', str_type=float)
        self.input_enh_resol = lecChannelOption('app.Acquisition.{ch}.EnhanceResType', choices=ChoiceStrings('0.5BITS', '1BITS', '1.5BITS', '2BITS', '2.5BITS', '3BITS', 'NONE'))
        self.input_invert = lecChannelOption('app.Acquisition.{ch}.Invert', choices=ChoiceDict({True:'-1', False:'0'}), write_quotes=False)
        self.volts_div = devChannelInOption('{ch}:Volt_DIV', str_type=float, setget=True)
        self.attenuation = devChannelInOption('{ch}:ATTeNuation', str_type=int, choices=[1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000, 10000])
        self.coupling = devChannelInOption('{ch}:CouPLing', choices=ChoiceStrings('D50', 'GND', 'D1M', 'A1M', 'OVL'), doc='OVL is returned on input overload in d50. Do not set it.')
        bwlim = ChoiceStrings('OFF', '16GHZ', '13GHZ', '8GHZ', '6GHZ', '4GHZ', '3GHZ', '1GHZ', '200MHZ', 'ON')
        cl = ['C%i'%i for i in range(1,5)] + ['C%iA'%i for i in range(1,5)] + ['C%iB'%i for i in range(1,5)]
        bwlim_choices = lecroy_dict(cl, bwlim)
        self.bandwith_limit = scpiDevice('BandWidth_Limit', choices=bwlim_choices, doc='OFF=full, ON=20 MHz')
        self.offset = devChannelInOption('{ch}:OFfSeT', str_type=float)
        self.offset_constant_mode = scpiDevice('OFFset_ConstanT', choices=ChoiceStrings('VOLTS', 'DIV'))
        self.time_div = scpiDevice('Time_DIV', str_type=float)
        self.memory_size = scpiDevice('Memory_SIZe', str_type=float)
        # C1-C4, EX, EX10, ETM10
        self.trig_coupling = devChannelTrigOption('{ch}:TRig_CouPling', choices=ChoiceStrings('DC', 'DC50', 'GND', 'DC1M', 'AC1M'))
        self.trig_level = devChannelTrigOption('{ch}:TRig_LeVel', str_type=float_stripUnit)
        self.trig_mode = scpiDevice('TRig_MoDe', choices=ChoiceStrings('AUTO', 'NORM', 'SINGLE', 'STOP'))
        self.trig_pattern = scpiDevice('TRig_PAttern')
        self.trig_slope = devChannelTrigOption('{ch}:TRig_SLope', choices=ChoiceStrings('NEG', 'POS'))
        channelsTrig = ['C%i'%i for i in range(1,5)] + ['LINE', 'EX', 'EX10', 'PA', 'ETM10']
        channelsTrig = ChoiceStrings(*channelsTrig)
        trig_select_holdtype = ChoiceDict({'time':'TI', 'tl':'TL', 'event':'EV', 'ps':'PS', 'pl':'PL', 'is':'IS', 'il':'IL', 'p2':'P2', 'i2':'I2', 'off':'OFF'})
        trig_select_mode = ChoiceStrings('DROP', 'EDGE', 'GLIT', 'INTV', 'STD', 'SNG', 'SQ', 'TEQ')
        trig_select_opt = lecroy_dict([('', 'mode'), ('SR', 'ch', ), ('QL','ch2'), ('HT','holdtype'), ('HV','holdvalue'), ('HV2','holdvalue2')], [trig_select_mode, channelsTrig, channelsTrig, trig_select_holdtype, float_stripUnit, float_stripUnit])
        self.trig_select = scpiDevice('TRig_SElect', choices=trig_select_opt)
        self.trig_pos_s = scpiDevice('TRig_DeLay', str_type=float, doc='The values are in seconds away from the center. Negative values move the trigger to the left of the screen.')

        self.current_parafunc = MemoryDevice('AMPL', doc="""
         Possible values are numerous:
             'AMPL': amplitude
             'TOTP': histogram total population
             'ALL': a bunch of parameters
             'AMPL,FREQ': both amplitude and frequency
             'CUST1': The result of P1
          See the lecroy Remote control manual for more options.""")
        pval_state = ChoiceDict({'OK':'OK', 'averaged':'AV', 'period truncated':'PT', 'invalid':'IV', 'no pulse':'NP', 'greather than':'GT', 'less than':'LT', 'overflow':'OF', 'undeflow':'UF', 'over and under flow':'OU'})
        pval_choice = lecroy_dict([('','func'), ('', 'value'), ('', 'state')], [str, float_undef, pval_state], repeats=(0,2))
        self.parameter_value = devChannelOption(getstr='{ch}:PArameter_VAlue? {func}', choices=pval_choice, autoinit=False, trig=True,
                                             doc="""This calculates some parameter on a waveform. See current_parafunc for some function examples.""",
                                             options=dict(func=self.current_parafunc),
                                             options_apply=['ch', 'func'])

        self.current_para = MemoryDevice(1, min=1, max=12)
        pstat_choice = lecroy_dict([('', 'mode'), ('', 'ch'), ('', 'func'), 'avg', 'high', 'last', 'low', 'sigma', 'sweeps'], [str]*4+[float_undef]*7, required=2, repeats=2)
        pstat_modes = para_type[:3] # skip OFF
        self.parameter_stat_ch = scpiDevice(getstr='PArameter_STatistics? {mode},P{ch}', choices=pstat_choice, autoinit=False, trig=True,
                                         options=dict(ch=self.current_para, mode=self.parameter_mode_type),
                                         options_apply=['ch'],
                                         options_lim=dict(mode=pstat_modes),
                                         options_conv=dict(mode=lambda s,ts: s))
        para_stat = ChoiceStrings('AVG', 'LOW', 'HIGH', 'SIGMA', 'SWEEPS', 'LAST')
        pstat_all_ch = lecroy_dict([('', 'mode'), ('', 'stat'), ('', 'data')], [str]*2 + [float_undef], required=2, repeats=2)
        def takefirst(x,y):
            return x
        self.parameter_stat_all = scpiDevice(getstr='PArameter_STatistics? {mode},{stat}', choices=pstat_all_ch, autoinit=False, trig=True,
                                         options=dict(stat='AVG', mode=self.parameter_mode_type),
                                         options_lim=dict(stat=para_stat, mode=pstat_modes),
                                         options_conv=dict(mode=takefirst, stat=takefirst))
        self.parameter_stat_all_data = Dict_SubDevice(self.parameter_stat_all, 'data')
        pstat_params_ch = lecroy_dict([('', 'mode'), ('', 'stat'), ('', 'func'), ('', 'src')], [str]*4, required=2, repeats=(2,3))
        self.parameter_stat_params = scpiDevice(getstr='PArameter_STatistics? {mode},PARAM', choices=pstat_params_ch,
                                         options=dict(mode=self.parameter_mode_type),
                                         options_lim=dict(mode=pstat_modes),
                                         options_conv=dict(mode=takefirst))
        self.function_def = devChannelFuncOption('{ch}:DEFine', doc="""
            Note that doing set on the return of get might fail because of values with unit.
            Removes those and it will probably work.
            A full value for set might look like:
                'EQN,"HIST(P1)",VALUES,100,BINS,1024'
            when called with ch='F1' this will make trace F1
            be the histogram of P1, using  1024 bins and using the last
            1000 values, i.e. the sum of all the bins will eventually add up
            to 1000.""")
        self._devwrap('trace_enV', doc='Same as trace_en, but works on all the channels (even P1-12)')
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(lecroy_wavemaster, self)._create_devs()

# Directory for DISK option can use FLPY, HDD, C, D ...
# Lots of unknown trig_select modes like cascaded
#Functions like trace_en (C1:trace?) don't work for F9-f12, M5-M12, Z5-Z12 # still not working in 7.8.0
#            same with PArameter_STatistics? {mode},P{ch} for P10-12 # This seems to work now in 7.8.0
#            ...

# For timming
#  can use
#    clear_sweeps
#    and look at data.header.SWEEPS_PER_ACQ
#       which goes up when channel is averaging
#   lecr._async_trig_cleanup(); lecr.arm_acquisition(); lecr.force_trigger(); lecr.write('*OPC'); lecr.wait_after_trig()
#     need force trigger if want auto trigger.
#   lecr._async_trig_cleanup(); lecr.arm_acquisition();  lecr.write('wait;*OPC'); lecr.wait_after_trig()
# can use lecr.data or lecr.data_header
# I did not find how to stop processing
#   asking for some info during a long processing could time out.
# lecr.write('app.ProcessingResume', use_vbs=True)
# lecr.write('app.ProcessingResume', use_vbs=True)
