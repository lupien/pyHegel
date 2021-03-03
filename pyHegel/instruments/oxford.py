# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2011-2020  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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
import time
import re


from ..instruments_base import visaInstrument,\
                            BaseDevice, scpiDevice, MemoryDevice,\
                            float_as_fixed,\
                            visa_wrap, locked_calling, wait, ProxyMethod,\
                            resource_info, _general_check, release_lock_context,\
                            mainStatusLine, _delayed_signal_context_manager
from ..types import dict_improved
from ..instruments_registry import register_instrument, register_usb_name, register_idn_alias

from .logical import ScalingDevice

#register_idn_alias('Oxfortd instruments', '???')


float_fix1 = float_as_fixed('%.1f')
float_fix3 = float_as_fixed('%.3f')
float_fix4 = float_as_fixed('%.4f')
float_fix6 = float_as_fixed('%.6f')


#######################################################
##    Oxford Instruments IPS 120-10 magnet power supply
#######################################################

# When turning psh on it can be in fault for a short time. when going off it can show persistent not installed.

# immediately after pause, it can still show sweeping.
# immediately after to sweep, it can also show hold

# When ramping, it is not possible to set the switch (even if it is on and we set it to on.)

# The instrument seem to have a bit of space on its read buffer. So it can handle
# a few short writes before overflow. This is important because the instrument
# does not handle the operation when a key is pressed.
# So my handling for those key presses is to wait and retry the read.
# But if someone breaks, the buffer will need to be emptied. So I add a new command (and bad)
# command to be able to find out when the buffer as actually been empty.

class OxfordError(RuntimeError):
    """ Base error for Oxford communication """
class OxfordLocalError(OxfordError):
    """ This error is generated when the magnet is in local mode which breaks some commands """
class OxfordTimeoutError(OxfordError):
    """ This error is raised on communication timeout. Most common when a user holds a key
        down on the instrument """

def _ramp_setdev_factory(isTesla):
    def _ramp_setdev(self, val, return_persistent='auto', wait=None, quiet=True, no_wait_end=False):
        """ Goes to the requested setpoint and then waits until it is reached.
            After the instrument says we have reached the setpoint, we wait for the
            duration set by ramp_wait_after (in s).
            return_persistent can be True (always), False (never) or 'auto' (the default)
                              which returns to state from start of ramp.
            wait can be used to set a wait time (in s) after the ramp. It overrides ramp_wait_after.
            no_wait_end when True, will skip waiting for the ramp to finish and return immediately after
                      starting the ramp. Useful for record sequence. This will not work when changing sign.
            When going to persistence it waits persistent_wait_before before cooling the switch.

            When using get, returns the magnet %s.
        """
        def print_if(s):
            if not quiet:
                print s
        ps_installed = self.status.getcache().pers_switch_installed
        if wait is None:
            wait = self.ramp_wait_after.getcache()
        if ps_installed:
            # Go out of persistent (turn persistent switch on)
            prev_switch_en = self.do_persistent(to_pers=False, quiet=quiet, isTesla=isTesla)
            # Now change the field
            print_if('Ramping...')
            if return_persistent == True or (return_persistent == 'auto' and not prev_switch_en):
                self._do_ramp(val, self.psh_wait_before.getcache(), isTesla=isTesla, no_wait_end=no_wait_end)
                if no_wait_end:
                    return
                self.do_persistent(to_pers=True, quiet=quiet, extra_wait=wait, isTesla=isTesla)
            else:
                self._do_ramp(val, wait, isTesla=isTesla, no_wait_end=no_wait_end)
        else: # no persistent switch installed
            print_if('Ramping...')
            self._do_ramp(val, wait, isTesla=isTesla, no_wait_end=no_wait_end)
    extra = 'field' if isTesla else 'current'
    _ramp_setdev.__doc__ = _ramp_setdev.__doc__%extra
    return _ramp_setdev

#@register_instrument('OXFORD', 'IPS120-10', '1996/3.07')
@register_instrument('OXFORD', 'IPS120-10')
class oxford_ips120_10(visaInstrument):
    """\
    This is the driver of the Oxford instruments IPS 120-10 magnet power supply
    Useful devices:
        ramp_current
        ramp_field_T
        ramp_field_kG
        current
        current_magnet
        field_T
        field_kG
        volt
        voltage
        current_target
        field_target_T
        field_target_kG
        ramp_rate_current_min
        ramp_rate_current_s
        ramp_rate_field_T_min
        ramp_rate_field_T_s
        ramp_rate_field_kG_min
        ramp_rate_field_kG_s
    Useful methods:
        hold (to pause the sweep)
        control_mode  (to put instrument in remote)
        clear_buffers
    It is recommended to lock the instrument in remote so a user will not make it go to local
    and break the sweep.

    Note that for changing parameters, the instrument must be placed in remote control.
    The field target resolution might be larger than the current target resolution for
    magnets with coil constant >0.1 T/A. (The internal resolution might be a little larger
    than the one available through the remote interface.)
    """
    _passwd_check = "IknowWhatIamDoing"
    def __init__(self, visa_addr, isobus=None, psh_time=30, psh_wait_before=60,
                 allow_local_override=True, *args, **kwargs):
        """\
        psh_time is the wait time after heating or cooling the persistent switch heater before
                 allowing a change in current. If a single value is given, it is used for both.
                 If a tuple of 2 values is given they are used as (heat_time, cool_time).
        psh_wait_before is the value to wait after ramping before going into persistent mode
            automatically.
        Set the isobus, when multiple instruments are connected together.
        When connecting with GPIB, the primary instrument (with gpib) always has isobus address 0.
        allow_local_override when True (default) commands that require control to be set at remote
                 to work, will set the control to remote if needed. Otherwise an exception is raised.
        """
        rsrc_info = resource_info(visa_addr)
        if rsrc_info.interface_type == visa_wrap.constants.InterfaceType.asrl:
            baud_rate = kwargs.pop('baud_rate', 9600)
            parity = kwargs.pop('parity', visa_wrap.constants.Parity.space)
            data_bits = kwargs.pop('data_bits', 7)
            stop_bits = kwargs.pop('stop_bits', visa_wrap.constants.StopBits.two)
            kwargs['baud_rate'] = baud_rate
            kwargs['parity'] = parity
            kwargs['data_bits'] = data_bits
            kwargs['stop_bits'] = stop_bits
        if not isinstance(psh_time, (tuple, list, np.ndarray)):
            psh_time = (psh_time, psh_time)
        self._psh_time_heat, self._psh_time_cool = psh_time
        self._psh_wait_before = psh_wait_before
        self._orig_target_cache = None
        self._isobus_num = isobus
        self._allow_local_override = allow_local_override
        self._last_read_exception_timeout = False
        #kwargs['skip_id_test'] = True
        kwargs['read_termination'] = '\r'
        kwargs['write_termination'] = '\r'
        self._last_errors = []
        super(oxford_ips120_10, self).__init__(visa_addr, *args, **kwargs)
        self._extra_create_dev()

    def _isobus_helper(self, isobus=None):
        ret = ''
        if isobus is False:
            return ret
        if isobus is None:
            isobus = self._isobus_num
        if isobus is not None:
            ret = '@%i'%isobus
        return ret

    @locked_calling
    def clear_buffers(self, check=True, isobus=None):
        """ This clears the communication buffers.
            Necessary after a timeout caused by a button being pressed
            on the instrument.
        """
        #print 'CLEAR'
        # for gpib could use self.visa.clear()
        # However I can hang the instrument communication when I do that.
        # And for serial that does not work.
        prev_timeout = self.set_timeout
        last = None
        self.write('BAD99', no_read=True, no_clear=True)
        iso = self._isobus_helper(isobus)
        check_val = '?' + iso + 'BAD99'
        self.set_timeout = 0.3
        try:
            while True:
                # read until we get a timeout.
                # timeout should mean we ran out of things to read
                # but it can also mean a button is pressed on the instrument
                # so it has not returned anything yet.
                try:
                    while True:
                        last = self.read(retry_on_timeout=False)
                except OxfordTimeoutError:
                    self._last_read_exception_timeout = False
                if check:
                    if last is not None and last == check_val:
                        break
                else:
                    break
        finally:
            pass
            self.set_timeout = prev_timeout

    def init(self, full=False):
        if full:
            self.clear_buffers()
            status = self.status.get()
            if status.locrem == 'local locked':
                print 'Unlocking'
                self.control_mode(remote=False, locked=False)

    def control_remotelocal(self, *args, **kwargs):
        raise NotImplementedError

    def clear(self, *args, **kwargs):
        raise NotImplementedError

    @locked_calling
    def idn(self):
        ret = self.ask('V')
        # should return: 'IPS120-10  Version 3.07  (c) OXFORD 1996'
        #  the separator is multiple spaces
        model, vers_str, vers, copyright, vendor, date = ret.split()
        if vers_str != 'Version' or copyright != '(c)':
            raise RuntimeError('Unexpected words in version string')
        return '%s,%s,%s,%s'%(vendor, model, 'xxx', '%s/%s'%(date,vers))

    @locked_calling
    def write(self, val, termination='default', isobus=None, quiet=False, no_read=False, no_clear=False):
        """ quiet tells the instrument not to reply
            isobus can be a number, None (to use instrument isobus) or False to override
             the instrument isobus and use None.
        """
        if not no_clear and self._last_read_exception_timeout:
            print 'Clearing buffers!'
            self.clear_buffers(isobus=isobus)
        iso = self._isobus_helper(isobus)
        val = iso + val
        if quiet:
            if quiet != 'skip':
                val = '$' + val
            super(oxford_ips120_10, self).write(val, termination=termination)
        elif no_read:
            if no_read == 'ask':
                # This is to protect agains a CRTL-C between write and read
                self._last_read_exception_timeout = True
            super(oxford_ips120_10, self).write(val, termination=termination)
        else:
            i = 0
            while i<2:
                i += 1
                ret = self.ask(val, skip_error_handling=True, isobus=False)
                if ret.startswith('?'):
                    if self.status.get().locrem.startswith('local'):
                        if self._allow_local_override:
                            self.control_mode(remote=True)
                            continue
                        else:
                            raise OxfordLocalError(self.perror('Instrument is in Local. Should be in Remote.'))
                    self._last_errors.append(ret)
                    raise RuntimeError('Command failed: %s'%ret)
                else:
                    break

    @locked_calling
    def ask(self, question, raw=False, chunk_size=None, isobus=None, skip_error_handling=False, retry_on_timeout=True, no_clear=False):
        """
        Does write then read.
        With raw=True, replaces read with a read_raw.
        This is needed when dealing with binary data. The
        base read strips newlines from the end always.
        """
        # I would normally used the _delayed_signal_context_manager here
        # But because read can loop (too handle instrument keypress),
        # we do not use the manager here to allow KeyboardInterrupt to work.
        # If we get random ? responses (because of unstable serial),
        #  Could implement some retry attempts here.
        #  It would deal with both basic writes and general ask.
        # Enable this to force clearing the buffers if some CTRL-C between write and read.
        self.write(question, no_read='ask', isobus=isobus)
        ret = self.read(raw=raw, chunk_size=chunk_size, retry_on_timeout=retry_on_timeout)
        if not skip_error_handling and ret.startswith('?'):
            self._last_errors.append(ret)
            raise RuntimeError('Request failed: %s'%ret)
        return ret

    @locked_calling
    def read(self, raw=False, count=None, chunk_size=None, timeout_check=True, retry_on_timeout=True):
        repeats = 0
        with mainStatusLine.new(priority=10, timed=True) as progress:
            while True:
                try:
                    #print 'Reading %i'%repeats
                    ret = super(oxford_ips120_10, self).read(raw=raw, count=count, chunk_size=chunk_size)
                    self._last_read_exception_timeout = False
                    return ret
                except visa_wrap.VisaIOError as exc:
                    if timeout_check and exc.error_code == visa_wrap.constants.StatusCode.error_timeout:
                        self._last_read_exception_timeout = True
                        if retry_on_timeout:
                            repeats += 1
                            progress('Repeating read (possible key pressed on instrument) #%i'%repeats)
                            wait(0.1) # to allow updating graphics
                            continue
                        else:
                            raise OxfordTimeoutError(self.perror('The instrument timed-out. It might be because of a button press on the instrument.'))
                    raise

    def _current_config(self, dev_obj=None, options={}):
        base = self._conf_helper('field_T', 'field_target_T', 'current_magnet', 'current_target',
                                 'voltage', 'voltage_limit', 'ramp_rate_field_T_min',
                                 'field_trip_T', 'lead_resistance_mOhm', 'magnet_inductance_H',
                                 'persistent_heater_current_mA',
                                 'status', 'psh_time_cool', 'psh_time_heat', 'psh_wait_before')
        base += ['isobus_num=%s'%self._isobus_num]
        return base + self._conf_helper(options)
    def get_error(self):
        if self._last_errors:
            return self._last_errors.pop()
        else:
            return 'No error.'

    def set_activity(self, act):
        acts = {'hold':0, 'to setpoint':1, 'to zero':2, 'clamp':4}
        if act not in acts:
            raise ValueError('Invalid activity. Needs to be one of %s'%acts.keys())
        self.write('A%d'%acts[act])

    def set_persistent(self, enable, force=False, password=None):
        if enable:
            if force and self._check_password(password=password):
                self.write('H2')
            else:
                self.write('H1')
        else:
            self.write('H0')
    set_persistent.__doc__ = """\
        To enable the persistent switch heater.
        To override the security checks, use the force option and
        provide the password ('%s')"""%_passwd_check

    def hold(self):
        """ pauses the sweep """
        self.set_activity('hold')

    def _check_password(self, password, dev=None):
        if dev is not None:
            password = dev._check_cache['kwarg']['password']
        if password != self._passwd_check:
            raise ValueError('Invalid password.')

    def _current_magnet_getdev(self):
        pers = self.status.get().pers_switch
        if pers.startswith('off'):
            return self.current_persistent.get()
        else:
            return self.current.get()

    def _field_T_getdev(self):
        """ Field in magnet even in persistent mode. """
        pers = self.status.get().pers_switch
        if pers.startswith('off'):
            return self.field_persistent_T.get()
        else:
            return self.field_raw_T.get()

    @locked_calling
    def _extra_create_dev(self):
        scale_kG = 10.
        self.field_target_kG = ScalingDevice(self.field_target_T, scale_kG, quiet_del=True)
        self.field_kG = ScalingDevice(self.field_T, scale_kG, quiet_del=True, doc='Field in magnet (even in persistent mode)')
        self.ramp_rate_current_s = ScalingDevice(self.ramp_rate_current_min, 1./60, quiet_del=True, doc='In A/s')
        self.ramp_rate_field_T_s = ScalingDevice(self.ramp_rate_field_T_min, 1./60, quiet_del=True, doc='In T/s')
        self.ramp_rate_field_kG_s = ScalingDevice(self.ramp_rate_field_T_min, scale_kG/60, quiet_del=True, doc='In kG/s')
        self.ramp_rate_field_kG_min = ScalingDevice(self.ramp_rate_field_T_min, scale_kG, quiet_del=True, doc='In kG/s')
        self.ramp_field_kG = ScalingDevice(self.ramp_field_T, scale_kG, quiet_del=True, doc='same options as for ramp_field_T.\n')
        self._create_devs_helper() # to get logical devices return proper name (not name_not_found)

    def _get_states(self):
        """ returns one of:
              'quench' (for any errors)
              'paused'
              'ramping'
        """
        state = self.status.get()
        if state.abnormal:
            return 'quench'
        if state.ramp == 'at rest':
            return 'paused'
        return 'ramping'

    def is_ramping(self, param_dict=None):
        """ Returns True when the magnet is ramping the field. Can be used for the sequencer. """
        return self._get_states() in ['ramping']
    def is_stable(self, param_dict=None):
        """ Returns True when the magnet is not ramping. Can be used for the sequencer. """
        return self._get_states() in ['paused']


    def _ramping_helper(self, stay_states, end_states=None, extra_wait=None, isTesla=True):
        if isTesla:
            target = self.field_target_T
            unit = 'T'
            reading = self.field_raw_T
        else:
            target = self.current_target
            unit = 'A'
            reading = self.current
        wait(0.2) # wait some time to allow previous change to affect the _get_states results.
        to = time.time()
        switch_time = 0.
        just_wait = False
        if stay_states == 'cooling':
            switch_time = self.psh_time_cool.get()
            just_wait = True
            prog_base = 'Magnet Cooling switch: {time}/%.1f'%switch_time
        elif stay_states == 'warming':
            switch_time = self.psh_time_heat.get()
            just_wait = True
            prog_base = 'Magnet Heating switch: {time}/%.1f'%switch_time
        else: # ramping
            if self.status.get().activity == 'to setpoint':
                prog_base = 'Magnet Ramping {current:.3f}/%.3f %s'%(target.getcache(), unit)
            else:
                prog_base = 'Magnet Ramping {current:.3f}/0 %s'%unit

        if isinstance(stay_states, basestring):
            stay_states = [stay_states]
        with release_lock_context(self):
            with mainStatusLine.new(priority=10, timed=True) as progress:
                if just_wait:
                    waited = 0.
                    while waited < switch_time:
                        w = max(0.1, switch_time-waited)
                        wait(w)
                        waited = time.time() - to
                        progress(prog_base.format(current=reading.get(), time=waited))
                else:
                    while self._get_states() in stay_states:
                        wait(.1)
                        progress(prog_base.format(current=reading.get(), time=time.time()-to))
            if self._get_states() == 'quench':
                raise RuntimeError(self.perror('The magnet QUENCHED!!! (or some other error, see get_error_status'))
            if extra_wait:
                wait(extra_wait, progress_base='Magnet wait')
        if end_states is not None:
            if isinstance(end_states, basestring):
                end_states = [end_states]
            if self._get_states() not in end_states:
                raise RuntimeError(self.perror('The magnet state did not change to %s as expected'%end_states))

    @locked_calling
    def do_persistent(self, to_pers, quiet=True, extra_wait=None, isTesla=True):
        """
        This function goes in/out of persistent mode (inverse of activating the persistent switch heater).
        to_pers to True to go into persistent mode (turn persistent switch off, ramp to zero and leave magnet energized)
                   False to go out of persistent mode (reenergize leads and turn persistent switch on)
        It returns the previous state of the persistent switch.
        """
        def print_if(s):
            if not quiet:
                print s
        status = self.status.get()
        if not status.pers_switch_installed:
            return True
        if isTesla:
            target = self.field_target_T
            reading = self.field_raw_T
            pers_reading = self.field_persistent_T
        else:
            target = self.current_target
            reading = self.current
            pers_reading = self.current_persistent
        state = self._get_states()
        if state in ['ramping']:
            raise RuntimeError(self.perror('Magnet is ramping. Stop that before changing the persistent state.'))
        if state in ['quench']:
            raise RuntimeError(self.perror('The magnet QUENCHED!!! (or some other error, see get_error, status'))
        orig_switch_en = status.pers_switch
        if orig_switch_en not in ['off @zero', 'on', 'off @field']:
            raise RuntimeError(self.perror('persistent switch is in a fault.'))
        orig_switch_en = orig_switch_en == 'on'
        self.set_activity('hold')
        if to_pers:
            if orig_switch_en:
                # switch is active
                print_if('Turning persistent switch off and waiting for cooling...')
                self.set_persistent(False)
                self._ramping_helper('cooling', isTesla=isTesla)
            print_if('Ramping to zero ...')
            self.set_activity('to zero')
            self._ramping_helper('ramping', 'paused', extra_wait, isTesla=isTesla)
        else: # go out of persistence
            if not orig_switch_en:
                pers_target = pers_reading.get()
                cur = reading.get()
                if cur != pers_target:
                    # should be here when 'off @field' but not when 'off @zero'
                    print_if('Ramping to previous target ...')
                    target.set(pers_target)
                    self.set_activity('to setpoint')
                    # The ramp is fast but still wait and extra 5 s for stability before pausing.
                    self._ramping_helper('ramping', 'paused', 5., isTesla=isTesla)
                    self.set_activity('hold')
                print_if('Turning persistent switch on and waiting for heating...')
                self.set_persistent(True)
                self._ramping_helper('warming', None, extra_wait, isTesla=isTesla)
                if self.status.get().pers_switch not in ['off @zero', 'on', 'off @field']:
                    raise RuntimeError(self.perror('persistent switch is in a fault.'))
        return orig_switch_en

    def _do_ramp(self, current_target, wait_time, isTesla=True, no_wait_end=False):
        if current_target == 0:
            self.set_activity('to zero')
        else:
            self.set_activity('hold')
            if isTesla:
                self.field_target_T.set(current_target)
            else:
                self.current_target.set(current_target)
            self.set_activity('to setpoint')
        if no_wait_end:
            wait(0.2) # wait some time to allow previous change to affect the _get_states results.
            return
        self._ramping_helper('ramping', 'paused', wait_time, isTesla=isTesla)

    def _ramp_current_checkdev(self, val, return_persistent='auto', wait=None, quiet=True, no_wait_end=False):
        if return_persistent not in [True, False, 'auto']:
            raise ValueError(self.perror("Invalid return_persistent option. Should be True, False or 'auto'"))
        BaseDevice._checkdev(self.ramp_current, val)

    def _ramp_field_T_checkdev(self, val, return_persistent='auto', wait=None, quiet=True, no_wait_end=False):
        if return_persistent not in [True, False, 'auto']:
            raise ValueError(self.perror("Invalid return_persistent option. Should be True, False or 'auto'"))
        BaseDevice._checkdev(self.ramp_field_T, val)

    _ramp_current_setdev = _ramp_setdev_factory(False)
    _ramp_field_T_setdev = _ramp_setdev_factory(True)

    def _ramp_current_getdev(self, return_persistent='auto', wait=None, quiet=True, no_wait_end=False):
        # All the options are there to absorb the parameters on setget.
        return self.current_magnet.get()

    def _ramp_field_T_getdev(self, return_persistent='auto', wait=None, quiet=True, no_wait_end=False):
        # All the options are there to absorb the parameters on setget.
        return self.field_T.get()

    def _status_getdev(self, full=False):
        """\
        From ramp, 'sweep limiting' should be displayed when the persistent switch heater is off.
                   otherwise it should be 'sweeping' unless the rate is to fast then it is
                   'sweeping, sweep limiting'
        full set to True, adds polarity information (which is not normally required)
        """
        ret = self.ask('X')
        parse = re.match(r'^X(\d)(\d)A(\d)C(\d)H(\d)M(\d)(\d)P(\d)(\d)$', ret)
        if parse is None:
            raise RuntimeError('Invalid return value for status')
        Xm, Xn, A, C, H, Mm, Mn, Pm, Pn = [int(p) for p in parse.groups()]
        locrem = (['local locked', 'remote locked', 'local unlocked', 'remote unlocked'] +['Auto-Run-Down']*4)[C]
        remote = bool(C&1)
        locked = not bool(C&2)
        autorundown = bool(C&4)
        # I have seen 4, 6 when turning off the heater.
        pers_switch_installed = H!=8
        pers_switch = {0:'off @zero', 1:'on', 2:'off @field', 4:'heater fault off', 5:'heater fault', 6:'heater fault @field',  8:'no switch fitted'}[H]
        activity = ['hold', 'to setpoint', 'to zero', 'xxx', 'clamped'][A]
        display_T = bool(Mm&1)
        ramp_rate_slow = bool(Mm&4)
        ramp = ['at rest', 'sweeping', 'sweep limiting', 'sweeping, sweep limiting'][Mn]
        system = []
        limits = []
        if Xm&1:
            system.append('Quenched')
        if Xm&2:
            system.append('Over Heated')
        if Xm&4:
            system.append('Warming up')
        if Xm&8:
            system.append('Fault')
        if Xn&1:
            limits.append('On +V limit')
        if Xn&2:
            limits.append('On -V limit')
        if Xn&4:
            limits.append('outside -I limit')
        if Xn&8:
            limits.append('outside +I limit')
        if len(system):
            system = ','.join(system)
        else:
            system = 'Normal'
        if len(limits):
            limits = ','.join(limits)
        else:
            limits = 'Normal'
        quenched = bool(Xm&1)
        abnormal = system != 'Normal' or  limits != 'Normal' or autorundown or pers_switch == 'heater fault'
        d = dict(quenched=quenched, abnormal=abnormal, system=system, limits=limits,
                             locrem=locrem, pers_switch=pers_switch,
                             pers_switch_installed=pers_switch_installed, activity=activity,
                             display_T=display_T, ramp_rate_slow=ramp_rate_slow, ramp=ramp,
                             remote=remote, locked=locked, autorundown=autorundown)
        if full:
            polarity_neg_desired = bool(Pm&4)
            polarity_neg_magnet = bool(Pm&2)
            polarity_neg_commanded = bool(Pm&1)
            contactors = ['xxx', 'negative closed', 'positive closed', 'both open', 'both closed'][Pn]
            d.update(polarity_neg_desired=polarity_neg_desired, polarity_neg_magnet=polarity_neg_magnet,
                     polarity_neg_commanded=polarity_neg_commanded, contactors=contactors)
        return dict_improved(d)

    def _display_T_setdev(self, val):
        if val:
            self.write('M9')
        else:
            self.write('M8')
    def _display_T_getdev(self):
        ret = self.status.get()
        return ret.display_T

    def _ramp_rate_slow_setdev(self, val):
        prev = self.status.get()
        v = int(prev.display_t)
        if val:
            v += 4
        self.write('M%d'%v)
    def _ramp_rate_slow_getdev(self):
        ret = self.status.get()
        return ret.ramp_rate_slow

    def control_mode(self, remote=None, locked=None):
        """ when neither remote nor lock is given. It returns the current setup """
        prev = self.status.get()
        if remote is None and locked is None:
            return dict_improved(remote=prev.remote, locked=prev.locked)
        val = 0
        if remote is None and prev.remote:
            val += 1
        elif remote is not None and remote:
            val += 1
        if locked is None and not prev.locked:
            val += 2
        elif locked is not None and not locked:
            val += 2
        self.write('C%d'%val)

    def _create_devs(self):
        self.write('Q4', quiet='skip') # CR termination with extended resolution
        self.current = scpiDevice(getstr='R0', str_type=float_as_fixed('%.6f', 'R'))
        self.voltage = scpiDevice(getstr='R1', str_type=float_as_fixed('%.6f', 'R'))
        self.current_measured = scpiDevice(getstr='R2', str_type=float_as_fixed('%.6f', 'R'), doc='measured current, with 0.01 A resolution (current dev is more accurate)')
        self.current_target = scpiDevice('I{val}', 'R5', str_type=float_as_fixed('%.6f', 'R'), setget=True)
        self.ramp_rate_current_min = scpiDevice('S{val}', 'R6', str_type=float_as_fixed('%.6f', 'R'), doc='A/min', setget=True)
        self.field_raw_T = scpiDevice(getstr='R7', str_type=float_as_fixed('%.6f', 'R'), doc='current in leads converted to Tesla.')
        self.field_target_T = scpiDevice('J{val}', 'R8', str_type=float_as_fixed('%.6f', 'R'), setget=True)
        self.ramp_rate_field_T_min = scpiDevice('T{val}', 'R9', str_type=float_as_fixed('%.6f', 'R'), doc='T/min', setget=True)
        self.voltage_limit = scpiDevice(getstr='R15', str_type=float_as_fixed('%.6f', 'R'), setget=True)
        self.current_persistent = scpiDevice(getstr='R16', str_type=float_as_fixed('%.6f', 'R'))
        self.current_trip = scpiDevice(getstr='R17', str_type=float_as_fixed('%.6f', 'R'))
        self.field_persistent_T = scpiDevice(getstr='R18', str_type=float_as_fixed('%.6f', 'R'))
        self.field_trip_T = scpiDevice(getstr='R19', str_type=float_as_fixed('%.6f', 'R'))
        self.persistent_heater_current_mA = scpiDevice(getstr='R20', str_type=float_as_fixed('%.6f', 'R'))
        self.current_safe_min = scpiDevice(getstr='R21', str_type=float_as_fixed('%.6f', 'R'))
        self.current_safe_max = scpiDevice(getstr='R22', str_type=float_as_fixed('%.6f', 'R'))
        self.lead_resistance_mOhm = scpiDevice(getstr='R23', str_type=float_as_fixed('%.6f', 'R'))
        self.magnet_inductance_H = scpiDevice(getstr='R24', str_type=float_as_fixed('%.6f', 'R'))
        self._devwrap('status')
        self._devwrap('display_T')
        self._devwrap('ramp_rate_slow')
        self._devwrap('current_magnet')
        self._devwrap('field_T')
        self.psh_wait_before = MemoryDevice(self._psh_wait_before, min=0, doc="The recommended minimum value is 60 s")
        self.psh_time_cool = MemoryDevice(self._psh_time_cool, min=0, doc="The recommended minimum value is 15 s")
        self.psh_time_heat = MemoryDevice(self._psh_time_heat, min=0, doc="The recommended minimum value is 15 s")
        self.ramp_wait_after = MemoryDevice(10., min=0.)
        self._devwrap('ramp_current', autoinit=False, setget=True)
        self._devwrap('ramp_field_T', autoinit=False, setget=True)
        self.alias = self.field_T
        super(oxford_ips120_10, self)._create_devs()
