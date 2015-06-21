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

from .. import config as _config
from .. import instruments_registry as _registry

from ..instruments_base import (visaInstrument, visaInstrumentAsync, visaAutoLoader,
                            BaseDevice, BaseInstrument, MemoryDevice, scpiDevice,
                            find_all_instruments)


# Call this after importing this module
# It is needed to prevent cyclic import problems:
#   logical and load_instruments use function in instruments_registry which
#   import this module.
def _populate_instruments():
    global logical, _loaded
    # logical is excluded from config.load_instruments because it needs to be loaded
    # first. Other devices depend on it.
    from . import logical

    # Now load all other instruments.*
    _loaded = _config.load_instruments(exclude=['logical'])


# This space will be filled up by config.load_instruments
