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