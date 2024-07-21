import asyncio
import socket

import inspect
import random
import struct

from time import perf_counter

import logging
logger = logging.getLogger()

from .stream import Stream, Connection, TransferError
from commands import Command, SynchronizeCommand, FlushCommand, OutputMode
from .support import dump_hex

BIG_ENDIAN = (struct.pack('@H', 0x1234) == struct.pack('>H', 0x1234))


class TCPStream(Stream):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        
    async def write(self, data: bytes | bytearray | memoryview):
        self._logger.debug(f"send: data=<{dump_hex(data)}>")
        self._writer.write(data)
        self._logger.debug(f"send: done")

    async def flush(self):
        self._logger.debug("flush")
        await self._writer.drain()
        self._logger.debug("flush: done")

    async def read(self, length: int) -> memoryview:
        self._logger.debug(f"recv: length={length}")
        buffer = bytearray()
        remain = length
        while remain > 0:
            data = await self._reader.read(remain)
            if len(data) == 0:
                raise asyncio.IncompleteReadError
            remain -= len(data)
            self._logger.debug(f"recv: data=<{dump_hex(data)}> remain={remain}")
            buffer.extend(data)
        stop = perf_counter()
        self._logger.debug(f"recv: done")
        return memoryview(buffer)
    
    async def readuntil(self, separator=b'\n', *, flush=True, max_count=False) -> memoryview:
        return await self._reader.readuntil(seperator, flush=flush, max_count=max_count)

    async def xchg(self, data: bytes | bytearray | memoryview, *, recv_length: int) -> bytes:
        await self.send(data)
        return await self.recv(recv_length)

class TCPConnection:
    _logger = logger.getChild("Connection")
    def __init__(self, host: str, port: int, *, read_buffer_size=0x10000*128):
        self.host = host
        self.port = port
        self.read_buffer_size = read_buffer_size

        self._stream = None
        self._synchronized = False
        self._next_cookie = random.randrange(0, 0x10000, 2) # even cookies only

        self._interrupt = asyncio.Event()

    @property
    def connected(self):
        """`True` if the TCP connection with the instrument is open, `False` otherwise."""
        return self._stream is not None

    @property
    def synchronized(self):
        """`True` if the instrument is ready to accept commands, `False` otherwise."""
        return self._synchronized

    async def _connect(self):
        assert not self.connected
        self._stream = TCPStream(*await asyncio.open_connection(
            self.host, self.port, limit=self.read_buffer_size))

        peername = self._stream._writer.get_extra_info('peername')
        self._logger.info(f"connected to server at {peername}")

    def _disconnect(self):
        assert self.connected
        self._stream = None
        self._synchronized = False

    def _interrupt_scan(self):
        print(f'Scan interrupted externally')
        self._interrupt.set()


    async def _synchronize(self):
        if not self.connected:
            await self._connect()
        if self.synchronized:
            self._logger.debug("already synced")
            return

        cookie, self._next_cookie = self._next_cookie, (self._next_cookie + 2) & 0xffff # even cookie
        self._logger.debug(f'synchronizing with cookie {cookie:#06x}')

        #seq = CommandSequence(cookie=cookie, output=OutputMode.SixteenBit, raster=False)
        #seq.add(FlushCommand())
        await SynchronizeCommand(cookie=cookie, output=OutputMode.SixteenBit, raster=False).transfer(self._stream)
        await FlushCommand().transfer(self._stream)
        #res = SynchronizeCommand(cookie=cookie, output=OutputMode.SixteenBit, raster=False).byte_response
        res = struct.pack('>HH', 65535, cookie)
        #await self._stream.write(bytes(seq))
        while True:
            self._logger.debug("trying to synchronize...")
            try:
                flushed = await self._stream._reader.readuntil(res)
                self._logger.debug(f"synchronized after {len(flushed)} bytes")
                self._synchronized = True
                break
            except asyncio.LimitOverrunError:
                self._logger.debug("LimitOverrunError")
                # If we're here, it means the read buffer has exactly `self.read_buffer_size` bytes
                # in it (set by the `open_connection(limit=)` argument). A partial response could
                # still be at the very end of the buffer, so read less than that.
                await self._stream._reader.readexactly(self.read_buffer_size - len(res))
            except Exception as e:
                print(f"sync error: {e}")


    def _handle_incomplete_read(self, exc):
        self._disconnect()
        raise TransferError("connection closed") from exc

    def get_cookie(self):
        cookie, self._next_cookie = self._next_cookie + 1, self._next_cookie + 2 # odd cookie
        self._logger.debug(f"allocating cookie {cookie:#06x}")
        return cookie

    async def transfer(self, command: Command, flush:bool = False, **kwargs):
        self._logger.debug(f"transfer {command!r}")
        try:
            start = perf_counter()
            await self._synchronize() # may raise asyncio.IncompleteReadError
            stop = perf_counter()
            self._logger.debug(f"transfer: time - {stop-start:.4f}")
            return await command.transfer(self._stream, **kwargs)
        except asyncio.IncompleteReadError as e:
            self._handle_incomplete_read(e)

    async def transfer_multiple(self, command: Command, **kwargs):
        self._logger.debug(f"transfer multiple {command!r}")
        try:
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