from abc import abstractmethod, ABCMeta
import asyncio
import random
import struct

import logging
logger = logging.getLogger()
from . import *


class TransferError(Exception):
    pass

class Stream(metaclass = ABCMeta):
    _logger = logger.getChild("Stream")
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
    async def readuntil(self, separator=b'\n', *, flush=True, max_count=False) -> memoryview:
        ...
    # @abstractmethod
    # async def xchg(self, data: bytes | bytearray | memoryview, *, recv_length: int) -> bytes:
    #     ...
