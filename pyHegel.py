#!/usr/bin/ipython -i
# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:
#
# Programme principale pour remplacer Hegel
#

# In pythonxy version 2.7.2.0
#  The xy profiles imports numpy, scipy and from numpy *
#  It also sets the logging into ~\.xy
# Also the ipython pylab mode imports numpy, numpy as np
#  matplotlib, matplotlib.pylab as pylab and matplotlib.pyplot as plt

# We do it here again. ipython -pylab should have loaded it but
# in some situation it is disabled (option  -nopylab_import_all)
#  This imports: numpy *, numpy.fft *, numpy.random *, numpy.linalg *,
#                matplotlb.pyplot *, matplotlib.pyplot as plt, numpy as np
#                numpy.ma as ma
from matplotlib.pylab import *
# could also be from pylab import *

#import numpy as np # this is loaded by pylab
import os
import time
import sys

# If you start this from within ipython, you need to
# use run -i otherwise the global variable are not set properly
# so the load commands will not add instrument in the user environment

def _update_sys_path():
    # This will handle calling of the script in the following ways:
    #  python -i ./some/partial/path/pyHegel.py
    #  ipython ./some/partial/path/pyHegel.py
    #  ipython -i ./some/partial/path/pyHegel.py # in linux
    #    in ipython
    #     run ./some/partial/path/pyHegel
    #     run -i ./some/partial/path/pyHegel
    # But will not handle calling it this way
    #  execfile('./some/partial/path/pyHegel.py') # we assume that if execfile is used, that path is already set.
    #       actually if the variable _execfile_name exists (the user needs to define it), we use that
    #  from pyHegel import *   # for this to work, the path is already set
    if __name__ != '__main__':
        # importing pyHegel or execfile from a module
        return
    # Initialize assuming the python filename is the last argument.
    try:
        partial_path = _execfile_name
    except NameError:
        partial_path = sys.argv[-1] # for execfile this is left over from calling environment (can be empty)
    # Now check to see if it is another argument.
    for a in sys.argv:
        if a.lower().endswith('pyhegel.py'):
            partial_path = a
            break
    # cwd = os.getcwd()
    # partial_path = __file__ # This fails on windows for ipython ./some/partial/path/pyHegel
    # Make it a full path. (only already a full path when run under ipython -i in linux)
    full_exec_path = os.path.abspath(partial_path)
    # sys.path[0] for the running script is set properly, but it is not passed
    #  to the ipython session (same effect for run)
    full_path = os.path.dirname(full_exec_path)
    # ipython adds to sys.path the path to the executable when running a script
    # but strips it before returning control to the use (whether it is starting
    # from os command line or using run).
    # So we always insert a copy of the fullpath even if it is already there, because
    # ipython tends to remove one from the list after running a script
    # and this function will probably be executed only once.
    if full_path not in sys.path:
        sys.path.insert(1, full_path) # Insert after element 0
    else:
        sys.path.insert(2, full_path) # Insert after element 1, which is '' for ipython, element 0 is executable path that is stripped.
    return (full_exec_path, full_path)

try:
    _sys_path_modified  # already updated path.
except:
    _sys_path_modified = _update_sys_path()


from pyHegel_cmds import *

_init_pyHegel_globals()

quiet_KeyboardInterrupt(True)

