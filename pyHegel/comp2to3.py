# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2023-2023  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

# some of this codes comes for the module six
#   https://github.com/benjaminp/six

from __future__ import absolute_import, print_function, division
import sys
import warnings
import inspect
import types

is_py2 = sys.version_info[0] == 2
is_py3 = sys.version_info[0] == 3

def warn_deprecation(mess):
    warnings.warn(mess, warnings.DeprecationWarning)

def comp_execfile(filename, *args):
    if is_py2:
        execfile(filename, *args)
    else:
        # this break out of *args is prevent a syntax error when reading this module in python2
        # python3 accepts:
        #  exec(compile(open(filename, "rb").read(), filename, 'exec'), *args)
        N = len(args)
        if N == 0:
            exec(compile(open(filename, "rb").read(), filename, 'exec'))
        elif N == 1:
            exec(compile(open(filename, "rb").read(), filename, 'exec'), args[0])
        elif N == 2:
            exec(compile(open(filename, "rb").read(), filename, 'exec'), args[0], args[1])
        else:
            raise TypeError('Too many arguments')

if is_py2:
    import re
    _identifier_re = re.compile(r'[a-zA-Z_][a-zA-Z_0-9]*\Z')
    def isidentifier(s):
        """ python 2 identifier are ascii letters or _, and digits after the first character """
        res = _identifier_re.match(s)
        if res is None:
            return False
        return True
    def open_universal(name, mode, *args):
        mode += 'U'
        return open(name, mode, *args)
    #
    # Do the equivalent of  shutil.get_terminal_size
    #
    class Term_Size(object):
        def __init__(self, cols=80, rows=24):
            self.columns = cols
            self.lines = rows
        def __repr__(self):
            return "Term_Size(columns=%d, lines=%i)"%(self.columns, self.lines)
    import os
    import ctypes
    if os.name == 'nt':
        import ctypes.wintypes as wt
        import msvcrt
        class COORD(ctypes.Structure):
            _fields_ = [('X', wt.SHORT), ('Y', wt.SHORT)]
        class CONSOLE_SCREEN_BUFFER(ctypes.Structure):
            _fields_ = [('dwSize', COORD), ('dwCursorPosition', COORD),
                        ('wAttributes', wt.WORD), ('srWindow', wt.SMALL_RECT),
                        ('dwMaximumWindowSize', COORD)]
        GetConsoleScreenBufferInfo = ctypes.windll.kernel32.GetConsoleScreenBufferInfo
        GetConsoleScreenBufferInfo.restype = wt.BOOL
        GetConsoleScreenBufferInfo.argstype = [wt.HANDLE, ctypes.POINTER(CONSOLE_SCREEN_BUFFER)]
        def _get_terminal_size(fd):
            # This could genere IOError
            hndl = msvcrt.get_osfhandle(fd)
            csb = CONSOLE_SCREEN_BUFFER()
            if not GetConsoleScreenBufferInfo(hndl, ctypes.byref(csb)):
                return 0, 0
            #return csb.dwSize.X, csb.dwSize.Y # The Y size is the size of the buffer not the screen
            return csb.srWindow.Right - csb.srWindow.Left + 1, csb.srWindow.Bottom - csb.srWindow.Top + 1
    else:
        try:
            from termios import TIOCGWINSZ
            from fcntl import ioctl
        except ImportError:
            _get_terminal_size = lambda fd: (0, 0)
        else:
            class Term_ioctl_size(ctypes.Structure):
                _fields_ = [('ws_row', ctypes.c_ushort), ('ws_col', ctypes.c_ushort),
                            ('ws_xpixel', ctypes.c_ushort), ('ws_ypixel', ctypes.c_ushort)]
            def _get_terminal_size(fd):
                size = Term_ioctl_size()
                # this could generate an IOError
                ioctl(fd, TIOCGWINSZ, size, True)
                return size.ws_col, size.ws_row
    # this is based on the python 3 version of shutil.get_terminal_size
    def get_terminal_size(fallback=(80, 24)):
        try:
            columns = int(os.environ['COLUMNS'])
        except (KeyError, ValueError):
            columns = 0
        try:
            lines = int(os.environ['LINES'])
        except (KeyError, ValueError):
            lines = 0
        if columns <= 0 or lines <= 0:
            try:
                fd = sys.__stdout__.fileno()
                term_size = _get_terminal_size(fd)
            except (IOError, AttributeError):
                term_size = 0, 0
            if columns <= 0:
                columns = term_size[0] or fallback[0]
            if lines <= 0:
                lines = term_size[1] or fallback[1]
        return Term_Size(columns, lines)

if is_py3:
    from collections import namedtuple
    ArgSpec = namedtuple('ArgSpec', 'args varargs keywords defaults')
    def py3_inspect_getargspec(func):
        s = inspect.signature(func)
        args = []
        varargs = None
        keywords = None
        defaults = []
        for para in s.parameters.values():
            if para.kind not in [para.VAR_KEYWORD, para.VAR_POSITIONAL]:
                args.append(para.name)
            elif para.kind == para.VAR_POSITIONAL:
                varargs = para.name
            elif para.kind == para.VAR_KEYWORD:
                keywords = para.name
            elif para.default != para.empty:
                defaults.append(para.defaults)
        return ArgSpec(args, varargs, keywords, tuple(defaults))


if is_py3:
    import importlib
    import io
    from _thread import get_ident, error as thread_error
    import builtins
    reload = importlib.reload
    string_types = (str,)
    string_bytes_types = (str,bytes)
    bytes_type = bytes
    def StringIO(init=''):
        # Disable newline conversion
        return io.StringIO(init, newline='')
    unicode_type = str
    xrange = range
    string_upper = lambda s: s.upper()
    builtins_set = builtins.set
    from collections.abc import Iterator
    isidentifier = lambda s: s.isidentifier()
    inspect_getargspec = py3_inspect_getargspec
    open_universal = open
    from shutil import get_terminal_size

else:
    from StringIO import StringIO
    from thread import get_ident, error as thread_error
    import string
    import __builtin__
    reload = reload
    string_types = (basestring,)
    string_bytes_types = (basestring,)
    bytes_type = str
    unicode_type = unicode
    xrange = xrange
    string_upper = string.upper
    builtins_set = __builtin__.set
    from collections import Iterator
    inspect_getargspec = inspect.getargspec
    # This replaces the python 2 with the equivalent from python 3.
    # Note that for text this forces unicode strings
    # For text it turns on by default universal newlines mode
    # But it also handles line buffering correctly also in windows (which the
    # default open does not because windows does not do line buffering).
    # It also allows using a encoding.
    import io
    open = io.open

open_utf8 = lambda *args, **kwargs: open(*args, encoding='utf-8')

def fu(s, encoding='utf-8'):
    """ Make sure string is unicode """
    if isinstance(s, bytes_type):
        return s.decode(encoding)
    else:
        return s

def fb(b, encoding='utf-8'):
    """ Make sure string is byte """
    if isinstance(b, unicode_type):
        return b.encode(encoding)
    else:
        return b

def write_unicode_byte(f, s):
    f.write(fu(s))

def make_str(s, encoding='utf-8'):
    """ returns str in python2 (bytes) and str in python3 (unicode) """
    if is_py2:
        return fb(s, encoding=encoding)
    else:
        return fu(s, encoding=encoding)

# This is taken from the module six
#  https://github.com/benjaminp/six/
# Copyright (c) 2010-2020 Benjamin Peterson
def with_metaclass(meta, *bases):
    """Create a base class with a metaclass."""
    # This requires a bit of explanation: the basic idea is to make a dummy
    # metaclass for one level of class instantiation that replaces itself with
    # the actual metaclass.
    class metaclass(type):

        def __new__(cls, name, this_bases, d):
            if sys.version_info[:2] >= (3, 7):
                # This version introduced PEP 560 that requires a bit
                # of extra care (we mimic what is done by __build_class__).
                resolved_bases = types.resolve_bases(bases)
                if resolved_bases is not bases:
                    d['__orig_bases__'] = bases
            else:
                resolved_bases = bases
            return meta(name, resolved_bases, d)

        @classmethod
        def __prepare__(cls, name, this_bases):
            return meta.__prepare__(name, bases)
    return type.__new__(metaclass, 'temporary_class', (), {})

