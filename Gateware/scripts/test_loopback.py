from glasgowcontrib.applet.open_beam_interface.base_commands import *
import array

seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
for i in range(16384):
    for n in range(16384):
        seq.add(VectorPixelCommand(x_coord=n, y_coord = n, dwell = 3))
seq.add(FlushCommand())
print(f"writing")
await iface.write(seq.message)
await iface.flush()
print("wrote")
# print("reading")
# res = array.array('H', await iface.read(512*2))
# # print(res)

while True:
    await test()