from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.wiring import In, Out, flipped

from obi.applet.open_beam_interface.modules.structs import SuperDACStream, DACStream


class PowerOfTwoDetector(Elaboratable):
    """Priority encode requests to binary.

    If any bit in ``i`` is asserted, ``n`` is low and ``o`` indicates the least significant
    asserted bit.
    Otherwise, ``n`` is high and ``o`` is ``0``.

    Parameters
    ----------
    width : int
        Bit width of the input.

    Attributes
    ----------
    i : Signal(width), in
        Input requests.
    o : Signal(range(width)), out
        Encoded natural binary.
    n : Signal, out
        Invalid: no input bits are asserted.
    """
    def __init__(self, width):
        self.width = width

        self.i = Signal(width)
        self.o = Signal(range(width))
        self.n = Signal()
        self.p = Signal()

    def elaborate(self, platform):
        m = Module()
        p = Signal()
        for power in range(self.width):
            with m.If(self.i[power]):
                m.d.comb += self.o.eq(power)
            with m.If(self.i == 1 << power):
                m.d.comb += p.eq(1)
        m.d.comb += self.n.eq(self.i == 0)
        m.d.comb += self.p.eq(p & ~self.n)
        return m


class Supersampler(wiring.Component):
    """
    In:
        dac_stream: X and Y DAC codes and dwell time
        super_adc_stream: ADC sample value and `last` signal
    Out:
        super_dac_stream: X and Y DAC codes and `last` signal
        adc_stream: Averaged ADC sample value
    """
    dac_stream: In(stream.Signature(DACStream))

    adc_stream: Out(stream.Signature(data.StructLayout({
        "adc_code":   14,
    })))

    super_dac_stream: Out(stream.Signature(SuperDACStream))

    super_adc_stream: In(stream.Signature(data.StructLayout({
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
        self.encoder = PowerOfTwoDetector(16)

    def elaborate(self, platform):
        m = Module()
        m.submodules["encoder"] = self.encoder

        dwell_counter = Signal.like(self.dac_stream_data.dwell_time)
        sample_counter = Signal.like(self.dac_stream_data.dwell_time)
        last = Signal()
        m.d.comb += [
            self.super_dac_stream.payload.dac_x_code.eq(self.dac_stream_data.dac_x_code),
            self.super_dac_stream.payload.dac_y_code.eq(self.dac_stream_data.dac_y_code),
            self.super_dac_stream.payload.blank.eq(self.dac_stream_data.blank),
            self.super_dac_stream.payload.delay.eq(self.dac_stream_data.delay),
            last.eq(dwell_counter == self.dac_stream_data.dwell_time)
            #self.super_dac_stream.payload.last.eq(dwell_counter == self.dac_stream_data.dwell_time),
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
                    with m.If(last):
                        m.d.comb += self.super_dac_stream.payload.last.eq(last)
                        m.next = "Wait"
                    with m.Else():
                        m.d.sync += dwell_counter.eq(dwell_counter + 1)

        m.d.comb += self.encoder.i.eq(sample_counter)
        running_sum = Signal(30)
        last_p2_sum = Signal(30)
        selected_sum = Signal(30)
        shifted_sum = Signal(30)
        with m.If(self.encoder.p): #if the current sample counter is a power of 2, use all samples
            m.d.comb += selected_sum.eq(running_sum)
            m.d.sync += last_p2_sum.eq(running_sum)
        with m.Else(): # else, only average up to the last power of 2 samples
            m.d.comb += selected_sum.eq(last_p2_sum)
        m.d.comb += self.adc_stream.payload.adc_code.eq(selected_sum >> self.encoder.o)

        with m.FSM():
            with m.State("Start"):
                m.d.comb += self.super_adc_stream.ready.eq(1)
                with m.If(self.super_adc_stream.valid):
                    m.d.sync += sample_counter.eq(1)
                    m.d.sync += running_sum.eq(self.super_adc_stream.payload.adc_code)
                    with m.If(self.super_adc_stream.payload.last):
                        m.next = "Wait"
                    with m.Else():
                        m.next = "Average"

            with m.State("Average"):
                m.d.comb += self.super_adc_stream.ready.eq(1)
                with m.If(self.super_adc_stream.valid):
                    m.d.sync += sample_counter.eq(sample_counter + 1)
                    m.d.sync += running_sum.eq(running_sum + self.super_adc_stream.payload.adc_code)
                    with m.If(self.super_adc_stream.payload.last):
                        m.next = "Wait"
                    with m.Else():
                        m.next = "Average"


            with m.State("Wait"):
                m.d.comb += self.adc_stream.valid.eq(1)
                with m.If(self.adc_stream.ready):
                    m.next = "Start"

        return m