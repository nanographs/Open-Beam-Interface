import struct
import logging
logger = logging.getLogger()

from .abc import Stream, Connection
from obi.launch import _setup
from obi.commands import *
from .support import dump_hex

class GlasgowStream(Stream):
    def __init__(self, iface):
        self.iface = iface
    async def write(self, data):
        self._logger.debug(f"send: data=<{dump_hex(data)}>")
        await self.iface.write(data)
        self._logger.debug(f"send: done")
    async def flush(self):
        self._logger.debug(f"flush")
        await self.iface.flush()
        self._logger.debug(f"flush: done")
    async def read(self, length):
        return await self.iface.read(length)
    async def readexactly(self, length):
        return await self.iface.read(length)
    async def readuntil(self, *args, **kwargs):
        return await self.iface.readuntil(*args, **kwargs)

class GlasgowConnection(Connection):
    _logger = logger.getChild("Connection")
    def connect(self, stream):
        self._stream = stream

    async def _connect(self):
        assert not self.connected
        iface, assembly = _setup()
        await assembly.start(reload_bitstream=True) #FIXME: reload bitstream will eventually not be necessary
        self._stream = GlasgowStream(iface)

    # async def transfer(self, command, flush:bool = False, **kwargs):
    #     return await super().transfer(command, flush=flush, **kwargs)