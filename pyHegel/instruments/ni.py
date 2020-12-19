# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2020-2020  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

import numpy as np
from ..instruments_base import BaseInstrument,\
                            MemoryDevice,\
                            wait, ProxyMethod
from ..instruments_registry import register_instrument

from ..ni_dstp import Dstp_Client, TimeStamp
from collections import OrderedDict


# TODO handle disconnections

@register_instrument('UdeS', 'flowmeters')
class liquef_flow_meters(BaseInstrument):
    def __init__(self, default_room, *args, **kwargs):
        self._default_room = default_room
        self._dstp = self._get_dstp()
        self._last_data_time = 0.
        super(liquef_flow_meters, self).__init__(*args, **kwargs)
    def _get_dstp(self):
        dstp = Dstp_Client(address='liquef.physique.usherbrooke.ca', variable_path='flowmeters', max_buf_entries=1)
        dstp.proto_open_var()
        return dstp
    def _reset_dstp(self):
        if self._dstp is None:
            try:
                self._dstp = self._get_dstp()
                print 'Reconnected to NI dstp on liquef'
            except Exception as exc:
                print 'Unable to setup NI dstp communication to liquef. Exception: %s'%exc
    def close(self):
        self._dstp.proto_close_var()
        self._dstp.close()
    def __del__(self):
        self.close()
        super(liquef_flow_meters, self).__del__()
    def get_last_data(self):
        if self._dstp is not None:
            ret =  self._dstp.get_next_data()
            if ret is not None:
                if ret[0] != 'flowmeters':
                    raise RuntimeError(self.perror('Unexpected data name.'))
                self._last_data_time = ret[3]
        else:
            ret = None
        return ret
    def get_last_flows(self):
        ret = self.get_last_data()
        if ret is not None:
            return ret[1]
        return np.zeros(19)-1 # as of 2020-12-18 real data returns 19 values for Version 2.8
    def get_last_attrs(self):
        ret = self.get_last_data()
        if ret is not None:
            return ret[2]
        return OrderedDict([('Version', '0.0'), ('Temps', TimeStamp(0,0)), ('Message', 'No message.'),
                            ('Emplacements', np.array(['room %i'%i for i in range(19)])), ('Alarms', np.zeros(19, bool))])
    def get_last_flow(self, room):
        return self.get_last_flows()[room]
    def get_rooms_list(self):
        rooms = self.get_last_attrs()['Emplacements']
        return list(enumerate(rooms))
    def _current_config(self, dev_obj=None, options={}):
        base = ['rooms_list=%s'%self.get_rooms_list()]
        return base + self._conf_helper('current_room', 'flow', options)
    def _flow_getdev(self, room=None):
        """ Reads the flow from a particular room.
            room is the index that identifies the room. See get_rooms_list for the list.
                 when it is None (default), it will use the value in current_room.
            The units are m^3/hr of gas which is about 1.3 liters/hr of liquid Helium.
            A value of -1 is returned when there is a connection problem.
        """
        if room is None:
            room = self.current_room.get()
        else:
            self.current_room.set(room)
        return self.get_last_flow(room)
    def _create_devs(self):
        self.current_room = MemoryDevice(self._default_room)
        self._devwrap('flow')
        self.alias = self.flow
        # This needs to be last to complete creation
        super(liquef_flow_meters, self)._create_devs()
