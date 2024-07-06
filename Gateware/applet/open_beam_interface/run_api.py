import logging
import argparse
import asyncio
import pathlib
import tomllib
import sys

from . import OBIApplet, obi_resources
from glasgow.target.hardware import GlasgowHardwareTarget
from glasgow.device.hardware import GlasgowHardwareDevice
from glasgow.access.direct import DirectArguments, DirectMultiplexer, DirectDemultiplexer



logging.getLogger().setLevel(logging.INFO)
logging.getLogger().addHandler(loggingHandler := logging.StreamHandler())
loggingHandler.setFormatter(
    logging.Formatter(style="{", fmt="{levelname[0]:s}: {name:s}: {message:s}"))




from .base_commands import *
#from .base_commands.transfer2 import GlasgowStream, GlasgowConnection


class OBIDevice:
    def __init__(self):
        self.args = argparse.Namespace(port_spec="AB",
        pin_ext_ebeam_scan_enable=None, pin_ext_ebeam_scan_enable_2=None,
        pin_ext_ibeam_scan_enable=None, pin_ext_ibeam_scan_enable_2=None,
        pin_ext_ibeam_blank_enable=None, pin_ext_ibeam_blank_enable_2=None,
        pin_ibeam_blank_low=None, pin_ibeam_blank_high=None,
        pin_ebeam_blank=None, pin_ebeam_blank_2=None, 
        xflip=None, yflip=None, rotate90=None,
        loopback=None, out_only=None, benchmark=None)
    def load_config(self, config_path):
        import pathlib
        import tomllib
        config_path = pathlib.Path(config_path).expanduser()
        print(f"loading config from {config_path}")
        config = tomllib.load(open(config_path, "rb") )
        if "pinout" in config:
            pinout = config["pinout"]
            for pin_name in pinout:
                pin_num = pinout.get(pin_name)
                pin_name = f"pin_{pin_name.replace("-","_")}"
                setattr(self.args, pin_name, pin_num)
        if "transforms" in config:
            transforms = config["transforms"]
            for transform, setting in transforms.items():
                setattr(self.args, transform, setting)

    async def get_interface(self):
        device = GlasgowHardwareDevice()
        await device.set_voltage("AB", 5.0)
        print("port AB voltage set to 5.0 V")
        target = GlasgowHardwareTarget(revision=device.revision, 
                                    multiplexer_cls=DirectMultiplexer)
        applet = OBIApplet()
        applet.build(target, args)
        device.demultiplexer = DirectDemultiplexer(device, target.multiplexer.pipe_count)
        print("preparing build plan...")
        plan = target.build_plan()
        await device.download_target(plan)
        print("build plan downloaded")
        iface = await applet.run(device, args)
        conn = GlasgowConnection()
        stream = GlasgowStream(iface)
        conn.connect(stream)
        await conn._synchronize()
        return conn

class BeamInterface:
    def __init__(self, conn):
        pass


async def main():
    obi = OBIDevice()
    obi.load_config("~/open-beam-interface/configs/jsm_6400.toml")
    beam_interface = obi.get_interface(obi.args)

def run():
    asyncio.run(main())

if __name__ == "__main__":
    run()
