import asyncio
import socket

import inspect
import random
import struct

from time import perf_counter

import logging
logger = logging.getLogger()

from .abc import Stream, Connection, TransferError
from obi.commands import Command, SynchronizeCommand, FlushCommand, OutputMode
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
                raise asyncio.IncompleteReadError(data, remain)
            remain -= len(data)
            self._logger.debug(f"recv: data=<{dump_hex(data)}> remain={remain}")
            buffer.extend(data)
        stop = perf_counter()
        self._logger.debug(f"recv: done")
        return memoryview(buffer)
    
    #TODO: figure out if flush and max_count can be added back here
    async def readuntil(self, separator=b'\n') -> memoryview:
        return await self._reader.readuntil(separator)

    async def xchg(self, data: bytes | bytearray | memoryview, *, recv_length: int) -> bytes:
        await self.send(data)
        return await self.recv(recv_length)

class TCPConnection(Connection):
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

    def _interrupt_scan(self):
        print(f'Scan interrupted externally')
        self._interrupt.set()

    def _handle_incomplete_read(self, exc):
        self._disconnect()
        raise TransferError("connection closed") from exc

    def get_cookie(self):
        cookie, self._next_cookie = self._next_cookie + 1, self._next_cookie + 2 # odd cookie
        self._logger.debug(f"allocating cookie {cookie:#06x}")
        return cookie
