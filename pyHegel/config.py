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

import imp
import glob
import os
import os.path
from os.path import join as pjoin, isdir, isfile
import re

from .comp2to3 import configparser

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
    from ctypes.wintypes import HWND, HANDLE, HRESULT, DWORD, LPCSTR
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
    return pjoin(path.value, CONFIG_VENDOR, CONFIG_DIR)

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
    # Note that imp.load_source, forces a reload of the file
    # and adds the entry in sys.modules
    paths = [pjoin(d, LOCAL_CONFIG_FILE) for d in get_conf_dirs()]
    for p in paths:
        if isfile(p):
            return imp.load_source(LOCAL_CONFIG, p)
    # no file found, so load the default template
    print('\n'+'-'*30)
    print('WARNING: using %s template. You should create your own %s file.'%(
            LOCAL_CONFIG, LOCAL_CONFIG_FILE))
    print('see the pyHegel/local_config_template.py for more information')
    print('-'*30+'\n')
    return imp.load_source(LOCAL_CONFIG, DEFAULT_LOCAL_CONFIG_PATH)


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
            # instead of imp.load_source, could do
            #  insert path in sys.path
            #   import (using importlib.import_module)
            #  remove inserted path
            # But that makes reloading more complicated
            module = imp.load_source(fullname, f)
            loaded[fullname] = f
            add_to_instruments(name)(module)
    return loaded


class PyHegel_Conf(object):
    def __init__(self):
        self.config_parser = configparser.SafeConfigParser()
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
    def timezone(self):
        return self.config_parser.get('traces', 'timezone')

pyHegel_conf = PyHegel_Conf()
