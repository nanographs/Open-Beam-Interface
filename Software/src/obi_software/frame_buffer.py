import array
import asyncio
import numpy as np
import logging
from beam_interface import RasterScanCommand, RasterFreeScanCommand, setup_logging, DACCodeRange

setup_logging({"Command": logging.DEBUG, "Stream": logging.DEBUG})


class Frame:
    def __init__(self, x_range: DACCodeRange, y_range: DACCodeRange):
        self._x_range = x_range
        self._y_range = y_range
        self.pixels = self._x_range.count*self._y_range.count
        self.shape = self._x_range.count, self._y_range.count
        self.canvas = self._empty
    
    @property
    def _empty(self):
        return np.zeros(shape = self.shape, dtype = np.uint16)
    
    def fill(self, pixels: array.array):
        assert len(pixels) == self.pixels
        self.canvas = np.array(pixels, dtype = np.uint16).reshape(self.shape)
    
    def prepare_for_display(self):
        ar = np.left_shift(self.canvas, 2) # align MSB of 14-bit ADC with MSB of int16
        ar = ar.byteswap() # whyyyyy is this necessary?
        ar = ar.astype(np.uint8)
        return ar
class FrameBuffer():
    def __init__(self, conn):
        self.conn = conn
        self._interrupt = asyncio.Event()

    async def capture_frame(self, x_range, y_range, *, dwell, latency):
        frame = Frame(x_range, x_range)
        res = array.array('H')
        self.buffer = np.zeros(shape=(y_range.count, x_range.count), dtype = np.uint16)
        cmd = RasterScanCommand(cookie=self.conn.get_cookie(), 
            x_range=x_range, y_range=y_range, dwell=dwell)
        async for chunk in self.conn.transfer_multiple(cmd, latency=latency):
            res.extend(chunk)
        frame.fill(res)
        return frame
    
    # async def capture_continous(self, x_range, y_range, *, dwell, latency):
    #     while not self._interrupt.set():
    #         await self.capture_frame(x_range, y_range, dwell=dwell, latency=latency)

    async def free_scan(self, x_range, y_range, *, dwell, latency):
        frame = Frame(x_range, x_range)
        res = array.array('H')
        cmd = RasterFreeScanCommand(cookie=self.conn.get_cookie(), 
            x_range=x_range, y_range=y_range, dwell=dwell, interrupt=self.conn._interrupt)
        async for chunk in self.conn.transfer_multiple(cmd, latency=latency):
            res.extend(chunk)
            print(f"free scan yielded chunk of size {len(chunk)}")
            if len(res) > frame.pixels:
                frame = res[:frame.pixels]
                res = self._raster_scan_buffer[frame.pixels:]
                print(f'yielding frame of length {len(frame)}')
                yield frame



    def output_ndarray(self, x_range, y_range):
        ar = np.array(self._current_frame)
        ar = np.left_shift(ar, 2) # align MSB of 14-bit ADC with MSB of int16
        ar = ar.byteswap() # whyyyyy is this necessary?
        ar = ar.astype(np.uint8)
        ar = ar.reshape(x_range.count, y_range.count)
        return ar