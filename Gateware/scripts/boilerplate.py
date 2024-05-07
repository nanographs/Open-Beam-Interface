from glasgowcontrib.applet.open_beam_interface.base_commands import *

'''
CommandSequence sends a sync command with the following configurations options:
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
seq.add(BlankCommand())
'''Enable all of the external control relays'''
seq.add(EnableExtCtrlCommand())
'''Uncomment E or I beam to select what beam to use'''
## seq.add(SelectEbeamCommand())
## seq.add(SelectIbeamCommand())

'''Add your seqence of commands below here'''






'''Return beam control to the microscope'''
seq.add(DisableExtCtrlCommand())

'''Send the seqence of commands to the Open Beam Interface'''
await iface.write(seq.message)
'''Recieve the data back from the Open Beam Interface'''
response = await iface.read()
