import argparse

from glasgow.access.direct.arguments import PinArgument
from rich import print


class OBIAppletArguments:
    def __init__(self, path="microscope.toml"):
        self.path = path
        self.toml = None
        self.args = argparse.Namespace(port_spec="AB",
                pin_set_ebeam_scan_enable=None, pin_set_ibeam_scan_enable=None,
                pin_set_ebeam_blank_enable=None, pin_set_ibeam_blank_enable=None,
                pin_set_ebeam_blank=None, pin_set_ibeam_blank=None,
                xflip=None, yflip=None, rotate90=None,
                loopback=None, out_only=None, benchmark=None, ext_switch_delay=None,
                endpoint=('tcp', 'localhost', 2224))
    def load_toml(self):
        import tomllib
        self.toml = tomllib.load(open(self.path, "rb") )
    def parse_toml(self):
        if self.toml is None:
            self.load_toml()
        config = self.toml
        if "beam" in config:
            beam_types = config["beam"]
            print(f"beam types: {[x for x in beam_types.keys()]}")
            beam_prefixes = {"electron": "ebeam", "ion": "ibeam"}
            for beam, beam_config in beam_types.items():
                if "pinout" in beam_config:
                    pinout = beam_config["pinout"]
                    for pin_name in pinout:
                        pin_num = pinout.get(pin_name)
                        pin_name = f"pin_set_{beam_prefixes.get(beam)}_{pin_name.replace("-","_")}"
                        pins = [PinArgument(num) if num > 0 else PinArgument(abs(num), invert=True) for num in pin_num ]
                        print(pins)
                        setattr(self.args, pin_name, pins)
        if "transforms" in config:
            transforms = config["transforms"]
            for transform, setting in transforms.items():
                print(f"{transform} -> {setting}")
                setattr(self.args, transform, setting)
        if "timings" in config:
            timings = config["timings"]
            print(f"ext_switch_delay = {timings.get("ext_switch_delay_ms")} ms")
            setattr(self.args, "ext_switch_delay", timings.get("ext_switch_delay_ms"))
