from queue import Queue
import threading
import asyncio
from .beam_interface import Command, Connection

class UIThreadWorker:
    def __init__(self, in_queue: Queue, out_queue: Queue):
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.credit = Queue(maxsize=1) #arbitrary max-things-in-flight

    def send(self, command: Command):
        self.out_queue.put(command)
        self.credit.put("credit") 
        print(f"UI send {command}. credit: {self.credit.qsize()}")
    
    def recv(self):
        print(f"UI recv start. credit: {self.credit.qsize()}")
        # doesn't have to be 1:1 credit to response
        self.credit.get() # should block if credit.empty()
        self.credit.task_done()
        response = self.in_queue.get()
        print(f"UI recv {response}")
        self.in_queue.task_done()
        ## todo: process and display response
    
    def xchg(self, command: Command):
        self.send(command)
        while not self.credit.empty():
            self.recv()
        

class ConnThreadWorker:

    def __init__(self, in_queue: Queue, out_queue: Queue):
        self.in_queue = in_queue
        self.out_queue = out_queue
        # self.conn = Connection(host, port)

    def xchg(self):
        command = self.in_queue.get()
        print(f"CONN recv {command}")
        # response = await self.conn.transfer(command)
        response = f"{command} response"
        print(f"CONN send {response}")
        self.out_queue.put(response)
    
    def run(self):
        print(f"CONN run()")
        while not self.in_queue.empty():
            # await self.xchg()
            self.xchg()
        self.run()

def ui_thread(in_queue, out_queue):
    worker = UIThreadWorker(in_queue, out_queue)
    worker.xchg("Hello")
    worker.xchg("It's me")

def conn_thread(in_queue, out_queue):
    worker = ConnThreadWorker(in_queue, out_queue)
    worker.run()

ui_to_con = Queue()
con_to_ui = Queue()

ui = threading.Thread(target = ui_thread, args = [con_to_ui, ui_to_con])
con = threading.Thread(target = conn_thread, args = [ui_to_con, con_to_ui])

ui.start()
con.start()
# ui.join()
# con.join()




