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
        print("synchronizing")
        if not self.connected:
            await self._connect()
        if self.synchronized:
            print("already synced")
            return

        print("not synced")

        cookie, self._next_cookie = self._next_cookie, (self._next_cookie + 2) & 0xffff # even cookie
        self._logger.debug(f'synchronizing with cookie {cookie:#06x}')
        print("synchronizing with cookie")

        seq = CommandSequence(cookie=cookie, output=OutputMode.SixteenBit, raster=False)
        seq.add(FlushCommand())
        res = SynchronizeCommand(cookie=cookie, output=OutputMode.SixteenBit, raster=False).byte_response
        print(f"{res=}")
        self._stream.send(seq.message)
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


class StreamSynchronizeCommand(SynchronizeCommand, StreamCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert self._cookie in range(0x0001, 0x10000, 2)  # odd cookies only

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream):
        cmd = self.message
        res = await stream.xchg(cmd, recv_length=4)
        sync, cookie_1, cookie_2 = struct.unpack(">HBB", res)
        cookie_reversed = struct.pack('>H', cookie_2*256 + cookie_1)
        return cookie_reversed


class StreamAbortCommand(AbortCommand, StreamCommand):
    async def transfer(self, stream: Stream):
        stream.send(self.message)
        await stream.flush()

class StreamDelayCommand(DelayCommand, StreamCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream):
        stream.send(self.message)


class StreamBlankCommand(BlankCommand, StreamCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream):
        stream.send(self.message)


class StreamExternalCtrlCommand(ExternalCtrlCommand, StreamCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream):
        stream.send(self.message)

class StreamBeamSelectCommand(BeamSelectCommand, StreamCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream):
        stream.send(self.message)


# Scan Selector board uses TE 1462051-2 Relay
# Switching delay is 20 ms
RELAY_DELAY_CYCLES = int(20 * pow(10, -6) / (1/(48 * pow(10,6))))
class RelayExternalCtrlCommand(StreamCommand):
    def __init__(self, enable, beam_type):
        assert enable <= 1
        self._enable = enable
        self._beam_type = beam_type

    def __repr__(self):
        return f"RelayExternalCtrlCommand(enable={self._enable}, beam_type={self._beam_type})"

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream):
        await StreamBlankCommand(enable=(1-self._enable), inline=True).transfer(stream)
        await StreamExternalCtrlCommand(self._enable).transfer(stream)
        await StreamBeamSelectCommand(self._beam_type).transfer(stream)
        await StreamDelayCommand(RELAY_DELAY_CYCLES).transfer(stream)
        await stream.flush()


class StreamRasterRegionCommand(RasterRegionCommand, StreamCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream):
        stream.send(self.message)
        await stream.flush()

class RasterPixelsCommand(RasterPixelsCommand, StreamCommand):
    """Commands are submitted in chunks of no longer than `latency` total dwell time, in ADC cycles."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream, latency: int, output_mode:OutputMode=OutputMode.SixteenBit):
        for commands, pixel_count in self._iter_chunks(latency):
            stream.send(commands)
            stream.send(FlushCommand().message)
            yield await self.recv_res(pixel_count, stream, output_mode)


class StreamRasterPixelRunCommand(RasterPixelRunCommand, StreamCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream, latency: int, output_mode:OutputMode=OutputMode.SixteenBit):
        MAX_PIPELINE = 32

        tokens = MAX_PIPELINE
        token_fut = asyncio.Future()

        async def sender():
            nonlocal tokens
            for commands, pixel_count in self._iter_chunks(latency):
                self._logger.debug(f"sender: tokens={tokens}")
                if tokens == 0:
                    stream.send(FlushCommand().message)
                    await stream.flush()
                    await token_fut
                stream.send(commands)
                tokens -= 1
                await asyncio.sleep(0)
            stream.send(FlushCommand().message)
            await stream.flush()
        asyncio.create_task(sender())

        for commands, pixel_count in self._iter_chunks(latency):
            tokens += 1
            if tokens == 1:
                token_fut.set_result(None)
                token_fut = asyncio.Future()
            self._logger.debug(f"recver: tokens={tokens}")
            yield await self.recv_res(pixel_count, stream, output_mode)
            

class StreamRasterPixelFreeRunCommand(RasterPixelFreeRunCommand, StreamCommand):
    def __init__(self, *, interrupt: asyncio.Event,  **kwargs):
        super().__init__(**kwargs)
        self._interrupt = interrupt
        self._done_sending = asyncio.Event()

    def _iter_chunks(self, latency:int):
        assert not (self._dwell > latency), "Pixel dwell time higher than latency"
        while not self._interrupt.is_set():
            yield

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream, latency: int):

        async def sender():
            stream.send(self.message)
            for _ in self._iter_chunks(latency):
                await asyncio.sleep(0)
            stream.send(SynchronizeCommand(cookie=666, raster=True, output=OutputMode.SixteenBit).message)
            await stream.flush()
            self._done_sending.set()

        asyncio.create_task(sender())

        for _ in self._iter_chunks(latency):
            yield await self.recv_res(pixel_count, stream, output_mode)


class StreamVectorPixelCommand(VectorPixelCommand, StreamCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream, output_mode:OutputMode=OutputMode.SixteenBit):
        stream.send(self.message)
        stream.send(struct.pack(">B", CommandType.Flush))
        return await self.recv_res(1, stream, output_mode)


class VectorPixelLinearRunCommand(StreamCommand):
    def __init__(self, *, pattern_generator):
        self._pattern_generator = pattern_generator

    def __repr__(self):
        return f"VectorPixelLinearRunCommand({self._pattern_generator})"
    
    def _iter_chunks(self):
        commands = bytearray()
        pixel_count = 0
        total_dwell  = 0
        for x_coord, y_coord, dwell in self._pattern_generator:
            pixel_count += 1
            total_dwell += dwell
            commands.extend(VectorPixelCommand(x_coord=x_coord, y_coord=y_coord, dwell=dwell).message)
        print("iter_chunks: reached end of pattern generator")
        return commands, pixel_count
    


    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream, output_mode:OutputMode=OutputMode.SixteenBit):
        MAX_OUT_BUFFER = 131072
        commands, pixel_count = self._iter_chunks()

        #await StreamSynchronizeCommand(cookie=123, raster=False, output=output_mode).transfer(stream)

        async def sender():
            nonlocal commands
            start = perf_counter()
            while len(commands) > MAX_OUT_BUFFER:
                stream.send(commands[:MAX_OUT_BUFFER])
                commands = commands[MAX_OUT_BUFFER:]
            if len(commands) > 0:
                stream.send(commands)
            stream.send(FlushCommand().message)
            await stream.flush()
            stop = perf_counter()
            self._logger.debug(f"sender: time - {stop-start:.4f}")

        await sender()
        yield await self.recv_res(pixel_count, stream, output_mode)

class BenchmarkTransfer(StreamCommand):
    def __repr__(self):
        return f"BenchmarkTransfer)"

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream, output_mode: OutputMode=OutputMode.NoOutput):
        # await StreamSynchronizeCommand(cookie=123, raster=False, 
        #                         output=output_mode).transfer(stream)
        stream.send(SynchronizeCommand(cookie=123, raster=False, output=output_mode).message)
        commands = bytearray()
        print("preparing commands...")
        for _ in range(131072*16):
            commands.extend(VectorPixelCommand(x_coord=0, y_coord=16383, dwell=1).message)
            commands.extend(VectorPixelCommand(x_coord=16383, y_coord=0, dwell=1).message)
            print(f"{len(commands)=}")
        length = len(commands)
        pixel_count = int(length/7)
        while True:
            begin = time.time()
            stream.send(commands)
            # stream.send(struct.pack(">B", CommandType.Flush))
            await stream.flush()
            end = time.time()
            print(f"send: {(length / (end - begin)) / (1 << 20):.2f} MiB/s ({(length / (end - begin)) / (1 << 17):.2f} Mb/s)")
            begin = time.time()
            await self.recv_res(pixel_count, stream, output_mode)
            end = time.time()
            print(f"recv: {(pixel_count*2 / (end - begin)) / (1 << 20):.2f} MiB/s ({(length / (end - begin)) / (1 << 17):.2f} Mb/s)")



class VectorPixelRunCommand(StreamCommand):
    def __init__(self, *, pattern_generator):
        self._pattern_generator = pattern_generator

    def __repr__(self):
        return f"VectorPixelRunCommand({self._pattern_generator})"
    
    def _iter_chunks(self):
        commands = bytearray()
        pixel_count = 0
        total_dwell  = 0
        latency = yield
        for x_coord, y_coord, dwell in self._pattern_generator:
            pixel_count += 1
            total_dwell += dwell
            commands.extend(VectorPixelCommand(x_coord = x_coord, y_coord=y_coord, dwell=dwell))
            if total_dwell >= latency: #or pixel_count > 0xffff :
                latency = yield commands, pixel_count, total_dwell
                commands = bytearray()
                pixel_count = 0
                total_dwell = 0
        print("iter_chunks: reached end of pattern generator")
        if not pixel_count == 0:
            print(f"iter_chunks: remaining {pixel_count=}")
            yield commands, pixel_count, total_dwell
    
    def _iter_latency_send(self, latency:int):
        MINIMUM = 131072
        while True:
            while latency > MINIMUM:
                yield MINIMUM
                latency -= MINIMUM
            yield latency
    
    def _iter_latency_recv(self, latency:int):
        MINIMUM = 16384*2
        while True:
            while latency > MINIMUM:
                yield MINIMUM
                latency -= MINIMUM
            yield latency



    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream, latency: int, dead_band: int, output_mode:OutputMode=OutputMode.SixteenBit):
        # DEAD_BAND = int(min(16384, int(latency)/8))
        HIGH_WATER_MARK = latency + dead_band
        LOW_WATER_MARK = max(0,latency - dead_band)
        # HIGH_WATER_MARK = dead_band
        # LOW_WATER_MARK = dead_band

        latency_in_flight = 0
        pixels_in_flight = 0
        drain_fut = asyncio.Future()
        fill_fut = asyncio.Future()

        async def sender(abort_latency):
            nonlocal latency_in_flight, pixels_in_flight, fill_fut
            iter_chunks = self._iter_chunks()
            iter_chunks.send(None)
            iter_latency = self._iter_latency_send(abort_latency)
            while True:
                try:
                    if latency_in_flight >= HIGH_WATER_MARK: # & pixels_in_flight > 16384:
                        print(f"sender: {latency_in_flight=} >= {HIGH_WATER_MARK=}, waiting for drain")
                        stream.send(FlushCommand().message)
                        fill_fut.set_result(None)
                        fill_fut = asyncio.Future()
                        await stream.flush()
                        await drain_fut
                    latency = next(iter_latency)
                    # latency = HIGH_WATER_MARK - latency_in_flight
                    print(f"sender: sending {latency=} to iter_chunks")
                    commands, pixel_count, total_dwell = iter_chunks.send(latency)
                    print(f"sender: got {len(commands)=}, {pixel_count=} from iter_chunks")
                    stream.send(commands)
                    latency_in_flight += total_dwell
                    pixels_in_flight += pixel_count
                    self._logger.debug(f"sender: {latency_in_flight=}, {pixels_in_flight=}")
                    await asyncio.sleep(0)
                    # if latency_in_flight >= LOW_WATER_MARK:
                    #     print(f"sender: {latency_in_flight=} >= {LOW_WATER_MARK=}, setting fill")
                        
                    
                except StopIteration:
                    stream.send(struct.pack(">B", CommandType.Flush))
                    await stream.flush()
                    fill_fut.set_result(None)
                    break

        asyncio.create_task(sender(latency))

        iter_chunks_r = self._iter_chunks() ## be sure it's not the same as iter_chunks() in sender()
        iter_chunks_r.send(None)
        iter_latency_r = self._iter_latency_recv(latency)
        if latency_in_flight <= HIGH_WATER_MARK: #fill up the pipeline!
            print(f"recver: {latency_in_flight=} <= {LOW_WATER_MARK=}, waiting for initial fill")
            await fill_fut
        while True:
            try:
                if latency_in_flight <= LOW_WATER_MARK:
                    drain_fut.set_result(None)
                    drain_fut = asyncio.Future()
                if latency_in_flight <= 0:
                    print(f"recver: {latency_in_flight=} <= 0, waiting for fill")
                    await fill_fut
                # latency = latency_in_flight - LOW_WATER_MARK
                latency = next(iter_latency_r)
                latency = min(latency,latency_in_flight)
                print(f"recver: sending {latency=} to iter_chunk")
                commands, pixel_count, total_dwell = iter_chunks_r.send(latency)
                print(f"recver: got {len(commands)=}, {pixel_count=}")
                latency_in_flight -= total_dwell
                pixels_in_flight -= pixel_count
                print(f"recver: {latency_in_flight=}, {pixels_in_flight=}")
                yield await self.recv_res(pixel_count, stream, output_mode)
                # if latency_in_flight < HIGH_WATER_MARK:
                #     print(f"recver: {latency_in_flight=} < {HIGH_WATER_MARK=}, setting drain")
                    
                
            except StopIteration:
                print(f"recver: StopIteration")
                break


class RasterStreamCommand(StreamCommand):
    def __init__(self, *, cookie: int, x_range: DACCodeRange, y_range: DACCodeRange, dwells: list[DwellTime]):
        assert (x_range.count * y_range.count) % len(dwells) == 0, \
            "Pixel count not multiple of raster scan point count"

        self._cookie  = cookie
        self._x_range = x_range
        self._y_range = y_range
        self._dwells  = dwells

    def __repr__(self):
        return f"RasterStreamCommand(cookie={self._cookie}, x_range={self._x_range}, y_range={self._y_range}, dwells=<list of {len(self._dwells)}>)"

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream, latency: int, output_mode: OutputMode=OutputMode.SixteenBit):
        await StreamSynchronizeCommand(cookie=self._cookie, raster_mode=True, output_mode = output_mode).transfer(stream)
        await StreamRasterRegionCommand(x_range=self._x_range, y_range=self._y_range).transfer(stream)
        total, done = self._x_range.count * self._y_range.count, 0
        async for chunk in StreamRasterPixelsCommand(dwells=self._dwells).transfer(stream, latency=latency, output_mode=output_mode):
            yield chunk
            #done += len(chunk)
            #self._logger.debug(f"total={total} done={done}")
        await stream.flush()


class RasterScanCommand(StreamCommand):
    def __init__(self, *, cookie: int, x_range: DACCodeRange, y_range: DACCodeRange, dwell: DwellTime):
        self._cookie  = cookie
        self._x_range = x_range
        self._y_range = y_range
        self._dwell   = dwell

    def __repr__(self):
        return f"RasterScanCommand(cookie={self._cookie}, x_range={self._x_range}, y_range={self._y_range}, dwell={self._dwell}>)"

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream, latency: int):
        await StreamSynchronizeCommand(cookie=self._cookie, raster=True).transfer(stream)
        await StreamRasterRegionCommand(x_range=self._x_range, y_range=self._y_range).transfer(stream)
        total, done = self._x_range.count * self._y_range.count, 0
        async for chunk in StreamRasterPixelRunCommand(dwell=self._dwell, length=total).transfer(stream, latency):
            yield chunk
            done += len(chunk)
            self._logger.debug(f"{total=} {done=}")


class RasterFreeScanCommand(StreamCommand):
    def __init__(self, *, cookie: int, x_range: DACCodeRange, y_range: DACCodeRange, dwell: DwellTime, interrupt: asyncio.Event):
        self._cookie  = cookie
        self._x_range = x_range
        self._y_range = y_range
        self._dwell   = dwell
        self._interrupt = interrupt

    def __repr__(self):
        return f"RasterFreeScanCommand(cookie={self._cookie}, x_range={self._x_range}, y_range={self._y_range}, dwell={self._dwell}>)"

    @StreamCommand.log_transfer
    async def transfer(self, stream: Stream, latency: int):
        await StreamSynchronizeCommand(cookie=self._cookie, raster_mode=True).transfer(stream)
        await StreamRasterRegionCommand(x_range=self._x_range, y_range=self._y_range).transfer(stream)
        count = 0
        async for chunk in StreamRasterPixelFreeRunCommand(dwell=self._dwell, interrupt=self._interrupt).transfer(stream, latency):
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
