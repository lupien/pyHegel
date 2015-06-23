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

import xml.etree.ElementTree as ET
import copy
import os
import os.path
import sys
import subprocess
from _winreg import QueryValue, HKEY_LOCAL_MACHINE
from os.path import join as pjoin, isfile
# moved win32com import within the functions that need them
# This prevents an error when running under the installer for bdist_wininst
# during the post install script (it does not need these functions anyway.)
#from win32com.shell import shell, shellcon
#from win32com.client import Dispatch

from . import config

def get_reg_HKLM(subkey):
    # QueryValue always returns a string. It is OK for our use
    try:
        return QueryValue(HKEY_LOCAL_MACHINE, subkey)
    except WindowsError:
        return None

#PYTHONXY_DIR = r'C:\Program Files (x86)\pythonxy'
#CONSOLE_DIR  = pjoin(PYTHONXY_DIR, 'console')
PYTHONXY_DIR = get_reg_HKLM('Software\\Python(x,y)')
CONSOLE_DIR  = get_reg_HKLM('Software\\console')
# Always check for the not None of the above DIR before using the following ones
if CONSOLE_DIR is not None:
    CONSOLE_XML  = pjoin(CONSOLE_DIR, 'console.xml') # C:\Program Files (x86)\pythonxy\console\console.xml
    CONSOLE_EXEC = pjoin(CONSOLE_DIR, 'Console.exe') # C:\Program Files (x86)\pythonxy\console\Console.exe
    if CONSOLE_EXEC[1] == ':':
        # something like: r'C:"\Program Files (x86)\pythonxy\console\Console.exe"'
        CONSOLE_EXEC_QUOTED = CONSOLE_EXEC[:2]+'"'+CONSOLE_EXEC[2:]+'"'
    elif CONSOLE_EXEC.find(' ') == -1:
        # no space so no need to quote
        CONSOLE_EXEC_QUOTED = CONSOLE_EXEC
    else:
        # mayb it is an UNC path \\..., try to deal with it the same way as real path
        # insert quote after 2nd character (becomes \\"...")
        CONSOLE_EXEC_QUOTED = CONSOLE_EXEC[:2]+'"'+CONSOLE_EXEC[2:]+'"'
if PYTHONXY_DIR is not None:
    CONSOLE_ICON = pjoin(PYTHONXY_DIR, 'icons', 'consolexy.ico') # C:\Program Files (x86)\pythonxy\icons\consolexy.ico

DEFAULT_WORK_DIR = '%UserProfile%'


# TODO: when install as user, the scripts go to
#        ~\AppData\Roaming\Python\Scripts\
def get_pyhegel_start_script(script='pyHegel', pythonw=False, aslist=False, skip_last=False):
    # aslist is used for creating shortcuts. It returns [executable, arguments]
    exec_base = os.path.dirname(sys.executable)
    if pythonw:
        # This executable does not open the cmd terminal
        executable = pjoin(exec_base, 'pythonw.exe')
    else:
        #executable = sys.executable
        # this should be the same
        executable = pjoin(exec_base, 'python.exe')
    script_dir = pjoin(sys.exec_prefix, 'Scripts')
    name = pjoin(script_dir, script+'.exe')
    if isfile(name):
        if aslist:
            return [name, '']
        else:
            return '"%s"'%name
    for basename in [script+'-script.py', script+'.py']:
        name = pjoin(script_dir, basename)
        if isfile(name):
            if aslist:
                return [executable, '"%s"'%name]
            else:
                return '"%s" "%s"'%(executable, name)
    name = os.path.dirname(config.PYHEGEL_DIR) # Goes to parent
    name = os.path.join(name, 'pyHegel.py')
    if skip_last:
        return None
    if aslist:
        return [executable, '"%s"'%name]
    else:
        return '"%s" "%s"'%(executable, name)

def get_pyhegel_console_start_script(aslist=False):
    ret = get_pyhegel_start_script(script='pyHegel_console', pythonw=True, aslist=aslist, skip_last=True)
    if ret is not None:
        return ret
    name = get_pyhegel_start_script(pythonw=True, aslist=aslist)
    extra_arg = ' --console'
    if aslist:
        executable, args = name
        return [executable, args + extra_arg]
    else:
        return name + extra_arg


def write_tree(tree, filename):
    with open(filename, 'wb') as f:
        f.write('<?xml version="1.0"?>\n')
        tree.write(f)

def update_console_xml(dest, save_orig=None):
    """
    This codes will take the current default console.xml and convert it for
    use by pyHegel. The result will be in dest.
    The changes are:
        enable save_size for recent ConsoleZ
        make shift+up/down and shift+pageup/down scroll the display
        make mouse selection/copy work without modifier key (just left mouse button)
        add entry for pyHegel based on IPython entry.
    save_orig: when given a filename it writes the xml file before modification.
        It can be usefull to compare before and after the change since
        writing restructures the file somewhat.
    """
    if CONSOLE_DIR is None:
        raise RuntimeError("Can't find the Console directory. Is it installed?")
    if PYTHONXY_DIR is None:
        raise RuntimeError("Can't find the Python(x,y) (pythonxy) directory. Is it installed?")
    tree = ET.parse(CONSOLE_XML) # tree represents the settings entry
    if save_orig is not None:
        write_tree(tree, save_orig)
        #tree.write(save_orig, xml_declaration=True)
    code_map = dict(scrollrowdown='40', scrollrowup='38', scrollpagedown='34', scrollpageup='33')
    if tree.getroot().tag != 'settings':
        raise RuntimeError('The input console.xml does not have the expected structure.')
    # save_size in settings/console used to be 1
    # it is now 0, but no longer works in ConsoleZ
    # instead we need to change settings/appearance/position
    position = tree.find('./appearance/position')
    if position is not None:
        if position.get('save_size', None) is not None:
            position.set('save_size', '1')
            # need to provide defaults otherwise the window is minuscule
            position.set('w', '597')
            position.set('h', '484')
    hotkeys = tree.findall("./hotkeys/hotkey[@command]")
    for e in hotkeys:
        cmd = e.get('command')
        if cmd in ['scrollrowdown', 'scrollrowup', 'scrollpagedown', 'scrollpageup']:
            e.set('shift', '1')
            e.set('extended', '1')
            e.set('code', code_map[cmd])
    mouse_copy = tree.find("./mouse/actions/action[@name='copy']")
    if mouse_copy is not None:
        mouse_copy.set('ctrl', '1')
    mouse_select = tree.find("./mouse/actions/action[@name='select']")
    if mouse_select is not None:
        mouse_select.set('shift', '0')
    tabs = tree.find('tabs')
    if tabs is None:
        raise RuntimeError('Unexpected missing tabs sections in console.xml.')
    bases = ['IPython(x,y)', 'IPython (Qt)']
    for b in bases:
        e = tabs.find("./tab[@title='%s']"%b)
        if e is not None:
            n = copy.deepcopy(e)
            n.set('title', 'pyHegel')
            n.set('icon', CONSOLE_ICON)
            c = n.find('console')
            if c is not None:
                #c.set('shell', r"C:\Python27\Scripts\ipython.bat -pylab -p xy -nopylab_import_all -editor SciTE.exe C:\Codes\pyHegel\pyHegel.py")
                cmd = get_pyhegel_start_script()
                c.set('shell', cmd) # Console uses CreateProcess with the string
                #c.set('shell', r"cmd.exe /c C:\Codes\pyHegel\pyHegel.py")
                userroot = config.USER_HOME
                c.set('init_dir', userroot)
                #c.set('init_dir', r'C:\Codes\pyHegel')
            else:
                raise RuntimeError('Unexpected missing console entry in parent tab.')
            tabs.insert(0, n)
            break
    else:
        raise RuntimeError('Could not find a base tab to use.')
    write_tree(tree, dest)
    #tree.write(dest, xml_declaration=True)


def check_newer(dest):
    """
    returns true when the reference console.xml is newer than the user one (dest).
    or when this module file is newer
    """
    if CONSOLE_DIR is None:
        raise RuntimeError("Can't find the Console directory. Is it installed?")
    #  so far, every install of pythonxy leaves the console.xml with a modification
    #  time of the installation
    base_time = os.path.getmtime(CONSOLE_XML)
    if not os.path.isfile(dest):
        return True
        # otherwise I will get a WindowsError exc with exc.errno == 2
    dest_time = os.path.getmtime(dest)
    this_time = os.path.getmtime(__file__)
    #import time
    #print 'Base:', time.ctime(base_time), '  ---- Dest: ', time.ctime(dest_time)
    return base_time > dest_time or this_time > dest_time

def find_destination():
    # just pick the first entry
    path = config.get_conf_dirs()[0]
    return os.path.join(path, 'console.xml')

def update_if_needed(dest=None):
    if dest is None:
        dest = find_destination()
    conf_dir = os.path.dirname(dest)
    if not os.path.isdir(conf_dir):
        os.mkdir(conf_dir, 0755)
    if check_newer(dest):
        update_console_xml(dest)

# Important note about using os.system (or subprocess.call with shell enabled):
#   os.system(s) will execute "cmd /c s". So see the windows documentation: cmd /?
#   In particular the section about quoting. If the string s contains more than
#   one set of quotes and starts with one it is removed. So that is the
#   reason CONSOLE_EXEC_QUOTED does not start with a ".
# Also note that executing a graphical program (like Console) from am interactive
# cmd line returns immediately. But calling it from a script does not hence
# then need for the start command.

def start_console(mode=None):
    """
    mode can be
       None (default): will launch the console and not wait for it.
       'wait': will launch the console and wait for it to finishe before returning
       'replace': will launch the console by replaceing this process.
    If you need to force a change of the user console.xml file, you can just delete
    it. It will be recreated at the next start_console.
    """
    from win32com.client import Dispatch
    if CONSOLE_DIR is None:
        raise RuntimeError("Can't find the Console directory. Is it installed?")
    update_if_needed()
    dest = find_destination()
    if mode == 'replace':
        # This replaces the current process
        os.execl(CONSOLE_EXEC, CONSOLE_EXEC, '-c', dest, '-t', 'pyHegel')
    elif mode == 'wait':
        # This waits for the program to end
        subprocess.call([CONSOLE_EXEC, CONSOLE_EXEC, '-c', dest, '-t', 'pyHegel'])
        #os.system(CONSOLE_EXEC_QUOTED + ' -c "%s" -t "pyHegel"'%dest)
    else:
        # This starts and does not wait
        # note that start is a cmd.exe command, so it needs to be called from it.
        # (could be: cmd /c start ....)
        # However, if it is not running from a shell, it opens one.
        #  So if this script is a .pyw one, There will be a flashing
        #  console on the screen
        #os.system('start %s -c "%s" -t "pyHegel"'%(CONSOLE_EXEC_QUOTED, dest))
        # A work around that flashing problem is to use the windows scripting host
        shell = Dispatch('WScript.Shell')
        shell.Run('cmd /c %s -c "%s" -t "pyHegel"'%(CONSOLE_EXEC_QUOTED, dest), 0, False)


#################################################
# Some useful tools
#################################################
SHGFP_TYPE_CURRENT = 0
SHGFP_TYPE_DEFAULT = 1
CSIDL_FLAG_CREATE = 0x8000

def get_win_folder_path(csidl, create=False, default=False):
    """
    get the windows current folder path for a csidl
    useful entries:
         'CSIDL_COMMON_DESKTOPDIRECTORY'
         'CSIDL_COMMON_STARTMENU'
         'CSIDL_COMMON_PROGRAMS'
         'CSIDL_PROGRAM_FILES'
         'CSIDL_PROGRAM_FILESX86'
    create when True, will also create it if it does not exists
    default when True, returns the default directory instead of the current one.
    """
    from win32com.shell import shell, shellcon
    c = getattr(shellcon, csidl)
    flag = SHGFP_TYPE_CURRENT
    if create:
        c |= CSIDL_FLAG_CREATE
    if default:
        flag = SHGFP_TYPE_DEFAULT
    return shell.SHGetFolderPath(None, c, None, flag)

def create_shortcut(filename, description, target, arguments=None, iconpath=None, workdir=DEFAULT_WORK_DIR, iconindex=0):
    # This is based from
    #  http://www.blog.pythonlibrary.org/2010/01/23/using-python-to-create-shortcuts/
    # Another option would be to use the COM IShellLink interface of the windows shell
    # in comnbination with the standard IPersistFile.
    # They required constants are in win32com.shell.shell and pythoncom.
    #  see: from pywin32:  win32comex/shell/demos/create_link.py
    #         or: http://timgolden.me.uk/python/win32_how_do_i/create-a-shortcut.html
    # Another interface would be the scripting interface of the windows shell:
    #   Dispatch('Shell.Application').NameSpace('path to shortcut').ParseName('exising Shortcut Name.lnk').GetLink
    from win32com.client import Dispatch
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(filename)
    shortcut.Description = description
    # Quotes around filename are added automatically if necessary (contains spaces)
    shortcut.Targetpath = target
    if arguments is not None:
        shortcut.Arguments = arguments
    shortcut.WorkingDirectory = workdir
    if iconpath is not None:
        iconpath += ',%i'%iconindex
        shortcut.IconLocation = iconpath
    #shortcut.Hotkey = 'Ctrl+Alt+H'
    # To available window style are at
    #  https://technet.microsoft.com/en-us/library/ee156605.aspx
    # Default is 1: Activates and displays a window.
    #shortcut.WindowStyle = 1
    shortcut.save()
