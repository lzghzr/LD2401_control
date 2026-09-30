"""Read section headers from the Q32S ELF emitted by the JieLi linker."""
import struct
from pathlib import Path


def elf_sections(path):
    data = Path(path).read_bytes()
    shoff, = struct.unpack_from('<I', data, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', data, 0x2e)
    headers = []
    for i in range(shnum):
        off = shoff + i * shentsize
        name, _typ, _flags, addr, offset, size = struct.unpack_from('<IIIIII', data, off)
        headers.append((name, addr, offset, size))
    strtab = headers[shstrndx]
    sections = {}
    for name, addr, offset, size in headers:
        start = strtab[2] + name
        end = data.index(b'\0', start)
        section_name = data[start:end].decode('ascii')
        sections[section_name] = {
            'addr': addr,
            'offset': offset,
            'size': size,
            'data': data[offset:offset + size],
        }
    return sections

