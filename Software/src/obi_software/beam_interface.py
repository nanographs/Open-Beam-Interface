from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
import enum
import struct
import array
import asyncio
import socket
import logging
import inspect
import random

from .support import dump_hex


BIG_ENDIAN = (struct.pack('@H', 0x1234) == struct.pack('>H', 0x1234))


logger = logging.getLogger()


class TransferError(Exception):
    pass


class Stream:
    _logger = logger.getChild("Stream")

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer

    def send(self, data: bytes | bytearray | memoryview):
        self._logger.debug(f"send: data=<{dump_hex(data)}>")
        self._writer.write(data)
        self._logger.debug(f"send: done")

    async def flush(self):
        self._logger.debug("flush")
        await self._writer.drain()
        self._logger.debug("flush: done")

    async def recv(self, length: int) -> bytearray:
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
        self._logger.debug(f"recv: done")
        return buffer
    
    async def recv_until_done(self, length: int, done_sending: asyncio.Event) -> bytearray:
        self._logger.debug(f"recv: length={length}")
        buffer = bytearray()
        remain = length
        while remain > 0:
            if done_sending.is_set():
                self._logger.debug("recv: break on done_sending")
                break
            data = await self._reader.read(remain)
            if len(data) == 0:
                raise asyncio.IncompleteReadError
            remain -= len(data)
            self._logger.debug(f"recv: data=<{dump_hex(data)}> remain={remain}")
            buffer.extend(data)
        self._logger.debug(f"recv: done")
        return buffer

    async def xchg(self, data: bytes | bytearray | memoryview, *, recv_length: int) -> bytes:
        self.send(data)
        return await self.recv(recv_length)

class OutputMode(enum.IntEnum):
    SixteenBit          = 0x00
    EightBit            = 0x01
    NoOutput            = 0x02

class Command(metaclass=ABCMeta):
    def __init_subclass__(cls):
        cls._logger = logger.getChild(f"Command.{cls.__name__}")

    @classmethod
    def log_transfer(cls, transfer):
        if inspect.isasyncgenfunction(transfer):
            async def wrapper(self, *args, **kwargs):
                repr_short = repr(self).replace(self.__class__.__name__, "cls")
                self._logger.debug(f"iter begin={repr_short}")
                async for chunk in transfer(self, *args, **kwargs):
                    if isinstance(chunk, list):
                        self._logger.debug(f"iter chunk=<list of {len(chunk)}>")
                    elif isinstance(chunk, array.array):
                        self._logger.debug(f"iter chunk=<array of {len(chunk)}>")
                    else:
                        self._logger.debug(f"iter chunk={chunk!r}")
                    yield chunk
                self._logger.debug(f"iter end={repr_short}")
        else:
            async def wrapper(self, *args, **kwargs):
                repr_short = repr(self).replace(self.__class__.__name__, "cls")
                self._logger.debug(f"begin={repr_short}")
                await transfer(self, *args, **kwargs)
                self._logger.debug(f"end={repr_short}")
        return wrapper

    @abstractmethod
    async def transfer(self, stream: Stream):
        ...

    async def recv_res(self, pixel_count, stream: Stream, output_mode:OutputMode):
        if output_mode == OutputMode.NoOutput:
                pass
        else:
            if output_mode == OutputMode.SixteenBit:
                res = array.array('H', await stream.recv(pixel_count * 2))
                if not BIG_ENDIAN:
                    res.byteswap()
                return res
            if output_mode == OutputMode.EightBit:
                res = array.array('B', await stream.recv(pixel_count))
                return res

class Connection:
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
        self._stream = Stream(*await asyncio.open_connection(
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
        print("synchronizing")
        if not self.connected:
            await self._connect()
        if self.synchronized:
            print("already synced")
            return

        print("not synced")

        cookie, self._next_cookie = self._next_cookie, self._next_cookie + 2 # even cookie
        self._logger.debug(f'synchronizing with cookie {cookie:#06x}')
        print("synchronizing with cookie")

        cmd = struct.pack(">BHBB",
            CommandType.Synchronize, cookie, 0,
            CommandType.Flush)
        res = struct.pack(">HH", 0xffff, cookie)
        self._stream.send(cmd)
        while True:
            print("trying to synchronize...")
            try:
                flushed = await self._stream._reader.readuntil(res)
                self._logger.debug(f"synchronized after {len(flushed)} bytes")
                self._synchronized = True
                break
            except asyncio.LimitOverrunError:
                print("LimitOverrunError")
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

    async def transfer(self, command: Command, **kwargs):
        self._logger.debug(f"transfer {command!r}")
        try:
            await self._synchronize() # may raise asyncio.IncompleteReadError
            return await command.transfer(self._stream, **kwargs)
        except asyncio.IncompleteReadError as e:
            self._handle_incomplete_read(e)

    async def transfer_multiple(self, command: Command, **kwargs):
        self._logger.debug(f"transfer multiple {command!r}")
        try:
            await self._synchronize() # may raise asyncio.IncompleteReadError
            async for value in command.transfer(self._stream, **kwargs):
                yield value
        except asyncio.IncompleteReadError as e:
            self._handle_incomplete_read(e)


class CommandType(enum.IntEnum):
    Synchronize         = 0x00
    Abort               = 0x01
    Flush               = 0x02
    Delay               = 0x03
    ExternalCtrl        = 0x04

    RasterRegion        = 0x10
    RasterPixels        = 0x11
    RasterPixelRun      = 0x12
    RasterPixelFreeRun  = 0x13
    VectorPixel         = 0x14


class SynchronizeCommand(Command):
    def __init__(self, *, cookie: int, raster_mode: bool, output_mode: OutputMode=OutputMode.SixteenBit):
        assert cookie in range(0x0001, 0x10000, 2) # odd cookies only
        self._cookie = cookie
        self._raster_mode = raster_mode
        self._output_mode = output_mode
        self._mode = int(self._output_mode*2 + self._raster_mode)

    def __repr__(self):
        return f"SynchronizeCommand(cookie={self._cookie}, mode={self._mode} [raster_mode={self._raster_mode}, output_mode={self._output_mode}])"

    @Command.log_transfer
    async def transfer(self, stream: Stream):
        cmd = struct.pack(">BHB", CommandType.Synchronize, self._cookie, self._mode)
        res = await stream.xchg(cmd, recv_length=4)
        sync, cookie = struct.unpack(">HH", res)
        return cookie


class AbortCommand(Command):
    async def transfer(self, stream: Stream):
        cmd = struct.pack(">B", CommandType.Abort)
        stream.send(cmd)
        await stream.flush()

class DelayCommand(Command):
    def __init__(self, delay):
        assert delay <= 65536
        self._delay = delay
    def __repr__(self):
        return f"DelayCommand(delay={self._delay})"
    @Command.log_transfer
    async def transfer(self, stream: Stream):
        cmd = struct.pack(">BH", CommandType.Delay, self._delay)
        stream.send(cmd)
        # await stream.flush()

class BeamType(enum.IntEnum):
    Electron = 0x01
    Ion = 0x02
class _ExternalCtrlCommand(Command):
    def __init__(self, enable, beam_type):
        assert enable <= 1
        assert (beam_type == BeamType.Electron) | (beam_type == BeamType.Ion)
        self._enable = enable
        self._beam_type = beam_type

    def __repr__(self):
        return f"_ExternalCtrlCommand(enable={self._enable}, beam_type={self._beam_type})"

    @Command.log_transfer
    async def transfer(self, stream: Stream):
        cmd = struct.pack(">BBB", CommandType.ExternalCtrl, self._enable, self._beam_type)
        stream.send(cmd)
        await stream.flush()

# Scan Selector board uses TE 1462051-2 Relay
# Switching delay is 20 ms
RELAY_DELAY_CYCLES = int(20 * pow(10, -6) / (1/(48 * pow(10,6))))
class ExternalCtrlCommand(Command):
    def __init__(self, enable, beam_type):
        assert enable <= 1
        assert (beam_type == BeamType.Electron) | (beam_type == BeamType.Ion)
        self._enable = enable
        self._beam_type = beam_type

    def __repr__(self):
        return f"ExternalCtrlCommand(enable={self._enable}, beam_type={self._beam_type})"

    @Command.log_transfer
    async def transfer(self, stream: Stream):
        await _ExternalCtrlCommand(self._enable, self._beam_type).transfer(stream)
        await DelayCommand(RELAY_DELAY_CYCLES).transfer(stream)



@dataclass
class DACCodeRange:
    start: int # UQ(14,0)
    count: int # UQ(14,0)
    step:  int # UQ(8,8)


class _RasterRegionCommand(Command):
    def __init__(self, *, x_range: DACCodeRange, y_range: DACCodeRange):
        self._x_range = x_range
        self._y_range = y_range

    def __repr__(self):
        return f"_RasterRegionCommand(x_range={self._x_range}, y_range={self._y_range})"

    @Command.log_transfer
    async def transfer(self, stream: Stream):
        cmd = struct.pack(">BHHHHHH", CommandType.RasterRegion,
            self._x_range.start, self._x_range.count, self._x_range.step,
            self._y_range.start, self._y_range.count, self._y_range.step)
        stream.send(cmd)
        await stream.flush()


class DwellTime(int):
    pass


class _RasterPixelsCommand(Command):
    """Commands are submitted in chunks of no longer than `latency` total dwell time, in ADC cycles."""
    def __init__(self, *, dwells: list[DwellTime]):
        self._dwells  = dwells

    def __repr__(self):
        return f"_RasterPixelsCommand(dwells=<list of {len(self._dwells)}>)"

    def _iter_chunks(self, latency: int):
        assert not any(dwell > latency for dwell in self._dwells), "Pixel dwell time higher than latency"

        commands = b""
        def append_command(chunk):
            nonlocal commands
            commands += struct.pack(">BH", CommandType.RasterPixels, len(chunk) - 1)
            if not BIG_ENDIAN: # there is no `array.array('>H')`
                chunk.byteswap()
            commands += chunk.tobytes()

        chunk = array.array('H')
        pixel_count = 0
        total_dwell  = 0
        for pixel in self._pixels:
            chunk.append(pixel)
            pixel_count += 1
            total_dwell  += pixel
            if len(chunk) == 0xffff or total_dwell >= latency:
                append_command(chunk)
                del chunk[:] # clear
            if total_dwell >= latency:
                yield (commands, pixel_count)
                commands = b""
                pixel_count = 0
                total_dwell = 0
        if chunk:
            append_command(chunk)
            yield (commands, pixel_count)

    @Command.log_transfer
    async def transfer(self, stream: Stream, latency: int, output_mode:OutputMode=OutputMode.SixteenBit):
        for commands, pixel_count in self._iter_chunks(latency):
            stream.send(commands)
            stream.send(struct.pack(">B", CommandType.Flush))
            yield await self.recv_res(pixel_count, stream, output_mode)


class _RasterPixelRunCommand(Command):
    def __init__(self, *, dwell: DwellTime, length: int):
        self._dwell   = dwell
        self._length  = length

    def __repr__(self):
        return f"_RasterPixelRunCommand(dwell={self._dwell}, length={self._length})"

    def _iter_chunks(self, latency: int):
        assert not (self._dwell > latency), "Pixel dwell time higher than latency"

        commands = b""
        def append_command(run_length):
            nonlocal commands
            commands += struct.pack(">BHH", CommandType.RasterPixelRun, run_length - 1, self._dwell)

        pixel_count = 0
        total_dwell = 0
        for _ in range(self._length):
            pixel_count += 1
            total_dwell += self._dwell
            if total_dwell >= latency:
                append_command(pixel_count)
                yield (commands, pixel_count)
                commands = b""
                pixel_count = 0
                total_dwell = 0
        if pixel_count > 0:
            append_command(pixel_count)
            yield (commands, pixel_count)

    @Command.log_transfer
    async def transfer(self, stream: Stream, latency: int, output_mode:OutputMode=OutputMode.SixteenBit):
        MAX_PIPELINE = 32

        tokens = MAX_PIPELINE
        token_fut = asyncio.Future()

        async def sender():
            nonlocal tokens
            for commands, pixel_count in self._iter_chunks(latency):
                self._logger.debug(f"sender: tokens={tokens}")
                if tokens == 0:
                    stream.send(struct.pack(">B", CommandType.Flush))
                    await stream.flush()
                    await token_fut
                stream.send(commands)
                tokens -= 1
                await asyncio.sleep(0)
            stream.send(struct.pack(">B", CommandType.Flush))
            await stream.flush()
        asyncio.create_task(sender())

        for commands, pixel_count in self._iter_chunks(latency):
            tokens += 1
            if tokens == 1:
                token_fut.set_result(None)
                token_fut = asyncio.Future()
            self._logger.debug(f"recver: tokens={tokens}")
            await asyncio.sleep(0)
            yield await self.recv_res(pixel_count, stream, output_mode)
            

class _RasterPixelFreeRunCommand(Command):
    def __init__(self, *, dwell: DwellTime, interrupt: asyncio.Event):
        self._dwell = dwell
        self._interrupt = interrupt
        self._done_sending = asyncio.Event()

    def __repr__(self):
        return f"_RasterPixelFreeRunCommand(dwell={self._dwell})"
    
    def _iter_chunks(self, latency:int):
        assert not (self._dwell > latency), "Pixel dwell time higher than latency"
        while not self._interrupt.is_set():
            yield

    @Command.log_transfer
    async def transfer(self, stream: Stream, latency: int):

        async def sender():
            stream.send(struct.pack('>BH', CommandType.RasterPixelFreeRun, self._dwell))
            for _ in self._iter_chunks(latency):
                await asyncio.sleep(0)
            stream.send(struct.pack('>BHB', CommandType.Synchronize, 666, 1))
            await stream.flush()
            self._done_sending.set()

        asyncio.create_task(sender())

        for _ in self._iter_chunks(latency):
            res = array.array('H', await stream.recv_until_done(latency*2, self._done_sending))
            if not BIG_ENDIAN:
                res.byteswap()
            await asyncio.sleep(0)
            yield res


class _VectorPixelCommand(Command):
    def __init__(self, *, x_coord: int, y_coord: int, dwell: DwellTime):
        self._x_coord = x_coord
        self._y_coord = y_coord
        self._dwell   = dwell

    def __repr__(self):
        return f"_VectorPixelCommand(x_coord={self._x_coord}, y_coord={self._y_coord}, dwell={self._dwell})"

    @Command.log_transfer
    async def transfer(self, stream: Stream):
        cmd = struct.pack(">BHHH", self._x_coord, self._y_coord, self._dwell)
        res = await stream.xchg(cmd, 2)
        data, = struct.unpack(res, ">H")
        return data

class RasterStreamCommand(Command):
    def __init__(self, *, cookie: int, x_range: DACCodeRange, y_range: DACCodeRange, dwells: list[DwellTime]):
        assert (x_range.count * y_range.count) % len(dwells) == 0, \
            "Pixel count not multiple of raster scan point count"

        self._cookie  = cookie
        self._x_range = x_range
        self._y_range = y_range
        self._dwells  = dwells

    def __repr__(self):
        return f"RasterStreamCommand(cookie={self._cookie}, x_range={self._x_range}, y_range={self._y_range}, dwells=<list of {len(self._dwells)}>)"

    @Command.log_transfer
    async def transfer(self, stream: Stream, latency: int):
        await SynchronizeCommand(cookie=self._cookie, raster_mode=True).transfer(stream)
        await _RasterRegionCommand(x_range=self._x_range, y_range=self._y_range).transfer(stream)
        total, done = self._x_range.count * self._y_range.count, 0
        async for chunk in _RasterPixelsCommand(dwells=self._dwells).transfer(stream, latency=latency):
            yield chunk
            done += len(chunk)
            self._logger.debug(f"total={total} done={done}")


class RasterScanCommand(Command):
    def __init__(self, *, cookie: int, x_range: DACCodeRange, y_range: DACCodeRange, dwell: DwellTime, beam_type: BeamType):
        self._cookie  = cookie
        self._x_range = x_range
        self._y_range = y_range
        self._dwell   = dwell
        self._beam_type = beam_type

    def __repr__(self):
        return f"RasterScanCommand(cookie={self._cookie}, x_range={self._x_range}, y_range={self._y_range}, dwell={self._dwell}, beam_type={self._beam_type}>)"

    @Command.log_transfer
    async def transfer(self, stream: Stream, latency: int):
        await SynchronizeCommand(cookie=self._cookie, raster_mode=True).transfer(stream)
        await _RasterRegionCommand(x_range=self._x_range, y_range=self._y_range).transfer(stream)
        total, done = self._x_range.count * self._y_range.count, 0
        async for chunk in _RasterPixelRunCommand(dwell=self._dwell, length=total).transfer(stream, latency):
            yield chunk
            done += len(chunk)
            self._logger.debug(f"{total=} {done=}")


class RasterFreeScanCommand(Command):
    def __init__(self, *, cookie: int, x_range: DACCodeRange, y_range: DACCodeRange, dwell: DwellTime, beam_type: BeamType, interrupt: asyncio.Event):
        self._cookie  = cookie
        self._x_range = x_range
        self._y_range = y_range
        self._dwell   = dwell
        self._beam_type = beam_type
        self._interrupt = interrupt

    def __repr__(self):
        return f"RasterFreeScanCommand(cookie={self._cookie}, x_range={self._x_range}, y_range={self._y_range}, dwell={self._dwell}, beam_type={self._beam_type}>)"

    @Command.log_transfer
    async def transfer(self, stream: Stream, latency: int):
        await SynchronizeCommand(cookie=self._cookie, raster_mode=True).transfer(stream)
        await _RasterRegionCommand(x_range=self._x_range, y_range=self._y_range).transfer(stream)
        count = 0
        async for chunk in _RasterPixelFreeRunCommand(dwell=self._dwell, interrupt=self._interrupt).transfer(stream, latency):
            yield chunk
            count += len(chunk)
            self._logger.debug(f"{count=}")
        self._interrupt.clear()
        self._logger.debug("RasterFreeScanCommand exited and interrupt cleared.")


import numpy as np
#import PIL
class FrameBuffer():
    def __init__(self, conn):
        self.conn = conn

    async def capture_image(self, x_range, y_range, *, dwell, latency):
        cmd = RasterScanCommand(cookie=self.conn.get_cookie(),
            x_range=x_range, y_range=y_range, dwell=dwell)
        res = array.array('H')
        async for chunk in self.conn.transfer_multiple(cmd, latency=latency):
            res.extend(chunk)
        return res

    def output_pgm(self, res, x_range, y_range):
        with open("output.pgm", "wt") as f:
            f.write(f"P2\n")
            f.write(f"{x_range.count} {y_range.count}\n")
            f.write(f"{(1 << 14) - 1}\n")
            for x_start in range(0, len(res), y_range.count):
                row = res[x_start:x_start + x_range.count]
                f.write(" ".join(str(val) for val in row))
                f.write("\n")

    def output_ndarray(self, res, x_range, y_range):
        ar = np.array(res)
        ar = ar.astype(np.uint8)
        ar = ar.reshape(x_range.count, y_range.count)
        return ar


def setup_logging(levels=None):
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(style="{",
        fmt="{levelname[0]:s}: {name:s}: {message:s}"))
    logging.getLogger().addHandler(handler)

    logging.getLogger().setLevel(logging.INFO)
    if levels:
        for logger_name, level in levels.items():
            logging.getLogger(logger_name).setLevel(level)


async def main():
    # setup_logging()
    #setup_logging({"Command": logging.DEBUG})
    setup_logging({"Command": logging.DEBUG, "Stream": logging.DEBUG})

    conn = Connection('localhost', 2223)
    fb = FrameBuffer(conn)

    # x_range = y_range = DACCodeRange(0, 16384, 1)
    x_range = y_range = DACCodeRange(0, 2048, int((16384/2048)*256))
    # x_range = y_range = DACCodeRange(0, 192, 21845)

    #res = await fb.capture_image(x_range, y_range, dwell=2, latency=0x10000)
    # fb.output_pgm(res, x_range, y_range)

    await fb.free_scan(x_range, y_range, dwell=2, latency=0x10000)


if __name__ == '__main__':
    asyncio.run(main())
