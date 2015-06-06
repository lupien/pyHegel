#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Note that starting this script, or excuting it with python
# from a command line anywhere will work, since python then adds
# the script directory in the search path. So we can use it from outside
# the main python site (uninstalled).

# You can also start the script from a live python or ipython shell.
# From an ipython shell, the start code is redirected to the interactive env
# and you can use either run or run -i.
# In a python live shell you can use execfile.
# However, in all those cases, the session will be fragile since then the path
# will not be changed. Further imports or reset_pyHegel will fail unless
# the current working path is at the root of the package.
# And another problem will be that the CTRL-C fix might not be applied properly.

if __name__ == '__main__':
    from  pyHegel import start_pyHegel
    start_pyHegel()
