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


file = open(args.csv_path)
prev_x = 0
prev_y = 0
for line in file:
    x, y = line.strip().split(',')
    x = int(float(x)*254)
    y = int(float(y)*254)
    
    for line in file:
        x, y = line.strip().split(',')
        x = int(float(x)*254)
        y = int(float(y)*254)
        if (abs(prev_x-x) > 2000) or (abs(prev_y-y) > 2000):
            #print(f"added blank between {x},{y} and prev {prev_x}, {prev_y}")
            seq.add(BlankCommand(enable=True))
            seq.add(BlankCommand(enable=False, inline=True))
        prev_x = x
        prev_y = y
        seq.add(VectorPixelCommand(x_coord = x, y_coord = y, dwell = dwell))

    print("writing pattern")
    await iface.write(seq.message)
    await iface.flush()
    print("done")


await setup()
await pattern()
await teardown()
