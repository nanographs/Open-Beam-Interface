import asyncio
import struct

from obi.commands import *

BIG_ENDIAN = (struct.pack('@H', 0x1234) == struct.pack('>H', 0x1234))

class RasterScanCommand(BaseCommand):
    def __init__(self, x_range: DACCodeRange, y_range: DACCodeRange, dwell_time:DwellTime, cookie: u16,
        output_mode:OutputMode=OutputMode.SixteenBit, frame_blank=True):
        """
        Scan a frame and return data using a combination of :class:`RasterRegionCommand` and :class:`RasterPixelRunCommand`.

        Args:
            x_range (DACCodeRange): 
            y_range (DACCodeRange):
            dwell_time (DwellTime): 
            cookie (u16):
            output_mode (OutputMode, optional): Defaults to OutputMode.SixteenBit.
            frame_blank (bool, optional): Start frame from a blanked state and return to a blanked state. Defaults to True.
        """
        self._x_range = x_range
        self._y_range = y_range
        self._dwell = dwell_time
        self._cookie = cookie
        self._output_mode = output_mode
        self.frame_blank = frame_blank
        self.abort = asyncio.Event()
    
    def __repr__(self):
        return f"RasterScanCommand: x_range={self._x_range}, y_range={self._y_range}, \
                dwell={self._dwell}, cookie={self._cookie}, output_mode={self._output_mode}"
    def _iter_chunks(self, latency):
        commands = bytearray()

        def append_command(pixel_count):
            while pixel_count > 65536:
                cmd = RasterPixelRunCommand(dwell_time = self._dwell, length=65535)
                commands.extend(bytes(cmd))
                pixel_count -= 65536
            cmd = RasterPixelRunCommand(dwell_time = self._dwell, length=pixel_count-1)
            commands.extend(bytes(cmd))

        pixel_count = 0
        total_dwell = 0
        for n in range(self._x_range.count * self._y_range.count):
            pixel_count += 1
            total_dwell += self._dwell
            if total_dwell >= latency:
                append_command(pixel_count)
                ## blank at the end of the last pixel
                if self.frame_blank and n + 1 == self._x_range.count * self._y_range.count:
                    commands.extend(bytes(BlankCommand(enable=True, inline=False)))
                yield(commands, pixel_count)
                commands = bytearray()
                pixel_count = 0
                total_dwell = 0

        if pixel_count > 0:
            append_command(pixel_count)
            yield(commands, pixel_count)

    @BaseCommand.log_transfer
    async def transfer(self, stream, *, latency:int=65536*65536):
        self._logger.debug(f"transfer - {latency=}")
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
                if self.frame_blank and self.abort.is_set():
                    ## go to a blanked state after an aborted frame
                    commands.extend(bytes(BlankCommand(enable=True, inline=False)))
                await stream.write(commands)
                tokens -= 1
                if self.abort.is_set():
                    break
                await asyncio.sleep(0)
            await FlushCommand().transfer(stream)

        await SynchronizeCommand(cookie=self._cookie, raster=True, output = self._output_mode).transfer(stream)
        await RasterRegionCommand(x_range=self._x_range, y_range=self._y_range).transfer(stream)
        asyncio.create_task(sender())

        cookie = await stream.read(4) #just assume these are exactly FFFF + cookie, and discard them
        ## TODO: assert against synchronization result
        for commands, pixel_count in self._iter_chunks(latency):
            tokens += 1
            if tokens == 1:
                token_fut.set_result(None)
                token_fut = asyncio.Future()
            if tokens == MAX_PIPELINE + 1:
                if self.abort.is_set():
                    break
            self._logger.debug(f"recver: tokens={tokens}")
            yield await self.recv_res(pixel_count, stream, self._output_mode)
        ## fly back
        # await VectorPixelCommand(x_coord=self._x_range.start, y_coord=self._y_range.start, dwell_time=1).transfer(stream)



