import sys

data = sys.stdin.buffer.read()
print(f"read {len(data)} bytes")
await iface.write(data)
await iface.flush()

