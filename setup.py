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

# following steps from
#   https://packaging.python.org/en/latest/distributing.html
# and documentation from
#   http://pythonhosted.org/setuptools/setuptools.html

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

requirements = [ 'ipython', 'numpy', 'scipy', 'matplotlib' ]
extras_require = {
        'visa': ['PyVISA']
        }


entry_points = {
        'console_scripts': ['pyHegel=pyHegel:start_pyHegel']
        }
if os.name == 'nt':
    entry_points['gui_scripts'] = ['pyHegel_console=pyHegel:start_console']

setup(name='pyHegel',
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
      install_requires=requirements,
      extras_require=extras_require,
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
            'pyHegel': ['pyHegel_default.ini'],
          },
      entry_points=entry_points,
      zip_safe=False)

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
