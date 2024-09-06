from abc import abstractmethod, ABCMeta
import asyncio
import random
import struct

import logging
logger = logging.getLogger()
from . import *

from obi.commands import *

class TransferError(Exception):
    pass

class Stream(metaclass = ABCMeta):
    _logger = logger.getChild("Stream")
    @abstractmethod
    async def write(self, data: bytes | bytearray | memoryview):
        ...
    @abstractmethod
    async def flush(self):
        ## if write buffer is full, wait until it is ready to receive more
        ...
    @abstractmethod
    async def read(self, length: int) -> memoryview:
        ...
    @abstractmethod
    async def readuntil(self, separator=b'\n', *, flush=True, max_count=False) -> memoryview:
        ...
    # @abstractmethod
    # async def xchg(self, data: bytes | bytearray | memoryview, *, recv_length: int) -> bytes:
    #     ...

class Connection(metaclass = ABCMeta):
    _logger = logger.getChild("Connection")

    def __init__(self):
        self._stream = None
        self._synchronized = False
        self._next_cookie = random.randrange(0, 0x10000, 2) # even cookies only
    
    @property
    def connected(self):
        """`True` if the connection with the instrument is open, `False` otherwise."""
        return self._stream is not None

    @property
    def synchronized(self):
        """`True` if the instrument is ready to accept commands, `False` otherwise."""
        return self._synchronized
    
    @abstractmethod
    async def _connect(self):
        ...
    
    def _disconnect(self):
        assert self.connected
        self._stream = None
        self._synchronized = False
    
    # @abstractmethod
    # async def _synchronize(self):
    #     ...

    async def _synchronize(self):
        if not self.connected:
            await self._connect()
        if self.synchronized:
            self._logger.debug("already synced")
            return

        cookie, self._next_cookie = self._next_cookie, (self._next_cookie + 2) & 0xffff # even cookie
        self._logger.debug(f'synchronizing with cookie {cookie:#06x}')

        cmd = bytearray()
        cmd.extend(bytes(SynchronizeCommand(raster=True, output=OutputMode.SixteenBit, cookie=cookie)))
        cmd.extend(bytes(FlushCommand()))
        await self._stream.write(cmd)
        await self._stream.flush()
        res = struct.pack(">HH", 0xffff, cookie)
        data = await self._stream.readuntil(res)
    
    def _handle_incomplete_read(self, exc):
        self._disconnect()
        raise TransferError("connection closed") from exc

    def get_cookie(self):
        cookie, self._next_cookie = self._next_cookie + 1, self._next_cookie + 2 # odd cookie
        self._logger.debug(f"allocating cookie {cookie:#06x}")
        return cookie
    
    async def transfer(self, command, **kwargs):
        self._logger.debug(f"transfer {command!r}")
        try:
            if not self.synchronized:
                await self._synchronize() # may raise asyncio.IncompleteReadError
            return await command.transfer(self._stream, **kwargs)
        except asyncio.IncompleteReadError as e:
            self._handle_incomplete_read(e)
    
    async def transfer_multiple(self, command, **kwargs):
        self._logger.debug(f"transfer multiple {command!r}")
        try:
            if not self.synchronized:
                await self._synchronize() # may raise asyncio.IncompleteReadError
            self._logger.debug(f"synchronize transfer_multiple")
            async for value in command.transfer(self._stream, **kwargs):
                yield value
                self._logger.debug(f"yield transfer_multiple")
        except asyncio.IncompleteReadError as e:
            self._handle_incomplete_read(e)
    
    async def transfer_raw(self, command, flush:bool = False, **kwargs):
        self._logger.debug(f"transfer {command!r}")
        await self._synchronize() # may raise asyncio.IncompleteReadError
        await self._stream.write(bytes(command))
        await self._stream.flush()
    
    async def transfer_bytes(self, data:bytes, flush:bool = False, **kwargs):
        await self._synchronize() # may raise asyncio.IncompleteReadError
        await self._stream.write(data)
        await self._stream.flush()

