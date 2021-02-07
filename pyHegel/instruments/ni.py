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

from ..ni_dstp import Dstp_Client, TimeStamp, DataNotPresent
from collections import OrderedDict
import time


# We need to handle varying configuration
# 1) The data server could be down then nothing will work (no connection possible)
# 2) The server is up but the data is not present or is initialized to be 0.
# 3) the server is up, data is present but not being updated (server keep alive works)
# 4) the server is up and the data is updated.
# 5) The data update was working but stops. The data should be uppdated every 0.5 s. So
#     detect when no data is coming in the last 10 s?
#     When no data comes in, return the previous one or an invalid value?
# 6) The server stops (either nicelly or not). Use is_connection_ok() to check.

# On open, help with default_room assignment
# Allow to start without immediatelly establishing a connection.
# Allow the user to decide if a failure is critical (exception) or to handle it by retrying in the future.

@register_instrument('UdeS', 'flowmeters')
class liquef_flow_meters(BaseInstrument):
    def __init__(self, default_room, *args, **kwargs):
        """
        default_room is the integer corresponding to the room to obtain the flow information.
        allow_reconnect keyword can be True (default), 'delay' or False (any error produces an exception)
          The delay option allow misconnection even during init while True requires a valid connection
          during instrument creation.
        you can use 0. Then list the options with get_rooms_list, and change it with the current_room device.
        You can overide the address and variable names with keywords arguments default_address, default_variable.
        """
        self._default_room = default_room
        self._dstp = None
        self._last_data = None
        self._variable_retry = 0
        self._connect_last_fail_n = 0
        self._connect_last_fail_time = 0
        self._variable_opened = False
        self._default_address = kwargs.pop('default_address', 'liquef.physique.usherbrooke.ca')
        self._default_variable = kwargs.pop('default_variable', 'flowmeters')
        self._allow_reconnect = kwargs.pop('allow_reconnect', True)
        self._ni_quiet_del = kwargs.pop('_ni_quiet_del', True) # use this for debugging
        super(liquef_flow_meters, self).__init__(*args, **kwargs)
        self._get_dstp(init=True)

    def _get_dstp_connection(self, init=False):
        if self._dstp is not None and self._dstp.is_connection_ok():
            return # we are good.
        self.close(_internal=True)
        self._variable_opened = False
        self._variable_retry = 0
        if self._allow_reconnect is False or (init and self._allow_reconnect is True):
            self._dstp = Dstp_Client(address=self._default_address, variable_path=self._default_variable, max_buf_entries=1, quiet_del=self._ni_quiet_del)
        else:
            # first wait at least 2s between attempts, then wait at leas 4, then 8 until 1024 (17.1 min) and keep that
            # spacing. We keep this spacing until we get the variable opened.
            max_time = 2.**min(self._connect_last_fail_n, 10)
            if time.time() - self._connect_last_fail_time < max_time:
                return
            try:
                self._dstp = Dstp_Client(address=self._default_address, variable_path=self._default_variable, max_buf_entries=1, quiet_del=self._ni_quiet_del)
            except Exception as e:
                if self._connect_last_fail_n == 0:
                    print self.perror("Failed to connect to %s server. Will keep trying."%self._default_address)
                self._connect_last_fail_n += 1
                self._connect_last_fail_time = time.time()
                self._dstp = None
    def _get_dstp_variable(self, init=False):
        if self._variable_opened:
            return
        if self._dstp is None:
            return
        if self._allow_reconnect is False or (init and self._allow_reconnect is True):
            self._dstp.proto_open_var()
            self._variable_opened = True
        else:
            try:
                self._dstp.proto_open_var()
            except DataNotPresent:
                self._variable_retry += 1
                # The data is not present and we can't create it. We have to wait until somebody creates it.
                if self._variable_retry == 1:
                    print self.perror('The data is not yet available (waiting for it to created). Will keep trying.')
                return
            except Exception as e:
                # something else went wrong (no permission, error writing to socket, no response)
                # reset the connection but keep limited retries.
                self.close(_internal=True)
            else:
                self._variable_opened = True
                self._connect_last_fail_n = 0
                self._connect_last_fail_time = 0
                self._dstp.get_next_data() # to absorb the initial value which could be old.


    def _get_dstp(self, init=False):
        self._get_dstp_connection(init=init)
        self._get_dstp_variable(init=init)
    def close(self, _internal=False):
        if self._dstp is not None:
            if self._variable_opened:
                try:
                    self._dstp.proto_close_var()
                except Exception as exc:
                    if not _internal:
                        print self.perror("Exception during close var: %s"%exc)
                self._variable_opened = False
                self._variable_retry = 0
            try:
                self._dstp.close(quiet=True)
            except Exception as exc:
                if not _internal:
                    print self.perror("Exception during close: %s"%exc)
            self._dstp = None
        if not _internal:
            # so that a next open forces an immediate reconnection attempt.
            self._connect_last_fail_n = 0
            self._connect_last_fail_time = 0
    def __del__(self):
        self.close()
        super(liquef_flow_meters, self).__del__()
    def get_last_data(self):
        self._get_dstp()
        if self._variable_opened:
            ret =  self._dstp.get_next_data()
            if ret is not None:
                if ret[0] != self._default_variable:
                    raise RuntimeError(self.perror('Unexpected data name.'))
                # if data is invalid, return None
                # It could be invalid if we are the first to connect to the server and we have
                # the right to create the variable. It then contains 0 as the value.
                try:
                    if len(ret[1]) < 19:
                        ret = None
                except TypeError:
                    ret = None
                self._last_data = ret
            else:
                last = self._last_data
                if last is not None:
                    if time.time() - last[3] < 10:
                        # we keep that last data as valid for 10s
                        ret = last
                    else:
                        self._last_data = None
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

