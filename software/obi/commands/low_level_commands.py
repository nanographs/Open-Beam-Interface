from .structs import (BitLayout, ByteLayout, CmdType,
                    OutputMode, OutputEnable, BeamType, 
                    u14, u16, DwellTime, DACCodeRange, CMD_SHAPE)
from . import BaseCommand

from amaranth import *
from amaranth.lib import enum, data, wiring

import json
import inspect

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
        cls.generate_bitfield_wavedrom()
    @classmethod
    def generate_bitfield_wavedrom(cls):
        if cls is LowLevelCommand or cls.__module__ != __name__:
            return

        def prepend_wavedrom_block(wavedrom_dict: dict, name:str=""):
            wavedrom_json = json.dumps(wavedrom_dict, indent=2)
            block = ["", f".. wavedrom:: {cls.__name__}{name}", ""]
            block += [f"    {L}" for L in wavedrom_json.splitlines()]
            cls.__doc__ =  "\n".join(block) + "\n" + (cls.__doc__ or "")

        if cls.bytelayout:
            prepend_wavedrom_block(cls.bytelayout.wavedrom(), "Bytes")
        prepend_wavedrom_block(cls.bitlayout.wavedrom(cls.cmdtype), "Bits")

    @classmethod
    def as_struct_layout(cls):
        """Convert to Amaranth data.Struct
        Returns
        -------
        :class: data.Struct
        """
        return data.StructLayout({**cls.bitlayout.as_struct_layout(), **cls.bytelayout.as_struct_layout()})
    @classmethod
    def header(cls, **kwargs):
        """Generate just the header (first byte) of a command sequence
        Returns:
            int
        """
        header_funcstr = cls.bitlayout.pack_fn(cls.cmdtype)
        func = eval(f"lambda value_dict: {header_funcstr}")
        return func(kwargs)
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    def __bytes__(self):
        """return bytes
        """
        return self.pack()
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
        return self.pack_fn(vars(self))
    async def transfer(self, stream):
        await stream.write(bytes(self))
        await stream.flush()



class SynchronizeCommand(LowLevelCommand):
    bitlayout = BitLayout({"mode": {
            "raster": 1,
            "output": OutputMode
        }})
    bytelayout = ByteLayout({"cookie": 2})
    def __init__(self, *, cookie:u16, output:OutputMode, raster:bool):
        super().__init__(cookie=cookie, output=output, raster=raster)

    # async def transfer(self, stream):
    #     await stream.write(bytes(self))
    #     # synchronize command is exempt from output mode
    #     return await stream.readuntil(bytes(self.cookie))


class AbortCommand(LowLevelCommand):
    '''
    End the current :class:`RasterRegionCommand`
    '''
    def __init__(self):
        super().__init__()

class FlushCommand(LowLevelCommand):
    '''
    Submits the data in the FPGA FIFO over USB,
    regardless of whether the FIFO is full.
    '''
    def __init__(self):
        super().__init__()

class ExternalCtrlCommand(LowLevelCommand):
    '''
    Enable or disable external control of the beam
    '''
    bitlayout = BitLayout({"enable": 1})
    def __init__(self, enable: bool):
        super().__init__(enable=enable)


class BeamSelectCommand(LowLevelCommand):
    '''
    Select a beam type. Blanking will be enabled on all other beams if blanking IO is available.

    Args:
        beam_type
    '''
    bitlayout = BitLayout({"beam_type": BeamType})
    def __init__(self, beam_type: BeamType):
        super().__init__(beam_type=beam_type)

class BlankCommand(LowLevelCommand):
    """
    Triggers beam blanking

    Args:
        enable: True if blanking, False if unblanking.
        inline: True if blanking in sync with the next pixel, \
            False if blanking immediately upon command execution. Defaults to False.
    """
    bitlayout = BitLayout({"enable": 1, "inline": 1})
    def __init__(self, enable: bool, inline:bool = False):
        super().__init__(enable=enable, inline=inline)

class DelayCommand(LowLevelCommand):
    '''
    Starts a counter, pausing execution of subsequent commands until the
    time is up.
    One unit of delay is one 48MHz clock cycle, or 20.83 ns.
    '''
    bytelayout = ByteLayout({"delay": 2})
    def __init__(self, delay: u16):
        super().__init__(delay=delay)


class RasterRegionCommand(LowLevelCommand):
    '''
    Sets the region of the internal raster scanner module.
    Takes two DAC code ranges (X andas input.
    '''
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
    '''
    One pixel dwell value. The position at which this pixel is executed
    depends on the current :class:`RasterRegionCommand`. 
    '''
    bitlayout = BitLayout({"output_en": OutputEnable})
    bytelayout = ByteLayout({"dwell_time" : 2})
    def __init__(self, dwell_time:DwellTime, output_en: OutputEnable=OutputEnable.Enabled):
        super().__init__(output_en=output_en, dwell_time=dwell_time)

class ArrayCommand(LowLevelCommand):
    bytelayout = ByteLayout({"command": 1, "array_length": 2})
    def __init__(self, command:bytes, array_length: u16):
        super().__init__(command=command, array_length=array_length)

class RasterPixelFillCommand(LowLevelCommand):
    bytelayout = ByteLayout({"dwell_time" : 2})
    def __init__(self, dwell_time:DwellTime):
        super().__init__(dwell_time=dwell_time)

class RasterPixelRunCommand(LowLevelCommand):
    '''
    One pixel dwell value, to be repeated for a specified length. 
    The position at which these pixels are executed
    depends on the current :class:`RasterRegionCommand`. 
    '''
    bitlayout = BitLayout({"output_en": OutputEnable})
    bytelayout = ByteLayout({"length": 2, "dwell_time" : 2})
    def __init__(self, length: u16, dwell_time: DwellTime, output_en: OutputEnable=OutputEnable.Enabled):
        super().__init__(output_en=output_en, length=length, dwell_time=dwell_time)

class RasterPixelFreeRunCommand(LowLevelCommand):
    '''
    One pixel dwell value, to be repeated indefinitely.
    The position at which these pixels are executed
    depends on the current :class:`RasterRegionCommand`.
    '''
    bytelayout = ByteLayout({"dwell_time": 2})
    def __init__(self, dwell_time:DwellTime):
        super().__init__(dwell_time=dwell_time)

class VectorPixelCommand(LowLevelCommand):
    '''
    Sets DAC output to the coordinate X, Y for the specified dwell time.
    '''
    bitlayout = BitLayout({"output_en": OutputEnable})
    bytelayout = ByteLayout({"x_coord": 2, "y_coord": 2, "dwell_time": 2})
    def __init__(self, x_coord:u14, y_coord:u14, dwell_time:u16, output_en: OutputEnable=OutputEnable.Enabled):
        super().__init__(output_en=output_en, x_coord=x_coord, y_coord=y_coord, dwell_time=dwell_time)
    def pack(self):
        if vars(self)["dwell_time"] <= 1:
            return VectorPixelMinDwellCommand(**vars(self)).pack()
        else:
            return super().pack()
    def as_dict(self):
        if vars(self)["dwell_time"] <= 1:
            return VectorPixelMinDwellCommand(**vars(self)).as_dict()
        else:
            return super().as_dict()
    async def transfer(self, stream, output_mode=OutputMode.SixteenBit):
        await stream.write(bytes(self))
        await stream.write(bytes(FlushCommand()))
        return await self.recv_res(1, stream, output_mode)
        
class VectorPixelMinDwellCommand(LowLevelCommand):
    bitlayout = BitLayout({"output_en": OutputEnable})
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
                RasterPixelFillCommand,
                RasterPixelFreeRunCommand,
                VectorPixelCommand,
                VectorPixelMinDwellCommand]




class Command(data.Struct):
    """
    The layout of cmd_stream (which is producedby CommandParser and consumed by CommandExecutor)

    Fields:
        type: CmdType
        payload: a Union Layout of all LowLevelCommands

    Properties:
        deserialized_states: A dictionary mapping each command type to a list of states corresponding to
        each subsequent byte of the command.
    """
    type: CmdType
    payload: data.UnionLayout({cmd.fieldstr: cmd.as_struct_layout() for cmd in all_commands})
    deserialized_states = {cmd.cmdtype : 
            {f"{cmd.fieldstr}_{state}":offset for state, offset in cmd.bytelayout.as_deserialized_states().items()} 
            for cmd in all_commands}