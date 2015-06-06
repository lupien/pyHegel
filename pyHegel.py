#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Note that starting this script, or excuting it with python
# from a command line anywhere will work, since python then adds
# the script directory in the search path. So we can use it from outside
# the main python site (uninstalled).
# However it will be fragile if you execute the script with execfile from
# a python prompt since then the path will not be changed. It will work
# only if the current working path is at the root of the package.
# And commands will delay import/reload will later fail if the cwd is changed.

if __name__ == '__main__':
    from  pyHegel import start_pyHegel
    start_pyHegel()
