from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
import asyncio
import enum
import struct
import array
from collections import deque
import random
import re
import numpy as np



class CommandType(enum.IntEnum):
    Synchronize         = 0x00
    Abort               = 0x01
    Flush               = 0x02
    Delay               = 0x03
    EnableExtCtrl       = 0x04
    DisableExtCtrl      = 0x05
    SelectEbeam         = 0x06
    SelectIbeam         = 0x07
    SelectNoBeam        = 0x08
    Blank               = 0x09
    BlankInline         = 0x0a
    Unblank             = 0x0b
    UnblankInline       = 0x0d

    RasterRegion        = 0x10
    RasterPixel         = 0x11
    RasterPixelRun      = 0x12
    RasterPixelFreeRun  = 0x13
    VectorPixel         = 0x14
    VectorPixelMinDwell = 0x15

class OutputMode(enum.IntEnum):
    SixteenBit          = 0
    EightBit            = 1
    NoOutput            = 2

class BeamType(enum.IntEnum):
    NoBeam              = 0
    Electron            = 1
    Ion                 = 2

@dataclass
class DACCodeRange:
    start: int # UQ(14,0)
    count: int # UQ(14,0)
    step:  int # UQ(8,8)

class DwellTime(int):
    '''Dwell time is measured in units of ADC cycles.
        One DwellTime = 125 ns'''
    pass

class DelayTime(int):
    '''Delay time is measured in units of 48 MHz clock cycles.
        One DelayTime = 20.833 ns'''
    pass


class BaseCommand(metaclass=ABCMeta):
    # def __init_subclass__(cls):
    #     cls._logger = logger.getChild(f"Command.{cls.__name__}")

    @property
    @abstractmethod
    def message(self):
        ...
    
    # @property
    # def response(self):
    #     return 0

class BaseResponse:
    def __init__(self, name, length):
        self.name = name
        self.length = length
    def __repr__(self):
        return f"Response: {self.name} with length {self.length}"

class ResponseCollection():
    _responses = deque()
    _length = 0
    def __init__(self, responses:dict={}):
        for name, length in responses.items():
            print(f"adding {name}, {length}")
            self._responses.append(BaseResponse(name, length))
            self._length  += length

class SynchronizeCommand(BaseCommand):
    def __init__(self, *, cookie: int, raster: bool, output: OutputMode=OutputMode.SixteenBit):
        self._cookie = cookie
        self._raster_mode = raster
        self._output_mode = output

    def __repr__(self):
        return f"SynchronizeCommand(cookie={self._cookie}, raster_mode={self._raster_mode}, output_mode={self._output_mode})"

    @property
    def message(self):
        combined = int(self._output_mode<<1 | self._raster_mode)
        return struct.pack(">BHB", CommandType.Synchronize, self._cookie, combined)

    def response(self, *, output_mode):
        return ResponseCollection({
            "sync": 2,
            "cookie": 2
        })

class AbortCommand(BaseCommand):
    def __repr__(self):
        return f"AbortCommand"
    
    @property
    def message(self):
        return struct.pack(">B", CommandType.Abort)

class FlushCommand(BaseCommand):
    def __repr__(self):
        return f"FlushCommand"
    
    @property
    def message(self):
        return struct.pack(">B", CommandType.Flush)
    

class DelayCommand(BaseCommand):
    def __init__(self, delay:DelayTime):
        assert delay <= 65535
        self._delay = delay

    def __repr__(self):
        return f"DelayCommand(delay={self._delay})"

    @property
    def message(self):
        return struct.pack(">BH", CommandType.Delay, self._delay)
    

class BlankCommand(BaseCommand):
    def __init__(self, enable:bool=True, inline: bool=False):
        self._enable = enable
        self._inline = inline

    def __repr__(self):
        return f"BlankCommand(enable={self._enable}, inline={self._inline})"

    @property
    def message(self):
        #combined = int(self._inline<<1 | self._enable)
        #return struct.pack(">BB", CommandType.Blank, combined)
        if self._enable and not self._inline:
            return struct.pack('>B', CommandType.Blank)
        elif self._enable and self._inline:
            return struct.pack('>B', CommandType.BlankInline)
        elif not (self._enable and self._inline):
            return struct.pack('>B', CommandType.Unblank)
        elif not self._enable and self._inline:
            return struct.pack('>B', CommandType.UnblankInline)

class BlankInlineCommand(BaseCommand):
    def __repr__(self):
        return f"BlankInlineCommand"
    @property
    def message(self):
        return struct.pack('>B', CommandType.BlankInline)

class UnblankCommand(BaseCommand):
    def __repr__(self):
        return f"UnblankCommand"
    @property
    def message(self):
        return struct.pack('>B', CommandType.Unblank)

class UnblankInlineCommand(BaseCommand):
    def __repr__(self):
        return f"UnblankInlineCommand"
    @property
    def message(self):
        return struct.pack('>B', CommandType.UnblankInline)

class ExternalCtrlCommand(BaseCommand):
    def __init__(self, enable:bool):
        self._enable = enable

    def __repr__(self):
        return f"ExternalCtrlCommand(enable={self._enable})"

    @property
    def message(self):
        if self._enable:
            return struct.pack(">B", CommandType.EnableExtCtrl)
        if not self._enable:
            return struct.pack(">B", CommandType.DisableExtCtrl)

class EnableExtCtrlCommand(BaseCommand):
    @property
    def message(self):
        return struct.pack('>B', CommandType.EnableExtCtrl)

class DisableExtCtrlCommand(BaseCommand):
    @property
    def message(self):
        return struct.pack('>B', CommandType.DisableExtCtrl)

class SelectBeamCommand(BaseCommand):
    def __init__(self, beam_type:BeamType):
        self._beam_type = beam_type
    @property
    def message(self):
        if self._beam_type == BeamType.Electron:
            return struct.pack('>B', CommandType.SelectEbeam)
        elif self._beam_type == BeamType.Ion:
            return struct.pack('>B', CommandType.SelectIbeam)
        else:
            return struct.pack('>B', CommandType.SelectNoBeam)

class SelectEbeamCommand(BaseCommand):
    @property
    def message(self):
        return struct.pack('>B', CommandType.SelectEbeam)

class SelectIbeamCommand(BaseCommand):
    @property
    def message(self):
        return struct.pack('>B', CommandType.SelectIbeam)

class SelectNoBeamCommand(BaseCommand):
    @property
    def message(self):
        return struct.pack('>B', CommandType.SelectNoBeam)

class RasterRegionCommand(BaseCommand):
    def __init__(self, *, x_range: DACCodeRange, y_range: DACCodeRange):
        self._x_range = x_range
        self._y_range = y_range

    def __repr__(self):
        return f"RasterRegionCommand(x_range={self._x_range}, y_range={self._y_range})"

    @property
    def message(self):
        return struct.pack(">BHHHHHH", CommandType.RasterRegion,
            self._x_range.start, self._x_range.count, self._x_range.step,
            self._y_range.start, self._y_range.count, self._y_range.step)

class RasterPixelsCommand(BaseCommand):
    def __init__(self, *, dwells: list[DwellTime]):
        assert len(dwells) <= 65536
        self._pixel_count = len(dwells)
        self._dwells = array.array('H', dwells)
        
    def __repr__(self):
        return f"RasterPixelsCommand(dwells=<list of {self._pixel_count}>)"

    @property
    def message(self):
        commands = bytearray()
        commands.extend(struct.pack(">BH", CommandType.RasterPixels, self._pixel_count - 1))
        commands.extend(self._dwells)
        return commands
    
    def response(self, *, output_mode):
        return ResponseCollection({
            "RasterPixels": 2*self._pixel_count
        })

class RasterPixelRunCommand(BaseCommand):
    def __init__(self, *, dwell: DwellTime, length: int):
        assert dwell <= 65536
        assert length <= 65536, "Run length counter is 16 bits"
        self._dwell   = dwell
        self._length  = length

    def __repr__(self):
        return f"RasterPixelRunCommand(dwell={self._dwell}, length={self._length})"

    @property
    def message(self):
        return struct.pack(">BHH", CommandType.RasterPixelRun, self._length - 1, self._dwell)

class RasterPixelFreeRunCommand(BaseCommand):
    def __init__(self, *, dwell: DwellTime):
        assert dwell <= 65536
        self._dwell   = dwell

    def __repr__(self):
        return f"RasterPixelFreeRunCommand(dwell={self._dwell})"

    @property
    def message(self):
        return struct.pack(">BH", CommandType.RasterPixelFreeRun, self._dwell)

class VectorPixelCommand(BaseCommand):
    def __init__(self, *, x_coord: int, y_coord: int, dwell: DwellTime):
        assert x_coord <= 65535
        assert y_coord <= 65535
        assert dwell <= 65536
        self._x_coord = x_coord
        self._y_coord = y_coord
        self._dwell   = dwell

    def __repr__(self):
        return f"VectorPixelCommand(x_coord={self._x_coord}, y_coord={self._y_coord}, dwell={self._dwell})"

    @property
    def message(self):
        if self._dwell == 1:
            return struct.pack(">BHH", CommandType.VectorPixelMinDwell, self._x_coord, self._y_coord)
        else:
            return struct.pack(">BHHH", CommandType.VectorPixel, self._x_coord, self._y_coord, self._dwell-1)

class CommandSequence(BaseCommand):
    def __init__(self, output: OutputMode, raster:bool, cookie=345):
        self._message = bytearray()
        self._response = deque()
        self._response_length = 0
        self._output = output
        self._raster = raster
        self.add(SynchronizeCommand(cookie=cookie, output=output, raster=raster))
    def add(self, other: BaseCommand):
        #print(f"added {other!r}")
        self._message.extend(other.message)
        if self._output != OutputMode.NoOutput:
            if "response" in dir(other):
                res = other.response(output_mode=self._output)
                #self._response += res._responses
                while len(res._responses):
                    self._response.append(res._responses.popleft())
                self._response_length += res._length
        # print(f"{self._response=}")

    def unpack(self, data: bytes | bytearray | memoryview):
        while len(self._response) > 0:
            response = self._response.popleft()
            response_data = data[:response.length]
            print(f"{response.name}: {str(list(response_data))}")
            data = data[response.length:]
    
    @property
    def message(self):
        return self._message


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













