#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Programme principale pour remplacer Hegel
#

import numpy as np
import instrument

class _sweep(instrument.BaseInstrument):
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
      for i in span():
          dev.set(i)
          f.write('%f\n'%i)
      f.close()

sweep = _sweep()

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

