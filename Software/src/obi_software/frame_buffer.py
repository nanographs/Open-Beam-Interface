import os
import datetime
import array
import asyncio
import threading
import queue
import numpy as np
import logging
import tifffile

from .beam_interface import RasterScanCommand, RasterFreeScanCommand, setup_logging, DACCodeRange, BeamType, ExternalCtrlCommand
from .tiff_export import draw_scalebar

# setup_logging({"Command": logging.DEBUG, "Stream": logging.DEBUG})

class Frame:
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
        print(f"{len(pixels)=}")
        assert len(pixels)%self._x_count == 0, f"invalid shape: {len(pixels)} is not a multiple of {self._x_count}"
        fill_y_count = int(len(pixels)/self._x_count)
        print(f"starting with {self.y_ptr=}")
        print(f"{fill_y_count=}")
        if (fill_y_count == self._y_count) & (self.y_ptr == 0):
            self.fill(pixels)
        elif self.y_ptr + fill_y_count <= self._y_count:
            self.canvas[self.y_ptr:self.y_ptr + fill_y_count] = np.array(pixels, dtype = np.uint16).reshape(fill_y_count, self._x_count)
            self.y_ptr += fill_y_count
            if self.y_ptr == self._y_count:
                print("Rolling over")
                self.y_ptr == 0
        elif self.y_ptr + fill_y_count > self._y_count:
            print(f"{self.y_ptr} + {fill_y_count} > {self._y_count}")
            remaining_lines = self._y_count - self.y_ptr
            remaining_pixel_count = remaining_lines*self._x_count
            remaining_pixels = pixels[:remaining_pixel_count]
            print(f"{remaining_lines=}")
            self.canvas[self.y_ptr:self._y_count] = np.array(remaining_pixels, dtype = np.uint16).reshape(remaining_lines, self._x_count)
            rewrite_lines = fill_y_count - remaining_lines
            rewrite_pixels = pixels[remaining_pixel_count:]
            print(f"{rewrite_lines=}")
            self.canvas[:rewrite_lines] = np.array(rewrite_pixels, dtype = np.uint16).reshape(rewrite_lines, self._x_count)
            self.y_ptr = rewrite_lines
        print(f"ending with {self.y_ptr=}")

    def opt_chunk_size(self, dwell):
        FPS = 30
        DWELL_NS = 125
        s_per_frame = 1/FPS
        dwells_per_frame = s_per_frame/(DWELL_NS*pow(10,-9)*dwell)
        if dwells_per_frame > self.pixels:
            return self.pixels
        else:
            lines_per_chunk = dwells_per_frame//self._x_count
            return int(self._x_count*lines_per_chunk)

    def as_uint16(self):
        return np.left_shift(self.canvas, 2)

    def as_uint8(self):
        return np.right_shift(self.canvas, 6).astype(np.uint8)

    def saveImage_tifffile(self, save_dir, img_name=None, bit_depth_eight=True, bit_depth_16=False,
                            scalebar_HFOV=None):
        if img_name == None:
            img_name = "saved" + datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        else:
            img_name = img_name + " " + datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        img_name = os.path.join(save_dir, img_name)
        if not scalebar_HFOV==None:
            draw_scalebar(np.fliplr(self.as_uint8()), scalebar_HFOV, img_name)
        else:
            if bit_depth_8:
                tifffile.imwrite(f"{img_name}_8bit.tif", self.as_uint8(), shape = self.np_shape, dtype = np.uint8)
            if bit_depth_16:
                tifffile.imwrite(f"{img_name}_16bit.tif", self.as_uint16(), shape = self.np_shape, dtype = np.uint16)

        print(f"saved: {img_name}")
    
class DisplayBuffer():
    def __init__(self):
        self.current_frame = None
        self.opt_chunk_size = None
        self.res = array.array('H')

    def get_frame(self, x_range, y_range):
        if self.current_frame == None:
            return Frame(x_range, y_range)
        elif (x_range == self.current_frame._x_range) & (y_range == self.current_frame._y_range):
            return self.current_frame
        else:
            return Frame(x_range, y_range)

    def prepare_display(self, x_range, y_range, *, dwell, latency, frame=None):
        self.current_frame = self.get_frame(x_range, y_range)
        self.opt_chunk_size = self.current_frame.opt_chunk_size(dwell)

    def display_image(self, chunk):
        frame = self.current_frame
        pixels_per_chunk = self.opt_chunk_size
        res = self.res
        print(f"have {len(res)=}. got {len(chunk)=}")
        res.extend(chunk)
        print(f"now have {len(res)=}")

        def slice_chunk():
            nonlocal res
            if len(res) >= pixels_per_chunk:
                to_frame = res[:pixels_per_chunk]
                res = res[pixels_per_chunk:]
                print(f"after slicing {pixels_per_chunk} chunk, have {len(res)}")
                frame.fill_lines(to_frame)
                yield frame
                if len(res) > pixels_per_chunk:
                    yield slice_chunk()
            else:
                print(f"need {pixels_per_chunk=}, have {len(res)=}")

        for frame in slice_chunk():
            yield frame

        print(f"end of frame: {len(res)=}")
        frame.fill_lines(res)
        self.current_frame = frame
        self.res = res
        yield frame


class FrameBuffer():
    def __init__(self, conn):
        self.conn = conn
        self._interrupt = asyncio.Event()
        self.queue = queue.Queue()

    async def set_ext_ctrl(self, enable):
        await self.conn.transfer(ExternalCtrlCommand(enable=enable, beam_type=1))
    
    async def capture_frame(self, x_range, y_range, *, dwell, latency, frame=None):
        cmd = RasterScanCommand(cookie=self.conn.get_cookie(),
            x_range=x_range, y_range=y_range, dwell=dwell, beam_type=BeamType.Electron)
        async for chunk in self.conn.transfer_multiple(cmd, latency=latency):
            res = array.array('H')
            res.extend(chunk)
            self.queue.put(res)

    async def free_scan(self, x_range, y_range, *, dwell, latency):
        cmd = RasterFreeScanCommand(cookie=self.conn.get_cookie(),
            x_range=x_range, y_range=y_range, dwell=dwell, beam_type=BeamType.Electron,
            interrupt=self.conn._interrupt)
        async for chunk in self.conn.transfer_multiple(cmd, latency=65536*16):
            res = array.array('H')
            res.extend(chunk)
            self.queue.put(res)

        self.conn._synchronized = False
        await self.conn._synchronize()

