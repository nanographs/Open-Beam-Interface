import unittest
from amaranth.sim import Simulator


class OBIAppletTestCase(GlasgowAppletTestCase, applet=OBIApplet):
    pass