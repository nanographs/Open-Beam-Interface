import logging
logger = logging.getLogger()

from .stream import Connection, Stream
from .support import dump_hex

class MockStream(Stream):
    _logger = logger.getChild("Stream")

    async def write(self, data: bytes | bytearray | memoryview):
        self._logger.debug(f"write {dump_hex(data)}")

    async def flush(self):
        pass

    async def read(self, length: int) -> memoryview:
        return memoryview(bytes([0]*length))

    async def readuntil(self, separator=b'\n', *, flush=True, max_count=False) -> memoryview:
        return separator

class MockConnection(Connection):
    _logger = logger.getChild("Connection")
    
    async def _synchronize(self):
        pass
    
    async def _connect(self):
        assert not self.connected
        self._stream = MockStream()


