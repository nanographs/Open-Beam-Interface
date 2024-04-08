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
    
    async def transfer_cmd_e_beam(self, command:Command):
        if not self.e_beam.in_control:
            await self.e_beam.enable(self.conn)
        await self.conn.transfer(command)
        await self.e_beam.disable(self.conn)

