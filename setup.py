#!/usr/bin/env python
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

# following steps from
#   https://packaging.python.org/en/latest/distributing.html
# and documentation from
#   http://pythonhosted.org/setuptools/setuptools.html

from __future__ import print_function
import sys

try:
    from setuptools import setup, find_packages
except ImportError:
    print('Please install or upgrade setuptools or pip to continue')
    sys.exit(1)

import os
from codecs import open
from os import path


from pyHegel import __version__

here = path.abspath(path.dirname(__file__))

def read(filename):
        return open(path.join(here, filename), encoding='utf-8').read()

long_description = '\n\n'.join([read('README.rst'), read('AUTHORS'), read('CHANGES')])

__doc__ = long_description

setup_dict = dict(name='pyHegel',
      description='Command line interface to provide a uniform interface to laboratory instruments',
      version=__version__,
      long_description=long_description,
      author='Christian Lupien',
      author_email='Christian.Lupien@usherbrooke.ca',
      #maintainer='Christian Lupien',
      #maintainer_email='Christian.Lupien@usherbrooke.ca',
      url='https://github.com/lupien/pyHegel',
      #test_suite='pyHegel...',
      keywords='CLI VISA GPIB USB serial RS232 measurement acquisition automation',
      license='LGPL',
      platforms = ['Linux', 'Max OSX', 'Windows'],
      classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Science/Research',
        'Environment :: Console',
        'Framework :: IPython',
        'License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: POSIX :: Linux',
        'Operating System :: MacOS :: MacOS X',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 2 :: Only',
        'Programming Language :: Python :: Implementation :: CPython'
        'Topic :: Scientific/Engineering',
        'Topic :: Scientific/Engineering :: Interface Engine/Protocol Translator',
        'Topic :: Software Development :: Libraries :: Python Modules',
        ],
      #packages=find_packages(exclude=['attic', 'docs', 'manual', 'tests']),
      packages=find_packages(),
      package_data = {
            #'pyHegel': ['pyHegel_default.ini'],
            'pyHegel': ['pyHegel*.ini'],
          },
      zip_safe=False
      )

requirements = [ 'ipython', 'numpy', 'scipy', 'matplotlib', 'packaging' ]
setup_requires = []
extras_require = {
        'visa': ['PyVISA']
        }

scripts = []
entry_points = {
        'console_scripts': ['pyHegel=pyHegel:start_pyHegel']
        }

options = {}

# Parse the arguments for extra flags
#do_post = True
# As of 2020-10-26, fully disable post script.
do_post = False
if '--no-post' in sys.argv:
    do_post = False
    sys.argv.remove('--no-post')


post_script = 'pyHegel_postinstall.py'
def _post_install(cmd='install'):
    if not do_post:
        return
    print('Running post install')
    from subprocess import call
    if cmd == 'install':
        call([sys.executable, post_script, '-install'])
    elif cmd == 'remove':
        call([sys.executable, post_script, '-remove'])
    else:
        raise ValueError('The _post_install cmd parameter is invalide: %s'%cmd)


# TODO: once we have icons, don't forget to add them to data stuff
if os.name == 'nt':
    entry_points['gui_scripts'] = ['pyHegel_console=pyHegel:start_console']
    requirements.append('pywin32')
    if 'bdist_msi' in sys.argv or 'bdist_wininst' in sys.argv:
        if 'install' in sys.argv:
            raise RuntimeError('You cannot select both a bdist and an install')
        scripts.append(post_script)
    if 'bdist_wininst' not in sys.argv:
        # needed by postinstall scripts
        setup_requires.append('pywin32')
    if 'bdist_msi' in sys.argv and do_post:
        options.update({'bdist_msi': {'install_script': post_script}})
    if 'bdist_wininst' in sys.argv and do_post:
        options.update({'bdist_wininst': {'install_script': post_script}})
    from setuptools.command.install import install as _install
    from setuptools.command.develop import develop as _develop
    class my_install(_install):
        def run(self):
            _install.run(self)
            self.execute(_post_install, [], msg='Running post install script')
    class my_develop(_develop):
        def run(self):
            if self.uninstall:
                self.execute(_post_install, ['remove'], msg='Running post develop uninstall script')
            _develop.run(self)
            if not self.uninstall:
                self.execute(_post_install, [], msg='Running post develop script')
    cmdclass = {'develop': my_develop}
    if 'install' in sys.argv:
        cmdclass.update({'install': my_install})
    setup_dict.update(dict(cmdclass=cmdclass))

setup_dict.update(dict(install_requires=requirements,
                       extras_require=extras_require,
                       entry_points=entry_points))
if setup_requires:
    setup_dict.update(dict(setup_requires=setup_requires))
if scripts:
    setup_dict.update(dict(scripts=scripts))
if options:
    setup_dict.update(dict(options=options))

setup(**setup_dict)

# different ways to install (not as root):
#  PYTHONPATH=/tmp/inst/lib/python2.7/site-packages pip install --install-option="--prefix=/tmp/inst" .
#  PYTHONPATH=/tmp/inst/lib/python2.7/site-packages ./setup.py install --prefix /tmp/inst
# execute:
#  PYTHONPATH=/tmp/inst/lib/python2.7/site-packages /tmp/inst/bin/pyHegel
# delete package
#  PYTHONPATH=/tmp/inst/lib/python2.7/site-packages pip uninstall pyHegel

# To install under my account (~/.local/bin and ~/.local/lib/python2.7/site-packages/...)
#  pip install --user .
#  ~/.local/bin/pyHegel
#  pip uninstall pyHegel
# Reinstall
#  pip install --user -I --no-deps .
# As develop under my account
#  pip install --user -e .
#  ~/.local/bin/pyHegel
#  pip uninstall pyHegel   # but it leaves the executable
#
# Could also install:
#  ./setup.py install --user

# develop mode
#  PYTHONPATH=/tmp/inst/lib/python2.7/site-packages ./setup.py develop --prefix /tmp/inst
# undevelop
#  PYTHONPATH=/tmp/inst/lib/python2.7/site-packages ./setup.py develop --uninstall --prefix /tmp/inst
# or develop to user dir:
#  ./setup.py develop --user
# undevelop
#  ./setup.py develop --user --uninstall

# You can also create a windows installer executable (only under a windows environment):
#  setup.py bdist_wininst
# or a windows msi
#  setup.py bdist_msi
# Note that the msi file will not execute the remove post-install script so if
# you want to properly remove the shortcut call the pyHegel_postinstall script with the
#  -remove option before performing the uninstall
# Also clicking on the file might not execute the script as admin. One way to make sure the
# msi is executed as admin is to call it from an Administrator command shell
# using: msiexec /i path_to.msi
# Then you can uninstall with: msiexec /x path_to.msi
# (and you could turn on logging: /L*v some_log_file.txt)
