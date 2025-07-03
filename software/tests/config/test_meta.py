import unittest

from obi.config.meta import ScopeSettings, BeamSettings, MagCal, Pinout


class ParseMetaTest(unittest.TestCase):
    def test(self):
        s = ScopeSettings.from_toml_file("tests/config/test.toml")
        self.assertIn("electron", s.beam_settings)
        self.assertIn("ion", s.beam_settings)
        pinout_e = s.beam_settings["electron"].pinout
        pinout_i = s.beam_settings["ion"].pinout
        self.assertEqual(pinout_e.scan_enable, "A0:1")
        self.assertEqual(pinout_i.blank_enable, "A4:5")
        self.assertEqual(pinout_i.blank, "#A2,A3")