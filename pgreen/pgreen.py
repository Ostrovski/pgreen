import marshal
import sys
import time

from greenlet import greenlet


# TODO: В момент _d: c_return switch фиксировать реальное и кумулятивное время выполнения корутины,
#       отдающей управление. Понять, когда отдача управления происходит в последний раз, чтобы
#       сделать trace_dispatch_return

class Profile:
    """Profiler class.

    self.cur is always a tuple.  Each such tuple corresponds to a stack
    frame that is currently active (self.cur[-2]).  The following are the
    definitions of its members.  We use this external "parallel stack" to
    avoid contaminating the program that we are profiling. (old profiler
    used to write into the frames local dictionary!!) Derived classes
    can change the definition of some entries, as long as they leave
    [-2:] intact (frame and previous tuple).  In case an internal error is
    detected, the -3 element is used as the function name.

    [ 0] = Time that needs to be charged to the parent frame's function.
           It is used so that a function call will not have to access the
           timing data for the parent frame.
    [ 1] = Total time spent in this frame's function, excluding time in
           subfunctions (this latter is tallied in cur[2]).
    [ 2] = Total time spent in subfunctions, excluding time executing the
           frame's function (this latter is tallied in cur[1]).
    [-3] = Name of the function that corresponds to this frame.
    [-2] = Actual frame that we correspond to (used to sync exception handling).
    [-1] = Our parent 6-tuple (corresponds to frame.f_back).

    Timing data for each function is stored as a 5-tuple in the dictionary
    self.timings[].  The index is always the name stored in self.cur[-3].
    The following are the definitions of the members:

    [0] = The number of times this function was called, not counting direct
          or indirect recursion,
    [1] = Number of times this function appears on the stack, minus one
    [2] = Total time spent internal to this function
    [3] = Cumulative time that this function was present on the stack.  In
          non-recursive functions, this is the total execution time from start
          to finish of each invocation of a function, including time spent in
          all subfunctions.
    [4] = A dictionary indicating for each function name, the number of times
          it was called by us.
    """

    def __init__(self):
        self.timings = {}
        self.cur = None
        self.cmd = ""
        self.c_func_name = ""

        self.timer = self.get_time = time.process_time
        self.dispatcher = self.trace_dispatch

        self.t = self.get_time()
        self.simulate_call('profiler')

        self.curs = {}
        self.c_func_names = {}
        self._hack = False

    def _debug_print(fn):
        def print_cur(cur):
            if cur is None:
                print('Current <empty>')
            else:
                print('Current %s %s' % (id(cur), cur[-3]))
                print('\tparent time %.6f' % cur[0])
                print('\tinternal time %.6f' % cur[1])
                print('\texternal time %.6f' % cur[2])
                print('\tframe %s' % id(cur[-2]))
                print('\tparent frame %s' % (id(cur[-1]) if cur[-1] else None))

        def print_timings(timings):
            print('Timings')

            for func in sorted(timings.keys()):
                timing = timings[func]
                print('\t%s: ncalls=%s nstack=%s tottime=%.6f cumtime=%.6f callers=%s'
                      % (func, timing[0], timing[1], timing[2], timing[3], timing[4]))

        def wrapper(*args, **kwargs):
            self = args[0]
            print('[in] %s' % fn.__name__)
            print_cur(self.cur)
            rv = fn(*args, **kwargs)
            print('[out] %s' % fn.__name__)
            print_cur(self.cur)
            print_timings(self.timings)
            print()
            return rv

        return wrapper

    def gl_dispatcher(self, event, args):
        if event in ('switch', 'throw'):
            origin, target = args

            # Simulate return
            timer = self.timer
            t = timer() - self.t

            # Prefix "r" means part of the Returning or exiting frame.
            # Prefix "p" means part of the Previous or Parent or older frame.

            rpt, rit, ret, rfn, frame, rcur = self.cur
            rit = rit + t
            frame_total = rit + ret

            pfn = rcur[3]

            timings = self.timings
            cc, ns, tt, ct, callers = timings[rfn]
            if not ns:
                # This is the only occurrence of the function on the stack.
                # Else this is a (directly or indirectly) recursive call, and
                # its cumulative time will get updated when the topmost call to
                # it returns.
                ct = ct + frame_total
                cc = cc + 1

            if pfn in callers:
                callers[pfn] = callers[pfn] + 1  # hack: gather more
                # stats such as the amount of time added to ct courtesy
                # of this specific call, and the contribution to cc
                # courtesy of this call.
            else:
                callers[pfn] = 1

            timings[rfn] = cc, ns - 1, tt + rit, ct, callers

            self.t = timer()

            # Switch current
            oid = id(origin)
            tid = id(target)
            ptid = id(target.parent) if target.parent else -1

            print('switching %s (parent %s) -> %s (parent %s)'
                  % (oid, id(origin.parent) if origin.parent else -1, tid, ptid))

            self.curs[oid] = self.cur
            self.cur = self.curs.get(tid) or self.curs.get(ptid)

            self.c_func_names[oid] = self.c_func_name
            self.c_func_name = self.c_func_names.get(tid) or self.c_func_names.get(ptid)

            self._hack = True

    def trace_dispatch(self, frame, event, arg):
        if event in ("c_call", "c_return") and arg.__name__ in ("switch", "throw"):
            print("skip trace_dispatch [!] %s.%s" % (event, arg.__name__))
            return

        timer = self.timer
        t = timer() - self.t

        if event == "c_call":
            self.c_func_name = arg.__name__

        if self.dispatch[event](self, frame, t):
            self.t = timer()
        else:
            self.t = timer() - t  # put back unrecorded delta

    @_debug_print
    def trace_dispatch_exception(self, frame, t):
        rpt, rit, ret, rfn, rframe, rcur = self.cur
        if (rframe is not frame) and rcur:
            return self.trace_dispatch_return(rframe, t)
        self.cur = rpt, rit+t, ret, rfn, rframe, rcur
        return 1

    @_debug_print
    def trace_dispatch_call(self, frame, t):
        if self.cur and frame.f_back is not self.cur[-2]:
            if self._hack:
                self._hack = False
            else:
                rpt, rit, ret, rfn, rframe, rcur = self.cur
                if not isinstance(rframe, Profile.fake_frame):
                    assert rframe.f_back is frame.f_back, ("Bad call", rfn,
                                                           rframe, rframe.f_back,
                                                           frame, frame.f_back)
                    self.trace_dispatch_return(rframe, 0)
                    assert (self.cur is None or \
                            frame.f_back is self.cur[-2]), ("Bad call",
                                                            self.cur[-3])
        fcode = frame.f_code
        fn = (fcode.co_filename, fcode.co_firstlineno, fcode.co_name)
        self.cur = (t, 0, 0, fn, frame, self.cur)
        timings = self.timings
        if fn in timings:
            cc, ns, tt, ct, callers = timings[fn]
            timings[fn] = cc, ns + 1, tt, ct, callers
        else:
            timings[fn] = 0, 0, 0, 0, {}
        return 1

    @_debug_print
    def trace_dispatch_c_call(self, frame, t):
        fn = ("", 0, self.c_func_name)
        self.cur = (t, 0, 0, fn, frame, self.cur)
        timings = self.timings
        if fn in timings:
            cc, ns, tt, ct, callers = timings[fn]
            timings[fn] = cc, ns+1, tt, ct, callers
        else:
            timings[fn] = 0, 0, 0, 0, {}
        return 1

    @_debug_print
    def trace_dispatch_return(self, frame, t):
        if frame is not self.cur[-2]:
            assert frame is self.cur[-2].f_back, ("Bad return", self.cur[-3])
            self.trace_dispatch_return(self.cur[-2], 0)

        # Prefix "r" means part of the Returning or exiting frame.
        # Prefix "p" means part of the Previous or Parent or older frame.

        rpt, rit, ret, rfn, frame, rcur = self.cur
        rit = rit + t
        frame_total = rit + ret

        ppt, pit, pet, pfn, pframe, pcur = rcur
        self.cur = ppt, pit + rpt, pet + frame_total, pfn, pframe, pcur

        timings = self.timings
        cc, ns, tt, ct, callers = timings[rfn]
        if not ns:
            # This is the only occurrence of the function on the stack.
            # Else this is a (directly or indirectly) recursive call, and
            # its cumulative time will get updated when the topmost call to
            # it returns.
            ct = ct + frame_total
            cc = cc + 1

        if pfn in callers:
            callers[pfn] = callers[pfn] + 1  # hack: gather more
            # stats such as the amount of time added to ct courtesy
            # of this specific call, and the contribution to cc
            # courtesy of this call.
        else:
            callers[pfn] = 1

        timings[rfn] = cc, ns - 1, tt + rit, ct, callers
        return 1

    dispatch = {
        "call": trace_dispatch_call,
        "exception": trace_dispatch_exception,
        "return": trace_dispatch_return,
        "c_call": trace_dispatch_c_call,
        "c_exception": trace_dispatch_return,  # the C function returned
        "c_return": trace_dispatch_return,
        }

    def set_cmd(self, cmd):
        if self.cur[-1]:
            return   # already set
        self.cmd = cmd
        self.simulate_call(cmd)

    class fake_code:
        def __init__(self, filename, line, name):
            self.co_filename = filename
            self.co_line = line
            self.co_name = name
            self.co_firstlineno = 0

        def __repr__(self):
            return repr((self.co_filename, self.co_line, self.co_name))

    class fake_frame:
        def __init__(self, code, prior):
            self.f_code = code
            self.f_back = prior

    def simulate_call(self, name):
        code = self.fake_code('profile', 0, name)
        if self.cur:
            pframe = self.cur[-2]
        else:
            pframe = None
        frame = self.fake_frame(code, pframe)
        self.dispatch['call'](self, frame, 0)

    def simulate_cmd_complete(self):
        get_time = self.get_time
        t = get_time() - self.t
        while self.cur[-1]:
            # We *can* cause assertion errors here if
            # dispatch_trace_return checks for a frame match!
            self.dispatch['return'](self, self.cur[-2], t)
            t = 0
        self.t = get_time() - t

    def print_stats(self, sort=-1):
        import pstats
        pstats.Stats(self).strip_dirs().sort_stats(sort).print_stats()

    def dump_stats(self, file):
        with open(file, 'wb') as f:
            self.create_stats()
            marshal.dump(self.stats, f)

    def create_stats(self):
        self.simulate_cmd_complete()
        self.snapshot_stats()

    def snapshot_stats(self):
        self.stats = {}
        for func, (cc, ns, tt, ct, callers) in self.timings.items():
            callers = callers.copy()
            nc = 0
            for callcnt in callers.values():
                nc += callcnt
            self.stats[func] = cc, nc, tt, ct, callers

    def runcall(self, func, *args, **kw):
        self.set_cmd(repr(func))
        greenlet.settrace(self.gl_dispatcher)

        def _d(*args):
            print('_d: %s' % args[1], end=' ')
            if args[1] in ('c_call', 'c_return'):
                print(args[2].__name__, end='')
            elif args[1] in ('call', 'return'):
                print(args[0].f_code.co_name, end='')
            print()
            return self.dispatcher(*args)

        sys.setprofile(_d)
        try:
            return func(*args, **kw)
        finally:
            sys.setprofile(None)
            greenlet.settrace(None)


class gProfile:
    def __init__(self):
        self.get_time = time.process_time
        self.last_event_tick = None

    def dispatch_greenlet_event(self, event, args):
        if event in ('switch', 'throw'):
            origin, target = args

    def dispatch_trace_event(self, frame, event, arg):
        elapsed = self.get_time() - self.last_event_tick

        handler = self.dispatch_table[event]
        handler(frame, arg, elapsed)

        self.last_event_tick = self.get_time()

    def handle_event_call(self, frame, arg, elapsed):
        pass

    def handle_event_c_call(self, frame, arg, elapsed):
        pass

    def handle_event_return(self, frame, arg, elapsed):
        pass

    def handle_event_exception(self, frame, arg, elapsed):
        pass

    dispatch_table = {
        'call': handle_event_call,
        'exception': handle_event_exception,
        'return': handle_event_return,
        'c_call': handle_event_c_call,
        'c_exception': handle_event_return,  # the C function returned
        'c_return': handle_event_return,
    }

    def runcall(self, func, *args, **kw):
        self.last_event_tick = self.get_time()
        greenlet.settrace(self.dispatch_greenlet_event)
        sys.setprofile(self.dispatch_trace_event)
        try:
            return func(*args, **kw)
        finally:
            sys.setprofile(None)
            greenlet.settrace(None)


def main():
    def test1():
        start = time.time()
        for x in range(5000):
            for y in range(5000):
                _ = x*y
        print('test1 payload1 %s ms' % int(round((time.time() - start) * 1000)))

        print(12)
        # print(greenlet.getcurrent().parent)

        gr2.switch()
        # print(greenlet.getcurrent().parent)

        start = time.time()
        for a in range(10000):
            for b in range(10000):
                _ = a*b
        print('test1 payload2 %s ms' % int(round((time.time() - start) * 1000)))

        print(34)
        gr2.switch()
        print(910)

    def test2():
        print(56)
        # print(greenlet.getcurrent().parent)
        gr1.switch()
        # print(greenlet.getcurrent().parent)

        start = time.time()
        for x in range(5000):
            for y in range(5000):
                _ = x*y
        print('test2 payload %s ms' % int(round((time.time() - start) * 1000)))

        print(78)
        gr1.switch()
        print(1112)

    # print(greenlet.getcurrent())

    gr1 = greenlet(test1)
    gr2 = greenlet(test2)
    gr1.switch()

    # print(greenlet.getcurrent())


def main_sync():
    def test1():
        print('test1')
        test2()

    def test2():
        print('test2')
        test3()

    def test3():
        print('test3')
        for x in range(5000):
            for y in range(5000):
                _ = x*y

    test1()
    test3()

p = Profile()
p.runcall(main)
p.print_stats()
