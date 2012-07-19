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


# the argument names from a function are obtained with:
# v=inspect.getargspec(sinc)
# v[0]
# v.args

def noisePower(V, T, R):
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

def noisefitV(V, A, T, R, Toffset):
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

def noisefitI(I, Amp, T, R, Toffset):
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
    return amp*(noisePower(I*R, T, R)+offset)/Aunit
noisefitI.display_str = r"$\frac{A}{4k_B T/R}\left(2eI \coth\left(\frac{eIR}{2k_B T}\right) +\frac{4 k_B T_{offset}}{50})\right)$"

def noiseRF(Vdc, Vac, f, T, R, N=100):
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


def noiseRFfit(Vdc, A, Toffset, Vac, T, f=20e9, R=70., N=100):
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
    return A*(noiseRF(Vdc, Vac, f, T, R, N)+offset)/Aunit
noiseRFfit.display_str = r"$ A \left(\left[\sum_{n=-N}^{N} J_n(e V_{AC}/hf)^2 \frac{e V_{DC}-nhf}{2 k_B T} \coth\left(\frac{e V_{DC}-nhf}{2 k_B T} \right)\right] + T_{offset}/T\right)$"

def fitcurve(func, x, y, p0, yerr=None, extra={}, **kwarg):
    """
    The kwarg available are the ones for leastsq: 
     ftol
     xtol
     gtol
     maxfev
     epsfcn
     factor
     diag
    Returns pf, chi2, pe, extras
      extras is chiNorm, sigmaCorr, s, covar
    """
    do_corr = False
    if yerr == None:
        yerr = 1.
        do_corr = True
    f = lambda p, x, y, yerr: (y-func(x, *p, **extra))/yerr
    p, cov_x, infodict, mesg, ier = leastsq(f, p0, args=(x, y, yerr), full_output=True, **kwarg)
    if ier != 1:
        print 'Problems fitting:', mesg
    chi2 = np.sum(f(p, x, y, yerr)**2)
    Ndof = len(x)- len(p)
    chiNorm = chi2/Ndof
    sigmaCorr = np.sqrt(chiNorm)
    pe = np.sqrt(cov_x.diagonal())
    pei = 1./pe
    covar =  cov_x*pei[None,:]*pei[:,None]
    s = yerr
    if do_corr:
        pe *= sigmaCorr
        s *= sigmaCorr
    extras = dict(mesg=mesg, ier=ier, chiNorm=chiNorm, sigmaCorr=sigmaCorr, s=s, covar=covar)
    return p, chi2, pe, extras


def fitplot(func, x, y, p0, yerr=None, extra={}, fig=None, skip=False, **kwarg):
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
    plt.errorbar(x, y-func(x, *p0, **extra), yerr=yerr, fmt='.')
    plt.draw()
    if not skip:
        p, resids, pe, extras = fitcurve(func, x, y, p0, yerr=yerr, extra=extra, **kwarg)
        #xx.set_ydata(func(xx, *p, **extra))
        plt.sca(ax1)
        plt.cla()
        plt.errorbar(x, y, yerr=extras['s'], fmt='.', label='data')
        plt.plot(xx, func(xx, *p, **extra), 'r-')
        plt.sca(ax2)
        plt.cla()
        plt.errorbar(x, y-func(x, *p, **extra), yerr=extras['s'], fmt='.')
        try:
            plt.sca(ax1)
            plt.title(func.display_str)
        except AttributeError: # No display_str
            pass
        plt.draw()
        return p, resids, pe, extras


if __name__ == "__main__":
    import gen_poly
    N = 200
    x = np.linspace(-0.22e-3, 0.21e-3, N)
    y = noiseRFfit(x, -.22e-3, 8., 0.113e-3, 0.069, f=20e9, R=70., N=100)
    y += np.random.randn(N) * 1e-5
    res = fitcurve(noiseRFfit, x, y,[-.003,4.,.01e-3,.05], extra=dict(N=10,f=20e9))
    fitplot(noiseRFfit, x, y,[-.003,4.,.01e-3,.05], extra=dict(N=10,f=20e9),skip=1, fig=1)
    res2 = fitplot(noiseRFfit, x, y,[-.003,4.,.01e-3,.05], extra=dict(N=10,f=20e9), fig=2)
    res3 = fitplot(noiseRFfit, x, y,[-.003,4.,.01e-3,.05], extra=dict(N=10,f=20e9), yerr=1e-5, fig=3)
    res4 = fitplot(noiseRFfit, x, y,[-.003,4.,.01e-3,.05], extra=dict(N=10,f=20e9), yerr=1e-6, fig=4)
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
