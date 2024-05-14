import sys

data = sys.stdin.buffer.read()
print("writing")
await iface.write(data)
await iface.flush()
print("all done!")
