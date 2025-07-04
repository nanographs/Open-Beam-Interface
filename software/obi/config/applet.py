import argparse

from glasgow.applet import GlasgowPin
from glasgow.abstract import GlasgowVio, GlasgowPort
from glasgow.support.endpoint import endpoint

from obi.config.meta import ScopeSettings

def get_applet_args(path="microscope.toml"):
    args = argparse.Namespace(port_spec="AB",
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

    scope = ScopeSettings.from_toml_file(path)
    for beam_id, beam_settings in scope.beam_settings.items():
        def set_pin_arg(pin_id: str):
            pin_str = getattr(beam_settings.pinout, pin_id)
            if not isinstance(pin_str, str):
                #FIXME: remove this after... a while
                raise ValueError(f"""
The provided pin format is not valid. 
Your previously valid configuration file might be incompatible with the latest changes to OBI: https://github.com/nanographs/Open-Beam-Interface/pull/58
Sorry about that! The documentation and example config files have been updated to the new format.
Here's a quick guide on how to convert to the new format:
\t Old \t New
\t [0] \t "A0"
\t [0,1] \t "A0,A1" or "A0:1"
\t [0,-1] \t "A0,#A1"
\t [8,9] \t "B0, B1"
                """)
                return
            if pin_str is not None:
                pin_name = f"{beam_id}_{pin_id}"
                pins = GlasgowPin.parse(pin_str)
                setattr(args, pin_name, pins)
        set_pin_arg("scan_enable")
        set_pin_arg("blank_enable")
        set_pin_arg("blank")
    
    def set_transform_arg(transform_id: str):
        setattr(args, transform_id, getattr(scope.transforms, transform_id))
    
    if scope.transforms is not None:
        set_transform_arg("xflip")
        set_transform_arg("yflip")
        set_transform_arg("rotate90")

    if scope.endpoint is not None:
        setattr(args, "endpoint", ('tcp', scope.endpoint.host, scope.endpoint.port))
    
    if scope.ext_switch_delay is not None:
        setattr(args, "ext_switch_delay_ms", scope.ext_switch_delay)

    return args
