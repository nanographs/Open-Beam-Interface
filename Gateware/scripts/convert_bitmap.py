import sys
import argparse
import numpy as np
import pathlib
from PIL import Image, ImageChops
from base_commands import *

# parser = argparse.ArgumentParser()
# parser.add_argument('--img_path', required=True,
#                     type=lambda p: pathlib.Path(p).expanduser(), #expand paths starting with ~ to absolute
#                     help='path to image file')
# parser.add_argument('--show', action='store_true', help="just display the processed image")
# args = parser.parse_args()

p = input("Enter image path: ")
img_path = pathlib.Path(p).expanduser()

im = Image.open(img_path)
print(f"loaded file from {img_path}")

im = im.convert("L") ## 8 bit grayscale
im = ImageChops.invert(im) ## 255 = longest dwell time, 0 = no dwell

## scale to 16384 x 16384
x_pixels, y_pixels = im._size
scale_factor = 16384/max(x_pixels, y_pixels)
scaled_y_pixels = int(y_pixels*scale_factor)
scaled_x_pixels = int(x_pixels*scale_factor)
# https://pillow.readthedocs.io/en/stable/_modules/PIL/Image.html#Image.resize
im = im.resize((scaled_x_pixels, scaled_y_pixels))
print(f"input image: {x_pixels=}, {y_pixels=} -> {scaled_x_pixels=}, {scaled_y_pixels=}")

## scale dwell times 
def level_adjust(pixel_value):
    return int(pixel_value*(160/255))
pixel_range = im.getextrema()
im = im.point(lambda p: level_adjust(p))
scaled_pixel_range = im.getextrema()
print(f"{pixel_range=} -> {scaled_pixel_range=}")

array = np.asarray(im)
im.show()
def show():
    im.show()

async def setup():
    seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
    ## seq.add(Command())
    ## ...
    seq.add(BlankCommand(enable=True))
    seq.add(BeamSelectCommand(beam_type=BeamType.Electron))
    seq.add(ExternalCtrlCommand(enable=True))
    seq.add(DelayCommand(5760))
    await iface.write(seq.message)
    await iface.flush()

    wait = input("ready to go?")

async def teardown():
    wait = input("return control?")
    await iface.write(ExternalCtrlCommand(enable=False).message)
    await iface.flush()
    print("bye~")

async def pattern():
    seq = CommandSequence(raster=False, output=OutputMode.NoOutput)

    ## Unblank with beam at position 0,0
    seq.add(BlankCommand(enable=False, inline=True))
    seq.add(VectorPixelCommand(x_coord=0, y_coord=0, dwell=1))

    for y in range(scaled_y_pixels):
        for x in range(scaled_x_pixels):
            dwell = array[y][x]
            if dwell > 0:
                seq.add(VectorPixelCommand(x_coord=x, y_coord = y, dwell=dwell))
        progress = 20*y/16384
        progress_bar = "".join(["#"]*int(progress))
        print(f"{progress*5:.2f}%, {y=}/16384")
        print(progress_bar)
    
    print("writing pattern")
    await iface.write(seq.message)
    await iface.flush()
    print("done")


# if args.show:
#     show()
# else:
await setup()
await pattern()
await teardown()


