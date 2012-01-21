# -*- coding: utf-8 -*-
"""
Created on Thu Jan 19 17:21:20 2012

@author: reuletlab
"""

import os
import glob

import numpy as np
from pylab import plot, figure, hist, histogram, clf, legend, show, yscale, draw
from pylab import xlabel, ylabel
from PyQt4 import QtGui, QtCore
import time
import pickle


SAMPLING_RATE = 400e6
GAIN = 26.75
R = 50
Dlevel = 6500

def getdata(filename):
    return np.fromfile(filename, np.uint16)

def bin2v(b, off=2**13): # remember it is inverted
    return (off-b)*.75/2**14

def v2bin(v):
    return np.round(-v/.75*2**14+2**13)

def bin2t(b): # to seconds
    return b/SAMPLING_RATE

def v2i(v): # voltage to current
    return v/R/GAIN

def bin2i(bin, off=2**13):
    return v2i(bin2v(bin, off=off))

def analyse(v, level = None):
    if level == None:
        level = Dlevel
    # index to all avalanche data points
    aval_i = np.where(v < level)[0]
    Na = len(aval_i)
    # index to all not avalanche data points
    naval_i = np.where(v >= level)[0]
    Nna = len(naval_i)
    if Na > 0 and Nna > 0:
        if aval_i[0] == 0:
            first_i = naval_i[0]
        else:
            first_i = aval_i[0]
        last_i = Na+Nna
        N = last_i-first_i
        #print 'N', N
    else:
        N = 1
    if Na > 0:
        Haval = v[aval_i].mean()
        HSa = v[aval_i].std()
        #HSa2 = (v[aval_i]-Haval).std()
        #HSa3 = np.sqrt(((1.*v[aval_i])**2).mean()-Haval**2)
        #print HSa, HSa2, HSa3
        # jumps point into aval_i at last value of an avalanche
        jump_i = np.where(np.diff(aval_i)>1)[0]
        # obtain length of not avalanches
        figure(1)
        clf()
        if len(jump_i) > 0:
            if jump_i[-1]+1 >= Na:
                # last not avalanche does not end so skip it
                jump_i = jump_i[:-1]
            Dna = aval_i[jump_i+1]-aval_i[jump_i] -1
            Dna_avg = Dna.mean()
            Ah, Ax, Apatches = hist(Dna, 100, label='not Avalanches')
            legend()
            Nnaval = len(Dna)
        else:
            Dna_avg = 0.
            Ah = Ax = np.array([])
            Nnaval = 0
        #print 'Na', Na, 'Dna', Dna_avg, 'Nnaval', Nnaval
    else:
        Haval=0.
        HSa = 0.
        Ah = Ax = np.array([])
        Nnaval=0
        Dna_avg=1.
    if Nna > 0:
        Hnaval = v[naval_i].mean()
        HSna = v[naval_i].std()
        # jumps point into naval_i at last value of an not avalanche
        jump_i = np.where(np.diff(naval_i)>1)[0]
        # obtain length of not avalanches
        figure(2)
        clf()
        if len(jump_i) > 0:
            if jump_i[-1]+1 >= Nna:
                # last avalanche does not end so skip it
                jump_i = jump_i[:-1]
            Da = naval_i[jump_i+1]-naval_i[jump_i] -1
            Da_avg = Da.mean()
            NAh, NAx, NApatches = hist(Da, 100, label='Avalanches')
            legend()
            Naval = len(Da)
        else:
            Da_avg = 0.
            Naval = 0
            NAh = NAx = np.array([])
        #print 'Nna', Nna, 'Da', Da_avg, 'Naval', Naval
    else:
        Hnaval = 0.
        HSna = 0.
        Naval=0
        NAh = NAx = np.array([])
        Da_avg=1.
    print 'N', N, 'Na', Na, 'Nna', Nna, 'Na+Nna', Na+Nna
    print 'Naval', Naval, 'Nnaval', Nnaval
    print 'Da', Da_avg, 'Dna', Dna_avg
    print 'Haval', Haval, 'sigma', HSa
    print 'Hnaval', Hnaval, 'sigma', HSna
    Hdc = v.mean()
    #Hdc2 = (Haval*Na + Hnaval*Nna)/(Na+Nna)
    #print 'Should be equal', Hdc, Hdc2, 'diff=',Hdc-Hdc2
    return ((Naval/bin2t(N), bin2t(Da_avg), bin2t(Dna_avg),
            Da_avg/(Dna_avg+Da_avg), Na*1./(Na+Nna), 
            bin2i(Haval), bin2i(Hnaval), bin2i(Hdc-Hnaval,off=0), 
            bin2i(-HSa, off=0), bin2i(-HSna, off=0)),
            (Ah, Ax, NAh, NAx))

def updateFig():
    qApp = QtGui.QApplication.instance()
    to=time.time()
    figure(1)
    draw()
    figure(2)
    draw()
    while time.time()-to < .5 :
        qApp.processEvents(QtCore.QEventLoop.AllEvents, 50)
        #time.sleep(.1)

def doall(filebase, level=None):
    filelist = sorted(glob.glob(filebase))
    res=[]
    resH=[]
    for f in filelist:
        print '------file:',f
        v=getdata(f)
        vec, histo = analyse(v, level=level)
        res.append(vec)
        resH.append(histo)
        updateFig()
    return np.asarray(res).T, resH

def ploth(hval):
    x1 = hval[1]
    x1 = (x1[:-1]+x1[1:])/2.
    x3 = hval[3]
    x3 = (x3[:-1]+x3[1:])/2.
    figure(1)
    clf()
    plot(x1, hval[0], '.', label='Avalanches')
    #yscale('symlog', linthreshy=.1)
    yscale('log')
    legend()
    draw()
    figure(2)
    clf()
    plot(x3, hval[2], '.', label='Not Avalanches')
    yscale('log')
    legend()
    draw()

if __name__ == "__main__":
    figure(1)
    show()
    #r,h=doall('/data/avalanchefelix/sweep19_195/20120119-133212_acq1_readval_*.bin')
    #pickle.dump((r,h), open('results.pickle','wb'))
    r,h = pickle.load(open('results.pickle','rb'))
    base = np.loadtxt('/data/avalanchefelix/sweep19_195/20120119-133212.txt').T
    v = base[0]
    ploth(h[80])
    figure(3)
    clf()
    plot(v, r[0])
    ylabel('Avalanche Rate(1/s)')
    xlabel('Voltage (V)')
    draw()
    figure(4)
    clf()
    plot(v, r[1], label='Avalanche')
    plot(v, r[2], label='Not Avalanche')
    ylabel('Avg Duration (s)')
    legend()
    draw()
    figure(5)
    clf()
    plot(v, r[3], label='Duration')
    plot(v, r[4], label='Number')
    ylabel('Fraction')
    legend()
    draw()
    figure(6)
    clf()
    plot(v, r[7])
    ylabel('calc current (A)')
    draw()
    figure(7)
    clf()
    plot(v, r[8], label='Avalanche')
    plot(v, r[9], label='Not Avalanche')
    ylabel('Sigma (A)')
    legend()
    draw()
