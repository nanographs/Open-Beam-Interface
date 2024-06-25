import struct
import enum
import array

from collections import UserDict
from dataclasses import dataclass

from amaranth import *
from amaranth import ShapeCastable, Shape
from amaranth.lib import enum, data, wiring
from amaranth.lib.wiring import In, Out, flipped

BIG_ENDIAN = (struct.pack('@H', 0x1234) == struct.pack('>H', 0x1234))

CMD_SHAPE = 4
class CmdType(enum.IntEnum, shape=CMD_SHAPE):
    Synchronize         = 0x0
    Abort               = 0x1
    Flush               = 0x2
    ExternalCtrl        = 0x3
    BeamSelect          = 0x4
    Blank               = 0x5
    Delay               = 0x6

    Array = 0x8

    RasterPixelFill = 0x9

    RasterRegion        = 0xa
    RasterPixel         = 0xb
    RasterPixelRun      = 0xc
    RasterPixelFreeRun  = 0xd
    VectorPixel         = 0xe
    VectorPixelMinDwell = 0xf 

class CommandLayout(UserDict):
    def unpack_apply(self, leaf_func=eval("lambda key, value: value"), 
                        wrap_func=eval("lambda dict: dict")):
        def unpack(from_dict, to_dict):
            for key, value in from_dict.items():
                if isinstance(value, dict):
                    to_dict[key] = wrap_func(unpack(value, {}))
                else:
                    to_dict[key] = leaf_func(key, value)
            return to_dict
        return unpack(self.data, {})
    @staticmethod
    def convert_shape(value):
        if isinstance(value, data.ShapeCastable):
            value = value.as_shape()._width
        return value
    def flatten(self):
        new_dict = {}
        def transform(key, value):
            new_dict[key] = self.convert_shape(value)
        self.unpack_apply(transform)
        return new_dict
    def field_names(self):
        return list(self.flatten().keys())
    def total_fields(self):
        total = 0
        def add_to_total(key, value):
            nonlocal total
            total += self.convert_shape(value)
        self.unpack_apply(add_to_total)
        return total
    def as_struct_layout(self):
        return self.unpack_apply(
            lambda field, field_width: field_width,
            lambda field_dict: data.StructLayout(field_dict))
    def pack_dict(self, value_dict):
        return self.unpack_apply(lambda key, value : value_dict[key])
    

class BitLayout(CommandLayout):
    bits_per_field = 1
    def as_struct_layout(self):
        struct_dict = super().as_struct_layout()
        total_bits = self.total_fields()
        assert total_bits <= CMD_SHAPE, f"{total_bits} bits can't fit in {CMD_SHAPE} bits"
        struct_dict["reserved"] = (8-CMD_SHAPE) - total_bits # add padding to header
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
    bits_per_field = 8
    def as_struct_layout(self):
        return self.unpack_apply(
            lambda field, field_width: field_width*self.bits_per_field,
            lambda field_dict: data.StructLayout(field_dict))
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
            structformat += STRUCT_FORMATS.get(field_width)
            structargs += f"value_dict['{field_name}'], "
        func = f'lambda value_dict: struct.pack("{structformat}", {header_funcstr}, {structargs})'
        return eval(func)





##### start commands

class BaseCommand:
    """
    A command

    Attributes
    ----------
    cmdtype
    fieldstr
    pack_fn
    """
    bitlayout = BitLayout({})
    bytelayout = ByteLayout({})
    def __init_subclass__(cls):
        assert (not field in cls.bitlayout.keys() for field in cls.bytelayout.keys()), f"Name collision: {field}"
        name_str = cls.__name__.removesuffix("Command")
        cls.cmdtype = CmdType[name_str] #SynchronizeCommand -> CmdType["Synchronize"]
        cls.fieldstr = "".join([name_str[0].lower()] + ['_'+i.lower() if i.isupper() 
                                else i for i in name_str[1:]])  #RasterPixelCommand -> "raster_pixel"
        header_funcstr = cls.bitlayout.pack_fn(cls.cmdtype) ## bitwise operations code
        cls.pack_fn = staticmethod(cls.bytelayout.pack_fn(header_funcstr)) ## struct.pack code
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    def __bytes__(self):
        """return bytes
        """
        return self.pack_fn(vars(self))
    def __len__(self):
        return len(bytes(self))
    def __repr__(self):
        return f"{type(self).__name__}: {vars(self)}"
    @classmethod
    def as_struct_layout(cls):
        """Convert to Amaranth data.Struct
        Returns
        -------
        :class: data.Struct
        """
        return data.StructLayout({**cls.bitlayout.as_struct_layout(), **cls.bytelayout.as_struct_layout()})
    def pack_dict(self):
        """Convert to nested dictionary of field names:values
        Returns
        -------
        :class: dict
        """
        return {"type": self.cmdtype, 
                "payload": {self.fieldstr: 
                    {**self.bitlayout.pack_dict(vars(self)), **self.bytelayout.pack_dict(vars(self))}}}

class OutputMode(enum.IntEnum, shape = 2):
    SixteenBit          = 0
    EightBit            = 1
    NoOutput            = 2

class SynchronizeCommand(BaseCommand):
    bitlayout = BitLayout({"mode": {
            "raster": 1,
            "output": OutputMode
        }})
    bytelayout = ByteLayout({"cookie": 2})

class AbortCommand(BaseCommand):
    pass

class FlushCommand(BaseCommand):
    pass

class ExternalCtrlCommand(BaseCommand):
    bitlayout = BitLayout({"enable": 1})

class BeamType(enum.IntEnum, shape = 2):
    NoBeam              = 0
    Electron            = 1
    Ion                 = 2

class BeamSelectCommand(BaseCommand):
    bitlayout = BitLayout({"beam_type": BeamType})

class BlankCommand(BaseCommand):
    bitlayout = BitLayout({"enable": 1, "inline": 1})

class DelayCommand(BaseCommand):
    bytelayout = ByteLayout({"delay": 2})

@dataclass
class DACCodeRange:
    start: int # UQ(14,0)
    count: int # UQ(14,0)
    step:  int # UQ(8,8)

class RasterRegionCommand(BaseCommand):
    bytelayout = ByteLayout({"roi": {
        "x_start": 2,
        "x_count": 2,
        "x_step": 2,
        "y_start": 2,
        "y_count": 2,
        "y_step": 2,
        
    }})
    def __init__(self, x_range: DACCodeRange, y_range:DACCodeRange):
        return super().__init__(x_start = x_range.start, x_count = x_range.count, x_step = x_range.step,
                            y_start = y_range.start, y_count = y_range.count, y_step = y_range.step)

class RasterPixelCommand(BaseCommand):
    bytelayout = ByteLayout({"dwell_time" : 2})

class ArrayCommand(BaseCommand):
    bitlayout = BitLayout({"cmdtype": CmdType})
    bytelayout = ByteLayout({"array_length": 2})

class RasterPixelRunCommand(BaseCommand):
    bytelayout = ByteLayout({"length": 2, "dwell_time" : 2})
    def __bytes__(self):
        all_commands = bytearray()
        for commands, pixel_count in self._iter_chunks():
            all_commands.extend(commands)
        return bytes(all_commands)

    def _iter_chunks(self, latency=65536*65536):
        commands = bytearray()

        def append_command(pixel_count):
            array_count = pixel_count//65536
            remainder_pixel_count = pixel_count%65536
            assert array_count < 65536, "can't handle more than 65536x65536 points"
            print(f"{array_count=}, {remainder_pixel_count=}")
            if array_count > 0:
                commands.extend(bytes(ArrayCommand(cmdtype=CmdType.RasterPixelRun, array_length=array_count)))
                chunk = array.array('H', [self.dwell_time]*array_count)
                if not BIG_ENDIAN: # there is no `array.array('>H')`
                    chunk.byteswap()
                commands.extend(chunk.tobytes())
            if remainder_pixel_count > 0:
                commands.extend(self.pack_fn({"dwell_time":self.dwell_time, "length":remainder_pixel_count}))

        pixel_count = 0
        total_dwell = 0
        for _ in range(self.length):
            pixel_count += 1
            total_dwell += self.dwell_time
            if total_dwell >= latency:
                append_command(pixel_count)
                yield(commands, pixel_count)
                commands = bytearray()
                pixel_count = 0
                total_dwell = 0
        if pixel_count > 0:
            append_command(pixel_count)
            yield(commands, pixel_count)

class RasterPixelArray:
    def __init__(self, dwells: list):
        self.dwells = dwells
    def __bytes__(self):
        all_commands = bytearray()
        for commands, pixel_count in self._iter_chunks():
            all_commands.extend(commands)
        return bytes(all_commands)

    def _iter_chunks(self, latency=65536*65536):
        commands = bytearray()

        def append_command(chunk):
            cmd = ArrayCommand(cmdtype = CmdType.RasterPixel, array_length=len(chunk))
            commands.extend(bytes(cmd))
            if not BIG_ENDIAN: # there is no `array.array('>H')`
                chunk.byteswap()
            commands.extend(chunk.tobytes())

        chunk = array.array('H')
        pixel_count = 0
        total_dwell = 0
        for pixel in self.dwells:
            chunk.append(pixel)
            pixel_count += 1
            total_dwell += pixel
            if len(chunk) == 0xffff or total_dwell >= latency:
                append_command(chunk)
                del chunk[:] # clear
            if total_dwell >= latency:
                yield (commands, pixel_count)
                commands = bytearray()
                pixel_count = 0
                total_dwell = 0
        if chunk:
            append_command(chunk)
            yield (commands, pixel_count)

class RasterPixelFreeRunCommand(BaseCommand):
    bytelayout = ByteLayout({"dwell_time": 2})

class VectorPixelCommand(BaseCommand):
    bytelayout = ByteLayout({"dac_stream": {"x_coord": 2, "y_coord": 2, "dwell_time": 2}})
    def pack(self, **kwargs):
        if kwargs["dwell_time"] == 0:
            return VectorPixelMinDwellCommand.pack(**kwargs)
        else:
            return super().pack(**kwargs)

import itertools
class VectorPixelArray:
    def __init__(self, *, points):
        self.dwells = itertools.batched(points, 3)
    def __iter__(self):
        return self
    def _iter_chunks(self, latency=65536):
        commands = bytearray()

        def append_command(chunk):
            if len(chunk)==3:
                x_coord, y_coord, dwell_time = chunk
                cmd = VectorPixelCommand(x_coord = x_coord, y_coord=y_coord, dwell_time=dwell_time)
                commands.extend(bytes(cmd))
            else:
                cmd = ArrayCommand(cmdtype = CmdType.VectorPixel, array_length=len(chunk)//3)
                commands.extend(bytes(cmd))
                if not BIG_ENDIAN: # there is no `array.array('>H')`
                    chunk.byteswap()
                commands.extend(chunk.tobytes())
        
        chunk = array.array('H')
        pixel_count = 0
        total_dwell = 0
        for x, y, dwell in self.points:
            chunk.extend(array.array("H", [x, y, dwell]))
            pixel_count += 1
            total_dwell += dwell
            if len(chunk) == 0xffff or total_dwell >= latency:
                append_command(chunk)
                del chunk[:] # clear
            if total_dwell >= latency:
                yield(commands, pixel_count)
                commands = bytearray()
                pixel_count = 0
                total_dwell = 0
        if chunk:
            append_command(chunk)
            yield (commands, pixel_count)

class VectorPixelMinDwellCommand(BaseCommand):
    bytelayout = ByteLayout({"dac_stream": {"x_coord": 2, "y_coord": 2}})

all_commands = [SynchronizeCommand, 
                AbortCommand, 
                FlushCommand,
                ExternalCtrlCommand,
                BeamSelectCommand,
                BlankCommand,
                DelayCommand,
                ArrayCommand,
                RasterRegionCommand,
                RasterPixelCommand, 
                RasterPixelRunCommand,
                RasterPixelFreeRunCommand,
                VectorPixelCommand,
                VectorPixelMinDwellCommand]

class Command(data.Struct):
    type: CmdType
    payload: data.UnionLayout({cmd.fieldstr: cmd.as_struct_layout() for cmd in all_commands})

    deserialized_states = {cmd.cmdtype : 
            {f"{cmd.fieldstr}_{state}":offset for state, offset in cmd.bytelayout.as_deserialized_states().items()} 
            for cmd in all_commands}


# class DwellTimeVal(int):
#     '''Dwell time is measured in units of ADC cycles.
#         One DwellTime = 125 ns'''
#     def __init__(self, value):
#         assert value <= 65536, f"Pixel dwell time {value} is higher than 65536. Dwell times are limited to 16 bit values"
#         self.value = value - 1 #Dwell time counter is 0-indexed


class CommandSequence:
    def __init__(self, sync:bool=True, cookie: int=123, output: OutputMode=OutputMode.SixteenBit, raster:bool=False,
                verbose:bool=False):
        self._bytes = bytearray()
        self._output = output
        self._raster = raster
        self.verbose = verbose
        if sync:
            self.extend(SynchronizeCommand(cookie=cookie, output=output, raster=raster))
    def extend(self, other: BaseCommand, verbose:bool=False):
        if self.verbose:
            print(f"adding {other!r}")
        try:
            self._bytes.extend(bytes(other))
        except TypeError:
            raise TypeError("Command syntax error. Did you use 'command' instead of 'command()'?")
        #self._response.extend(other.response)
    def __bytes__(self):
        return bytes(self._bytes)
    def __len__(self):
        return len(bytes(self))


##### test / simulation

def test_speed():
    import time
    start = time.time()
    for _ in range(1000):
        s = SynchronizeCommand.pack(raster = 1, output = 2, cookie = 1024)
    end = time.time()
    print(f"{end-start:.4f}")
    print(f"{s}")
