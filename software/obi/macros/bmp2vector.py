from multiprocessing import Pool, Value
import numpy as np
from PIL import Image

from obi.commands import *


def pool_initializer(S):
    global scale_factor
    scale_factor = S

def line(xarray):
    if xarray:
        y, xarray = xarray
        c = bytearray()
        for x in np.nonzero(xarray)[0]:
            c.extend(bytes(VectorPixelCommand(x_coord=int(x*scale_factor), y_coord = int(y*scale_factor), dwell_time=xarray[x])))
        return c


class BitmapVectorPattern:
    """
    Converts an image to an array of vector points (as :class:`VectorPixelCommand`).\
    For high resolution images, this process can be quite resource intensive.\
    This class uses :py:mod:`multiprocessing.Pool` to speed up conversion by executing multiple threads.
    
    Attributes:
        im (PIL.Image): See https://pillow.readthedocs.io/en/stable/reference/Image.html
        processed_im (PIL.Image | None): Populated by :func:`rescale`
        pattern_seq (bytearray | None): Populated by :func:`vector_convert`
    
    Args:
        path: Path to a PIL-compatible image file
    """
    def __init__(self, path):
        self.im = Image.open(path)
        self.processed_im = None
        self.pattern_seq = None
    
    def rescale(self, resolution:u16, max_dwell:DwellTime, invert:bool):
        """
        Rescale the image to specified resolution, upsampling or downsampling as necessary.
        Rescale dwell times such that the brightest pixel has dwell time max_dwell.

        Important:
            By default, white pixels (brightness 255) correspond to the maximum dwell time,\
            and black pixels (brightness 0) correspond to no dwell time and will be skipped.

        Args:
            resolution: Resolution to scale pattern to.
            max_dwell: Maximum dwell value
            invert: Invert grayscale levels
        """
        im = self.im
        im = im.convert("L") #TODO: handle 16 bit grayscale
        ## scale dwell times 
        def level_adjust(pixel_value):
            return int((pixel_value/255)*max_dwell)
        pixel_range = im.getextrema()
        im = im.point(lambda p: level_adjust(p))
        print(f"{pixel_range=} -> scaled_pixel_range= (0,{max_dwell})")
        
        ## scale to resolution
        x_pixels, y_pixels = im._size
        scale_factor = resolution/max(x_pixels, y_pixels)
        scaled_y_pixels = int(y_pixels*scale_factor)
        scaled_x_pixels = int(x_pixels*scale_factor)

        # https://pillow.readthedocs.io/en/stable/_modules/PIL/Image.html#Image.resize
        im = im.resize((scaled_x_pixels, scaled_y_pixels), resample = Image.Resampling.NEAREST)
        print(f"input image: {x_pixels=}, {y_pixels=} -> {scaled_x_pixels=}, {scaled_y_pixels=}")

        self.processed_im = im

    def vector_convert(self, progress_fn=lambda p: print(p)): #progress fn input: int from 0 to 100
        """
        Args:
            progress_fn (function, optional): Function that accepts a value from 0 to 100 \
                and emits a progress indicator. Defaults to :code:`lambda p:print(p)`.
        """
        pattern_array = np.asarray(self.processed_im)
        seq = bytearray()

        ## Prepare to unblank with beam at the first vector pixel
        seq.extend(bytes(SynchronizeCommand(raster=False, output=OutputMode.NoOutput, cookie=123)))
        seq.extend(bytes(FlushCommand()))
        seq.extend(bytes(BeamSelectCommand(beam_type = BeamType.Ion)))
        seq.extend(bytes(BlankCommand(enable=False, inline=True)))

        y_pixels, x_pixels = pattern_array.shape
        pattern_scale_factor = 16384/max(x_pixels,y_pixels)
        pool = Pool(initializer=pool_initializer, initargs=[pattern_scale_factor])
        n = 0
        for i in pool.imap(line, enumerate(pattern_array)):
            seq.extend(i)
            n += 1
            progress = int(100*n/y_pixels)
            progress_fn(progress)
        pool.close()

        seq.extend(bytes(BlankCommand(enable=True)))
        self.pattern_seq = seq
        print("done~")


if __name__ == "__main__":
    bmp = BitmapVectorPattern("/Users/isabelburgos/Open-Beam-Interface/software/nanographs_logo.bmp")
    bmp.rescale(2048, 10, False)
    bmp.vector_convert()