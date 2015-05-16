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


"""
Wrapper for pyvisa to handle both versions <1.5 and after
"""

# don't export threading, warnings, os
import threading as _threading
import warnings as _warnings
import os as _os
from ctypes import byref as _byref
from math import isinf as _isinf

try_agilent_first = True
agilent_path = r"c:\Windows\system32\agvisa32.dll"
old_interface = True       # True when pyvisa versons < 1.5
version = "1.4"

_agilent_visa = False

def _add_enum_equivalent_old():
        class Parity(object):
            none = constants.VI_ASRL_PAR_NONE
            odd = constants.VI_ASRL_PAR_ODD
            even = constants.VI_ASRL_PAR_EVEN
            mark = constants.VI_ASRL_PAR_MARK
            space = constants.VI_ASRL_PAR_SPACE
        constants.Parity = Parity
        class StopBits(object):
            one = 1.
            one_and_a_half = 1.5
            two = 2.0
        constants.StopBits = StopBits
        class SerialTermination(object):
            none = constants.VI_ASRL_END_NONE
            last_bit = constants.VI_ASRL_END_LAST_BIT
            termination_char = constants.VI_ASRL_END_TERMCHAR
            termination_break = constants.VI_ASRL_END_BREAK
        constants.SerialTermination = SerialTermination


try:
    import pyvisa
    try:
        import pyvisa.vpp43 as vpp43
        import pyvisa.vpp43_constants as constants
        _add_enum_equivalent_old()
        # Use these instead of the VI_ASRL constants for the code to
        # work in both pyvisa 1.4 and 1.6
        from pyvisa.visa_exceptions import VisaIOError
        visa = None  # to be replaced during get_resource_manager
        old_interface = True
    except ImportError:
        # vppp43 is not present in new interface
        old_interface = False
        version = pyvisa.__version__
        import pyvisa.constants as constants
        from pyvisa import VisaIOError

except ImportError as exc:
    # give a dummy visa to handle imports
    pyvisa = None
    print 'Error importing pyVisa (not installed). You will have reduced functionality.'


def _get_lib_properties(libraryHandle):
    import win32api
    global _win32api
    _win32api = win32api
    filename = win32api.GetModuleFileName(libraryHandle)
    fixedInfo = win32api.GetFileVersionInfo(filename, '\\')
    # Only pick the first lang, codepage combination
    lang, codepage = win32api.GetFileVersionInfo(filename, r'\VarFileInfo\Translation')[0]
    base = '\\StringFileInfo\\%04X%04X\\'%(lang, codepage)
    company = win32api.GetFileVersionInfo(filename, base+'CompanyName')
    product = win32api.GetFileVersionInfo(filename, base+'ProductName')
    version = win32api.GetFileVersionInfo(filename, base+'ProductVersion')
    fileversion = win32api.GetFileVersionInfo(filename, base+'FileVersion')
    comments = win32api.GetFileVersionInfo(filename, base+'Comments')
    descr = win32api.GetFileVersionInfo(filename, base+'FileDescription')
    return dict(fixed=fixedInfo, lang=lang, codepage=codepage, company=company,
                product=product, version=version, fileversion=fileversion,
                comments=comments, descr=descr, filename=filename)

def _visa_test_agilent(handle=None):
    global _visa_lib_properties, _agilent_visa
    if _os.name != 'nt':
        _agilent_visa = False
        return _agilent_visa
    if handle is None:
        handle = vpp43.visa_library()._handle
    _visa_lib_properties = _get_lib_properties(handle)
    if 'agilent' in _visa_lib_properties['company'].lower():
        _agilent_visa = True
    else:
        _agilent_visa = False
    return _agilent_visa


##################################
# routines needed for pyvisa < 1.5
##################################

def _patch_pyvisa():
    """ This functions applies a patch to pyvisa
        to allow visa read to work in multi threads
    """
    if hasattr(visa, "_removefilter_orig"):
        #print 'Skipping patch: already applied'
        return
    #print 'Installing pyvisa patch'
    # we change visa.warnings (the same as _warnings)
    _warnings._filters_lock_pyvisa = _threading.Lock()
    def removefilter(*arg, **kwarg):
        #print 'Doing remove filter %r, %r'%(arg, kwarg)
        with _warnings._filters_lock_pyvisa:
            visa._removefilter_orig(*arg, **kwarg)
    def filterwarnings(*arg, **kwarg):
        #print 'Doing filter warnings %r, %r'%(arg, kwarg)
        with _warnings._filters_lock_pyvisa:
            _warnings.filterwarnings_orig(*arg, **kwarg)
    visa._removefilter_orig = visa._removefilter
    visa._removefilter = removefilter
    _warnings.filterwarnings_orig = _warnings.filterwarnings
    _warnings.filterwarnings = filterwarnings

def _old_load_visa(path=None):
    """
    if path==None: obeys the try_agilent_first. If try_agilent_first is True
                   it overrides even a choice in .pyvisarc
    if path='': only load the default library, does not follow try_agilent_first
                but listens to .pyvisarc
    for any other path, load it.
    On windows the usual path for 32bits can be
        For National instrument: r'c:\Windows\system32\visa32.dll'
        For Agilent: r'c:\Windows\system32\agvisa32.dll'
          (That is for agilent and NI installed at the same time)
    """
    if vpp43.visa_library._VisaLibrary__lib:
        old_close = vpp43.visa_library().viClose
    else:
        old_close = None
    loaded = False
    if _os.name == 'nt' and path is None and try_agilent_first:
        try:
            vpp43.visa_library.load_library(agilent_path)
        except WindowsError: 
            print 'Unable to load Agilent visa library. Will try the default one (National Instruments?).'
        else:
            loaded = True
    if not loaded:
        if path is None:
            path = ''
        if path == '':
            try:
                path = pyvisa._visa_library_path
            except AttributeError:
                path = None
        try:
            vpp43.visa_library.load_library(path)
        except WindowsError:
            if path is None:
                error = 'Unable to load default visa32.dll.'
            else:
                error = 'Unable to load %s'%path
            raise ImportError(error)
        except OSError as exc: # on linux if can't find visa library
            raise ImportError('\nError loading visa library: %s'%exc)
    # When pyvisa.visa is imported for the first time, it initializes the
    # resource manager (which would load a default library if it is not loaded yet)
    # Here we have loaded the library.
    global visa
    import pyvisa.visa as visa

    # Now, if necessary, we reinitialize the resource manager
    try:
        visa.resource_manager.resource_name
    except visa.VisaIOError: # resource manager session is wrong.
        try:
            old_close(visa.resource_manager.session)
        except visa.VisaIOError:
            _warnings.warn('Unable to properly close previous resource manager')
        visa.resource_manager.init()

    _patch_pyvisa()
    _visa_test_agilent()
    

####################################################################
# Redirection class
####################################################################

class redirect_instr(object):
    def __init__(self, instr_instance):
        # Need to set this first, all others set will probably need this.
        self.instr = instr_instance
    # we redirect all unknown access to self.instr
    def __attr_in_redirect(self, name):
        try:
            super(redirect_instr, self).__getattribute__(name)
            return True
        except AttributeError:
            return False
    def __getattr__(self, name):
        return getattr(self.instr, name)
    def __setattr__(self, name, value):
        # To overide a value only present in self.instr, create the
        # attribute wirh _new_attr below
        if self.__attr_in_redirect(name):
            # when present in self, use that
            super(redirect_instr, self).__setattr__(name, value)
        elif name == 'instr' or not hasattr(self.instr, name):
            # for 'instr' or if not already in self.instr
            # we need to check for instr because otherwise self.instr will fail
            # on the initial self.instr =  ...
            super(redirect_instr, self).__setattr__(name, value)
        else:
            # it is only in self.instr
            setattr(self.instr, name, value)
    def _new_attr(self, name, value=None):
        super(redirect_instr, self).__setattr__(name, value)
    def __delattr__(self, name):
        if self.__attr_in_redirect(name):
            super(redirect_instr, self).__delattr__(name)
        else:
            delattr(self.instr, name)

####################################################################
# Instruments wrapper classes
####################################################################
def _strip_termination(input_str, termination=None):
    """ Similar to the one in pyvisa 1.4, except only removes CR, LF or CR+LF
        if present at the end of the string when None is used.
    """
    CR = '\r'
    LF = '\n'
    if termination:
        if input_str.endswith(termination):
            return input_str[:-len(termination)]
        else:
            _warnings.warn("read string doesn't end with "
                           "termination characters", stacklevel=2)
    if input_str.endswith(CR+LF):
        return input_str[:-2]
    elif input_str[-1] in (CR, LF):
        return input_str[:-1]
    return input_str

def _write_helper(self, message, termination='default'):
    # For old: improved termination handling, does not use the delay, matches new interface
    # For new: overides the resource write to remove handling of encoding
    termination = self.write_termination if termination == 'default' else termination
    if termination:
        if message.endswith(termination):
            _warnings.warn("write message already ends with "
                          "termination characters", stacklevel=2)
        else:
            message += termination
    self.write_raw(message)

def _read_helper(self, termination='default'):
    # For old: improved termination handling, matches new interface
    # For new: overides the resource read to remove handling of encoding and add stripping of termination
    #          It does not change the hardware termination handling
    termination = self.read_termination if termination == 'default' else termination
    return _strip_termination(self.read_raw(), termination)

def _query_helper(self, message, termination='default', read_termination='default', write_termination='default', raw=False):
    if termination != 'default':
        if read_termination != 'default':
            read_termination = termination
        if write_termination != 'default':
            write_termination = termination
    self.write(message, termination=write_termination)
    if raw:
        return self.read_raw()
    else:
        return self.read(termination=read_termination)

class WaitResponse(object):
    """Class used in return of wait_on_event. It properly closes the context upon delete.
    """
    def __init__(self, event_type, context, ret, visalib, timed_out=False):
        self.event_type = event_type
        self.context = context
        self.ret = ret
        self._visalib = visalib
        self.timed_out = timed_out
    def __del__(self):
        if self.context != None:
            self._visalib.close(self.context)

@property
def flow_control_helper(self):
    return self.get_visa_attribute(constants.VI_ATTR_ASRL_FLOW_CNTRL)
@flow_control_helper.setter
def flow_control_helper(self, value):
    self.set_visa_attribute(constants.VI_ATTR_ASRL_FLOW_CNTRL, value)

# Important: do not use wait_for_srq
#            it enables constants.VI_EVENT_SERVICE_REQ, constants.VI_QUEUE

class old_Instrument(redirect_instr):
    CR = '\r'
    LF = '\n'
    _read_termination = None
    _write_termination = CR + LF
    def __init__(self, instr_instance, **kwargs):
        super(old_Instrument, self).__init__(instr_instance)
        for k,v in kwargs.items():
            setattr(self, k, v)
        if self.is_gpib():
            # The old library enables this automatically. We turn it off here
            # to match the behavior of the new library
            # The reason to enable it early was probably to make
            #  wait_for_srq work even if the first time it is called the SRQ has
            # already occured.
            # But with it enabled, it can prevent VI_HDNLR from working (for NI visa)
            self.disable_event(constants.VI_EVENT_SERVICE_REQ, constants.VI_QUEUE)
    # Make timeout handling, the same as new version (use ms)
    # The old version is bases on seconds
    # Also note that the timeout used could depend on the visa library and the
    # device. gpib libraries only allow a limited set of values
    #   0, 10us, 30us, 100us, 300us,... 1s, 3s, 10s, ..., 1000s
    # it usually rounds up. NI returns the round up value, agilent does not.
    # The old code used to default to 5s, the new code to 2s (visa default timeout)
    # instrument_base.visaInstrument sets it to 3,
    # so I change the default to match the new one.
    @property
    def timeout(self):
        try:
            return int(self.instr.timeout*1000)
        except NameError:
            return float('+inf')
    @timeout.setter
    def timeout(self, value):
        if value is None or _isinf(value):
            del self.timeout
        else:
            self.instr.timeout = value/1000.
    @timeout.deleter
    def timeout(self):
        # first set a timeout to prevent NameError exception
        self.instr.timeout = 0
        del self.instr.timeout
    @property
    def read_termination(self):
        return self._read_termination
    @read_termination.setter
    def read_termination(self, value):
        # This changes the hardware read termination
        if value:
            last_char = value[-1:]
            if last_char in value[:-1]:
                raise ValueError("ambiguous ending in termination characters")
            self.term_chars = value
        else: # value is None
            # This is needed for serial because  VI_ATTR_TERMCHAR can also be used by VI_ATTR_ASRL_END_IN
            # so return it to the default value
            self.term_chars = self.LF
            self.term_chars = None
        self._read_termination = value
    @property
    def write_termination(self):
        return self._write_termination
    @write_termination.setter
    def write_termination(self, value):
        self._write_termination = value
    flow_control = flow_control_helper
    def is_serial(self):
        return self.get_visa_attribute(constants.VI_ATTR_INTF_TYPE) == constants.VI_INTF_ASRL
        #return isinstance(self.instr, visa.SerialInstrument)
    def is_gpib(self):
        return self.get_visa_attribute(constants.VI_ATTR_INTF_TYPE) == constants.VI_INTF_GPIB
        #return isinstance(self.instr, visa.GpibInstrument)
    def get_visa_attribute(self, attr):
        return vpp43.get_attribute(self.vi, attr)
    def set_visa_attribute(self, attr, state):
        vpp43.set_attribute(self.vi, attr, state)
    def lock_excl(self, timeout_ms):
        """
        timeout_ms is in ms or can be constants.VI_TMO_IMMEDIATE or constants.VI_TMO_INFINITE
        """
        vpp43.lock(self.vi, constants.VI_EXCLUSIVE_LOCK, timeout_ms)
    def lock(self, timeout_ms='default', requested_key=None):
        """ Shared lock
        """
        # does not handle infinite time
        timeout_ms = self.timeout if timeout_ms == 'default' else timeout_ms
        ret = vpp43.lock(self.vi, constants.VI_SHARED_LOCK, timeout_ms, requested_key)
        return ret.value
    def unlock(self):
        vpp43.unlock(self.vi)
    def install_visa_handler(self, event_type, handler, user_handle):
        # returns the converted user_handle
        return vpp43.install_handler(self.vi, event_type, handler, user_handle)
    def uninstall_visa_handler(self, event_type, handler, user_handle):
        # does not work with user_handle None
        # user_handle is the converted user_handle
        vpp43.uninstall_handler(self.vi, event_type, handler, user_handle)
    def enable_event(self, event_type, mechanism):
        vpp43.enable_event(self.vi, event_type, mechanism)
    def disable_event(self, event_type, mechanism):
        vpp43.disable_event(self.vi, event_type, mechanism)
    def discard_events(self, event_type, mechanism):
        vpp43.discard_events(self.vi, event_type, mechanism)
    def wait_on_event(self, in_event_type, timeout_ms, capture_timeout=False):
        try:
            # replace vpp43 wait_on_event to obtain status in a thread safe manner
            # ret can be VI_SUCCESS or VI_SUCCESS_QUEUE_NEMPTY without raising a VisaIOError
            event_type = vpp43.ViEventType()
            context = vpp43.ViEvent()
            ret = vpp43.visa_library().viWaitOnEvent(self.vi, in_event_type, timeout_ms,
                                        _byref(event_type), _byref(context))
            #event_type, context = vpp43.wait_on_event(self.vi, in_event_type, timeout_ms)
        except VisaIOError as exc:
            if capture_timeout and exc.error_code == constants.VI_ERROR_TMO:
                return WaitResponse(0, None, exc.error_code, vpp43, timed_out=True)
            raise
        return WaitResponse(event_type, context, ret, vpp43)
    def control_ren(self, mode):
        vpp43.gpib_control_ren(self.vi, mode)
    def read_stb(self):
        return vpp43.read_stb(self.vi)
    @property
    def stb(self):
        return self.read_stb()
    def read_raw_n(self, size):
        try:
            _warnings.filterwarnings("ignore", "VI_SUCCESS_MAX_CNT")
            ret = vpp43.read(self.vi, size)
        finally:
            visa._removefilter("ignore", "VI_SUCCESS_MAX_CNT")
        return ret
    # read_raw is ok
    def write_raw(self, message):
        vpp43.write(self.vi, message)
    write = _write_helper
    read = _read_helper
    query = _query_helper

class new_Instrument(redirect_instr):
    def __init__(self, instr_instance, **kwargs):
        super(new_Instrument, self).__init__(instr_instance)
        for k,v in kwargs.items():
            setattr(self, k, v)
    def is_serial(self):
        return self.interface_type == constants.InterfaceType.asrl
        #return isinstance(self.instr, pyvisa.resources.SerialInstrument)
    def is_gpib(self):
        return self.interface_type == constants.InterfaceType.gpib
        #return isinstance(self.instr, pyvisa.resources.GPIBInstrument)
    def trigger(self):
        # VI_TRIG_SW is the default
        #self.set_attribute(constants.VI_ATTR_TRIG_ID, constants.VI_TRIG_SW) # probably uncessary but the code was like that
        self.assert_trigger()
    def install_visa_handler(self, event_type, handler, user_handle):
        # returns the converted user_handle
        return self.visalib.install_visa_handler(self.session, event_type, handler, user_handle)
    def uninstall_visa_handler(self, event_type, handler, user_handle):
        # user_handle is the converted user_handle
        if version in ['1.5', '1.6', '1.6.1', '1.6.2', '1.6.3']:
            # The code was wrong, we overide it
            session = self.session
            for ndx, element in enumerate(self.visalib.handlers[session]):
                if element[0] is handler and element[1] is user_handle:
                    del self.visalib.handlers[session][ndx]
                    break
            else:
                raise pyvisa.errors.UnknownHandler(event_type, handler, user_handle)
            try:
                # check if we are using the ctwrapper default backend
                self.visalib.viUninstallHandler
            except AttributeError:
                self.visalib.uninstall_handler(event_type, element[2], user_handle)
            else:
                pyvisa.ctwrapper.functions.set_user_handle_type(self.visalib, user_handle)
                if user_handle is not None:
                        user_handle = _byref(user_handle)
                self.visalib.viUninstallHandler(self.session, event_type, element[2], user_handle)
        else:
            self.visalib.uninstall_visa_handler(self.session, event_type, handler, user_handle)
    if version in ['1.5', '1.6', '1.6.1', '1.6.2']:
        @property
        def interface_type(self):
            return self.visalib.parse_resource(self._resource_manager.session,
                                           self.resource_name)[0].interface_type
    if version in ['1.5', '1.6', '1.6.1', '1.6.2', '1.6.3']:
        def lock_excl(self, timeout_ms):
            """
            timeout_ms is in ms or can be constants.VI_TMO_IMMEDIATE or constants.VI_TMO_INFINITE
            """
            self.visalib.lock(self.session, constants.VI_EXCLUSIVE_LOCK, timeout_ms)
        def lock(self, timeout_ms='default', requested_key=None):
            """ Shared lock
            """
            # does not handle infinite time
            timeout_ms = self.timeout if timeout_ms == 'default' else timeout_ms
            ret = self.visalib.lock(self.session, constants.VI_SHARED_LOCK, timeout_ms, requested_key)[0]
            return ret.value
        def enable_event(self, event_type, mechanism):
            self.visalib.enable_event(self.session, event_type, mechanism)
        def disable_event(self, event_type, mechanism):
            self.visalib.disable_event(self.session, event_type, mechanism)
        def discard_events(self, event_type, mechanism):
            self.visalib.discard_events(self.session, event_type, mechanism)
        def wait_on_event(self, in_event_type, timeout, capture_timeout=False):
            try:
                event_type, context, ret = self.visalib.wait_on_event(self.session, in_event_type, timeout)
            except VisaIOError as exc:
                if capture_timeout and exc.error_code == constants.StatusCode.error_timeout:
                    return WaitResponse(0, None, exc.error_code, self.visalib, timed_out=True)
                raise
            return WaitResponse(event_type, context, ret, self.visalib)
        @property
        def read_termination(self):
            return self.instr.read_termination
        @read_termination.setter
        def read_termination(self, value):
            if value is None:
                # This is needed for serial because  VI_ATTR_TERMCHAR can also be used by VI_ATTR_ASRL_END_IN
                # so return it to the default value
                self.instr.read_termination = '\n'
            self.instr.read_termination = value
        flow_control = flow_control_helper
    def control_ren(self, mode):
        try:
            self.instr.control_ren(mode)
        except AttributeError:
            self.visalib.viGpibControlREN(self.session, mode)
    #read_raw, write_raw are ok
    write = _write_helper
    read = _read_helper
    query = _query_helper
    def read_raw_n(self, size):
        with self.ignore_warning(constants.VI_SUCCESS_MAX_CNT):
            return self.visalib.read(self.session, size)[0]



####################################################################
# Resource_manager wrapper classes
####################################################################

def _get_resource_info_helper(rsrc_manager, resource_name):
    normalized = alias_if_exists = None
    try:
        _, _, _, normalized, alias_if_exists = rsrc_manager.resource_info(resource_name)
    except AttributeError:
        pass
    return normalized, alias_if_exists

def _get_instrument_list(self, use_aliases=True):
    # same as old pyvisa 1.4 version of get_instrument_list except with 
    # a separated and fixed (memory leak) first part (self.list_resources)
    # and a second part modified for bad visa implementations
    rsrcs = self.list_resources()
    # Phase two: If available and use_aliases is True, substitute the alias.
    # Otherwise, truncate the "::INSTR".
    result = []
    for resource_name in rsrcs:
        # For agilent visa version 16.2.15823.0 (at least), the serial number (for USB)
        # is converted to lower in the library, but the instrument really uses
        # the upper one for the extended resources so without this upper
        # it fails to find the alias.
        # Howerver, this is a hack because if a serial number really uses lower case
        # then this will prevent the match
        # It used to work ok with agilent io 16.0.14518.0 and 16.1.14827.0
        # Agilent also does not normalize the entries properly (it likes decimal instead of hexadecimal)
        # National instruments (MAX) 5.1.0f0 for usb does not accept the extra ::0  (interface number)
        # that it returns as normalized, and it requires the values to be in hexadecimal.
        #  The open function is a lot less sensitive on both.
        #  according to specs, the comparison should be case insensitive.
        # So lets try a few different ones
        normalized1, alias_if_exists1 = _get_resource_info_helper(self, resource_name)
        normalized2, alias_if_exists2 = _get_resource_info_helper(self, resource_name.upper())
        if alias_if_exists1:
            normalized, alias_if_exists = normalized1, alias_if_exists1
        elif alias_if_exists2:
            normalized, alias_if_exists = normalized2, alias_if_exists2
        else:
            normalized, alias_if_exists = normalized1, None
        if alias_if_exists and use_aliases:
            result.append(alias_if_exists)
        else:
            result.append(normalized[:-7])
    return result


class old_resource_manager(object):
    def __init__(self, path=None):
        """
        Note that loading a new resource_manager will break a previous one if it used
        a different dll. It is not possible to use 2 different dlls at the same time
        with pyvisa <1.5.
        """
        self._is_agilent = None
        _old_load_visa(path)
    # The same as the first part of visa.get_instruments_list except for the close
    def list_resources(self, query='?*::INSTR'):
        resource_names = []
        find_list, return_counter, instrument_description = \
            vpp43.find_resources(visa.resource_manager.session, query)
        resource_names.append(instrument_description)
        for i in xrange(return_counter - 1):
            resource_names.append(vpp43.find_next(find_list))
        vpp43.close(find_list)
        return resource_names
    def resource_info(self, resource_name):
        """ unpacks to: interface_type, interface_board_number, resource_class, resource_name alias,
            alias is returned as None when it is empty
        """
        return vpp43.parse_resource_extended(visa.resource_manager.session,
                                               resource_name)

    get_instrument_list = _get_instrument_list

    def open_resource(self, resource_name, **kwargs):
        if 'term_chars' in kwargs:
            # does not map to
            raise ValueError('term_chars is not permitted in open_resource')
        kwargs_after = {}
        for k in ['read_termination', 'write_termination', 'timeout', 'flow_control']:
            if kwargs.has_key(k):
                kwargs_after[k] = kwargs.pop(k)
        instr = visa.instrument(resource_name, **kwargs)
        if isinstance(instr, visa.SerialInstrument):
            # serials was setting term_chars to CR
            # change it to same defaults as new code (which is the general default)
            kwargs_after.setdefault('read_termination', old_Instrument._read_termination)
        kwargs_after.setdefault('timeout', 2000)
        return old_Instrument(instr, **kwargs_after)
    def is_agilent(self):
        if self._is_agilent is None:
            try:
                self._is_agilent = _visa_test_agilent(vpp43.visa_library()._handle)
            except AttributeError:
                self._is_agilent = False
        return self._is_agilent
    @property
    def visalib(self):
        return vpp43.visa_library()

class new_WrapResourceManager(redirect_instr):
    def __init__(self, new_rsrc_manager):
        super(new_WrapResourceManager, self).__init__(new_rsrc_manager)
        self._is_agilent = None
    if version in ['1.5', '1.6', '1.6.1', '1.6.2', '1.6.3']:
        additional_properties = ['flow_control']
        # The same as the original ResourceManager one (1.6.1) except for the close statement
        def list_resources(self, query='?*::INSTR'):
            """Returns a tuple of all connected devices matching query.
    
            :param query: regular expression used to match devices.
            """
    
            lib = self.visalib
    
            resources = []
            find_list, return_counter, instrument_description, err = lib.find_resources(self.session, query)
            resources.append(instrument_description)
            for i in range(return_counter - 1):
                resources.append(lib.find_next(find_list)[0])
        
            lib.close(find_list)
    
            return tuple(resource for resource in resources)
    else:
        additional_properties = []
    def is_agilent(self):
        if self._is_agilent is None:
            try:
                self._is_agilent = _visa_test_agilent(self.visalib.lib._handle)
            except AttributeError:
                self._is_agilent = False
        return self._is_agilent
    def open_resource(self, resource_name, **kwargs):
        kwargs_after = {}
        for k in self.additional_properties:
            if kwargs.has_key(k):
                kwargs_after[k] = kwargs.pop(k)
        instr = self.instr.open_resource(resource_name, **kwargs)
        return new_Instrument(instr, **kwargs_after)

    get_instrument_list = _get_instrument_list


####################################################################
# Resource_manager factory
####################################################################

def _clean_up_registry(path):
    if version in ['1.5', '1.6', '1.6.1', '1.6.2', '1.6.3']:
        registry = pyvisa.highlevel.VisaLibraryBase._registry
        for t in list(registry):
            if t[1] == path:
                del registry[t]

def get_resource_manager(path=None):
    """
    if path==None: obeys the try_agilent_first.
    if path='': only load the default library, does not follow try_agilent_first
    for any other path, load it.
    In case of problem it raises ImportError
    Note that for pyvisa<1.5 only one dll can be loaded at the same time. Loading
    a new one kills the previous one (resource_manager will no longer work.)
    """
    if pyvisa is None:
        return None
    if old_interface:
        # The next line can produce ImportError
        return old_resource_manager(path)
    else:
        if _os.name == 'nt' and path is None and try_agilent_first:
            try:
                return new_WrapResourceManager(pyvisa.ResourceManager(agilent_path))
            except (pyvisa.errors.LibraryError, UnicodeDecodeError):
                # for UnicodeDecodeError see: https://github.com/hgrecco/pyvisa/issues/136
                print 'Unable to load Agilent visa library. Will try the default one (National Instruments?).'
                _clean_up_registry(agilent_path)
        if path is None:
            path = ''
        try:
            return new_WrapResourceManager(pyvisa.ResourceManager(path))
        except (pyvisa.errors.LibraryError, UnicodeDecodeError, OSError) as exc:
            # We get OSError when no libraries are found
            raise ImportError('Unable to load backend: %s'%exc)



# read, read_raw and write have changed
# read_raw is the same (it now accepts size which is used internally as the block size to read. reading stops when not getting status max_count_read)
# read and write have separate termination characters
#  used to be self.__term_chars
#  now they are _write_termination and _read_termination and can be passed as parameters to read and write
# Before, when termination was None it meant removing all CR and LF from the end of the read and adding CR+LF to write
#     Note that removing any combination of any length of CR,LF at the end was probably wrong.
# Now it only adds/removes the termination when requesting one. The default read term is None, the default write term is CR+LF
# There is now a write_raw
# The new read/write also use encoding/decoding (they now return unicode) and they default to en encoding of 'ascii'
#    the encoding can be changed for the instruments or on each call with an encoding argument
#    The encoding stuff will probably be a problem
# new interface v.timeout is now in ms (was in s)
# new interface provides a read_stb, set_visa_attribute, get_visa_attribute, install_handler, uninstall_handler
#           lock (Shared_Lock), unlock
#      does not provide enable/disable event wait_on_event
# The old Serial used 9600/8/1/no parity, term_chars=CR, end_input(VI_ATTR_ASRL_END_IN)=VI_ASRL_END_TERMCHAR
#  These are all defaults except for term_chars=CR (the char used internally defaults to LF)
#  The old code, when not specifying term_chars, would have VI_ATTR_TERMCHAR_EN disabled, VI_ATTR_TERMCHAR
#    defaulting to LF, VI_ATTR_ASRL_END_IN=VI_ASRL_END_TERMCHAR and would strip all CR,LF from ends of read and add
#        CR+LF to end of write
#   For serial, by default, this would change to term_chars=CR, VI_ATTR_TERMCHAR_EN enabled, VI_ATTR_TERMCHAR=CR
#      and read would strip a single CR and writes would add CR.
#  The new code always goes for the defaults (VI_ATTR_TERMCHAR=LF), VI_ATTR_TERMCHAR_EN disabled, no strip on read,
#    adds CR+LF on write
# Now any of the valid attributes can be specified on the open_resource call
# (only some were allowed before)

# I believe the patch to allow read in multiple threads is not longer needed.

"""
1.4
On visa instrument obtained by
  v=visa.instrument(addr)
  obtain vi=v.vi
  I use:
    Lock_Visa(vi)
    v.timeout=3
    v.timeout
  check if v is instance of visa.SerialInstrument
    vpp43.read_stb(vi)
    vpp43.lock(vi, vpp43.VI_EXCLUSIVE_LOCK, timeout)
       using vpp43.VisaIOError, vpp43.VI_ERROR_TMO, vpp43.VI_ERROR_SESN_NLOCKED
    vpp43.gpib_control_ren(vi, val)
       vpp43.VI_GPIB_REN_ASSERT vpp43.VI_GPIB_REN_DEASSERT vpp43.VI_GPIB_REN_ASSERT_ADDRESS_LLO
       vpp43.VI_GPIB_REN_DEASSERT_GTL vpp43.VI_GPIB_REN_ASSERT_ADDRESS vpp43.VI_GPIB_REN_ADDRESS_GTL
    v.read()
    v.read_raw()
    v.write(something)
    v.clear()
    v.trigger()
    vpp43.get_attribute(vi, vpp43.VI_ATTR_INTF_TYPE) == vpp43.VI_INTF_GPIB
    vpp43.install_handler(vi, vpp43.VI_EVENT_SERVICE_REQ, self._proxy_handler, 0)
    vpp43.enable_event(vi, vpp43.VI_EVENT_SERVICE_REQ, vpp43.VI_HNDLR)
    vpp43.disable_event(vi, vpp43.VI_EVENT_SERVICE_REQ, vpp43.VI_QUEUE)
    vpp43.enable_event(vi, vpp43.VI_EVENT_SERVICE_REQ, vpp43.VI_QUEUE)
    vpp43.uninstall_handler(vi, vpp43.VI_EVENT_SERVICE_REQ, self._proxy_handler, self._handler_userval)
    vpp43.wait_on_event(vi, vpp43.VI_EVENT_SERVICE_REQ, int(max_time*1000))
    vpp43.wait_on_event(vi, vpp43.VI_EVENT_SERVICE_REQ, 0)
    vpp43.close(context_from_event)
    vpp43.find_resources(visa.resource_manager.session, "?*::INSTR")
    vpp43.find_next(find_list)
    vpp43.close(find_list)
    vpp43.parse_resource_extended(visa.resource_manager.session, resource_name)
in instruments_others:
     self.visa.term_chars='\n'  (for sr780_analyzer)
      visa.vpp43.set_attribute(vi, visa.VI_ATTR_TERMCHAR_EN, visa.VI_FALSE)
      visa.vpp43.read(vi, 1)
      visa.VisaIOError
     for MagnetController_SMC
      visa.SerialInstrument
      vpp43.set_attribute(self.visa.vi, vpp43.VI_ATTR_ASRL_FLOW_CNTRL, vpp43.VI_ASRL_FLOW_XON_XOFF)
     for Lakeshore 370
       visa.SerialInstrument
       self.visa.parity = True
       self.visa.data_bits = 7
       self.visa.term_chars = '\r\n'
"""
# TODO: test of cross visa driver locks
#              should also check the LAN.
#       test event/handlers (QUEUE and HDNLR at same time, any combination allowed)
#       test gpib RQS and read status byte handling

"""
   opening multiple times a serial instrument, works if all opened operation are on the same
   visalib (either NI or agilent, but not on both)
   
   Opening the same GPIB instrument on two visalib at the same time is possible.
   A locked_exclusive instrument on NI does a hardware lock which interferes with
   usage of the device on the agilent visa. This does not happen for shared lock, nor
   for any locks on agilent. The lock themselves don't interface (you can lock on both
   visa lib at the same time, but using the agilent will be broken).

   USB device can also be shared and none of the locks on different implementation interfere with
   each other.

   TCP device (VXI11) propagates the exclusive lock to the instrument so both libraries interoperate properly.
   Shared lock are not propagated so there is no protection across visalib for shared lock.

   So the main consequence: DO NOT USE BOTH IMPLEMENTATION AT THE SAME TIME

   As for event/handlers
     agilent allows the use of both at the same time, NI does not.
     NI does not allow installing service_request handlers on serial, agilent allows it.
     NI does not allow queued service_request on serial
     Queued exceptions are never allowed
     SRQ behavior on agilent and NI is probably different ((NI does autopoll?), agilent checks the line)


cd /Codes/pyvisa

import pyvisa
rm1 = pyvisa.ResourceManager(r"c:\Windows\system32\agvisa32.dll")
rm2 = pyvisa.ResourceManager()

#vs1 = rm1.get_instrument('ASRL1::INSTR', baud_rate=9600)
vs2 = rm2.get_instrument('ASRL1::INSTR', baud_rate=9600)
vu1 = rm1.get_instrument('USB::0x0957::0x0B0B::MY52220278')
vu2 = rm2.get_instrument('USB::0x0957::0x0B0B::MY52220278')
vg1 = rm1.get_instrument('GPIB0::6::INSTR')
vg2 = rm2.get_instrument('GPIB0::6::INSTR')

def handler_func(session, event_type, context, user_handle):
    s = v.read_stb()
    if user_handle is not None:
        user_handle = user_handle.contents.value
    print 'session_id=%s (==%s event_session), type=%s, context=%s, user_handle=%s, stb=%s'%( v.session, session.value, pyvisa.constants.EventType(event_type), context.value, user_handle, int(s))
    return pyvisa.constants.VI_SUCCESS

#user_handle_2_s1 = vs1.install_handler(pyvisa.constants.EventType.service_request, handler_func, 2)
user_handle_2_g1 = vg1.install_handler(pyvisa.constants.EventType.service_request, handler_func, 2)
user_handle_2_u1 = vu1.install_handler(pyvisa.constants.EventType.service_request, handler_func, 2)
user_handle_2_s2 = vs2.install_handler(pyvisa.constants.EventType.exception, handler_func, 2)
user_handle_2_g2 = vg2.install_handler(pyvisa.constants.EventType.service_request, handler_func, 2)
user_handle_2_u2 = vu2.install_handler(pyvisa.constants.EventType.service_request, handler_func, 2)

#vs1.enable_event(pyvisa.constants.EventType.service_request, pyvisa.constants.EventMechanism.handler)
vg1.enable_event(pyvisa.constants.EventType.service_request, pyvisa.constants.EventMechanism.handler)
vu1.enable_event(pyvisa.constants.EventType.service_request, pyvisa.constants.EventMechanism.handler)
vs2.enable_event(pyvisa.constants.EventType.exception, pyvisa.constants.EventMechanism.handler)
vg2.enable_event(pyvisa.constants.EventType.service_request, pyvisa.constants.EventMechanism.handler)
vu2.enable_event(pyvisa.constants.EventType.service_request, pyvisa.constants.EventMechanism.handler)

#vs1.enable_event(pyvisa.constants.EventType.service_request, pyvisa.constants.EventMechanism.queue)
vg1.enable_event(pyvisa.constants.EventType.service_request, pyvisa.constants.EventMechanism.queue)
vu1.enable_event(pyvisa.constants.EventType.service_request, pyvisa.constants.EventMechanism.queue)
vs2.enable_event(pyvisa.constants.EventType.service_request, pyvisa.constants.EventMechanism.queue)
vg2.enable_event(pyvisa.constants.EventType.service_request, pyvisa.constants.EventMechanism.queue)
vu2.enable_event(pyvisa.constants.EventType.service_request, pyvisa.constants.EventMechanism.queue)

"""

########################### testing code #######################################################
from contextlib import contextmanager

@contextmanager
def visa_context(ok=None, bad=None):
    """
    ok selects the status that will produce True, all others are False
    bad selects the status that will produce False, all others are True
    Use one or the other. If neither are sets, it is the same as ok='OK'
    select one of: 'OK'(no erros), 'timeout', 'unsupported', 'locked', 'io_error', 'busy'
    """
    res = [True, '']
    error = 'OK'
    if ok is None and bad is None:
        ok = 'OK'
    try:
        yield res
    except VisaIOError as exc:
        if exc.error_code == constants.VI_ERROR_TMO:
            error = 'timeout'
        elif exc.error_code == constants.VI_ERROR_NSUP_OPER:
            error = 'unsupported'
        elif exc.error_code == constants.VI_ERROR_RSRC_LOCKED:
            error = 'locked'
        elif exc.error_code == constants.VI_ERROR_IO:
            error = 'io_error'
        elif exc.error_code == constants.VI_ERROR_RSRC_BUSY:
            error = 'busy'
        else:
            error = str(exc)
    except Exception as exc:
            print type(exc)
            error = str(exc)
    finally:
        if ok is not None:
            if error != ok:
                res[:] = [False, error]
        else:
            if error == bad:
                res[:] = [False, '']
            else:
                res[:] = [True, error]

@contextmanager
def subprocess_start():
    import sys
    old_arg0 = sys.argv[0]
    sys.argv[0] = ''
    try:
        yield
    finally:
        sys.argv[0] = old_arg0


def visa_lib_info(rsrc_manager):
    if _os.name != 'nt':
        return 'Unknown version'
    if old_interface:
        handle = vpp43.visa_library()._handle
    else:
        handle = rsrc_manager.visalib.lib._handle
    props = _get_lib_properties(handle)
    return '{company}, {product}: {version}'.format(**props)

def _test_lock(instrument, exclusive=True):
    # Use a short timeout to run more quickly
    timeout = 500 #ms
    # bad='OK' means it returns False if the lock went through
    with visa_context(bad='OK') as res:
        if exclusive:
            instrument.lock_excl(timeout)
        else:
            instrument.lock(timeout)
    res = res if res[0] else False
    return res

def _test_lock_communication(instrument):
    # bad='OK' means it returns False if the communication went through
    with visa_context(bad='OK') as res:
        id = instrument.query('*idn?')
    res = res if res[0] else False
    return res

class dictAttr(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    def copy(self):
        return dictAttr(self)

def _test_cross_other_side(rsrc_manager_path, instr_name, event, pipe):
    rm = get_resource_manager(rsrc_manager_path)
    #pipe.send(visa_lib_info(rm))
    #print 'subprocess started'
    res, state, instr = _test_open_instr(rm, instr_name)
    pipe.send([res, state])
    if not res:
        return
    event.wait()
    event.clear()
    #print 'subprocess stage2'
    pipe.send(_test_lock_comm(instr, exclusive=False))
    event.wait()
    event.clear()
    #print 'subprocess stage3'
    pipe.send(_test_lock_comm(instr, exclusive=True))
    event.wait()
    event.clear()
    #print 'subprocess stage4'
    pipe.send(_test_lock_comm(instr, comm=True))
    event.wait()
    event.clear()
    #print 'subprocess stage5'
    pipe.send(_test_lock_comm(instr, exclusive=False))
    event.wait()
    event.clear()
    #print 'subprocess stage6'
    pipe.send(_test_lock_comm(instr, exclusive=True))
    event.wait()
    event.clear()
    #print 'subprocess stage7'
    pipe.send(_test_lock_comm(instr, comm=True))
    #print 'subprocess finished'


def _test_open_instr(rsrc_manager, instr_name, pipe=None):
    """ Returns [succes_bool, error_string, instr] """
    from multiprocessing import Process
    if isinstance(rsrc_manager, Process):
        return pipe.recv() + [None]
    else:
        instr = None
        with visa_context() as res:
           instr = rsrc_manager.open_resource(instr_name)
        return res + [instr]


def _test_lock_comm(instr, event=None, pipe=None, exclusive=False, comm=False):
    from multiprocessing import Process
    if isinstance(instr, Process):
        # The other end should do the proper sequence of tests.
        event.set()
        res = pipe.recv()
    else:
        if comm == False:
            res = _test_lock(instr, exclusive)
            if res == False: # lock went through
                instr.unlock()
        else:
            res = _test_lock_communication(instr)
    return res

_base_cross_result = dictAttr(
        shared_blocks_shared = False,
        shared_blocks_excl = False,
        shared_blocks_comm = False,
        excl_blocks_shared = False,
        excl_blocks_excl = False,
        excl_blocks_comm = False)

def _test_cross_show_diff(result):
    if isinstance(result, basestring):
        # there was an error, just return it
        return result
    if len(result) != len(_base_cross_result):
        raise RuntimeError('the dictionnaries are incompatible in cross_show_diff')
    only_diff = {k:result[k] for k in result if result[k] != _base_cross_result[k]}
    if only_diff == {}:
        return 'Same as default'
    return only_diff


def _test_cross_lib_helper(i1, i2, event=None, pipe=None):
    from multiprocessing import Process
    if isinstance(i2, Process):
        if event is None or pipe is None:
            raise RuntimeError('You need event and pipe when i2 is a Process')
        success, error, instr = _test_open_instr(i2, '', pipe)
        if not success:
            return "Failure, can't open second instrument remotely, error: %s"%error
    results = _base_cross_result.copy()
    res = _test_lock(i1, exclusive=False)
    if res != False: # It did not lock
        if isinstance(i2, Process):
            i2.terminate()
        raise RuntimeError('Unable to make initial shared lock on: %s'%res[1])
    results.shared_blocks_shared = _test_lock_comm(i2, event, pipe, exclusive=False)
    results.shared_blocks_excl = _test_lock_comm(i2, event, pipe, exclusive=True)
    results.shared_blocks_comm = _test_lock_comm(i2, event, pipe, comm=True)
    i1.unlock()
    res = _test_lock(i1, exclusive=True)
    if res != False:
        if isinstance(i2, Process):
            i2.terminate()
        raise RuntimeError('Unable to make exclusive lock on: %s'%res[1])
    results.excl_blocks_shared = _test_lock_comm(i2, event, pipe, exclusive=False)
    results.excl_blocks_excl = _test_lock_comm(i2, event, pipe, exclusive=True)
    results.excl_blocks_comm = _test_lock_comm(i2, event, pipe, comm=True)
    i1.unlock()
    return results


def test_cross_lib(visa_name, rsrc_manager_path1=agilent_path, rsrc_manager_path2='', mode='both'):
    """
    Try this for a device on gpib, lan and usb.
    It will probably not work for serial (only one visalib can access
    a serial device at a time).
    mode can be 'both', 'remote' or 'local' (but for old interface it is disregarded and will only do remote)
    """
    if old_interface:
        mode = 'remote'
    rsrc_manager1 = get_resource_manager(rsrc_manager_path1)
    R1 = visa_lib_info(rsrc_manager1)
    success, error, i1 = _test_open_instr(rsrc_manager1, visa_name)
    if not success:
        raise RuntimeError('Unable to open first instrument. visa_name: %s, R1:%s, error: %s'%(visa_name, R1, error))
    serial = i1.is_serial()
    if mode in ['both', 'remote']:
        from multiprocessing import Process, Event, Pipe
        plocal, premote = Pipe()
        event = Event()
        process = Process(target=_test_cross_other_side, args=(rsrc_manager_path2, visa_name, event, premote))
        with subprocess_start():
            process.start()
        R12R = _test_cross_lib_helper(i1, process, event, plocal)
        process.join()
    rsrc_manager2 = get_resource_manager(rsrc_manager_path2)
    if mode == 'remote':
        del i1
        del rsrc_manager1
    R2 = visa_lib_info(rsrc_manager2)
    print 'visa=', visa_name
    print 'R1=', R1
    print 'R2=', R2
    print 'Default result (no locking accross visalib):', _base_cross_result
    success, error, i2 = _test_open_instr(rsrc_manager2, visa_name)
    if not success:
        print 'Unable to open instrument(%s) locally on second manager(%s) because of error: %s'%(visa_name, R2, error)
        # show only result possible:
        if mode == 'local':
            print 'No result possible'
        else:
            print 'R1->R2(remote):', R12R
        return
    if mode in ['both', 'remote']:
        plocal, premote = Pipe()
        event.clear()
        process = Process(target=_test_cross_other_side, args=(rsrc_manager_path1, visa_name, event, premote))
        with subprocess_start():
            process.start()
        R21R = _test_cross_lib_helper(i2, process, event, plocal)
        process.join()
    if mode in ['both', 'local']:
        R12L = _test_cross_lib_helper(i1, i2)
        R21L = _test_cross_lib_helper(i2, i1)
    if mode == 'both':
        if R12R == R12L:
            print 'R1->R2(remote/local):', _test_cross_show_diff(R12R)
        else:
            print 'R1->R2(remote):', _test_cross_show_diff(R12R), ' (local):', _test_cross_show_diff(R12L)
        if R21R == R21L:
            print 'R2->R1(remote/local):', _test_cross_show_diff(R21R)
        else:
            print 'R2->R1(remote):', _test_cross_show_diff(R21R), ' (local):', _test_cross_show_diff(R12L)
    elif mode == 'local':
        print 'R1->R2(local):', _test_cross_show_diff(R12L)
        print 'R2->R1(local):', _test_cross_show_diff(R21L)
    else: #remote only
        print 'R1->R2(remote):', _test_cross_show_diff(R12R)
        print 'R2->R1(remote):', _test_cross_show_diff(R21R)


def test_handlers_events(rsrc_manager, visa_name):
    """
    Try this for a device on gpib, lan, usb and serial.

    """
    print 'visa=', visa_name
    print 'R1=', visa_lib_info(rsrc_manager)
    instr = rsrc_manager.open_resource(visa_name)
    # test: event and handlers at the same time
    #       service_request handlers and events
    #       exception  handlers and queue
    #       completion  handlers and queue

def test_gpib_handlers_events(rsrc_manager, visa_name1, visa_name2):
    """
    Try this for both devices on gpib.

    """
    i1 = rsrc_manager.open_resource(visa_name1)
    i2 = rsrc_manager.open_resource(visa_name2)
    if not (i1.is_gpib() and i2.is_gpib()):
        print 'Skipping GPIB handlers tests'
        return
    print 'visa1=', visa_name1, ' id=', i1.query('*idn?')
    print 'visa2=', visa_name2, ' id=', i2.query('*idn?')
    print 'R1=', visa_lib_info(rsrc_manager)
    # test: tests activating srq on i1, i2 works
    #       using queue, test service request interactions
    #       using handlers, test service request interactions
    #       poll?, auto-serial poll?


def test_usb_resource_list(rsrc_manager):
    print 'R1=', visa_lib_info(rsrc_manager)


def test_all(rsrc_manager1, rsrc_manager2, visa_name1, visa_name2, rsrc_manager_path1=agilent_path, rsrc_manager_path2=''):
    if rsrc_manager_path1 != rsrc_manager_path2:
        mng_paths = [rsrc_manager_path1, rsrc_manager_path2]
        test_cross_lib(visa_name1, rsrc_manager_path1, rsrc_manager_path2)
    else:
        print 'Skipping cross test: only one manager selescted'
        mng_paths = [rsrc_manager_path1]
    for mng_path in mng_paths:
        rsrc_manager = get_resource_manager(mng_path)
        test_usb_resource_list(rsrc_manager)
        test_handlers_events(rsrc_manager, visa_name1)
        test_gpib_handlers_events(rsrc_manager, visa_name1, visa_name2)

