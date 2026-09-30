"""Pinned read-only UFW/JLFS parser for the Auditor toolkit.

Format/cipher algorithms are based on the local jl-misctools unpacker.
No device access. The parser does not write firmware or access a device.
The local chip key is decoded as needed and never included in the report.
"""
import binascii
import struct


def crc(data):
    return binascii.crc_hqx(data, 0)

def cipher(data, key=0xffff):
    out = bytearray(data)
    for i in range(len(out)):
        out[i] ^= key & 255
        key = ((key << 1) ^ (0x1021 if key & 0x8000 else 0)) & 0xffff
    return out

def entry(data, offset):
    raw = data[offset:offset+32]
    assert len(raw) == 32
    hcrc, dcrc, off, size, flags, reserved, last, name = struct.unpack('<HHIIBBH16s', raw)
    assert hcrc == crc(raw[2:]), f'JLFS header CRC at {offset:#x}'
    return dict(header=offset, data_crc=dcrc, offset=off, size=size,
                flags=flags, reserved=reserved, last=last,
                name=name.split(b'\0')[0].decode('ascii'))

def key_decode(data):
    s = sum(data[:16]) & 255
    s = 0xaa if s >= 0xe0 else 0x55 if s <= 0x10 else s
    return sum(1 << i for i in range(16) if (data[16+i] ^ data[15-i]) < s)

def sfc(data, start, end, base, key):
    assert (start-base) % 32 == 0
    for off in range(start, end, 32):
        n = min(32, end-off)
        data[off:off+n] = cipher(data[off:off+n], key ^ ((off-base) >> 2))

def read_ufw(data):
    header = cipher(data[:64])
    hc, lc, size, count, _, _, chip = struct.unpack('<HHIHHI48s', header)
    assert hc == crc(header[2:]), 'UFW header CRC'
    assert lc == crc(data[64:64+count*80]), 'UFW list CRC'
    entries = []
    for off in range(64, 64+count*80, 80):
        raw = cipher(data[off:off+80])
        kind, index, dc, reserved, pos, length, length2, extra, name = struct.unpack('<HHHHIII44s16s', raw)
        assert pos+length <= len(data), 'UFW payload bounds'
        payload = data[pos:pos+length]
        entries.append(dict(header=off, type=kind, index=index, data_crc=dc,
                            offset=pos, size=length, size2=length2,
                            crc_valid=crc(payload)==dc,
                            name=name.split(b'\0')[0].decode('ascii')))
    return header, entries

def audit(data, image_type=0):
    header, ufw = read_ufw(data)
    flash_ent = next(e for e in ufw if e['type'] == image_type)
    flash = bytearray(data[flash_ent['offset']:flash_ent['offset']+flash_ent['size']])
    fh = cipher(flash[:32])
    assert crc(fh[2:]) == int.from_bytes(fh[:2], 'little'), 'Flash header CRC'
    top = []
    off = 32
    while True:
        raw = cipher(flash[off:off+32])
        e = entry(raw, 0)
        e['header'] = off
        top.append(e)
        off += 32
        if e['last']:
            break
    key_ent = next(e for e in top if e['name'] == 'isd_config.ini')
    keydata = flash[key_ent['offset']:key_ent['offset']+34]
    assert crc(keydata[:32]) == int.from_bytes(keydata[32:], 'little')
    key = key_decode(keydata[:32])
    base = next(e['offset'] for e in top if e['name'] == 'app_dir_head')
    plain = bytearray(flash)
    # Decrypt the first SFC header, then exactly the blocks consumed by the iterator.
    sfc(plain, base, base+32, base, key)
    areas = []
    off = base
    decoded = base+32
    while True:
        e = entry(plain, off)
        assert e['size'] >= 32 and off+e['size'] <= len(plain)
        end = off+e['size']
        decode_end = end if e['last'] else (end+32+31)//32*32
        if decoded < decode_end:
            sfc(plain, decoded, decode_end, base, key)
            decoded = decode_end
        e['computed_data_crc'] = crc(plain[off+32:end])
        e['crc_valid'] = e['computed_data_crc'] == e['data_crc']
        areas.append(e)
        if e['last']:
            break
        off = end
    apparea = areas[0]
    appfiles = []
    off = base+32
    while True:
        e = entry(plain, off)
        start = base+e['offset']
        if e['flags'] & 0x10:
            e['crc_valid'] = True
            e['crc_check'] = 'not applicable: reserved area'
        else:
            assert start+e['size'] <= base+apparea['size'], repr(e)
            e['computed_data_crc'] = crc(plain[start:start+e['size']])
            e['crc_valid'] = e['computed_data_crc'] == e['data_crc']
        appfiles.append(e)
        if e['last']:
            break
        off += 32
    app = next(e for e in appfiles if e['name'] == 'app.bin')
    payload = bytes(plain[base+app['offset']:base+app['offset']+app['size']])
    return dict(ufw=ufw, top=top, areas=areas, appfiles=appfiles,
                base=base, end=decoded, key=key, plain=plain,
                flash=flash, flash_ent=flash_ent, header=header, app=app, payload=payload)
