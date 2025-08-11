import inspect
import array
from abc import ABCMeta, abstractmethod
import asyncio

import logging
logger = logging.getLogger()

import struct
BIG_ENDIAN = (struct.pack('@H', 0x1234) == struct.pack('>H', 0x1234))

__all__ = []
from .structs import CmdType, OutputMode, OutputEnable, BeamType, u14, u16, fp8_8, DwellTime, DACCodeRange
__all__ += ["CmdType", "OutputMode", "OutputEnable", "BeamType", "u14", "u16", "fp8_8", "DwellTime", "DACCodeRange"]

class BaseCommand(metaclass = ABCMeta):
    def __init_subclass__(cls):
        cls._logger = logger.getChild(f"Command.{cls.__name__}")

    @classmethod
    def log_transfer(cls, transfer):
        if inspect.isasyncgenfunction(transfer):
            async def wrapper(self, *args, **kwargs):
                repr_short = repr(self).replace(self.__class__.__name__, "cls")
                self._logger.debug(f"iter begin={repr_short}")
                async for chunk in transfer(self, *args, **kwargs):
                    if isinstance(chunk, list):
                        self._logger.debug(f"iter chunk=<list of {len(chunk)}>")
                    elif isinstance(chunk, array.array):
                        self._logger.debug(f"iter chunk=<array of {len(chunk)}>")
                    else:
                        self._logger.debug(f"iter chunk={chunk!r}")
                    yield chunk
                self._logger.debug(f"iter end={repr_short}")
        else:
            async def wrapper(self, *args, **kwargs):
                repr_short = repr(self).replace(self.__class__.__name__, "cls")
                self._logger.debug(f"begin={repr_short}")
                await transfer(self, *args, **kwargs)
                self._logger.debug(f"end={repr_short}")
        return wrapper

    @abstractmethod
    async def transfer(self, stream):
        ...

    async def recv_res(self, pixel_count, stream, output_mode:OutputMode):
        if output_mode == OutputMode.SixteenBit:
            self._logger.debug(f"waiting to receive {pixel_count} pixels, ({pixel_count*2} bytes)")
            res = array.array('H', bytes(await stream.read(pixel_count * 2)))
            if not BIG_ENDIAN:
                res.byteswap()
            await asyncio.sleep(0)
            return res
        if output_mode == OutputMode.EightBit:
            self._logger.debug(f"waiting to receive {pixel_count} pixels, ({pixel_count} bytes)")
            res = array.array('B', await stream.read(pixel_count))
            await asyncio.sleep(0)
            return res
__all__ += ["BaseCommand"]

from .low_level_commands import (SynchronizeCommand, AbortCommand, FlushCommand, ExternalCtrlCommand,
                    BeamSelectCommand, BlankCommand, DelayCommand, RasterRegionCommand,
                    RasterPixelCommand, ArrayCommand, RasterPixelRunCommand, 
                    RasterPixelFreeRunCommand, VectorPixelCommand, Command)
__all__ += ["SynchronizeCommand", "AbortCommand", "FlushCommand", "ExternalCtrlCommand",
            "BeamSelectCommand", "BlankCommand", "DelayCommand", "RasterRegionCommand",
            "RasterPixelCommand", "ArrayCommand", "RasterPixelRunCommand", 
            "RasterPixelFreeRunCommand", "VectorPixelCommand", "Command"]
    