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

from __future__ import absolute_import

# Use version according to option 5 in https://packaging.python.org/en/latest/single_source_version.html

# make sure that new versions numbers compare properly when using
# pkg_resources.parse_version
__version__ = '1.1.0'
__copyright__ = '2011-2019  Christian Lupien'

def start_pyHegel():
    """ This is the recommanded way to start pyHegel.
        It starts ipython in a standard way (pylab, autocall enabled,...)
        and then loads and initializes the pyHegel commands.

        If the python session was started with command line arguments
        --console, it will try to start pyHegel in the Console program
        that comes with pythonxy. This is windows only.

        If you later need access to the commands in a module:
            import pyHegel.commands as cmds
            cmds.get(somedevice)
        or
            from pyHegel.commands import *
            get(somedevice)
        or any other variants you want.
    """
    import sys
    import os
    if os.name == 'nt' and len(sys.argv) == 2 and sys.argv[1] == '--console':
        start_console()
    else:
        from . import main
        main.main_start()

def start_console():
    from . import win_console_helper
    win_console_helper.start_console()
