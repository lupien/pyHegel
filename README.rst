pyHegel
=======

A Python package to control laboratory instruments in a uniform way using a
command line interface (ipython).  It can communicate with VISA (using PyVISA)
which permits GPIB, USB, RS232 and Ethernet control of instruments. But other
communication protocols can be used (custom network or serial protocols,
manufacturers provided libraries).

Some code needs to be written to use a new instrument, but this makes it more
uniform so it can easily be used with more general tools that perform sweeping
measurements and time series recording. The general tools also write the
results in files in a standard format that includes headers describing the
instruments state.

Description
-----------

In a laboratory experiment, many devices are interconnected and they need to be
operated in a particular sequence. For example, you might do a sweep, changing
a voltage applied to a circuit while reading a current somewhere else. Or you
might decide to add to the sweep readings on a spectrum analyzer at each point.
Or you might decide to record the drifts in some voltage over time.

To performs those operations, you could write a program in Visual Basic, C or
more commonly in LabVIEW. You might need many different programs for each
situations or a more complex one that handles all the situations you thought
of. Well pyHegel is intended to be the later.

However, contrary to LabVIEW (C, C++, etc.), it uses a command line interface
(the one provided by IPython: http://ipython.org/), and the generality of the
python language itself to provide the flexibility needed to quickly change and
adapt to the experiments and the measurements needed.

Interactivity provides a quick exploration of a setup. And advanced functions
like sweep and record permit measurements to be taken interactively (with a
single line command).  But for more advanced uses, or to better repeat
measurements, you can write scripts and new functions.

However to allow this power, some code is required for each new device. Many
instruments already have some code, but obviously it is still a small fraction
of what is available in laboratories around the world. The needed code is not
necessarily very large. It depends on the complexity of the instruments, and
the number of their features you want to provide control over.

The communications to many instruments can use the standard VISA library using
the python bindings of PyVISA (https://pyvisa.readthedocs.io/en/latest/index.html).
It is not a requirement of pyHegel, but it is needed for most instruments. This
allows to communicate with standard instruments using GPIB, USB (usbtmc),
LAN(VXI-11) and serial (RS232).

Other interfaces can be used. For instance Zurich Instruments UHFLI does not
use VISA but the manufacturer provides the zhinst python package.

For most instruments, pyHegel also tries very hard to allow proper simultaneous
access from many running process and threads (using proper VISA locking for
example). Therefore you could have a pyHegel process recording the temperature,
while another process sweeps and also reads the same temperature, without
blocking or reading the wrong values.

Another feature is to allow measurements to be done in parallel. Imagine you
perform a sweep and for each points in the sweep, you need to read two
instruments and they both take 10s. If you proceed sequentially it would take
20s in total for each points in the sweep. However if you can take both
measurements concurently (in parallel) then it only takes 10s. This is allowed
in pyHegel in what is known as async mode. The same tricks that are use for
that allow instruments that take a long time to respond to a request to be
waited on instead of receiving timeouts (or making the timeouts too long which
makes error recovery slower).

The locking and waiting is normally non-blocking and keeps the graphical
interface updated.  If you want it to stop waiting you can press CTRL-C (or
quit a sweep by using the abort button, which is cleaner, but requires waiting
for the end of the point).

For simple sweeps and time records, figures are plotted as the data is taken.
This uses the matplotlib librairies (http://matplotlib.org/) which needs numpy
(http://www.numpy.org/).

pyHegel also provides tools/wrappers to read all the data files created, merge
pdf files (using pyPDF or PyPDF2), perform non-linear and polynomial fits
(using scipy: http://www.scipy.org/), and other conversions.

Requirements
------------

- Python (works in 2.7 and 3.7 and above)
- numpy
- scipy
- matplotlib
- PyVISA (optional: will run without it, but controlling instruments will be impaired)
- PyPDF2 or pyPdf (optional: needed for pdf merging)
- pywin32 is needed on windows platforms
- some other packages depending on the instruments.

An easy way to obtain most of these on windows is to intall the Anaconda Distribution
(https://www.anaconda.com/download#downloads). That includes python, numpy, scipy and matplotlib.
Others like PyVISA and PyPDF2 can be installed can be install from the command line using::

    pip install pyVisa
    pip install PyPDF2

or using the conda package installer like::

    conda install pyserial

Note that pyHegel starts ipython in pylab mode with autocall enabled and with completions
in a readlike fashion. You can start your own ipython with those options like this::

    ipython --pylab --TerminalInteractiveShell.display_completions=readlinelike --autocall=1

In newer ipython, I add the equivalent of the following parameter::

    --TerminalInteractiveShell.autosuggestions_provider=None

To have an improved windows console, you can install ConsoleZ
(https://github.com/cbucher/console). I provide a starting console.xml config file
in extra/console.xml. It can be copied to %USERPROFILE%\\AppData\\Roaming\\Console\\console.xml
then the different tabs can be modified/removed depending on your personal setup.
(It presumes anaconda is installed in C:\\Anaconda2 or C:\\Anaconda3 and that for 3 that the python2
is in C:\\Anaconda3\\envs\\py2)

Installation
--------------

Download the distribution to some directory on your computer ::

    git clone https://github.com/lupien/pyHegel.git

You can then use it from there directly by calling the pyHegel.py script at the
base of the distributions.

However you can install it either in develop mode ::

    python setup.py develop

or with newer versions (where setup is deprecated) ::

    pip install -e .

which will keep the current directory the active one (so the code can be
modified there) but updates python so it finds the module correctly and creates
the pyHegel command so you can start a session. Or use a full install ::

    python setup.py install

or with newer versions (where setup is deprecated) ::

    pip install .

Documentation
--------------

There is some old/partially written documentation in the distribution under the
manual directory. However most pyHegel commands as well as instruments/devices
have inline documentation (use the ipython trick of placing "?" after an object
to obtain its documentation).

