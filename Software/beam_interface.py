from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
import struct
import array
import asyncio
import logging
import inspect


BIG_ENDIAN = (struct.pack('@H', 0x1234) == struct.pack('>H', 0x1234))


logger = logging.Logger(__name__)


class TransferError(Exception):
    pass


class Stream:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
    
    async def send(self, data: bytes | bytearray | memoryview):
        self._writer.write(data)
        await self._writer.drain()
    
    async def recv(self, length: int) -> bytes:
        return await self._reader.readexactly(data)
    
    async def xchg(self, data: bytes | bytearray | memoryview, *, recv_length: int) -> bytes:
        await self.send(data)
        return await self.recv(recv_length)


class Command(metaclass=ABCMeta):
    @abstractmethod
    async def transfer(self, stream: Stream):
        ...


class Connection:
    def __init__(self, host: str, port: int, *, read_buffer_size=0x10000):
        self.host = host
        self.port = port
        self.read_buffer_size = read_buffer_size

        self._stream = None
        self._synchronized = False
        self._next_cookie = 0 # even cookies only
    
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
        self._stream = Stream(*await asyncio.open_connection(
            self.host, self.port, limit=self.read_buffer_size))

        peername = self._writer.get_extra_info('peername')
        logger.info(f'Connected to server at {addr}')
    
    def _disconnect(self):
        assert self.connected
        self._stream = None

    async def _synchronize(self):
        self._next_cookie += 2 # even cookie to next even cookie
        logger.debug(f'Synchronizing with cookie {self._next_cookie:#06x}')
        command  = struct.pack(">BHB", CommandType.Synchronize, self._next_cookie, 0)
        response = struct.pack(">HH", 0xffff, self._next_cookie)
        await self._stream.send(output)
        while True:
            try:
                await self._stream._reader.readuntil(response)
            except asyncio.LimitOverrunError:
                # If we're here, it means the read buffer has exactly `self.read_buffer_size` bytes
                # in it (set by the `open_connection(limit=)` argument). A partial response could
                # still be at the very end of the buffer, so read less than that.
                await self._stream._reader.readexactly(self.read_buffer_size - len(response))

    async def transfer(self, command: Command):
        if not self.connected:
            await self._connect()

        try:
            if not self.synchronized:
                await self._synchronize() # may raise asyncio.IncompleteReadError

            result = await command.transfer(stream)
            if inspect.isasyncgen(result):
                async for value in result:
                    yield value
            else:
                return result

        except asyncio.IncompleteReadError as e:
            self._disconnect()
            raise TransferError("connection closed") from e


class CommandType(enum.IntEnum):
    Synchronize     = 0x00
    Abort           = 0x01
    Flush           = 0x02

    RasterRegion    = 0x10
    RasterPixels    = 0x11
    RasterPixelRun  = 0x12
    VectorPixel     = 0x13


class SynchronizeCommand(Command):
    def __init__(self, *, cookie: int, raster_mode: bool):
        assert cookie in range(0x0001, 0x10000, 2) # odd cookies only
        self._cookie = cookie
        self._raster_mode = raster_mode

    async def transfer(self, stream: Stream):
        cmd = struct.pack(">BHB", CommandType.Synchronize, self._cookie, self._raster_mode)
        res = await writer.xchg(cmd, recv_length=2)
        cookie, = struct.unpack(">H", res)
        return cookie


class AbortCommand(Command):
    async def transfer(self, stream: Stream):
        await writer.send([CommandType.Abort])


class FlushCommand(Command):
    async def transfer(self, stream: Stream):
        await writer.send([CommandType.Flush])


@dataclass
class DACCodeRange:
    start: int # UQ(14,0)
    count: int # UQ(14,0)
    step:  int # UQ(8,8)


class _RasterRegionCommand(Command):
    def __init__(self, *, x_range: DACCodeRange, y_range: DACCodeRange):
        self._x_range = x_range
        self._y_range = y_range

    async def transfer(self, stream: Stream):
        cmd = struct.pack(">BHHHHHH", CommandType.RasterRegion,
            self._x_range.start, self._x_range.count, self._x_range.step,
            self._y_range.start, self._y_range.count, self._y_range.step)
        await writer.send(cmd)


class DwellTime(int):
    pass


class _RasterPixelsCommand(Command):
    """Commands are submitted in chunks of no longer than `latency` total dwell time, in ADC cycles."""
    def __init__(self, *, pixels: list[DwellTime], latency: int):
        assert not any(pixel > latency for pixel in pixels), "Pixel dwell time higher than latency"

        self._pixels  = pixels
        self._latency = latency

    def _iter_chunks(self):
        commands = b""
        def append_command(chunk):
            nonlocal commands
            commands += struct.pack(">BH", CommandType.RasterPixels, len(chunk))
            if not BIG_ENDIAN: # there is no `array.array('>H')`
                chunk.byteswap()
            commands += chunk.tobytes()

        chunk = array.array('H')
        dwell_time = 0
        for pixel in self._pixels:
            chunk.append(pixel)
            dwell_time += pixel
            if len(chunk) == 0xffff or dwell_time >= self._latency:
                append_command(chunk)
                del chunk[:] # clear
            if dwell_time >= self._latency:
                yield (commands, len(chunk))
                commands = b""
        if chunk:
            append_command(chunk)
            yield (commands, len(chunk))
    
    async def transfer(self, stream: Stream):
        for commands, pixel_count in self._iter_chunks():
            await stream.send(commands)
            data = array('H', await stream.recv(pixel_count * 2))
            if not BIG_ENDIAN:
                data.byteswap()
            yield data


class _RasterPixelRunCommand(Command):
    def __init__(self, *, pixel: DwellTime, length: int, latency: int):
        assert not (pixel > latency), "Pixel dwell time higher than latency"

        self._pixel   = pixel
        self._length  = length
        self._latency = latency

    def _iter_chunks(self):
        commands = b""
        def append_command(run_length):
            nonlocal commands
            commands += struct.pack(">BHH", CommandType.RasterPixelRun, run_length, self._pixel)

        run_length = 0
        dwell_time = 0
        for pixel in range(self._length):
            run_length += 1
            dwell_time += pixel
            if dwell_time >= self._latency:
                append_command(run_length)
                yield (commands, run_length)
                commands = b""
        if run_length > 0:
            append_command(run_length)
            yield (commands, run_length)
        
    async def transfer(self, stream: Stream):
        for commands, pixel_count in self._iter_chunks():
            await stream.send(commands)
            res = array.array('H', await stream.recv(pixel_count * 2))
            if not BIG_ENDIAN:
                res.byteswap()
            yield res


class _VectorPixelCommand(Command):
    def __init__(self, *, x_coord: int, y_coord: int, pixel: DwellTime):
        self._x_coord = x_coord
        self._y_coord = y_coord
        self._pixel   = pixel

    async def transfer(self, stream: Stream):
        cmd = struct.pack(">BHHH", self._x_coord, self._y_coord, self._pixel)
        res = await stream.xchg(cmd, 2)
        data, = struct.unpack(res, ">H")
        return data


class RasterScanCommand(Command):
    def __init__(self, *, cookie: int, x_range: DACCodeRange, y_range: DACCodeRange):
        self._cookie = cookie

    async def transfer(self, stream: Stream):
        await SynchronizeCommand(cookie=self._cookie, raster_mode=True).transfer(stream)