import asyncio
import logging
import sys
logger = logging.getLogger()
logging.basicConfig(stream=sys.stdout, level=5)

import struct

from amaranth import *
from amaranth.lib import data, wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.simulation.assembly import SimulationAssembly
from glasgow.hardware.assembly import HardwareAssembly
from glasgow.hardware.device import GlasgowDevice
from glasgow.gateware.uart import *

from obi.applet.open_beam_interface import CommandParser, CommandExecutor, ImageSerializer, BeamType, obi_resources

class OBISubtarget(wiring.Component):
    i_stream:   In(stream.Signature(8))
    o_stream:   Out(stream.Signature(8))
    def __init__(self, ports):
        self.ports = ports
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

        ### Main OBI digital IO
        platform.add_resources(obi_resources) #LVDS connector
        
        self.led            = platform.request("led", dir="-")
        self.control        = platform.request("control", dir={pin.name:"-" for pin in obi_resources[0].ios})
        self.data           = platform.request("data", dir="-")

        ### IO buffers
        m.submodules.led_buffer = led = io.Buffer("o", self.led)

        m.submodules.x_latch_buffer  = x_latch  = io.Buffer("o", self.control.x_latch)
        m.submodules.y_latch_buffer  = y_latch  = io.Buffer("o", self.control.y_latch)
        m.submodules.a_latch_buffer  = a_latch  = io.Buffer("o", self.control.a_latch)
        m.submodules.a_enable_buffer = a_enable = io.Buffer("o", self.control.a_enable)
        m.submodules.d_clock_buffer  = d_clock  = io.Buffer("o", self.control.d_clock)
        m.submodules.a_clock_buffer  = a_clock  = io.Buffer("o", self.control.a_clock)

        m.submodules.data_buffer = data = io.Buffer("io", self.data)

        ### use LED to indicate backpressure
        m.d.comb += led.o.eq(~serializer.usb_stream.ready)

        ### connect buffers to data + control signals
        m.d.comb += [
            x_latch.o.eq(executor.bus.dac_x_le_clk),
            y_latch.o.eq(executor.bus.dac_y_le_clk),
            a_latch.o.eq(executor.bus.adc_le_clk),
            a_enable.o.eq(executor.bus.adc_oe),
            d_clock.o.eq(executor.bus.dac_clk),
            a_clock.o.eq(executor.bus.adc_clk),

            data.o.eq(executor.bus.data_o),
            data.oe.eq(executor.bus.data_oe),

            #data.oe.eq(~self.control.power_good.i),
            #control.oe.eq(~self.control.power_good.i)
        ]

        #### External IO control logic  
        def connect_pins(pin_name: str, signal):
            if hasattr(self.ports, pin_name):
                if self.ports[f"{pin_name}"] is not None:
                    if not hasattr(m.submodules, f"{pin_name}_buffer"):
                        m.submodules[f"{pin_name}_buffer"] = io.Buffer("o", self.ports[f"{pin_name}"])
                    # drive every pin in port with 1-bit signal
                    for pin in m.submodules[f"{pin_name}_buffer"].o:
                        m.d.comb += pin.eq(signal)
        
        connect_pins("ebeam_scan_enable", executor.ext_ctrl_enable)      
        connect_pins("ibeam_scan_enable", executor.ext_ctrl_enable)
        connect_pins("ebeam_blank_enable", executor.ext_ctrl_enable)
        connect_pins("ibeam_blank_enable", executor.ext_ctrl_enable)

        with m.If(executor.ext_ctrl_enabled):
            with m.If(executor.beam_type == BeamType.NoBeam):
                connect_pins("ebeam_blank", 1)
                connect_pins("ibeam_blank", 1)

            with m.Elif(executor.beam_type == BeamType.Electron):
                connect_pins("ebeam_blank", executor.blank_enable)
                connect_pins("ibeam_blank", 1)
                
            with m.Elif(executor.beam_type == BeamType.Ion):
                connect_pins("ibeam_blank", executor.blank_enable)
                connect_pins("ebeam_blank", 1)
        with m.Else():
            # Do not blank if external control is not enabled
            connect_pins("ebeam_blank",0) #TODO: check diff pair behavior here
            connect_pins("ibeam_blank",0)
        

        return m


class OBIInterface:
    logger = logging.getLogger(__name__)
    def __init__(self, assembly, args):
        ports = assembly.add_port_group(
            ebeam_scan_enable = "A1",
            ibeam_scan_enable = "A2",
            ebeam_blank_enable = "A3",
            ibeam_blank_enable = "A4",
            ebeam_blank = "A5",
            ibeam_blank = "A6",
        )

        component = assembly.add_submodule(OBISubtarget(ports))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)
        self._sys_clk_period = assembly.sys_clk_period  
        print(f"{self._pipe=}")

    async def read(self, data):
        self.logger.debug("READ")
        await self._pipe.flush()
        return await self._pipe.recv(data)

    async def write(self, data):
        self.logger.debug("WRITE")
        await self._pipe.send(data)

    async def flush(self):
        self.logger.debug("FLUSH")
        await self._pipe.flush()
    
    async def reset(self):
        self.logger.debug("RESET")
        await self._pipe.reset()
        self.logger.debug("RESET COMPLETE")

    async def test(self):
        iface = self

        output_mode = 2 #no output
        raster_mode = 0 #no raster
        mode = int(output_mode<<1 | raster_mode)
        sync_cmd = struct.pack('>BHB', 0, 123, mode)
        flush_cmd = struct.pack('>B', 2)
        await iface.write(sync_cmd)
        await iface.write(flush_cmd)
        await iface.flush()
        response = await iface.read(4)
        print(f"{response.tobytes()=}")
    
    async def interact(self, args, assembly):

        class InterceptedError(Exception):
            """
            An error that is only raised in response to GlasgowDeviceError or USBError.
            Should /always/ be triggered when the USB cable is unplugged.
            """
            pass

        iface = self

        class ForwardProtocol(asyncio.Protocol):
            logger = self.logger
            
            #TODO: will no longer be needed if Python requirement is bumped to 3.13
            def intercept_err(self, func):
                def if_err(err):
                    self.transport.write_eof()
                    self.transport.close()
                    raise InterceptedError(err)

                async def wrapper(*args, **kwargs):
                    try:
                        await func(*args, **kwargs)
                    except USBError as err:
                        if_err(err)
                    except GlasgowDeviceError as err:
                        if_err(err)
                return wrapper

            async def reset(self):
                print("server: RESET")
                await iface.reset()
                await iface.write(bytes(ExternalCtrlCommand(enable=False)))
                self.logger.debug("reset")
                self.logger.debug(iface.statistics())

            def connection_made(self, transport):
                self.backpressure = False
                self.send_paused = False

                transport.set_write_buffer_limits(131072*16)

                self.transport = transport
                peername = self.transport.get_extra_info("peername")
                self.logger.info("connect peer=[%s]:%d", *peername[0:2])

                async def initialize():
                    print("server: INITIALIZE")
                    await assembly.reset()
                    asyncio.create_task(self.send_data())
                self.init_fut = asyncio.create_task(initialize())

                self.flush_fut = None
            
            async def send_data(self):
                self.send_paused = False
                self.logger.debug("awaiting read")
                await asyncio.sleep(0)

                @self.intercept_err
                async def read_send_data():
                    data = await iface.read(flush=False)

                    if self.transport:
                        self.logger.debug(f"in-buffer size={len(iface._in_buffer)}")
                        self.logger.debug("dev->net <%s>", dump_hex(data))
                        self.transport.write(data)
                        await asyncio.sleep(0)
                        if self.backpressure:
                            self.logger.debug("paused send due to backpressure")
                            self.send_paused = True
                        else:
                            asyncio.create_task(self.send_data())
                    else:
                        self.logger.debug("dev->🗑️ <%s>", dump_hex(data))

                await read_send_data()

            
            def pause_writing(self):
                self.backpressure = True
                self.logger.debug("dev->NG")

            def resume_writing(self):
                self.backpressure = False
                self.logger.debug("dev->OK->net")
                if self.send_paused:
                    asyncio.create_task(self.send_data())

            
            def data_received(self, data):
                print("DATA RECEIVED")

                @self.intercept_err
                async def recv_data():
                    print("RECV_DATA")
                    await self.init_fut
                    print("initialized OK")
                    if not self.flush_fut == None:
                        print("pausing to flush")
                        self.transport.pause_reading()
                        try:
                            print("waiting to flush")
                            await self.flush_fut
                            print("flushed")
                        except USBErrorOther:
                            self.transport.write_eof()
                            print("Wrote EOF")
                        self.transport.resume_reading()
                        self.logger.debug("net->dev flush: done")
                    self.logger.debug("net->dev <%s>", dump_hex(data))
                    await iface.write(data)
                    self.logger.debug("net->dev write: done")

                    @self.intercept_err
                    async def flush():
                        await iface.flush(wait=True)
                            
                    self.flush_fut = asyncio.create_task(flush())


                asyncio.create_task(recv_data())

            def connection_lost(self, exc):
                peername = self.transport.get_extra_info("peername")
                self.logger.info("disconnect peer=[%s]:%d", *peername[0:2], exc_info=exc)
                self.transport = None

                asyncio.create_task(self.reset())
                
        proto, *proto_args = args.endpoint
        server = await asyncio.get_event_loop().create_server(ForwardProtocol, *proto_args, backlog=1)

        def handler(loop, context):
            if "exception" in context.keys():
                if isinstance(context["exception"], InterceptedError):
                    #TODO: in python 3.13, use server.close_clients()
                    self.logger.warning("Device Error detected.")
                    server.close()
                    self.logger.warning("Forcing Server To Close...")            


        loop = asyncio.get_running_loop()
        loop.set_exception_handler(handler)
        
        try:
            self.logger.info("Start OBI Server")
            await server.serve_forever()
        except asyncio.CancelledError:
            self.logger.warning("Server shut down due to device error.\n Check device connection.")
        finally:
            self.logger.info("OBI Server Closed.")


def run():
    from obi.config.applet import OBIAppletArguments
    args = OBIAppletArguments()
    args.parse_toml()
    args = args.args #smh

    device = GlasgowDevice()
    assembly = HardwareAssembly(device=device)
    iface = OBIInterface(assembly, args)
    async def launch():
        async with assembly:
            await iface.interact(args, assembly)
    asyncio.run(launch())

run()