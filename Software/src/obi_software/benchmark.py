import asyncio
import time
import logging
from .beam_interface import Connection, BenchmarkTransfer, setup_logging


setup_logging({"Stream": logging.DEBUG})

async def benchmark():
    conn = Connection('localhost', 2224)
    await conn._connect()
    print(type(conn._stream._writer.transport))
    print(vars(conn._stream._writer.transport))

    # conn._stream._writer.transport.set_write_buffer_limits(high=131072*16)

    await conn.transfer(BenchmarkTransfer(),output_mode=0)


asyncio.run(benchmark())