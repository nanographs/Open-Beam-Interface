from queue import Queue
import threading
import asyncio
import inspect
import logging
from .beam_interface import *

setup_logging({"Command": logging.DEBUG, "Stream": logging.DEBUG, "Connection": logging.DEBUG})
class UIThreadWorker:
    def __init__(self, in_queue: Queue, out_queue: Queue, loop):
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.credit = Queue(maxsize=1) #arbitrary max-things-in-flight
        self.loop = loop #asyncio event loop

    def _send(self, command: Command):
        self.out_queue.put(command)
        self.credit.put("credit") 
        print(f"UI send {command}. credit: {self.credit.qsize()}")
    
    async def _recv(self):
        print(f"UI recv start. credit: {self.credit.qsize()}")
        # doesn't have to be 1:1 credit to response
        self.credit.get() # should block if credit.empty()
        self.credit.task_done()
        response = self.in_queue.get()
        self.in_queue.task_done()
        ## todo: process and display response
        return response
    
    async def _xchg(self, command: Command):
        self._send(command)
        while not self.credit.empty():
            await self._recv()
    
    def xchg(self, command: Command):
        self.loop.run_until_complete(self._xchg(command))
        

class ConnThreadWorker:

    def __init__(self, host, port, in_queue: Queue, out_queue: Queue, loop):
        self.conn = Connection(host, port)
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.loop = loop #asyncio event loop

    async def _xchg(self):
        command = self.in_queue.get()
        print(f"CONN recv {command}")
        com = command.transfer
        print(f"{com=}, {type(com)=}, {inspect.isasyncgenfunction(com)=}")

        if inspect.isasyncgenfunction(com):
            print("async")
            async for chunk in self.conn.transfer_multiple(command, latency=63356):
                print(f"CONN send {chunk}")
                self.out_queue.put(chunk)
        else:
            res = await self.conn.transfer(command)
            print(f"CONN send {res}")
            self.out_queue.put(res)
    
    async def _run(self):
        while True:
            await self._xchg()
    
    def run(self):
        self.loop.create_task(self._run())
        self.loop.run_forever()
    

def ui_thread(in_queue, out_queue):
    loop = asyncio.new_event_loop()
    worker = UIThreadWorker(in_queue, out_queue, loop)
    # cmd = SynchronizeCommand(cookie=123, raster_mode=1)
    # cmd = SynchronizeCommand(cookie=123, raster_mode=1)
    x_range = y_range = DACCodeRange(0, 2048, int((16384/2048)*256))
    cmd = RasterScanCommand(cookie=123,
            x_range=x_range, y_range=y_range, dwell=2)
    worker.xchg(cmd)
    
def conn_thread(in_queue, out_queue):
    loop = asyncio.new_event_loop()
    worker = ConnThreadWorker('127.0.0.1', 2224, in_queue, out_queue, loop)
    worker.run()

if __name__ == "__main__":
    ui_to_con = Queue()
    con_to_ui = Queue()

    ui = threading.Thread(target = ui_thread, args = [con_to_ui, ui_to_con])
    con = threading.Thread(target = conn_thread, args = [ui_to_con, con_to_ui])

    ui.start()
    con.start()
    # ui.join()
    # con.join()




