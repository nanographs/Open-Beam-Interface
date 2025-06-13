import asyncio
import array
import csv
import itertools

from obi.transfer import TCPConnection
from obi.macros.vector import VectorScanCommand
from obi.commands import OutputMode

async def main():
    # Open Connection
    # TCP server must be running at this port
    conn = TCPConnection('localhost', 2224)

    # Convert a CSV file into an iterator that yields (x, y, dwell)
    def iter_read_csv(path:str):
        with open(path, newline='') as csvfile:
            reader = csv.reader(csvfile, delimiter=',')
            for row in reader:
                x, y, dwell = [int(n) for n in row]
                yield (x, y, dwell) #if the csv file contains characters, this breaks

    # Iterate over the csv file twice - once when creating the vector commands, and again when writing the output
    send_iter, recv_iter = itertools.tee(iter_read_csv("points.csv"))

    # construct the vector scan command from an iterator that yields (x, y, dwell)
    cmd = VectorScanCommand(cookie=123, output_mode=OutputMode.EightBit, iter_points=send_iter)
    # convert vector commands into raw bytes
    # point commands are divided into chunks when combined dwell time exceeds 65536
    cmd._pre_process_chunks(latency=65536)

    # acquire the data
    res = array.array('B')
    async for chunk in conn.transfer_multiple(cmd):
        print(f"{chunk=}")
        res.extend(chunk)
    print(f"{res=}")

    # save the data into another csv in the format x, y, brightness
    with open("points_data.csv", 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter=',')
        for (x, y, dwell), (brightness) in zip(recv_iter, iter(res)):
            print(x, y, dwell, brightness)
            writer.writerow([x, y, brightness])


if __name__ == "__main__":
    asyncio.run(main())
