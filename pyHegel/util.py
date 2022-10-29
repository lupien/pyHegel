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

"""
This module contains many utilities:
    readfile
    loadtxt_csv
    read_comments
    merge_pdf
    savefig
    savefig_reset
    savefig_set_enable
    savefig_enabled
    merge_all
    print_file
    list_printers
    blueforsTlog
    read_blueforsTlog
    find_closest_times
    read_bluefors
    read_bluefors_all
    read_blueforsRTF
    read_blueforsGauges
    read_blueforsChannels
    read_iceoxford
    sort_file
    find_index_closest
    QD_Data
Conversion functions and time constants calculation helpers:
    dB2A, dB2P, P2dB, A2dB
    dBm2o, o2dBm
    G2Z, Z2G, vswr2g, g2vswr
    xy2rt, rt2xy
    phase_unwrap
    phase_wrap
    filter_to_fraction
    fraction_to_filter
    tc_to_enbw_3dB

Note that savefig is initially disabled.
"""

from __future__ import absolute_import

import datetime
import time
import os
import os.path
import subprocess
import numpy as np
import io
from scipy.optimize import brentq as brentq_rootsolver
from scipy.special import gamma

from pyHegel import qd_data
from .qd_data import QD_Data

try:
    try:
        from PyPDF2 import PdfFileWriter, PdfFileReader
        # TODO with PyPDF2 we could use the PyPDF2.PdfFileMerger
        #      instead of Reader-Writer combo.
        #      see: http://www.blog.pythonlibrary.org/2012/07/11/pypdf2-the-new-fork-of-pypdf/
    except ImportError:
        from pyPdf import PdfFileWriter, PdfFileReader
    pyPdf_loaded = True
except ImportError:
    pyPdf_loaded = False
import pylab
import glob
import csv
import re

##################################################

def read_comments(filename, comments='#', pick=None, before=False, skiprows=0, encoding='utf8'):
    """ reads comments in filename
        Goes line by line and counts line that do not start with the comments string symbol
        (comments can also be a list of symbols)
        pick are the start string of comments to find. Can be a string or a list of strings.
        Or if it is None, will be automatic to find comment pyHegel saves in files.
        It returns a list of tuple of (comments, prev_line_count, timestamp)
         and the final count. The timestamp is None if it is not known.
        where timestamp is extracted from the comment header when pick is None and
        when it was saved with the data (for data generated with versions of pyHegel that
        contain this read_comments function).
        So prev_line_count will be the index to the line following the comment.
        If you prefer it to point to the previous line, use option before
        or convert it like this:
           [ (c, max(i-1,0), t) for c, i, t in result]
        skiprows is to skip lines at the start.
        encoding is the encoding used to convert to unicode.
    """
    if isinstance(comments, (basestring, bytes)):
        comments = [comments]
    comments = [re.escape(c) for c in comments]
    time_re = False
    if pick is None:
        numeric_const_pattern = r'[-+]?(?:(?:\d*\.\d+)|(?:\d+\.?))(?:[Ee][+-]?\d+)?'
        pick = [r'\#C\# ', r'\#C\:%s\# '%numeric_const_pattern]
        pick_re = re.compile('(' + '|'.join(pick) + ')')
        time_re = re.compile(r'\#C\:(%s)\# $'%numeric_const_pattern)
    else:
        if isinstance(pick, (basestring, bytes)):
            pick = [pick]
        pick_re = re.compile('(' + '|'.join(re.escape(c) for c in pick) + ')')
    # use a group to return the group in the split
    comments_re = re.compile('(' + '|'.join(comments + pick) + ')')
    count = 0
    skip_count = 0
    result = []
    with io.open(filename, 'rt', encoding=encoding) as f:
        for line in f:
            if skip_count < skiprows:
                skip_count += 1
                continue
            split = comments_re.split(line, maxsplit=1)
            if len(split) == 1: # no comments
                count += 1
                continue
            # we have a general comment, now check if it is a pick one
            split = pick_re.split(line, maxsplit=1)
            if len(split) == 1: # not a pick comment
                continue
            # we have a pick comment
            comment = split[-1].rstrip()
            token = split[-2]
            if time_re:
                timestamp = time_re.match(token)
                if timestamp is not None:
                    timestamp = float(timestamp.group(1))
            else:
                timestamp = None
            if split[0].strip() == '':
                # comment starts at beginning of line (except for empty spaces)
                i = count
                if before:
                    i = max(0, i-1)
                result.append( (comment, i, timestamp) )
            else:
                # comment is probably on the end of a data line, make it point to this line.
                result.append( (comment, count, timestamp) )
                count += 1
    return result, count


##################################################

def loadtxt_csv(filename, dtype=float, unpack=False, ndmin=0, skiprows=0, **kwargs):
    """\
       Load a csv file using the reader from the csv module.
       It does some extra cleaning, and converts data using dtype.
       skiprows is the nimber of line to skip before parsing the file.
       unpack then True, does a transpose on the returned data (like for loadtxt).
       ndim is the minimum dimension of the returned array (like for loadtxt).
       the kwargs arguments are passed on to the csv.reader
    """
    X=[]
    # The docs says to use mode 'rb' but if the file uses mac termination it will fail
    # (should be rare). So instead use 'rU' (the parser can always deal with newline)
    # see http://bugs.python.org/issue8387
    with open(filename, 'rU') as f:
        reader = csv.reader(f, **kwargs)
        skip_count = 0
        for line in reader:
            if skip_count < skiprows:
                skip_count += 1
                continue
            try:
                if line[-1] is '':
                    # some files have an ending , sep which produces an empty last field
                    line = line [:-1]
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

def _shape_compare(shape1, shape2, concatenate):
    if concatenate is True:
        concatenate = -1
    if concatenate is not False:
        axes = list(range(len(shape1)))[concatenate]
        shape1 = [s for i,s in enumerate(shape1) if i != axes]
        shape2 = [s for i,s in enumerate(shape2) if i != axes]
    return shape1 == shape2

def _reshape_helper(data, shape, force=False, force_def=np.nan, file=None):
    if shape is not None:
        old_shape = data.shape
        new_shape = old_shape[:-1] + shape
        ncol = old_shape[0]
        if file is not None:
            pre = file+': '
        else:
            pre = ''
        try:
            data = data.reshape(new_shape)
        except ValueError:
            if force:
                new_data = np.full(new_shape, force_def)
                data_flat = data.reshape((ncol, -1)).T
                nd_flat = new_data.reshape((ncol, -1)).T
                nd_flat[:len(data_flat)] = data_flat
                data = new_data
                print pre+'Forced shape from %s to %s.'%(old_shape, new_shape)
            else:
                print pre+'Unable to convert shape from %s to %s (probably an incomplet sweep). Shape unadjusted.'%(old_shape, new_shape)
        else:
            print pre+'Converted shape from %s to %s.'%(old_shape, new_shape)
    return data

_readfile_lastnames = []
_readfile_lastheaders = []
_readfile_lasttitles = []
def readfile(filename, prepend=None, getnames=False, getheaders=False, csv='auto', dtype=None, multi_sweep=True, concatenate=False, multi_force_def=np.nan, comments=False, encoding='utf8', firstdim='default', opts={}):
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
     or (n_comuns, n_rows*n_files) if using concatenate
    When multi_sweep is True and the file was created from a multi sweep,
     n_rows is replaced by the correct shape to handle the multiple dimensions of the sweep
     if possible. When it is 'force', it creates the correct shape filled with multi_force_def for
     unavailable values.

    The csv option can be True, False or 'auto'. When in auto, the file extension
    is used to detect wheter to use csv or not. When csv is used
    the column separator is ',' and all lines not containing only numerical
    are automatically skipped.

    When dtype is given a valid type (like uint16), it means all the files will
    be read in binary mode as containing that dtype.

    If the file extension ends with .npy, it is read with np.load as a numpy
    file.

    concatenante, when True, will merge rows from multiple files together.
      It can also be set to an integer to select the axes to merge (it
      is -1 when using True)

    encoding is the encoding used to convert text to unicode (for headers, comments).
      It defaults to utf8. Use latin1 if you have some random binary data.

    opts is a dictionnary of options passed to the actual reader which is np.fromfile (when dtype is given),
      np.load (for files ending in .npy), util.loadtxt_csv (for csv files) and np.loadtxt
      otherwise.

    comments when True, will read and return a list of all in-line comments in the file using
       read_comments. comments can also be a dictionnary, in which case they are the options
       to read_comments. When enabled, the return values will be
         (array, comments).

    firstdim can be 'default', False, True or a column index.
             False will not transpose axes,
             True will swap axes (switching dim 0 and 1)
             an index will move that dimension to be the first one.
             default does like True but only for multiple files that have more than one column.
               Note that it will swap axes for multiple files of .npy with 2 dimensions


    The list of files is saved in the global variable _readfile_lastnames.
    When the parameter getnames=True, the return value is a tuple
    (array, filenames_list) or (array, comments, filenames_list)
    The headers of the FIRST file are saved in the global variable _readfile_lastheaders.
    The headers are recognized has lines starting with #
    The last header is probably the title line (_readfile_lastheaders[-1]) and is parsed into
    _readfile_lasttitles (assuming columns are separated by tabs)
    When the parameter getheaders=True, the return value is a tuple
    (array, titles_list, headers_list) or (array, comments, titles_list, headers_list)
    If both getheaders and getnames are True, the the return value is a tuple
    (array, filenames_list, titles_list, headers_list) or (array, comments, filenames_list, titles_list, headers_list)
    """
    global _readfile_lastnames, _readfile_lastheaders, _readfile_lasttitles
    if multi_sweep not in [True, False, 'force']:
        raise ValueError("multi_sweep needs to be one of True, False or 'force'")
    if comments is True:
        comments = {}
    do_comments = comments is not False
    if not isinstance(filename, (list, tuple, np.ndarray)):
        filename = [filename]
    filelist = []
    for fglob in filename:
        if prepend is not None:
            fglob = os.path.join(prepend, fglob)
        fl = glob.glob(fglob)
        fl.sort()
        filelist.extend(fl)
    _readfile_lastnames[:] = filelist
    if len(filelist) == 0:
        print 'No file found'
        return
    elif len(filelist) > 1:
        print 'Found %i files'%len(filelist)
        multi = True
    else:
        multi = False
    hdrs = []
    titles = []
    if dtype is None and not filelist[0].lower().endswith('.npy'): # binary files don't have headers
        with io.open(filelist[0], 'rt', encoding=encoding) as f: # only the first file
            while True:
                line = f.readline()
                if len(line) == 0:
                    # eof encountered
                    raise RuntimeError('File "%s" contains no data, except for possibly some headers'%filelist[0])
                if line[0] != '#':
                    break
                hdrs.append(line)
        if len(hdrs): # at least one line, we use the last one, strip start # and end newline
            titles = hdrs[-1][1:-1].split('\t')
    _readfile_lastheaders[:] = hdrs
    _readfile_lasttitles[:] = titles
    # This needs to match the line in commands.sweep_multi
    multi_hdr = '#readback numpy shape for line part: '
    if multi_sweep and len(hdrs)>2 and hdrs[-2].startswith(multi_hdr):
        shape_s = hdrs[-2][len(multi_hdr):].strip().split(',')
        shape = tuple([int(s) for s in shape_s])
        do_reshape = lambda data, fn: _reshape_helper(data, shape, multi_sweep=='force', multi_force_def, fn)
    else:
        shape = None
        do_reshape = lambda data, fn: data
    if concatenate is True:
        concatenate = -1
    ret = []
    comments_array = []
    first_shape = None
    orig_ndim = None
    for fn in filelist:
        if dtype is not None:
            current = np.fromfile(fn, dtype=dtype, **opts)
        elif fn.lower().endswith('.npy'):
            current = np.load(fn, **opts)
        else:
            if csv=='auto':
                if fn.lower().endswith('.csv'):
                    docsv = True
                else:
                    docsv = False
            else:
                docsv = csv
            if docsv:
                current = loadtxt_csv(fn, **opts).T
            else:
                current = np.loadtxt(fn, **opts).T
        N_lines = np.atleast_1d(current).shape[-1]
        orig_ndim = current.ndim
        current = do_reshape(current, fn)
        if first_shape is None:
            first_shape = current.shape
        elif not _shape_compare(first_shape, current.shape, concatenate):
            raise RuntimeError('Not all objects have same shape. "%s"=%s and "%s"=%s'%
                                (filelist[0], first_shape, fn, current.shape))
        if do_comments:
            ret_comments, data_len = read_comments(fn, encoding=encoding, **comments)
            if data_len != N_lines:
                raise RuntimeError('Incompatible data length between read data (%i) and read comments (%i).'%(N_lines, data_len))
            comments_array.append(ret_comments)
        ret.append(current)
    do_comment_reshape = True
    if not multi:
        ret = ret[0]
        if do_comments and shape is None:
            comments_array = comments_array[0]
            do_comment_reshape = False
    elif concatenate is not False:
        if do_comments:
            # fixup comments index for concatenation.
            # could be on multi dim data.
            offsets = [0] + list(np.cumsum([r.shape[concatenate] for r in ret])[:-1])
            a = []
            def adjust_shape(index, offset, data):
                sh = data.shape
                i = list(np.unravel_index(index, sh))
                i[concatenate] += offset
                i = i[1:] # now skip the column index
                if len(i) == 1:
                    return i[0]
                return tuple(i)
            for o, ca, r in zip(offsets, comments_array, ret):
                a.extend( [ (c, adjust_shape(j, o, r), t) for c,j,t in ca] )
            comments_array = a
        ret = np.concatenate(ret, axis=concatenate)
        do_comment_reshape = False
    else:
        # convert into a nice numpy array. The data is copied and made contiguous
        # originally I would swapaxes for any ndim==3 data set (before reshaping of multisweep)
        #   This meant that it would swap 2 dim .npy multiple files and also
        #    3 dim single .npy file.
        # then I modified (commit 4bda44652c39be12af55163679162ddc05dd44c1)
        #   the workings and it swapaxes for all multiple files except
        #   raw binary data (dtype) and .npy files with 2 dimensions.
        #   Therefore it even affected data files with a single dim (which is incorrect).
        #   So that was wrong
        # Now default firstdim is the same as originally except I do not swap axes
        #  for single 3 dim .npy files.
        ret = np.array(ret)
        ndim = ret[0].ndim
        if firstdim == 'default':
            if dtype is not None:
                firstdim = False
            elif orig_ndim == 2:
                firstdim = 1
            else:
                firstdim = False
        elif firstdim is True:
            firstdim = 1
        if firstdim is not False:
            # old code was
            # ret = ret.swapaxes(0,1).copy()
            a = range(ndim+1) # +1 for file index
            indx = [firstdim] + a[:firstdim] + a[firstdim+1:]
            ret = ret.transpose(indx).copy()
    if do_comments and do_comment_reshape:
        a = []
        sh = ret.shape[1:]
        # note that np.unravel_index is the opposite of np.ravel_multi_index
        for i, ca in enumerate(comments_array):
            a.extend( [ (c, np.unravel_index(j+i*N_lines, sh), t) for c,j,t in ca] )
        comments_array = a
    if not do_comments and not getnames and not getheaders:
        return ret
    ret = (ret, )
    if do_comments:
        ret = ret + (comments_array,)
    if getnames:
        ret = ret + (filelist, )
    if getheaders:
        ret = ret + (titles, hdrs)
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
        raise ImportError, 'Missing PyPDF2 or pyPdf package. You need to install one of them.'
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
# Tools to handle printing
#########################################################
def _is_windows():
    return os.name == 'nt'

_default_printer = None
def _get_default_printer():
    if _is_windows():
        import win32print
        default = win32print.GetDefaultPrinter()
    else:
        s = subprocess.check_output(['lpstat', '-d'])
        default = s.rstrip().rsplit(' ', 2)[-1]
    return default

def print_file(filename, printer=None):
    """
    prints filename using printer. When printer is None, it uses
    _default_printer. If _default_printer is None (default), it will
    use the system default printer (see list_printers)
    """
    default = _get_default_printer()
    if printer is None:
        if _default_printer is not None:
            printer = _default_printer
        else:
            printer = default
    if _is_windows():
        import win32api
        # the function does not always handle paths with / properly so clean it first
        # and make it absolute to be sure
        filename = os.path.realpath(filename)
        win32api.ShellExecute(0, 'print', filename, '/d:"%s"'%printer, None, 0)
    else:
        subprocess.check_call(['lp', '-d', printer, filename])

def list_printers():
    """
    prints the default system printer and
    lists the available printers (local and connected for windows)
    """
    default = _get_default_printer()
    print 'System default printer is: %r'%default
    if _is_windows():
        import win32print
        plist = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL|win32print.PRINTER_ENUM_CONNECTIONS, None, 4)
        plist = [p['pPrinterName'] for p in plist]
    else:
        alls = subprocess.check_output(['lpstat', '-a'])
        plist = [s.split(' ', 2)[0] for s in alls.rstrip().split('\n')]
    return plist


#########################################################
# Convert to BlueFors Tlog format
#########################################################

def _blueforsTlog_Conv(data, time_data, channels, logdir, onlyT=False):
    """
    input is similar to blueforsTlog except data and time_data are a single row
    It returns a tuple of dirname, list of (filename, datastr)
    """
    if onlyT:
        dataT = dataR = data
    else:
        dataT = data[::2]
        dataR = data[1::2]
    localtime = time.localtime(time_data)
    str_pref = time.strftime('%d-%m-%y,%H:%M:%S', localtime)+',%.6E'
    filedir = time.strftime('%y-%m-%d', localtime)
    dirname = os.path.join(logdir, filedir)
    Tfile = 'CH%i T {}.log'.format(filedir)
    Rfile = 'CH%i R {}.log'.format(filedir)
    outvec = []
    for T, R, c in zip(dataT, dataR, channels):
        outvec.append((Tfile%c, str_pref%T))
        if not onlyT:
            outvec.append((Rfile%c, str_pref%R))
    return dirname, outvec

def blueforsTlog(data, time_data, channels=[1,2,5,6], logdir='C:/BlueFors/Logs',
                 sort_exist=True, cleanup=True, onlyT=False):
    """
    From a vector of data and time_data (obtained from a py hegel record for example),
    it creates the temperature logfiles in the logdir path
    data needs to have a shape (2*nch, ndata) where nch is the number of channels
    which needs to match with channels. The 2 is because the data needs to be
    temperature then resistance. Unless onlyT is used.
    time_data is in seconds since epoch (what record and sweep use)
    The data is always appended to the destination file.
    When sort_exist=True, file that existed before being called are sorted
           and duplicates are removed.
    cleanup is used by sort_file
    WARNING:
        It is better to close all the open file that could be affected by this
        script.
        Also you should not try to update a file that is being accessed by another program.
        So if you are about the change the file into which the Bluefors log program is currently
        writing you will possibly corrupt the file. Stop the logging before proceeding or don't
        process the data for the current day (skip that data, or wait a day)
    example:
        a=readfile('some_log_file_from_record.txt')
        util.blueforsTlog(a[3:],a[0]) # assuming a record([sr1, tc3.fetch]), sr1 adds 2 columns
    """
    N = len(channels)
    N = N if onlyT else 2*N
    if data.shape[0] != N:
        raise ValueError, 'Invalid number of columns in data vs channels'
    prevdir = ''
    prevfile = [('', None, '')]*N
    for d, t in zip(data.T, time_data):
        dirname, vec = _blueforsTlog_Conv(d, t, channels, logdir, onlyT=onlyT)
        if prevdir != dirname:
            if not os.path.exists(dirname):
                os.mkdir(dirname)
            prevdir = dirname
        for i, (fn, s) in enumerate(vec):
            pv = prevfile[i]
            if fn != pv[0]:
                if pv[1] is not None:
                    pv[1].close()
                    if pv[2] and sort_exist:
                        sort_file(pv[2], cleanup=cleanup)
                fullname = os.path.join(dirname, fn)
                ex = os.path.exists(fullname)
                exfn = ''
                if ex:
                    exfn = fullname
                print 'appending to ', fullname, '(exist=%s)'%ex
                f = open(fullname, 'ab') # use binary access to properly terminate lines
                prevfile[i] = (fn, f, exfn)
            else:
                f = pv[1]
            f.write(s+'\r\n') # use windows line termination always.
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
    lines=[]
    # we try to keep the line termination of the files, irrespective of OS
    term = None
    with open(filename, 'rU') as f:
        lines = f.readlines()
        term = f.newlines
    if term is None:
        term = os.linesep
    if isinstance(term, tuple):
        # there is no time order in the tuple
        # now pick termination of first line
        with open(filename, 'rb') as f:
            line = f.read(len(lines[0])+1)
        if line[-2:] == '\r\n':
            term = '\r\n'
        else:
            term = line[-2]
    if term != '\n':
        lines = [l.replace('\n', term) for l in lines]
    # different versions added/removed a space at the beginning of the line
    if uniq:
        lines = sorted(set(lines), key=str.lstrip)
    else:
        lines.sort(key=str.lstrip)
    backup = filename+'.bak'
    if os.path.exists(backup):
        # windows does not rename if the file already exists, so delete
        os.remove(backup)
    os.rename(filename, backup)
    with open(filename, 'wb') as f:
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
    with open(filename, 'rU') as f:
        for line in f:
            #   print line
            splits = line.lstrip(' ').split(',')
            if len(splits)<3:
                continue
            # This strptime is the slowest thing when reading the log files
            # TODO: speed this up and reading will be much quicker
            t = time.strptime(splits[0]+','+splits[1], '%d-%m-%y,%H:%M:%S')
            ret.append((time.mktime(t), splits[2:]))
    return ret

def read_blueforsRTF(filename, missing_as_empty=False, quiet=False):
    """
    Reads a bluefors log filename that contains Temperature, Resistance or Flow
    information.
    returns an array of shape (2, n) for n lines in the data
    The columns are time and values
    when missing_as_empty, missing files are returned as empty arrays instead of causing an error.
    quiet when False (default) shows the missing files.
    """
    if missing_as_empty:
        if not os.path.isfile(filename):
            if not quiet:
                print 'Skipping: %s'%filename
            return np.zeros((2,0))
    v = read_bluefors(filename)
    v = [(t, float(val[0])) for t, val in v]
    return np.array(v).T


def _parse_day(date):
    """
    takes in the start/stop date format of read_blueforsTlog and returns a date object.
    """
    if date is None:
        return datetime.date.today()
    if isinstance(date, basestring):
        parts = date.split('-')
        if len(parts) != 3:
            parts = date.split('/')
        if len(parts) != 3:
            parts = [date[:-4], date[-4:-2], date[-2:]]
        year, month, day = [int(p) for p in parts]
        if year < 2000:
            year += 2000
        return datetime.date(year, month, day)
    else:
        return datetime.date.fromtimestamp(date)

def _read_helper(filename):
    if os.path.isfile(filename):
        return read_blueforsRTF(filename)
    else:
        return np.ndarray((2,0))

def _read_bluefors_select(start_date, stop_date=None):
    """
    Helper to find the directories
    start_date and stop_date are either epoch values (number of days since jan 1st 1970)
    or strings giving the date '20150921' '2015-09-21', '2015-9-21', '150921', '15-09-21',
    '15-9-21' or replace '-' with '/'
    if stop_day is None, then today's date is used.
    If start_date is an ndarray, it uses the minimum as start_date and maximum as stop_date
    If start_date is a list, it is used directly.
    This function returns the list of possible directories.
    """
    if isinstance(start_date, np.ndarray):
        stop_date = start_date.max()
        start_date = start_date.min()
    elif isinstance(start_date, list):
        return [ _parse_day(date) for date in start_date ]
    start_date = _parse_day(start_date)
    stop_date = _parse_day(stop_date)
    date = start_date
    dirs = []
    while date <= stop_date:
        dirs.append(date.strftime('%y-%m-%d'))
        date += datetime.timedelta(days=1)
    return dirs

def read_blueforsTlog(start_date, stop_date=None, channels=[1,2,5,6], logdir='C:/BlueFors/Logs', merge_if_possible=True, missing_ok=True, quiet=False):
    """
    Reads and combines the data files for temperature channels selected.
    It looks for the files under date directories under logdir.
    start_date and stop_date are either epoch values (number of days since jan 1st 1970)
    or strings giving the date '20150921' '2015-09-21', '2015-9-21', '150921', '15-09-21',
    '15-9-21' or replace '-' with '/'
    It returns a list of arrays (one for each channel). The arrays contain the
    are shaped (3, n) where the 3 columns stand for time since the epoch, the temperature
    and the resistance.
    When merge_if_possible is True (default), it checks if all the channels have the same date, if so
    it combines them in a single (1+2*Nch, n) array. If it can't it outputs a warning and returns the list.
    if stop_day is None, then today's date is used.
    If start_date is an ndarray, it uses the minimum as start_date and maximum as stop_date.
    If start_date is a list, it is used directly.
    missing_ok, when True which is the default, just skip missing files without producing an exception (but prints it, unless quiet is True).
    """
    results = []
    for ch in channels:
        results.append(np.ndarray((0,3)))
    for dirname in _read_bluefors_select(start_date, stop_date):
        Tfile = 'CH%i T {}.log'.format(dirname)
        Rfile = 'CH%i R {}.log'.format(dirname)
        for i,ch in enumerate(channels):
            Tvals = read_blueforsRTF(os.path.join(logdir, dirname, Tfile%ch), missing_as_empty=missing_ok, quiet=quiet)
            Rvals = read_blueforsRTF(os.path.join(logdir, dirname, Rfile%ch), missing_as_empty=missing_ok, quiet=quiet)
            if Tvals.shape[1] == 0 and Rvals.shape[1] == 0:
                continue
            if Tvals.shape[1] == 0:
                Tvals = Rvals.copy()
                Tvals[1] = np.nan
            elif Rvals.shape[1] == 0:
                Rvals = Tvals.copy()
                Rvals[1] = np.nan
            if Tvals.shape[1] == Rvals.shape[1] and np.all(Rvals[0] == Tvals[0]):
                ar = np.empty((Tvals.shape[1],3), dtype=Tvals.dtype)
                ar[:,:2] = Tvals.T
                ar[:,2] = Rvals[1]
                results[i] = np.concatenate((results[i], ar))
            else:
                Ts = set(Tvals[0])
                Rs = set(Rvals[0])
                Us = Ts.union(Rs)
                if len(Ts.intersection(Rs)) == 0:
                    print 'Merging data with no intersection between R and T (%i, %s)'%(ch, dirname)
                elif len(Us) != max(len(Ts), len(Rs)):
                    print 'Merging data with no complete set between R and T (%i, %s)'%(ch, dirname)
                else:
                    print 'Merging data with partial overlap between R and T (%i, %s)'%(ch, dirname)
                # make sure the values are in increasing time order
                Tvals = Tvals[:,Tvals[0].argsort()]
                Rvals = Rvals[:,Rvals[0].argsort()]
                Tn = Tvals.shape[1]
                Rn = Rvals.shape[1]
                ar = []
                j = k = 0
                while j<Tn or k<Rn:
                    if j == Tn:
                        ar.append([Rvals[0, k], np.nan, Rvals[1, k]])
                        k += 1
                        continue
                    if k == Rn:
                        ar.append([Tvals[0, j], Tvals[1, j], np.nan])
                        j += 1
                        continue
                    ti = Tvals[0,j]
                    tj = Rvals[0,k]
                    if ti == tj:
                        ar.append([ti, Tvals[1, j], Rvals[1, k]])
                        j += 1
                        k += 1
                    elif ti < tj:
                        ar.append([ti, Tvals[1, j], np.nan])
                        j += 1
                    elif ti > tj:
                        ar.append([tj, np.nan, Rvals[1, k]])
                        k += 1
                results[i] = np.concatenate((results[i], np.array(ar)))
    results = [r.T for r in results]
    if merge_if_possible:
        for i in range(len(channels)-1):
            if results[i+1].shape != results[0].shape or np.all(results[i+1][0] != results[0][0]):
                print 'WARNING: unable to merge the data. Returning a list instead of a numpy array.'
                break
        else:
            # did not break so all times are the same
            merged = np.empty((1+2*len(channels), results[0].shape[1]), dtype=results[0].dtype)
            merged[0] = results[0][0]
            for i in range(len(channels)):
                j = 1 + 2*i
                merged[j:j+2] = results[i][1:]
            results = merged
    return results


def find_index_closest(data, search_values, already_sorted=False):
    """
    This function finds the index of data closest the the values in search_values
    It does the equivalent of
        ret = []
        for v in search_values:
            ret.append( np.abs(data-v).argmin() )
        ret = np.array(ret)
    but is much faster when data is large.
    If you are sure your data is already sorted, you can skip
    a sorting step by setting already_sorted=True.
    To find the actual minimum values use:
      data[find_index_closest(data, search_values)]
    """
    data = np.asarray(data)
    search_values = np.asarray(search_values)
    if not already_sorted:
        sort_idx = data.argsort()
        data = data[sort_idx]
    N = len(data)
    idx = np.searchsorted(data, search_values, side='left')
    # Using left we know that the index returned points to a value that is
    # larger or equal to the requested search
    # We need to check the point to the left to see if it is closer.
    w = np.nonzero((idx != N)*(idx != 0))[0]
    if len(w):
        idxw = idx[w]
        df = np.abs(data[idxw] - search_values[w])
        df1 = np.abs(data[idxw-1] - search_values[w])
        w_closer = np.nonzero(df1 < df)[0]
        if len(w_closer):
            idx[w[w_closer]] -= 1
    # When index points to past the end of the array, take the last point
    w = np.nonzero(idx == N)[0]
    if len(w):
        idx[w] = N-1
    if not already_sorted:
        return sort_idx[idx]
    return idx

def find_closest_times(data_set, times_to_search_for, max_delta=60*10.):
    """
    The input is a list of ndarray or a single ndarray which has time has the first column.
    The return has the same structure as data_set but picks the points closest to where
    times_to_search_for is given (can be a single value or an array)
    The input can be the returned value from read_blueforsTlog.
    I describe the function using time but the data can be anything (just pick the closests match
    on the first column).
    max_delta, when not None, prints a warning if the closest point is ever farther than that.
    The default max_delta is 10 min.
    """
    ret_one = False
    single_search = False
    dmax = 0
    times_to_search_for = np.asarray(times_to_search_for)
    if len(times_to_search_for.shape) == 0:
        single_search = True
        times_to_search_for.shape = (1,)
    if isinstance(data_set, np.ndarray):
        ret_one = True
        data_set = [data_set]
    ret = []
    for ar in data_set:
        t = ar[0]
        idx = find_index_closest(t, times_to_search_for)
        if max_delta:
            dmax = max(dmax, np.abs(t[idx] - times_to_search_for).max())
        ar = ar[:, idx]
        if single_search:
            ar = ar[0]
        ret.append(ar)
    if max_delta:
        if dmax > max_delta:
            print 'WARNING: found values outside of requested range (max_delta found = %r)'%dmax
    if ret_one:
        return ret[0]
    return ret

def read_blueforsChannels(filename):
    """
    Reads a bluefors log filename that contains Channels state (valve on/off).
    Returns a list of (time, dict) tuples.
    Note that main status of PANEL is also produced upon restart of valve program when some valve is open.
    Power out or local lockout produces  all valves open.
    """
    v = read_bluefors(filename)
    d = [(t,dict(zip(s[1::2], map(lambda ss: bool(int(ss.strip())), s[2::2])))) for t,s in v]
    main_st = {1:'PROG', 4:'manual', 8:'PANEL ', 9:'GLITCH'}
    for i in range(len(v)):
        d[i][1]['main'] = main_st.get(int(v[i][1][0]), '!! UNKNOWN !!')
    return d

def read_blueforsStatus(filename):
    """
    Reads a bluefors log filename that contains Status information.
    Returns a list of (time, dict) tuples.
    """
    v = read_bluefors(filename)
    d = [(t,dict(zip(s[0::2], map(lambda ss: float(ss.strip()), s[1::2])))) for t,s in v]
    return d

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


def _filename_build_check(file_base, logdir, dirname, quiet=False, missing_ok=True):
    """ helper for filename building and checking) """
    if not isinstance(file_base, list):
        file_base = [file_base]
    for f in file_base:
        filename = os.path.join(logdir, dirname, f%dirname)
        if os.path.isfile(filename):
            return filename
    # did not find it.
    if missing_ok:
        if not quiet:
            print 'Skipping: %s'%filename
        return None
    return filename

def read_bluefors_all(start_date, stop_date=None, logdir='C:/BlueFors/Logs', flow=True, gauges=True, channels=False, missing_ok=True, quiet=False):
    """
    Reads bluefors log for flow, gauges and channels depending on the boolean values.
    Returns the arrays read in the order flow, gauges, channels. For emptry flow, gauges, returns None.
    start_date and stop_date are either epoch values (number of days since jan 1st 1970)
    or strings giving the date '20150921' '2015-09-21', '2015-9-21', '150921', '15-09-21',
    '15-9-21' or replace '-' with '/'
    if stop_day is None, then today's date is used.
    If start_date is an ndarray, it uses the minimum as start_date and maximum as stop_date.
    If start_date is a list, it is used directly.
    missing_ok, when True which is the default, just skip missing files without producing an exception (but prints it, unless quiet is True).
                It is always on for channels (and quiet is on for it also).
    """
    data_flow = []
    data_gauges = []
    data_channels = []
    if flow == gauges == channels == False:
        raise ValueError('At least one of flow, gauges or channels should be True.')
    filename_build_check = lambda file_base, quiet=quiet, missing_ok=missing_ok: _filename_build_check(file_base, logdir, dirname, quiet, missing_ok)
    for dirname in _read_bluefors_select(start_date, stop_date):
        if flow:
            filename = filename_build_check('Flowmeter %s.log')
            if filename is not None:
                data_flow.append(read_blueforsRTF(filename))
        if gauges:
            # It used to be Maxigauge, now it is maxigauge
            # These are not the same under case sensitive filesystems (like linux).
            filename = filename_build_check(['maxigauge %s.log', 'Maxigauge %s.log'])
            if filename is not None:
                data_gauges.append(read_blueforsGauges(filename))
        if channels:
            filename = filename_build_check('Channels %s.log', missing_ok=True, quiet=True)
            if filename is not None:
                data_channels += read_blueforsChannels(filename)
    ret = ()
    if flow:
        if len(data_flow):
            ret += (np.concatenate(data_flow, axis=1), )
        else:
            ret += (None,)
    if gauges:
        if len(data_gauges):
            ret += (np.concatenate(data_gauges, axis=1), )
        else:
            ret += (None,)
    if channels:
        ret += (data_channels, )
    if len(ret) == 1:
        ret = ret[0]
    return ret

#########################################################
# Read ICE oxford NI data files
#########################################################

_ICEoxford_n2i_default = dict(t4k=0, time_raw=1, htr2=2, htr1=3, t50k=4, t1k=7, pcirc=8, s1k=10, s4k=11, s50k=12,
                              nv1=13, pdump=21, dt=22) # dt is time since start of file in s.
#_ICEoxford_n2i_default = dict(t4k=0, time=1, htr2=2, htr1=3, t50k=4, mag_field=5, heat_ex_50k=6, t1k=7,
#                              pcirc=8, mag_current=9, s1k=10, s4k=11, s50k=12,
#                              nv1=13, nv2=14,
#                              s_raw_d4=15, s_raw_d5=16, s_raw_d1=17, s_raw_d2=18, s_raw_d3=19,
#                              heat_1k_ex=20, pdump=21, dt=22, out_current=23
#                              sample=24, tdynamic_heat_exchanger=25, sample2=26)

# The timestamp in the data is calculated incorrectly
# My guess is that they take the labview timestamp (seconds since 1904-01-01 00:00:00 UTC)
# and substract the unix epoch 1970-01-01 00:00:00 UTC, but they probably used
# the local timezone instead of the UTC one for the unix epoch.

class ICEoxford_Data(object):
    """
    d is full data array.
    filenames is the list of all filenames.
    filenames_clean is the list of non-empty files
    full_columns is the full name of the columns.
    show_full_columns returns the full_columns name with the index
    other names index a particular column.
    """
    def __init__(self, data, columns, filenames=None, filenames_clean=None, names2index=_ICEoxford_n2i_default, tz_offset=None):
        self.filenames = filenames
        self.filenames_clean = filenames_clean
        self.full_columns = columns
        if not isinstance(names2index, dict):
            names = names2index
            index = range(len(names))
            names2index = dict( zip(names, index) )
        self._names2index = names2index
        self.d = data
        # added them as (hidden) attribute so tab expansion can find them
        for n in names2index.iterkeys():
            setattr(self, n, None)
        if tz_offset is None:
            tz_offset = time.timezone
        self._timeoffset = tz_offset
    def __getattribute__(self, name):
        names2index = super(ICEoxford_Data, self).__getattribute__('_names2index')
        if name in names2index:
            d = super(ICEoxford_Data, self).__getattribute__('d')
            return d[names2index[name]]
        return super(ICEoxford_Data, self).__getattribute__(name)
    def show_full_columns(self):
        return list(enumerate(self.full_columns))
    @property
    def time(self):
        return self.time_raw + self._timeoffset

_full_columns = ["/'Data'/'4k Stage'",  "/'Data'/'Unix Timestamp'",  "/'Data'/'Heater 2'",  "/'Data'/'Heater 1'",
                 "/'Data'/'50k Stage'",  "/'Data'/'Magnetic Field'",  "/'Data'/'50k Heat Exchanger'",  "/'Data'/'1K pot'",
                 "/'Data'/'Circulation Pressure'", "/'Data'/'Magnet Current'", "/'Data'/'Raw C'",  "/'Data'/'Raw B'",
                 "/'Data'/'Raw A'", "/'Data'/'Needle Valve 1'", "/'Data'/'Needle Valve 2'", "/'Data'/'Raw D4'",
                 "/'Data'/'Raw D5'", "/'Data'/'Raw D1'", "/'Data'/'Raw D2'", "/'Data'/'Raw D3'", "/'Data'/'1k Heat Exchanger'",
                 "/'Data'/'Dump Pressure'", "/'Data'/'Elapsed (s)'", "/'Data'/'Output Current'", "/'Data'/'Sample'",
                 "/'Data'/'Dynamic Heat Exchanger'", "/'Data'/'Sample 2'"]

def read_iceoxford(filenames_or_glob, prepend=None, tz_offset=None):
    """ Read one or many files (either lists or globs)
    written by ICE oxford program (.tdms files).
    Returns a class will all the data concatenated and with
    names to access to the columns.
    preprend is prepended to all the filenames.
    tz_offset if None (default) will use the local timezone to fix the time
              otherwise, provide the value to add to time_raw to generate the time
              attribute
    """
    try:
        import nptdms
    except ImportError:
        raise RuntimeError('You need to install the nptdms module: pip install npTDMS')
    if not isinstance(filenames_or_glob, (list, tuple, np.ndarray)):
        filenames_or_glob = [filenames_or_glob]
    filelist = []
    for fglob in filenames_or_glob:
        if prepend is not None:
            fglob = os.path.join(prepend, fglob)
        fl = glob.glob(fglob)
        fl.sort()
        filelist.extend(fl)
    all_tdms = [nptdms.TdmsFile.read(f) for f in filelist]
    all_panda = [d.as_dataframe() for d in all_tdms]
    all_data = [d.to_numpy().T for d in all_panda]
    #Sanity checks
    all_columns = [d.columns.to_list() for d in all_panda]
    all_sel = [g!=[] for g in all_columns] # to remove empty files
    all_data_clean = [d for s, d in zip(all_sel,  all_data) if s]
    all_columns_clean = [d for s, d in zip(all_sel,  all_columns) if s]
    if not len(all_columns_clean):
        raise RuntimeError('All data files are empty.')
    c0 = all_columns_clean[0]
    if not all([c == c0  for c in all_columns_clean]):
            raise RuntimeError("The files don't have all the same data structure")
    if c0 != _full_columns:
        print "read_iceoxford: the full_columns name are not the expected ones. Column assignment is probably wrong."
    data = np.concatenate(all_data_clean, axis=-1)
    return ICEoxford_Data(data, c0, filelist, [f for s, f in zip(all_sel, filelist) if s], tz_offset=tz_offset)


#########################################################
# Conversion functions, time constants calcs
#########################################################

def dB2A(dB):
    """ Returns the amplitude ratio that corresponds to the input in dB
        see also: dB2P, A2dB, P2dB
    """
    return 10.**(dB/20.)

def A2dB(A):
    """ Returns the corresponding dB value for an amplitude ratio A
        see also: dB2A, dB2P, P2dB
    """
    return 20.*np.log10(A)

def dB2P(dB):
    """ Returns the power ratio that corresponds to the input in dB
        see also: dB2A, A2dB, P2dB
    """
    return 10.**(dB/10.)

def P2dB(P):
    """ Returns the corresponding dB value for a power ratio P
        see also: dB2A, dB2P, A2dB
    """
    return 10.*np.log10(P)


def rt2xy(r, phase=None, deg=True, cmplx=False, dB=True):
    """
    if phase is None, then, r is presume to have at least
    2 dimensions, the first one selecting between amplitude and phase
    The phase is in degrees unless deg=False then it is in radians
    r is in dB when dB=True, otherwise it is a linear scale
    It returns the amplitudes
    cmplx: when True it returns complex values instead of a an array with 2
            elements as the first dimension (in-phase, out-phase)
    See also: xy2rt
    """
    if phase is None:
        if len(r) != 2:
            raise ValueError('The first dimension of db needs to have 2 element when phase is not given')
        r, phase = r
    if dB:
        r = dB2A(r)
    if deg:
        phase = np.deg2rad(phase)
    if cmplx:
        return r*np.exp(1j*phase)
    x = r*np.cos(phase)
    y = r*np.sin(phase)
    return np.array([x,y])

def phase_unwrap(phase, deg=True, axis=-1):
    """ This removes large discontinuities in the phase. It is useful when
        many adjacent points have normally small changes of phase except when the
        phase wraps around (changes of 2 pi rad or 360 deg)
        axis: the axis (dimension) to operate on.
        deg: when True the phase is in degrees, otherwise it is in radians
        See also: phase_wrap, scipy.signal.detrend
    """
    if deg:
        phase = np.deg2rad(phase)
    phase = np.unwrap(phase, axis=axis)
    if deg:
        return np.rad2deg(phase)
    else:
        return phase

def phase_wrap(phase, deg=True):
    """ Returns the phase wrapped around.
        deg : when True the range is [-180, 180]
              when False the range is [-pi , pi]
        See also phase_unwrap
    """
    half = 180. if deg else np.pi
    full = 2*half
    return (phase + half)%full - half


def xy2rt(x, y=None, cmplx=False, deg=True, dB=True, unwrap=False):
    """
    Takes the incoming x,y data and returns the amplitude and
    the phase.
    dB: when True returns the amplitude in dB otherwise in linear scale
    deg: when True returns the phase in degrees, otherwise in radians
    cmplx: when True, the incoming x is presumed to be complex numbers
           z = x+1j*y
    unwrap: when True, applies phase_unwrap to the phase on the last dimension(axis)
    The return value will be a single array have 2 elements on the first dimension
    corresonding to db and phase.
    See also: rt2xy
    """
    if cmplx:
        z = x
    else:
        if y is None:
            if len(x) != 2:
                raise ValueError('The first dimension of x needs to have 2 element when y is not given')
            x, y = x
        z = x + 1j*y
    A = np.abs(z)
    if dB:
        A = A2dB(A)
    phase = np.angle(z, deg=deg)
    if unwrap:
        phase = phase_unwrap(phase, deg=deg)
    return np.array([A, phase])

def dBm2o(dbm, o='W', ro=50):
    """ This function converts an input amplitude in dBm
        to an output in o, which can be 'W' (default),
        'A', 'A2', 'V' or 'V2' for Watts, Amperes(RMS),
        A**2, Volts(RMS) or V**2.
        ro: is the impedance used to calculate the values
            for o='V', 'V2', 'A' or 'A2'
        If you prefer a different default you can do it like this:
            dBm2A = lambda x: dBm2o(x, o='A')
        See also: o2dBm
    """
    Pref = 1e-3 # reference power for dBm is 1 mW
    ro = ro*1. # make sure it is a float
    w = Pref * dB2P(dbm)
    if o == 'W':
        return w
    elif o == 'A':
        return np.sqrt(w/ro)
    elif o == 'A2':
        return w/ro
    elif o == 'V':
        return np.sqrt(w*ro)
    elif o == 'V2':
        return w*ro
    else:
        raise ValueError("o needs to be 'W', 'A', 'A2', 'V' or 'V2'")

def o2dBm(v, o='W', ro=50):
    """ This function converts an input amplitude in some units
        to an output in dBm.
        o: selects the incoming units. It can be 'W' (default,)
        'A', 'A2', 'V' or 'V2' for Watts, Amperes(RMS),
        A**2, Volts(RMS) or V**2.
        ro: is the impedance used to calculate the values
            for o='V', 'V2', 'A' or 'A2'
        If you prefer a different default you can do it like this:
            A2dBm = lambda x: o2dBm2(x, o='A')
        See also: dBm2o
    """
    Pref = 1e-3 # reference power for dBm is 1 mW
    ro = ro*1. # make sure it is a float
    if o == 'W':
        w = v
    elif o == 'V':
        w = v**2./ro
    elif o == 'V2':
        w = v/ro
    elif o == 'A':
        w = v**2.*ro
    elif o == 'A2':
        w = v*ro
    else:
        raise ValueError("o needs to be 'W', 'A' or 'V'")
    return 10.*np.log10(w/Pref)

def vswr2g(v):
    """
    Converts from a Voltage Standing Wave Ratio (VSWR) to the
    modulus of the reflection coefficient rho = |Gamma|:
          Gamma(S11) = (Z2-Z1)/(Z2+Z1)
     where Z1 is the incoming medium and Z2 is the medium producing the reflection.
    v should be >= 1.
    for rho = |Gamma|, then vswr = (1+rho)/(1-rho)
    where 0 <= rho <= 1
    You might also be interested in the return loss which is given by
       -20 log10(rho) (or -A2dB(abs(Gamma)))
       which is <= 0.
    See also: g2vswr, G2Z, Z2G
    """
    return (v-1.)/(v+1.)

def g2vswr(g):
    """
    Converts from the coefficient of reflection Gamma (S11) to
    the Voltage Standing Wave Ratio (VSWR).
           Gamma = (Z2-Z1)/(Z2+Z1).
     where Z1 is the incoming medium and Z2 is the medium producing the reflection.
    We have for rho = |Gamma|:
        0 <= rho <= 1.
    The VSWR is givent by
       VSWR = (1+rho)/(1-rho)
    and will be >= 1.
    You might also be interested in the return loss which is given by
       -20 log10(rho) (or -A2dB(abs(Gamma)))
       which range from -infinity to 0.
    See also: vswr2g, G2Z, Z2G
    """
    rho = np.abs(g)
    return (rho+1.)/(1.-rho)

def Z2G(Z1, Z2=None):
    """
    Converts from an impedance Z1, Z2 to a reflection coefficient
    Gamma (S11) = (Z2-Z1)/(Z2+Z1)
     where Z1 is the incoming medium and Z2 the medium producing the reflection.
    if Z2 is None, then Z1 is the ratio Z1/Z2
    See also: G2Z, vswr2g, g2vswr
    """
    if Z2 is None:
        Z2 = 1.
    Z1 *= 1. # make it a float
    return (Z2-Z1)/(Z2+Z1)

def G2Z(G, Z1=None, Z2=None):
    """
    Converts from a reflection coefficient Gamma (S11) to
    an impedance Z1 or Z2
        Gamma = (Z2-Z1)/(Z2+Z1)
     where Z1 is the incoming medium and Z2 the medium producing the reflection.
    if either Z1 or Z2 is given, then it returns the other one.
    If neither Z1 nor Z2 are given (they are both None),
    it returns the ration Z1/Z2
    if Z2 is None, then Z1 is the ratio Z1/Z2
    See also: Z2G, vswr2g, g2vswr
    """
    if Z1 is not None and Z2 is not None:
        raise ValueError('You cannot specify both Z1 and Z2.')
    G = np.asarray(G) # shows a divide by zero warning instead of raising one
    Z12 =  (-G+1.)/(1.+G)
    if Z2 is not None:
        return Z12*Z2
    elif Z1 is not None:
        return Z1/Z12
    else:
        return Z12

def filter_to_fraction(n_time_constant, n_filter=1):
    """
    Calculates the fraction of a step function that is obtained after
    waiting n_time_constant. It tends toward 1. (100% of stop change)
    n_time_constant is the number of time_constants (can be fractionnal, is unitless)
    n_filter is the number of filters (all using the same time_constants non-interacting
     (buffered in between each))

    See also the inverse function fraction_to_filter
    """
    t = n_time_constant * 1. # make sure n_time_constant is a float
    if n_time_constant <= 0:
        return 0.
    old = n_filter
    n_filter = int(n_filter) # makes sure n_filter is an integer
    if old != n_filter:
        print 'n_filter was not an integer (%r). Converted it to %i'%(old, n_filter)
    if n_filter <= 0 or n_filter > 100:
        raise ValueError('n_filter to be positive and non-zero (and not greater than 100)')
    et = np.exp(-t)
    if n_filter == 1:
        return 1.-et
    elif n_filter == 2:
        return 1.-et*(1.+t)
#    elif n_filter == 3:
#        return 1.-et*(1.+t+0.5*t**2)
#    elif n_filter == 4:
#        return 1.-et*(1.+t+0.5*t**2+t**3/6.)
    else:
        # general formula: 1-exp(-t)*( 1+t +t**2/2 + ... t**(n-1)/(n-1)!) )
        m = 1.
        tt = 1.
        for i in range(1, n_filter):
            tt *= t/i
            m += tt
        return 1.-et*m

def fraction_to_filter(frac=0.99, n_filter=1):
    """
    Calculates the number of time constants to wait to achieve the requested
    fractional change (frac) from a step function.
    n_filter is the number of filters (all using the same time_constants non-interacting
     (buffered in between each))

    See also the inverse function filter_to_fraction
    """
    if frac <= 0. or frac >= 1:
        raise ValueError('frac is out of range need 0 < frac < 1')
    if n_filter != int(n_filter):
        old = n_filter
        n_filter = int(n_filter)
        print 'n_filter was not an integer (%r). Converted it to %i'%(old, n_filter)
    if n_filter <= 0 or n_filter > 100:
        raise ValueError('n_filter to be positive and non-zero (and not greater than 100)')
    func = lambda x: filter_to_fraction(x, n_filter)-frac
    n_time = brentq_rootsolver(func, 0, 1000)
    return n_time

def tc_to_enbw_3dB(tc, order=1, enbw=True):
    """
    When enbw=True, uses the formula for the equivalent noise bandwidth
                    which is the max frequency for an absolutely abrupt filter
                    (transfer function is 1 below fc and 0 above)
                    which lets through the same noise power (for a white noise source)
    When enbw=False, uses the formula for the 3dB point.
    tc is the time constant.
    Note that these conversions are the same in reverse. So if you provide
    a enbw or 3dB frequency it returns the time constant
    """
    tcp = 2*np.pi*tc
    if enbw:
        # This is obtain from the integral of an RC filter
        # i.e.: integral_0^inf (1/(1+(2*pi*f*tc)**2)**order
        # since we need to integrate the power we take the square of the
        # absolute reponse of the filter (1/(1+R/Zc) = 1/(1+1j*2*pi*f*tc))
        return (1./tcp) * np.sqrt(np.pi)*gamma(order-0.5)/(2*gamma(order))
    else:
        # This is solving 1/2 = (1/(1+(2*pi*f*tc)**2)**order
        return np.sqrt(2.**(1./order) -1) / tcp
