"""Audit one HLK UFW package against its own claims and the factory baseline.

Read-only.  Parses the package, the factory baseline, and - when asked - the build
report, the linked tail ELF and its disassembly, then reports what is proven and what
is not.  Exits non-zero when a check fails, so it can gate a delivery.

Inputs are supplied explicitly; see Auditor/README.md for commands.

Two coordinate systems are kept apart on purpose:

* CPU addresses map to application-image bytes with ``addr - 0x1e00120``.
* ``areas`` / ``appfiles`` offsets are inside the flash payload, exactly as the UFW
  records them; they are never mixed with CPU addresses.
"""
import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import lib_dir, project_root, resolve_input  # noqa: E402

BASE = 0x1E00120           # CPU address the application image is mapped at
PC_LIMIT = 0x1E09BFC       # stock execution/PC limit immediate
A0_STAMP = 0x1E1B488       # 4-byte UART A0 version constant (reverse the bytes to read it)
VERSION_BLOCK = 0x1E07A2A  # advertising manufacturer version block (38 bytes)
RESERVED = ('PRCT', 'VM', 'BTIF', 'EXIF')
SECTION_SKIP = (2, 3, 8, 11)   # SYMTAB, STRTAB, NOBITS, DYNSYM

# Hook sites of the tail-append design: address, width, purpose, factory bytes.  A site
# holding its factory bytes means that part of the design is not present in this package.
HOOK_SITES = [
    (0x1E03256, 4, 'frame hook (report path)', 'bff3a4f8'),
    (0x1E10A48, 4, 'scan-response hook', '80f3d79e'),
    (0x1E012F0, 4, 'A6 parameter branch', '00e02f12'),
    (0x1E01250, 4, 'A2 factory-restore hook', '5f16201b'),
    (0x1E0168C, 4, 'FE config-session store', '16f9d401'),
    (0x1E02110, 4, 'start hook (timer registration)', '80f3d595'),
    (0x1E04C82, 4, 'RX advertisement report hook', '00f905b0'),
]


class Report:
    """Collect check results so the printed summary and the JSON dump stay in step."""

    def __init__(self):
        self.rows = []

    def add(self, ident, status, detail=''):
        assert status in ('ok', 'FAIL', 'skip'), status
        self.rows.append(dict(id=ident, status=status, detail=detail))

    def failed(self):
        return [r for r in self.rows if r['status'] == 'FAIL']

    def counts(self):
        out = dict(ok=0, FAIL=0, skip=0)
        for r in self.rows:
            out[r['status']] += 1
        return out


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_parser(root):
    sys.path.insert(0, str(lib_dir(root)))
    import audit_ld2401_ufw as parser
    return parser


def app_file(state, name):
    for e in state.get('appfiles', []):
        if e['name'] == name:
            return e
    return None


def payload(state):
    return bytes(state['payload'])


def audit_image(rep, parser, data, kind):
    """Parse one flash image; a parse or CRC failure is reported, never raised."""
    try:
        state = parser.audit(data, kind)
    except Exception as exc:                      # parse/CRC assertions of the parser
        rep.add('container.image%s.parse' % kind, 'FAIL', '%s: %s' % (type(exc).__name__, exc))
        return None
    rep.add('container.image%s.flash_crc' % kind,
            'ok' if state['flash_ent']['crc_valid'] else 'FAIL',
            state['flash_ent'].get('name', 'flash entry'))
    nested = [e for group in ('areas', 'appfiles') for e in state[group]]
    bad = [e['name'] for e in nested if not e['crc_valid']]
    rep.add('container.image%s.nested_crc' % kind, 'ok' if not bad else 'FAIL',
            'failed entries: %s' % bad if bad else '%d entries checked' % len(nested))
    return state


def check_container_length(rep, parser, data):
    try:
        header, entries = parser.read_ufw(data)
    except Exception as exc:
        rep.add('container.list', 'FAIL', '%s: %s' % (type(exc).__name__, exc))
        return
    declared = int.from_bytes(header[4:8], 'little')
    rep.add('container.list', 'ok' if declared == len(data) else 'FAIL',
            'declared %d, file %d, %d entries' % (declared, len(data), len(entries)))


def check_mirrors(rep, new):
    if not (new.get(0) and new.get(32)):
        rep.add('mirrors.identical', 'skip', 'an image failed to parse')
        return
    a, b = payload(new[0]), payload(new[32])
    rep.add('mirrors.identical', 'ok' if a == b else 'FAIL', '%d / %d bytes' % (len(a), len(b)))


def check_layout(rep, new, stock_by_kind):
    """Reserved regions: what moved, what must not move, and the free margin left.

    Layout arithmetic stays in flash-payload coordinates: `appfiles` offsets are relative
    to the area start the parser reports as `base`, the VM/PRCT/BTIF/EXIF offsets are
    payload offsets, and the area appended after the recorded files (p11_code) adds its
    own size - the same sum the packaging helper uses.
    """
    for kind in (0, 32):
        state, stock = new.get(kind), stock_by_kind.get(kind)
        if state is None or stock is None:
            continue
        for name in RESERVED:
            e, s = app_file(state, name), app_file(stock, name)
            if e is None or s is None:
                rep.add('layout.image%s.%s' % (kind, name), 'skip', 'entry absent')
                continue
            moved = (e['offset'], e['size']) != (s['offset'], s['size'])
            end_ok = e['offset'] + e['size'] == s['offset'] + s['size']
            if name == 'VM':
                note = ('start %d->%d (%+d), size %d->%d, end %s'
                        % (s['offset'], e['offset'], e['offset'] - s['offset'],
                           s['size'], e['size'], 'preserved' if end_ok else 'MOVED'))
                if moved:
                    note += '; a moved VM region does not carry existing settings across the update'
                rep.add('layout.image%s.VM' % kind, 'ok' if end_ok else 'FAIL', note)
            elif name == 'PRCT':
                # The program region is [0, flash size] by design, so it tracks the package
                # size; the invariant is that it ends exactly where the VM region starts.
                vm_start = (app_file(state, 'VM') or {}).get('offset')
                ok = e['offset'] == 0 and e['size'] == vm_start
                rep.add('layout.image%s.PRCT' % kind, 'ok' if ok else 'FAIL',
                        'offset %d, size %d (baseline %d), VM starts %s'
                        % (e['offset'], e['size'], s['size'], vm_start))
            else:
                rep.add('layout.image%s.%s' % (kind, name), 'ok' if not moved else 'FAIL',
                        'offset %d, size %d' % (e['offset'], e['size']))
        vm = app_file(state, 'VM')
        if vm is not None:
            files_end = max(e['offset'] + e['size'] for e in state['appfiles']
                            if e['name'] not in RESERVED)
            trailing = sum(e['size'] for e in state['areas'] if e['name'] != 'app_area_head')
            content_end = state['base'] + files_end + trailing
            margin = vm['offset'] - content_end
            rep.add('layout.image%s.margin' % kind, 'ok' if margin > 0 else 'FAIL',
                    'content ends %d (= %d + %d + %d), VM starts %d, margin %d bytes'
                    % (content_end, state['base'], files_end, trailing, vm['offset'], margin))
    if all(new.get(k) and stock_by_kind.get(k) for k in (0, 32)):
        same = all(new[k]['key'] == stock_by_kind[k]['key'] for k in (0, 32))
        rep.add('layout.factory_key', 'ok' if same else 'FAIL',
                'factory key data %s' % ('preserved' if same else 'CHANGED'))


def check_report(rep, pkg, pkg_bytes, report_path):
    """A build report counts as evidence only for the package it names."""
    if report_path is None:
        rep.add('report.present', 'skip', 'no report supplied or found beside the package')
        return None
    if not report_path.exists():
        rep.add('report.present', 'FAIL', 'missing: %s' % report_path)
        return None
    rep.add('report.present', 'ok', str(report_path))
    report = json.loads(report_path.read_text(encoding='utf-8'))
    want = sha256(pkg_bytes)
    rep.add('report.binds_package', 'ok' if report.get('output_sha256') == want else 'FAIL',
            'report %s, package %s' % (str(report.get('output_sha256'))[:16], want[:16]))
    out = report.get('output')
    if out:
        # The report may have been produced on another OS, so split on either separator
        # instead of trusting this platform's path semantics.
        base = re.split(r'[\\/]', str(out))[-1]
        rep.add('report.names_package', 'ok' if base == pkg.name else 'FAIL',
                '%s vs %s' % (base, pkg.name))
    version = report.get('version')
    if version:
        rep.add('report.version_in_name', 'ok' if version in pkg.name else 'FAIL',
                'report %s, package %s' % (version, pkg.name))
    for key in ('vm_headroom_image0', 'vm_headroom_image32'):
        if key in report:
            rep.add('report.%s' % key, 'ok' if report[key] >= 0 else 'FAIL', str(report[key]))
    return report


def check_declared_changes(rep, stock_payload, report, app):
    """Every byte differing from the factory image must sit in a declared region."""
    allowed, covered_by = set(), 'the report patches plus the declared tail'
    if report and report.get('patches'):
        for p in report['patches']:
            at = int(p['address'], 16) - BASE
            allowed.update(range(at, at + p['size']))
    else:
        covered_by = 'the stock hook sites plus the version/limit fields (no report patches)'
        for addr, width, _why, _pre in HOOK_SITES:
            allowed.update(range(addr - BASE, addr - BASE + width))
        allowed.update(range(VERSION_BLOCK - BASE, VERSION_BLOCK - BASE + 38))
        allowed.update(range(A0_STAMP - BASE, A0_STAMP - BASE + 4))
        allowed.update(range(PC_LIMIT - BASE, PC_LIMIT - BASE + 4))
    tail_start = int(report['tail_start'], 16) - BASE if report and report.get('tail_start') else len(stock_payload)
    allowed.update(range(tail_start, len(app)))
    changed = [i for i in range(min(len(stock_payload), len(app))) if stock_payload[i] != app[i]]
    outside = [hex(BASE + i) for i in changed if i not in allowed]
    rep.add('changes.declared', 'ok' if not outside else 'FAIL',
            '%d bytes differ from the factory image; allowed set = %s; outside: %s'
            % (len(changed), covered_by, outside[:8] if outside else 'none'))
    return changed


def elf_sections(path):
    """Return [(name, addr, offset, size)] for the sections that carry image bytes."""
    text = path.read_bytes()
    if text[:4] != b'\x7fELF':
        raise ValueError('not an ELF: %s' % path)
    shoff, = struct.unpack_from('<I', text, 0x20)
    shentsize, shnum, _shstrndx = struct.unpack_from('<HHH', text, 0x2E)
    out = []
    for i in range(shnum):
        at = shoff + i * shentsize
        _name, typ, _flags, addr, offset, size = struct.unpack_from('<IIIIII', text, at)
        if not size or typ in SECTION_SKIP or addr < BASE:
            continue
        out.append((addr, offset, size))
    return out


def check_elf(rep, path, app):
    if path is None:
        rep.add('elf.matches_package', 'skip', 'no --elf given')
        return
    if not path.exists():
        rep.add('elf.matches_package', 'FAIL', 'missing: %s' % path)
        return
    try:
        sections = elf_sections(path)
    except Exception as exc:
        rep.add('elf.matches_package', 'FAIL', '%s: %s' % (type(exc).__name__, exc))
        return
    text = path.read_bytes()
    mismatched = []
    for addr, offset, size in sections:
        at = addr - BASE
        if app[at:at + size] != text[offset:offset + size]:
            mismatched.append(hex(addr))
    rep.add('elf.matches_package', 'ok' if not mismatched else 'FAIL',
            '%d sections compared; mismatched: %s' % (len(sections), mismatched[:6] or 'none'))


def check_pc_limit(rep, app, report):
    """The execution limit must cover exactly the image the report declares as linked."""
    at = PC_LIMIT - BASE
    if at + 4 > len(app):
        rep.add('image.pc_limit', 'skip', 'application image shorter than the limit field')
        return
    limit = int.from_bytes(app[at:at + 4], 'little')
    declared = None
    for key in ('new_app_end', 'tail_end'):
        if report and report.get(key):
            declared = int(report[key], 16)
            break
    if declared is None:
        rep.add('image.pc_limit', 'skip',
                'PC limit %s; the report declares no application end' % hex(limit))
        return
    image_end = BASE + len(app)
    rep.add('image.pc_limit', 'ok' if limit == declared == image_end else 'FAIL',
            'limit %s, report %s, image ends %s' % (hex(limit), hex(declared), hex(image_end)))


def version_block_immediates(asm):
    """Decimal immediates the advertising version block loads, in source order."""
    lines = asm.read_text(encoding='utf-8', errors='replace').splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith('Disassembly of section .version')), None)
    if start is None:
        return None
    out = []
    for line in lines[start + 1:]:
        if line.startswith('Disassembly of section'):
            break
        m = re.search(r'\tr[0-9]+ = ([0-9]+)$', line.rstrip())
        if m:
            out.append(int(m.group(1)))
    return out


def version_of(pkg_name, report):
    """Version digits: the build report's, else the 8-digit group in the package name."""
    if report and report.get('version'):
        return str(report['version'])
    m = re.search(r'(\d{8})', pkg_name)
    return m.group(1) if m else None


def check_version_stamps(rep, app, version, asm):
    """Both version stamps carry the version as byte-reversed hex pairs.

    The four bytes are the version string's hex, byte-reversed (so `26092430` is stored
    as `30 24 09 26`); the UART reply and the advertising block both reproduce it.
    """
    at = A0_STAMP - BASE
    stamp = app[at:at + 4]
    if len(stamp) != 4:
        rep.add('version.a0_stamp', 'FAIL', 'stamp field shorter than 4 bytes')
        return
    text = bytes(reversed(stamp)).hex()
    if version is None:
        rep.add('version.a0_stamp', 'skip', 'A0 stamp %s; no version to compare against' % text)
    else:
        rep.add('version.a0_stamp', 'ok' if text == version else 'FAIL',
                'A0 reads %s, expected %s' % (text, version))
    if asm is None:
        rep.add('version.advertising_block', 'skip',
                'no --asm given; block bytes %s' % app[VERSION_BLOCK - BASE:VERSION_BLOCK - BASE + 8].hex())
        return
    if not asm.exists():
        rep.add('version.advertising_block', 'FAIL', 'missing: %s' % asm)
        return
    seen = version_block_immediates(asm)
    if not seen:
        rep.add('version.advertising_block', 'FAIL', 'no .version section found in %s' % asm)
        return
    if version is None:
        rep.add('version.advertising_block', 'skip',
                'block immediates %s; no version to compare against' % seen)
        return
    # The listing prints the immediates in decimal; the block carries the version's hex
    # bytes, so compare values: version 26092430 -> seq 0x30 (48), month 0x09 (9), year 0x26 (38).
    want = (int(version[6:8], 16), int(version[2:4], 16), int(version[0:2], 16))
    missing = [hex(v) for v in want if v not in seen]
    rep.add('version.advertising_block', 'ok' if not missing else 'FAIL',
            'block immediates %s; version %s implies seq/month/year %s'
            % (seen, version, tuple(hex(v) for v in want)))


def check_hooks(rep, app, stock_payload, asm):
    lines = []
    if asm is not None and asm.exists():
        lines = asm.read_text(encoding='utf-8', errors='replace').splitlines()
    at_line = {}
    for line in lines:
        m = re.match(r'\s*([0-9a-f]{5,8}):', line)
        if m:
            at_line[int(m.group(1), 16)] = line
    for addr, width, why, factory in HOOK_SITES:
        at = addr - BASE
        now = app[at:at + width].hex()
        base_bytes = stock_payload[at:at + width].hex()
        target = ''
        line = at_line.get(addr)
        if line:
            m = re.search(r'<([^>]+)>', line)
            if m:
                target = ' -> %s' % m.group(1)
        if base_bytes != factory:
            rep.add('hook.%s' % hex(addr), 'FAIL',
                    'factory bytes at this site are %s, expected %s (baseline layout differs)'
                    % (base_bytes, factory))
            continue
        if now == factory:
            rep.add('hook.%s' % hex(addr), 'skip',
                    'factory instruction kept (%s); this feature is not in the package' % why)
        else:
            rep.add('hook.%s' % hex(addr), 'ok', '%s%s  (%s)' % (now, target, why))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--package', type=Path, required=True, help='explicit candidate UFW path')
    ap.add_argument('--stock', type=Path, required=True, help='LD2401_2.50.24110415.ufw baseline path')
    ap.add_argument('--report', type=Path, help='build report (default: sibling build-report.json)')
    ap.add_argument('--no-report', action='store_true', help='audit without any build report')
    ap.add_argument('--elf', type=Path, help='linked tail ELF to compare against the package')
    ap.add_argument('--asm', type=Path, help='disassembly of that ELF (llvm-objdump -d)')
    ap.add_argument('--json', type=Path, help='write the structured result here')
    args = ap.parse_args()

    root = project_root(HERE)
    parser = load_parser(root)
    if not __debug__:
        raise SystemExit('Run without -O: parser validation uses assertions')
    pkg_path = resolve_input(args.package, root)
    stock_path = resolve_input(args.stock, root)
    for path in (pkg_path, stock_path):
        if not path.is_file():
            raise SystemExit('input not found: %s' % path)
    report_path = None
    if not args.no_report:
        report_path = resolve_input(args.report, root) if args.report \
            else pkg_path.parent / 'build-report.json'
    elf = resolve_input(args.elf, root) if args.elf else None
    asm = resolve_input(args.asm, root) if args.asm else None

    pkg_bytes, stock_bytes = pkg_path.read_bytes(), stock_path.read_bytes()
    rep = Report()
    expected_stock = '3e518750921f9392eb71da0becc641915d4204376f7eb571c54ed4f586bab9a7'
    rep.add('baseline.sha256', 'ok' if sha256(stock_bytes) == expected_stock else 'FAIL',
            sha256(stock_bytes))
    check_container_length(rep, parser, pkg_bytes)
    new = {0: audit_image(rep, parser, pkg_bytes, 0), 32: audit_image(rep, parser, pkg_bytes, 32)}
    stock_by_kind = {}
    for kind in (0, 32):
        try:
            stock_by_kind[kind] = parser.audit(stock_bytes, kind)
        except Exception as exc:
            rep.add('baseline.image%s' % kind, 'FAIL', '%s: %s' % (type(exc).__name__, exc))
    check_mirrors(rep, new)
    check_layout(rep, new, stock_by_kind)
    report = check_report(rep, pkg_path, pkg_bytes, report_path)
    version = version_of(pkg_path.name, report)
    app = payload(new[0]) if new.get(0) else b''
    if app and stock_by_kind.get(0):
        check_declared_changes(rep, payload(stock_by_kind[0]), report, app)
        check_elf(rep, elf, app)
        check_pc_limit(rep, app, report)
        check_version_stamps(rep, app, version, asm)
        check_hooks(rep, app, payload(stock_by_kind[0]), asm)

    print('audit: %s' % pkg_path.name)
    print('  sha256   %s  (%d bytes)' % (sha256(pkg_bytes), len(pkg_bytes)))
    print('  baseline %s' % stock_path.name)
    print()
    width = max(len(r['id']) for r in rep.rows)
    for row in rep.rows:
        print('  %-4s %-*s  %s' % (row['status'], width, row['id'], row['detail']))
    counts = rep.counts()
    print('\n  %d ok, %d failed, %d skipped' % (counts['ok'], counts['FAIL'], counts['skip']))
    if args.json:
        args.json.write_text(json.dumps(dict(package=str(pkg_path), sha256=sha256(pkg_bytes),
                                             baseline=str(stock_path),
                                             report=str(report_path) if report_path else None,
                                             checks=rep.rows, counts=counts),
                                        ensure_ascii=False, indent=2), encoding='utf-8')
        print('  wrote %s' % args.json)
    if rep.failed():
        print('AUDIT FAILED: ' + ', '.join(r['id'] for r in rep.failed()))
        return 1
    print('STATIC CHECKS PASSED (review skips and coverage in Auditor/README.md)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
