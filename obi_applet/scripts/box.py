from glasgowcontrib.applet.open_beam_interface.base_commands import *

seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
## seq.add(Command())
## ...
seq.add(BlankCommand())
seq.add(ExternalCtrlCommand(enable=True))
seq.add(DelayCommand(5760))
seq.add(BeamSelectCommand(beam_type=BeamType.Ion))
seq.add(BlankCommand(enable=False, inline=True))


dwell = 65536


def box(x_start, y_start, x_width, y_height):
    ## start ______ x = x_start + x_width, y = y_start
    ##       |    |
    ##       ------ x = x_start + x_width, y = y_start + y_height
    for x in range(x_start, x_start+x_width):
        seq.add(VectorPixelCommand(x_coord=x, y_coord = y_start, dwell = dwell))
        print(f"{x=}")
    for y in range(y_start, y_start+y_height):
        seq.add(VectorPixelCommand(x_coord=x_start+x_width, y_coord = y, dwell = dwell))
        print(f"{y=}")
    for x in range(x_start+x_width, x_start, -1):
        seq.add(VectorPixelCommand(x_coord=x, y_coord = y_start+y_height, dwell = dwell))
        print(f"{x=}")
    for y in range(y_start+y_height, y_start, -1):
        seq.add(VectorPixelCommand(x_coord=x_start, y_coord = y, dwell = dwell))
        print(f"{y=}")


box(5000, 5000, 5000, 5000)

seq.add(ExternalCtrlCommand(enable=False))


await iface.write(seq.message)
await iface.flush()
