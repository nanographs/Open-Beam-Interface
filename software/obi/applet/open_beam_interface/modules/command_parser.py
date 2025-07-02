from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.wiring import In, Out, flipped

from obi.commands.structs import CmdType
from obi.commands.low_level_commands import Command

class CommandParser(wiring.Component):
    usb_stream: In(stream.Signature(8))
    cmd_stream: Out(stream.Signature(Command))

    def elaborate(self, platform):
        m = Module()
        self.command = Signal(Command)
        m.d.comb += self.cmd_stream.payload.eq(self.command)
        self.command_reg = Signal(Command)
        array_length = Signal(16)

        self.is_started = Signal()
        with m.FSM() as fsm:
            m.d.comb += self.is_started.eq(fsm.ongoing("Type"))
            def goto_first_deserialized_state(from_type=self.command.type):
                with m.Switch(from_type):
                    for cmdtype, state_sequence in Command.deserialized_states.items():
                        with m.Case(cmdtype):
                            if len(state_sequence.keys()) > 0:
                                m.next = list(state_sequence.keys())[0]
                            else:
                                m.next = "Submit"

            with m.State("Type"):
                m.d.comb += self.usb_stream.ready.eq(1)
                with m.If(self.usb_stream.valid):
                    m.d.comb += self.command.type.eq(self.usb_stream.payload[4:8])
                    m.d.comb += self.command.payload.as_value()[0:4].eq(self.usb_stream.payload[0:4])
                    m.d.sync += self.command_reg.eq(self.command)
                    goto_first_deserialized_state()
                    

            def Deserialize(target, state, next_state):
                m.d.comb += self.command.eq(self.command_reg)
                #print(f'state: {state} -> next state: {next_state}')
                with m.State(state):
                    m.d.comb += self.usb_stream.ready.eq(1)
                    with m.If(self.usb_stream.valid):
                        m.d.sync += target.eq(self.usb_stream.payload)
                        m.next = next_state
            
            for state_sequence in Command.deserialized_states.values():
                for n, (state, offset) in enumerate(state_sequence.items()):
                    if n < len(state_sequence) - 1:
                        next_state = list(state_sequence.keys())[n+1]
                    elif n == len(state_sequence) - 1:
                        next_state = "Submit"
                    Deserialize(self.command_reg.as_value()[offset:offset+8], state, next_state)


            with m.State("Submit"):
                m.d.comb += self.command.eq(self.command_reg)
                with m.If(self.command.type == CmdType.Array):
                        m.d.sync += self.command_reg.type.eq(self.command.payload.array.cmdtype)
                        m.d.sync += self.command_reg.as_value()[4:].eq(0)
                        m.d.sync += array_length.eq(self.command.payload.array.array_length)
                        goto_first_deserialized_state(from_type=self.command.payload.array.cmdtype)
                with m.Else():
                    with m.If(self.cmd_stream.ready):
                        m.d.comb += self.cmd_stream.valid.eq(1)
                        with m.If(array_length != 0):
                            m.d.sync += array_length.eq(array_length - 1)
                            goto_first_deserialized_state()
                        with m.Else():
                            m.next = "Type"
        return m