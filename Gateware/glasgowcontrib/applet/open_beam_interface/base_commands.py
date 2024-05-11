from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
import enum
import struct
import array
from . import Command, CmdType

BIG_ENDIAN = (struct.pack('@H', 0x1234) == struct.pack('>H', 0x1234))


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
        self._raster = raster
        self._output = output
        self._raster = raster
        self._output = output

    def __repr__(self):
        return f"SynchronizeCommand(cookie={self._cookie}, raster={self._raster}, outpute={self._output})"

    @property
    def message(self):
        return Command.serialize(CmdType.Synchronize, 
                payload = 
                {"synchronize": {
                    "reserved": 0,
                    "payload": {
                        "mode": {
                            "raster": self._raster,
                            "output": self._output
                        },
                        "cookie": self._cookie
                    }    
                }})


class AbortCommand(BaseCommand):
    def __repr__(self):
        return f"AbortCommand"
    
    @property
    def message(self):
        return struct.pack(">B", CommandType.Abort)
    
class FlushCommand(BaseCommand):
    def __repr__(self):
        return f"FlushCommand"
    
    @property
    def message(self):
        return struct.pack(">B", CommandType.Flush)
    

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
        self._dwells  = dwells
        
    def __repr__(self):
        return f"RasterPixelsCommand(dwells=<list of {len(self._dwells)}>)"
    
    def _iter_chunks(self):
        max_counter = 65536
        assert not any(dwell > max_counter for dwell in self._dwells), "Pixel dwell time higher than 65536. Dwell times are limited to 16 bit values"

        commands = b""
        def append_command(chunk):
            nonlocal commands
            commands += struct.pack(">BH", CommandType.RasterPixel, len(chunk) - 1)
            if not BIG_ENDIAN: # there is no `array.array('>H')`
                chunk.byteswap()
            commands += chunk.tobytes()

        chunk = array.array('H')
        pixel_count = 0
        total_dwell  = 0
        for pixel in self._dwells:
            chunk.append(pixel)
            pixel_count += 1
            total_dwell  += pixel
            if len(chunk) == 0xffff or total_dwell >= max_counter:
                append_command(chunk)
                del chunk[:] # clear
            if total_dwell >= max_counter:
                yield (commands, pixel_count)
                commands = b""
                pixel_count = 0
                total_dwell = 0
        if chunk:
            append_command(chunk)
            yield (commands, pixel_count)

    @property
    def message(self):
        commands = bytearray()
        for command_chunk, pixel_count in self._iter_chunks():
            commands.extend(command_chunk)
        return commands

class RasterPixelRunCommand(BaseCommand):
    def __init__(self, *, dwell: DwellTime, length: int):
        assert dwell <= 65536
        self._dwell   = dwell
        self._length  = length

    def __repr__(self):
        return f"RasterPixelRunCommand(dwell={self._dwell}, length={self._length})"

    def _iter_chunks(self):
        max_counter = 65536
        assert self._dwell < max_counter, f"Pixel dwell time ({self._dwell}) higher than 65536. Dwell times are limited to 16 bit values"

        commands = b""
        def append_command(run_length):
            nonlocal commands
            commands += struct.pack(">BHH", CommandType.RasterPixelRun, run_length - 1, self._dwell)

        pixel_count = 0
        total_dwell = 0
        for _ in range(self._length):
            pixel_count += 1
            total_dwell += self._dwell
            if total_dwell >= max_counter:
                append_command(pixel_count)
                print(f"{len(commands)=}, {pixel_count=}, {total_dwell=}")
                yield (commands, pixel_count)
                commands = b""
                pixel_count = 0
                total_dwell = 0
        if pixel_count > 0:
            append_command(pixel_count)
            yield (commands, pixel_count)

    @property
    def message(self):
        commands = bytearray()
        for command_chunk, pixel_count in self._iter_chunks():
            print(f"{len(command_chunk)=}")
            commands.extend(command_chunk)
        return commands
        print(f"{len(commands)=}")

        #return struct.pack(">BHH", CommandType.RasterPixelRun, self._length - 1, self._dwell)

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
        print(f"adding {other!r}")
        try:
            self._message.extend(other.message)
        except TypeError:
            raise TypeError("Command syntax error. Did your use 'command' instead of 'command()'?")
        #self._response.extend(other.response)

    @property
    def message(self):
        return self._message




            






