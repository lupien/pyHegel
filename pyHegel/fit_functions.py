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

"""
This module contains many tools for fitting data
"""

from __future__ import absolute_import

import numpy as np
import scipy.constants as C
from scipy.special import jn

def poly(x, a, b=0., c=0., d=0., e=0.):
    """
    This functions returns the general polynomial function:
        a + b*x + c*x**2 + d*x**3 + e*x**4
    For polynomial fit it is recommended to use the gen_poly module
    """
    return a + b*x + c*x**2 + d*x**3 + e*x**4
poly.display_str = r"$a + b x + c x^2 + d x^3 + e x^4$"


def linear(x, b, m=0.):
    """
    This functions returns the standard linear function: mx + b
    For linear fit it is recommended to use the gen_poly module
    """
    return m*x+b
linear.display_str = r"$m x + b$"

def gaussian(x, sigma, mu=0., A=1.):
    """
    This functions returns the Gaussian function (normal distribution)
       (A/sqrt(2*pi*sigma**2)) exp(- (x-mu)**2/(2*sigma**2))
    A is a scaling factor that multiplies the statistical distribution.
    Leave it a 1. if your data is properly normalized.
    The maximum (at mu) is: A/sqrt(2*pi*sigma**2)
    The half width at half max is: sigma*sqrt(2*log(2)) for log the base e log.
    The Fourier transform (to k) is the same function but with x, A, mu and sigma replaced
    by k, A', mu', sigma' which are given by:
       A'=(A/sigma)*exp(-1j*k*mu),  mu'=0,  sigma'=1/sigma
    """
    s2 = sigma**2.
    norm = 1./np.sqrt(2*np.pi*s2)
    k = -(x-mu)**2./(2.*s2)
    return A*norm*np.exp(k)
gaussian.display_str = r"$A \frac{1}{\sqrt{2\pi\sigma^2}} e^{- \frac{1}{2} \left( \frac{x-\mu}{\sigma}\right)^2}$"

def lorentzian(x, Gamma, xo=0., A=1.):
    """
    This functions returns the Lorentzian function (Lorentz or Cauchy distribution).
       (A/pi) * Gamma/((x-xo)**2 + Gamma**2  )
    It is often used for spectral lines or resonances.
    Gamma is half width at half max.
    xo is center.
    A is a scaling factor that multiplies the statistical distribution.
    Leave it a 1. if your data is properly normalized.
    The maximum of the function (at xo) is 2A/(pi Gamma)
    It has an inverse Fourier transform of: A*exp(1j*xo*t - Gamma*abs(t))/sqrt(2*pi), if x was w (radial frequency)
    It has no mean nor variance (nor any higher moments).
    See also: lorentzian_cnst_h
    """
    return (A/np.pi)* Gamma/((x-xo)**2 + Gamma**2)
lorentzian.display_str = r"$A \, \frac{1}{\pi} \,\frac{\Gamma}{\left(x - x_0\right)^2 + \left( \Gamma\right)^2}$"

def lorentzian_cnst_h(x, Gamma, xo=0., A=1.):
    """
    This functions returns the Lorentzian function (Lorentz or Cauchy distribution),
    but normalized to keep a constant height at maximum of A (indepedent of Gamma)
       A * Gamma**2/((x-xo)**2 + Gamma**2  )
    This can be mapped to the resonance of an RLC circuit:
       vr/vs = jwCR / ( 1- L*C*w**2 +jwCR )
    The lorentzian is an approximation to |vr/vs|**2, for small dissipation (large Q),
    with xo = wo = 1/sqrt(LC) and Gamma = (R*C*wo**2)/2 = R/(2*L) and A=1

    See also: lorentzian

    Intermediate step:
       |vr/vs|**2 = (w*R*C)**2 / ( (w-wo)**2 * (w+wo)**2/wo**4 + (w*R*C)**2 )
       and approximate w+wo with 2wo, and w*R*C with wo*R*C
    """
    return A* Gamma**2/((x-xo)**2 + Gamma**2)
lorentzian.display_str = r"$A \frac{\Gamma^2}{\left(x - x_0\right)^2 + \left( \Gamma\right)^2}$"

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
    ###   could also have used:
    # with np.errstate(invalid='ignore', divide='ignore'):
    #     return np.nan_to_num(nx/np.tanh(nx))
    ###
    # np.nan_to_num before numpy version 1.17 does not have the option to change nan to something
    # other than 0. To do that, use np.
    # For numpy before 1.12.0 0/0 error was divide, now it is invalid
    #  nan_to_num and errstate exist since at least numpy v1.3
xcothx.display_str = r"$\frac{x}{\tanh(x)}"

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

