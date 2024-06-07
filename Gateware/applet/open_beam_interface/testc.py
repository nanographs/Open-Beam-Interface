from .base_commands import OutputMode, CmdType#Command, CmdType, SynchronizeCommand, FlushCommand, OutputMode #VectorPixelCommand, 
from amaranth import ShapeCastable, Shape
from amaranth.lib import data
import time
import struct
import enum

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
    
    

def field_dict(payload):
    shape = data.StructLayout({
    "type": CmdType,
    "payload": data.UnionLayout(payload)})

    field_dict = {}
    def unpack(shape):
        for field_name, field in shape._fields.items():
            if isinstance(field.shape, data.Layout):
                unpack(field.shape)
            else:
                try: 
                    Shape.cast(field.shape)
                    unpack(field.shape.as_shape())              
                except:
                    if field.width > 0:
                        print(f"{field_name}: width {field.width}")
                    field_dict.update({field_name: field.width})
    unpack(shape)
    return field_dict

def pack_fn(cmdtype, field_dict):
    command_length = PAYLOAD_SIZE[cmdtype]
    field_values = [str(cmdtype.value)]
    field_offset = field_dict.pop("type")
    for field_name, field_width in field_dict.items():
        if not (("padding" in field_name) | ("reserved" in field_name)):
            field_values.append(f'((value_dict[{field_name!r}] & {(1 << field_width) - 1}) << {field_offset})')
        field_offset += field_width
    func = f'lambda value_dict: int({" | ".join(field_values)}).to_bytes({command_length+1}, byteorder="little")'
    return eval(func)

class BaseCommand:
    def __init_subclass__(cls):
        cls.pack_fn = staticmethod(pack_fn(cls.cmdtype, field_dict(cls.payload)))
        print(f"{field_dict(cls.payload)=}")

    def __init__(self, **kwargs):
        def tovalue(kw):
            try:
                return kw.value
            except:
                return kw
        self._kwargs = {key:tovalue(value) for key, value in kwargs.items()}
        print(f"{self._kwargs=}")

    @property
    def message(self):
        return self.pack_fn(self._kwargs)

class SynchronizeCommand(BaseCommand):
    cmdtype = CmdType.Synchronize
    payload = {"synchronize": data.StructLayout({
                "reserved": 0,
                "payload": data.StructLayout({
                    "mode": data.StructLayout({
                        "raster": 1,
                        "output": OutputMode,
                    }),
                    "cookie": 16})})}


class Command(data.Struct):
    type: CmdType
    payload: data.UnionLayout(SynchronizeCommand.payload)


print(SynchronizeCommand(raster= False, output=OutputMode.NoOutput, cookie = 16383).message)

# repack_code = Command.flatten_fields(CmdType.VectorPixel, 
#                     payload = 
#                     {"vector_pixel": {
#                         "reserved": 0,
#                         "payload": {
#                             "transform": {
#                                 "xflip": 0,
#                                 "yflip": 0,
#                                 "rotate90": 0,
#                             },
#                             "dac_stream": {
#                             "x_coord": 0,
#                             "padding_x": 0,
#                             "y_coord": 0,
#                             "padding_y": 0,
#                             "dwell_time": 0,
#                             }
#                         }    
#                     }})


# value_dict = {"xflip": 1,
#                     "yflip": 0,
#                     "rotate90": 1,
#                     "x_coord": 16383,
#                     "y_coord": 16383,
#                     "dwell_time": 16380}


# 
# start = time.time()
# for _ in range(10000):
#     s = repack_code(value_dict)
# end = time.time()
# print(f"pack: {end-start:.4f}, {s}")


# print(FlushCommand().message)



# start = time.time()
# for _ in range(10000):
#     s = VectorPixelCommand(x_coord=16383, y_coord=16383, dwell=16380, xflip=True, rotate90=True).message
# end = time.time()
# print(f"message: {end-start:.4f}, {s}")

# start = time.time()
# for _ in range(10000):
#     q = struct.pack(">BHHH", CmdType.VectorPixel.value, 16383, 16383, 16379)
# end = time.time()
# print(f"struct: {end-start:.4f}, {q}")

# import cProfile, pstats, io
# from pstats import SortKey
# pr = cProfile.Profile()
# pr.enable()

# pr.disable()
# s = io.StringIO()
# sortby = SortKey.TIME
# ps = pstats.Stats(pr, stream=s).strip_dirs().sort_stats(sortby)
# ps.print_stats()
# print(s.getvalue())
# file = open("stats.txt", "w")
# file.write(s.getvalue())

# import dis
# print(dis.dis(repack_code))
# print("\n==============\n")
# print(dis.dis('struct.pack(">BHHH", 14, 16383, 16383, 16379)'))