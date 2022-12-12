# -*- coding: utf-8 -*-
# written by Christian Lupien, 2021

"""
Tools to read Quantum Design PPMS and MPMS data files.
"""

import numpy as np
import time
import glob
import csv
from numpy import genfromtxt, isnan, where, array
import datetime
import dateutil.tz
import io

def timestamp_offset(year=None):
    """ Returns the timestamp offset to add to the timestamp column
        to obtain a proper time for resistance data
        This offset is wrong when daylight saving is active.
        Because of the way it is created, it is not possible to know exactly
        when the calculation is wrong.
    """
    # MultiVu (dynacool) probably uses GetTickCount data
    # so it is not immediately affected by clock change or daylight savings.
    # but since it lasts at most 49.7 days, it must reset at some point.
    # Multivu itself does not calculate the date correctly (offset by 1) and
    # the time is also eventually wrong after daylight saving.
    # The time might be readjusted after deactivating and reactivating the resistivity option.
    #  Here dynacool multivu seems to decode the timestamp ts as
    #    datetime.timedelta(ts//86400, ts%86400)+datetime.datetime(1999,12,31)
    if year is None:
        year = time.localtime().tm_year
    offset = time.mktime(time.strptime('{}/12/31'.format(year-1), '%Y/%m/%d'))
    return offset

def timestamp_offset_log():
    """ Returns the timestamp offset to add to the timestamp column
        to obtain a proper time for log data.
        This offset is wrong when daylight saving is active.
    """
    # The multivu(dynacool) timestamp calculation is wrong
    # It jumps by 3600 s when the daylight savings starts and repeats 3600 of time
    # when it turns off. It probably does time calculations assuming a day has
    # 24*3600 = 86400 s (which is not True when daylight is used).
    # The number is based on local date/time from 1899-12-30 excel, lotus epoch.
    # dynacool multivu seems to be using the following algorithms
    #  timestamp = (datetime.datetime.now()- datetime.datetime(1899,12,30)).total_seconds()
    #    note that that assumes 86400 s per day
    #  for example (datetime.datetime.now()- datetime.datetime.fromtimestamp(0)).total_seconds() can be different from
    #    time.time()
    #  going the other way:
    #    datetime.timedelta(timestamp//86400, timestamp%86400) + datetime.datetime(1899,12,30)
    unix_epoch = datetime.datetime.fromtimestamp(0) # this returns a local time.
    t0 = datetime.datetime(1899,12,30)
    offset = unix_epoch-t0
    return -offset.total_seconds()

def timestamp_log_conv(timestamp):
    """ Does a full conversion of all the timestamp data (can be a vector)
        to unix time.
    """
    single = False
    if not isinstance(timestamp, (list, tuple, np.ndarray)):
        single = True
        timestamp = [timestamp]
    timestamp_flat = np.asarray(timestamp).ravel()
    base = datetime.datetime(1899,12,30)
    day = 3600*24
    ret = np.empty(len(timestamp_flat))
    for i, ts in enumerate(timestamp_flat):
        if np.isnan(ts):
            ret[i] = np.nan
        else:
            dt = datetime.timedelta(ts//day, ts%day) + base
            ret[i] = time.mktime(dt.timetuple()) + dt.microsecond/1e6
    if single:
        ret = ret[0]
    elif isinstance(timestamp, np.ndarray) and timestamp.ndim >1:
        ret.shape = timestamp.shape
    return ret


def pick_not_nan(data):
    """ For data, provide a single row of data.
        It will return the list of columns where the data is not NaN
    """
    sel = where(isnan(data)==False)[0]
    return sel

def quoted_split(string):
    """ Split on , unless quoted with " """
    reader = csv.reader([string])
    return list(reader)[0]

def read_one_ppms_dat(filename, sel_i=0, nbcols=None, encoding='latin1'):
    hdrs = []
    titles = []
    i = 0
    kwargs = {}
    if nbcols is not None:
        kwargs['usecols'] = list(range(nbcols))
        kwargs['invalid_raise'] = False
    with io.open(filename, 'r', encoding=encoding) as f:
        while True:
            line = f.readline().rstrip()
            i += 1
            hdrs.append(line)
            if line == '[Data]':
                break
            if i>40:
                break
        line = f.readline().rstrip()
        i += 1
        hdrs.append(line)
        titles = quoted_split(line)
    titles = np.array(titles)
    v = genfromtxt(filename, skip_header=i, delimiter=',', encoding=encoding, **kwargs).T
    if v.ndim == 1:
        # There was only one line:
        v = v[:, np.newaxis]
    if sel_i is None:
        sel = None
    else:
        sel = pick_not_nan(v[:, sel_i])
    return v, titles, hdrs, sel

def _glob(filename):
    if not isinstance(filename, (list, tuple, np.ndarray)):
        filename = [filename]
    filelist = []
    for fglob in filename:
        fl = glob.glob(fglob)
        fl.sort()
        filelist.extend(fl)
    if len(filelist) == 0:
        print('No file found')
        return None, False
    elif len(filelist) > 1:
        print('Found %i files'%len(filelist))
        multi = True
    else:
        multi = False
    return filelist, multi


# Instead of: v2 = genfromtxt('cooldown.dat', skip_header=31, names=None, delimiter=',').T
# could have used: v = loadtxt('cooldown.dat', skiprows=31, delimiter=',', converters={i:(lambda s: float(s.strip() or np.nan)) for i in range(23) }).T
# if the file has 23 columns
# Or if the colums to load is known: v2 = loadtxt('cooldowntransition.dat', skiprows=31, delimiter=',', usecols=sel).T
#  where sel was [1,3,4,5,6,7,8,9,10,11,14,15,16,18,19,20,21]

# To make it look completely like an ndarray,
# see:
#  https://numpy.org/doc/stable/user/basics.dispatch.html
#  https://numpy.org/doc/stable/reference/generated/numpy.lib.mixins.NDArrayOperatorsMixin.html
#  https://numpy.org/doc/stable/user/basics.subclassing.html

class QD_Data(object):
    def __init__(self, filename_or_data, sel_i=0, titles=None, qd_data=None, concat=False, nbcols=None, timestamp='auto',
                 encoding='latin1'):
        """ provide either a numpy data array a filename or a list of filenames,
            of a Quantum Design .dat file. The filenames can have glob patterns (*,?).
            When multiple files are provided, either they are concatenated if
            concat is True (last axis) or they are combined in a 3D array
            with the middle dimension the file number, but only if they
            all have the same shape.
            When providing data, you should also provide titles
            sel_i, when not None, will select columns that are not NaN.
             It is only applied on the first file.
            The object returned can be indexed directly,
            you can also use the v attribute which refers the the data
              with selected colunmns or vr which is the raw data.
            The t attribute will be the converted timestamp.
            The trel attribute is the timestamp column minus the first value.
            timestamp is the parameter used for do_timestamp.
            titles is the selected columns,
            titles_raw is the full column names.
            headers is the full headers.
            qd_data when given, will be used for headers, titles, sel_i defaults when
              data is ndarray.
            nbcols when not None, forces to load that particular number of column and
                    skip lines without enough elements.
                    Use it if you receive ValueError with showing the wrong number of columns.

            Use show_titles to see the selected columns.
            Use do_sel and do_timestamp to change the column selection or the t attribute.
        """
        super(QD_Data, self).__init__()
        if isinstance(filename_or_data, np.ndarray):
            self.filenames = None
            self.vr = filename_or_data
            if qd_data is not None:
                self.filenames = qd_data.filenames
                self.headers = qd_data.headers
                self.headers_all = qd_data.headers_all
                if titles is None:
                    titles = qd_data.titles_raw
                if sel_i is None:
                    sel_i = qd_data._sel
            else:
                self.headers = None
        else:
            filenames, multi = _glob(filename_or_data)
            if filenames is None:
                return
            self.filenames = filenames
            first = True
            hdrs_all = []
            vr_all = []
            for f in filenames:
                v, _titles, hdrs, sel = read_one_ppms_dat(f, sel_i=None, nbcols=nbcols, encoding=encoding)
                if titles is None:
                    titles = _titles
                if first:
                    self.headers = hdrs
                    v_first = v
                    first = False
                else:
                    if not concat and v.shape != v_first.shape:
                        raise RuntimeError("Files don't have the same shape. Maybe use the concat option.")
                    elif concat and v.shape[:-1] != v_first.shape[:-1]:
                        raise RuntimeError("Files don't have the same number of columns shape.")
                vr_all.append(v)
                hdrs_all.append(hdrs)
                if any(_titles != titles):
                    raise RuntimeError('All files do not have the same titles.')
            self.headers_all = hdrs_all
            if concat:
                v = np.concatenate(vr_all, axis=-1)
            elif not multi:
                v = vr_all[0]
            else:
                v = np.array(vr_all).swapaxes(0,1).copy()
            self.vr = v
            self.headers = hdrs
        if titles is None:
            self.titles_raw = array(['Col_%i'%i for i in range(self.vr.shape[0])])
        else:
            self.titles_raw = array(titles)
        self._t_cache = None
        self._trel_cache = None
        self._t_conv_auto = timestamp
        self.do_sel(sel_i)

    def do_sel(self, row=0):
        """ select columns for v and titles according to row content not being NaN,
            unless it is None.
            When row is a list/tuple/ndarray it will be used to select the columns.
        """
        if self.vr.ndim < 2:
            # No data, disable selection
            row = None
        if row is None:
            self._sel = row
            self.v = self.vr.copy()
            self.titles = self.titles_raw
        elif isinstance(row, slice):
            self._sel = row
            self.v = self.vr[row].copy()
            self.titles = self.titles_raw[row]
        elif isinstance(row, (list, tuple, np.ndarray)):
            self._sel = row
            self.v = self.vr[row]
            self.titles = self.titles_raw[row]
        else:
            vr = self.vr
            if len(vr.shape) == 3:
                vr = vr[:, 0] # pick first file only.
            sel = pick_not_nan(vr[:, row])
            self._sel = sel
            self.v = self.vr[sel]
            self.titles = self.titles_raw[sel]
        self._t_cache = None
        self._trel_cache = None

    def do_timestamp(self, year='auto'):
        """ generates the proper t attribute (and also returns it) from the timestamp data (column 0)
            if year is given or None, the value is used with timestamp_offset.
            if year is 'auto_year', it will try and search the header for a year,
                                   if it fails it will use the current year.
            if year is 'auto' (default), it will try either timestamp_offset or timestamp_offset_log
             depending on the value. For timestamp_offset it will behave like 'auto_year'.
            if year is 'log' the timestamp_offset_log is used.
        """
        t = self[0]
        is_log = False
        if year is None:
            offset = timestamp_offset()
        elif year == 'log':
            is_log = True
            offset = timestamp_offset_log()
        elif year in ['auto', 'auto_year']:
            # do not use t.min, I have seen missing time datapoints
            #   cause by an empty line in the data logs (wrapped BRlog)
            if year == 'auto' and np.nanmin(t) > 10*365*24*3600:
                is_log = True
                offset = timestamp_offset_log()
            else: # auto_year
                year = None
                for h in self.headers:
                    if h.startswith('FILEOPENTIME'):
                        # looks like: FILEOPENTIME,1636641706.00,11/11/2021,9:41 AM
                        # or for brlog:
                        #  FILEOPENTIME, 3846454070.154991 11/19/2021, 3:27:44 AM
                        year = int(h.split(',')[-2].split('/')[-1])
                        break
                offset = timestamp_offset(year)
        elif 1970 < year:
            offset = timestamp_offset(year)
        else:
            raise ValueError('Invalid parameter for year.')
        if is_log:
            # This is wrong, it does not handle daylight saving correctly
            #tconv = t + timestamp_offset_log()
            # But this work (however it is slower)
            tconv = timestamp_log_conv(t)
        else:
            tconv = t + offset
            # Now try to improve (it will not always be correct) for daylight savings
            lcl = time.localtime(tconv[0])
            if lcl.tm_isdst:
                tz = dateutil.tz.gettz()
                dst_offset = tz.dst(datetime.datetime(*lcl[:6])).total_seconds()
                tconv -= dst_offset
        self._t_cache = tconv
        return self._t_cache


    def show_titles(self, raw=False):
        if raw:
            t = self.titles_raw
        else:
            t = self.titles
        return list(enumerate(t))

    def __getitem__(self, indx):
        return self.v[indx]
    def __setitem__(self, indx, val):
        self.v[indx] = val
    def __iter__(self):
        return iter(self.v)

    # bring in all methods/attributes of ndarray here (except specials functions like __add__
    #  that work differently when used with + operator, those need to be added directly)
    def __getattr__(self, name):
        return getattr(self.v, name)

    @property
    def shape(self):
        return self.v.shape
    @shape.setter
    def shape(self, val):
        self.v.shape = val

    def __add__(self, val):
        """ add will concatenate to data sets """
        if not isinstance(val, QD_Data):
            raise ValueError("Can only add two Qd_Data")
        v = np.concatenate((self.vr, val.vr), axis=-1)
        nd = QD_Data(v, qd_data=self)
        nd.filenames = self.filenames + val.filenames
        nd.headers_all = [self.headers, val.headers]
        return nd

    @property
    def t(self):
        if self._t_cache is None:
            self.do_timestamp(self._t_conv_auto)
        return self._t_cache

    @property
    def trel(self):
        if self._trel_cache is None:
            self._trel_cache = self[0] - self[0, 0]
        return self._trel_cache
