from amaranth import ShapeCastable, Shape
from amaranth.lib import data
import struct
import enum
from dataclasses import dataclass


def get_field_dict(shape):
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



def pack_fn(command):
    field_values = [str(int(command.cmdtype))]
    print(f"{int(field_values[0],2)=}")
    field_offset = 4
    field_dict = get_field_dict(command.field_layout)
    for field_name, field_width in field_dict.items():
        field_values.append(f'((value_dict[{field_name!r}] & {(1 << field_width) - 1}) << {field_offset})')
        field_offset += field_width
    func = f'lambda value_dict: int({" | ".join(field_values)})'
    return field_dict, eval(func)

class CommandLayout:
    def __init_subclass__(cls):
        cls.structshape = "B"
        cls.structcontents = []
        cls.bitcontents = []
        if hasattr(cls, "cmdbytes"):
            cls.structshape += "".join(x for x in cls.cmdbytes.values())
            cls.structcontents += [x for x in cls.cmdbytes.keys()]
        if hasattr(cls, "cmdbits"):
            cls.field_layout = data.StructLayout({cls.fieldstr: cls.cmdbits})
            field_dict, field_pack_fn = pack_fn(cls)
            cls.pack_fn = staticmethod(field_pack_fn)
            cls.bitcontents += [x for x in field_dict.keys()]
    def __init__(self, **kwargs):
        self.structargs = [kwargs[x] for x in self.structcontents]
        self.bitargs = {x:kwargs[x] for x in self.bitcontents}
    def pack(self):
        typeheader = self.pack_fn(self.bitargs)
        return struct.pack(self.structshape, typeheader, *self.structargs)
    

class SynchronizeCommand(CommandLayout):
    cmdtype = 0x0
    fieldstr= "synchronize"
    cmdbits = data.StructLayout({
        "mode": data.StructLayout({
            "output": 2,
            "raster": 1
        })
    })
    cmdbytes = {"cookie": "H"}


class AbortCommand(CommandLayout):
    cmdtype = 0x1

@dataclass
class DACCodeRange:
    start: int # UQ(14,0)
    count: int # UQ(14,0)
    step:  int # UQ(8,8)


class RasterRegionCommand(CommandLayout):
    cmdtype = 0xa
    fieldstr = "raster_region"
    cmdbytes = {"x_start": "H",
                "x_count": "H",
                "x_step": "H",
                "y_start": "H",
                "y_count": "H",
                "y_step": "H"}


print(SynchronizeCommand(raster = 1, output = 1, cookie=123).pack())

allcommands = [SynchronizeCommand, RasterRegionCommand]

class Command(data.Struct):
    type: 4
    payload: data.UnionLayout({x.fieldstr: x.cmd})

