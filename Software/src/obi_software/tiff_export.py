# from ome_types import to_xml, OME

# from ome_types.model import Instrument, Microscope, InstrumentRef, Image, Pixels
import numpy as np
import tifffile

from PIL import Image, ImageDraw, ImageFont


# def get_image_data():
#     ome = OME()

#     microscope = Microscope(
#                 manufacturer='JEOL',
#                 model='Lab Mk4',
#                 serial_number='L4-5678',
#             )

#     instrument = Instrument(microscope = microscope)
#     ome.instruments.append(instrument)

#     pixels = Pixels(
#         type = "uint8",
#         dimension_order = "XYZCT",
#         size_x = 512,
#         size_y = 512,
#         size_z = 1,
#         size_c = 1,
#         size_t = 1,
#         physical_size_x = 2, #default physical_size unit is microns
#         physical_size_y = 2,
#         BigEndian = False,
#         ) 

#     image = Image(pixels=pixels)
#     ome.images.append(image)

#     print(ome.to_xml())

# ome_xml = get_image_data()

imagedata = np.full(shape=(1024,1024), fill_value = 100, dtype= np.uint8)



def draw_scalebar(imagedata, hfov): #hfov in m
    
    height_in_px, width_in_px = imagedata.shape
    n_blank_lines = int(.05*height_in_px)
    blank_lines = np.zeros(shape=(n_blank_lines,width_in_px))
    imagedata = np.vstack((imagedata, blank_lines))
    height_in_px += n_blank_lines
    scalebar_px = int(.25*width_in_px)
    scalebar_length = hfov*(scalebar_px/width_in_px)
    hfov_text = str(hfov*pow(10,6)) + " µm"
    scalebar_offset_px = int(.03*width_in_px)
    image = Image.fromarray(imagedata)
    draw = ImageDraw.Draw(image)
    draw.line([(scalebar_offset_px,height_in_px-scalebar_offset_px),
                (scalebar_offset_px+scalebar_px,height_in_px-scalebar_offset_px)], fill=255, width=int(n_blank_lines/3))
    font = ImageFont.truetype("iAWriterQuattroV.ttf", size=int(n_blank_lines*.9))
    draw.text([scalebar_px + scalebar_offset_px*3,height_in_px-scalebar_offset_px], hfov_text, fill=255, anchor="lm", font=font)
    image.save("test.tif")

draw_scalebar(imagedata, .001)

# tifffile.imwrite(f"test.tif", imagedata, metadata={
#     "PixelSizeX": 1,
#     "PixelSizeY": 2
# })
