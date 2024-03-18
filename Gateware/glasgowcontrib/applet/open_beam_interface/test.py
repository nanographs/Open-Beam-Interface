import unittest
from amaranth import *
from amaranth.sim import Simulator, Tick, Active

from . import StreamSignature
from . import Supersampler, RasterScanner, RasterRegion


def put_stream(stream, data):
    if isinstance(data, dict):
        for field, value in data.items():
            yield getattr(stream.data, field).eq(value)
    else:
        yield stream.data.eq(data)

    yield stream.valid.eq(1)
    yield Tick()
    timeout = 0
    while not (yield stream.ready):
        yield Tick()
        timeout += 1; assert timeout < 10
    yield stream.valid.eq(0)


def get_stream(stream, data):
    timeout = 0
    while not (yield stream.valid):
        yield Tick()
        timeout += 1; assert timeout < 10

    if isinstance(data, dict):
        for field, value in data.items():
            assert (yield getattr(stream.data, field)) == value, \
                f"{field}: {yield getattr(stream.data, field)} != {value}"
    else:
        assert (yield stream.data) == value, \
            f"data: {yield stream.data} != {value}"

    yield stream.ready.eq(1)
    yield Tick()
    yield stream.ready.eq(0)


class OBIAppletTestCase(unittest.TestCase):
    def simulate(self, dut, testbenches, setup = None):
        sim = Simulator(dut)
        sim.add_clock(20.83e-9)
        for testbench in testbenches:
            sim.add_testbench(testbench)
        with sim.write_vcd("test.vcd"):
            sim.run()

    def test_supersampler_expand(self):
        def run_test(dwell):
            print(f"dwell {dwell}")
            dut = Supersampler()

            def put_testbench():
                yield from put_stream(dut.dac_stream,
                    {"dac_x_code": 123, "dac_y_code": 456, "dwell_time": dwell})

            def get_testbench():
                for index in range(dwell + 1):
                    yield from get_stream(dut.super_dac_stream,
                        {"dac_x_code": 123, "dac_y_code": 456, "last": int(index == dwell)})
                assert (yield dut.super_dac_stream.valid) == 0

            self.simulate(dut, [put_testbench, get_testbench])

        run_test(0)
        run_test(1)
        run_test(2)

    def test_supersampler_average1(self):
        dut = Supersampler()

        def put_testbench():
            yield from put_stream(dut.super_adc_stream,
                {"adc_code": 123, "adc_ovf": 0, "last": 1})

        def get_testbench():
            yield from get_stream(dut.adc_stream,
                {"adc_code": 123})
            assert (yield dut.adc_stream.valid) == 0

        self.simulate(dut, [put_testbench, get_testbench])

    def test_supersampler_average2(self):
        dut = Supersampler()

        def put_testbench():
            yield from put_stream(dut.super_adc_stream,
                {"adc_code": 456, "adc_ovf": 0, "last": 0})
            yield from put_stream(dut.super_adc_stream,
                {"adc_code": 123, "adc_ovf": 0, "last": 1})
            yield from put_stream(dut.super_adc_stream,
                {"adc_code": 999, "adc_ovf": 0, "last": 0})

        def get_testbench():
            yield from get_stream(dut.adc_stream,
                {"adc_code": (456+123)//2})
            assert (yield dut.adc_stream.valid) == 0

        self.simulate(dut, [put_testbench, get_testbench])

    def test_raster_scanner(self):
        dut = RasterScanner()

        x_start = 5
        x_count = 3
        x_step = 0x2_00
        y_start = 9
        y_count = 2
        y_step = 0x5_00

        dwell_times = [1,2,3,7,8,9]

        def setup_testbench():
            yield from put_stream(dut.roi_stream, {
                "x_start": x_start, "x_count": x_count, "x_step": x_step,
                "y_start": y_start, "y_count": y_count, "y_step": y_step,
            })

        def put_testbench():
            for dwell_time in dwell_times:
                yield from put_stream(dut.dwell_stream, dwell_time)

        def frame(x_start, x_count, x_step, y_start, y_count, y_step):
            _x_step = float(x_step/256)
            _y_step = float(y_step/256)
            x_accum = x_start
            y_accum = y_start
            for y in range(y_count+1):
                for x in range(x_count+1):
                    yield x_accum, y_accum
                    x_accum += _x_step
                x_accum = x_start
                y_accum += _y_step

        self.frame = frame(x_start, x_count, x_step, y_start, y_count, y_step)

        def get_testbench():
            for dwell_time in dwell_times:
                x_accum, y_accum = next(self.frame)
                yield from get_stream(dut.dac_stream, 
                        {"dac_x_code":x_accum, "dac_y_code":y_accum, "dwell_time":dwell_time})
            assert (yield dut.dac_stream.valid) == 0

        self.simulate(dut, [setup_testbench, put_testbench, get_testbench])



                            


            # yield from get_stream(dut.dac_stream, {"dac_x_code": 5, "dac_y_code": 9,  "dwell_time": 1})
            # yield from get_stream(dut.dac_stream, {"dac_x_code": 7, "dac_y_code": 9,  "dwell_time": 2})
            # yield from get_stream(dut.dac_stream, {"dac_x_code": 9, "dac_y_code": 9,  "dwell_time": 3})
            # yield from get_stream(dut.dac_stream, {"dac_x_code": 5, "dac_y_code": 11, "dwell_time": 7})
            # yield from get_stream(dut.dac_stream, {"dac_x_code": 7, "dac_y_code": 11, "dwell_time": 8})
            # yield from get_stream(dut.dac_stream, {"dac_x_code": 9, "dac_y_code": 11, "dwell_time": 9})

            # yield from put_stream(dut.dwell_stream, 1)
            # yield from put_stream(dut.dwell_stream, 2)
            # yield from put_stream(dut.dwell_stream, 3)
            # yield from put_stream(dut.dwell_stream, 7)
            # yield from put_stream(dut.dwell_stream, 8)
            # yield from put_stream(dut.dwell_stream, 9)