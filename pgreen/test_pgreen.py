import unittest

from greenlet import greenlet

from pgreen.pgreen import PGreen


class PGreenTestCase(unittest.TestCase):
    def test_1(self):
        def foo():
            pass

        profiler = PGreen()
        profiler.attach()

        foo()

        profiler.detach()


def scenario():
    # import time

    def test1():
        # start = time.time()
        for x in range(5000):
            for y in range(5000):
                _ = x*y
        # print('test1 payload1 %s ms' % int(round((time.time() - start) * 1000)))

        print(12)
        # print(greenlet.getcurrent().parent)

        gr2.switch()
        # print(greenlet.getcurrent().parent)

        # start = time.time()
        for a in range(10000):
            for b in range(10000):
                _ = a*b
        # print('test1 payload2 %s ms' % int(round((time.time() - start) * 1000)))

        print(34)
        gr2.switch()
        print(910)

    def test2():
        print(56)
        # print(greenlet.getcurrent().parent)
        gr1.switch()
        # print(greenlet.getcurrent().parent)

        # start = time.time()
        for x in range(5000):
            for y in range(5000):
                _ = x*y
        # print('test2 payload %s ms' % int(round((time.time() - start) * 1000)))

        print(78)
        gr1.switch()
        print(1112)

    # print(greenlet.getcurrent())

    gr1 = greenlet(test1)
    gr2 = greenlet(test2)
    gr1.switch()

    # print(greenlet.getcurrent())


# def main_sync():
#     def test1():
#         print('test1')
#         test2()
#
#     def test2():
#         print('test2')
#         test3()
#
#     def test3():
#         print('test3')
#         for x in range(5000):
#             for y in range(5000):
#                 _ = x*y
#
#     test1()
#     test3()
