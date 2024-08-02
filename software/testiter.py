

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


async def a_task(stop):
    while not stop.done():
        print("Hello world!")
        await asyncio.sleep(1)
    print(stop.result())

async def async_iter_fn():
    n = 0
    while True:
        stop = asyncio.Future()
        asyncio.create_task(a_task(stop))
        s = random.randint(1,10)
        await asyncio.sleep(s)
        stop.set_result("All done!")
        n += 1
        yield n


async def main():
    async for n in async_iter_fn():
        print(f"{n=}")

asyncio.run(main())



