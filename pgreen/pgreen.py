import sys
import time
from collections import namedtuple

import greenlet


# TODO: В момент _d: c_return switch фиксировать реальное и кумулятивное время выполнения корутины,
#       отдающей управление. Понять, когда отдача управления происходит в последний раз, чтобы
#       сделать trace_dispatch_return

__all__ = ['PGreen']


Frame = namedtuple('Frame', ('fn', 'parent_time', 'internal_time', 'external_time',
                             'wait_time', 'current_frame', 'parent_frame'))


class PGreen:
    def __init__(self):
        self.get_time = time.process_time
        self.last_event_at = None

        self.cur_frame = None
        self.stacks = {}
        self.cur_timeline = []
        self.timelines = {}

    def attach(self):
        self.last_event_at = self.get_time()
        greenlet.settrace(self.dispatch_greenlet_event)
        sys.setprofile(self.dispatch_trace_event)

    def detach(self):
        sys.setprofile(None)
        greenlet.settrace(None)

    def dispatch_greenlet_event(self, event, args):
        print('dispatch_greenlet_event %s' % event)
        if event in ('switch', 'throw'):
            origin, target = args

    def dispatch_trace_event(self, frame, event, arg):
        elapsed = self.get_time() - self.last_event_at

        handler = self.dispatch_table[event]
        handler(self, frame, arg, elapsed)

        self.last_event_at = self.get_time()

    def handle_event_call(self, frame, arg, elapsed):
        code = frame.f_code
        func = (code.co_name, code.co_filename, code.co_firstlineno)
        if func[1] == __file__ and func[0] == 'detach':
            return
        print('handle_event_call ' + str(func))
        self.cur_frame = Frame(func, elapsed, 0, 0, 0, frame, None)

    def handle_event_c_call(self, frame, arg, elapsed):
        func = (arg.__name__, '', 0)
        if func[0] == 'setprofile':
            return
        print('handle_event_c_call ' + str(func))
        self.cur_frame = Frame(func, elapsed, 0, 0, 0, frame, None)

    def handle_event_return(self, frame, arg, elapsed):
        code = frame.f_code
        func = (code.co_name, code.co_filename, code.co_firstlineno)
        if func[1] == __file__ and func[0] == 'attach':
            return
        print('handle_event_return ' + str(func))

        if not self.cur_frame:
            # NOTE: attach was called while a call stack was not empty
            self.cur_frame = Frame(func, 0, elapsed, 0, 0, frame, None)

        func, parent_time, int_time, ext_time, wait_time, frame, parent_frame = self.cur_frame

        self.cur_timeline.append()
        self.cur_frame = parent_frame

    def handle_event_exception(self, frame, arg, elapsed):
        print('handle_event_exception %s' % frame.f_code.co_name)

    dispatch_table = {
        'call': handle_event_call,
        'exception': handle_event_exception,
        'return': handle_event_return,
        'c_call': handle_event_c_call,
        'c_exception': handle_event_return,  # the C function returned
        'c_return': handle_event_return,
    }
