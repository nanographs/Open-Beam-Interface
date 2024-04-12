from queue import Queue
import threading
import asyncio
import inspect
import logging
from .beam_interface import *

# setup_logging({"Command": logging.DEBUG, "Stream": logging.DEBUG, "Connection": logging.DEBUG})
class UIThreadWorker:
    _logger = logger.getChild("UIThread")
    def __init__(self, in_queue: Queue, out_queue: Queue, loop):
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.credit = Queue(maxsize=16) #arbitrary max-things-in-flight
        self.loop = loop #asyncio event loop

    def _send(self, command: Command):
        self.out_queue.put(command)
        self.credit.put("credit") 
        self._logger.debug(f"ui->con put {command}")
    
    async def _recv(self):
        # doesn't have to be 1:1 credit to response
        self.credit.get() # should block if credit.empty()
        self.credit.task_done()
        self._logger.debug(f"ui credits={self.credit.qsize()}")
        response = self.in_queue.get()
        self.in_queue.task_done()
        if not response==None:
            self._logger.debug(f"con->ui get {type(response)=}")
            return response
        else:
            self._logger.debug("con->ui get None")
        
    
    async def _xchg(self, command: Command):
        self._send(command)
        self._logger.debug(f"_xchg send {command}")
        while not self.credit.empty():
            return await self._recv()
    
    def xchg(self, command: Command):
        return self.loop.run_until_complete(self._xchg(command))
        

class ConnThreadWorker:
    _logger = logger.getChild("ConnThread")
    def __init__(self, host, port, in_queue: Queue, out_queue: Queue, loop):
        self.conn = Connection(host, port)
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.loop = loop #asyncio event loop

    async def _xchg(self):
        command = self.in_queue.get()
        self._logger.debug(f"ui->con get {command}")
        com = command.transfer

        if inspect.isasyncgenfunction(com):
            res = array.array('H')
            async for chunk in self.conn.transfer_multiple(command, latency=63356):
                self._logger.debug(f"net->con transfer {len(chunk)=} {type(chunk)=}")
                res.extend(chunk)
            self.out_queue.put(res)
            self._logger.debug(f"con->ui put {len(res)=} {type(res)=}")
                    
        else:
            res = await self.conn.transfer(command)
            self.out_queue.put(res)
            self._logger.debug(f"con->ui put {type(res)=}")

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
    cmd = SynchronizeCommand(cookie=123, raster_mode=1)
    worker.xchg(cmd)
    x_range = y_range = DACCodeRange(0, 2048, int((16384/2048)*256))
    cmd = RasterRegionCommand(x_range=x_range, y_range=y_range)
    # cmd = RasterScanCommand(cookie=123,
    #         x_range=x_range, y_range=y_range, dwell=2)
    worker.xchg(cmd)
    cmd = RasterPixelRunCommand(dwell=2, length=1024*1024)
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




