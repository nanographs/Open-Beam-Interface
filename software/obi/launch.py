import asyncio
import logging

from glasgow.hardware.assembly import HardwareAssembly

from obi.config.applet import get_applet_args
from obi.applet.open_beam_interface import OBIInterface
from obi.support import stream_logs

logger = logging.getLogger()

async def _setup():
    args = get_applet_args("microscope.toml")

    assembly = await HardwareAssembly.find_device()
    #TODO: maybe make voltage configurable
    assembly.use_voltage({"A": 5.0, "B": 5.0})

    iface = OBIInterface(logger, assembly, args)

    return iface, assembly

@stream_logs
async def main():
    iface, assembly = await _setup()
    async with assembly:
        await iface.server()

if __name__ == "__main__":
    asyncio.run(main())
