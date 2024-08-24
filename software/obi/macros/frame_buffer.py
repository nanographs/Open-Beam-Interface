import logging
import array
import datetime
import os

import numpy as np
import tifffile

from obi.commands import *
from obi.transfer import Connection
from .raster import RasterScanCommand
logger = logging.getLogger()

class Frame:
    _logger = logger.getChild("Frame")
    def __init__(self, x_res:int, y_res:int):
        """
        A Frame represents a 2D array of pixels.

        Properties:
            canvas: 2D np.array of uint16 representing an image

        Args:
            x_res (int): Number of pixels in X
            y_res (int): Number of pixels in Y
        """
        self._x_count = x_res
        self._y_count = y_res
        self.canvas = np.zeros(shape = self.np_shape, dtype = np.uint16)
        self.y_ptr = 0
    
    @classmethod
    def from_DAC_ranges(cls, x_range:DACCodeRange, y_range:DACCodeRange):
        """Generate a frame from two instances of :class:DACCodeRange

        Args:
            x_range (DACCodeRange)
            y_range (DACCodeRange)

        Returns:
            Frame
        """
        return cls(x_range.count, y_range.count)

    @property
    def pixels(self):
        """
        Returns:
            int: Number of pixels in the frame
        """
        return self._x_count * self._y_count

    @property
    def np_shape(self):
        """

        Returns:
            tuple: Shape of the underlying array in the form (y, x)
        """
        return self._y_count, self._x_count

    def fill(self, pixels: array.array):
        """
        Fill the entire contents of the Frame at once.

        Args:
            pixels (array.array): 1D array of pixel data

        Raises:
            ValueError: If the number of pixels isn't equal to the Frame's pixels
        """
        if len(pixels) != self.pixels:
            raise ValueError(f"expected {self._x_count} x {self._y_count} = {self.pixels} pixels, got {len(pixels)} pixels")
        self.canvas = np.array(pixels, dtype = np.uint16).reshape(self.np_shape)
    
    def fill_lines(self, pixels: array.array):
        """
        Fill a partial section of the frame with data.
        Only whole lines will be accepted.

        Args:
            pixels (array.array): 1D array of pixel data
        """
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

    def saveImage_tifffile(self, save_path, bit_depth_8=True, bit_depth_16=False,
                            scalebar_HFOV=None):
        img_name = save_path + " saved " + datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
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
        """
        The Frame Buffer executes raster scan commands and stores the results in a :class:Frame.
        It is suitable for a live graphical display, or for headless scripted capture.

        Args:
            conn (Connection)
        """
        self.conn = conn
        self.current_frame = None
        self.abort = None

    def _opt_chunk_size(self, frame: Frame):
        """
        Very rough frame rate control.

        Args:
            frame (Frame)
            ## TODO: take dwell time into account

        Returns:
            int: Number of pixels to update each time display is repainted.
        """
        FPS = 60
        DWELL_NS = 125
        s_per_frame = 1/FPS
        dwells_per_frame = s_per_frame/(DWELL_NS*pow(10,-9))
        if dwells_per_frame > frame.pixels:
            return frame.pixels
        else:
            lines_per_chunk = dwells_per_frame//frame._x_count
            return int(frame._x_count*lines_per_chunk)
    
    def _set_current_frame(self, x_res:int, y_res:int):
        """
        Called when scan settings have been changed. 
        If the buffer contains an existing Frame as current_frame, and that \
        frame has the same resolution as x_res and y_res, then keep the current frame \
        but reset the Y pointer to the top of the frame.
        Otherwise, generate a new frame and assign to current_frame.

        Args:
            x_res (_type_): Number of pixels in X
            y_res (_type_): Number of pixels in Y
        """
        # if resolution is exactly the same
        if (self.current_frame is not None):
            if (x_res == self.current_frame._x_count) & (y_res == self.current_frame._y_count):
                self.current_frame.y_ptr = 0 #reset to top
            else:
                self.current_frame = Frame(x_res, y_res) #Create new empty frame
        else:
            self.current_frame = Frame(x_res, y_res) #Create new empty frame
    
    def abort_scan(self):
        """Stop the scan without completing a frame
        """
        if self.abort is not None:
            self.abort.set()
    
    @property
    def is_aborted(self):
        """
        True if all of the following are true:
            - An abort event exists
            - The abort event has already been set
        If true, also clears the existing abort event by setting self.abort to None.

        Returns:
            bool
        """
        if self.abort is not None:
            if self.abort.is_set():
                self.abort = None
                return True
            else:
                return False
        else:
            return False

    async def _capture_frame_iter_fill(self, *, frame: Frame, x_range:DACCodeRange, y_range:DACCodeRange, dwell_time: int, latency:int=65536):
        """
        Core function for capturing image data produced by a raster scan into a 2D array.

        Args:
            frame (Frame): Frame to capture into
            x_range (DACCodeRange)
            y_range (DACCodeRange)
            dwell_time (int)
            latency (int, optional): Send chunks of pixels that will take no longer \
                                    than this many dwell times to execute. Defaults to 65536.
        Yields:
            Frame: A Frame object is yielded each time new pixels are added
        """
        res = array.array('H')
        pixels_per_chunk = self._opt_chunk_size(frame)
        self._logger.debug(f"{pixels_per_chunk=}")

        await self.conn.transfer(BlankCommand(enable=False, inline=True))

        cmd = RasterScanCommand(cookie=123,x_range=x_range, y_range=y_range, dwell_time=dwell_time)
        self.abort = cmd.abort
        #self.conn._synchronized = False
        async for chunk in self.conn.transfer_multiple(cmd, latency=latency):
            self._logger.debug(f"{len(res)} old pixels + {len(chunk)} new pixels -> {len(res)+len(chunk)} total in buffer. {latency=}")
            res.extend(chunk)

            async def slice_chunk():
                nonlocal res
                if len(res) >= pixels_per_chunk:
                    to_frame = res[:pixels_per_chunk]
                    res = res[pixels_per_chunk:]
                    self._logger.debug(f"slice to display: {pixels_per_chunk}, {len(res)} pixels left in buffer")
                    frame.fill_lines(to_frame)
                    yield frame
                    if len(res) > pixels_per_chunk:
                        yield slice_chunk()
                else:
                    pass
                    self._logger.debug(f"have {len(res)} pixels in buffer, need minimum {pixels_per_chunk} pixels to complete this chunk")

            async for frame in slice_chunk():
                yield frame

        self._logger.debug(f"end of scan: {len(res)} pixels in buffer")
        last_lines = len(res)//frame._x_count
        if last_lines > 0:
            frame.fill_lines(res[:frame._x_count*last_lines])
        yield frame

    async def capture_frame(self, *, x_range:DACCodeRange, y_range:DACCodeRange, dwell_time:int, **kwargs):
        """
        Simplest method to capture a single frame. 
        Unlike frame capture methods that are used with the GUI, no partially filled frames are returned.

        Args:
            x_range (DACCodeRange): X range for raster scan
            y_range (DACCodeRange): Y range for raster scan
            dwell_time (int): Pixel dwell time

        Returns:
            Frame
        """
        async for frame in self._capture_iter_fill(x_range=x_range, y_range=y_range, dwell_time=dwell_time,
        latency=x_range.count*y_range.count*dwell_time, **kwargs):
            pass
        return self.current_frame

        async def capture_frame_roi(self, *, x_res:int, y_res:int, x_start:int, x_count:int, y_start:int, y_count:int, **kwargs):
        """Scan and capture data into a selected region of a frame

        Args:
            x_res (int): X resolution of full frame
            y_res (int): Y resolution of full frame
            x_start (int): X coordinate of top left corner of ROI
            x_count (int): Number of steps in X in ROI
            y_start (int): Y coordinate of top left corner of ROI
            y_count (int): Number of steps in Y in ROI

        Yields:
            Frame: Full frame with new data filled into region of interest. \
                A Frame object is yielded each time new pixels are added.
        """
        x_range = DACCodeRange.from_roi(x_res, x_start, x_count)
        y_range = DACCodeRange.from_roi(y_res, y_start, y_count)
        roi_frame = Frame.from_DAC_ranges(x_range, y_range)
        roi_frame.canvas = self.current_frame.canvas[y_start:(y_start+y_count),x_start:(x_start+x_count)] #copy frame underneath
        self._set_current_frame(x_res, y_res)
        async for roi_frame in self.capture_frame_iter_fill(frame=roi_frame, x_range=x_range, y_range=y_range,**kwargs):
            self.current_frame.canvas[y_start:(y_start+y_count),x_start:(x_start+x_count)] = roi_frame.canvas
            yield self.current_frame

    async def capture_full_frame(self, *, x_res: int, y_res: int, **kwargs):
        """Scan and capture data into a frame that spans the entire DAC range.

        Args:
            x_res (int): Number of pixels in X
            y_res (int): Number of pixels in Y

        Yields:
            Frame: A Frame object is yielded each time new pixels are added
        """
        x_range = DACCodeRange.from_resolution(x_res)
        y_range = DACCodeRange.from_resolution(y_res)
        self._set_current_frame(x_res, y_res)
        async for frame in self._capture_frame_iter_fill(frame=self.current_frame, x_range=x_range, y_range=y_range, **kwargs):
            self.current_frame = frame
            yield frame

