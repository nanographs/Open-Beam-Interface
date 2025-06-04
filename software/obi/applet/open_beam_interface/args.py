from dataclasses import dataclass

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

class BeamStateIO:
    def __init__(self, beam_id: str):
        self.id = beam_id
    def add_pin_arguments(self, parser, access):
        access.add_pins_argument(parser, f"{self.id}_scan_enable", range(1,3))
        access.add_pins_argument(parser, f"{self.id}_blank_enable", range(1,3))
        access.add_pins_argument(parser, f"{self.id}_blank", range(1,3))