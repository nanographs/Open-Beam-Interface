from abc import abstractmethod, ABCMeta
import asyncio

import logging
logger = logging.getLogger()

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
    async def readuntil(self, sep:bytes) -> memoryview:
        ...

class TransferError(Exception):
    pass


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

    async def xchg(self, data: bytes | bytearray | memoryview, *, recv_length: int) -> bytes:
        await self.send(data)
        return await self.recv(recv_length)


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




class OBIInterface:
    def __init__(self, iface):
        self._synchronized = False
        self._next_cookie = random.randrange(0, 0x10000, 2) # even cookies only
        self.lower = iface
    
    @property
    def synchronized(self):
        """`True` if the instrument is ready to accept commands, `False` otherwise."""
        return self._synchronized
    
    async def _synchronize(self):
        print("synchronizing")
        if self.synchronized:
            print("already synced")
            return

        print("not synced")
        cookie, self._next_cookie = self._next_cookie, (self._next_cookie + 2) & 0xffff # even cookie
        #self._logger.debug(f'synchronizing with cookie {cookie:#06x}')
        print("synchronizing with cookie")

        cmd = struct.pack(">BHBB",
            CommandType.Synchronize, cookie, 0,
            CommandType.Flush)
        await self.lower.write(cmd)
        await self.lower.flush()
        res = struct.pack(">HH", 0xffff, cookie)
        data = await self.readuntil(res)
        print(str(list(data)))
    
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
    
    async def transfer(self, seq): #CommandSequence
        #await self._synchronize()
        await self.lower.write(seq.message)
        await self.lower.flush()
        data = await self.lower.read(seq._response_length)
        return seq.unpack(data)
    
    async def read(self, length):
        return await self.lower.read(length)
    
    async def write(self, data):
        await self.lower.write(data)


@dataclass
class LinearRegion:
    pos: int
    size: int

class FrameContext:
    def __init__(self, x_pixels: int, y_pixels: int, x_roi:LinearRegion=None, y_roi:LinearRegion=None,
                bit_mode:OutputMode = OutputMode.SixteenBit):
        assert x_pixels <= 16384
        assert y_pixels <= 16384
        if x_roi == None:
            x_roi = LinearRegion(0, x_pixels)
        if y_roi == None:
            y_roi = LinearRegion(0, y_pixels)
        self.x_pixels = x_pixels
        self.y_pixels = y_pixels
        self._stepsize = (16384/max(self.x_pixels, self.y_pixels))
        self._step = int(self._stepsize*256)
        assert self._step <= 65535
        self.x_roi = x_roi
        self.y_roi = y_roi
        self.y_ptr = 0
        self.bit_mode = bit_mode
        if bit_mode == OutputMode.SixteenBit:
            self._pixbuffer = array.array('H')
            self.np_dtype = np.uint16
            self.canvas = np.zeros(shape = self.np_shape, dtype = self.np_dtype)
        if bit_mode == OutputMode.EightBit:
            self._pixbuffer = array.array('B')
            self.np_dtype = np.uint8
            self.canvas = np.zeros(shape = self.np_shape, dtype = self.np_dtype)
    
    def _convert_range(self, loi: LinearRegion):
        return DACCodeRange(start = int(loi.pos*self._stepsize), count = loi.size, step = self._step)

    @property
    def ranges(self):
        x_range = self._convert_range(self.x_roi)
        y_range = self._convert_range(self.y_roi)
        return x_range, y_range
    
    @property
    def pixels(self):
        return self.x_pixels * self.y_pixels

    @property
    def np_shape(self):
        return self.y_pixels, self.x_pixels
    
    def insert_data(self, data:bytes):
        print("insert into pixbuffer")
        self._pixbuffer.extend(data)
        #self.process()
    
    def process(self):
        print(f"process. {len(self._pixbuffer)=}, {self.pixels=}, {self.x_pixels=}")
        while len(self._pixbuffer) >= self.pixels:
            pixels = self._pixbuffer[:self.pixels] 
            self._pixbuffer = self._pixbuffer[self.pixels:]
            self.fill(pixels)
        if len(self._pixbuffer) >= self.x_pixels:
            y_lines = len(self._pixbuffer)//self.x_pixels
            pixels = self._pixbuffer[:self.x_pixels*y_lines]
            self._pixbuffer = self._pixbuffer[self.x_pixels*y_lines:]
            self.fill_lines(pixels, y_lines)
        if len(self._pixbuffer) > 0:
            pass #ignore partial lines for now...

    
    def fill(self, pixels: array.array):
        print("filled full frame")
        assert len(pixels) == self.pixels, f"expected {self.pixels}, got {len(pixels)}"
        self.canvas = np.array(pixels, dtype = np.uint16).reshape(self.np_shape)
    
    def fill_lines(self, pixels: array.array, fill_y_lines:int):
        assert fill_y_lines == len(pixels)/self.x_pixels
        if self.y_ptr + fill_y_lines <= self.y_pixels:
            self.canvas[self.y_ptr:self.y_ptr + fill_y_lines] = np.array(pixels, dtype = self.np_dtype).reshape(fill_y_lines, self.x_pixels)
            self.y_ptr += fill_y_lines
            if self.y_ptr == self.y_pixels:
                print("Rolling over")
                self.y_ptr == 0
        elif self.y_ptr + fill_y_lines > self.y_pixels:
            print(f"{self.y_ptr} + {fill_y_lines} > {self.y_pixels}")
            remaining_lines = self.y_pixels - self.y_ptr
            remaining_pixel_count = remaining_lines*self.x_pixels
            remaining_pixels = pixels[:remaining_pixel_count]
            print(f"{remaining_lines=}")
            self.canvas[self.y_ptr:self.y_pixels] = np.array(remaining_pixels, dtype = self.np_dtype).reshape(remaining_lines, self.x_pixels)
            rewrite_lines = fill_y_lines - remaining_lines
            rewrite_pixels = pixels[remaining_pixel_count:]
            print(f"{rewrite_lines=}")
            self.canvas[:rewrite_lines] = np.array(rewrite_pixels, dtype = self.np_dtype).reshape(rewrite_lines, self.x_pixels)
            self.y_ptr = rewrite_lines
        print(f"ending with {self.y_ptr=}")

class RollingContext:
    SEP = b'\xff\xff\xff\xff'
    config_match = re.compile(b'\xff{2}.{2}\xff{2}', flags=re.DOTALL)

    def __init__(self):
        self._context_dict = {}
        self._current_context = None
        self._next_cookie = random.randrange(0, 0x10000, 2) # even cookies only
        self._search_buffer = bytearray() # holds a max of 5 bytes
    def get_next_cookie(self):
        cookie, self._next_cookie = self._next_cookie, (self._next_cookie + 2) & 0xffff # even cookie
        return cookie
    def extend_context(self, context):
        cookie = self.get_next_cookie()
        self._context_dict.update({cookie:context})
        return cookie
    def get_context(self, cookie):
        try:
            return self._context_dict.pop(cookie)
        except:
            return None
    def process_with_context(self, data:bytes, context):
        print(f"processing with {context=}")
        if not context==None:
            context.insert_data(data)
            context.process()
    def extract_context_and_process(self, data: memoryview):
        print("processing data")
        isep = 0
        if len(self._search_buffer) > 0:
            data = self._search_buffer + bytes(data)
        else: 
            data = bytes(data)
        n = re.finditer(self.config_match, data)
        prev_stop = 0
        prev_context = None
        while True:
            try:
                match = next(n)
                start, stop = match.span()
                cookie = match.group()[2:4]
                cookie = struct.unpack('>H', cookie)[0]
                print(f"found {cookie=}, {type(cookie)=}")
                self._current_context, prev_context = self.get_context(cookie), self._current_context
                self.process_with_context(data[prev_stop:start], prev_context)
                prev_stop = stop
            except StopIteration:
                d = data[prev_stop:]
                self.process_with_context(data[prev_stop:], self._current_context)
                if prev_stop < (len(data) - 6):
                    self._search_buffer.extend(data[len(data)-5:])
                break


class StreamingFrameContext(FrameContext):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    def command(self, cookie):
        seq = CommandSequence(output=self.bit_mode, raster=True, cookie=cookie)
        x_range, y_range = self.ranges
        seq.add(RasterRegionCommand(x_range = x_range, y_range = y_range))
        seq.add(RasterPixelFreeRunCommand(dwell = 2))
        return seq.message


class StreamWheel:
    MAX_CHUNK = 16384
    def __init__(self, conn):
        self.conn = conn
        self.cm = RollingContext()
        self.inject_pending = asyncio.Event()
        self._write_buffer = bytearray()
    def request_new_context(self, context):
        cookie = self.cm.extend_context(context)
        print(f"requested context, got {cookie=}")
        self.request_inject(context.command(cookie))
    def request_inject(self, data):
        self._write_buffer.extend(data)
        self.inject_pending.set()
    async def inject(self):
        if len(self._write_buffer) >= self.MAX_CHUNK:
            print("writing..")
            await self.conn.write(self._write_buffer[:self.MAX_CHUNK])
            print(f"wrote {self.MAX_CHUNK} bytes")
            self._write_buffer = self._write_buffer[self.MAX_CHUNK:]
        else:
            print("writing...")
            await self.conn.write(self._write_buffer)
            print(f"wrote {len(self._write_buffer)} bytes: {self._write_buffer}")
            self._write_buffer = bytearray()
            self.inject_pending.clear()
    async def turn(self):
        while True:
            if self.inject_pending.is_set():
                print("inject_pending is set")
                await self.inject()
            print("reading")
            data = await self.conn.read(self.MAX_CHUNK)
            print(f"read {len(data)} bytes")
            self.cm.extract_context_and_process(data)


