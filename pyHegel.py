#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:
#
# Main program to start pyHegel
#  It replaces the older C version of Hegel

# You should start this script directly.
# It is possible to load it in ipython, however, fix_scipy is not applied
# so CTRL-C will end the program. (applying the fix would prevent program ending
# but time.sleep would still be unbreakable because ipython already loaded the time
# module).
# Under ipython, you need to use run -i, otherwise load does not add instruments
# in the correct global environment.
# if you need to access the commands in a script/import use: import pyHegel_cmds

def fix_scipy():
    """ This fixes a problem with scipy 0.14.0-7 from python(x,y) 2.7.6.1
        which uses the intel fortran compiler which changes the Interrupt handler.
        This makes import scipy.special, scipy.optimize exit python when ctrl-C is pressed.
        see: http://stackoverflow.com/questions/15457786/ctrl-c-crashes-python-after-importing-scipy-stats
             https://github.com/scipy/scipy/pull/3880
    """
    import os
    if os.name == 'nt':
        import scipy_fortran_fix

start_code = """
get_ipython().run_line_magic('pylab', 'qt')
import scipy
import scipy.constants
import scipy.constants as C

from pyHegel_cmds import *
_init_pyHegel_globals()
quiet_KeyboardInterrupt(True)
"""

# Note that importing pyHegel_cmds works if this script is executed from the python
# command line because it then adds this script directory to the import paths.
# Therefore it will probably not work if you start it under python and try
# to load the file with execfile(). It might work partially if you start it while
# the current working directory is the code one.

try:
    get_ipython # if this does not produce a NameError, we are running in an ipyhton shell
    # we usually get here because of a reset_pyHegel
    exec(start_code)
except NameError:
    # need to fix before importing IPython (which imports time...)
    fix_scipy()
    import IPython

    IPython.start_ipython(argv=['--matplotlib=qt', '--autocall=1', '--InteractiveShellApp.exec_lines=%s'%start_code.split('\n')])
    #IPython.start_ipython(argv=['--pylab=qt', '--autocall=1', '--InteractiveShellApp.exec_lines=%s'%start_code.split('\n')])
    # qt and qt4 are both Qt4Agg
    #TerminalIPythonApp.exec_lines is inherited from InteractiveShellApp.exec_lines

"""
Informations
we could use --pylab instead of --matplotlib, but I choose --matplotlib for better control
see the help of %pylab to see what it does. The code is in IPython.core.pylabtools.import_pylab
and it protects the result of %who from being contamianted by all those imports
The code is called from core.interactiveshell.enable_pylab()
which is called from core.magics.pylab pylab
and core.shellapp.InteractiveShellApp.init_gui_pylab

"from pylab import *" and "from matplotlib.pylab import *" are the same.
They "import numpy as np" and also "from numpy import *" and then
"from matplotlib.pyplot import *" and "import matplotlib.pyplot as plt" as well as
many other numpy and matplotlib sections.

We used the xy profile which executed (after starting pylab)
    import numpy
    import scipy
    from numpy import *
Then it started dated logger in .xy directory, but multiple terminal would merge into
the same file.
So the import_pylab ends up also loading numpy and  doing "from numpy import *"
after importing pylab. So it is the same as before except for scipy and logging.

Changes from IPython 2.1 vs 0.10
*   -pylab used to only "from matplotlib.pylab import *" not numpy but pylab did import numpy internally and still does
    It did not have %pylab or %matplotlib macros
    Now -pylab is deprecated. Use --pylab instead or %pylab interactivelly (well ipython
    recommends to use matplotlib and only import what is required)
    --pylab now also adds figsize, display and getfigs to the environment
*   autocall is now disabled by default (it used to be enabled.)
*   omit__names went from 0 (none) to 2 (omit names staring with _ whe using tab)
*   CTRL-L went from doing possible-completions to clear-screen
*   there is no longer a message cmdline option, nor a log option
*   the pylab imports do about the same things.
*   The configuration used to be loaded this way:
     The defaults are initialized in IPython/ipmaker.py
     rc files are loaded before executing the ipy_someprofile_conf.py
     ipythonrc-PROF or simply ipythonrc if not present or not using a profile
     ipy_system_conf
     ipy_profile_PROF (if rc file was not loaded only else ipy_profile_none)
     ipy_user_conf
    In our case the config loaded was $USER/_ipython/ipythonrc.ini (which is the same as the default IPython/UserConfig/ipythonrc) then
    IPython/Extensions/ipy_profile_xy.py (which executed xy.startup.run()) then
    $USER/_ipython/ipy_user_conf.py (which was the same as the default IPython/UserConfig/ipy_user_conf.py)
    Above, when I compare default settings, it is with respect to the result of those files.
*   CTRL-C behavior has changed
     pressing it does not save the current line (it was a bug when ipython was running the Qt handler)
     when Qt is running, it requires pressing it twice, otherwise you return to editing the line.
*   The history is saved in a database file, connected to the sessions and after each commands
    so badly ending a session (closing the window) will no longer loose the history.
    To read old history, use
       %history -l 100
       #read last session
       %history ~1/0-~/0
       %history ~10/1-~0/1000
    Therefore logging is no longer necessary. But can use %history -f some file
    or %logstart ...
*   The -i option to ipython did not change anything. It would always go into interactive mode.
*   the banner was shown after the external script was loaded
"""
