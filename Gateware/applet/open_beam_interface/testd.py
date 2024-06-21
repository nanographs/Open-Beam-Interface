import struct
import enum
from collections import UserDict

from amaranth import *
from amaranth import ShapeCastable, Shape
from amaranth.lib import enum, data, wiring
from amaranth.lib.wiring import In, Out, flipped

from . import StreamSignature


# def expand_map(value):
#     if isinstance(value, ShapeCastable):
#         print(f"*cast from {value=} {type(value)=}")
#         value = value.as_shape()
#         print(f"cast to {value=} {type(value)=}")
#     elif isinstance(value, data.Layout):
#         print(f"**cast from {value=} {type(value)=}")
#         value = value.members
#         print(f"cast to {value=} {type(value)=}")
#     return value


# class CommandLayout(UserDict):
#     def unpack_apply(self, 
#         passthru_func=eval("lambda key, value: (key, value)"),
#         exit_func=eval("lambda key, value: (key, value)")):
#         def unpack(from_dict, to_dict):
#             print(f"{to_dict=}")
#             for key, value in from_dict.items():
#                 value = passthru_func(value)
#                 if isinstance(value, dict):
#                     to_dict[key] = unpack(value, {})
#                 else:
#                     to_dict.update({key:value})
#             return to_dict
#         return unpack(self.data, {})


# class RasterRegion(data.Struct):
#     x_start: 14 # UQ(14,0)
#     x_count: 14 # UQ(14,0)
#     x_step:  16 # UQ(8,8)
#     y_start: 14 # UQ(14,0)
#     y_count: 14 # UQ(14,0)
#     y_step:  16 # UQ(8,8)


# DwellTime = unsigned(16)

# class OutputMode(enum.IntEnum, shape = 8):
#     SixteenBit          = 0
#     EightBit            = 1
#     NoOutput            = 2


# class Tly(data.Struct):
#     type: 4
#     payload: data.StructLayout({
#         "cookies": data.StructLayout({"a": 1, "b": 2}),
#         "cookies2": data.StructLayout({"c": 2, "d": 2}),
#         "cookies3": data.StructLayout({"e": 3, "f": 2})
#     })

# b = CommandLayout({"region": RasterRegion, "cookies": {"a": 8, "b": 16}, 
#                 "dwelltime": DwellTime, "mode": OutputMode, "and": {"f": 8, "g": Tly}})

# print(b.unpack_apply(expand_map))


# class CmdType(enum.IntEnum, shape=4):
#     Synchronize         = 0x0
#     Abort               = 0x1
#     Flush               = 0x2
#     ExternalCtrl        = 0x3
#     BeamSelect          = 0x4
#     Blank               = 0x5
#     Delay               = 0x6

#     Run = 0x8

#     RasterRegion        = 0xa
#     RasterPixel         = 0xb
#     RasterPixelRun      = 0xc
#     RasterPixelFreeRun  = 0xd
#     VectorPixel         = 0xe
#     VectorPixelMinDwell = 0xf 

# print(CmdType << 2)


class CommandLayout:
    bitlayout = "ABC"
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

c = CommandLayout(param1 = "a", param2 = "b")

print(vars(c))