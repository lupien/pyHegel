# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

import numpy as np
from collections import OrderedDict, namedtuple
from ctypes import Structure, c_float, c_double, c_int8, c_int16, c_int32, c_char

from instruments_base import visaInstrumentAsync, visaInstrument,\
                            BaseDevice, scpiDevice, MemoryDevice, ReadvalDev,\
                            ChoiceBase, _general_check, _fromstr_helper, _tostr_helper,\
                            ChoiceStrings, ChoiceMultiple, ChoiceMultipleDep, Dict_SubDevice,\
                            _decode_block_base,\
                            sleep, locked_calling

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
        On writing, it is not necessary to gave all. Values not given are not
        changed by lecroy instrument.
        fielnames is a list of ('SN', 'dict_name'), where SN is the shortname
        used to communicate with the instrument, dict_name is the name
        used for the pyHegel dictionnary. It can also be a list of strings, in
        which case it is used as both SN and dict_name
        'SN' can be '', in which case it should be the first elements of the list.
        and is not named. There can only be more than one.
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
        if required == None:
            required = cnt
        self.required = required
        if repeats != None:
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
        if fromdict == None:
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

class StructureImproved(Structure):
    """
    This adds to the way Structure works (structure elements are
    class attribute).
    -can also access (RW) elements with numerical ([1]) and name indexing (['key1'])
    -can get and OrderedDict from the data (as_dict method)
    -can get the number of elements (len)
    -can get a list of items, keys or values like for a dict
    -can print a more readable version of the structure
    Note that it can be initialized with positional arguments or keyword arguments.
    And changed later with update.
    """
    _names_cache = []
    def _get_names(self):
        if self._names_cache == []:
            self._names_cache.extend([n for n,t in self._fields_])
        return self._names_cache
    _names_ = property(_get_names)
    def __getitem__(self, key):
        if not isinstance(key, basestring):
            key = self._names_[key]
        return getattr(self, key)
    def __setitem__(self, key, value):
        if not isinstance(key, basestring):
            key = self._names_[key]
        setattr(self, key, value)
    def __len__(self):
        return len(self._fields_)
    def update(self, *args, **kwarg):
        for i,v in enumerate(args):
            self[i]=v
        for k,v in kwarg:
            self[k]=v
    def as_dict(self):
        return OrderedDict(self.items())
    def items(self):
        return [(k,self[k]) for k in self._names_]
    def keys(self):
        return self._names_
    def values(self):
        return [self[k] for k in self._names_]
    def __repr__(self):
        return self.show_all(multiline=False, show=False)
    def show_all(self, multiline=True, show=True):
        strs = ['%s=%r'%(k, v) for k,v in self.items()]
        if multiline:
            ret = '%s(\n  %s\n)'%(self.__class__.__name__, '\n  '.join(strs))
        else:
            ret = '%s(%s)'%(self.__class__.__name__, ', '.join(strs))
        if show:
            print ret
        else:
            return ret

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

#COMM_TYPE: chosen by remote command COMM_FORMAT
#0:byte  1:word

#COMM_ORDER: 0:HIFIRST 1:LOFIRST

# RECORD_TYPE:
#0 single_sweep
#1 interleaved
#2 histogram
#3 graph
#4 filter_coefficient
#5 complex
#6 extrema
#7 sequence_obsolete
#8 centered_RIS
#9 peak_detect

#PROCESSING_DONE
#0 no_processing
#1 fir_filter
#2 interpolated
#3 sparsed
#4 autoscaled
#5 no_result
#6 rolling
#7 cumulative

#TIMEBASE
#0 1_ps/div
#1 2_ps/div
#2 5_ps/div
#3 10_ps/div
#4 20_ps/div
#5 50_ps/div
#6 100_ps/div
#7 200_ps/div
#8 500_ps/div
#9 1_ns/div
#10 2_ns/div
#11 5_ns/div
#12 10_ns/div
#13 20_ns/div
#14 50_ns/div
#15 100_ns/div
#16 200_ns/div
#17 500_ns/div
#18 1_us/div
#19 2_us/div
#20 5_us/div
#21 10_us/div
#22 20_us/div
#23 50_us/div
#24 100_us/div
#25 200_us/div
#26 500_us/div
#27 1_ms/div
#28 2_ms/div
#29 5_ms/div
#30 10_ms/div
#31 20_ms/div
#32 50_ms/div
#33 100_ms/div
#34 200_ms/div
#35 500_ms/div
#36 1_s/div
#37 2_s/div
#38 5_s/div
#39 10_s/div
#40 20_s/div
#41 50_s/div
#42 100_s/div
#43 200_s/div
#44 500_s/div
#45 1_ks/div
#46 2_ks/div
#47 5_ks/div
#100 EXTERNAL

#FIXED_VERT_GAIN
#0 1_uV/div
#1 2_uV/div
#2 5_uV/div
#3 10_uV/div
#4 20_uV/div
#5 50_uV/div
#6 100_uV/div
#7 200_uV/div
#8 500_uV/div
#9 1_mV/div
#10 2_mV/div
#11 5_mV/div
#12 10_mV/div
#13 20_mV/div
#14 50_mV/div
#15 100_mV/div
#16 200_mV/div
#17 500_mV/div
#18 1_V/div
#19 2_V/div
#20 5_V/div
#21 10_V/div
#22 20_V/div
#23 50_V/div
#24 100_V/div
#25 200_V/div
#26 500_V/div
#27 1_kV/div

#BANDWIDTH_LIMIT: 0:off 1:on

#WAVE_SOURCE:
#0 CHANNEL_1
#1 CHANNEL_2
#2 CHANNEL_3
#3 CHANNEL_4
#9 UNKNOWN


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
        if getstr == None and autoget:
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

class lecroy_wavemaster(visaInstrumentAsync):
    """
    This instrument controls a LeCory WaveMaster 820Zi-A
     To use this instrument, the most useful devices are probably:
       fetch
       readval
       snap_png
    """
    def __init__(self, visa_addr):
        # The SRQ for this intrument does not work
        # as of version 7.2.1.0
        super(lecroy_wavemaster, self).__init__(visa_addr, poll=True)
    def init(self, full=False):
        self.write('Comm_ORDer LO') # can be LO or HI: LO=LSB first
        self.write('Comm_ForMaT DEF9,WORD,BIN') #DEF9=IEEE 488.2 block data, WORD (default is BYTE)
        self.write('Comm_HeaDeR OFF') #can be OFF, SHORT, LONG. OFF removes command echo and units
        super(lecroy_wavemaster, self).init(full=full)
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('memory_size', 'trig_coupling', options)
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
        if ch==None:
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
        if ch==None:
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
        if data_fmt != None:
            extra = ',' + data_fmt
        ret = self.ask('%s:INSPect? %s%s'%(ch, info, extra))
        if do_print:
            print ret
        else:
            return ret
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
        # also XY, math(ET, SpecAn, Spectro, SpecWindow), trigger(EX, EX10, EX5, LINE)
        self.current_channel = MemoryDevice('C1', choices=channelsF)
        #self.points = scpiDevice(':WAVeform:POINts', str_type=int) # 100, 250, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000, 2000000, 4000000, 8000000
        #self.waveform_count = scpiDevice(getstr=':WAVeform:COUNt?', str_type=int)
        #self.average_count = scpiDevice(':ACQuire:COUNt', str_type=int, min=2, max=65536)
        #self.acq_samplerate = scpiDevice(getstr=':ACQuire:SRATe?', str_type=float)
        #self.acq_npoints = scpiDevice(getstr=':ACQuire:POINts?', str_type=int)
        def devChannelOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.data = devChannelOption(getstr='{ch}:WaveForm? ALL', str_type=waveformdata(), autoinit=False, trig=True, raw=True)
        self.data_header = devChannelOption(getstr='{ch}:WaveForm? DESC', str_type=waveformdata(return_only_header=True), autoinit=False, trig=True, raw=True)
        data_setup_ch = lecroy_dict([('SP', 'steps'), ('NP', 'maxpnts'), ('FP', 'first'), ('SN', 'segment_n')], [int]*4)
        self.data_setup = scpiDevice('WaveForm_SetUp', choices=data_setup_ch, doc="""
             steps of 0,1 is all, otherwise is every n pnts.
             maxpnts=0 means all
             first is 0 bases index of first point returned
             segment_n selects segment to return or all segements if set to 0""")
        self.trace_en = devChannelOption('{ch}:TRAce', choices=bool_lecroy)
        self.current_input_channel = MemoryDevice('C1', choices=ChoiceStrings('C1', 'C2', 'C3', 'C4'))
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
        self.volts_div = devChannelOption('{ch}:Volt_DIV', str_type=float, setget=True)
        self.attenuation = devChannelOption('{ch}:ATTeNuation', str_type=int, choices=[1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000, 10000])
        self.coupling = devChannelOption('{ch}:CouPLing', choices=ChoiceStrings('D50', 'GND', 'D1M', 'A1M', 'OVL'), doc='OVL is returned on input overload in d50. Do not set it.')
        bwlim = ChoiceStrings('OFF', '16GHZ', '13GHZ', '8GHZ', '6GHZ', '4GHZ', '3GHZ', '1GHZ', '200MHZ', 'ON')
        cl = ['C%i'%i for i in range(1,5)] + ['C%iA'%i for i in range(1,5)] + ['C%iB'%i for i in range(1,5)]
        bwlim_choices = lecroy_dict(cl, bwlim)
        self.bandwith_limit = devChannelOption('BandWidth_Limit', choices=bwlim_choices, doc='OFF=full, ON=20 MHz')
        self.offset = devChannelOption('{ch}:OFfSeT', str_type=float)
        self.offset_constant_mode = scpiDevice('OFFset_ConstanT', choices=ChoiceStrings('VOLTS', 'DIV'))
        self.time_div = scpiDevice('Time_DIV', str_type=float)
        self.memory_size = scpiDevice('Memory_SIZe', str_type=float)
        # C1-C4, EX, EX10, ETM10
        self.trig_coupling = devChannelOption('{ch}:TRig_CouPling', choices=ChoiceStrings('DC', 'DC50', 'GND', 'DC1M', 'AC1M'))
        self.trig_level = devChannelOption('{ch}:TRig_LeVel', str_type=float_stripUnit)
        self.trig_mode = scpiDevice('TRig_MoDe', choices=ChoiceStrings('AUTO', 'NORM', 'SINGLE', 'STOP'))
        self.trig_pattern = scpiDevice('TRig_PAttern', autoinit=False)
        self.trig_slope = devChannelOption('{ch}:TRig_SLope', choices=ChoiceStrings('NEG', 'POS'))
        channelsTrig = ['C%i'%i for i in range(1,5)] + ['LINE', 'EX', 'EX10', 'PA', 'ETM10']
        channelsTrig = ChoiceStrings(*channelsTrig)
        trig_select_holdtype = ChoiceDict({'time':'TI', 'tl':'TL', 'event':'EV', 'ps':'PS', 'pl':'PL', 'is':'IS', 'il':'IL', 'p2':'P2', 'i2':'I2', 'off':'OFF'})
        trig_select_mode = ChoiceStrings('DROP', 'EDGE', 'GLIT', 'INTV', 'STD', 'SNG', 'SQ', 'TEQ')
        trig_select_opt = lecroy_dict([('', 'mode'), ('SR', 'ch', ), ('QL','ch2'), ('HT','holdtype'), ('HV','holdvalue'), ('HV2','holdvalue2')], [trig_select_mode, channelsTrig, channelsTrig, trig_select_holdtype, float_stripUnit, float_stripUnit])
        self.trig_select = devChannelOption('TRig_SElect', choices=trig_select_opt)
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
        self.function_def = devChannelOption('{ch}:DEFine', autoinit=False, doc="""
            Note that doing set on the return of get might fail because of values with unit.
            Removes those and it will probably work.
            A full value for set might look like:
                'EQN,"HIST(P1)",VALUES,100,BINS,1024'
            when called with ch='F1' this will make trace F1
            be the histogram of P1, using  1024 bins and using the last
            1000 values, i.e. the sum of all the bins will eventually add up
            to 1000.""")
        self._devwrap('fetch', autoinit=False, trig=True)
        #self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(lecroy_wavemaster, self)._create_devs()

# Directory for DISK option can use FLPY, HDD, C, D ...
# Lots of unknown trig_select modes like cascaded
#Functions like trace_en (C1:trace?) don't work for F9-f12, M5-M12, Z5-Z12
#            same with PArameter_STatistics? {mode},P{ch} for P10-12
#            ...
