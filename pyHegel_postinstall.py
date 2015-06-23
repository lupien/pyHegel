#!/usr/bin/env python
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

import sys
import os
import os.path as osp
import time

SHORTCUT_CMD = 'pyHegel.lnk'
SHORTCUT_CONSOLE = 'pyHegel_console.lnk'

#DEBUG_SLEEP = False # Turns it off
#DEBUG_SLEEP = 10 # s
DEBUG_SLEEP = 2 # s

def _install(create_shortcut, get_special_folder_path, file_created, directory_created):
    import pyHegel.win_console_helper as helper
    def mk_sc(folder, filename, *arg, **kwarg):
        path = osp.join(folder, filename)
        create_shortcut(path, *arg, **kwarg)
        print 'file created: "%s"'%path
        file_created(path)
    target1 = helper.get_pyhegel_start_script(aslist=True)
    icon1 = r'%windir%\system32\cmd.exe'
    if helper.CONSOLE_DIR is not None:
        target2 = helper.get_pyhegel_console_start_script(aslist=True)
        icon2 = r'%windir%\system32\cmd.exe'
        if helper.PYTHONXY_DIR is not None:
            icon2 = helper.CONSOLE_ICON
    install_folders = [('CSIDL_COMMON_DESKTOPDIRECTORY', 'CSIDL_DESKTOPDIRECTORY'),
                       ('CSIDL_COMMON_PROGRAMS', 'CSIDL_PROGRAMS')]
    for admin, user in install_folders:
        admin = get_special_folder_path(admin)
        try:
            open(osp.join(admin, SHORTCUT_CMD), 'w')
        except IOError:
            # probably running as user
            folder = get_special_folder_path(user)
            if not osp.isdir(folder):
                os.mkdir(folder)
                print 'directory created: "%s"'%folder
                directory_created(folder)
        else:
            folder = admin
        mk_sc(folder, SHORTCUT_CMD, 'pyHegel started in a windows cmd prompt', target1[0], target1[1], icon1)
        if helper.CONSOLE_DIR is not None:
            mk_sc(folder, SHORTCUT_CONSOLE, 'pyHegel started within a console window', target2[0], target2[1], icon2)


def install_wininst():
    import pyHegel.win_console_helper as helper
    def mk_shortcut(filename, description, target, arguments=None, iconpath=None, workdir=helper.DEFAULT_WORK_DIR, iconindex=0):
        if iconpath is None:
            iconpath = ''
        if arguments is None:
            arguments = ''
        create_shortcut(target, description, filename, arguments, workdir, iconpath, iconindex)
    #with open(r'\TEMP\pyHegel_install_test.txt', 'w') as f:
    #    print >>f, 'In bdist_wininst install'
    print 'In bdist_wininst install'
    _install(mk_shortcut, get_special_folder_path, file_created, directory_created)
    print 'Finished executing post install script'

def remove_wininst():
    # nothing to do. We registered the shortcuts so they should be removed properly
    pass

def install():
    import pyHegel.win_console_helper as helper
    # TODO improve file/directory created to allow removing them later.
    def file_created(path):
        #print 'file created: "%s"'%path
        pass
    def directory_created(path):
        #print 'directory created: "%s"'%path
        pass
    print 'In regular install'
    _install(helper.create_shortcut, helper.get_win_folder_path, file_created, directory_created)
    print 'Finished executing post install script'
    if DEBUG_SLEEP:
        print '   waiting.. %i s'%DEBUG_SLEEP
        time.sleep(DEBUG_SLEEP)
    #sys.exit(1) # This will produce an error message under msi install

def remove():
    # lets just try and remove all possible shortcuts we might have created.
    # This should be executed before the unistalling of the package (we need
    #  pyHegel.win_console_helper)
    # Note: I don't think msi uninstall calls this script.
    import pyHegel.win_console_helper as helper
    install_folders = ['CSIDL_COMMON_DESKTOPDIRECTORY', 'CSIDL_DESKTOPDIRECTORY',
                       'CSIDL_COMMON_PROGRAMS', 'CSIDL_PROGRAMS']
    for folder in install_folders:
        folder = helper.get_win_folder_path(folder)
        for filename in [SHORTCUT_CMD, SHORTCUT_CONSOLE]:
            path = osp.join(folder, filename)
            try:
                os.remove(path)
                print 'file deleted: "%s"'%path
            except OSError:
                pass
    if DEBUG_SLEEP:
        print '   waiting.. %i s'%DEBUG_SLEEP
        time.sleep(DEBUG_SLEEP)

#import sys
#with open(r'\TEMP\pyHegel_install_test.txt', 'w') as f:
#    print 'This is regular output'
#    print >>sys.stderr, 'This is std error output'
#    print >>f, 'Executing test script'
#    try:
#        print >>f,'Folder', get_special_folder_path('CSIDL_COMMON_DESKTOPDIRECTORY')
#    except Exception as exc:
#        print >>f, 'exception: ', exc

def main():
    do_install = True
    # With no arguments we default to install
    if len(sys.argv) > 1:
        if sys.argv[1] == '-remove':
            do_install = False
        elif sys.argv[1] == '-install':
            do_install = True
        else:
            print >>sys.stderr, 'Script called with invalid argument. Should be either -remove or -install.'
            sys.exit(1)
    try:
        get_special_folder_path
    except NameError:
        # Note running under wininst, So either under msi or a straight install
        if do_install:
            install()
        else:
            remove()
    else:
        if do_install:
            install_wininst()
        else:
            remove_wininst()

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print >>sys.stderr, 'There was an exception during script execution: %s'%exc
