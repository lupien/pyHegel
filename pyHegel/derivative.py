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

"""
This modules contains functions to perform numerical derivatives in different ways to
compare them. The all use and return the same vector format.
Many of the functions require uniform point spacing.
Functions:
    D1
    Dn
    Du
    Dfilter
    Dspline
Be careful with spline. It is not always easy to pick proper parameters (too much
or too little smoothing).

For smoothing curves (not derivatives) you might also try the external package statsmodel.
In particular, statsmodels.nonparametric.smoothers_lowess.lowess
"""

from __future__ import absolute_import, print_function, division

from numpy import diff
from scipy.misc import central_diff_weights
from scipy import signal, interpolate
from scipy.ndimage import filters

def D1(x, y, axis=-1):
    """ Simplest numerical derivative of order 1
        returns x', dy/dx(x')
    """
    dx = diff(x,axis=axis)
    dy = diff(y,axis=axis)
    return x[:-1]+dx/2, dy/dx

def _do_strip(x, y, Np, axis=-1):
    first = Np//2
    if Np%2: #odd
        last = - (Np//2)
    else:
        last = - (Np//2) + 1
    if last == 0:
        last = None
    ind = [slice(None)]*x.ndim
    ind[axis] = slice(first, last)
    ind = tuple(ind)
    return x[ind], y[ind]

def Dn(x, y, Np, ndiv=1, axis=-1, mode='strip', cval=0.):
    """ central numerical derivative using Np points of order ndiv
        (Np>1 and odd), using convolution
        Data needs to be equally spaced in x
        can use mode= 'nearest', 'wrap', 'reflect', 'constant'
                      'strip'
                      'strip' will just cut the bad data at the ends
        cval is for 'constant'
        returns x', d^n y/dx^n(x')

        Note the algorithm is not intended to remove noise
        But to provide more accurate derivative of a function.
        The larger Np the more deriviatives are available.
        It basically finds the best taylor series parameter
        assuming Np around the center are available:
          assuming f_k = f(xo + k dx),  k=-n .. n, Np=2*n+1
          and with f(x) = f(xo) + f' (x-xo) + f''(x-xo)^2/2 + ....
                        = f(xo) + f' k dx + ((f'' dx**2)/2) k**2 + ...
          we want to solve for (1, f', f'' dx**2/2, ...)
          and we pick the answer for the correct derrivative.
    """
    dx = x[1]-x[0]
    kernel = central_diff_weights(Np,ndiv=ndiv)
    strip = False
    if mode=='strip':
        strip = True
        mode = 'reflect'
    dy = filters.correlate1d(y, kernel, axis=axis, mode=mode, cval=cval)
    D = dy/dx**ndiv
    if strip:
        x, D = _do_strip(x, D, Np, axis=axis)
    return x, D

def Du(x, y, Np, ndiv=1, axis=-1, mode='strip', cval=0.):
    """
    Does the central derrivative after performing a uniform
    filter (average of Np points).
    Date needs to be equally spaced and Np odd.
    """
    strip = False
    if mode == 'strip':
        strip = True
        mode = 'reflect'
    y = filters.uniform_filter1d(y, Np, axis=axis, mode=mode, cval=cval)
    #if Np%2 == 0: x -= (x[1]-x[0])/2 # or x = filters.uniform_filter1d(x, Np, axis=axis, mode='nearest')
    if strip:
        x, y = _do_strip(x, y, Np, axis=axis)
    Np = ndiv*2+1
    x, D = Dn(x, y, Np, ndiv=ndiv, axis=axis, mode=mode, cval=cval)
    if strip:
        x, D = _do_strip(x, D, Np, axis=axis)
    return x, D

def Dfilter(x, y, sigma, axis=-1, mode='reflect', cval=0.):
    """ gaussian filter of size sigma and order 1
        Data should be equally space for filter to make sense
        (sigma in units of dx)
        can use mode= 'nearest'. 'wrap', 'reflect', 'constant'
        cval is for 'constant'
    """
    dx = x[1]-x[0]
    yf = filters.gaussian_filter1d(y, sigma, axis=axis, mode=mode, cval=cval, order=1)
    return x, yf/dx
    #return D1(x, yf, axis=axis)

def Dspline(x, y, sigma=None, s=None, k=3, n=1):
    """ derivative using splines
         k is spline oder (3: cubic, 1 <= k <= 5)
         sigma is standard error of y (needed for smoothing)
         s is smoothing factor (chi^2 <= s)
        returns x', d^n y/dx^n(x')
          n needs to be <= k
        To check the initial data use n=0
         plot(x,y,'.-')
         plot(*Dspline(x,y,s=1,n=0))
    """
    global tck
    extra={}
    if sigma is not None:
       extra['w']=1./sigma
    tck = interpolate.splrep(x, y, k=k, s=s, **extra)
    return (x, interpolate.splev(x, tck, der=n))

# for 2d look at filters.sobel and filers.prewitt
# other filters: filters.uniform_filter1d
#                signal.spline_filter signal.cspline1d, signal.bspline
#                 signal is for fast transform. Assumes equally spaced points
