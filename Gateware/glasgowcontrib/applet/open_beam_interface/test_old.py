from ... import *
from . import OBIApplet



from amaranth.sim import Simulator

def duplicate(gen_fn, *args):
    return gen_fn(*args), gen_fn(*args)
class SimulationOBIInterface():
    def __init__(self, dut, lower):
        self.dut = dut
        self.lower = lower
        self.text_file = open("results.txt", "w+")

        self.bench_queue = []
        self.expected_stream = bytearray()

    def queue_sim(self, bench):
        self.bench_queue.append(bench)
    def run_sim(self):
        print("run sim")
        sim = Simulator(self.dut)

        def bench():
            for bench in self.bench_queue:
                while len(self.expected_stream) < 512:
                    try:
                        yield from bench
                    except RuntimeError: #raised StopIteration
                        break
                    finally:
                        yield from self.compare_against_expected()
            print("All done.")

        sim.add_clock(1e-6) # 1 MHz
        sim.add_sync_process(bench)
        with sim.write_vcd("applet_sim.vcd"):
            sim.run()
    
    def compare_against_expected(self):
        read_len = min(512, len(self.expected_stream))
        if read_len < 512:
            yield from self.lower.write(OBICommands.flush())
        data = yield from self.lower.read(read_len)
        self.text_file.write("\n READ: \n")
        self.text_file.write(str(list(data)))

        for n in range(read_len):
            #print(f'expected: {self.expected_stream[n]}, actual: {data[n]}')
            print(f'expected: {hex(self.expected_stream[n])}, actual: {hex(data[n])}')
            assert(data[n] == self.expected_stream[n])
        self.expected_stream = self.expected_stream[read_len:]
    
    def sim_vector_stream(self, stream_gen, *args):

        #read_gen, write_gen = duplicate(stream_gen, *args) 
        write_gen = stream_gen(*args)
    
        bytes_written = 0
        read_bytes_expected = 0

        sync_cmd = OBICommands.sync_cookie_vector()
        yield from self.lower.write(sync_cmd)
        self.text_file.write("\n WRITTEN: \n")
        self.text_file.write(str(list(sync_cmd)))
        self.expected_stream.extend([255,255])
        self.expected_stream.extend(sync_cmd[1:3])
        self.text_file.write("---->\n")

        while True:    
            try:
                if len(self.expected_stream) >= 512:
                    yield from self.compare_against_expected()
                else:
                    x, y, d = next(write_gen)
                    cmd = OBICommands.vector_pixel(x, y, d)
                    yield from self.lower.write(cmd)
                    self.expected_stream.extend(struct.pack('>H',d))
                    self.text_file.write(str(list(cmd)))
                    self.text_file.write("\n")
            except StopIteration:
                print("pattern complete")
                break

        raise StopIteration
    
    def sim_raster_region(self, x_start, x_count,
                            y_start, y_count, dwell_time, run_length):
        sync_cmd = OBICommands.sync_cookie_raster()
        yield from self.lower.write(sync_cmd)
        self.text_file.write("\n WRITTEN: \n")
        self.text_file.write(str(list(sync_cmd)))
        self.expected_stream.extend([255,255])
        self.expected_stream.extend(sync_cmd[1:3])

        x_step = 16384/max((x_count - x_start + 1),(y_count-y_start + 1))
        region_cmd = OBICommands.raster_region(x_start, x_count, x_step,
                            y_start, y_count)
        yield from self.lower.write(region_cmd)
        self.text_file.write(str(list(region_cmd)))

        dwell_cmd = OBICommands.raster_pixel_run(run_length, dwell_time)
        yield from self.lower.write(dwell_cmd)
        self.text_file.write(str(list(dwell_cmd)))
        self.text_file.write("---->\n")


        for y in range(y_count):
            for x in range(x_count):
                x_position = struct.pack('>H', int(x_start + x*x_step))
                self.expected_stream.extend(x_position)
                print(f'x position: {x_position}, expected len: {len(self.expected_stream)}, run length: {run_length}')
                #yield
                run_length -= 1
                if run_length == 0:
                    break
                if len(self.expected_stream) > 512:
                    yield from self.compare_against_expected()
            break


        raise StopIteration

    def sim_raster_pattern(self, x_start, x_count,
                        y_start, y_count, stream_gen, *args):

        #read_gen, write_gen = duplicate(stream_gen, *args)
        write_gen = stream_gen(*args)

        sync_cmd = OBICommands.sync_cookie_raster()
        yield from self.lower.write(sync_cmd)
        self.text_file.write("\n WRITTEN: \n")
        self.text_file.write(str(list(sync_cmd)))
        
        self.expected_stream.extend([255,255])
        self.expected_stream.extend(sync_cmd[1:3])

        x_step = 16384/max((x_count - x_start + 1),(y_count-y_start + 1))
        region_cmd = OBICommands.raster_region(x_start, x_count, x_step,
                            y_start, y_count)
        yield from self.lower.write(region_cmd)
        self.text_file.write(str(list(region_cmd)))

        run_length = max(512, (x_count*y_count))
        run_length_cmd = OBICommands.raster_pixel(run_length)
        yield from self.lower.write(run_length_cmd)
        self.text_file.write("---->\n")



        while True:    
            try:
                if len(self.expected_stream) >= 512:
                    yield from self.compare_against_expected()
                else:
                    print(f'run length: {run_length}, expected len: {len(self.expected_stream)}',)
                    d = next(write_gen)
                    run_length -= 1
                    d_bytes = struct.pack('>H', d)
                    yield from self.lower.write(d_bytes)
                    self.expected_stream.extend(struct.pack('>H',d))
                    self.text_file.write(str(list(d_bytes)))
                    self.text_file.write("\n")
                    if run_length == 0:
                        break
            except StopIteration:
                print("pattern complete")
                break

        raise StopIteration



        if args.sim:
            from glasgow.access.simulation import SimulationMultiplexerInterface, SimulationDemultiplexerInterface
            from glasgow.device.hardware import GlasgowHardwareDevice

            self.mux_interface = iface = SimulationMultiplexerInterface(OBIApplet)

            in_fifo = iface._in_fifo = iface.get_in_fifo(auto_flush=False, depth = 512)
            out_fifo = iface._out_fifo = iface.get_out_fifo(depth = 512)

            iface = SimulationDemultiplexerInterface(GlasgowHardwareDevice, OBIApplet, iface)

            dut = OBISubtarget(
                in_fifo = in_fifo, 
                out_fifo = out_fifo, 
                sim = args.sim, 
                loopback = args.loopback)
            
            sim_iface = SimulationOBIInterface(dut, iface)

            
            def vector_rectangle(x_width, y_height):
                for y in range(0, y_height):
                    for x in range(0, x_width):
                        yield [x, y, x+y]

            def raster_rectangle(x_width, y_height):
                for y in range(0, 5):
                    for x in range(0, x_width):
                        yield x+y
                
            bench1 = sim_iface.sim_vector_stream(vector_rectangle, 10,10)
            sim_iface.queue_sim(bench1)

            bench2 = sim_iface.sim_raster_region(255, 511, 0, 255, 2, 200)
            sim_iface.queue_sim(bench2)

            # bench3 = sim_iface.sim_raster_pattern(0, 255, 0, 2, raster_rectangle, 256, 3)
            # sim_iface.queue_sim(bench3)

            sim_iface.run_sim()


class OBIAppletTestCase(GlasgowAppletTestCase, applet=OBIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()