from glasgowcontrib.applet.open_beam_interface.base_commands import *

seq = CommandSequence()
## seq.add(Command().message)
## ...

await iface.write(seq)
response = await iface.read()
