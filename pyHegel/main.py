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

#
# Main program to start pyHegel
#  It replaces the older C version of Hegel

# The routine below helps to start pyHegel in a proper ipython environment
# and then reload it when necessary.

# To properly fix the scipy CTRL-C problem (that CTRL-C ends the program)
# requires to first execute fix_scipy, then import IPython and scipy (any order).
# If IPython is loaded before fix_scipy, then CTRL-C ending programs is fixed
# however, it is no longer possible to stop time.sleep (becomes unbreakable)
# because IPython imports time (and normally installs a handler but fix_scipy
# later installs another handler that does not call any previously installed ones)
# The is a similar problem with starting within a pure python prompt since it also
# imports the time module.

# if you need to access the commands in a script/import import pyHegel.commands

from __future__ import absolute_import

def fix_scipy():
    """ This fixes a problem with scipy 0.14.0-7 from python(x,y) 2.7.6.1
        which uses the intel fortran compiler which changes the Interrupt handler.
        This makes import scipy.special, scipy.optimize exit python when ctrl-C is pressed.
        see: http://stackoverflow.com/questions/15457786/ctrl-c-crashes-python-after-importing-scipy-stats
             https://github.com/scipy/scipy/pull/3880
    """
    import os
    if os.name == 'nt':
        from . import scipy_fortran_fix


def get_parent_globals(n=2):
    """
    returns the globals dictionnary of the n th caller to this function
    n=0 would be this functions globals which is useless.
    n=1 would be the callers frame which is useless (it will return
         the same globals as the caller would get directly)
    """
    g = {}
    if n < 2:
        raise ValueError('n needs to be >= 1')
    from inspect import currentframe
    frame = currentframe()
    try:
        while n:
            frame = frame.f_back
            n -= 1
        g = frame.f_globals
    except AttributeError:
        # we reach here when frame is None which happens when we go past the
        # first ancestor
        g = None
        pass
    finally:
        del frame # this is to break cyclic references, see inspect doc
    return g


_base_start_code = """
import scipy
import scipy.constants
import scipy.constants as C

from pyHegel.commands import *
_init_pyHegel_globals()
"""

_start_code = """
get_ipython().run_line_magic('pylab', 'qt')
get_ipython().run_line_magic('autocall', '1') # smart
""" + _base_start_code + """
quiet_KeyboardInterrupt(True)
"""

def main_start():
    # we check if we are called from an ipython session
    # we detect the presence of a running ipython by get_ipython being present in the
    # caller (or caller of caller, if called from pyHegel.start_pyHegel, and so one...)
    # However this will not work if the get_ipython function has been deleted.
    n = 2
    g = get_parent_globals(n)
    while g != None:
        if g.has_key('get_ipython'):
            # execute start_code in the already running ipython session.
            #print 'Under ipython', n
            exec(_start_code, g)
            return
        n += 1
        g = get_parent_globals(n)
    #print 'Outside ipython', n
    # We are not running in under an ipython session, start one.
    # need to fix before importing IPython (which imports time...)
    fix_scipy()
    import IPython
    IPython.start_ipython(argv=['--matplotlib=qt', '--InteractiveShellApp.exec_lines=%s'%_start_code.split('\n')])
    #IPython.start_ipython(argv=['--matplotlib=qt', '--autocall=1', '--InteractiveShellApp.exec_lines=%s'%start_code.split('\n')])
    #IPython.start_ipython(argv=['--pylab=qt', '--autocall=1', '--InteractiveShellApp.exec_lines=%s'%start_code.split('\n')])
    # qt and qt4 are both Qt4Agg
    #TerminalIPythonApp.exec_lines is inherited from InteractiveShellApp.exec_lines



def reset_start(globals_env):
    """ You need to provide the global environment where the code will be executed
        you can obtain it from running globals() in the interactive env.
    """
    if globals_env.has_key('get_ipython'):
        exec(_start_code, globals_env)
    else:
        exec(_base_start_code, globals_env)




_light_code = """
from pyHegel.commands import *
_init_pyHegel_globals()
"""

def light_start(globals_env=None):
    """ Use this to start pyHegel in an already running session of
        ipython. By default, it will load all the pyHegel commands
        into the callers environment and initialize it properly.
        To fully work, your ipython session should be setup to
        display matplotlib graphics using qt(qt4) or qt5 gui.

        When globals_env is None, it uses the caller's frame globals
        for installing all the commands and initialisation, otherwise
        it uses the specified one.
    """
    if globals_env is None:
        globals_env = get_parent_globals()
    exec(_light_code, globals_env)


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
