import asyncio
import struct
import array

from obi.commands import *

BIG_ENDIAN = (struct.pack('@H', 0x1234) == struct.pack('>H', 0x1234))

def default_iter():
    for x in range(2048):
        for y in range(2048):
            yield x, y, 1

class VectorScanCommand(BaseCommand):
    def __init__(self, cookie: int, output_mode:OutputMode=OutputMode.SixteenBit, iter_points=default_iter()):
        self._iter_points = iter_points
        self._processed_points = []
        self._processed = False
        self._cookie = cookie
        self._output_mode = output_mode
        self.abort = asyncio.Event()
    
    def __repr__(self):
        return f"VectorScanCommand: cookie={self._cookie}, output_mode={self._output_mode}"
    
    def _pre_process_chunks(self, latency):
        print("Pre-processing commands...")
        for commands, pixel_count in self._iter_chunks(latency):
            self._processed_points.append((commands,pixel_count))
        self._processed = True
        print("Done processing")

    def _iter_chunks(self, latency):
        if self._processed:
            for commands, pixel_count in self._processed_points:
                yield commands, pixel_count
        else:
            commands = bytearray()

            def get_command(pixel_count):
                nonlocal commands
                cmd = ArrayCommand(command=VectorPixelCommand.header(output_en=OutputEnable.Enabled), array_length=pixel_count-1)
                return bytes(cmd)
                
            pixel_count = 0
            total_dwell = 0
            for (x, y, dwell) in self._iter_points:
                pixel_count += 1
                total_dwell += dwell
                commands.extend(struct.pack(">HHH", x, y, dwell))
                if total_dwell >= latency:
                    cmd = get_command(pixel_count)
                    yield(memoryview(cmd + commands), pixel_count)
                    commands = bytearray()
                    pixel_count = 0
                    total_dwell = 0
                if pixel_count == 65536:
                    cmd = get_command(pixel_count)
                    yield(memoryview(cmd + commands), pixel_count)
                    commands = bytearray()
                    pixel_count = 0
                    total_dwell = 0

            if pixel_count > 0:
                cmd = get_command(pixel_count)
                yield(memoryview(cmd + commands), pixel_count)

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
                if self.abort.is_set():
                    ## go to a blanked state after an aborted frame
                    commands.extend(bytes(BlankCommand(enable=True, inline=False)))
                await stream.write(commands)
                tokens -= 1
                if self.abort.is_set():
                    break
                await asyncio.sleep(0)
            await FlushCommand().transfer(stream)

        await SynchronizeCommand(cookie=self._cookie, raster=False, output = self._output_mode).transfer(stream)
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

