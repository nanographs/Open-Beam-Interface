from glasgowcontrib.applet.open_beam_interface.base_commands import *

dwell = 2
loops = 1000

seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
seq.add(BlankCommand(beam_type=BeamType.Ion, enable=True))
seq.add(ExternalCtrlCommand(beam_type=BeamType.Ion, enable=True))

def dash_line(y):
    seq.add(VectorPixelCommand(x_coord = 0, y_coord=y, dwell=1))
    seq.add(BlankCommand(beam_type=BeamType.Ion, enable=False))
    for x in range(4096):
        seq.add(VectorPixelCommand(x_coord = x, y_coord=y, dwell=dwell))
    seq.add(BlankCommand(beam_type=BeamType.Ion, enable=True))

    seq.add(VectorPixelCommand(x_coord = 8192, y_coord=y, dwell=1))
    seq.add(BlankCommand(beam_type=BeamType.Ion, enable=False))
    for x in range(12288,16384):
        seq.add(VectorPixelCommand(x_coord = x, y_coord=y, dwell=dwell))
    seq.add(BlankCommand(beam_type=BeamType.Ion, enable=True))

for _ in range(loops):
    dash_line(4096)
    dash_line(12288)

await iface.write(seq.message)
await iface.flush()



