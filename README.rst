pyHegel
=======

A Python package to control laboratory instrument in a uniform way using a
command line interface (ipython).
It can communicate with VISA (using PyVISA) which permits GPIB, USB,
RS232 and ethernet control of instruments. But other communication can
be used (custom network or serial protocols, manufacturers provided libraries).

Some code needs to be written to use an new instrument, but this makes it more
uniform so it can easily be used for more general tools that perform sweeping
measurements and time series recording. The general tool also provide write the
results in files in a standard format that includes headers describing the instruments
state.

Description
-----------

In a laboratory experiments, many devices are interconnected and they need to
be operated in a particular sequence. For example, you might do a sweep, changing a
voltage applied to a circuit while reading a current somewhere else. Or you might decide
to still sweep the voltage but also take readings on a spectrum analyzer at each point.
Or you might decide to record the drifts in some voltage over time.

To performs those operations, you could write a program in Visual Basic, C or more commonly
in LabVIEW. You might need many different programs for each situations or a more complex
one that handles all the situations you tought of. Well pyHegel is intended to be the latter.

However, contrary to LabVIEW, it uses a command line interface (the one provided py
IPython (http://ipython.org/), and the generality of the python language itself to provide the
flexibililty needed to quickly change the experiments and the measurements needed.

Interactivity provides a quick exploration of a setup. And advance function like
sweep and record permits measurement to be taken interactivelly. But for more advanced
uses, or to better repeat measurement, you can write scripts and new functions.

However to allow this power, some code is required for each new device. Many instruments
already habe some code, but obviously it is still a small fraction of what is available
in laboratories around the world. The code is not necessarily very large. It depends on the
complexity of the instruments, and the number of their features you want to provide control over.

The communications to many instruments can use the standard VISA library using the python
bindings of PyVISA (https://pyvisa.readthedocs.org/en/master/). It is no a requirement of
to run pyHegel, but it is needed for most instruments. This allows communicated with standard
equipments using GPIB, USB (usbtmc), LAN(VXI-11) and serial (RS232).

Other interfaces can be used. For instance Zurich Instruments UHFLI does not use VISA but
the manufactures provided zhinst python package.

For most instruments, pyHegel also tries very hard to allow control access from many running
process and threads (using proper VISA locking for example). Therefore you could have a pyhegel
process running recording the temperature, while another process sweeps and also reads the
same temperature, without blocking or reading the wrong values.

Another feature is to allow measurement to be done in parallel. Imagine you need to for each
points in a sweep, you need to read to instruments and they both take 10s. If you procede
sequentially it would take 20s in total for each points in the sweep. However if you can
take both measurement concurently (in parallel) then it only takes 10s. This is allowed in pyHegel
in what is known as async mode. They same tricks that are use for that, allow instruments
that take a long time to respond to a request to be waited on instead of receiving timeouts
(or making the timeouts too long which makes error recovery slower).

The locking and waiting is normally non-blocking and keeps to graphical interface updated.
If you want it to stop waiting you can press CTRL-C (or quit a sweep by using the abort button,
which is cleaner, but requires waiting for the end of the point).

For simple sweeps and time records, figures are plotted as the data is taken. This uses the
matplotlib librairies (http://matplotlib.org/) which needs numpy (http://www.numpy.org/).

pyHegel also provides tools/wrappers to read all the datafiles created, merge pdf
files (using pyPDF or PyPDF2), perform non-linear and polynomial fits (using scipy: http://www.scipy.org/), and others.

Requirements
------------

- Python (tested on 2.7, does not work on 3.x)
- numpy
- scipy
- matplotlib
- PyVISA (optional: will run without it, but controlling instruments will be impaired)
- PyPDF2 or pyPdf (optional: needed for pdf merging)
- some other packages depending on the instrument.

An easy way to obtain most of these on windows is to intall Python(x,y) (https://code.google.com/p/pythonxy/)
and use the custom install to install everything. That is the distribution used by the maintainers on windows
and pyHegel provides shortcuts to use the improved console packaged with it (ConsoleZ: https://github.com/cbucher/console).


Installation
--------------

Download the distribution to some directory on your computer
 git clone .....

You can then use it from there directly by calling the pyHegel.py script at the base of the
distributions.

However you can install it either in develop mode
  python setup.py develop
which will keep the current directory the active one (so the code can be
modified there) but update python so it finds the module corretly and
create the pyHegel command so you can start the session. Or use a full
install
  python setup.py install

Documentation
--------------

There is some old/partially written documentation in the distribution under
the manual directory. However most pyHegel commands as well as instruments/devices
have online documentation (use the ipython trick of placing "?" after an object
to obtain its documentation).
