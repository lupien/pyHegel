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

from __future__ import absolute_import, print_function, division

import numpy as np
import scipy.linalg as la
import types

from .comp2to3 import xrange

# TODO error handling

def oneDpoly(X,m,rank=None):
    """ m est le nombre de termes à créer. 
        if rank is given then the highest power will be rank
        (and m is not used)
    """
    if rank is not None: m=rank+1
    power=np.arange(m)
    #xs=X.shape+(1,) # add a broadcast dimension
    #return X.reshape(xs) ** power
    return X[...,np.newaxis] ** power

DefaultPoly = oneDpoly

def twoDpoly(X,m=3,rank=None):
    """ The first dimension of X as size 2 and represent the (x, y) coordinates
        On return the first dimensions is removed and a new dimension is 
        added at the end of lenght m
        if rank is given it is the rank of the polynomial and it will
        overide the m value
        The default m value is for a plane: z= a + bx + cy
               dxy would introduce some quadratic term.

        The terms for a certain rank need to from a closed group under
        rotation of the plane. For example. a rotation of 45 deg to give
        x', y' from x,y makes x= x'/s-y'/s and y=y'/s+x'/s with s=sqrt(2)
        Then  z=a+bx+cy+dxy becomes z=a+(b/s+c/s)x' + (c/s-b/s)y' +
                                      (d/s^2)(x'^2 - y'^2)
        Therefore to be a closed group you need to add 
               ex^2 + fy^2 and this gives the 2nd rank 2D polynomial

    """
    if rank is not None: m= (rank+1)*(rank+2)//2
    maxp=int(np.ceil(np.sqrt(m)))
    mr= list(range(maxp))
    powercomb = [[px,py] for px in mr for py in mr]
    # Sort in place first with the smallest sum of power
    # then with the smallest max power first i.e
    #  [1,1] before [0,2] and [2,0] 
    powercomb.sort(key=lambda x: [sum(x),max(x)])
    powercomb=np.array(powercomb[:m]) # pick only first m powers
    return X[0][...,np.newaxis]**powercomb[...,0] * X[1][...,np.newaxis]**powercomb[...,1]

def gen_polyeval(X, pf, param=None, sel=None):
    """ Calls func and returns created polynomial 

        here pf is a sequence (p,func)
        Pour le tableau x(N,...,M,T)=func(X,m,param) et p(T,S,P,Q,...), 
        m est T=p.shape[0]
        ou T est le nombre de parametre du fit et S,P,Q ... si présent 
        sont le nombre de lissage différents réalisé.

        Le résultat est Y(N,...,M,S,P,Q,...) = x(N,...,M,T+) * p(T+,S,P,Q,...)
           (le + indique a sum product: 2D produit matricielle)
        sel si definie fera ls sélection p[:,sel]
             sel can be the result of np.index_exp
              which is detected if sel is a tuple

        Les premières dimensions représenntent des conditions différentes
        (positions xy différentes ...) les dernières le résultat de différents
        lissage (des layers de carte 3D)

        DefaultPoly is the function used by default if func is
        None (initialized to oneDpoly

"""
    p,func = pf
    if not func: func = DefaultPoly
    m=p.shape[0]
    if sel is not None:
        if isinstance(sel,tuple):
            p=p[ (slice(None),)+sel ]
        else:
            p = p[:,sel]
    return np.tensordot(func(X,m,param),p,axes=(-1,0))

def lstsq_er(X,Y,cond=-1):
    # following numerical recipes
    # X= U S Vh
    # U, Vh are unitary matrices (orthogonal): So U U^T =1
    # s is diag
    # For X (N,M), 
    # then U, Vh are (N,K), (K,M)
    # s is (K) K=min(N,M) (really should be (K,K) but only keep diag elements)
    # Here M is the number of parameters so M<N so K=M
    # Y is either (N,) or (N,P)
    U,s,Vh = la.svd(X, full_matrices=False)
    TOL=1e-13 # for double: Also look at np.finfo(0.).eps and .resolution (base 10 rounded of .eps)
    if cond == -1: cond=TOL
    # s[0] should be s,max()
    s = np.where(s>cond*s[0], s,s*0.)
    invs = np.where(s!=0, 1./s, s*0.) 
    # The solution for Y (N,) or (N,L)
    # p = Vh^T S^-1 U^T Y
    #invsd = np.diag(invs)
    #p = np.dot(Vh.T, np.dot(invsd, np.dot(U.T, Y) )  )
    p = np.dot(Vh.T, (invs*(np.dot(U.T, Y)).T).T ) # faster maybe...
    # covar = (A^T A)^-1 =  V (S^T S)^-1 V^T
    #   (S^T S)^-1 = 1/diag^2   (the square of the inverse of the diag elements)
    #invsd2 = invsd**2
    #covar = np.dot(Vh.T, np.dot(invsd2, Vh) # covar is MxM
    covar = np.dot(Vh.T, Vh*(invs**2)[:,None]) #faster than above (one less dot)
    pe = np.sqrt(covar.diagonal())
    pei = 1./pe
    covar =  covar*pei[None,:]*pei[:,None]
    resids = np.sum( (Y.T-np.dot(X,p).T)**2, axis=-1)
    rank = len(np.flatnonzero(s))
    return p, resids, pe, (U,s,Vh,rank, covar)

def gen_polyfit(X,Y,m,s=None,func=None, param=None,adjust=None, p0=None, filter=None, errors=True, rcond=-1):
    """
       This calcutes the fit of a general polynomial expression
       method in yorick defaults to LUsolve, otherwise it is SVsolve
       Here we use scipy.linalg.lstsq

       La forme de x=func(X,m,param) est (M,..,N,T) 
        ou T est la liste de parametres de la reponse.
       Y est (M,...,N,S), ou S est optionnel et represente des
         solutions supplementaires  
       La reponse est soit 1D ou 2D

       s est l'erreur standard. Elle ajuste le poid du lissage.
       s est scalaire (effet seulement sur les erreurs, pas sur le lissage)
        ou s (M,...,N)
        ou s (M, ..., N, S) 
         Attention, dans ce dernier cas le lissage sera beaucoup plus lent
         puisque tous les S fit devront être fait séparément.
         Dans ce cas Y ne peut pas avoir 
       Si s n'est pas spécifié, c'est l'équivalent de s=1.
       Le lissage est le résultat de minimiser:
             \chi^2 = \sum_{i=1}^N {\left(\frac{y_i - f(x_i)}{s_i}\right)}^2
       En prenant les dérivés avec p (les paramètres) et en les mettant =0
       On trouve le minimum.
           puisque f(x_i) = p_0 x_i^0 + p_1 x_i^1 ...
           où x^n ne veut pas nécessairement duire la puissance n de x
           mais bien la combinaison n des éléments du vecteur x_i 
             (x_i est une vecteur de paramètre indépendant pour le point i)
           donc d chi^2/dp nous donne les équations
          X p = Y
        où X_k,l = sum_i (x_i^k x_i^l/s_i^2)
           p_l sont les paramètres
           Y_k = sum_i (y_i x_i^k/s_i^2)
        C'est le système d'équations que lstsq résous de façon interne.
        Ce qu'on donne à lstsq est X' p = Y'
        où X'_i,l = x_i^l/s_i
           p_l commen ci-haut
           Y'_i = y_i/s_i
         (La définition de lstsq utilise s_i =1)
        Pour obtenir X et Y de X' et Y' lstsq fait
         X=X'^T X',  Y=X'^T Y'  où ^T est la transpose
        Donc si on redéfinie X' et Y' comme ci-haut (divise par s_i)
        on exécutera une lissage linéaire avec poids variables.

       filter is a M,.., N matrix where 1 selects the data point
                                    and 0 deselects it
                                   (actually it is selected if >0.5)

       Si  Y(X) est un vecteur (Disons Y=(Yx, Yy) ou Yx=fx(x,y) et Yy=fy(x,y)
       pour un vecteur Y 2D dépédant d'un vecteur xy=(x,y) aussi 2D.
       Si Yy et Yx sont indépendant ils peuvent être lissé séparément.
       Si ils utilisent la même fonction mais des paramètres différents alors
       ils peuvent être lissé en même temps (Yx et Yy forment la dimension S
       de Y)
       Sinon, Yx et Yy doivent être combinés dans le même Y (sans la dimention S
       et le vecteur X ne sera pas le même pour les éléments Yx et Yy. 
       Certains des éléments de X seront mis à zéro si il ne s'applique pas aux
       deux avec le même paramètre.

       adjust is either an array(list) or a selector to pick the
          parameters to adjust (using their index).  
       You can set the value of the unused parameters with p0
         it should be a vector of shape T or T,S

       rcond is the same as in lstsq

       La fonction retourne: pf,resids,pe, extras
                où extras est un dict: chiNorm, sigmaCorr, rank, sv, covar (voir lstsq)
                      pe sont les erreurs sur les parametres
                      sv are the singular values
                        = [] si errors=False
                      même chose pour covar (covar renorm, diag=1)
            Si errors == 1 or True: mode auto (corrige pe si il n'y a pas de s)
                                    sinon retourne le pe calculé
                  Pour errors ce sont des flags:
                         1:  Calculer les erreurs
                         2:  Mode non-automatique
                         4:  corrige le pe (si mode non-auto)
                         8:  pe peut avoir dimension differente de p
                              (sinon p et pe ont les même dimensions)
                      Toutes les combinaisons (sommes) sont permises.
                      mode auto (corrige pe si il n'y a pas de s
                                    sinon retourne le pe calculé)
                      Valeur défaut: 1 ou True (erreurs auto et même forme que p)
                      Pas d'erreurs: 0 ou False
                      Erreurs non-corrigées: 1+2 = 3
                      Erreurs corrigés: 1+2+4 = 7
                   Erreurs corrigées signifie que l'on ajuste les s
                     pour obtenir chiNorm=1 (chiNorm= chi/dof), chi=resids

                      
            où pf est (p,func) et peut être utilisé avec gen_polyeval

       Exemple: pour function Y= (a*x+b*y+c,d*x+e*y+c),
                donc Y1=a*x1_b*y1+c, Y2=d*x1+e*y1+c,
                     Y3=a*x2_b*y2+c, Y4=d*x2+e*y2+c ...
                donc X=(x,y,1,x,y) (pour les paramètres (a,b,c,d,e)
                pour Y1: X1=(x1,y1,1,0,0), Y2: X2=(0,0,1,x1,y1) ...
    """
    if not func: func = DefaultPoly
    # need to check this, deal with s (errors), method and adjust
    x=func(X,m,param)
    m=x.shape[-1]
    xx=x.reshape((-1,m))
    if x.ndim == Y.ndim: #multiple solutions
        nfits = Y.shape[-1]
        y=Y.reshape((-1, nfits))
        multi = True
    else: #single solution
        y=Y.ravel()
        multi = False
        nfits = 0
    errors = int(errors) # True ->1, False ->0
    if errors&1 == 0 : errors = 0 
    if not errors: covar=pe = []
    elif errors&2 == 0: # automatic mode
        if s is None: errors |= 4  # fix pe
        else: errors &= ~4 #keep pe
    needloop=False
    if s is not None:
        s=np.asarray(s)
        ss=s.shape
        if s.ndim == 0:
            #scalar, only changes error calc (chi square)
            s=s.reshape((1,1))
        elif s.ndim == x.ndim-1:
            # Same errors for all y sets
            s=s.ravel()[:,None]
        elif s.ndim == Y.ndim: # and s.ndim == x.ndim
            # different errors for every y sets
            s=s.reshape((-1, nfits))
            needloop = True
        else:
            raise ValueError('shape mismatch: s is not a valid shape')
    if adjust is not None:
        pind = np.arange(m)
        adjust = pind[adjust] # in case adjust is a selector
        #we make sure we don't change the order, and don't repeat
        sel = np.intersect1d(pind, adjust)
        mm = len(sel)
        xo = xx
        xx = xo[:,sel]
        if p0 is not None:
            p0 = np.asarray(p0) # if necessary, turn list into array
            if p0.shape[0] != m:
                raise ValueError('shape mismatch: p0 is not a valid shape')
            # move the unadjusted parameters from left handside to right
            # hanside of equation
            unsel = np.setdiff1d(pind, adjust)
            if nfits != 0 and p0.ndim == 1:
                p0 = p0[:,None]
            if len(unsel)>0: 
                y = y - np.tensordot(xo[:,unsel],p0[unsel],axes=(-1,0))
    else: mm = m
    ind=slice(None)
    if filter is not None:
        ind=np.flatnonzero(filter>0.5)
        if len(ind) == 0:
            ind = slice(None)
    if needloop:
        p=np.zeros((mm, nfits))
        if errors:
            pe=np.zeros((mm, nfits))
            covar=np.zeros((mm,mm, nfits))
        resids=np.zeros(nfits)
        sv=np.zeros((mm, nfits))
        for i in xrange(s.shape[1]):
            xxs=xx[ind]/s[ind,i][:,None]
            ys=y[ind,i]/s[ind,i]
            if not errors:
                p[:,i],resids[i],rank,sv[:,i] = la.lstsq(xxs,ys,cond=rcond)
            else:
                p[:,i],resids[i], pe[:,i], (foo1,sv[:,i],foo2,rank,covar[:,:,i]) = lstsq_er(xxs,ys,cond=rcond)
    else:
        if s is not None:
            xx/=s
            if multi:
                y=y/s
            else:
                y=y/s[:,0]
        xx=xx[ind]
        ys=y[ind]
        if not errors:
            p,resids,rank,sv = la.lstsq(xx,ys,cond=rcond)
        else:
            p,resids,pe, (foo1,sv,foo2,rank,covar) = lstsq_er(xx,ys,cond=rcond)
    if adjust is not None:
        ptmp = p
        if nfits != 0:
            p=np.zeros((m,nfits))
        else:
            p=np.zeros(m)
        p[sel]=ptmp
        if p0 is not None:
            p[unsel] = p0[unsel]
        if errors:
            petmp = pe
            pes=list(pe.shape)
            pes[0] = m
            pe = np.zeros(pes)
            pe[sel] = petmp
            cvt = covar
            cvts = list(covar.shape)
            cvts[0] = cvts[1] = m
            covar=np.zeros(cvts)
            covar[sel[:,None],sel] = cvt
    # ramk should be the same as  mm
    chiNorm = resids/(ys.shape[0]-mm) #this assumes the given errors are correct
    # sigmaCorr is a correction factor that should multiply the given s
    # Since wihtout a given s the caclculations assume s=1 this is simply the
    # estimate of what should have been s in that case (to give the proper chi^2)
    sigmaCorr = np.sqrt(chiNorm)
    if errors&4:
        if nfits>0 and pe.ndim==1:
            pe=pe[:,None]
        pe = pe *sigmaCorr
    if errors and not errors&8: # force same shape
        if nfits>0 and pe.ndim==1:
            pe = pe[:,None] + np.zeros(nfits)
    extras = dict(chiNorm=chiNorm, sigmaCorr=sigmaCorr,rank=rank,sv=sv,covar=covar)
    return ((p,func), resids, pe, extras)


def rankdata(x, avg=True):
    """
       Returns the rank (order from 1 to n) of the n elements of x
       When avg = True (default), then for x values that are equal,
       it returns the avg.
       X can be either of shape (N,) or (N,M). It that second case,
       The rank is obtained along the first dimension only 
       i.e. the rank operation is repeated for x[:,i]

       It is faster and accepts more dimensions than scipy's version
       See also: scipy.stats.rankdata
    """
    xshapeOrg = x.shape
    if x.ndim==1:
        x= x[:,None]
    #x is now 2d
    sind = x.argsort(axis=0)
    n = x.shape[0] 
    ranklist = np.arange(n)*1. + 1 # make it floats and starting at 1 not 0
    nm = x.shape[1]
    sind = (sind, np.arange(nm)[None,:])
    ranklist = ranklist[:,None]
    rank = np.empty(x.shape)
    rank[sind] = ranklist
    if avg: # deal with repeats
        same = np.diff(x[sind],axis=0) == 0.
        # add a row of False before, and a row of False after
        falserow = np.zeros(nm)!= 0.
        same = np.r_['0,2,1', falserow, same, falserow]
        for i in xrange(nm):
            ind = sind[0][:,i]
            samei = same[:,i]
            beg = samei[1:]>samei[:-1] # goes from False to True
            end = samei[1:]<samei[:-1] # goes from True to False
            begi = beg.nonzero()[0]
            endi = end.nonzero()[0]
            assert len(begi) == len(endi), 'begi end endi should be same length'
            for b,e in zip(begi,endi):
                sel = ind[b:e+1]
                val = (b+e)/2.+1
                print(b,e,val)
                rank[sel,i] = val
    return rank.reshape(xshapeOrg)


def report(X,Y,pf,func=None, s=1., param=None, adjust=None, filter=None):
    """ Calculate a bunch of fit quality numbers.
        Parameters are the same as for gen_polyfit.
        pf is the result of a polynomial fit or just the parameters
        for a the func.
        Returns a dict with:
                Chi square      : chisq 
                Chi square /dof : chisqNorm
                R square        : R2
                R               : R
                R square adjust : R2adjust
                Pearson's r     : pearson
                Spearman's rank : spearman
                r*              : rstar
                
        where R = sqrt(max(R2,0)), R2 range -inf, 1]
                                      range [0,1] if fit contains a constant term
               (which is used by KaleidoGraph which returns +inf when R2<0)
          R2 = 1 - SSE/SSY
             Also callled Coefficient of determination
             where SSE is sum of squares of errors
                   SSY is sum of squares of Y-Yavg
              can be less than 0 if fit func does not include
              a constant term (to at least do like yavg).
              R2 close to 1 means the fit goes through the points
              R2 always increases with more fitting parameter.
              see 15.2 of Numerical Recipes C++ 2nd
          R2adjust = 1 - (SSE/dofe) / (SSY/dofy)
              where dofy degree fo freedom for unbiased estimator = N-1
                    dofe = N-p
                   for p the number of fit parameters (including a constant term.)
              This value should not increase when new parameters are added unless
              they are a useful parameter.
              see http://en.wikipedia.org/wiki/Coefficient_of_determination
                  Applied linear statistical models, 3rd, J. Neter, W. Wassermanm
                                                    W.H. Kutner section 7.5

          Pearson's  r = {Sum_i (x_i-xavg)(y_i-yavg)}/
                           sqrt{ [Sum_i (x_i-xavg)^2] [Sum_i (y_i - yavg)^2] }
                     range [-1,1]
              Also called linear correlation coefficient or
                          product-moment correlation
              It is +1 or -1 for a perfectly linear data set (data is on
                 a y=mx+b line) The correlation is between (y-yavg) and
                  (x-xavg) which corrrespond: yavg = m xavg +b
                           so y - yavg = mx +b - mxavg-b = m(x-avg)
              See 14.5 of Numerical Recipes

          Spearman's rank: 
                     Same as Perasons except replace x and y by their rank.
                     So x_i -> rank(x_i), xavg=Avg(rank(x_i)) ...
                     For x_i = x_j = x_k ... we give them the same rank
                          which is the average of the basic rank.
                          This keeps the sum (and avg) a constant.
                          i.e. for 0.1, 0.5, 0.1, -0.2 we have
                            rank(0.5) = 4, rank(-0.2) = 1, rank(0.1) = 2.5
                                (basic rank for both 0.1 was 2 and 3)
              It is a more robuts correlator than Person's r
              See 14.6 of Numerical Recipes
                  14.8 of Introduction to probability and mathematical 
                          statistics, 2nd, Bain, Engelhardt

          Note that Pearson and Spearman values only make sense when x and
          y are 1D vectors.

          rstar:
             Similar to Pearson but with y-yfit replacing x-xavg:
                  rstar = {Sum_i (y_i-f(x_i))(y_i-yavg)}/
                           sqrt{ [Sum_i (y_i-f(x_i))^2] [Sum_i (y_i - yavg)^2] }
                  with yfit = f(x_i) is the result of the fit evaluated
                  with the best fit parameters.
                  range [-1, 1]
             This is a coorelator between the fit error and the data.
             For a perfect fit it goes to 0.
             Under certain conditions (see below) r = sqrt(1-R^2)

          Note that chisq (chisqNorm, R2, R, R2adjust) pearson and rstar are
          all extended in a conventional way to handle variable s_i.
          Averages become weighted averages...

                          
          For a linear fit (y=mx+b):
               R^2 = pearson^2 = 1-rstar^2
          In the more general case where Sum_i (y_i-f(x_i))=0  and
          Sum_ (y_i-f(x_i)) f(x_i) = 0 then
               R^2 = 1-rstar^2
          Since least-square fitting finds solution for 
                  Sum_i (y_i-f(x_i)) df(x_i)/dpj = 0
          The requirements need f to have one term independent of x,
          and all the terms reproducible from a constant multiplied by
          a derivative.
          So f must have like: (p1, p2, ... are fit parameters)
              p1 + p2*x
              p1^2 + p2*exp(p3*x)
              p1*p2+p2*x^2+p2*x^3+p3*x^4
          but NOT of the form of
              p1*(1+x^2)        # no constant term: df/dp1 = 1+x^2
              10+p1*x           # no constant term: df/dp1 = 0 + x
              p1+x^p2           # x*p2 is not reproduced by any df/dpi
              p1+p2*x+p2^2*x^2  # 2nd and 3rd term not reproduced by any df/dpi

          See also: scipy.stats.spearmanr, pearsonr
              
    """
    ret = {}
    if len(pf) == 2 and isinstance(pf[1], types.FunctionType):
        yfit = gen_polyeval(X,pf,param=param)
        p = pf[0]
    else:
        yfit = func(X,pf,param=param)
        p = pf
    m = p.shape[0] # number of parameters
    s = np.asarray(s) # make sure it is an array
    if p.ndim == 2:
        nfits = p.shape[1]
        if s.ndim == Y.ndim and s.shape[-1]!=1:
            s = s.reshape((-1,nfits))
        elif s.ndim > 0:
            s = s.reshape((-1,1))
        Y = Y.reshape((-1,nfits))
        yfit = yfit.reshape((-1,nfits))
    else:
        nfits = 0
        Y = Y.reshape((-1,))
        yfit = yfit.reshape((-1,))
        if s.ndim > 0:
            s = s.reshape((-1,))
    ind=slice(None)
    if filter is not None:
        # this needs to match with gen_polyfit
        ind=np.flatnonzero(filter>0.5)
        if len(ind) == 0:
            ind = slice(None)
        if filter.ndim == X.ndim:
            X = X.ravel()[ind]
        else:  # filter is smaller than X, like
               # for twoDpoly where X is [2, ...]
            X = X.reshape((-1,filter.size))[:,ind]
            X = X.ravel()
        Y = Y[ind, ...]
        yfit = yfit[ind, ...]
        if s.ndim > 0 and s.shape[0]>1:
            s= s[ind, ...]
    else:
        X = X.ravel()
    Nx = X.size
    N = Y.shape[0]
    # X is now 1D always, even when it should not.
    # Because there correlation coefficient don't really
    # make sense there anyway. Need to event new ones.
    if adjust is not None:
        baseAdj = np.arange(m)
        adjust = baseAdj[adjust] # in case adjust is a selector
        #we make sure we don't change the order, and don't repeat
        #could probably use unique1d if it is sorted.
        m = len(np.intersect1d(baseAdj, adjust))
    #w = 1./s
    w = (1./s)**2
    # weighted average: yavg =  (sum wi yi)/sum wi
    # unweighed wi =1
    # we need to deal properly wi the case
    # if wi are all the same (jsut one element broadcast)
    # we can do that with: yavg = mean(w*y)/mean(w)
    # where mean(x) =  (sum_i x_i) / N
    # Which works fine in either case (Nw=1 or =Ny)
    wavg = np.mean(w,axis=0)
    Yavg = np.mean(Y*w,axis=0)/wavg # or np.average
    Yfd = (Y-yfit)
    chisq = np.sum(Yfd**2 * w, axis=0)
    chisqNorm = chisq/(N-m)
    ret['chisq'] = chisq
    ret['chisqNorm'] = chisqNorm
    Yad = (Y - Yavg)
    wSSya = np.sum((Yad**2*w),axis=0)
    R2 = 1 - chisq/wSSya
    ret['R2'] = R2
    ret['R'] = np.sqrt(np.maximum(0,R2))
    R2adjust = 1 - chisqNorm/(wSSya/(N-1))
    ret['R2adjust'] = R2adjust
    # r star
    rstar = np.sum(Yfd*Yad*w,axis=0)/np.sqrt(chisq*wSSya)
    ret['rstar'] = rstar
    if Nx != N:
        ret['pearson'] = None
        ret['spearman'] = None
    else:
        # pearson
        if nfits > 0: 
            Xavg = np.mean(X[:,None]*w,axis=0)/wavg
            Xad = (X[:,None]-Xavg)
        else:
            Xavg = np.mean(X*w)/wavg
            Xad = (X - Xavg)
        wSSxa = np.sum(Xad**2*w,axis=0)
        pearson = np.sum(Xad*Yad*w,axis=0)/np.sqrt(wSSxa*wSSya)
        ret['pearson'] = pearson
        # spearman, don't consider the sigma's (weight)
        Xrank = rankdata(X)
        Yrank = rankdata(Y)
        rankavg = (N+1.)/2 # 1,2,3 -> 2,  1.5, 1.5,3,4 ->2.5 ...
        Xrd = Xrank-rankavg
        if nfits > 0: Xrd = Xrd[:,None]
        Yrd = Yrank-rankavg
        spearman = np.sum(Xrd*Yrd,axis=0)/   \
                     np.sqrt(np.sum(Xrd**2,axis=0)*np.sum(Yrd**2,axis=0))
        ret['spearman'] = spearman
    return ret
    

# test/example routine
if __name__ == "__main__":
    from matplotlib.pylab import figure, clf, plot, legend, show, ylim
    #from pretty import pprint
    from pprint import pprint
    N=500
    x=np.linspace(0,1,N)
    y=3+5*x**2+np.random.randn(N)*.1
    y[200]=100
    figure(1)
    clf()
    plot(x,y,label='data')
    ss=y*0+1.
    ER=True
    #ER=False
    (pf,res,pe,extras) = gen_polyfit(x,y,3,errors=ER)
    plot(x,gen_polyeval(x,pf),'g',label='fit no s')
    pprint (('fit no s',pf[0],pe,res,extras))
    pprint (report(x,y,pf))
    (pf,res,pe,extras) = gen_polyfit(x,y,3,s=10,errors=ER)
    plot(x,gen_polyeval(x,pf),'r',label='fit constant s')
    pprint (('fit constant s',pf[0],pe,res,extras))
    pprint ( report(x,y,pf,s=10) )
    ss[200]=100
    (pf,res,pe,extras) = gen_polyfit(x,y,3,s=ss,errors=ER)
    plot(x,gen_polyeval(x,pf),'k', label='fit with s')
    pprint (( 'fit with s',pf[0],pe,res,extras ))
    pprint ( report(x,y,pf,s=ss) )
    legend()
    ylim(0,10)

    # compare with leastsq
    fn = lambda p,x,y,s: (y-gen_polyeval(x,(p,oneDpoly)))/s
    from scipy.optimize import leastsq
    (pf,res,pe,extras) = gen_polyfit(x,y,3,s=ss,errors=3)
    p0 = pf[0]*2.
    rr=leastsq(fn, p0, args=(x,y,ss), full_output=True)
    pre = np.sqrt(rr[1].diagonal())
    print('========== non linear fit start =========')
    pprint (( 'polyfit', pf[0], pe, extras['covar'], (extras['covar']*pe*pe[:,None]).round(4) ))
    pprint ( report(x,y,pf,s=ss) )
    pprint (( 'non linear', rr[0],pre, rr[1]/pre/pre[:,None], rr[1].round(4) ))
    pprint ( report(x,y,rr[0],s=ss,func=lambda x,p,param=None:gen_polyeval(x,(p,oneDpoly))) )
    print('========== non linear fit end =========')

    figure(2)
    clf()
    figure(3)
    clf()
    figure(4)
    clf()
    xx=x+np.array([0,1.01])[:,None]
    yy=np.zeros((2,N,3))
    yy[:,:,0]=4+6*xx**2+np.random.randn(2,N)*.1
    yy[:,:,1]=1+2*xx**2+np.random.randn(2,N)*.1
    yy[...,2]=5+9*xx+np.random.randn(2,N)*.2
    yy[1,20,:]=-100
    yy[0,N-50,2]=200
    figure(2)
    plot(xx.T,yy[...,0].T,'b',label='data')
    figure(3)
    plot(xx.T,yy[...,1].T,'b',label='data')
    figure(4)
    plot(xx.T,yy[...,2].T,'b',label='data')
    sss=yy*0+1.
    ((p,f),res,pe,extras) = gen_polyfit(xx,yy,4,errors=ER)
    figure(2)
    plot(xx.T,gen_polyeval(xx,(p[:,0],f)).T,'g',label='fit no s')
    figure(3)
    plot(xx.T,gen_polyeval(xx,(p[:,1],f)).T,'g',label='fit no s')
    figure(4)
    plot(xx.T,gen_polyeval(xx,(p[:,2],f)).T,'g',label='fit no s')
    pprint (( 'fit no s',p,pe,res,extras ))
    pprint ( report(xx,yy,(p,f)) )
    ((p,f),res,pe,extras) = gen_polyfit(xx,yy,4,s=10,adjust=[0,0,2],
                     p0=np.array([[-1,-20,-3,0],[-.1,-.2,-.3,0],[11,9,13,0]]).T,errors=ER)
    figure(2)
    plot(xx.T,gen_polyeval(xx,(p[:,0],f)).T,'r',label='fit constant s, adj0,2')
    figure(3)
    plot(xx.T,gen_polyeval(xx,(p[:,1],f)).T,'r',label='fit constant s, adj0,2')
    figure(4)
    plot(xx.T,gen_polyeval(xx,(p[:,2],f)).T,'r',label='fit constant s, adj0,2')
    pprint (( 'fit constant s',p,pe,res,extras ))
    pprint ( report(xx,yy,(p,f),s=10,adjust=[0,0,2]) )
    sss[1,20,:]=100
    sss[0,N-50,2]=-100 # negative sigma does not make sense, but code should not care
    (pf,res,pe,extras) = gen_polyfit(xx,yy,4,s=sss,errors=ER)
    figure(2)
    plot(xx.T,gen_polyeval(xx,pf,sel=0).T,'c', label='fit with s')
    figure(3)
    plot(xx.T,gen_polyeval(xx,pf,sel=1).T,'c', label='fit with s')
    figure(4)
    plot(xx.T,gen_polyeval(xx,pf,sel=2).T,'c', label='fit with s')
    pprint (( 'fit with s',pf[0],pe,res,extras ))
    pprint ( report(xx,yy,pf,s=sss) )
    (pf,res,pe,extras) = gen_polyfit(xx,yy,4,s=sss[...,0],errors=ER)
    pprint (( 'fit with s uniform',p,pe,res,extras ))
    pprint ( report(xx,yy,pf,s=sss[...,0]) )
    (pf,res,pe,extras) = gen_polyfit(xx,yy,2,s=sss,errors=ER)
    pprint (( 'fit with s linear(y=mx+b)',p,pe,res,extras ))
    rep=report(xx,yy,pf,s=sss)
    pprint ( rep )
    pprint ( 1-rep['rstar']**2 )
    figure(2)
    legend()
    ylim(5,15)
    figure(3)
    legend()
    ylim(2,10)
    figure(4)
    legend()
    ylim(7,17)
    show()
