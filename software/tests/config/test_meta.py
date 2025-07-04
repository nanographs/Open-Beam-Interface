import unittest

from obi.config.meta import ScopeSettings, BeamSettings, MagCal, Pinout
from obi.config.applet import get_applet_args

import os


class ParseMetaTest(unittest.TestCase):
    def test_pinouts(self):
        s = ScopeSettings.from_toml_file("tests/config/test_full.toml")
        self.assertIn("electron", s.beam_settings)
        self.assertIn("ion", s.beam_settings)
        pinout_e = s.beam_settings["electron"].pinout
        pinout_i = s.beam_settings["ion"].pinout
        self.assertEqual(pinout_e.scan_enable, "A0:1")
        self.assertEqual(pinout_i.blank_enable, "B2#")
        self.assertEqual(pinout_i.blank, "B3:4")

    def test_load(self):
        get_applet_args("tests/config/test_full.toml")
        get_applet_args("tests/config/test_minimal.toml") 

        for file in os.listdir("configs"):
            get_applet_args(f"configs/{file}")

