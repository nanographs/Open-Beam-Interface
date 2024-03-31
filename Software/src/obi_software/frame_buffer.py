import array
import asyncio
import numpy as np
import logging
from beam_interface import RasterScanCommand, RasterFreeScanCommand, setup_logging

setup_logging({"Command": logging.DEBUG, "Stream": logging.DEBUG})

class FrameBuffer():
    def __init__(self, conn):
        self.conn = conn
        self._raster_scan_buffer = array.array('H') #this is where raw data is moved through
        self._current_frame = array.array('H') #this is what is displayed on the viewer
        # the size of _current_frame should always match the x and y range of the viewer
        self._interrupt = asyncio.Event()

    async def capture_frame(self, x_range, y_range, *, dwell, latency):
        self._current_frame = array.array('H')
        self.buffer = np.zeros(shape=(y_range.count, x_range.count), dtype = np.uint16)
        cmd = RasterScanCommand(cookie=self.conn.get_cookie(), 
            x_range=x_range, y_range=y_range, dwell=dwell)
        async for chunk in self.conn.transfer_multiple(cmd, latency=latency):
            self._current_frame.extend(chunk)
    
    # async def capture_continous(self, x_range, y_range, *, dwell, latency):
    #     while not self._interrupt.set():
    #         await self.capture_frame(x_range, y_range, dwell=dwell, latency=latency)

    async def free_scan(self, x_range, y_range, *, dwell, latency):
        self._raster_scan_buffer = array.array('H')
        cmd = RasterFreeScanCommand(cookie=self.conn.get_cookie(), 
            x_range=x_range, y_range=y_range, dwell=dwell, interrupt=self.conn._interrupt)
        async for chunk in self.conn.transfer_multiple(cmd, latency=latency):
            self._raster_scan_buffer.extend(chunk)
            print(f"free scan yielded chunk of size {len(chunk)}")
            if len(self._raster_scan_buffer) > x_range.count*y_range.count:
                frame = self._raster_scan_buffer[:x_range.count*y_range.count]
                self._raster_scan_buffer = self._raster_scan_buffer[x_range.count*y_range.count:]
                print(f'yielding frame of length {len(frame)}')
                self._current_frame = frame
                yield 

        self._raster_scan_buffer = array.array('H')
        self._current_frame = array.array('H')


    def output_ndarray(self, x_range, y_range):
        ar = np.array(self._current_frame)
        ar = np.left_shift(ar, 2) # align MSB of 14-bit ADC with MSB of int16
        ar = ar.byteswap() # whyyyyy is this necessary?
        ar = ar.astype(np.uint8)
        ar = ar.reshape(x_range.count, y_range.count)
        return ar