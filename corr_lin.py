# -*- coding: utf-8 -*-
"""
Éditeur de Spyder

Ce script temporaire est sauvegardé ici :
C:\Users\zads2401\.spyder2\.temp.py
"""

def fCorrS(AmpSinPP, OffsetDC):
    Nbit = 14
    
    AmpSinPP = AmpSinPP*(16384/0.75)  
    OffsetDC = (OffsetDC + 0.375)*(16384/0.75)
    
#    get(acq1.readval,filename='reference_histogram.txt')    
    H = ndarray(16384.0)
    NormalizedH = ndarray(16384.0)
    code_width = ndarray(16384.0)
    H = loadtxt('reference_histogram.txt')
    S= H.sum()
    
    AmpSin = AmpSinPP/2
    Tk0 = OffsetDC - AmpSin*cos(pi*H[0]/S)
    T0 = Tk0
        
    corrected_code = arange(16384.0)        
    corrected_code[0] = 0
        
    
    for i in range(2**Nbit - 1):
        Tk = OffsetDC - AmpSin*cos(pi*(sum(H[0:(i + 2)]))/S)
       
        corrected_code[i + 1] = (Tk + Tk0)/2.0 + 0.5 - T0
        NormalizedH[i + 1] = H[i + 1]/(Tk - Tk0)
        code_width[i] = 1/(Tk - Tk0)
        Tk0 = Tk
    
    corrected_code[16383] = 0
    
    savetxt('corrected_codes.txt', corrected_code)
    savetxt('corrected_code_width.txt', code_width)
    
    plot(corrected_code[1:16382], NormalizedH[1:16382])
    
 # ---------------------------------------------------------------    
 

def fCorrG(V0, M2, dead_zone):
    import scipy.special
    
    Nbit = 14
    
    sigma = sqrt(M2)/0.75*16384
    delta = V0/0.75*16384 + 8192
    
    H = ndarray(16384.0)
    NormalizedH = ndarray(16384.0)
    code_width = ndarray(16384.0)
    H = loadtxt('reference_histogram.txt')
    S = H.sum()
    
   
    if dead_zone > 0:
        Hc = sum(H[0:dead_zone])
    else:
        Hc = H[0]
    
      
    
    Tk0 = sqrt(2)*scipy.special.erfinv(2*Hc/S - 1)*sigma + delta
    T0 = Tk0
    
#    print(Tk0)    
    
#    corrected_code = arange(16384.0)    
    
    corrected_code = zeros(16384.0)    
    
        
    
    for i in linspace (dead_zone, (2**Nbit - dead_zone - 2), (2**Nbit - 2*dead_zone -1)):
        
        Hc = Hc + H[i+1]        
        
        Tk = sqrt(2)*(scipy.special.erfinv(2*Hc/S - 1))*sigma + delta
        
 #       print(Tk-Tk0)
 #       print(sum(H[0:(i + 2)])/S) 
        
        corrected_code[i + 1] = (Tk + Tk0)/2.0 + 0.5 - T0
        NormalizedH[i + 1] = H[i + 1]/(Tk - Tk0)
        code_width[i] = 1/(Tk - Tk0)
        Tk0 = Tk
    
    corrected_code[16383] = corrected_code[16382] + 1
 #    corrected_code[16383] = 0
    
    savetxt('corrected_codes.txt', corrected_code)
    savetxt('corrected_code_width.txt', code_width)
    
    plot(corrected_code[dead_zone : (2**Nbit - dead_zone)] + dead_zone, NormalizedH[dead_zone : (2**Nbit - dead_zone)]) 
 
 
 
 
  # ---------------------------------------------------------------  
    
def HistShowZ (fname):
    
    H = ndarray(16384)
    H = loadtxt(fname)
    codes = ndarray(16384)
    code_width = ndarray(16382)
    codes = loadtxt('corrected_codes.txt')
    code_width = loadtxt('corrected_code_width.txt')
    
    for i in range (16382):
        H[i+1] = H[i+1]*code_width[i]
        
    plot(codes[1:16383], H[1:16383])

# --------------------------------------------------------------- 
    
def m_calc(HistogramNumber, dead_zone):
    Nbit = 14
    v = zeros((HistogramNumber, 2**Nbit))
#    z0 = zeros(dead_zone)
    
    for i in range (HistogramNumber):
        v[i,:] = loadtxt('20120223-163733_acq1_readval_%03i.txt'%i)

#        v[i,0:dead_zone] = 0
#        v[i,(2**Nbit - dead_zone): 2**Nbit] = 0

#      Normalisator!!!!

     
    
    codes = loadtxt('corrected_codes.txt')
    
    matr0 = zeros_like(v)
    matrDev = matr0 + codes
    
    v = v*1.0
    S = v.sum(axis=1)
    if dead_zone> 0:
        v[:, 0:dead_zone] = 0
        v[:, -dead_zone:] = 0
    
       
    ProbabilityMatrix = v/S[:, None]
#    ProbabilityMatrix[:, 0:dead_zone] = 0
#    ProbabilityMatrix[:, -dead_zone:] = 0
  
#    v2 = v*codes[None,:]
#    vm = v2.sum(axis=1)/v.sum(axis=1)    

    v2 = ProbabilityMatrix*codes[None,:]
    vm = v2.sum(axis=1)

    
    for i in range(HistogramNumber):
        matrDev[i,:] = matrDev[i,:] - vm[i]
    
    vm = (vm - 8192)*(0.75/16384)
    
    m2t = matrDev**2*ProbabilityMatrix
    m2 = m2t.sum(axis=1)*(0.75/16384)**2
    
    m3t = matrDev**3*ProbabilityMatrix
    m3 = m3t.sum(axis=1)*(0.75/16384)**3  
    
    save_calculated_moments(vm, m2, m3, HistogramNumber)
    
# --------------------------------------------------------------- 
def m_calc2 (dead_zone, HistogramNumber):
    
    m2 = zeros(HistogramNumber)
    m3 = zeros(HistogramNumber)
#    m4 = zeros(HistogramNumber)
   
    
    for i in range (HistogramNumber):
        filename = '20120404-073414_acq1_readval_%03i.txt'%i
        print("Processing   ")
        print (filename)
        
        Histogram = loadtxt(filename)
        m2[i],m3[i] =  moments (Histogram, dead_zone)
        
    
    
    
    save_calculated_moments(arange(HistogramNumber), m2, m3, HistogramNumber)
    
    
# --------------------------------------------------------------- 
    
def save_calculated_moments(vector1, vector2, vector3, HistogramNumber):
    fname = _process_filename('calculated_moments_%T.txt')
    
    fhandle = open(fname, 'at')
    
    for i in range(HistogramNumber):
        instrument._writevec(fhandle, [vector1[i], vector2[i], vector3[i]])
 
 
# ---------------------------------------------------------------    
    
def fast_sweep():
    acq1.set_histogram(1024*1, 400, 1, 'Internal')
    for i in range(115):
        sweep (yo4, -2.0, 2.0, 201, out = [acq1.readval, acq1.hist_m2, acq1.hist_m3])
    
# --------------------------------------------------------------- 

def fhsum():
    import os

    directory_listing = os.listdir(".")

    for i in range(201):
        v = zeros(16384)
        for filename in directory_listing:
            if filename[29:32] == '%03i'%i and  filename[16:28] =='acq1_readval':
                print("Processing   ")
                print (filename)
                v = v + loadtxt(filename)
        savetxt('histo_merged_%03i.txt'%i, v)
        
        
 # --------------------------------------------------------------- 

def moments (Histogram, dead_zone):
    Histogram = Histogram*1.0
    somme = Histogram.sum()
    
    if dead_zone > 0:
        Histogram[0:dead_zone] = 0
        Histogram[-dead_zone:] = 0
        
       
    codes = loadtxt('corrected_codes.txt')
    ProbabilityMatrix = Histogram/somme
    vm = sum(ProbabilityMatrix*codes)
    
    m2 = sum((codes - vm)**2*ProbabilityMatrix)*(0.75/16384)**2
    m3 = sum((codes - vm)**3*ProbabilityMatrix)*(0.75/16384)**3
#    m4 = sum((codes - vm)**4*ProbabilityMatrix)*(0.75/16384)**4
    
# -    vm = (vm - 8192 + dead_zone)*(0.75/16384)
    
    return m2, m3
    
# ---------------------------------------------------------------    
    
def fhsum():
    import os

    directory_listing = os.listdir(".")

    for i in range(201):
        v = zeros(16384)
        for filename in directory_listing:
            if filename[29:32] == '%03i'%i and  filename[16:28] =='acq1_readval':
                print("Processing   ")
                print (filename)
                v = v + loadtxt(filename)
        savetxt('histo_merged_%03i.txt'%i, v)
        
        
# --------------------------------------------------------------- 

def m_batch(dead_zone, HistogramNumber):
    import os

    directory_listing = os.listdir(".")
    
    m2_vector = zeros(HistogramNumber)
    m3_vector = zeros(HistogramNumber)

    for i in range(HistogramNumber):
        
        file_counter = 0
        
        for filename in directory_listing:
            if filename[29:32] == '%03i'%i and filename[16:28] =='acq1_readval':
                print("Processing   ")
                print (filename)
                
                file_counter = file_counter + 1
                
                Histogram = loadtxt(filename)
                m2,m3 =  moments (Histogram, dead_zone)
                print(m2,m3)
                m2_vector[i] = m2_vector[i] + m2
                m3_vector[i] = m3_vector[i] + m3
                
        m2_vector[i] = m2_vector[i]/file_counter
        m3_vector[i] = m3_vector[i]/file_counter               
    
    save_calculated_moments(arange(HistogramNumber), m2_vector, m3_vector, HistogramNumber)
    
# ---------------------------------------------------------------    
    
def sg_fast_sweep():
    acq1.set_histogram(1024*10, 400, 1, 'Internal')
    for i in range(16):
        sweep (rf1.amp_lf_dbm, -20.0, -15.0, 101, out = [acq1.readval, acq1.hist_m2, acq1.hist_m3])

# ---------------------------------------------------------------    
    
def sg_fast_sweepF():
    acq1.set_histogram(1024*10, 400, 1, 'Internal')
    for i in range(16):
        sweep (rf1.freq, 1000000.0, 386000000, 201, out = [acq1.readval, acq1.hist_m2, acq1.hist_m3])
    
    set (rf1.amp_rf_dbm, -110.0)
 # --------------------------------------------------------------- 
   
def yo_nuit():
    acq1.set_histogram(1024*10, 1)
    print("The board has been initialized successfully   ")
    
    for i in range(10):
        sweep (yo4, -1.0, 1.0, 201, out = [acq1.readval, acq1.hist_m2, acq1.hist_m3])
    
    set (yo4, 0.0)
 # --------------------------------------------------------------- 
   
def weekend():
    acq1.set_histogram(1024*10, 1)
    for i in range(40):
        sweep (yo4, -1.0, 1.0, 201, out = [acq1.readval, acq1.hist_m2, acq1.hist_m3])
    
    set (yo4, 0.0)
 
 # --------------------------------------------------------------- 
 
# --------------------------------------------------------------- 
   
def paques():
    acq1.set_histogram(1024*10, 1)
    print("The board has been initialized successfully   ")
    for i in range(71):
        sweep (yo4, -1.0, 1.0, 201, out = [acq1.readval, acq1.hist_m2, acq1.hist_m3])
    
    set (yo4, 0.0)
  
 
 # --------------------------------------------------------------- 

def avspectr(N):
    acq1.set_spectrum(32, 8192, 'Single', 1)
    print("The board has been initialized successfully   ")
  
    v = zeros(4097)
    for i in range(N):
        print (i)
        v= v + get(acq1.readval)
    return v/N
    
 # --------------------------------------------------------------- 
   
def refhist():
    set (yo4, 0.0)
    acq1.set_histogram(1024*1024, 1)
    print("The board has been initialized successfully   ")
    v= get(acq1.readval)
    savetxt('reference_histogram.txt', v)
    
# --------------------------------------------------------------- 
       