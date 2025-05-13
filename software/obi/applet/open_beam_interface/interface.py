import asyncio

from amaranth import *
from amaranth.lib import data, wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.simulation.assembly import SimulationAssembly
from glasgow.hardware.assembly import HardwareAssembly
from glasgow.hardware.device import GlasgowDevice
from glasgow.gateware.uart import *

from obi.applet.open_beam_interface import CommandParser, CommandExecutor, ImageSerializer

class OBISubtarget(wiring.Component):
    i_stream:   In(stream.Signature(8))
    o_stream:   Out(stream.Signature(8))
    def __init__(self):
        super().__init__()
    
    def elaborate(self, platform):
        m = Module()

        m.submodules.parser     = parser     = CommandParser()
        m.submodules.executor   = executor   = CommandExecutor()
        m.submodules.serializer = serializer = ImageSerializer()

        wiring.connect(m, parser.cmd_stream, executor.cmd_stream)
        wiring.connect(m, executor.img_stream, serializer.img_stream)

        # wiring.connect(m, self.i_stream, parser.usb_stream)
        m.d.comb += [
            parser.usb_stream.valid.eq(self.i_stream.valid),
            self.i_stream.ready.eq(parser.usb_stream.ready),
            parser.usb_stream.payload.eq(self.i_stream.payload),
        ]
        # wiring.connect(m, self.o_stream, serializer.usb_stream)
        m.d.comb += [
            self.o_stream.valid.eq(serializer.usb_stream.valid),
            serializer.usb_stream.ready.eq(self.o_stream.ready),
            self.o_stream.payload.eq(serializer.usb_stream.payload)
        ]

        return m


class OBIInterface:
    def __init__(self, assembly):
        component = assembly.add_submodule(OBISubtarget())
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)
        self._sys_clk_period = assembly.sys_clk_period

    async def read(self, data):
        await self._pipe.flush()
        return await self._pipe.recv(data)

    async def write(self, data):
        await self._pipe.send(data)

    async def flush(self):
        await self._pipe.flush()


def run():
    device = GlasgowDevice()
    assembly = HardwareAssembly(device=device)
    iface = OBIInterface(assembly)
    async def launch():
        async with assembly:
            await asyncio.sleep(.1)
    asyncio.run(launch())

run()