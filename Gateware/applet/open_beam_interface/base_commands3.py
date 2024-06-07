from amaranth import ShapeCastable, Shape
from amaranth.lib import data
import struct
import enum
from dataclasses import dataclass


def parse_input(command):
    flatlist = []
    def flatpack(a_key, a_dict):
        for key, value in a_dict.items():
            key = f"{a_key}.{key}"
            if isinstance(value, dict):
                flatpack(key, value)
            else:
                flatlist.append(f"{key}.{value}")
    if hasattr(command, "bitlayout"):    
        flatpack("bits", command.bitlayout)
    if hasattr(command, "bytelayout"):    
        flatpack("bytes", command.bytelayout)
    print(flatlist)

class SynchronizeCommand:
    bitlayout = {"mode": {
            "raster": 1,
            "output": 2
        }}
    bytelayout = {"cookie": 1}

parse_input(SynchronizeCommand)

