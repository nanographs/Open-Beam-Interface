import unittest
import struct
from amaranth.sim import Simulator, Tick
from amaranth import Signal, ShapeCastable, Const

from . import StreamSignature
from . import Supersampler, RasterScanner, RasterRegion
from . import CommandParser, CommandExecutor, Command


def put_dict(stream, signal):
    for sig_field, sig_value in signal.items():
        new_stream = getattr(stream, sig_field)
        if isinstance(sig_value, dict):
            yield from put_dict(new_stream, sig_value)
        else:
            yield new_stream.eq(sig_value)


def put_stream(stream, payload, timeout_steps=10):
    # if isinstance(payload, dict):
    #     for field, value in payload.items():
    #         yield getattr(stream.payload, field).eq(value)
    # else:
    #     yield stream.payload.eq(payload)

    if isinstance(payload, dict):
        yield from put_dict(stream.payload, payload)
    else:
        yield stream.payload.eq(payload)
    

    yield stream.valid.eq(1)
    ready = False
    timeout = 0
    while not ready:
        ready = (yield stream.ready)
        yield Tick()
        timeout += 1; assert timeout < timeout_steps
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
            f"payload: {value!r} != {payload!r} (expected)"

def unpack_const(data):
    newmembers = {}
    members = data.shape().members
    for member in members:
        field = data.__getattr__(member)
        newmembers[member] = field
    return newmembers

def unpack_dict(data):
    all_data = {}
    for member in data:
        try:
            unpacked_data = unpack_const(data.get(member))
            all_data[member] = unpack_dict(unpacked_data)
        except Exception as e:
            all_data[member] = data.get(member)
    return all_data

def prettier_print(data):
    try:
        data = unpack_const(data)
        if isinstance(data, dict):
            all_data = unpack_dict(data)
        else:
            all_data = data
    except: all_data = data
    return all_data
    

def get_stream(stream, payload, timeout_steps=10):
    yield stream.ready.eq(1)
    valid = False
    timeout = 0
    while not valid:
        valid, data = (yield Tick(sample=[stream.valid, stream.payload]))
        if isinstance(stream.payload.shape(), ShapeCastable):
            data = stream.payload.shape().from_bits(data)
        # print(f"get_stream {valid=} {data=}\n")
        print(f'get_stream {valid=} {prettier_print(data)}')
        timeout += 1; assert timeout < timeout_steps
    yield stream.ready.eq(0)
    if isinstance(payload, dict):
        wrapped_payload = stream.payload.shape().const(payload)
    else:
        wrapped_payload = payload
    assert data == wrapped_payload,\
        f"payload: {prettier_print(data)} != {prettier_print(payload)} (expected)"




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
                    yield from get_stream(dut.super_dac_stream,
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
            yield from get_stream(dut.adc_stream,
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
            yield from get_stream(dut.adc_stream,
                {"adc_code": (456+123)//2})
            assert (yield dut.adc_stream.valid) == 0

        self.simulate(dut, [put_testbench, get_testbench], name = "ss_avg2")

    def test_raster_scanner(self):
        dut = RasterScanner()

        def put_testbench():
            yield from put_stream(dut.roi_stream, {
                "x_start": 5, "x_count": 3, "x_step": 0x2_00,
                "y_start": 9, "y_count": 2, "y_step": 0x5_00,
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
                yield from put_stream(dut.usb_stream, 0) #Type
                yield from put_stream(dut.usb_stream, 123) #Cookie
                yield from put_stream(dut.usb_stream, 234)
                yield from put_stream(dut.usb_stream, 1) #Raster Mode

            def get_testbench():
                yield from get_stream(dut.cmd_stream, {
                            "type": Command.Type.Synchronize, 
                            "payload": {
                                "synchronize": {
                                    "cookie": 123*256 + 234,
                                    "raster_mode": 1,
                                }
                            }})
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_sync")  
        
        def test_rasterregion_cmd():
            def put_testbench():
                cmd = struct.pack('>BHHHHHH', 0x10, 5, 2, 0x2_00, 9, 1, 0x5_00)
                for b in cmd:
                    yield from put_stream(dut.usb_stream, b, timeout_steps=15)

            def get_testbench():
                yield from get_stream(dut.cmd_stream, {
                            "type":Command.Type.RasterRegion,
                            "payload": {
                                "raster_region": {
                                    "x_start": 5,
                                    "x_count": 2,
                                    "x_step": 0x2_00,
                                    "y_start": 9,
                                    "y_count": 1,
                                    "y_step": 0x5_00
                                }
                            }}, timeout_steps = 15)
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_rasterregion")

        def test_rasterpixel_cmd():
            def put_testbench():
                cmd = struct.pack('>BH', 0x11, 2)
                for b in cmd:
                    yield from put_stream(dut.usb_stream, b)
                for n in [1,2]:
                    yield from put_stream(dut.usb_stream, 0)
                    yield from put_stream(dut.usb_stream, n)

            def get_testbench():
                yield from get_stream(dut.cmd_stream, {
                            "type": Command.Type.RasterPixel,
                            "payload": {
                                "raster_pixel": 1
                            }})
                yield from get_stream(dut.cmd_stream, {
                            "type": Command.Type.RasterPixel,
                            "payload": {
                                "raster_pixel": 2
                            }})
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_rasterpixel")  
        
        def test_rasterpixelrun_cmd():
            def put_testbench():
                cmd = struct.pack('>BHH', 0x12, 2, 1)
                for b in cmd:
                    yield from put_stream(dut.usb_stream, b)

            def get_testbench():
                yield from get_stream(dut.cmd_stream, {
                    "type":Command.Type.RasterPixelRun,
                    "payload": {
                        "raster_pixel_run": {
                            "length": 2,
                            "dwell_time": 1
                        }
                    }})
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_rasterpixelrun")  

        def test_rasterfreescan_cmd():
            def put_testbench():
                cmd = struct.pack('>BH', 0x13, 2)
                for b in cmd:
                    yield from put_stream(dut.usb_stream, b)

            def get_testbench():
                yield from get_stream(dut.cmd_stream, {
                    "type":Command.Type.RasterFreeScan,
                    "payload": {
                        "raster_pixel": 2
                        }
                    })
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_rasterfreescan")  
        
        def test_vectorpixel_cmd():
            def put_testbench():
                cmd = struct.pack('>BHHH', 0x14, 1, 2, 3)
                for b in cmd:
                    yield from put_stream(dut.usb_stream, b)

            def get_testbench():
                yield from get_stream(dut.cmd_stream, {
                    "type":Command.Type.VectorPixel,
                    "payload": {
                        "vector_pixel": {
                            "x_coord": 1,
                            "y_coord": 2,
                            "dwell_time": 3
                        }
                    }})
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_vectorpixel")  

        test_synchronize_cmd()
        test_rasterregion_cmd()
        test_rasterpixel_cmd()
        test_rasterpixelrun_cmd()
        test_rasterfreescan_cmd()
        test_vectorpixel_cmd()
    

    def test_command_executor(self):
        dut = CommandExecutor(loopback=False)

        def test_sync_exec():
            cookie = 123*256 + 234

            def put_testbench():
                yield from put_stream(dut.cmd_stream, {
                    "type": Command.Type.Synchronize,
                    "payload": {
                        "synchronize": {
                            "cookie": cookie,
                            "raster_mode": 1
                        }
                    }
                })
            
            def get_testbench():
                yield from get_stream(dut.img_stream, 65535) # FFFF
                yield from get_stream(dut.img_stream, cookie)
        
            self.simulate(dut, [put_testbench, get_testbench], name = "exec_sync")  

        def test_rasterregion_exec():

            def put_testbench():
                yield from put_stream(dut.cmd_stream, {
                    "type": Command.Type.RasterRegion,
                    "payload": {
                        "raster_region": {
                            "x_start": 5,
                            "x_count": 2,
                            "x_step": 0x2_00,
                            "y_start": 9,
                            "y_count": 1,
                            "y_step": 0x5_00,
                        }
                    }
                })

            def get_testbench():
                yield from get_stream(dut.raster_scanner.roi_stream, 
                        {   "x_start": 5,
                            "x_count": 2,
                            "x_step": 0x2_00,
                            "y_start": 9,
                            "y_count": 1,
                            "y_step": 0x5_00}, timeout_steps=30)

            self.simulate(dut, [get_testbench,put_testbench], name = "exec_rasterregion")  

        def test_rasterpixel_exec():

            def put_testbench():
                yield from put_stream(dut.cmd_stream, {
                    "type": Command.Type.RasterPixel,
                    "payload": {
                        "raster_pixel": 1
                    }
                })

            def get_testbench():
                yield from get_stream(dut.raster_scanner.dwell_stream, 1)

            self.simulate(dut, [get_testbench,put_testbench], name = "exec_rasterpixel")  
        
        def test_rasterpixelrun_exec():

            def put_testbench():
                yield from put_stream(dut.cmd_stream, {
                    "type": Command.Type.RasterPixelRun,
                    "payload": {
                        "raster_pixel_run": {
                            "length": 2,
                            "dwell_time": 1,
                        } 
                    }
                })

            def get_testbench():
                yield from get_stream(dut.raster_scanner.dwell_stream, 1)
                yield from get_stream(dut.raster_scanner.dwell_stream, 1)

            self.simulate(dut, [get_testbench,put_testbench], name = "exec_rasterpixelrun")  

        test_sync_exec()
        test_rasterregion_exec()
        test_rasterpixel_exec()
        test_rasterpixelrun_exec()







