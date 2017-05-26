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
This module contains some improved types:
 StructureImproved (ctypes Structure improvement)
 dict_improved  (OrderedDict improvement)
"""
from __future__ import absolute_import

from collections import OrderedDict
from ctypes import Structure

class _StructureImprovedMeta(Structure.__class__):
    # Using this metaclass will add a separate cache to each new subclass
    def __init__(cls, name, bases, d):
        super(_StructureImprovedMeta, cls).__init__(name, bases, d)
        cls._names_cache = [] # every sub class needs to have its own cache


class StructureImproved(Structure):
    """
    This adds to the way Structure works (structure elements are
    class attribute).
    -can also access (RW) elements with numerical ([1]) and name indexing (['key1'])
    -can get and OrderedDict from the data (as_dict method)
    -can get the number of elements (len)
    -can get a list of items, keys or values like for a dict
    -can print a more readable version of the structure
    Note that it can be initialized with positional arguments or keyword arguments.
    And changed later with update.
    You probably cannot subclass this structure (self._fields_ then only contains
    a fraction of the names.)
    """
    # TODO fix the problem of not being able to subclass (_fields_ does not habe all names)
    __metaclass__ = _StructureImprovedMeta
    _names_cache = [] # This gets overwritten but metaclass so that all subclass have their own list
    def _get_names(self):
        if self._names_cache == []:
            self._names_cache.extend([n for n,t in self._fields_])
        return self._names_cache
    _names_ = property(_get_names)
    def __getitem__(self, key):
        if not isinstance(key, basestring):
            key = self._names_[key]
        return getattr(self, key)
    def __setitem__(self, key, value):
        if not isinstance(key, basestring):
            key = self._names_[key]
        setattr(self, key, value)
    def __len__(self):
        return len(self._fields_)
    def update(self, *args, **kwarg):
        for i,v in enumerate(args):
            self[i]=v
        for k,v in kwarg:
            self[k]=v
    def as_dict(self):
        return OrderedDict(self.items())
    def items(self):
        return [(k,self[k]) for k in self._names_]
    def keys(self):
        return self._names_
    def values(self):
        return [self[k] for k in self._names_]
    def __repr__(self):
        return self.show_all(multiline=False, show=False)
    def show_all(self, multiline=True, show=True):
        strs = ['%s=%r'%(k, v) for k,v in self.items()]
        if multiline:
            ret = '%s(\n  %s\n)'%(self.__class__.__name__, '\n  '.join(strs))
        else:
            ret = '%s(%s)'%(self.__class__.__name__, ', '.join(strs))
        if show:
            print ret
        else:
            return ret


class dict_improved(OrderedDict):
    """
    This adds to the basic dict/OrderedDict syntax:
        -getting/setting/deleting with numerical indexing (obj[0])
                or with slices obj[1:3] or with list of index
                obj[[2,1,3]]. can also use list of keys (obj[['key1', 'key2']])
        -getting a regular dict/OrderedDict copy (as_dict)
        -getting/setting/deleting as attributes (obj.key)
        -adding new elements to the dict as attribute (obj.newkey=val)
         (could already do obj['newkey']=val)
    Note that it can be initialized like dict(a=1, b=2) but the order is not
    conserved: dict_improved(a=1, b=2) is the same as dict_improved(b=2, a=1) but is not the same
    as dict_improved([('b', 2), ('a', 1)]). So to recreate a dict, use the output from repr_raw
    not from str.
    show_all method shows all the entry, one per line by default.
    the option _freeze=True prevents adding/removing elements to the dict (defaults to False).
    the option _allow_overwrite=True (the default) allows overwritting existing attributes
      (the original attribute is saved as oldname_orig)
    """
    def __init__(self, *arg, **kwarg):
        freeze = kwarg.pop('_freeze', False)
        allow_overwrite = kwarg.pop('_allow_overwrite', True)
        #self._known_keys = []
        super(dict_improved, self).__setattr__('_known_keys', [])
        super(dict_improved, self).__setattr__('_dict_improved__init_complete', False)
        super(dict_improved, self).__setattr__('_freeze', freeze)
        super(dict_improved, self).__setattr__('_allow_overwrite', allow_overwrite)
        # Now check the entries
        tmp = OrderedDict(*arg, **kwarg)
        for key in tmp.keys():
            if not isinstance(key, basestring):
                raise TypeError, "You can only use strings as keys."
        # input is ok so create the object
        super(dict_improved, self).__init__(*arg, **kwarg)
        self._dict_improved__init_complete = True
    def _set_freeze(self, val):
        """
        Change the freeze state. val is True or False
        This works even when _allow_overwrite is True
        """
        super(dict_improved, self).__setattr__('_freeze', val)
    def __getattribute__(self, name):
        known = super(dict_improved, self).__getattribute__("_known_keys")
        if name in known:
            return self[name]
        else:
            return super(dict_improved, self).__getattribute__(name)
    def _setattribute_helper(self, name):
        # Check to see if use indexing (returns True) or the parent call (returns False)
        if not self._dict_improved__init_complete:
            # during init, we use parent call
            return False
        if name in self._known_keys:
            return True
        if hasattr(self, name):
            # not in known but already exists
            if self._freeze:
                # This allows changing the value directly
                return False
            if self._allow_overwrite:
                return True
        # not known and does not exist
        return True # should add it or raise an exception
    def __setattr__(self, name, value):
        if self._setattribute_helper(name):
            self[name] = value
        else:
            super(dict_improved, self).__setattr__(name, value)
    def __delattr__(self, name):
        if name in self._known_keys:
            del self[name]
        else:
            super(dict_improved, self).__delattr__(name)
    def __getitem__(self, key):
        if isinstance(key, list):
            return [self[k] for k in key]
        if not isinstance(key, basestring):
            # assume we are using an integer index
            key = self.keys()[key]
            if isinstance(key, list): # it was a slice
                return self[key]
        return super(dict_improved, self).__getitem__(key)
    def __delitem__(self, key):
        if isinstance(key, list):
            for k in key:
                del self[k]
            return
        if not isinstance(key, basestring):
            # assume we are using an integer index
            key = self.keys()[key]
            if isinstance(key, list): # it was a slice
                del self[key]
                return
        if self._freeze and key in self._known_keys:
            raise RuntimeError, "Modifying keys of dictionnary not allowed for this object."
        super(dict_improved, self).__delitem__(key)
        self._known_keys.remove(key)
        delattr(self, key)
    def __setitem__(self, key, value):
        if isinstance(key, list):
            if len(key) != len(value):
                raise RuntimeError('keys and values are not the same length.')
            for k,v in zip(key, value):
                self[k] = v
            return
        if not isinstance(key, basestring):
            # assume we are using an integer index
            key = self.keys()[key]
            if isinstance(key, list): # it was a slice
                self[key] = value
                return
        if self._dict_improved__init_complete and self._freeze and key not in self._known_keys:
            raise RuntimeError, "Modifying keys of dictionnary not allowed for this object."
        if key not in self._known_keys:
            if hasattr(self, key):
                if not self._allow_overwrite:
                    raise RuntimeError, "Replacing existing attributes not allowed for this object."
                super(dict_improved, self).__setattr__(key+'_orig', getattr(self, key))
            # add entry so tab completion sees it
            super(dict_improved, self).__setattr__(key, 'Should never see this')
            self._known_keys.append(key)
        super(dict_improved, self).__setitem__(key, value)
    def clear(self):
        if self._freeze:
            raise RuntimeError, "Modifying keys of dictionnary not allowed for this object."
        keys = self._known_keys
        del self._known_keys[:]
        for k in keys:
            delattr(self, k)
        super(dict_improved, self).clear()
    def as_dict(self, order=False):
        """
        Returns a copy in a regular dict (order=False)
        or an ordered dict copy (order=True, same as copy method).
        """
        if order:
            return OrderedDict(self)
        else:
            return dict(self)
    def show_all(self, multiline=True, show=True):
        strs = ['%s=%r'%(k, v) for k,v in self.items()]
        if multiline:
            ret = '%s(\n  %s\n)'%(self.__class__.__name__, '\n  '.join(strs))
        else:
            ret = '%s(%s)'%(self.__class__.__name__, ', '.join(strs))
        if show:
            print ret
        else:
            return ret
    def __repr__(self):
        # could use numpy.get_printoptions()['threshold']
        """ This is a simplified view of the data. Using it to recreate
            the structure would necessarily keep the order.
            Use the repr_raw method output for that."""
        return self.show_all(multiline=False, show=False)
    def repr_raw(self):
        return super(dict_improved, self).__repr__()
