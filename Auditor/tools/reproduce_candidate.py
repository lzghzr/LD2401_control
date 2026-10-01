"""Rebuild one candidate independently and bind the sources to its package.

This tool does not import ``Developer/tools/build.py``.  It compiles the committed
Q32S sources with the pinned toolchain itself, links them with the recorded linker
script, reads the resulting ELF with its own section reader, and checks that every
allocated section appears byte-for-byte in the candidate package at its linked
address.  It also derives the application end from the ELF and compares it with the
execution-limit immediate inside the package, so the package is bound to the sources
without trusting the build report.

Read-only for the repository: all outputs go to an explicit empty directory.
"""
import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import project_root, resolve_input  # noqa: E402
import audit_ld2401_ufw as parser  # noqa: E402

BASE = 0x1E00120            # CPU address of the application image
PC_LIMIT = 0x1E09BFC        # stock execution/PC limit immediate
SHT_NOBITS = 8
SHF_ALLOC = 0x2
SOURCE_FILES = ('payload.c', 'scanrsp.c', 'rxcontrol.c')
# Only payload.c takes the feature define; the other files are feature-neutral.
DEFINE_TARGET = 'payload.c'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def version_digits(version):
    """Advertising version byte order: sequence, month, year (all as hex pairs)."""
    return {'VSEQ': '0x' + version[6:8], 'VMON': '0x' + version[2:4], 'VYY': '0x' + version[0:2]}


def substitute(source, version, where):
    out = source
    for name, value in version_digits(version).items():
        out = out.replace('%%' + name + '%%', value)
    if leftover := re.findall(r'%%[A-Z]+%%', out):
        raise SystemExit('%s: unsubstituted placeholder %s' % (where, leftover))
    return out


def elf_sections(path):
    """Return [(name, addr, data)] for allocated, non-empty, non-NOBITS sections."""
    blob = path.read_bytes()
    if blob[:4] != b'\x7fELF':
        raise SystemExit('not an ELF: %s' % path)
    if blob[4] != 1:
        raise SystemExit('only 32-bit ELF is expected: %s' % path)
    shoff, = struct.unpack_from('<I', blob, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', blob, 0x2E)
    headers = [struct.unpack_from('<IIIIIIIIII', blob, shoff + i * shentsize)
               for i in range(shnum)]
    strtab = headers[shstrndx]
    names = blob[strtab[4]:strtab[4] + strtab[5]]
    out = []
    for name_at, typ, flags, addr, offset, size in ((h[0], h[1], h[2], h[3], h[4], h[5]) for h in headers):
        if not size or typ == SHT_NOBITS or not flags & SHF_ALLOC or addr < BASE:
            continue
        name = names[name_at:names.index(b'\0', name_at)].decode('ascii', 'replace')
        out.append((name, addr, blob[offset:offset + size]))
    return out


def run(command, cwd=None):
    result = subprocess.run([str(part) for part in command], cwd=cwd,
                            capture_output=True, text=True, errors='replace')
    if result.returncode:
        raise SystemExit('command failed (%d): %s\n%s\n%s'
                         % (result.returncode, ' '.join(str(c) for c in command),
                            result.stdout[-2000:], result.stderr[-2000:]))
    return result.stdout


def build(root, out, version, define, toolchain):
    (out / 'hooks_gen.s').write_text(
        substitute((root / 'Developer/src/hooks.s').read_text(encoding='utf-8'), version,
                   'Developer/src/hooks.s'), encoding='utf-8')
    cc = [toolchain / 'clang.exe', '-target', 'q32s', '-Os', '-fno-builtin']
    objects = []
    for name in SOURCE_FILES:
        obj = out / (name + '.o')
        command = cc + (['-D' + define] if define and name == DEFINE_TARGET else []) \
            + ['-c', root / 'Developer/src' / name, '-o', obj]
        run(command)
        objects.append(obj)
    hooks = out / 'hooks.s.o'
    run([toolchain / 'clang.exe', '-target', 'q32s', '-integrated-as',
         '-c', out / 'hooks_gen.s', '-o', hooks])
    objects.append(hooks)
    elf = out / 'tail.elf'
    run([toolchain / 'q32s-ld.exe', '-T', root / 'Developer/linker/layout.ld', *objects,
         '-o', elf])
    (out / 'tail.asm').write_text(
        run([toolchain / 'llvm-objdump.exe', '-d', elf]), encoding='utf-8')
    return elf, out / 'tail.asm'


def asm_section(asm, section):
    lines, inside = [], False
    for line in asm.read_text(encoding='utf-8', errors='replace').splitlines():
        if line.startswith('Disassembly of section'):
            inside = line.strip().endswith(section + ':')
            continue
        if inside:
            lines.append(line)
    return lines


IMMEDIATE = re.compile(r'\br\d+ = (0x[0-9a-fA-F]+|[0-9]+)\b')


def immediate_loads(asm, address):
    """Load sites of an address literal, in both listing notations.

    This keeps the reference scan inside the same run that links the source, so the
    binding and the code survey are produced from one build.  A low address can also
    equal an ordinary constant (an object size, a mask); every hit is printed so it can
    be judged.  ``q32s_xref.py refs`` answers the same question against any listing.
    """
    hits = []
    for line in asm.read_text(encoding='utf-8', errors='replace').splitlines():
        if any((int(value, 16) if value[:2].lower() == '0x' else int(value, 10)) == address
               for value in IMMEDIATE.findall(line)):
            hits.append(line.strip())
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--package', type=Path, required=True, help='candidate UFW to bind')
    ap.add_argument('--out', type=Path, required=True, help='empty output directory')
    ap.add_argument('--version', default='26092431')
    ap.add_argument('--define', default='LD24_OUT_MODE_STATUS',
                    help='feature define for payload.c; empty for the 26092430 layout')
    ap.add_argument('--toolchain', type=Path,
                    default=Path(os.environ.get('JL_Q32S_BIN', 'C:/JL/pi32/bin')),
                    help='directory holding the pinned clang/q32s-ld/llvm-objdump')
    ap.add_argument('--elf', type=Path, help='optional shipped tail ELF to compare with')
    ap.add_argument('--require-immediate', action='append', default=[],
                    help='address literal that must appear in the .crypto disassembly')
    ap.add_argument('--forbid-immediate', action='append', default=[],
                    help='address literal that must not appear in the .crypto disassembly')
    ap.add_argument('--ref', action='append', default=[],
                    help='address whose immediate load sites are printed (e.g. 0x4514)')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()

    root = project_root(HERE)
    package = resolve_input(args.package, root)
    out = resolve_input(args.out, root)
    if out.exists() and any(out.iterdir()):
        raise SystemExit('output directory must be empty: %s' % out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []

    def add(ident, ok, detail):
        rows.append(dict(id=ident, status='ok' if ok else 'FAIL', detail=detail))
        return ok

    tool_hashes = json.loads((root / 'metadata/firmware-26092430.json')
                             .read_text(encoding='utf-8'))['toolchain_sha256s']
    for name, expected in tool_hashes.items():
        tool = resolve_input(args.toolchain, root) / name
        got = sha256(tool.read_bytes()) if tool.is_file() else None
        add('toolchain.%s' % name, got == expected, got or 'missing')

    elf, asm = build(root, out, args.version, args.define, resolve_input(args.toolchain, root))
    sections = elf_sections(elf)
    tail_end = max(addr + len(data) for _n, addr, data in sections)

    state = parser.audit(package.read_bytes(), 0)
    app = state['payload']
    add('image.length', len(app) == tail_end - BASE,
        'package app %d bytes, linked tail ends %s (%d bytes)'
        % (len(app), hex(tail_end), tail_end - BASE))

    mismatched = []
    for name, addr, data in sections:
        at = addr - BASE
        if app[at:at + len(data)] != data:
            mismatched.append('%s@%s' % (name, hex(addr)))
    add('sections.in_package', not mismatched,
        '%d allocated sections compared, mismatched: %s'
        % (len(sections), ', '.join(mismatched[:8]) or 'none'))

    limit = int.from_bytes(app[PC_LIMIT - BASE:PC_LIMIT - BASE + 4], 'little')
    add('image.pc_limit', limit == tail_end,
        'limit %s, linked tail end %s' % (hex(limit), hex(tail_end)))

    if args.elf:
        shipped = resolve_input(args.elf, root)
        want = {name: data for name, _addr, data in elf_sections(shipped)}
        have = {name: data for name, _addr, data in sections}
        differ = sorted(set(want) ^ set(have)) + \
            sorted(n for n in set(want) & set(have) if want[n] != have[n])
        add('sections.shipped_elf', not differ, 'sections differing from %s: %s'
            % (shipped.name, ', '.join(differ) or 'none'))

    crypto = '\n'.join(asm_section(asm, '.crypto'))
    for literal in args.require_immediate:
        add('asm.requires.%s' % literal, literal.lower() in crypto.lower(),
            'literal in .crypto disassembly')
    for literal in args.forbid_immediate:
        add('asm.forbids.%s' % literal, literal.lower() not in crypto.lower(),
            'literal absent from .crypto disassembly')

    references = {}
    for value in args.ref:
        address = int(value, 16)
        hits = immediate_loads(asm, address)
        references[value] = hits
        print('  ref  %-10s %d immediate load site(s)' % (value, len(hits)))
        for line in hits:
            print('         %s' % line[:110])

    print('reproduce: %s  version %s  define %s'
          % (package.name, args.version, args.define or '(none)'))
    print('  package sha256 %s' % sha256(package.read_bytes()))
    print('  linked tail    %s .. %s  (%d sections)'
          % (hex(BASE), hex(tail_end), len(sections)))
    for row in rows:
        print('  %-4s %-34s %s' % (row['status'], row['id'], row['detail']))
    failed = [r for r in rows if r['status'] == 'FAIL']
    print('\n  %d ok, %d failed' % (len(rows) - len(failed), len(failed)))
    if args.json:
        args.json.write_text(json.dumps(dict(
            package=str(package), sha256=sha256(package.read_bytes()), version=args.version,
            define=args.define or None, tail_end=hex(tail_end), sections=len(sections),
            references=references, checks=rows), ensure_ascii=False, indent=2), encoding='utf-8')
        print('  wrote %s' % args.json)
    if failed:
        print('REPRODUCTION FAILED: ' + ', '.join(r['id'] for r in failed))
        return 1
    print('INDEPENDENT REBUILD MATCHES THE PACKAGE')
    return 0


if __name__ == '__main__':
    sys.exit(main())