from amaranth import *

from amaranth.lib import data, wiring
from amaranth.lib.wiring import In, Out, flipped

from dataclasses import dataclass

from obi.commands.structs import OutputEnable

class BlankRequest(data.Struct):
    enable: 1
    request: 1

BusSignature = wiring.Signature({
    "adc_clk":  Out(1),
    "adc_le_clk":   Out(1),
    "adc_oe":   Out(1),

    "dac_clk":  Out(1),
    "dac_x_le_clk": Out(1),
    "dac_y_le_clk": Out(1),

    "data_i":   In(15),
    "data_o":   Out(15),
    "data_oe":  Out(1),
})

DwellTime = unsigned(16)

class DACStream(data.Struct):
    dac_x_code: 14
    padding_x: 2
    dac_y_code: 14
    padding_x: 2
    dwell_time: 16
    blank: BlankRequest
    output_en: OutputEnable
    delay: 3


class SuperDACStream(data.Struct):
    dac_x_code: 14
    padding_x: 2
    dac_y_code: 14
    padding_y: 2
    blank: BlankRequest
    output_en: OutputEnable
    last: 1
    delay: 3

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

@dataclass
class Transforms:
    xflip: bool
    yflip: bool
    rotate90: bool

    @staticmethod
    def add_transform_arguments(parser):
        parser.add_argument("--xflip",
        dest = "xflip", action = 'store_true',
        help = "flip x axis")
        parser.add_argument("--yflip",
        dest = "yflip", action = 'store_true',
        help = "flip y axis")
        parser.add_argument("--rotate90",
        dest = "rotate90", action = 'store_true',
        help = "switch x and y axes")
    @classmethod
    def parse_transform_arguments(args):
        return cls(xflip=args.xflip, yflip=args.yflip, rotate90=args.rotate90)
