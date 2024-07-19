import unittest
import struct
import array
from amaranth.sim import Simulator, Tick
from amaranth import Signal, ShapeCastable, Const
from amaranth import DriverConflict
from abc import ABCMeta, abstractmethod
import asyncio

from applet.open_beam_interface import StreamSignature
from applet.open_beam_interface import Supersampler, RasterScanner, RasterRegion
from applet.open_beam_interface import CommandParser, CommandExecutor, Command, BeamType, OutputMode, CmdType
from applet.open_beam_interface import BusController, Flippenator
from commands import *


## support functions for prettier output
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

def prettier_dict(data):
    try:
        data = unpack_const(data)
        if isinstance(data, dict):
            all_data = unpack_dict(data)
        else:
            all_data = data
    except: all_data = data
    return all_data

def filtered_dict(data, payload):
    data = prettier_dict(data)
    filtered_data = {}
    def unpack(data, payload, filtered_data):
        for signal, payload_value in payload.items():
            data_value = data[signal]
            if isinstance(data_value, dict):
                filtered_data[signal] = {}
                unpack(data_value, payload_value, filtered_data[signal])
            else:
                filtered_data[signal] = data_value
    if isinstance(data, dict):
        unpack(data, payload, filtered_data)
    else:
        filtered_data = data
    return filtered_data
    
def prettier_diff(data, payload:dict):
    summary = "\nSignal \t Expected \t Actual"
    data = filtered_dict(data, payload)
    def unpack_diff(data, payload):
        nonlocal summary
        for signal, payload_value in payload.items():
            data_value = data[signal]
            if isinstance(data_value, dict):
                unpack_diff(data_value, payload_value)
            else:
                summary += f"\n{signal}\t {payload_value}\t {data_value}"
                if payload_value != data_value:
                    summary += "\t<---"
    if isinstance(data, dict):
        unpack_diff(data, payload)
    else:
        summary += f"\n \t {payload} \t {data}"
    return summary


# Submit a test payload into a stream. Paayload gets put into stream.
async def put_stream(ctx, stream, payload, timeout_steps=10):
    ctx.set(stream.payload, payload)
    ctx.set(stream.valid, 1)
    ready = False
    timeout = 0
    while not ready:
        ready = ctx.get(stream.ready)
        #print(f"put_stream: {ready=}, {timeout=}/{timeout_steps}")
        await ctx.tick()
        timeout += 1; assert timeout < timeout_steps
    print(f"put_stream: {ready=}, {timeout=}/{timeout_steps}")
    ctx.set(stream.valid, 0)

# Receive and validate a test payload from a stream. Payload gets compared against stream output.
async def get_stream(ctx, stream, payload, timeout_steps=10):
    ctx.set(stream.ready, 1)
    valid = False
    timeout = 0
    while not valid:
        _, _, valid, data = await ctx.tick().sample(stream.valid, stream.payload)
        #print(f"get_stream: {valid=}, data={filtered_dict(data, payload)}")
        timeout += 1; assert timeout < timeout_steps
    print(f"get_stream: {valid=}, data={filtered_dict(data, payload)}")
    if isinstance(payload, dict):
        wrapped_payload = stream.payload.shape().const(payload)
    else:
        wrapped_payload = payload
    assert data == wrapped_payload, f"{prettier_diff(data, payload)}"
    ctx.set(stream.ready, 0)

class OBIAppletTestCase(unittest.TestCase):
    '''
    Creates a simulation with a set of testbenches
    
    Attributes
    ----------
    testbench - an Amaranth testbench bench(ctx) see amaranth.SimulatorContext
    name - str - name of vcd file to be generated
    '''
    def simulate(self, dut, testbenches, *, name="test"):
        print(f"running {name}")
        sim = Simulator(dut)
        sim.add_clock(20.83e-9)
        for testbench in testbenches:
            sim.add_testbench(testbench)
        with sim.write_vcd(f"{name}.vcd"), sim.write_vcd(f"{name}+d.vcd", fs_per_delta=250_000):
            sim.run()

    ## Bus Controller
    def test_bus_controller(self):
        dut = BusController(adc_half_period=3, adc_latency=6)
        async def put_testbench(ctx):
            await put_stream(ctx, dut.dac_stream, {"dac_x_code": 123, "dac_y_code": 456, "last": 1})

        async def get_testbench(ctx):
            await get_stream(ctx, dut.adc_stream, {"adc_code": 0, "last": 1}, timeout_steps=100)

        self.simulate(dut, [put_testbench, get_testbench], name="bus_controller")
    
    ## Supersampler
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
            await put_stream(ctx, dut.super_adc_stream,
                {"adc_code": 123, "adc_ovf": 0, "last": 1})

        async def get_testbench(ctx):
            await get_stream(ctx, dut.adc_stream,
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
    
    ## Flippenator
    def test_flippenator(self):
        # TODO: figure out why 16383 flips to 1 and not 0
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

        def test_xflip_2():
            async def put_testbench(ctx):
                ctx.set(dut.transforms.xflip, 1)
                await put_stream(ctx, dut.in_stream, {
                    "dac_x_code": 2,
                    "dac_y_code": 16383,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            async def get_testbench(ctx):
                await get_stream(ctx, dut.out_stream, {
                    "dac_x_code": 16382,
                    "dac_y_code": 16383,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            self.simulate(dut, [get_testbench,put_testbench], name="flippenator_xflip_2")  
        
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
        def test_yflip_2():
            async def put_testbench(ctx):
                ctx.set(dut.transforms.yflip, 1)
                await put_stream(ctx, dut.in_stream, {
                    "dac_x_code": 1,
                    "dac_y_code": 16382,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            async def get_testbench(ctx):
                await get_stream(ctx, dut.out_stream, {
                    "dac_x_code": 1,
                    "dac_y_code": 2,
                    "last": 1,
                    "blank": {
                        "enable": 1,
                        "request": 1
                    }
                })
            self.simulate(dut, [get_testbench,put_testbench], name="flippenator_yflip_2") 
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
        test_xflip_2()
        test_yflip()
        test_rot90()

    # Raster Scanner
    def test_raster_scanner(self):

        #TODO: add a test that covers fractional steps
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

    # Command Parser
    def test_command_parser(self):
        dut = CommandParser()

        def test_cmd(command:BaseCommand, name:str="cmd"):
            print(f"testing {command.fieldstr}")
            async def put_testbench(ctx):
                for byte in bytes(command):
                    await put_stream(ctx, dut.usb_stream, byte)
            async def get_testbench(ctx):
                d = command.as_dict()
                print(f"{d=}")
                await get_stream(ctx, dut.cmd_stream, d, 
                    timeout_steps=len(command)*2 + 2)
                await ctx.tick()
                assert ctx.get(dut.cmd_stream.valid) == 0
            self.simulate(dut, [get_testbench,put_testbench], name="parse_" + name)  
        
        test_cmd(SynchronizeCommand(cookie=1234, raster=True, output=OutputMode.NoOutput),"cmd_sync")
        
        test_cmd(AbortCommand(), "cmd_abort")
        
        test_cmd(FlushCommand(),"cmd_flush")
        
        test_cmd(ExternalCtrlCommand(enable=True), "cmd_extctrlenable")
        
        test_cmd(BeamSelectCommand(beam_type=BeamType.Electron),"cmd_selectebeam")

        test_cmd(BlankCommand(enable=True, inline=False),"cmd_blank")

        test_cmd(DelayCommand(delay=960),"cmd_delay")

        x_range = DACCodeRange(start=5, count=2, step=0x2_00)
        y_range = DACCodeRange(start=9, count=1, step=0x5_00)

        test_cmd(RasterRegionCommand(x_range=x_range, y_range=y_range), "cmd_rasterregion")

        test_cmd(RasterPixelRunCommand(length=5, dwell_time= 6),"cmd_rasterpixelrun")
        

        test_cmd(RasterPixelFreeRunCommand(dwell_time = 10), "cmd_rasterpixelfreerun")


        test_cmd(VectorPixelCommand(x_coord=4, y_coord=5, dwell_time= 6),"cmd_vectorpixel")

        test_cmd(VectorPixelCommand(x_coord=4, y_coord=5, dwell_time= 1),"cmd_vectorpixelmin")
    
        def test_raster_pixels_cmd():
            command = ArrayCommand(cmdtype = CmdType.RasterPixel, array_length = 5)
            dwells = [1,2,3,4,5]
            async def put_testbench(ctx):
                for byte in bytes(command):
                    await put_stream(ctx, dut.usb_stream, byte)
                for dwell in dwells:
                    for byte in struct.pack(">H", dwell):
                        await put_stream(ctx, dut.usb_stream, byte)
            async def get_testbench(ctx):
                for dwell in dwells:
                    await get_stream(ctx, dut.cmd_stream, RasterPixelCommand(dwell_time=dwell).as_dict(), timeout_steps=len(command)*2 + len(dwells)*2 + 2)
                    assert ctx.get(dut.cmd_stream.valid) == 0
            self.simulate(dut, [get_testbench,put_testbench], name="parse_cmd_rasterpixel")  
        
        test_raster_pixels_cmd()

    # Command Executor
    def test_command_executor_individual(self):
        dut = CommandExecutor()

        def test_sync_exec():
            cookie = 1234

            async def put_testbench(ctx):
                await put_stream(ctx, dut.cmd_stream, 
                        SynchronizeCommand(raster=True, output=OutputMode.NoOutput, cookie=cookie).as_dict())
            
            async def get_testbench(ctx):
                await get_stream(ctx, dut.img_stream, 65535) # FFFF
                await get_stream(ctx, dut.img_stream, cookie)
        
            self.simulate(dut, [put_testbench, get_testbench], name = "exec_sync")  

        def test_rasterregion_exec():

            async def put_testbench(ctx):
                await put_stream(ctx, dut.cmd_stream, 
                    RasterRegionCommand(x_range=DACCodeRange(start=5, count=2, step=0x2_00),
                    y_range=DACCodeRange(start=9, count=1, step=0x5_00)).as_dict())
            async def get_testbench(ctx):
                data = await ctx.tick().sample(dut.raster_scanner.roi_stream.payload).until(dut.raster_scanner.roi_stream.valid == 1)
                print(f"{data=}")
                payload = {"x_start": 5,
                            "x_count": 2,
                            "x_step": 0x2_00,
                            "y_start": 9,
                            "y_count": 1,
                            "y_step": 0x5_00}
                wrapped_payload = dut.raster_scanner.roi_stream.payload.shape().const(payload)
                assert data[0] == wrapped_payload,  f"{prettier_diff(data[0], payload)}"

            self.simulate(dut, [get_testbench,put_testbench], name = "exec_rasterregion")  

        def test_rasterpixel_exec():

            async def put_testbench(ctx):
                await put_stream(ctx, dut.cmd_stream, 
                    RasterPixelCommand(dwell_time=5).as_dict())
            async def get_testbench(ctx):
                data = await ctx.tick().sample(dut.raster_scanner.dwell_stream.payload).until(dut.raster_scanner.dwell_stream.valid == 1)
                payload = {
                        "dwell_time": 5,
                        "blank": {
                            "enable": 0,
                            "request": 0
                        }}
                wrapped_payload = dut.raster_scanner.dwell_stream.payload.shape().const(payload)
                assert data[0] == wrapped_payload,  f"{prettier_diff(data[0], payload)}"
                
            self.simulate(dut, [get_testbench,put_testbench], name = "exec_rasterpixel")  
        
        def test_rasterpixelrun_exec():

            async def put_testbench(ctx):
                await put_stream(ctx, dut.cmd_stream, 
                RasterPixelRunCommand(length=2, dwell_time=1).as_dict())

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

    def test_blanking(self):
        dut = CommandExecutor()

        async def async_unblank(ctx): #assumes starting from default or blanked state
            ctx.set(dut.cmd_stream.payload, BlankCommand(enable=False, inline=False).as_dict())
            ctx.set(dut.cmd_stream.valid, 1)
            await ctx.tick()
            ctx.set(dut.cmd_stream.valid, 0)
            await ctx.tick("dac_clk")
            assert ctx.get(dut.blank_enable) == 0

        async def async_blank(ctx): #assumes starting from an unblanked state
            ctx.set(dut.cmd_stream.payload, BlankCommand(enable=True, inline=False).as_dict())
            ctx.set(dut.cmd_stream.valid, 1)
            await ctx.tick()
            ctx.set(dut.cmd_stream.valid, 0)
            await ctx.tick("dac_clk")
            assert ctx.get(dut.blank_enable) == 1
        
        async def sync_unblank(ctx): #assumes starting from default or blanked state
            ctx.set(dut.cmd_stream.payload, BlankCommand(enable=False, inline=True).as_dict())
            ctx.set(dut.cmd_stream.valid, 1)
            await ctx.tick().until(dut.cmd_stream.ready == 0)
            assert ctx.get(dut.blank_enable) == 1 #shouldn't be unblanked yet
            ctx.set(dut.cmd_stream.payload, 
                VectorPixelCommand(x_coord=1, y_coord=1, dwell_time=1).as_dict())
            ctx.set(dut.cmd_stream.valid, 1)
            await ctx.tick().until(dut.cmd_stream.ready == 0)
            ctx.set(dut.cmd_stream.valid, 0)
            await ctx.tick().until(dut.flippenator.out_stream.valid == 1) # bus controller recieves dac codes
            await ctx.tick("dac_clk").repeat(2) # dac codes are latched
            assert ctx.get(dut.blank_enable) == 0

        async def sync_blank(ctx): #assumes starting from an unblanked state
            ctx.set(dut.cmd_stream.payload, BlankCommand(enable=True, inline=True).as_dict())
            ctx.set(dut.cmd_stream.valid, 1)
            await ctx.tick().until(dut.cmd_stream.ready == 0)
            assert ctx.get(dut.blank_enable) == 0 #shouldn't be blanked yet
            ctx.set(dut.cmd_stream.payload, VectorPixelCommand(x_coord=2, y_coord=2, dwell_time=1).as_dict())
            ctx.set(dut.cmd_stream.valid, 1)
            await ctx.tick().until(dut.cmd_stream.ready == 0)
            ctx.set(dut.cmd_stream.valid, 0)
            await ctx.tick().until(dut.flippenator.out_stream.valid == 1) # bus controller recieves dac codes
            await ctx.tick("dac_clk").repeat(2) # dac codes are latched
            assert ctx.get(dut.blank_enable) == 1
        
        async def test_seq_1(ctx):
            await async_unblank(ctx)
            await async_blank(ctx)
            await async_unblank(ctx)
            await sync_blank(ctx)
            await sync_unblank(ctx)
            await async_blank(ctx)
            #await sync_unblank(ctx)
        
        self.simulate(dut, [async_unblank], name="async_unblank")
        self.simulate(dut, [sync_unblank], name="sync_unblank")
        self.simulate(dut, [test_seq_1], name="blank_seq_1")
    