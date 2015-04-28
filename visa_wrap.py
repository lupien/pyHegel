# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

"""
Wrapper for pyvisa to handle both versions <1.5 and after

Created on Wed Apr 08 15:42:32 2015

@author: Christain lupien
"""

import threading
# don't export os
import os as _os

try_agilent_first = True
agilent_path = r"c:\Windows\system32\agvisa32.dll"
old_interface = True       # True when pyvisa versons < 1.5
version = "1.4"

_agilent_visa = False

# TODO read/write and redirect_instr handling of delete

try:
    import pyvisa
    try:
        import pyvisa.vpp43 as vpp43
        import pyvisa.vpp43_constants as constants
        import pyvisa.visa_exceptions as VisaIOError
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
    import pyvisa.visa as visa
    if hasattr(visa, "_removefilter_orig"):
        #print 'Skipping patch: already applied'
        return
    #print 'Installing pyvisa patch'
    visa.warnings._filters_lock_pyvisa = threading.Lock()
    def removefilter(*arg, **kwarg):
        #print 'Doing remove filter %r, %r'%(arg, kwarg)
        with visa.warnings._filters_lock_pyvisa:
            visa._removefilter_orig(*arg, **kwarg)
    def filterwarnings(*arg, **kwarg):
        #print 'Doing filter warnings %r, %r'%(arg, kwarg)
        with visa.warnings._filters_lock_pyvisa:
            visa.warnings.filterwarnings_orig(*arg, **kwarg)
    visa._removefilter_orig = visa._removefilter
    visa._removefilter = removefilter
    visa.warnings.filterwarnings_orig = visa.warnings.filterwarnings
    visa.warnings.filterwarnings = filterwarnings

def _old_load_visa(path):
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
    old_close = vpp43.visa_library().viClose
    if _os.name == 'nt' and path is None and try_agilent_first:
        try:
            vpp43.visa_library.load_library(agilent_path)
        except WindowsError: 
            print 'Unable to load Agilent visa library. Will try the default one (National Instruments?).'
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
            visa.resource_manager.close()
        except visa.VisaIOError:
            pass
        visa.resource_manager.init()

    _patch_pyvisa()
    

####################################################################
# Redirection class
####################################################################

class redirect_instr(object):
    def __init__(self, instr_instance):
        self.instr = instr_instance
    # we redirect all unknown access to self.instr
    def __getattr__(self, name):
        return getattr(self.instr, name)
    def __setattr__(self, name, value):
        if name == 'instr' or not hasattr(self.instr, name):
            super(old_Instrument, self).__setattr__(self, name, value)
        else:
            setattr(self.instr, name, value)
    def __delattr__(self, name):
        if not hasattr(self.instr, name):
            super(old_Instrument, self).__delattr__(self, name)
        else:
            delattr(self.instr, name)

####################################################################
# Instruments wrapper classes
####################################################################

class old_Instrument(redirect_instr):
    def is_serial(self):
        return isinstance(self.instr, visa.SerialInstrument)
    def is_gpib(self):
        return isinstance(self.instr, visa.GpibInstrument)
    def get_visa_attribute(self, attr):
        return vpp43.get_attribute(self.vi, attr)
    def set_visa_attribute(self, attr, state):
        vpp43.set_attribute(self.vi, attr, state)
    def lock(self, lock_type, timeout_ms):
        vpp43.lock(self.vi, lock_type, timeout_ms*1000)
    def unlock(self):
        vpp43.lock(self.vi)
    def install_visa_handler(self, event_type, handler, user_handle):
        # returns the converted user_handle
        return vpp43.install_handler(self.vi, event_type, handler, user_handle)
    def uninstall_visa_handler(self, event_type, handler, user_handle):
        # user_handle is the converted user_handle
        vpp43.uninstall_handler(self.vi, event_type, handler, user_handle)
    def enable_event(self, event_type, mechanism):
        vpp43.enable_event(self.vi, event_type, mechanism)
    def disable_event(self, event_type, mechanism):
        vpp43.disable_event(self.vi, event_type, mechanism)
    def control_ren(self, mode):
        vpp43.gpib_control_ren(self.vi, mode)

class new_Instrument(redirect_instr):
    def is_serial(self):
        return isinstance(self.instr, pyvisa.resources.SerialInstrument)
    def is_gpib(self):
        return isinstance(self.instr, pyvisa.resources.GPIBInstrument)
    def trigger(self):
        # VI_TRIG_SW is the default
        #self.set_attribute(constants.VI_ATTR_TRIG_ID, constants.VI_TRIG_SW) # probably uncessary but the code was like that
        self.assert_trigger()
    def lock(self, lock_type, timeout_ms): # timeout in ms
        self.visalib.lock(self.session, lock_type, timeout_ms)
    def enable_event(self, event_type, mechanism):
        self.visalib.enable_event(self.session, event_type, mechanism)
    def disable_event(self, event_type, mechanism):
        self.visalib.disable_event(self.session, event_type, mechanism)
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
            self.uninstall_handler(event_type, element[2], user_handle)            
        else:
            self.visalib.uninstall_handler(self.session, event_type, handler, user_handle)
    def control_ren(self, mode):
        try:
            self.instr.control_ren(mode)
        except AttributeError:
            self.visalib.viGpibControlREN(self.session, mode)


####################################################################
# Resource_manager wrapper classes
####################################################################

def _get_resource_info_helper(self, resource_name):
    normalized = alias_if_exists = None
    try:
        _, _, _, normalized, alias_if_exists = self.resource_info(resource_name)
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
        normalized1, alias_if_exists1 = self.resource_info(resource_name)
        normalized2, alias_if_exists2 = self.resource_info(resource_name.upper())
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
    def __init__(self):
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
    def resource_info(self, session, resource_name):
        """ unpacks to: interface_type, interface_board_number, resource_class, resource_name alias,
            alias is returned as None when it is empty
        """
        return vpp43.parse_resource_extended(visa.resource_manager.session,
                                               resource_name)

    get_instrument_list = _get_instrument_list

    def open_resource(self, resource_name, **kwargs):
        instr = visa.instrument(resource_name, **kwargs)
        return old_Instrument(instr)
    def is_agilent(self):
        if self._is_agilent is None:
            try:
                self._is_agilent = _visa_test_agilent(vpp43.visa_library()._handle)
            except AttributeError:
                self._is_agilent = False
        return self._is_agilent


class new_WrapResourceManager(redirect_instr):
    def __init__(self):
        super(new_WrapResourceManager, self).__init__()
        self._is_agilent = None
    if version in ['1.5', '1.6', '1.6.1', '1.6.2', '1.6.3']:
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
    def is_agilent(self):
        if self._is_agilent is None:
            try:
                self._is_agilent = _visa_test_agilent(self.visalib.lib._handle)
            except AttributeError:
                self._is_agilent = False
        return self._is_agilent
    def open_resource(self, resource_name, **kwargs):
        instr = self.instr.open_resource(resource_name, **kwargs)
        return new_Instrument(instr)

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
        except (pyvisa.errors.LibraryError, UnicodeDecodeError) as exc:
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