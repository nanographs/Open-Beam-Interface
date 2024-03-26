import unittest
import struct
from amaranth.sim import Simulator, Tick
from amaranth import Signal

from . import StreamSignature
from . import Supersampler, RasterScanner, RasterRegion
from . import CommandParser, CommandExecutor, Command


def put_stream(stream, payload):
    if isinstance(payload, dict):
        for field, value in payload.items():
            yield getattr(stream.payload, field).eq(value)
    else:
        yield stream.payload.eq(payload)

    yield stream.valid.eq(1)
    ready = False
    timeout = 0
    while not ready:
        ready = (yield stream.ready)
        yield Tick()
        timeout += 1; assert timeout < 15
    yield stream.valid.eq(0)


def get_stream_nosample(stream, payload):
    yield stream.ready.eq(1)
    valid = False
    timeout = 0
    while not valid:
        valid = (yield stream.valid)
        if isinstance(payload, dict):
            value = {}
            for field in payload:
                value[field] = (yield getattr(stream.payload, field))
        else:
            value = (yield stream.payload)
        print(f"get_stream {valid=} {value=}")
        yield Tick()
        timeout += 1; assert timeout < 15
    yield stream.ready.eq(0)

    if isinstance(payload, dict):
        for field in payload:
            assert value[field] == payload[field], \
                f"payload.{field}: {value[field]} != {payload[field]} (expected)"
    else:
        assert value == payload, \
            f"payload: {value} != {payload} (expected)"


def get_stream(stream, payload):
    yield stream.ready.eq(1)
    valid = False
    timeout = 0
    while not valid:
        valid, data = (yield Tick(sample=[stream.valid, stream.payload]))
        data = stream.payload.shape().from_bits(data)
        if isinstance(payload, dict):
            value = {}
            for field in payload:
                value[field] = getattr(data, field)
        else:
            value = (yield stream.payload)
        print(f"get_stream {valid=} {value=}")
        timeout += 1; assert timeout < 15
    yield stream.ready.eq(0)

    if isinstance(payload, dict):
        for field in payload:
            assert value[field] == payload[field], \
                f"payload.{field}: {value[field]} != {payload[field]} (expected)"
    else:
        assert value == payload, \
            f"payload: {value} != {payload} (expected)"




class OBIAppletTestCase(unittest.TestCase):
    def simulate(self, dut, testbenches, *, name="test"):
        sim = Simulator(dut)
        sim.add_clock(20.83e-9)
        for testbench in testbenches:
            sim.add_testbench(testbench)
        with sim.write_vcd(f"{name}.vcd"), sim.write_vcd(f"{name}+d.vcd", fs_per_delta=250_000):
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
                    yield from get_stream_nosample(dut.super_dac_stream,
                        {"dac_x_code": 123, "dac_y_code": 456, "last": int(index == dwell)})
                assert (yield dut.super_dac_stream.valid) == 0

            self.simulate(dut, [put_testbench, get_testbench], name="ss_expand")

        run_test(0)
        run_test(1)
        run_test(2)

    def test_supersampler_average1(self):
        dut = Supersampler()

        def put_testbench():
            yield from put_stream(dut.super_adc_stream,
                {"adc_code": 123, "adc_ovf": 0, "last": 1})

        def get_testbench():
            yield from get_stream_nosample(dut.adc_stream,
                {"adc_code": 123})
            assert (yield dut.adc_stream.valid) == 0

        self.simulate(dut, [put_testbench, get_testbench], name = "ss_avg1")

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
            yield from get_stream_nosample(dut.adc_stream,
                {"adc_code": (456+123)//2})
            assert (yield dut.adc_stream.valid) == 0

        self.simulate(dut, [put_testbench, get_testbench], name = "ss_avg2")

    def test_raster_scanner(self):
        dut = RasterScanner()

        def put_testbench():
            yield from put_stream(dut.roi_stream, {
                "x_start": 5, "x_count": 2, "x_step": 0x2_00,
                "y_start": 9, "y_count": 1, "y_step": 0x5_00,
            })
            yield from put_stream(dut.dwell_stream, 1)
            yield from put_stream(dut.dwell_stream, 2)
            yield from put_stream(dut.dwell_stream, 3)
            yield from put_stream(dut.dwell_stream, 7)
            yield from put_stream(dut.dwell_stream, 8)
            yield from put_stream(dut.dwell_stream, 9)

        def get_testbench():
            yield from get_stream(dut.dac_stream, {"dac_x_code": 5, "dac_y_code": 9,  "dwell_time": 1})
            yield from get_stream(dut.dac_stream, {"dac_x_code": 7, "dac_y_code": 9,  "dwell_time": 2})
            yield from get_stream(dut.dac_stream, {"dac_x_code": 9, "dac_y_code": 9,  "dwell_time": 3})
            yield from get_stream(dut.dac_stream, {"dac_x_code": 5, "dac_y_code": 14, "dwell_time": 7})
            yield from get_stream(dut.dac_stream, {"dac_x_code": 7, "dac_y_code": 14, "dwell_time": 8})
            yield from get_stream(dut.dac_stream, {"dac_x_code": 9, "dac_y_code": 14, "dwell_time": 9})
            assert (yield dut.dac_stream.valid) == 0
            assert (yield dut.roi_stream.ready) == 1

        self.simulate(dut, [get_testbench,put_testbench], name = "raster_scanner")  

    def test_command_parser(self):
        dut = CommandParser()

        def test_synchronize_cmd():
            def put_testbench():
                yield from put_stream(dut.usb_stream, 0)
                yield from put_stream(dut.usb_stream, 1)
                yield from put_stream(dut.usb_stream, 123)
                yield from put_stream(dut.usb_stream, 234)

            def get_testbench():
                yield from get_stream(dut.cmd_stream, {"type":Command.Type.Synchronize})
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_sync")  
        
        def test_rasterregion_cmd():
            def put_testbench():
                cmd = struct.pack('>BHHHHHH', 0x10, 5, 2, 0x2_00, 9, 1, 0x5_00)
                for b in cmd:
                    yield from put_stream(dut.usb_stream, b)

            def get_testbench():
                yield from get_stream(dut.cmd_stream, {"type":Command.Type.RasterRegion})
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_rasterregion")

        def test_rasterpixel_cmd():
            def put_testbench():
                cmd = struct.pack('>BH', 0x11, 2)
                for b in cmd:
                    print(f'b: {b}')
                    yield from put_stream(dut.usb_stream, b)
                for n in [1,2]:
                    print(f'n: {n}')
                    yield from put_stream(dut.usb_stream, 0)
                    yield from put_stream(dut.usb_stream, n)

            def get_testbench():
                yield from get_stream(dut.cmd_stream, {"type":Command.Type.RasterPixel})
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_rasterpixel")  
        
        def test_rasterpixelrun_cmd():
            def put_testbench():
                cmd = struct.pack('>BHH', 0x12, 2, 2)
                for b in cmd:
                    print(f'b: {b}')
                    yield from put_stream(dut.usb_stream, b)


            def get_testbench():
                yield from get_stream(dut.cmd_stream, {"type":Command.Type.RasterPixelRun})
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_rasterpixelrun")  
        
        def test_vectorpixel_cmd():
            def put_testbench():
                cmd = struct.pack('>BHHH', 0x13, 2, 2, 2)
                for b in cmd:
                    print(f'b: {b}')
                    yield from put_stream(dut.usb_stream, b)


            def get_testbench():
                yield from get_stream(dut.cmd_stream, {"type":Command.Type.VectorPixel})
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_vectorpixel")  

        test_synchronize_cmd()
        test_rasterregion_cmd()
        test_rasterpixel_cmd()
        test_rasterpixelrun_cmd()
        test_vectorpixel_cmd()




