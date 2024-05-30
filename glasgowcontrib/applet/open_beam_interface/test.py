import unittest
import struct
import array
from amaranth.sim import Simulator, Tick
from amaranth import Signal, ShapeCastable, Const
from amaranth import DriverConflict
from abc import ABCMeta, abstractmethod

from . import StreamSignature
from . import Supersampler, RasterScanner, RasterRegion
from . import CommandParser, CommandExecutor, Command, BeamType, OutputMode, CmdType
from . import BusController, Flippenator
from glasgowcontrib.applet.open_beam_interface.base_commands import *



async def put_stream(ctx, stream, payload, timeout_steps=10):
    ctx.set(stream.payload, payload)
    ctx.set(stream.valid, 1)
    ready = False
    timeout = 0
    while not ready:
        ready = ctx.get(stream.ready)
        print(f"put_stream: {ready=}")
        await ctx.tick()
        timeout += 1; assert timeout < timeout_steps
    ctx.set(stream.valid, 0)




async def get_stream(ctx, stream, payload, timeout_steps=10):
    ctx.set(stream.ready, 1)
    valid = False
    timeout = 0
    while not valid:
        _, _, valid, data = await ctx.tick().sample(stream.valid, stream.payload)
        print(f"get_stream: {valid=}, {data=}")
        timeout += 1; assert timeout < timeout_steps
    if isinstance(payload, dict):
        wrapped_payload = stream.payload.shape().const(payload)
    else:
        wrapped_payload = payload
    assert data == wrapped_payload, f"{data} != {wrapped_payload}"
    ctx.set(stream.ready, 0)



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
        async def put_testbench(ctx):
            await put_stream(ctx, dut.dac_stream, {"dac_x_code": 123, "dac_y_code": 456, "last": 1})

        async def get_testbench(ctx):
            await get_stream(ctx, dut.adc_stream, {"adc_code": 0, "last": 1}, timeout_steps=100)

        self.simulate(dut, [put_testbench, get_testbench], name="bus_controller")

    def test_supersampler_expand(self):
        def run_test(dwell):
            print(f"dwell {dwell}")
            dut = Supersampler()

            async def put_testbench(ctx):
                await put_stream(ctx, dut.dac_stream,
                    {"dac_x_code": 123, "dac_y_code": 456, "dwell_time": dwell})

            async def get_testbench(ctx):
                for index in range(dwell + 1):
                    await get_stream(ctx, dut.super_dac_stream,
                        {"dac_x_code": 123, "dac_y_code": 456, "last": int(index == dwell)})
                assert ctx.get(dut.super_dac_stream.valid) == 0

            self.simulate(dut, [put_testbench, get_testbench], name="ss_expand")

        run_test(0)
        run_test(1)
        run_test(2)

    def test_supersampler_average1(self):
        dut = Supersampler()

        async def put_testbench(ctx):
            await put_stream(dut.super_adc_stream,
                {"adc_code": 123, "adc_ovf": 0, "last": 1})

        async def get_testbench(ctx):
            await get_stream(dut.adc_stream,
                {"adc_code": 123})
            assert ctx.get(dut.adc_stream.valid) == 0

        self.simulate(dut, [put_testbench, get_testbench], name = "ss_avg1")

    def test_supersampler_average2(self):
        dut = Supersampler()

        async def put_testbench(ctx):
            await put_stream(ctx, dut.super_adc_stream,
                {"adc_code": 456, "adc_ovf": 0, "last": 0})
            await put_stream(ctx, dut.super_adc_stream,
                {"adc_code": 123, "adc_ovf": 0, "last": 1})
            await put_stream(ctx, dut.super_adc_stream,
                {"adc_code": 999, "adc_ovf": 0, "last": 0})

        async def get_testbench(ctx):
            await get_stream(ctx, dut.adc_stream,
                {"adc_code": (456+123)//2})
            assert ctx.get(dut.adc_stream.valid) == 0

        self.simulate(dut, [put_testbench, get_testbench], name = "ss_avg2")

    def test_flippenator(self):
        dut = Flippenator()

        def test_xflip():
            async def put_testbench(ctx):
                ctx.set(dut.transforms.xflip, 1)
                await put_stream(ctx, dut.in_stream, {
                    "dac_x_code": 1,
                    "dac_y_code": 16383,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            async def get_testbench(ctx):
                await get_stream(ctx, dut.out_stream, {
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
            async def put_testbench(ctx):
                ctx.set(dut.transforms.yflip, 1)
                await put_stream(ctx, dut.in_stream, {
                    "dac_x_code": 1,
                    "dac_y_code": 16383,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            async def get_testbench(ctx):
                await get_stream(ctx, dut.out_stream, {
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
            async def put_testbench(ctx):
                ctx.set(dut.transforms.rotate90, 1)
                await put_stream(ctx, dut.in_stream, {
                    "dac_x_code": 1,
                    "dac_y_code": 16383,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            async def get_testbench(ctx):
                await get_stream(ctx, dut.out_stream, {
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

        async def put_testbench(ctx):
            await put_stream(ctx, dut.roi_stream, {
                "x_start": 5, "x_count": 3, "x_step": 0x2_00,
                "y_start": 9, "y_count": 2, "y_step": 0x5_00,
            })
            await put_stream(ctx, dut.dwell_stream, {"dwell_time": 1})
            await put_stream(ctx, dut.dwell_stream, {"dwell_time": 2})
            await put_stream(ctx, dut.dwell_stream, {"dwell_time": 3})
            await put_stream(ctx, dut.dwell_stream, {"dwell_time": 7})
            await put_stream(ctx, dut.dwell_stream, {"dwell_time": 8})
            await put_stream(ctx, dut.dwell_stream, {"dwell_time": 9})

        async def get_testbench(ctx):
            await get_stream(ctx, dut.dac_stream, {"dac_x_code": 5, "dac_y_code": 9,  "dwell_time": 1})
            await get_stream(ctx, dut.dac_stream, {"dac_x_code": 7, "dac_y_code": 9,  "dwell_time": 2})
            await get_stream(ctx, dut.dac_stream, {"dac_x_code": 9, "dac_y_code": 9,  "dwell_time": 3})
            await get_stream(ctx, dut.dac_stream, {"dac_x_code": 5, "dac_y_code": 14, "dwell_time": 7})
            await get_stream(ctx, dut.dac_stream, {"dac_x_code": 7, "dac_y_code": 14, "dwell_time": 8})
            await get_stream(ctx, dut.dac_stream, {"dac_x_code": 9, "dac_y_code": 14, "dwell_time": 9})
            assert ctx.get(dut.dac_stream.valid) == 0
            assert ctx.get(dut.roi_stream.ready) == 1

        self.simulate(dut, [get_testbench,put_testbench], name = "raster_scanner")  
    
    def test_command_parser(self):
        dut = CommandParser()

        def test_cmd(command:BaseCommand, response: dict, name:str="cmd"):
            async def put_testbench(ctx):
                print(f"{command.message}")
                for byte in command.message:
                    await put_stream(ctx, dut.usb_stream, byte)
            async def get_testbench(ctx):
                await get_stream(ctx, dut.cmd_stream, response, timeout_steps=len(command.message)*2)
                assert ctx.get(dut.cmd_stream.valid) == 0
            self.simulate(dut, [get_testbench,put_testbench], name="parse_" + name)  
        
        test_cmd(SynchronizeCommand(cookie=1234, raster=True, output=OutputMode.NoOutput),
                {"type": CmdType.Synchronize, 
                    "payload": {
                        "synchronize": {
                            "payload": {
                                "mode": {
                                    "raster": 1,
                                    "output": 2,
                                },
                                "cookie": 1234,
                }}}}, "cmd_sync")
        
        test_cmd(AbortCommand(),
                {"type": CmdType.Abort}, "cmd_abort")
        
        test_cmd(FlushCommand(),
                {"type": CmdType.Flush}, "cmd_flush")
        
        test_cmd(ExternalCtrlCommand(enable=True),
                {"type": CmdType.ExternalCtrl, 
                        "payload": {"external_ctrl": {"payload": {"enable": 1}}}
                }, "cmd_extctrlenable")
        
        test_cmd(BeamSelectCommand(beam_type=BeamType.Electron),
                {"type": CmdType.BeamSelect, 
                            "payload": {"beam_select": {"payload": {"beam_type": BeamType.Electron}}}
                }, "cmd_selectebeam")

        test_cmd(BlankCommand(),
                {"type": CmdType.Blank, 
                            "payload": {"blank": {"payload": {"enable": 1, "inline": 0}}}
                }, "cmd_blank")

        test_cmd(DelayCommand(delay=960),
                {"type": CmdType.Delay, 
                            "payload": {
                                "delay": {"payload":{ "delay": 960}}}
                }, "cmd_delay")

        x_range = DACCodeRange(start=5, count=2, step=0x2_00)
        y_range = DACCodeRange(start=9, count=1, step=0x5_00)

        test_cmd(RasterRegionCommand(x_range=x_range, y_range=y_range),
                {"type": CmdType.RasterRegion, 
                    "payload": {
                        "raster_region": {
                            "payload": {
                                "transform": {
                                    "xflip": 0,
                                    "yflip": 0,
                                    "rotate90": 0
                                },
                                "roi": {
                                    "x_start": 5,
                                    "x_count": 2,
                                    "x_step": 0x2_00,
                                    "y_start": 9,
                                    "y_count": 1,
                                    "y_step": 0x5_00
                                }
                }}}}, "cmd_rasterregion")

        test_cmd(RasterPixelRunCommand(length=5, dwell= 6),
                {"type": CmdType.RasterPixelRun, 
                    "payload": {
                        "raster_pixel_run": {
                            "payload": {
                                "length": 4, #length = length-1 because of 0-indexing
                                "dwell_time": 6
                }}}}, "cmd_rasterpixelrun")
        

        test_cmd(RasterPixelFreeRunCommand(dwell = 10),
                {"type": CmdType.RasterPixelFreeRun, 
                    "payload": {
                        "raster_pixel_free_run": {
                            "payload": {
                                "dwell_time": 10, #dwell = dwell-1 because of 0-indexing
                }}}}, "cmd_rasterpixelfreerun")


        test_cmd(VectorPixelCommand(x_coord=4, y_coord=5, dwell= 6),
                {"type": CmdType.VectorPixel, 
                    "payload": {
                        "vector_pixel": {
                            "payload": {
                                "transform": {
                                    "xflip": 0,
                                    "yflip": 0,
                                    "rotate90": 0
                                },
                                "dac_stream": {
                                "x_coord": 4,
                                "y_coord": 5,
                                "dwell_time": 6
                                }
                }}}}, "cmd_vectorpixel")

        test_cmd(VectorPixelCommand(x_coord=4, y_coord=5, dwell= 0),
                {"type": CmdType.VectorPixelMinDwell, 
                    "payload": {
                        "vector_pixel_min": {
                            "payload": {
                                "transform": {
                                    "xflip": 0,
                                    "yflip": 0,
                                    "rotate90": 0
                                },
                                "dac_stream":{
                                "x_coord": 4,
                                "y_coord": 5,
                                }
                }}}}, "cmd_vectorpixelmin")
    
        def test_raster_pixels_cmd(command:BaseCommand):
            def put_testbench():
                print(f"{command.message}")
                for byte in command.message:
                    yield from put_stream(dut.usb_stream, byte)
            def get_testbench():
                for dwell in command._dwells:
                    response = {"type": CmdType.RasterPixel, 
                        "payload": {
                            "raster_pixel": {
                                "payload": {
                                    "length": len(command._dwells)-1,
                                    "dwell_time": dwell
                    }}}}
                    yield from get_stream(dut.cmd_stream, response, timeout_steps=len(command.message)*2)
                    assert (yield dut.cmd_stream.valid) == 0
            self.simulate(dut, [get_testbench,put_testbench], name="parse_cmd_rasterpixel")  
        
        test_raster_pixels_cmd(RasterPixelsCommand(dwells = [1,2,3,4,5]))

    def test_command_executor_individual(self):
        dut = CommandExecutor()

        def test_sync_exec():
            cookie = 123*256 + 234

            async def put_testbench(ctx):
                await put_stream(ctx, dut.cmd_stream, {
                    "type": CmdType.Synchronize,
                    "payload": {
                        "synchronize": {
                            "payload":{
                                "cookie": cookie,
                                "mode" : {
                                    "raster": 1,
                                    "output": 0,
                                    }
                                }}}})
            
            async def get_testbench(ctx):
                await get_stream(ctx, dut.img_stream, 65535) # FFFF
                await get_stream(ctx, dut.img_stream, cookie)
        
            self.simulate(dut, [put_testbench, get_testbench], name = "exec_sync")  

        def test_rasterregion_exec():

            async def put_testbench(ctx):
                await put_stream(ctx, dut.cmd_stream, {
                    "type": CmdType.RasterRegion,
                    "payload": {
                        "raster_region": { "payload": {
                            "transform": {
                                "xflip": 1,
                                "yflip": 0,
                                "rotate90": 0,
                            },
                            "roi": {
                                "x_start": 5,
                                "x_count": 2,
                                "x_step": 0x2_00,
                                "y_start": 9,
                                "y_count": 1,
                                "y_step": 0x5_00,
                            }}}}})

            async def get_testbench(ctx):
                res = await ctx.tick().sample(dut.raster_scanner.roi_stream.payload).until(dut.raster_scanner.roi_stream.valid == 1)
                wrapped_payload = dut.raster_scanner.roi_stream.payload.shape().const(
                        {   "x_start": 5,
                            "x_count": 2,
                            "x_step": 0x2_00,
                            "y_start": 9,
                            "y_count": 1,
                            "y_step": 0x5_00})
                assert res[0] == wrapped_payload,  f"{res[0]} != {wrapped_payload}"

            self.simulate(dut, [get_testbench,put_testbench], name = "exec_rasterregion")  

        def test_rasterpixel_exec():

            async def put_testbench(ctx):
                await put_stream(ctx, dut.cmd_stream, {
                    "type": CmdType.RasterPixel,
                    "payload": {
                        "raster_pixel": {"payload": {"length": 1, "dwell_time": 1}}
                    }
                })
            async def get_testbench(ctx):
                res = await ctx.tick().sample(dut.raster_scanner.dwell_stream.payload).until(dut.raster_scanner.dwell_stream.valid == 1)
                wrapped_payload = dut.raster_scanner.dwell_stream.payload.shape().const(
                            {
                        "dwell_time": 1,
                        "blank": {
                            "enable": 0,
                            "request": 0
                        }})
                assert res[0] == wrapped_payload,  f"{res[0]} != {wrapped_payload}"
                
            self.simulate(dut, [get_testbench,put_testbench], name = "exec_rasterpixel")  
        
        def test_rasterpixelrun_exec():

            async def put_testbench(ctx):
                await put_stream(ctx, dut.cmd_stream, {
                    "type": CmdType.RasterPixelRun,
                    "payload": {
                        "raster_pixel_run": { "payload": {
                            "length": 2,
                            "dwell_time": 1,
                        }}}})

            async def get_testbench(ctx):
                async def get_stream(ctx, stream, payload):
                    res = await ctx.tick().sample(stream.payload).until(dut.raster_scanner.dwell_stream.valid == 1)
                    wrapped_payload = stream.payload.shape().const(payload)
                    assert res[0] == wrapped_payload,  f"{res[0]} != {wrapped_payload}"

                await get_stream(ctx, dut.raster_scanner.dwell_stream,  {
                    "dwell_time": 1,
                    "blank": {
                        "enable": 0,
                        "request": 0
                    }})
                await get_stream(ctx, dut.raster_scanner.dwell_stream,  {
                    "dwell_time": 1,
                    "blank": {
                        "enable": 0,
                        "request": 0
                    }})

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

            async def _put_testbench(self, ctx, dut, timeout_steps=100):
                print(f"put_testbench: {self._command}")
                await put_stream(ctx, dut.cmd_stream, self._command, timeout_steps=2*timeout_steps)
            
            async def _get_testbench(self, ctx, dut, timeout_steps=100):
                print(f"get_testbench: response to {self._command}")
                n = 0
                print(f"getting {len(self._response)} responses")
                for res in self._response:
                    await get_stream(ctx, dut.img_stream, res, timeout_steps=timeout_steps)
                    n += 1
                    print(f"got {n} responses")
                print(f"got all {len(self._response)} responses")

        class TestCommandSequence:
            def __init__(self):
                self.dut =  CommandExecutor()
                self._put_testbenches = []
                self._get_testbenches = []
        
            def add(self, command: TestCommand, timeout_steps=100):
                async def put_bench(ctx):
                    await command._put_testbench(ctx, self.dut, timeout_steps)
                self._put_testbenches.append(put_bench)
                async def get_bench(ctx):
                    await command._get_testbench(ctx, self.dut, timeout_steps)
                self._get_testbenches.append(get_bench)
            
            async def _put_testbench(self, ctx):
                for testbench in self._put_testbenches:
                    await testbench(ctx)
            
            async def _get_testbench(self, ctx):
                for testbench in self._get_testbenches:
                    await testbench(ctx)
        class TestSyncCommand(TestCommand):
            def __init__(self, cookie, raster_mode, output_mode=0):
                self._cookie = cookie
                self._raster_mode = raster_mode
                self._output_mode = output_mode
            
            @property
            def _command(self):
                return {"type": CmdType.Synchronize,
                        "payload": {"synchronize": {"payload": {
                                "cookie": self._cookie,
                                "mode": {
                                    "raster": self._raster_mode,
                                    "output": self._output_mode, 
                                    }}}}}
                    
            @property
            def _response(self):
                return [65535, self._cookie]
        
        class TestDelayCommand(TestCommand):
            def __init__(self, delay):
                self._delay = delay

            @property
            def _command(self):
                return {"type": CmdType.Delay,
                        "payload": { "delay": { "payload": {
                            "delay": self._delay
                            }}}}
                    
            @property
            def _response(self):
                return []

        class TestFlushCommand(TestCommand):
            @property
            def _command(self):
                return {"type": CmdType.Flush}
                    
            @property
            def _response(self):
                return []

        
        class TestExtCtrlCommand(TestCommand):
            def __init__(self, enable: bool):
                self._enable = enable
            
            @property
            def _command(self):
                return {"type": CmdType.ExternalCtrl,
                        "payload": {
                            "external_ctrl": {"payload": {
                                "enable": self._enable,
                                }}}}
            @property
            def _response(self):
                return []
        
        class TestBeamSelectCommand(TestCommand):
            def __init__(self, beam_type: BeamType):
                self._beam_type = beam_type
            
            @property
            def _command(self):
                    return {"type": CmdType.BeamSelect,
                            "payload": { "beam_select": { "payload": {
                                "beam_type": self._beam_type
                                }}}}
 
            @property
            def _response(self):
                return []
        
        class TestBlankCommand(TestCommand):
            def __init__(self, enable:bool, inline:bool):
                self._enable = enable
                self._inline = inline
            
            @property
            def _command(self):
                    return {"type": CmdTypeBlank,
                            "payload": { "blank": { "payload": {
                                    "enable": self._enable,
                                    "inline": self._inline
                                    }}}}
                    
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
                return {"type": CmdType.RasterRegion,
                            "payload": { "raster_region": { "payload": {
                                "transform": {
                                    "xflip": 0,
                                    "yflip": 0,
                                    "rotate90": 0
                                },
                                "roi": {
                                    "x_start": self._x_start,
                                    "x_count": self._x_count,
                                    "x_step": self._x_step,
                                    "y_start": self._y_start,
                                    "y_count": self._y_count,
                                    "y_step": self._y_step}
                            }}}}
                    
            @property
            def _response(self):
                return []
        
        class TestRasterPixelRunCommand(TestCommand):
            def __init__(self, length, dwell_time):
                self._length = length
                self._dwell_time = dwell_time

            @property
            def _command(self):
                return {"type": CmdType.RasterPixelRun,
                        "payload": { "raster_pixel_run": { "payload": {
                                "length": self._length - 1,
                                "dwell_time": self._dwell_time
                            }}}}
                    
            @property
            def _response(self):
                return [0]*self._length

        class TestRasterPixelFreeRunCommand(TestCommand):
            def __init__(self, dwell_time: int, *, test_samples=6):
                self._dwell_time = dwell_time
                self._test_samples = test_samples
            
            @property
            def _command(self):
                return {"type": CmdType.RasterPixelFreeRun,
                        "payload": { "raster_pixel_free_run": {"payload": {
                            "dwell_time":self._dwell_time
                        }}}}
                    
            @property
            def _response(self):
                return [0]*(self._test_samples)
            
            async def _put_testbench(self, ctx, dut, timeout_steps):
                print("put_testbench: {self._command}")
                await put_stream(ctx, dut.cmd_stream, self._command, timeout_steps=timeout_steps)
                n = 0
                print(f"extending put_testbench for {self._test_samples=}")
                while True:
                    if n == self._test_samples:
                        break
                    if not ctx.get(dut.supersampler.dac_stream.ready) == 1:
                        await ctx.tick()
                    else:
                        n += 1
                        print(f"{n} valid samples")
                        await ctx.tick()

        class TestVectorPixelCommand(TestCommand):
            def __init__(self, x_coord, y_coord, dwell_time):
                self._x_coord = x_coord
                self._y_coord = y_coord
                self._dwell_time = dwell_time

            @property
            def _command(self):
                return {"type": CmdType.VectorPixel,
                        "payload": { "vector_pixel": { "payload": {
                                "transform": {
                                    "xflip": 0,
                                    "yflip": 0,
                                    "rotate90": 0
                                },
                                "dac_stream":{
                                    "x_coord": self._x_coord,
                                    "y_coord": self._y_coord,
                                    "dwell_time": self._dwell_time
                                }
                            }}}}
                    
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
            test_seq.add(TestSyncCommand(102, 1))

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

            ## tests that actually test against output
            
            @applet_simulation_test("setup_test")
            async def test_sync_cookie(self):
                iface = await self.run_simulated_applet()
                #await iface.write(bytes([0, 123, 234])) # sync, cookie, raster_mode
                await iface.write(SynchronizeCommand(cookie=123*256 + 234, raster=False, output=OutputMode.SixteenBit).message)
                self.assertEqual(await iface.read(4), bytes([0xFF, 0xFF, 123, 234])) # FF, FF, cookie
            
            @applet_simulation_test("setup_x_loopback")
            async def test_loopback_raster(self):
                iface = await self.run_simulated_applet()
                await iface.write(SynchronizeCommand(cookie=123*256 + 234, raster=True, output=OutputMode.SixteenBit).message)
                self.assertEqual(await iface.read(4), bytes([0xFF, 0xFF, 123, 234])) # FF, FF, cookie
                x_range = DACCodeRange(start=0, count=5, step=256) #step = 1 DAC code
                y_range = DACCodeRange(start=5, count=10, step=256)
                await iface.write(RasterRegionCommand(x_range=x_range, y_range=y_range).message)
                await iface.write(RasterPixelRunCommand(length=25, dwell=2).message)
                res = array.array('H',[x for x in range(5)]*5)
                res.byteswap()
                self.assertEqual(await iface.read(50), bytes(res))
            
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
            async def test_loopback_vector(self):
                iface = await self.run_simulated_applet()
                await iface.write(SynchronizeCommand(output=OutputMode.SixteenBit, raster=False, cookie=123*256+234).message)
                await iface.write(FlushCommand().message)
                self.assertEqual(await iface.read(4), bytes([0xFF, 0xFF, 123, 234])) # FF, FF, cookie
                # await iface.flush()
                commands = bytearray()
                for n in range(10):
                    await iface.write(VectorPixelCommand(x_coord=n, y_coord=n, dwell=1).message)
                res = array.array('H',[x for x in range(10)])
                res.byteswap()
                self.assertEqual(await iface.read(20), bytes(res))
            
            ## tests that are more for observation
            @applet_simulation_test("setup_test", args=["--pin-ext-ibeam-scan-enable", "0", "--pin-ext-ibeam-scan-enable-2", "1"])
            async def test_vector_blank(self):
                iface = await self.run_simulated_applet()
                await iface.write(SynchronizeCommand(cookie=4, output=2, raster=0).message)
                await iface.write(BlankCommand().message)
                await iface.write(ExternalCtrlCommand(enable=True).message)
                await iface.write(BeamSelectCommand(beam_type=BeamType.Ion).message)
                await iface.write(DelayCommand(delay=10).message)
                await iface.write(BlankCommand(enable=False).message)
                for n in range(1,3):
                    await iface.write(VectorPixelCommand(x_coord=n, y_coord=n, dwell=1).message)
                await iface.write(VectorPixelCommand(x_coord=7, y_coord=7, dwell=3).message)
                await iface.write(BlankCommand(enable=True).message)
                await iface.write(DelayCommand(delay=3).message)
                await iface.write(BlankCommand(enable=False).message)
                await iface.write(VectorPixelCommand(x_coord=1, y_coord=1, dwell=1).message)
                await iface.write(BlankCommand(enable=True).message)
                await iface.write(SynchronizeCommand(cookie=4, output=2, raster=0).message)
                await iface.read(6)


            @applet_simulation_test("setup_x_loopback", args=["--out_only"])
            async def test_vector_delay(self):
                iface = await self.run_simulated_applet()
                await iface.write(VectorPixelCommand(x_coord=1, y_coord=1, dwell=6).message)
                await iface.write(InlineDelayCommand(delay=2).message)
                await iface.write(VectorPixelCommand(x_coord=2, y_coord=2, dwell=6).message)
                await iface.write(InlineDelayCommand(delay=3).message)
                await iface.write(VectorPixelCommand(x_coord=3, y_coord=3, dwell=6).message)
                await iface.write(InlineDelayCommand(delay=4).message)
                await iface.write(VectorPixelCommand(x_coord=4, y_coord=4, dwell=6).message)
                await iface.write(InlineDelayCommand(delay=5).message)
                await iface.write(VectorPixelCommand(x_coord=5, y_coord=5, dwell=6).message)
                await iface.write(InlineDelayCommand(delay=6).message)
                await iface.write(VectorPixelCommand(x_coord=6, y_coord=6, dwell=6).message)
                await iface.write(InlineDelayCommand(delay=7).message)
                await iface.write(SynchronizeCommand(cookie=4, output=2, raster=0).message)
                await iface.read(4)
                
            
        test_case = OBIApplet_TestCase()
        test_case.setUp()
        test_case.test_build()
        test_case.test_sync_cookie()
        test_case.test_benchmark()
        test_case.test_vector_blank()
        test_case.test_loopback_raster()
        test_case.test_loopback_vector()

        


        




