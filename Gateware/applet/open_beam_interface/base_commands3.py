import struct
import enum
from collections import UserDict

from amaranth import *
from amaranth import ShapeCastable, Shape
from amaranth.lib import enum, data, wiring
from amaranth.lib.wiring import In, Out, flipped

from . import StreamSignature




CMD_SHAPE = 4
class CmdType(enum.IntEnum, shape=CMD_SHAPE):
    Synchronize         = 0x0
    Abort               = 0x1
    Flush               = 0x2
    ExternalCtrl        = 0x3
    BeamSelect          = 0x4
    Blank               = 0x5
    Delay               = 0x6

    RasterRegion        = 0xa
    RasterPixel         = 0xb
    RasterPixelRun      = 0xc
    RasterPixelFreeRun  = 0xd
    VectorPixel         = 0xe
    VectorPixelMinDwell = 0xf 

class OutputMode(enum.IntEnum, shape = 2):
    SixteenBit          = 0
    EightBit            = 1
    NoOutput            = 2

class CommandLayout(UserDict):
    def unpack_apply(self, end_func=eval("lambda x: x"), unpack_func=eval("lambda x: x")):
        new_dict = {}
        def unpack(a_dict, new_dict):
            for key, value in a_dict.items():
                if isinstance(value, dict):
                    new_dict[key] = unpack_func(unpack(value, {}))
                else:
                    new_dict[key] = end_func(key, value)
            return new_dict
        return unpack(self.data, new_dict)
    def convert_shape(self, value):
        if isinstance(value, Shape):
            assert value._width%self.field_length == 0, f"{value!r} is not a multiple of {self.field_length}"
            value = value._width//self.field_length
        return value
    # def flatten(self):
    #     new_dict = {}
    #     def unpack(field_dict):
    #         for field, value in field_dict.items():
    #             if isinstance(value, dict):
    #                 unpack(value)
    #             else:
    #                 new_dict[field] = self.convert_shape(value)
    #     unpack(self.data)
    #     return new_dict
    def flatten(self):
        new_dict = {}
        def transform(key, value):
            new_dict[key] = self.convert_shape(value)
        self.unpack_apply(transform)
        print(f"{new_dict=}")
        return new_dict
    def field_names(self):
        return list(self.flatten().keys())
    # def total_fields(self):
    #     total = 0
    #     def unpacksum(field_dict):
    #         nonlocal total
    #         for field, value in field_dict.items():
    #             if isinstance(value, dict):
    #                 unpacksum(value)
    #             else:
    #                 total += value
    #     unpacksum(self.data)
    #     return total
    def total_fields(self):
        total = 0
        def transform(key, value):
            nonlocal total
            total += value
        self.unpack_apply(transform)
        return total
    # def as_struct_layout(self):
    #     struct_dict = {}
    #     def unpack(field_dict, struct_dict):
    #         for field, value in field_dict.items():
    #             if isinstance(value, dict):
    #                 struct_dict[field] = data.StructLayout(unpack(value, {}))
    #             else:
    #                 struct_dict[field] = self.convert_shape(value)*self.field_length
    #         return struct_dict
    #     unpack(self.data, struct_dict)
    #     return struct_dict
    def as_struct_layout(self):
        def end_transform(key, value):
            return self.convert_shape(value)*self.field_length
        def unpack_transform(x):
            return data.StructLayout(x)
        return self.unpack_apply(end_transform, unpack_transform)
        
    # def pack_dict(self, value_dict):
    #     packed_dict = {}
    #     def unpack(field_dict, packed_dict):
    #         for field, value in field_dict.items():
    #             if isinstance(value, dict):
    #                 packed_dict[field] = {}
    #                 unpack(value, packed_dict[field])
    #             else:
    #                 packed_dict[field] = value_dict[field]
    #     unpack(self.data, packed_dict)
    #     return packed_dict
    def pack_dict(self, value_dict):
        def transform(key, value):
            return value_dict[key]
        return self.unpack_apply(transform)
    

class BitLayout(CommandLayout):
    field_length = 1
    def as_struct_layout(self):
        struct_dict = super().as_struct_layout()
        total_bits = self.total_fields()
        assert total_bits <= CMD_SHAPE, f"{total_bits} bits can't fit in {CMD_SHAPE} bits"
        struct_dict["reserved"] = (8-CMD_SHAPE) - total_bits
        return struct_dict
    def pack_fn(self, cmdtype):
        field_values = []
        field_offset = 0
        field_dict = self.flatten()
        for field_name, field_width in field_dict.items():
            field_values.append(f'((value_dict[{field_name!r}] & {(1 << field_width) - 1}) << {field_offset})')
            field_offset += field_width
        field_values.append(f"{str(int(cmdtype))} << {CMD_SHAPE}") # add type field
        funcstr = f'int({" | ".join(field_values)})'
        return funcstr

STRUCT_FORMATS = {
    1: "B",
    2: "H",
}
class ByteLayout(CommandLayout):
    field_length = 8
    def as_deserialized_states(self):
        deserialized_states = {}
        offset = 8 #first byte at [0:7] is reserved for header
        for field, bytelength in self.flatten().items():
            deserialized_words = {}
            for n in range(bytelength):
                deserialized_words[f"{field}_{n}"] = offset
                offset += 8
            # reverse byte order
            deserialized_states.update(dict(reversed(deserialized_words.items())))
        return deserialized_states
    def pack_fn(self, header_funcstr):
        field_dict = self.flatten()
        structformat = ">B" #first byte = header
        structargs = ""
        for field_name, field_width in field_dict.items():
            print(f"{field_name=}, {field_width=}, {type(field_width)=}")
            structformat += STRUCT_FORMATS.get(field_width)
            structargs += f"value_dict['{field_name}'], "
        func = f'lambda value_dict: struct.pack("{structformat}", {header_funcstr}, {structargs})'
        return eval(func)


##### start commands

class BaseCommand:
    bitlayout = BitLayout({})
    bytelayout = ByteLayout({})
    def __init_subclass__(cls):
        assert (not field in cls.bitlayout.keys() for field in cls.bytelayout.keys()), "Name collision!"
        cls.cmdtype = CmdType[cls.__name__.strip("Command")] #SynchronizeCommand -> CmdType["Synchronize"]
        print(f"{cls.cmdtype=}, {type(cls.cmdtype)=}")
        cls.fieldstr = cls.__name__.strip("Command").lower() #SynchronizeCommand -> "synchronize"
        header_funcstr = cls.bitlayout.pack_fn(cls.cmdtype) ## bitwise operations code
        cls.pack_fn = staticmethod(cls.bytelayout.pack_fn(header_funcstr)) ## struct.pack code
    @classmethod
    def as_struct_layout(cls):
        return data.StructLayout({**cls.bitlayout.as_struct_layout(), **cls.bytelayout.as_struct_layout()})
    @classmethod
    def pack_dict(cls, **kwargs):
        return {"type": cls.cmdtype, 
                "payload": {cls.fieldstr: 
                    {**cls.bitlayout.pack_dict(kwargs), **cls.bytelayout.pack_dict(kwargs)}}}
    @classmethod
    def pack(cls, **kwargs):
        return cls.pack_fn(kwargs)


class SynchronizeCommand(BaseCommand):
    bitlayout = BitLayout({"mode": {
            "raster": 1,
            "output": 2
        }})
    bytelayout = ByteLayout({"cookie": 2})

class AbortCommand(BaseCommand):
    pass

class FlushCommand(BaseCommand):
    pass

DwellTime = unsigned(16)

class VectorPixelCommand(BaseCommand):
    bytelayout = ByteLayout({"dac_stream": {"x_coord": 2, "y_coord": 2, "dwell_time": DwellTime}})


all_commands = [SynchronizeCommand, AbortCommand, VectorPixelCommand]

class Command(data.Struct):
    type: CmdType
    payload: data.UnionLayout({cmd.fieldstr: cmd.as_struct_layout() for cmd in all_commands})

    deserialized_states = {cmd.cmdtype : cmd.bytelayout.as_deserialized_states() for cmd in all_commands}


class CommandParser(wiring.Component):
    usb_stream: In(StreamSignature(8))
    cmd_stream: Out(StreamSignature(Command))

    def elaborate(self, platform):
        m = Module()
        self.command = Signal(Command)
        m.d.comb += self.cmd_stream.payload.eq(self.command)
        self.command_reg = Signal(Command)
        
        with m.FSM():
            with m.State("Type"):
                m.d.comb += self.usb_stream.ready.eq(1)
                with m.If(self.usb_stream.valid):
                    m.d.comb += self.command.type.eq(self.usb_stream.payload[(8-CMD_SHAPE):8])
                    m.d.comb += self.command.payload.as_value()[0:(8-CMD_SHAPE)].eq(self.usb_stream.payload[0:(8-CMD_SHAPE)])
                    m.d.sync += self.command_reg.eq(self.command)
                    with m.Switch(self.command.type):
                        for cmdtype, state_sequence in Command.deserialized_states.items():
                            with m.Case(cmdtype):
                                if len(state_sequence.keys()) > 0:
                                    m.next = list(state_sequence.keys())[0]
                                else:
                                    m.next = "Submit"

            def Deserialize(target, state, next_state):
                m.d.comb += self.command.eq(self.command_reg)
                print(f'state: {state} -> next state: {next_state}')
                with m.State(state):
                    m.d.comb += self.usb_stream.ready.eq(1)
                    with m.If(self.usb_stream.valid):
                        m.d.sync += target.eq(self.usb_stream.payload)
                        m.next = next_state
            
            for state_sequence in Command.deserialized_states.values():
                for n, (state, offset) in enumerate(state_sequence.items()):
                    if n < len(state_sequence) - 1:
                        next_state = list(state_sequence.keys())[n+1]
                    elif n == len(state_sequence) - 1:
                        next_state = "Submit"
                    Deserialize(self.command_reg.as_value()[offset:offset+8], state, next_state)

            with m.State("Submit"):
                m.d.comb += self.command.eq(self.command_reg)
                m.d.comb += self.cmd_stream.valid.eq(1)
                with m.If(self.cmd_stream.ready):
                    m.next = "Type"
                    

        return m


##### test / simulation

def test_speed():
    import time
    start = time.time()
    for _ in range(1000):
        s = SynchronizeCommand.pack(raster = 1, output = 2, cookiea = 1024, cookieb = 50, another = 200)
    end = time.time()
    print(f"{end-start:.4f}")
    print(f"{s}")



def test_sim():
    dut = CommandParser()

    from .test import put_stream, get_stream
    from amaranth.sim import Simulator
    
    def test_command_parse(command:BaseCommand, **kwargs):
        s = command.pack(**kwargs)
        print(f"{s=}, {len(s)=}")

        async def put_testbench(ctx):
            for byte in s:
                print(f"{byte=}, {hex(byte)=}")
                await put_stream(ctx, dut.usb_stream, byte)
        
        async def get_testbench(ctx):
            d = command.pack_dict(**kwargs)
            print(f"{d=}")
            await get_stream(ctx, dut.cmd_stream, d)
        
        sim = Simulator(dut)
        sim.add_clock(20.83e-9)
        for testbench in [put_testbench, get_testbench]:
            sim.add_testbench(testbench)
        with sim.write_vcd(f"bc3.vcd"):
            sim.run()
    
    test_command_parse(SynchronizeCommand, raster = 0, output = OutputMode.NoOutput, cookie = 1111)
    test_command_parse(AbortCommand)
    test_command_parse(VectorPixelCommand, x_coord = 1000, y_coord = 2000, dwell_time = 1500)


test_sim()