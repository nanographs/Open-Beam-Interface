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
import time
from time import perf_counter

from .support import dump_hex
from base_commands import *


BIG_ENDIAN = (struct.pack('@H', 0x1234) == struct.pack('>H', 0x1234))


logger = logging.getLogger()


class TransferError(Exception):
    pass


class Stream:
    _logger = logger.getChild("Stream")
    high_water = 262144 #65536

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
        loop_start = perf_counter()
        while remain > 0:
            start = perf_counter()
            data = await self._reader.read(remain)
            stop = perf_counter()
            if len(data) == 0:
                raise asyncio.IncompleteReadError
            remain -= len(data)
            self._logger.debug(f"recv: data=<{dump_hex(data)}> remain={remain} - time {stop-start:.4f}")
            buffer.extend(data)
        stop = perf_counter()
        self._logger.debug(f"recv: done - time {stop-loop_start:.4f}")
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
        start = perf_counter()
        self.send(data)
        return await self.recv(recv_length)
        stop = perf_counter()
        self._logger.debug(f"xchg time: {stop-start:.4f}")


class StreamCommand(metaclass=ABCMeta):
    def __init_subclass__(cls):
        cls._logger = logger.getChild(f"Command.{cls.__name__}")

    @classmethod
    def log_transfer(cls, transfer):
        if inspect.isasyncgenfunction(transfer):
            async def wrapper(self, *args, **kwargs):
                repr_short = repr(self).replace(self.__class__.__name__, "cls")
                self._logger.debug(f"iter begin={repr_short}")
                loop_start = perf_counter()
                start = perf_counter()
                async for chunk in transfer(self, *args, **kwargs):
                    now = perf_counter()
                    if isinstance(chunk, list):
                        self._logger.debug(f"iter chunk=<list of {len(chunk)}> time - {now-start:.4f}")
                    elif isinstance(chunk, array.array):
                        self._logger.debug(f"iter chunk=<array of {len(chunk)}> time - {now-start:.4f}")
                    else:
                        self._logger.debug(f"iter chunk={chunk!r} time - {now-start:.4f}")
                    start = now
                    yield chunk
                now = perf_counter()
                self._logger.debug(f"iter end={repr_short} time - {now-loop_start:.4f}")
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
                start = perf_counter()
                await asyncio.sleep(0)
                stop = perf_counter()
                self._logger.debug(f"recv_res None: time - {stop-start:.4f}")
                pass
        else:
            if output_mode == OutputMode.SixteenBit:
                start = perf_counter()
                res = array.array('H', await stream.recv(pixel_count * 2))
                if not BIG_ENDIAN:
                    res.byteswap()
                stop = perf_counter()
                self._logger.debug(f"recv_res 16: time - {stop-start:.4f}")
                await asyncio.sleep(0)
                sleep = perf_counter()
                self._logger.debug(f"recv_res sleep: time - {sleep-stop:.4f}")
                return res
            if output_mode == OutputMode.EightBit:
                start = perf_counter()
                res = array.array('B', await stream.recv(pixel_count))
                stop = perf_counter()
                self._logger.debug(f"recv_res 8: time - {stop-start:.4f}")
                await asyncio.sleep(0)
                sleep = perf_counter()
                self._logger.debug(f"recv_res sleep: time - {sleep-stop:.4f}")
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
        if not self.connected:
            await self._connect()
        if self.synchronized:
            self._logger.debug("already synced")
            return

        cookie, self._next_cookie = self._next_cookie, (self._next_cookie + 2) & 0xffff # even cookie
        self._logger.debug(f'synchronizing with cookie {cookie:#06x}')

        seq = CommandSequence(cookie=cookie, output=OutputMode.SixteenBit, raster=False)
        seq.extend(FlushCommand())
        #res = SynchronizeCommand(cookie=cookie, output=OutputMode.SixteenBit, raster=False).byte_response
        res = struct.pack(">HH", 65535, cookie)
        self._stream.send(bytes(seq))
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
            start = perf_counter()
            await self._synchronize() # may raise asyncio.IncompleteReadError
            stop = perf_counter()
            self._logger.debug(f"synchronize transfer_multiple: time - {stop-start:.4f}")
            start = perf_counter()
            async for value in command.transfer(self._stream, **kwargs):
                yield value
                now = perf_counter()
                self._logger.debug(f"yield transfer_multiple: time - {now-start:.4f}")
                start = now
        except asyncio.IncompleteReadError as e:
            self._handle_incomplete_read(e)
    
    async def transfer_raw(self, command, flush:bool = False, **kwargs):
        self._logger.debug(f"transfer {command!r}")
        await self._synchronize() # may raise asyncio.IncompleteReadError
        self._stream.send(command.message)
        await self._stream.flush()
    
    async def transfer_bytes(self, data:bytes, flush:bool = False, **kwargs):
        await self._synchronize() # may raise asyncio.IncompleteReadError
        self._stream.send(data)
        await self._stream.flush()


class StreamCommand(metaclass=ABCMeta):
    def __init_subclass__(cls, command:BaseCommand):
        cls._logger = logger.getChild(f"Command.{cls.__name__}")
        cls.command_cls = command
    def __init__(self, **kwargs):
        self.command = self.command_cls(**kwargs)
    def __repr__(self):
        return self.command.__repr__()

    @classmethod
    def log_transfer(cls, transfer):
        if inspect.isasyncgenfunction(transfer):
            async def wrapper(self, *args, **kwargs):
                repr_short = repr(self).replace(self.__class__.__name__, "cls")
                self._logger.debug(f"iter begin={repr_short}")
                loop_start = perf_counter()
                start = perf_counter()
                async for chunk in transfer(self, *args, **kwargs):
                    now = perf_counter()
                    if isinstance(chunk, list):
                        self._logger.debug(f"iter chunk=<list of {len(chunk)}> time - {now-start:.4f}")
                    elif isinstance(chunk, array.array):
                        self._logger.debug(f"iter chunk=<array of {len(chunk)}> time - {now-start:.4f}")
                    else:
                        self._logger.debug(f"iter chunk={chunk!r} time - {now-start:.4f}")
                    start = now
                    yield chunk
                now = perf_counter()
                self._logger.debug(f"iter end={repr_short} time - {now-loop_start:.4f}")
        else:
            async def wrapper(self, *args, **kwargs):
                repr_short = repr(self).replace(self.__class__.__name__, "cls")
                self._logger.debug(f"begin={repr_short}")
                await transfer(self, *args, **kwargs)
                self._logger.debug(f"end={repr_short}")
        return wrapper

   #@abstractmethod
    async def transfer(self, stream: Stream, flush=False):
        stream.send(bytes(self.command))
        await stream.flush()

    async def recv_res(self, pixel_count, stream: Stream, output_mode:OutputMode):
        if output_mode == OutputMode.NoOutput:
                start = perf_counter()
                await asyncio.sleep(0)
                stop = perf_counter()
                self._logger.debug(f"recv_res None: time - {stop-start:.4f}")
                pass
        else:
            if output_mode == OutputMode.SixteenBit:
                start = perf_counter()
                res = array.array('H', await stream.recv(pixel_count * 2))
                if not BIG_ENDIAN:
                    res.byteswap()
                stop = perf_counter()
                self._logger.debug(f"recv_res 16: time - {stop-start:.4f}")
                await asyncio.sleep(0)
                sleep = perf_counter()
                self._logger.debug(f"recv_res sleep: time - {sleep-stop:.4f}")
                return res
            if output_mode == OutputMode.EightBit:
                start = perf_counter()
                res = array.array('B', await stream.recv(pixel_count))
                stop = perf_counter()
                self._logger.debug(f"recv_res 8: time - {stop-start:.4f}")
                await asyncio.sleep(0)
                sleep = perf_counter()
                self._logger.debug(f"recv_res sleep: time - {sleep-stop:.4f}")
                return res

class StreamSynchronizeCommand(StreamCommand, command=SynchronizeCommand):
    pass

class StreamExternalCtrlCommand(StreamCommand, command=ExternalCtrlCommand):
    pass

class StreamDelayCommand(StreamCommand, command=DelayCommand):
    pass

class StreamBeamSelectCommand(StreamCommand, command=BeamSelectCommand):
    pass

class StreamBlankCommand(StreamCommand, command=BlankCommand):
    pass

class StreamRasterRegionCommand(StreamCommand, command=RasterRegionCommand):
    pass


# Scan Selector board uses TE 1462051-2 Relay
# Switching delay is 20 ms
RELAY_DELAY_CYCLES = int(20 * pow(10, -6) / (1/(48 * pow(10,6))))
class RelayExternalCtrlCommand:
    def __init__(self, enable, beam_type):
        assert enable <= 1
        self._enable = enable
        self._beam_type = beam_type

    def __repr__(self):
        return f"RelayExternalCtrlCommand(enable={self._enable}, beam_type={self._beam_type})"

    #@StreamCommand.log_transfer
    async def transfer(self, stream: Stream):
        await StreamBlankCommand(enable=(1-self._enable), inline=True).transfer(stream)
        await StreamExternalCtrlCommand(enable=self._enable).transfer(stream)
        await StreamBeamSelectCommand(beam_type=self._beam_type).transfer(stream)
        await StreamDelayCommand(delay=RELAY_DELAY_CYCLES).transfer(stream)
        await stream.flush()


class StreamRasterPixelRunCommand(StreamCommand, command = RasterPixelRunCommand):
    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream, latency: int, output_mode:OutputMode=OutputMode.SixteenBit):
        MAX_PIPELINE = 32

        tokens = MAX_PIPELINE
        token_fut = asyncio.Future()

        async def sender():
            nonlocal tokens
            for commands, pixel_count in self.command._iter_chunks(latency):
                self._logger.debug(f"sender: tokens={tokens}")
                if tokens == 0:
                    stream.send(FlushCommand())
                    await stream.flush()
                    await token_fut
                stream.send(commands)
                tokens -= 1
                await asyncio.sleep(0)
            stream.send(FlushCommand())
            await stream.flush()
        asyncio.create_task(sender())

        for commands, pixel_count in self.command._iter_chunks(latency):
            tokens += 1
            if tokens == 1:
                token_fut.set_result(None)
                token_fut = asyncio.Future()
            self._logger.debug(f"recver: tokens={tokens}")
            yield await self.recv_res(pixel_count, stream, output_mode)


class RasterScanCommand:
    def __init__(self, *, cookie: int, x_range: DACCodeRange, y_range: DACCodeRange, dwell: int):
        self._cookie  = cookie
        self._x_range = x_range
        self._y_range = y_range
        self._dwell   = dwell

    def __repr__(self):
        return f"RasterScanCommand(cookie={self._cookie}, x_range={self._x_range}, y_range={self._y_range}, dwell={self._dwell}>)"

    #@StreamCommand.log_transfer
    async def transfer(self, stream: Stream, latency: int):
        await StreamSynchronizeCommand(cookie=self._cookie, raster=True).transfer(stream)
        await StreamRasterRegionCommand(x_range=self._x_range, y_range=self._y_range).transfer(stream)
        total, done = self._x_range.count * self._y_range.count, 0
        async for chunk in StreamRasterPixelRunCommand(dwell=self._dwell, length=total).transfer(stream, latency):
            yield chunk
            done += len(chunk)
            self._logger.debug(f"{total=} {done=}")

def setup_logging(levels=None):
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(style="{",
        fmt="{levelname[0]:s}: {name:s}: {message:s}"))
    logging.getLogger().addHandler(handler)

    logging.getLogger().setLevel(logging.INFO)
    if levels:
        for logger_name, level in levels.items():
            logging.getLogger(logger_name).setLevel(level)

