import sys

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

data = sys.stdin.buffer.read()
print(f"read {len(data)} bytes")
print("writing")
await iface.write(data)
await iface.flush()
print("all done!")

wait = input("return control?")
await iface.write(ExternalCtrlCommand(enable=False).message)
await iface.flush()
print("bye~")
