import argparse
import functools
from glasgow.access.direct.arguments import DirectArguments
# from glasgowcontrib.applet.open_beam_interface import OBIApplet

class OBIArguments(DirectArguments):
    def __init__(self):
        super().__init__("OBI", "AB", 8)
    def add_pin_copy_argument(self, parser, name, width):
        self.add_pin_set_argument(parser, name, width)


parser = argparse.ArgumentParser()
obi_args = OBIArguments()
obi_args.add_pin_set_argument(parser, "test", 2)
args = parser.parse_args()
print(f"{args=}")