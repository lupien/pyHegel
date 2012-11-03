# -*- coding: utf-8 -*-
# vim: set autoindent shiftwidth=4 softtabstop=4 expandtab:

"""
This module contains many tools for fitting data
"""

import numpy as np
import inspect
import scipy.constants as C
from scipy.special import jn
from scipy.optimize import leastsq
# see also scipy.optimize.curve_fit
import matplotlib.pylab as plt
import collections
import __builtin__

def xcothx(x):
    """
    This functions returns the x/tanh(x) and does the proper thing
    when x=0.
    """
    # similar to sinc function
    x = np.asanyarray(x)
    # remove 0 from x
    nx = np.where(x==0, 1e-16, x)
    # 1e-8 is enough to give exactly 1.
    #return where(x==0, 1., nx/tanh(nx))
    return nx/np.tanh(nx)

def noisePower(V, T, R=50.):
    """
    Use this function to fit the noise power (from a diode).
    T is in Kelvin
    V in Volts is the dc voltage on the sample
    R in Ohms of the tunnel junction
    The returned values is the noise power density.
    i.e. (I-Iavg)^2
    The current is obtained by integrating over the bandwidth.

    For V=0, this is 4 kB T/R
    For large V this tends to 2e V/R
    """
    kbt = C.k*T
    v = C.e * V / (2.*kbt)
    return xcothx(v) * (4.*kbt/R)
noisePower.display_str = r"$2e\frac{V}{R} \coth\left(\frac{eV}{2k_B T}\right)$"

def noisefitV(V, T, A, Toffset, R=50.):
    """
    Use this function to fit. Based on noisePower.
    Use this when you know the applied DC voltage (in volts) on the sample.
    A is the scale of the fit. It contains the effect of the
    bandwidth and the amplifiers gains. In the measurement unit.
    The Toffset is in units of Kelvin and is the noise temperature of the
    amplifiers, assuming Ro=50 Ohms.
    """
    kbt = C.k*T
    offset = 4.*C.k*Toffset/50.
    Aunit = 4.*kbt/R
    return A*(noisePower(V, T, R)+offset)/Aunit
noisefitV.display_str = r"$\frac{A}{4k_B T/R}\left(2e\frac{V}{R} \coth\left(\frac{eV}{2k_B T}\right) +\frac{4 k_B T_{offset}}{50})\right)$"

def noisefitI(I, T, A, Toffset, R=50.):
    """
    Use this function to fit. Based on noisePower.
    Use this when you know the applied DC current (in amps) on the sample.
    A is the scale of the fit. It contains the effect of the
    bandwidth and the amplifiers gains. In the measurement unit.
    The Toffset is in units of Kelvin and is the noise temperature of the
    amplifiers, assuming Ro=50 Ohms.
    """
    kbt = C.k*T
    offset = 4.*C.k*Toffset/50.
    Aunit = 4.*kbt/R
    return A*(noisePower(I*R, T, R)+offset)/Aunit
noisefitI.display_str = r"$\frac{A}{4k_B T/R}\left(2eI \coth\left(\frac{eIR}{2k_B T}\right) +\frac{4 k_B T_{offset}}{50})\right)$"

def noiseRF(Vdc, T, Vac, f, R=50., N=100):
    """
    Vdc in Volts
    RF signal of Vac (Volts peak) at frequency f (Hz)
    T in Kelvin
    R in Ohms of the junction.
    N is the limit of the sum of bessels (from -N to +N)
    """
    hf = C.h*f
    kbt = C.k*T
    ev = C.e*Vdc
    vac = C.e*Vac/hf
    n = np.arange(-N, N+1)[:,None]
    x=(ev-n*hf)/(2.*kbt)
    tmp = jn(n,vac)**2 *xcothx(x)
    return tmp.sum(axis=0) * (4*kbt/R)
noiseRF.display_str = r"$\frac{4 k_B T}{R} \sum_{n=-N}^{N} J_n(e V_{AC}/hf)^2 \frac{e V_{DC}-nhf}{2 k_B T} \coth\left(\frac{e V_{DC}-nhf}{2 k_B T}\right)$"


def noiseRFfit(Vdc, T, A, Toffset, Vac, f=20e9, R=70., N=100):
    """
    A is the scale of the fit. It contains the effect of the
    bandwidth and the amplifiers gains. In the measurement unit.
    The Toffset is in units of Kelvin and is the noise temperature of the
    amplifiers, assuming Ro=50 Ohms.

    Vdc in Volts
    RF signal of Vac (Volts peak) at frequency f (Hz)
    T in Kelvin
    R in Ohms of the junction.
    N is the limit of the sum of bessels (from -N to +N)
    """
    kbt = C.k*T
    offset = 4.*C.k*Toffset/50.
    Aunit = 4.*kbt/R
    return A*(noiseRF(Vdc, T, Vac, f, R, N)+offset)/Aunit
noiseRFfit.display_str = r"$ A \left(\left[\sum_{n=-N}^{N} J_n(e V_{AC}/hf)^2 \frac{e V_{DC}-nhf}{2 k_B T} \coth\left(\frac{e V_{DC}-nhf}{2 k_B T} \right)\right] + T_{offset}/T\right)$"



#########################################################
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
    (args, varargs, varkw, defaults) = inspect.getargspec(func)
    if defaults == None:
        Nkw = 0
    else:
        Nkw = len(defaults)
    Nall = len(args)
    Narg = Nall-Nkw
    para = args[:Narg]
    kwpara = args[Narg:]
    return (para, kwpara, varargs, varkw, defaults)

def toEng(p, pe, signif=2):
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
    pe10Eng = (int(np.floor(pe10+2))/3)*3.
    #For p make the rescaled value
    # between 499 and 0.5
    p10Eng = (int(np.floor(p10 - np.log10(.5)))/3)*3.
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
        return '%r'%p, None, None
    if pe == 0:
        if p == 0:
            return '0', None, '0'
        else:
            return ( '{0!r}'.format(p_rescaled, prec=frac_prec), None, '%i'%expEng )
    else:
        return ( '{0:.{prec}f}'.format(p_rescaled, prec=frac_prec),
                 '{0:.{prec}f}'.format(pe_rescaled, prec=frac_prec), '%i'%expEng )

def _split_decimal(s):
    if s == None:
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
        pstr_l, pstr_r = _split_decimal(pstr)
        pestr_l, pestr_r = _split_decimal(pestr)
        if expstr == None:
            expstr = ''
        elif pestr == None:
            noerr_i.append(i)
        else:
            full_i.append(i)
        r = [name, pstr_l, pstr_r, pestr_l, pestr_r, expstr]
        ret_str.append(r)
        ret_len.append( map(len,r) )
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

def printResult(func, p, pe, extra={}, signif=2):
    (para, kwpara, varargs, varkw, defaults) = getVarNames(func)
    N = len(p)
    Npara = len(para) -1
    para = para[1:] # first para is X
    if len(pe) != N:
        raise ValueError, "p and pe don't have the same dimension"
    if Npara > N:
        raise ValueError, "The function has too many positional parameters"
    if Npara < N and varargs == None and kwpara == None:
        raise ValueError, "The function has too little positional parameters"
    if Npara < N and varargs != None:
        # create extra names par1, par2, for all needed varargs
        para.extend(['par%i'%(i+1) for i in range(N-Npara)])
    elif Npara < N and kwpara != None:
        para.extend(kwpara[:N-Npara])
        kwpara = kwpara[N-Npara:]
        defaults = defaults[N-Npara:]
    if defaults != None:
        kw = collections.OrderedDict(zip(kwpara, defaults))
    else:
        kw = {}
    kw.update(extra)
    splits, maxlen, maxlen_noerr = _splitResult(para+kw.keys(), list(p)+kw.values(), list(pe)+[0]*len(kw), signif=signif)
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

def _handle_adjust(func, p0, adjust, noadjust):
    if adjust == None and noadjust == None:
        return slice(None)
    Np = len(p0)
    all_index = range(Np)
    para, kwpara, varargs, varkw, defaults = getVarNames(func)
    names = para
    Npara = len(para)
    if Npara < Np:
        names += kwpara[:Np-Npara]
    if isinstance(adjust, slice):
        adjust = all_index(adjust)
    if isinstance(noadjust, slice):
        adjust = all_index(noadjust)
    if adjust == None:
        adjust = all_index
    if noadjust == None:
        noadjust = []
    #s = set() # This fails when running under pyHegel (not on import).
    s = __builtin__.set()
    # cleanup adjust. Remove duplicates, handle named variables.
    for a in adjust:
        if isinstance(a, basestring):
            s.add(names.index(a)-1) # -1 to remove the x parameter of f(x, p1, ...)
        else:
            s.add(a)
    # Now cleanup noadjust
    sna = __builtin__.set()
    for na in noadjust:
        if isinstance(na, basestring):
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

def fitcurve(func, x, y, p0, yerr=None, extra={}, errors=True, adjust=None, noadjust=None, **kwarg):
    """
    func is the function. It needs to be of the form:
          f(x, p1, p2, p3, ..., k1=1, k2=2, ...)
    can also be defined as
          f(x, *ps, **ks)
          where ps will be a list and ks a dictionnary
    where x is the independent variables. All the others are
    the parameters (they can be named as you like)
    The function can also have and attribute display_str that contains
    the function representation in TeX form (func.disp='$a_1 x+b x^2$')

    x is the independent variable (passed to the function).
    y is the dependent variable. The fit will minimize sum((func(x,..)-y)**2)
    p0 is a vector of the initial parameters used for the fit. It needs to be
    at least as long as all the func parameters without default values.

    yerr when given is the value of the sigma (the error) of all the y.
         It needs a shape broadcastable to y, so it can be a constant.

    extra is a way to specify any of the function parameters that
          are not included in the fit. It needs to be a dictionnary.
          It will be passed to the function evaluation as
           func(..., **extra)
          so if extra={'a':1, 'b':2}
          which is the same as extra=dict(a=1, b=2)
          then the function will be effectivaly called like:
           func(..., a=1, b=2)
    errors controls the handling of the yerr.
           It can be True (default), or False.
           When False, yerr are used as fitting weights.
            w = 1/yerr**2

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
          it does the neede correction to make chiNornm==1.
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
    if yerr == None:
        yerr = 1.
        do_corr = True
    p0 = np.array(p0, dtype=float) # this allows complex indexing lik p0[[1,2,3]]
    adj = _handle_adjust(func, p0, adjust, noadjust)
    f = lambda p, x, y, yerr: (func(x, *_adjust_merge(p, p0, adj), **extra)-y)/yerr
    p, cov_x, infodict, mesg, ier = leastsq(f, p0[adj], args=(x, y, yerr), full_output=True, **kwarg)
    if ier not in [1, 2, 3, 4]:
        print 'Problems fitting:', mesg
    chi2 = np.sum(f(p, x, y, yerr)**2)
    Ndof = len(x)- len(p)
    chiNorm = chi2/Ndof
    sigmaCorr = np.sqrt(chiNorm)
    if cov_x != None:
        pe = np.sqrt(cov_x.diagonal())
        pei = 1./pe
        covar =  cov_x*pei[None,:]*pei[:,None]
    else: # can happen when with a singular matrix (very flat curvature in some direction)
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


def fitplot(func, x, y, p0, yerr=None, extra={}, errors=True, fig=None, skip=False, **kwarg):
    """
    This does the same as fitcurve (see its documentation)
    but also plots the data, the fit on the top panel and
    the difference between the fit and the data on the bottom panel.

    fig selects which figure to use. By default it uses the currently active one.
    skip when True, prevents the fitting. This is useful when trying out initial
         parameters for the fit. In this case, the returned values are
         (chi2, chiNorm)
    """
    if fig:
        fig=plt.figure(fig)
    else:
        fig=plt.gcf()
    plt.clf()
    fig, (ax1, ax2) = plt.subplots(2,1, sharex=True, num=fig.number)
    ax1.set_position([.125, .3, .85, .6])
    ax2.set_position([.125, .05, .85, .2])
    plt.sca(ax1)
    plt.errorbar(x, y, yerr=yerr, fmt='.', label='data')
    xx= np.linspace(x.min(), x.max(), 1000)
    pl = plt.plot(xx, func(xx, *p0, **extra), 'r-')[0]
    plt.sca(ax2)
    plt.cla()
    plt.errorbar(x, func(x, *p0, **extra)-y, yerr=yerr, fmt='.')
    plt.draw()
    if not skip:
        p, resids, pe, extras = fitcurve(func, x, y, p0, yerr=yerr, extra=extra, **kwarg)
        res_str = printResult(func, p, pe, extra=extra)
        print '\n'.join(res_str)
        #xx.set_ydata(func(xx, *p, **extra))
        plt.sca(ax1)
        plt.cla()
        plt.errorbar(x, y, yerr=extras['s'], fmt='.', label='data')
        plt.plot(xx, func(xx, *p, **extra), 'r-')
        plt.sca(ax2)
        plt.cla()
        plt.errorbar(x, func(x, *p, **extra)-y, yerr=extras['s'], fmt='.')
        try:
            plt.sca(ax1)
            plt.title(func.display_str)
        except AttributeError: # No display_str
            pass
        plt.draw()
        return p, resids, pe, extras
    else:
        if yerr==None:
            yerr=1
        f = lambda p, x, y, yerr: (func(x, *p, **extra)-y)/yerr
        chi2 = np.sum(f(p0, x, y, yerr)**2)
        Ndof = len(x)- len(p0)
        chiNorm = chi2/Ndof
        return chi2, chiNorm

if __name__ == "__main__":
    import gen_poly
    N = 200
    x = np.linspace(-0.22e-3, 0.21e-3, N)
    y = noiseRFfit(x, 0.069, -.22e-3, 8., 0.113e-3, f=20e9, R=70., N=100)
    y += np.random.randn(N) * 1e-5
    res = fitcurve(noiseRFfit, x, y,[0.05, -.003,4.,.01e-3], extra=dict(N=10,f=20e9))
    fitplot(noiseRFfit, x, y,[.05, -.003,4.,.01e-3], extra=dict(N=10,f=20e9),skip=1, fig=1)
    res2 = fitplot(noiseRFfit, x, y,[.05, -.003,4.,.01e-3], extra=dict(N=10,f=20e9), fig=2)
    res3 = fitplot(noiseRFfit, x, y,[.05, -.003,4.,.01e-3], extra=dict(N=10,f=20e9), yerr=1e-5, fig=3)
    res4 = fitplot(noiseRFfit, x, y,[.05, -.003,4.,.01e-3], extra=dict(N=10,f=20e9), yerr=1e-6, fig=4)
    print '-----------------------------------------'
    print ' Comparison with poly fit'
    linfunc = lambda x, b, m, c:   c*x**2 + m*x + b
    yl = linfunc(x, 1.e-3,2,3.e3)
    yl += np.random.randn(N) * 2e-5
    yerr = 2e-5
    #yerr = 1e-4
    #yerr = None
    resnl = fitcurve(linfunc, x, yl,[1,1,1], yerr=yerr)
    fitplot(linfunc, x, yl,[1e-3,2.,3.e3],fig=5, yerr=yerr, skip=True)
    print resnl
    resp = gen_poly.gen_polyfit(x, yl, 3, s=yerr)
    print resp
    print '-----------------------------------------'
    plt.show()
