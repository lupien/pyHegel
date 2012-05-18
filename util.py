# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

"""
This module contains many utilities:
    merge_pdf
    savefig
    savefig_reset
    savefig_set_enable
    savefig_enabled
    merge_all
Note that savefig is initially disabled.
"""

try:
    from pyPdf import PdfFileWriter, PdfFileReader
    pyPdf_loaded = True
except ImportError:
    pyPdf_loaded = False
import pylab
    
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

