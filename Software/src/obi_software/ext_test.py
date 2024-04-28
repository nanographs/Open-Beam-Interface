import asyncio
import logging
from .beam_interface import Connection, _ExternalCtrlCommand, BeamType, setup_logging, ExternalCtrlCommand

setup_logging({"Command": logging.DEBUG})

async def run():
    conn = Connection('localhost', 2224)
    await conn._connect()
    print(type(conn._stream._writer.transport))
    await conn.transfer(ExternalCtrlCommand(enable=True, beam_type=BeamType.Ion))
    # await conn.transfer(ExternalCtrlCommand(enable=False, beam_type=BeamType.Ion))
    # await conn.transfer(ExternalCtrlCommand(enable=True, beam_type=BeamType.Electron))
    # await conn.transfer(ExternalCtrlCommand(enable=False, beam_type=BeamType.Electron))


asyncio.run(run())