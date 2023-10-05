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
This module contains many tools for fitting data
see also the module fit_functions for many examples of functions to
use in fitting.
"""

from __future__ import absolute_import, print_function, division

import numpy as np
import inspect
from scipy.optimize import leastsq
# see also scipy.optimize.curve_fit
import matplotlib.pyplot as plt
import matplotlib.colors
import matplotlib.text
import collections

from .comp2to3 import string_bytes_types, builtins_set, inspect_getargspec, is_py2

def getVarNames(func):
    """
    This function finds the name of the parameter as used in the function
    definition.
    It returns a tuple (para, kwpara, varargs, varkw, defaults)
    Where para is a list of the name positional parameters
          kwpara is a list of the keyword parameters
          varargs and varkw ar the name for the *arg and **kwarg
           paramters. They are None if not present.
          defaults are the default values for the kwpara
    """
    (args, varargs, varkw, defaults) = inspect_getargspec(func)
    if defaults is None:
        Nkw = 0
    else:
        Nkw = len(defaults)
    Nall = len(args)
    Narg = Nall-Nkw
    para = args[:Narg]
    kwpara = args[Narg:]
    return (para, kwpara, varargs, varkw, defaults)

def toEng(p, pe, signif=2):
    if isinstance(p, string_bytes_types):
        raise NotImplementedError
    if not np.isscalar(p): # lists and arrays:
        raise NotImplementedError
    if pe != 0:
        pe10 = np.log10(np.abs(pe))
    else:
        pe10 = 0
    if p != 0:
        p10 = np.log10(np.abs(p))
    else:
        p10 = pe10
    pe10f = int(np.floor(pe10))
    p10f = int(np.floor(p10))
    #For pe make the rescaled value
    # between 9.9 and 0.010
    pe10Eng = (int(np.floor(pe10+2))//3)*3.
    #For p make the rescaled value
    # between 499 and 0.5
    p10Eng = (int(np.floor(p10 - np.log10(.5)))//3)*3.
    if pe != 0:
        expEng = max(pe10Eng, p10Eng)
        frac_prec = signif-1 - (pe10f-expEng)
    else:
        expEng = p10Eng
        frac_prec = 15-(p10f-expEng) #15 digit of precision
    frac_prec = int(frac_prec)
    if frac_prec < 0:
        frac_prec = 0
    pe_rescaled = pe/10.**expEng
    p_rescaled = p/10.**expEng
    return p_rescaled, pe_rescaled, expEng, frac_prec

def convVal(p, pe, signif=2):
    # handle one p, pe at a time
    try:
        p_rescaled, pe_rescaled, expEng, frac_prec = toEng(p, pe, signif=signif)
    except NotImplementedError:
        # p is not a numeric type
        s = '%r'%p
        if len(s)>20:
            s=s[:17]+'...'
        return s, None, None
    if pe == 0:
        if p == 0:
            return '0', None, '0'
        else:
            return ( '{0!r}'.format(p_rescaled, prec=frac_prec), None, '%i'%expEng )
    else:
        return ( '{0:.{prec}f}'.format(p_rescaled, prec=frac_prec),
                 '{0:.{prec}f}'.format(pe_rescaled, prec=frac_prec), '%i'%expEng )

def _split_decimal(s):
    if s is None:
        return '', ''
    try:
        l, r = s.split('.')
    except ValueError:
        l = s
        r = ''
    return l, r

def _splitResult(names, ps, pes, signif=2):
    ret_str = []
    ret_len = []
    full_i = []
    noerr_i = []
    i = 0
    for name, p, pe, in zip(names, ps, pes):
        pstr, pestr, expstr = convVal(p, pe, signif=signif)
        if expstr is None:
            pstr_l, pstr_r = pstr, ''
        else:
            pstr_l, pstr_r = _split_decimal(pstr)
        pestr_l, pestr_r = _split_decimal(pestr)
        if expstr is None:
            expstr = ''
        elif pestr is None:
            noerr_i.append(i)
        else:
            full_i.append(i)
        r = [name, pstr_l, pstr_r, pestr_l, pestr_r, expstr]
        ret_str.append(r)
        ret_len.append( list(map(len,r)) )
        i += 1
    ret_len = np.array(ret_len)
    if len(full_i) > 0:
        ret_maxlen = ret_len[full_i].max(axis=0)
    else:
        ret_maxlen = ret_len.max(axis=0)
        ret_maxlen[2] = 0
    if len(noerr_i) > 0:
        ret_max_noerr = ret_len[noerr_i,2].max()
    else:
        ret_max_noerr = 0
    return ret_str, ret_maxlen, ret_max_noerr

#micro sign unicode: 00B5
_expUnits = {-24:'y', -21:'z', -18:'a', -15:'f', -12:'p', -9:'n', -6:u'µ', -3:'m',
               0:'', 3:'k', 6:'M', 9:'G', 12:'T', 15:'P', 18:'E', 21:'Z', 24:'Y'}

#rc('text', usetex=True)
#text(0,0,r'\begin{tabular}{l r@{.}l c r@{.}l l} \hline aa & 123&22&$\pm$&1&33&$\times 10^{-6}$\\ adasd & 5& 777 & \multicolumn{3}{l}{}&55 \\ \hline\hline\end{tabular}')

def strResult(func, p, pe, extra={}, signif=2):
    (para, kwpara, varargs, varkw, defaults) = getVarNames(func)
    N = len(p)
    Npara = len(para) -1
    para = para[1:] # first para is X
    if len(pe) != N:
        raise ValueError("p and pe don't have the same dimension")
    if Npara > N:
        raise ValueError("The function has too many positional parameters")
    if Npara < N and varargs is None and kwpara is None:
        raise ValueError("The function has too little positional parameters")
    if Npara < N and varargs is not None:
        # create extra names par1, par2, for all needed varargs
        para.extend(['par%i'%(i+1) for i in range(N-Npara)])
    elif Npara < N and kwpara is not None:
        para.extend(kwpara[:N-Npara])
        kwpara = kwpara[N-Npara:]
        defaults = defaults[N-Npara:]
    if defaults is not None:
        kw = collections.OrderedDict(list(zip(kwpara, defaults)))
    else:
        kw = {}
    kw.update(extra)
    splits, maxlen, maxlen_noerr = _splitResult(para+list(kw.keys()), list(p)+list(kw.values()), list(pe)+[0]*len(kw), signif=signif)
    maxlen[0] += 1 # because of += ':'
    # unicode: plus-minus = 00B1, multiplication(times) = 00D7
    err_len = maxlen[2]+maxlen[3]+maxlen[4]+4 # +4 is for ' ± ' and the '.'
    noerr = max(maxlen_noerr, err_len)
    if noerr == maxlen_noerr:
        maxlen[4] += noerr - err_len
    kwargs = dict(l=maxlen, noerr=noerr)
    ret = []
    for n, pl, pr, pel, per, ex in splits:
        n += ':'
        args = n, pl, pr, pel, per, ex
        if pel == '' and ex == '':
            s = u'{0:<{l[0]}s} {1:<s}'.format(*args, **kwargs)
        elif pel == '':
            s = u'{0:<{l[0]}s} {1:>{l[1]}s}.{2:<{noerr}s} ×10^ {5:>{l[5]}s}'.format(*args, **kwargs)
        else:
            s = u'{0:<{l[0]}s} {1:>{l[1]}s}.{2:<{l[2]}s} ± {3:>{l[3]}s}.{4:<{l[4]}s} ×10^ {5:>{l[5]}s}'.format(*args, **kwargs)
        ret.append(s)
    return ret

def printResult(func, p, pe, extra={}, signif=2):
    s = u'\n'.join(strResult(func, p, pe, extra, signif))
    if is_py2:
        print(s.encode('utf8'))
    else:
        print(s)

def _get_axis_bgcolor(axis):
    # get_axis_bgcolor cot depracated in matplotlib 2.0 and removed in 2.2
    # It is replaced by get_facecolor
    try:
        return axis.get_axis_bgcolor()
    except AttributeError:
        return axis.get_facecolor()

# TODO: handler positioning better (the bbox is not where I ask for)
def plotResult(func, p, pe, extra={}, signif=2, loc='upper right', ax=None, formats={}):
    """
    takes the fitting results and make a text box on the axis ax
    according to location loc (can be the same as for legend except for best(0) or
    a (x,y) tuple in axes fraction coordinate.
    It uses annotate, so you can override some of the settings with formats
    """
    res = '\n'.join(strResult(func, p, pe, extra, signif))
    kwarg = dict(family='monospace', size=14, xycoords='axes fraction', multialignment='left')
    update = False
    if ax is None:
        ax = plt.gca()
        update = True
    bg = _get_axis_bgcolor(ax)
    kwarg['bbox'] = dict(boxstyle='round', fill=True, facecolor=bg, alpha=.6)
    codes = {'upper right':  1,
             'upper left':   2,
             'lower left':   3,
             'lower right':  4,
             'right':        5,
             'center left':  6,
             'center right': 7,
             'lower center': 8,
             'upper center': 9,
             'center':       10
            }
    UR, UL, LL, LR, R, CL, CR, LC, UC, C = range(1, 11)
    loc_para = {
            UR : (.99, .99, 'right', 'top'),
            UL : (.01, .99, 'left', 'top'),
            LL : (.01, .01, 'left', 'bottom'),
            LR : (.99, .01, 'right', 'bottom'),
            R : (.99, .5, 'right', 'center'),
            CL : (.01, .5, 'left', 'center'),
            CR : (.99, .5, 'right', 'center'),
            LC : (.5, .01, 'center', 'bottom'),
            UC : (.5, .99, 'center', 'top'),
            C : (.5, .5, 'center', 'center')
            }
    if not isinstance(loc, tuple):
        if isinstance(loc, string_bytes_types):
            loc = codes[loc]
        x, y, ha, va = loc_para[loc]
        loc = x, y
        kwarg['horizontalalignment'] = ha
        kwarg['verticalalignment'] = va
    kwarg.update(formats)
    if update:
        a = plt.annotate(res, loc, **kwarg).draggable()
    else:
        a = ax.annotate(res, loc, **kwarg).draggable()
    return a


def _handle_adjust(func, p0, adjust, noadjust):
    if adjust is None and noadjust is None:
        return slice(None)
    Np = len(p0)
    all_index = list(range(Np))
    para, kwpara, varargs, varkw, defaults = getVarNames(func)
    names = para
    Npara = len(para)
    if Npara < Np:
        names += kwpara[:Np-Npara]
    if isinstance(adjust, slice):
        adjust = all_index(adjust)
    if isinstance(noadjust, slice):
        adjust = all_index(noadjust)
    if adjust is None:
        adjust = all_index
    if noadjust is None:
        noadjust = []
    #s = set() # This fails when running under pyHegel (not on import).
    s = builtins_set()
    # cleanup adjust. Remove duplicates, handle named variables.
    for a in adjust:
        if isinstance(a, string_bytes_types):
            s.add(names.index(a)-1) # -1 to remove the x parameter of f(x, p1, ...)
        else:
            s.add(a)
    # Now cleanup noadjust
    sna = builtins_set()
    for na in noadjust:
        if isinstance(na, string_bytes_types):
            sna.add(names.index(na)-1)
        else:
            sna.add(na)
    #Remove noadjust from adjust set
    s = s-sna
    adj=list(s)
    adj.sort()
    return adj

def _adjust_merge(padj, p0, adj):
    p0 = p0.copy()
    p0[adj] = padj
    return p0

def _complex2real(z, reshape_real=True):
    # contiguous is required by view when changing type.
    # It can be non contiguous if a selector skips data.
    conv = lambda z, t: np.ascontiguousarray(z).view(t).reshape(z.shape + (2,))
    if np.iscomplexobj(z):
        if z.ndim == 0:
            z = z.reshape((1,))
        if z.dtype == np.complex128:
            return conv(z, np.float64)
        elif z.dtype == np.complex64:
            return conv(z, np.float32)
        #elif z.dtype == np.complex256:
        #    return conv(z., np.float128)
        else:
            raise NotImplementedError('complex type not handled')
    elif reshape_real: # if not complex but want a matching shape
        return z[..., np.newaxis]
    raise NotImplementedError('type not handled')

def fitcurve(func, x, y, p0, yerr=None, extra={}, errors=True, adjust=None, noadjust=None, sel=None, skip=False, **kwarg):
    """
    func is the function. It needs to be of the form:
          f(x, p1, p2, p3, ..., k1=1, k2=2, ...)
    can also be defined as
          f(x, *ps, **ks)
          where ps will be a list and ks a dictionnary
    where x is the independent variables. All the others are
    the parameters (they can be named as you like)
    The function can also have and attribute display_str that contains
    the function representation in TeX form (func.display_str='$a_1 x+b x^2$')

    The fit always minimizes
     sum( ((func(x,..)-y)/yerr)**2 )

    x is the independent variable (passed to the function). It can be any shape.
      It can be a tuple of arrays (result from meshgrid)
    y is the dependent variable.
      y and funct(x,...) need to be of the same shape and need to be arrays.
        They can be multi-dimensional.
        It can also be a complex value (minimizes real and imaginary parts)
    p0 is a vector of the initial parameters used for the fit. It needs to be
    at least as long as all the func parameters without default values.

    yerr when given is the value of the sigma (the error) of all the y.
         It needs a shape broadcastable to y, so it can be a constant.
         When not given, the minimazation proceeds using yerr=1. internally.
         If complex, then the real(imag) is the error on the real(imag) of y.

    extra is a way to specify any of the function parameters that
          are not included in the fit. It needs to be a dictionnary.
          It will be passed to the function evaluation as
           func(..., **extra)
          so if extra={'a':1, 'b':2}
          which is the same as extra=dict(a=1, b=2)
          then the function will be effectivaly called like:
           func(x, *p, a=1, b=2)
    errors controls the handling of the yerr.
           It can be True (default), or False.
           When False, yerr behave as fitting weights w:
            w = 1/yerr**2
           The fit error is then independent of sum(w)

    adjust and noadjust select the parameters to fit.
           They are both lists, or slices.
           For lists, the elements can be the index of the parameter
           or the name of the parameter (according to the function definition).
           noadjust is applied after adjust and removes parameters from
           fitting. The default is to adjust all the parameters in p0
           Example: with f(x, a, b, c, d, e, f=1)
             fitcurve(f,x,y, [1,2,3,4,5], adjust=[1, 2, 'e'])
              will adjust parameter b, c and e only
             fitcurve(f,x,y, [1,2,3,4,5], noadjust=[1,2])
              will adjust parameter a, d and e
             fitcurve(f,x,y, [1,2,3,4,5], adjust=slice(1,4), noadjust=[1,2])
              will adjust parameter d only (adjust selects, b,c,d; noadjusts
              removes b,c)
             fitcurve(f,x,y, [1,2,3,4,5,6], noadjust=[1,2])
              will adjust parameter c,d,e and also f
    sel is a point selector. It can be a slice or a list of indices, or a
        tuple of those (you can also use the Ellipsis).
        It is applied on x, y and yerr to limit the range of samples used in
        the fit. When left as None, all the points are used.
        For this to work in multiple dimensions requires y.shape to start with
        the same as x.shape (unless Ellipsis are used.)
        Can use numpy.s_ to build complicated indexing.

    skip when True, functions does not perform fit and only returns
        chi2, chiNorm

    The kwarg available are the ones for leastsq (see its documentation):
      The tolerances when set to 0 is the same as the machine precision
       (2.22044604926e-16 for double). The tests are done as <=
     ftol: relative tolerance test on chi2
     xtol: relative tolerance test on largest fitting parameter (they
           are rescaled by diag)
     gtol: relative tolerance test on angle of solutions
     maxfev: maximum number of iterations. When 0 it is set to
             100*(N+1) or 200*(N+1) if Dfun is given or not. (N is
             number of fit para).
     epsfcn: Used in calculation derivatives (when Dfun is not given).
             will do (f(x)+f(x+p))/p, where p is from sqrt(epsfcn)*x
             or just sqrt(epsfcn) if x==0. When epsfcn=0 it is equivalent
             to setting it toe the machine precision.
     factor: Controls the initial step size.
     diag:  a vector (the same length as the fitting parameters)
            that forces the scaling factors (positive values)
            None (defaults) is auto calculated (mode = 1) and readjusted
            for each iterations.
     Dfun:  This is the vector of derivative of the function with
            respect to the fit parameters.
            It does not handle adjust/noadjust.
            It is called as f(p, x, y, yerr)
     col_deriv: Set to True when Dfun is [f1', f2', f3']
                It will then internally do a transpose to
                provide it in Fortran order.

    Returns pf, chi2, pe, extras
      pf is the fit result
      chi2 is the chi square
      pe are the errors on pf
          Without a yerr given, or with a yerr and errors=False,
          it does the needed correction to make chiNornm==1.
          With a yerr given and errors=True: it takes into account
          of the yerr and does not consider chiNorm at all.

      extras is chiNorm, sigmaCorr, s, covar, nfev
       chiNorm is the normalized chi2 (divided by the degree of freedom)
               When the yerr are properly given (and errrors=True), it should
               statistically tend to 1.
       sigmaCorr is the correction factor to give to yerr, or the yerr themselves
                 (if yerr is not given) thats makes chiNornm==1
       s are the errors. It is either yerr, when they are given (and errors=True)
         or the estimated yerr assuming chiNornm==1
       nfev is the number of functions calls

     Note that this routine does not implement limits. If you need to limit
     the range of the fit, you can make the chi2 grow much larger outside of the
     range of validity, or you can wrap your variable using modulo arithmetic
     or some other trick.
    """
    do_corr = not errors
    if yerr is None:
        yerr = 1.
        do_corr = True
    p0 = np.array(p0, dtype=float) # this allows complex indexing lik p0[[1,2,3]]
    adj = _handle_adjust(func, p0, adjust, noadjust)
    y = np.asarray(y)
    yerra = np.asarray(yerr)
    if sel is not None:
        y = y[sel]
        x = x[sel]
        if yerra.size > 1:
            yerr = yerra = yerra[sel]
    Ny = y.size
    # we returned a flat vector.
    if np.iscomplexobj(y):
        Ny = y.size*2
        yerra = _complex2real(yerra)
        f = lambda p, x, y, yerr: (_complex2real(func(x, *_adjust_merge(p, p0, adj), **extra)-y)/yerr).reshape(-1)
    else:
        f = lambda p, x, y, yerr: ((func(x, *_adjust_merge(p, p0, adj), **extra)-y)/yerr).reshape(-1)
    if not skip:
        p, cov_x, infodict, mesg, ier = leastsq(f, p0[adj], args=(x, y, yerra), full_output=True, **kwarg)
        if ier not in [1, 2, 3, 4]:
            print('Problems fitting:', mesg)
    else:
        p = p0[adj]
    chi2 = np.sum(f(p, x, y, yerra)**2)
    Ndof = Ny - len(p)
    chiNorm = chi2/Ndof
    sigmaCorr = np.sqrt(chiNorm)
    if skip:
        return chi2, chiNorm
    if cov_x is not None:
        pe = np.sqrt(cov_x.diagonal())
        pei = 1./pe
        covar =  cov_x*pei[None,:]*pei[:,None]
    else: # can happen with a singular matrix (very flat curvature in some direction)
        pe = p*0. -1 # same shape as p but with -1
        covar = None
    s = yerr
    if do_corr:
        pe *= sigmaCorr
        s = yerr*sigmaCorr
    extras = dict(mesg=mesg, ier=ier, chiNorm=chiNorm, sigmaCorr=sigmaCorr, s=s, covar=covar, nfev=infodict['nfev'])
    p_all = p0.copy()
    pe_all = np.zeros_like(p0)
    p_all[adj] = p
    pe_all[adj] = pe
    return p_all, chi2, pe_all, extras


def _errorbar(ax, x, y, yerr=None, label=None, **kwarg):
    if yerr is not None:
        yerr = np.asarray(yerr)
    labels = None
    if np.iscomplexobj(y):
        y = _complex2real(y)
        if yerr is not None:
            yerr = _complex2real(yerr)
        labels = ['_real', '_imag']
    if y.ndim > 1:
        if yerr is not None:
            yerr = np.broadcast_to(yerr, y.shape)
        N = y.shape[-1]
        ret = []
        if labels is None:
            labels = ['_%i'%i for i in range(N)]
        for i in range(N):
            if label not in [None, '_nolegend_']:
                l = label+labels[i]
            else:
                l = label
            if yerr is not None:
                ye = yerr[..., i]
            else:
                ye = None
            ret.append(ax.errorbar(x, y[...,i], yerr=ye, label=l, **kwarg))
    else:
        if yerr is not None and yerr.shape == ():
            yerr = yerr[()] # convert numpy 0d array (scalar) to scalar. matplotlib 2.1.0 does not like 0d array.
        ret = ax.errorbar(x, y, yerr=yerr, **kwarg)
    return ret


# TODO: better handling of colors with multiple curves
def fitplot(func, x, y, p0, yerr=None, extra={}, sel=None, fig=None, skip=False, hold=False,
                  col_fit='red', col_data=None, col_unsel_data=None, label=None, result_loc='upper right',
                  xpts=1000, xlabel=None, ylabel=None, title_fmt={}, **kwarg):
    """
    This does the same as fitcurve (see its documentation)
    but also plots the data, the fit on the top panel and
    the difference between the fit and the data on the bottom panel.
    sel selects the point to use for the fit. The unselected points are plotted
        in a color closer to the background.
    xpts selects the number of points to use for the xscale (from min to max)
         or it can be a tuple (min, max, npts)
         or it can also be a vector of points to use directly
         or it can be 'reuse' to reuse the x data.

    fig selects which figure to use. By default it uses the currently active one.
    skip when True, prevents the fitting. This is useful when trying out initial
         parameters for the fit. In this case, the returned values are
         (chi2, chiNorm)
    hold: when True, the plots are added on top of the previous ones.
    xlabel, ylabel: when given, changes the x and y labels.
    title_fmt is the options used to display the functions.
           For example to have a larger title you can use:
           title_fmt = dict(size=20)
    col_fit, col_data, col_unsel_data: are respectivelly the colors for the
           fit, the (selected) data and the unselected data.
           By default, the fit is red, the others cycle.
    label is a string used to label the curves. 'data' or 'fit' is appended
    result_loc when not None, is the position where the parameters will be printed.
            the box is draggable.
               see plotResult
    On return the active axis is the main one.
    """
    x = np.asarray(x)
    y = np.asarray(y)
    if fig:
        fig=plt.figure(fig)
    else:
        fig=plt.gcf()
    if title_fmt.get('verticalalignment', None) is None:
        # This prevents the title from leaking into the axes.
        title_fmt['verticalalignment'] = 'bottom'
    if not hold:
        plt.clf()
    if label is not None:
        data_label = label+' data'
        fit_label = label+' fit'
    else:
        data_label = 'data'
        fit_label = 'fit'
    fig, (ax1, ax2) = plt.subplots(2,1, sharex=True, num=fig.number)
    ax1.set_position([.125, .30, .85, .60])
    ax2.set_position([.125, .05, .85, .20])
    if not hold and col_fit == 'red':
        # skip red from color cycle.
        # here it gets hard coded
        try:
            # new in matplotlib 1.5
            ax1.set_prop_cycle('color', ['b', 'g', 'c', 'm', 'y', 'k'])
        except AttributeError:
            ax1.set_color_cycle(['b', 'g', 'c', 'm', 'y', 'k'])
    if col_data is None:
        # This is a bit of a hack, a matplotlib update could break this.
        # Another way would be to create a plot, use get_color() on it and remove the plot.
        try:
            # This works from 2.1
            col_data = ax1._get_lines.get_next_color()
        except AttributeError:
            try:
                # new in matplotlib 1.5
                col_data = ax1._get_lines.prop_cycler.next()['color']
            except AttributeError:
                col_data = ax1._get_lines.color_cycle.next()
    if col_fit is None:
        try:
            # new in matplotlib 1.5
            col_fit = ax1._get_lines.prop_cycler.next()['color']
        except AttributeError:
            col_fit = ax1._get_lines.color_cycle.next()
    if col_unsel_data is None:
        col = matplotlib.colors.colorConverter.to_rgb(col_data)
        bgcol = matplotlib.colors.colorConverter.to_rgb(_get_axis_bgcolor(ax1))
        # move halfway between col abd bgcol
        col = np.array(col)
        bgcol = np.array(bgcol)
        col_unsel_data = tuple( (col+bgcol)/2. )
    if xlabel is not None:
        ax1.set_xlabel(xlabel)
    if ylabel is not None:
        ax1.set_ylabel(ylabel)
    plt.sca(ax1) # the current axis on return
    if sel is not None:
        xsel = x[sel]
        ysel = y[sel]
        if yerr is not None:
            yerr_arr = np.asarray(yerr)
            if yerr_arr.size > 1:
                yerrsel = yerr_arr[sel]
            else:
               yerrsel = yerr
        else:
           yerrsel = yerr
        _errorbar(ax1, x, y, yerr=yerr, fmt='.', label='_nolegend_', color=col_unsel_data)
    else:
        xsel = x
        ysel = y
        yerrsel = yerr
    if xpts == 'reuse':
        xx = x
    elif isinstance(xpts, (list, np.ndarray)):
        xx = xpts
    elif isinstance(xpts, tuple):
        xx = np.linspace(xpts[0],xpts[1], xpts[2])
    else:
        xx = np.linspace(x.min(), x.max(), xpts)
    err_func = lambda x, y, p: func(x, *p, **extra) - y
    if skip:
        pld1 = _errorbar(ax1, xsel, ysel, yerr=yerrsel, fmt='.', label=data_label, color=col_data)
        pld2 = _errorbar(ax2, xsel, err_func(xsel, ysel, p0), yerr=yerrsel, fmt='.', label=data_label, color=col_data)
    if np.iscomplexobj(ysel):
        func_z = lambda *args, **kwargs: _complex2real(func(*args, **kwargs))
    else:
        func_z = func
    pl = ax1.plot(xx, func_z(xx, *p0, **extra), '-', color=col_fit, label=fit_label)
    try:
        plt.title(func.display_str, **title_fmt)
    except AttributeError: # No display_str
        pass
    fig.canvas.draw()
    #plt.draw()
    if not skip:
        p, resids, pe, extras = fitcurve(func, xsel, ysel, p0, yerr=yerrsel, extra=extra, **kwarg)
        printResult(func, p, pe, extra=extra)
        #pld1.remove()
        _errorbar(ax1, xsel, ysel, yerr=extras['s'], fmt='.', label=data_label, color=col_data)
        fz = func_z(xx, *p, **extra)
        if fz.ndim == 1:
            fz = fz[..., np.newaxis]
        for i in range(len(pl)):
            pl[i].set_ydata(fz[..., i])
        ax1.relim() # this is needed for the autoscaling to use the new data
        #pld2.remove()
        _errorbar(ax2, xsel, err_func(xsel, ysel, p), yerr=extras['s'], fmt='.', label=data_label, color=col_data)
        ax2.autoscale_view(scalex=False) # only need to rescale y
        ax1.autoscale_view(scalex=False) # only need to rescale y
        for t in ax1.texts:
            if isinstance(t, matplotlib.text.Annotation):
                t.remove()
                break
        if result_loc is not None:
            plotResult(func, p, pe, extra=extra, loc=result_loc, ax=ax1)
        fig.canvas.draw()
        #plt.draw()
        return p, resids, pe, extras
    else:
        chi2, chiNorm = fitcurve(func, xsel, ysel, p0, yerr=yerrsel, extra=extra, skip=True, **kwarg)
        return chi2, chiNorm

if __name__ == "__main__":
    from pyHegel.fit_functions import noiseRFfit
    from pyHegel import gen_poly
    N = 200
    x = np.linspace(-0.22e-3, 0.21e-3, N)
    y = noiseRFfit(x, 0.069, -.22e-3, 8., 0.113e-3, f=20e9, R=70., N=100)
    y += np.random.randn(N) * 1e-5
    res = fitcurve(noiseRFfit, x, y,[0.05, -.003,4.,.01e-3], extra=dict(N=10,f=20e9))
    fitplot(noiseRFfit, x, y,[.05, -.003,4.,.01e-3], extra=dict(N=10,f=20e9),skip=1, fig=1)
    res2 = fitplot(noiseRFfit, x, y,[.05, -.003,4.,.01e-3], extra=dict(N=10,f=20e9), fig=2)
    res3 = fitplot(noiseRFfit, x, y,[.05, -.003,4.,.01e-3], extra=dict(N=10,f=20e9), yerr=1e-5, fig=3)
    res4 = fitplot(noiseRFfit, x, y,[.05, -.003,4.,.01e-3], extra=dict(N=10,f=20e9), yerr=1e-6, fig=4)
    print('-----------------------------------------')
    print(' Comparison with poly fit')
    linfunc = lambda x, b, m, c:   c*x**2 + m*x + b
    yl = linfunc(x, 1.e-3,2,3.e3)
    yl += np.random.randn(N) * 2e-5
    yerr = 2e-5
    #yerr = 1e-4
    #yerr = None
    resnl = fitcurve(linfunc, x, yl,[1,1,1], yerr=yerr)
    fitplot(linfunc, x, yl,[1e-3,2.,3.e3],fig=5, yerr=yerr, skip=True)
    print(resnl)
    resp = gen_poly.gen_polyfit(x, yl, 3, s=yerr)
    print(resp)
    print('-----------------------------------------')
    plt.show()
