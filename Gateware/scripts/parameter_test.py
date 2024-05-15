from glasgowcontrib.applet.open_beam_interface.base_commands import *
import numpy as np


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
seq = CommandSequence(output=OutputMode.NoOutput, raster=False)
seq.add(BlankCommand(enable=False, inline=True))
seq.add(VectorPixelCommand(x_coord=0, y_coord=0, dwell=1))


def gradient_line(x_start, x_count, x_step, y, dwells):
    for x in range(x_start, x_start+(x_count*x_step), x_step):
        #seq.add(BlankCommand(enable=False, inline=True))
        seq.add(VectorPixelCommand(x_coord=int(x), y_coord = int(y), dwell = int(dwells[x])))
        #seq.add(BlankCommand(enable=True))

dwells = np.linspace(1, 160, num=16384)
n_lines_array = np.logspace(0, 9, num=25, base=2)
y_sections = np.arange(0, 16384-650, 650)

print(f"{len(y_sections)=}")
print(f"{len(n_lines_array)=}")

total_lines = 0

def horizontal_lines():
    for yn in range(len(y_sections)):
        y_start = y_sections[yn]
        n_lines = int(n_lines_array[yn])
        print(f"{y_start=}, {n_lines=}, {y_start+n_lines=}")
        for line in range(n_lines):
            gradient_line(0, 16384, 1, int(y_start+4), dwells) #shift everything down 4 lines
            y_start += 1


def vertical_lines():
    for y in range(16384):
        for xn in range(len(y_sections)):
            x_start = y_sections[xn]
            n_lines = int(n_lines_array[yn])
            print(f"{y_start=}, {n_lines=}, {y_start+n_lines=}")
            for line in range(n_lines):
                seq.add(VectorPixelCommand(x_coord=int(x_start), y_coord = int(y), dwell = int(dwells[x])))
                x_start += 1

seq.add(BlankCommand(enable=True))

print("writing")
await iface.write(seq.message)
await iface.flush()
print("all done!")

wait = input("return control?")
await iface.write(ExternalCtrlCommand(enable=False).message)
await iface.flush()
print("bye~")

