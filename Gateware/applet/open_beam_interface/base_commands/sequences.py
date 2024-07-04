from . import *

import itertools
import asyncio
import array

class VectorPixelArray(BaseCommand):
    def __init__(self, *, points):
        self.dwells = itertools.batched(points, 3)
    def __iter__(self):
        return self
    def _iter_chunks(self, latency=65536):
        commands = bytearray()

        def append_command(chunk):
            if len(chunk)==3:
                x_coord, y_coord, dwell_time = chunk
                cmd = VectorPixelCommand(x_coord = x_coord, y_coord=y_coord, dwell_time=dwell_time)
                commands.extend(bytes(cmd))
            else:
                cmd = ArrayCommand(cmdtype = CmdType.VectorPixel, array_length=len(chunk)//3)
                commands.extend(bytes(cmd))
                if not BIG_ENDIAN: # there is no `array.array('>H')`
                    chunk.byteswap()
                commands.extend(chunk.tobytes())
        
        chunk = array.array('H')
        pixel_count = 0
        total_dwell = 0
        for x, y, dwell in self.points:
            chunk.extend(array.array("H", [x, y, dwell]))
            pixel_count += 1
            total_dwell += dwell
            if len(chunk) == 0xffff or total_dwell >= latency:
                append_command(chunk)
                del chunk[:] # clear
            if total_dwell >= latency:
                yield(commands, pixel_count)
                commands = bytearray()
                pixel_count = 0
                total_dwell = 0
        if chunk:
            append_command(chunk)
            yield (commands, pixel_count)




#### start macro commands

# Scan Selector board uses TE 1462051-2 Relay
# Switching delay is 20 ms
RELAY_DELAY_CYCLES = int(20 * pow(10, -6) / (1/(48 * pow(10,6))))
class RelayExternalCtrlCommand(BaseCommand):
    def __init__(self, enable, beam_type):
        assert enable <= 1
        self._enable = enable
        self._beam_type = beam_type

    def __repr__(self):
        return f"RelayExternalCtrlCommand(enable={self._enable}, beam_type={self._beam_type})"

    @BaseCommand.log_transfer
    async def transfer(self, stream):
        await BlankCommand(enable=(1-self._enable), inline=True).transfer(stream)
        await ExternalCtrlCommand(enable=self._enable).transfer(stream)
        await BeamSelectCommand(beam_type=self._beam_type).transfer(stream)
        await DelayCommand(delay=RELAY_DELAY_CYCLES).transfer(stream)
        await stream.flush()



class RasterScanCommand(BaseCommand):
    def __init__(self, *, cookie: int, x_range: DACCodeRange, y_range: DACCodeRange, dwell: int):
        self._cookie  = cookie
        self._x_range = x_range
        self._y_range = y_range
        self._dwell   = dwell

    def __repr__(self):
        return f"RasterScanCommand(cookie={self._cookie}, x_range={self._x_range}, y_range={self._y_range}, dwell={self._dwell}>)"

    def pack(self):
        all_commands = bytearray()
        for commands, pixel_count in self._iter_chunks():
            all_commands.extend(commands)
        return bytes(all_commands)

    def _iter_chunks(self, latency=65536*65536):
        commands = bytearray()

        def append_command(pixel_count):
            array_count = pixel_count//65536
            remainder_pixel_count = pixel_count%65536
            assert array_count < 65536, "can't handle more than 65536x65536 points"
            print(f"{array_count=}, {remainder_pixel_count=}")
            if array_count > 0:
                commands.extend(bytes(ArrayCommand(cmdtype=CmdType.RasterPixelRun, array_length=array_count)))
                chunk = array.array('H', [self._dwell]*array_count)
                if not BIG_ENDIAN: # there is no `array.array('>H')`
                    chunk.byteswap()
                commands.extend(chunk.tobytes())
            if remainder_pixel_count > 0:
                commands.extend(bytes(RasterPixelRunCommand(dwell_time = self._dwell, length = remainder_pixel_count)))

        pixel_count = 0
        total_dwell = 0
        for _ in range(self._x_range.count * self._y_range.count):
            pixel_count += 1
            total_dwell += self._dwell
            if total_dwell >= latency:
                append_command(pixel_count)
                yield(commands, pixel_count)
                commands = bytearray()
                pixel_count = 0
                total_dwell = 0
        if pixel_count > 0:
            append_command(pixel_count)
            yield(commands, pixel_count)
    
    @BaseCommand.log_transfer
    async def transfer(self, stream, latency: int, output_mode:OutputMode=OutputMode.SixteenBit):
        MAX_PIPELINE = 32

        tokens = MAX_PIPELINE
        token_fut = asyncio.Future()

        async def sender():
            nonlocal tokens
            for commands, pixel_count in self._iter_chunks(latency):
                self._logger.debug(f"sender: tokens={tokens}")
                if tokens == 0:
                    await FlushCommand().transfer(stream)
                    await token_fut
                await stream.write(commands)
                tokens -= 1
                await asyncio.sleep(0)
            await FlushCommand().transfer(stream)

        await SynchronizeCommand(cookie=self._cookie, raster=True, output = output_mode).transfer(stream)
        await RasterRegionCommand(x_range=self._x_range, y_range=self._y_range).transfer(stream)
        asyncio.create_task(sender())

        for commands, pixel_count in self._iter_chunks(latency):
            tokens += 1
            if tokens == 1:
                token_fut.set_result(None)
                token_fut = asyncio.Future()
            self._logger.debug(f"recver: tokens={tokens}")
            yield await self.recv_res(pixel_count, stream, output_mode)


class RasterPatternCommand(BaseCommand):
    def __init__(self, *, cookie: int, x_range: DACCodeRange, y_range: DACCodeRange, dwells: list):
        self._cookie  = cookie
        self._x_range = x_range
        self._y_range = y_range
        self.dwells   = dwells
    def __bytes__(self):
        all_commands = bytearray()
        for commands, pixel_count in self._iter_chunks():
            all_commands.extend(commands)
        return bytes(all_commands)

    def _iter_chunks(self, latency=65536*65536):
        commands = bytearray()

        def append_command(chunk):
            cmd = ArrayCommand(cmdtype = CmdType.RasterPixel, array_length=len(chunk))
            commands.extend(bytes(cmd))
            if not BIG_ENDIAN: # there is no `array.array('>H')`
                chunk.byteswap()
            commands.extend(chunk.tobytes())

        chunk = array.array('H')
        pixel_count = 0
        total_dwell = 0
        for pixel in self.dwells:
            chunk.append(pixel)
            pixel_count += 1
            total_dwell += pixel
            if len(chunk) == 0xffff or total_dwell >= latency:
                append_command(chunk)
                del chunk[:] # clear
            if total_dwell >= latency:
                yield (commands, pixel_count)
                commands = bytearray()
                pixel_count = 0
                total_dwell = 0
        if chunk:
            append_command(chunk)
            yield (commands, pixel_count)

    @BaseCommand.log_transfer
    async def transfer(self, stream, latency: int, output_mode:OutputMode=OutputMode.SixteenBit):
        MAX_PIPELINE = 32

        tokens = MAX_PIPELINE
        token_fut = asyncio.Future()

        async def sender():
            nonlocal tokens
            for commands, pixel_count in self._iter_chunks(latency):
                self._logger.debug(f"sender: tokens={tokens}")
                if tokens == 0:
                    await FlushCommand().transfer(stream)
                    await token_fut
                await stream.write(commands)
                tokens -= 1
                await asyncio.sleep(0)
            await FlushCommand().transfer(stream)

        await SynchronizeCommand(cookie=self._cookie, raster=True, output = output_mode).transfer(stream)
        await RasterRegionCommand(x_range=self._x_range, y_range=self._y_range).transfer(stream)
        asyncio.create_task(sender())

        for commands, pixel_count in self._iter_chunks(latency):
            tokens += 1
            if tokens == 1:
                token_fut.set_result(None)
                token_fut = asyncio.Future()
            self._logger.debug(f"recver: tokens={tokens}")
            yield await self.recv_res(pixel_count, stream, output_mode)

class CommandSequence:
    """A sequence of commands
    """
    def __init__(self, *, sync:bool=True, cookie: int=123, output: OutputMode=OutputMode.SixteenBit, raster:bool=False,
                verbose:bool=False):
        self._bytes = bytearray()
        self._output = output
        self._raster = raster
        self.verbose = verbose
        if sync:
            self.add(SynchronizeCommand(cookie=cookie, output=output, raster=raster))
    def add(self, other, verbose:bool=False):
        """
        Parameters
        ----------
        other
        verbose
        """
        if self.verbose | verbose:
            print(f"adding {other!r}")
        try:
            self._bytes.extend(bytes(other))
        except TypeError:
            raise TypeError("Command syntax error. Did you use 'command' instead of 'command()'?")
        #self._response.extend(other.response)
    def __bytes__(self):
        return bytes(self._bytes)
    def __len__(self):
        return len(bytes(self))