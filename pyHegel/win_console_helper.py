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
from . import config
from os.path import join as pjoin

# hard code the original file location for now.
PYTHONXY_DIR = r'C:\Program Files (x86)\pythonxy'
CONSOLE_DIR  = pjoin(PYTHONXY_DIR, 'console')
CONSOLE_XML  = pjoin(CONSOLE_DIR, 'console.xml') # C:\Program Files (x86)\pythonxy\console\console.xml
CONSOLE_EXEC = pjoin(CONSOLE_DIR, 'Console.exe') # C:\Program Files (x86)\pythonxy\console\Console.exe
CONSOLE_EXEC_QUOTED = r'C:"\Program Files (x86)\pythonxy\console\Console.exe"'
CONSOLE_ICON = pjoin(PYTHONXY_DIR, 'icons', 'consolexy.ico') # C:\Program Files (x86)\pythonxy\icons\consolexy.ico

# TODO: improve this to find installed script location (if pyHegel was installed.)
def get_pyhegel_start_script():
    start_script = os.path.dirname(config.PYHEGEL_DIR) # Goes to parent
    start_script = os.path.join(start_script, 'pyHegel.py')
    return start_script


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
                start_script = get_pyhegel_start_script()
                cmd = '"%s" "%s"'%(sys.executable, start_script)
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
    """
    #  so far, every install of pythonxy leaves the console.xml with a modification
    #  time of the installation
    base_time = os.path.getmtime(CONSOLE_XML)
    if not os.path.isfile(dest):
        return True
        # otherwise I will get a WindowsError exc with exc.errno == 2
    dest_time = os.path.getmtime(dest)
    #import time
    #print 'Base:', time.ctime(base_time), '  ---- Dest: ', time.ctime(dest_time)
    return base_time > dest_time

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
        # not that start is a cmd.exe command, so it needs to be called from it.
        # (could be: cmd /c start ....)
        os.system('start %s -c "%s" -t "pyHegel"'%(CONSOLE_EXEC_QUOTED, dest))
