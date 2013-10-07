# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

import numpy as np
from collections import OrderedDict, namedtuple
from ctypes import Structure, c_float, c_double, c_int8, c_int16, c_int32, c_char

from instruments_base import visaInstrumentAsync, visaInstrument,\
                            BaseDevice, scpiDevice, MemoryDevice, ReadvalDev,\
                            ChoiceMultiple, _repr_or_string,\
                            quoted_string, quoted_list, quoted_dict,\
                            ChoiceBase,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDevSwitch,\
                            _decode_block_base,\
                            sleep, locked_calling

"""
Unimplemented commands that could be interesting

     ACQUISITION — TO CONTROL WAVEFORM CAPTURE
  ASET AUTO_SETUP Adjusts vertical, timebase and trigger parameters for signal display.
BWL BANDWIDTH_LIMIT Enables or disables the bandwidth-limiting low-pass filter.
COMB COMBINE_CHANNELS Controls the channel interleaving function.
CPL COUPLING Selects the specified input channel’s coupling mode.
ILVD INTERLEAVED Enables or disables Random Interleaved Sampling (RIS).
SCLK SAMPLE_CLOCK Toggles between internal clock and external clock.
SEQ SEQUENCE Controls the sequence mode of acquisition.
*TRG *TRG Executes an ARM command.
TRDL TRIG_DELAY Sets the time at which the trigger is to occur.
WAIT WAIT Prevents new command analysis until current acquisition completion.
     CURSOR — TO PERFORM MEASUREMENTS
CRMS CURSOR_MEASURE Specifies the type of cursor or parameter measurement for display.
CRST CURSOR_SET Allows positioning of any cursor.
CRVA? CURSOR_VALUE? Returns the values measured by the specified cursors for a given trace.
CRS CURSORS Sets the cursor type.
PARM PARAMETER Controls the parameter mode.
PACL PARAMETER_CLR Clears all current parameters in Custom and Pass/Fail modes.
PACU PARAMETER_CUSTOM Controls parameters with customizable qualifiers.
PADL PARAMETER_DELETE Deletes a specified parameter in Custom and Pass/Fail modes.
PAST? PARAMETER_STATISTICS Returns parameter statistics results.
PAVA? PARAMETER_VALUE? Returns current value(s) of parameter(s) and mask tests.
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
DEF DEFINE Specifies math expression for function evaluation.
FCR FIND_CENTER_RANGE Automatically sets the center and width of a histogram.
FRST FUNCTION_RESET Resets a waveform processing function.
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
INSP? INSPECT? Allows acquired waveform parts to be read.
  STO STORE Stores a trace in one of the internal memories M1–4 or mass storage.
  STST STORE_SETUP Sets up waveform storage
WFSU WAVEFORM_SETUP Specifies amount of waveform data for transmission to controller.
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

waveformdataType = namedtuple('waveformdataType', 'header data1 data2 trigtime ristime usertext')
class waveformdata(object):
    def __call__(self, inputstr):
        ds =inputstr.split(',', 1) # strip DESC, TEXT, TIME, DAT1, DAT2, ALL
        fullblock = _decode_block_base(ds[1])
        header = WAVEDESC.from_buffer_copy(fullblock)
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
            trigtime = fromstring(trigtime, [('trig_time', float64), ('time_offset', float64)])
        if ristime:
            ristime = fromstring(ristime, float64)
        return waveformdataType(header, data1, data2, trigtime, ristime, usertext)
    def tostr(self, val):
        pass

#######################################################
##    LeCroy WaveMaster 820Zi-A
#######################################################

class lecroy_wavemaster(visaInstrument):
    """
    This instrument controls a LeCory WaveMaster 820Zi-A
     To use this instrument, the most useful devices are probably:
       fetch
       readval
       snap_png
    """
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
    def buzz(self):
        self.write('BUZZer BEEP')
    def message(self, msg=''):
        """ Will show msg on the message field at bottom of instrument. Not message clears line."""
        self.write('MeSsaGe "%s"'%msg)
    def get_error(self):
        errors = self.ask('Comm_HeLP_Log? CLR').strip('"').splitlines()
        #if errors == []:
        #    errors = ['No errors']
        return errors
    def _create_devs(self):
        self._devwrap('snap_png', autoinit=False)
        self.snap_png._format['bin']='.png'
        self.autocal_en = scpiDevice('Auto_CALibrate', choices=bool_lecroy)
        self.display_en = scpiDevice('DISPlay', choices=bool_lecroy)
        self.lecroy_options = scpiDevice(getstr='*OPT?')
        self.reference_clock = scpiDevice('Reference_CLocK', choices=ChoiceStrings('INTERNAL', 'EXTERNAL'))
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
        #self.data = scpiDevice(getstr=':waveform:DATA?', raw=True, str_type=decode_uint16_bin, autoinit=False) # returns block of data (always header# for asci byte and word)
          # also read :WAVeform:PREamble?, which provides, format(byte,word,ascii),
          #  type (Normal, peak, average, HRes), #points, #avg, xincr, xorg, xref, yincr, yorg, yref
          #  xconv = xorg+x*xincr, yconv= (y-yref)*yincr + yorg
        #self.points = scpiDevice(':WAVeform:POINts', str_type=int) # 100, 250, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000, 2000000, 4000000, 8000000
        #self.points_mode = scpiDevice(':WAVeform:POINts:MODE', choices=ChoiceStrings('NORMal', 'MAXimum', 'RAW'))
        #self.preamble = scpiDevice(getstr=':waveform:PREamble?', choices=ChoiceMultiple(['format', 'type', 'points', 'count', 'xinc', 'xorig', 'xref', 'yinc', 'yorig', 'yref'],[int, int, int, int, float, float, int, float, float, int]))
        #self.waveform_count = scpiDevice(getstr=':WAVeform:COUNt?', str_type=int)
        #self.acq_type = scpiDevice(':ACQuire:TYPE', choices=ChoiceStrings('NORMal', 'AVERage', 'HRESolution', 'PEAK'))
        #self.acq_mode= scpiDevice(':ACQuire:MODE', choices=ChoiceStrings('RTIM', 'SEGM'))
        #self.average_count = scpiDevice(':ACQuire:COUNt', str_type=int, min=2, max=65536)
        #self.acq_samplerate = scpiDevice(getstr=':ACQuire:SRATe?', str_type=float)
        #self.acq_npoints = scpiDevice(getstr=':ACQuire:POINts?', str_type=int)
        def devChannelOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.data = devChannelOption(getstr='{ch}:WaveForm? ALL', str_type=waveformdata(), autoinit=False)
        self.trace_en = devChannelOption('{ch}:TRAce', choices=bool_lecroy)
        # TODO only channelsIn
        self.volts_div = devChannelOption('{ch}:Volt_DIV', choices=float)
        self.attenuation = devChannelOption('{ch}:Volt_DIV', str_type=int, choices=[1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000, 10000])
        #returns 'C1,OFF,C2,ON,C3,OFF,C4,OFF,C1A,OFF,C2A,ON,C3A,OFF,C4A,OFF,C1B,OFF,C2B,OFF,C3B,OFF,C4B,OFF'
        self.bandwith_limit = devChannelOption('BandWidth_Limit {ch},{val}', 'BandWidth_Limit?', choices=ChoiceStrings('OFF', '16GHZ', '13GHZ', '8GHZ', '6GHZ', '4GHZ', '3GHZ', '1GHZ', '200MHZ', 'ON'), autoinit=False, doc='OFF=full, ON=20 MHz')
        self.offset = devChannelOption('{ch}:OFfSeT', choices=float)
        self.offset_constant_mode = scpiDevice('OFFset_ConstanT', choices=ChoiceStrings('VOLTS', 'DIV'))
        self.time_div = scpiDevice('Time_DIV', choices=float)
        self.memory_size = scpiDevice('Memory_SIZe', choices=float)
        # C1-C4, EX, EX10, ETM10
        self.trig_coupling = devChannelOption('{ch}:TRig_CouPling', choices=ChoiceStrings('DC', 'DC50', 'GND', 'DC1M', 'AC1M'))
        self.trig_level = devChannelOption('{ch}:TRig_LeVel', str_type=float)
        self.trig_mode = scpiDevice('TRig_MoDe', choices=ChoiceStrings('AUTO', 'NORM', 'SINGLE', 'STOP'))
        self.trig_pattern = scpiDevice('TRig_PAttern', autoinit=False)
        self.trig_slope = devChannelOption('{ch}:TRig_SLope', choices=ChoiceStrings('NEG', 'POS'))
        # C1, C2, C3, C4, LINE, EX, EX10, PA, ETM10
        # holdtype: TI, TL, EV, PS, PL, IS, IL, P2, I2, OFF
        self.trig_select = devChannelOption('TRig_SElect {val},SR,{ch},QL,{ch},HT,{holdtype},HV,{holdvalue},{holdvalue2}', choices=ChoiceStrings('DROP', 'EDGE', 'GLIT', 'INTV', 'STD', 'SNG', 'SQ', 'TEQ'), autoinit=False)
        #self.timebase_mode= scpiDevice(':TIMebase:MODE', choices=ChoiceStrings('MAIN', 'WINDow', 'XY', 'ROLL'))
        #self.timebase_pos= scpiDevice(':TIMebase:POSition', str_type=float) # in seconds from trigger to display ref
        #self.timebase_range= scpiDevice(':TIMebase:RANGe', str_type=float) # in seconds, full scale
        #self.timebase_reference= scpiDevice(':TIMebase:REFerence', choices=ChoiceStrings('LEFT', 'CENTer', 'RIGHt'))
        self._devwrap('fetch', autoinit=False, trig=True)
        #self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(lecroy_wavemaster, self)._create_devs()
