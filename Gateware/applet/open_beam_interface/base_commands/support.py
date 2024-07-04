def dump_hex(data):
    def to_hex(data):
        try:
            data = memoryview(data)
        except TypeError:
            data = memoryview(bytes(data))
        if dump_hex.limit is None or len(data) < dump_hex.limit:
            return data.hex()
        else:
            return "{}... ({} bytes total)".format(
                data[:dump_hex.limit].hex(), len(data))
    return to_hex(data)

dump_hex.limit = 32