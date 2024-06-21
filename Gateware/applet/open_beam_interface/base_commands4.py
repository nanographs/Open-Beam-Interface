# import struct
# import enum
# from collections import UserDict

# from amaranth import *
# from amaranth import ShapeCastable, Shape
# from amaranth.lib import enum, data, wiring
# from amaranth.lib.wiring import In, Out, flipped

# from . import StreamSignature




# class CommandLayout(UserDict):
#     def unpack_apply(self, *, start_func=eval("lambda key, value: (key, value)"),
#                             unpack_func=eval("lambda dict: dict"),
#                             end_func=eval("lambda key, value: dict")):
#         new_dict = {}
#         def unpack(a_dict, new_dict):
#             for key, value in a_dict.items():
#                 print(f"**{key}: {value}")
#                 key, value = start_func(key, value)
#                 if isinstance(value, dict):
#                     new_dict[key] = unpack_func(unpack(value, {}))
#                 else:
#                     new_dict.update(self.zip_dict(*end_func(key, value)))
#             return new_dict
#         return unpack(self.data, new_dict)
    
#     @staticmethod
#     def unpack_layouts(key, value):
#         if isinstance(value, ShapeCastable):
#             value = value.as_shape()
#         if isinstance(value, data.Layout):
#             value = value._fields
#         print(f"unpacked {key}: {value}")
#         return key, value
    
#     @staticmethod
#     def cast_shapes(key, value):
#         if isinstance(value, data.Field):
#             value = value._shape
#         if isinstance(value, data.Shape):
#             value = value._width
#         print(f"cast {key}: {value}")
#         return key, value
        
    
#     @staticmethod
#     def zip_dict(key, value):
#         if isinstance(key, list):
#             return {a_key:a_value for a_key, a_value in zip(key, value)}
#         else:
#             return {key:value}

#     def parse(self):
#         return self.unpack_apply(start_func=self.unpack_layouts, 
#         end_func=self.cast_shapes)


# class ByteLayout(CommandLayout):
#     def pack_fn(self):
#         print(self.parse())
    
#     @staticmethod
#     def cast_shapes(key, value):
#         key, value = CommandLayout.cast_shapes(key, value)
#         if value%8 != 0:
#             key = [key, f"padding_{key}"]
#             value = [value, (8-value%8)] #pad to whole bytes
#         return key, value



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

# class RasterRegionCommand:
#     bytelayout = ByteLayout({"region": RasterRegion, "cookies": {"a": 8, "b": 16}, "dwelltime": DwellTime, "mode": OutputMode})

# print(RasterRegionCommand.bytelayout.parse())