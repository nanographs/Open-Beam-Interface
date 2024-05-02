import sys
import struct

b = bytearray()
for n in range(65536):
    b.extend(struct.pack('>H',n))

sys.stdout.buffer.write(b)