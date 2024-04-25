import asyncio
import time
from .beam_interface import Connection, BenchmarkTransfer



async def benchmark():
    conn = Connection('localhost', 2224)
    await conn._connect()
    print(type(conn._stream._writer.transport))
    print(vars(conn._stream._writer.transport))

    # conn._stream._writer.transport.set_write_buffer_limits(high=131072*16)

    await conn.transfer(BenchmarkTransfer())


asyncio.run(benchmark())