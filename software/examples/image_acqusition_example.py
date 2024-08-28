import asyncio

from obi.transfer import TCPConnection
from obi.macros import FrameBuffer

async def main():
    conn = TCPConnection('localhost', 2224)
    fb = FrameBuffer
    frame = await fb.capture_frame(2048, 2048)

if __name__ == "__main__":
    asyncio.run(main())


