import sys

data = sys.stdin.buffer.read()
print(f"writing {len(data)} bytes")
await iface.write(data)
await iface.flush()
print("all done!")
