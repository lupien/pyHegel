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

# answers obtained on phone in july 2014
#  next version might use msi for python install (option of distutils)
#     Done in 14.08
#  Juerg said set-sync--get is the safest (better than set--get). Other option
#    would be to subscribe to the changes.
#  time-constants in sweep (real vs calculated value).
#    Discussed it. The conversion could be done on client side, but that requires making
#    sure the algorithm is the same everywhere in all details. He has a similar problem
#    with frequency when sync will be enabled (limits the number of frequency usable)
#    Also from email (23062014): Extracting the real timeconstant is some effort.
#      It should be done asynchronous as we otherwise diminish the sweeper speed
#      significantly. I will put it in out ticket system. It is however not clear
#      when I can offer a solution.

from __future__ import absolute_import

import numpy as np
#import zhinst.ziPython as zi
#import zhinst.utils as ziu
zi = None
ziu = None

from ..instruments_base import BaseInstrument,\
                            BaseDevice, scpiDevice, InvalidAutoArgument,\
                            MemoryDevice, ReadvalDev,\
                            ChoiceDevDep,\
                            sleep, locked_calling, ProxyMethod, _retry_wait, _repr_or_string
from ..instruments_base import ChoiceIndex as _ChoiceIndex
from ..instruments_registry import register_instrument
from .logical import FunctionDevice
from scipy.special import gamma

def _get_zi_python_version(dev=None, host='localhost', port=8004):
    if dev == None:
        dev = zi.ziDAQServer(host, port, 1)
    python_ver = dev.version()
    python_rev = dev.revision()
    return python_ver, python_rev

_error_connection_invalid = 'ZIAPIException with status code: 32780. Connection invalid'
def _check_zi_python_version(*arg, **kwarg):
    try:
        python_ver, python_rev = _get_zi_python_version(*arg, **kwarg)
    except RuntimeError as e:
        if e.message == _error_connection_invalid:
            # We get this when the server does not accept the connection because the client is too old
            python_ver, python_rev = '0.0', 0
        else:
            raise
    python_ver = [int(v) for v in python_ver.split('.')]
    if python_ver[0] < 14 or python_ver[1] < 8 or python_rev < 26222:
        raise RuntimeError("The ziPython is too old. Install at least ziPython2.7_ucs2-14.08.26222-win32.msi")

class ChoiceIndex(_ChoiceIndex):
    def __call__(self, input_val):
        return self[input_val]
    def tostr(self, input_choice):
        return self.index(input_choice)

def _tostr_helper(val, t):
    # This function converts from pyHegel val to ZI val (on set/write)
    if t == None:
        return val
    if t == bool:
        return int(val)
    if t == float:
        return float(val)
    if t == int:
        return int(val)
    if type(t) == type and issubclass(t, basestring):
        return t(val)
    return t.tostr(val)

def _fromstr_helper(valstr, t):
    # This function converts from ZI val to pyHegel (on get/ask)
    if t == None:
        return valstr
    if t == bool:
        return bool(valstr)
    if t == float:
        return float(valstr)
    if t == int:
        return int(valstr)
    if type(t) == type and issubclass(t, basestring):
        return t(valstr)
    return t(valstr)



class ziDev(scpiDevice):
    _autoset_val_str = ''
    def __init__(self, setstr=None, getstr=None, autoget=True, str_type=None, insert_dev=True,
                 input_sel='auto', input_repeat=None, input_type='auto', input_src='main', **kwarg):
        """
        input_sel can be None: then it returns the whole thing
                    otherwise it is the index to use
                    When auto, it is None for input_src='main' and 0 otherwise
        input_repeat is an iterable that will be passed to set/getstr
                     as rpt_i
        The _tostr and _fromstr converter no longer need to convert to and from
        str, but to and from the device representation
        insert_dev when True, inserts '/{dev}/' to the entry if input_src=='main'

        str_type available (pyHegel, zi):
                  None (no conversion)
                  bool (bool, 'int')
                  float(float, 'double')
                  int(int, 'int')
                  str(str, 'byte')
                  unicode(unicode, 'byte')

        if ask_write_options is given, it is used as is, otherwise:
         input_type can be None, 'auto', 'int', 'double', 'byte'
              and for getstr only it can also be: 'dio', 'sample', 'dict'
             'auto' will select according to str_type unless input_src is not
              'main' in which case it will be None
           it is used as the t value for ask_write_opt options.
         input_src selects the source of the info. It can be
             'main', 'sweep', 'record' or 'zoomFFT'
        """
        if input_sel == 'auto':
            if input_src == 'main':
                input_sel = None
            else:
                input_sel = 0
        self._input_sel = input_sel
        self._input_repeat = input_repeat
        ask_write_opt = kwarg.pop('ask_write_opt', None)
        if ask_write_opt == None:
            t = input_type
            if t == 'auto':
                if input_src == 'main':
                    t = {None:None, bool:'int', float:'double', int:'int', str:'byte', unicode:'byte'}[str_type]
                else:
                    t = None
            ask_write_opt = dict(t=t, src=input_src)
        kwarg.update(ask_write_opt=ask_write_opt)
        if autoget and setstr != None:
            getstr = setstr
        insert_dev_pre = '/{{dev}}/'
        if insert_dev and input_src=='main':
            if getstr:
                getstr = insert_dev_pre+getstr
            if setstr:
                setstr = insert_dev_pre+setstr
        super(ziDev, self).__init__(setstr, getstr, str_type=str_type, **kwarg)
    def _tostr(self, val):
        # This function converts from val to a str for the command
        t = self.type
        return _tostr_helper(val, t)
    def _fromstr(self, valstr):
        # This function converts from the query result to a value
        t = self.type
        return _fromstr_helper(valstr, t)
    def _apply_sel(self, val):
        if self._input_sel != None:
            return val[self._input_sel]
        return val
    def _setdev(self, val, **kwarg):
        if self._setdev_p == None:
            raise NotImplementedError, self.perror('This device does not handle _setdev')
        options = self._combine_options(**kwarg)
        command = self._setdev_p
        repeat = self._input_repeat
        if repeat == None:
            repeat = [1]
            val = [val]
        for i, rpt_i in enumerate(repeat):
            options['rpt_i'] = rpt_i
            cmd = command.format(**options)
            v = self._tostr(val[i])
            self.instr.write(cmd, v, **self._ask_write_opt)
    def _getdev(self, **kwarg):
        if self._getdev_p == None:
            raise NotImplementedError, self.perror('This device does not handle _getdev')
        try:
            options = self._combine_options(**kwarg)
        except InvalidAutoArgument:
            self.setcache(None)
            raise
        command = self._getdev_p
        ret = []
        repeat = self._input_repeat
        if repeat == None:
            repeat = [1]
        for i in repeat:
            options['rpt_i'] = i
            cmd = command.format(**options)
            reti = self.instr.ask(cmd, **self._ask_write_opt)
            reti = self._apply_sel(reti)
            reti = self._fromstr(reti)
            ret.append(reti)
        if self._input_repeat == None:
            return ret[0]
        return ret



# sweeper structure
#  sweep/averaging/sample
#  sweep/averaging/tc
#  sweep/bandwidth
#  sweep/bandwidthcontrol
#  sweep/clearhistory
#  sweep/device
#  sweep/endless
#  sweep/fileformat
#  sweep/filename
#  sweep/gridnode
#  sweep/historylength
#  sweep/loopcount
#  sweep/maxbandwidth      (new 14.08)
#  sweep/omegasuppression  (new 14.08)
#  sweep/order             (new 14.08)
#  sweep/phaseunwrap
#  sweep/samplecount
#  sweep/savepath          (new 14.08)
#  sweep/scan
#  sweep/settling/inaccuracy (new 14.08)
#  sweep/settling/tc
#  sweep/settling/time
#  sweep/sincfilter        (new 14.08)
#  sweep/start
#  sweep/stop
#  sweep/xmapping

# record structure
#  trigger/0/bandwidth
#  trigger/0/bitmask
#  trigger/0/bits
#  trigger/0/count
#  trigger/0/delay
#  trigger/0/duration
#  trigger/0/edge
#  trigger/0/findlevel
#  trigger/0/holdoff/count
#  trigger/0/holdoff/time
#  trigger/0/hwtrigsource (new in 13.10)
#  trigger/0/hysteresis   (new 14.08)
#  trigger/0/path
#  trigger/0/pulse/max
#  trigger/0/pulse/min
#  trigger/0/retrigger
#  trigger/0/source
#  trigger/0/type
#  trigger/buffersize
#  trigger/clearhistory
#  trigger/device
#  trigger/endless
#  trigger/fileformat    (new 14.08)
#  trigger/filename
#  trigger/forcetrigger (new in 13.10)
#  trigger/historylength
#  trigger/savepath      (new 14.08)
#  trigger/triggered
#          14.08 removed trigger/0/highlevel, trigger/0/lowlevel

# zoomFFT structure
#  zoomFFT/absolute
#  zoomFFT/bit
#  zoomFFT/device
#  zoomFFT/endless
#  zoomFFT/loopcount
#  zoomFFT/mode
#  zoomFFT/overlap
#  zoomFFT/settling/tc
#  zoomFFT/settling/time
#  zoomFFT/window  (new in 13.10)

#######################################################
##    Zurich Instruments UHF (600 MHz, 1.8 GS/s lock-in amplifier)
#######################################################

# make this match idn
@register_instrument('Zurich Instrument', 'UHFLI')
class zurich_UHF(BaseInstrument):
    """
    This instrument controls a Zurich Instrument UHF lock-in amplifier
     To use this instrument, the most useful devices are probably:
       fetch
       readval
     Important methods are:
       set_lia_mode
       set_sweep_mode
    """
    def __init__(self, zi_dev=None, host='localhost', port=8004):
        """
        By default will use the first zi device available.
        """
        global zi, ziu
        import zhinst.ziPython as zi
        import zhinst.utils as ziu
        timeout = 500 #ms
        # Note that deleting the _zi_daq frees up all the memory of
        #  sweep, record, .... and renders them unusable
        # To free up the memory of sweep, call sweep.clear() before deleting
        # (or replacing) it.
        APIlevel = 4 # 1 or 4 for version 14.02, 14.08
        try:
            self._zi_daq = zi.ziDAQServer(host, port, APIlevel)
        except RuntimeError as e:
            if e.message == _error_connection_invalid:
                # we are probably using the wrong version, check that.
                _check_zi_python_version(host=host, port=port)
            if e.message == 'ZIAPIException with status code: 32778. Unable to connect socket':
                raise RuntimeError('Unable to connect to server. Either you have the wrong host/port '
                                   'or the server is not running. On Windows you need to start (from start menu): '
                                   'Zurich Instrument/LabOne Servers/LabOne Data Server UHF (make sure that at least '
                                   'the DATA server runs. The WEB can run but it is not used from python.)')
            raise
        _check_zi_python_version(self._zi_daq)
        self._zi_record = self._zi_daq.record(10, timeout) # 10s length
        self._zi_sweep = self._zi_daq.sweep(timeout)
        self._zi_zoomFFT = self._zi_daq.zoomFFT(timeout)
        self._zi_devs = ziu.devices(self._zi_daq)
        self._zi_sep = '/'
        if zi_dev == None:
            try:
                zi_dev = self._zi_devs[0]
                print 'Using zi device ', zi_dev
            except IndexError:
                raise ValueError, 'No devices are available'
        elif zi_dev not in self._zi_devs:
            raise ValueError, 'Device "%s" is not available'%zi_dev
        self._zi_dev = zi_dev
        self._current_mode = 'lia'
        super(zurich_UHF, self).__init__()
        self._async_select()
    def _tc_to_enbw_3dB(self, tc=None, order=None, enbw=True):
        """
        When enbw=True, uses the formula for the equivalent noise bandwidth
        When enbw=False, uses the formula for the 3dB point.
        When either or both tc and order are None, the cached values are used
        for the current_demod channel.
        If you enter the bandwith frequency for tc, a time constant is returned.
        If you enter a timeconstant for tc, a bandwidth frequency is returned.
        """
        if order == None:
            order = self.demod_order.getcache()
        if tc == None:
            tc = self.demod_tc.getcache()
        if enbw:
            return (1./(2*np.pi*tc)) * np.sqrt(np.pi)*gamma(order-0.5)/(2*gamma(order))
        else:
            return np.sqrt(2.**(1./order) -1) / (2*np.pi*tc)
    def _current_config_demod_helper(self, chs):
        # chs needs to be a list
        just_one = False
        if len(chs) == 1:
            just_one = True
        # could add demod_bw3db, demod_enbw but they are conversion of demod_tc
        demod_conf = ['demod_en', 'demod_freq', 'demod_harm', 'demod_rate', 'demod_tc',
                      'demod_order', 'demod_phase', 'demod_trigger','demod_bypass_en',
                      'demod_osc_src', 'demod_adc_src', 'demod_sinc_en']
        ret = []
        for c in chs:
            self.current_demod.set(c)
            cret = []
            for n in demod_conf:
                # follows _conf_helper
                val = _repr_or_string(getattr(self, n).getcache())
                cret.append(val)
            if ret == []:
                ret = cret
            else:
                ret = [old+', '+new for old, new in zip(ret, cret)]
        if just_one:
            ret = [n+'='+v for n, v in zip(demod_conf, ret)]
        else:
            ret = [n+'=['+v+']' for n, v in zip(demod_conf, ret)]
        return ret
    def _current_config(self, dev_obj=None, options={}):
        extra = []
        if dev_obj in  [self.fetch, self.readval]:
            if self._current_mode == 'sweep':
                extra = self._conf_helper('sweep_x_start', 'sweep_x_stop', 'sweep_x_count', 'sweep_x_log',
                                          'sweep_loop_count', 'sweep_auto_bw_mode', 'sweep_auto_bw_fixed', 'sweep_max_bw',
                                          'sweep_order', 'sweep_omega_suppression_db', 'sweep_sinc_en',
                                          'sweep_settling_time_s', 'sweep_settling_n_tc', 'sweep_settling_inaccuracy',
                                          'sweep_averaging_count', 'sweep_averaging_n_tc',
                                          'sweep_mode', 'sweep_phase_unwrap_en', 'sweep_x_src_node',
                                          'sweep_endless_loop_en')
            elif self._current_mode == 'lia':
                pass
            orig_ch = self.current_demod.getcache()
            ch = options.get('ch', None)
            ch = self._fetch_ch_helper(ch)
            extra += self._current_config_demod_helper(ch)
            self.current_demod.set(orig_ch)
        else:
            extra = self._conf_helper('current_demod',
                                      'demod_en', 'demod_freq', 'demod_harm', 'demod_rate', 'demod_tc', 'demod_order',
                                      'demod_phase', 'demod_trigger', 'demod_bypass_en', 'sweep_sinc_en',
                                      'demod_osc_src', 'demod_adc_src')
        base = self._conf_helper('current_demod', 'current_osc', 'current_sigins', 'current_sigouts',
                                 'osc_freq', 'sigins_en', 'sigins_ac_en', 'sigins_50ohm_en',
                                 'sigins_range',
                                 'sigouts_en', 'sigouts_offset', 'sigouts_range', 'sigouts_ampl_Vp', 'sigouts_50ohm_en',
                                 'sigouts_autorange_en', 'sigouts_output_clipped', options)
        return extra+base
    def _conv_command(self, comm):
        """
        comm can be a string, a list of strings (to concatenate together)
        or a list of tuples (command, value)
        and it replaces {dev} with the current device
        """
        sep = self._zi_sep
        if isinstance(comm, (list, tuple)):
            if isinstance(comm[0], (list, tuple)):
                comm = [(c.format(dev=self._zi_dev), v) for c,v in comm]
            else: # a list of strings to join using sep
                comm = sep+ sep.join(comm)
        else: # a single command
            comm = comm.format(dev=self._zi_dev)
        return comm
    def _select_src(self, src):
        """
        available sources are:
            'main', 'sweep', 'record' and 'zoomFFT'
        returns object and prepend string
        """
        if src == 'main':
            ret = self._zi_daq
            pre = ''
        elif src == 'sweep':
            ret = self._zi_sweep
            pre = 'sweep'
        elif src == 'record':
            ret = self._zi_record
            pre = 'trigger'
        elif src == 'zoomFFT':
            ret = self._zi_zoomFFT
            pre = 'zoomFFT'
        else:
            raise ValueError, 'Invalid src'
        if ret == None:
            raise ValueError, 'Requested src is not available'
        return ret, pre
    def list_nodes(self, base='/', src='main', recursive=True, absolute=True, leafs_only=True, settings_only=False):
        """
        base = '/' unless src is not 'main' in which case
        it will be '/*'
        see _select_src for available src
        """
        base = self._conv_command(base)
        flags = 0
        if base == '/' and src != 'main':
            base = '/*'
        if recursive:
            flags |= 1
        if absolute:
            flags |= (1<<1)
        if leafs_only:
            flags |= (1<<2)
        if settings_only:
            flags |= (1<<3)
        src, pre = self._select_src(src)
        # The returned list is all caps (up to 14.02), but I prefer/want it lower case
        return [s.lower() for s in src.listNodes(pre+base, flags)]
    def _subscribe(self, base='/{dev}/demods/*/sample', src='main'):
        base = self._conv_command(base)
        src, pre = self._select_src(src)
        sub = getattr(src, 'subscribe')
        sub(base)
    def _unsubscribe(self, base='/{dev}/demods/*/sample', src='main'):
        base = self._conv_command(base)
        src, pre = self._select_src(src)
        unsub = getattr(src, 'unsubscribe')
        unsub(base)
    #def echo_dev(self):
    #    """
    #    It is suppose to wait until all buffers are flushed.
    #    """
    #    self._zi_daq.echoDevice(self._zi_dev)
    def flush(self):
        """
        Flush data in socket connection and API buffers.
        Use between subscribe and poll.
        """
        self._zi_daq.flush()
    def _flat_dict(self, in_dict, root=True):
        """
        this converts the get(str,False) or get for
        other than main object in a flat dict
        i.e.
          {'a':{'0':{'c':4, 'd':5}}}
            into
          {'/a/0/c':4, '/a/0/d':5} if root is True
          {'a/0/c':4, 'a/0/d':5}   if root is False
        """
        sep = self._zi_sep
        pre = ''
        if root:
            pre = sep
        out_dict = {}
        for k,v in in_dict.iteritems():
            if isinstance(v, dict):
                v = self._flat_dict(v, False)
                for ks, vs in v.iteritems():
                    out_dict[pre+k+sep+ks] = vs
            else:
                out_dict[pre+k] = v
        return out_dict
    @locked_calling
    def read(self, timeout_ms=0):
        """
        read currently available susbscribed data.
        """
        # timeout value of -1 disables it. poll becomes completely blocking
        # with a non negative timeout poll is blocking for the timeout duration
        # poll and pollevent use the timeout in the same way
        #  poll also has a duration.
        #   it seems to repeat pollEvent as long as duration is not finished
        #   so the duration can be rounded up by timeout if no data is available.
        return self._zi_daq.pollEvent(timeout_ms)
    @locked_calling
    def write(self, command, val=None, src='main', t=None, sync=True):
        """
         use like:
             obj.write('/dev2021/sigins/0/on', 1, t='int')
                t can be 'byte', 'double', 'int'
             obj.write([('/dev2021/sigins/0/on', 1), ('/dev2021/sigins/1/on', 0)])
             obj.write('/dev2021/sigins/0/on', 1) # no recommended for device code,
                                                  # but OK on command line
             obj.write('loopcount', 2, src='zoomFFT')
                the 'sweepFFT/' is automatically inserted
        see _select_src for available src
            it only affects t==None
            for src not 'main', the only choice is
            t==None, and to give a single val.
        sync is for 'double' or 'int' and is to use the sync interface

        You can replace /dev2021/ by /{dev}/
        """
        command = self._conv_command(command)
        if t=='byte':
            self._zi_daq.setByte(command, val)
        elif t=='double':
            if sync:
                self._zi_daq.syncSetDouble(command, val)
            else:
                self._zi_daq.setDouble(command, val)
        elif t=='int':
            if sync:
                self._zi_daq.syncSetInt(command, val)
            else:
                self._zi_daq.setInt(command, val)
        elif t==None:
            src, pre = self._select_src(src)
            if pre == '':
                if val == None:
                    src.set(command)
                else:
                    src.set([(command, val)])
            else:
                src.set(pre+'/'+command, val)
        else:
            raise ValueError, 'Invalid value for t=%r'%t
    @locked_calling
    def ask(self, question, src='main', t=None, strip_timestamp=True):
        """
        use like:
            obj.ask('/dev2021/sigins/0/on', t='int')
              t can be 'byte', 'double', 'int', 'sample' or 'dict'
                for demods sample data, only t='sample' works
              In which case only one value can be asked for (not * or partial tree)
              The default is to return the value of the only item
              of the dict, unless there is more than one item,
              then a dict is return
              strip_timestamp when True, checks if entries are dict with
              timestamp and valies and only return the value (make APIlevel=4
              return similar results to APIlevel=1)
            obj.ask('')
            obj.ask('*')
            obj.ask('/dev2021/sigins')
            obj.ask('/{dev}/sigins')
            obj.ask('/dev2021/sig*')
            obj.ask('averaging/tc', src='sweep')
            obj.ask('*', src='sweep')
            obj.ask('/{dev}/demods/0/sample', t='sample')
            obj.ask('/{dev}/dios/0/input', t='dio')
        """
        question = self._conv_command(question)
        if t=='byte':
            return self._zi_daq.getByte(question)
        elif t=='double':
            return self._zi_daq.getDouble(question)
        elif t=='int':
            return self._zi_daq.getInt(question)
        elif t=='sample':
            return self._zi_daq.getSample(question)
        elif t=='dio':
            return self._zi_daq.getDIO(question)
        elif t==None or t=='dict':
            src, pre = self._select_src(src)
            if pre == '':
                #ret = self._flat_dict(src.get(question))
                ret = src.get(question, True) # True makes it flat
                if strip_timestamp:
                    for k,v in ret.items():
                        if isinstance(v, dict) and len(v) == 2 and 'timestamp' in v:
                            ret[k] = v['value']
            else:
                ret = self._flat_dict(src.get(pre+'/'+question), False)
            if t == 'dict' or len(ret) != 1:
                return ret
            return ret.values()[0]
        else:
            raise ValueError, 'Invalid value for t=%r'%t
    def timestamp_to_s(self, timestamp):
        """
        Using a timestamp from the instrument, returns
        the number of seconds since the instrument turn on.
        """
        # Starting in 14.08, officially documented as the counter of the 1.8 GHz clock
        return timestamp/self.clockbase.getcache()
    def sync(self):
        """ Performs a synchronization. All data read after this point use
            the previously set values.
        """
        self._zi_daq.sync()
    def idn(self):
        name = 'Zurich Instrument'
        python_ver, python_rev = _get_zi_python_version(self._zi_daq)
        python_rev = str(python_rev)
        server_ver = self.ask('/zi/about/version')[0]
        #server_rev = self.ask('/zi/about/revision')[0]
        server_rev = self.ask('/zi/about/revision', t='int')
        server_fw_rev = str(self.ask('/zi/about/fwrevision')[0])
        system_devtype = self.ask('/{dev}/features/devtype')[0]
        system_serial = self.ask('/{dev}/features/serial')[0]
        #system_code = self.ask('/{dev}/features/code')[0] # not available in vs 13.10, in 14.02, 14.08 it returns an empty dict after a long timeout. It is a write only node.
        system_options = self.ask('/{dev}/features/options')[0]
        #system_analog_board_rev = self.ask('/{dev}/system/analogboardrevision')[0]
        #system_digital_board_rev = self.ask('/{dev}/system/digitalboardrevision')[0]
        system_analog_board_rev = self.ask('/{dev}/system/boardrevisions/1')[0] # To match web interface, 1=analog, 0=digital
        system_digital_board_rev = self.ask('/{dev}/system/boardrevisions/0')[0]
        system_fpga_rev = str(self.ask('/{dev}/system/fpgarevision')[0])
        system_fw_rev = str(self.ask('/{dev}/system/fwrevision')[0])
        system_fx2_usb = self.ask('/{dev}/system/fx2revision')[0]
        #return '{name} {system_devtype} #{system_serial} (analog/digital/fpga/fw_rev:{system_analog_board_rev}/{system_digital_board_rev}/{system_fpga_rev}/{system_fw_rev}, code:{system_code}, opt:{system_options}  [server {server_ver}-{server_rev} fw:{server_fw_rev}] [python {python_ver}-{python_rev}])'.format(
        return '{name},{system_devtype},{system_serial},(analog/digital/fpga/fw_rev/fx2_usb:{system_analog_board_rev}/{system_digital_board_rev}/{system_fpga_rev}/{system_fw_rev}, opt:{system_options}  [server {server_ver}-{server_rev} fw:{server_fw_rev}] [python {python_ver}-{python_rev}])'.format(
             name=name, python_ver=python_ver, python_rev=python_rev,
             server_ver=server_ver, server_rev=server_rev, server_fw_rev=server_fw_rev,
             system_devtype=system_devtype, system_serial=system_serial,
             #system_code=system_code,
             system_options=system_options,
             system_analog_board_rev=system_analog_board_rev, system_digital_board_rev=system_digital_board_rev,
             system_fpga_rev=system_fpga_rev, system_fw_rev=system_fw_rev, system_fx2_usb=system_fx2_usb)

    def find_all_active_channels(self):
        current_ch = self.current_demod.getcache()
        channels_en = []
        for ch in range(8):
            if self.demod_en.get(ch=ch):
                channels_en.append(ch)
        self.current_demod.set(current_ch)
        return channels_en
    def _fetch_ch_helper(self, ch):
        if ch==None:
            ch = self.find_all_active_channels()
        if not isinstance(ch, (list)):
            ch = [ch]
        return ch
    def _fetch_getformat(self, **kwarg):
        if self._current_mode == 'lia':
            ch = kwarg.get('ch', None)
            ch = self._fetch_ch_helper(ch)
            vals = kwarg.get('vals', ['x', 'y'])
            multi = []
            for c in ch:
                for v in vals:
                    multi.append('ch%i_%s'%(c,v))
            fmt = self.fetch._format
            fmt.update(multi=multi)
        elif self._current_mode == 'sweep':
            ch = kwarg.get('ch', None)
            ch = self._fetch_ch_helper(ch)
            xaxis = kwarg.get('xaxis', True)
            vals = kwarg.get('vals', ['x', 'y'])
            multi = []
            if xaxis:
                multi = ['grid']
            for c in ch:
                for v in vals:
                    multi.append('ch%i_%s'%(c,v))
            multi = tuple(multi)
            fmt = self.fetch._format
            fmt.update(multi=multi)
        else:
            pass
        return BaseDevice.getformat(self.fetch, **kwarg)
    def _fetch_pick_help(self, d, vals):
        ret = []
        for v in vals:
            x = d['x'][0]
            y = d['y'][0]
            z = x + 1j*y
            if v == 'r':
                ret.append(np.abs(z))
            elif v == 'deg':
                ret.append(np.angle(z, deg=True))
            else:
                ret.append(d[v][0])
        return ret
    def _fetch_getdev(self, ch=None, xaxis=True, raw=False, vals=None):
        """
           Options available: ch, xaxis
            -ch:    a single value or a list of values for the channels to capture
                    a value of None(default) selects all the active ones from 0-7.
                    in sweep mode this does nothing
            -xaxis: Set to True (default) to return the grid value (sweep control, often frequency)
                    as the first column (it is the value it wants, not necessarily the one used)
                    If you really want the measured frequency, add it to vals
                    in sweep mode (it is not necessarily the sweep variable)
            -vals:  is a list of strings of elements to return.
                    The strings can be 'auxin0', 'auxin1', 'dio', 'frequency'
                    'phase', 'timestamp', 'trigger', 'x', 'y'
                    'r', 'deg' for lia mode. Defauts to ['x', 'y']
                       Note that 'phase' is not the angle from x,y (use deg for that)
                       but instead is the phase of the ref at the point in time
                    For sweep mode defaults to ['x', 'y', 'r' ,'phase'] and the available strings are:
                      'auxin0', 'auxin0pwr', 'auxin0stddev',
                      'auxin1', 'auxin1pwr', 'auxin1stddev',
                      'bandwidth', 'tc', 'tcmeas', 'grid',
                      'settimestamp', 'nexttimestamp', 'settling',
                      'frequency',  'frequencypwr', 'frequencystddev',
                      'x', 'xpwr', 'xstddev',
                      'y', 'ypwr', 'ystddev',
                      'r', 'rpwr', 'rstddev',
                      'phase', 'phasepwr', 'phasestddev',
                    where endings for any of x, y, r, phase, auxin0/1, frequency
                     the base name, here x, is the avg: sum_i x_i/N
                                         xp           : sum_i (x_i**2)/N
                                         xstddev      : sqrt((1/(N-1)) sum_i (x_i - x)**2)
                                         xstddev is nan if count < 2.
                                           N is the average count number
                                         so xstddev = sqrt(xpwr - x**2) * sqrt(N/(N-1))
                     r and phase are as above but using r_i = abs(x_i + 1j y_i)
                                                    phase_i = angle(x_i + 1j y_i)
                    grid are the sweep points requested.
                    settimestamp, nexttimestamp are respectivelly the timestamps (in s)
                      of the set and of the first read.
                    settling  (=nexttimestamp-settimestamp)
                    bandwidth is the enbw (related to tc)
                      to obtain the actually used bandwith: bandwidth*tc/tcmeas
                    tc is calculated tc
                    tcmeas is the tc actually used (due to rounding)
        """
        # the demod sample phase is related to timestamp, the following should return almost a constant
        #    I get the constant to vary over 8e-5
        #    From Juerg email of Jul 18, 2014, this is because:
        #     "the number of bits transferred for the oscillator phase (16bit) is low."
        #     frequency is a 48 bit value. The oscillator phase is only useful for syncronisation
        # z=get(zi.demod_data); tzo = z['timestamp']
        # while True:
        #    z=get(zi.demod_data); t=zi.timestamp_to_s(z['timestamp']-tzo)
        #    print ((2*pi*t*z['frequency'] - z['phase'] + 2*pi)%(2*pi))[0]
        #For sweep mode there is also a timestamp value. It is a single value and represents
        # the end in raw clock ticks: 1.8 GHz
        # with multiple enable channel, one of the timestamp is the same as the last nexttimestamp
        #  (the last channel)
        #  the others are probably the same as the last measured value:
        #                  last next + (set_(i+1) - next_i)
        #  with only a single channel, it is the last nexttimestamp
        if self._current_mode == 'lia':
            if vals is None:
                vals = ['x', 'y']
            channels = self._fetch_ch_helper(ch)
            current_ch = self.current_demod.getcache()
            ret = []
            for ch in channels:
                d = self.demod_data.get(ch=ch)
                ret.append(self._fetch_pick_help(d, vals))
            self.current_demod.set(current_ch)
        elif self._current_mode == 'sweep':
            # Lets assume we selected all enabled channels, or selected a particular one
            # Does not currently handle the sweep subs option
            channels = self._fetch_ch_helper(ch)
            if vals is None:
                vals = ['x', 'y']
            data = self.sweep_data()
            ret = []
            multi_data = False
            xaxis_differ = False
            for ch in channels:
                name = self._conv_command('/{dev}/demods/%i/sample'%ch)
                try:
                    d = data[name]
                except KeyError:
                    raise RuntimeError("Selected data is not available (can't use fetch with sweep): %s"%name)
                if len(d) > 1 and not multi_data:
                    print 'More than one sweep data set, using the latest one only'
                    multi_data = True
                d = d[-1]
                if len(d) != 1:
                    raise RuntimeError('Second dimension size of data set is invalid.')
                d = d[0]
                x = d['grid']
                if ret == [] and xaxis:
                    main_x =x
                    ret.append(x)
                if not xaxis_differ and xaxis and np.any(np.abs((x-main_x)/x) > 1e-8):
                    #print np.abs((x-main_x)/x)
                    print 'Not all x-axis are the same, returned only the first one'
                    xaxis_differ = True
                for v in vals:
                    ret.append(d[v])
        else:
            raise RuntimeError('invalid mode selected. Should be lia or sweep.')
        ret = np.asarray(ret)
        if ret.shape[0]==1:
            ret=ret[0]
        return ret
    def _create_devs(self):
        self.clockbase = ziDev(getstr='clockbase', str_type=float)
        self.fpga_core_temp = ziDev(getstr='stats/physical/fpga/temp', str_type=float)
        self.calib_required = ziDev(getstr='system/calib/required', str_type=bool)
        #self.mac_addr = ziDev('system/nics/0/mac/{rpt_i}', input_repeat=range(6), str_type=int)
        self.mac_addr = ziDev('system/nics/0/mac')
        self.current_demod = MemoryDevice(0, choices=range(8))
        self.current_osc = MemoryDevice(0, choices=range(2))
        self.current_sigins = MemoryDevice(0, choices=range(2))
        self.current_sigouts = MemoryDevice(0, choices=range(2))
        def ziDev_ch_gen(ch, *arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            options.update(ch=ch)
            app = kwarg.pop('options_apply', ['ch'])
            options_conv = kwarg.pop('options_conv', {}).copy()
            options_conv.update(ch=lambda base_val, conv_val: base_val)
            kwarg.update(options=options, options_apply=app, options_conv=options_conv)
            return ziDev(*arg, **kwarg)
        ziDev_ch_demod = lambda *arg, **kwarg: ziDev_ch_gen(self.current_demod, *arg, **kwarg)
        ziDev_ch_osc = lambda *arg, **kwarg: ziDev_ch_gen(self.current_osc, *arg, **kwarg)
        ziDev_ch_sigins = lambda *arg, **kwarg: ziDev_ch_gen(self.current_sigins, *arg, **kwarg)
        ziDev_ch_sigouts = lambda *arg, **kwarg: ziDev_ch_gen(self.current_sigouts, *arg, **kwarg)
        self.demod_freq = ziDev_ch_demod(getstr='demods/{ch}/freq', str_type=float)
        self.demod_harm = ziDev_ch_demod('demods/{ch}/harmonic', str_type=int)
        self.demod_en = ziDev_ch_demod('demods/{ch}/enable', str_type=bool)
        # demod_sinc_en did not do anything before 14.08. In 14.02 in made UHF crash. Now it works
        self.demod_sinc_en = ziDev_ch_demod('demods/{ch}/sinc', str_type=bool)
        self.demod_bypass_en = ziDev_ch_demod('demods/{ch}/bypass', str_type=bool, doc="Don't know what this does.")
        self.demod_osc_src = ziDev_ch_demod(getstr='demods/{ch}/oscselect', str_type=int, choices=[0,1])
        self.demod_adc_src = ziDev_ch_demod('demods/{ch}/adcselect', str_type=int, choices=range(13))
        self.demod_rate = ziDev_ch_demod('demods/{ch}/rate', str_type=float, setget=True, doc="""
            The rate are power of 2 fractions of the base sampling rate.
            With the base of 1.8 GS/s, the web interface has a max rate of
              1.8e9/2**7 = 14.1 MS/s
            and a min rate of
              1.8e9/2**30 = 1.68 S/s
            The recommended rate is 7-10 higher rate than filter bandwidth for
            sufficient antialiasing suppression.
        """)
        self.demod_tc = ziDev_ch_demod('demods/{ch}/timeconstant', str_type=float, setget=True)
        self.demod_order = ziDev_ch_demod('demods/{ch}/order', str_type=int, choices=range(1,9))
        self.demod_phase = ziDev_ch_demod('demods/{ch}/phaseshift', str_type=float, setget=True)
        self.demod_trigger = ziDev_ch_demod('demods/{ch}/trigger', str_type=int)
        self.demod_data = ziDev_ch_demod(getstr='demods/{ch}/sample', input_type='sample', doc='It will wait for the next available samples (depends on rate). X and Y are in RMS')
        self.osc_freq = ziDev_ch_osc('oscs/{ch}/freq', str_type=float, setget=True)
        # TODO figure out what sigins/{ch}/bw does
        self.sigins_ac_en = ziDev_ch_sigins('sigins/{ch}/ac', str_type=bool)
        self.sigins_50ohm_en = ziDev_ch_sigins('sigins/{ch}/imp50', str_type=bool)
        self.sigins_en = ziDev_ch_sigins('sigins/{ch}/on', str_type=bool)
        range_lst = np.concatenate( (np.linspace(0.01, .1, 10), np.linspace(0.2, 1.5, 14)))
        range_lst = [float(v) for v in np.around(range_lst, 3)]
        self.sigins_range = ziDev_ch_sigins('sigins/{ch}/range', str_type=float, setget=True, choices=range_lst, doc='The voltage range amplitude A (the input needs to be between -A and +A. There is a attenuator for A<= 0.1')
        self.sigouts_en = ziDev_ch_sigouts('sigouts/{ch}/on', str_type=bool)
        self.sigouts_offset = ziDev_ch_sigouts('sigouts/{ch}/offset', str_type=float, setget=True)
        self.sigouts_range = ziDev_ch_sigouts('sigouts/{ch}/range', str_type=float, setget=True, choices=[0.15, 1.5])
        self.sigouts_autorange_en = ziDev_ch_sigouts('sigouts/{ch}/autorange', str_type=bool)
        self.sigouts_output_clipped = ziDev_ch_sigouts(getstr='sigouts/{ch}/over', str_type=bool)
        # There is also 1/amplitudes/7, 0/enables/3, 1/enables/7,
        #     (syncfallings/3 and /7, syncrisings/3 and /7 have been removed in 14.08)
        #   Without the multi-frequency (MF) option signal output 1 (2) is connected to demod3 (7) see Juerg 22012014
        # Here I implement a general way to select sigouts ch and the demod ch.
        # However, since on my system U don't have multi-frequency, I make the demod parameter invisible (using _demod)
        # and I override the value so ch=0 gives demod 3 and ch=1 gives demod 7, always.
        # Because of the override, current_sigouts_demod is not kept up to date, however that values
        # ends up never to be used.
        # To later implement multi-frequency should mostly invovle removing the override
        # making demod visible (remove _) and adjusting out_demod
        out_demod = ChoiceDevDep(self.current_sigouts, {0:[3], 1:[7]})
        self.current_sigouts_demod = MemoryDevice(3, choices=out_demod)
        # using _demod make it invisible in help
        def ziDev_ch_demod_sigouts(*arg, **kwarg):
            options = kwarg.pop('options', {}).copy()
            #options.update(_demod=self.current_sigouts_demod)
            options.update(_demod=self.current_sigouts_demod)
            app = kwarg.pop('options_apply', ['ch', '_demod'])
            options_conv = kwarg.pop('options_conv', {}).copy()
            def demod_override(base_val, conv_val):
                index = self.current_sigouts.getcache()
                return [3, 7][index]
            options_conv.update(_demod=demod_override)
            options_lim = kwarg.pop('options_lim', {}).copy()
            # We need to prevent the use of the device check until the apply because
            # otherwise it will be checked before ch is changed (on which it depends)
            options_lim.update(_demod=(0,7)) #This prevents the use of the device check until the apply
            kwarg.update(options=options, options_apply=app, options_conv=options_conv, options_lim=options_lim)
            return ziDev_ch_sigouts(*arg, **kwarg)
        self.sigouts_ampl_Vp = ziDev_ch_demod_sigouts(getstr='sigouts/{ch}/amplitudes/{_demod}', str_type=float, doc='Amplitude A of sin wave (it goes from -A to +A without an offset')
        self.sigouts_50ohm_en = ziDev_ch_sigins('sigouts/{ch}/imp50', str_type=bool)
        # TODO: triggers, SYSTEM(/EXTCLK), EXTREFS, status stats
        #       conn, inputpwas, outputpwas
        #       auxins/0/sample, auxins/0/averaging
        #       auxouts/0-4, dios/0, scopes/0

        self.sweep_device = ziDev('device', str_type=str, input_src='sweep')
        self.sweep_x_start = ziDev('start', str_type=float, input_src='sweep')
        self.sweep_x_stop = ziDev('stop', str_type=float, input_src='sweep')
        self.sweep_x_count = ziDev('samplecount', str_type=int, input_src='sweep')
        self.sweep_x_src_node = ziDev('gridnode', str_type=str, input_src='sweep')
        self.sweep_x_log = ziDev('xmapping', str_type=bool, input_src='sweep')
        self.sweep_loop_count = ziDev('loopcount', str_type=int, input_src='sweep')
        self.sweep_endless_loop_en = ziDev('endless', str_type=bool, input_src='sweep')
        auto_bw_ch = ChoiceIndex(['manual', 'fixed', 'auto'])
        self.sweep_auto_bw_mode = ziDev('bandwidthcontrol', choices=auto_bw_ch, input_src='sweep')
        #self.sweep_auto_bw_en = ziDev('bandwidthcontrol', str_type=bool, input_src='sweep')
        self.sweep_auto_bw_fixed = ziDev('bandwidth', str_type=float, input_src='sweep', min=1e-6)
        self.sweep_max_bw = ziDev('maxbandwidth', str_type=float, input_src='sweep')
        self.sweep_omega_suppression_db = ziDev('omegasuppression', str_type=float, input_src='sweep', min=0)
        self.sweep_order = ziDev('order', str_type=int, input_src='sweep', min=1, max=8)
        self.sweep_sinc_en = ziDev('sincfilter', str_type=bool, input_src='sweep', doc='When True, sinc will be used when f<50 Hz')
        self.sweep_settling_time_s = ziDev('settling/time', str_type=float, input_src='sweep')
        self.sweep_settling_n_tc = ziDev('settling/tc', str_type=float, input_src='sweep')
        self.sweep_settling_inaccuracy = ziDev('settling/inaccuracy', str_type=float, input_src='sweep')
        self.sweep_averaging_count = ziDev('averaging/sample', str_type=int, input_src='sweep')
        #self.sweep_averaging_n_tc = ziDev('averaging/tc', str_type=float, choices=[0, 5, 15, 50], input_src='sweep')
        self.sweep_averaging_n_tc = ziDev('averaging/tc', str_type=float, input_src='sweep')
        sweep_mode_ch = ChoiceIndex(['sequential', 'binary', 'bidirectional', 'reverse'])
        self.sweep_mode = ziDev('scan', choices=sweep_mode_ch, input_src='sweep')

        self.sweep_phase_unwrap_en = ziDev('phaseunwrap', str_type=bool, input_src='sweep')
# sweeper structure
#  sweep/fileformat
#  sweep/filename
#  sweep/historylength
#  sweep/savepath

        self._devwrap('fetch', autoinit=False, trig=True)
        self.readval = ReadvalDev(self.fetch)
        self.alias = self.readval

        tc_to_bw = ProxyMethod(self._tc_to_enbw_3dB)
        func1 = lambda v: tc_to_bw(v, enbw=False)
        self.demod_bw3db = FunctionDevice(self.demod_tc, func1, func1)
        func2 = lambda v: tc_to_bw(v)
        self.demod_enbw = FunctionDevice(self.demod_tc, func2, func2)

        # This needs to be last to complete creation
        super(zurich_UHF, self)._create_devs()
    def clear_history(self, src='sweep'):
        """
        empties the read buffer (the next read will be empty).
        also, during a sweep, it restarts all loops.
        """
        self.write('clearhistory', 1, src=src)
    def sweep_progress(self):
        return self._zi_sweep.progress()
    def is_sweep_finished(self):
        if self._zi_sweep.finished() and self.sweep_progress() == 1.:
            return True
        return False
    def sweep_start(self):
        self._zi_sweep.execute()
    def sweep_stop(self):
        self._zi_sweep.finish()
    @locked_calling
    def _async_trig(self):
        super(zurich_UHF, self)._async_trig()
        if self._async_mode == 'sweep':
            self.sweep_start()
    def _async_select(self, devs=[]):
        if self._current_mode == 'sweep':
            self._async_mode = 'sweep'
        else: # lia
            self._async_mode = 'wait'
    def _async_detect(self, max_time=.5):
        if self._current_mode == 'sweep':
            return _retry_wait(self.is_sweep_finished, max_time, delay=0.05)
        else:
            return super(zurich_UHF, self)._async_detect(max_time)
    def sweep_data(self):
        """ Call after running a sweep """
        return self._flat_dict(self._zi_sweep.read())
    def set_lia_mode(self):
        """
        Goes to LIA mode.
        see also set_sweep_mode
        """
        self._current_mode = 'lia'
        self._async_select()
# The bw calculation has changed in 14.08. Before that it was:
#        The following discussion is valid for version 14.02
#               for auto the computed bandwidth (the one asked for, but the instruments rounds it
#               to another value) is the equivalent noise bandwidth and is:
#                   min(df/2,  f/100**(1/n))
#                     where n is order,
#                     f is frequency, and df[1:] = diff(f), df[0]=df[1]
#                   It is also bounded by the max and min available bandwidth (time constants)
#                    available for the order (min tc=1.026e-7, max tc=76.35)
#                   The reason for df/2 is to have independent points,
#                   The reason for f/100*(1/n) is to kill the harmonics in a similar way.
#                     The H harmonic is attenuated for order n by ~100*(H*Kn)**n,
#                      where Kn is 2*pi*ENBW(tau=1, order=n)
#                      hence the attenuation for the 2nd harmonic is
#                        ~314 for order 1,  ~247 for 2, ~164 for 3, ..., =31.5 for 8 (no approximation, approx gave 3)
#                           the formula for no approximation is sqrt(1 + (F)**2)**n
#                            with F = 100**(1./n) * (H*Kn)
#                   Enabling sync does not seem to change anything (crashes in 14.02)
    def set_sweep_mode(self, start, stop, count, logsweep=False, src='oscs/0/freq', subs='all',
                       bw='auto', loop_count=1, mode='sequential',
                       avg_count=1, avg_n_tc=0, settle_time_s=0, settle_n_tc=15,
                       order=4, sinc=False, max_bw=1.25e6, w_suppr=40.):
        """
        bw can be a value (fixed mode), 'auto' or None (uses the currently set timeconstant)
           The following discussion is valid for version 14.08
           for auto the computed bandwidth (the one asked for, but the instruments rounds it
           to another value) is the equivalent noise bandwidth and is:
               min( df/2,  f/sqrt(atten**(2/n)-1)*Kn, max_bw )
                 where n is order, atten = 10**(w_suppr/20.)
                 Kn is 2*pi*ENBW(tc=1, order=n)
                     ENBW = _tc_to_enbw_3dB
                 f is frequency, and df[1:] = diff(f), df[0]=df[1]
               It is also bounded by the max and min available bandwidth (time constants)
                available for the order (min tc=1.026e-7, max tc=76.35)
               The reason for df/2 is to have independent points.
               The reason for the other term is to kill the first harmonic by at least w_suppr dB.
                 The H harmonic is attenuated for order n by ~ atten*(H**n),
               With sinc enabled, frequencies below 50 Hz will use the frequency as the bandwidth
        max_bw: Maximum enbw to use when bw is 'auto'
        mode is 'sequential', 'binary', 'bidirectional', or 'reverse'
          Note that 1 loopcount of bidirectionnal includes twice the count
          of points (the up and down sweep together)
        subs is the list of demods channels to subscribe to
        loop_count <= 0 turns on endless mode (infinite count, need to use finish to stop)
        subs is a list of demods channel number to subscribe to (to record in the sweep result)
              or it is 'all' to record all active channels.
              Channels are active if they are enabled and the data rate is not 0.
              If no channels are active, the sweep will not progress, it will stall.
              If an active channel is subscribed to, deactivating without changing the
              subscription will hang the sweep.
        order: is the filter order when bw is fixed or 'auto'
        w_suppr: is omega suppression in dB used for bw='auto'
        sinc: sets the filter sinc, when bw is fixed or 'auto'
        The total settling time in seconds is max(settle_time_s, settle_n_tc*timeconstant_s)
        where timeconstant_s is the timeconstant in seconds for each frequency (can change with bw='auto').
        The total averaging time in seconds is max(avg_count/rate, avg_n_tc*timeconstant_s, 1/rate).
        (a minimum of 1 sample)
        where rate is the demod rate for that channel.
        In between points of the sweep, there can be an additiontion ~60 ms delay.

        The usual parameter for the web interface:
              they all use bw='auto', settle_time_s=0
            parameter/high: settle_n_tc=15, avg_count=1, avg_n_tc=0
            parameter/low : settle_n_tc=5,  avg_count=1, avg_n_tc=0
            avg param/high: settle_n_tc=15, avg_count=1000, avg_n_tc=15
            avg param/low : settle_n_tc=5,  avg_count=100,  avg_n_tc=5
            noise/high:     settle_n_tc=50, avg_count=1000, avg_n_tc=50
            noise/low :     settle_n_tc=15, avg_count=100,  avg_n_tc=15
        """
        # sweep/bandwidthcontrol = 0 is still enabled if sweep/bandwidth=0
        self.sweep_device.set(self._zi_dev)
        self.sweep_x_start.set(start)
        self.sweep_x_stop.set(stop)
        self.sweep_x_count.set(count)
        self.sweep_x_src_node.set(src)
        self.sweep_x_log.set(logsweep)
        # Need to set order first, otherwise the time constant is not
        # set properly
        self.sweep_order.set(order)
        sleep(0.1) # This seems to be needed to make sure order is set before we change
                   # the fix frequency
        # In version 14.02, whenever sweep_auto_bw_fixed is 0.
        # It goes in auto mode. This is the same
        # behavior as before. 14.02 added auto has bw_mode=2
        # which is auto irrespective of sweep_auto_bw_fixed value.
        # The old behavior was not change to keep backwards compatibility (Juerg 23062014)
        #  Documentations errors should be fixed (done in 14.08)
        if bw == None:
            self.sweep_auto_bw_mode.set('manual')
            if self.sweep_auto_bw_fixed.getcache()<=0:
                self.sweep_auto_bw_fixed.set(1)
        elif bw == 'auto':
            self.sweep_auto_bw_mode.set('auto')
        else:
            self.sweep_auto_bw_mode.set('fixed')
            # bw needs to be >0 (checked in device). =0 means auto in 14.02
            self.sweep_auto_bw_fixed.set(bw)
        if loop_count <= 0:
            self.sweep_endless_loop_en.set(True)
        else:
            self.sweep_endless_loop_en.set(False)
            self.sweep_loop_count.set(loop_count)
        self.sweep_x_log.set(logsweep)
        self.sweep_mode.set(mode)
        self.sweep_sinc_en.set(sinc)
        self.sweep_max_bw.set(max_bw)
        self.sweep_omega_suppression_db.set(w_suppr)
        self.sweep_averaging_count.set(avg_count)
        self.sweep_averaging_n_tc.set(avg_n_tc)
        self.sweep_settling_time_s.set(settle_time_s)
        self.sweep_settling_n_tc.set(settle_n_tc)
        for i in range(8):
            # This will remove multiple subscribes to a particular channel
            self._unsubscribe('/{dev}/demods/%i/sample'%i, src='sweep')
        # This removes subscribes to * (it is not removed by above iteration)
        self._unsubscribe('/{dev}/demods/*/sample', src='sweep')
        if subs == 'all':
            self._subscribe('/{dev}/demods/*/sample', src='sweep')
        else:
            if not isinstance(subs, (list, tuple, np.ndarray)):
                subs = [subs]
            for i in subs:
                self._subscribe('/{dev}/demods/%i/sample'%i, src='sweep')
        self._current_mode = 'sweep'
        self._async_select()

# In the result data set:
#   available: auxin0, auxin0pwr, auxin0stddev
#              auxin1, auxin1pwr, auxin1stddev
#              bandwidth, tc (for auto they are the computed ones, the ones set to, the used one are truncated)
#              tcmeas
#              frequency, frequencypwr, frequencystddev
#              grid
#              nexttimestamp, settimestamp (both in s, timestamps of set and first read)
#              settling  (=nexttimestamp-settimestamp)
#              timestamp (single value, in raw clock ticks: 1.8 GHz)
#              r, rpwr, rstddev
#              phase, phasepwr, phasestddev
#              x, xpwr, xstddev
#              y, ypwr, ystddev
# All points are in order of start-stop, even for binary.
#  however
# bandwidth is enbw (related to tc)
#  for the various stddev to not be nan, you need avg count>1 (>2 only for 14.02)
#    for i the iterations of N averages
#   base(avg): sum_i x_i/N
#   pwr: sum_i (x_i**2)/N
#   stddev: sqrt((1/(N-1)) sum_i (x_i - base)**2)  # N-1 since version 14.02, was N before
#    so stddev = sqrt(pwr - base**2) * sqrt(N/(N-1))
#  The r, rpwr and rstddev are calculated from r_i = sqrt(x_i**2 + y_i**2)
#    not from x, xpwr and xstddev



# Problems discovered:
#  get('*') is slow and does not return sample data (because it is slow?, uses polling)
#    As of version 14.02 it is fast
#  get of subdevices does not work like get of main device (not option to flatten)
#   should be changed in next version (Juerg 23062014)
#   fixed in 14.08
# Documentation is much improved in version 14.02
#     pwrtemps was temps before version 14.02
#  timeit zi.ask('/{dev}/stats/physical/digitalboard/pwrtemps/0', t='int')
#    for 14.08 use this instead
#  timeit zi.ask('/{dev}/stats/physical/temperatures/0', t='int')
#  100 loops, best of 3: 2.55 ms per loop
#  100 loops, best of 3: 5.36 ms per loop  # version 14.02 using USB
#  100 loops, best of 3: 5.75 ms per loop  # version 14.08 using USB
# timeit zi.ask('/{dev}/stats/physical/digitalboard/pwrtemps/0')
#  timeit zi.ask('/{dev}/stats/physical/temperatures/0')
#   10 loops, best of 3: 250 ms per loop (for 13.06 and 100 ms for 13.10)
#  100 loops, best of 3: 9.31 ms per loop  # version 14.02 using USB
#  100 loops, best of 3: 12.5 ms per loop  # version 14.08 using USB
# This is because it uses get_as_poll
#  some are faster like '/zi' or '/{dev}/stats/cmdstream'
#  as of 14.02 that is no longer the case.
#   a bunch of values are not obtainable with get subbranches or *
# ll = zi.list_nodes()
# llso = zi.list_nodes(settings_only=True)
# vv=zi.ask('')
# sorted([ k for k in vv if k not in ll]) # nodes in get('') but not in list_nodes. This is an empty list.
# sorted([ k for k in vv if k not in llso]) # nodes in get('') but not in setting only list_nodes. This is an empty list.
# sorted([ k for k in llso if k not in vv]) # setting only nodes not in get(''). this is an empty list.
# sorted([ k for k in ll if k not in vv]) # nodes not in get('')
# sorted([ k for k in ll if k not in llso]) # nodes that are not settings only (they are stream, read only), same as above
#   there are many: /zi/about /zi/clockbase /zi/devices
#                   {dev}/*/*/sample
#                   {dev}/aucarts/*/value
#                   {dev}/aupolars/*/value
#                   {dev}/auxouts/*/value
#                   {dev}/clockbase
#                   {dev}/demods/0/freq
#                   {dev}/dios/0/input
#                   {dev}/extrefs/*/adcselect
#                   {dev}/features/*
#                   {dev}/inputpwas/*/wave
#                   {dev}/outputpwas/*/wave
#                   {dev}/scopes/0/trigforce
#                   {dev}/scopes/0/wave
#                   {dev}/sigouts/*/over
#                   {dev}/stats
#                   {dev}/status
#                   {dev}/system everything except:
#                       sorted([k for k in vv if k.startswith('/dev2021/system')])
#                      {dev}/system/calib/auto
#                      {dev}/system/calib/tempthreshold
#                      {dev}/system/calib/timeinterval
#                      {dev}/system/extclk
#                      {dev}/system/preampenable
#                      {dev}/system/xenpakenable
#
# nodes not identified as settings only (and maybe should): {dev}/system/
#                         jumbo
#                         nics ...
#                         porttcp portudp
#  These might be more properly documented in next version (Juerg 23062014)
#     14.08: no change

# instruments_ZI = instruments.zurich
# za=instruments_ZI.ziAPI()
def _time_poll(za):
    import time
    s = '/dev2021/demods/0/sinc'
    to=time.time()
    za.get_as_poll('/dev2021/demods/0/sinc')
    done = False
    n = 0
    while not done:
        n += 1
        r=za.poll(1000)
        if r['path'].lower() == s:
            done = True
    return time.time()-to,n,r
# za.poll() # first empty the poll buffer
# timeit instruments_ZI._time_poll(za)
# timeit print instruments_ZI._time_poll(za)
#  This is always 100 ms (version 13.10). For version 14.02 it is now ~6 ms, version 14.08 it is 6.9 ms
#  When subscribing to something like
#    /dev2021/demods/0/sample at 1.717 kS/s  (timeit za.poll()  returns ~25 ms)
#             in version 14.02 timeit za.poll(100)  returns ~ 16ms
#             in version 14.08 timeit za.poll(100)  returns ~ 18ms
#  polls will return more quickly but with the information from /dev2021/demods/0/sample multiples times
#  between the /dev2021/demods/0/sinc ones
#
#  tests: (These are unchanged for 14.02)
# set(zi.demod_en,True, ch=0); set(zi.demod_rate,13.41); set(zi.demod_order,3); set(zi.demod_enbw,1.)
#   get(zi.demod_tc) # 0.0938 s (1.00 enbw, 0.865 3dB bw)
#   first test settling time/average time is maximum of both n_tc and time
# In 14.08 this test is no longer possible as is because settle_n_tc is forced to 1 has minimum
#   There also seem to be a longer overhead. 14.08 also incorrectly calculates the bandwidth
#     when calling set_sweep_mode successively with different order
#  But documentation now specifies that it is the maximum of both times.
# zi.set_sweep_mode(10e3,10e4,10, bw=1, settle_time_s=0, settle_n_tc=0, avg_count=1, order=3)
# timeit zi.run_and_wait() # 1.78s,  14.08 gives 7.89 s
# zi.set_sweep_mode(10e3,10e4,10, bw=1, settle_time_s=1, settle_n_tc=0, avg_count=1, order=3)
# timeit zi.run_and_wait() # 11.5s,  14.08 gives 15.4
# zi.set_sweep_mode(10e3,10e4,10, bw=1, settle_time_s=0, settle_n_tc=5, avg_count=1, order=3)
# timeit zi.run_and_wait() # 6.25s,  14.08 gives 13.9
# zi.set_sweep_mode(10e3,10e4,10, bw=1, settle_time_s=0, settle_n_tc=0, avg_count=13, order=3)
# timeit zi.run_and_wait() # 10.8s,  14.08 gives 17.6
# zi.set_sweep_mode(10e3,10e4,10, bw=1, settle_time_s=0, settle_n_tc=0, avg_count=0, avg_n_tc=5, order=3)
# timeit zi.run_and_wait() # 5.59s,  14.08 gives 11.6
#
# set(zi.demod_rate, 1.717e3)
#  test the calculations for stddev
# zi.set_sweep_mode(10e3,10e4,10, bw=1, settle_time_s=0, settle_n_tc=0, avg_count=2, order=3)
# zi.run_and_wait(); r=zi.sweep_data(); rr=r['/dev2021/demods/0/sample'][0][0]
# sqrt(rr['ypwr']-rr['y']**2)/rr['ystddev'] # should be all 1.
#   Version 14.02 is now unbiased so for avg_count=n
# sqrt((rr['ypwr']-rr['y']**2)*n/(n-1.))/rr['ystddev'] # should be all 1.
#   This fails for n=2 because rr['ystddev'] is NaN
#   It should be fixed in next version (Juerg 23062014) and return a real number when n=2
#   Fixed in 14.08
#
#  test auto time constants
def _calc_bw(demod_result_dict, order=3):
    r=demod_result_dict
    f=r['grid']
    df = np.diff(f)
    df = np.append(df[0], df)
    k = 100.**(1./order)
    m =np.array([df/2, f/k])
    bw = np.min(m, axis=0)
    return bw
# For 14.08 the bandwidth calculation has changed
def _calc_bw2(f, order=3, w_suppr=40, sinc=False, max_bw=1.25e6):
    atten = 10.**(w_suppr/20.)
    df = np.diff(f)
    df = np.append(df[0], df)
    # atten = (fc/f)**n, f>>fc, fc=1/(2*pi*tc)
    #  we need enbw from fc
    k = np.sqrt(atten**(2./order) - 1.)
    fc = f/k
    enbw = fc * np.sqrt(np.pi)*gamma(order-0.5)/(2*gamma(order))
    m =np.array([df/2, enbw])
    bw = np.min(m, axis=0)
    if sinc:
        # I checked and it is really f<50, not f<=50.
        bw = np.where(f<50, f, bw)
    bw = np.minimum(bw, max_bw)
    return bw
# zi.set_sweep_mode(10e3,10e4,10, bw='auto', settle_time_s=0, settle_n_tc=0, avg_count=1, order=3, w_suppr=40)
# zi.set_sweep_mode(10,1010,10, bw='auto', settle_time_s=0, settle_n_tc=0, avg_count=1, order=3, w_suppr=40)
#  zi.run_and_wait(); r=zi.sweep_data(); rr=r['/dev2021/demods/0/sample'][0][0]
# instruments_ZI._calc_bw(rr)/rr['bandwidth'] # should all be 1
#   for 14.08, use instead
# instruments_ZI._calc_bw2(rr['grid'], order=3, w_suppr=46.)/ rr['bandwidth']
#  repeat with
# zi.set_sweep_mode(10,1010,10, bw='auto', settle_time_s=0, settle_n_tc=0, avg_count=1, logsweep=True, order=3, w_suppr=40)
# ##set(zi.demod_sinc_en,True)  # For 14.02 this makes the instrument crash
# ##zi.set_sweep_mode(10,1010,10, bw='auto', settle_time_s=0, settle_n_tc=0, avg_count=1, order=3, w_suppr=40) # same bandwidth calc but much slower to run
# zi.set_sweep_mode(10,1010,10, bw='auto', settle_time_s=0, settle_n_tc=0, avg_count=1, logsweep=True, sinc=True, order=3, w_suppr=40)
#    sinc filter is not enabled yet (Juerg 23062014):
#      We're currently working on a fix on
#      the firmware. The next step is then support on the sweeper. This is
#      needed as the sinc filter does only support discrete frequency values.
#      The filter itself should be working in the next release. The sweeper
#      support may take longer.
#    Fixed in 14.08
#   instruments_ZI._calc_bw2(rr['grid'], order=3., w_suppr=40, sinc=True)/ rr['bandwidth']
#
# zi.set_sweep_mode(10,1010,10, bw='auto', settle_time_s=0, settle_n_tc=0, avg_count=1, logsweep=True, sinc=True, order=3, w_suppr=40, max_bw=17)
#   instruments_ZI._calc_bw2(rr['grid'], order=3., w_suppr=40, max_bw=17., sinc=True)/ rr['bandwidth']
#
# find all available time constants
def _find_tc(zi, start, stop, skip_start=False, skip_stop=False):
    if skip_start:
        tc_start = start
    else:
        zi.demod_tc.set(start)
        tc_start = zi.demod_tc.getcache()
    #if tc_start<start:
    #    print 'tc<'
    #    return []
    if skip_stop:
        tc_stop = stop
    else:
        zi.demod_tc.set(stop)
        tc_stop = zi.demod_tc.getcache()
    if tc_start == tc_stop:
        print start, stop, (stop-start), tc_start, tc_stop
        return [tc_start]
    df = stop-start
    mid = start+df/2.
    zi.demod_tc.set(mid)
    tc_mid = zi.demod_tc.getcache()
    print start, stop, df, tc_start, tc_mid, tc_stop,
    if tc_start == tc_mid:
        print 'A'
        t1 = [tc_start]
        if skip_start==True and skip_stop==False:
            # previously tc_mid == tc_stop, so no other points in between
            t2 = [tc_stop]
        else:
            t2 = _find_tc(zi, mid, tc_stop, False, True)
    elif tc_mid == tc_stop:
        print 'B'
        if skip_start==False and skip_stop==True:
            # previously tc_mid == tc_start, so no other points in between
            t1 = [tc_start]
        else:
            t1 = _find_tc(zi, tc_start, mid, True, False)
        t2 = [tc_stop]
    else:
        print 'C'
        t1 = _find_tc(zi, tc_start, tc_mid, True, True)
        t2 = _find_tc(zi, tc_mid, tc_stop, True, True)
    if t1[-1] == t2[0]:
        t1 = t1[:-1]
    return t1+t2
#  for demod_order=3
#  array(instruments_ZI._find_tc(zi, 10,2000))
#    returns:  array([  9.5443716 ,  10.90785408,  12.72582912,  15.27099514,  19.08874321, 25.45165825,  38.17748642,  76.35497284])
#  array(instruments_ZI._find_tc(zi, 1e-8, 1.026e-7))
#    returns: array([  1.02592772e-07,   1.02593908e-07,   1.02595038e-07,  1.02596161e-07,   1.02597291e-07,   1.02598420e-07,  1.02599557e-07])
#  for demod_order=1
#  array(instruments_ZI._find_tc(zi, 1e-8, 1.026e-7))
#             array([  2.99000007e-08,   6.00999996e-08,   1.02592772e-07, 1.02593908e-07,   1.02595038e-07,   1.02596161e-07,  1.02597291e-07,   1.02598420e-07,   1.02599557e-07])
#  array(instruments_ZI._find_tc(zi, 10,2000))
#    returns:  array([  9.5443716 ,  10.90785408,  12.72582912,  15.27099514,  19.08874321, 25.45165825,  38.17748642,  76.35497284])
# The above results have not changed for version 14.02
#
# From those observations the time constant is selected as:
#      numerically, the algorithm used is Vo(i+1) = (Vi + (t-1)Voi)/t
#      where t is a number express in dt (the time step for the incoming data, here 1/f = 1/1.8GHz)
#      to be easier to implement numerically (divisions are slow), lets express
#        t as N/n where N is a power of 2 (so division by N can be done with shift operators)
#      then the formula can be reexpressed as
#             Vo(i+1) = (n Vi  + (N-n) Voi)/N
#      Therefore the largest time constant is obtained with n=1
#      The max one of 76.355 s  ==> N=2**37  (N/f=76.355)
#      The top segment of time constants uses N=2**37 and n:1..4095 (4095=2**12-1)
#      After that it uses N=2**25  (N/f = 0.018641351)
# m = 2**37/1.8e9
# v=array(instruments_ZI._find_tc(zi, m/50,m/1)); len(v); m/v  # returns 50 points, numbers from 50 to 1
# v=array(instruments_ZI._find_tc(zi, m/10000,m/4050)); len(v); m/v # returns 50 points, numbers 12288(3*2**12), 8192(2*2**12) and 4097 to 4050
#                                                                   # note that 2**12 = 4096
# m2 = 2**25/1.8e9
# v=array(instruments_ZI._find_tc(zi, m2/50,m2/1)); len(v); m2/v # returns 51 points, numbers from 50 to 1 (there are 2 points around 1)
#   explore second section
# n=14; v=array(instruments_ZI._find_tc(zi, m2/(2**n+40),m2/2**n)); 2**n;len(v); np.round(m2/v)
# set zi.demod_order,1
# n=17; v=array(instruments_ZI._find_tc(zi, m2/2**n,m2/(2**n+40))); 2**n;len(v); np.round(m2/v) #25 pts from 131073 to 131112
# v=array(instruments_ZI._find_tc(zi, m2/2**25,m2/181684)); 2**n;len(v); np.round(m2/v) # 12 pts:  623457,  310172, et 181702 - 181684 en saut de 2
#  these give t=(v*f):   53.82, 108.18, 184.667, 184.669 ...
# it seems to do the time constants calculation in floats instead of double
#
# in 13.10 get('', True) fails (was returning a flat dictionnary), 14.02 it now works again.
#  also zhinst loads all the examples. (still in 14.02. This is no longer the case in 14.08 where nothing
#    is automatically loaded, and the examples have moved to a submodule.)
#  and list_nodes shows FEATURES/CODE but it cannot be read (in 14.02 it times out). It is a write only node.
# sweep has lots of output to the screen (can it be disabled?) (fixed in 14.02)
#   can reenable it in 14.02 (also logs the info in a file with zi._zi_daq.setDebugLevel(2) (2 or below looks like what I had before))
#    after that can disable it fully only by quitting python (to unload the ziPython.pyd). Using reload does not seem to work.
#    and no debug value seems to work either (confirmed by Juerg 23062014 that there is no way
#    to redisable it)
#
# python says revision 20298, installer says 20315 (installer revision is head revision. installer>python is normal)
# for 14.02, python says 23152, installer says 23225
# for 14.08, python says 26222, installer says 26222
#
# echoDevice does not work (still in 14.02). It is for HF2 instruments not for UHF.
#   better documention awaits changes to properly handle synchronisation on all platforms (Juerg 23062014)
#   This is fixed in 14.08: echoDevice now works and does the same as sync (which is a new function to help synchronise)
# syncSetInt takes 250 ms (with 13.06,100 ms with 13.10, It is no longer a problem with 14.02, but sync/no sync give ~6 ms)
#  compare
#   timeit zi.write('/dev2021/sigins/0/on', 1, t='int')
#   timeit zi.write('/dev2021/sigins/0/on', 1, t='int', sync=False)
# setInt followed by getInt does not return the new value, but the old one instead
#  For 14.02 setInt seems to behave as for setInt_Sync
#   This is a bugfix (Juerg 23062014) and is as intended. The difference:
#    a syncSet command will block until the value
#    was set on the device, whereas a set command will immediately return as
#    soon as the data server got the command.
#    However sync-set does not help to synchronize between sessions or with streaming (subscribe)
#    Suggest to add 100 ms if there is a need to make sure streaming data comes after change
#    A futur sync-set might do this stream sync correctly.
#  For 14.08 sync=True: 7.2ms, False: 6.0 ms
# Compare
# s='/dev2021/demods/0/enable'
# za.set_async(s,1); print za.getI(s); time.sleep(.1); print za.getI(s)
#   returns 1 1
# za.set_async(s,0); print za.getI(s); time.sleep(.1); print za.getI(s)
#   returns 1 0
# za.set_sync(s,0); print za.getI(s); time.sleep(.1); print za.getI(s)
#   returns 0 0
# za.set_sync(s,1); print za.getI(s); time.sleep(.1); print za.getI(s)
#   returns 1 1
# za.set(s,1); print za.getI(s); time.sleep(.1); print za.getI(s)
#   returns 1 1
# za.set(s,0); print za.getI(s); time.sleep(.1); print za.getI(s)
#   returns 0 0
# timeit za.set(s,0)
#  100 loops, best of 3: 5.63 ms per loop
# timeit za.set_sync(s,0)
#  100 loops, best of 3: 6.67 ms per loop
# timeit za.set_async(s,0)
#  10000 loops, best of 3: 23 us per loop
#
# Other changes from release note 14.02 but that I could not figure out:
# in API section
#- Sweeper: Fix for very small sweep steps
#   Juerg 23062014 answer:
#    For small sweep steps the frequency epsilon for comparison was too big
#    for UHF devices. As consequence the sweeper did not wait for the proper
#    settling time and started immediately recording the statistics. The
#    issue could be observed by using very small sweep steps (mHz). It can be
#    observed by setting a large settling time constant factor. Also binary
#    sweeps help to provoke the problem. This issue is fixed by 14.02.
#- Sweeper: Fix for higher harmonics at low frequencies (mHz)
#   Juerg 23062014 answer:
#    The order was not used for the frequency matching. As consequence, for
#    low frequencies the sweeper was waiting forever as it was never
#    detecting the target frequency.


##################################################################
#   Direct Access to ZI C API
#    use ziAPI class
##################################################################

import ctypes
import weakref
from numpy.ctypeslib import as_array
from ctypes import Structure, Union, POINTER, byref, sizeof, addressof, resize,\
                   c_int, c_int16, c_int32, c_short, c_ushort, c_uint,\
                   c_double, c_float,\
                   c_uint32, c_uint8, c_uint16, c_int64, c_uint64,\
                   c_void_p, c_char_p, c_char, c_ubyte, create_string_buffer
c_uchar_p = c_char_p # POINTER(c_ubyte)
c_uint8_p = c_char_p # POINTER(c_uint8)
c_uint32_p = POINTER(c_uint32)

from ..types import StructureImproved

try:
    warnings
    #print "We are reloading this module, no need to add the filter again"
except NameError:
    import warnings
    # The RE are done with match (they have to match from the start of the string)
    # This filters a warning when using ctypeslib as_array on a ctypes array.
    #  http://stackoverflow.com/questions/4964101/pep-3118-warning-when-using-ctypes-array-as-numpy-array
    warnings.filterwarnings('ignore', 'Item size computed from the PEP 3118 buffer format string does not match the actual item size.', RuntimeWarning, r'numpy\.ctypeslib')

ziDoubleType = c_double
ziIntegerType = c_int64
ziTimeStampType = c_uint64
ziAPIDataType = c_int
ziConnection = c_void_p

MAX_PATH_LEN = 256
MAX_EVENT_SIZE = 0x400000
#MAX_BINDATA_SIZE = 0x10000

class DemodSample(StructureImproved):
    _fields_ = [('timeStamp', ziTimeStampType),
                ('x', c_double),
                ('y', c_double),
                ('frequency', c_double),
                ('phase', c_double),
                ('dioBits', c_uint32),
                ('trigger', c_uint32),
                ('auxIn0', c_double),
                ('auxIn1', c_double) ]

class AuxInSample(StructureImproved):
    _fields_ = [('timeStamp', ziTimeStampType),
                ('ch0', c_double),
                ('ch1', c_double) ]

class DIOSample(StructureImproved):
    _fields_ = [('timeStamp', ziTimeStampType),
                ('bits', c_uint32),
                ('reserved', c_uint32) ]

TREE_ACTION = {0:'removed', 1:'add', 2:'change'}
class TreeChange(StructureImproved):
    _fields_ = [('timeStamp', ziTimeStampType),
                ('action', c_uint32),
                ('name', c_char*32) ]

class TreeChange_old(StructureImproved):
    _fields_ = [('Action', c_uint32),
                ('Name', c_char*32) ]


# ctypes in Python 2.6.2 at least has a bug that prevents
# subclassing arrays unless _length_ and _type_ are redefined
# create a metaclass to automatically do that transformation
_ctypes_array_metabase = (c_uint8*4).__class__
class _ctypes_array_metabase_fix(_ctypes_array_metabase):
    def __new__(mcls, name, bases, d):
        d['_length_'] = bases[0]._length_
        d['_type_'] = bases[0]._type_
        return super(_ctypes_array_metabase_fix, mcls).__new__(mcls, name, bases, d)

# TODO Fix the ctypes.sizeof instruction which returns the base size, not the
# augmented size of the structure. I am not sure if it is possible
class StructureImproved_extend(StructureImproved):
    """
    Adds to StructImproved a way to extend the last entry.
    a _mask_ variable containing (src, dst), both strings
    while replace access to src with calls to _dst_get, and assignment to src
    with calls to _dst_set. This can be useful for structure that have a last
    of variable length.
    If _mask_ is just a string, it replaces that entry with
    _mask_default_set, _mask_default_get.
    They both use the string in _mask_lengthvar to access a size variable for
    the mask attribute
    They also use the type in _mask_basetype as the base type of the array.
    And the use the _mask_get_conv to convert from the new proper ctype structure
    to something else. By default the function tries to return a numpy array,
    unless the basetype is c_char, in which case it returns the type as is.
    By default c_char arrays are return with .value (zero terminated string), to have them
    return .raw, set attribute _mask_char_raw to True
    It will also make the set_data_size method work (assuming the variable to replace is the last one)
    You can return the unmakes variable as _maskname_raw for a masked variable called maskname
    """
    _mask_ = (None, '')
    _mask_lengthvar = ''
    _mask_basetype = c_ubyte
    _mask_char_raw = False
    @staticmethod
    def _normalize_mask(mask):
        if isinstance(mask, basestring):
            mask = (mask, 'mask_default')
        return mask
    def __setattr__(self, name, value):
        mask = self._normalize_mask(self._mask_)
        if name == mask[0]:
            getattr(self, '_'+mask[1]+'_set')(value)
        else:
            super(StructureImproved_extend, self).__setattr__(name, value)
    def __getattribute__(self, name):
        mask = super(StructureImproved_extend, self).__getattribute__('_mask_')
        normalize = super(StructureImproved_extend, self).__getattribute__('_normalize_mask')
        mask = normalize(mask)
        if name == mask[0]:
            name = '_'+mask[1]+'_get'
            return super(StructureImproved_extend, self).__getattribute__(name)()
        elif name == '_'+mask[0]+'_raw':
            return super(StructureImproved_extend, self).__getattribute__(mask[0])
        else:
            return super(StructureImproved_extend, self).__getattribute__(name)
    def _mask_get_offset(self):
        mask = self._normalize_mask(self._mask_)
        return getattr(self.__class__, mask[0]).offset
    def _mask_get_count(self):
        # returns the number of elements, used for resize and newtype
        return getattr(self, self._mask_lengthvar)
    def _mask_get_conv(self, cdata):
        # This should return an object that can be assigned to
        cnt = self._mask_get_count()
        if self._mask_basetype == c_char:
            return cdata
        if cnt > 0:
            # this can produce the warning we filter above (about PEP 3118)
            return as_array(cdata)
        else:
            return cdata
    def set_data_size(self, n):
        """
        Use this instead of changing the count directly. It will properly resize
        the structure.
        It assumes the variable to mask is the last element of the structure.
        """
        mask = self._normalize_mask(self._mask_)
        if mask[1] != 'mask_default':
            raise NotImplementedError('This function is only implemented when using the default mask. Subclasses should overwrite this.')
        setattr(self, self._mask_lengthvar, n)
        offset = self._mask_get_offset()
        cnt = self._mask_get_count()
        t = self._mask_basetype
        newsize = offset + cnt * sizeof(t)
        minsize = sizeof(self)
        newsize = max(minsize, newsize)
        resize(self, newsize)
    def _mask_default_get(self):
        #print 'Get called'
        cnt = self._mask_get_count()
        #cnt = min(cnt, 1024*1024)
        newtype = self._mask_basetype * cnt
        if self._mask_basetype == c_char:
            # we now deal with character arrays.
            if self._mask_char_raw:
                # define a new class that shows the raw data when displayed with repr
                newtype = _ctypes_array_metabase_fix('tmp_array_class', (newtype,), dict(__repr__= lambda s: repr(s.raw)))
            else:
                # define a new class that shows the value data when displayed with repr
                newtype = _ctypes_array_metabase_fix('tmp_array_class', (newtype,), dict(__repr__= lambda s: repr(s.value)))
        offset = self._mask_get_offset()
        cdata = newtype.from_address(addressof(self) + offset)
        return self._mask_get_conv(cdata)
    def _mask_default_set(self, val):
        #print 'set called'
        self._mask_default_get()[:] = val

class ByteArrayData(StructureImproved_extend):
    _fields_ = [('length', c_uint32),
                ('bytes', c_char*0) ] # c_uint8*0
    _mask_ = 'bytes'
    _mask_basetype = c_char
    _mask_lengthvar = 'length'
    _mask_char_raw = True


class ScopeWave_old(StructureImproved_extend):
    _fields_ = [('dt', c_double),
                ('ScopeChannel', c_uint),
                ('TriggerChannel', c_uint),
                ('BWLimit', c_uint),
                ('Count', c_uint),
                ('Data', c_short*0) ]
    _mask_ = 'Data'
    _mask_basetype = c_short
    _mask_lengthvar = 'Count'

class ziDoubleTypeTS(StructureImproved):
    _fields_ = [('timeStamp', ziTimeStampType),
                ('value', ziDoubleType) ]

class ziIntegerTypeTS(StructureImproved):
    _fields_ = [('timeStamp', ziTimeStampType),
                ('value', ziIntegerType) ]

class ByteArrayDataTS(StructureImproved_extend):
    _fields_ = [('timeStamp', ziTimeStampType),
                ('length', c_uint32),
                ('bytes', c_char*0) ] # c_uint8*0
    _mask_ = 'bytes'
    _mask_basetype = c_char
    _mask_lengthvar = 'length'
    _mask_char_raw = True


# These will display the data instead of the class name
class c_uint8x4(c_uint8*4):
    __metaclass__ = _ctypes_array_metabase_fix
    def __repr__(self):
        return repr(self[:])

class c_floatx4(c_float*4):
    __metaclass__ = _ctypes_array_metabase_fix
    def __repr__(self):
        return repr(self[:])

class ScopeWave(StructureImproved_extend): # Changed a lot on version 14.02
    _fields_ = [('timeStamp', ziTimeStampType),
                ('triggerTimeStamp', ziTimeStampType), # can be between samples
                ('dt', c_double), # time between samples
                ('channelEnable', c_uint8x4), # bool for enabled channel
                ('channelInput', c_uint8x4), # input source for each channel (0-1: input1-2, 2-3: trigger in1-2, 4-7:Aux out1-4, 8-9:Aux in 1-2)
                ('triggerEnable', c_uint8), # bit0: rising edge enable, bit1: falling edge enable (enable=1)
                ('triggerInput', c_uint8), # same as channelInput
                ('reserved0', c_uint8*2),
                ('channelBWLimit', c_uint8x4), # per channel, bit0: off=0, on=1, bit1-7: reserved
                ('channelMath', c_uint8x4), # Math(averaging...) per channel, bit0-7: reserved
                ('channelScaling', c_floatx4),
                ('sequenceNumber', c_uint32),
                ('segmentNumber', c_uint32),
                ('blockNumber', c_uint32), # large scope shots comes in multiple blocks that need to be concatenated
                ('totalSamples', c_uint64),
                ('dataTransferMode', c_uint8), # SingleTransfer = 0, BlockTransfer = 1, ContinuousTransfer = 3, FFTSingleTransfer = 4
                ('blockMarker', c_uint8),  # bit0: 1=end marker
                ('flags', c_uint8),  # bit0: data lost detected(samples are 0), bit1: missed trigger, bit2: Transfer failure (corrupted data)
                ('sampleFormat', c_uint8), # 0=int16, 1=int32, 2=float, 4=int16interleaved, 5=int32interleaved, 6=float interleaved
                ('sampleCount', c_uint32), # number of samples in one channel, the same in the others
                ('Data', c_short*0) ] # Data can be int16, int32 or float
    _mask_ = 'Data'
    #_mask_basetype = c_short
    _mask_lengthvar = 'sampleCount'
    # Warning: you need to set channel_Enable and sampleFormat appropriately before calling set_data_size
    #  set_data_size adjusts sampleCount directly but also reserves space according to that
    #  and sampleFormat and channelEnable
    @property
    def _mask_basetype(self):
        fmt = self.sampleFormat & 3
        types = [c_int16, c_int32, c_float]
        return types[fmt]
    def _get_nch(self):
        nch = 0
        for i in range(4):
            if self.channelEnable[i]:
                nch += 1
        return nch
    def _mask_get_count(self):
        nch = self._get_nch()
        return self.sampleCount * nch
    def _mask_get_conv(self, cdata):
        newd = super(ScopeWave, self)._mask_get_conv(cdata)
        if isinstance(newd, np.ndarray):
            nch = self._get_nch()
            if nch > 1:
                # TODO figure out the data structure for interleaved or not
                #   I have not been able to produce data with nch>1 (14.02). So not checked.
                if self.sampleFormat & 4: #interleaved
                    newd.shape=(-1, nch)
                else:
                    newd.shape=(nch, -1)
        return newd


class PWASample(StructureImproved):
    _fields_ = [('binPhase', c_double),
                ('x', c_double),
                ('y', c_double),
                ('countBin', c_uint32),
                ('reserved', c_uint32) ]

class PWAWave(StructureImproved_extend):
    _fields_ = [('timeStamp', ziTimeStampType),
                ('sampleCount', c_uint64),
                ('inputSelect', c_uint32),
                ('oscSelect', c_uint32),
                ('harmonic', c_uint32),
                ('binCount', c_uint32),
                ('frequency', c_double),
                ('pwaType', c_uint8),
                ('mode', c_uint8), #0:zoom, 1: harmonic
                ('overflow', c_uint8), #bit0: data accumulator overflow, bit1: counter at limit, bit7: invalid (missing frames), other bits are reserved
                ('commensurable', c_uint8),
                ('reservedUInt', c_uint32),
                ('data', PWASample*0) ]
    _mask_ = 'data'
    _mask_basetype = PWASample
    _mask_lengthvar = 'sampleCount'
    def _mask_get_conv(self, cdata):
        # This should return an object that can be assigned to
        cnt = self._mask_get_count()
        if cnt > 0:
            dt = [('binPhase', np.double), ('x', np.double), ('y', np.double), ('countBin', np.int32), ('reserved',np.int32)]
            return np.frombuffer(cdata, dtype=dt).view(np.recarray)
        else:
            return cdata

# These point to the first element of DATA with the correct type.
class ziEventUnion(Union):
    _fields_ = [('Void', c_void_p),
                ('Double', POINTER(ziDoubleType)),
                ('DoubleTS', POINTER(ziDoubleTypeTS)),
                ('Integer', POINTER(ziIntegerType)),
                ('IntegerTS', POINTER(ziIntegerTypeTS)),
                ('ByteArray', POINTER(ByteArrayData)),
                ('ByteArrayTS', POINTER(ByteArrayDataTS)),
                ('Tree', POINTER(TreeChange)),
                ('Tree_old', POINTER(TreeChange_old)),
                ('SampleDemod', POINTER(DemodSample)),
                ('SampleAuxIn', POINTER(AuxInSample)),
                ('SampleDIO', POINTER(DIOSample)),
                ('ScopeWave', POINTER(ScopeWave)),
                ('ScopeWave_old', POINTER(ScopeWave_old)),
                ('pwaWave', POINTER(PWAWave)) ]

ziAPIDataType_vals = {0:'None', 1:'Double', 2:'Integer', 3:'SampleDemod', 4:'ScopeWave_old',
                 5:'SampleAuxIn', 6:'SampleDIO', 7:'ByteArray', 16:'Tree_old',
                 32:'DoubleTS', 33:'IntegerTS', 35:'ScopeWave', 38:'ByteArrayTS', 48:'Tree',
                 8:'pwaWave'}

class ziEvent(StructureImproved):
    _fields_ = [('valueType', ziAPIDataType),
                ('count', c_uint32),
                ('path', c_char*MAX_PATH_LEN), # c_uint8*MAX_PATH_LEN
                ('value', ziEventUnion),
                ('data', c_char*MAX_EVENT_SIZE) ] # c_uint8*MAX_EVENT_SIZE
    def _init_pointer(self):
        """
        Use this for testing. It properly initializes the value union pointers.
        """
        self.value.Void = addressof(self) + ziEvent.data.offset
    def get_union(self):
        """
        This returns the correct pointer. You can acces the data
        with the contents method or by indexing [0], [1] (when count>0)
        """
        if self.count == 0 or self.valueType == 0:
            return None
        return getattr(self.value, ziAPIDataType_vals[self.valueType])
    @property
    def first_data(self):
        data = self.get_union()
        if data != None:
            return data.contents
    def __repr__(self):
        if self.count == 0:
            return 'ziEvent(None)'
        data = self.get_union()
        return "zevent('%s', count=%i, data0=%r)"%(self.path, self.count, data.contents)
    def show_all(self, multiline=True, show=True):
        if self.count == 0:
            strs = ['None']
        else:
            strs = ['Path=%s'%self.path,'Count=%i'%self.count]
            data = self.get_union()
            for i in range(self.count):
                strs.append('data_%i=%r'%(i, data[i]))
        if multiline:
            ret = '%s(\n  %s\n)'%(self.__class__.__name__, '\n  '.join(strs))
        else:
            ret = '%s(%s)'%(self.__class__.__name__, ', '.join(strs))
        if show:
            print ret
        else:
            return ret


ZIResult_enum = c_int
ZI_INFO_SUCCESS    = ZI_INFO_BASE     = 0x0000
ZI_WARNING_GENERAL = ZI_WARNING_BASE  = 0x4000
ZI_ERROR_GENERAL   = ZI_ERROR_BASE    = 0x8000

ZIAPIVersion = c_int
#zi_api_version = {1:'ziAPIv1', 3:'ziAPIv3'}
zi_api_version = {1:'ziAPIv1', 4:'ziAPIv4'}

zi_result_dic = {ZI_INFO_SUCCESS:'Success (no error)',
                 ZI_INFO_SUCCESS+1:'Max Info',
                 ZI_WARNING_GENERAL:'Warning (general)',
                 ZI_WARNING_GENERAL+1:'FIFO Underrun',
                 ZI_WARNING_GENERAL+2:'FIFO Overflow',
                 ZI_WARNING_GENERAL+3:'NotFound',
                 ZI_WARNING_GENERAL+4:'Max Warning',
                 ZI_ERROR_GENERAL:'Error (general)',
                 ZI_ERROR_GENERAL+1:'USB communication failed',
                 ZI_ERROR_GENERAL+2:'Malloc failed',
                 ZI_ERROR_GENERAL+3:'mutex unable to init',
                 ZI_ERROR_GENERAL+4:'mutex unable to destroy',
                 ZI_ERROR_GENERAL+5:'mutex unable to lock',
                 ZI_ERROR_GENERAL+6:'mutex unable to unlock',
                 ZI_ERROR_GENERAL+7:'thread unable to start',
                 ZI_ERROR_GENERAL+8:'thread unable tojoin',
                 ZI_ERROR_GENERAL+9:'socket cannot init',
                 ZI_ERROR_GENERAL+0x0a:'socket unable to connect',
                 ZI_ERROR_GENERAL+0x0b:'hostname not found',
                 ZI_ERROR_GENERAL+0x0c:'Connection invalid',
                 ZI_ERROR_GENERAL+0x0d:'timed out',
                 ZI_ERROR_GENERAL+0x0e:'command failed internally',
                 ZI_ERROR_GENERAL+0x0f:'command failed in server',
                 ZI_ERROR_GENERAL+0x10:'provided buffer length to short',
                 ZI_ERROR_GENERAL+0x11:'unable to open or read from file',
                 ZI_ERROR_GENERAL+0x12:'Duplicate entry',
                 ZI_ERROR_GENERAL+0x13:'invalid attempt to change a read-only node',
                 ZI_ERROR_GENERAL+0x14:'Device not visible to server',
                 ZI_ERROR_GENERAL+0x15:'Device already in use (by another server)',
                 ZI_ERROR_GENERAL+0x16:'Device does not support interface',
                 ZI_ERROR_GENERAL+0x17:'Device connection timeout',
                 ZI_ERROR_GENERAL+0x18:'Device already connected using another interface',
                 ZI_ERROR_GENERAL+0x19:'Device needs firmware upgrade',
                 ZI_ERROR_GENERAL+0x1a:'Trying to get data from a poll event with wrong target data type',
                 ZI_ERROR_GENERAL+0x1b:'Max Error' }

class ziAPI(object):
    _default_host = 'localhost'
    _default_port = 8004
    def __init__(self, hostname=_default_host, port=_default_port, autoconnect=True):
        self._last_result = 0
        self._ziDll = ctypes.CDLL('/Program Files/Zurich Instruments/LabOne/API/C/lib/ziAPI-win32.dll')
        self._conn = ziConnection()
        self._makefunc('ziAPIInit', [POINTER(ziConnection)],  prepend_con=False)
        self._makefunc('ziAPIDestroy', [] )
        self._makefunc('ziAPIGetRevision', [POINTER(c_uint)], prepend_con=False )
        self._makefunc('ziAPIConnect', [c_char_p, c_ushort] )
        self._makefunc('ziAPIDisconnect', [] )
        self._makefunc('ziAPIListNodes', [c_char_p, c_char_p, c_int, c_int] )
        self._makefunc('ziAPIUpdateDevices', [] )
        self._makefunc('ziAPIConnectDevice', [c_char_p, c_char_p, c_char_p] ) # deviceSerialNum, deviceInterface(USB|1GbE), interfaceParameters
        self._makefunc('ziAPIDisconnectDevice', [c_char_p] ) # deviceSerialNum
        self._makegetfunc('D', ziDoubleType)
        self._makegetfunc('I', ziIntegerType)
        self._makegetfunc('DemodSample', DemodSample, base='Get')
        self.getS = self.getDemodSample
        self._makegetfunc('DIOSample', DIOSample, base='Get')
        self.getDIO = self.getDIOSample
        self._makegetfunc('AuxInSample', AuxInSample, base='Get')
        self.getAuxIn = self.getAuxInSample
        self._makegetfunc('B', c_char_p)
        self._makefunc('ziAPISetValueD', [c_char_p, ziDoubleType] )
        self._makefunc('ziAPISetValueI', [c_char_p, ziIntegerType] )
        self._makefunc('ziAPISetValueB', [c_char_p, c_uchar_p, c_uint] )
        self._makefunc('ziAPISyncSetValueD', [c_char_p, POINTER(ziDoubleType)] )
        self._makefunc('ziAPISyncSetValueI', [c_char_p, POINTER(ziIntegerType)] )
        self._makefunc('ziAPISyncSetValueB', [c_char_p, c_uint8_p, c_uint32_p, c_uint32] )
        self._makefunc('ziAPISync', [] ) # added in 14.08
        self._makefunc('ziAPIEchoDevice', [c_char_p] ) # added in 14.08, deprecated.
        self._makefunc('ziAPISubscribe', [c_char_p] )
        self._makefunc('ziAPIUnSubscribe', [c_char_p] )
        self._makefunc('ziAPIPollDataEx', [POINTER(ziEvent), c_uint32] )
        self._makefunc('ziAPIGetValueAsPollData', [c_char_p] )
        self._makefunc('ziAPIGetError', [ZIResult_enum, POINTER(c_char_p), POINTER(c_int)], prepend_con=False)
        # skipped ReadMEMFile
        self._makefunc('ziAPIAsyncSetDoubleData', [c_char_p, ziDoubleType] )
        self._makefunc('ziAPIAsyncSetIntegerData', [c_char_p, ziIntegerType] )
        self._makefunc('ziAPIAsyncSetByteArray', [c_char_p, c_uint8_p, c_uint32] )
        self._makefunc('ziAPIListImplementations', [c_char_p, c_uint32], prepend_con=False )
        self._makefunc('ziAPIConnectEx', [c_char_p, c_uint16, ZIAPIVersion, c_char_p] )
        self._makefunc('ziAPIGetConnectionAPILevel', [POINTER(ZIAPIVersion)] )
        # SecondsTimeStamp is depracated and does not work properly for UHF, used for HF2
        self._SecondsTimeStamp = self._ziDll.ziAPISecondsTimeStamp
        self._SecondsTimeStamp.restype = c_double
        self._SecondsTimeStamp.argtypes = [ziTimeStampType]
        # The allocate/deallocate are not useful in python but they are included here for completeness/testing
        self._AllocateEventEx = self._ziDll.ziAPIAllocateEventEx
        self._AllocateEventEx.restype = POINTER(ziEvent)
        self._AllocateEventEx.argtypes = []
        self._DeallocateEventEx = self._ziDll.ziAPIDeallocateEventEx # added in 14.08
        self._DeallocateEventEx.restype = None
        self._DeallocateEventEx.argtypes = [POINTER(ziEvent)]
        self.init()
        if autoconnect:
            self.connect_ex(hostname, port)
    def _errcheck_func(self, result, func, arg):
        self._last_result = result
        if result<ZI_WARNING_GENERAL:
            return
        else:
            if result<ZI_ERROR_GENERAL:
                raise RuntimeWarning, 'Warning: %s'%zi_result_dic[result]
            else:
                raise RuntimeError, 'ERROR: %s'%zi_result_dic[result]
    def _makefunc(self, f, argtypes, prepend_con=True):
        rr = r = getattr(self._ziDll, f)
        r.restype = ZIResult_enum
        r.errcheck = ProxyMethod(self._errcheck_func)
        if prepend_con:
            argtypes = [ziConnection]+argtypes
            selfw = weakref.proxy(self)
            rr = lambda *arg, **kwarg: r(selfw._conn, *arg, **kwarg)
            setattr(self, '_'+f[5:] , rr) # remove 'ziAPI'
        r.argtypes = argtypes
        setattr(self, '_'+f , r)
    def _makegetfunc(self, f, argtype, base='GetValue'):
        fullname = 'ziAPI'+base+f
        if argtype == c_char_p:
            self._makefunc(fullname, [c_char_p, argtype, POINTER(c_uint), c_uint])
        else:
            self._makefunc(fullname, [c_char_p, POINTER(argtype)])
        basefunc = getattr(self, '_'+base+f)
        def newfunc(path):
            val = argtype()
            if argtype == c_char_p:
                val = create_string_buffer(1024)
                length = c_uint()
                basefunc(path, val, byref(length), len(val))
                return val.raw[:length.value]
            basefunc(path, byref(val))
            if isinstance(val, Structure):
                return val
            else:
                return val.value
        setattr(self, 'get'+f, newfunc)
    def __del__(self):
        # can't use the redirected functions because weakproxy no longer works here
        print 'Running del on ziAPI:', self
        del self._ziAPIDisconnect.errcheck
        del self._ziAPIDestroy.errcheck
        self._ziAPIDisconnect(self._conn)
        self._ziAPIDestroy(self._conn)
    def restart(self, hostname=_default_host, port=_default_port, autoconnect=True):
        self.disconnect()
        self.destroy()
        self.init()
        if autoconnect:
            self.connect_ex(hostname, port)
    def init(self):
        self._ziAPIInit(self._conn)
    def destroy(self):
        self._Destroy()
    def connect(self, hostname=_default_host, port=_default_port):
        """
        If you want to reconnect, you need to first disconnect.
        """
        # before 14.08, to reconnect required: first disconnect, then destroy
        # then init, before trying connect. Now just disconnect first is necessary
        self._Connect(hostname, port)
        print 'Connected'
    def disconnect(self):
        self._Disconnect()
    def get_revision(self):
        rev = c_uint()
        self._ziAPIGetRevision(byref(rev))
        return rev.value
    def connect_ex(self, hostname=_default_host, port=_default_port, version=4, implementation=None):
        self._ConnectEx(hostname, port, version, implementation)
        print 'Connected ex'
    def list_implementation(self):
        buf = create_string_buffer(1024)
        self._ziAPIListImplementations(buf, len(buf))
        return buf.value.split('\n')
    def get_connection_ver(self):
        ver = ZIAPIVersion()
        self._GetConnectionAPILevel(byref(ver))
        return ver.value, zi_api_version[ver.value]
    def list_nodes(self, path='/', flags=3):
        buf = create_string_buffer(102400)
        self._ListNodes(path, buf, len(buf), flags)
        return buf.value.split('\n')
    def update_devices(self):
        """
        Rescans the devices available
        """
        self._UpdateDevices()
    def subscribe(self, path):
        self._Subscribe(path)
    def unsubscribe(self, path):
        self._UnSubscribe(path)
    def poll(self, timeout_ms=0):
        ev = ziEvent()
        self._PollDataEx(byref(ev),timeout_ms)
        return ev
    def get_as_poll(self, path):
        self._GetValueAsPollData(path)
    def get_error(self, result=None):
        """
        if result==None, uses the last returned result
        """
        if result==None:
            result = self._last_result
        buf = c_char_p()
        base = c_int()
        self._ziAPIGetError(result, byref(buf), byref(base))
        print 'Message:', buf.value, '\nBase:', hex(base.value)
    def set(self, path, val):
        if isinstance(val, int):
            self._SetValueI(path, val)
        elif isinstance(val, float):
            self._SetValueD(path, val)
        elif isinstance(val, basestring):
            self._SetValueB(path, val, len(val))
        else:
            raise TypeError, 'Unhandled type for val'
    def set_async(self, path, val):
        if isinstance(val, int):
            self._AsyncSetIntegerData(path, val)
        elif isinstance(val, float):
            self._AsyncSetDoubleData(path, val)
        elif isinstance(val, basestring):
            self._AsyncSetByteArray(path, val, len(val))
        else:
            raise TypeError, 'Unhandled type for val'
    def set_sync(self, path, val):
        if isinstance(val, int):
            val = ziIntegerType(val)
            self._SyncSetValueI(path, byref(val))
        elif isinstance(val, float):
            val = c_double(val)
            self._SyncSetValueD(path, byref(val))
        elif isinstance(val, basestring):
            l = c_uint(len(val))
            self._SyncSetValueB(path, val, byref(l), l)
        else:
            raise TypeError, 'Unhandled type for val'
    def sync(self):
        """ Make sure all changes have been propagated
        """
        self._Sync()
        # For 14.08, %timeit z.sync(), takes about 10 ms
    def echo(self, device_serial=''):
        """ For UHF, the same as sync, device_serial is ignored.
            Only for HF2 is per decice echo implemented.
            Note: It is a depracated function.
        """
        self._EchoDevice(device_serial)

# In Visual studio use, Tools/Visual studio command prompt, then:
#    dumpbin /EXPORTS "\Program Files\Zurich Instruments\LabOne\API\C\lib\ziAPI-win32.dll"
#
#        or use pefile:
#import pefile
#pe = pefile.PE(r"\Program Files\Zurich Instruments\LabOne\API\C\lib\ziAPI-win32.dll")
#for x in pe.DIRECTORY_ENTRY_EXPORT.symbols:
#   print '%5i: %s'%(x.ordinal, x.name)
#
#        or use cygwin objdump
# objdump -x "\Program Files\Zurich Instruments\LabOne\API\C\lib\ziAPI-win32.dll" | less
#    and look for The Export Tables section


# Version 14.08
#  msi install worked well
#  /dev/demods/0/bypass: what is this (it has been there for a while, but undocumented)
#  /{dev}/sigins/0/bw: what is this
#  Documentation for settling/inaccuracy is unclear (it is the fraction of the change left)
#  settling/tc can't be <1 anymore
#  longer overhead for sweep
#  Documentation for sweeeper output: repeat of rpwr, missing tcmeas
# web: Sweep statistics *TC only allows 0, 5, 15, 50
#      sweep reverse mode undocumented
#      sweep.fixed always turns on sync at lowe freq
# ziPython:
#      Could you return the error code as a value available in the exception
#         (so I don't have to parse the error message (in case it changes))
#      Also it no longer produces the
#          'ZIAPIException with status code: 32778. Unable to connect socket'
#      which I was using to tell the user to start the server.
#      There is a problem when changing the order/ fixed bw for sweep:
#         zi.sweep_auto_bw_mode.set('fixed')
#         zi.sweep_order.set(3); zi.sweep_auto_bw_fixed.set(23.); wait(1)
#         get(zi.sweep_order), get(zi.sweep_auto_bw_fixed) # should see (3. 23)
#         zi.sweep_order.set(4); zi.sweep_auto_bw_fixed.set(23.); wait(1)
#         get(zi.sweep_order), get(zi.sweep_auto_bw_fixed) # should see (4, 23) but instead get (4, 19.167)
#      Changing order changes the bw. But when they are done quickly, they behave as if
#          fixed_bw is set before order is changed, hence the incorrect bw.
#      It is probably a thread sync problem
