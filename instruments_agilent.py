# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

import numpy as np
import scipy
import time

from instruments_base import visaInstrument, visaInstrumentAsync,\
                            BaseDevice, scpiDevice, MemoryDevice, ReadvalDev,\
                            ChoiceMultiple, _repr_or_string,\
                            quoted_string, quoted_list, quoted_dict,\
                            ChoiceStrings, ChoiceDevDep, ChoiceDevSwitch,\
                            decode_float64, decode_float64_avg, decode_float64_meanstd,\
                            decode_uint16_bin, _decode_block_base, decode_float64_2col,\
                            decode_complex128

#######################################################
##    Agilent RF 33522A generator
#######################################################

class agilent_rf_33522A(visaInstrument):
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('ampl1', 'freq1', 'offset1', 'phase1', 'mode1', 'out_en1', 'pulse_width1',
                                 'ampl2', 'freq2', 'offset2', 'phase2', 'mode2', 'out_en2', 'pulse_width2', options)
    def _create_devs(self):
        # voltage unit depends on front panel/remote selection (sourc1:voltage:unit) vpp, vrms, dbm
        self.ampl1 = scpiDevice('SOUR1:VOLT', str_type=float, min=0.001, max=10)
        self.freq1 = scpiDevice('SOUR1:FREQ', str_type=float, min=1e-6, max=30e6)
        self.pulse_width1 = scpiDevice('SOURce1:FUNCtion:PULSe:WIDTh', str_type=float, min=16e-9, max=1e6) # s
        self.offset1 = scpiDevice('SOUR1:VOLT:OFFS', str_type=float, min=-5, max=5)
        self.phase1 = scpiDevice('SOURce1:PHASe', str_type=float, min=-360, max=360) # in deg unless changed by unit:angle
        self.mode1 = scpiDevice('SOUR1:FUNC') # SIN, SQU, RAMP, PULS, PRBS, NOIS, ARB, DC
        self.out_en1 = scpiDevice('OUTPut1', str_type=bool) #OFF,0 or ON,1
        self.ampl2 = scpiDevice('SOUR2:VOLT', str_type=float, min=0.001, max=10)
        self.freq2 = scpiDevice('SOUR2:FREQ', str_type=float, min=1e-6, max=30e6)
        self.pulse_width2 = scpiDevice('SOURce2:FUNCtion:PULSe:WIDTh', str_type=float, min=16e-9, max=1e6) # s
        self.phase2 = scpiDevice('SOURce2:PHASe', str_type=float, min=-360, max=360) # in deg unless changed by unit:angle
        self.offset2 = scpiDevice('SOUR2:VOLT:OFFS', str_type=float, min=-5, max=5)
        self.mode2 = scpiDevice('SOUR2:FUNC') # SIN, SQU, RAMP, PULS, PRBS, NOIS, ARB, DC
        self.out_en2 = scpiDevice('OUTPut2', str_type=bool) #OFF,0 or ON,1
        self.alias = self.freq1
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
    def phase_sync(self):
        self.write('PHASe:SYNChronize')


#######################################################
##    Agilent EPM power meter
#######################################################

class agilent_PowerMeter(visaInstrumentAsync):
    """
    This instrument is for Agilent N1913A EPM seris power meter with a N8487A
    average power sensor.

    Get data with readval (force read of new data) or fetch (gets possibly old data)
    Note that only the upper display upper line is read.

    gain_ch_{dB,en} applies a correction to the channel data.
    gain_{dB,en} applies a correction to the display (measurement menu)
                 (goes with relative menu)
    cset1_en is for manual sensor calibration (cannot be turn on for our sensor
             because it already provides a calibration, see th CF percent value on the
             display that depends on frequency. It is 100% at 50 MHz)
    cset2_en is a second manual calibration (called FDO table in channel/offsets)
             to compensate for the circuit used. It also depends on the frequency.
             You can read this correction value with freq_offset

    WARNING: currently only works for GPIB (usb and lan don't work)
             and the relative value cannot be read.
             (firmware A1.01.07)
    """
    # The instrument has 4 display position (top upper, top lower, ...)
    #  1=upper window upper meas, 2=lower upper, 3=upper lower, 4=lower lower
    # They are not necessarily active on the display but they are all used for
    # average calculation and can all be used for reading data.
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('range', 'range_auto_en', 'unit',
                                 'gain_en', 'hold_mode', 'relative_en', 'average_en',
                                 'average_cnt', 'average_cnt_auto', 'average_step_detection',
                                 'cset1_en', 'cset2_en', 'trig_src',
                                 'sensor_calib_date', 'sensor_type', 'sensor_serialno',
                                 'linear_corr_type', 'meas_rate',
                                 'gain_ch_dB', 'gain_ch_en',
                                 'duty_cycle_percent', 'duty_cycle_en',
                                 'freq', 'freq_offset', 'freq_offset_unit',
                                 options)
    def _async_trig(self):
        self.trig_delay_en.set(True)
        self.cont_trigger.set(False)
        super(agilent_PowerMeter, self)._async_trig()
    def set_relative(self):
        self.write('CALCulate1:RELative:AUTO ONCE')
    def _create_devs(self):
        # voltage unit depends on front panel/remote selection (sourc1:voltage:unit) vpp, vrms, dbm
        self.range = scpiDevice('SENSe:POWer:AC:RANGe', str_type=int, min=0, max=1)
        self.config = scpiDevice('CONFigure1')
        #self.resolution = scpiDevice('CONFig1 DEF,{val}', str_type=int, min=1, max=4)
        self.resolution = scpiDevice('DISPlay:WINDow1:NUMeric1:RESolution', str_type=int, min=1, max=4)
        self.range_auto_en = scpiDevice('SENSe:POWer:AC:RANGe:AUTO', str_type=bool)
        self.unit = scpiDevice('UNIT:POWer', choices=ChoiceStrings('DBM', 'W'))
        self.gain_dB = scpiDevice('CALCulate1:GAIN', str_type=float, min=-100, max=100)
        self.gain_en = scpiDevice('CALCulate1:GAIN:STATe', str_type=bool)
        self.hold_mode = scpiDevice('CALCulate1:HOLD:STAT', choices=ChoiceStrings('OFF', 'MIN', 'MAX'))
        self.relative_en = scpiDevice('CALCulate1:RELative:STATe', str_type=bool)
        #SENSE subsystem
        self.average_cnt = scpiDevice('AVERage:COUNt', str_type=int, min=1, max=1024)
        self.average_cnt_auto = scpiDevice('AVERage:COUNt:AUTO', str_type=bool)
        self.average_step_detection = scpiDevice('AVERage:SDETect', str_type=bool)
        self.average_en = scpiDevice('AVERage', str_type=bool)
        #self.gain_factor_pct = scpiDevice('CORRection:CFACtor', str_type=float, min=1., max=150.)
        self.cset1_en = scpiDevice('CORRection:CSET1:STATe', str_type=bool)
        self.cset2_en = scpiDevice('CORRection:CSET2:STATe', str_type=bool)
        self.freq = scpiDevice('FREQuency', str_type=float, min=1e3, max=1e12)
        self.freq_offset = scpiDevice(getstr='CORRection:FDOFfset?', str_type=float)
        self.freq_offset_unit = scpiDevice('CORRection:FDOFfset:UNIT', choices=ChoiceStrings('PCT', 'DB'))
        self.duty_cycle_percent = scpiDevice('CORRection:DCYCle', str_type=float, min=.001, max=99.999)
        self.duty_cycle_en = scpiDevice('CORRection:DCYCle:STATe', str_type=bool)
        self.gain_ch_dB = scpiDevice('CORRection:GAIN2', str_type=float, min=-100, max=100)
        self.gain_ch_en = scpiDevice('CORRection:GAIN2:STATe', str_type=bool)
        self.meas_rate = scpiDevice('MRATe', choices=ChoiceStrings('NORMal', 'DOUBle', 'FAST'))
        self.linear_corr_type = scpiDevice('V2P', choices=ChoiceStrings('ATYPe', 'DTYPe'))
        self.sensor_calib_date = scpiDevice(getstr='SERVice:SENSor:CDATe?')
        self.sensor_calib_place = scpiDevice(getstr='SERVice:SENSor:CPLace?')
        self.sensor_type = scpiDevice(getstr='SERVice:SENSor:TYPE?')
        self.sensor_serialno = scpiDevice(getstr='SERVice:SENSor:SNUMber?')
        self.raw_reading = scpiDevice(getstr='SERVice:SENSor:RADC?', autoinit=False, trig=True)
        #TRIGGER block
        self.trig_src = scpiDevice('TRIGger:SOURce', choices=ChoiceStrings('BUS', 'EXTernal', 'HOLD', 'IMMediate'))
        self.trig_delay_en = scpiDevice('TRIGger:DELay:AUTO', str_type=bool)
        self.cont_trigger = scpiDevice('INITiate:CONTinuous', str_type=bool)
        #READ, FETCH
        self.fetch = scpiDevice(getstr='FETCh?',str_type=float, autoinit=False, trig=True) #You need to read some data first.
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


#######################################################
##    Agilent PSG generator
#######################################################

class agilent_rf_PSG(visaInstrument):
    """
    This controls a PSG signal generetor
    Most useful devices:
        ampl
        ampl_unit
        rf_en
        mod_en
        freq_cw
    The alc devices refer to automatic level (amplitude) control.
    Available methods:
        phase_sync
    """
    def _current_config(self, dev_obj=None, options={}):
        # TODO Get the proper config
        return self._conf_helper('oscillator_source', 'rf_en', 'ampl', 'ampl_unit', 'amp_flatness_corr_en',
                                 'ampl_offset_db', 'ampl_reference_dbm', 'ampl_reference_en',
                                 'ampl_protection', 'ampl_mode', 'ampl_start', 'ampl_stop',
                                 'alc_en', 'alc_source', 'alc_bw', 'alc_bw_auto_en',
                                 'attenuation_db', 'attenuation_auto_en', 'amp_flatness_corr_en',
                                 'output_blanking_en', 'output_blanking_auto_en',
                                 'freq_mode', 'freq_cw', 'freq_start', 'freq_stop',
                                 'freq_multiplier', 'freq_offset', 'freq_offset_en', 'freq_reference', 'freq_reference_en',
                                 'phase', 'mod_en', 'mod_am_en', 'mod_fm_en', 'mod_phase_en', 'mod_pulse_en', options)
    def _create_devs(self):
        self.installed_options = scpiDevice(getstr='*OPT?')
        self.oscillator_source = scpiDevice(getstr=':ROSCillator:SOURce?', str_type=str)
        self.rf_en = scpiDevice(':OUTPut', str_type=bool)
        self.ampl = scpiDevice(':POWer', str_type=float, doc='unit depends on device ampl_unit', setget=True)
        self.ampl_unit = scpiDevice(':UNIT:POWer', choices=ChoiceStrings('DBM', 'DBUV', 'DBUVEMF', 'V', 'VEMF', 'DB'),
                                    doc='Note that EMF are 2x above the base unit (power arriving at infinite impedance load)')
        # unit:volt:type affects volt scale like power:alc:search:ref:level, which are not user changeable
        self.ampl_offset_db = scpiDevice(':POWer:OFFset', str_type=float, min=-200, max=+200)
        self.ampl_reference_dbm = scpiDevice(':POWer:REFerence', str_type=float, doc='This value is always in dBm')
        self.ampl_reference_en = scpiDevice(':POWer:REFerence:STATe', str_type=bool)
        self.ampl_mode = scpiDevice(':POWer:MODE', choices=ChoiceStrings('FIXed', 'LIST'))
        #self.ampl_optimize_lownoise = scpiDevice(':POWer:NOISe', str_type=bool)
        self.ampl_protection = scpiDevice(':POWer:PROTection', str_type=bool, doc='When enabled, sets the attenuation to maximum when performing a power search. Could decrease the life of the attenuator.')
        self.ampl_start = scpiDevice(':POWer:STARt', str_type=float, doc='unit depends on device ampl_unit', setget=True)
        self.ampl_stop = scpiDevice(':POWer:STOP', str_type=float, doc='unit depends on device ampl_unit', setget=True)
        # TODO handle the search stuff for when alc is off
        self.alc_en = scpiDevice(':POWer:ALC', str_type=bool)
        self.alc_source = scpiDevice(':POWer:ALC:SOURce', choices=ChoiceStrings('INTernal', 'DIODe'))
        # The alc_bw don't seem to have a front panel control. It might not do anything for the
        # generator N5183A we used.
        self.alc_bw = scpiDevice(':POWer:ALC:BANDwidth', str_type=float)
        self.alc_bw_auto_en = scpiDevice(':POWer:ALC:BANDwidth:AUTO', str_type=bool)
        self.attenuation_db = scpiDevice(':POWer:ATTenuation', str_type=float, min=0, max=15, setget=True)
        self.attenuation_auto_en = scpiDevice(':POWer:ATTenuation:AUTO', str_type=bool)
        self.amp_flatness_corr_en = scpiDevice(':CORRection', str_type=bool)
        self.output_blanking_en = scpiDevice(':OUTPut:BLANKing:STATe', str_type=bool)
        self.output_blanking_auto_en = scpiDevice(':OUTPut:BLANKing:AUTO', str_type=bool)
        self.freq_mode = scpiDevice(':FREQuency:MODE', choices=ChoiceStrings('CW', 'FIXed', 'LIST'), doc='CW and FIXed are the same, LIST means sweeping')
        minfreq = float(self.ask(':FREQ? min'))
        maxfreq = float(self.ask(':FREQ? max'))
        self.freq_cw = scpiDevice(':FREQuency', str_type=float, min=minfreq, max=maxfreq)
        self.freq_center = scpiDevice('FREQuency:CENTer', str_type=float, min=minfreq, max=maxfreq)
        self.freq_start = scpiDevice('FREQuency:STARt', str_type=float, min=minfreq, max=maxfreq)
        self.freq_stop = scpiDevice('FREQuency:STOP', str_type=float, min=minfreq, max=maxfreq)
        # TODO SPAN range is probably something else
        self.freq_span = scpiDevice('FREQuency:SPAN', str_type=float, min=0, max=maxfreq)
        self.freq_multiplier = scpiDevice(':FREQuency:MULTiplier', str_type=float, min=-1000, max=1000, doc='The range is -1000 to -0.001 and 0.001 to 1000')
        self.freq_offset = scpiDevice(':FREQuency:OFFSet', str_type=float, min=-200e9, max=200e9)
        self.freq_offset_en = scpiDevice(':FREQuency:OFFSet:STATe', str_type=bool)
        self.freq_reference = scpiDevice(':FREQuency:REFerence', str_type=float, min=0, max=maxfreq)
        self.freq_reference_en = scpiDevice(':FREQuency:REFerence:STATe', str_type=bool)
        self.phase = scpiDevice(':PHASe', str_type=float, min=-3.14, max=3.14, doc='Adjust phase arounf ref. In rad.')
        # TODO handle the marker stuff
        self.mod_en = scpiDevice(':OUTPut:MODulation:STATe', str_type=bool)
        self.mod_am_en = scpiDevice(':AM:STATe', str_type=bool)
        self.mod_fm_en = scpiDevice(':FM:STATe', str_type=bool)
        self.mod_phase_en = scpiDevice(':PM:STATe', str_type=bool)
        self.mod_pulse_en = scpiDevice(':PULM:STATe', str_type=bool)
        self.alias = self.freq_cw
        # This needs to be last to complete creation
        super(agilent_rf_PSG,self)._create_devs()
    def phase_sync(self):
        """
        Sets the current output phase as a zero reference.
        """
        self.write('PHASe:REFerence')


#######################################################
##    Agilent MXG generator
#######################################################

class agilent_rf_MXG(agilent_rf_PSG):
    """
    This controls a MXG signal generetor
    Most useful devices:
        ampl
        ampl_unit
        rf_en
        mod_en
        freq_cw
    The alc devices refer to automatic level (amplitude) control.
    Available methods:
        phase_sync
    """
    def _current_config(self, dev_obj=None, options={}):
        # TODO Get the proper config
        return self._conf_helper('oscillator_source', 'rf_en', 'ampl', 'ampl_unit', 'amp_flatness_corr_en',
                                 'ampl_offset_db', 'ampl_reference_dbm', 'ampl_reference_en', 'ampl_min_lim',
                                 'ampl_protection', 'ampl_mode', 'ampl_start', 'ampl_stop', 'ampl_user_max', 'ampl_user_max_en',
                                 'alc_en', 'alc_source', 'alc_bw', 'alc_bw_auto_en',
                                 'attenuation_db', 'attenuation_auto_en', 'amp_flatness_corr_en',
                                 'output_blanking_en', 'output_blanking_auto_en',
                                 'freq_mode', 'freq_cw', 'freq_low_spurs_en', 'freq_start', 'freq_stop',
                                 'freq_multiplier', 'freq_offset', 'freq_offset_en', 'freq_reference', 'freq_reference_en',
                                 'phase', 'mod_en', 'mod_am_en', 'mod_fm_en', 'mod_phase_en', 'mod_pulse_en', options)
    def _create_devs(self):
        self.ampl_min_lim = scpiDevice(':POWer:MINimum:LIMit', choices=ChoiceStrings('LOW', 'HIGH'))
        self.ampl_user_max = scpiDevice(':POWer:USER:MAX', str_type=float, doc='unit depends on device ampl_unit', setget=True)
        self.ampl_user_max_en = scpiDevice(':POWer:USER:ENABle', str_type=bool)
        self.freq_low_spurs_en = scpiDevice(':FREQuency:LSPurs:STATe', str_type=bool)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
    def phase_sync(self):
        """
        Sets the current output phase as a zero reference.
        """
        self.write('PHASe:REFerence')


#######################################################
##    Agilent multimeter
#######################################################

class agilent_multi_34410A(visaInstrumentAsync):
    """
    This controls the agilent digital multimeters.
    Note that most of the devices requires a proper selection of the
    mode first. They can behave differently in various mode.

    Important devices:
     readval  (default alias), same as initiating a measurement, waiting then fetch
     fetch
     fetch_all   (returns more than one value when count >1)
     fetch_std   (returns the standard deviation when count >1)
     mode
     aperture
     aperture_en
     nplc
     sample_count
     range
     autorange
     zero
    Useful method:
     set_long_avg  To average for even longer than 1s (controls aperture and sample_count)
     show_long_avg To see the current averaging settings.

    Do NOT use the mode parameter of devices (like fetch) when creating
    files (sweep, trace, ...) because the headers in the file might be incorrect.
    Set it first.

    """
    def math_clear(self):
        self.write('CALCulate:AVERage:CLEar')
    def _current_config(self, dev_obj=None, options={}):
        mode = self.mode.getcache()
        choices = self.mode.choices
        baselist =('mode', 'trig_src', 'trig_delay', 'trig_count',
                   'sample_count', 'sample_src', 'sample_timer', 'trig_delayauto',
                   'line_freq', 'math_func')
        if mode in choices[['curr:ac', 'volt:ac']]:
            extra = ('bandwidth', 'autorange', 'range',
                     'null_en', 'null_val', 'peak_mode_en')
        elif mode in choices[['volt', 'curr']]:
            extra = ('nplc', 'aperture', 'aperture_en', 'zero', 'autorange', 'range',
                     'null_en', 'null_val', 'peak_mode_en')
            if mode in choices[['volt']]:
                extra += ('voltdc_impedance_autoHigh',)
        elif mode in choices[['cont', 'diode']]:
            extra = ()
        elif mode in choices[['freq', 'period']]:
            extra = ('aperture','null_en', 'null_val',  'freq_period_p_band',
                        'freq_period_autorange', 'freq_period_volt_range')
        elif mode in choices[['res', 'fres']]:
            extra = ('nplc', 'aperture', 'aperture_en', 'autorange', 'range',
                     'null_en', 'null_val', 'res_offset_comp')
            if mode in choices[['res']]:
                extra += ('zero',)
        elif mode in choices[['cap']]:
            extra = ('autorange', 'range', 'null_en', 'null_val')
        elif mode in choices[['temp']]:
            extra = ('nplc', 'aperture', 'aperture_en', 'null_en', 'null_val',
                     'zero', 'temperature_transducer', 'temperature_transducer_subtype')
            t_ch = self.temperature_transducer.choices
            if self.temperature_transducer.getcache() in t_ch[['rtd', 'frtd']]:
                extra += ('temperature_transducer_rtd_ref', 'temperature_transducer_rtd_off')
        return self._conf_helper(*(baselist + extra + (options,)))
    def set_long_avg(self, time, force=False):
        """
        Select a time in seconds.
        It will change the aperture accordingly (and round it to the nearest nplc
        unless force=True).
        If time is greater than 1 s, an alternative mode
        with a smaller aperture (10 nplc) and a repeat count is used. That
        mode also waits trig_delay between each count.
        In that mode, you can use fetch_std to return the statistical error
        on the measurement.
        """
        # update mode first, so aperture applies to correctly
        self.mode.get()
        line_period = 1./self.line_freq.getcache()
        if time > 1.:
            width = 10*line_period
            count = round(time/width)
            self.sample_src.set('immediate')
        else:
            count = 1
            width = time
            if not force:
                width = line_period*round(width/line_period)
        self.aperture.set(width)
        self.sample_count.set(count)
    def show_long_avg(self):
        # update mode first, so aperture applies to correctly
        self.mode.get()
        count = self.sample_count.get()
        aper_en = self.aperture_en.get()
        if aper_en:
            width = self.aperture.get()
            width_str = 'aperture=%g'%width
        else:
            line_period = 1./self.line_freq.getcache()
            nplc = self.nplc.get()
            width = nplc * line_period
            width_str = 'nplc=%g'%nplc
        count_str = ''
        if count > 1:
            count_str = ', sample_count=%i'%count
        width = width*count
        print 'The full avg time is %f s (%s%s)'%(width, width_str, count_str)
        return width
    def _create_devs(self):
        # This needs to be last to complete creation
        ch = ChoiceStrings(
          'CURRent:AC', 'VOLTage:AC', 'CAPacitance', 'CONTinuity', 'CURRent', 'VOLTage',
          'DIODe', 'FREQuency', 'PERiod', 'RESistance', 'FRESistance', 'TEMPerature', quotes=True)
        self.mode = scpiDevice('FUNC', choices=ch)
        def devOption(lims, *arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options_lim = kwarg.pop('options_lim', {}).copy()
            options.update(mode=self.mode)
            options_lim.update(mode=lims)
            kwarg.update(options=options)
            kwarg.update(options_lim=options_lim)
            return scpiDevice(*arg, **kwarg)
        # _decode_float64_avg is needed because count points are returned
        # fetch? and read? return sample_count*trig_count data values (comma sep)
        self.fetch = scpiDevice(getstr='FETCh?',str_type=decode_float64_avg, autoinit=False, trig=True) #You can't ask for fetch after an aperture change. You need to read some data first.
        # autoinit false because it can take too long to readval
        #self.readval = scpiDevice(getstr='READ?',str_type=_decode_float64_avg, autoinit=False, redir_async=self.fetch) # similar to INItiate followed by FETCh.
        self.fetch_all = scpiDevice(getstr='FETCh?',str_type=decode_float64, autoinit=False, trig=True)
        self.fetch_std = scpiDevice(getstr='FETCh?',str_type=decode_float64_meanstd, autoinit=False, trig=True, doc="""
             Use this to obtain the standard deviation(using ddof=1) of the fetch.
             It is the standard deviation of the mean (it decreases when the averaging is longer).
             This will only return something usefull for long time averages where
             count is > 1. This is the case with set_long_avg(time) for time longer
             than 1s.
             (fetch_all needs to have more than one value)
        """)
        self.line_freq = scpiDevice(getstr='SYSTem:LFRequency?', str_type=float) # see also SYST:LFR:ACTual?
        ch_aper = ch[['volt', 'curr', 'res', 'fres', 'temp', 'freq', 'period']]
        ch_aper_nplc = ch[['volt', 'curr', 'res', 'fres', 'temp']]
        aper_max = float(self.ask('volt:aper? max'))
        aper_min = float(self.ask('volt:aper? min'))
        # TODO handle freq, period where valid values are .001, .010, .1, 1 (between .001 and 1 can use setget)
        self.aperture = devOption(ch_aper, '{mode}:APERture', str_type=float, min = aper_min, max = aper_max, setget=True)
        self.aperture_en = devOption(ch_aper_nplc, '{mode}:APERture:ENabled', str_type=bool)
        self.nplc = devOption(ch_aper_nplc, '{mode}:NPLC', str_type=float,
                                   choices=[0.006, 0.02, 0.06, 0.2, 1, 2, 10, 100])
        ch_band = ch[['curr:ac', 'volt:ac']]
        self.bandwidth = devOption(ch_band, '{mode}:BANDwidth', str_type=float,
                                   choices=[3, 20, 200]) # in Hz
        ch_freqperi = ch[['freq', 'per']]
        self.freq_period_p_band = devOption(ch_freqperi, '{mode}:RANGe:LOWer', str_type=float,
                                   choices=[3, 20, 200]) # in Hz
        self.freq_period_autorange = devOption(ch_freqperi, '{mode}:VOLTage:RANGe:AUTO', str_type=bool) # Also use ONCE (immediate autorange, then off)
        self.freq_period_volt_range = devOption(ch_freqperi, '{mode}:VOLTage:RANGe', str_type=float,
                                                choices=[.1, 1., 10., 100., 1000.]) # Setting this disables auto range

        ch_zero = ch[['volt', 'curr', 'res', 'temp']] # same as ch_aper_nplc wihtout fres
        self.zero = devOption(ch_zero, '{mode}:ZERO:AUTO', str_type=bool,
                              doc='Enabling auto zero double the time to take each point (the value and a zero correction is done for each point)') # Also use ONCE (immediate zero, then off)
        ch_range = ch[[0, 1, 2,  4, 5,  9, 10]] # everything except continuity, diode, freq, per and temperature
        self.autorange = devOption(ch_range, '{mode}:RANGE:AUTO', str_type=bool) # Also use ONCE (immediate autorange, then off)
        range_ch = ChoiceDevDep(self.mode, {ch[['volt', 'volt:ac']]:[.1, 1., 10., 100., 1000.],
                                            ch[['curr', 'curr:ac']]:[.1e-3, 1e-3, 1e-2, 1e-1, 1, 3],
                                            ch[['fres', 'res']]:[1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9] }) # in V, A, Ohm
        self.range = devOption(ch_range, '{mode}:RANGe', str_type=float, choices=range_ch) # Setting this disables auto range
        ch_null = ch[[0, 1, 2,  4, 5,  7, 8, 9, 10, 11]] # everything except continuity and diode
        self.null_en = devOption(ch_null, '{mode}:NULL', str_type=bool)
        self.null_val = devOption(ch_null, '{mode}:NULL:VALue', str_type=float)
        self.voltdc_impedance_autoHigh = scpiDevice('VOLTage:IMPedance:AUTO', str_type=bool, doc='When True and V range <= 10V then impedance >10 GO else it is 10 MOhm')
        tch = ChoiceStrings('FRTD', 'RTD', 'FTHermistor', 'THERmistor')
        self.temperature_transducer = scpiDevice('TEMPerature:TRANsducer:TYPE', choices=tch)
        tch_rtd = tch[['frtd', 'rtd']]
        ch_temp_typ = ChoiceDevDep(self.temperature_transducer, {tch_rtd:[85], None:[2252, 5000, 10000]})
        self.temperature_transducer_subtype = scpiDevice('TEMPerature:TRANsducer:{trans}:TYPE',
                                        choices = ch_temp_typ,
                                        options=dict(trans=self.temperature_transducer),
                                        str_type=int)
        self.temperature_transducer_rtd_ref = scpiDevice('TEMPerature:TRANsducer:{trans}:RESistance',
                                        min = 49, max= 2.1e3, str_type=float,
                                        options=dict(trans=self.temperature_transducer),
                                        options_lim=dict(trans=tch_rtd))
        self.temperature_transducer_rtd_off = scpiDevice('TEMPerature:TRANsducer:{trans}:OCOMpensated', str_type=bool,
                                        options=dict(trans=self.temperature_transducer),
                                        options_lim=dict(trans=tch_rtd))

        ch_compens = ch[['res', 'fres']]
        self.res_offset_comp = devOption(ch_compens, '{mode}:OCOMpensated', str_type=bool)
        ch_peak = ch[['volt', 'volt:ac', 'curr', 'curr:ac']]
        self.peak_mode_en = devOption(ch_peak, '{mode}:PEAK:STATe', str_type=bool)
        peak_op = dict(peak=self.peak_mode_en)
        peak_op_lim = dict(peak=[True])
        self.fetch_peaks_ptp = devOption(ch_peak, 'FETCh:{mode}:PTPeak', str_type=float,
                                         doc='Call this after a fetch or readval',
                                         options=peak_op, options_lim=peak_op_lim, autoinit=False, trig=True)
        ch_peak_minmax = ch[['volt', 'curr']]
        self.fetch_peaks_min = devOption(ch_peak_minmax, 'FETCh:{mode}:PEAK:MINimum', str_type=float,
                                         doc='Call this after a fetch or readval',
                                         options=peak_op, options_lim=peak_op_lim, autoinit=False, trig=True)
        self.fetch_peaks_max = devOption(ch_peak_minmax, 'FETCh:{mode}:PEAK:MAXimum', str_type=float,
                                         doc='Call this after a fetch or readval',
                                         options=peak_op, options_lim=peak_op_lim, autoinit=False, trig=True)
        ch = ChoiceStrings('NULL', 'DB', 'DBM', 'AVERage', 'LIMit')
        self.math_func = scpiDevice('CALCulate:FUNCtion', choices=ch)
        self.math_state = scpiDevice('CALCulate:STATe', str_type=bool)
        self.math_avg = scpiDevice(getstr='CALCulate:AVERage:AVERage?', str_type=float, trig=True)
        self.math_count = scpiDevice(getstr='CALCulate:AVERage:COUNt?', str_type=float, trig=True)
        self.math_max = scpiDevice(getstr='CALCulate:AVERage:MAXimum?', str_type=float, trig=True)
        self.math_min = scpiDevice(getstr='CALCulate:AVERage:MINimum?', str_type=float, trig=True)
        self.math_ptp = scpiDevice(getstr='CALCulate:AVERage:PTPeak?', str_type=float, trig=True)
        self.math_sdev = scpiDevice(getstr='CALCulate:AVERage:SDEViation?', str_type=float, trig=True)
        ch = ChoiceStrings('IMMediate', 'BUS', 'EXTernal')
        self.trig_src = scpiDevice('TRIGger:SOURce', choices=ch)
        self.trig_delay = scpiDevice('TRIGger:DELay', str_type=float) # seconds
        self.trig_count = scpiDevice('TRIGger:COUNt', str_type=float)
        self.sample_count = scpiDevice('SAMPle:COUNt', str_type=int)
        ch = ChoiceStrings('IMMediate', 'TIMer')
        self.sample_src = scpiDevice('SAMPle:SOURce', choices=ch)
        self.sample_timer = scpiDevice('SAMPle:TIMer', str_type=float) # seconds
        self.trig_delayauto = scpiDevice('TRIGger:DELay:AUTO', str_type=bool)
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval
        super(type(self),self)._create_devs()
        # For INITiate: need to wait for completion of triggered measurement before calling it again
        # for trigger: *trg and visa.trigger seem to do the same. Can only be called after INItiate and
        #   during measurement.
        # To get completion stats: write('INITiate;*OPC') and check results from *esr? bit 0
        #   enable with *ese 1 then check *stb bit 5 (32) (and clear *ese?)
        # Could also ask for data and look at bit 4 (16) output buffer ready
        #dmm1.mathfunc.set('average');dmm1.math_state.set(True)
        #dmm1.write('*ese 1;*sre 32')
        #dmm1.write('init;*opc')
        #dmm1.read_status_byte()
        #dmm1.ask('*stb?;*esr?')
        #dmm1.math_count.get(); dmm1.math_avg.get() # no need to reset count, init does that
        #visa.vpp43.enable_event(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, visa.vpp43.VI_QUEUE)
        #dmm1.write('init;*opc')
        #dmm1.read_status_byte()
        #visa.vpp43.wait_on_event(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, 10000)
        #dmm1.read_status_byte()
        #dmm1.ask('*stb?;*esr?')
        #  For installing handler (only seems to work with USB not GPIB for NI visa library. Seems to work fine with Agilent IO visa)
        #   def event_handler(vi, event_type, context, use_handle): stb = visa.vpp43.read_stb(vi);  print 'helo 0x%x'%stb, event_type==visa.vpp43.VI_EVENT_SERVICE_REQ, context, use_handle; return visa.vpp43.VI_SUCCESS
        #   def event_handler(vi, event_type, context, use_handle): stb = visa.vpp43.read_stb(vi);  print 'HELLO 0x%x'%stb,vi; return visa.vpp43.VI_SUCCESS
        #   visa.vpp43.install_handler(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, event_handler)
        #   visa.vpp43.enable_event(dmm1.visa.vi, visa.vpp43.VI_EVENT_SERVICE_REQ, visa.vpp43.VI_HNDLR)
        #   The handler is called for all srq on the bus (not necessarily the instrument we want)
        #     the vi parameter refers to the installed handler, not the actual srq source
        #The wait_on_event seems to be handling only event from src, not affecting the other instruments srq
        # reading the status is not necessary after wait to clear srq (cleared during wait internal handler) for agilent visa
        #  but it is necessary for NI visa (it will receive the SRQ like for agilent but will not transmit
        #      the next ones to the wait queue until acknowledged)
        #      there seems to be some inteligent buffering going on, which is different in agilent and NI visas
        # When wait_on_event timesout, it produces the VisaIOError (VI_ERROR_TMO) exception
        #        the error code is available as VisaIOErrorInstance.error_code


#######################################################
##    Agilent RF attenuator
#######################################################

class agilent_rf_Attenuator(visaInstrument):
    """
    This controls an Agilent Attenuation Control Unit
    Use att_level_dB to get or change the attenuation level.
    Use cal_att_level_dB to obtain the calibrated attenuation.
    Note that the attenuation for 0dB is not included for the
    other calibration levels.
    """
    def _current_config(self, dev_obj=None, options={}):
        return self._conf_helper('att_level_dB', 'cal_att_level_dB', 'current_freq_Hz',
                                 'relative_en', 'relative_ref_dB', options)
    def _att_level_dB_getdev(self):
        return int(self.ask('ATTenuation?'))
    def _att_level_dB_setdev(self, val):
        val = int(val)
        self.write('ATTenuation %i'%val)
        time.sleep(0.02)
    def _create_devs(self):
        self.relative_en = scpiDevice('RELative', str_type=bool)
        self.relative_ref_dB = scpiDevice('REFerence', str_type=float)
        # TODO implement RELative:LEVel  (only when relative is enabled)
        self.current_freq_Hz = MemoryDevice(1e9, min=0, max=26.5e9)
        self._devwrap('att_level_dB', min=0, max=101)
        #self.att_level_dB = scpiDevice('ATTenuation', str_type=int, min=0, max=101)
        self.alias = self.att_level_dB
        self.cal_att_level_dB = scpiDevice(getstr='CORRection? {att},{freq}', str_type=float,
                                           options=dict(att=self.att_level_dB, freq=self.current_freq_Hz),
                                           options_apply=['freq'])
        # This needs to be last to complete creation
        super(agilent_rf_Attenuator, self)._create_devs()


#######################################################
##    Agilent infiniiVision Scopes
#######################################################

class infiniiVision_3000(visaInstrument):
    """
     To use this instrument, the most useful devices are probably:
       fetch  (only works in the main timebase mode, not for roll or XY or zoom)
       snap_png
    """
    def init(self, full=False):
        self.write(':WAVeform:FORMat WORD') # can be WORD BYTE or ASCii
        self.write(':WAVeform:BYTeorder LSBFirst') # can be LSBFirst pr MSBFirst
        self.write(':WAVeform:UNSigned ON') # ON,1 or OFF,0
        super(infiniiVision_3000, self).init(full=full)
    def _current_config(self, dev_obj=None, options={}):
        # TODO:  improve this
        return self._conf_helper('source', 'points_mode', 'preamble', options)
    def digitize(self):
        """
        Starts an acquisition
        """
        self.write(':DIGitize')
    def run_trig(self):
        """
        The same as pressing run
        """
        self.write(':RUN')
    def stop_trig(self):
        """
        The same as pressing stop
        """
        self.write(':STOP')
    def single_trig(self):
        """
        The same as pressing single
        """
        self.write(':SINGle')
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
            multi.append('ch%i'%c)
        fmt = self.fetch._format
        multi = tuple(multi)
        fmt.update(multi=multi, graph=[], xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_getdev(self, ch=None, xaxis=True):
        """
           Options available: ch, xaxis
            -ch:    a single value or a list of values for the channels to capture
                    a value of None selects all the active ones.(1-4)
            -xaxis: Set to True (default) to return the timebase as the first column
        """
        ch = self._fetch_ch_helper(ch)
        if ch==None:
            ch = self.find_all_active_channels()
        if not isinstance(ch, (list)):
            ch = [ch]
        ret = []
        first = True
        for c in ch:
            self.source.set('chan%i'%c)
            pream = self.preamble.get()
            data = self.data.get()*1. # make it floats
            data_real = (data - pream['yref']) * pream['yinc'] + pream['yorig']
            if xaxis and first:
                first = False
                ret = [(np.arange(pream['points'])- pream['xref']) * pream['xinc'] + pream['xorig']]
            ret.append(data_real)
        ret = np.asarray(ret)
        if ret.shape[0]==1:
            ret=ret[0]
        return ret
    def find_all_active_channels(self):
        orig_ch = self.current_channel.get()
        ret = []
        for i in range(1,5):
            if self.channel_display.get(ch=i):
                ret.append(i)
        self.current_channel.set(orig_ch)
        return ret
    def _create_devs(self):
        self.snap_png = scpiDevice(getstr=':DISPlay:DATA? PNG, COLor', raw=True, str_type=_decode_block_base, autoinit=False, doc="Use like this: get(s500.snap_png, filename='testname.png')\nThe .png extensions is optional. It will be added if necessary.")
        self.snap_png._format['bin']='.png'
        self.inksaver = scpiDevice(':HARDcopy:INKSaver', str_type=bool, doc='This control whether the graticule colors are inverted or not.') # ON, OFF 1 or 0
        self.data = scpiDevice(getstr=':waveform:DATA?', raw=True, str_type=decode_uint16_bin, autoinit=False) # returns block of data (always header# for asci byte and word)
          # also read :WAVeform:PREamble?, which provides, format(byte,word,ascii),
          #  type (Normal, peak, average, HRes), #points, #avg, xincr, xorg, xref, yincr, yorg, yref
          #  xconv = xorg+x*xincr, yconv= (y-yref)*yincr + yorg
        self.points = scpiDevice(':WAVeform:POINts', str_type=int) # 100, 250, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000, 2000000, 4000000, 8000000
        self.points_mode = scpiDevice(':WAVeform:POINts:MODE', choices=ChoiceStrings('NORMal', 'MAXimum', 'RAW'))
        self.preamble = scpiDevice(getstr=':waveform:PREamble?', choices=ChoiceMultiple(['format', 'type', 'points', 'count', 'xinc', 'xorig', 'xref', 'yinc', 'yorig', 'yref'],[int, int, int, int, float, float, int, float, float, int]))
        self.waveform_count = scpiDevice(getstr=':WAVeform:COUNt?', str_type=int)
        self.acq_type = scpiDevice(':ACQuire:TYPE', choices=ChoiceStrings('NORMal', 'AVERage', 'HRESolution', 'PEAK'))
        self.acq_mode= scpiDevice(':ACQuire:MODE', choices=ChoiceStrings('RTIM', 'SEGM'))
        self.average_count = scpiDevice(':ACQuire:COUNt', str_type=int, min=2, max=65536)
        self.acq_samplerate = scpiDevice(getstr=':ACQuire:SRATe?', str_type=float)
        self.acq_npoints = scpiDevice(getstr=':ACQuire:POINts?', str_type=int)
        self.current_channel = MemoryDevice(1, min=1, max=4)
        def devChannelOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.source = scpiDevice(':WAVeform:SOURce', choices=ChoiceStrings('CHANnel1', 'CHANnel2', 'CHANnel3', 'CHANnel4'))
        self.channel_display = devChannelOption('CHANnel{ch}:DISPlay', str_type=bool)
        self.timebase_mode= scpiDevice(':TIMebase:MODE', choices=ChoiceStrings('MAIN', 'WINDow', 'XY', 'ROLL'))
        self.timebase_pos= scpiDevice(':TIMebase:POSition', str_type=float) # in seconds from trigger to display ref
        self.timebase_range= scpiDevice(':TIMebase:RANGe', str_type=float) # in seconds, full scale
        self.timebase_reference= scpiDevice(':TIMebase:REFerence', choices=ChoiceStrings('LEFT', 'CENTer', 'RIGHt'))
        self.timebase_scale= scpiDevice(':TIMebase:SCALe', str_type=float) # in seconds, per div
        #TODO: add a bunch of CHANNEL commands, Then MARKER and MEASure, TRIGger
        self._devwrap('fetch', autoinit=False, trig=True)
        #self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()


#######################################################
##    Agilent EXA signal analyzer
#######################################################

class agilent_EXA(visaInstrumentAsync):
    """
    To use this instrument, the most useful devices are probably:
        fetch, readval
        marker_x, marker_y
        snap_png
    Some commands are available:
        abort
    A lot of other commands require a selected trace or a mkr
    see current_trace, current_mkr
    They are both memory device on the computer. They are not changeable from
    the hardware itself.

    Note about fetch_base and get_trace. They both return the same y data
    The units are given by y_unit and it is not affected by y offset.
    get_trace is immediate, fetch_base waits for the end of the current sweep
    if needed (including averaging).
    fetch_base includes the correct x scale. It can be different from the currently active
    x scale when not updating. x-scales are affected by freq offset.
    """
    def init(self, full=False):
        self.Ro = 50
        self.write(':format REAL,64')
        self.write(':format:border swap')
        super(agilent_EXA, self).init(full=full)
    def _async_trig(self):
        self.cont_trigger.set(False)
        super(agilent_EXA, self)._async_trig()
    def abort(self):
        self.write('ABORt')
    def _current_config_trace_helper(self, traces=None):
        # traces needs to be a list or None
        just_one = False
        if not isinstance(traces, (list)):
            just_one = True
            traces = [traces]
        trace_conf = ['current_trace', 'trace_type', 'trace_updating', 'trace_displaying',
                                      'trace_detector', 'trace_detector_auto']
        ret = []
        for t in traces:
            if t != None:
                self.current_trace.set(t)
            tret = []
            for n in trace_conf:
                # follows _conf_helper
                val = _repr_or_string(getattr(self, n).getcache())
                tret.append(val)
            if ret == []:
                ret = tret
            else:
                ret = [old+', '+new for old, new in zip(ret, tret)]
        if just_one:
            ret = [n+'='+v for n, v in zip(trace_conf, ret)]
        else:
            ret = [n+'=['+v+']' for n, v in zip(trace_conf, ret)]
        return ret
    def _current_config(self, dev_obj=None, options={}):
        # Assume SA instrument mode, SAN measurement (config)
        if options.has_key('trace'):
            self.current_trace.set(options['trace'])
        if options.has_key('mkr'):
            self.current_mkr.set(options['mkr'])
        extra = []
        base_conf = self._conf_helper('instrument_mode', 'meas_mode', 'attenuation_db', 'attenuation_auto', 'y_unit', 'uW_path_bypass',
                                 'auxif_sel', 'preamp_en', 'preamp_band', 'cont_trigger',
                                 'freq_span', 'freq_start', 'freq_center', 'freq_stop', 'freq_offset', 'input_coupling',
                                 'gain_correction_db', 'ext_ref', 'ext_ref_mode', 'sweep_time', 'sweep_time_auto',
                                 'sweep_time_rule', 'sweep_time_rule_auto', 'sweep_type', 'sweep_type_auto', 'sweep_type_rule',
                                 'sweep_type_rule_auto', 'sweep_fft_width', 'sweep_fft_width_auto', 'sweep_npoints',
                                 'bw_res', 'bw_res_auto', 'bw_video', 'bw_video_auto', 'bw_video_auto_ratio', 'bw_video_auto_ratio_auto',
                                 'bw_res_span', 'bw_res_span_auto', 'bw_res_shape', 'bw_res_gaussian_type', 'noise_eq_bw',
                                 'average_count', 'average_type', 'average_type_auto', options)
        # trace
        if dev_obj in [self.readval, self.fetch]:
            traces_opt = self._fetch_traces_helper(options.get('traces'), options.get('updating'))
            extra = self._current_config_trace_helper(traces_opt)
        elif dev_obj in [self.fetch_base, self.get_trace]:
            extra = self._current_config_trace_helper()
        # marker dependent
        if dev_obj in [self.marker_x, self.marker_y, self.marker_z]:
            extra = self._conf_helper('current_mkr', 'marker_mode', 'marker_x_unit', 'marker_x_unit_auto', 'marker_ref', 'marker_trace',
                                      'marker_x', 'marker_y', 'marker_z', 'marker_trace',
                                      'marker_function', 'marker_function_band_span', 'marker_function_band_left',
                                      'marker_function_band_right', 'peak_search_continuous')
            old_trace = self.current_trace.get()
            extra += self._current_config_trace_helper(self.marker_trace.getcache())
            self.current_trace.set(old_trace)
        return extra+base_conf
    def _noise_eq_bw_getdev(self):
        """
        Using the bw_res and bw_res_shape this estimates the bandwith
        necessary to convert the data into power density.

        For gaussian filters the error in the estimate compared to the marker
        result is at most 0.06 dB (1.4% error) at 4 MHz (DB3),
        otherwise it is mostly within 0.01 dB (0.23%)
        For Flattop filters the error is at most -0.45 dB at 8 MHz (11%),
        otherwise it is mostly 0.040 - 0.050 (0.92-1.12%), centered around
        0.045 dB (1.0% offset) for bw below 120 kHz. (EXA N9010A, MY51170142)
        The correction means the equivalent bandwidth used for markers is
        1% greater than the selected value of the flat bandwidth. To correct
        for this, you can substract the noise density by 0.045 dB (or divide by
        1.010 if linear power scale).

        To see this errors, or to obtain the same factor as for the markers,
        set the instrument in the following way:
            -select resolution bandwidth (range, type ...)
            -setup a trace (assume units are dB...)
            -on trace put 2 markers at the same position
            -First marker shows just the raw value
            -Second marker setup to show noise (either noise or band density function)
            -Set band span for second marker to 0 (or the a single bin)
            -Then the bandwith used for marker calculation is
             10**((marker1-marker2)/10)
        You can see both by enabling the marker table. Note that for the function
        results the Y and function column should be the same here, but when the
        band span is larger they will be different. The Y value is the value of
        the function when the sweep has reached the marker position so it uses
        old values after the marker and so is not a valid result. You should
        consider the function result as the proper one. That is the value
        returned by marker_y devce in that case.

        The band power function is the integral of the band density over the
        selected band span (a span of 0 is the same as a span of one bin).
        So when band span is one bin:
            band_power(dBm)-band_density(dBm) = 10*log10(bin_width(Hz))
            bin_width = (freq_stop-freq_start)/(npoints-1)

        The distinction between the noise function and the band density function
        is that the noise function tries to apply correction for non-ideal
        detectors (peak, negative peak) or wrong averaging (volt, log Pow).
        The correction is calculated assuming the incoming signal is purely noise,
        and considers the video bandwidth.
        The band density function makes no such assumption and will return
        incorrect values for wrong detector/averaging. The best result is normally
        obtained with averaging detector in RMS mode.
        """
        bw = self.bw_res.get()
        bw_mode = self.bw_res_shape.get()
        if bw_mode in self.bw_res_shape.choices[['gaussian']]:
            # The filters are always the same. They are defined for db3
            # but they are reported differently in the other modes.
            # We need the noise one.
            # In theory:
            #  The 3dB full width is 2*sqrt(log(2))*sigma
            #  The 6dB full width is sqrt(2) times 3dB
            #  The noise width is sqrt(pi)/(2*sqrt(log(2))) times 3dB (and is equivalent bw for power: from integral of V**2)
            #  The impulse width is sqrt(2) times noise (and is equivalent bw for amplitude: from integral of V)
            # In practice we use the noise and it is probably related to the
            # 3dB by some calibration. The conversion factor between 3dB and noise returned by
            # the instrument is not a constant (it is ~1.065).
            old_gaus_type = self.bw_res_gaussian_type.get()
            self.bw_res_gaussian_type.set('noise')
            bw = self.bw_res.get()
            self.bw_res_gaussian_type.set(old_gaus_type)
        else: # flat
            # Normally the equivalent noise bandwidth of a flat filter
            # is the bw of the filter. However, in practice, it could be different.
            bw = self.bw_res.get()
            # TODO maybe decide to apply the correction
            #bw *= 1.01
        return bw
    def _fetch_getformat(self, **kwarg):
        unit = kwarg.get('unit', 'default')
        xaxis = kwarg.get('xaxis', True)
        traces = kwarg.get('traces', None)
        updating = kwarg.get('updating', True)
        traces = self._fetch_traces_helper(traces, updating)
        if xaxis:
            zero_span = self.freq_span.get() == 0
            if zero_span:
                multi = 'time(s)'
            else:
                multi = 'freq(Hz)'
            multi = [multi]
        else:
            multi = []
        for t in traces:
            multi.append('trace%i'%t)
        fmt = self.fetch._format
        multi = tuple(multi)
        fmt.update(multi=multi, graph=[], xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_traces_helper(self, traces, updating=True):
        """
        When updating is True, only updating trace are selected when
        traces=None. Otherwise all visible traces are selected.
        """
        if isinstance(traces, (tuple, list)):
            pass
        elif traces != None:
            traces = [traces]
        else: # traces == None
            traces = []
            old_trace = self.current_trace.get()
            for t in range(1,7):
                if updating and self.trace_updating.get(trace=t):
                    traces.append(t)
                elif not updating and self.trace_displaying.get(trace=t):
                    traces.append(t)
            self.current_trace.set(old_trace)
        return traces
    def _convert_unit(self, v, from_unit, to_unit, bw):
        Ro = self.Ro
        if to_unit == 'default':
            return v
        from_unit = from_unit.upper()
        db_list = ['DBM', 'DBMV', 'DBMA', 'DBUV', 'DBUA', 'DBUVM', 'DBUAM', 'DBPT', 'DBG']
        db_ref = [1e-3, 2e-8, 5e-5, 2e-14, 5e-11, 0, 0, 0, 0] # in W
        if from_unit in db_list:
            in_db = True
            i = db_list.index(from_unit)
            in_ref = db_ref[i]
            if in_ref == 0:
                raise ValueError, self.perror("Don't know how to convert from antenna unit %s"%from_unit)
        else: # V, W and A
            in_db = False
            # convert to W
            if from_unit == 'V':
                v = v**2 / Ro
            elif from_unit == 'A':
                v = v**2 * Ro
        to_db_list = ['dBm', 'dBm_Hz']
        to_lin_list = ['W', 'W_Hz', 'V', 'V_Hz', 'V2', 'V2_Hz']
        if to_unit not in to_db_list+to_lin_list:
            raise ValueError, self.perror("Invalid conversion unit: %s"%to_unit)
        if not to_unit.endswith('_Hz'):
            bw = 0
        if to_unit in to_db_list:
            if in_db:
                v = v + 10*np.log10(in_ref/1e-3)
            else: # in is in W
                v = 10.*np.log10(v/1e-3)
            if bw:
                v -= 10*np.log10(bw)
        else: # W, V and V2 and _Hz variants
            if in_db:
                v = in_ref*10.**(v/10.)
            if to_unit in ['V', 'V_Hz']:
                bw = np.sqrt(bw)
                v = np.sqrt(v*Ro)
            elif to_unit in ['V2', 'V2_Hz']:
                v = v*Ro
            if bw:
                v /= bw
        return v
    def _fetch_getdev(self, traces=None, updating=True, unit='default', xaxis=True):
        """
         Available options: traces, updating, unit, xaxis
           -traces:  can be a single value or a list of values.
                     The values are integer representing the trace number (1-6)
           -updating: is used when traces is None. When True (default) only updating traces
                      are fetched. Otherwise all visible traces are fetched.
           -unit: can be default (whatever the instrument gives) or
                       dBm    for dBm
                       W      for Watt
                       V      for Volt
                       V2     for Volt**2
                       dBm_Hz for noise density
                       W_Hz   for W/Hz
                       V_Hz   for V/sqrt(Hz)
                       V2_Hz  for V**2/Hz
                 It can be a single value or a vector the same length as traces
                 See noise_eq_bw device for information about the
                 bandwidth used for _Hz unit conversion.
            -xaxis:  when True(default), the first column of data is the xaxis

           This version of fetch uses get_trace instead of fetch_base so it never
           block. It assumes all the data have the same x-scale (should be the
           case when they are all updating).
        """
        traces = self._fetch_traces_helper(traces, updating)
        if xaxis:
            ret = [self.get_xscale()]
        else:
            ret = []
        if not isinstance(unit, (list, tuple)):
            unit = [unit]*len(traces)
        base_unit = self.y_unit.get()
        noise_bw = self.noise_eq_bw.get()
        for t, u in zip(traces, unit):
            v = self.get_trace.get(trace=t)
            v = self._convert_unit(v, base_unit, u, noise_bw)
            ret.append(v)
        ret = np.asarray(ret)
        if ret.shape[0]==1:
            ret=ret[0]
        return ret
    def restart_averaging(self):
        command = ':AVERage:CLEar'
        self.write(command)
    def peak_search(self, mkr=None, next=False):
        """
        next can be True (same as finding next)
        left  to find the left
        right to find the next peak to the right
        """
        if mkr == None:
            mkr = self.current_mkr.getcache()
        if mkr<1 or mkr>12:
            raise ValueError, self.perror('mkr need to be between 1 and 12')
        if next == True:
            next = ':NEXT'
        elif next:
            next = ':'+next
        else:
            next = ''
        self.write('CALCulate:MARKer{mkr}:MAXimum'.format(mkr=mkr)+next)
    def marker_to_center_freq(self, mkr=None):
        if mkr == None:
            mkr = self.current_mkr.getcache()
        if mkr<1 or mkr>12:
            raise ValueError, self.perror('mkr need to be between 1 and 12')
        self.write('CALCulate:MARKer{mkr}:CENTer'.format(mkr=mkr))
    def get_xscale(self):
        """
        Returns the currently active x scale. It uses cached values so make sure
        they are up to date.
        This scale is recalculated but produces the same values (within floating
        point errors) as the instrument.
        """
        zero_span = self.freq_span.get() == 0
        if zero_span:
            offset = start = 0
            stop = self.sweep_time.get()
        else:
            start = self.freq_start.get()
            stop = self.freq_stop.get()
            offset = self.freq_offset.get()
        npts = self.sweep_npoints.get()
        return np.linspace(start+offset, stop+offset, npts)
    def _create_devs(self):
        self.installed_options = scpiDevice(getstr='*OPT?', str_type=quoted_string())
        ql = quoted_list(sep=', ')
        instrument_mode_list = ql(self.ask(':INSTrument:CATalog?'))
        # the list is name number, make it only name
        instrument_mode_list = [i.split(' ')[0] for i in instrument_mode_list]
        self.instrument_mode = scpiDevice(':INSTrument', choices=ChoiceStrings(*instrument_mode_list))
        # This list depends on instrument mode: These are measurement type
        self.meas_mode_list = scpiDevice(getstr=':CONFigure:CATalog?', str_type=ql)
        # From the list: SAN=SANalyzer
        self.meas_mode = scpiDevice(':CONFigure:{val}:NDEFault', ':CONFigure?')
        self.attenuation_db = scpiDevice(':POWer:ATTenuation', str_type=float)
        self.attenuation_auto = scpiDevice(':POWer:ATTenuation:AUTO', str_type=bool)
        self.y_unit = scpiDevice('UNIT:POWer', choices=ChoiceStrings('DBM', 'DBMV', 'DBMA', 'DBUV', 'DBUA', 'DBUVM', 'DBUAM', 'DBPT', 'DBG', 'V', 'W', 'A'))
        self.uW_path_bypass = scpiDevice(':POWer:MW:PATH', choices=ChoiceStrings('STD', 'LNPath', 'MPBypass', 'FULL'))
        self.auxif_sel = scpiDevice(':OUTPut:AUX', choices=ChoiceStrings('SIF', 'OFF')) # others could be AIF and LOGVideo if options are installed
        self.preamp_en = scpiDevice(':POWer:GAIN', str_type=bool)
        self.preamp_band = scpiDevice(':POWer:GAIN:BAND', choices=ChoiceStrings('LOW', 'FULL'))
        self.cont_trigger = scpiDevice('INITiate:CONTinuous', str_type=bool)
        minfreq = float(self.ask(':FREQ:START? min'))
        maxfreq = float(self.ask(':FREQ:STOP? max'))
        self.freq_start = scpiDevice(':FREQuency:STARt', str_type=float, min=minfreq, max=maxfreq-10.)
        self.freq_center = scpiDevice(':FREQuency:CENTer', str_type=float, min=minfreq, max=maxfreq)
        self.freq_stop = scpiDevice(':FREQuency:STOP', str_type=float, min=minfreq, max=maxfreq)
        self.freq_offset = scpiDevice(':FREQuency:OFFset', str_type=float, min=-500e-9, max=500e9)
        self.input_coupling = scpiDevice(':INPut:COUPling', choices=ChoiceStrings('AC', 'DC'))
        self.gain_correction_db = scpiDevice(':CORREction:SA:GAIN', str_type=float)
        self.ext_ref = scpiDevice(getstr=':ROSCillator:SOURce?', str_type=str)
        self.ext_ref_mode = scpiDevice(':ROSCillator:SOURce:TYPE', choices=ChoiceStrings('INTernal', 'EXTernal', 'SENSe'))
        self.sweep_time = scpiDevice(':SWEep:TIME', str_type=float, min=1e-6, max=6000) # in sweep: 1ms-4000s, in zero span: 1us-6000s
        self.sweep_time_auto = scpiDevice(':SWEep:TIME:AUTO', str_type=bool)
        self.sweep_time_rule = scpiDevice(':SWEep:TIME:AUTO:RULes', choices=ChoiceStrings('NORMal', 'ACCuracy', 'SRESponse'))
        self.sweep_time_rule_auto = scpiDevice(':SWEep:TIME:AUTO:RULes:AUTO', str_type=bool)
        self.sweep_type = scpiDevice(':SWEep:TYPE', choices=ChoiceStrings('FFT', 'SWEep'))
        self.sweep_type_auto = scpiDevice(':SWEep:TYPE:AUTO', str_type=bool)
        self.sweep_type_rule = scpiDevice(':SWEep:TYPE:AUTO:RULes', choices=ChoiceStrings('SPEEd', 'DRANge'))
        self.sweep_type_rule_auto = scpiDevice(':SWEep:TYPE:AUTO:RULes:AUTO', str_type=bool)
        self.sweep_fft_width = scpiDevice(':SWEep:FFT:WIDTh', str_type=float)
        self.sweep_fft_width_auto = scpiDevice(':SWEep:FFT:WIDTh:AUTO', str_type=bool)
        self.sweep_npoints = scpiDevice(':SWEep:POINts', str_type=int, min=1, max=40001)
        # For SAN measurement
        # available bandwidths gaussian db3:
        #   b = around(logspace(0,1,25),1)[:-1]; b[-2]-=.1; b[10:17] +=.1
        #   r = (b*10**arange(7)[:,None]).ravel()
        #   rgaus = append(r[:-12], [4e6,5e6, 6e6, 8e6])
        # and flat:
        #   rflat = append(r[11:-35], [3.9e5, 4.3e5, 5.1e5, 6.2e5, 7.5e5, 1e6, 1.5e6, 3e6, 4e6, 5e6, 6e6, 8e6])
        self.bw_res = scpiDevice(':BANDwidth', str_type=float, min=1, max=8e6, setget=True)
        self.bw_res_auto = scpiDevice(':BANDwidth:AUTO', str_type=bool)
        self.bw_video = scpiDevice(':BANDwidth:VIDeo', str_type=float, min=1, max=50e6)
        self.bw_video_auto = scpiDevice(':BANDwidth:VIDeo:AUTO', str_type=bool)
        self.bw_video_auto_ratio = scpiDevice(':BANDwidth:VIDeo:RATio', str_type=float, min=1e-5, max=3e6)
        self.bw_video_auto_ratio_auto = scpiDevice(':BANDwidth:VIDeo:RATio:AUTO', str_type=bool)
        self.bw_res_span = scpiDevice(':FREQuency:SPAN:BANDwidth:RATio', str_type=float, min=2, max=10000)
        self.bw_res_span_auto = scpiDevice(':FREQuency:SPAN:BANDwidth:RATio:AUTO', str_type=bool)
        self.bw_res_shape = scpiDevice(':BANDwidth:SHAPe', choices=ChoiceStrings('GAUSsian', 'FLATtop'))
        self.bw_res_gaussian_type = scpiDevice(':BANDwidth:TYPE', choices=ChoiceStrings('DB3', 'DB6', 'IMPulse', 'NOISe'))
        self.average_count = scpiDevice(':AVERage:COUNt',str_type=int, min=1, max=10000)
        self.average_type = scpiDevice(':AVERage:TYPE', choices=ChoiceStrings('RMS', 'LOG', 'SCALar'))
        self.average_type_auto = scpiDevice(':AVERage:TYPE:AUTO', str_type=bool)
        self.freq_span = scpiDevice(':FREQuency:SPAN', str_type=float, min=0, doc='You can select 0 span, otherwise minimum span is 10 Hz')
        # Trace dependent
        self.current_trace = MemoryDevice(1, min=1, max=6)
        def devTraceOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(trace=self.current_trace)
            app = kwarg.pop('options_apply', ['trace'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        # trace 0 is special, The others are 1-6 and return x,y pairs
        # trace 0:  margin/limit fail, F, F, F, N dB points result, current avg count, npoints sweep, F, F, F , Mkr1xy, Mkr2xy, .., Mkr12xy
        self.fetch_base = devTraceOption(getstr=':FETCh:{measurement}{trace}?', raw=True,
                                         str_type=decode_float64_2col, autoinit=False, trig=True, options=dict(measurement=self.meas_mode))
        self.fetch0_base = scpiDevice(getstr=':FETCh:{measurement}0?', str_type=str, autoinit=False, trig=True, options=dict(measurement=self.meas_mode))
        self.trace_type = devTraceOption(':TRACe{trace}:TYPE', choices=ChoiceStrings('WRITe', 'AVERage', 'MAXHold', 'MINHold'))
        self.trace_updating = devTraceOption(':TRACe{trace}:UPDate', str_type=bool)
        self.trace_displaying = devTraceOption(':TRACe{trace}:DISPlay', str_type=bool)
        self.trace_detector = devTraceOption(':DETector:TRACe{trace}', choices=ChoiceStrings('AVERage', 'NEGative', 'NORMal', 'POSitive', 'SAMPle', 'QPEak', 'EAVerage', 'RAVerage'))
        self.trace_detector_auto = devTraceOption(':DETector:TRACe{trace}:AUTO', str_type=bool)
        self.get_trace = devTraceOption(getstr=':TRACe? TRACE{trace}', raw=True, str_type=decode_float64, autoinit=False, trig=True)
        # TODO implement trace math, ADC dither, swept IF gain FFT IF gain
        # marker dependent
        self.current_mkr = MemoryDevice(1, min=1, max=12)
        def devMkrOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_mkr)
            app = kwarg.pop('options_apply', ['mkr'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.marker_mode = devMkrOption(':CALCulate:MARKer{mkr}:MODE', choices=ChoiceStrings('POSition', 'DELTa', 'FIXed', 'OFF'))
        self.marker_x = devMkrOption(':CALCulate:MARKer{mkr}:X', str_type=float, trig=True)
        self.marker_x_unit = devMkrOption(':CALCulate:MARKer{mkr}:X:READout', choices=ChoiceStrings('FREQuency', 'TIME', 'ITIMe', 'PERiod'))
        self.marker_x_unit_auto = devMkrOption(':CALCulate:MARKer{mkr}:X:READout:AUTO', str_type=bool)
        self.marker_y = devMkrOption(':CALCulate:MARKer{mkr}:Y', str_type=float, trig=True)
        self.marker_z = devMkrOption(':CALCulate:MARKer{mkr}:Z', str_type=float, trig=True) # for spectrogram mode
        self.marker_ref = devMkrOption(':CALCulate:MARKer{mkr}:REFerence', str_type=int, min=1, max=12)
        self.marker_trace = devMkrOption(':CALCulate:MARKer{mkr}:TRACe', str_type=int, min=1, max=6)
        self.marker_function = devMkrOption(':CALCulate:MARKer{mkr}:FUNCtion', choices=ChoiceStrings('NOISe', 'BPOWer', 'BDENsity', 'OFF'))
        self.marker_function_band_span = devMkrOption(':CALCulate:MARKer{mkr}:FUNCtion:BAND:SPAN', str_type=float, min=0)
        self.marker_function_band_left = devMkrOption(':CALCulate:MARKer{mkr}:FUNCtion:BAND:LEFT', str_type=float, min=0)
        self.marker_function_band_right = devMkrOption(':CALCulate:MARKer{mkr}:FUNCtion:BAND:RIGHt', str_type=float, min=0)
        self.peak_search_continuous = devMkrOption(':CALCulate:MARKer{mkr}:CPSearch', str_type=bool)

        #following http://www.mathworks.com/matlabcentral/fileexchange/30791-taking-a-screenshot-of-an-agilent-signal-analyzer-over-a-tcpip-connection
        #note that because of *OPC?, the returned string is 1;#....
        self.snap_png = scpiDevice(getstr=r':MMEMory:STORe:SCReen "C:\TEMP\SCREEN.PNG";*OPC?;:MMEMory:DATA? "C:\TEMP\SCREEN.PNG"',
                                   raw=True, str_type=lambda x:_decode_block_base(x[2:]), autoinit=False)
        self.snap_png._format['bin']='.png'

        self._devwrap('noise_eq_bw', autoinit=.5) # This should be initialized after the devices it depends on (if it uses getcache)
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
# status byte stuff
# There is a bunch of register groups:
#  :status:operation
#  :status:questionable
#  :status:questionable:power
#  :status:questionable:frequency
# ALSO see comments below agilent_PNAL


#######################################################
##    Agilent PNA-L network analyzer
#######################################################

class agilent_PNAL(visaInstrumentAsync):
    """
    To use this instrument, the most useful device is probably:
        fetch, readval
    Some commands are available:
        abort
        create_measurement
        delete_measurement
        restart_averaging
        phase_unwrap, phase_wrap, phase_flatten
        get_file
    Other useful devices:
        channel_list
        current_channel
        select_trace
        select_traceN
        freq_start, freq_stop, freq_cw
        power_en
        power_dbm_port1, power_dbm_port2
        marker_x, marker_y
        snap_png
        cont_trigger

    Note that almost all devices/commands require a channel.
    It can be specified with the ch option or will use the last specified
    one if left to the default.
    A lot of other commands require a selected trace (per channel)
    The active one can be selected with the trace option or select_trace, select_traceN
    If unspecified, the last one is used.

    If a trace is REMOVED from the instrument, you should perform a get of
    the channel_list device to update pyHegel knowledge of the available
    traces (needed when trying to fetch all traces).
    """
    def init(self, full=False):
        self.write(':format REAL,64')
        self.write(':format:border swap')
        super(agilent_PNAL, self).init(full=full)
    def _async_trig(self):
        # we don't use the STATus:OPERation:AVERaging1? status
        # because for n averages they turn on after the n-1 average.
        # Also it is a complex job to figure out which traces to keep track of
        # Here we will assume that _async_trigger_helper ('INITiate;*OPC')
        # starts all the channels (global triggering). It also does a single
        # iteration of an average.
        # We will just count the correct number of repeats to do.
        ch_orig = self.current_channel.getcache()
        ch_list = self.active_channels_list.getcache()
        reps = 1
        for ch in ch_list:
            if self.average_en.get(ch=ch):
                self.restart_averaging(ch) # so instrument displays shows the restart
                count = self.average_count.get()
                reps = max(reps, count)
        self.current_channel.set(ch_orig)
        self._trig_reps_total = reps
        self._trig_reps_current = 0
        self.cont_trigger.set(False)
        super(agilent_PNAL, self)._async_trig()
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        ret = super(agilent_PNAL, self)._async_detect(max_time)
        if not ret:
            # This cycle is not finished
            return ret
        # cycle is finished
        self._trig_reps_current += 1
        if self._trig_reps_current < self._trig_reps_total:
            self._async_trigger_helper()
            return False
        return True
    def abort(self):
        self.write('ABORt')
    def create_measurement(self, name, param, ch=None):
        """
        name: any unique, non-empty string. If it already exists, we change its param
        param: Any S parameter as S11 or S1_1 (second form only for double-digit port numbers S10_1)
               Ratio measurement, any 2 physical receiver separated by / and followed by , and source port
               like A/R1,3
               Non-Ratio measurement: Any receiver followed by , and source port like A,4
               Ratio and non-ratio can also use logical receiver notation
               ADC measurement: ADC receiver, then , then source por like AI1,2
               Balanced measurment: ...
        """
        ch_list = self.channel_list.get(ch=ch)
        ch=self.current_channel.getcache()
        if name in ch_list:
            self.select_trace.set(name)
            command = 'CALCulate{ch}:PARameter:MODify:EXTended "{param}"'.format(ch=ch, param=param)
        else:
            command = 'CALCulate{ch}:PARameter:EXTended "{name}","{param}"'.format(ch=ch, name=name, param=param)
        self.write(command)
    def delete_measurement(self, name=None, ch=None):
        """ delete a measurement.
            if name == None: delete all measurements for ch
            see channel_list for the available measurments
        """
        ch_list = self.channel_list.get(ch=ch)
        ch=self.current_channel.getcache()
        if name != None:
            if name not in ch_list:
                raise ValueError, self.perror('Invalid Trace name')
            command = 'CALCulate{ch}:PARameter:DELete "{name}"'.format(ch=ch, name=name)
        else:
            command = 'CALCulate{ch}:PARameter:DELete:ALL'.format(ch=ch)
        self.write(command)
    def restart_averaging(self, ch=None):
        #sets ch if necessary
        if not self.average_en.get(ch=ch):
            return
        ch=self.current_channel.getcache()
        command = 'SENSe{ch}:AVERage:CLEar'.format(ch=ch)
        self.write(command)
    def get_file(self, remote_file, local_file):
        """
            Obtain the file remote_file from the analyzer and save it
            on this computer as local_file
        """
        s = self.ask('MMEMory:TRANsfer? "%s"'%remote_file, raw=True)
        s = _decode_block_base(s)
        f = open(local_file, 'wb')
        f.write(s)
        f.close()
    def _fetch_getformat(self, **kwarg):
        unit = kwarg.get('unit', 'default')
        xaxis = kwarg.get('xaxis', True)
        ch = kwarg.get('ch', None)
        traces = kwarg.get('traces', None)
        if ch != None:
            self.current_channel.set(ch)
        traces = self._fetch_traces_helper(traces)
        if xaxis:
            sweeptype = self.sweep_type.getcache()
            choice = self.sweep_type.choices
            if sweeptype in choice[['linear', 'log', 'segment']]:
                multi = 'freq(Hz)'
            elif sweeptype in choice[['power']]:
                multi = 'power(dBm)'
            elif sweeptype in choice[['CW']]:
                multi = 'time(s)'
            else: # PHASe
                multi = 'deg' # TODO check this
            multi = [multi]
        else:
            multi = []
        # we don't handle cmplx because it cannot be saved anyway so no header or graph
        if unit == 'db_deg':
            names = ['dB', 'deg']
        else:
            names = ['real', 'imag']
        for t in traces:
            name, param = self.select_trace.choices[t]
            basename = name+'='+param+'_'
            multi.extend( [basename+n for n in names])
        fmt = self.fetch._format
        multi = tuple(multi)
        fmt.update(multi=multi, graph=[], xaxis=xaxis)
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_traces_helper(self, traces):
        # assume ch is selected
        ch_list = self.channel_list.getcache()
        if isinstance(traces, (tuple, list)):
            traces = traces[:] # make a copy so it can be modified without affecting caller. I don't think this is necessary anymore but keep it anyway.
        elif traces != None:
            traces = [traces]
        else: # traces == None
            traces = ch_list.keys()
        return traces
    def _fetch_getdev(self, ch=None, traces=None, unit='default', mem=False, xaxis=True):
        """
           options available: traces, unit, mem and xaxis
            -traces: can be a single value or a list of values.
                     The values are strings representing the trace or the trace number
            -unit:   can be 'default' (real, imag)
                       'db_deg' (db, deg) , where phase is unwrapped
                       'cmplx'  (complexe number), Note that this cannot be written to file
            -mem:    when True, selects the memory trace instead of the active one.
            -xaxis:  when True(default), the first column of data is the xaxis
        """
        if ch != None:
            self.current_channel.set(ch)
        traces = self._fetch_traces_helper(traces)
        getdata = self.calc_sdata
        if mem:
            getdata = self.calc_smem
        if xaxis:
            # get the x axis of the first trace selected
            self.select_trace.set(traces[0])
            ret = [self.calc_x_axis.get()]
        else:
            ret = []
        for t in traces:
            v = getdata.get(trace=t)
            if unit == 'db_deg':
                r = 20.*np.log10(np.abs(v))
                theta = np.angle(v, deg=True)
                theta = self.phase_unwrap(theta)
                ret.append(r)
                ret.append(theta)
            elif unit == 'cmplx':
                ret.append(v)
            else:
                ret.append(v.real)
                ret.append(v.imag)
        ret = np.asarray(ret)
        if ret.shape[0]==1:
            ret=ret[0]
        return ret
    @staticmethod
    def phase_unwrap(phase_deg):
        return scipy.rad2deg( scipy.unwrap( scipy.deg2rad(phase_deg) ) )
    @staticmethod
    def phase_wrap(phase_deg):
        return (phase_deg +180.) % 360 - 180.
    @staticmethod
    def phase_flatten(phase_deg, freq, delay=0., ratio=[0,-1]):
        """
           Using an unwrapped phase, this removes a slope.
           if delay is specified, it adds delay*f*360
           If delay is 0. (default) then it uses 2 points
           specified by ratio (defaults to first and last)
           to use to extract slope (delay)
        """
        dp = phase_deg[ratio[1]] - phase_deg[ratio[0]]
        df = freq[ratio[1]] - freq[ratio[0]]
        if delay == 0.:
            delay = -dp/df/360.
            print 'Using delay=', delay
        return phase_deg + delay*freq*360.
    def get_xscale(self):
        return self.x_axis.get()

    def _current_config(self, dev_obj=None, options={}):
        # These all refer to the current channel
        # calib_en depends on trace
        if options.has_key('ch'):
            self.current_channel.set(options['ch'])
        if options.has_key('trace'):
            self.select_trace.set(options['trace'])
        if options.has_key('mkr'):
            self.current_mkr.set(options['mkr'])
        extra = []
        if dev_obj in [self.marker_x, self.marker_y]:
            # Cannot get cache of marker_x while getting marker_x (end up getting an old cache)
            if dev_obj == self.marker_x:
                mxy = 'marker_y'
            else:
                mxy = 'marker_x'
            extra = self._conf_helper('current_mkr', 'marker_format', 'marker_trac_func', 'marker_trac_en',
                              mxy, 'marker_discrete_en', 'marker_target')
        if dev_obj in [self.readval, self.fetch]:
            traces_opt = self._fetch_traces_helper(options.get('traces'))
            cal = []
            traces = []
            for t in traces_opt:
                cal.append(self.calib_en.get(trace=t))
                name, param = self.select_trace.choices[t]
                traces.append(name+'='+param)
        elif dev_obj == self.snap_png:
            traces = cal='Unknown'
        else:
            t=self.select_trace.getcache()
            cal = self.calib_en.get()
            name, param = self.select_trace.choices[t]
            traces = name+'='+param
        extra += ['calib_en=%r'%cal, 'selected_trace=%r'%traces]
        base = self._conf_helper('current_channel', 'freq_cw', 'freq_start', 'freq_stop', 'ext_ref',
                                 'power_en', 'power_couple',
                                 'power_slope', 'power_slope_en',
                                 'power_dbm_port1', 'power_dbm_port2',
                                 'power_mode_port1', 'power_mode_port2',
                                 'npoints', 'sweep_gen', 'sweep_gen_pointsweep',
                                 'sweep_fast_en', 'sweep_time', 'sweep_type',
                                 'bandwidth', 'bandwidth_lf_enh', 'cont_trigger',
                                 'average_count', 'average_mode', 'average_en', options)
        return extra+base
    def _create_devs(self):
        self.installed_options = scpiDevice(getstr='*OPT?', str_type=quoted_string())
        self.self_test_results = scpiDevice(getstr='*tst?', str_type=int, doc="""
            Flag bits:
                0=Phase Unlock
                1=Source unleveled
                2=Unused
                3=EEprom write fail
                4=YIG cal failed
                5=Ramp cal failed""")
        self.current_channel = MemoryDevice(1, min=1, max=200)
        self.active_channels_list = scpiDevice(getstr='SYSTem:CHANnels:CATalog?', str_type=quoted_list(element_type=int))
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.channel_list = devChOption(getstr='CALCulate{ch}:PARameter:CATalog:EXTended?', str_type=quoted_dict(), doc='Note that some , are replaced by _')
        traceN_options = dict(trace=1)
        traceN_options_lim = dict(trace=(1,None))
        # The instrument complains that MEASurement12 is too long (for 2 digit trace)
        # so use just MEAS instead
        # I think it must be a limit of 12 characters for every scpi element (between :)
        self.traceN_name = scpiDevice(getstr=':SYSTem:MEAS{trace}:NAME?', str_type=quoted_string(),
                                      options = traceN_options, options_lim = traceN_options_lim)
        self.traceN_window = scpiDevice(getstr=':SYSTem:MEAS{trace}:WINDow?', str_type=int,
                                      options = traceN_options, options_lim = traceN_options_lim)
        # windowTrace restarts at 1 for each window
        self.traceN_windowTrace = scpiDevice(getstr=':SYSTem:MEAS{trace}:TRACe?', str_type=int,
                                      options = traceN_options, options_lim = traceN_options_lim)
        traceN_name_func = self.traceN_name
        select_trace_choices = ChoiceDevSwitch(self.channel_list,
                                               lambda t: traceN_name_func.get(trace=t),
                                               sub_type=quoted_string())
        self.select_trace = devChOption('CALCulate{ch}:PARameter:SELect', autoinit=8,
                                        choices=select_trace_choices, doc="""
                Select the trace using either the trace name (standard ones are 'CH1_S11_1')
                which are unique, the trace param like 'S11' which might not be unique
                (in which case the first one is used), or even the trace number
                whiche are also unique.""")
        def devCalcOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(trace=self.select_trace)
            app = kwarg.pop('options_apply', ['ch', 'trace'])
            kwarg.update(options=options, options_apply=app)
            return devChOption(*arg, **kwarg)
        # select_trace needs to be set for most of the calc commands
        #calc:par:TNUMber and WNUMber don't exist for our PNAL
        # since select_trace handles the number here we make it only a get
        # but MNUMber could also be a set.
        self.select_trace_N = devCalcOption(getstr='CALCulate{ch}:PARameter:MNUMber?', str_type=int, doc='The number is from the Tr1 annotation next to the parameter nane on the PNA screen')
        self.edelay_length = devCalcOption('CALCulate{ch}:CORRection:EDELay:DISTance', str_type=float)
        self.edelay_length_unit = devCalcOption('CALC{ch}:CORR:EDEL:UNIT', choices=ChoiceStrings('METer', 'FEET', 'INCH'))
        self.edelay_length_medium = devCalcOption('CALC{ch}:CORR:EDEL:MEDium', choices=ChoiceStrings('COAX', 'WAVEguide'))
        self.edelay_time = devCalcOption('CALC{ch}:CORR:EDEL', str_type=float, min=-10, max=10, doc='Set delay in seconds')
        self.calib_en = devCalcOption('CALC{ch}:CORR', str_type=bool)
        self.snap_png = scpiDevice(getstr='HCOPy:SDUMp:DATA:FORMat PNG;:HCOPy:SDUMp:DATA?', raw=True, str_type=_decode_block_base, autoinit=False)
        self.snap_png._format['bin']='.png'
        self.cont_trigger = scpiDevice('INITiate:CONTinuous', str_type=bool)
        self.bandwidth = devChOption('SENSe{ch}:BANDwidth', str_type=float, setget=True) # can obtain min max
        self.bandwidth_lf_enh = devChOption('SENSe{ch}:BANDwidth:TRACk', str_type=bool)
        self.average_count = devChOption('SENSe{ch}:AVERage:COUNt', str_type=int)
        self.average_mode = devChOption('SENSe{ch}:AVERage:MODE', choices=ChoiceStrings('POINt', 'SWEep'))
        self.average_en = devChOption('SENSe{ch}:AVERage', str_type=bool)
        self.coupling_mode = devChOption('SENSe{ch}:COUPle', choices=ChoiceStrings('ALL', 'NONE'), doc='ALL means sweep mode set to chopped (trans and refl measured on same sweep)\nNONE means set to alternate, imporves mixer bounce and isolation but slower')
        self.freq_start = devChOption('SENSe{ch}:FREQuency:STARt', str_type=float, min=10e6, max=40e9)
        self.freq_stop = devChOption('SENSe{ch}:FREQuency:STOP', str_type=float, min=10e6, max=40e9)
        self.freq_cw= devChOption('SENSe{ch}:FREQuency:CW', str_type=float, min=10e6, max=40e9)
        self.ext_ref = scpiDevice(getstr='SENSe:ROSCillator:SOURce?', str_type=str)
        self.npoints = devChOption('SENSe{ch}:SWEep:POINts', str_type=int, min=1)
        self.sweep_gen = devChOption('SENSe{ch}:SWEep:GENeration', choices=ChoiceStrings('STEPped', 'ANALog'))
        self.sweep_gen_pointsweep =devChOption('SENSe{ch}:SWEep:GENeration:POINtsweep', str_type=bool, doc='When true measure rev and fwd at each frequency before stepping')
        self.sweep_fast_en =devChOption('SENSe{ch}:SWEep:SPEed', choices=ChoiceStrings('FAST', 'NORMal'), doc='FAST increases the speed of sweep by almost a factor of 2 at a small cost in data quality')
        self.sweep_time = devChOption('SENSe{ch}:SWEep:TIME', str_type=float, min=0, max=86400.)
        self.sweep_type = devChOption('SENSe{ch}:SWEep:TYPE', choices=ChoiceStrings('LINear', 'LOGarithmic', 'POWer', 'CW', 'SEGMent', 'PHASe'))
        self.x_axis = devChOption(getstr='SENSe{ch}:X?', raw=True, str_type=decode_float64, autoinit=False, doc='This gets the default x-axis for the channel (some channels can have multiple x-axis')
        self.calc_x_axis = devCalcOption(getstr='CALC{ch}:X?', raw=True, str_type=decode_float64, autoinit=False, doc='Get this x-axis for a particular trace.')
        self.calc_fdata = devCalcOption(getstr='CALC{ch}:DATA? FDATA', raw=True, str_type=decode_float64, autoinit=False, trig=True)
        # the f vs s. s is complex data, includes error terms but not equation editor (Except for math?)
        #   the f adds equation editor, trace math, {gating, phase corr (elect delay, offset, port extension), mag offset}, formating and smoothing
        self.calc_sdata = devCalcOption(getstr='CALC{ch}:DATA? SDATA', raw=True, str_type=decode_complex128, autoinit=False, trig=True)
        self.calc_fmem = devCalcOption(getstr='CALC{ch}:DATA? FMEM', raw=True, str_type=decode_float64, autoinit=False)
        self.calc_smem = devCalcOption(getstr='CALC{ch}:DATA? SMEM', raw=True, str_type=decode_complex128, autoinit=False)
        self.current_mkr = MemoryDevice(1, min=1, max=10)
        def devMkrOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_mkr)
            app = kwarg.pop('options_apply', ['ch', 'trace', 'mkr'])
            kwarg.update(options=options, options_apply=app)
            return devCalcOption(*arg, **kwarg)
        def devMkrEnOption(*arg, **kwarg):
            # This will check if the marker is currently enabled.
            options = kwarg.pop('options', {}).copy()
            options.update(_marker_enabled=self.marker_en)
            options_lim = kwarg.pop('options_lim', {}).copy()
            options_lim.update(_marker_enabled=[True])
            kwarg.update(options=options, options_lim=options_lim)
            return devMkrOption(*arg, **kwarg)
        self.marker_en = devMkrOption('CALC{ch}:MARKer{mkr}', str_type=bool, autoinit=5)
        marker_funcs = ChoiceStrings('MAXimum', 'MINimum', 'RPEak', 'LPEak', 'NPEak', 'TARGet', 'LTARget', 'RTARget', 'COMPression')
        self.marker_trac_func = devMkrEnOption('CALC{ch}:MARKer{mkr}:FUNCtion', choices=marker_funcs)
        # This is set only
        self.marker_exec = devMkrOption('CALC{ch}:MARKer{mkr}:FUNCTION:EXECute', choices=marker_funcs, autoget=False)
        self.marker_target = devMkrEnOption('CALC{ch}:MARKer{mkr}:TARGet', str_type=float)
        marker_format = ChoiceStrings('DEFault', 'MLINear', 'MLOGarithmic', 'IMPedance', 'ADMittance', 'PHASe', 'IMAGinary', 'REAL',
                                      'POLar', 'GDELay', 'LINPhase', 'LOGPhase', 'KELVin', 'FAHRenheit', 'CELSius')
        self.marker_format = devMkrEnOption('CALC{ch}:MARKer{mkr}:FORMat', choices=marker_format)
        self.marker_trac_en = devMkrEnOption('CALC{ch}:MARKer{mkr}:FUNCtion:TRACking', str_type=bool)
        self.marker_discrete_en = devMkrEnOption('CALC{ch}:MARKer{mkr}:DISCrete', str_type=bool)
        self.marker_x = devMkrEnOption('CALC{ch}:MARKer{mkr}:X', str_type=float, trig=True)
        self.marker_y = devMkrEnOption('CALC{ch}:MARKer{mkr}:Y', str_type=decode_float64, multi=['val1', 'val2'], graph=[0,1], trig=True)
        self.power_en = scpiDevice('OUTPut', str_type=bool)
        self.power_couple = devChOption(':SOURce{ch}:POWer:COUPle', str_type=bool)
        self.power_slope = devChOption(':SOURce{ch}:POWer:SLOPe', str_type=float, min=-2, max=2)
        self.power_slope_en = devChOption(':SOURce{ch}:POWer:SLOPe:STATe', str_type=bool)
        # for max min power, ask source:power? max and source:power? min
        self.power_dbm_port1 = devChOption(':SOURce{ch}:POWer1', str_type=float)
        self.power_dbm_port2 = devChOption(':SOURce{ch}:POWer2', str_type=float)
        self.power_mode_port1 = devChOption(':SOURce{ch}:POWer1:MODE', choices=ChoiceStrings('AUTO', 'ON', 'OFF'))
        self.power_mode_port2 = devChOption(':SOURce{ch}:POWer2:MODE', choices=ChoiceStrings('AUTO', 'ON', 'OFF'))
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()
# status byte stuff
# There is a bunch of register groups:
#  :status:operation     # 8(256)=averaging, 9(512)=user, 10(1024)=device
#  :status:operation:device  # contains sweep complete 4(16)
#  :status:operation:averaging1 # handles 1 summary of aver2-42(bit0) and traces 1-14 (bit 1:14)
#  :                          2 # handles 1 summary of aver3-42(bit0) and traces 15-28 (bit 1:14)
#  :status:questionable # 9 (512)=inieg, 10(1024)=limit, 11(2048)=define
#  :status:questionable:integrity
#  :status:questionable:limit1
#   ...
#
#  sweep complete and opc give the same information. Note that the status event latches
#   need to be cleared everywhere in order to be reset (STATus:OPERation:AVERaging1, STATus:OPERation:AVERaging2,
#   STATus:OPERation for and average of trace 15-28)
#  Note that average:cond stays True as long as the average count as been reached
#  If average is not enabled, the condition is never set to true
#
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
# With both GPIB and USB interface activated. They both have their own status registers
# for STB to OPERATION ...
# They also have their own error queues and most other settings (active measurement for channel,
#   data format) seem to also be independent on the 2 interfaces


#######################################################
##    Agilent ENA network analyzer
#######################################################

class agilent_ENA(agilent_PNAL):
    """
    To use this instrument, the most useful device is probably:
        fetch, readval  : Note that for the ENA the traces must be the trace number (cannot be a string)
    Some commands are available:
        abort
        reset_trig: to return to continuous internal trig (use this after readval, will restart
                    the automatic refresh on the instrument display)
        restart_averaging
        phase_unwrap, phase_wrap, phase_flatten
    Other useful devices:
        channel_list
        current_channel
        select_trace
        freq_start, freq_stop, freq_cw
        power_en
        power_dbm_port1, power_dbm_port2
        marker_x, marker_y
        cont_trigger
        trig_source
    method:
        load_segment

    Note that almost all devices/commands require a channel.
    It can be specified with the ch option or will use the last specified
    one if left to the default.
    A lot of other commands require a selected trace (per channel)
    The active one can be selected with the trace option or select_trace, select_traceN
    If unspecified, the last one is used.
    """
    def init(self, full=False):
        self.write(':format:data REAL')
        self.write(':format:border swap')
        self.reset_trig()
        # skip agilent_PNAL, go directly to its parent.
        super(agilent_PNAL, self).init(full=full)
    def reset_trig(self):
        self.trig_source.set('INTernal')
        self.cont_trigger.set(True)
    def _async_trig(self):
        self.cont_trigger.set(False)
        super(agilent_PNAL, self)._async_trig()
    def _async_detect(self, max_time=.5): # 0.5 s max by default
        return super(agilent_PNAL, self)._async_detect(max_time)
    def _async_trigger_helper(self):
        self.trig_source.set('BUS')
        self.average_triggering_en.set(True)
        self.initiate()
        self.write(':TRIGger:SINGle;*OPC')
        #self.trig_source.set('INTernal')
    def _current_config(self, dev_obj=None, options={}):
        # These all refer to the current channel
        # calib_en depends on trace
        if options.has_key('ch'):
            self.current_channel.set(options['ch'])
        if options.has_key('trace'):
            self.select_trace.set(options['trace'])
        if options.has_key('mkr'):
            self.current_mkr.set(options['mkr'])
        extra = []
        if dev_obj in [self.marker_x, self.marker_y]:
            # Cannot get cache of marker_x while getting marker_x (end up getting an old cache)
            if dev_obj == self.marker_x:
                mxy = 'marker_y'
            else:
                mxy = 'marker_x'
            extra = self._conf_helper('current_mkr', 'marker_trac_func', 'marker_trac_en', mxy,
                              'marker_discrete_en', 'marker_target')
        if dev_obj in [self.readval, self.fetch]:
            traces_opt = self._fetch_traces_helper(options.get('traces'))
            traces = []
            for t in traces_opt:
                name, param = self.select_trace.choices[t]
                traces.append(name+'='+param)
        else:
            traces_opt = self._fetch_traces_helper(None) # get all traces
            name, param = self.select_trace.choices[self.select_trace.getcache()]
            traces = name+'='+param
        extra += ['selected_trace=%r'%traces]
        if self._is_E5071C:
            base = self._conf_helper('current_channel',
                                 'calib_en', 'freq_cw', 'freq_start', 'freq_stop', 'ext_ref',
                                 'power_en', 'power_couple',
                                 'power_slope', 'power_slope_en',
                                 'power_dbm_port1', 'power_dbm_port2',
                                 'power_dbm_port3', 'power_dbm_port4',
                                 'npoints', 'sweep_gen',
                                 'sweep_time', 'sweep_type',
                                 'bandwidth', 'bandwidth_auto_en', 'bandwidth_auto_limit', 'cont_trigger',
                                 'average_count', 'average_en', options)
        else:
            base = self._conf_helper('current_channel',
                                 'calib_en', 'freq_cw', 'freq_start', 'freq_stop', 'ext_ref',
                                 'power_en', 'power_couple',
                                 'power_slope', 'power_slope_en',
                                 'power_dbm_port1', 'power_dbm_port2',
                                 'npoints',
                                 'sweep_time', 'sweep_type',
                                 'bandwidth', 'bandwidth_auto_en', 'bandwidth_auto_limit', 'cont_trigger',
                                 'average_count', 'average_en', options)
        return extra+base
    def _fetch_traces_helper(self, traces):
        count = self.select_trace_count.getcache()
        trace_orig = self.select_trace.getcache()
        all_tr = range(1,count+1)
        # First create the necessary entries, so that select_trace works
        self.select_trace.choices = {i:('%i'%i, 'empty') for i in all_tr}
        # Now fill them properly (trace_meas, uses select_trace and needs to access them)
        self.select_trace.choices = {i:('%i'%i, self.trace_meas.get(trace=i)) for i in all_tr}
        self.select_trace.set(trace_orig)
        if isinstance(traces, (tuple, list)):
            traces = traces[:] # make a copy so it can be modified without affecting caller. I don't think this is necessary anymore but keep it anyway.
        elif traces != None:
            traces = [traces]
        else: # traces == None
            traces = all_tr
        return traces
    def initiate(self):
        """ Enables the current channel for triggering purposes """
        ch = self.current_channel.getcache()
        self.write('INITiate%i'%ch)
    def load_segment(self, filename):
        """ To load from the instrument disk a file describing the
            segments to use.
            Make sure to select the table shape (start/stop or center/span,
            power or no power, etc...) to be the same as the content of the file
            before loading, otherwise the load will fail or be wrong.
            Ex:
                ena1.load_segment('d:/Segments/SEGM100MHz.csv')
            You can use either forward or backslash (but be careful with
            backslash, might need r'd:\\test.csv' or double them 'd:\\\\test.csv')
        """
        self.write('MMEMory:LOAD:SEGMent "%s"'%filename)
    def _create_devs(self):
        idn = self.idn()
        self._is_E5071C = 'E5071C' in idn.split(',')[1]
        self.create_measurement = None
        self.delete_measurement = None
        self.installed_options = scpiDevice(getstr='*OPT?', str_type=str)
        self.current_channel = MemoryDevice(1, min=1, max=160)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        # Either: CALCulate{ch}:PARameter{tr}:SELect (write only)
        #         CALCulate{ch}:PARemeter:COUNt
        # select_trace is needed by PNAL:fetch so we cannot rename it to current_trace.
        self.select_trace = MemoryDevice(1, min=1, max=16)
        #self.select_trace = devChOption('CALCulate{ch}:PARameter{val}:SELect', autoinit=8, autoget=False, str_type=int, min=1, max=16)
        self.select_trace_count = devChOption('CALCulate{ch}:PARameter:COUNt', str_type=int)
        def devCalcOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(trace=self.select_trace)
            app = kwarg.pop('options_apply', ['ch', 'trace'])
            kwarg.update(options=options, options_apply=app)
            return devChOption(*arg, **kwarg)
        # select_trace needs to be set for most of the calc commands
        self.trace_meas = devCalcOption('CALCulate{ch}:PARameter{trace}:DEFine')
        self.calib_en = devChOption('SENSe{ch}:CORRection:STATe', str_type=bool)
        self.cont_trigger = devChOption('INITiate{ch}:CONTinuous', str_type=bool)
        self.bandwidth = devChOption('SENSe{ch}:BANDwidth', str_type=float, setget=True) # can obtain min max
        self.bandwidth_auto_en = devChOption('SENSe{ch}:BWAuto', str_type=bool)
        self.bandwidth_auto_limit = devChOption('SENSe{ch}:BWAuto:LIMit', str_type=float, setget=True)
        self.average_count = devChOption('SENSe{ch}:AVERage:COUNt', str_type=int)
        self.average_en = devChOption('SENSe{ch}:AVERage', str_type=bool)
        self.average_triggering_en = devChOption('TRIGger:AVERage', str_type=bool)
        self.freq_start = devChOption('SENSe{ch}:FREQuency:STARt', str_type=float, min=5, max=3e9)
        self.freq_stop = devChOption('SENSe{ch}:FREQuency:STOP', str_type=float, min=5, max=3e9)
        self.freq_cw= devChOption('SENSe{ch}:FREQuency:CW', str_type=float, min=5, max=3e9)
        self.ext_ref = scpiDevice(getstr='SENSe:ROSCillator:SOURce?', str_type=str)
        self.npoints = devChOption('SENSe{ch}:SWEep:POINts', str_type=int, min=2, max=20001)
        if self._is_E5071C:
            self.sweep_gen = devChOption('SENSe{ch}:SWEep:GENeration', choices=ChoiceStrings('STEPped', 'ANALog', 'FSTepped', 'FANalog'))
        self.sweep_time = devChOption('SENSe{ch}:SWEep:TIME', str_type=float, min=0, max=86400.)
        self.sweep_type = devChOption('SENSe{ch}:SWEep:TYPE', choices=ChoiceStrings('LINear', 'LOGarithmic', 'POWer', 'SEGMent'))
        self.calc_x_axis = devCalcOption(getstr='CALC{ch}:TRACe{trace}:DATA:XAXIs?', raw=True, str_type=decode_float64, autoinit=False, doc='Get this x-axis for a particular trace.')
        self.calc_fdata = devCalcOption(getstr='CALC{ch}:TRACe{trace}:DATA:FDATa?', raw=True, str_type=decode_float64, autoinit=False, trig=True)
        # the f vs s. s is complex data, includes error terms but not equation editor (Except for math?)
        #   the f adds equation editor, trace math, {gating, phase corr (elect delay, offset, port extension), mag offset}, formating and smoothing
        self.calc_sdata = devCalcOption(getstr='CALC{ch}:TRACe{trace}:DATA:SDATa?', raw=True, str_type=decode_complex128, autoinit=False, trig=True)
        self.calc_fmem = devCalcOption(getstr='CALC{ch}:TRACe{trace}:DATA:FMEMory?', raw=True, str_type=decode_float64, autoinit=False)
        self.calc_smem = devCalcOption(getstr='CALC{ch}:TRACe{trace}:DATA:SMEMory?', raw=True, str_type=decode_complex128, autoinit=False)
        self.current_mkr = MemoryDevice(1, min=1, max=10)
        def devMkrOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(mkr=self.current_mkr)
            app = kwarg.pop('options_apply', ['ch', 'trace', 'mkr'])
            kwarg.update(options=options, options_apply=app)
            return devCalcOption(*arg, **kwarg)
        def devMkrEnOption(*arg, **kwarg):
            # This will check if the marker is currently enabled.
            options = kwarg.pop('options', {}).copy()
            options.update(_marker_enabled=self.marker_en)
            options_lim = kwarg.pop('options_lim', {}).copy()
            options_lim.update(_marker_enabled=[True])
            kwarg.update(options=options, options_lim=options_lim)
            return devMkrOption(*arg, **kwarg)
        self.marker_en = devMkrOption('CALC{ch}:TRACe{trace}:MARKer{mkr}', str_type=bool, autoinit=5)
        marker_funcs = ChoiceStrings('MAXimum', 'MINimum', 'RPEak', 'LPEak', 'TARGet', 'LTARget', 'RTARget', 'COMPression')
        self.marker_trac_func = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:FUNCtion', 'CALC{ch}:MARKer{mkr}:FUNCtion:TYPE?', choices=marker_funcs)
        # This is set only
        self.marker_exec = devMkrOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:FUNCTION:EXECute', choices=marker_funcs, autoget=False)
        self.marker_target = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:FUNCtion:TARGet', str_type=float)
        self.marker_trac_en = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:FUNCtion:TRACking', str_type=bool)
        self.marker_discrete_en = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:DISCrete', str_type=bool)
        self.marker_x = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:X', str_type=float, trig=True)
        self.marker_y = devMkrEnOption('CALC{ch}:TRACe{trace}:MARKer{mkr}:Y', str_type=decode_float64, multi=['val1', 'val2'], graph=[0,1], trig=True)
        self.power_en = scpiDevice('OUTPut', str_type=bool)
        self.power_couple = devChOption(':SOURce{ch}:POWer:PORT:COUPle', str_type=bool)
        self.power_slope = devChOption(':SOURce{ch}:POWer:SLOPe', str_type=float, min=-2, max=2)
        self.power_slope_en = devChOption(':SOURce{ch}:POWer:SLOPe:STATe', str_type=bool)
        # for max min power, ask source:power? max and source:power? min
        self.power_dbm_port1 = devChOption(':SOURce{ch}:POWer:PORT1', str_type=float)
        self.power_dbm_port2 = devChOption(':SOURce{ch}:POWer:PORT2', str_type=float)
        if self._is_E5071C:
            self.power_dbm_port3 = devChOption(':SOURce{ch}:POWer:PORT3', str_type=float)
            self.power_dbm_port4 = devChOption(':SOURce{ch}:POWer:PORT4', str_type=float)
        self.trig_source = scpiDevice(':TRIGger:SOURce',
                                      choices=ChoiceStrings('INTernal', 'EXTernal', 'MANual', 'BUS'))
        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        # This needs to be last to complete creation
        super(agilent_PNAL, self)._create_devs()


#######################################################
##    Agilent M8190A Arbitrary Waveform Generator
#######################################################

class agilent_AWG(visaInstrumentAsync):
    """
    This is to control the M8190A Arbitrary Waveform Generator.
    It has 2 independent channels that can be coupled (for start/stop)
    and each channel can be with 12 bit @ 12 GS/s max of 2 GS or 14 bit @ 8 GS/s
    max of 1.5 GS.
    For the binary files:
     DAC values are signed. The data is in the most significant bits,
      so bits 15-2 in 14 bit mode and 15-4 in 12 bit mode (then bits 3 and 2 are
      don't care). Bit 1 is the sequence marker, bit 0 is the sample marker.
     Data needs to be in blocks (or vectors). Only the sequence marker of the first
     sample in a vector is used.
     The vector length is 48 samples in 14 bits mode and 64 in 12 bits mode.
     The smallest common multiple of 48 and 64 is 192.
     The minimum length is 5 vectors (240 samples in 14 bits, 320 for 12 bits)

    The voltage amplitude can be set with either volt_amplitude, volt_offset
    or volt_high, volt_low (volt_ampl is peak to peak amplitude)
    There is one sampling frequency for both channels.
    Many options depend on the channel.
    """
    def init(self, full=False):
        self.write(':format:border swap')
        # initialize async stuff
        super(agilent_AWG, self).init(full=full)
    def _async_trigger_helper(self):
        self.write('*OPC')
    def _current_config(self, dev_obj=None, options={}):
        orig_ch = self.current_channel.getcache()
        ch_list = ['current_channel', 'freq_source', 'cont_trigger', 'gate_mode_en', 'output_en',
                                'delay_coarse', 'delay_fine', 'volt_ampl', 'volt_offset',
                                'sample_marker_volt_ampl', 'sample_marker_volt_offset',
                                'sync_marker_volt_ampl', 'sync_marker_volt_offset',
                                'dac_format', 'differential_offset', 'speed_mode',
                                'advance_mode', 'repeat_count', 'marker_en', 'segment_list']
        self.current_channel.set(1)
        ch1 = self._conf_helper(*ch_list)
        self.current_channel.set(2)
        ch2 = self._conf_helper(*ch_list)
        self.current_channel.set(orig_ch)
        return ch1+ch2+self._conf_helper('coupled_en', 'freq_sampling', 'freq_ext',
                                         'ref_source', 'ref_freq', options)
    def _create_devs(self):
        self.current_channel = MemoryDevice(1, min=1, max=2)
        self.coupled_en = scpiDevice(':INSTrument:COUPle:STATe', str_type=bool)
        self.freq_sampling = scpiDevice(':FREQuency:RASTer', str_type=float)
        self.freq_ext = scpiDevice(':FREQuency:RASTer:EXTernal', str_type=float)
        self.ref_source = scpiDevice(':ROSCillator:SOURce', choices=ChoiceStrings('AXI', 'EXTernal'))
        self.ref_freq = scpiDevice(':ROSCillator:FREQuency', str_type=float)
        def devChOption(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=self.current_channel)
            app = kwarg.pop('options_apply', ['ch'])
            kwarg.update(options=options, options_apply=app)
            return scpiDevice(*arg, **kwarg)
        self.freq_source = devChOption(':FREQuency:RASTer:SOURce{ch}', choices=ChoiceStrings('INTernal', 'EXTernal'))
        self.cont_trigger = devChOption(':INITiate:CONTinuous{ch}', str_type=bool)
        self.gate_mode_en = devChOption(':INITiate:GATE{ch}', str_type=bool, doc=
            """
            When cont_trigger is False, selects between gate or trigger mode of triggering.
            Under gating mode, the segment repeating is started after the rising edge
            of the gating signal. When the falling edge is detected, repeat_count
            segments are produced and then stops.
            """)
        #self.arming_mode = devChOption(':INITiate:CONTinuous{ch}:ENABle', choices=ChoiceStrings('SELF', 'ARMed'))
        self.output_en = devChOption(':OUTPut{ch}', str_type=bool)
        self.delay_coarse = devChOption(':ARM:CDELay{ch}', str_type=float, min=0, max=10e-9)
        self.delay_fine = devChOption(':ARM:DELay{ch}', str_type=float, min=0, max=150e-12, doc='max delay is 60e-12 between 2.5 and 6.25 GS/s and 30e-12 above 6.25 GS/s')
        self.volt_ampl = devChOption(':VOLTage{ch}', str_type=float, min=.35, max=0.7)
        self.volt_offset = devChOption(':VOLTage{ch}:OFFSet', str_type=float, min=-.02, max=0.02)
        self.volt_high = devChOption(':VOLTage{ch}:HIGH', str_type=float, min=.155, max=.37)
        self.volt_low = devChOption(':VOLTage{ch}:LOW', str_type=float, min=-0.37, max=0.155)
        self.sample_marker_volt_ampl = devChOption(':MARKer{ch}:SAMPle:VOLTage:AMPLitude', str_type=float, min=0., max=2.25)
        self.sample_marker_volt_offset = devChOption(':MARKer{ch}:SAMPle:VOLTage:OFFSet', str_type=float, min=-0.5, max=1.75)
        self.sample_marker_volt_high = devChOption(':MARKer{ch}:SAMPle:VOLTage:HIGH', str_type=float, min=0.5, max=1.75)
        self.sample_marker_volt_low = devChOption(':MARKer{ch}:SAMPle:VOLTage:LOW', str_type=float, min=-0.5, max=1.75)
        self.sync_marker_volt_ampl = devChOption(':MARKer{ch}:SYNC:VOLTage:AMPLitude', str_type=float, min=0., max=2.25)
        self.sync_marker_volt_offset = devChOption(':MARKer{ch}:SYNC:VOLTage:OFFSet', str_type=float, min=-0.5, max=1.75)
        self.sync_marker_volt_high = devChOption(':MARKer{ch}:SYNC:VOLTage:HIGH', str_type=float, min=0.5, max=1.75)
        self.sync_marker_volt_low = devChOption(':MARKer{ch}:SYNC:VOLTage:LOW', str_type=float, min=-0.5, max=1.75)
        self.dac_format = devChOption(':DAC:FORMat', choices=ChoiceStrings('RZ', 'DNRZ', 'NRZ', 'DOUBlet'), doc=
            """ RZ:      Return to zero (DAC A, DAC B=0) (first half of time step, second half)
                NRZ:     Non return to zero (DAC A, DAC A)
                DNRZ:    double NRZ (DAC A, DAC B=A)
                Doublet: (DAC A, DAC B=-A)
            """)
        self.differential_offset = devChOption(':OUTPut{ch}:DIOFfset', str_type=int, doc='An integer to fix DAC offset between direct and its complement output.')
        #self.func_mode = devChOption(':FUNCtion{ch}:MODE', choices=ChoiceStrings('ARBitrary', 'STSequence', 'STSCenario'))
        self.advance_mode = devChOption(':TRACE{ch}:ADVance', choices=ChoiceStrings('AUTO', 'CONDitional', 'REPeat', 'SINGle'), doc=
            """
            This setting only works for cont_trigger False and gate_mode_en False
            AUTO:   Every trig event produces repeat_count segments
            REPEAT: A trig event produces repeat_count segments.
                    Then need the advance event to enable next trig.
            SINGLE: A trig event produces the first segment.
                    Then N-1 advance event to produce the N-1 repeats of the segment.
                    (for N=repeat_count)
            COND:   A trig event starts a continous repeat of the segment.
            """)
        self.repeat_count = devChOption(':TRACE{ch}:COUNt', str_type=int)
        self.marker_en = devChOption(':TRACE{ch}:MARKer', str_type=bool)
        speed_choices = ChoiceStrings('WSPeed', 'WPRecision')
        self.speed_mode = devChOption(':TRACe{ch}:DWIDth', choices=speed_choices, doc=
            """
                wspeed:     speed mode, 12 bits, 12 GS/s max
                wprecision: precision mode, 14 bits, 8 GS/s max
                See also: speed_mode_both
            """) # SKIP all the interpolation modes (INTX3, X12 ...) because needs option DUC
        self.speed_mode_both = scpiDevice(':TRACe1:DWIDth {val};:TRACe2:DWIDth {val}', ':TRACe1:DWIDth?', choices=speed_choices, doc=
            """
                Same as speed_mode except it changes both channel at the same time.
                This is needed when both channel use the internal sample clock.
                Using get returns the result for channel 1.
            """)
        # TODO implement loading of data using the TRACE{ch}:DEFine 1, length, init_val
        #   and TRACE{ch}:DATA 1,offset (scpi has limit of 999999999 bytes 0.999 GB)
        # read with TRACE{ch}:DATA? 1,offset,length  (returns ascii, length needs to be multiple of 48 or 64)
        #   Getting trace data this way seems very slow.
        self.segment_list = devChOption(getstr=':TRACE{ch}:CATalog?', doc='Returns a list of segment id, length')
        # This needs to be last to complete creation
        super(type(self),self)._create_devs()

    def run(self, enable=True, ch=None):
        """
        When channels are coupled, both are affected.
        """
        if ch!=None:
            self.current_channel.set(ch)
        ch = self.current_channel.getcache()
        if enable:
            self.ask(':INITiate:IMMediate%i;*OPC?'%ch)
        else:
            self.ask(':ABORt%i;*OPC?'%ch)
    def set_length(self, sample_length, ch=None, init_val=None):
        """
        init_val is the DAC value to use for initialization. No initialization by default.
        """
        # TODO should check the lenght is valid
        if ch!=None:
            self.current_channel.set(ch)
        ch = self.current_channel.getcache()
        extra=''
        if init_val != None:
            extra=',{init}'
        self.write((':TRACe{ch}:DELete:ALL;:TRACe{ch}:DEFine 1,{L}'+extra).format(ch=ch, L=sample_length, init=init_val))
    def load_file(self, filename, ch=None, fill=False):
        """
        filename needs to be a file in the correct binary format.
        fill when True will pad the data with 0 to the correct length
             when an integer (not 0), will pad the data with that DAC value,
               (there seems to be a bug here: every sample with value fill is followed by a 0)
             when false, will copy (repeat) the data multiple times to obtain
             the correct length.
             Note that with padding enabled, the segment length stays the same
             lenght as defined (so it can be shorted than the file; the data is truncated)
             With fill disabled (False): the segment length is adjusted
        The vector length is 48 samples in 14 bits mode and 64 in 12 bits mode.
        The minimum length is 5 vectors (240 samples in 14 bits, 320 for 12 bits)
        This command will wait for the transfer to finish before returning.
        If the output is running when calling load_file, it will be temporarilly
        stopped during loading.
        """
        if fill==False:
            padding='ALENgth'
        elif fill==True:
            padding='FILL'
        else:
            padding='FILL,%i'%fill
        if ch!=None:
            self.current_channel.set(ch)
        ch = self.current_channel.getcache()
        self._async_trig_cleanup()
        self.write(':TRACe{ch}:IQIMPort 1,"{f}",BIN,BOTH,ON,{p}'.format(ch=ch, f=filename, p=padding))
        self._async_trigger_helper()
        self.wait_after_trig()
