import amaranth
from amaranth import *
from amaranth.sim import Simulator, Tick
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out, flipped


from obi.applet.open_beam_interface import BusSignature

class SN74ALVCH16374(Elaboratable):
    def __init__(self):
        self.le_clk = Signal()
        self.oe = Signal()
        self.d = Signal(16)
        self.q = Signal(16)
    def elaborate(self, platform):
        m = Module()
        m.domains.le = le =  ClockDomain(local=True)
        m.d.comb += le.clk.eq(self.le_clk)
        m.d.le += self.q.eq(self.d)
        return m


class AD9744(Elaboratable):
    def __init__(self):
        self.clock = Signal()
        self.d = Signal(14)
        self.a = Signal(14) # analog output
    def elaborate(self, platform):
        m = Module()
        m.domains.dac_clock = dac_clock =  ClockDomain(local=True)
        m.d.comb += dac_clock.clk.eq(self.clock)
        m.d.dac_clock += self.a.eq(self.d)
        return m

class LTC2246H(Elaboratable):
    def __init__(self):
        self.clock = Signal()
        self.a = Signal(14) # analog input
        self.d = Signal(14)
    def elaborate(self, platform):
        m = Module()
        m.domains.adc_clock = adc_clock =  ClockDomain(local=True)
        m.d.comb += adc_clock.clk.eq(self.clock)

        sample_n_minus_5 = Signal(14)
        sample_n_minus_4 = Signal(14)
        sample_n_minus_3 = Signal(14)
        sample_n_minus_2 = Signal(14)
        sample_n_minus_1 = Signal(14)
        sample_n = Signal(14)

        m.d.comb += self.d.eq(sample_n_minus_5)

        m.d.adc_clock += sample_n.eq(self.a)
        m.d.adc_clock += sample_n_minus_1.eq(sample_n)
        m.d.adc_clock += sample_n_minus_2.eq(sample_n_minus_1)
        m.d.adc_clock += sample_n_minus_3.eq(sample_n_minus_2)
        m.d.adc_clock += sample_n_minus_4.eq(sample_n_minus_3)
        m.d.adc_clock += sample_n_minus_5.eq(sample_n_minus_4)
        return m


class OBI_Board(wiring.Component):
    # simulated digital inputs/output
    bus: In(BusSignature)
    def __init__(self, loopback=True):
        self.loopback=loopback
        ## simulated analog input
        self.adc_input = Signal(14)
        ## simulated hardware
        self.x_latch_chip = SN74ALVCH16374()
        self.y_latch_chip = SN74ALVCH16374()
        self.a_latch_chip = SN74ALVCH16374()
        self.x_dac_chip = AD9744()
        self.y_dac_chip = AD9744()
        self.a_adc_chip = LTC2246H()

        super().__init__()
    def elaborate(self, platform):
        m = Module()
        m.submodules["x_latch"] = self.x_latch_chip
        m.submodules["y_latch"] = self.y_latch_chip
        m.submodules["a_latch"] = self.a_latch_chip
        m.submodules["x_dac"] = self.x_dac_chip
        m.submodules["y_dac"] = self.y_dac_chip
        m.submodules["adc"] = self.a_adc_chip

        m.d.comb += self.x_latch_chip.le_clk.eq(self.bus.dac_x_le_clk)
        m.d.comb += self.y_latch_chip.le_clk.eq(self.bus.dac_y_le_clk)
        m.d.comb += self.a_latch_chip.le_clk.eq(self.bus.adc_le_clk)
        m.d.comb += self.x_latch_chip.oe.eq(1)
        m.d.comb += self.y_latch_chip.oe.eq(1)
        m.d.comb += self.a_latch_chip.oe.eq(self.bus.adc_oe)
        m.d.comb += self.x_dac_chip.clock.eq(self.bus.dac_clk)
        m.d.comb += self.y_dac_chip.clock.eq(self.bus.dac_clk)
        m.d.comb += self.a_adc_chip.clock.eq(self.bus.adc_clk)
        m.d.comb += self.x_dac_chip.d.eq(self.x_latch_chip.q)
        m.d.comb += self.y_dac_chip.d.eq(self.y_latch_chip.q)
        m.d.comb += self.a_latch_chip.d.eq(self.a_adc_chip.d)
        m.d.comb += self.a_adc_chip.a.eq(self.adc_input)
        m.d.comb += self.x_latch_chip.d.eq(self.bus.data_o)
        m.d.comb += self.y_latch_chip.d.eq(self.bus.data_o)
        m.d.comb += self.bus.data_i.eq(self.a_latch_chip.q)

        return m


if __name__ == "__main__":
    dut = SN74ALVCH16374()
    sim = Simulator(dut)
    sim.add_clock(20.83e-9)
    def testbench():
        yield dut.d.eq(1000)
        yield dut.oe.eq(1)
        yield Tick()
        yield dut.le_clk.eq(1)
        yield Tick()
        yield dut.le_clk.eq(0)

    sim.add_testbench(testbench)
    with sim.write_vcd("latch.vcd"):
        sim.run()