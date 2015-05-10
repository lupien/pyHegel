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

import signal
import time
import sys

def _sleep_delayed_signal_handler(signum, stack_frame):
    # replaces ipython 0.10 use of ctypes.pythonapi.PyThreadState_SetAsyncExc
    raise KeyboardInterrupt

# All functions using time.sleep should use the _sleep_signal_context_manager
# and all time.sleep should be replaced by this sleep (which includes the manager)
#
# For visa, time.sleep is only used for
# ressource creation and
# for write. For write time.sleep is only used if object.delay >0
#
# For threading, time.sleep is used in
# _Condition.wait
# which is used in _Event.wait, Thread.join
#    _Event.wait is used in _Timer.run
#


def _empty_async():
    # run this after changing the signal handler away from the iptyhon 0.10
    # one, in order to remove any possible queued PyThreadState_SetAsyncExc
    # exception
    # This function can be interrupted by any exception, but probably
    # by KeyboardInterrupt
    # We need to use the same inner loop as for test_async below
    # for the default check interval of 100, this functions
    #  takes 5.5 us on reuletlab4
    for i in range(sys.getcheckinterval()+50):
        pass

class _sleep_signal_context_manager():
    # This temporarily changes the context handler for SIGINT
    # This is needed for time.sleep under ipython 0.10 (python xy 2.7.2.0)
    # because the ipython handler screws up CTRL-C handling and is
    # reapplied for each ipython new input line
    def __init__(self, absorb_ctrlc=False):
        self.old_sig = None
        self.ctrlc_occured = False
        self.absorb_ctrlc = absorb_ctrlc
    def __enter__(self):
        try:
            try:
                #old_sig = signal.signal(signal.SIGINT, _sleep_signal_handler)
                self.old_sig = signal.signal(signal.SIGINT, signal.default_int_handler)
            except ValueError, e: # occurs when not in main thread
                #print 'Not installing handler because in secondary thread', e
                self.old_sig = None
            _empty_async()
            return self # will be used for target in : with xxx as target
        except KeyboardInterrupt: # capture a break (possibly async)
            if self.old_sig: # we can get here with old_sig == None, it is rare but I have seen it
                signal.signal(signal.SIGINT, self.old_sig)
            raise
    def __exit__(self, exc_type, exc_value, exc_traceback):
        # exc_type, exc_value, exc_traceback are None if no exception occured
        if exc_type == KeyboardInterrupt:
            self.ctrlc_occured = True
        if self.old_sig != None:
            signal.signal(signal.SIGINT, self.old_sig)
        if self.ctrlc_occured and self.absorb_ctrlc:
            return True # this will suppress the exception


def sleep(sec, absorb_ctrlc=False):
    """
    Same as time.sleep (wait for sec seconds)
    Will be stopped by CTRL-C
    But this version always produces KeyboardInterrupt when interrupted
    which is not the case of time.sleep with ipython 0.10 (python xy 2.7.2.0)
    When absorb_ctrlc=True, it does not raise the KeyboardInterrupt,
     but instead returns 'break' instead of None
    For threads other than main, the sleep cannot be interrupted, so except
    for absorb_ctrlc=True it is the same as time.sleep.
    (not that on linux SIGINT signal from CTRL-C is most often send to main
     thread but can sometimes and can be forced to go to another thread.
     Under those conditions, sleep in another thread can exit before
     the full time, but the exception is raised in main thread.)
    """
    with _sleep_signal_context_manager(absorb_ctrlc) as context:
        time.sleep(sec)
    if context.ctrlc_occured:
        # can only be here if absorb_ctrlc was True
        # otherwise the exception was raised
        return 'break'

#########################################
# _delayed_signal_context_manager is for
#  Handling of KeyboardInterrupt during PyQt eventLoop (paintEvent...)
#  and to disable raising of KeyboardInterrupt at critical time
#  But NOT for sleeping functions (sleeping function could still stop
#  and produce IOError with EINTR as errno)
#########################################

class _delayed_signal_context_manager():
    # This temporarily changes the context handler for SIGINT
    # when we don't want to be interrupted
    def __init__(self, absorb_ctrlc=False, raiseit=False):
        self.old_sig = None
        self.ctrlc_occured = False
        self.absorb_ctrlc = absorb_ctrlc
        self.signaled = False
        self.raiseit = raiseit
    def delayed_sigint_handler(self, signum, stack_frame):
        self.signaled = True
        if self.raiseit:
            raise KeyboardInterrupt
    def __enter__(self):
        try:
            try:
                self.old_sig = signal.signal(signal.SIGINT, self.delayed_sigint_handler)
            except ValueError, e: # occurs when not in main thread
                #print 'Not installing handler because in secondary thread', e
                self.old_sig = None
            _empty_async()
            return self # will be used for target in : with xxx as target
        except KeyboardInterrupt: # capture a break (possibly async)
            if self.old_sig: # we can get here with old_sig == None, it is rare but I have seen it
                signal.signal(signal.SIGINT, self.old_sig)
            raise
    def __exit__(self, exc_type, exc_value, exc_traceback):
        # exc_type, exc_value, exc_traceback are None if no exception occured
        if self.old_sig != None:
            signal.signal(signal.SIGINT, self.old_sig)
            # Starting from here, delayed_sigint_handle will no longer be called
            # And if it was called before the switch, it completed because
            # we are in the main thread, and the signal is executed in the main thread.
            if self.signaled and not exc_type:
                self.ctrlc_occured = True
                if not self.absorb_ctrlc:
                    raise KeyboardInterrupt('Delayed Interrupt')
        # exc_type == KeyboardInterrupt: This will only happen if someone raises
        # KeyboardInterrupt
        # or from a PyThreadState_SetAsyncExc of KeyboardInterrupt
        # not from CTRL-C being pressed. So treat it like any other exception
        # and let it be raised


if __name__ == "__main__":
    # tests of the kbint handling
    from ctypes import pythonapi, c_long, py_object
    import thread
    from qt_wrap import QtCore, processEvents
    import dis
    def test_async(n_inner=200, n_repeat=1000):
        """ n_inner should be larger than check interval by at around 20.
            It returns a list of for loop count.
            The first one could be anything below check interval
            The other ones should be similar.
            Anything bigger is bad.
        """
        check_interval =  sys.getcheckinterval()
        print 'current check interval', check_interval
        result = []
        for i in range(n_repeat):
            j=-99
            pythonapi.PyThreadState_SetAsyncExc(c_long(thread.get_ident()), py_object(KeyboardInterrupt))
            try:
                for j in range(n_inner):
                    pass
            except KeyboardInterrupt:
                result.append(j)
        for r in result:
            if r>check_interval:
                print '  WARNING found: %i > check interval', r
        return result
    def test_sleep_exc(timeout=10, newsleep=False):
        print 'press CTRL-C in the next ', timeout,' seconds'
        try:
            try:
                if newsleep:
                    sleep(timeout)
                else:
                    time.sleep(timeout)
            except IOError as exc:
                print 'The timeout inner exception is IOError ', exc.errno
            except KeyboardInterrupt:
                print 'The timeout inner exception is KeyboardInterrupt'
            except:
                exc_type, exc_val, exc_traceback = sys.exc_info()
                print 'The timeout inner exception is ', exc_type, ' with value', exc_val
            _empty_async()
        except:
                exc_type, exc_val, exc_traceback = sys.exc_info()
                print 'Obtained a second, later exception: ', exc_type, ' with value', exc_val
    def test_qtloop(timeout=10, with_context=False, raiseit=True):
        def inner_loop():
            to = time.time()
            while time.time()-to < timeout:
                pass
        print 'Press CTRL-C in the next ', timeout, ' seconds'
        try:
            QtCore.QTimer.singleShot(1, inner_loop)
            to = time.time()
            while time.time()-to < 1: # the timer should start after 1ms
                if with_context:
                    with _delayed_signal_context_manager(raiseit=raiseit):
                        processEvents(max_time_ms = 20)
                else:
                    processEvents(max_time_ms = 20)
        except KeyboardInterrupt:
            print 'The interrupt reached the python main thread'
        else:
            print 'WARNING: the Qt event loop absorbed the exception'
    def test_signal_absorb(timeout=10):
        def new_signal(sig, stack):
            print 'Got Signal'
        old_signal = signal.signal(signal.SIGINT, new_signal)
        _empty_async()
        print 'Press CTRL-C many times in the next ', timeout, ' seconds'
        to = time.time()
        while time.time()-to < timeout:
            signal.signal(signal.SIGINT, new_signal)
        signal.signal(signal.SIGINT, old_signal)
    print '------------- disassembly of _empty_async -----------------------'
    dis.dis(_empty_async)
    print '------------- test_async -----------------------'
    async_result = test_async() # could do an histogram on this
    print async_result
    print '------------- test_sleep_exc -----------------------'
    print '  inner that are not KeyboardInterrupt, or outer implies we need to use new sleep'
    test_sleep_exc()
    print '------------- test_sleep_exc new sleep -----------------------'
    print '  if there was a problem with old sleep this should fix it (or change nothing)'
    print '  i.e. the sleep should interrupt and produce only inner KeyboardInterrupt'
    test_sleep_exc(newsleep=True)
    print '------------- test_qtloop -----------------------'
    print '  if qt absorbs exception, we need to delay them, see next test'
    test_qtloop()
    print '------------- test_qtloop with context-----------------------'
    test_qtloop(with_context=True)
    print '------------- test_signal_absorb-----------------------'
    print '  python 2.7.2 can absorb signals when changing signals'
    print '  Therefore it is normal that not all CTRL-C produce a Got Signal'
    # problem is the c codes resets the tripped signal when changing the signal
    # therefore, if a signal arrives during the change, it will not call the
    # python handler.
    # Only option is not change the signal handler too often, and to live with
    # the rare event where a CTRL-C can be absorbed.
    # This problem was first detected because a timeout was set incorrectly (too short)
    # so that signal.signal was called too rapidly. Fixing that bug, made the problem
    # disappear (technically still there but cannot observe it anymore because it is now
    # too rare.)
    test_signal_absorb()
