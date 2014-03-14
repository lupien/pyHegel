# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

"""
This module contains many utilities:
    loadtxt_csv
    readfile
    merge_pdf
    savefig
    savefig_reset
    savefig_set_enable
    savefig_enabled
    merge_all
    blueforsTlog
    sort_file
Note that savefig is initially disabled.
"""

import time
import os
import numpy as np

try:
    from pyPdf import PdfFileWriter, PdfFileReader
    pyPdf_loaded = True
except ImportError:
    pyPdf_loaded = False
import pylab
import glob
import csv

##################################################

def loadtxt_csv(filename, dtype=float, unpack=False, ndmin=0):
    f=open(filename, 'r')
    reader = csv.reader(f)
    X=[]
    for line in reader:
        try:
            conv = map(dtype, line)
        except ValueError:
            # skip this line
            continue
        if conv != []:
            X.append(conv)
    X = np.array(X)
    # following loadtxt
    if not ndmin in [0, 1, 2]:
        raise ValueError('Illegal value of ndmin keyword: %s' % ndmin)
    # Tweak the size and shape of the arrays - remove extraneous dimensions
    if X.ndim > ndmin:
        X = np.squeeze(X)
    # and ensure we have the minimum number of dimensions asked for
    # - has to be in this order for the odd case ndmin=1, X.squeeze().ndim=0
    if X.ndim < ndmin:
        if ndmin == 1:
            X = np.atleast_1d(X)
        elif ndmin == 2:
            X = np.atleast_2d(X).T
    if unpack:
        return X.T
    return X

#TODO add handling of title column and extracting headers
_readfile_lastnames = []
def readfile(filename, prepend=None, getnames=False, csv='auto', dtype=None):
    """
    This function will return a numpy array containing all the data in the
    file.
    When not None, the path is joined to prepend (unless absolute)
    filename can contain a glob (*) parameter to combine many files.
    or be a list of files or glob. (the glob.glob function is used internally)
    The result of a glob is sorted.
    When reading multiple files, they need to have the same shape.
       glob examples:
         base_other_*.txt   (* matches any string, including empty one )
         base_other_??.txt  (? matches a single character )
         base_other[abc]_.txt  ([abc] matches a single character among abc
                                [a-zA-F] matches a single character in ranges
                                   a-z and A-F
                                [!...] does not match any of the characters (or ranges)
                                   in ... )
        *, ? and [ can be escaped with a \\

    For a single file, the returned array has shape (n_columns, n_rows)
    so selecting a column in a data file is the first index dimension.
    For multiple files, the shape is (n_columns, n_files, n_rows)
     or (nfiles, n_rows) if the files contain only a single column

    The csv option can be True, False or 'auto'. When in auto, the file extension
    is used to detect wheter to use csv or not. When csv is used
    the column separator is ',' and all lines not containing only numerical
    are automatically skipped.

    When dtype is given a valid type (like uint16), it means all the files will
    be read in binary mode as containing that dtype.

    If the file extension ends with .npy, it is read with np.load as a numpy
    file.

    The list of files is saved in the global variable _readfile_lastnames.
    When the parameter getnames=True, the return value is a tuple
    (array, filenames_list)
    """
    global _readfile_lastnames
    if not isinstance(filename, (list, tuple, np.ndarray)):
        filename = [filename]
    filelist = []
    for fglob in filename:
        if prepend != None:
            fglob = os.path.join(prepend, fglob)
        fl = glob.glob(fglob)
        fl.sort()
        filelist.extend(fl)
    _readfile_lastnames = filelist
    if len(filelist) == 0:
        print 'No file found'
        return
    elif len(filelist) > 1:
        print 'Found %i files'%len(filelist)
        multi = True
    else:
        multi = False
    ret = []
    for fn in filelist:
        if dtype != None:
            ret.append(np.fromfile(fn, dtype=dtype))
            continue
        if fn.lower().endswith('.npy'):
            ret.append(np.load(fn))
            continue
        if csv=='auto':
            if fn.lower().endswith('.csv'):
                docsv = True
            else:
                docsv = False
        else:
            docsv = csv
        if docsv:
            ret.append(loadtxt_csv(fn).T)
        else:
            ret.append(np.loadtxt(fn).T)
    if not multi:
        return ret[0]
    # convert into a nice numpy array. The data is copied and made contiguous
    ret = np.array(ret)
    if ret.ndim == 3:
        # we make a copy to make it a nice contiguous array
        ret = ret.swapaxes(0,1).copy()
    if getnames:
        return (ret, filelist)
    else:
        return ret

##################################################

def merge_pdf(filelist, outname):
    """
    This merges many pdf files (a list of names filelist) into one (outname).
    To obtain a list you could use the glob.glob function if necessary.

    You can obtain the same thing on the command line with the pdftk
    command. (Install it with cygwin on windows)
      !/cygwin/bin/pdftk file1.pdf file2.pdf file3.pdf cat output file123.pdf
    """
    if not pyPdf_loaded:
        raise ImportError, 'Missing pyPdf package. You need to install that.'
    output = PdfFileWriter()
    in_files = []
    for f in filelist:
        in_file = file(f, 'rb')
        in_files.append(in_file)
        input = PdfFileReader(in_file)
        for page in input.pages:
            output.addPage(page)
    of = file(outname, 'wb')
    output.write(of)
    for f in in_files:
        f.close()
    of.close()

_savefig_list=[]
_savefig_enabled=False

def savefig_set_enable(state=True):
    """
    This enables or disables the savefing function.
    """
    global _savefig_enabled
    _savefig_enabled = state

def savefig_enabled():
    """
    This returns True when savefig is currently enabled.
    """
    global _savefig_enabled
    return _savefig_enabled

def savefig_reset():
    """
    This resets the list of filename being saved.
    Useful if merge_pdf is later needed.
    """
    global _savefig_list
    _savefig_list = []

def merge_all(outname):
    """
    Merge all the files in the savelist so far into the filename outname
    It will not work if savefig is disabled is set.
    """
    global _savefig_list
    if not savefig_enabled():
        print 'Skipping merge all to', outname
        return
    merge_pdf(_savefig_list, outname)

def savefig(filename, *args, **kwarg):
    """
    Similar to the matplotlib savefig, except it keeps a list
    of the names since the last savefig_reset and it can be disabled
    with savefig_set_enable(False)
    """
    global _savefig_list
    if not savefig_enabled():
        print 'Skipping savefig to', filename
        return
    pylab.savefig(filename, *args, **kwarg)
    _savefig_list.append(filename)

#########################################################
# Convert to BlueFors Tlog format
#########################################################

def _blueforsTlog_Conv(data, time_data, channels, logdir):
    """
    input is similar to blueforsTlog except data and time_data are a single row
    It returns a tuple of dirname, list of (filename, datastr)
    """
    dataT = data[::2]
    dataR = data[1::2]
    localtime = time.localtime(time_data)
    str_pref = time.strftime(' %d-%m-%y,%H:%M:%S', localtime)+',%.6E'
    filedir = time.strftime('%y-%m-%d', localtime)
    dirname = os.path.join(logdir, filedir)
    Tfile = 'CH%i T {}.log'.format(filedir)
    Rfile = 'CH%i R {}.log'.format(filedir)
    outvec = []
    for T, R, c in zip(dataT, dataR, channels):
        outvec.append((Tfile%c, str_pref%T))
        outvec.append((Rfile%c, str_pref%R))
    return dirname, outvec

def blueforsTlog(data, time_data, channels=[1,2,5,6], logdir='C:/BlueFors/Log-files',
                 sort_exist=True, cleanup=True):
    """
    From a vector of data and time_data (obtained from a py hegel record for example),
    it creates the temperature logfiles in the logdir path
    data needs to have a shape (2*nch, ndata) where nch is the number of channels
    which needs to match with channels. The 2 is because the data needs to be
    temperature then resistance.
    time_data is in seconds since epoch (what record and sweep use)
    The data is always appended to the destination file.
    When sort_exist=True, file that existed before being called are sorted
           and duplicates are removed.
    cleanup is used by sort_file
    WARNING:
        It is better to close all the open file that could be affected by this
        script.
    example:
        a=readfile('some_log_file_from_record.txt')
        util.blueforsTlog(a[3:],a[0]) # assuming a record([sr1, tc3.fetch]), sr1 adds 2 columns
    """
    if data.shape[0] != len(channels)*2:
        raise ValueError, 'Invalid number of columns in data vs channels'
    prevdir = ''
    prevfile = [('', None, '')]*len(channels)*2
    for d, t in zip(data.T, time_data):
        dirname, vec = _blueforsTlog_Conv(d, t, channels, logdir)
        if prevdir != dirname:
            if not os.path.exists(dirname):
                os.mkdir(dirname)
            prevdir = dirname
        for i, (fn, s) in enumerate(vec):
            pv = prevfile[i]
            if fn != pv[0]:
                if pv[1] != None:
                    pv[1].close()
                    if pv[2] and sort_exist:
                        sort_file(pv[2], cleanup=cleanup)
                fullname = os.path.join(dirname, fn)
                ex = os.path.exists(fullname)
                exfn = ''
                if ex:
                    exfn = fullname
                print 'appending to ', fullname, '(exist=%s)'%ex
                f = open(fullname, 'a')
                prevfile[i] = (fn, f, exfn)
            else:
                f = pv[1]
            f.write(s+'\n')
    for fn, f, ex in prevfile:
        f.close()
        if ex:
            sort_file(ex, cleanup=cleanup)

def sort_file(filename, uniq=True, cleanup=False):
    """
    This functions sorts the entries in a file in alphabetical order
    It will create a .bak file
    uniq=True (default) will remove duplicates in the file, otherwise
           duplicates are kept
    cleanup=True will remove the .bak file when the script completes (False by default)
    """
    f=open(filename)
    lines=[]
    with open(filename) as f:
        lines = f.readlines()
    if uniq:
        lines = sorted(set(lines))
    else:
        lines.sort()
    backup = filename+'.bak'
    if os.path.exists(backup):
        # windows does not rename if the file already exists, so delete
        os.remove(backup)
    os.rename(filename, backup)
    with open(filename, 'w') as f:
        f.writelines(lines)
    if cleanup:
        os.remove(backup)

def read_bluefors(filename):
    """
    reads and parse the bluefors logfile named filename
    returns a list of (time, [str1, str2])
    The time is in seconds since epoch.
    The str1, str2 are the data columns following the time.
    To have them converted use read_blueforsRTF or read_blueforsGauges
    """
    ret = []
    with open(filename) as f:
        for line in f:
            #   print line
            splits = line.lstrip(' ').split(',')
            if len(splits)<3:
                continue
            t = time.strptime(splits[0]+','+splits[1], '%d-%m-%y,%H:%M:%S')
            ret.append((time.mktime(t), splits[2:]))
    return ret

def read_blueforsRTF(filename):
    """
    Reads a bluefors log filename that contains Temperature, Resistance or Flow
    information.
    returns an array of shape (2, n) for n lines in the data
    The columns are time and values
    """
    v = read_bluefors(filename)
    v = [(t, float(val[0])) for t, val in v]
    return np.array(v).T

def read_blueforsGauges(filename):
    """
    Reads a bluefors log filename that contains Maxi Gauge info
    information.
    returns an array of shape (ngages+1, nlines). The +1 is for the time
    column which comes first.
    """
    v = read_bluefors(filename)
    # The file data is "CH1,P1  ,1, 7.25E-6,0,1" which repeats for every channel
    # the fields are CHn, channel name, enabled, value, status, always 1??
    # status: 0:OK, 1:underange, 2:Overange, 3:SensorError, 4:SensorOFf, 5:NoSensor, 6: identificationError
    # unit: 0:mbar, 1:Torr, 2:Pascal
    v = [[t]+[float(x) for x in vals[3::6]] for t, vals in v]
    return np.array(v).T
