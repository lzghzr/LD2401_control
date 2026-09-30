"""Check Auditor tool relocation with synthetic fixtures; no candidate audit."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_ld2401_ufw as parser
import fw_audit
import q32s_xref as xref


def main():
    if not __debug__:
        raise SystemExit('Run without -O')
    assert Path(parser.__file__).resolve().parent == HERE
    assert fw_audit.load_parser(HERE) is parser
    assert parser.crc(b'123456789') == 0x31C3
    assert parser.cipher(parser.cipher(bytes(range(64)))) == bytes(range(64))
    header = bytearray(struct.pack('<HHIHHI48s', 0, 0, 64, 0, 0, 0, b'SYNTHETIC'))
    struct.pack_into('<H', header, 0, parser.crc(header[2:]))
    decoded, entries = parser.read_ufw(parser.cipher(header))
    assert decoded == header and entries == []
    bad = bytearray(header)
    bad[-1] ^= 1
    try:
        parser.read_ufw(parser.cipher(bad))
    except AssertionError:
        pass
    else:
        raise AssertionError('Corrupt header accepted')
    with tempfile.TemporaryDirectory(prefix='auditor tools ') as directory:
        listing = Path(directory) / 'synthetic.asm'
        listing.write_text('1000: 5f 16 \t[--sp] = rets\n'
                           '1002: bf f3 00 00 \tcall 0x8\n', encoding='utf-8')
        rows = xref.load_rows(listing)
        assert len(rows) == 2 and xref.function_of(rows, 0x1002) == 0x1000
        assert xref.branch_target(*rows[1]) == (0x100E, 'call')
        assert xref.branch_target(0x1002, bytes(4), 'call 8 <target : 100e >') == (0x100E, 'call')
        assert xref.branch_target(0x1002, bytes(4), 'goto -2 <target : 1004 >') == (0x1004, 'goto')
        subprocess.run([sys.executable, '-B', str(HERE / 'q32s_xref.py'),
                        '--asm', str(listing), 'callers', '0x100e'], cwd=directory,
                       stdout=subprocess.DEVNULL, check=True)
        table = Path(directory) / 'table.asm'
        table.write_text('1006: 02 00 \tdata\n', encoding='utf-8')
        result = subprocess.check_output([sys.executable, '-B', str(HERE / 'q32s_xref.py'),
                                          '--asm', str(table), 'table', '0x1006',
                                          '--base', '0x1008', '--count', '1'],
                                         cwd=directory, text=True)
        assert '0x100c' in result
        for tool in ('fw_audit.py', 'q32s_xref.py'):
            subprocess.run([sys.executable, '-B', str(HERE / tool), '--help'],
                           cwd=directory, stdout=subprocess.DEVNULL, check=True)
    print('PASS: Auditor local imports, CRC/header rejection, Q32S fixture, CLI entries')


if __name__ == '__main__':
    main()
