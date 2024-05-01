from glasgowcontrib.applet.open_beam_interface.base_commands import *

dwell = 1
loops = 1000

seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
seq.add(BlankCommand(enable=True, asynced=True))
seq.add(ExternalCtrlCommand(beam_type=BeamType.Ion, enable=True))
seq.add(BlankCommand(enable=True))
seq.add(VectorPixelCommand(x_coord = 0, y_coord=0, dwell=1))
seq.add(BlankCommand(enable=False, asynced=True))

def dash_line(y):
    seq.add(BlankCommand(enable=True))
    seq.add(VectorPixelCommand(x_coord = 0, y_coord=y, dwell=1))
    seq.add(BlankCommand(enable=False))
    for x in range(4096):
        seq.add(VectorPixelCommand(x_coord = x, y_coord=y, dwell=dwell))
    seq.add(BlankCommand(enable=True))

    seq.add(VectorPixelCommand(x_coord = 8192, y_coord=y, dwell=1))
    seq.add(BlankCommand(enable=False))
    for x in range(12288,16383):
        seq.add(VectorPixelCommand(x_coord = x, y_coord=y, dwell=dwell))
    seq.add(BlankCommand(enable=True))
    seq.add(VectorPixelCommand(x_coord = 16383, y_coord=y, dwell=1))

for _ in range(loops):
    dash_line(4096)
    dash_line(12288)

await iface.write(seq.message)
await iface.flush()



