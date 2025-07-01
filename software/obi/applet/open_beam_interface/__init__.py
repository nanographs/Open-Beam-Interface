from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
import enum
import struct
import time
import asyncio
from amaranth import *
from amaranth.lib import enum, data, io, wiring
from amaranth.lib.fifo import SyncFIFOBuffered
from amaranth.lib.wiring import In, Out, flipped

from glasgow.applet import GlasgowApplet
from glasgow.support.logging import dump_hex
from glasgow.support.endpoint import ServerEndpoint

from obi.applet.open_beam_interface.modules.structs import Transforms
from obi.commands import (CmdType, BeamType, OutputMode, 
                        SynchronizeCommand, FlushCommand, VectorPixelMinDwellCommand)
from obi.applet.open_beam_interface.modules import (
    Transforms, BlankRequest,BusSignature, DwellTime, DACStream, SuperDACStream, 
    PipelinedLoopbackAdapter, BusController, FastBusController, 
    Supersampler, RasterScanner, CommandParser)

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

class CommandExecutor(wiring.Component):
    cmd_stream: In(StreamSignature(Command))
    img_stream: Out(StreamSignature(unsigned(16)))

    bus: Out(BusSignature)
    inline_blank: In(BlankRequest)

    #: Active if `Synchronize`, `Flush`, or `Abort` was the last received command.
    flush: Out(1)

    # Input to Scan/Signal Selector Relay Board
    ext_ctrl_enable: Out(2)
    ext_ctrl_enabled: Out(2)
    beam_type: Out(BeamType)
    # Input to Blanking control board
    blank_enable: Out(1, init=1)

    #Input to Serializer
    output_mode: Out(2)


    def __init__(self, *, out_only:bool=False, adc_latency=8, ext_switch_delay=960000,
                transforms: Transforms=Transforms(False, False, False)):
        self.adc_latency = adc_latency
        # Time for external control relay/switch to actuate
        self.ext_switch_delay = ext_switch_delay
        self.transforms = transforms

        self.supersampler = Supersampler()

        self.out_only = out_only
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        delay_counter = Signal(DwellTime)
        inline_delay_counter = Signal(3)

        ext_switch_delay_counter = Signal(24)

        if self.out_only:
            m.submodules.bus_controller = bus_controller = FastBusController()
        else:
            m.submodules.bus_controller = bus_controller = BusController(adc_half_period=3, adc_latency=self.adc_latency, transforms=self.transforms)
        m.submodules.raster_scanner = self.raster_scanner = RasterScanner()
        m.submodules.supersampler = self.supersampler

        wiring.connect(m, self.supersampler.super_dac_stream, bus_controller.dac_stream)
        wiring.connect(m, bus_controller.adc_stream, self.supersampler.super_adc_stream)
        wiring.connect(m, flipped(self.bus), bus_controller.bus)
        m.d.comb += self.inline_blank.eq(bus_controller.inline_blank)

        vector_stream = StreamSignature(DACStream).create()

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
        raster_region = Signal.like(command.payload.raster_region.roi)
        m.d.comb += [
            self.raster_scanner.roi_stream.payload.eq(raster_region),
            vector_stream.payload.dac_x_code.eq(command.payload.vector_pixel.x_coord),
            vector_stream.payload.dac_y_code.eq(command.payload.vector_pixel.y_coord),
            vector_stream.payload.dwell_time.eq(command.payload.vector_pixel.dwell_time)
        ]

        sync_req = Signal()
        sync_ack = Signal()

        self.is_executing = Signal()
        with m.FSM() as fsm:
            m.d.comb += self.is_executing.eq(fsm.ongoing("Execute"))
            with m.State("Fetch"):
                m.d.comb += self.cmd_stream.ready.eq(1)
                with m.If(self.cmd_stream.valid):
                    m.d.sync += command.eq(self.cmd_stream.payload)
                    m.next = "Execute"

            with m.State("Execute"):
                m.d.sync += self.flush.eq(0)

                with m.Switch(command.type):
                    with m.Case(CmdType.Synchronize):
                        m.d.sync += self.flush.eq(1)
                        m.d.comb += sync_req.eq(1)
                        with m.If(sync_ack):
                            #m.d.sync += raster_mode.eq(command.payload.synchronize.mode.raster)
                            m.d.sync += output_mode.eq(command.payload.synchronize.mode.output)
                            m.next = "Fetch"

                    with m.Case(CmdType.Abort):
                        m.d.sync += self.flush.eq(1)
                        m.d.comb += self.raster_scanner.abort.eq(1)
                        m.next = "Fetch"

                    with m.Case(CmdType.Flush):
                        m.d.sync += self.flush.eq(1)
                        m.next = "Fetch"

                    with m.Case(CmdType.Delay):
                        # if inline delay
                        #     m.d.sync += inline_delay_counter.eq(command.payload.delay.delay)
                        with m.If(delay_counter == command.payload.delay.delay):
                            m.d.sync += delay_counter.eq(0)
                            m.next = "Fetch"
                        with m.Else():
                            m.d.sync += delay_counter.eq(delay_counter + 1)
                    
                    with m.Case(CmdType.ExternalCtrl):
                        #Don't change control in the middle of previously submitted pixels
                        with m.If(self.supersampler.dac_stream.ready):
                            m.d.sync += self.ext_ctrl_enable.eq(command.payload.external_ctrl.enable)
                            # if we are going into external control, change blank states instantly
                            with m.If(command.payload.external_ctrl.enable):
                                m.d.sync += self.ext_ctrl_enabled.eq(1)
                            # if we are going out of external control, don't change blank states
                            # until switching delay has elapsed
                            with m.If(ext_switch_delay_counter == self.ext_switch_delay): 
                                m.d.sync += ext_switch_delay_counter.eq(0)
                                with m.If(~command.payload.external_ctrl.enable):
                                    m.d.sync += self.ext_ctrl_enabled.eq(0)
                                m.next = "Fetch"
                            with m.Else():
                                m.d.sync += ext_switch_delay_counter.eq(ext_switch_delay_counter + 1)
                    
                    with m.Case(CmdType.BeamSelect):
                        #Don't change control in the middle of previously submitted pixels
                        with m.If(self.supersampler.dac_stream.ready):
                            m.d.sync += self.beam_type.eq(command.payload.beam_select.beam_type)
                            m.next = "Fetch"

                    with m.Case(CmdType.Blank):
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

                    with m.Case(CmdType.RasterRegion):
                        m.d.comb += raster_mode.eq(1)
                        m.d.sync += raster_region.eq(command.payload.raster_region.roi)
                        m.d.comb += [
                            self.raster_scanner.roi_stream.valid.eq(1),
                            self.raster_scanner.roi_stream.payload.eq(command.payload.raster_region.roi),
                        ]
                        
                        m.d.comb += self.raster_scanner.abort.eq(1)
                        with m.If(self.raster_scanner.roi_stream.ready):
                            m.next = "Fetch"

                    with m.Case(CmdType.RasterPixel):
                        m.d.comb += raster_mode.eq(1)
                        m.d.comb += [
                            self.raster_scanner.dwell_stream.valid.eq(1),
                            self.raster_scanner.dwell_stream.payload.dwell_time.eq(command.payload.raster_pixel.dwell_time),
                            self.raster_scanner.dwell_stream.payload.blank.eq(sync_blank)
                        ]
                        with m.If(self.raster_scanner.dwell_stream.ready):
                            m.d.comb += submit_pixel.eq(1)
                            m.next = "Fetch"

                    with m.Case(CmdType.RasterPixelRun):
                        m.d.comb += raster_mode.eq(1)
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
                    
                    with m.Case(CmdType.RasterPixelFill):
                        m.d.comb += raster_mode.eq(1)
                        with m.If(self.raster_scanner.dwell_stream.ready):
                            m.d.comb += submit_pixel.eq(1)
                        with m.If(self.raster_scanner.roi_stream.ready):
                            m.next = "Fetch"
                        with m.Else():
                            m.d.comb += [
                                self.raster_scanner.dwell_stream.valid.eq(1),
                                self.raster_scanner.dwell_stream.payload.dwell_time.eq(command.payload.raster_pixel_fill.dwell_time),
                                self.raster_scanner.dwell_stream.payload.blank.eq(sync_blank)
                            ]

                            
                    with m.Case(CmdType.RasterPixelFreeRun):
                        m.d.comb += raster_mode.eq(1)
                        m.d.comb += [
                            self.raster_scanner.roi_stream.payload.eq(raster_region),
                            self.raster_scanner.dwell_stream.payload.dwell_time.eq(command.payload.raster_pixel.dwell_time),
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


                    with m.Case(CmdType.VectorPixel, CmdType.VectorPixelMinDwell):
                        m.d.comb += vector_stream.valid.eq(1)
                        m.d.comb += vector_stream.payload.blank.eq(sync_blank)
                        m.d.comb += vector_stream.payload.delay.eq(inline_delay_counter)
                        with m.If(vector_stream.ready):
                            m.d.sync += inline_delay_counter.eq(0)
                            m.d.comb += submit_pixel.eq(1)
                            m.next = "Fetch"

        with m.FSM():
            with m.State("Imaging"):
                m.d.comb += [
                    self.img_stream.payload.eq(self.supersampler.adc_stream.payload.adc_code << 2),
                    self.img_stream.valid.eq(self.supersampler.adc_stream.valid),
                    self.supersampler.adc_stream.ready.eq(self.img_stream.ready),
                    self.output_mode.eq(output_mode) #input to Serializer
                ]
                if self.out_only:
                    m.d.comb += retire_pixel.eq(submit_pixel)
                else:
                    m.d.comb += retire_pixel.eq(self.supersampler.adc_stream.valid & self.img_stream.ready)
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

obi_resources  = [
    Resource("control", 0,
        Subsignal("power_good", Pins("K1", dir="i")), # D17
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
    def __init__(self, *, ports, out_fifo, in_fifo, #led, control, data, 
                        ext_switch_delay=0, transforms: Transforms, 
                        benchmark_counters=None, loopback=False, out_only=False):
        self.ports            = ports
        self.out_fifo         = out_fifo
        self.in_fifo          = in_fifo
        # self.led              = led
        # self.control          = control
        # self.data             = data

        self.ext_switch_delay = ext_switch_delay
        self.transforms = transforms
        self.loopback         = loopback
        self.out_only         = out_only

        if not benchmark_counters == None:
            self.benchmark = True
            out_stall_events, out_stall_cycles, stall_count_reset = benchmark_counters
            self.out_stall_events = out_stall_events
            self.out_stall_cycles = out_stall_cycles
            self.stall_count_reset = stall_count_reset
        else:
            self.benchmark = False

    def elaborate(self, platform):
        m = Module()

        ## core modules and interconnections
        m.submodules.parser     = parser     = CommandParser()
        m.submodules.executor   = executor   = CommandExecutor(out_only=self.out_only, ext_switch_delay=self.ext_switch_delay, transforms=self.transforms)
        m.submodules.serializer = serializer = ImageSerializer()

        wiring.connect(m, parser.cmd_stream, executor.cmd_stream)
        wiring.connect(m, executor.img_stream, serializer.img_stream)

        from glasgow.hardware.multiplexer import _FIFOReadPort, _FIFOWritePort
        if isinstance(self.out_fifo, _FIFOReadPort):
            self.out_fifo.r_stream = self.out_fifo.stream
        if isinstance(self.in_fifo, _FIFOWritePort):
            self.in_fifo.w_stream = self.in_fifo.stream
        wiring.connect(m, self.out_fifo.r_stream, parser.usb_stream)
        wiring.connect(m, self.in_fifo.w_stream, serializer.usb_stream)

        m.d.comb += [
            self.in_fifo.flush.eq(executor.flush),
            serializer.output_mode.eq(executor.output_mode)
        ]


        ## Ports/resources ==========================================================
        platform.add_resources(obi_resources)

        if platform is not None:
            self.led            = platform.request("led", dir="-")
            self.control        = platform.request("control", dir={pin.name:"-" for pin in obi_resources[0].ios})
            self.data           = platform.request("data", dir="-")
        else: 
            self.led = io.SimulationPort("o",1)
            self.control = io.SimulationPort("io",7)
            self.control.x_latch  = io.SimulationPort("o",1,name="x_latch")
            self.control.y_latch  = io.SimulationPort("o",1,name="y_latch")
            self.control.a_latch  = io.SimulationPort("o",1,name="a_latch")
            self.control.a_enable = io.SimulationPort("o",1,name="a_enable")
            self.control.d_clock  = io.SimulationPort("o",1,name="d_clock")
            self.control.a_clock  = io.SimulationPort("o",1,name="a_clock")
            self.data = io.SimulationPort("io", 14)

        ### IO buffers
        m.submodules.led_buffer = led = io.Buffer("o", self.led)

        m.submodules.x_latch_buffer  = x_latch  = io.Buffer("o", self.control.x_latch)
        m.submodules.y_latch_buffer  = y_latch  = io.Buffer("o", self.control.y_latch)
        m.submodules.a_latch_buffer  = a_latch  = io.Buffer("o", self.control.a_latch)
        m.submodules.a_enable_buffer = a_enable = io.Buffer("o", self.control.a_enable)
        m.submodules.d_clock_buffer  = d_clock  = io.Buffer("o", self.control.d_clock)
        m.submodules.a_clock_buffer  = a_clock  = io.Buffer("o", self.control.a_clock)

        m.submodules.data_buffer = data = io.Buffer("io", self.data)

        ### use LED to indicate backpressure
        m.d.comb += led.o.eq(~serializer.usb_stream.ready)

        ### connect buffers to data + control signals
        m.d.comb += [
            x_latch.o.eq(executor.bus.dac_x_le_clk),
            y_latch.o.eq(executor.bus.dac_y_le_clk),
            a_latch.o.eq(executor.bus.adc_le_clk),
            a_enable.o.eq(executor.bus.adc_oe),
            d_clock.o.eq(executor.bus.dac_clk),
            a_clock.o.eq(executor.bus.adc_clk),

            data.o.eq(executor.bus.data_o),
            data.oe.eq(executor.bus.data_oe),

            #data.oe.eq(~self.control.power_good.i),
            #control.oe.eq(~self.control.power_good.i)
        ]

        #### External IO control logic  
        def connect_pins(pin_name: str, signal):
            if hasattr(self.ports, pin_name):
                if self.ports[f"{pin_name}"] is not None:
                    if not hasattr(m.submodules, f"{pin_name}_buffer"):
                        m.submodules[f"{pin_name}_buffer"] = io.Buffer("o", self.ports[f"{pin_name}"])
                    # drive every pin in port with 1-bit signal
                    for pin in m.submodules[f"{pin_name}_buffer"].o:
                        m.d.comb += pin.eq(signal)
        
        connect_pins("ebeam_scan_enable", executor.ext_ctrl_enable)      
        connect_pins("ibeam_scan_enable", executor.ext_ctrl_enable)
        connect_pins("ebeam_blank_enable", executor.ext_ctrl_enable)
        connect_pins("ibeam_blank_enable", executor.ext_ctrl_enable)

        with m.If(executor.ext_ctrl_enabled):
            with m.If(executor.beam_type == BeamType.NoBeam):
                connect_pins("ebeam_blank", 1)
                connect_pins("ibeam_blank", 1)

            with m.Elif(executor.beam_type == BeamType.Electron):
                connect_pins("ebeam_blank", executor.blank_enable)
                connect_pins("ibeam_blank", 1)
                
            with m.Elif(executor.beam_type == BeamType.Ion):
                connect_pins("ibeam_blank", executor.blank_enable)
                connect_pins("ebeam_blank", 1)
        with m.Else():
            # Do not blank if external control is not enabled
            connect_pins("ebeam_blank",0) #TODO: check diff pair behavior here
            connect_pins("ibeam_blank",0)
        
        #=================================================================== end resources

        if self.loopback: ## In loopback mode, connect input to output
            m.submodules.loopback_adapter = loopback_adapter = PipelinedLoopbackAdapter(executor.adc_latency)
            wiring.connect(m, executor.bus, flipped(loopback_adapter.bus))

            loopback_dwell_time = Signal()
            if self.loopback:
                m.d.sync += loopback_dwell_time.eq(executor.cmd_stream.payload.type == CmdType.RasterPixel)

            with m.If(loopback_dwell_time):
                m.d.comb += loopback_adapter.loopback_stream.eq(executor.supersampler.dac_stream_data.dwell_time)
            with m.Else():
                m.d.comb += loopback_adapter.loopback_stream.eq(executor.supersampler.super_dac_stream.payload.dac_x_code)
        else: ## if not in loopback, connect input to external input
            m.d.comb += executor.bus.data_i.eq(data.i)
            

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

        return m


class OBIApplet(GlasgowApplet):
    required_revision = "C3"
    logger = logging.getLogger(__name__)
    help = "open beam interface"
    description = """
    Scanning beam control applet
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "ebeam_scan_enable", range(1,3))
        access.add_pin_set_argument(parser, "ibeam_scan_enable", range(1,3))
        access.add_pin_set_argument(parser, "ebeam_blank_enable", range(1,3))
        access.add_pin_set_argument(parser, "ibeam_blank_enable", range(1,3))
        access.add_pin_set_argument(parser, "ibeam_blank", range(1,3))
        access.add_pin_set_argument(parser, "ebeam_blank", range(1,3))


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
        parser.add_argument("--out_only",
            dest = "out_only", action = 'store_true',
            help = "use FastBusController instead of BusController; don't use ADC")
        parser.add_argument("--ext_switch_delay", type=int, default=0,
            help="time for external control switch to actuate, in ms")


    def build(self, target, args):
        self.mux_interface = iface = \
                target.multiplexer.claim_interface(self, args)

        ports = iface.get_port_group(
            ebeam_scan_enable = args.pin_set_ebeam_scan_enable,
            ibeam_scan_enable = args.pin_set_ibeam_scan_enable,
            ebeam_blank_enable = args.pin_set_ebeam_blank_enable,
            ibeam_blank_enable = args.pin_set_ibeam_blank_enable,
            ebeam_blank = args.pin_set_ebeam_blank,
            ibeam_blank = args.pin_set_ibeam_blank,
        )

        subtarget_args = {
            "ports": ports,
            "in_fifo": iface.get_in_fifo(depth=512, auto_flush=False),
            "out_fifo": iface.get_out_fifo(depth=512),
            "loopback": args.loopback,
            "transforms": Transforms(args.xflip, args.yflip, args.rotate90),
            "out_only": args.out_only
        }

        if args.ext_switch_delay:
            ext_delay_cycles = int(args.ext_switch_delay * pow(10, -3) / (1/(48 * pow(10,6))))
            subtarget_args.update({"ext_switch_delay": ext_delay_cycles})

        if args.benchmark:
            out_stall_events, self.__addr_out_stall_events = target.registers.add_ro(8, init=0)
            out_stall_cycles, self.__addr_out_stall_cycles = target.registers.add_ro(16, init=0)
            stall_count_reset, self.__addr_stall_count_reset = target.registers.add_rw(1, init=1)
            subtarget_args.update({"benchmark_counters": [out_stall_events, out_stall_cycles, stall_count_reset]})

        subtarget = OBISubtarget(**subtarget_args)

        return iface.add_subtarget(subtarget)

    # @classmethod
    # def add_run_arguments(cls, parser, access):
    #     super().add_run_arguments(parser, access)

    async def run(self, device, args):
        from glasgow.device.simulation import GlasgowSimulationDevice
        if isinstance(device, GlasgowSimulationDevice):
            iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        else:
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

    async def run(self, args):
        await self.obi_iface.benchmark()
        # await self.obi_iface.server()