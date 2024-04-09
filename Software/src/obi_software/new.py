from .beam_interface import Connection, BeamType, Command, ExternalCtrlCommand

class ExternalBeamCtrl:
    def __init__(self, beam_type: BeamType):
        self.beam_type = beam_type
        self._in_control = False

    @property
    def in_control(self):
        # True if OBI board is electrically 
        # connected to X, Y, and Video signals
        return self._in_control
    
    def enable(self, conn):
        await conn.transfer(ExternalCtrlCommand(enable=1, beam_type=self.beam_type))
        self._in_control = True
    
    def disable(self, conn):
        await conn.transfer(ExternalCtrlCommand(enable=0, beam_type=self.beam_type))
        self._in_control = False
    

class OBIInterface:
    def __init__(self, port:int):
        self.conn = Connection('localhost', port)
        self.e_beam = ExternalBeamCtrl(BeamType.Electron)
    
    async def transfer_scan_cmd(self, command:Command, beam: ExternalBeamCtrl):
        if not beam.in_control:
            await beam.enable(self.conn)
        await self.conn.transfer(command)
        await beam.disable(self.conn)

    async def set_raster_resolution(self, x_range:DACCodeRange, y_range:DACCodeRange):
        await self.conn.transfer_cmd(_RasterRegionCommand(x_range=x_range, y_range=y_range))
    
    async def live_scan.