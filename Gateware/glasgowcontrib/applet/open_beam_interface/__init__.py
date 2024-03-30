import asyncio
from amaranth import *
from amaranth.lib import enum, data, wiring
from amaranth.lib.fifo import SyncFIFOBuffered
from amaranth.lib.wiring import In, Out, flipped

from glasgow.support.logging import dump_hex
from glasgow.support.endpoint import ServerEndpoint


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


BusSignature = wiring.Signature({
    "adc_clk":  Out(1),
    "adc_le":   Out(1),
    "adc_oe":   Out(1),

    "dac_clk":  Out(1),
    "dac_x_le": Out(1),
    "dac_y_le": Out(1),

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


class BusController(wiring.Component):
    # FPGA-side interface
    dac_stream: In(StreamSignature(data.StructLayout({
        "dac_x_code": 14,
        "dac_y_code": 14,
        "last":       1,
    })))

    adc_stream: Out(StreamSignature(data.StructLayout({
        "adc_code": 14,
        "adc_ovf":  1,
        "last":     1,
    })))

    # IO-side interface
    bus: Out(BusSignature)

    def __init__(self, *, adc_half_period: int, adc_latency: int):
        assert (adc_half_period * 2) >= 6, "ADC period must be large enough for FSM latency"
        self.adc_half_period = adc_half_period
        self.adc_latency     = adc_latency

        super().__init__()

    def elaborate2(self, platform):
        m = Module()

        m.d.comb += [
            self.adc_stream.valid.eq(self.dac_stream.valid),
            self.adc_stream.payload.adc_code.eq(self.dac_stream.data.dac_x_code),
            self.adc_stream.payload.last.eq(self.dac_stream.data.last),
            self.dac_stream.ready.eq(self.adc_stream.ready),
        ]

        return m

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

        m.submodules.adc_stream_fifo = adc_stream_fifo = \
            SyncFIFOBuffered(depth=self.adc_latency, width=len(self.adc_stream.payload.as_value()))
        m.d.comb += [
            self.adc_stream.payload.eq(adc_stream_fifo.r_data),
            self.adc_stream.valid.eq(adc_stream_fifo.r_rdy),
            adc_stream_fifo.r_en.eq(self.adc_stream.ready),
        ]

        adc_stream_data = Signal.like(self.adc_stream.payload) # FIXME: will not be needed after FIFOs have shapes
        m.d.comb += [
            # Cat(adc_stream_data.adc_code,
            #     adc_stream_data.adc_ovf).eq(self.bus.i),
            adc_stream_data.last.eq(last_sample[self.adc_latency-1]),
            adc_stream_fifo.w_data.eq(adc_stream_data),
        ]

        dac_stream_data = Signal.like(self.dac_stream.payload)

        m.d.comb += adc_stream_data.adc_code.eq(self.bus.data_i),

        with m.FSM():
            with m.State("ADC_Wait"):
                with m.If(self.bus.adc_clk & (adc_cycles == 0)):
                    m.d.comb += self.bus.adc_le.eq(1)
                    m.d.comb += self.bus.adc_oe.eq(1) #give bus time to stabilize before sampling
                    m.next = "ADC_Read"

            with m.State("ADC_Read"):
                m.d.comb += self.bus.adc_le.eq(1)
                m.d.comb += self.bus.adc_oe.eq(1)
                m.d.comb += adc_stream_fifo.w_en.eq(accept_sample[self.adc_latency-1]) # does nothing if ~adc_stream_fifo.w_rdy
                with m.If(self.dac_stream.valid & adc_stream_fifo.w_rdy):
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
                    self.bus.dac_x_le.eq(1),
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
                    self.bus.dac_y_le.eq(1),
                ]
                m.next = "ADC_Wait"

        return m

#=========================================================================

class Supersampler(wiring.Component):
    dac_stream: In(StreamSignature(data.StructLayout({
        "dac_x_code": 14,
        "dac_y_code": 14,
        "dwell_time": 16,
    })))

    adc_stream: Out(StreamSignature(data.StructLayout({
        "adc_code":   14,
    })))

    super_dac_stream: Out(StreamSignature(data.StructLayout({
        "dac_x_code": 14,
        "dac_y_code": 14,
        "last":       1,
    })))

    super_adc_stream: In(StreamSignature(data.StructLayout({
        "adc_code":   14,
        "adc_ovf":    1,  # ignored
        "last":       1,
    })))

    def __init__(self):
        super().__init__()

        self.dac_stream_data = Signal.like(self.dac_stream.payload)

    def elaborate(self, platform):
        m = Module()

        dwell_counter = Signal.like(self.dac_stream_data.dwell_time)
        m.d.comb += [
            self.super_dac_stream.payload.dac_x_code.eq(self.dac_stream_data.dac_x_code),
            self.super_dac_stream.payload.dac_y_code.eq(self.dac_stream_data.dac_y_code),
            self.super_dac_stream.payload.last.eq(dwell_counter == self.dac_stream_data.dwell_time),
        ]
        with m.FSM():
            with m.State("Wait"):
                m.d.comb += self.dac_stream.ready.eq(1)
                with m.If(self.dac_stream.valid):
                    m.d.sync += self.dac_stream_data.eq(self.dac_stream.payload)
                    m.d.sync += dwell_counter.eq(0)
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

    dwell_stream: In(StreamSignature(DwellTime))

    abort: In(1)
    #: Interrupt the scan in progress and fetch the next ROI from `roi_stream`.

    dac_stream: Out(StreamSignature(data.StructLayout({
        "dac_x_code": 14,
        "dac_y_code": 14,
        "dwell_time": DwellTime,
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
            self.dac_stream.payload.dwell_time.eq(self.dwell_stream.payload),
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
                with m.If(self.dwell_stream.valid & self.dac_stream.ready):
                    # AXI4-Stream §2.2.1
                    # > Once TVALID is asserted it must remain asserted until the handshake occurs.
                    with m.If(self.abort):
                        m.next = "Get-ROI"

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


class Command(data.Struct):
    class Type(enum.Enum, shape=8):
        Synchronize     = 0x00
        Abort           = 0x01
        Flush           = 0x02

        RasterRegion    = 0x10
        RasterPixel     = 0x11
        RasterPixelRun  = 0x12
        RasterFreeScan  = 0x13
        VectorPixel     = 0x14

    type: Type

    payload: data.UnionLayout({
        "synchronize":      data.StructLayout({
            "cookie":           Cookie,
            "raster_mode":      1,
        }),
        "raster_region":    RasterRegion,
        "raster_pixel":     DwellTime,
        "raster_pixel_run": data.StructLayout({
            "length":           16,
            "dwell_time":       DwellTime,
        }),
        "vector_pixel":     data.StructLayout({
            "x_coord":          14,
            "y_coord":          14,
            "dwell_time":       DwellTime,
        })
    })


class CommandParser(wiring.Component):
    usb_stream: In(StreamSignature(8))
    cmd_stream: Out(StreamSignature(Command))

    def elaborate(self, platform):
        m = Module()

        command = Signal(Command)
        m.d.comb += self.cmd_stream.payload.eq(command)

        with m.FSM():
            with m.State("Type"):
                m.d.comb += self.usb_stream.ready.eq(1)
                m.d.sync += command.type.eq(self.usb_stream.payload)
                with m.If(self.usb_stream.valid):
                    with m.Switch(self.usb_stream.payload):
                        with m.Case(Command.Type.Synchronize):
                            m.next = "Payload_Synchronize_1_High"

                        with m.Case(Command.Type.Abort):
                            m.next = "Submit"

                        with m.Case(Command.Type.Flush):
                            m.next = "Submit"

                        with m.Case(Command.Type.RasterRegion):
                            m.next = "Payload_Raster_Region_1_High"

                        with m.Case(Command.Type.RasterPixel): # actually an array
                            m.next = "Payload_Raster_Pixel_Count_High"

                        with m.Case(Command.Type.RasterPixelRun):
                            m.next = "Payload_Raster_Pixel_Run_1_High"
                        
                        with m.Case(Command.Type.RasterFreeScan):
                            m.next = "Payload_Raster_Free_Scan_High"

                        with m.Case(Command.Type.VectorPixel):
                            m.next = "Payload_Vector_Pixel_1_High"

            def Deserialize(target, state, next_state):
                #print(f'state: {state} -> next state: {next_state}')
                with m.State(state):
                    m.d.comb += self.usb_stream.ready.eq(1)
                    with m.If(self.usb_stream.valid):
                        m.d.sync += target.eq(self.usb_stream.payload)
                        m.next = next_state

            def DeserializeWord(target, state_prefix, next_state):
                # print(f'\tdeserializing: {state_prefix} to {next_state}')
                Deserialize(target[8:16],
                    f"{state_prefix}_High", f"{state_prefix}_Low")
                Deserialize(target[0:8],
                    f"{state_prefix}_Low",  next_state)

            DeserializeWord(command.payload.synchronize.cookie,
                "Payload_Synchronize_1", "Payload_Synchronize_2")
            Deserialize(command.payload.synchronize.raster_mode,
                "Payload_Synchronize_2", "Submit")

            DeserializeWord(command.payload.raster_region.x_start,
                "Payload_Raster_Region_1", "Payload_Raster_Region_2_High")
            DeserializeWord(command.payload.raster_region.x_count,
                "Payload_Raster_Region_2", "Payload_Raster_Region_3_High")
            DeserializeWord(command.payload.raster_region.x_step,
                "Payload_Raster_Region_3", "Payload_Raster_Region_4_High")
            DeserializeWord(command.payload.raster_region.y_start,
                "Payload_Raster_Region_4", "Payload_Raster_Region_5_High")
            DeserializeWord(command.payload.raster_region.y_count,
                "Payload_Raster_Region_5", "Payload_Raster_Region_6_High")
            DeserializeWord(command.payload.raster_region.y_step,
                "Payload_Raster_Region_6", "Submit")

            raster_pixel_count = Signal(16)
            DeserializeWord(raster_pixel_count,
                "Payload_Raster_Pixel_Count", "Payload_Raster_Pixel_Array_High")
            DeserializeWord(command.payload.raster_pixel,
                "Payload_Raster_Pixel_Array", "Payload_Raster_Pixel_Array_Submit")
            with m.State("Payload_Raster_Pixel_Array_Submit"):
                m.d.comb += self.cmd_stream.valid.eq(1)
                with m.If(self.cmd_stream.ready):
                    with m.If(raster_pixel_count == 0):
                        m.next = "Type"
                    with m.Else():
                        m.d.sync += raster_pixel_count.eq(raster_pixel_count - 1)
                        m.next = "Payload_Raster_Pixel_Array_High"

            DeserializeWord(command.payload.raster_pixel_run.length,
                "Payload_Raster_Pixel_Run_1", "Payload_Raster_Pixel_Run_2_High")
            DeserializeWord(command.payload.raster_pixel_run.dwell_time,
                "Payload_Raster_Pixel_Run_2", "Submit")

            DeserializeWord(command.payload.raster_pixel,
                "Payload_Raster_Free_Scan", "Submit")

            DeserializeWord(command.payload.vector_pixel.x_coord,
                "Payload_Vector_Pixel_1", "Payload_Vector_Pixel_2_High")
            DeserializeWord(command.payload.vector_pixel.y_coord,
                "Payload_Vector_Pixel_2", "Payload_Vector_Pixel_3_High")
            DeserializeWord(command.payload.vector_pixel.dwell_time,
                "Payload_Vector_Pixel_3", "Submit")

            with m.State("Submit"):
                m.d.comb += self.cmd_stream.valid.eq(1)
                with m.If(self.cmd_stream.ready):
                    m.next = "Type"

        return m

#=========================================================================
class CommandExecutor(wiring.Component):
    cmd_stream: In(StreamSignature(Command))
    img_stream: Out(StreamSignature(unsigned(16)))

    bus: Out(BusSignature)

    #: Active if `Synchronize`, `Flush`, or `Abort` was the last received command.
    flush: Out(1)

    def __init__(self, *, adc_latency=6):
        self.adc_latency = 6
        self.supersampler = Supersampler()
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus_controller = bus_controller = BusController(adc_half_period=3, adc_latency=self.adc_latency)
        m.submodules.supersampler   = self.supersampler
        m.submodules.raster_scanner = self.raster_scanner = RasterScanner()


        wiring.connect(m, self.supersampler.super_dac_stream, bus_controller.dac_stream)
        wiring.connect(m, bus_controller.adc_stream, self.supersampler.super_adc_stream)
        wiring.connect(m, flipped(self.bus), bus_controller.bus)

        vector_stream = StreamSignature(data.StructLayout({
            "dac_x_code": 14,
            "dac_y_code": 14,
            "dwell_time": DwellTime,
        })).create()


        raster_mode = Signal()
        command = Signal.like(self.cmd_stream.payload)
        with m.If(raster_mode):
            wiring.connect(m, self.raster_scanner.dac_stream, self.supersampler.dac_stream)
        with m.Else():
            wiring.connect(m, vector_stream, self.supersampler.dac_stream)

        in_flight_pixels = Signal(4) # should never overflow
        submit_pixel = Signal()
        retire_pixel = Signal()
        m.d.sync += in_flight_pixels.eq(in_flight_pixels + submit_pixel - retire_pixel)


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
                            m.d.sync += raster_mode.eq(command.payload.synchronize.raster_mode)
                            m.next = "Fetch"

                    with m.Case(Command.Type.Abort):
                        m.d.sync += self.flush.eq(1)
                        m.d.comb += self.raster_scanner.abort.eq(1)
                        m.next = "Fetch"

                    with m.Case(Command.Type.Flush):
                        m.d.sync += self.flush.eq(1)
                        m.next = "Fetch"

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
                            self.raster_scanner.dwell_stream.payload.eq(command.payload.raster_pixel),
                        ]
                        with m.If(self.raster_scanner.dwell_stream.ready):
                            m.d.comb += submit_pixel.eq(1)
                            m.next = "Fetch"

                    with m.Case(Command.Type.RasterPixelRun):
                        m.d.comb += [
                            self.raster_scanner.dwell_stream.valid.eq(1),
                            self.raster_scanner.dwell_stream.payload.eq(command.payload.raster_pixel_run.dwell_time)
                        ]
                        with m.If(self.raster_scanner.dwell_stream.ready):
                            m.d.comb += submit_pixel.eq(1)
                            with m.If(run_length == command.payload.raster_pixel_run.length):
                                m.d.sync += run_length.eq(0)
                                m.next = "Fetch"
                            with m.Else():
                                m.d.sync += run_length.eq(run_length + 1)

                    with m.Case(Command.Type.RasterFreeScan):
                        m.d.comb += [
                            self.raster_scanner.roi_stream.payload.eq(raster_region),
                            self.raster_scanner.dwell_stream.payload.eq(command.payload.raster_pixel),
                        ]
                        with m.If(self.cmd_stream.valid):
                            m.d.comb += self.raster_scanner.abort.eq(1)
                            # `abort` only takes effect on the next opportunity!
                            with m.If(self.raster_scanner.dac_stream.ready):
                                m.next = "Fetch"
                        with m.Else():
                            # don't count pixels; resynchronization is mandatory after this command
                            m.d.comb += [
                                self.raster_scanner.roi_stream.valid.eq(1),
                                self.raster_scanner.dwell_stream.valid.eq(1),
                            ]


                    with m.Case(Command.Type.VectorPixel):
                        m.d.comb += vector_stream.valid.eq(1)
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

    def elaborate(self, platform):
        m = Module()

        low = Signal(8)

        with m.FSM():
            with m.State("High"):
                m.d.comb += self.usb_stream.payload.eq(self.img_stream.payload[8:16])
                m.d.comb += self.usb_stream.valid.eq(self.img_stream.valid)
                m.d.comb += self.img_stream.ready.eq(self.usb_stream.ready)
                m.d.sync += low.eq(self.img_stream.payload[0:8])
                with m.If(self.usb_stream.ready & self.img_stream.valid):
                    m.next = "Low"

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
        Subsignal("d_clock", Pins("F3", dir="o")), # D23
        Subsignal("a_clock", Pins("G1", dir="o")), # D24
        Attrs(IO_STANDARD="SB_LVCMOS33")
    ),

    Resource("data", 0, Pins("B2 B1 C4 C3 C2 C1 D1 D3 F4 G2 E3 F1 E2 F2", dir="io"), # ; E1 D2
        Attrs(IO_STANDARD="SB_LVCMOS33")
    ),
]

class OBISubtarget(wiring.Component):
    def __init__(self, *, out_fifo, in_fifo, sim=False, loopback=False):
        self.out_fifo = out_fifo
        self.in_fifo  = in_fifo
        self.sim = sim
        self.loopback = loopback

    def elaborate(self, platform):
        m = Module()

        m.submodules.parser     = parser     = CommandParser()
        m.submodules.executor   = executor   = CommandExecutor()
        m.submodules.serializer = serializer = ImageSerializer()

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
        ]

        if not self.sim:
            control = platform.request("control")
            data = platform.request("data")

            m.d.comb += [
                control.x_latch.o.eq(executor.bus.dac_x_le),
                control.y_latch.o.eq(executor.bus.dac_y_le),
                control.a_latch.o.eq(executor.bus.adc_le),
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

class OBIApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "open beam interface"
    description = """
    Scanning beam control applet
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        parser.add_argument("--loopback",
            dest = "loopback", action = 'store_true',
            help = "connect output and input streams internally")

    def build(self, target, args):
        target.platform.add_resources(obi_resources)

        self.mux_interface = iface = \
            target.multiplexer.claim_interface(self, args=None, throttle="none")

        subtarget = OBISubtarget(
            in_fifo=iface.get_in_fifo(depth=512, auto_flush=False),
            out_fifo=iface.get_out_fifo(depth=512),
            loopback=args.loopback,
        )
        return iface.add_subtarget(subtarget)

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args=None)
        return iface

    @classmethod
    def add_interact_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint")

    async def interact(self, device, args, iface):
        class ForwardProtocol(asyncio.Protocol):
            logger = self.logger

            def connection_made(self, transport):
                self.transport = transport

                peername = self.transport.get_extra_info("peername")
                self.logger.info("new connection from [%s]:%d", *peername[0:2])

                async def initialize():
                    self.logger.debug("reset")
                    await iface.reset()

                    async def send_data():
                        data = await iface.read(flush=False)
                        self.logger.debug("dev->ui <%s>", dump_hex(data))
                        transport.write(data)
                        asyncio.create_task(send_data())
                    asyncio.create_task(send_data())
                self.init_fut = asyncio.create_task(initialize())
            
            def connection_lost(self, exc):
                peername = self.transport.get_extra_info("peername")
                self.logger.info("connection from [%s]:%d lost", *peername[0:2], exc_info=exc)

            def data_received(self, data):
                async def recv_data():
                    await self.init_fut
                    self.logger.debug("ui->dev <%s>", dump_hex(data))
                    await iface.write(data)
                    await iface.flush(wait=False)
                asyncio.create_task(recv_data())

        proto, *proto_args = args.endpoint
        server = await asyncio.get_event_loop().create_server(ForwardProtocol, *proto_args, backlog=1)
        await server.serve_forever()
