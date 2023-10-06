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

#
# python-matplotlib-0.99.1.2-4.fc13.i686 QT backend is missing many
# key codes compared to gtk so add missing ones needed for FigureManagerQT

from __future__ import absolute_import, print_function, division

import time
import functools
import sys
import gc

from . import qt_wrap  # This is used for reset_pyhegel command
from .qt_wrap import QtCore, QtGui
import numpy as np
import matplotlib
from matplotlib import pyplot, rcParams, __version__ as mpl_version
from matplotlib.dates import date2num, num2date
import dateutil
from . import config

from .comp2to3 import is_py3, string_types, string_bytes_types, unicode_type, is_py2

# same as in fullmpcanvas.py
# follows new_figure_manager
if qt_wrap.api == 'pyqt5':
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt5 import FigureManagerQT
else:
    from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt4 import FigureManagerQT

from matplotlib.figure import Figure
if is_py2:
    from distutils.version import LooseVersion as Version
    # see from mpl_toolkits.axes_grid1 import host_subplot
    # matplotlib/Examples/axes_grid/demo_parasite_axes2.py
    #from mpl_toolkits.axes_grid1 import host_subplot
    from mpl_toolkits.axes_grid1.parasite_axes import host_subplot_class_factory
    import mpl_toolkits.axisartist as AA
    host_subplot_class = host_subplot_class_factory(AA.Axes)
else:
    from packaging.version import Version

# This problem affects Anaconda 5.2
# see https://github.com/matplotlib/matplotlib/issues/12208
Vmpl = Version(mpl_version)
if Version('2.2.0') <= Vmpl < Version('2.2.4') or \
   Vmpl == Version('3.0.0'):
       def transform_non_affine_wrapper(self, points):
           if not isinstance(points, np.ndarray):
               points = np.array(points)
           return self._transform_non_affine_cl_org(points)
       BGT = matplotlib.transforms.BlendedGenericTransform
       #print('About to fix mpl_toolkit log scale transform bug of 2.2.x')
       if not hasattr(BGT, '_transform_non_affine_cl_org'):
           print('Fixing mpl_toolkit log scale transform bug of 2.2.x')
           BGT._transform_non_affine_cl_org = BGT.transform_non_affine
           BGT.transform_non_affine = transform_non_affine_wrapper

SEC_PER_DAY = 3600*24.
if Vmpl < Version('3.3.0'):
    from matplotlib.dates import num2epoch, epoch2num
else:
    from matplotlib.dates import get_epoch
    # epoch2num and num2epoch were deprated in matplotlib 3.3 and removed in 3.7
    # The matplotlib epoch as aslo changed from 0000-12-31 to 1970-01-01
    # and could be changed using set_epoch.
    # now could use
    def _get_epoch():
        """ unix epoch offset in sec from current matplotlib offset """
        return (np.datetime64('1970-01-01T00:00:00', 's') -  np.datetime64(get_epoch(), 's')).astype(float)
    def epoch2num(e):
        return (np.asarray(e) + _get_epoch()) / SEC_PER_DAY
    def num2epoch(d):
        return np.asarray(d)*SEC_PER_DAY - _get_epoch()

def set_draggable(legend):
    try:
        legend.set_draggable(True)
    except AttributeError:
        legend.draggable()

_plot_date_discouraged = False
if Vmpl >= Version('3.5.0'):
    _plot_date_discouraged = True
    def _unixepoch2datetime64(x):
        x = np.asarray(x) * 1e6
        return x.astype('datetime64[us]')

_figlist = []

# set the timezone for proper display of date/time axis
# to see available ones: import pytz; pytz.all_timezones
#rcParams['timezone']='Canada/Eastern'
rcParams['timezone'] = config.pyHegel_conf.timezone
#rc('mathtext', fontset='stixsans')

"""
The figure handles many hot keys. They can be changed using rcParams (keymap...)
They are:
  fullscreen ( default: f)
  home (home, h, r)
  backward (left, backspace, c)
  forward (right, v)
  pan (p)
  zoom (o)
  save (s)
When over an axis:
  grid (g)
  y log/linear (l)
  x log/linear (k, L)
  pan/zoom all axes (a)
  pan/zoom one axis (1-9)
     Added: This also selects the axis used to display values in status bar.

Mouse:
 in pan mode:
   left button: moves
   right button: scales in/out while dragging
 in zoom mode:
   left button: zoom in on rectangle
   right button: zoom out of rectangle
   press x or y while zooming to limit the zooming to the x or y scale

"""

# FigureCanvas is already a subclass of object because of QWidget (for older
# versions of matplotlib that used old style classes)
class TraceCanvas(FigureCanvas):
    def __init__(self, *args, **kwargs):
        super(TraceCanvas, self).__init__(*args, **kwargs)
        try:
            self.keyvald.update({QtCore.Qt.Key_Left:'left',
                                    QtCore.Qt.Key_Right:'right',
                                    QtCore.Qt.Key_Up:'up',
                                    QtCore.Qt.Key_Down:'down',
                                    QtCore.Qt.Key_Escape:'escape',
                                    QtCore.Qt.Key_Home:'home',
                                    QtCore.Qt.Key_End:'end',
                                    QtCore.Qt.Key_Backspace:'backspace'})
        except AttributeError: # matplotlib 1.4.2 includes all these keys already
            pass               # in matplotlib.backends.backend_qt5.SPECIAL_KEYS
    def get_default_filename(self, *args, **kwargs):
        default_filename = super(TraceCanvas, self).get_default_filename(*args, **kwargs)
        # cleanup more, matplotlib 1.4.2 at least, allows : / \ in default_filename
        # but qt, _getSaveFileName does not run with an improper filename (like sweep:0)
        # In older versions of matplotlib (like 1.0.1) this functions was not used
        #   The _getSaveFilename was always 'image.ext'
        default_filename = default_filename.replace(':', '-')
        default_filename = default_filename.replace('/', '-')
        default_filename = default_filename.replace('\\', '-')
        default_filename = default_filename.replace('\\', '-')
        # other onces that windows does not like:
        default_filename = default_filename.replace('"', '_')
        default_filename = default_filename.replace('?', '_')
        default_filename = default_filename.replace('|', '_')
        default_filename = default_filename.replace('*', '_')
        default_filename = default_filename.replace('<', '_')
        default_filename = default_filename.replace('>', '_')
        return default_filename

def get_last_trace():
    return _figlist[-1]

def close_last_trace():
    get_last_trace().window.close()

def time2date(x):
    """
    This is the same as epoch2num.
    It converts time in sec since epoch to matplotlib date format.
    Can do the reverse with num2epoch
    """
    return x/SEC_PER_DAY + epoch2num(0)

if _plot_date_discouraged:
    _time2date = _unixepoch2datetime64
else:
    _time2date = time2date

def get_timezone_shift(x=None):
    """
    returns the timezone shift of x in seconds (UTC - local)
    x should be the time in s since the unix epoch
     (as returned by time.time())
    """
    dt = time.localtime(x)
    if dt.tm_isdst:
        tz = time.altzone
    else:
        tz = time.timezone
    return tz

_TZOFFSETS = {'EST': -5*3600, 'DST':-4*3600}
def str_epoch2num(s):
    """
    input is either a string or and time in seconds since epoch
    output is the date format of matplotlib
    Without a timezone in the input string, the local timezone is used.
    To enter a timezone you can use UTC, GMT,Z or something like
    -0500. It also knows about EST and DST.
    """
    if isinstance(s, string_types):
        # we replace pyplot.datestr2num to better handle local timezone
        dt = dateutil.parser.parse(s, tzinfos=_TZOFFSETS)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dateutil.tz.tzlocal())
        return date2num(dt)
    else:
        return epoch2num(s)

def num2str(n, tz=False):
    """
    converts from matplotlib date format to a string
    With tz=True also shows the timezone
    """
    # could also use .isoformat
    if tz:
        return num2date(n).strftime('%Y-%m-%d %H:%M:%S.%f %Z')
    else:
        return num2date(n).strftime('%Y-%m-%d %H:%M:%S.%f')

def xlim_time(xmin=None, xmax=None, epoch=False):
    """
    same as xlim, except xmin, xmax
    are in epoch time or a string on input
    and are str as output
    unless epoch=True then the return is seconds since epoch
    For the format accepted see str_epoch2num
    """
    if isinstance(xmin, tuple):
        xmin, xmax = xmin
    if xmin is not None:
        xmin = str_epoch2num(xmin)
    if xmax is not None:
        xmax = str_epoch2num(xmax)
    xmin, xmax = pyplot.xlim(xmin, xmax)
    if epoch:
        return num2epoch(xmin), num2epoch(xmax)
    else:
        return num2str(xmin), num2str(xmax)


def time_stripdate(x, first=None):
    """
    takes either first if given or the first element of x
    and returns x minus that first value date (time=0:0:0)
    x, first and return are in seconds.
    x and first are since epoch (time.time())
    """
    if first is None:
        try:
            first = x[0]
        except TypeError:
            first = x
    dt = list(time.localtime(first))
    dt[3]=0 # tm_hour
    dt[4]=0 # tm_min
    dt[5]=0 # tm_sec
    offset = time.mktime(dt)
    return x-offset

class _Trace_Cleanup(object):
    def __del__(self):
        #print('Trace cleanup (garbage collect)')
        gc.collect()

class TraceBase(FigureManagerQT, object): # FigureManagerQT is old style class so need object to make it new one (so super works properly for childs)
    # A useful subclass will need at least to include update
    def __init__(self, width=9.00, height=7.00, dpi=72, do_show=True):
        self.fig = Figure(figsize=(width,height),dpi=dpi)
        self.canvas = TraceCanvas(self.fig)
        FigureManagerQT.__init__(self,self.canvas,-1)
        self.MainWidget = self.window
        self.setWindowTitle('Trace...')
        self.isclosed = False
        #########
        _figlist.append(self)
        # The closing of matplotlib was changed in 1.2.1
        #   https://github.com/matplotlib/matplotlib/pull/1498
        #   It used to have QtCore.Qt.WA_DeleteOnClose attribute set on the main window
        #   now it uses the closing signal for regular figures. Lets do something similar.
        #self.window.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        # closing is emitted when calling function slot close (usually connected to the window close
        #  button)
        try:
            # for matplotlib >= 1.2.1
            self.window.closing.connect(self.close_slot)
        except AttributeError:
            # Using that QtCore.Qt.WA_DeleteOnClose attribute is set
            self.window.destroyed.connect(self.close_slot)
        if do_show:
            self.show()
    def close_slot(self):
        """
        Remove the Trace from the list so that it can be deleted on the next
        garbage collect. It returns an object that will do a garbage collect
        once it is deleted.
        """
        if not self.isclosed:
            self.isclosed = True
            _figlist.remove(self)
        # The figure is removed when all references to it are lost and probably
        # needs a garbage collection. The _figlist removal is only one location
        # for references. A user might have others.
        return _Trace_Cleanup() #when this return value is deleted, it will call do a gargage collect
    def destroy(self, *args):
        """
        This functions returns an object that will finish the clean up.
        You should call it in this way:
            tr = tr.destroy() # this removes the last connection to the TraceBase (tr) object
                              # and replaces it by a new clean up class
            del tr            # this executes the clean up class (does a garbage collect)
        """
        if self.isclosed:
            super(TraceBase, self).destroy(*args)
            return _Trace_Cleanup()
        # we want control of the garbage collection so lets do the close_slot directly.
        try:
            self.window.closing.disconnect(self.close_slot)
        except AttributeError:
            self.window.destroyed.disconnect(self.close_slot)
        ret = self.close_slot() # This removes the _figlist reference (if needed) and returns a garbage collector object.
        super(TraceBase, self).destroy(*args) # this will call self.window.close()
        return ret

    def mykey_press(self, event):
        # TODO add a Rescale
        # based on FigureManagerBase.key_press
        try:
            all_keys = rcParams['keymap.all_axes']
        except KeyError:
            all_keys = ['a']
        if event.inaxes is None:
            return
        if (event.key.isdigit() and event.key!='0') or event.key in all_keys:
              # if it was the axes, where the event was raised
            if not (event.key in all_keys):
                n = int(event.key)-1
            for i, a in enumerate(self.canvas.figure.get_axes()):
                # consider axes, in which the event was raised
                # FIXME: Why only this axes?
                if event.x is not None and event.y is not None \
                       and a.in_axes(event):
                    if event.key in all_keys:
                        a.zorder = 0
                        a.set_navigate(True)
                        if is_py3:
                            a.patch.set_visible(i == 0)
                    else:
                        a.zorder = 1 if i==n else 0
                        a.set_navigate(i==n)
                        if is_py3:
                            # this is to prevent the background patch from overwriting the curves
                            # keep the first axis patch visible only if it has not been
                            # set to a higher zorder, otherwise enable the second axes background patch
                            # By default only the first of the axes patch is visible.
                            if (i == 0 and n > 0) or (i == 1 and n == 0):
                                a.patch.set_visible(True)
                            else:
                                a.patch.set_visible(False)

    def setWindowTitle(self, title):
        self.set_window_title(title)
    def draw(self):
        if self.isclosed:
            return
        self.canvas.draw()
    def show(self):
        if self.isclosed:
            return
        self.fig.canvas.window().show()
    def hide(self):
        if self.isclosed:
            return
        self.fig.canvas.window().hide()
    def savefig(self,*args,**kwargs):
        self.fig.savefig(*args, **kwargs)

def _offsetText_helper(self):
    self._update_offsetText_orig()
    new_xyann = False
    try:
        x,y = self.offsetText.xyann
        new_xyann = True
    except AttributeError:
        x,y = self.offsetText.xytext
    new_xy = (x+self._offsetText_xshift, y)
    if new_xyann:
        self.offsetText.xyann = new_xy
    else:
        self.offsetText.xytext = new_xy

class ExtraDialog(QtGui.QDialog):
    def __init__(self, value, parent=None):
        if value is None:
            value = 1.
        super(ExtraDialog, self).__init__(parent, windowModality=QtCore.Qt.WindowModal)
        lay = QtGui.QGridLayout()
        self.setLayout(lay)
        sb = QtGui.QDoubleSpinBox(value=value, decimals=3, minimum=0.020, maximum=86400)
        self.sb_wait_time = sb
        lay.addWidget(QtGui.QLabel('Wait time (s)'), 0, 0)
        lay.addWidget(sb, 0, 1)
        cb = QtGui.QCheckBox()
        self.cb_sync_all_y = cb
        lay.addWidget(QtGui.QLabel('Synchronize all y axes'), 1, 0)
        lay.addWidget(cb, 1, 1)
        ok = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok)
        self.button_box = ok
        lay.addWidget(ok, 2, 0, 1, 2)
        ok.accepted.connect(self.hide)


class Trace(TraceBase):
    def __init__(self, width=9.00, height=7.00, dpi=72, time_mode = False, comment_func=None, wait_time=None):
        super(Trace, self).__init__(width=width, height=height, dpi=dpi)
        if is_py2:
            ax = host_subplot_class(self.fig, 111)
            self.fig.add_subplot(ax)
        else:
            ax = self.fig.subplots()
        self.offset = 50
        self.axs = [ax]
        self.xs = None
        self.ys = None
        self.xmax = None
        self.xmin = None
        self.legend_strs = None
        self.first_update = True
        self.time_mode = time_mode
        self.wait_time = wait_time
        # could also use self.fig.autofmt_xdate()
        ax = self.axs[0]
        if time_mode:
            if is_py2:
                tlabels = ax.axis['bottom'].major_ticklabels
                tlabels.set_size(9)
                tlabels.set_rotation(10)
                tlabels.set_rotation_mode('default')
                tlabels.set_verticalalignment('top')
            else:
                # labelrotation could be a tuple (mode, angle), mode defaults to 'default'
                # Also the verticalalignment seems to be hardcoded to 'top'
                # the horizontal alignment would be changed with rcParams["xtick.alignment"]
                ax.tick_params(axis='x', which='both', labelsize=9, labelrotation=10)
        self.canvas_resizeEvent_orig = self.canvas.resizeEvent
        self.canvas.resizeEvent = self.windowResize
        self.update()
        # handle status better for twinx (pressing 1 or 2 selects axis)
        self.canvas.mpl_connect('key_press_event', self.mykey_press)
        ######### Add button to toolbar
        # Pause
        self.pause_button = QtGui.QPushButton('Pause')
        self.pause_enabled = False
        self.pause_button.setCheckable(True)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.pause_button)
        self.pause_button.toggled.connect(self.pause_button_press)
        # abort
        self.abort_button = QtGui.QPushButton('Abort')
        self.abort_enabled = False
        self.abort_button.setCheckable(True)
        self.toolbar.addWidget(self.abort_button)
        self.abort_button.toggled.connect(self.abort_button_press)
        # add comment
        self._comment_func = comment_func
        self.comment_button = QtGui.QPushButton('Comment')
        self.comment_button.setCheckable(True)
        self.toolbar.addWidget(self.comment_button)
        self.comment_button.toggled.connect(self.comment_button_press)
        self.comment_entry = QtGui.QLineEdit(enabled=False)
        self.comment_entry.returnPressed.connect(self.comment_entry_press)
        self.comment_entry.textEdited.connect(self.comment_entry_edited)
        self.comment_action = self.toolbar.addWidget(self.comment_entry)
        # for addWidget on toolbars, need to use the action for show/hide
        self.comment_action.setVisible(False)
        # Rescale
        self.rescale_button = QtGui.QPushButton('Rescale')
        self.toolbar.addWidget(self.rescale_button)
        self.rescale_button.clicked.connect(self.rescale_button_press)
        # extra
        self.extra_button = QtGui.QPushButton('Extra...')
        self.toolbar.addWidget(self.extra_button)
        self.extra_dialog = ExtraDialog(wait_time, self.extra_button)
        self.extra_button.clicked.connect(self.extra_dialog.show)
        self.extra_dialog.sb_wait_time.valueChanged.connect(self.wait_time_changed)
        self.extra_dialog.cb_sync_all_y.clicked.connect(self.sync_all_y_changed)
        # status
        self.status_label = QtGui.QLabel(text='temporary')
        self.toolbar.addWidget(self.status_label)
        self.set_status(True)
    def set_comment_func(self, func):
        self._comment_func = func
    def set_status(self, running, stop_reason='completed'):
        """
           running is True or False, or paused
           stop_reason is completed, abort or ctrl-c.
        """
        if running:
            if running == 'paused':
                t = 'Paused'
                c = 'red'
            else:
                t = 'Running'
                c = 'green'
        else:
            self.pause_button.setEnabled(False)
            self.abort_button.setEnabled(False)
            self.comment_button.setEnabled(False)
            self.comment_entry.setEnabled(False)
            self.comment_action.setVisible(False)
            t = {'completed':'Completed', 'abort':'Aborted', 'ctrl-c':'Terminated'}[stop_reason]
            if t == 'Completed':
                c = 'blue'
            else:
                c = 'red'
        self.status_label.setText('<font color="%s">%s</font>'%(c, t))
    def pause_button_press(self, state):
        self.pause_enabled = state
        if state:
            self.set_status('paused')
        else:
            self.set_status(True)
    def abort_button_press(self, state):
        self.abort_enabled = state
    def comment_button_press(self, state):
        self.comment_entry.setEnabled(state)
        self.comment_action.setVisible(state)
        self.comment_entry_edited()
    def comment_entry_edited(self, text=None):
        self.comment_entry.setStyleSheet('color: red;')
    def comment_entry_press(self):
        t = unicode_type(self.comment_entry.text())
        self.comment_entry.setStyleSheet('color: green;')
        f = self._comment_func
        if f is not None:
            f(t)
        else:
            print('Unable to save comment: %s'%t)
        #print('Got:', t)
    def rescale_button_press(self):
        # TODO tell toolbar that a new set of scales exists
        for i,ax in enumerate(self.axs):
            ax.relim()
            if i==0:
                ax.set_xlim(self.xmin, self.xmax, auto=True)
            ax.set_autoscaley_on(True)
            ax.autoscale(enable=None)
        self.draw()
    def wait_time_changed(self, val):
        self.wait_time = val

    def sync_all_y_changed(self, checked):
        if checked:
            grouper = self.axs[0].get_shared_y_axes()
            grouper.join(*self.axs)
        else:
            grouper = self.axs[0].get_shared_y_axes()
            for ax in self.axs:
                grouper.remove(ax)

    def set_xlogscale(self, enable=True):
        s = {True:'log', False:'linear'}
        self.axs[0].set_xscale(s[enable])

    def setLim(self, minx, maxx=None):
        if isinstance(minx, (list, tuple, np.ndarray)):
            maxx = np.max(minx)
            minx = np.min(minx)
        self.xmax = maxx
        self.xmin = minx
        self.axs[0].set_xlim(minx, maxx, auto=False)
        self.update()
    def set_xlabel(self, label):
        self.axs[0].set_xlabel(label)
    def addPoint(self, x, ys):
        if self.time_mode:
            # convert from sec since epoch to matplotlib date format
            x = _time2date(x)
        if self.xs is None:
            self.xs = np.array([x])
        else:  self.xs = np.append(self.xs, x)
        if self.ys is None:
            self.ys = np.array([ys])
        else:  self.ys = np.append(self.ys, [ys], axis=0)
        self.update()
    def setPoints(self, x, y):
        if self.time_mode:
            # convert from sec since epoch to matplotlib date format
            x = _time2date(x)
        self.xs = np.array(x)
        self.ys = np.array(y.T)
        self.update()
    def setlegend(self, str_lst):
        self.legend_strs = str_lst
        self.update()
    def windowResize(self, event):
        self.canvas_resizeEvent_orig(event)
        self.do_resize()
    def do_resize(self, draw=True):
        if self.xs is None:
            return
        ndim = self.ys.shape[1]
        offset = self.offset
        rel_dx, rel_dy = self.fig.transFigure.inverted().transform((offset,0))
        right = .95-(ndim-1)*rel_dx
        if right < .5:
            right = .5
        left = rel_dx*1.5
        if left >= right:
            left = right - .01
        self.fig.subplots_adjust(left=left, right=right)
        if draw:
            self.draw()
    def update(self):
        if self.xs is None:
            self.draw()
            return
        if self.first_update:
            # some older toolbar initialized the array of views to 0,1 which caused error with time conversion when hitting home.
            # some empty it now.
            self.toolbar.update() # this resets the views
            self.do_resize(draw=False)
            ndim = self.ys.shape[1]
            offset = self.offset
            host = self.axs[0]
            # cycle over all extra axes
            for i in range(ndim-1):
                ax = host.twinx()
                if is_py2:
                    new_fixed_axis = ax.get_grid_helper().new_fixed_axis
                    ax.axis['right'] = new_fixed_axis(loc='right', axes=ax, offset=(offset*i,0))
                    axr = ax.axis['right']
                    axr.toggle(all=True)
                    # Now fix problem with offset string always on same spot for all right axes
                    axr._update_offsetText_orig = axr._update_offsetText
                    axr._offsetText_xshift = offset*i
                    axr._update_offsetText = functools.partial(_offsetText_helper, axr)
                    if ndim > 2:
                        axr.offsetText.set_rotation(20)
                else:
                    ax.spines['right'].set_position(('outward', offset*i))
                self.axs.append(ax)
                # add them to figure so selecting axes (press 1, 2, a) works properly
                self.fig.add_axes(ax)
                if self.time_mode:
                    autox=True
                else:
                    autox=False
                ax.set_xlim(self.xmin, self.xmax, auto=autox)
            self.crvs = []
            #self.ax.clear()
        x = self.xs
        plot_kwargs = {}
        if is_py3:
            color_cycler = rcParams['axes.prop_cycle']()
        for i,(y,ax) in enumerate(zip(self.ys.T, self.axs)):
            style = '.-'
            if is_py3:
                line_color = next(color_cycler)['color']
                plot_kwargs['color'] = line_color
            if self.first_update:
                try:
                    lbl = self.legend_strs[i]
                except TypeError:
                    lbl = 'data '+str(i)
                if self.time_mode:
                    if _plot_date_discouraged:
                        plt = ax.plot(x, y, style, label=lbl, **plot_kwargs)[0]
                    else:
                        plt = ax.plot_date(x, y, style, label=lbl, **plot_kwargs)[0]
                else:
                    plt = ax.plot(x, y, style, label=lbl, **plot_kwargs)[0]
                if is_py2:
                    line_color = ax.lines[0].get_color()
                ax.set_ylabel(lbl, color=line_color)
                self.crvs.append(plt)
            else:
                self.crvs[i].set_data(x, y)
        if is_py2:
            leg = self.axs[0].legend(loc='upper left', bbox_to_anchor=(0, 1.10))
        else:
            leg = self.fig.legend(loc='upper left', bbox_to_anchor=(0.1, 0.98))
        set_draggable(leg)
        for ax in self.axs:
            ax.relim()
            ax.autoscale(enable=None)
        self.first_update = False
        self.draw()

def lots_pick(n):
    """
    This returns a fucntion that will pick one out of every n point
    """
    return lambda x: x[::n]

def lots_avg(n):
    """
    This returns a fucntion that will return the average of blocks of n points
    """
    return lambda x: x.reshape((-1, n)).mean(axis=1)

class TraceLots(TraceBase):
    def __init__(self, filename, width=9.00, height=7.00, dpi=72,
                 block_size=10*1024, dtype=np.uint8, trans=None):
        """
        This class allows the exploration of very large raw (binary) data file.
        The filename has to be provided.
        block_size is the number of points to show at a time
         (the slider will move in increments of half of this)
        dtype is a numpy dtype for the data (uint8, uint16 ...)
        trans is a transformation function on the data.
              The function takes the read data as input and must return
              the data to display.
              See lots_pick and lots_avg as possible functions
        """
        super(TraceLots, self).__init__(width=width, height=height, dpi=dpi)
        self.filename = filename
        self.dtype = dtype
        self.trans = trans
        self.byte_per_point = 1
        if dtype().nbytes == 2:
            self.byte_per_point = 2
        self.block_nbpoints = block_size
        self.block_size = block_size*self.byte_per_point
        self.fh = open(filename, 'rb')
        ax = self.fig.add_subplot(111)
        self.ax = ax
        self.fh.seek(0, 2) # go to end of file
        self.nbpoints = self.fh.tell() // self.byte_per_point
        self.readit() # sets self.vals
        self.mainplot = ax.plot(self.vals)[0]
        self.bar = QtGui.QScrollBar(QtCore.Qt.Horizontal)
        self.bar.setMaximum(self.nbpoints//block_size*2 -1) # every step is half a block size
        self.bar_label = QtGui.QLabel()
        self.central_widget = QtGui.QWidget()
        self.central_layout = QtGui.QVBoxLayout()
        self.central_layout.setContentsMargins(0, 0, 0, 0)
        # The QMainWindow.centralWidget is self.canvas
        self.central_layout.addWidget(self.canvas)
        self.central_layout.addWidget(self.bar)
        self.central_layout.addWidget(self.bar_label)
        self.central_widget.setLayout(self.central_layout)
        self.MainWidget.setCentralWidget(self.central_widget)
        self.bar.valueChanged.connect(self.bar_update)
        self.bar_update(0)
    def bar_update(self, val):
        offset = val * self.block_nbpoints //2
        self.bar_label.setText('offest: {:,}'.format(offset))
        self.readit(offset)
        self.update()
    def readit(self, offset=0):
        self.fh.seek(offset*self.byte_per_point)
        vals = np.fromfile(self.fh, dtype=self.dtype, count=self.block_size)
        if self.trans is not None:
            vals = self.trans(vals)
        self.vals = vals
    def update(self):
        self.mainplot.set_ydata(self.vals)
        self.draw()

class TraceWater(TraceBase):
    def __init__(self, xy, y=None, width=9.00, height=7.00, dpi=72,
                 xoffset=0., yoffset=0., xlog=False, ylog=False):
        """
        This makes a waterfall plot with adjustable spacing
        Either specify x and y with the same dimensions, or xy
        can contain x and y as the first index.
        xy can be left None, which will make the x axis the index of the points
        When x and y are given separatelly, x can be a 1D vector
        So y should have shape (ncurves, nptspercurve)
        x is the same or (2, ncurves, nptspercurve)
        xoffset and yoffset are fractions of full scale (or of half scale for x)
        """
        super(TraceWater, self).__init__(width=width, height=height, dpi=dpi)
        ax = self.fig.add_subplot(111)
        self.ax = ax
        if y is None:
            self.y = xy[1]
            self.x = xy[0]
        else:
            self.y = y
            self.x = xy
        if self.x is None:
            self.x = np.arange(self.y.shape[-1])+.01 # prevents divide by zero
        if self.x.ndim == 1:
            self.x = self.x[None, :]
        self.dx = float(self.x.max() - self.x.min())
        self.dy = float(self.y.max() - self.y.min())
        self.xratio = float(self.x.max() / self.x.min())
        self.yratio = float(self.y.max() / self.y.min())
        self.ncurves = self.y.shape[0]
        #self.hbar = QtGui.QScrollBar(QtCore.Qt.Horizontal)
        #self.vbar = QtGui.QScrollBar(QtCore.Qt.Vertical)
        self.hbar = QtGui.QSlider(QtCore.Qt.Horizontal)
        self.vbar = QtGui.QSlider(QtCore.Qt.Vertical)
        self.hbar_rev = QtGui.QCheckBox('Reverse')
        self.xlog = QtGui.QCheckBox('Xlog')
        self.ylog = QtGui.QCheckBox('Ylog')
        #### handle central widget layout
        self.central_widget = QtGui.QWidget()
        layout = QtGui.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout_top = QtGui.QHBoxLayout()
        layout_top.setContentsMargins(0, 0, 0, 0)
        layout_bottom = QtGui.QHBoxLayout()
        layout_bottom.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(layout_top)
        layout.addLayout(layout_bottom)
        # The QMainWindow.centralWidget is self.canvas
        layout_top.addWidget(self.canvas)
        layout_top.addWidget(self.vbar)
        layout_bottom.addWidget(self.hbar)
        layout_bottom.addWidget(self.hbar_rev)
        layout_bottom.addWidget(self.xlog)
        layout_bottom.addWidget(self.ylog)
        self.central_widget.setLayout(layout)
        self.MainWidget.setCentralWidget(self.central_widget)
        ####
        self.max_bar = 100
        self.gamma = 30.
        self.hbar.setMaximum(self.max_bar)
        self.vbar.setMaximum(self.max_bar)
        #self.vbar.setInvertedAppearance(True)
        #self.vbar.setInvertedControls(True)
        self.invert_y = False
        self.set_xy_offset(xoffset, yoffset)
        self.hbar.valueChanged.connect(self.update)
        self.vbar.valueChanged.connect(self.update)
        self.hbar_rev.stateChanged.connect(self.update)
        self.xlog.stateChanged.connect(self.update)
        self.ylog.stateChanged.connect(self.update)
        self.update()
    def bar_to_x(self, bar, rev=False, invert=False):
        # invert to change bar direction
        # rev to make the offset negative
        # returned value ranges from 0. to 1.
        mx = self.max_bar
        gamma = self.gamma
        if invert:
            bar = mx - bar
        if bar == 0:
            return 0
        return 10.**((bar-mx)/gamma)
    def x_to_bar(self, x, invert=False):
        mx = self.max_bar
        gamma = self.gamma
        rev = False
        if x < 0:
            rev = True
            x = -x
        if x == 0:
            return 0, rev
        bar = int(np.log10(x)*gamma) + mx
        if invert:
            bar = mx - bar
        return bar, rev
    def set_xy_offset(self, xo, yo):
        h, rev = self.x_to_bar(xo)
        self.hbar_rev.setCheckState(rev)
        v, foo = self.x_to_bar(yo, invert=self.invert_y)
        self.hbar.setValue(h)
        self.vbar.setValue(v)
    def get_xy_offset(self):
        h = self.hbar.value()
        v = self.vbar.value()
        xo = self.bar_to_x(h, rev=self.hbar_rev.checkState())
        yo = self.bar_to_x(v, invert=self.invert_y)
        if self.hbar_rev.checkState():
            xo = -xo
        return xo, yo
    def get_scaled_xy_offset(self):
        xo, yo = self.get_xy_offset()
        if self.xlog.checkState():
            xs = self.xratio**(xo/2)
        else:
            xs = xo*self.dx/2.
        if self.ylog.checkState():
            ys = self.yratio**yo
        else:
            ys = yo*self.dy
        return xs, ys
    def update(self, foo=None):
        self.ax.cla()
        xs, ys = self.get_scaled_xy_offset()
        v = np.arange(self.ncurves)
        x = self.x.T
        y = self.y.T
        if self.xlog.checkState():
            self.ax.set_xscale('log')
            x = x * xs**v
        else:
            x = x + xs*v
        if self.ylog.checkState():
            self.ax.set_yscale('log')
            y = y * ys**v
        else:
            y = y + v*ys
        self.ax.plot(x, y)
        self.draw()


def plot_time(x, *extrap, **extrak):
    """
       The same as plot_date, but takes in the time in sec since epoch
       instead of the matplotlib date format.
       (It can use the result of time.time())
       Added Parameter:
        xrotation: which rotates the x ticks (defautls to 10 deg)
        xticksize: changes x axis thick size (defaults to 9)
    """
    x = _time2date(x)
    xrotation = extrak.pop('xrotation', 10)
    xticksize = extrak.pop('xticksize', 9)
    if _plot_date_discouraged:
        ret = pyplot.plot(x, *extrap, **extrak)
    else:
        ret = pyplot.plot_date(x, *extrap, **extrak)
    ax = ret[0].axes
    # Rotate axes ticks
    # could also use self.fig.autofmt_xdate()
    lbls = ax.get_xticklabels()
    for l in lbls:
        l.update(dict(rotation=xrotation, size=xticksize))
    pyplot.draw()
    return ret

def _plot_time_mouse(event):
    if event.button != 1:
        return
    if event.canvas.toolbar.mode != u'':
        # only work in selection mode, not u'pan/zoom', u'zoom rect'
        return
    axs = event.canvas.figure.axes
    if len(axs) < 2:
        return
    #print(event, event.name)
    if event.name == 'button_press_event':
        def do_l(l):
            l.set_visible(True)
            l.set_xdata([event.xdata, event.xdata])
    else: # button_release_event
        def do_l(l):
            l.set_visible(False)
    for ax in event.canvas.figure.axes:
        if len(ax.lines):
            l = ax.lines[0]
            ydata = l.get_ydata()
            # detect for axvline
            if isinstance(ydata, list) and ydata  == [0, 1]:
                do_l(l)
    event.canvas.draw()


def plot_time_stack(x, *ys, **kwargs):
    """
       Uses plot_time (so x is the time axis)
       but plots vertically stacked graphs (all the same x axis).
       Every ys argument is plotted in its own graph (from top to bottom).
       The ys can be a single 2D numpy array (first dim is line index, second is pt index)
        or a list of 1D array.
       The last ys can be a fmt argument (like ".-")
       other kargs are passed to plot_time.
       you can provide a labels argument and it will be applied to the graph (same shape as the data,
          use None to skip labels on an axes).
       It plots in the current figure. If the current figure already has enough
       axes, it reuses them, otherwise it creates new ones. You should clf() before changing the
       number of axes.
       title: providing this will put a figure title (title on the first axis).
       A vertical line on all axes is displayed when pressing the mouse button is pressed and no tool is selected.
    """
    labels = kwargs.pop('labels', None)
    title = kwargs.pop('title', None)
    if isinstance(ys[-1], str):
        fmt = ys[-1]
        ys = ys[:-1]
        extra = [fmt]
    else:
        extra = []
    Nr = len(ys)
    if labels is None:
        labels = [None]*Nr
    if len(labels) < Nr:
        labels = labels + [None]*(Nr-len(labels))
    fig = pyplot.gcf()
    if len(fig.axes) < Nr:
        fig1, axs1 = pyplot.subplots(nrows=Nr, sharex=True, squeeze=True, gridspec_kw=dict(hspace=0), num=fig.number)
        xo = _time2date(x[0])
        for ax in axs1[1:]:
            ax.yaxis.get_major_locator().set_params(prune='upper')
        for ax in axs1:
            ax.axvline(x=xo, color='k', linewidth=.5, visible=False)
        if any([c==_plot_time_mouse for c in fig.canvas.callbacks.callbacks['button_press_event'].values()]):
            pass
        else:
            fig.canvas.mpl_connect('button_press_event', _plot_time_mouse)
            fig.canvas.mpl_connect('button_release_event', _plot_time_mouse)
    else:
        fig1, axs1 = fig, fig.axes
    for i, (y, ax, lbls) in enumerate(zip(ys, axs1, labels)):
        pyplot.sca(ax)
        if i == 0 and title is not None:
            pyplot.title(title)
        if isinstance(y, (list, tuple)):
            y = np.asarray(y)
        lines = plot_time(x, y.T, *extra, **kwargs)
        if lbls is not None:
            if not isinstance(lbls, (list, tuple, np.ndarray)):
                lbls = [lbls]
            for l, lbl in zip(lines, lbls):
                l.set_label(lbl)
            leg = pyplot.legend()
            set_draggable(leg)



def plot_time_stack_qd(qdata, *indices, **kwargs):
    """ like plot_time_stack except for QD_Data.
        Instead of providing x and ys you provide the Qd_Data
        and the indices. It will generate the correct labels by default.
        You can set raw=True if you want to use the raw indices instead.
        The indices can be a single value, a list of indices or a slice.
    """
    raw = kwargs.pop('raw', False)
    labels = kwargs.pop('labels', None)
    data = qdata.vr if raw else qdata
    if labels is None:
        titles = qdata.titles_raw if raw else qdata.titles
    if isinstance(indices[-1], str):
        extra = [indices[-1]]
        indices = indices[:-1]
    else:
        extra = []
    ys = [data[sel] for sel in indices]
    if labels is None:
        labels = [titles[sel] for sel in indices]
    kwargs['labels'] = labels
    ys += extra
    plot_time_stack(qdata.t, *ys, **kwargs)

