from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
import enum
import struct
import array
from . import Command, CmdType, OutputMode, BeamType

BIG_ENDIAN = (struct.pack('@H', 0x1234) == struct.pack('>H', 0x1234))


@dataclass
class DACCodeRange:
    start: int # UQ(14,0)
    count: int # UQ(14,0)
    step:  int # UQ(8,8)

class DwellTime(int):
    '''Dwell time is measured in units of ADC cycles.
        One DwellTime = 125 ns'''
    def __init__(self, value):
        assert value <= 65536, f"Pixel dwell time {value} is higher than 65536. Dwell times are limited to 16 bit values"
        self.value = value - 1 #Dwell time counter is 0-indexed


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
    
    @property
    def test_response(self):
        return []

class SynchronizeCommand(BaseCommand):
    def __init__(self, *, cookie: int, raster: bool, output: OutputMode=OutputMode.SixteenBit):
        self._cookie = cookie
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
    
    @property
    def test_response(self):
        return [65535, self._cookie]


class AbortCommand(BaseCommand):
    def __repr__(self):
        return f"AbortCommand"
    
    @property
    def message(self):
        return Command.serialize(CmdType.Abort, 
                payload = 
                {"abort": {
                    "reserved": 0,  
                }})
    
class FlushCommand(BaseCommand):
    def __repr__(self):
        return f"FlushCommand"
    
    @property
    def message(self):
        return Command.serialize(CmdType.Flush, 
                payload = 
                {"flush": {
                    "reserved": 0,  
                }})

class ExternalCtrlCommand(BaseCommand):
    def __init__(self, enable:bool):
        self._enable = enable

    def __repr__(self):
        return f"ExternalCtrlCommand(enable={self._enable})"

    @property
    def message(self):
        return Command.serialize(CmdType.ExternalCtrl, 
                payload = 
                {"external_ctrl": {
                    "reserved": 0,  
                    "payload": {
                        "enable": self._enable
                    }
                }})

class BeamSelectCommand(BaseCommand):
    def __init__(self, beam_type:BeamType):
        self._beam_type = beam_type
    @property
    def message(self):
        return Command.serialize(CmdType.BeamSelect, 
                payload = 
                {"beam_select": {
                    "reserved": 0,  
                    "payload": {
                        "beam_type": self._beam_type
                    }
                }})

class BlankCommand(BaseCommand):
    def __init__(self, enable:bool=True, inline: bool=False):
        self._enable = enable
        self._inline = inline

    def __repr__(self):
        return f"BlankCommand(enable={self._enable}, inline={self._inline})"

    @property
    def message(self):
        return Command.serialize(CmdType.Blank, 
                payload = 
                {"blank": {
                    "reserved": 0,
                    "payload": {
                        "enable": self._enable,
                        "inline": self._inline
                    }    
                }})


class DelayCommand(BaseCommand):
    def __init__(self, delay):
        assert delay <= 65535
        self._delay = delay

    def __repr__(self):
        return f"DelayCommand(delay={self._delay})"

    @property
    def message(self):
        return Command.serialize(CmdType.Delay, 
                payload = 
                {"delay": {
                    "reserved": 3,
                    "payload": {"delay": self._delay},  
                }})



class RasterRegionCommand(BaseCommand):
    def __init__(self, *, x_range: DACCodeRange, y_range: DACCodeRange, 
                xflip=False, yflip=False, rotate90=False):
        self._x_range = x_range
        self._y_range = y_range
        self._xflip = xflip
        self._yflip = yflip
        self._rotate90 = rotate90

    def __repr__(self):
        return f"RasterRegionCommand(x_range={self._x_range}, y_range={self._y_range}, x_flip={self._xflip}, y_flip={self._yflip}, rotate_90={self._rotate90})"

    @property
    def message(self):
        return Command.serialize(CmdType.RasterRegion, 
                payload = 
                {"raster_region": {
                    "reserved": 0,
                    "payload": {
                        "transform": {
                            "xflip": self._xflip,
                            "yflip": self._yflip,
                            "rotate90": self._rotate90,
                        },
                        "roi": {
                            "x_start": self._x_range.start,
                            "x_count": self._x_range.count,
                            "x_step": self._x_range.step,
                            "y_start": self._y_range.start,
                            "y_count": self._y_range.count,
                            "y_step": self._y_range.step
                        }
                    }    
                }})

class RasterPixelRunCommand(BaseCommand):
    def __init__(self, *, dwell: int, length: int):
        assert dwell <= 65536
        self._dwell   = DwellTime(dwell)
        self._length  = length

    def __repr__(self):
        return f"RasterPixelRunCommand(dwell={self._dwell}, length={self._length})"

    def _iter_chunks(self):
        max_counter = 65536

        commands = bytearray()
        def append_command(run_length):
            nonlocal commands
            cmd = Command.serialize(CmdType.RasterPixelRun, 
                payload = 
                {"raster_pixel_run": {
                    "reserved": 0,
                    "payload": {
                        "length": run_length - 1,
                        "dwell_time": self._dwell
                    }    
                }})
            commands.extend(cmd)

        pixel_count = 0
        total_dwell = 0
        for _ in range(self._length):
            pixel_count += 1
            total_dwell += self._dwell
            if total_dwell >= max_counter:
                append_command(pixel_count)
                print(f"{len(commands)=}, {pixel_count=}, {total_dwell=}")
                yield (commands, pixel_count)
                commands = bytearray()
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
    
    @property
    def test_response(self):
        return [0]*self._length

class RasterPixelFreeRunCommand(BaseCommand):
    def __init__(self, *, dwell: int):
        assert dwell <= 65536
        self._dwell   = DwellTime(dwell)

    def __repr__(self):
        return f"RasterPixelFreeRunCommand(dwell={self._dwell})"

    @property
    def message(self):
        return Command.serialize(CmdType.RasterPixelFreeRun, 
                payload = 
                {"raster_pixel_free_run": {
                    "reserved": 0,
                    "payload": {
                        "dwell_time": self._dwell
                    }    
                }})

class VectorPixelCommand(BaseCommand):
    def __init__(self, *, x_coord: int, y_coord: int, dwell: DwellTime,
                        xflip=False, yflip=False, rotate90=False):
        assert x_coord <= 65535
        assert y_coord <= 65535
        assert dwell <= 65536
        self._x_coord = x_coord
        self._y_coord = y_coord
        self._dwell   = DwellTime(dwell)
        self._xflip = xflip
        self._yflip = yflip
        self._rotate90 = rotate90

    def __repr__(self):
        return f"VectorPixelCommand(x_coord={self._x_coord}, y_coord={self._y_coord}, dwell={self._dwell}, x_flip={self._xflip}, y_flip={self._yflip}, rotate_90={self._rotate90})"

    @property
    def message(self):
        if self._dwell == 0:
            return Command.serialize(CmdType.VectorPixelMinDwell, 
                    payload = 
                    {"vector_pixel_min": {
                        "reserved": 0,
                        "payload": {
                            "transform": {
                                "xflip": self._xflip,
                                "yflip": self._yflip,
                                "rotate90": self._rotate90,
                            },
                            "x_coord": self._x_coord,
                            "y_coord": self._y_coord,
                        }    
                    }})
        else:
            return Command.serialize(CmdType.VectorPixel, 
                    payload = 
                    {"vector_pixel": {
                        "reserved": 0,
                        "payload": {
                            "transform": {
                                "xflip": self._xflip,
                                "yflip": self._yflip,
                                "rotate90": self._rotate90,
                            },
                            "x_coord": self._x_coord,
                            "y_coord": self._y_coord,
                            "dwell_time": self._dwell
                        }    
                    }})
    @property
    def test_response(self):
        return [0]



class RasterPixelsCommand(BaseCommand):
    def __init__(self, *, dwells: list[DwellTime]):
        self._dwells  = dwells
        
    def __repr__(self):
        return f"RasterPixelsCommand(dwells=<list of {len(self._dwells)}>)"
    
    def _iter_chunks(self):
        max_counter = 65536
        assert not any(dwell > max_counter for dwell in self._dwells), "Pixel dwell time higher than 65536. Dwell times are limited to 16 bit values"

        commands = bytearray()
        def append_command(chunk):
            nonlocal commands
            cmd = Command.serialize(CmdType.RasterPixel, 
                payload = 
                {"raster_pixel": {
                    "reserved": 0,
                    "payload": {
                        "length": len(chunk) - 1}    
                }})
            commands.extend(cmd)
            if not BIG_ENDIAN: # there is no `array.array('>H')`
                chunk.byteswap()
            commands.extend(chunk.tobytes())

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
                commands = bytearray()
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
    
    @property
    def test_response(self):
        return [0]*len(self._dwells)


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




            






