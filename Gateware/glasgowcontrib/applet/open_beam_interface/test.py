from ... import *
from . import OBIApplet


class OBIAppletTestCase(GlasgowAppletTestCase, applet=OBIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()