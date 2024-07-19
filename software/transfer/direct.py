
from stream import Stream, Connection

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
        self._stream = stream
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
        cmd.extend(bytes(SynchronizeCommand(raster=True, output=OutputMode.SixteenBit, cookie=cookie)))
        cmd.extend(bytes(FlushCommand()))
        await self._stream.write(cmd)
        await self._stream.flush()
        res = struct.pack(">HH", 0xffff, cookie)
        data = await self._stream.readuntil(res)
        #data = await self.stream.read(4)
        print(str(list(data)))

    async def transfer(self, command, flush:bool = False, **kwargs):
        self._logger.debug(f"transfer {command!r}")
        try:
            await self._synchronize() # may raise asyncio.IncompleteReadError")
            return await command.transfer(self._stream, **kwargs)
        except asyncio.IncompleteReadError as e:
            self._handle_incomplete_read(e)

    async def transfer_multiple(self, command, **kwargs):
        self._logger.debug(f"transfer multiple {command!r}")
        try:
            await self._synchronize() # may raise asyncio.IncompleteReadError
            self._logger.debug(f"synchronize transfer_multiple")
            async for value in command.transfer(self._stream, **kwargs):
                yield value
                self._logger.debug(f"yield transfer_multiple")
        except asyncio.IncompleteReadError as e:
            self._handle_incomplete_read(e)