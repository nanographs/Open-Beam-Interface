from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
import enum
import struct
from . import Command, ByteCommandView, ByteCommandLayout
from amaranth import Signal


class OutputMode(enum.IntEnum):
    SixteenBit          = 0
    EightBit            = 1
    NoOutput            = 2

class BeamType(enum.IntEnum):
    NoBeam              = 0
    Electron            = 1
    Ion                 = 2

@dataclass
class DACCodeRange:
    start: int # UQ(14,0)
    count: int # UQ(14,0)
    step:  int # UQ(8,8)

class DwellTime(int):
    '''Dwell time is measured in units of ADC cycles.
        One DwellTime = 125 ns'''
    pass


class BaseCommand(metaclass=ABCMeta):
    # def __init_subclass__(cls):
    #     cls._logger = logger.getChild(f"Command.{cls.__name__}")

    @property
    @abstractmethod
    def message(self):
        ...
    
    @property
    def response(self):
        return 0

class SynchronizeCommand(BaseCommand):
    def __init__(self, *, cookie: int, raster: bool, output: OutputMode=OutputMode.SixteenBit):
        self._cookie = cookie
        self._raster_mode = raster
        self._output_mode = output

    def __repr__(self):
        return f"SynchronizeCommand(cookie={self._cookie}, raster_mode={self._raster_mode}, output_mode={self._output_mode})"

    @property
    def message(self):
        combined = Command.const({
                                "type": Command.Type.Synchronize.value,
                                "payload": {
                                    "synchronize": {
                                        "mode": {
                                            "raster": self._raster_mode,
                                            "output": self._output_mode,
                                        }
                                    }}})
        combined = ByteCommandView(Command, combined).first_byte()
        print(f"{combined=}")
        #combined = int(self._output_mode<<5 | self._raster_mode <<3 | Command.Type.Synchronize.value)
        print(f"cookie= {struct.pack(">H", self._cookie)}")
        print(f"cmd= {struct.pack(">BH", combined, self._cookie)}")
        return struct.pack(">BH", combined, self._cookie)


class AbortCommand(BaseCommand):
    def __repr__(self):
        return f"AbortCommand"
    
    @property
    def message(self):
        return struct.pack(">B", CommandType.Abort)
    

class DelayCommand(BaseCommand):
    def __init__(self, delay):
        assert delay <= 65535
        self._delay = delay

    def __repr__(self):
        return f"DelayCommand(delay={self._delay})"

    @property
    def message(self):
        return struct.pack(">BH", Command.Type.Delay.value, self._delay)
    

class BlankCommand(BaseCommand):
    def __init__(self, enable:bool=True, inline: bool=False):
        self._enable = enablemaller
        self._inline = inline

    def __repr__(self):
        return f"BlankCommand(enable={self._enable}, inline={self._inline})"

    @property
    def message(self):
        combined = int(self._inline<<5 | self._enable << 3 | Command.Type.Blank.value)
        return struct.pack(">B", combined)
        # if self._enable and not self._inline:
        #     return struct.pack('>B', CommandType.Blank)
        # elif self._enable and self._inline:
        #     return struct.pack('>B', CommandType.BlankInline)
        # elif not (self._enable and self._inline):
        #     return struct.pack('>B', CommandType.Unblank)
        # elif not self._enable and self._inline:
        #     return struct.pack('>B', CommandType.UnblankInline)


class ExternalCtrlCommand(BaseCommand):
    def __init__(self, enable:bool):
        self._enable = enable

    def __repr__(self):
        return f"ExternalCtrlCommand(enable={self._enable})"

    @property
    def message(self):
        combined = int(self._enable << 5 | Command.Type.ExtCtrl.value)


class BeamSelectCommand(BaseCommand):
    def __init__(self, beam_type:BeamType):
        self._beam_type = beam_type
    @property
    def message(self):
        combined = int(Command.Type.BeamSelect.value << 5 | self._beam_type)


class RasterRegionCommand(BaseCommand):
    def __init__(self, *, x_range: DACCodeRange, y_range: DACCodeRange):
        self._x_range = x_range
        self._y_range = y_range

    def __repr__(self):
        return f"RasterRegionCommand(x_range={self._x_range}, y_range={self._y_range})"

    @property
    def message(self):
        return struct.pack(">BHHHHHH", CommandType.RasterRegion,
            self._x_range.start, self._x_range.count, self._x_range.step,
            self._y_range.start, self._y_range.count, self._y_range.step)

class RasterPixelsCommand(BaseCommand):
    def __init__(self, *, dwells: list[DwellTime]):
        assert len(dwells) <= 65536
        self._dwells  = dwells
        
    def __repr__(self):
        return f"RasterPixelsCommand(dwells=<list of {len(self._dwells)}>)"

    @property
    def message(self):
        commands = bytearray()
        commands.extend(struct.pack(">BH", CommandType.RasterPixels, len(self._dwells) - 1))
        commands.extend(self._dwells)
        return commands

class RasterPixelRunCommand(BaseCommand):
    def __init__(self, *, dwell: DwellTime, length: int):
        assert dwell <= 65536
        assert length <= 65536, "Run length counter is 16 bits"
        self._dwell   = dwell
        self._length  = length

    def __repr__(self):
        return f"RasterPixelRunCommand(dwell={self._dwell}, length={self._length})"

    @property
    def message(self):
        return struct.pack(">BHH", CommandType.RasterPixelRun, self._length - 1, self._dwell)

class VectorPixelCommand(BaseCommand):
    def __init__(self, *, x_coord: int, y_coord: int, dwell: DwellTime):
        assert x_coord <= 65535
        assert y_coord <= 65535
        assert dwell <= 65536
        self._x_coord = x_coord
        self._y_coord = y_coord
        self._dwell   = dwell

    def __repr__(self):
        return f"VectorPixelCommand(x_coord={self._x_coord}, y_coord={self._y_coord}, dwell={self._dwell})"

    @property
    def message(self):
        if self._dwell == 1:
            return struct.pack(">BHH", CommandType.VectorPixelMinDwell, self._x_coord, self._y_coord)
        else:
            return struct.pack(">BHHH", CommandType.VectorPixel, self._x_coord, self._y_coord, self._dwell-1)

class CommandSequence(BaseCommand):
    _message = bytearray()
    _response = bytearray()
    def __init__(self, output: OutputMode, raster:bool):
        self._output = output
        self._raster = raster
        self.add(SynchronizeCommand(cookie=123, output=output, raster=raster))
    def add(self, other: BaseCommand):
        try:
            self._message.extend(other.message)
        except TypeError:
            raise TypeError("Command syntax error. Did your use 'command' instead of 'command()'?")
        #self._response.extend(other.response)

    @property
    def message(self):
        return self._message




            






