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

from __future__ import absolute_import

# don't export threading, warnings, os
import threading as _threading
import warnings as _warnings
import os as _os
from ctypes import byref as _byref
from math import isinf as _isinf
from distutils.version import LooseVersion

from . import config

#try_agilent_first = True
try_agilent_first = config.pyHegel_conf.try_agilent_first
agilent_path = r"c:\Windows\system32\agvisa32.dll"
old_interface = True       # True when pyvisa versons < 1.5
version = "1.4"

_agilent_visa = False

def is_version(lower=None, upper=None):
    """
    Return True if the pyvisa version is between lower and upper
    including either limit if given.
    Otherwise returns False
    """
    if lower is None and upper is None:
        raise RuntimeError('You need to specify at least one of upper or lower')
    current_version = LooseVersion(version)
    if current_version < LooseVersion(lower):
        return False
    if current_version > LooseVersion(upper):
        return False
    return True


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
    class InterfaceType(object):
        gpib = constants.VI_INTF_GPIB
        asrl = constants.VI_INTF_ASRL
        try:
            pxi = constants.VI_INTF_PXI
        except:
            pxi = 5
        usb = constants.VI_INTF_USB
        tcpip = constants.VI_INTF_TCPIP
    constants.InterfaceType = InterfaceType

def _add_missing_attributes_new():
    # needed for tests
    def not_attr(s):
        id = getattr(constants, s)
        return not pyvisa.attributes.AttributesByID.has_key(id)
    #if is_version('1.5', '1.7'):
    if not_attr('VI_ATTR_EVENT_TYPE'):
        #class _AttrVI_ATTR_EVENT_TYPE(pyvisa.attributes.EnumAttribute):
        class AttrVI_ATTR_EVENT_TYPE(pyvisa.attributes.IntAttribute):
            """ Provides the event type in all event contexts.
            """
            resources = []
            py_name = ''
            visa_name = 'VI_ATTR_EVENT_TYPE'
            visa_type = 'ViEventType'
            default = pyvisa.attributes.NotAvailable
            read, write, local = True, False, False
            #enum_type = constants.EventType
    if not_attr('VI_ATTR_STATUS'):
        class AttrVI_ATTR_STATUS(pyvisa.attributes.EnumAttribute):
            """ Provides the status for the source of the exception in event contexts.
            """
            resources = []
            py_name = ''
            visa_name = 'VI_ATTR_STATUS'
            visa_type = 'ViStatus'
            default = pyvisa.attributes.NotAvailable
            read, write, local = True, False, False
            enum_type = constants.StatusCode
    if not_attr('VI_ATTR_OPER_NAME'):
        class AttrVI_ATTR_OPER_NAME(pyvisa.attributes.Attribute):
            """ Provides the operation name for the source of the exception in event contexts.
            """
            resources = []
            py_name = ''
            visa_name = 'VI_ATTR_OPER_NAME'
            visa_type = 'ViString'
            default = pyvisa.attributes.NotAvailable
            read, write, local = True, False, False


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
        _add_missing_attributes_new()

except ImportError as exc:
    # give a dummy visa to handle imports
    pyvisa = None
    print 'Error importing pyVisa (not installed). You will have reduced functionality.'


def _get_lib_properties(libraryHandle):
    import win32api
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
    company = _visa_lib_properties['company'].lower()
    #print company
    if 'agilent' in company or 'keysight' in company:
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
    if path=None: obeys the try_agilent_first. If try_agilent_first is True
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

def _read_helper(self, termination='default', chunk_size=None):
    # For old: improved termination handling, matches new interface
    # For new: overides the resource read to remove handling of encoding and add stripping of termination
    #          It does not change the hardware termination handling
    termination = self.read_termination if termination == 'default' else termination
    return _strip_termination(self.read_raw(size=chunk_size), termination)

def _read_raw_n_all_helper(self, count, chunk_size=None):
    """ Read until count is obtained, possibly asking data in chunks of chunk (unless it is None)
        It will pass through ends detected because of AttrVI_ATTR_ASRL_END_IN set to
          SerialTermination.termination_char
    """
    if chunk_size is None:
        chunk_size = count
    n_read = 0
    result = bytearray(count)
    while n_read<count:
        chunk_size = min(chunk_size, count-n_read)
        s = self.read_raw_n(chunk_size)
        n = len(s)
        result[n_read:n_read+n] = s
        n_read += n
    return result

def _query_helper(self, message, termination='default', read_termination='default', write_termination='default', raw=False, chunk_size=None):
    if termination != 'default':
        if read_termination == 'default':
            read_termination = termination
        if write_termination == 'default':
            write_termination = termination
    self.write(message, termination=write_termination)
    if raw:
        return self.read_raw(size=chunk_size)
    else:
        return self.read(termination=read_termination, chunk_size=chunk_size)

def _cleanup_timeout(timeout):
    if timeout is None or _isinf(timeout):
        timeout = constants.VI_TMO_INFINITE
    elif timeout < 1:
        timeout = constants.VI_TMO_IMMEDIATE
    elif not (1 <= timeout <= 4294967294):
        raise ValueError("timeout value is invalid")
    else:
        timeout = int(timeout)
    return timeout


class WaitResponse(object):
    """Class used in return of wait_on_event. It properly closes the context upon delete.
    """
    def __init__(self, event_type, context, ret, visalib, timed_out=False):
        if event_type == 0:
            self.event_type = None
        else:
            self.event_type = event_type
        self.context = context
        self.ret = ret
        self._visalib = visalib
        self.timed_out = timed_out
    def __del__(self):
        if self.context is not None:
            self._visalib.close(self.context)

@property
def flow_control_helper(self):
    return self.get_visa_attribute(constants.VI_ATTR_ASRL_FLOW_CNTRL)
@flow_control_helper.setter
def flow_control_helper(self, value):
    self.set_visa_attribute(constants.VI_ATTR_ASRL_FLOW_CNTRL, value)

def _get_ressource_impl_manuf_name(self):
    """
    Returns the manufacturer that implemented the library being used to access
    the ressource.
    This is useful on 64bit architecture were the conflict manager can redirect
    to different implementations
    """
    return self.get_visa_attribute(constants.VI_ATTR_RSRC_MANF_NAME)

# Important: do not use wait_for_srq
#            it enables constants.VI_EVENT_SERVICE_REQ, constants.VI_QUEUE

class old_Instrument(redirect_instr):
    CR = '\r'
    LF = '\n'
    _read_termination = None
    _write_termination = CR + LF
    def __init__(self, manager, instr_instance, **kwargs):
        super(old_Instrument, self).__init__(instr_instance)
        self.resource_manager = manager
        for k,v in kwargs.items():
            setattr(self, k, v)
        if self.is_gpib() and self.resource_class != 'INTFC':
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
    def session(self):
        return self.vi
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
    def is_usb(self):
        return self.get_visa_attribute(constants.VI_ATTR_INTF_TYPE) == constants.VI_INTF_USB
    def is_tcpip(self):
        return self.get_visa_attribute(constants.VI_ATTR_INTF_TYPE) == constants.VI_INTF_TCPIP
    def get_visa_attribute(self, attr):
        return vpp43.get_attribute(self.vi, attr)
    def set_visa_attribute(self, attr, state):
        vpp43.set_attribute(self.vi, attr, state)
    def lock_excl(self, timeout_ms):
        """
        timeout_ms is in ms or can be None or +inf for infinite
        """
        timeout_ms = self.timeout if timeout_ms == 'default' else timeout_ms
        timeout_ms = _cleanup_timeout(timeout_ms)
        vpp43.lock(self.vi, constants.VI_EXCLUSIVE_LOCK, timeout_ms)
    def lock(self, timeout_ms='default', requested_key=None):
        """ Shared lock
        """
        timeout_ms = self.timeout if timeout_ms == 'default' else timeout_ms
        timeout_ms = _cleanup_timeout(timeout_ms)
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
    read_raw_n_all = _read_raw_n_all_helper
    def read_raw(self, size=None):
        # the pyvisa one does not have the size option
        # It uses self.chunk_size internally
        if size is None:
            return self.instr.read_raw()
        orig_chunk = self.chunk_size
        try:
            self.chunk_size = size
            ret = self.instr.read_raw()
        except:
            raise
        finally:
            self.chunk_size = orig_chunk
        return ret
    def write_raw(self, message):
        vpp43.write(self.vi, message)
    write = _write_helper
    read = _read_helper
    query = _query_helper
    def flush(self, mask):
        vpp43.flush(self.vi, mask)
    get_ressource_impl_manuf_name = _get_ressource_impl_manuf_name

class new_Instrument(redirect_instr):
    #def __del__(self):
    #    print 'Deleting instrument', self.resource_name
    def __init__(self, manager, instr_instance, **kwargs):
        super(new_Instrument, self).__init__(instr_instance)
        self.resource_manager = manager
        for k,v in kwargs.items():
            setattr(self, k, v)
    def is_serial(self):
        return self.interface_type == constants.InterfaceType.asrl
        #return isinstance(self.instr, pyvisa.resources.SerialInstrument)
    def is_usb(self):
        return self.interface_type == constants.InterfaceType.usb
    def is_gpib(self):
        return self.interface_type == constants.InterfaceType.gpib
        #return isinstance(self.instr, pyvisa.resources.GPIBInstrument)
    def is_tcpip(self):
        return self.interface_type == constants.InterfaceType.tcpip
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
    if is_version('1.5', '1.6.2'):
        @property
        def interface_type(self):
            return self.visalib.parse_resource(self._resource_manager.session,
                                           self.resource_name)[0].interface_type
    if is_version('1.5', '1.7'):
        def lock_excl(self, timeout_ms='default'):
            """
            timeout_ms is in ms or can be None or +inf for infinite
            """
            timeout_ms = self.timeout if timeout_ms == 'default' else timeout_ms
            timeout_ms = _cleanup_timeout(timeout_ms)
            # could have used self.visalib.lock except that the version in 1.7 is just bad.
            self.visalib.viLock(self.session, constants.VI_EXCLUSIVE_LOCK, timeout_ms, None, None)
    if is_version('1.5', '1.6.3'):
        def lock(self, timeout_ms='default', requested_key=None):
            """ Shared lock
            """
            timeout_ms = self.timeout if timeout_ms == 'default' else timeout_ms
            timeout_ms = _cleanup_timeout(timeout_ms)
            ret = self.visalib.lock(self.session, constants.VI_SHARED_LOCK, timeout_ms, requested_key)[0]
            return ret.value
        def enable_event(self, event_type, mechanism):
            self.visalib.enable_event(self.session, event_type, mechanism)
        def disable_event(self, event_type, mechanism):
            self.visalib.disable_event(self.session, event_type, mechanism)
        def discard_events(self, event_type, mechanism):
            self.visalib.discard_events(self.session, event_type, mechanism)
    if is_version('1.5', '1.7'):
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
    if version == '1.5':
        def flush(self, mask):
            self.visalib.flush(self.session, mask)
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
    read_raw_n_all = _read_raw_n_all_helper
    get_ressource_impl_manuf_name = _get_ressource_impl_manuf_name


####################################################################
# Resource_manager wrapper classes
####################################################################

# This is a tool to check the state of the srq line, in case it is hung.
# I can't find a way to clear the SRQ of all devices on the bus (IFC, or all device clear don't work)
# So to fix a problem, either load instruments (and clear their state) or turn them off

def _get_gpib_intfc_srq_state(self, bus=0):
    name = 'GPIB%d::INTFC'%bus
    control = self.open_resource(name)
    return bool(control.get_visa_attribute(constants.VI_ATTR_GPIB_SRQ_STATE))

def _get_resource_info_helper(rsrc_manager, resource_name):
    normalized = alias_if_exists = None
    try:
        _, _, _, normalized, alias_if_exists = rsrc_manager.resource_info(resource_name)
    except AttributeError:
        # This could happen for very old visa lib that miss the viParseRsrcEx function
        # which is used by resource_info
        pass
    return normalized, alias_if_exists

def _find_normalized_alias(rsrc_manager, resource_name):
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
    normalized1, alias_if_exists1 = _get_resource_info_helper(rsrc_manager, resource_name)
    normalized2, alias_if_exists2 = _get_resource_info_helper(rsrc_manager, resource_name.upper())
    if alias_if_exists1:
        normalized, alias_if_exists = normalized1, alias_if_exists1
    elif alias_if_exists2:
        normalized, alias_if_exists = normalized2, alias_if_exists2
    else:
        normalized, alias_if_exists = normalized1, None
    # alias_if_exists is None if it was not found.
    return normalized, alias_if_exists

def _get_instrument_list(self, use_aliases=True):
    # same as old pyvisa 1.4 version of get_instrument_list except with 
    # a separated and fixed (memory leak) first part (self.list_resources)
    # and a second part modified for bad visa implementations
    # and safer truncation of "::INSTR"
    rsrcs = self.list_resources()
    # Phase two: If available and use_aliases is True, substitute the alias.
    # Otherwise, truncate the "::INSTR".
    result = []
    for resource_name in rsrcs:
        normalized, alias_if_exists = _find_normalized_alias(self, resource_name)
        if alias_if_exists and use_aliases:
            result.append(alias_if_exists)
        elif normalized and normalized.endswith('::INSTR'):
            result.append(normalized[:-7]) # This removes ::INSTR
        elif normalized:
            result.append(normalized)
        else:
            result.append(resource_name)
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
        if resource_name.lower().endswith('intfc'):
            instr = visa.Interface(resource_name, **kwargs)
        else:
            instr = visa.instrument(resource_name, **kwargs)
        if isinstance(instr, visa.SerialInstrument):
            # serials was setting term_chars to CR
            # change it to same defaults as new code (which is the general default)
            kwargs_after.setdefault('read_termination', old_Instrument._read_termination)
        kwargs_after.setdefault('timeout', 2000)
        return old_Instrument(self, instr, **kwargs_after)
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
    get_gpib_intfc_srq_state = _get_gpib_intfc_srq_state

class new_WrapResourceManager(redirect_instr):
    def __init__(self, new_rsrc_manager):
        super(new_WrapResourceManager, self).__init__(new_rsrc_manager)
        self._is_agilent = None
    if is_version('1.5', '1.6.3'):
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
        return new_Instrument(self, instr, **kwargs_after)

    get_instrument_list = _get_instrument_list
    get_gpib_intfc_srq_state = _get_gpib_intfc_srq_state


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
    if path=None: obeys the try_agilent_first.
    if path='': only load the default library, does not follow try_agilent_first
    for any other path, load it.
    In case of problem it raises ImportError
    Note that for pyvisa<1.5 only one dll can be loaded at the same time. Loading
    a new one kills the previous one (resource_manager will no longer work.)
    On windows 64 bit platform, loading visa32.dll or visa64.dll loads the conflict
    resolution layer. Therefore the actual implementation used for a loaded device
    can depend on the user selection (in the vias conflict manager).
     see get_ressource_impl_manuf_name to identify which is being used on a ressource.
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
            except ValueError:
                # If we get here we are in pyVisa 1.9.1 at least and no standard visa dll is found
                # from pyvisa.ctwrapper.highlevel.NIVisaLibrary.get_library_paths
                # This means NI visa is not installed and if agilent is installed, it is as secondary
                # so it did not create the standard names. We skip the error, it will be caught again.
                if _os.path.exists(agilent_path):
                    raise ImportError('Agilent library exists without NI base libraries.')
        if path is None:
            path = ''
        try:
            return new_WrapResourceManager(pyvisa.ResourceManager(path))
        except (pyvisa.errors.LibraryError, UnicodeDecodeError, OSError, ValueError) as exc:
            # We get OSError when no libraries are found
            # We get ValueError since 1.9.1 if no NI dll is found
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


import visa_wrap
visa_wrap.test_all('GPIB0::6', 'GPIB0::11')
# ASRL1 is a lakeshore T controller
visa_wrap.test_all('ASRL1', instr_options=dict(data_bits=7, parity=visa_wrap.constants.Parity.odd))
visa_wrap.test_all('ASRL4', instr_options=dict(data_bits=7, parity=visa_wrap.constants.Parity.odd, write_delay=.1))
visa_wrap.test_all('TCPIP::A-N9010A-20278.local')
visa_wrap.test_all('USB0::2391::2827::MY52220278::0')
"""
########################### testing code #######################################################
from contextlib import contextmanager as _contextmanager
from time import time as _time, sleep as _sleep, clock as _clock

@_contextmanager
def visa_context(ok=None, bad=None, handler=None):
    """
    ok selects the status that will produce True, all others are False
    bad selects the status that will produce False, all others are True
    Use one or the other. If neither are sets, it is the same as ok='OK'
    select one of: 'OK'(no erros), 'timeout', 'unsupported_operation', 'locked', 'io_error', 'busy',
                   'invalid_mechanism', 'invalid_event', 'unsupported_mechanism'
    """
    res = [True, '']
    error = 'OK'
    if ok is None and bad is None:
        ok = 'OK'
    if handler is not None:
        handler.reset()
    try:
        yield res
        if handler is not None and handler.exc_status is not None:
            print 'visa_context sees error:', handler.exc_status
            VisaIOError(handler.exc_status)
    except VisaIOError as exc:
        if exc.error_code == constants.VI_ERROR_TMO:
            error = 'timeout'
        elif exc.error_code == constants.VI_ERROR_NSUP_OPER:
            error = 'unsupported_operation'
        elif exc.error_code == constants.VI_ERROR_RSRC_LOCKED:
            error = 'locked'
        elif exc.error_code == constants.VI_ERROR_IO:
            error = 'io_error'
        elif exc.error_code == constants.VI_ERROR_RSRC_BUSY:
            error = 'busy'
        elif exc.error_code == constants.VI_ERROR_INV_MECH:
            error = 'invalid_mechanism'
        elif exc.error_code == constants.VI_ERROR_INV_EVENT:
            error = 'invalid_event'
        elif exc.error_code == constants.VI_ERROR_NSUP_MECH:
            error = 'unsupported_mechanism'
        elif exc.error_code == constants.VI_ERROR_INV_ACCESS_KEY:
            error = 'invalid access key'
        else:
            error = str(exc)
    except Exception as exc:
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

@_contextmanager
def subprocess_start():
    import sys
    old_arg0 = sys.argv[0]
    sys.argv[0] = ''
    try:
        yield
    finally:
        sys.argv[0] = old_arg0

def start_test(test_name):
    print '======================================================'
    print '= {:^50} ='.format(test_name)
    print '======================================================'

def visa_lib_info(rsrc_manager):
    if _os.name != 'nt':
        return 'Unknown version'
    if old_interface:
        handle = vpp43.visa_library()._handle
    else:
        handle = rsrc_manager.visalib.lib._handle
    props = _get_lib_properties(handle)
    return '{company}, {product}: {version}'.format(**props)

def _test_open_instr(rsrc_manager, instr_name, pipe=None, instr_options={}):
    """ Returns [succes_bool, error_string, instr] """
    from multiprocessing import Process
    if isinstance(rsrc_manager, Process):
        return pipe.recv() + [None]
    else:
        global _test_write_delay
        instr_options = instr_options.copy() # we don't want to change the incoming dict
        _test_write_delay = instr_options.pop('write_delay', None)
        instr = None
        with visa_context() as res:
           instr = rsrc_manager.open_resource(instr_name, **instr_options)
        return res + [instr]

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

def _test_communication(instrument, lock=False):
    # for locking a bad test means not responding to lock so
    # actually going through.
    if lock:
        kwargs = dict(bad='OK')
    else:
        kwargs = dict(ok='OK')
    with visa_context(**kwargs) as res:
        id = instrument.query('*idn?')
    if lock:
        res = res if res[0] else False
    else:
        res = res if not res[0] else True
    return res

class dictAttr(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    def copy(self):
        return dictAttr(self)

########################################################################

def _test_cross_other_side(rsrc_manager_path, instr_name, event, pipe, instr_options):
    rm = get_resource_manager(rsrc_manager_path)
    #pipe.send(visa_lib_info(rm))
    #print 'subprocess started'
    res, state, instr = _test_open_instr(rm, instr_name, instr_options=instr_options)
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
            res = _test_communication(instr, lock=True)
    return res

_base_cross_result = dictAttr(
        shared_blocks_shared = False,
        shared_blocks_excl = False,
        shared_blocks_comm = False,
        excl_blocks_shared = False,
        excl_blocks_excl = False,
        excl_blocks_comm = False)

_base_inner_result = dictAttr(
        shared_blocks_shared = [True, 'timeout'],
        shared_blocks_excl = [True, 'timeout'],
        shared_blocks_comm = [True, 'locked'],
        excl_blocks_shared = [True, 'timeout'],
        excl_blocks_excl = [True, 'timeout'],
        excl_blocks_comm = [True, 'locked'])

def _test_cross_show_diff(result, cross=True):
    base = _base_cross_result if cross else _base_inner_result
    if isinstance(result, basestring):
        # there was an error, just return it
        return result
    if len(result) != len(base):
        raise RuntimeError('the dictionnaries are incompatible in cross_show_diff')
    only_diff = {k:result[k] for k in result if result[k] != base[k]}
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


def test_cross_lib(visa_name, rsrc_manager_path1=agilent_path, rsrc_manager_path2='', mode='both', instr_options={}):
    """
    Try this for a device on gpib, lan and usb.
    It will probably not work for serial (only one visalib can access
    a serial device at a time).
    mode can be 'both', 'remote' or 'local' (but for old interface it is disregarded and will only do remote)
    """
    if rsrc_manager_path1 != rsrc_manager_path2:
        start_test('Cross library locking effects')
        cross = True
    else:
        start_test('Inner library locking effects')
        cross = False
    if old_interface and cross:
        mode = 'remote'
    rsrc_manager1 = get_resource_manager(rsrc_manager_path1)
    R1 = visa_lib_info(rsrc_manager1)
    success, error, i1 = _test_open_instr(rsrc_manager1, visa_name, instr_options=instr_options)
    if not success:
        raise RuntimeError('Unable to open first instrument. visa_name: %s, R1:%s, error: %s'%(visa_name, R1, error))
    #serial = i1.is_serial()
    if mode in ['both', 'remote']:
        from multiprocessing import Process, Event, Pipe
        plocal, premote = Pipe()
        event = Event()
        process = Process(target=_test_cross_other_side, args=(rsrc_manager_path2, visa_name, event, premote, instr_options))
        with subprocess_start():
            process.start()
        R12R = _test_cross_lib_helper(i1, process, event, plocal)
        process.join()
    rsrc_manager2 = get_resource_manager(rsrc_manager_path2)
    if mode == 'remote':
        del i1   # This might produce an ignored exception (VI_ERROR_INV_OBJECT on old_interface). That is ok.
        del rsrc_manager1
    R2 = visa_lib_info(rsrc_manager2)
    print 'visa=', visa_name
    print 'R1=', R1
    print 'R2=', R2
    if cross:
        print 'Default result (no locking accross visalib):', _base_cross_result
    else:
        print 'Default result (locking within lib, with timeouts):', _base_inner_result
    success, error, i2 = _test_open_instr(rsrc_manager2, visa_name, instr_options=instr_options)
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
        process = Process(target=_test_cross_other_side, args=(rsrc_manager_path1, visa_name, event, premote, instr_options))
        with subprocess_start():
            process.start()
        R21R = _test_cross_lib_helper(i2, process, event, plocal)
        process.join()
    if mode in ['both', 'local']:
        R12L = _test_cross_lib_helper(i1, i2)
        R21L = _test_cross_lib_helper(i2, i1)
    if mode == 'both':
        if R12R == R12L:
            print 'R1->R2(remote/local):', _test_cross_show_diff(R12R, cross)
        else:
            print 'R1->R2(remote):', _test_cross_show_diff(R12R, cross), ' (local):', _test_cross_show_diff(R12L, cross)
        if R21R == R21L:
            print 'R2->R1(remote/local):', _test_cross_show_diff(R21R, cross)
        else:
            print 'R2->R1(remote):', _test_cross_show_diff(R21R, cross), ' (local):', _test_cross_show_diff(R12L, cross)
    elif mode == 'local':
        print 'R1->R2(local):', _test_cross_show_diff(R12L, cross)
        print 'R2->R1(local):', _test_cross_show_diff(R21L, cross)
    else: #remote only
        print 'R1->R2(remote):', _test_cross_show_diff(R12R, cross)
        print 'R2->R1(remote):', _test_cross_show_diff(R21R, cross)

########################################################################

def _test_multiprocess_connect_sub(visa_name, rsrc_manager_path, pipe, instr_options={}):
    rsrc_manager = get_resource_manager(rsrc_manager_path)
    res, state, instr = _test_open_instr(rsrc_manager, visa_name, instr_options=instr_options)
    pipe.send([res, state])
    if not res:
        return
    pipe.recv() # sync1
    pipe.send(_test_communication(instr))
    _test_event(instr, 'srq', 'queue')
    _test_reset_queue(instr, high=True)
    pipe.recv() # sync2
    _test_write(instr, '*OPC')
    res = _test_wait(instr)
    # wait to give time to other side to detect event in case each sides polls
    _sleep(.2)
    stb = _test_stb(instr)&96
    _test_write(instr, '*cls')
    pipe.send((res, stb))
    # Now test if we run to quickly it will steal an event:
    _test_reset_queue(instr, high=True)
    pipe.recv() # sync3
    _test_write(instr, '*OPC')
    res = _test_wait(instr)
    stb = _test_stb(instr)&96
    _test_write(instr, '*cls')
    pipe.send((res, stb))
    # Now test what happens when multiple events are produced and detected on one
    # side what happens on the other
    pipe.recv() # sync4
    _test_reset_queue(instr, high=True)
    # once
    n = 0
    _test_write(instr, '*OPC')
    res = _test_wait(instr)
    if res == True:
        n += 1
    _test_stb(instr)
    _test_write(instr, '*cls')
    # twice
    _test_write(instr, '*OPC')
    res = _test_wait(instr)
    if res == True:
        n += 1
    _test_stb(instr)
    _test_write(instr, '*cls')
    # three times
    _test_write(instr, '*OPC')
    res = _test_wait(instr)
    if res == True:
        n += 1
    _test_stb(instr)
    _test_write(instr, '*cls')
    _test_event(instr, 'srq', 'queue', disable=True)
    pipe.send(n)
    ######################################
    # Now repeat the test but for handlers
    pipe.recv() # sync5
    c0 = _clock()
    diffs = []
    hndlr = Handlers('SRQ', instr)
    hndlr.install('srq')
    _test_event(instr, 'srq', 'handler')
    # once
    hndlr.reset()
    _test_write(instr, '*OPC')
    res = _test_wait(hndlr)
    if res == True:
        diffs.append(hndlr.last - c0)
    _test_stb(instr)
    _test_write(instr, '*cls')
    # twice
    hndlr.reset()
    _test_write(instr, '*OPC')
    res = _test_wait(hndlr)
    if res == True:
        diffs.append(hndlr.last - c0)
    _test_stb(instr)
    _test_write(instr, '*cls')
    # three times
    hndlr.reset()
    _test_write(instr, '*OPC')
    res = _test_wait(hndlr)
    if res == True:
        diffs.append(hndlr.last - c0)
    _test_stb(instr)
    _test_write(instr, '*cls')
    _test_event(instr, 'srq', 'handler', disable=True)
    hndlr.uninstall()
    pipe.send(diffs)



def test_multiprocess_connect(visa_name, rsrc_manager_path=None, instr_options={}):
    """
    Try this for a device on gpib, lan, usb and serial.
    """
    from multiprocessing import Process, Pipe
    import numpy as np
    start_test('multi process access to device (same visalib)')
    rsrc_manager = get_resource_manager(rsrc_manager_path)
    R1 = visa_lib_info(rsrc_manager)
    success, error, i1 = _test_open_instr(rsrc_manager, visa_name, instr_options=instr_options)
    if not success:
        raise RuntimeError('Unable to open local instrument. visa_name: %s, R1:%s, error: %s'%(visa_name, R1, error))
    success, error, i2local = _test_open_instr(rsrc_manager, visa_name, instr_options=instr_options)
    if not success:
        raise RuntimeError('Unable to open local instrument twice. visa_name: %s, R1:%s, error: %s'%(visa_name, R1, error))
    del i2local
    print 'visa=', visa_name
    print 'R1=', R1
    ok = True
    plocal, premote = Pipe()
    process = Process(target=_test_multiprocess_connect_sub, args=(visa_name, rsrc_manager_path, premote, instr_options))
    with subprocess_start():
        process.start()
    success, error, i2 = _test_open_instr(process, '', plocal)
    if not success:
        ok = False
        print "Failure, remote did not open, error: %s"%error
    else:
        # Both sides are open.
        res = _test_communication(i1)
        if res != True:
            print 'Failure to communicate on local: %s'%res[1]
            ok = False
        plocal.send('Proceed to remote communication test') # sync1
        res = plocal.recv()
        if res != True:
            print 'Failure to communicate on remote: %s'%res[1]
            ok = False
        # Now tests cross use of service request events
        _test_event(i1, 'srq', 'queue')
        _test_reset_queue(i1, high=True)
        plocal.send('Proceed to remote event test') # sync2
        resl1 = _test_wait(i1)
        _sleep(.3)
        stbl1 = int(_test_stb(i1))&96
        _test_write(i1, '*cls')
        resr1, stbr1 = plocal.recv()
        _test_reset_queue(i1, high=True)
        plocal.send('Proceed to steal test') # sync3
        resl2 = _test_wait(i1)
        stbl2 = int(_test_stb(i1))&96
        _test_write(i1, '*cls')
        _test_event(i1, 'srq', 'queue', disable=True)
        resr2, stbr2 = plocal.recv()
        if resr1 != True and resl1 != True:
            print '!! multi event not produced on both sides: local(%s), remote(%s)'%(resl1[1], resr1[1])
            ok = False
        elif resl1 != True:
            print '!! multi event not produced on local: %s'%(resl1[1])
            ok = False
        elif resr1 != True:
            print '!! multi event not produced on remote: %s'%(resr1[1])
            ok = False
        else:
            if stbl1 == 96 and stbr1 == 96:
                print 'multi event received properly on both (stbl=stbr=96)'
            elif (stbl1 == 96 and stbr1 == 32) or (stbl1 == 32 and stbr1 == 64):
                print '!! multi event received properly but only one with rqs set (stbl=%d, stbr=%d)'%(stbl1, stbr1)
            elif stbl1 == 0 and stbr1 == 96:
                print 'multi event received properly (stbl=0, stbr=96)'
            else:
                print '!! multi event received properly but unexpected stb (stbl=%d, stbr=%d)'%(stbl1, stbr1)
                ok = False
        if resl2 != True and resr2 != True:
            pass # Same error as above
        elif resl2 != True:
            print '!! multi event not produced on local(stolen because of polling srq): %s'%(resl2[1])
            ok = False
        elif resr2 != True:
            print '!! multi event not produced on remote(stolen because of polling srq): %s'%(resr2[1])
            ok = False
        else:
            print 'multi event not stolen (not using polling of srq) (stbl=%d, stbr=%d)'%(stbl2, stbr2)
            ok = False
        # Now test what happens for a sequence of multiple events across process
        # remote should produce 3.
        _test_reset_queue(i1, high=True)
        plocal.send('Proceed to multiple queue test') # sync4
        remote_n = plocal.recv()
        n = 0
        while _test_wait(i1) == True:
            n += 1
        n_srq = 0
        while _test_stb(i1)&0x40:
            n_srq += 1
        if remote_n != 3:
            print '!! multi queue event across process remote did not generate 3 events, instead %i (local=%i, nsrq=%i)'%(remote_n, n, n_srq)
        elif remote_n != n:
            print '! missed some multi queue event from across process. Expected 3, got %i, nsrq=%i.'%(n, n_srq)
        else:
            print 'Got the expected 3 queue events on both sides (_srq=%i)'%n_srq
        # Now redo the test but with handlers instead of queues, and the queue with a long wait.
        # so also check that the handlers in separate process are independent.
        hndlr = Handlers('SRQ', i1)
        hndlr.install('srq')
        _test_event(i1, 'srq', 'handler')
        _test_reset_queue(i1, high=True, hndlr=hndlr)
        hndlr.set_block_time(1.)
        plocal.send('Proceed to multiple handler test') # sync5
        c0 = _clock()
        remote_diffs = np.array(plocal.recv())
        diff = 0.
        n = 0
        _sleep(2.) # make sure we wait long enough so that all events went through
        if _test_wait(hndlr) == True:
            diff = hndlr.last - c0
            n = hndlr.count
        n_srq = 0
        while _test_stb(i1)&0x40:
            n_srq += 1
        _test_event(i1, 'srq', 'handler', disable=True)
        hndlr.uninstall()
        if len(remote_diffs) != 3:
            print '!! multi handler event across process remote did not generate 3 events, instead delta(s) %s (local=%i in %f s, nsrq=%i)'%(remote_diffs, n, diff, n_srq)
        elif np.any(remote_diffs>.5):
            print '!! multi handler event across process local wait blocked remote events, delta(s) %s (local=%i in %f s, nsrq=%i)'%(remote_diffs, n, diff, n_srq)
        elif len(remote_diffs) != n:
            print '! missed some multi handler event from across process. Expected 3(%s), got %i in %f s, nsrq=%i.'%(remote_diffs, n, diff, n_srq)
        else:
            print 'Got the expected 3 handler events on both sides. (remote delta: %s, local total: %f s, nsrq=%i)'%(remote_diffs, diff, n_srq)
    if ok:
        print 'Success!'
    process.join()

########################################################################

class Handlers(object):
    #def __del__(self):
    #    print 'Deleting handler', self.name
    def __init__(self, name, instr):
        import threading
        super(Handlers, self).__init__()
        self.event = threading.Event()
        self.instr = instr
        self.session = instr.session
        self.event_type = None
        self.userHandle = None
        self.name = name
        self.reset()
        self._handler_func = None
        self._exc_type = False
        self.block_time = 0.
    def install(self, event_type, userHandle=None):
        if self.event_type is not None:
            raise RuntimeError('Handler %s is already installed'%self.name)
        if event_type == 'exc':
            self._exc_type = True
        event_type = _event_type(event_type)
        if old_interface and userHandle is None:
            userHandle = 1 # old interface does not accept None
        #userHandle = 1
        self._handler_func = self.handler
        with visa_context(ok='OK') as res:
            handl = self.instr.install_visa_handler(event_type, self._handler_func, userHandle)
            self.event_type = event_type
            self.userHandle = handl
        res = res if not res[0] else True
        if res != True:
            self._handler_func = None
        return res
    def uninstall(self):
        if self.event_type is None:
            return True
        with visa_context(ok='OK', handler=self) as res:
            self.instr.uninstall_visa_handler(self.event_type, self._handler_func, self.userHandle)
        self.event_type = None
        self.userHandle = None
        self._exc_type = False
        self._handler_func = None
        res = res if not res[0] else True
        return res
    def set_block_time(self, t):
        """
        The next handler event will wait this amount of seconds before
        completing. The wait is reset after every handler call and by reset.
        So call this after a reset if you want it to work.
        """
        self.block_time = t
    def wait(self, timeout_s=1.):
        """
        returns the state. Should be True unless there is a timeout.
        """
        res = self.event.wait(timeout_s)
        if res:
            self.check()
        return res
    def reset(self):
        self.wrong_handle = False
        self.wrong_type = False
        self.wrong_cntx_type = False
        self.wrong_session = False
        self.last = 0
        self.count = 0
        self.event.clear()
        self.exc_status = None
        self.oper_name = None
        self.block_time = 0.
    def check(self):
        if self.wrong_handle:
            print 'Handler(%s) received the wrong handle'%self.name
        if self.wrong_type:
            print 'Handler(%s) received the wrong type'%self.name
        if self.wrong_cntx_type:
            print 'Handler(%s) received the wrong context type'%self.name
        if self.wrong_session:
            print 'Handler(%s) received the wrong session'%self.name
    def get_attr(self, context, attr):
        if old_interface:
            return vpp43.get_attribute(context, attr)
        else:
            return self.instr.visalib.get_attribute(context, attr)[0]
    def handler(self, session, event_type, context, userHandle):
        # context gives access to VI_ATTR_: EVENT_TYPE, MAX_QUEUE_LENGTH, RM_SESSION,
        #                                   RSRC_IMPL_VERSION, RSRC_LOCK_STATE, RSRC_MANF_ID,
        #                                   RSRC_MANF_NAME, RSRC_NAME, RSRC_SPEC_VERSION,
        #                                   USER_DATA
        #print session, event_type, context, userHandle
        if not old_interface:
            session = session.value
            context = context.value
        cntx_event_type = self.get_attr(context, constants.VI_ATTR_EVENT_TYPE)
        if event_type != self.event_type:
            self.wrong_type = True
        if cntx_event_type != event_type:
            self.wrong_cntx_type = True
        if userHandle is None and self.userHandle is not None:
            self.wrong_handle = True
        elif self.userHandle is None and userHandle is not None:
            self.wrong_handle = True
        elif userHandle is not None and userHandle.contents.value != self.userHandle.value:
            print 'Handles:', userHandle, userHandle.contents, self.userHandle
            self.wrong_handle = True
        if session != self.session:
            print 'wrong:', session, self.session
            self.wrong_session = True
        self.count += 1
        self.last = _clock()
        if self._exc_type:
            # the error will stil go through and cause the usual python exception
            # but just in case we also keep track of it here.
            status = self.get_attr(context, constants.VI_ATTR_STATUS)
            oper_name = self.get_attr(context, constants.VI_ATTR_OPER_NAME)
            self.oper_name = oper_name
            #status_str = str(status) if old_interface else str(constants.StatusCode(status))
            #print '--->> Exception Handler(%s) caught in operation %s: %s'%(self.name, oper_name, status_str)
            self.exc_status = status
            #self.instr.visalib.set_attribute(context, constants.VI_ATTR_STATUS, constants.VI_SUCCESS)
            #raise VisaIOError(status)
        if self.block_time > 0.:
            _sleep(self.block_time)
            self.block_time = 0.
        self.event.set()
        return constants.VI_SUCCESS

def _event_type(event_type):
    """ event_type is one of 'srq', 'io', 'exc' or 'all'
        can also use bad. It should produce an error
    """
    if event_type == 'srq':
        return constants.VI_EVENT_SERVICE_REQ
    elif event_type == 'io':
        return constants.VI_EVENT_IO_COMPLETION
    elif event_type == 'exc':
        return constants.VI_EVENT_EXCEPTION
    elif event_type == 'all':
        return constants.VI_ALL_ENABLED_EVENTS
    elif event_type == 'bad':
        return 0XF8
    raise RuntimeError('Invalid event_type')

def _mech(mech):
    """ queue is either 'queue', 'handler', 'suspend', or 'all', 'both'
    """
    if mech == 'queue':
        return constants.VI_QUEUE
    elif mech == 'suspend':
        return constants.VI_SUSPEND_HNDLR
    elif mech == 'all':
        return constants.VI_ALL_MECH
    elif mech == 'handler':
        return constants.VI_HNDLR
    elif mech == 'both':
        return constants.VI_HNDLR + constants.VI_QUEUE
    raise RuntimeError('Invalid mechanism')

def _test_event(instr, event_type, mech, ok='OK', disable=False, discard=False, handler=None):
    """ queue is either True, False, or 'suspend'
        if neither disable or discard are True it will do enable
    """
    mech = _mech(mech)
    tn = _event_type(event_type)
    with visa_context(ok=ok, handler=handler) as res:
        if disable:
            instr.disable_event(tn, mech)
        elif discard:
            instr.discard_events(tn, mech)
        else:
            instr.enable_event(tn, mech)
    res = res if not res[0] else True
    return res

def _test_one_event(instr, event_type):
    res = _test_event(instr, event_type, 'queue')
    if res != True:
        queue = False
        pre = '!! '
        if event_type == 'exc':
            # exception event don't handle queues
            pre = ''
        print pre+'Device does not allow %s queue events: %s'%(event_type, res[1])
    else:
        pre = ''
        if event_type == 'exc':
            pre = '!! '
        print pre+'Device allows %s queue events'%event_type
        queue = True
        res = _test_event(instr, event_type, 'queue', disable=True)
        if res != True:
            print '!!! Device does not properly disable %s queue events: %s'%(event_type, res[1])
        else:
            res = _test_event(instr, event_type, 'queue', disable=True)
            if res != True:
                print '!!! Device fails for second disable of  %s queue events: %s'%(event_type, res[1])
        res = _test_event(instr, event_type, 'queue', discard=True)
        if res != True:
            print '!!! Device does not properly discard %s queue events: %s'%(event_type, res[1])
        if event_type == 'srq':
            print '-- Testing srq queued events'
            if _test_one_srq_queue(instr):
                print 'Queued srq events worked perfectly'
    hndlr = Handlers(event_type.upper(), instr)
    res = hndlr.install(event_type)
    if res != True:
        print '!! Device does not allow %s handler: %s'%(event_type, res[1])
    else:
        res = _test_event(instr, event_type, 'handler', handler=hndlr)
        if res != True:
            print '!! Device does not allow %s handler events: %s'%(event_type, res[1])
        else:
            print 'Device allows %s handler events'%event_type
            if queue:
                res = _test_event(instr, event_type, 'queue', handler=hndlr)
                if res != True:
                    print '!! Device does not allow %s handler and queue events: %s'%(event_type, res[1])
                else:
                    print 'Device allows %s handler and queue events'%event_type
                    _test_event(instr, event_type, 'queue', disable=True, handler=hndlr)
            res = _test_event(instr, event_type, 'handler', disable=True, handler=hndlr)
            if res != True:
                print '!!! Device does not properly disable %s handler events: %s'%(event_type, res[1])
            res = _test_event(instr, event_type, 'handler', disable=True, handler=hndlr)
            if res != True:
                print '!!! Device fails for second disable of %s handler events: %s'%(event_type, res[1])
            if event_type == 'srq':
                print '-- Testing srq handler events'
                if _test_one_srq_handler(instr, hndlr):
                    print 'Handler srq events worked perfectly'
            elif event_type == 'exc':
                print '-- Testing exc handler events'
                if _test_one_exc_handler(instr, hndlr):
                    print 'Handler exc events worked perfectly'
            if queue:
                res = _test_event(instr, event_type, 'both', handler=hndlr)
                if res != True:
                    print '!! Device does not allow %s handler and queue(both) events: %s'%(event_type, res[1])
                else:
                    print 'Device allows %s handler and queue (both) events'%event_type
                    _test_event(instr, event_type, 'queue', disable=True, handler=hndlr)
                    _test_event(instr, event_type, 'handler', disable=True, handler=hndlr)
                    if event_type == 'srq':
                        print '-- Testing srq handler+queue events'
                        if _test_one_srq_handler_queue(instr, hndlr):
                            print 'Handler srq handler+events worked perfectly'
            res = _test_event(instr, event_type, 'suspend', handler=hndlr)
            if res != True:
                pre = '!! '
                if event_type == 'exc':
                    # exception event don't handle suspend handlers
                    pre = ''
                print pre+'Device does not allow %s suspend handler events: %s'%(event_type, res[1])
            else:
                print 'Device allows %s suspend handler events'%event_type
                res = _test_event(instr, event_type, 'suspend', disable=True, handler=hndlr)
                if res != True:
                    print '!!! Device does not properly disable %s suspend handler events: %s'%(event_type, res[1])
                _test_event(instr, event_type, 'handler', handler=hndlr)
                res = _test_event(instr, event_type, 'suspend', disable=True, handler=hndlr)
                if res != True:
                    print '!!! Device does not properly disable %s suspend handler for handler events: %s'%(event_type, res[1])
                _test_event(instr, event_type, 'handler', disable=True, handler=hndlr)
            res = _test_event(instr, event_type, 'suspend', discard=True, handler=hndlr)
            if res != True:
                pre = '!! '
                if event_type == 'exc':
                    # exception event don't handle suspend handlers
                    pre = ''
                print pre+'Device does not properly discard %s suspend handler events: %s'%(event_type, res[1])
        res = hndlr.uninstall()
        if res != True:
            print '!! Device does not allow uninstall of %s handler: %s'%(event_type, res[1])
    res = _test_event(instr, event_type, 'all', disable=True)
    if res != True:
        print '!!! Device does not properly disable %s events with all mechs: %s'%(event_type, res[1])
    res = _test_event(instr, event_type, 'all', discard=True)
    if res != True:
        print '!!! Device does not properly discard %s events with all mechs: %s'%(event_type, res[1])

def test_handlers_events(rsrc_manager, visa_name, instr_options={}):
    """
    Try this for a device on gpib, lan, usb and serial.
    """
    R1 = visa_lib_info(rsrc_manager)
    success, error, instr = _test_open_instr(rsrc_manager, visa_name, instr_options=instr_options)
    if not success:
        raise RuntimeError('Unable to open instrument. visa_name: %s, R1:%s, error: %s'%(visa_name, R1, error))
    start_test('General events (and handlers)')
    print 'visa=', visa_name
    print 'R1=', R1
    res = _test_event(instr, 'all', 'all', disable=True)
    if res != True:
        print '!!! Device does not allow disabling all events/mechs: %s'%res[1]
    else:
        print 'Device allows disabling all events/mechs'
    res = _test_event(instr, 'all', 'all', discard=True)
    if res != True:
        print '!!! Device does not allow discarding all events/mechs: %s'%res[1]
    else:
        print 'Device allows discarding all events/mechs'
    _test_one_event(instr, 'srq')
    _test_one_event(instr, 'io')
    _test_one_event(instr, 'exc')
    event_type = 'exc'
    hndlr1 = Handlers('EXC_1', instr)
    res = hndlr1.install(event_type)
    if res == True:
        hndlr2 = Handlers('EXC_2', instr)
        res = hndlr2.install(event_type)
        if res != True:
            print '!! Device does not allow multiple handlers: %s'%res[1]
        else:
            print 'Device allows installing multiple handlers (at least 2 for exceptions)'
            hndlr2.uninstall()
        hndlr1.uninstall()
    else:
        print '!! Unable to test multiple handlers (exception handler does not work)'

########################################################################

def _test_wait(instrument, timeout_ms=500, event_type='srq'):
    """
    returns True when it works
    or [False, reason] when not
    """
    # 500 ms is probably ok, some tcpip *opc event can take 200 ms
    if isinstance(instrument, Handlers):
        res = instrument.wait(timeout_ms/1e3)
        res = True if res else [False, 'timeout']
    else:
        event = _event_type(event_type)
        with visa_context(ok='OK') as res:
            instrument.wait_on_event(event, timeout_ms)
        res = res if not res[0] else True
    return res


_test_write_delay = None

def _test_write(instrument, message):
    """ absorbs any errors, but print an error message """
    name = instrument.resource_name
    with visa_context(ok='OK') as res:
        instrument.write(message)
    res = res if not res[0] else True
    if res != True:
        print '!! Error when writing to %s, message: %s, error: %s'%(name, message, res[1])
    if _test_write_delay is not None:
        _sleep(_test_write_delay)

def _test_query(instrument, message):
    """ absorbs any errors, but print an error message """
    name = instrument.resource_name
    ret = '0'
    with visa_context(ok='OK') as res:
        ret = instrument.query(message)
    res = res if not res[0] else True
    if res != True:
        print '!! Error when querying to %s, message: %s, error: %s'%(name, message, res[1])
    return ret

def _test_stb(instrument):
    """ absorbs any errors, but print an error message """
    name = instrument.resource_name
    ret = 0
    with visa_context(ok='OK') as res:
        ret = instrument.stb
    res = res if not res[0] else True
    if res != True:
        print '!! Error when querying status byte for %s, error: %s'%(name, res[1])
    return ret

def _test_reset_queue(instr, high=False, hndlr=None):
    name = instr.resource_name
    _test_write(instr, '*cls') # should reset the status and clear errors
    if high:
        msg = '*ese 1;*sre 96'
    else:
        msg = '*ese 1;*sre 32'
    _test_write(instr, msg)
    if hndlr:
        _test_event(instr, 'srq', 'handler', discard=True)
        hndlr.reset()
        wait_object = hndlr
    else:
        _test_event(instr, 'srq', 'queue', discard=True)
        wait_object = instr
    extras = 0
    while _test_wait(wait_object, 0) == True:
        extras += 1
        if wait_object == hndlr:
            hndlr.reset()
    if extras:
        print '!! Discard of events left %d events in queue for %s'%(extras, name)
    extras = 0
    while _test_stb(instr)&64:
        extras += 1
    if extras:
        print '!! Status byte RQS left %d events for %s'%(extras, name)
    for i in range(10): # make absolutelly certain we empty autopolled serial buffer
        _test_stb(instr)

def _test_one_srq_queue(instr):
    name = instr.resource_name
    high = False
    good = True
    _test_event(instr, 'srq', 'queue')
    _test_reset_queue(instr, high=high)
    _test_write(instr, '*OPC')
    res = _test_wait(instr)
    if res != True:
        good = False
        high = True
        low = res[1]
        _test_reset_queue(instr, high=high)
        _test_write(instr, '*OPC')
        res = _test_wait(instr)
        if res != True:
            print '!!! Device(%s) will not produce service requests, aborting: %s'%(name, res[1])
            _test_event(instr, 'srq', 'queue', disable=True)
            return good
        else:
            print '! Device(%s) requires sre 96: %s'%(name, low)
    else: # test high anyway
        high = True
        # clear previous event and start new one
        _test_stb(instr)
        _test_reset_queue(instr, high=high)
        _test_write(instr, '*OPC')
        res = _test_wait(instr)
        if res != True:
            print '!!! Device(%s) will not produce service requests when using high: %s'%(name, res[1])
            good = False
            return good
    # check discard
    _test_stb(instr)
    _test_reset_queue(instr, high=high)
    _test_write(instr, '*OPC')
    _sleep(0.500) # tcpip can be 200 ms, make sure we wait long enough
    _test_event(instr, 'srq', 'queue', discard=True)
    res = _test_wait(instr)
    if res == True:
        print '!! Device(%s) did not properly discard queued events'%name
        good = False
    _test_stb(instr)
    # check read stb, *stb
    _test_reset_queue(instr, high=high)
    _test_write(instr, '*OPC')
    _test_wait(instr)
    stb_q1 = int(_test_query(instr, '*stb?'))&96
    stb_q2 = int(_test_query(instr, '*stb?'))&96
    stb1 = _test_stb(instr)&96
    stb2 = _test_stb(instr)&96
    stb_q3 = int(_test_query(instr, '*stb?'))&96
    if stb_q1 != 96:
        print '!! Device(%s) *stb not as expected before'%name
        good = False
    if stb_q1 != stb_q2:
        print '!! Device(%s) *stb request changes the bits'%name
        good = False
    if stb1 != 96:
        print '!! Device(%s) read stb not as expected before'%name
        good = False
    if stb2&64:
        print '!! Device(%s) read stb not as expected after (no reset)'%name
        good = False
    if not stb2&32:
        print '!! Device(%s) read stb not as expected after (summary reset)'%name
        good = False
    if stb_q2 != stb_q3:
        print '!! Device(%s) *stb changed after reset'%name
        good = False
    # check *esr
    ev1 = int(_test_query(instr, '*esr?'))&1
    stb_q = int(_test_query(instr, '*stb?'))&96
    stb = _test_stb(instr)&96
    ev2 = int(_test_query(instr, '*esr?'))&1
    if not ev1:
        print '!! Device(%s) *esr was not set'%name
        good = False
    if ev2:
        print '!! Device(%s) *esr does not clear the bits'%name
        good = False
    if stb_q or stb:
        print '!! Device(%s) *stb and read_stb are incorrect after *esr reset'%name
        good = False
    # test stb/esr
    _test_reset_queue(instr, high=high)
    _test_write(instr, '*OPC')
    _test_wait(instr)
    ev = int(_test_query(instr, '*esr?'))&1
    stb_q = int(_test_query(instr, '*stb?'))&96
    stb1 = _test_stb(instr)&96
    stb2 = _test_stb(instr)&96
    if not ev:
        print '!! Device(%s) *esr was not set(2)'%name
        good = False
    if stb_q:
        print '!! Device(%s) *stb not cleared properly by *esr'%name
        good = False
    if not stb1:
        print 'Device(%s) lost read stb because of *esr (probably no autopoll: call *esr after stb)'%name
        good = False
    elif stb == 32:
        print '!! Device(%s) lost read stb RQS because of *esr'%name
        good = False
    elif stb == 64:
        print '!! Device(%s) lost summary bit for stb because of *esr'%name
        good = False
    if stb2:
        print '!! Device(%s) status not reset properly after second read after *esr'%name
        good = False
    # test *clr
    _test_reset_queue(instr, high=high)
    _test_write(instr, '*OPC')
    _test_wait(instr)
    stb_q = int(_test_query(instr, '*stb?'))&96
    if stb_q != 96:
        print '!! Device(%s) did not produce a proper service request'%name
        good = False
    _test_write(instr, '*cls')
    stb_q = int(_test_query(instr, '*stb?'))&96
    stb = _test_stb(instr)&96
    ev = int(_test_query(instr, '*esr?'))&1
    if stb_q:
        print '!! Device(%s) *cls does not reset *stb: %d'%(name, stb_q)
        good = False
    if stb:
        stb2 = _test_stb(instr)&96
        if stb2:
            print '!! Device(%s) *cls does not reset read stb(twice): %d, %d'%(name, stb, stb2)
        else:
            if stb == 96:
                print 'Device(%s) *cls does not reset read stb(single) (probably because of autopoll): %d'%(name, stb)
            else:
                print '!! Device(%s) *cls does not reset read stb(single): %d'%(name, stb)
        good = False
    if ev:
        print '!! Device(%s) *cls does not reset *esr: %d'%(name, ev)
        good = False
    _test_one_srq_queue_timing(instr)
    _test_event(instr, 'srq', 'queue', disable=True)
    return good

def _test_gpib_queue(i1, i2):
    good = True
    # already done for i1, but repeat it anyway
    if not _test_one_srq_queue(i1):
        good = False
    if not _test_one_srq_queue(i2):
        good = False
    return good

def _test_one_srq_queue_timing(instr):
    import numpy as np
    name = instr.resource_name
    high = True
    n = 0
    dts_opc = []
    dts_wait = []
    _test_reset_queue(instr, high=high)
    # Note that some system wait (0.2s) before acknowledging an
    # SRQ on tcpip (vxi-11). The instrument might wait for that ack
    # before sending the next srq. So lets wait to make sure the first one
    # is good anyway,
    _sleep(.5)
    start = _time()
    while _time()-start < 1.: # test for 1 second
        n += 1
        c0 = _clock()
        _test_write(instr, '*OPC')
        c1 = _clock()
        _test_wait(instr)
        c2 = _clock()
        _test_stb(instr)
        _test_query(instr, '*esr?')
        dts_opc.append(c1 - c0)
        dts_wait.append(c2 - c1)
    dts_opc = np.array(dts_opc)*1e3 # to ms
    dts_wait = np.array(dts_wait)*1e3
    #print dts_opc, dts_wait
    print '  Queue(%s) are called on (avg=%f, std=%f, min=%f, max=%f ms) after *OPC (count=%d)'%(
                name, dts_wait.mean(), dts_wait.std(), dts_wait.min(), dts_wait.max(), n)
    if dts_wait.max() > 100.:
        dl = dts_wait[np.where(dts_wait < 100.)]
        dh = dts_wait[np.where(dts_wait >= 100.)]
        if len(dl):
            print '  Queue(%s) event< 0.1s (avg=%f, std=%f, min=%f, max=%f ms) after *OPC (count=%d)'%(
                        name, dl.mean(), dl.std(), dl.min(), dl.max(), len(dl))
        if len(dh):
            print '  Queue(%s) event>=0.1s (avg=%f, std=%f, min=%f, max=%f ms) after *OPC (count=%d)'%(
                        name, dh.mean(), dh.std(), dh.min(), dh.max(), len(dh))
    print '  Write OPC for are take on (avg=%f, std=%f, min=%f, max=%f ms, count=%d)'%(
                dts_opc.mean(), dts_opc.std(), dts_opc.min(), dts_opc.max(), n)
    _test_stb(instr)
    _test_write(instr, '*cls')


def _test_one_srq_handler_timing(instr, hndlr):
    import numpy as np
    name = instr.resource_name
    high = True
    n = 0
    dts = []
    _test_reset_queue(instr, high=high, hndlr=hndlr)
    # Note that some system wait (0.2s) before acknowledging an
    # SRQ on tcpip (vxi-11). The instrument might wait for that ack
    # before sending the next srq. So lets wait to make sure the first one
    # is good anyway,
    _sleep(.5)
    start = _time()
    while _time()-start < 1.: # test for 1 second
        n += 1
        hndlr.reset()
        _test_write(instr, '*OPC')
        c0 = _clock()
        _test_wait(hndlr)
        _test_stb(instr)
        _test_query(instr, '*esr?')
        dts.append(hndlr.last - c0)
    dts = np.array(dts)*1e3
    #print dts
    print '  Handlers(%s) are called on (avg=%f, std=%f, min=%f, max=%f ms) after *OPC (count=%d)'%(
                name, dts.mean(), dts.std(), dts.min(), dts.max(), n)
    if dts.max() > 100.:
        dl = dts[np.where(dts < 100.)]
        dh = dts[np.where(dts >= 100.)]
        if len(dl):
            print '  Handlers(%s) event< 0.1s (avg=%f, std=%f, min=%f, max=%f ms) after *OPC (count=%d)'%(
                        name, dl.mean(), dl.std(), dl.min(), dl.max(), len(dl))
        if len(dh):
            print '  Handlers(%s) event>=0.1s (avg=%f, std=%f, min=%f, max=%f ms) after *OPC (count=%d)'%(
                        name, dh.mean(), dh.std(), dh.min(), dh.max(), len(dh))
    _test_stb(instr)
    _test_write(instr, '*cls')


def _test_one_srq_handler(instr, hndlr):
    # We presume all the results for queue apply to handlers.
    # So just tests it works.
    good = True
    name = instr.resource_name
    high = True
    _test_event(instr, 'srq', 'handler')
    _test_reset_queue(instr, high=high, hndlr=hndlr)
    _test_write(instr, '*OPC')
    res = _test_wait(hndlr)
    if res != True:
        print '!!! Device(%s) will not produce service requests for handlers: %s'%(name, res[1])
        good = False
        _test_event(instr, 'srq', 'handler', disable=True)
        return good
    _sleep(.5)
    if hndlr.count != 1:
        print '! Device(%s) produced %d events in 0.5 s'%(name, hndlr.count)
        good = False
    # Now clear the event. To be general, both of the following are needed
    _test_stb(instr)
    _test_write(instr, '*cls')
    _test_one_srq_handler_timing(instr, hndlr)
    # Now clear the event. To be general, both of the following are needed
    _test_event(instr, 'srq', 'handler', disable=True)
    return good

def _test_one_exc_handler(instr, hndlr):
    good = True
    name = instr.resource_name
    _test_event(instr, 'exc', 'handler')
    hndlr.reset()
    # Produce an error
    res = _test_event(instr, 'bad', 'handler')
    if res == True:
        print '!!! Device(%s) unable to produce error event for handlers'%(name)
        good = False
    # produce a second error
    _test_event(instr, 'bad', 'handler')
    res = _test_wait(hndlr, event_type='exc')
    if res != True:
        print '!!! Device(%s) will not produce exception event for handlers: %s'%(name, res[1])
        good = False
    _sleep(.5)
    if hndlr.count != 2:
        print '! Device(%s) produced %d exception events in 0.5 s (should be 2)'%(name, hndlr.count)
        good = False
    _test_event(instr, 'exc', 'handler', disable=True)
    return good


def _test_one_srq_handler_queue(instr, hndlr):
    # We presume all the results for queue apply to handlers.
    # So just tests it works.
    good = True
    name = instr.resource_name
    high = True
    _test_event(instr, 'srq', 'both')
    _test_reset_queue(instr, high=high, hndlr=hndlr)
    _test_reset_queue(instr, high=high)
    _test_write(instr, '*OPC')
    res = _test_wait(hndlr)
    if res != True:
        print '!!! Device(%s) will not produce srq for handlers when both: %s'%(name, res[1])
        good = False
    res = _test_wait(instr)
    if res != True:
        print '!!! Device(%s) will not produce srq for queue when both: %s'%(name, res[1])
        good = False
    res = _test_wait(instr)
    if res == True:
        print '!!! Device(%s) produced multiple srq for queue when both'%(name)
        good = False
    if hndlr.count != 1:
        print '! Device(%s) produced %d handler events for both (should be 1)'%(name, hndlr.count)
        good = False
    _test_stb(instr)
    _test_write(instr, '*cls')
    _test_event(instr, 'srq', 'both', disable=True)
    return good


def _test_gpib_handler(i1, hndlr1, i2, hndlr2):
    good = True
    # already done for i1, but repeat it anyway
    if not _test_one_srq_handler(i1, hndlr1):
        good = False
    if not _test_one_srq_handler(i2, hndlr2):
        good = False
    return good

def _test_gpib_cross(instr1, hndlr1, instr2, hndlr2, manager, force=None):
    good = True
    name1 = instr1.resource_name
    name2 = instr2.resource_name
    gpib_bus = name1.split('::')[0]
    control = manager.open_resource(gpib_bus+'::INTFC')
    high = True
    # clear both status so they don't have a chance to produce events while clearing.
    if force is not None:
        print '===> Forcing autoprobe %s'%force
        _force_autopoll(force)
    _test_write(instr2, '*cls')
    _test_write(instr1, '*cls')
    _test_event(instr1, 'srq', 'handler')
    _test_event(instr2, 'srq', 'handler')
    _test_reset_queue(instr1, high=high, hndlr=hndlr1)
    _test_reset_queue(instr2, high=high, hndlr=hndlr2)
    _test_write(instr1, '*OPC')
    _sleep(.100)
    srq1 = control.get_visa_attribute(constants.VI_ATTR_GPIB_SRQ_STATE)
    _test_query(instr1, '*esr?') # This turns off the srq line
    _sleep(.100)
    srq2 = control.get_visa_attribute(constants.VI_ATTR_GPIB_SRQ_STATE)
    _test_write(instr1, '*OPC')
    _sleep(.100)
    srq3 = control.get_visa_attribute(constants.VI_ATTR_GPIB_SRQ_STATE)
    _test_query(instr1, '*esr?')
    _sleep(.100)
    _test_stb(instr2)
    _sleep(.100)
    _test_stb(instr2)
    _sleep(.100)
    _test_stb(instr2)
    _sleep(.100)
    _test_stb(instr2)
    _sleep(.100)
    _test_stb(instr1)
    _sleep(.100)
    srq4 = control.get_visa_attribute(constants.VI_ATTR_GPIB_SRQ_STATE)
    _test_write(instr1, '*OPC')
    _sleep(.100)
    res = _test_wait(hndlr1)
    if res != True:
        print '!!! Device(%s) will not produce service requests for handlers: %s'%(name1, res[1])
        good = False
    _test_wait(hndlr2)
    #res = _test_wait(hndlr2)
    #if res == True:
    #    print 'Device(%s)received request from %s (probably no autopoll)'%(name2, name1)
    #    good = False
    # Now clear the event. To be general, all of the following 4 lines are needed
    _test_write(instr2, '*cls')
    _test_stb(instr2)
    _test_write(instr1, '*cls')
    _test_stb(instr1)
    _test_stb(instr1)
    if not srq1 and not srq2 and not srq3 and not srq4:
        print 'SRQ line sequence is that of auto serial polling'
    elif srq1 and not srq2 and srq3 and not srq4:
        print 'SRQ line sequence is that of NO auto serial polling'
    else:
        print 'SRQ line as an unknown sequence: %s'%((srq1, srq2, srq3, srq4),)
    if hndlr1.count == 3 and hndlr2.count == 0:
        print 'Only device(%s) produced 3 events (sign of autoprobe). Both instruments are independent'%name1
    elif hndlr1.count == 3 and hndlr2.count == 3:
        print 'Both devices produced 3 events (sign of not autoprobe)'
    elif hndlr1.count == 1 and hndlr2.count == 1:
        print '!! Both devices produced 1 events (sign of autoprobe enabled but not used)'
        good = False
    elif hndlr1.count == 0 and hndlr2.count == 0:
        print '!! Both devices produced no events (sign of autoprobe needed but not enabled, or polling of srq missing the change because of fast auto serial poll)'
        good = False
    else:
        print '!! Device(%s, %s) produced %d,%d events (exepected 3,0 or 3,3)'%(name1, name2, hndlr1.count, hndlr2.count)
        good = False
    # Now test what happens when both device are in Request:
    _test_reset_queue(instr1, high=high, hndlr=hndlr1)
    _test_reset_queue(instr2, high=high, hndlr=hndlr2)
    _test_write(instr1, '*OPC')
    _test_write(instr2, '*OPC')
    # with autoserial poll, both handlers should already have been called.
    # without autoserial poll, and with polling of the RQS line, every
    # read_stb call that leaves the RQS active will generate another handler
    # call after the poll delay time.
    _sleep(.100)
    _test_stb(instr2)
    _sleep(.100)
    _test_stb(instr2)
    _sleep(.100)
    _test_stb(instr2)
    _sleep(.100)
    before_stb = _clock()
    _test_stb(instr2)
    after_stb = _clock()
    _sleep(.100)
    last = hndlr1.last
    _test_stb(instr1)
    _sleep(.100)
    _test_wait(hndlr2)
    _test_wait(hndlr1)
    print '--Testing concurent SRQs'
    if hndlr1.count == 1 and hndlr2.count == 1:
        print 'Both devices produced 1 events separated by %f ms (sign of autoprobe). Both instruments are independent'%(
                 (hndlr2.last-hndlr1.last)*1e3)
    elif hndlr1.count == 5 and hndlr2.count == 5:
        print 'Both devices produced 5 events (sign of not autoprobe) . stb took %f ms, produced new event after %f ms.'%(
                (after_stb-before_stb)*1e3, (last-after_stb)*1e3)
    elif hndlr1.count == 0 and hndlr2.count == 0:
        print '!! Both devices produced no events (sign of autoprobe needed but not enabled, or polling of srq missing the change because of fast auto serial poll)'
    else:
        print '!! Device(%s, %s) produced %d,%d events (exepected 1,1 or 5,5). stb took %f ms, produced new event after %f ms.'%(
                name1, name2, hndlr1.count, hndlr2.count, (after_stb-before_stb)*1e3, (last-after_stb)*1e3)
        good = False
    _test_stb(instr1)
    _test_stb(instr1)
    _test_stb(instr1)
    _test_stb(instr1)
    _test_reset_queue(instr1, high=high, hndlr=hndlr1)
    _test_reset_queue(instr2, high=high, hndlr=hndlr2)
    _test_event(instr2, 'srq', 'handler', disable=True)
    _test_event(instr1, 'srq', 'handler', disable=True)
    return good

# To reset autopoll, at least for some version of NI,
#   need to restart the library (here in another process) and enable events.
def _reset_autopoll_helper(manager_path, visa_name, instr_options):
    manager = get_resource_manager(manager_path)
    success, error, instr = _test_open_instr(manager, visa_name, instr_options=instr_options)
    if not success:
        print "!! Reset of %s autopoll failed (can't open): %s"%(visa_name, error)
        return
    res = _test_event(instr, 'srq', 'queue')
    if res != True:
        print "!! Reset of %s autopoll failed (can't enable event): %s"%(visa_name, res[1])

def _reset_autopoll_gpib(rsrc_manager_path, visa_name, instr_options):
    manager = get_resource_manager(rsrc_manager_path)
    success, error, instr = _test_open_instr(manager, visa_name, instr_options=instr_options)
    if success and instr.is_gpib():
        from multiprocessing import Process
        process = Process(target=_reset_autopoll_helper, args=(rsrc_manager_path, visa_name, instr_options))
        with subprocess_start():
            process.start()
        process.join()
        print '  --> autopoll reset'


def test_gpib_handlers_events(rsrc_manager, rsrc_manager_path, visa_name1, visa_name2, instr_options={}, force_autopoll=None):
    """
    Try this for both devices on gpib.
    """
    R1 = visa_lib_info(rsrc_manager)
    success, error, i1 = _test_open_instr(rsrc_manager, visa_name1, instr_options=instr_options)
    if not success:
        raise RuntimeError('Unable to open first instrument. visa_name: %s, R1:%s, error: %s'%(visa_name1, R1, error))
    success, error, i2 = _test_open_instr(rsrc_manager, visa_name2, instr_options=instr_options)
    if not success:
        raise RuntimeError('Unable to open second instrument. visa_name: %s, R1:%s, error: %s'%(visa_name2, R1, error))
    start_test('GPIB events (and handlers)')
    if not (i1.is_gpib() and i2.is_gpib()):
        print '!!! Skipping GPIB handlers tests, both devices are not GPIB'
        return
    print 'visa1=', visa_name1, ' id=', i1.query('*idn?')
    print 'visa2=', visa_name2, ' id=', i2.query('*idn?')
    print 'R1=', R1
    hndlr1 = Handlers('i1', i1)
    hndlr2 = Handlers('i2', i2)
    res = hndlr1.install('srq')
    if res != True:
        print '!! Failure to install first handler, skipping gpib test'
        return
    res = hndlr2.install('srq')
    if res != True:
        print '!! Failure to install second handler, skipping gpib test'
        hndlr1.uninstall()
    if _test_gpib_queue(i1, i2):
        print 'Both separate queues work properly!'
    if _test_gpib_handler(i1, hndlr1, i2, hndlr2):
        print 'Both separate handlers work properly!'
    _test_gpib_cross(i1, hndlr1, i2, hndlr2, rsrc_manager, force=force_autopoll)
    hndlr2.uninstall()
    hndlr1.uninstall()

"""
To explore the auto-serial poll stuff (NI-488.2 gpib driver)
    http://www.ni.com/tutorial/4054/en/
Start NI MAX (Measurement ? Automation Explorer)
  See properties of GPIB-USB-HS card
     there is an autopolling option that can be toggled.
     however it does not represent the current state of the setting. To see
     that, click on "Interactive control" and type:
      ibask IbaAUTOPOLL
     To change it type
      ibconfig IbcAUTOPOLL 1
     To see the ibconfig IbcAUTOPOLL calls launch NI I/O trace
     In options deselect visa trace (otherwise, NI visa calls will not show
     the gpib trace. Agilent uses gpib directly.) Then start the trace.
     You can then search for AUTOPOLL

Observations:
  National Instruments, NIVISA_CORE: 5.1.1f0
    Always enables autopoll on first service request event enable communication
      accross all devices.
        It is only set once. To reset it requires restarting a python
        session (reinits the visa library)
    Forcing it to be disabled screws up its algorithm (the instruments RQS status
    is never changed, so it times out)
 Agilent Technologies, Agilent IO Libraries: 16.0.14518.0
    Always disables autopoll on opening a new gpib device.
    Forcing it be enabled it seems to miss most (if not all events)

"""

def _force_autopoll(enable):
    """
    This can force autopoll enable (True) or disabled (False)
    You need to be on windows, with a NI usb card for
    this to work. Also the card needs to show up as gpib0.
    """
    import subprocess
    exec_name = r"c:\Program Files (x86)\National Instruments\NI-488.2\Bin\ibic.exe"
    if enable is None:
        command = 'ibfind gpib0\nibask IbaAUTOPOLL\nquit\n'
    else:
        command = 'ibfind gpib0\nibconfig IbcAUTOPOLL %s\nibask IbaAUTOPOLL\nquit\n'%int(enable)
    pipe = subprocess.Popen(exec_name, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    #(out, err) = pipe.communicate('ibfind gpib0\nibask IbaAUTOPOLL\nquit\n')
    #(out, err) = pipe.communicate('ibfind gpib0\nibconfig IbcAUTOPOLL '+str(int(enable))+'\nquit\n')
    (out, err) = pipe.communicate(command)
    pipe.wait()
    #print 'PIPE: out', repr(out)
    current = out.split('Current Value:')[1].lstrip().split()[0]
    print '  current autopoll status now: ', bool(int(current, 16))

########################################################################

def _test_lock_cleanup_helper(visa_name, rsrc_manager_path, pipe, instr_options={}, handler=False):
    rsrc_manager = get_resource_manager(rsrc_manager_path)
    res, state, instr = _test_open_instr(rsrc_manager, visa_name, instr_options=instr_options)
    pipe.send([res, state])
    if not res:
        return
    if handler:
        if handler is True:
            event_type = 'exc'
        else:
            event_type = handler
        hndlr = Handlers('lock_test', instr)
        hndlr.install(event_type, instr)
        _test_event(instr, event_type, 'handler', handler=hndlr)
    pipe.send(_test_lock(instr, exclusive=True))

def test_lock_cleanup(visa_name, rsrc_manager_path, instr_options={}, handler=False):
    """ This tests if the visalib properly cleanups open locks
        before closing a device. If left open, the device will not be reloadable
        until a reboot.
        With handler=True, tests if not cleaning up handlers borks the visalib
         handler can also be 'srq' or 'exc' (default)
    """
    if not (handler is False or handler is True or handler == 'exc' or handler == 'srq'):
        raise ValueError("handler can only be True, False, 'exc' or 'srq'")
    from multiprocessing import Process, Pipe
    start_test('Check proper lock cleanup')
    rsrc_manager = get_resource_manager(rsrc_manager_path)
    R1 = visa_lib_info(rsrc_manager)
    print 'visa=', visa_name
    print 'R1=', R1
    plocal, premote = Pipe()
    process = Process(target=_test_lock_cleanup_helper, args=(visa_name, rsrc_manager_path, premote, instr_options, handler))
    with subprocess_start():
        process.start()
    success, error, i2 = _test_open_instr(process, '', plocal)
    if not success:
        print '!! Unable to open remote instrument, abort test: %s'%error
        process.join()
        return
    res = plocal.recv()
    process.join()
    if res != False:
        print '!! Unable to lock the remote instrument, abort test %s'%res[1]
        return
    success, error, instr = _test_open_instr(rsrc_manager, visa_name, instr_options=instr_options)
    if not success:
        print '!! Unable to open the instrument: %s'%error
    else:
        res = _test_lock(instr, exclusive=True)
        if res != False:
            print '!! Unable to obtain the lock: %s'%res[1]
        else:
            res = _test_communication(instr)
            if res != True:
                print '!! Unable to communicate with lock: %s'%res[1]
            else:
                print 'Locks are properly cleaned up!'
            instr.unlock()
            res = _test_communication(instr)
            if res != True:
                # I have seen the above work, and this fail
                # Seems to happen to NI visalib (must be some borked global lock)
                print '!! Unable to communicate without lock: %s'%res[1]

########################################################################

def _is_hex(s):
    if s.lower().startswith('0x'):
        # test it
        try:
            int(s, 16)
        except ValueError:
            print '!!! Invalid hexadecimal value'
        return True
    else:
        try:
            int(s, 10)
        except ValueError:
            print '!!! Invalid decimal value'
        return False

def _is_upper(s):
    if s.lower() == s:
        return False
    if s.upper() == s:
        return True
    print '!!! String is neither pure upper or lower. Considered lower...'
    return False

########################################################################

def test_usb_resource_list(rsrc_manager):
    """ To properly tests the aliases, you should give some to various devices
        for all visa lib being tested.
    """
    start_test('resource list')
    print 'R1=', visa_lib_info(rsrc_manager)
    lst = rsrc_manager.list_resources()
    # We will try a bunch of things to make sure the routines above will not
    # crash (raise exception).
    print 'List: ['
    for l in lst:
        normalized, alias_if_exists = _find_normalized_alias(rsrc_manager, l)
        if normalized:
            normalized2, alias_if_exists2 = _find_normalized_alias(rsrc_manager, normalized)
            if normalized != normalized2:
                print '!!! normalized string not stable: %s %s'%(normalized, normalized)
            if alias_if_exists != alias_if_exists2:
                print '!!! alias string not stable: %s %s'%(normalized, normalized)
        alias = ' (alias: %s)'%repr(alias_if_exists) if alias_if_exists else ''
        print '    %s%s'%(repr(l), alias)
    print '    ]'
    usbs = 0
    serials = 0
    upper_serial = None
    hex_vendor_product = None
    for e in lst:
        if e.lower().startswith('usb'):
            usbs += 1
            l = e.split('::')
            v = _is_hex(l[1])
            p = _is_hex(l[2])
            if v != p:
                print '!!! vendor and product not the same format for ', e
            if hex_vendor_product is None:
                hex_vendor_product = v
            elif hex_vendor_product != v:
                print '!!! vendor and product format changes accross devices'
            serial = l[3]
            if serial.upper() == serial.lower():
                pass # Not usable, not alphanumeric
            else:
                serials += 1
                up = _is_upper(serial)
                if upper_serial is None:
                    upper_serial = up
                elif upper_serial != up:
                    print '!!! serial numbers upper/lower is not constant accross devices'
    if usbs>0:
        if usbs == 1:
            print 'Only one device used (more limited tests)'
        else:
            print 'Used %d usb devices for test'%usbs
        if hex_vendor_product:
            print 'Vendor and product ids are in hexadecimal'
        else:
            print '!! Vendor and product ids are in decimal'
        if serials == 0:
            print '!! Found no usb serial numbers with alphanumeric. lower/upper untested.'
        elif upper_serial:
            print 'Found %d testable usb device, all using upper serial numbers'%serials
        else:
            print '!! Found %d testable usb device, all using lower serial numbers'%serials
    else:
        print '!!! You need some usb devices connected to the computer for futher tests.'

########################################################################

def are_mngr_diff(m1, m2):
    if _os.name == 'nt' and try_agilent_first:
        if m1 != m2 and (m1 is None or m2 is None):
            # if agilent visa is present on system, this should be different, otherwise it will be the same
            return True
    if m1 != m2:
        return True
    else:
        return False

def test_all(visa_name1, visa_name2=None, rsrc_manager_path1=agilent_path, rsrc_manager_path2='', instr_options={}, force_autopoll=None):
    """
    provide visa_name2 for gpib devices
    Note that the test will change the device event and request registers and send some commands (*idn?, *OPC, )
    Make sure that the instruments are not loaded somewhere else (this is especially important on GPIB,
    otherwise you will get locking problems (other device gpib handler locks when reading the status byte
    in pyhegel))
    Also for TCPIP (VXI-11, make sure that the firewall does not block incoming connection to the python executable
    (the scilland for agilent SICL-LAN)
    (It could affect agilent and NI differently since agilent can use a different protocol (SICL-LAN) to agilent device
     RPC program 395180 instead of 395183, and the interrupt probably works slightly differently)
    """
    start_test('-- START --')
    if are_mngr_diff(rsrc_manager_path1, rsrc_manager_path2):
        mng_paths = [rsrc_manager_path1, rsrc_manager_path2]
        test_cross_lib(visa_name1, rsrc_manager_path1, rsrc_manager_path2, instr_options=instr_options)
    else:
        print '!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!'
        print '!!! Skipping cross test: only one manager selescted'
        mng_paths = [rsrc_manager_path1]
    for mng_path in mng_paths:
        _reset_autopoll_gpib(mng_path, visa_name1, instr_options)
        test_cross_lib(visa_name1, mng_path, mng_path, instr_options=instr_options)
        test_multiprocess_connect(visa_name1, rsrc_manager_path=mng_path, instr_options=instr_options)
        rsrc_manager = get_resource_manager(mng_path)
        test_usb_resource_list(rsrc_manager)
        test_handlers_events(rsrc_manager, visa_name1, instr_options=instr_options)
        if visa_name2 is None or visa_name1 == visa_name2:
            print '!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!'
            print '!!!! Skipping multi device tests (needs visa_name2) (only for gpib)'
        else:
            test_gpib_handlers_events(rsrc_manager, mng_path, visa_name1, visa_name2, instr_options=instr_options, force_autopoll=force_autopoll)
    start_test('-- End --')

