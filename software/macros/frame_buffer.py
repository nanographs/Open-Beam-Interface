import logging
import array
import datetime
import os

import numpy as np
import tifffile

from .raster import RasterScanCommand
from commands import DACCodeRange
from transfer import Connection
logger = logging.getLogger()

class Frame:
    _logger = logger.getChild("Frame")
    def __init__(self, x_range: DACCodeRange, y_range: DACCodeRange):
        self._x_range = x_range
        self._y_range = y_range
        self._x_count = x_range.count
        self._y_count = y_range.count
        self.canvas = np.zeros(shape = self.np_shape, dtype = np.uint16)
        self.y_ptr = 0

    @property
    def pixels(self):
        return self._x_range.count * self._y_range.count

    @property
    def np_shape(self):
        return self._y_range.count, self._x_range.count

    def fill(self, pixels: array.array):
        assert len(pixels) == self.pixels, f"expected {self.pixels}, got {len(pixels)}"
        self.canvas = np.array(pixels, dtype = np.uint16).reshape(self.np_shape)
    
    def fill_lines(self, pixels: array.array):
        assert len(pixels)%self._x_count == 0, f"invalid shape: {len(pixels)} is not a multiple of {self._x_count}"
        fill_y_count = int(len(pixels)/self._x_count)
        self._logger.debug(f"fill_lines: fill {len(pixels)} pixels ({fill_y_count} lines), from y ={self.y_ptr}")
        if (fill_y_count == self._y_count) & (self.y_ptr == 0):
            self.fill(pixels)
        elif self.y_ptr + fill_y_count <= self._y_count:
            self.canvas[self.y_ptr:self.y_ptr + fill_y_count] = np.array(pixels, dtype = np.uint16).reshape(fill_y_count, self._x_count)
            self.y_ptr += fill_y_count
            if self.y_ptr == self._y_count:
                self._logger.debug("fill_lines: roll over to top of frame")
                self.y_ptr == 0
        elif self.y_ptr + fill_y_count > self._y_count:
            self._logger.debug(f"fill_lines: {self.y_ptr} + {fill_y_count} > {self._y_count}")
            remaining_lines = self._y_count - self.y_ptr
            remaining_pixel_count = remaining_lines*self._x_count
            remaining_pixels = pixels[:remaining_pixel_count]
            self.canvas[self.y_ptr:self._y_count] = np.array(remaining_pixels, dtype = np.uint16).reshape(remaining_lines, self._x_count)
            rewrite_lines = fill_y_count - remaining_lines
            rewrite_pixels = pixels[remaining_pixel_count:]
            self._logger.debug(f"fill_lines: {remaining_lines=}, {rewrite_lines=}")
            self.canvas[:rewrite_lines] = np.array(rewrite_pixels, dtype = np.uint16).reshape(rewrite_lines, self._x_count)
            self.y_ptr = rewrite_lines
        self._logger.debug(f"fill_lines: end at y = {self.y_ptr}")


    def as_uint16(self):
        return np.left_shift(self.canvas, 2)

    def as_uint8(self):
        return np.right_shift(self.canvas, 6).astype(np.uint8)

    def saveImage_tifffile(self, save_dir, img_name=None, bit_depth_8=True, bit_depth_16=False,
                            scalebar_HFOV=None):
        if img_name == None:
            img_name = "saved" + datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        else:
            img_name = img_name + " " + datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        img_name = os.path.join(save_dir, img_name)
        if not scalebar_HFOV==None:
            #draw_scalebar(np.fliplr(self.as_uint8()), scalebar_HFOV, img_name)
            pass
        else:
            if bit_depth_8:
                tifffile.imwrite(f"{img_name}_8bit.tif", self.as_uint8(), shape = self.np_shape, dtype = np.uint8)
            if bit_depth_16:
                tifffile.imwrite(f"{img_name}_16bit.tif", self.as_uint16(), shape = self.np_shape, dtype = np.uint16)

        print(f"saved: {img_name}")

class FrameBuffer():
    _logger = logger.getChild("FrameBuffer")
    def __init__(self, conn: Connection):
        self.conn = conn
        self.current_frame = None
    
    def get_frame(self, x_range, y_range):
        if self.current_frame == None:
            return Frame(x_range, y_range)
        elif (x_range == self.current_frame._x_range) & (y_range == self.current_frame._y_range):
            return self.current_frame
        else:
            return Frame(x_range, y_range)

    async def capture_frame_iter_fill(self, *, x_range:DACCodeRange, y_range:DACCodeRange, dwell_time: int, latency, frame=None):
        frame = self.get_frame(x_range,y_range)
        res = array.array('H')
        pixels_per_chunk = self.opt_chunk_size(frame)
        self._logger.debug(f"{pixels_per_chunk=}")
        cmd = RasterScanCommand(cookie=123,
            x_range=x_range, y_range=y_range, dwell_time=dwell_time)
        async for chunk in self.conn.transfer_multiple(cmd, latency=latency):
            self._logger.debug(f"{len(res)} old pixels + {len(chunk)} new pixels -> {len(res)+len(chunk)} total")
            res.extend(chunk)

            async def slice_chunk():
                nonlocal res
                if len(res) >= pixels_per_chunk:
                    to_frame = res[:pixels_per_chunk]
                    res = res[pixels_per_chunk:]
                    self._logger.debug(f"slice: {pixels_per_chunk}, {len(res)} pixels remaining")
                    frame.fill_lines(to_frame)
                    yield frame
                    if len(res) > pixels_per_chunk:
                        yield slice_chunk()
                else:
                    self._logger.debug(f"need chunk: {pixels_per_chunk}, have {len(res)} pixels")

            async for frame in slice_chunk():
                self.current_frame = frame
                yield frame

        self._logger.debug(f"end of frame: {len(res)} pixels")
        frame.fill_lines(res)
        self.current_frame = frame
        yield frame

    async def capture_frame(self, *, x_range:DACCodeRange, y_range:DACCodeRange, dwell_time, **kwargs):
        async for frame in self.capture_iter_fill(x_range=x_range, y_range=y_range, dwell_time=dwell_time,
        latency=x_range.count*y_range.count*dwell_time, **kwargs):
            pass
        return self.current_frame


    def opt_chunk_size(self, frame: Frame):
        FPS = 60
        DWELL_NS = 125
        s_per_frame = 1/FPS
        dwells_per_frame = s_per_frame/(DWELL_NS*pow(10,-9))
        if dwells_per_frame > frame.pixels:
            return frame.pixels
        else:
            lines_per_chunk = dwells_per_frame//frame._x_count
            return int(frame._x_count*lines_per_chunk)

