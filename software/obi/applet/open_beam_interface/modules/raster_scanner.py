from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.wiring import In, Out, flipped

from obi.applet.open_beam_interface.modules.structs import RasterRegion, DACStream, DwellTime, BlankRequest, OutputEnable

class RasterScanner(wiring.Component):
    """
    Properties:
        FRAC_BITS: number of fixed fractional bits in accumulators

    In:
        roi_stream: A RasterRegion provided by a RasterScanCommand
        dwell_stream: A dwell time value provided by one of the RasterPixel commands
        abort: Interrupt the scan in progress and fetch the next ROI from `roi_stream`
    Out:
        dac_stream: X and Y DAC codes and a dwell time
    """
    FRAC_BITS = 8

    roi_stream: In(stream.Signature(RasterRegion))

    dwell_stream: In(stream.Signature(data.StructLayout({
        "dwell_time": DwellTime,
        "blank": BlankRequest,
        "output_en": OutputEnable
    })))

    abort: In(1)
    #: Interrupt the scan in progress and fetch the next ROI from `roi_stream`.

    dac_stream: Out(stream.Signature(DACStream))

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
            self.dac_stream.payload.blank.eq(self.dwell_stream.payload.blank),
            self.dac_stream.payload.output_en.eq(self.dwell_stream.payload.output_en)
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

                    ## TODO: AC line sync 
                    ## TODO: external trigger
                    ## TODO: be flyback aware, line and frame

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