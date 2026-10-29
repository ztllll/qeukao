#!/usr/bin/env python3
"""Verify the linked PE icon group and image bytes without third-party PE tools."""
import struct
import sys
from pathlib import Path


def check(path):
    data = Path(path).read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0"
    sections, optsize = struct.unpack_from("<H12xH", data, pe + 6)
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    directory = opt + (112 if magic == 0x20B else 96)
    resource_rva = struct.unpack_from("<I", data, directory + 16)[0]

    def offset(rva):
        for n in range(sections):
            s = opt + optsize + 40 * n
            size, start, raw_size, raw = struct.unpack_from("<IIII", data, s + 8)
            if start <= rva < start + max(size, raw_size):
                return raw + rva - start
        raise AssertionError("RVA outside PE sections")

    base = offset(resource_rva)

    def entries(relative):
        named, ids = struct.unpack_from("<HH", data, base + relative + 12)
        return dict(struct.unpack_from("<II", data, base + relative + 16 + i * 8)
                    for i in range(named + ids))

    def resource(kind, identity):
        types = entries(0)
        groups = entries(types[kind] & 0x7fffffff)
        languages = entries(groups[identity] & 0x7fffffff)
        leaf = next(iter(languages.values()))
        rva, size = struct.unpack_from("<II", data, base + leaf)
        start = offset(rva)
        return data[start:start + size]

    group = resource(14, 1)
    assert struct.unpack_from("<HHH", group) == (0, 1, 7)
    ico = (Path(__file__).resolve().parent / "qeukao-client.ico").read_bytes()
    sizes = []
    for n in range(7):
        width, height, _, _, planes, bits, length, identity = struct.unpack_from("<BBBBHHIH", group, 6 + n * 14)
        iw, ih, _, _, ip, ib, il, start = struct.unpack_from("<BBBBHHII", ico, 6 + n * 16)
        assert (width, height, planes, bits, length) == (iw, ih, ip, ib, il)
        assert resource(3, identity) == ico[start:start + il]
        sizes.append(width or 256)
    assert sizes == [16, 24, 32, 48, 64, 128, 256]
    print("%s: RT_GROUP_ICON=1; seven matching RT_ICON images %s" % (path, sizes))


if __name__ == "__main__":
    for filename in sys.argv[1:]:
        check(filename)
