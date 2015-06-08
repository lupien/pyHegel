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

from __future__ import absolute_import

import ConfigParser
import imp
import os
import os.path
from os.path import join as pjoin

CONFIG_DIR = 'pyHegel'
CONFIG_DOT_DIR = '.pyHegel'

try:
    PYHEGEL_DIR
except NameError:
    # only change this on first run. On reload use the previous one
    # This is necessary if the __file__ was relative and the working
    # directory has changed
    PYHEGEL_DIR = os.path.absolute(os.path.dirname(__file__))

CONFIG_NAME = 'pyHegel.ini'
DEFAULT_CONFIG_NAME = 'pyHegel_default.ini'
DEFAULT_CONF = pjoin(PYHEGEL_DIR, DEFAULT_CONFIG_NAME)
DEFAULT_LOAD_CONF = pjoin(PYHEGEL_DIR, 'load_config_template.py')

defaults = ConfigParser.SafeConfigParser()
config_parser = ConfigParser.SafeConfigParser()

USER_HOME = os.path.expanduser('~')

config_parser.read([])

# For config file location see suggestions from https://github.com/ActiveState/appdirs
# but don't really follow them completely

# My list of choices:
# under windows:
#   $PYHEGELDIR or ~/.pyHegel
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

def get_conf_dirs_nt():
    # might add CSIDL_COMMON_APPDATA (0x0023), CSIDL_APPDATA (0x001A, roaming)
    #     using SHGetFolderPath
    default_user = pjoin(USER_HOME, CONFIG_DOT_DIR)
    default_user = os.environ.get('PYHEGELDIR', default_user)
    return [default_user, PYHEGEL_DIR]

def get_conf_dirs_posix():
    xdg_config_home = os.environ.get('XDG_CONFIG_HOME', pjoin(USER_HOME, '.config'))
    xdg_config_dirs = os.environ.get('XDG_CONFIG_DIRS', '/etc/xdg').split(':')
    default_user = pjoin(USER_HOME, CONFIG_DOT_DIR)
    default_system = pjoin('/etc', CONFIG_DIR)
    paths = []
    if os.path.isdir(xdg_config_home):
        # XDG
        xdg_user = pjoin(xdg_config_home, CONFIG_DIR)
        xdg_dirs = [pjoin(d, CONFIG_DIR) for d in xdg_config_dirs]
        if os.path.isdir(xdg_user):
            paths.append(xdg_user)
        else:
            paths.append(default_user)
        for d in xdg_dirs:
            if os.path.isdir(d):
                paths.extend(xdg_dirs)
                break
        else:
            paths.append(default_system)
    else:
        paths.append(default_user)
        paths.append(default_system)
    paths.append(PYHEGEL_DIR)
    return paths

# to detect the operating system:
# os.name: posix, nt
# sys.name startswith: linux, darwin (for mac), cygwin, win32

def get_conf_dirs():
    if os.name == 'nt':
        return get_conf_dirs_nt()
    else:
        return get_conf_dirs_posix()



def load_config():
    # Note that imp.load_source, forces a reload of the file
    # and adds the entry in sys.modules
    paths = [pjoin(d, 'load_config.py') for d in get_conf_dirs()]
    for p in paths:
        if os.path.isfile(p):
            return imp.load_source('load_config', p)
    # no file found
    print 'WARNING: using load_config template. You should create your own load_config.py file.'
    return imp.load_source('load_config', DEFAULT_LOAD_CONF)

def load_instruments():
    pass


