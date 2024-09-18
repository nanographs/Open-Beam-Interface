from amaranth import *
from amaranth.lib import data, wiring
from amaranth.lib.wiring import In, Out



class BinaryTreeAverager(wiring.Component):
    def __init__(self, *, value_shape, max_count: int):
        self.value_shape = value_shape
        self.max_count = max_count
        super().__init__(wiring.Signature({
            "i_stream": In(wiring.Signature({
                "data": Out(data.StructLayout({
                    "values": data.ArrayLayout(value_shape, max_count),
                    "last_n": range(max_count)
                })),
                "valid": Out(1),
                "ready": In(1)
            })),
            "o_stream": Out(wiring.Signature({
                "data": Out(value_shape),
                "valid": Out(1),
                "ready": In(1)
            }))
        }))

    def elaborate(self, platform):
        m = Module()

        layer = 0
        ready = self.i_stream.ready
        valid = self.i_stream.valid
        last_n = self.i_stream.data.last_n
        values = [self.i_stream.data.values[n] for n in range(self.max_count)]

        while len(values) > 1:
            next_ready = Signal.like(ready, name=f"l{layer+1}_ready")
            m.d.comb += ready.eq(next_ready | ~valid)

            with m.If(ready & valid):
                next_valid = Signal.like(valid, name=f"l{layer+1}_valid")
                m.d.sync += next_valid.eq(valid)
                next_last_n = Signal.like(last_n, name=f"l{layer+1}_last_n")
                m.d.sync += next_last_n.eq(last_n.shift_right(1))

                next_values = []

                for n in range(0, len(values), 2): # n = 0, 2, ...
                    name = f"l{layer+1}_value{n>>1}"
                    print(f"{name=}")
                    next_value = Signal(unsigned(self.value_shape.width + 1), name=name)
                    next_values.append(next_value)

                    print(f"{n=}, {len(values)=}")
                    if n + 1 == len(values):
                        print(f"edge mux")
                        print(f"if last_n >= {n}, values[{n}] x 2, else 0")
                        m.d.sync += next_value.eq(Mux(last_n >= n, values[n] + values[n], 0))
                    else:
                        print("node mux")
                        print(f"if last_n >= {n}")
                        print(f"\t if last_n >= {n+1}, values[{n}] + values[{-n}], else values[{n}] x 2")
                        print(f"else 0")
                        m.d.sync += next_value.eq(Mux(last_n >= n,
                                                    Mux(last_n >= n + 1,
                                                        (values[n] + values[n+1]),
                                                        values[n] + values[n]),
                                                    0))


            layer = layer + 1
            ready = next_ready
            valid = next_valid
            last_n = next_last_n
            values = next_values

            m.d.comb += [
                self.o_stream.data.eq(values[0].shift_right(layer)),
                self.o_stream.valid.eq(valid),
                ready.eq(self.o_stream.ready),
            ]

        return m



averager = BinaryTreeAverager(value_shape=unsigned(14), max_count=16)

from amaranth.sim import Simulator

sim = Simulator(averager)
sim.add_clock(1e-6)

def testbench():
    values = [1 + n * 3 for n in range(16)]
    print(values)
    for last_n in range(0, 16):
        for n in range(16):     
            yield averager.i_stream.data.values[n].eq(values[n])
            yield averager.i_stream.data.last_n.eq(last_n)
            yield averager.i_stream.valid.eq(1)
            yield averager.o_stream.ready.eq(1)
            yield
            yield averager.i_stream.valid.eq(0)
            yield
            yield
            yield
            yield
            yield
            yield

        print(f"python = {sum(values[:last_n+1]) // (last_n+1)}")
        print(f"amaranth = {(yield averager.o_stream.data)}")
        # break

sim.add_sync_process(testbench)

with sim.write_vcd("average.vcd"):
    sim.run()


