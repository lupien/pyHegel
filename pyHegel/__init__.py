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
__version__ = '0.9.9'
__copyright__ = '2011-2015  Christian Lupien'

def start_pyHegel():
    """ This is the recommanded way to start pyHegel.
        It starts ipython in a standard way (pylab, autocall enabled,...)
        and then loads and initializes the pyHegel commands.

        If you later need access to the commands in a module:
            import pyHegel.commands as cmds
            cmds.get(somedevice)
        or
            from pyHegel.commands import *
            get(somedevice)
        or any other variants you want.
    """
    from . import main
    main.main_start()