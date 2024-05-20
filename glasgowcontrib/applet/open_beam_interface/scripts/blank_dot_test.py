from glasgowcontrib.applet.open_beam_interface.base_commands import *

seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
## seq.add(Command())
## ...
seq.add(BlankCommand())
seq.add(ExternalCtrlCommand(enable=True))
seq.add(DelayCommand(5760))
seq.add(BeamSelectCommand(beam_type=BeamType.Ion))


dwell = 1

for x in range(10000000):
    seq.add(BlankCommand(enable=False, inline=True))
    seq.add(VectorPixelCommand(x_coord=2000, y_coord = 5000, dwell = dwell))
    seq.add(BlankCommand())

    seq.add(BlankCommand(enable=False, inline=True))
    seq.add(VectorPixelCommand(x_coord=8000, y_coord = 5000, dwell = dwell))

    seq.add(VectorPixelCommand(x_coord=14000, y_coord = 5000, dwell = dwell))
    seq.add(BlankCommand())

    seq.add(BlankCommand(enable=False, inline=True))
    seq.add(VectorPixelCommand(x_coord=14000, y_coord = 10000, dwell = dwell))
    seq.add(BlankCommand())

    seq.add(BlankCommand(enable=False, inline=True))
    seq.add(VectorPixelCommand(x_coord=8000, y_coord = 10000, dwell = dwell))

    seq.add(VectorPixelCommand(x_coord=2000, y_coord = 10000, dwell = dwell))
    seq.add(BlankCommand())






seq.add(ExternalCtrlCommand(enable=False))


await iface.write(seq.message)
await iface.flush()
