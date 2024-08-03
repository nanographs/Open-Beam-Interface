

# def iter_fn():
#     n = 0
#     while True:
#         m = yield n
#         n += m
#         print(f"iter_fn got {m}, now {n=}")
        

# my_iter = iter_fn()
# my_iter.send(None)
# for m in range(10):
#     n = my_iter.send(m)
#     print(f"sent {m=}, got {n=}")

import time
import asyncio
import random

from obi.transfer import TCPConnection


class ConnectionWrapper:
    def __init__(self):
        self.open = asyncio.Lock()
        self.conn = TCPConnection('127.0.0.1', 8888)
    async def write(self, message):
        async with self.open:
            await self.conn._stream.write(message.encode())
            await self.conn._stream.flush()
            data = await self.conn._stream._reader.readuntil(message.encode())
            print(f"Recieved {data.decode()}")
            

async def a_task(n, conn):
    s = random.randint(0,10)
    print(f"Task {n} will sleep for {s} seconds")
    await asyncio.sleep(s)
    print(f"Task {n} woke up!")
    await conn.write(f"Hello from task {n}")

        

async def main():
    loop = asyncio.get_event_loop()
    conn = ConnectionWrapper()
    await conn.conn._connect()

    for n in range(10):
        asyncio.create_task(a_task(n, conn))

    pending = asyncio.all_tasks()
    await asyncio.gather(*pending)

asyncio.run(main())



    