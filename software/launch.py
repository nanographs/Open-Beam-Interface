import asyncio
import logging

import argparse
args = argparse.Namespace(port_spec="AB",
        pin_ext_ebeam_scan_enable=None, pin_ext_ebeam_scan_enable_2=None,
        pin_ext_ibeam_scan_enable=None, pin_ext_ibeam_scan_enable_2=None,
        pin_ext_ibeam_blank_enable=None, pin_ext_ibeam_blank_enable_2=None,
        pin_ibeam_blank_low=None, pin_ibeam_blank_high=None,
        pin_ebeam_blank=None, pin_ebeam_blank_2=None, 
        xflip=None, yflip=None, rotate90=None,
        loopback=None, out_only=None, benchmark=None,
        endpoint=('tcp', 'localhost', 2224))

async def main():
    from glasgow.target.hardware import GlasgowHardwareTarget
    from glasgow.device.hardware import GlasgowHardwareDevice

    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger().addHandler(loggingHandler := logging.StreamHandler())
    loggingHandler.setFormatter(
        logging.Formatter(style="{", fmt="{levelname[0]:s}: {name:s}: {message:s}"))
    device = GlasgowHardwareDevice()

    from applet.open_beam_interface import OBIApplet, obi_resources
    from glasgow.access.direct import DirectMultiplexer, DirectDemultiplexer

    applet = OBIApplet()
    target = GlasgowHardwareTarget(revision=device.revision, 
                                    multiplexer_cls=DirectMultiplexer)
    applet.build(target, args)
    device.demultiplexer = DirectDemultiplexer(device, target.multiplexer.pipe_count)
    print("preparing build plan...")
    plan = target.build_plan()
    print("build plan done")
    await device.download_target(plan)
    print("bitstream loaded")
    voltage = 5.0
    ## TODO: only turn on voltage after gateware is loaded
    await device.set_voltage("AB", voltage)
    print(f"port AB voltage set to {voltage} V")
    iface = await applet.run(device, args)
    await applet.interact(device, args, iface)

asyncio.run(main())
