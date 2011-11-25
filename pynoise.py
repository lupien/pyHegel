#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Programme principale pour remplacer Hegel
#

import numpy as np
import instrument
from time import sleep

class _sweep(instrument.BaseInstrument):
    before = instrument.MemoryDevice()
    out = instrument.MemoryDevice()
    def __call__(self, dev, start, stop, npts, rate, filename):
        """
            routine pour faire un sweep
             dev est l'objet a varier
            ....
        """
        try:
           dev.check(start)
           dev.check(stop)
        except ValueError:
           print 'Wrong start or stop values. Aborting!'
           return
        span = np.linspace(start, stop, npts)
        f = open(filename, 'w')
        for i in span:
            dev.set(i)
            f.write('%f\n'%i)
        f.close()

sweep = _sweep()
# sleep seems to have 0.001 s resolution on windows at least
wait = sleep

###  set overides set builtin function
def set(dev, value):
    """
       Change la valeur de dev
    """
    dev.set(value)

### get overides get the mathplotlib
def get(dev):
    """
       Obtien la valeur de get
    """
    try:
       return dev.get()
    except KeyboardInterrupt:
       print 'CTRL-C pressed!!!!!!' 

