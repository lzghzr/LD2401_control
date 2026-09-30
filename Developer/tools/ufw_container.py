"""Repack flash mirrors into the original UFW container."""
import struct
from ufw_format import read_ufw, cipher, crc

def repack(original, images):
    header, entries = read_ufw(original)
    result = bytearray(original[:min(e['offset'] for e in entries)])
    for e in entries:
        raw = cipher(original[e['header']:e['header']+80])
        struct.pack_into('<I', raw, 8, len(result))
        payload = images.get(e['type'])
        if payload is None:
            payload = original[e['offset']:e['offset']+e['size2']]
        else:
            struct.pack_into('<H', raw, 4, crc(payload))
            struct.pack_into('<II', raw, 12, len(payload), len(payload))
        result.extend(payload)
        result[e['header']:e['header']+80] = cipher(raw)
    struct.pack_into('<I', header, 4, len(result))
    struct.pack_into('<H', header, 2, crc(result[64:64+80*len(entries)]))
    struct.pack_into('<H', header, 0, crc(header[2:]))
    result[:64] = cipher(header)
    return bytes(result)
