from .beam_interface import *
from .threads import conn_thread, UIThreadWorker
from queue import Queue

class ExternalBeamCtrl:
    def __init__(self, beam_type: BeamType, worker: UIThreadWorker):
        self.beam_type = beam_type
        self.worker = worker
        self._in_control = False

    @property
    def in_control(self):
        # True if OBI board is electrically 
        # connected to X, Y, and Video signals
        return self._in_control
    
    def enable(self):
        self.worker.xchg(ExternalCtrlCommand(enable=1, beam_type=self.beam_type))
        self._in_control = True
    
    def disable(self):
        self.worker.xchg(ExternalCtrlCommand(enable=0, beam_type=self.beam_type))
        self._in_control = False
    

class OBIInterface:
    def __init__(self, worker: UIThreadWorker):
        self.worker = worker
        self.e_beam = ExternalBeamCtrl(BeamType.Electron, self.worker)
    
    def transfer_scan_cmd(self, command:Command, beam: ExternalBeamCtrl):
        if not beam.in_control:
            beam.enable()
        worker.xchg(command)
        beam.disable()

    def set_full_resolution(self, x_resolution, y_resolution):
        full_fov_pixels = max(x_resolution, y_resolution)
        step_size = int((16384/full_fov_pixels)*256)
        x_range = DACCodeRange(0, x_resolution, step_size)
        y_range = DACCodeRange(0, y_resolution, step_size)
        self.worker.xchg(_RasterRegionCommand(x_range=x_range, y_range=y_range))
    
    def capture_pixel_run(self, dwell, length):
        res = self.worker.xchg(_RasterPixelRunCommand(dwell=dwell, length=length))
        print(res)



def main():
    ui_to_con = Queue()
    con_to_ui = Queue()

    def ui_thread(in_queue, out_queue):
        loop = asyncio.new_event_loop()
        worker = UIThreadWorker(in_queue, out_queue, loop)
        iface = OBIInterface(worker)
        iface.set_full_resolution(1024, 2048)
        iface.capture(2)

    ui = threading.Thread(target = ui_thread, args = [con_to_ui, ui_to_con])
    con = threading.Thread(target = conn_thread, args = [ui_to_con, con_to_ui])

    ui.start()
    con.start()

main()