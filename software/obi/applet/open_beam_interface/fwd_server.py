import asyncio

from glasgow.support.logging import dump_hex

from glasgow.hardware.device import GlasgowDeviceError
from usb1 import USBError


class InterceptedError(Exception):
    """
    An error that is only raised in response to GlasgowDeviceError or USBError.
    Should /always/ be triggered when the USB cable is unplugged.
    """
    pass

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
        await self.__pipe.reset()
        await self.__pipe.send(bytes(ExternalCtrlCommand(enable=False)))
        self.logger.debug("reset")
        # self.logger.debug(iface.statistics())

    def connection_made(self, transport):
        self.backpressure = False
        self.send_paused = False

        transport.set_write_buffer_limits(131072*16)

        self.transport = transport
        peername = self.transport.get_extra_info("peername")
        self.logger.info("connect peer=[%s]:%d", *peername[0:2])

        async def initialize():
            await self.reset()
            asyncio.create_task(self.send_data())
        self.init_fut = asyncio.create_task(initialize())

        self.flush_fut = None

    async def send_data(self):
        self.send_paused = False
        self.logger.debug("awaiting read")

        @self.intercept_err
        async def read_send_data():
            data = await self__pipe.recv(flush=False)

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
        @self.intercept_err
        async def recv_data():
            await self.init_fut
            if not self.flush_fut == None:
                self.transport.pause_reading()
                try:
                    await self.flush_fut
                except USBErrorOther:
                    self.transport.write_eof()
                    print("Wrote EOF")
                self.transport.resume_reading()
                self.logger.debug("net->dev flush: done")
            self.logger.debug("net->dev <%s>", dump_hex(data))
            await self.__pipe.send(data)
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
    


def handler(loop, context):
    if "exception" in context.keys():
        if isinstance(context["exception"], InterceptedError):
            #TODO: in python 3.13, use server.close_clients()
            self.logger.warning("Device Error detected.")
            server.close()
            self.logger.warning("Forcing Server To Close...")            


def run(args):
    proto, *proto_args = args.endpoint
    server = await asyncio.get_event_loop().create_server(ForwardProtocol, *proto_args, backlog=1)

    loop = asyncio.get_running_loop()
    loop.set_exception_handler(handler)

    try:
        self.logger.info("Start OBI Server")
        await server.serve_forever()
    except asyncio.CancelledError:
        self.logger.warning("Server shut down due to device error.\n Check device connection.")
    finally:
        self.logger.info("OBI Server Closed.")