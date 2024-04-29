import asyncio
import logging
import argparse
from ..beam_interface import (Connection, BeamType, setup_logging, _ExternalCtrlCommand, 
                            _BlankCommand, VectorPixelLinearRunCommand, _VectorPixelCommand)

setup_logging({"Command": logging.DEBUG})

parser = argparse.ArgumentParser()
parser.add_argument('--dwell', type=int, help="dwell time per pixel", default=2)
parser.add_argument('--loops', type=int, help="number of times to repeat pattern", default=1000)
args = parser.parse_args()
dwell = args.dwell



async def run():
    conn = Connection('localhost', 2224)
    start_points = [x for x in range(4096)]
    end_points = [x for x in range(12288, 16384)]
    def start_line(y):
        for x in start_points:
            yield x, y, dwell
    def end_line(y):
        for x in end_points:
            yield x, y, dwell
    await conn.transfer(_BlankCommand(enable=True, beam_type=BeamType.Ion)) ## set IO for blanking
    await conn.transfer(_ExternalCtrlCommand(enable=True, beam_type=BeamType.Ion)) ## take control of scan and blank

    async def test_pattern():
        await conn.transfer(_VectorPixelCommand(x_coord = 0, y_coord = 4096, dwell=0)) #move the beam
        await conn.transfer(_BlankCommand(enable=False, beam_type=BeamType.Ion)) ## unblank
        async for chunk in conn.transfer_multiple(VectorPixelLinearRunCommand(pattern_generator=start_line(4096)), 
                                            output_mode=0):
            pass
        await conn.transfer(_BlankCommand(enable=True, beam_type=BeamType.Ion)) ## blank

        await conn.transfer(_VectorPixelCommand(x_coord = 8192, y_coord = 4096, dwell=0)) #move the beam
        await conn.transfer(_BlankCommand(enable=False, beam_type=BeamType.Ion)) ## unblank
        async for chunk in conn.transfer_multiple(VectorPixelLinearRunCommand(pattern_generator=end_line(4096)), 
                                            output_mode=0):
            pass
        await conn.transfer(_BlankCommand(enable=True, beam_type=BeamType.Ion)) ## blank

        await conn.transfer(_VectorPixelCommand(x_coord = 0, y_coord = 12288, dwell=0)) #move the beam
        await conn.transfer(_BlankCommand(enable=False, beam_type=BeamType.Ion)) ## unblank
        async for chunk in conn.transfer_multiple(VectorPixelLinearRunCommand(pattern_generator=start_line(12288)), 
                                            output_mode=0):
            pass
        await conn.transfer(_BlankCommand(enable=True, beam_type=BeamType.Ion)) ## blank

        await conn.transfer(_VectorPixelCommand(x_coord = 8192, y_coord = 12288, dwell=0)) #move the beam
        await conn.transfer(_BlankCommand(enable=False, beam_type=BeamType.Ion)) ## unblank
        async for chunk in conn.transfer_multiple(VectorPixelLinearRunCommand(pattern_generator=end_line(12288)), 
                                            output_mode=0):
            pass
        await conn.transfer(_BlankCommand(enable=True, beam_type=BeamType.Ion)) ## blank

    for _ in range(args.loops):
        await test_pattern()
        #await conn.transfer(_ExternalCtrlCommand(enable=False, beam_type=BeamType.Ion)) ## yield control

asyncio.run(run())