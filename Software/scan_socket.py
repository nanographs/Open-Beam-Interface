import asyncio

class ConnectionManager:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None

    async def open_connection(self, future):
        while True:
            try:
                reader, writer = await asyncio.open_connection(
                    self.host, self.port)
                addr = writer.get_extra_info('peername')
                print(f'Connected to server at {addr}')
                future.set_result([reader,writer])
                break
            except ConnectionError:
                pass
    
    async def start_client(self):
        loop = asyncio.get_event_loop()
        future_con = loop.create_future()
        loop.create_task(self.open_connection(future_con))
        self.reader, self.writer = await future_con
    
    async def write(self, data):
        if not self.writer == None:
            self.writer.write(data)
            await self.writer.drain()
    
    async def read(self):
        if not self.writer == None:
            data = await self.reader.read()
            return data
        else:
            return None


import struct
from enum import Enum

class SyncType(Enum):
    Vector = 0
    Raster = 1

class CmdType(Enum):
    Synchronize     = 0
    RasterRegion    = 1
    RasterPixel     = 2
    RasterPixelRun  = 3
    VectorPixel     = 4


def ffp_8_8(num: float): #couldn't find builtin python function for this if there is one
    b_str = ""
    assert (num <= pow(2,8))
    for n in range(8, 0, -1):
        b = num//pow(2,n)
        b_str += str(int(b))
        num -= b*pow(2,n)
    for n in range(1,9):
        b = num//pow(2,-1*n)
        b_str += str(int(b))
        num -= b*pow(2,-1*n)
    return int(b_str, 2)

class OBICommands:
    def sync_cookie(cookie:int, sync_type: SyncType):
        assert(cookie <= 65535)
        cmd_sync = CmdType.Synchronize
        return struct.pack('>bHb', cmd_sync, cookie, sync_type) 
    def raster_region(x_start: int, x_count:int , x_step: int, 
                    y_start: int, y_count: int):
        x_step = ffp_8_8(x_step)
        assert (x_count <= 16384)
        assert (y_count <= 16384)
        assert (x_start <= x_count)
        assert (y_start <= y_count)
        cmd_type = CmdType.RasterRegion
        return struct.pack('>bHHHHH', cmd_type, x_start, x_count, x_step, y_start, y_count)

    def raster_pixel(dwell_time: int):
        assert (dwell_time <= 65535)
        cmd_type = CmdType.RasterPixel
        return struct.pack('>bH', cmd_type, dwell_time)
    
    def raster_pixel_run(length: int, dwell_time: int):
        assert (length <= 65535)
        assert (dwell_time <= 65535)
        cmd_type = CmdType.RasterPixelRun
        return struct.pack('>bHH', cmd_type, length, dwell_time)
    
    def vector_pixel(x_coord: int, y_coord:int, dwell_time: int):
        assert (x_coord <= 16384)
        assert (y_coord <= 16384)
        assert (dwell_time <= 65535)
        cmd_type = CmdType.VectorPixel
        return struct.pack('>bHHH', cmd_type, x_coord, y_coord, dwell_time)



class OBIInterface(ConnectionManager):
    cookies: {}
    n_cookie: 0
    stream_decoder: OBIStreamDecoder
def get_cookie(self): #use sequential numbers
    if n_cookie >= 65536:
        n_cookie = 0
    n_cookie += 1
    return n_cookie
async def send_cmds_with_sync(self, cmds: bytearray, sync_type: SyncType):
    all_cmds = bytearray()
    cookie = self.get_cookie()
    sync_cmd = OBICommands.sync_cookie(cookie, sync_type)
    all_cmds.extend(sync_cmd)
    all_cmds.extend(cmds)
    await self.write(all_cmds)
    self.cookies.update({cookie:cmds}) 
def find_cookies(self, data):
    n_cookies = data.count(b"\xff\xff")
    sync_index = 0
    while n_cookies > 0:
        prev_data = data[:sync_index]
        sync_index = data.index(b"\xff\xff", i_start)
        cookie = data[sync_index + 2: sync_index + 4]
        cookie_cmd = self.cookies.pop(cookie)
        self.stream.apply_cmd(cookie_cmd)
        data = data[sync_index + 4:]
        self.stream.process_data(data)
    data = data[sync_index:]
    self.stream.process_data(data)




