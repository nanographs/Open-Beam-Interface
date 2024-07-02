from abc import abstractmethod, ABCMeta
import asyncio
import random

import logging
logger = logging.getLogger()
from . import *


class TransferError(Exception):
    pass

class Stream(metaclass = ABCMeta):
    #_logger = logger.getChild("Stream")
    @abstractmethod
    async def write(self, data: bytes | bytearray | memoryview):
        ...
    @abstractmethod
    async def flush(self):
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
    
    # @abstractmethod
    # async def _connect(self):
    #     ...
    
    # def _disconnect(self):
    #     assert self.connected
    #     self._stream = None
    #     self._synchronized = False
    
    @abstractmethod
    async def _synchronize(self):
        ...
    
    def _handle_incomplete_read(self, exc):
        self._disconnect()
        raise TransferError("connection closed") from exc

    def get_cookie(self):
        cookie, self._next_cookie = self._next_cookie + 1, self._next_cookie + 2 # odd cookie
        self._logger.debug(f"allocating cookie {cookie:#06x}")
        return cookie
    
    async def transfer(self, command: BaseCommand, **kwargs):
        self._logger.debug(f"transfer {command!r}")
        try:
            await self._synchronize() # may raise asyncio.IncompleteReadError
            return await command.transfer(self._stream, **kwargs)
        except asyncio.IncompleteReadError as e:
            self._handle_incomplete_read(e)



class TCPStream(Stream):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        
    async def write(self, data: bytes | bytearray | memoryview):
        #self._logger.debug(f"send: data=<{dump_hex(data)}>")
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
            #self._logger.debug(f"recv: data=<{dump_hex(data)}> remain={remain} - time {stop-start:.4f}")
            buffer.extend(data)
        stop = perf_counter()
        self._logger.debug(f"recv: done - time {stop-loop_start:.4f}")
        return memoryview(buffer)
    
    async def readuntil(self, separator=b'\n', *, flush=True, max_count=False) -> memoryview:
        return await self._reader.readuntil(seperator, flush=flush, max_count=max_count)

    async def xchg(self, data: bytes | bytearray | memoryview, *, recv_length: int) -> bytes:
        await self.send(data)
        return await self.recv(recv_length)

class GlasgowStream(Stream):
    def __init__(self, iface):
        self.lower = iface
    async def write(self, data):
        await self.lower.write(data)
    async def flush(self):
        await self.lower.flush()
    async def read(self, length):
        return await self.lower.read(length)
    async def readuntil(self, separator=b'\n', *, flush=True, max_count=False):
        def find_sep(buffer, separator=b'\n', offset=0):
            if buffer._chunk is None:
                if not buffer._queue:
                    raise asyncio.IncompleteReadError
                buffer._chunk  = buffer._queue.popleft()
                buffer._offset = 0
            return buffer._chunk.obj.find(separator)

        if flush and len(self.lower._out_buffer) > 0:
            # Flush the buffer, so that everything written before the read reaches the device.
            await self.lower.flush(wait=False)

        seplen = len(separator)
        if seplen == 0:
            raise ValueError('Separator should be at least one-byte string')
        chunks = []

        # Loop until we find `separator` in the buffer, exceed the buffer size,
        # or an EOF has happened.
        while True:
            buflen = len(self.lower._in_buffer)

            if max_count & (buflen >= max_count):
                break
        
            # Check if we now have enough data in the buffer for `separator` to fit.
            if buflen >= seplen:
                isep = find_sep(self.lower._in_buffer, separator)
                if isep != -1:
                    print(f"found {isep=}")
                    # `separator` is in the buffer. `isep` will be used later
                    # to retrieve the data.
                    break
            else:
                await self.lower._in_tasks.wait_one()

            async with self.lower._in_pushback:
                chunk = self.lower._in_buffer.read()
                self.lower._in_pushback.notify_all()
                chunks.append(chunk)
            
        if not (max_count & (buflen >= max_count)):
            async with self.lower._in_pushback:
                chunk = self.lower._in_buffer.read(isep+seplen)
                self.lower._in_pushback.notify_all()
                chunks.append(chunk)
        
        # Always return a memoryview object, to avoid hard to detect edge cases downstream.
        result = memoryview(b"".join(chunks))
        return result
    


class GlasgowConnection(Connection):
    def connect(self, stream):
        self.stream = stream
    async def _synchronize(self):
        print("synchronizing")
        if self.synchronized:
            print("already synced")
            return

        print("not synced")
        cookie, self._next_cookie = self._next_cookie, (self._next_cookie + 2) & 0xffff # even cookie
        #self._logger.debug(f'synchronizing with cookie {cookie:#06x}')
        print("synchronizing with cookie")

        cmd = bytearray()
        cmd.extend(bytes(SynchronizeCommand(raster=True, output=OutputMode.SixteenBit, cookie=123)))
        cmd.extend(bytes(FlushCommand()))
        await self.stream.write(cmd)
        await self.stream.flush()
        res = struct.pack(">HH", 0xffff, cookie)
        data = await self.stream.readuntil(res)
        print(str(list(data)))


#     async def transfer(self, seq): #CommandSequence
#         #await self._synchronize()
#         await self.lower.write(seq.message)
#         await self.lower.flush()
#         data = await self.lower.read(seq._response_length)
#         return seq.unpack(data)
    
