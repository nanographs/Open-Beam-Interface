import asyncio
import logging
from rich import print

from glasgow.access.direct import DirectMultiplexer
import glasgow.access.direct.demultiplexer as glasgow_access
glasgow_access._xfers_per_queue = 16
glasgow_access._packets_per_xfer = 128

class OBIDemux(glasgow_access.DirectDemultiplexer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    async def claim_interface(self, applet, mux_interface, *args, **kwargs):
        iface = await super().claim_interface(applet, mux_interface, *args, **kwargs)
        self._interfaces.remove(iface)
        new_iface = OBIDemuxInterface(self.device, applet, mux_interface, **kwargs)
        self._interfaces.append(new_iface)
        return new_iface

class OBIDemuxInterface(glasgow_access.DirectDemultiplexerInterface):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    async def _in_task(self):
        if self._read_buffer_size is not None:
            await asyncio.sleep(0)
        await super()._in_task()
    async def reset(self):
        await super().reset()


def load_config():
    import argparse
    args = argparse.Namespace(port_spec="AB",
            pins_ext_ebeam_scan_enable=None, pins_ext_ibeam_scan_enable=None,
            pins_ext_ebeam_blank_enable=None, pins_ext_ibeam_blank_enable=None,
            pins_ebeam_blank=None, pins_ibeam_blank=None,
            xflip=None, yflip=None, rotate90=None,
            loopback=None, out_only=None, benchmark=None,
            endpoint=('tcp', 'localhost', 2224))
    import pathlib
    import tomllib
    from glasgow.access.direct.arguments import PinArgument
    # config_path = pathlib.Path("~/microscope.toml").expanduser()
    config = tomllib.load(open("microscope.toml", "rb") )
    if "beam" in config:
        beam_types = config["beam"]
        print(f"beam types: {[x for x in beam_types.keys()]}")
        beam_prefixes = {"electron": "ebeam", "ion": "ibeam"}
        for beam, beam_config in beam_types.items():
            if "pinout" in beam_config:
                pinout = beam_config["pinout"]
                for pin_name in pinout:
                    pin_num = pinout.get(pin_name)
                    pin_name = f"pins_{beam_prefixes.get(beam)}_{pin_name.replace("-","_")}"
                    print(f"{pin_name=}")
                    print(f"{pin_num=}")
                    pins = [PinArgument(num) if num > 0 else PinArgument(num, invert=True) for num in pin_num ]
                    setattr(args, pin_name, pins)
    if "transforms" in config:
        transforms = config["transforms"]
        for transform, setting in transforms.items():
            setattr(args, transform, setting)
    return args


async def main():
    args = load_config()
    from glasgow.access.direct.arguments import PinArgument    

    from glasgow.target.hardware import GlasgowHardwareTarget
    from glasgow.device.hardware import GlasgowHardwareDevice

    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger().addHandler(loggingHandler := logging.StreamHandler())
    loggingHandler.setFormatter(
        logging.Formatter(style="{", fmt="{levelname[0]:s}: {name:s}: {message:s}"))
    device = GlasgowHardwareDevice()

    from obi.applet.open_beam_interface import OBIApplet, obi_resources


    applet = OBIApplet()
    target = GlasgowHardwareTarget(revision=device.revision, 
                                    multiplexer_cls=DirectMultiplexer)

    applet.build(target, args)
    device.demultiplexer = OBIDemux(device, target.multiplexer.pipe_count)
    print("preparing build plan...")
    plan = target.build_plan()
    print("build plan done")
    await device.download_target(plan)
    print("bitstream loaded")
    voltage = 5.0
    ## TODO: only turn on voltage after gateware is loaded
    await device.set_voltage("AB", voltage)
    print(f"port AB voltage set to {voltage} V")
    #iface = await applet.run(device, args)
    iface = await device.demultiplexer.claim_interface(applet, applet.mux_interface, args,
            # read_buffer_size=131072*16, write_buffer_size=131072*16)
            read_buffer_size=16384*16384, write_buffer_size=16384*16384)
    await applet.interact(device, args, iface)

asyncio.run(main())
