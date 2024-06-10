from amaranth import *
from amaranth import ShapeCastable, Shape
from amaranth.lib import enum, data, wiring
from amaranth.lib.wiring import In, Out, flipped
import struct
import enum
from dataclasses import dataclass
from . import StreamSignature
from amaranth.sim import Simulator
from .test import prettier_dict, unpack_dict, unpack_const


def parse_input(command):
    flatlist = []
    def flatpack(a_key, a_dict):
        for key, value in a_dict.items():
            key = f"{a_key}.{key}"
            if isinstance(value, dict):
                flatpack(key, value)
            else:
                flatlist.append(f"{key}.{value}")
    if hasattr(command, "bitlayout"):    
        flatpack("bits", command.bitlayout)
    if hasattr(command, "bytelayout"):    
        flatpack("bytes", command.bytelayout)
    print(flatlist)

class SynchronizeCommand:
    fieldstr = "synchronize"
    cmdtype = 0xa
    bitlayout = {"mode": {
            "raster": 1,
            "output": 2
        }}
    bytelayout = {"cookie": 2, "another": 1}

#parse_input(SynchronizeCommand)

def dict_to_struct(command):
    struct_dict = {}
    def unpack(field_dict, struct_dict):
        new_struct_dict = {}
        for field, value in field_dict.items():
            if isinstance(value, dict):
                struct_dict[field] = data.StructLayout(unpack(value, new_struct_dict))
            else:
                new_struct_dict[field] = value
        return new_struct_dict
    unpack(command.bitlayout, struct_dict)

    def deserialize(command):
        for field, bytelength in command.bytelayout.items():
            struct_dict[field] = 8*bytelength

    deserialize(command)
    return data.StructLayout(struct_dict)


def deserialize_array(command):
    deserialized_states = {}
    offset = 8 #first byte is reserved for header
    for field, bytelength in command.bytelayout.items():
        for n in range(bytelength):
            deserialized_states[f"{field}_{n}"] = offset
            offset += 8
    return deserialized_states

all_commands = [SynchronizeCommand]

class Command(data.Struct):
    type: 4
    payload: data.UnionLayout({cmd.fieldstr : dict_to_struct(cmd) for cmd in all_commands})


bytes_array = {cmd.cmdtype : sum([x for x in cmd.bytelayout.values()]) for cmd in all_commands}

deserialize_state_dict = {cmd.cmdtype : deserialize_array(cmd) for cmd in all_commands}

class CommandParser(wiring.Component):
    usb_stream: In(StreamSignature(8))
    cmd_stream: Out(StreamSignature(Command))

    def elaborate(self, platform):
        m = Module()
        self.t = Signal(4)
        self.command = Signal(Command)
        self.command_reg = Signal(Command)
        self.payload_size = Signal(max(bytes_array.values()))
        


        with m.FSM():
            with m.State("Type"):
                m.d.comb += self.usb_stream.ready.eq(1)
                with m.If(self.usb_stream.valid):
                    m.d.comb += self.command.type.eq(self.usb_stream.payload[4:8])
                    m.d.comb += self.command.payload.as_value()[0:4].eq(self.usb_stream.payload[0:4])
                    m.d.sync += self.command_reg.eq(self.command)
                    with m.Switch(self.command.type):
                        for cmdtype, state_sequence in deserialize_state_dict.items():
                            with m.Case(cmdtype):
                                m.next = list(state_sequence.keys())[0]

            def Deserialize(target, state, next_state):
                m.d.comb += self.command.eq(self.command_reg)
                print(f'state: {state} -> next state: {next_state}')
                with m.State(state):
                    with m.If(self.usb_stream.valid):
                        m.d.sync += target.eq(self.usb_stream.payload)
                        m.next = next_state
            
            for state_sequence in deserialize_state_dict.values():
                for n, (state, offset) in enumerate(state_sequence.items()):
                    if n < len(state_sequence) - 1:
                        next_state = list(state_sequence.keys())[n+1]
                    elif n == len(state_sequence) - 1:
                        next_state = "Submit"
                    Deserialize(self.command_reg.as_value()[offset:offset+8], state, next_state)

            
            # def DeserializeWord(target, state_prefix, next_state):
            #     # print(f'\tdeserializing: {state_prefix} to {next_state}')
            #     Deserialize(target[8:16],
            #         f"{state_prefix}_High", f"{state_prefix}_Low")
            #     Deserialize(target[0:8],
            #         f"{state_prefix}_Low",  next_state)

            with m.State("Submit"):
                m.d.comb += self.command.eq(self.command_reg)
                m.d.comb += self.cmd_stream.valid.eq(1)
                with m.If(self.cmd_stream.ready):
                    m.next = "Type"

        return m


dut = CommandParser()

async def bench(ctx):
    header = 0xa << 4 | 1 << 3 | 2 << 2
    ctx.set(dut.usb_stream.payload, header)
    ctx.set(dut.usb_stream.valid, 1)
    await ctx.tick()
    ctx.set(dut.usb_stream.payload, 123)
    ctx.set(dut.usb_stream.valid, 1)
    await ctx.tick()
    ctx.set(dut.usb_stream.payload, 255)
    ctx.set(dut.usb_stream.valid, 1)
    await ctx.tick()
    ctx.set(dut.usb_stream.payload, 64)
    ctx.set(dut.usb_stream.valid, 1)
    _, _, r = await ctx.tick().sample(dut.command)
    print(prettier_dict(r))

sim = Simulator(dut)
sim.add_clock(20.83e-9)
sim.add_testbench(bench)
with sim.write_vcd(f"bc3.vcd"):
    sim.run()