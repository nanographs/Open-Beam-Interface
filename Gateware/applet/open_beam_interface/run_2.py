import logging
import argparse
import asyncio

from . import OBIApplet
from glasgow.target.hardware import GlasgowHardwareTarget
from glasgow.device.hardware import GlasgowHardwareDevice
from glasgow.access.direct import DirectArguments, DirectMultiplexer, DirectDemultiplexer


# logging.getLogger().setLevel(logging.TRACE)
logging.getLogger().addHandler(loggingHandler := logging.StreamHandler())
loggingHandler.setFormatter(
    logging.Formatter(style="{", fmt="{levelname[0]:s}: {name:s}: {message:s}"))

access_args = DirectArguments(applet_name="open_beam_interface",
                            default_port="AB",
                            pin_count=16)
parser = argparse.ArgumentParser()
OBIApplet.add_build_arguments(parser, access_args)
# OBIApplet.add_interact_arguments(parser, access_args)
args = parser.parse_args()


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

def run():
    asyncio.run(main())

if __name__ == "__main__":
    run()
