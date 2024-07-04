import struct
import enum
import array
import inspect
import asyncio

from collections import UserDict
from dataclasses import dataclass

from amaranth import *
from amaranth import ShapeCastable, Shape
from amaranth.lib import enum, data, wiring
from amaranth.lib.wiring import In, Out, flipped

import logging
logger = logging.getLogger()

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

class PayloadLayout(UserDict):
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
    

class BitLayout(PayloadLayout):
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
class ByteLayout(PayloadLayout):
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
from abc import ABCMeta, abstractmethod

class OutputMode(enum.IntEnum, shape = 2):
    SixteenBit          = 0
    EightBit            = 1
    NoOutput            = 2
class BaseCommand(metaclass = ABCMeta):
    def __init_subclass__(cls):
        cls._logger = logger.getChild(f"Command.{cls.__name__}")

    @classmethod
    def log_transfer(cls, transfer):
        if inspect.isasyncgenfunction(transfer):
            async def wrapper(self, *args, **kwargs):
                repr_short = repr(self).replace(self.__class__.__name__, "cls")
                self._logger.debug(f"iter begin={repr_short}")
                async for chunk in transfer(self, *args, **kwargs):
                    if isinstance(chunk, list):
                        self._logger.debug(f"iter chunk=<list of {len(chunk)}>")
                    elif isinstance(chunk, array.array):
                        self._logger.debug(f"iter chunk=<array of {len(chunk)}>")
                    else:
                        self._logger.debug(f"iter chunk={chunk!r}")
                    yield chunk
                self._logger.debug(f"iter end={repr_short}")
        else:
            async def wrapper(self, *args, **kwargs):
                repr_short = repr(self).replace(self.__class__.__name__, "cls")
                self._logger.debug(f"begin={repr_short}")
                await transfer(self, *args, **kwargs)
                self._logger.debug(f"end={repr_short}")
        return wrapper

    @abstractmethod
    async def transfer(self, stream):
        ...

    async def recv_res(self, pixel_count, stream, output_mode:OutputMode):
        if output_mode == OutputMode.NoOutput:
                await asyncio.sleep(0)
                self._logger.debug(f"recv_res None")
                pass
        else:
            if output_mode == OutputMode.SixteenBit:
                res = array.array('H', await stream.recv(pixel_count * 2))
                if not BIG_ENDIAN:
                    res.byteswap()
                self._logger.debug(f"recv_res 16")
                await asyncio.sleep(0)
                self._logger.debug(f"recv_res sleep")
                return res
            if output_mode == OutputMode.EightBit:
                res = array.array('B', await stream.recv(pixel_count))
                self._logger.debug(f"recv_res 8")
                await asyncio.sleep(0)
                self._logger.debug(f"recv_res sleep")
                return res

class LowLevelCommand(BaseCommand):
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
    @classmethod
    def as_struct_layout(cls):
        """Convert to Amaranth data.Struct
        Returns
        -------
        :class: data.Struct
        """
        return data.StructLayout({**cls.bitlayout.as_struct_layout(), **cls.bytelayout.as_struct_layout()})
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
    def as_dict(self):
        """Convert to nested dictionary of field names:values
        Returns
        -------
        :class: dict
        """
        return {"type": self.cmdtype, 
                "payload": {self.fieldstr: 
                    {**self.bitlayout.pack_dict(vars(self)), **self.bytelayout.pack_dict(vars(self))}}}
    def pack(self):
        return bytes(self)
    async def transfer(self, stream):
        stream.send(bytes(self))
        await stream.flush()



class BeamType(enum.IntEnum, shape = 2):
    NoBeam              = 0
    Electron            = 1
    Ion                 = 2

class DwellTimeVal(int):
    '''Dwell time is measured in units of ADC cycles.
        One DwellTime = 125 ns'''
    def __init__(self, value):
        assert value <= 65536, f"Pixel dwell time {value} is higher than 65536. Dwell times are limited to 16 bit values"
        self.value = value - 1 #Dwell time counter is 0-indexed


class SynchronizeCommand(LowLevelCommand):
    bitlayout = BitLayout({"mode": {
            "raster": 1,
            "output": OutputMode
        }})
    bytelayout = ByteLayout({"cookie": 2})

class AbortCommand(LowLevelCommand):
    pass

class FlushCommand(LowLevelCommand):
    pass

class ExternalCtrlCommand(LowLevelCommand):
    bitlayout = BitLayout({"enable": 1})

class BeamSelectCommand(LowLevelCommand):
    bitlayout = BitLayout({"beam_type": BeamType})

class BlankCommand(LowLevelCommand):
    bitlayout = BitLayout({"enable": 1, "inline": 1})
    def __init__(self, enable: bool, inline:bool = False):
        super().__init__(enable=enable, inline=inline)

class DelayCommand(LowLevelCommand):
    bytelayout = ByteLayout({"delay": 2})


@dataclass
class DACCodeRange:
    start: int # UQ(14,0)
    count: int # UQ(14,0)
    step:  int # UQ(8,8)

class RasterRegionCommand(LowLevelCommand):
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

class RasterPixelCommand(LowLevelCommand):
    bytelayout = ByteLayout({"dwell_time" : 2})

class ArrayCommand(LowLevelCommand):
    bitlayout = BitLayout({"cmdtype": CmdType})
    bytelayout = ByteLayout({"array_length": 2})

class RasterPixelRunCommand(LowLevelCommand):
    bytelayout = ByteLayout({"length": 2, "dwell_time" : 2})
    def __init__(self, *, length, dwell_time):
        self.length = length
        self.dwell_time = dwell_time
        super().__init__(length=length, dwell_time=dwell_time)
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

class RasterPixelArray(BaseCommand):
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
    @BaseCommand.log_transfer
    async def transfer(self, stream, latency: int, output_mode:OutputMode=OutputMode.SixteenBit):
        for commands, pixel_count in self._iter_chunks(latency):
            stream.send(commands)
            await FlushCommand().transfer(stream)
            yield await self.recv_res(pixel_count, stream, output_mode)

class RasterPixelFreeRunCommand(LowLevelCommand):
    bytelayout = ByteLayout({"dwell_time": 2})

class VectorPixelCommand(LowLevelCommand):
    bytelayout = ByteLayout({"dac_stream": {"x_coord": 2, "y_coord": 2, "dwell_time": 2}})
    def __init__(self, *, x_coord, y_coord, dwell_time):
        dwell = DwellTimeVal(dwell_time).value
        super().__init__(x_coord=x_coord, y_coord=y_coord, dwell_time=dwell)
    def pack(self, **kwargs):
        if kwargs["dwell_time"] == 0:
            return VectorPixelMinDwellCommand.pack(**kwargs)
        else:
            return super().pack(**kwargs)




import itertools
class VectorPixelArray(BaseCommand):
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

class VectorPixelMinDwellCommand(LowLevelCommand):
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


#### start macro commands

# Scan Selector board uses TE 1462051-2 Relay
# Switching delay is 20 ms
RELAY_DELAY_CYCLES = int(20 * pow(10, -6) / (1/(48 * pow(10,6))))
class RelayExternalCtrlCommand(BaseCommand):
    def __init__(self, enable, beam_type):
        assert enable <= 1
        self._enable = enable
        self._beam_type = beam_type

    def __repr__(self):
        return f"RelayExternalCtrlCommand(enable={self._enable}, beam_type={self._beam_type})"

    @BaseCommand.log_transfer
    async def transfer(self, stream):
        await BlankCommand(enable=(1-self._enable), inline=True).transfer(stream)
        await ExternalCtrlCommand(enable=self._enable).transfer(stream)
        await BeamSelectCommand(beam_type=self._beam_type).transfer(stream)
        await DelayCommand(delay=RELAY_DELAY_CYCLES).transfer(stream)
        await stream.flush()


class RasterScanCommand(BaseCommand):
    def __init__(self, *, cookie: int, x_range: DACCodeRange, y_range: DACCodeRange, dwell: int):
        self._cookie  = cookie
        self._x_range = x_range
        self._y_range = y_range
        self._dwell   = dwell

    def __repr__(self):
        return f"RasterScanCommand(cookie={self._cookie}, x_range={self._x_range}, y_range={self._y_range}, dwell={self._dwell}>)"

    def pack(self):
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
                chunk = array.array('H', [self._dwell]*array_count)
                if not BIG_ENDIAN: # there is no `array.array('>H')`
                    chunk.byteswap()
                commands.extend(chunk.tobytes())
            if remainder_pixel_count > 0:
                commands.extend(bytes(RasterPixelRunCommand(dwell_time = self._dwell, length = remainder_pixel_count)))

        pixel_count = 0
        total_dwell = 0
        for _ in range(self._x_range.count * self._y_range.count):
            pixel_count += 1
            total_dwell += self._dwell
            if total_dwell >= latency:
                append_command(pixel_count)
                yield(commands, pixel_count)
                commands = bytearray()
                pixel_count = 0
                total_dwell = 0
        if pixel_count > 0:
            append_command(pixel_count)
            yield(commands, pixel_count)
    
    @BaseCommand.log_transfer
    async def transfer(self, stream, latency: int, output_mode:OutputMode=OutputMode.SixteenBit):
        MAX_PIPELINE = 32

        tokens = MAX_PIPELINE
        token_fut = asyncio.Future()

        async def sender():
            nonlocal tokens
            for commands, pixel_count in self._iter_chunks(latency):
                self._logger.debug(f"sender: tokens={tokens}")
                if tokens == 0:
                    await FlushCommand().transfer(stream)
                    await token_fut
                stream.send(commands)
                tokens -= 1
                await asyncio.sleep(0)
            await FlushCommand().transfer(stream)

        await SynchronizeCommand(cookie=self._cookie, raster=True, output = output_mode).transfer(stream)
        await RasterRegionCommand(x_range=self._x_range, y_range=self._y_range).transfer(stream)
        asyncio.create_task(sender())

        for commands, pixel_count in self._iter_chunks(latency):
            tokens += 1
            if tokens == 1:
                token_fut.set_result(None)
                token_fut = asyncio.Future()
            self._logger.debug(f"recver: tokens={tokens}")
            yield await self.recv_res(pixel_count, stream, output_mode)

class RasterPixelArray(BaseCommand):
    def __init__(self, dwell_generator):
        self.dwell_generator = dwell_generator
    def pack(self):
        all_commands = bytearray()
        iter_chunks = self._iter_chunks(self.dwell_generator)
        iter_chunks.send(None)
        while True:
            try:
                commands, pixel_count = iter_chunks.send(latency)
            except StopIteration:
                break
            
        return bytes(all_commands)
    def _iter_chunks(self, dwell_generator):
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
        max_time, max_points = yield
        while True:
            try:
                dwell = next(self.dwell_generator)
                chunk.append(pixel)
                pixel_count += 1
                total_dwell += pixel
                if len(chunk) == 0xffff or total_dwell >= latency:
                    append_command(chunk)
                    del chunk[:] # clear
                if total_dwell >= latency:
                    max_time, max_points = yield (commands, pixel_count)
                    commands = bytearray()
                    pixel_count = 0
                    total_dwell = 0
            except StopIteration:
                break
        if chunk:
            append_command(chunk)
            yield (commands, pixel_count)
    async def transfer(self, stream, latency: int, output_mode:OutputMode=OutputMode.SixteenBit):
        MAX_PIPELINE = 32

        tokens = MAX_PIPELINE
        token_fut = asyncio.Future()

        async def sender():
            nonlocal tokens
            for commands, pixel_count in self._iter_chunks(latency):
                self._logger.debug(f"sender: tokens={tokens}")
                if tokens == 0:
                    stream.send(FlushCommand().message)
                    await stream.flush()
                    await token_fut
                stream.send(commands)
                tokens -= 1
                await asyncio.sleep(0)
            stream.send(FlushCommand().message)
            await stream.flush()
        asyncio.create_task(sender())

        for commands, pixel_count in self._iter_chunks(latency):
            tokens += 1
            if tokens == 1:
                token_fut.set_result(None)
                token_fut = asyncio.Future()
            self._logger.debug(f"recver: tokens={tokens}")
            yield await self.recv_res(pixel_count, stream, output_mode)

class CommandSequence:
    """A sequence of commands
    """
    def __init__(self, *, sync:bool=True, cookie: int=123, output: OutputMode=OutputMode.SixteenBit, raster:bool=False,
                verbose:bool=False):
        self._bytes = bytearray()
        self._output = output
        self._raster = raster
        self.verbose = verbose
        if sync:
            self.add(SynchronizeCommand(cookie=cookie, output=output, raster=raster))
    def add(self, other, verbose:bool=False):
        """
        Parameters
        ----------
        other
        verbose
        """
        if self.verbose | verbose:
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



        