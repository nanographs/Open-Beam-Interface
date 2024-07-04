from .structs import BitLayout, ByteLayout, CmdType, OutputMode, BeamType, DACCodeRange
from . import BaseCommand

from amaranth import *
from amaranth.lib import enum, data, wiring

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
        await stream.write(bytes(self))
        await stream.flush()


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