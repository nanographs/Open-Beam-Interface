from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


class ScaleBar:
    height_to_width = 0.07
    font_to_height = 0.8
    line_to_height = 0.1
    allowed_scales = {
        0.0012: "1200 µm",
        0.0005: "500 µm",
        0.0001: "100 µm",
        0.00002: "20 µm",
        0.00001: "10 µm",
        0.000001: "1 µm"
    }
    fontpath = Path(__file__).parent / "IBMPlexMono-Bold.ttf"
    def __init__(self, hresolution:int, hfov:float):
        self.width = hresolution
        self.height = int(hresolution*self.height_to_width)
        self.mid_line = self.height//2
        self.mid_font = int(self.height/2.2) #make the text look centered by aligning it off center
        self.font = ImageFont.truetype(self.fontpath, size=int(self.height*self.font_to_height))
        self.hfov = hfov
        blank_lines = np.zeros(shape=(self.height, self.width), dtype=np.uint8)
        self.canvas = Image.fromarray(blank_lines, mode="L")
        self.draw = ImageDraw.Draw(self.canvas)
    def add_line(self):
        label, pixels = self.get_best_scalebar()
        space = self.width*0.05
        y = self.mid_line
        self.draw.line([(space,y),
                (space+pixels,y)], fill=255, width=int(self.height*self.line_to_height))
        self.draw.text([space+pixels+space,self.mid_font], f"{label}", fill=255, anchor="lm", font=self.font)
    def get_best_scalebar(self):
        target_len = self.hfov/3
        best = None
        for length in self.allowed_scales.keys():
            if length <= target_len:
                best = length
                break
        label = self.allowed_scales.get(best)
        pixels = int(best*(self.width/self.hfov))
        return label, pixels



if __name__=="__main__":
    imagedata = np.random.randint(0, 254, size=(1024,1024), dtype=np.uint8)
    scalebar = ScaleBar(1024, .001)
    scalebar.add_line()
    i = np.vstack((imagedata, np.array(scalebar.canvas)))
    image = Image.fromarray(i)
    image.show()
