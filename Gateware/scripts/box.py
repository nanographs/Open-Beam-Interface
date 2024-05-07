from glasgowcontrib.applet.open_beam_interface.base_commands import *

seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
## seq.add(Command())
## ...
seq.add(BlankCommand())
seq.add(EnableExtCtrlCommand())
seq.add(SelectIbeamCommand())

dwell = 2

def box(x_start, y_start, x_width, y_height):
    ## start ______ x = x_start + x_width, y = y_start
    ##       |    |
    ##       ------ x = x_start + x_width, y = y_start + y_height
    for x in range(x_start, x_start+x_width):
        seq.add(VectorPixelCommand(x_coord=x, y_coord = y_start, dwell = dwell))
    for y in range(y_start, y_start+y_height):
        seq.add(VectorPixelCommand(x_coord=x_start+x_width, y_coord = y, dwell = dwell))
    for x in range(x_start, x_start+x_width, -1):
        seq.add(VectorPixelCommand(x_coord=x, y_coord = y_start+y_height, dwell = dwell))
    for y in range(y_start, y_start+y_height, -1):
        seq.add(VectorPixelCommand(x_coord=x_start, y_coord = y, dwell = dwell))


box(5000, 5000, 5000, 5000)

seq.add(DisableExtCtrlCommand())


await iface.write(seq.message)
