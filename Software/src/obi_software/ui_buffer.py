import array
import numpy as np
import logging
from beam_interface import RasterScanCommand, RasterFreeScanCommand, setup_logging

setup_logging({"Command": logging.DEBUG, "Stream": logging.DEBUG})

class FrameBuffer():
    def __init__(self, conn):
        self.conn = conn
        self._raster_scan_buffer = array.array('H')

    async def capture_image(self, x_range, y_range, *, dwell, latency):
        self.buffer = np.zeros(shape=(y_range.count, x_range.count), dtype = np.uint16)
        cmd = RasterScanCommand(cookie=self.conn.get_cookie(), 
            x_range=x_range, y_range=y_range, dwell=dwell)
        async for chunk in self.conn.transfer_multiple(cmd, latency=latency):
            self._raster_scan_buffer.extend(chunk)

    async def free_scan(self, x_range, y_range, *, dwell, latency):
        cmd = RasterFreeScanCommand(cookie=self.conn.get_cookie(), 
            x_range=x_range, y_range=y_range, dwell=dwell, interrupt=self.conn._interrupt)
        res = array.array('H')
        async for chunk in self.conn.transfer_multiple(cmd, latency=latency):
            # res.extend(chunk)
            print(f"free scan yielded chunk of size {len(chunk)}")
            # if self.conn._interrupt.is_set():
            #     await asyncio.sleep(1)
            #     print("interrupted")
            #     break
        print("freescan concluded")

    def output_ndarray(self, x_range, y_range):
        ar = np.array(self._raster_scan_buffer)
        self._raster_scan_buffer = array.array('H')
        ar = ar.astype(np.uint8)
        ar = ar.reshape(x_range.count, y_range.count)
        return ar