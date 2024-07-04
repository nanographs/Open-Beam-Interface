from Gateware.applet.open_beam_interface.base_commands import *

'''
CommandSequence sends a sync command with the following configuration options:
output=
    - OutputMode.NoOutput
    - OutputMode.EightBit
    - OutputMode.SixteenBit
raster=
    - True
    - False
'''
seq = CommandSequence(output=OutputMode.NoOutput, raster=False)

'''Make sure beam is blanked before starting'''
seq.add(BlankCommand(enable=True))
'''Enable all of the external control relays'''
seq.add(ExternalCtrlCommand(enable=True))
'''Uncomment E or I beam to select what beam to use'''
## seq.add(BeamSelectCommand(beam_type=BeamType.Electron))
## seq.add(BeamSelectCommand(beam_type=BeamType.Ion))


'''Add your sequence of commands below here'''






'''Return beam control to the microscope'''
seq.add(ExternalCtrlCommand(enable=False))

'''Send the sequence of commands to the Open Beam Interface'''
await iface.write(bytes(seq))
'''Recieve the data back from the Open Beam Interface'''
response = await iface.read()
