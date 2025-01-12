import asyncio
import logging


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

class OBILauncher:
    @staticmethod
    async def launch_server():
        await OBILauncher.main(interact=True)
    @staticmethod
    async def launch_direct():
        return await OBILauncher.main(interact=False)
    @staticmethod
    async def main(interact=False):
        from obi.config.applet import OBIAppletArguments
        args = OBIAppletArguments()
        args.parse_toml()
        args = args.args #smh

        from glasgow.target.hardware import GlasgowHardwareTarget
        from glasgow.device.hardware import GlasgowHardwareDevice

        # logging.getLogger().setLevel(logging.DEBUG)
        # logging.getLogger().addHandler(loggingHandler := logging.StreamHandler())
        # loggingHandler.setFormatter(
        #     logging.Formatter(style="{", fmt="{levelname[0]:s}: {name:s}: {message:s}"))
        device = GlasgowHardwareDevice()

        from obi.applet.open_beam_interface import OBIApplet, obi_resources


        applet = OBIApplet()
        target = GlasgowHardwareTarget(revision=device.revision, 
                                        multiplexer_cls=DirectMultiplexer)

        applet.build(target, args)
        device.demultiplexer = OBIDemux(device, target.multiplexer.pipe_count)
        logging.info("main: preparing build plan...")
        plan = target.build_plan()
        logging.info("main: build plan done")
        await device.download_target(plan)
        logging.info("main: bitstream loaded")
        voltage = 5.0
        ## TODO: only turn on voltage after gateware is loaded
        await device.set_voltage("AB", voltage)
        logging.info(f"main: port AB voltage set to {voltage} V")
        #iface = await applet.run(device, args)
        iface = await device.demultiplexer.claim_interface(applet, applet.mux_interface, args,
                # read_buffer_size=131072*16, write_buffer_size=131072*16)
                read_buffer_size=16384*16384, write_buffer_size=16384*16384)
        if interact:
            await applet.interact(device, args, iface)

        else:
            await iface.reset()
            return iface

from obi.support import stream_logs

@stream_logs
async def run_server():
    l = OBILauncher()
    await l.launch_server()

if __name__ == "__main__":
    asyncio.run(run_server())