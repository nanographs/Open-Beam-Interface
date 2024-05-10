import unittest
import struct
import array
from amaranth.sim import Simulator, Tick
from amaranth import Signal, ShapeCastable, Const
from abc import ABCMeta, abstractmethod

from . import StreamSignature
from . import Supersampler, RasterScanner, RasterRegion
from . import CommandParser, CommandExecutor, Command, BeamType, OutputMode, CmdType
from . import BusController, Flippenator
from .base_commands import *


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
        f"payload: {prettier_print(data)} != {prettier_print(wrapped_payload)} (expected)"
        



class OBIAppletTestCase(unittest.TestCase):
    def simulate(self, dut, testbenches, *, name="test"):
        sim = Simulator(dut)
        sim.add_clock(20.83e-9)
        for testbench in testbenches:
            sim.add_testbench(testbench)
        with sim.write_vcd(f"{name}.vcd"), sim.write_vcd(f"{name}+d.vcd", fs_per_delta=250_000):
            sim.run()

    def test_bus_controller(self):
        dut = BusController(adc_half_period=3, adc_latency=6)
        def put_testbench():
            yield from put_stream(dut.dac_stream, {"dac_x_code": 123, "dac_y_code": 456, "last": 1})

        def get_testbench():
            yield from get_stream(dut.adc_stream, {"adc_code": 0, "last": 1}, timeout_steps=100)

        self.simulate(dut, [put_testbench, get_testbench], name="bus_controller")

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

    def test_flippenator(self):
        dut = Flippenator()

        def test_xflip():
            def put_testbench():
                yield dut.xflip.eq(1)
                yield from put_stream(dut.in_stream, {
                    "dac_x_code": 1,
                    "dac_y_code": 16383,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            def get_testbench():
                yield from get_stream(dut.out_stream, {
                    "dac_x_code": 16383,
                    "dac_y_code": 16383,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            self.simulate(dut, [get_testbench,put_testbench], name="flippenator_xflip")  
        
        def test_yflip():
            def put_testbench():
                yield dut.yflip.eq(1)
                yield from put_stream(dut.in_stream, {
                    "dac_x_code": 1,
                    "dac_y_code": 16383,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            def get_testbench():
                yield from get_stream(dut.out_stream, {
                    "dac_x_code": 1,
                    "dac_y_code": 1,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            self.simulate(dut, [get_testbench,put_testbench], name="flippenator_yflip") 
        def test_rot90():
            def put_testbench():
                yield dut.rotate90.eq(1)
                yield from put_stream(dut.in_stream, {
                    "dac_x_code": 1,
                    "dac_y_code": 16383,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            def get_testbench():
                yield from get_stream(dut.out_stream, {
                    "dac_x_code": 16383,
                    "dac_y_code": 1,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            self.simulate(dut, [get_testbench,put_testbench], name="flippenator_rot90")  
        test_xflip()
        test_yflip()
        test_rot90()

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
    
    def test_command_parser_2(self):
        dut = CommandParser()

        def test_cmd(command:BaseCommand, response: dict, name:str="cmd"):
            def put_testbench():
                for byte in command.message:
                    yield from put_stream(dut.usb_stream, byte)
            def get_testbench():
                yield from get_stream(dut.cmd_stream, response)
                assert (yield dut.cmd_stream.valid) == 0
            self.simulate(dut, [get_testbench,put_testbench], name="parse_" + name)  

        c = Command.serialize(CmdType.Command4, payload = 1234)
        
        # test_cmd(SynchronizeCommand(cookie=1024, raster=True, output=OutputMode.NoOutput),
        #         {"type": CmdType.Synchronize, 
        #             "payload": {
        #                 "synchronize": {
        #                     "mode": {
        #                         "raster": 1,
        #                         "output": 2,
        #                     },
        #                     "cookie": 1024,
        #         }}}, "cmd_sync")

        # test_cmd(DelayCommand(delay=960),
        #         {"type": Command.Type.Delay, 
        #                     "payload": {
        #                         "delay": 960}
        #         }, "cmd_delay")
        # test_cmd(DelayCommand(delay=960),
        #         {"type": Command.Type.Delay, 
        #                     "payload": {
        #                         "delay": 960}
        #         }, "cmd_delay")
        
        # test_cmd(ExtCtrlCommand(),
        #         {"type": Command.Type.ExtCtrl, 
        #                 "payload": {"external_ctrl": {"enable": 1}}
        #         }, "cmd_extctrlenable")
        # test_cmd(ExtCtrlCommand(),
        #         {"type": Command.Type.ExtCtrl, 
        #                 "payload": {"external_ctrl": {"enable": 1}}
        #         }, "cmd_extctrlenable")
        
        # test_cmd(BeamSelectCommand(),
        #         {"type": Command.Type.BeamSelect, 
        #                     "payload": {"beam_type": BeamType.Electron}
        #         }, "cmd_selectebeam")
        # test_cmd(BeamSelectCommand(),
        #         {"type": Command.Type.BeamSelect, 
        #                     "payload": {"beam_type": BeamType.Electron}
        #         }, "cmd_selectebeam")
        
        # test_cmd(BlankCommand(),
        #         {"type": Command.Type.Blank, 
        #                     "payload": {"blank": {"enable": 1, "inline": 0}}
        #         }, "cmd_blank")
        # test_cmd(BlankCommand(),
        #         {"type": Command.Type.Blank, 
        #                     "payload": {"blank": {"enable": 1, "inline": 0}}
        #         }, "cmd_blank")
        
        # test_cmd(RasterRegionCommand(x_start=5, x_count=2, x_step=0x2_00, 
        #                             y_start = 9, y_count = 1, y_step = 0x5_00))

    def test_command_parser_1(self):
        dut = CommandParser()


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

        def test_rasterpixelfreerun_cmd():
            def put_testbench():
                cmd = struct.pack('>BH', 0x13, 2)
                for b in cmd:
                    yield from put_stream(dut.usb_stream, b)

            def get_testbench():
                yield from get_stream(dut.cmd_stream, {
                    "type":Command.Type.RasterPixelFreeRun,
                    "payload": {
                        "raster_pixel": 2
                        }
                    })
                assert (yield dut.cmd_stream.valid) == 0

            self.simulate(dut, [get_testbench,put_testbench], name = "cmd_rasterpixelfreerun")  
        
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

        test_rasterregion_cmd()
        test_rasterpixel_cmd()
        test_rasterpixelrun_cmd()
        test_rasterpixelfreerun_cmd()
        test_vectorpixel_cmd()
    

    def test_command_executor_individual(self):
        dut = CommandExecutor()

        def test_sync_exec():
            cookie = 123*256 + 234

            def put_testbench():
                yield from put_stream(dut.cmd_stream, {
                    "type": Command.Type.Synchronize,
                    "payload": {
                        "synchronize": {
                            "cookie": cookie,
                            "mode" : {
                                "raster": 1,
                                "output": 0,
                                }
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

    def test_command_executor_sequences(self):
        BUS_CYCLES = 6 ## length of one cycle of DAC/ADC clock
        class TestCommand:

            @property
            @abstractmethod
            def _command(self):
                pass

            @property
            @abstractmethod
            def _response(self):
                pass

            def _put_testbench(self, dut, timeout_steps=100):
                print(f"put_testbench: {self._command}")
                yield from put_stream(dut.cmd_stream, self._command, timeout_steps=2*timeout_steps)
            
            def _get_testbench(self, dut, timeout_steps=100):
                print(f"get_testbench: response to {self._command}")
                n = 0
                print(f"getting {len(self._response)} responses")
                for res in self._response:
                    yield from get_stream(dut.img_stream, res, timeout_steps=timeout_steps)
                    n += 1
                    print(f"got {n} responses")
                print(f"got all {len(self._response)} responses")

        class TestCommandSequence:
            dut =  CommandExecutor()
            _put_testbenches = []
            _get_testbenches = []
        
            def add(self, command: TestCommand, timeout_steps=100):
                self._put_testbenches.append(command._put_testbench(self.dut, timeout_steps))
                self._get_testbenches.append(command._get_testbench(self.dut, timeout_steps))
            
            def _put_testbench(self):
                for testbench in self._put_testbenches:
                    yield from testbench
            
            def _get_testbench(self):
                for testbench in self._get_testbenches:
                    yield from testbench

        class TestSyncCommand(TestCommand):
            def __init__(self, cookie, raster_mode, output_mode=0):
                self._cookie = cookie
                self._raster_mode = raster_mode
                self._output_mode = output_mode
            
            @property
            def _command(self):
                return {"type": Command.Type.Synchronize,
                        "payload": {
                            "synchronize": {
                                "cookie": self._cookie,
                                "mode": {
                                    "raster": self._raster_mode,
                                    "output": self._output_mode, 
                                    }
                                }
                            }
                        }
                    
            @property
            def _response(self):
                return [65535, self._cookie]
        
        class TestDelayCommand(TestCommand):
            def __init__(self, delay):
                self._delay = delay

            @property
            def _command(self):
                return {"type": Command.Type.Delay,
                        "payload": {
                            "delay": self._delay
                            }
                        }
                    
            @property
            def _response(self):
                return []

        class TestFlushCommand(TestCommand):
            @property
            def _command(self):
                return {"type": Command.Type.Flush,}
                    
            @property
            def _response(self):
                return []

        
        class TestExtCtrlCommand(TestCommand):
            def __init__(self, enable: bool):
                self._enable = enable
            
            @property
            def _command(self):
                if self._enable:
                    return {"type": Command.Type.EnableExtCtrl,
                            "payload": {
                                "external_ctrl": {
                                    "enable": 1,
                                    }
                                }
                            }
                if not self._enable:
                    return {"type": Command.Type.DisableExtCtrl,
                            "payload": {
                                "external_ctrl": {
                                    "enable": 0,
                                    }
                                }
                            }
                    
            @property
            def _response(self):
                return []
        
        class TestBeamSelectCommand(TestCommand):
            def __init__(self, beam_type: BeamType):
                self._beam_type = beam_type
            
            @property
            def _command(self):
                if self._beam_type == BeamType.Electron:
                    return {"type": Command.Type.SelectEbeam,
                            "payload": {
                                "beam_type": BeamType.Electron
                                }
                            }
                elif self._beam_type == BeamType.Ion:
                    return {"type": Command.Type.SelectIbeam,
                            "payload": {
                                "beam_type": BeamType.Ion
                                }
                            }
                else:
                    return {"type": Command.Type.SelectNoBeam,
                            "payload": {
                                "beam_type": BeamType.NoBeam
                                }
                            }

                    
            @property
            def _response(self):
                return []
        
        class TestBlankCommand(TestCommand):
            def __init__(self, enable:bool, inline:bool):
                self._enable = enable
                self._inline = inline
            
            @property
            def _command(self):
                if self._enable & ~self._inline:
                    return {"type": Command.Type.Blank,
                            "payload": {
                                "blank": {
                                    "enable": 1,
                                    "inline": 0
                                    }
                                }
                            }
                if self._enable & self._inline:
                    return {"type": Command.Type.BlankInline,
                            "payload": {
                                "blank": {
                                    "enable": 1,
                                    "inline": 1
                                    }
                                }
                            }
                if ~self._enable & ~self._inline:
                    return {"type": Command.Type.Unblank,
                            "payload": {
                                "blank": {
                                    "enable": 0,
                                    "inline": 0
                                    }
                                }
                            }
                if ~self._enable & self._inline:
                    return {"type": Command.Type.UnblankInline,
                            "payload": {
                                "blank": {
                                    "enable": 0,
                                    "inline": 1
                                    }
                                }
                            }
                    
            @property
            def _response(self):
                return []
        
        class TestRasterRegionCommand(TestCommand):
            def __init__(self, x_start, x_count, x_step, y_start, y_count, y_step):
                self._x_start = x_start
                self._x_count = x_count
                self._x_step = x_step
                self._y_start = y_start
                self._y_count = y_count
                self._y_step = y_step
            
            @property
            def _command(self):
                return {"type": Command.Type.RasterRegion,
                            "payload": {
                            "raster_region": {
                                "x_start": self._x_start,
                                "x_count": self._x_count,
                                "x_step": self._x_step,
                                "y_start": self._y_start,
                                "y_count": self._y_count,
                                "y_step": self._y_step,
                            }
                        }
                    }
                    
            @property
            def _response(self):
                return []
        
        class TestRasterPixelRunCommand(TestCommand):
            def __init__(self, length, dwell_time):
                self._length = length
                self._dwell_time = dwell_time

            @property
            def _command(self):
                return {"type": Command.Type.RasterPixelRun,
                        "payload": {
                            "raster_pixel_run": {
                                "length": self._length - 1,
                                "dwell_time": self._dwell_time
                            } 
                        }
                    }
                    
            @property
            def _response(self):
                return [0]*self._length

        class TestRasterPixelFreeRunCommand(TestCommand):
            def __init__(self, dwell_time: int, *, test_samples=6):
                self._dwell_time = dwell_time
                self._test_samples = test_samples
            
            @property
            def _command(self):
                return {"type": Command.Type.RasterPixelFreeRun,
                        "payload": {
                            "raster_pixel":self._dwell_time
                        }
                    }
                    
            @property
            def _response(self):
                return [0]*(self._test_samples)
            
            def _put_testbench(self, dut, timeout_steps):
                print("put_testbench: {self._command}")
                yield from put_stream(dut.cmd_stream, self._command, timeout_steps=timeout_steps)
                n = 0
                print(f"extending put_testbench for {self._test_samples=}")
                while True:
                    if n == self._test_samples:
                        break
                    if not (yield dut.supersampler.dac_stream.ready):
                        yield Tick()
                    else:
                        n += 1
                        print(f"{n} valid samples")
                        yield Tick()
        class TestVectorPixelCommand(TestCommand):
            def __init__(self, x_coord, y_coord, dwell_time):
                self._x_coord = x_coord
                self._y_coord = y_coord
                self._dwell_time = dwell_time

            @property
            def _command(self):
                return {"type": Command.Type.VectorPixel,
                        "payload": {
                            "vector_pixel": {
                                "x_coord": self._x_coord,
                                "y_coord": self._y_coord,
                                "dwell_time": self._dwell_time
                            } 
                        }
                    }
                    
            @property
            def _response(self):
                return [0]
        
        def test_exec_1():
            test_seq = TestCommandSequence()
            test_seq.add(TestSyncCommand(502, 1))
            test_seq.add(TestSyncCommand(505, 1))
            test_seq.add(TestRasterRegionCommand(5, 3, 0x2_00, 9, 2, 0x5_00))
            test_seq.add(TestRasterPixelRunCommand(5, 1))
            test_seq.add(TestSyncCommand(502, 1))
            test_seq.add(TestRasterPixelFreeRunCommand(1, test_samples=6))
            test_seq.add(TestSyncCommand(502, 1))
            test_seq.add(TestSyncCommand(502, 1))

            self.simulate(test_seq.dut, [test_seq._put_testbench, test_seq._get_testbench], name="exec_1")
        
        def test_exec_2():
            test_seq = TestCommandSequence()
            test_seq.add(TestExtCtrlCommand(enable=True))
            test_seq.add(TestBeamSelectCommand(beam_type=BeamType.Electron))
            test_seq.add(TestDelayCommand(960))
            test_seq.add(TestSyncCommand(505, 1), timeout_steps = 1000*BUS_CYCLES)
            test_seq.add(TestRasterRegionCommand(5, 3, 0x2_00, 9, 2, 0x5_00))
            test_seq.add(TestRasterPixelRunCommand(5, 1))

            self.simulate(test_seq.dut, [test_seq._put_testbench, test_seq._get_testbench], name="exec_2")
        
        def test_exec_3():
            test_seq = TestCommandSequence()
            test_seq.add(TestSyncCommand(502, 1))
            test_seq.add(TestSyncCommand(505, 1))
            test_seq.add(TestExtCtrlCommand(enable=True))
            test_seq.add(TestBeamSelectCommand(beam_type=BeamType.Electron))
            test_seq.add(TestDelayCommand(960))
            test_seq.add(TestRasterRegionCommand(5, 3, 0x2_00, 9, 2, 0x5_00), timeout_steps=960*BUS_CYCLES)
            test_seq.add(TestRasterPixelFreeRunCommand(1, test_samples=20), timeout_steps = 960*BUS_CYCLES)
            test_seq.add(TestSyncCommand(502, 1))
            test_seq.add(TestRasterRegionCommand(5, 3, 0x2_00, 9, 2, 0x5_00), timeout_steps=960*BUS_CYCLES)
            test_seq.add(TestRasterPixelFreeRunCommand(1, test_samples=20), timeout_steps = 960*BUS_CYCLES)
            test_seq.add(TestExtCtrlCommand(enable=True))
            test_seq.add(TestBeamSelectCommand(beam_type=BeamType.Electron))
            test_seq.add(TestDelayCommand(960))
            test_seq.add(TestSyncCommand(502, 1), timeout_steps = 960*BUS_CYCLES)

            self.simulate(test_seq.dut, [test_seq._put_testbench, test_seq._get_testbench], name="exec_3")
        
        def test_exec_4():
            test_seq = TestCommandSequence()
            test_seq.add(TestSyncCommand(502, 0))
            test_seq.add(TestVectorPixelCommand(100, 244, 3))
            test_seq.add(TestVectorPixelCommand(90, 144, 2))
            test_seq.add(TestVectorPixelCommand(110, 2004, 5))
            test_seq.add(TestSyncCommand(502, 0))

            self.simulate(test_seq.dut, [test_seq._put_testbench, test_seq._get_testbench], name="exec_4")
        
        def test_exec_5():
            test_seq = TestCommandSequence()
            test_seq.add(TestSyncCommand(502, 0, output_mode = 2)) #no output
            test_seq.add(TestFlushCommand())
            for n in range(100):
                test_seq.add(TestVectorPixelCommand(1, 1, 1))
                test_seq.add(TestVectorPixelCommand(16384, 16384, 1))
            test_seq.add(TestSyncCommand(502, 0))

            self.simulate(test_seq.dut, [test_seq._put_testbench, test_seq._get_testbench], name="exec_5")
        
        def test_exec_6():
            test_seq = TestCommandSequence()
            test_seq.add(TestExtCtrlCommand(enable=True))
            test_seq.add(TestBeamSelectCommand(beam_type=BeamType.Ion))
            test_seq.add(TestVectorPixelCommand(1, 1, 1))
            self.simulate(test_seq.dut, [test_seq._put_testbench, test_seq._get_testbench], name="exec_6")


        test_exec_1()
        test_exec_2()
        test_exec_3()
        test_exec_4()
        test_exec_5()
        test_exec_6()

    def test_all(self):
        from amaranth import Module
        from . import OBIApplet
        from glasgow.applet import GlasgowAppletTestCase, synthesis_test, applet_simulation_test
        from .board_sim import OBI_Board

        class OBIApplet_TestCase(GlasgowAppletTestCase, applet = OBIApplet):
            @synthesis_test
            def test_build(self):
                self.assertBuilds(args=["--pin-ext-ebeam-scan-enable", "1", "--xflip", "--yflip", "--rotate90"])
            
            def setup_test(self):
                self.build_simulated_applet()

            def setup_x_loopback(self):
                self.build_simulated_applet()
                obi_subtarget = self.applet.mux_interface._subtargets[0]
                m = Module()
                m.submodules["board"] = board = OBI_Board()
                m.d.comb += [
                            obi_subtarget.data.i.eq(board.a_latch_chip.q),
                            board.x_latch_chip.d.eq(obi_subtarget.data.o),
                            board.y_latch_chip.d.eq(obi_subtarget.data.o),
                            board.a_adc_chip.a.eq(board.x_dac_chip.a),
                            board.x_latch.eq(obi_subtarget.control.x_latch.o),
                            board.y_latch.eq(obi_subtarget.control.y_latch.o),
                            board.a_latch.eq(obi_subtarget.control.a_latch.o),
                            board.a_enable.eq(obi_subtarget.control.a_enable.o),
                            board.a_clock.eq(obi_subtarget.control.a_clock.o),
                            board.d_clock.eq(obi_subtarget.control.d_clock.o),
                            board.adc_input.eq(board.x_dac_chip.a)
                            ]
                self.target.add_submodule(m)
            
            @applet_simulation_test("setup_test")
            async def test_sync_cookie(self):
                iface = await self.run_simulated_applet()
                await iface.write(bytes([0, 123, 234, 1])) # sync, cookie, raster_mode
                self.assertEqual(await iface.read(4), bytes([0xFF, 0xFF, 123, 234])) # FF, FF, cookie
            
            @applet_simulation_test("setup_x_loopback", args=["tcp::2222"], interact=True)
            async def test_raster(self):
                iface = await self.run_simulated_applet()
                await iface.write(bytes([0, 123, 234, 1])) 
                self.assertEqual(await iface.read(4), bytes([0xFF, 0xFF, 123, 234])) # FF, FF, cookie
                await iface.write(struct.pack(">BHHHHHH", 0x10, 5,3, 0x2_00, 9,2, 0x5_00))
                await iface.write(struct.pack('>BHH', 0x12, 6, 2))
                data = await iface.read(12)
                print(data)
            
            @applet_simulation_test("setup_x_loopback")
            async def test_benchmark(self):
                iface = await self.run_simulated_applet()
                output_mode = 2 #no output
                raster_mode = 0 #no raster
                mode = int(output_mode<<1 | raster_mode)
                sync_cmd = struct.pack('>BHB', 0, 123, mode)
                flush_cmd = struct.pack('>B', 2)
                await iface.write(sync_cmd)
                await iface.write(flush_cmd)
                # await iface.flush()
                commands = bytearray()
                for _ in range(10):
                    await iface.write(VectorPixelCommand(x_coord=4, y_coord=4, dwell=1).message)
                    await iface.write(VectorPixelCommand(x_coord=16380, y_coord=16380, dwell=1).message)
                    await iface.write(VectorPixelCommand(x_coord=4, y_coord=16380, dwell=1).message)
                    await iface.write(VectorPixelCommand(x_coord=16380, y_coord=4, dwell=1).message)
            
            @applet_simulation_test("setup_x_loopback")
            async def test_loopback(self):
                iface = await self.run_simulated_applet()
                await iface.write(SynchronizeCommand(output=OutputMode.EightBit, raster=False, cookie=123*256+234).message)
                await iface.write(FlushCommand().message)
                self.assertEqual(await iface.read(4), bytes([0xFF, 0xFF, 123, 234])) # FF, FF, cookie
                # await iface.flush()
                commands = bytearray()
                for n in range(10):
                    await iface.write(VectorPixelCommand(x_coord=n, y_coord=n, dwell=1).message)
                self.assertEqual(await iface.read(10), bytes([x for x in range(10)]))


            @applet_simulation_test("setup_test", args=["--pin-ext-ibeam-scan-enable", "0", "--pin-ext-ibeam-scan-enable-2", "1"])
            async def test_vector_blank(self):
                iface = await self.run_simulated_applet()
                #await iface.write(struct.pack(">BHB", 0x00, 123, mode)) #sync
                await iface.write(SynchronizeCommand(cookie=4, output=2, raster=0).message)
                #await iface.write(struct.pack(">BB",0x05, combined)) ## blank
                await iface.write(BlankCommand().message)
                await iface.write(ExternalCtrlCommand(enable=True).message)
                await iface.write(SelectIbeamCommand().message)
                await iface.write(DelayCommand(delay=10).message)
                await iface.write(UnblankInlineCommand().message)
                for n in range(1,3):
                    await iface.write(VectorPixelCommand(x_coord=n, y_coord=n, dwell=1).message)
                # for n in range(1,3):
                #     await iface.write(VectorPixelCommand(x_coord=5*n, y_coord=5*n, dwell=4).message)
                await iface.write(VectorPixelCommand(x_coord=7, y_coord=7, dwell=3).message)
                await iface.write(BlankCommand().message)
                await iface.write(DelayCommand(delay=3).message)
                await iface.write(UnblankCommand().message)
                await iface.write(VectorPixelCommand(x_coord=1, y_coord=1, dwell=1).message)
                await iface.write(BlankCommand().message)
                await iface.write(SynchronizeCommand(cookie=4, output=2, raster=0).message)
                await iface.read(6)
                # await iface.write(ExternalCtrlCommand(enable=0, beam_type=2).message)
                # await iface.write(DelayCommand(delay=10).message)
                # for n in range(1,10):
                #     await iface.write(VectorPixelCommand(x_coord=2*n, y_coord=2*n, dwell=4).message)

                

            
        test_case = OBIApplet_TestCase()
        test_case.setUp()
        # test_case.test_build()
        # test_case.test_sync_cookie()
        test_case.test_raster()
        # test_case.test_benchmark()
        # test_case.test_vector_blank()
        # test_case.test_loopback()

        


        




