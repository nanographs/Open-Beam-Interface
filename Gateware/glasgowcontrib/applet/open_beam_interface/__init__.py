from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
import enum
import struct
import time
import asyncio
from amaranth import *
from amaranth import ShapeCastable
from amaranth.lib import enum, data, wiring
from amaranth.lib.fifo import SyncFIFOBuffered
from amaranth.lib.wiring import In, Out, flipped

from glasgow.support.logging import dump_hex
from glasgow.support.endpoint import ServerEndpoint
# from .base_commands import CommandType

# Overview of (linear) processing pipeline:
# 1. PC software (in: user input, out: bytes)
# 2. Glasgow software/framework (in: bytes, out: same bytes; vendor-provided)
# 3. Command deserializer (in: bytes; out: structured commands)
# 4. Command parser/executor (in: structured commands, out: DAC state changes and ADC sample strobes)
# 5. DAC (in: DAC words, out: analog voltage; Glasgow plug-in)
# 6. electron microscope
# 7. ADC (in: analog voltage; out: ADC words, Glasgow plug-in)
# 8. Image serializer (in: ADC words, out: image frames)
# 9. Configuration synchronizer (in: image frames, out: image pixels or synchronization frames)
# 10. Frame serializer (in: frames, out: bytes)
# 11. Glasgow software/framework (in: bytes, out: same bytes; vendor-provided)
# 12. PC software (in: bytes, out: displayed image)


def StreamSignature(data_layout):
    return wiring.Signature({
        "payload":  Out(data_layout),
        "valid": Out(1),
        "ready": In(1)
    })

class BlankRequest(data.Struct):
    enable: 1
    request: 1


#=========================================================================

class SkidBuffer(wiring.Component):
    def __init__(self, data_layout, *, depth):
        self.width = Shape.cast(data_layout).width
        self.depth = depth
        super().__init__({
            "i": In(StreamSignature(data_layout)),
            "o": Out(StreamSignature(data_layout)),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.fifo = fifo = \
            SyncFIFOBuffered(depth=self.depth, width=self.width)
        m.d.comb += [
            fifo.w_data.eq(self.i.payload),
            fifo.w_en.eq(self.i.valid),
            self.i.ready.eq(fifo.level <= 1),
            self.o.payload.eq(fifo.r_data),
            self.o.valid.eq(fifo.r_rdy),
            fifo.r_en.eq(self.o.ready),
        ]

        return m

#=========================================================================
BusSignature = wiring.Signature({
    "adc_clk":  Out(1),
    "adc_le_clk":   Out(1),
    "adc_oe":   Out(1),

    "dac_clk":  Out(1),
    "dac_x_le_clk": Out(1),
    "dac_y_le_clk": Out(1),

    "data_i":   In(15),
    "data_o":   Out(15),
    "data_oe":  Out(1),
})

DwellTime = unsigned(16)

class PipelinedLoopbackAdapter(wiring.Component):
    loopback_stream: In(unsigned(14))
    bus: Out(BusSignature)

    def __init__(self, adc_latency: int):
        self.adc_latency = adc_latency
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        prev_bus_adc_oe = Signal()
        adc_oe_falling = Signal()
        m.d.sync += prev_bus_adc_oe.eq(self.bus.adc_oe)
        m.d.comb += adc_oe_falling.eq(prev_bus_adc_oe & ~self.bus.adc_oe)

        shift_register = Signal(14*self.adc_latency)

        with m.If(adc_oe_falling):
            m.d.sync += shift_register.eq((shift_register << 14) | self.loopback_stream)

        m.d.comb += self.bus.data_i.eq(shift_register.word_select(self.adc_latency-1, 14))

        return m

class Transforms(data.Struct):
    xflip: 1
    yflip: 1
    rotate90: 1

class Flippenator(wiring.Component):
    transforms: In(Transforms)
    in_stream: In(StreamSignature(data.StructLayout({
        "dac_x_code": 14,
        "dac_y_code": 14,
        "blank": BlankRequest,
        "last":       1,
        
    })))
    out_stream: Out(StreamSignature(data.StructLayout({
        "dac_x_code": 14,
        "dac_y_code": 14,
        "blank": BlankRequest,
        "last":       1,
    })))
    def elaborate(self, platform):
        m = Module()
        a = Signal(14)
        b = Signal(14)
        with m.If(~self.out_stream.valid | (self.out_stream.valid & self.out_stream.ready)):
            m.d.comb += a.eq(Mux(self.transforms.rotate90, self.in_stream.payload.dac_x_code, self.in_stream.payload.dac_y_code))
            m.d.comb += b.eq(Mux(self.transforms.rotate90, self.in_stream.payload.dac_y_code, self.in_stream.payload.dac_x_code))
            m.d.sync += self.out_stream.payload.dac_x_code.eq(Mux(self.transforms.xflip, -a, a)) #>> xscale)
            m.d.sync += self.out_stream.payload.dac_y_code.eq(Mux(self.transforms.yflip, -b, b)) #>> yscale)
            m.d.sync += self.out_stream.payload.last.eq(self.in_stream.payload.last)
            m.d.sync += self.out_stream.payload.blank.eq(self.in_stream.payload.blank)
            m.d.sync += self.out_stream.valid.eq(self.in_stream.valid)
        m.d.comb += self.in_stream.ready.eq(self.out_stream.ready)
        return m
        


class BusController(wiring.Component):
    # FPGA-side interface
    dac_stream: In(StreamSignature(data.StructLayout({
        "dac_x_code": 14,
        "dac_y_code": 14,
        "blank":      BlankRequest,
        "last":       1,
    })))

    adc_stream: Out(StreamSignature(data.StructLayout({
        "adc_code": 14,
        "adc_ovf":  1,
        "last":     1,
    })))

    # IO-side interface
    bus: Out(BusSignature)
    inline_blank: Out(BlankRequest)

    def __init__(self, *, adc_half_period: int, adc_latency: int):
        assert (adc_half_period * 2) >= 6, "ADC period must be large enough for FSM latency"
        self.adc_half_period = adc_half_period
        self.adc_latency     = adc_latency

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        adc_cycles = Signal(range(self.adc_half_period))
        with m.If(adc_cycles == self.adc_half_period - 1):
            m.d.sync += adc_cycles.eq(0)
            m.d.sync += self.bus.adc_clk.eq(~self.bus.adc_clk)
        with m.Else():
            m.d.sync += adc_cycles.eq(adc_cycles + 1)
        # ADC and DAC share the bus and have to work in tandem. The ADC conversion starts simultaneously
        # with the DAC update, so the entire ADC period is available for DAC-scope-ADC propagation.
        m.d.comb += self.bus.dac_clk.eq(self.bus.adc_clk)


        # Queue; MSB = most recent sample, LSB = least recent sample
        accept_sample = Signal(self.adc_latency)
        # Queue; as above
        last_sample = Signal(self.adc_latency)

        m.submodules.skid_buffer = skid_buffer = \
            SkidBuffer(self.adc_stream.payload.shape(), depth=self.adc_latency)
        wiring.connect(m, flipped(self.adc_stream), skid_buffer.o)

        adc_stream_data = Signal.like(self.adc_stream.payload) # FIXME: will not be needed after FIFOs have shapes
        m.d.comb += [
            # Cat(adc_stream_data.adc_code,
            #     adc_stream_data.adc_ovf).eq(self.bus.i),
            adc_stream_data.last.eq(last_sample[self.adc_latency-1]),
            skid_buffer.i.payload.eq(adc_stream_data),
        ]

        dac_stream_data = Signal.like(self.dac_stream.payload)
        m.d.comb += self.inline_blank.eq(dac_stream_data.blank)

        m.d.comb += adc_stream_data.adc_code.eq(self.bus.data_i)

        stalled = Signal()

        with m.FSM():
            with m.State("ADC_Wait"):
                with m.If(self.bus.adc_clk & (adc_cycles == 0)):
                    m.d.comb += self.bus.adc_le_clk.eq(1)
                    m.d.comb += self.bus.adc_oe.eq(1) #give bus time to stabilize before sampling
                    m.next = "ADC_Read"

            with m.State("ADC_Read"):
                #m.d.comb += self.bus.adc_le_clk.eq(1)
                m.d.comb += self.bus.adc_oe.eq(1)
                # buffers up to self.adc_latency samples if skid_buffer.i.ready
                m.d.comb += skid_buffer.i.valid.eq(accept_sample[self.adc_latency-1])
                with m.If(self.dac_stream.valid & skid_buffer.i.ready):
                    # Latch DAC codes from input stream.
                    m.d.comb += self.dac_stream.ready.eq(1)
                    m.d.sync += dac_stream_data.eq(self.dac_stream.payload)
                    # Schedule ADC sample for these DAC codes to be output.
                    m.d.sync += accept_sample.eq(Cat(1, accept_sample))
                    # Carry over the flag for last sample [of averaging window] to the output.
                    m.d.sync += last_sample.eq(Cat(self.dac_stream.payload.last, last_sample))
                with m.Else():
                    # Leave DAC codes as they are.
                    # Schedule ADC sample for these DAC codes to be discarded.
                    m.d.sync += accept_sample.eq(Cat(0, accept_sample))
                    # The value of this flag is discarded, so it doesn't matter what it is.
                    m.d.sync += last_sample.eq(Cat(0, last_sample))
                m.next = "X_DAC_Write"

            with m.State("X_DAC_Write"):
                m.d.comb += [
                    self.bus.data_o.eq(dac_stream_data.dac_x_code),
                    self.bus.data_oe.eq(1),
                ]
                m.next = "X_DAC_Write_2"

            with m.State("X_DAC_Write_2"):
                m.d.comb += [
                    self.bus.data_o.eq(dac_stream_data.dac_x_code),
                    self.bus.data_oe.eq(1),
                    self.bus.dac_x_le_clk.eq(1),
                ]
                m.next = "Y_DAC_Write"

            with m.State("Y_DAC_Write"):
                m.d.comb += [
                    self.bus.data_o.eq(dac_stream_data.dac_y_code),
                    self.bus.data_oe.eq(1),
                ]
                m.next = "Y_DAC_Write_2"

            with m.State("Y_DAC_Write_2"):
                m.d.comb += [
                    self.bus.data_o.eq(dac_stream_data.dac_y_code),
                    self.bus.data_oe.eq(1),
                    self.bus.dac_y_le_clk.eq(1),
                ]
                m.next = "ADC_Wait"

        return m


#=========================================================================

class Supersampler(wiring.Component):
    dac_stream: In(StreamSignature(data.StructLayout({
        "dac_x_code": 14,
        "dac_y_code": 14,
        "dwell_time": 16,
        "blank": BlankRequest
    })))

    adc_stream: Out(StreamSignature(data.StructLayout({
        "adc_code":   14,
    })))

    super_dac_stream: Out(StreamSignature(data.StructLayout({
        "dac_x_code": 14,
        "dac_y_code": 14,
        "last":       1,
        "blank": BlankRequest
    })))

    super_adc_stream: In(StreamSignature(data.StructLayout({
        "adc_code":   14,
        "adc_ovf":    1,  # ignored
        "last":       1,
    })))

    ## debug info
    stall_cycles: Out(16)
    stall_count_reset: In(1)

    def __init__(self):
        super().__init__()

        self.dac_stream_data = Signal.like(self.dac_stream.payload)

    def elaborate(self, platform):
        m = Module()

        dwell_counter = Signal.like(self.dac_stream_data.dwell_time)
        m.d.comb += [
            self.super_dac_stream.payload.dac_x_code.eq(self.dac_stream_data.dac_x_code),
            self.super_dac_stream.payload.dac_y_code.eq(self.dac_stream_data.dac_y_code),
            self.super_dac_stream.payload.blank.eq(self.dac_stream_data.blank),
            self.super_dac_stream.payload.last.eq(dwell_counter == self.dac_stream_data.dwell_time),
        ]
        with m.If(self.stall_count_reset):
            m.d.sync += self.stall_cycles.eq(0)

        stalled = Signal()
        with m.FSM():
            with m.State("Wait"):
                m.d.comb += self.dac_stream.ready.eq(1)
                with m.If(self.dac_stream.valid):
                    m.d.sync += self.dac_stream_data.eq(self.dac_stream.payload)
                    m.d.sync += dwell_counter.eq(0)
                    # m.d.sync += delay_counter.eq(0)
                    m.next = "Generate"
                

            with m.State("Generate"):
                m.d.comb += self.super_dac_stream.valid.eq(1)
                with m.If(self.super_dac_stream.ready):
                    with m.If(self.super_dac_stream.payload.last):
                        m.next = "Wait"
                    with m.Else():
                        m.d.sync += dwell_counter.eq(dwell_counter + 1)

                        

        running_average = Signal.like(self.super_adc_stream.payload.adc_code)
        m.d.comb += self.adc_stream.payload.adc_code.eq(running_average)
        with m.FSM():
            with m.State("Start"):
                m.d.comb += self.super_adc_stream.ready.eq(1)
                with m.If(self.super_adc_stream.valid):
                    m.d.sync += running_average.eq(self.super_adc_stream.payload.adc_code)
                    with m.If(self.super_adc_stream.payload.last):
                        m.next = "Wait"
                    with m.Else():
                        m.next = "Average"

            with m.State("Average"):
                m.d.comb += self.super_adc_stream.ready.eq(1)
                with m.If(self.super_adc_stream.valid):
                    m.d.sync += running_average.eq((running_average + self.super_adc_stream.payload.adc_code) >> 1)
                    with m.If(self.super_adc_stream.payload.last):
                        m.next = "Wait"
                    with m.Else():
                        m.next = "Average"

            with m.State("Wait"):
                m.d.comb += self.adc_stream.valid.eq(1)
                with m.If(self.adc_stream.ready):
                    m.next = "Start"

        return m

#=========================================================================

class RasterRegion(data.Struct):
    x_start: 14 # UQ(14,0)
    x_count: 14 # UQ(14,0)
    x_step:  16 # UQ(8,8)
    y_start: 14 # UQ(14,0)
    y_count: 14 # UQ(14,0)
    y_step:  16 # UQ(8,8)


class RasterScanner(wiring.Component):
    FRAC_BITS = 8

    roi_stream: In(StreamSignature(RasterRegion))

    dwell_stream: In(StreamSignature(data.StructLayout({
        "dwell_time": DwellTime,
        "blank": BlankRequest,
    })))

    abort: In(1)
    #: Interrupt the scan in progress and fetch the next ROI from `roi_stream`.

    dac_stream: Out(StreamSignature(data.StructLayout({
        "dac_x_code": 14,
        "dac_y_code": 14,
        "dwell_time": DwellTime,
        "blank": BlankRequest
    })))

    def elaborate(self, platform):
        m = Module()

        region  = Signal.like(self.roi_stream.payload)

        x_accum = Signal(14 + self.FRAC_BITS)
        x_count = Signal.like(region.x_count)
        y_accum = Signal(14 + self.FRAC_BITS)
        y_count = Signal.like(region.y_count)
        m.d.comb += [
            self.dac_stream.payload.dac_x_code.eq(x_accum >> self.FRAC_BITS),
            self.dac_stream.payload.dac_y_code.eq(y_accum >> self.FRAC_BITS),
            self.dac_stream.payload.dwell_time.eq(self.dwell_stream.payload.dwell_time),
            self.dac_stream.payload.blank.eq(self.dwell_stream.payload.blank)
        ]

        with m.FSM():
            with m.State("Get-ROI"):
                m.d.comb += self.roi_stream.ready.eq(1)
                with m.If(self.roi_stream.valid):
                    m.d.sync += [
                        region.eq(self.roi_stream.payload),
                        x_accum.eq(self.roi_stream.payload.x_start << self.FRAC_BITS),
                        x_count.eq(self.roi_stream.payload.x_count - 1),
                        y_accum.eq(self.roi_stream.payload.y_start << self.FRAC_BITS),
                        y_count.eq(self.roi_stream.payload.y_count - 1),
                    ]
                    m.next = "Scan"

            with m.State("Scan"):
                m.d.comb += self.dwell_stream.ready.eq(self.dac_stream.ready)
                m.d.comb += self.dac_stream.valid.eq(self.dwell_stream.valid)
                with m.If(self.dac_stream.ready):
                    with m.If(self.abort):
                        m.next = "Get-ROI"
                with m.If(self.dwell_stream.valid & self.dac_stream.ready):
                    # AXI4-Stream §2.2.1
                    # > Once TVALID is asserted it must remain asserted until the handshake occurs.

                    with m.If(x_count == 0):
                        with m.If(y_count == 0):
                            m.next = "Get-ROI"
                        with m.Else():
                            m.d.sync += y_accum.eq(y_accum + region.y_step)
                            m.d.sync += y_count.eq(y_count - 1)

                        m.d.sync += x_accum.eq(region.x_start << self.FRAC_BITS)
                        m.d.sync += x_count.eq(region.x_count - 1)
                    with m.Else():
                        m.d.sync += x_accum.eq(x_accum + region.x_step)
                        m.d.sync += x_count.eq(x_count - 1)

        return m

#=========================================================================


Cookie = unsigned(16)
#: Arbitrary value for synchronization. When received, returned as-is in an USB IN frame.

class BeamType(enum.Enum, shape = 2):
    NoBeam              = 0
    Electron            = 1
    Ion                 = 2

class OutputMode(enum.Enum, shape = 2):
    SixteenBit          = 0
    EightBit            = 1
    NoOutput            = 2

# ===============================================================================================

class CmdType(enum.Enum, shape=5):
        Command1 = 1 # only type
        Command2 = 2 # type + payload bytes
        Command3 = 3 # type + payload bits
        Command4 = 4 # type + payload bits + payload bytes
        Synchronize = 0x00


class Command(data.Struct):
    

    # Only used for transfer via USB, where the command is split into octets.
    class Header(data.Struct):
        type: CmdType
        payload: 8 - Shape.cast(CmdType).width

    PAYLOAD_SIZE = { # type -> bytes
        CmdType.Command1: 0,
        CmdType.Command2: 4,
        CmdType.Command3: 0,
        CmdType.Command4: 4,
        CmdType.Synchronize: 2
    }
    # will be replaced by Amaranth's `Choice` when it is a part of the public API
    def payload_size_array(PAYLOAD_SIZE, Type):
        return Array([
        value if value in PAYLOAD_SIZE.values() else 0
        for value in range(1 << Shape.cast(Type).width)
        ])
    PAYLOAD_SIZE_ARRAY = payload_size_array(PAYLOAD_SIZE, CmdType)

    type: CmdType
    payload: data.UnionLayout({
        "command1": data.StructLayout({
            "reserved": 0,
        }),
        "command2": data.StructLayout({
            "reserved": 3,
            "data":     32,
        }),
        "command3": data.StructLayout({
            "reserved": 0,
            "payload":  3,
        }),
        "command4": data.StructLayout({
            "reserved": 2,
            "payload":  33,
        }),
        "synchronize": data.StructLayout({
            "reserved": 0,
            "payload": data.StructLayout({
                "mode": data.StructLayout({
                    "raster": 1,
                    "output": OutputMode,
                }),
                "cookie": 16
            })
        })
    })

    @classmethod
    def serialize(cls, type: CmdType, payload) -> bytes:
        dic = {"type": type, "payload": {**payload} }
        print(f"{dic=}")
        # https://amaranth-lang.org/docs/amaranth/latest/stdlib/data.html#amaranth.lib.data.Const
        command_bits = cls.const({"type": type,
                        "payload":
                        {**payload}}).as_value()
        print(f"{command_bits=}")
        command_length = cls.PAYLOAD_SIZE[type]

        # command_bits = data.Const(cls, {
        #     "type": type,
        #     "payload": {
        #         "reserved": 0,
        #         #**payload
        #     }
        # }).value
        return command_bits.to_bytes(command_length, byteorder="little")
    
        # usage: Command.serialize(Command.Type.Command4, payload=1234)


class CommandParser(wiring.Component):
    usb_stream: In(StreamSignature(8))
    cmd_stream: Out(StreamSignature(Command))

    def elaborate(self, platform):
        m = Module()

        command = Signal(Command)
        m.d.comb += self.cmd_stream.payload.eq(command)

        command_header = Signal(Command.Header)
        command_header_reg = Signal(Command.Header)
        m.d.comb += command.type.eq(command_header.type)
        m.d.comb += command.payload.as_value()[:len(command_header.payload)].eq(command_header.payload)

        payload_size = Command.PAYLOAD_SIZE_ARRAY[command_header.type]
        payload_parsed = Signal(range(max(Command.PAYLOAD_SIZE_ARRAY)))

        command_reg = Signal(Command)

        with m.FSM():
            with m.State("Type"):
                m.d.comb += self.usb_stream.ready.eq(1)
                m.d.comb += command_header.eq(self.usb_stream.payload)
                m.d.comb += command.type.eq(command_header.type)
                m.d.comb += command.payload.as_value()[:len(command_header.payload)].eq(command_header.payload)

                with m.If(self.usb_stream.valid):
                    with m.If(payload_size == 0):
                        m.d.comb += self.cmd_stream.valid.eq(1)
                        m.d.comb += self.usb_stream.ready.eq(self.cmd_stream.ready)
                    with m.Else():
                        m.d.sync += command_header_reg.eq(self.usb_stream.payload)
                        m.next = "Payload"

            with m.State("Payload"):
                m.d.comb += command_header.eq(command_header_reg)
                m.d.comb += command.type.eq(command_header.type)
                m.d.comb += command.payload.as_value()[:len(command_header.payload)].eq(command_header.payload)

                with m.If(self.usb_stream.valid):
                    m.d.sync += (command_reg.payload.as_value()[len(command_header.payload):]
                        .word_select(payload_parsed, 8)).eq(self.usb_stream.payload)
                    m.d.sync += payload_parsed.eq(payload_parsed + 1)
                    with m.If(payload_parsed + 1 == payload_size):
                        m.next = "Submit_with_payload"
            
            with m.State("Submit_with_payload"):
                m.d.comb += command.eq(command_reg)
                m.d.comb += self.cmd_stream.valid.eq(1)
                with m.If(self.cmd_stream.ready):
                    m.next = "Type"
        return m


# ===============================================================================================

# class CommandParser(wiring.Component):
#     usb_stream: In(StreamSignature(8))
#     cmd_stream: Out(StreamSignature(Command))

#     def elaborate(self, platform):
#         m = Module()

        command = Signal(Command)
        m.d.comb += self.cmd_stream.payload.eq(command)

        command_header = Signal(Command.Header)
        command_header_reg = Signal(Command.Header)
        m.d.comb += command.type.eq(command_header.type)
        m.d.comb += command.payload.as_value()[:len(command_header.payload)].eq(command_header.payload)

        payload_size = Command.PAYLOAD_SIZE_ARRAY[command_header.type]
        payload_parsed = Signal(range(max(Command.PAYLOAD_SIZE_ARRAY)))

        command_reg = Signal(Command)

        with m.FSM():
            with m.State("Type"):
                m.d.comb += self.usb_stream.ready.eq(1)
                m.d.comb += command_header.eq(self.usb_stream.payload)
                m.d.comb += command.type.eq(command_header.type)
                m.d.comb += command.payload.as_value()[:len(command_header.payload)].eq(command_header.payload)

                with m.If(self.usb_stream.valid):
                    with m.If(payload_size == 0):
                        m.d.comb += self.cmd_stream.valid.eq(1)
                        m.d.comb += self.usb_stream.ready.eq(self.cmd_stream.ready)
                    with m.Else():
                        m.d.sync += command_header_reg.eq(self.usb_stream.payload)
                        m.next = "Payload"

            with m.State("Payload"):
                m.d.comb += command_header.eq(command_header_reg)
                m.d.comb += command.type.eq(command_header.type)
                m.d.comb += command.payload.as_value()[:len(command_header.payload)].eq(command_header.payload)

                with m.If(self.usb_stream.valid):
                    m.d.sync += (command_reg.payload.as_value()[len(command_header.payload):]
                        .word_select(payload_parsed, 8)).eq(self.usb_stream.payload)
                    m.d.sync += payload_parsed.eq(payload_parsed + 1)
                    with m.If(payload_parsed + 1 == payload_size):
                        m.next = "Submit_with_payload"
            
            with m.State("Submit_with_payload"):
                m.d.comb += command.eq(command_reg)
                m.d.comb += self.cmd_stream.valid.eq(1)
                with m.If(self.cmd_stream.ready):
                    m.next = "Type"
        return m


# ===============================================================================================

# class CommandParser(wiring.Component):
#     usb_stream: In(StreamSignature(8))
#     cmd_stream: Out(StreamSignature(Command))

#     def elaborate(self, platform):
#         m = Module()

#         command = Signal(Command)
#         m.d.comb += self.cmd_stream.payload.eq(command)

#         with m.FSM():
#             with m.State("Type"):
#                 m.d.comb += self.usb_stream.ready.eq(1)
#                 m.d.sync += command.type.eq(self.usb_stream.payload[:5])
#                 m.d.sync += command.small_payload.eq(self.usb_stream.payload[5:])
#                 with m.If(self.usb_stream.valid):
#                     with m.Switch(self.usb_stream.payload[:5]):
#                         with m.Case(Command.Type.Synchronize):
#                             m.next = "Payload_Synchronize_1_High"

#                         with m.Case(Command.Type.Abort):
#                             m.next = "Submit"

#                         with m.Case(Command.Type.Flush):
#                             m.next = "Submit"

#                         with m.Case(Command.Type.Delay):
#                             m.next = "Payload_Delay_High"

#                         with m.Case(Command.Type.ExtCtrl):
#                             m.next = "Submit"
                        
#                         with m.Case(Command.Type.BeamSelect):
#                             m.next = "Submit"

#                         with m.Case(Command.Type.Blank):
#                             m.next = "Submit"
                        
#                         with m.Case(Command.Type.RasterRegion):
#                             m.next = "Payload_Raster_Region_1_High"

#                         with m.Case(Command.Type.RasterPixel): # actually an array
#                             m.next = "Payload_Raster_Pixel_Count_High"

#                         with m.Case(Command.Type.RasterPixelRun):
#                             m.next = "Payload_Raster_Pixel_Run_1_High"

#                         with m.Case(Command.Type.RasterPixelFreeRun):
#                             m.next = "Payload_Raster_Pixel_FreeRun_High"

#                         with m.Case(Command.Type.VectorPixel):
#                             m.next = "Payload_Vector_Pixel_1_High"
                        
#                         with m.Case(Command.Type.VectorPixelMinDwell):
#                             m.d.sync += command.payload.vector_pixel.dwell_time.eq(0)
#                             m.next = "Payload_Vector_Pixel_MinDwell_1_High"

#             def Deserialize(target, state, next_state):
#                 #print(f'state: {state} -> next state: {next_state}')
#                 with m.State(state):
#                     m.d.comb += self.usb_stream.ready.eq(1)
#                     with m.If(self.usb_stream.valid):
#                         m.d.sync += target.eq(self.usb_stream.payload)
#                         m.next = next_state

#             def DeserializeWord(target, state_prefix, next_state):
#                 # print(f'\tdeserializing: {state_prefix} to {next_state}')
#                 Deserialize(target[8:16],
#                     f"{state_prefix}_High", f"{state_prefix}_Low")
#                 Deserialize(target[0:8],
#                     f"{state_prefix}_Low",  next_state)

#             DeserializeWord(command.payload.synchronize.cookie,
#                 "Payload_Synchronize_1", "Submit")

#             DeserializeWord(command.payload.delay,
#                 "Payload_Delay", "Submit")

#             DeserializeWord(command.payload.raster_region.x_start,
#                 "Payload_Raster_Region_1", "Payload_Raster_Region_2_High")
#             DeserializeWord(command.payload.raster_region.x_count,
#                 "Payload_Raster_Region_2", "Payload_Raster_Region_3_High")
#             DeserializeWord(command.payload.raster_region.x_step,
#                 "Payload_Raster_Region_3", "Payload_Raster_Region_4_High")
#             DeserializeWord(command.payload.raster_region.y_start,
#                 "Payload_Raster_Region_4", "Payload_Raster_Region_5_High")
#             DeserializeWord(command.payload.raster_region.y_count,
#                 "Payload_Raster_Region_5", "Payload_Raster_Region_6_High")
#             DeserializeWord(command.payload.raster_region.y_step,
#                 "Payload_Raster_Region_6", "Submit")

#             raster_pixel_count = Signal(16)
#             DeserializeWord(raster_pixel_count,
#                 "Payload_Raster_Pixel_Count", "Payload_Raster_Pixel_Array_High")
#             DeserializeWord(command.payload.raster_pixel,
#                 "Payload_Raster_Pixel_Array", "Payload_Raster_Pixel_Array_Submit")
#             with m.State("Payload_Raster_Pixel_Array_Submit"):
#                 m.d.comb += self.cmd_stream.valid.eq(1)
#                 with m.If(self.cmd_stream.ready):
#                     with m.If(raster_pixel_count == 0):
#                         m.next = "Type"
#                     with m.Else():
#                         m.d.sync += raster_pixel_count.eq(raster_pixel_count - 1)
#                         m.next = "Payload_Raster_Pixel_Array_High"

#             DeserializeWord(command.payload.raster_pixel_run.length,
#                 "Payload_Raster_Pixel_Run_1", "Payload_Raster_Pixel_Run_2_High")
#             DeserializeWord(command.payload.raster_pixel_run.dwell_time,
#                 "Payload_Raster_Pixel_Run_2", "Submit")

#             DeserializeWord(command.payload.raster_pixel,
#                 "Payload_Raster_Pixel_FreeRun", "Submit")

#             DeserializeWord(command.payload.vector_pixel.x_coord,
#                 "Payload_Vector_Pixel_1", "Payload_Vector_Pixel_2_High")
#             DeserializeWord(command.payload.vector_pixel.y_coord,
#                 "Payload_Vector_Pixel_2", "Payload_Vector_Pixel_3_High")
#             DeserializeWord(command.payload.vector_pixel.dwell_time,
#                 "Payload_Vector_Pixel_3", "Submit")
            
#             DeserializeWord(command.payload.vector_pixel.x_coord,
#                 "Payload_Vector_Pixel_MinDwell_1", "Payload_Vector_Pixel_MinDwell_2_High")
#             DeserializeWord(command.payload.vector_pixel.y_coord,
#                 "Payload_Vector_Pixel_MinDwell_2", "Submit")

#             with m.State("Submit"):
#                 m.d.comb += self.cmd_stream.valid.eq(1)
#                 with m.If(self.cmd_stream.ready):
#                     m.next = "Type"

#         return m

#=========================================================================
class CommandExecutor(wiring.Component):
    cmd_stream: In(StreamSignature(Command))
    img_stream: Out(StreamSignature(unsigned(16)))

    bus: Out(BusSignature)
    inline_blank: In(BlankRequest)

    #: Active if `Synchronize`, `Flush`, or `Abort` was the last received command.
    flush: Out(1)

    default_transforms: In(Transforms)
    # Input to Scan/Signal Selector Relay Board
    ext_ctrl_enable: Out(1)
    beam_type: Out(BeamType)
    # Input to Blanking control board
    blank_enable: Out(1, reset=1)

    #Input to Serializer
    output_mode: Out(2)


    def __init__(self, *, adc_latency=6):
        self.adc_latency = 6
        self.supersampler = Supersampler()
        self.flippenator = Flippenator()
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        delay_counter = Signal(DwellTime)

        m.submodules.bus_controller = bus_controller = BusController(adc_half_period=3, adc_latency=self.adc_latency)
        m.submodules.supersampler   = self.supersampler
        m.submodules.flippenator    = self.flippenator
        m.submodules.raster_scanner = self.raster_scanner = RasterScanner()

        wiring.connect(m, self.supersampler.super_dac_stream, self.flippenator.in_stream)
        wiring.connect(m, self.flippenator.out_stream, bus_controller.dac_stream)
        wiring.connect(m, bus_controller.adc_stream, self.supersampler.super_adc_stream)
        wiring.connect(m, flipped(self.bus), bus_controller.bus)
        m.d.comb += self.inline_blank.eq(bus_controller.inline_blank)

        vector_stream = StreamSignature(data.StructLayout({
            "dac_x_code": 14,
            "dac_y_code": 14,
            "dwell_time": DwellTime,
            "blank": BlankRequest
        })).create()


        raster_mode = Signal()
        output_mode = Signal(2)
        command = Signal.like(self.cmd_stream.payload)
        with m.If(raster_mode):
            wiring.connect(m, self.raster_scanner.dac_stream, self.supersampler.dac_stream)
        with m.Else():
            wiring.connect(m, vector_stream, self.supersampler.dac_stream)

        in_flight_pixels = Signal(4) # should never overflow
        submit_pixel = Signal()
        retire_pixel = Signal()
        m.d.sync += in_flight_pixels.eq(in_flight_pixels + submit_pixel - retire_pixel)

        next_blank_enable = Signal()
        m.domains.dac_clk = dac_clk =  ClockDomain(local=True)
        m.d.comb += dac_clk.clk.eq(self.bus.dac_clk)
        m.d.dac_clk += self.blank_enable.eq(next_blank_enable)
        
        sync_blank = Signal(BlankRequest) #Outgoing synchronous blank state
        with m.If(submit_pixel):
            m.d.sync += sync_blank.request.eq(0)
        async_blank = Signal(BlankRequest)

        with m.If(self.inline_blank.request): #Incoming synchronous blank state
            m.d.sync += next_blank_enable.eq(self.inline_blank.enable)
        # sync blank requests are fulfilled before async blank requests
        with m.Else():
            with m.If(async_blank.request):
                m.d.sync += next_blank_enable.eq(async_blank.enable)
                m.d.sync += async_blank.request.eq(0)
            


        run_length = Signal.like(command.payload.raster_pixel_run.length)
        raster_region = Signal.like(command.payload.raster_region)
        m.d.comb += [
            self.raster_scanner.roi_stream.payload.eq(raster_region),
            vector_stream.payload.eq(command.payload.vector_pixel)
        ]

        sync_req = Signal()
        sync_ack = Signal()

        with m.FSM():
            with m.State("Fetch"):
                m.d.comb += self.cmd_stream.ready.eq(1)
                with m.If(self.cmd_stream.valid):
                    m.d.sync += command.eq(self.cmd_stream.payload)
                    m.next = "Execute"

            with m.State("Execute"):
                m.d.sync += self.flush.eq(0)

                with m.Switch(command.type):
                    with m.Case(Command.Type.Synchronize):
                        m.d.sync += self.flush.eq(1)
                        m.d.comb += sync_req.eq(1)
                        with m.If(sync_ack):
                            m.d.sync += raster_mode.eq(command.payload.synchronize.mode.raster)
                            m.d.sync += output_mode.eq(command.payload.synchronize.mode.output)
                            m.next = "Fetch"

                    with m.Case(Command.Type.Abort):
                        m.d.sync += self.flush.eq(1)
                        m.d.comb += self.raster_scanner.abort.eq(1)
                        m.next = "Fetch"

                    with m.Case(Command.Type.Flush):
                        m.d.sync += self.flush.eq(1)
                        m.next = "Fetch"

                    with m.Case(Command.Type.Delay):
                        with m.If(delay_counter == command.payload.delay):
                            m.d.sync += delay_counter.eq(0)
                            m.next = "Fetch"
                        with m.Else():
                            m.d.sync += delay_counter.eq(delay_counter + 1)

                    with m.Case(Command.Type.ExtCtrl):
                        #Don't change control in the middle of previously submitted pixels
                        with m.If(self.supersampler.dac_stream.ready):
                            m.d.sync += self.ext_ctrl_enable.eq(command.payload.external_ctrl.enable)
                            m.next = "Fetch"
                    
                    with m.Case(Command.Type.BeamSelect):
                        #Don't change control in the middle of previously submitted pixels
                        with m.If(self.supersampler.dac_stream.ready):
                            m.d.sync += self.beam_type.eq(command.payload.beam_type)
                            m.next = "Fetch"

                    with m.Case(Command.Type.Blank):
                        with m.If(command.payload.blank.inline):
                            m.d.sync += sync_blank.enable.eq(command.payload.blank.enable)
                            m.d.sync += sync_blank.request.eq(1)
                            m.next = "Fetch"
                        with m.Else():
                            #Don't blank in the middle of previously submitted pixels
                            with m.If(self.supersampler.dac_stream.ready):
                                m.d.sync += async_blank.enable.eq(command.payload.blank.enable)
                                m.d.sync += async_blank.request.eq(1)
                                m.next = "Fetch"

                    with m.Case(Command.Type.FlipX, Command.Type.UnFlipX):
                        m.d.sync += self.flippenator.transforms.xflip.eq(command.payload.transform.xflip ^ self.default_transforms.xflip)
                    
                    with m.Case(Command.Type.FlipY, Command.Type.UnFlipY):
                        m.d.sync += self.flippenator.transforms.yflip.eq(command.payload.transform.yflip ^ self.default_transforms.yflip)
                    
                    with m.Case(Command.Type.Rotate90, Command.Type.UnRotate90):
                        m.d.sync += self.flippenator.transforms.rotate90.eq(command.payload.transform.rotate90 ^ self.default_transforms.rotate90)

                    with m.Case(Command.Type.RasterRegion):
                        m.d.sync += raster_region.eq(command.payload.raster_region)
                        m.d.comb += [
                            self.raster_scanner.roi_stream.valid.eq(1),
                            self.raster_scanner.roi_stream.payload.eq(command.payload.raster_region),
                        ]
                        with m.If(self.raster_scanner.roi_stream.ready):
                            m.next = "Fetch"

                    with m.Case(Command.Type.RasterPixel):
                        m.d.comb += [
                            self.raster_scanner.dwell_stream.valid.eq(1),
                            self.raster_scanner.dwell_stream.payload.dwell_time.eq(command.payload.raster_pixel),
                            self.raster_scanner.dwell_stream.payload.blank.eq(sync_blank)
                        ]
                        with m.If(self.raster_scanner.dwell_stream.ready):
                            m.d.comb += submit_pixel.eq(1)
                            m.next = "Fetch"

                    with m.Case(Command.Type.RasterPixelRun):
                        m.d.comb += [
                            self.raster_scanner.dwell_stream.valid.eq(1),
                            self.raster_scanner.dwell_stream.payload.dwell_time.eq(command.payload.raster_pixel_run.dwell_time),
                            self.raster_scanner.dwell_stream.payload.blank.eq(sync_blank)
                        ]
                        with m.If(self.raster_scanner.dwell_stream.ready):
                            m.d.comb += submit_pixel.eq(1)
                            with m.If(run_length == command.payload.raster_pixel_run.length):
                                m.d.sync += run_length.eq(0)
                                m.next = "Fetch"
                            with m.Else():
                                m.d.sync += run_length.eq(run_length + 1)

                    with m.Case(Command.Type.RasterPixelFreeRun):
                        m.d.comb += [
                            self.raster_scanner.roi_stream.payload.eq(raster_region),
                            self.raster_scanner.dwell_stream.payload.dwell_time.eq(command.payload.raster_pixel),
                            self.raster_scanner.dwell_stream.payload.blank.eq(sync_blank)
                        ]
                        with m.If(self.cmd_stream.valid):
                            m.d.comb += self.raster_scanner.abort.eq(1)
                            # `abort` only takes effect on the next opportunity!
                            with m.If(in_flight_pixels == 0):
                                m.next = "Fetch"
                        with m.Else():
                            # resynchronization is mandatory after this command
                            m.d.comb += self.raster_scanner.roi_stream.valid.eq(1)
                            m.d.comb += self.raster_scanner.dwell_stream.valid.eq(1)
                            with m.If(self.raster_scanner.dwell_stream.ready):
                                m.d.comb += submit_pixel.eq(1)


                    with m.Case(Command.Type.VectorPixel, Command.Type.VectorPixelMinDwell):
                        m.d.comb += vector_stream.valid.eq(1)
                        m.d.comb += vector_stream.payload.blank.eq(sync_blank)
                        with m.If(vector_stream.ready):
                            m.d.comb += submit_pixel.eq(1)
                            m.next = "Fetch"

        with m.FSM():
            with m.State("Imaging"):
                m.d.comb += [
                    self.img_stream.payload.eq(self.supersampler.adc_stream.payload.adc_code),
                    self.img_stream.valid.eq(self.supersampler.adc_stream.valid),
                    self.supersampler.adc_stream.ready.eq(self.img_stream.ready),
                    retire_pixel.eq(self.supersampler.adc_stream.valid & self.img_stream.ready),
                    self.output_mode.eq(output_mode) #input to Serializer
                ]
                with m.If((in_flight_pixels == 0) & sync_req):
                    m.next = "Write_FFFF"

            with m.State("Write_FFFF"):
                m.d.comb += [
                    self.img_stream.payload.eq(0xffff),
                    self.img_stream.valid.eq(1),
                ]
                with m.If(self.img_stream.ready):
                    m.next = "Write_cookie"

            with m.State("Write_cookie"):
                m.d.comb += [
                    self.img_stream.payload.eq(command.payload.synchronize.cookie),
                    self.img_stream.valid.eq(1),
                ]
                with m.If(self.img_stream.ready):
                    m.d.comb += sync_ack.eq(1)
                    m.next = "Imaging"

        return m

#=========================================================================
class ImageSerializer(wiring.Component):
    img_stream: In(StreamSignature(unsigned(16)))
    usb_stream: Out(StreamSignature(8))
    output_mode: In(2)

    def elaborate(self, platform):
        m = Module()

        low = Signal(8)

        with m.FSM():
            with m.State("High"):
                with m.If(self.output_mode == OutputMode.NoOutput):
                    m.d.comb += self.img_stream.ready.eq(1) #consume and destroy image stream
                with m.Else():
                    m.d.comb += self.usb_stream.payload.eq(self.img_stream.payload[8:16])
                    m.d.comb += self.usb_stream.valid.eq(self.img_stream.valid)
                    m.d.comb += self.img_stream.ready.eq(self.usb_stream.ready)
                    with m.If(self.output_mode == OutputMode.SixteenBit):
                        m.d.sync += low.eq(self.img_stream.payload[0:8])
                        with m.If(self.usb_stream.ready & self.img_stream.valid):
                            m.next = "Low"
                    with m.If(self.output_mode == OutputMode.EightBit):
                        m.next = "High"

            with m.State("Low"):
                m.d.comb += self.usb_stream.payload.eq(low)
                m.d.comb += self.usb_stream.valid.eq(1)
                with m.If(self.usb_stream.ready):
                    m.next = "High"

        return m

#=========================================================================

from amaranth.build import *
from glasgow.gateware.pads import Pads

obi_resources  = [
    Resource("control", 0,
        Subsignal("power_good", Pins("K1", dir="o")), # D17
        #Subsignal("D18", Pins("J1", dir="o")), # D18
        Subsignal("x_latch", Pins("H3", dir="o")), # D19
        Subsignal("y_latch", Pins("H1", dir="o")), # D20
        Subsignal("a_enable", Pins("G3", dir="o", invert=True)), # D21
        Subsignal("a_latch", Pins("H2", dir="o")), # D22
        Subsignal("d_clock", Pins("F3", dir="o", invert=True)), # D23
        Subsignal("a_clock", Pins("G1", dir="o", invert=True)), # D24
        Attrs(IO_STANDARD="SB_LVCMOS33")
    ),

    Resource("data", 0, Pins("B2 C4 B1 C3 C2 C1 D3 D1 F4 G2 E3 F1 E2 F2", dir="io"), # ; E1 D2
        Attrs(IO_STANDARD="SB_LVCMOS33")
    ),
]

class OBISubtarget(wiring.Component):
    def __init__(self, *, pads, out_fifo, in_fifo, led, control, data, 
                        benchmark_counters = None, sim=False, loopback=False,
                        xflip = False, yflip = False, rotate90 = False):
        self.pads = pads
        self.out_fifo = out_fifo
        self.in_fifo  = in_fifo
        self.sim = sim
        self.loopback = loopback
        self.xflip = xflip
        self.yflip = yflip
        self.rotate90 = rotate90

        if not benchmark_counters == None:
            self.benchmark = True
            out_stall_events, out_stall_cycles, stall_count_reset = benchmark_counters
            self.out_stall_events = out_stall_events
            self.out_stall_cycles = out_stall_cycles
            self.stall_count_reset = stall_count_reset
        else:
            self.benchmark = False

        self.led = led
        self.control = control
        self.data = data

    def elaborate(self, platform):
        m = Module()

        m.submodules.parser     = parser     = CommandParser()
        m.submodules.executor   = executor   = CommandExecutor()
        m.submodules.serializer = serializer = ImageSerializer()

        if self.xflip:
            m.d.comb += executor.default_transforms.xflip.eq(1)
        if self.yflip:
            m.d.comb += executor.default_transforms.yflip.eq(1)
        if self.rotate90:
            m.d.comb += executor.default_transforms.rotate90.eq(1)
        

        if self.loopback:
            m.submodules.loopback_adapter = loopback_adapter = PipelinedLoopbackAdapter(executor.adc_latency)
            wiring.connect(m, executor.bus, flipped(loopback_adapter.bus))

            loopback_dwell_time = Signal()
            if self.loopback:
                m.d.sync += loopback_dwell_time.eq(executor.cmd_stream.payload.type == Command.Type.RasterPixel)

            with m.If(loopback_dwell_time):
                m.d.comb += loopback_adapter.loopback_stream.eq(executor.supersampler.dac_stream_data.dwell_time)
            with m.Else():
                m.d.comb += loopback_adapter.loopback_stream.eq(executor.supersampler.super_dac_stream.payload.dac_x_code)


        wiring.connect(m, parser.cmd_stream, executor.cmd_stream)
        wiring.connect(m, executor.img_stream, serializer.img_stream)

        if self.sim:
            m.submodules.out_fifo = self.out_fifo
            m.submodules.in_fifo = self.in_fifo

        m.d.comb += [
            parser.usb_stream.payload.eq(self.out_fifo.r_data),
            parser.usb_stream.valid.eq(self.out_fifo.r_rdy),
            self.out_fifo.r_en.eq(parser.usb_stream.ready),
            self.in_fifo.w_data.eq(serializer.usb_stream.payload),
            self.in_fifo.w_en.eq(serializer.usb_stream.valid),
            serializer.usb_stream.ready.eq(self.in_fifo.w_rdy),
            self.in_fifo.flush.eq(executor.flush),
            serializer.output_mode.eq(executor.output_mode)
        ]

        if self.benchmark:
            m.d.comb += self.out_stall_cycles.eq(executor.supersampler.stall_cycles)
            m.d.comb += executor.supersampler.stall_count_reset.eq(self.stall_count_reset)
            out_stall_event = Signal()
            begin_write = Signal()
            with m.If(self.stall_count_reset):
                # m.d.sync += self.out_stall_cycles.eq(0)
                m.d.sync += self.out_stall_events.eq(0)
                m.d.sync += out_stall_event.eq(0)
                m.d.sync += begin_write.eq(0)
            with m.Else():
                with m.If(self.out_fifo.r_rdy):
                    m.d.sync += begin_write.eq(1)
                with m.If(begin_write):
                    with m.If(~self.out_fifo.r_rdy):
                        # with m.If(~(self.out_stall_cycles >= 65536)):
                        #     m.d.sync += self.out_stall_cycles.eq(self.out_stall_cycles + 1)
                        with m.If(~out_stall_event):
                            m.d.sync += out_stall_event.eq(1)
                            with m.If(~(self.out_stall_events >= 65536)):
                                m.d.sync += self.out_stall_events.eq(self.out_stall_events + 1)
                    with m.Else():
                        m.d.sync += out_stall_event.eq(0)
        
        


        if not self.sim:
            led = self.led
            control = self.control
            data = self.data

            m.d.comb += led.o.eq(~serializer.usb_stream.ready)

            def connect_pin(pin_name: str, signal):
                pin_name += "_t"
                if hasattr(self.pads, pin_name):
                    m.d.comb += getattr(self.pads, pin_name).oe.eq(1)
                    m.d.comb += getattr(self.pads, pin_name).o.eq(signal)
            #### External IO control logic           
            connect_pin("ext_ibeam_scan_enable", executor.ext_ctrl_enable)
            connect_pin("ext_ibeam_scan_enable_2", executor.ext_ctrl_enable)
            connect_pin("ext_ibeam_blank_enable", executor.ext_ctrl_enable)
            connect_pin("ext_ibeam_blank_enable_2", executor.ext_ctrl_enable)
            connect_pin("ext_ebeam_scan_enable", executor.ext_ctrl_enable)
            connect_pin("ext_ebeam_scan_enable_2", executor.ext_ctrl_enable)

            with m.If(executor.ext_ctrl_enable):
                with m.If(executor.beam_type == BeamType.NoBeam):
                    connect_pin("ebeam_blank", 1)
                    connect_pin("ebeam_blank_2", 1)
                    connect_pin("ibeam_blank_low", 0)
                    connect_pin("ibeam_blank_high", 1)

                with m.Elif(executor.beam_type == BeamType.Electron):
                    connect_pin("ebeam_blank", executor.blank_enable)
                    connect_pin("ebeam_blank_2", executor.blank_enable)
                    connect_pin("ibeam_blank_low", 0)
                    connect_pin("ibeam_blank_high", 1)
                    
                with m.Elif(executor.beam_type == BeamType.Ion):
                    connect_pin("ibeam_blank_high", executor.blank_enable)
                    connect_pin("ibeam_blank_low", ~executor.blank_enable)
                    connect_pin("ebeam_blank", 1)
                    connect_pin("ebeam_blank_2", 1)
            with m.Else():
                # Do not blank if external control is not enables
                connect_pin("ebeam_blank",0)
                connect_pin("ebeam_blank_2",0)
                connect_pin("ibeam_blank_low",1)
                connect_pin("ibeam_blank_high",0)
            


            m.d.comb += [
                control.x_latch.o.eq(executor.bus.dac_x_le_clk),
                control.y_latch.o.eq(executor.bus.dac_y_le_clk),
                control.a_latch.o.eq(executor.bus.adc_le_clk),
                control.a_enable.o.eq(executor.bus.adc_oe),
                control.d_clock.o.eq(executor.bus.dac_clk),
                control.a_clock.o.eq(executor.bus.adc_clk),

                executor.bus.data_i.eq(data.i),
                data.o.eq(executor.bus.data_o),
                data.oe.eq(executor.bus.data_oe),
            ]

        return m

#=========================================================================


import logging
import random
from glasgow.applet import *
import struct


class OBIInterface:
    def __init__(self, iface):
        self._synchronized = False
        self._next_cookie = random.randrange(0, 0x10000, 2) # even cookies only
        self.lower = iface
    
    @property
    def synchronized(self):
        """`True` if the instrument is ready to accept commands, `False` otherwise."""
        return self._synchronized
    
    async def _synchronize(self):
        print("synchronizing")
        if self.synchronized:
            print("already synced")
            return

        print("not synced")
        cookie, self._next_cookie = self._next_cookie, (self._next_cookie + 2) & 0xffff # even cookie
        #self._logger.debug(f'synchronizing with cookie {cookie:#06x}')
        print("synchronizing with cookie")

        cmd = struct.pack(">BHBB",
            Command.Type.Synchronize.value, cookie, 0,
            Command.Type.Flush.value)
        await self.lower.write(cmd)
        await self.lower.flush()
        res = struct.pack(">HH", 0xffff, cookie)
        data = await self.readuntil(res)
        print(str(list(data)))
    
    async def readuntil(self, separator=b'\n', *, flush=True):
        if flush and len(self._out_buffer) > 0:
            # Flush the buffer, so that everything written before the read reaches the device.
            await self.lower.flush(wait=False)

        seplen = len(separator)
        if seplen == 0:
            raise ValueError('Separator should be at least one-byte string')
        chunks = []

        # Loop until we find `separator` in the buffer, exceed the buffer size,
        # or an EOF has happened.
        while True:
            buflen = len(self.lower._in_buffer)

            # Check if we now have enough data in the buffer for `separator` to fit.
            if buflen >= seplen:
                isep = self.find(self.lower._in_buffer, separator)
                if isep != -1:
                    print(f"found {isep=}")
                    # `separator` is in the buffer. `isep` will be used later
                    # to retrieve the data.
                    break
            else:
                await self.lower._in_tasks.wait_one()

            async with self.lower._in_pushback:
                chunk = self.lower._in_buffer.read()
                self.lower._in_pushback.notify_all()
                chunks.append(chunk)
        
        async with self.lower._in_pushback:
            chunk = self.lower._in_buffer.read(isep+seplen)
            self.lower._in_pushback.notify_all()
            chunks.append(chunk)
        
        # Always return a memoryview object, to avoid hard to detect edge cases downstream.
        result = memoryview(b"".join(chunks))
        return result
    
    def find(self, buffer, separator=b'\n', offset=0):
        if buffer._chunk is None:
            if not buffer._queue:
                raise IncompleteReadError
            buffer._chunk  = buffer._queue.popleft()
            buffer._offset = 0
        return buffer._chunk.obj.find(separator)

class OBIApplet(GlasgowApplet):
    required_revision = "C3"
    logger = logging.getLogger(__name__)
    help = "open beam interface"
    description = """
    Scanning beam control applet
    """

    __pins = ("ext_ebeam_scan_enable", "ext_ebeam_scan_enable_2",
                "ext_ibeam_scan_enable", "ext_ibeam_scan_enable_2",
                "ext_ibeam_blank_enable", "ext_ibeam_blank_enable_2",
                "ibeam_blank_high", "ibeam_blank_low",
                "ebeam_blank", "ebeam_blank_2")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "ext_ebeam_scan_enable", default=None)
        access.add_pin_argument(parser, "ext_ebeam_scan_enable_2", default=None)
        access.add_pin_argument(parser, "ext_ibeam_scan_enable", default=None)
        access.add_pin_argument(parser, "ext_ibeam_scan_enable_2", default=None)
        access.add_pin_argument(parser, "ext_ibeam_blank_enable", default=None)
        access.add_pin_argument(parser, "ext_ibeam_blank_enable_2", default=None)
        access.add_pin_argument(parser, "ibeam_blank_high", default=None)
        access.add_pin_argument(parser, "ibeam_blank_low", default=None)
        access.add_pin_argument(parser, "ebeam_blank", default=None)
        access.add_pin_argument(parser, "ebeam_blank_2", default=None)

        parser.add_argument("--loopback",
            dest = "loopback", action = 'store_true',
            help = "connect output and input streams internally")
        parser.add_argument("--benchmark",
            dest = "benchmark", action = 'store_true',
            help = "run benchmark test")
        parser.add_argument("--xflip",
            dest = "xflip", action = 'store_true',
            help = "flip x axis")
        parser.add_argument("--yflip",
            dest = "yflip", action = 'store_true',
            help = "flip y axis")
        parser.add_argument("--rotate90",
            dest = "rotate90", action = 'store_true',
            help = "switch x and y axes")


    def build(self, target, args):
        target.platform.add_resources(obi_resources)

        self.mux_interface = iface = \
            target.multiplexer.claim_interface(self, args, throttle="none")

        pads = iface.get_pads(args, pins=self.__pins)

        subtarget_args = {
            "pads": pads,
            "in_fifo": iface.get_in_fifo(depth=512, auto_flush=False),
            "out_fifo": iface.get_out_fifo(depth=512),
            "led": target.platform.request("led"),
            "control": target.platform.request("control"),
            "data": target.platform.request("data"),
            "loopback": args.loopback,
            "xflip": args.xflip,
            "yflip": args.yflip,
            "rotate90": args.rotate90
        }

        if args.benchmark:
            out_stall_events, self.__addr_out_stall_events = target.registers.add_ro(8, reset=0)
            out_stall_cycles, self.__addr_out_stall_cycles = target.registers.add_ro(16, reset=0)
            stall_count_reset, self.__addr_stall_count_reset = target.registers.add_rw(1, reset=1)
            subtarget_args.update({"benchmark_counters": [out_stall_events, out_stall_cycles, stall_count_reset]})

        subtarget = OBISubtarget(**subtarget_args)

        return iface.add_subtarget(subtarget)

    # @classmethod
    # def add_run_arguments(cls, parser, access):
    #     super().add_run_arguments(parser, access)

    async def run(self, device, args):
        # await device.set_voltage("AB", 0)
        # await asyncio.sleep(5)
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
            # read_buffer_size=131072*16, write_buffer_size=131072*16)
            read_buffer_size=16384*16384, write_buffer_size=16384*16384)
        
        if args.benchmark:
            output_mode = 2 #no output
            raster_mode = 0 #no raster
            mode = int(output_mode<<1 | raster_mode)
            sync_cmd = struct.pack('>BHB', 0, 123, mode)
            flush_cmd = struct.pack('>B', 2)
            await iface.write(sync_cmd)
            await iface.write(flush_cmd)
            await iface.flush()
            await iface.read(4)
            print(f"got cookie!")
            commands = bytearray()
            print("generating block of commands...")
            for _ in range(131072*16):
                commands.extend(struct.pack(">BHHH", 0x14, 0, 16383, 1))
                commands.extend(struct.pack(">BHHH", 0x14, 16383, 0, 1))
            length = len(commands)
            print("writing commands...")
            while True:
                await device.write_register(self.__addr_stall_count_reset, 1)
                await device.write_register(self.__addr_stall_count_reset, 0)
                begin = time.time()
                await iface.write(commands)
                await iface.flush()
                end = time.time()
                out_stall_events = await device.read_register(self.__addr_out_stall_events)
                out_stall_cycles = await device.read_register(self.__addr_out_stall_cycles, width=2)
                self.logger.info("benchmark: %.2f MiB/s (%.2f Mb/s)",
                                 (length / (end - begin)) / (1 << 20),
                                 (length / (end - begin)) / (1 << 17))
                self.logger.info(f"out stalls: {out_stall_events}, stalled cycles: {out_stall_cycles}")
                
        else:
            return iface

    @classmethod
    def add_interact_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint")

    async def interact(self, device, args, iface):
        class ForwardProtocol(asyncio.Protocol):
            logger = self.logger

            async def reset(self):
                await iface.reset()
                # await iface.write([4,0,1]) #disable external ctrl
                self.logger.debug("reset")
                self.logger.debug(iface.statistics())

            def connection_made(self, transport):
                self.backpressure = False
                self.send_paused = False

                transport.set_write_buffer_limits(131072*16)

                self.transport = transport
                peername = self.transport.get_extra_info("peername")
                self.logger.info("connect peer=[%s]:%d", *peername[0:2])

                async def initialize():
                    await self.reset()
                    asyncio.create_task(self.send_data())
                self.init_fut = asyncio.create_task(initialize())

                self.flush_fut = None
            
            async def send_data(self):
                self.send_paused = False
                self.logger.debug("awaiting read")
                data = await iface.read(flush=False)
                if self.transport:
                    self.logger.debug(f"in-buffer size={len(iface._in_buffer)}")
                    self.logger.debug("dev->net <%s>", dump_hex(data))
                    self.transport.write(data)
                    await asyncio.sleep(0)
                    if self.backpressure:
                        self.logger.debug("paused send due to backpressure")
                        self.send_paused = True
                    else:
                        asyncio.create_task(self.send_data())
                else:
                    self.logger.debug("dev->🗑️ <%s>", dump_hex(data))
            
            def pause_writing(self):
                self.backpressure = True
                self.logger.debug("dev->NG")

            def resume_writing(self):
                self.backpressure = False
                self.logger.debug("dev->OK->net")
                if self.send_paused:
                    asyncio.create_task(self.send_data())

            def data_received(self, data):
                async def recv_data():
                    await self.init_fut
                    if not self.flush_fut == None:
                        self.transport.pause_reading()
                        await self.flush_fut
                        self.transport.resume_reading()
                        self.logger.debug("net->dev flush: done")
                    self.logger.debug("net->dev <%s>", dump_hex(data))
                    await iface.write(data)
                    self.logger.debug("net->dev write: done")
                    self.flush_fut = asyncio.create_task(iface.flush(wait=True))
                asyncio.create_task(recv_data())

            def connection_lost(self, exc):
                peername = self.transport.get_extra_info("peername")
                self.logger.info("disconnect peer=[%s]:%d", *peername[0:2], exc_info=exc)
                self.transport = None

                asyncio.create_task(self.reset())
                


        proto, *proto_args = args.endpoint
        server = await asyncio.get_event_loop().create_server(ForwardProtocol, *proto_args, backlog=1)
        await server.serve_forever()
        
