import asyncio
import time
from .beam_interface import Connection, BenchmarkTransfer



async def benchmark():
    conn = Connection('localhost', 2224)
    await conn.transfer(BenchmarkTransfer())


asyncio.run(benchmark())