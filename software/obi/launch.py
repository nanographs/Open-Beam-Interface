import asyncio
import logging

from glasgow.hardware.assembly import HardwareAssembly

from obi.config.applet import get_applet_args
from obi.applet.open_beam_interface import OBIInterface
from obi.support import stream_logs

logger = logging.getLogger()

def _setup():
    args = get_applet_args("microscope.toml")

    assembly = HardwareAssembly()
    assembly.use_voltage({"A": 3.3, "B": 3.3})

    iface = OBIInterface(logger, assembly, args)

    return iface, assembly

@stream_logs
async def main():
    iface, assembly = _setup()
    async with assembly:
        await iface.server()

if __name__ == "__main__":
    asyncio.run(main())
