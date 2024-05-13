from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
import enum
import struct
import array

from amaranth import *
from amaranth import ShapeCastable
from amaranth.lib import enum, data


BIG_ENDIAN = (struct.pack('@H', 0x1234) == struct.pack('>H', 0x1234))


DwellTime = unsigned(16)

class RasterRegion(data.Struct):
    x_start: 14 # UQ(14,0)
    padding_x_start: 2
    x_count: 14 # UQ(14,0)
    padding_x_count: 2
    x_step:  16 # UQ(8,8)
    y_start: 14 # UQ(14,0)
    padding_y_start: 2
    y_count: 14 # UQ(14,0)
    padding_y_count: 2
    y_step:  16 # UQ(8,8)

class BeamType(enum.Enum, shape = 2):
    NoBeam              = 0
    Electron            = 1
    Ion                 = 2

class OutputMode(enum.Enum, shape = 2):
    SixteenBit          = 0
    EightBit            = 1
    NoOutput            = 2

class Transforms(data.Struct):
    xflip: 1
    yflip: 1
    rotate90: 1


class CmdType(enum.Enum, shape=5):
        Synchronize = 0
        Abort       = 1
        Flush       = 2
        ExternalCtrl = 3
        BeamSelect = 4
        Blank = 5
        Delay  = 6

        RasterRegion = 10
        RasterPixel = 11
        RasterPixelRun = 12
        RasterPixelFreeRun = 13
        VectorPixel = 14
        VectorPixelMinDwell = 15   


class Command(data.Struct):
    

    # Only used for transfer via USB, where the command is split into octets.
    class Header(data.Struct):
        type: CmdType
        payload: 8 - Shape.cast(CmdType).width

    PAYLOAD_SIZE = { # type -> bytes
        CmdType.Synchronize: 2,
        CmdType.Abort: 0,
        CmdType.Flush: 0,
        CmdType.Delay: 2,
        CmdType.ExternalCtrl: 0,
        CmdType.BeamSelect: 0,
        CmdType.Blank: 0,

        CmdType.RasterRegion: 12,
        CmdType.RasterPixel: 2,
        CmdType.RasterPixelRun: 4,
        CmdType.RasterPixelFreeRun: 2,
        CmdType.VectorPixel: 6,
        CmdType.VectorPixelMinDwell: 4

    }
    # will be replaced by Amaranth's `Choice` when it is a part of the public API
    def payload_size_array(PAYLOAD_SIZE, Type):
        return Array([
        PAYLOAD_SIZE.get(Type._value2member_map_.get(value)) 
        if value in Type._value2member_map_ else 0
        for value in range(1 << Shape.cast(Type).width)
        ])
    PAYLOAD_SIZE_ARRAY = payload_size_array(PAYLOAD_SIZE, CmdType)

    type: CmdType
    payload: data.UnionLayout({
        "synchronize": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "mode": data.StructLayout({
                    "raster": 1,
                    "output": OutputMode,
                }),
                "cookie": 16
            })
        }),
        "abort": data.StructLayout({
            "reserved": 0
        }),
        "flush": data.StructLayout({
            "reserved": 0
        }),
        "external_ctrl": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "enable": 1
            })
        }),
        "beam_select": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "beam_type": BeamType
            })
        }),
        "blank": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "enable": 1,
                "inline": 1
                })
        }),
        "delay": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "delay": 16
            })
        }),
        "raster_region": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "transform": Transforms,
                "roi": RasterRegion
            })
        }),
        "raster_pixel": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "length": 16,
                "dwell_time": DwellTime
            })
        }),
        "raster_pixel_run": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "length": 16,
                "dwell_time": DwellTime
            })
        }),
        "raster_pixel_free_run": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "dwell_time": DwellTime
            })
        }),
        "vector_pixel": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "transform": Transforms,
                "dac_stream": data.StructLayout({
                    "x_coord": 14,
                    "padding_x": 2,
                    "y_coord": 14, 
                    "padding_y": 2,
                    "dwell_time": DwellTime
                })
            }),
        }),
        "vector_pixel_min": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "transform": Transforms,
                "dac_stream": data.StructLayout({
                "x_coord": 14,
                "padding_x": 2,
                "y_coord": 14,
                "padding_y": 2,
                "dwell_time": DwellTime
                })
            })
        }),
    })

    @classmethod
    def serialize(cls, type: CmdType, payload) -> bytes:
        # https://amaranth-lang.org/docs/amaranth/latest/stdlib/data.html#amaranth.lib.data.Const
        command_bits = cls.const({"type": type,
                        "payload":
                        {**payload}}).as_value().value
        command_length = cls.PAYLOAD_SIZE[type]
        return command_bits.to_bytes(command_length+1, byteorder="little")
    
        # usage: Command.serialize(Command.Type.Command4, payload=1234)



@dataclass
class DACCodeRange:
    start: int # UQ(14,0)
    count: int # UQ(14,0)
    step:  int # UQ(8,8)

class DwellTimeVal(int):
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
    
    @property
    def byte_response(self):
        cookie = struct.pack('>H', self._cookie)
        print(f"{cookie=}")
        print(f"{len(cookie)=}")
        return struct.pack('>HBB', 0xffff, cookie[0], cookie[1])


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
        self._dwell   = DwellTimeVal(dwell)
        self._length  = length

    def __repr__(self):
        return f"RasterPixelRunCommand(dwell={self._dwell}, length={self._length})"

    def _iter_chunks(self, latency=65536):
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
            if total_dwell >= max_latency:
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
        self._dwell   = DwellTimeVal(dwell)

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
        self._dwell   = DwellTimeVal(dwell)
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
                        "dac_stream": {
                            "x_coord": self._x_coord,
                            "y_coord": self._y_coord,
                            }
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
                            "dac_stream": {
                            "x_coord": self._x_coord,
                            "y_coord": self._y_coord,
                            "dwell_time": self._dwell
                            }
                        }    
                    }})
    @property
    def test_response(self):
        return [0]



class RasterPixelsCommand(BaseCommand):
    def __init__(self, *, dwells: list[DwellTimeVal]):
        self._dwells  = dwells
        
    def __repr__(self):
        return f"RasterPixelsCommand(dwells=<list of {len(self._dwells)}>)"
    
    def _iter_chunks(self, latency=65536):
        assert not any(dwell > latency for dwell in self._dwells), f"Pixel dwell time higher than {latency}"

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
    def __init__(self, cookie: int=123, output: OutputMode=OutputMode.SixteenBit, raster:bool=False):
        self._output = output
        self._raster = raster
        self.add(SynchronizeCommand(cookie=cookie, output=output, raster=raster))
    def add(self, other: BaseCommand):
        # print(f"adding {other!r}")
        try:
            self._message.extend(other.message)
        except TypeError:
            raise TypeError("Command syntax error. Did your use 'command' instead of 'command()'?")
        #self._response.extend(other.response)

    @property
    def message(self):
        return self._message