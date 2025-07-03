import argparse

from glasgow.applet import GlasgowPin
from glasgow.abstract import GlasgowVio, GlasgowPort
from glasgow.support.endpoint import endpoint

try:
    from rich import print
    from rich.table import Table
    from rich.console import Console
    has_rich = True
except:
    has_rich = False

# TODO: generate this from ScopeSettings
class OBIAppletArguments:
    def __init__(self, path="microscope.toml"):
        self.path = path
        self.toml = None
        self.args = argparse.Namespace(port_spec="AB",
                voltage = {
                    GlasgowPort.A: GlasgowVio(3.3),
                    GlasgowPort.B: GlasgowVio(3.3)
                },
                electron_scan_enable=None, ion_scan_enable=None,
                electron_blank_enable=None, ion_blank_enable=None,
                electron_blank=None, ion_blank=None,
                xflip=None, yflip=None, rotate90=None, line_clock=None, frame_clock=None,
                loopback=None, out_only=None, benchmark=None, ext_switch_delay=None,
                endpoint=('tcp', 'localhost', 2224))
    def load_toml(self):
        from tomlkit.toml_file import TOMLFile
        self.toml_file = TOMLFile(self.path)
        self.toml = self.toml_file.read()
    def parse_toml(self):
        if has_rich:
            table = Table(title="pinout")
            table.add_column("name")
            table.add_column("number")
            table.add_column("invert")
        if self.toml is None:
            self.load_toml()
        config = self.toml
        if "server" in config:
            ep = config["server"]
            ep_str = "tcp:"
            if "host" in ep:
                ep_str += str(ep["host"]) 
            ep_str += ":"
            if "port" in ep:
                ep_str += str(ep["port"])
            ep = endpoint(ep_str) #using input spec from Glasgow
            setattr(self.args, "endpoint", ep)
        if "beam" in config:
            beam_types = config["beam"]
            print(f"beam types: {[x for x in beam_types.keys()]}")
            for beam, beam_config in beam_types.items():
                if "pinout" in beam_config:
                    pinout = beam_config["pinout"]
                    for pin_name in pinout:
                        pin_str = pinout.get(pin_name)
                        pin_name = f"{beam}_{pin_name.replace('-','_')}"
                        pins = GlasgowPin.parse(pin_str)
                        setattr(self.args, pin_name, pins)

        if "transforms" in config:
            transforms = config["transforms"]
            for transform, setting in transforms.items():
                print(f"{transform} -> {setting}")
                setattr(self.args, transform, setting)
        if "timings" in config:
            timings = config["timings"]
            print(f"ext_switch_delay = {timings.get('ext_switch_delay_ms')} ms")
            setattr(self.args, "ext_switch_delay", timings.get("ext_switch_delay_ms"))
