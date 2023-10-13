# -*- coding: utf-8 -*-

########################## Copyrights and license ############################
#                                                                            #
# Copyright 2011-2023  Christian Lupien <christian.lupien@usherbrooke.ca>    #
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

from __future__ import absolute_import, print_function, division

import glob
import os
import os.path
from os.path import join as pjoin, isdir, isfile, pathsep
import re
import sys
import warnings

from .comp2to3 import is_py2
if is_py2:
    from ConfigParser import SafeConfigParser as ConfigParser
    from imp import load_source
else:
    from configparser import ConfigParser
    import importlib.util
    def load_source(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        init = False
        if name in sys.modules:
            module = sys.modules[name]
        else:
            init = True
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except:
            if init:
                try:
                    del sys.modules[name]
                except KeyError:
                    pass
            raise
        # reorder import entries
        module = sys.modules.pop(name)
        sys.modules[name] = module
        return module

CONFIG_DIR = 'pyHegel'
CONFIG_DOT_DIR = '.pyHegel'
CONFIG_VENDOR = 'UdeS_Reulet'

CONFIG_ENV = 'PYHEGELDIR'

try:
    PYHEGEL_DIR
except NameError:
    # only change this on first run. On reload use the previous one
    # This is necessary if the __file__ was relative and the working
    # directory has changed
    PYHEGEL_DIR = os.path.abspath(os.path.dirname(__file__))

# Could also use pkg_resources resource_string
#  see http://peak.telecommunity.com/DevCenter/PythonEggs#accessing-package-resources
# from pkg_resources import resource_filename
# DEFAULT_CONFIG_PATH = resource_string('pyHegel', DEFAULT_CONFIG_NAME)
#  or rewrite code to use resource_stream or resource_string

CONFIG_NAME = 'pyHegel.ini'
DEFAULT_CONFIG_NAME = 'pyHegel_default.ini'
DEFAULT_CONFIG_PATH = pjoin(PYHEGEL_DIR, DEFAULT_CONFIG_NAME)
LOCAL_CONFIG = 'pyHegel.local_config'
LOCAL_CONFIG_FILE = 'local_config.py'
DEFAULT_LOCAL_CONFIG_PATH = pjoin(PYHEGEL_DIR, 'local_config_template.py')

INSTRUMENTS_BASE = 'pyHegel.instruments'

USER_HOME = os.path.expanduser('~')
DEFAULT_USER_DIR = pjoin(USER_HOME, CONFIG_DOT_DIR)

# For config file location see suggestions from https://github.com/ActiveState/appdirs
# but don't really follow them completely

# My list of choices (or on one line means the first that exists is taken, the others are skipped):
# under windows:
#   $PYHEGELDIR or windons appdata (probably ~/AppData/Roaming/UdeS_Reulet/pyHegel) or ~/.pyHegel
#   windows Common_appdata (probably c:/ProgramData/UdeS_Reulet/pyHegel)
#   pyHegel module directory
# under unix
#  if using XDG (~/.config exists)
#    $XDG_CONFIG_HOME/pyHegel or ~/.config/pyHegel or ~/.pyHegel
#    list of $XDG_CONFIG_DIRS/pyHegel or /etc/xdg/pyHegel or /etc/pyHegel
#    pyHegel module directory
#  otherwise
#   $PYHEGELDIR or ~/.pyHegel
#   /etc/pyHegel
#   pyHegel module directory

def get_windows_appdata(user=True):
    import ctypes
    from ctypes.wintypes import HWND, HANDLE, DWORD, LPCSTR
    from ctypes import HRESULT
    from ctypes import c_int
    CSIDL_COMMON_APPDATA = 0x0023
    CSIDL_APPDATA = 0x001A # roaming
    MAX_PATH = 260
    S_OK = 0x00000000
    if user:
        nfolder = CSIDL_APPDATA
    else:
        nfolder = CSIDL_COMMON_APPDATA
    path = ctypes.create_string_buffer(MAX_PATH)
    func = ctypes.windll.shell32.SHGetFolderPathA
    func.argtypes = [HWND, c_int, HANDLE, DWORD, LPCSTR]
    func.restype = HRESULT
    ret = func(None, nfolder, None, 0, path)
    S_OK
    if ret != S_OK:
        raise RuntimeError('Unable to find windows default dir (HRESULT = %#0.8x)'%ret)
    path_unicode = path.value.decode(sys.getfilesystemencoding())
    return pjoin(path_unicode, CONFIG_VENDOR, CONFIG_DIR)

def get_env_user_dir(default_user):
    default_user = os.environ.get(CONFIG_ENV, default_user)
    return default_user

def get_conf_dirs_nt():
    default_user = get_windows_appdata(user=True)
    if not isdir(default_user):
        default_user = DEFAULT_USER_DIR
    default_user = get_env_user_dir(default_user)
    default_system = get_windows_appdata(user=False)
    return [default_user, default_system]

def get_conf_dirs_posix():
    xdg_config_home = os.environ.get('XDG_CONFIG_HOME', pjoin(USER_HOME, '.config'))
    xdg_config_dirs = os.environ.get('XDG_CONFIG_DIRS', '/etc/xdg').split(':')
    default_user = DEFAULT_USER_DIR
    default_system = pjoin('/etc', CONFIG_DIR)
    paths = []
    if isdir(xdg_config_home):
        # XDG
        xdg_user = pjoin(xdg_config_home, CONFIG_DIR)
        xdg_dirs = [pjoin(d, CONFIG_DIR) for d in xdg_config_dirs]
        if isdir(xdg_user):
            default_user = xdg_user
        default_user = get_env_user_dir(default_user)
        paths.append(default_user)
        for d in xdg_dirs:
            if isdir(d):
                paths.extend(xdg_dirs)
                break
        else:
            paths.append(default_system)
    else:
        default_user = get_env_user_dir(default_user)
        paths.append(default_user)
        paths.append(default_system)
    return paths

# to detect the operating system:
# os.name: posix, nt
# sys.name startswith: linux, darwin (for mac), cygwin, win32

def get_conf_dirs(skip_module_dir=False):
    if os.name == 'nt':
        paths = get_conf_dirs_nt()
    else:
        paths = get_conf_dirs_posix()
    if not skip_module_dir:
        paths.append(PYHEGEL_DIR)
    return paths



def load_local_config():
    # Note that load_source, forces a reload of the file
    # and adds the entry in sys.modules
    paths = [pjoin(d, LOCAL_CONFIG_FILE) for d in get_conf_dirs()]
    for p in paths:
        if isfile(p):
            return load_source(LOCAL_CONFIG, p)
    # no file found, so load the default template
    print('\n'+'-'*30)
    print('WARNING: using %s template. You should create your own %s file.'%(
            LOCAL_CONFIG, LOCAL_CONFIG_FILE))
    print('see the pyHegel/local_config_template.py for more information')
    print('-'*30+'\n')
    return load_source(LOCAL_CONFIG, DEFAULT_LOCAL_CONFIG_PATH)


def load_instruments(exclude=None):
    if exclude is None:
        exclude = []
    #paths = [pjoin(d, 'instruments') for d in get_conf_dirs(skip_module_dir=True)]
    paths = [pjoin(d, 'instruments') for d in get_conf_dirs(skip_module_dir=False)]
    # move last path (within the pyHegel module) as the first so users can't override those
    # Reverse paths so we load pyHegel internal first and let user override them if needed.
    paths = paths[::-1]
    loaded = {}
    from .instruments_registry import add_to_instruments
    for p in paths:
        filenames = glob.glob(pjoin(p, '*.py'))
        for f in filenames:
            name = os.path.basename(f)[:-3] # remove .py
            if name == '__init__' or name in exclude:
                continue
            if re.match(r'[A-Za-z_][A-Za-z0-9_]*\Z', name) is None:
                raise RuntimeError('Trying to load "%s" but the name is invalid (should only contain letters, numbers and _)'%
                                    f)
            if name in loaded:
                print('Skipping loading "%s" because a module with that name is already loaded from %s'%(f, loaded[name]))
            fullname = INSTRUMENTS_BASE+'.'+name
            # instead of load_source, could do
            #  insert path in sys.path
            #   import (using importlib.import_module)
            #  remove inserted path
            # But that makes reloading more complicated
            module = load_source(fullname, f)
            loaded[fullname] = f
            add_to_instruments(name)(module)
    return loaded

class Extra_dlls(object):
    def __init__(self, paths=[]):
        """ paths is a list of paths. They need to be valid. """
        if isinstance(paths, str):
            paths = [paths]
        if hasattr(os, 'add_dll_directory'):
            self.paths = paths
        else:
            self.paths = []
        self.added_paths = []
    def __enter__(self):
        for p in self.paths:
            try:
                # Need try except because if p is not a proper directory, OSError or FileNotFountError
                # are raised.
                cookie = os.add_dll_directory(p)
            except OSError:
                warnings.warn('Warning: Path %s not added to search path because it is not valid.'%p, stacklevel=2)
            else:
                self.added_paths.append(cookie)
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        for p in self.added_paths:
            p.close()

class Addition_dll_search(object):
    def __init__(self):
        self.added_paths = {}
    def add(self, path):
        # only for windows nt
        if os.name != 'nt':
            return
        if path in self.added_paths:
            # already added, just increase count
            add_obj, already_in_path, count = self.added_paths[path]
            count += 1
        else:
            count = 1
            if hasattr(os, 'add_dll_directory'):
                try:
                    add_obj = os.add_dll_directory(path)
                except OSError:
                    warnings.warn('Warning: Path %s not added to search path because it is not valid.'%path)
                    add_obj = None
            else:
                add_obj = None
            env_path = os.environ['PATH'].split(pathsep)
            if path in env_path:
                already_in_path = True
            else:
                already_in_path = False
                env_path.append(path)
                os.environ['PATH'] = pathsep.join(env_path)
        self.added_paths[path] = (add_obj, already_in_path, count)
    def remove(self, path):
        if path not in self.added_paths:
            raise RuntimeError('Removing a path that was not added by this class: %s'%path)
        add_obj, already_in_path, count = self.added_paths[path]
        count -= 1
        if count == 0:
            del self.added_paths[path]
            if add_obj is not None:
                add_obj.close()
            if not already_in_path:
                env_path = os.environ['PATH'].split(pathsep)
                env_path.remove(path)
                os.environ['PATH'] = pathsep.join(env_path)
        else:
            self.added_paths[path] = (add_obj, already_in_path, count)
    def add_paths(self, paths):
        for p in paths:
            self.add(p)
    def remove_all(self):
        for p in self.added_paths:
            self.remove(p)
    def __del__(self):
        self.remove_all()

class PyHegel_Conf(object):
    def __init__(self):
        self.config_parser = ConfigParser()
        paths = get_conf_dirs()
        paths = [pjoin(d, CONFIG_NAME) for d in paths]
        paths.append(DEFAULT_CONFIG_PATH)
        # configparser.SafeConfigParser.read reads the files in the order given
        # so if multiple files are present, later ones overide settings in
        # earlier ones. Therefore we need the more important files last
        # however paths is in the order of more important first. So inverse.
        paths = paths[::-1]
        self._paths_used = self.config_parser.read(paths)
    @property
    def try_agilent_first(self):
        return self.config_parser.getboolean('VISA', 'try_agilent_first')
    @property
    def visa_dll_paths(self):
        paths = self.config_parser.get('VISA', 'add_dll_paths').splitlines()
        # clean up empties
        paths = [p for p in paths if p != '']
        return paths
    @property
    def extra_dll_paths(self):
        paths = self.config_parser.get('Global', 'extra_dll_paths').splitlines()
        # clean up empties
        paths = [p for p in paths if p != '']
        return paths
    @property
    def timezone(self):
        return self.config_parser.get('traces', 'timezone')

pyHegel_conf = PyHegel_Conf()
additional_dll_search = Addition_dll_search()
additional_dll_search.add_paths(pyHegel_conf.extra_dll_paths)