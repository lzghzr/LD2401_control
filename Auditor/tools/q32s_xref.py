"""Cross-reference the q32s disassembly: what calls what, and where a table goes.

Input is an explicitly supplied Q32S llvm-objdump listing.
Branch operands are byte offsets from the end of the branching instruction:
    target = instruction_address + instruction_size + operand

Subcommands:

    func <addr>              function that contains <addr> (both prologue forms)
    callers <addr>           call/goto sites that reach <addr>, with their function
    chain <addr> [--depth N] walk `callers` upward N hops (how a feature is entered)
    refs <addr>              immediate load operands of <addr>, decimal or hex, plus raw
                             LE32 hits in --bin; a low address also matches constants
    sites --range LO HI      every call/goto site in a range and its resolved target
    table <addr> [--base B]  decode a jump table: entries are halfword offsets from the
                             address right after the table branch


`table` reflects the encoding observed in this build (each entry scaled by 2); pass
`--base` when the branch does not sit immediately before the table.
"""
import argparse
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import project_root, resolve_input  # noqa: E402

ROW = re.compile(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*\t(.*)$')
BRANCH = re.compile(r'\b(call|goto) (-?(?:0x[0-9a-f]+|[0-9]+))(?:\s+<[^>]*>)?$')
# llvm-objdump prints a register-load operand as a decimal number in most cases and as
# 0x... in others, then appends a "<symbol+0xNN : address >" annotation.  Only the operand
# is matched: the annotation of a branch is a target, not an immediate load, and matching
# the bare "= 0x" substring would also read a comparison such as "if (r0 != 0x1e5000)".
IMM = re.compile(r'\br\d+ = (0x[0-9a-fA-F]+|[0-9]+)\b')
TABLE_BRANCH = re.compile(r'\btb[hb]\b')


def immediate_loads(text):
    """Integer operands of the register-load instructions on one listing line."""
    return [int(value, 16) if value[:2].lower() == '0x' else int(value, 10)
            for value in IMM.findall(text)]


def load_rows(path):
    """[(address, raw_bytes, text)] in file order, unparsed lines dropped."""
    rows = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        m = ROW.match(line)
        if m:
            rows.append((int(m.group(1), 16), bytes(int(b, 16) for b in m.group(2).split()),
                         m.group(3).strip()))
    if not rows:
        raise SystemExit('no instructions parsed from %s' % path)
    return rows


def is_prologue(text):
    t = text.strip()
    return t.startswith('[--sp] = {rets') or t == '[--sp] = rets'


def function_of(rows, addr):
    """Start of the function containing `addr`, or None."""
    found = None
    for at, _blob, text in rows:
        if at > addr:
            break
        if is_prologue(text):
            found = at
    return found


def branch_target(at, blob, text):
    m = BRANCH.search(text)
    if not m:
        return None
    value = m.group(2)
    operand = int(value, 16 if '0x' in value else 10)
    return (at + len(blob) + operand) & 0x1FFFFFF, m.group(1)


def bytes_from(rows, start, length):
    """Raw bytes of the listing covering [start, start+length)."""
    out = bytearray()
    for at, blob, _text in rows:
        if start <= at < start + length:
            out.extend(blob)
    return bytes(out[:length])


def sub_func(rows, args):
    addr = int(args.target, 16)
    start = function_of(rows, addr)
    if start is None:
        print('no function start found at or before %s' % hex(addr))
        return 1
    print('function containing %s starts at %s (+%d)' % (hex(addr), hex(start), addr - start))
    return 0


def sub_callers(rows, args):
    addr = int(args.target, 16)
    hits = [(at, kind, function_of(rows, at)) for at, blob, text in rows
            for kind in [branch_target(at, blob, text)] if kind and kind[0] == addr]
    for at, (target, kind), func in hits:
        print('%s %s -> %s  in function %s'
              % (hex(at), kind, hex(target), hex(func) if func is not None else '?'))
    print('%d reference(s) to %s' % (len(hits), hex(addr)))
    return 0 if hits else 1


def sub_chain(rows, args):
    addr = int(args.target, 16)
    seen, level = set(), [addr]
    for hop in range(args.depth):
        nxt = []
        for target in level:
            for at, blob, text in rows:
                got = branch_target(at, blob, text)
                if got and got[0] == target and at not in seen:
                    seen.add(at)
                    func = function_of(rows, at)
                    print('hop %d: %s %s -> %s  (function %s)'
                          % (hop + 1, hex(at), got[1], hex(target),
                             hex(func) if func is not None else '?'))
                    if func is not None and func != at:
                        nxt.append(func)
        if not nxt:
            print('(no further callers)')
            break
        level = nxt
    return 0


def sub_refs(rows, args):
    addr = int(args.target, 16)
    # Both listing notations are read.  A low address can also equal an ordinary constant
    # (an object size, a mask), so each hit is a candidate to judge, not a proven pointer.
    hits = [(at, text) for at, _blob, text in rows if addr in immediate_loads(text)]
    for at, text in hits:
        print('%s  %s' % (hex(at), text))
    print('%d immediate load(s) of %s' % (len(hits), hex(addr)))
    if args.bin:
        data = Path(args.bin).read_bytes()
        needle, pos, raw = struct.pack('<I', addr), data.find(struct.pack('<I', addr)), []
        while pos >= 0:
            raw.append(pos)
            pos = data.find(needle, pos + 1)
        print('%d raw LE32 hit(s) in %s: %s'
              % (len(raw), Path(args.bin).name, [hex(p) for p in raw[:8]]))
    return 0 if hits else 1


def sub_sites(rows, args):
    lo, hi = args.range
    count = 0
    for at, blob, text in rows:
        if lo <= at <= hi:
            got = branch_target(at, blob, text)
            if got:
                print('%s  %-4s -> %s  (function %s)'
                      % (hex(at), got[1], hex(got[0]), hex(function_of(rows, at) or 0)))
                count += 1
    print('%d branch site(s) in %s..%s' % (count, hex(lo), hex(hi)))
    return 0


def sub_table(rows, args):
    table = int(args.target, 16)
    if args.base is None:
        base = None
        for at, blob, text in rows:
            if TABLE_BRANCH.search(text) and at < table:
                base = at + len(blob)
        if base is None:
            raise SystemExit('no table branch before %s; pass --base' % hex(table))
        print('table branch located, base %s' % hex(base))
    else:
        base = args.base
    for i in range(args.count):
        entry = bytes_from(rows, table + i * 2, 2)
        if len(entry) < 2:
            break
        value = int.from_bytes(entry, 'little', signed=True)
        print('index %2d (opcode %2d): entry 0x%04x -> %s'
              % (i, i + 1, value & 0xFFFF, hex((base + value * 2) & 0x1FFFFFF)))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--asm', type=Path, required=True, help='explicit Q32S disassembly path')
    ap.add_argument('--bin', type=Path, help='raw application image, for the `refs` pointer scan')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('func', 'callers', 'chain', 'refs'):
        p = sub.add_parser(name)
        p.add_argument('target', help='address, e.g. 0x1e10938')
        if name == 'chain':
            p.add_argument('--depth', type=int, default=4)
    p = sub.add_parser('sites')
    p.add_argument('--range', type=lambda s: int(s, 16), nargs=2, default=[0, 0x1FFFFFF],
                   metavar=('LO', 'HI'))
    p = sub.add_parser('table')
    p.add_argument('target', help='table address')
    p.add_argument('--base', type=lambda s: int(s, 16), help='table base (default: after the table branch)')
    p.add_argument('--count', type=int, default=27, help='entry count (default 27)')
    args = ap.parse_args()

    root = project_root(HERE)
    args.asm = resolve_input(args.asm, root)
    if args.bin:
        args.bin = resolve_input(args.bin, root)
    if not args.asm.exists():
        raise SystemExit('missing disassembly: %s (pass --asm, or generate it with the JL '
                         'toolchain - see README section on portability)' % args.asm)
    rows = load_rows(args.asm)
    return {'func': sub_func, 'callers': sub_callers, 'chain': sub_chain,
            'refs': sub_refs, 'sites': sub_sites, 'table': sub_table}[args.cmd](rows, args)


if __name__ == '__main__':
    sys.exit(main())
