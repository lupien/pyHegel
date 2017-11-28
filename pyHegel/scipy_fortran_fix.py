# -*- coding: utf-8 -*-

# KeyboardInterrupt fixes from:
#   https://github.com/scipy/scipy/pull/3880
# by Christian Lupien (2014-12-18)

# prevent interference with KeyboardInterrupt on Windows
# due to Fortran libraries
# See stackoverflow for explanation:
# http://stackoverflow.com/questions/15457786/ctrl-c-crashes-python-after-importing-scipy-stats
#
# In newer versions of scipy (at least the one with anaconda 5.0.1 as of 2017-11-27)
# the scipy config files contains mkl_rt instead of mkl_blas.
# The code below does work when making the change but another option is available to prevent
# the fortran routines from setting the handler: set the environment variable FOR_DISABLE_CONSOLE_CTRL_HANDLER
# to TRUE
#  see https://software.intel.com/en-us/node/691984 (intel fortran 16.0 compiler, default console event handling)


from __future__ import absolute_import

import imp
import ctypes
import os

INSTALL = False

#dirname = os.path.dirname(scipy.__file__)
dirname = os.path.dirname(imp.find_module('scipy')[1])
dirname = imp.find_module('scipy')[1]
config_file = os.path.join(dirname, '__config__.py')

if os.path.exists(config_file):
    with open(config_file, 'rb') as fid:
        text = fid.read()
    if 'mkl_blas' in text:
        INSTALL = True
#    if 'mkl_rt' in text:
#        INSTALL = True

def handler(sig):
    try:
        import _thread
    except ImportError:
        import thread as _thread
    _thread.interrupt_main()
    return 1 # do not execute any other handlers.

def load_lib(name):
    """ Load a numpy dll by first trying a specific location, the
        uses the dll search path which is hopefully set correctly
        On my system the dlls are in C:\\Python27\\DLLs
    """
    try:
        ctypes.CDLL(os.path.join(basepath, 'core', name))
    except WindowsError:
        ctypes.CDLL(name)

def fix_problem():
    global basepath, routine
    # load numpy math and fortran libraries (but do not import numpy)
    basepath = imp.find_module('numpy')[1]

    #ctypes.CDLL(os.path.join(basepath, 'core', 'libmmd.dll'))
    #ctypes.CDLL(os.path.join(basepath, 'core', 'libifcoremd.dll'))
    load_lib('libmmd.dll')
    load_lib('libifcoremd.dll')

    # These are not needed but could be:
    # I found them with
    #  grep -ri SetConsoleCtrlHandler /c/Python27/DLLs
    #  grep -ri libiomp5md /c/Python27/Lib/site-packages/scipy
    #  grep -ri libiomp5md /c/Python27/Lib/site-packages/numpy
    #load_lib('libiomp5md.dll')
    #load_lib('svml_dispmd.dll')

    # install handler
    routine = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)(handler)

    ctypes.windll.kernel32.SetConsoleCtrlHandler(routine, 1)

def fix_problem_new(force=False):
    envvar = 'FOR_DISABLE_CONSOLE_CTRL_HANDLER'
    if not force:
        if envvar in os.environ:
            return
    os.environ[envvar] = 'TRUE'

if INSTALL:
    fix_problem()
else:
    fix_problem_new()
