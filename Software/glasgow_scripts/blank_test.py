from Gateware.applet.open_beam_interface.base_commands import *

dwell = 1
loops = 100

seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
seq.add(BlankCommand(enable=True))
seq.add(ExternalCtrlCommand(enable=False))
seq.add(BeamSelectCommand(beam_type=BeamType.Ion))

def dash_line(y):
    seq.add(BlankCommand(enable=False, inline=True))
    for x in range(4096):
        seq.add(VectorPixelCommand(x_coord = x, y_coord=y, dwell_time=dwell))
    seq.add(BlankCommand())
    for x in range(4096, 12288):
        seq.add(VectorPixelCommand(x_coord = x, y_coord=y, dwell_time=dwell))
    seq.add(BlankCommand(enable=False, inline=True))
    for x in range(12288,16383):
        seq.add(VectorPixelCommand(x_coord = x, y_coord=y, dwell_time=dwell))
    seq.add(BlankCommand())

for _ in range(loops):
    dash_line(4096)
    dash_line(12288)


seq.add(ExternalCtrlCommand(enable=False))

for _ in range(loops):
    await iface.write(bytes(seq))
    await iface.flush()

response = await iface.read()

