#!/usr/bin/env python3
"""Crop the top-left WxH region out of a PNG (RGB/RGBA, 8-bit) without PIL.

Usage: python3 crop_png.py <src> <dst> <width> <height>, or import crop().
"""
import struct, sys, zlib


def crop(src, dst, W, H):
    data = open(src, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"

    pos, chunks, idat = 8, [], b""
    width = height = bitdepth = colortype = None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos+4])
        ctype = data[pos+4:pos+8]
        body = data[pos+8:pos+8+length]
        if ctype == b"IHDR":
            width, height, bitdepth, colortype = struct.unpack(">IIBB", body[:10])
        elif ctype == b"IDAT":
            idat += body
        pos += 12 + length

    assert bitdepth == 8 and colortype in (2, 6), (bitdepth, colortype)
    bpp = 3 if colortype == 2 else 4
    raw = zlib.decompress(idat)
    stride = width * bpp

    # unfilter
    prev = bytearray(stride)
    rows = []
    p = 0
    for _ in range(height):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p+stride]); p += stride
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i-bpp]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i-bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i-bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i-bpp] if i >= bpp else 0
                pp = a + b - c
                pa, pb, pc = abs(pp-a), abs(pp-b), abs(pp-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        rows.append(line)
        prev = line

    out_rows = b"".join(b"\x00" + bytes(r[:W*bpp]) for r in rows[:H])

    def chunk(t, b):
        c = struct.pack(">I", len(b)) + t + b
        return c + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, colortype, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(out_rows, 9))
           + chunk(b"IEND", b""))
    open(dst, "wb").write(png)
    print(f"cropped {W}x{H} ({len(png)} bytes) from {width}x{height}")


if __name__ == "__main__":
    crop(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
