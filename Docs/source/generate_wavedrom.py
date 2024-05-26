from amaranth import *
from amaranth.lib import enum, data


class Command(data.Struct):
    class Type(enum.Enum, shape=8):
        Synchronize         = 0x00
        Abort               = 0x01
        Flush               = 0x02
        Delay               = 0x03
        InlineDelay         = 0xa3
        EnableExtCtrl       = 0x04
        DisableExtCtrl      = 0x05
        SelectEbeam         = 0x06
        SelectIbeam         = 0x07
        SelectNoBeam        = 0x08
        Blank               = 0x09
        BlankInline         = 0x0a
        Unblank             = 0x0b
        UnblankInline       = 0x0d

        RasterRegion        = 0x10
        RasterPixel         = 0x11
        RasterPixelRun      = 0x12
        RasterPixelFreeRun  = 0x13
        VectorPixel         = 0x14
        VectorPixelMinDwell = 0x15
        FlipX               = 0x16
        FlipY               = 0x17
        Rotate90            = 0x18
        UnFlipX             = 0x19
        UnFlipY             = 0x20
        UnRotate90          = 0x21

    type: Type

    payload: data.UnionLayout({
        "synchronize":      data.StructLayout({
            "cookie":           Cookie,
            "mode":         data.StructLayout ({
                "raster": 1,
                "output": OutputMode,
            })
        }),
        "delay": DwellTime,
        "external_ctrl":       data.StructLayout({
            "enable": 1,
        }),
        "beam_type": BeamType,
        "blank":       data.StructLayout({
            "enable": 1,
            "inline": 1,
        }),
        "raster_region":    RasterRegion,
        "raster_pixel":     DwellTime,
        "raster_pixel_run": data.StructLayout({
            "length":           16,
            "dwell_time":       DwellTime,
        }),
        "vector_pixel":     data.StructLayout({
            "x_coord":          14,
            "y_coord":          14,
            "dwell_time":       DwellTime,
        }),
        "transform":        data.StructLayout({
            "xflip":            1,
            "yflip":            1,
            "rotate90":         1
        })
    })


