import pathlib

from glasgowcontrib.applet.open_beam_interface.base_commands import *

print("This program is intended to convert a csv file with two columns: x, y")
p = input("Enter csv path: ")
csv_path = pathlib.Path(p).expanduser()
file = open(csv_path)
print(f"loaded csv from {csv_path}")

dwell = int(input("Enter dwell time (1-65536): "))

async def setup():
    seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
    ## seq.add(Command())
    ## ...
    seq.add(BlankCommand(enable=True))
    seq.add(BeamSelectCommand(beam_type=BeamType.Electron))
    seq.add(ExternalCtrlCommand(enable=True))
    seq.add(DelayCommand(5760))
    await iface.write(seq.message)
    await iface.flush()

    wait = input("ready to go?")

async def teardown():
    wait = input("return control?")
    await iface.write(ExternalCtrlCommand(enable=False).message)
    await iface.flush()
    print("bye~")


async def pattern():
    seq = CommandSequence(output=OutputMode.NoOutput, raster=False)

    for line in file:
        x, y = line.strip().split(',')
        x = int(float(x)*254)
        y = int(float(y)*254)
        seq.add(VectorPixelCommand(x_coord = x, y_coord = y, dwell = dwell))

    print("writing pattern")
    await iface.write(seq.message)
    await iface.flush()
    print("done")


await setup()
await pattern()
await teardown()
