import logging
import argparse
import asyncio
import pathlib
import tomllib
import sys

from . import OBIApplet
from glasgow.target.hardware import GlasgowHardwareTarget
from glasgow.device.hardware import GlasgowHardwareDevice
from glasgow.access.direct import DirectArguments, DirectMultiplexer, DirectDemultiplexer


parser = argparse.ArgumentParser()
parser.add_argument('-c', '--config_path', required=False, 
                    #expand paths starting with ~ to absolute
                    type=lambda p: pathlib.Path(p).expanduser(), 
                    help='path to microscope.toml')

logging.getLogger().setLevel(logging.INFO)
logging.getLogger().addHandler(loggingHandler := logging.StreamHandler())
loggingHandler.setFormatter(
    logging.Formatter(style="{", fmt="{levelname[0]:s}: {name:s}: {message:s}"))

access_args = DirectArguments(applet_name="open_beam_interface",
                            default_port="AB",
                            pin_count=16)
OBIApplet.add_build_arguments(parser, access_args)
#OBIApplet.add_interact_arguments(parser)


args = parser.parse_args()

if args.config_path != None:
    print(f"loading config from {args.config_path}")
    config = tomllib.load(open(args.config_path, "rb") )
    if "pinout" in config:
        pinout = config["pinout"]
        for pin_name in pinout:
            pin_num = pinout.get(pin_name)
            pin_name = f"pin_{pin_name.replace("-","_")}"
            #pin_args += ["--pin-"+pin_name, str(pin_num)]
            setattr(args, pin_name, pin_num)
    if "transforms" in config:
        transforms = config["transforms"]
        for transform, setting in transforms.items():
            setattr(args, transform, setting)

from .base_commands import *
from .base_commands.transfer2 import GlasgowStream, GlasgowConnection

async def main():
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


def run():
    asyncio.run(main())

if __name__ == "__main__":
    run()
