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
This code is used for registering instruments to the instruments module.
For visa devices that respond to IDN or are USB tmc devices, it allows to build
a database of information for them.

Non-Visa instruments can register idn, but they will not be used.
"""

from __future__ import absolute_import

from collections import defaultdict

#from . import instruments
# importing instrument is delayed to the functions that require it
# to prevent import loops.
# Just make sure That intruments_registry has been fully imported before
# import any object that depends on it.

_instruments_ids = {}
_instruments_ids_alias = {}
_instruments_ids_rev = defaultdict(list)
_instruments_usb = {}
_instruments_add = {}
_instruments_usb_names = {}

def clean_instruments():
    from . import instruments
    for name in _instruments_add:
        delattr(instruments, name)
    _instruments_add.clear()

def _add_to_instruments(some_object, name=None):
    from . import instruments
    if name is None:
        # this works for classes and functions
        name = some_object.__name__
    if _instruments_add.has_key(name):
        if _instruments_add[name] is some_object:
            # already installed
            return name
        print 'Warning: There is already a different entry "%s"=%s, overriding it with %s'%(
            name, _instruments_add[name], some_object)
    else:
        # not installed yet
        if hasattr(instruments, name):
            raise RuntimeError('There is already an attribute "%s" within the instruments package'%(name))
    setattr(instruments, name, some_object)
    _instruments_add[name] = some_object
    return name


def find_instr(manuf=None, product=None, firmware_version=None):
    """
    look for a matching instrument to the manuf, product, firmware_version
    specification. It tries a complete match first and then matches with
    instruments not specifying firmware_version, then not specifying product.
    It returns the instrument or raises KeyError.
    manuf could be the 3 element tuple
    """
    if isinstance(manuf, tuple):
        key = manuf
    else:
        key = (manuf, product, firmware_version)
    keybase = key
    try:
        return _instruments_ids[key]
    except KeyError:
        pass
    # try a simpler key
    key = key[:2]+(None,)
    try:
        return _instruments_ids[key]
    except KeyError:
        pass
    # try the simplest key
    key = (key[0], None, None)
    try:
        return _instruments_ids[key]
    except KeyError:
        raise KeyError(keybase)


def find_usb(vendor_id, product_id=None):
    """ vendor_id can be the vendor_id or a tuple of vendor_id, product_id
        The search looks for an exact match followed by a match for
        instruments only specifying vendor_id
    """
    if isinstance(vendor_id, tuple):
        key = vendor_id
    else:
        key = (vendor_id, product_id)
    keybase = key
    try:
        return _instruments_usb[key]
    except KeyError:
        pass
    # try a simpler key
    key = (key[0], None)
    try:
        return _instruments_usb[key]
    except KeyError:
        raise KeyError(keybase)


def check_instr_id(instr, idn_manuf, product=None, firmware_version=None):
    """
    idn_manuf is either the 3 element tuple (manuf, product, firmware version)
    or the value of manuf
    Returns True if there is a match found. Otherwise False.
    Note that the check works for overrides.
    If the full check does not work, it tries to see if manuf/product is correct
    then if manuf is.
    """
    if not isinstance(idn_manuf, tuple):
        idn_manuf = (idn_manuf, product, firmware_version)
    if idn_manuf in _instruments_ids_rev[instr]:
        return True
    if idn_manuf[2] is not None:
        idn_manuf = idn_manuf[:2]+(None,)
        if idn_manuf in _instruments_ids_rev[instr]:
            return True
    if idn_manuf[1] is not None:
        idn_manuf = (idn_manuf[0], None, None)
        if idn_manuf in _instruments_ids_rev[instr]:
            return True
    return False

def register_idn_alias(alias, manuf, product=None, firmware_version=None):
    """
    This adds (or overwrites a previous) entry for eithe the name of the manuf
    or the name to attach to the manuf+product, or to the manuf+product+firmware_version
    Note: the last use of this functions will be the one remembered.
          This function is called by register_instrument
    """
    key = (manuf, product, firmware_version)
    _instruments_ids_alias[key] = alias

def find_idn_alias(manuf, product=None, firmware_version=None, check_no_fw=True, retnone=False):
    """
    Finds the alias attached to the manuf/product/firmware_version combination
    given.
    With check_no_fw it will also check for just manuf/product.
    If not found, and retnone is True it returns None, otherwise it returns
    the product if given, otherwise it returns manuf.
    """
    key = (manuf, product, firmware_version)
    try:
        return _instruments_ids_alias[key]
    except KeyError:
        if check_no_fw and key[2] is not None:
            key = key[:2] + (None,)
            try:
                return _instruments_ids_alias[key]
            except KeyError:
                pass
    if product:
        return product
    else:
        return manuf


def register_usb_name(name, vendor_id, product_id=None):
    """
    This adds (or overwrites a previous) entry for either the name of the product
    or the name to attach to the product id (if given)
    Note: the last use of this functions will be the one remembered.
          This function is called by register_instrument
    If you want to use the names provided by USB, use the idn_usb for any USB visa instrument.
    """
    key = (vendor_id, product_id)
    _instruments_usb_names[key] = name

def find_usb_name(vendor_id, product_id=None, retnone=False):
    """
    Finds the name attached to a vendor_id, or to a particular vendor_id+product_id
    retnone when True returns None if the entry is not found, otherwise(default)
            it returns a default string.
    """
    key = (vendor_id, product_id)
    try:
        return _instruments_usb_names[key]
    except KeyError:
        if product_id is None:
            return 'Unknown Vendor (0x%04x)'%vendor_id
        else:
            return 'Unknown Product (0x%04x)'%product_id

####################################################################
# The following functions are(can) be used as decorators
def register_instrument(manuf=None, product=None, firmware_version=None, usb_vendor_product=None, alias=None,
                        skip_alias=False, quiet=False, skip_add=False):
    """
    If you don't specify any of the options, the instrument will only be added to the instruments
    module. It will not be searchable.
    usb_vendor_product needs to be a tuple (vendor_id, product_id), where both ids are 16 bit integers.
    product_id could be None to match all devices with vendor_id (should be rarelly used).
    Similarly you should specify manuf and product together to match them agains the returned
    values from SCPI *idn?. You can also specify firmware_version (the 4th member of idn) to only
    match instruments with that particular firmware.

    You can use multiple register_instrument decorator on an instruments.

    alias, if given, is used for register_usb_name (otherwise product or manuf is used)
           and to the ids_alias database
    quiet prevents the warning registration override
    skip_add prevents the adding of the instrument into the instruments module namespace.
    skip_alias prevents adding the alias to the usb name database (register_usb_name)
               and to the ids alias database
    """
    def _internal_reg(instr_class):
        if not skip_add:
            class_name = _add_to_instruments(instr_class)
        if manuf is not None:
            if ',' in manuf:
                raise ValueError("manuf can't contain ',' for %s"%instr_class)
            if product is not None and ',' in product:
                raise ValueError("product can't contain ',' for %s"%instr_class)
            key = (manuf, product, firmware_version)
            if not quiet and _instruments_ids.has_key(key):
                print ' Warning: Registering %s with %s to override %s'%(
                        key, instr_class, _instruments_ids[key])
            _instruments_ids[key] = instr_class
            _instruments_ids_rev[instr_class].append(key)
            if not skip_alias and alias:
                register_idn_alias(alias, manuf, product, firmware_version)
        if usb_vendor_product is not None:
            vid, pid = usb_vendor_product
            if vid<0 or vid>0xffff:
                raise ValueError('Out of range vendor id for %s'%instr_class)
            if pid is not None and (pid<0 or pid>0xffff):
                raise ValueError('Out of range product id for %s'%instr_class)
            key = (vid, pid)
            if _instruments_usb.has_key(key):
                if not quiet and _instruments_usb[key] is not instr_class:
                    print ' Warning: Registering usb %s with %s to override %s'%(
                            tuple(hex(k) for k in key), instr_class, _instruments_usb[key])
            _instruments_usb[key] = instr_class
            if not skip_alias:
                if alias:
                    name = alias
                elif product:
                    name = product
                elif manuf:
                    name = manuf
                else:
                    name = None
                if name:
                    register_usb_name(name, vid, product_id=pid)
        return instr_class
    return _internal_reg


def add_to_instruments(name=None):
    """ Use this decorator function to insert the object in the instruments
        module namespace. This is not needed if you already used
        register_instrument.
        Note that if you don't specify name, it will use the class or function name.
        For an object that does not possess a __name__ attribute, you need to
        specify name.
        When no specifyin a name, you can use it either like:
         @add_to_instruments()
         some_object....
        or:
         @add_to_instruments
         some_object....
    """
    if isinstance(name, basestring) or name is None:
        def _internal_add(some_object):
            _add_to_instruments(some_object, name)
            return some_object
        return _internal_add
    else:
        # we get here if we are called like:
        #  @add_to_instruments  # no ()
        #  some_class_or_func_def
        some_object = name
        _add_to_instruments(some_object)
        return some_object
