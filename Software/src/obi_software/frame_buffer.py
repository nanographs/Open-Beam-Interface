import datetime
import array
import asyncio
import numpy as np
import logging
import tifffile

from .beam_interface import RasterScanCommand, RasterFreeScanCommand, setup_logging, DACCodeRange, BeamType, ExternalCtrlCommand


setup_logging({"Command": logging.DEBUG, "Stream": logging.DEBUG})


class Frame:
    def __init__(self, x_range: DACCodeRange, y_range: DACCodeRange):
        self._x_range = x_range
        self._y_range = y_range
        self.canvas = np.zeros(shape = self.np_shape, dtype = np.uint16)

    @property
    def pixels(self):
        return self._x_range.count * self._y_range.count

    @property
    def np_shape(self):
        return self._x_range.count, self._y_range.count

    def fill(self, pixels: array.array):
        assert len(pixels) == self.pixels
        self.canvas = np.array(pixels, dtype = np.uint16).reshape(self.np_shape)

    def as_uint16(self):
        return np.left_shift(self.canvas, 2)

    def as_uint8(self):
        return np.right_shift(self.canvas, 6).astype(np.uint8)

    def saveImage_tifffile(self):
        img_name = "saved" + datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        tifffile.imwrite(f"{img_name}_16bit.tif", self.as_uint16(), shape = self.np_shape, dtype = np.uint16)
        tifffile.imwrite(f"{img_name}_8bit.tif", self.as_uint8(), shape = self.np_shape, dtype = np.uint8)
        print(f"{img_name}")

class FrameBuffer():
    def __init__(self, conn):
        self.conn = conn
        self._interrupt = asyncio.Event()
        self.current_frame = None

    async def set_ext_ctrl(self, enable):
        await self.conn.transfer(ExternalCtrlCommand(enable=enable, beam_type=1))

    async def capture_frame(self, x_range, y_range, *, dwell, latency):
        frame = Frame(x_range, y_range)
        res = array.array('H')
        cmd = RasterScanCommand(cookie=self.conn.get_cookie(),
            x_range=x_range, y_range=y_range, dwell=dwell, beam_type=BeamType.Electron)
        async for chunk in self.conn.transfer_multiple(cmd, latency=latency):
            res.extend(chunk)
        frame.fill(res)
        self.current_frame = frame
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
                res = res[frame.pixels:]
                print(f'yielding frame of length {len(frame)}')
                self.current_frame = frame
                yield frame