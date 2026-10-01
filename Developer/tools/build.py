"""Build versioned LD2401 candidates from the pinned factory base."""
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
ROOT = HERE.parents[1]
SRC = ROOT / 'Developer/src'
LINKER = ROOT / 'Developer/linker/layout.ld'
sys.path.insert(0, str(HERE))
from ufw_format import parse_flash_image, read_ufw  # noqa: E402
from flash_layout import transplant_image  # noqa: E402
from ld24_elf_sections import elf_sections  # noqa: E402
from ufw_container import repack  # noqa: E402

BIN = Path(os.environ.get('JL_Q32S_BIN', 'C:/JL/pi32/bin'))
BASE_IN = ROOT / 'vendor/LD2401_2.50.24110415.ufw'
BASE = 0x1e00120
STOCK_SHA = '3e518750921f9392eb71da0becc641915d4204376f7eb571c54ed4f586bab9a7'
sha = lambda b: hashlib.sha256(b).hexdigest()

EXPECTED_SHA = '7e74ed708e109bbd721371a2b74244ea52743be85e9b251198cecdf1f23add7d'
CANDIDATE_SHA = '367df6fde866918147b5ad5e61257e0cc8db00fecd872a2a6390885b9565872a'
ap = argparse.ArgumentParser(description='Build LD2401 firmware (JieLi Q32S).')
ap.add_argument('--version', choices=('26092430', '26092431'), default='26092431')
ap.add_argument('--build-id', help='Candidate identity recorded in the build report')
ap.add_argument('--stock', type=Path, default=BASE_IN, help='Pinned factory UFW input')
ap.add_argument('--toolchain', type=Path, default=BIN, help='Directory containing Q32S tools')
ap.add_argument('--output-dir', type=Path, help='An empty candidate output directory')
ap.add_argument('--check-inputs', action='store_true', help='Validate inputs without compiling')
ap.add_argument('--release', action='store_true', help='Require a clean Git commit for handoff')
args = ap.parse_args()
if not __debug__:
    ap.error('Run normal Python; -O disables required assertions')
BASE_IN = args.stock.resolve()
BIN = args.toolchain.resolve()
VERSION = args.version
BUILD_ID = args.build_id or VERSION
WORK = (args.output_dir or ROOT / 'build' / BUILD_ID).resolve()
for protected in ('Developer', 'Auditor', 'Tester', 'custom_components', 'esphome',
                  'metadata', 'docs', 'tools', 'third_party', '.github'):
    if (ROOT / protected).resolve() in (WORK, *WORK.parents):
        ap.error('Place build outputs outside public source directories')
for source in (*SRC.glob('*.c'), SRC / 'hooks.s', LINKER):
    if not source.is_file():
        ap.error('Missing source: ' + str(source))
if not BASE_IN.is_file():
    ap.error('Provide the factory UFW with --stock; see docs/firmware-build.md')
if sha(BASE_IN.read_bytes()) != STOCK_SHA:
    ap.error('Factory UFW SHA-256 does not match the pinned baseline')
for executable in ('clang.exe', 'q32s-ld.exe', 'llvm-objdump.exe'):
    if not (BIN / executable).is_file():
        ap.error('Missing Q32S tool: ' + str(BIN / executable))
tool_hashes = json.loads((ROOT / 'metadata/firmware-26092430.json').read_text())['toolchain_sha256s']
for executable, expected in tool_hashes.items():
    if sha((BIN / executable).read_bytes()) != expected:
        ap.error('Q32S tool hash differs from the verified toolchain: ' + executable)
try:
    commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                                     text=True, stderr=subprocess.DEVNULL).strip()
    git_root = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', '--show-toplevel'],
                                       text=True).strip()
    if Path(git_root).resolve() != ROOT:
        raise ValueError('This distribution must have its own repository root')
    dirty = bool(subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain'], text=True))
except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
    commit, dirty = None, True
if args.release and (not commit or dirty):
    ap.error('Release builds require this repository to have a clean committed source tree')
if args.check_inputs:
    print(json.dumps({'version': VERSION, 'build_id': BUILD_ID, 'input_sha256': STOCK_SHA,
                      'tools_found': True, 'git_commit': commit, 'dirty': dirty}))
    raise SystemExit(0)
if WORK.exists() and any(WORK.iterdir()):
    ap.error('Output directory must be empty; preserve previous build artifacts')
WORK.mkdir(parents=True, exist_ok=True)
args.variant = 'plain'
V = dict(define='LD24_OUT_MODE_STATUS' if VERSION == '26092431' else None,
         notes='Encrypted BTHome telemetry and authenticated OUT control; '
         'random persistent Bindkey, reserved counters, full-width RX context pointer. '
         'Undocumented factory commands remain available.')
if V['define']:
    V['notes'] += ' Manual-hold feedback in every authenticated telemetry frame.'
OUTPUT = WORK / f'LD2401_2.50_{VERSION}.ufw'
REPORT = WORK / 'build-report.json'

raw = BASE_IN.read_bytes()
assert sha(raw) == STOCK_SHA, 'unexpected stock package'
states = {k: parse_flash_image(raw, k) for k in (0, 32)}
stock = states[0]['payload']
assert stock == states[32]['payload'], 'stock mirrors differ'

# ------------------------------------------------------------------ build sources
# version string is YYMM24nn: the middle '24' is the company-id byte the advertising
# manufacturer segment reuses, so the family never changes - only the sequence moves.
yy, mm, seq = VERSION[0:2], VERSION[2:4], VERSION[6:8]
assert VERSION[4:6] == '24', 'version must stay in the 260924xx family'
hooks_src = (SRC / 'hooks.s').read_text(encoding='utf-8')
assert '%%VSEQ%%' in hooks_src
hooks_gen = hooks_src.replace('%%VSEQ%%', '0x' + seq).replace('%%VMON%%', '0x' + mm) \
                     .replace('%%VYY%%', '0x' + yy)
for leftover in re.findall(r'%%[A-Z]+%%', hooks_gen):
    raise SystemExit('unsubstituted placeholder ' + leftover)
(WORK / 'hooks_gen.s').write_text(hooks_gen, encoding='utf-8')

cc = [str(BIN / 'clang.exe'), '-target', 'q32s', '-Os', '-fno-builtin']
for src in ('payload.c', 'scanrsp.c', 'rxcontrol.c'):
    cmd = cc + ['-c', str(SRC / src), '-o', str(WORK / (src + '.o'))]
    if V['define'] and src == 'payload.c':
        cmd.insert(4, '-D' + V['define'])
    subprocess.run(cmd, check=True)
subprocess.run([str(BIN / 'clang.exe'), '-target', 'q32s', '-integrated-as',
                '-c', str(WORK / 'hooks_gen.s'), '-o', str(WORK / 'hooks.s.o')], check=True)
ELF = WORK / f'tail_{args.variant}.elf'
subprocess.run([str(BIN / 'q32s-ld.exe'), '-T', str(LINKER),
                str(WORK / 'payload.c.o'), str(WORK / 'scanrsp.c.o'),
                str(WORK / 'rxcontrol.c.o'), str(WORK / 'hooks.s.o'),
                '-o', str(ELF)], check=True)
dump = subprocess.check_output([str(BIN / 'llvm-objdump.exe'), '-d', str(ELF)],
                               text=True, errors='replace')
(WORK / f'tail_{args.variant}.asm').write_text(dump, encoding='utf-8')
sec = elf_sections(ELF)

TAIL_START = 0x1e2a454                      # end of the stock app.bin
TAIL_SECTIONS = ['.guard', '.scanrsp', '.capture', '.a6', '.a2', '.lock',
                 '.crypto', '.cdata', '.aes', '.rxshim', '.rxcode', '.rxconst']
HOOKS = ['.frame_hook', '.scanrsp_hook', '.a6_branch', '.a2_hook', '.fe_fix',
         '.start_hook', '.rx_report_hook', '.version']
assert min(sec[n]['addr'] for n in TAIL_SECTIONS) == TAIL_START
tail_end = max(sec[n]['addr'] + sec[n]['size'] for n in TAIL_SECTIONS)
assert all(sec[n]['addr'] > tail_end - 0x2000 for n in TAIL_SECTIONS)

# ------------------------------------------------------------------ assemble app
app = bytearray(stock)
app.extend(bytes(tail_end - TAIL_START))     # zero-filled tail region
for n in TAIL_SECTIONS:
    off = sec[n]['addr'] - BASE
    app[off:off + len(sec[n]['data'])] = sec[n]['data']
assert len(app) == tail_end - BASE
app.extend(b'\x00' * ((-len(app)) % 4))
app_end = BASE + len(app)

patches = []


def patch(addr, data, label):
    off = addr - BASE
    assert 0 <= off and off + len(data) <= len(app), hex(addr)
    before = bytes(app[off:off + len(data)])
    assert before != data, 'no-op patch: ' + label
    app[off:off + len(data)] = data
    patches.append(dict(address=hex(addr), size=len(data), before=before.hex(),
                        after=data.hex(), purpose=label))


STOCK_PREIMAGE = {
    '.frame_hook': 'bff3a4f8',      # call stock_report_mode -> report_hook
    '.scanrsp_hook': '80f3d79e',    # call 0x1e247fa -> scanrsp_hook
    '.a6_branch': '00e02f12',       # if (param != 0) goto reject -> goto a6_tail
    '.a2_hook': '5f16201b',         # stock restore call + success goto -> checked wrapper
    '.fe_fix': '16f9d401',          # preserve A6-selected manual OUT hold at 0x4514 across FE
    '.start_hook': '80f3d595',      # stock_timer_add call -> refresh_start wrapper
    '.rx_report_hook': '00f905b0',  # stock report gate load -> candidate copy and replay
}
for name, pre in STOCK_PREIMAGE.items():
    off = sec[name]['addr'] - BASE
    assert bytes(app[off:off + 4]) == bytes.fromhex(pre), (name, hex(app[off:off + 4]))
    patch(sec[name]['addr'], sec[name]['data'], 'hook ' + name)
off = sec['.version']['addr'] - BASE
assert bytes(app[off:off + 4]) == bytes.fromhex('5171d1f5'), 'version block pre-image changed'
patch(sec['.version']['addr'], sec['.version']['data'],
      'advertising version block (4 date bytes) -> ' + VERSION)
patch(0x1e1b488, bytes.fromhex(VERSION)[::-1], 'UART A0 version -> ' + VERSION)
patch(0x1e09bfc, struct.pack('<I', app_end), 'execution limit -> new app end')
assert struct.unpack_from('<I', app, 0x1e09bfc - BASE)[0] == app_end

# ------------------------------------------------------------------ invariants
COMMAND_BODIES = [(0x1e01410, 0x1e015ea)]
DISPATCH_ENTRIES = [(0x1e0110e, 2), (0x1e01110, 2), (0x1e01112, 2), (0x1e01160, 4)]
DECLARED = [(sec[n]['addr'], sec[n]['size']) for n in TAIL_SECTIONS + HOOKS]
DECLARED += [(0x1e1b488, 4), (0x1e09bfc, 4), (TAIL_START, len(app) - (TAIL_START - BASE))]
allowed = set()
for a, n in DECLARED:
    allowed.update(range(a - BASE, a - BASE + n))
outside = [hex(BASE + i) for i in range(len(stock))
           if stock[i] != app[i] and i not in allowed]
assert not outside, outside[:20]
for lo, hi in COMMAND_BODIES:
    assert stock[lo - BASE:hi - BASE] == app[lo - BASE:hi - BASE], 'command body changed'
for a, n in DISPATCH_ENTRIES:
    assert stock[a - BASE:a - BASE + n] == app[a - BASE:a - BASE + n], hex(a)
assert app[0x1e012f4 - BASE:0x1e012f8 - BASE] == stock[0x1e012f4 - BASE:0x1e012f8 - BASE]

# ------------------------------------------------------------------ package
replacement, layouts = {}, {}
VM_START_FIXED = {0: 0x2f000, 32: 0x2e000}
for kind, alignment in ((0, 4096), (32, 256)):
    template = dict(states[kind])
    fixed = VM_START_FIXED[kind]
    if len(template['flash']) > fixed:
        raise SystemExit('selected fixed VM boundary is below original flash size')
    # Keep app.bin at its actual linked length. Extend only the template flash
    # floor so the transplant helper places VM at this reviewed fixed boundary.
    template['flash'] = states[kind]['flash'] + b'\xff' * (fixed - len(states[kind]['flash']))
    replacement[kind], layouts[kind] = transplant_image(template, states[kind],
                                                        alignment, bytes(app))
    assert layouts[kind]['new_vm_start'] == fixed
    assert layouts[kind]['program_end'] <= fixed
result = repack(raw, replacement)
if VERSION == '26092430':
    assert sha(result) == EXPECTED_SHA, 'Rebuild differs from the tested 26092430 reference'
else:
    assert sha(result) == CANDIDATE_SHA, 'Rebuild differs from the identified 26092431 candidate'
assert layouts[0]['new_vm_start'] > layouts[0]['old_vm_start']
assert layouts[0]['vm_end_preserved'] == states[0]['appfiles'][2]['offset'] + states[0]['appfiles'][2]['size']
assert len(result) - len(raw) == sum(layouts[k]['new_vm_start'] - layouts[k]['old_vm_start']
                                     for k in (0, 32))
assert all(layouts[k]['program_end'] <= layouts[k]['new_vm_start'] for k in (0, 32))
if OUTPUT.exists():
    assert OUTPUT.read_bytes() == result, 'refusing to overwrite a different file'
OUTPUT.write_bytes(result)

checks = {}
for kind in (0, 32):
    chk = parse_flash_image(result, kind)
    checks[kind] = dict(
        app_matches=chk['payload'] == bytes(app),
        app_bytes=len(chk['payload']), app_sha256=sha(chk['payload']),
        key_preserved=chk['key'] == states[kind]['key'],
        flash_crc=chk['flash_ent']['crc_valid'],
        nested_crc=all(e['crc_valid'] for g in ('areas', 'appfiles') for e in chk[g]),
        reserved_entries_unchanged=[(e['name'], e['offset'], e['size']) for e in chk['appfiles'] if e['flags'] & 0x10] ==
                                   [(e['name'], e['offset'], e['size']) for e in states[kind]['appfiles'] if e['flags'] & 0x10],
        vm_entry=[(e['offset'], e['size']) for e in chk['appfiles'] if e['name'] == 'VM'],
        stock_vm_entry=[(e['offset'], e['size']) for e in states[kind]['appfiles'] if e['name'] == 'VM'],
        vm_start=layouts[kind]['new_vm_start'], app_area_end=layouts[kind]['program_end'],
    )
_, old_entries = read_ufw(raw)
_, new_entries = read_ufw(result)
non_flash_identical = all(
    raw[a['offset']:a['offset'] + a['size2']] == result[b['offset']:b['offset'] + b['size2']]
    for a, b in zip(old_entries, new_entries) if a['type'] not in (0, 32))
assert non_flash_identical, 'non-flash UFW payload changed'
assert BASE_IN.read_bytes() == raw

report = dict(
    variant=args.variant, version=VERSION, build_id=BUILD_ID,
    git_commit=commit, git_dirty=dirty,
    source_sha256s={p.relative_to(ROOT).as_posix(): sha(p.read_bytes())
                   for p in sorted((ROOT / 'Developer').rglob('*')) if p.is_file()},
    toolchain_sha256s={name: sha((BIN / name).read_bytes())
                      for name in ('clang.exe', 'q32s-ld.exe', 'llvm-objdump.exe')},
    source=str(BASE_IN), source_sha256=sha(raw),
    output=str(OUTPUT), output_sha256=sha(result), output_size=len(result),
    stock_app_bytes=len(stock), new_app_bytes=len(app), new_app_end=hex(app_end),
    tail_start=hex(TAIL_START), tail_end=hex(tail_end),
    tail_sections={n: dict(address=hex(sec[n]['addr']), size=sec[n]['size']) for n in TAIL_SECTIONS},
    hook_addresses={n: hex(sec[n]['addr']) for n in HOOKS},
    build_define=V['define'], changes=V['notes'],
    context_ram=dict(pointer='0x465c..0x465f', pointer_bits=32,
                     lock='0x4660', snapshot='heap context + 96', context_bytes=100),
    bthome_payload=dict(
        out_object='0x10', out_source='GPIO register 0x1e5000 bit 0',
        hold_object='0x0f' if V['define'] else None,
        hold_source='stock manual hold byte 0x4514' if V['define'] else None,
        valid_snapshot_even_counter=['0x05', '0x0c'] + (['0x0f'] if V['define'] else []) + ['0x10', '0x21', '0x23'],
        valid_snapshot_odd_counter=['0x05'] + (['0x0f'] if V['define'] else []) + ['0x10', '0x21', '0x23', '0x40'],
        no_snapshot=['0x05', '0x0c'] + (['0x0f'] if V['define'] else []) + ['0x10'],
        max_plaintext_bytes=15 if V['define'] else 13,
        max_legacy_ad_bytes=31 if V['define'] else 29,
        voltage_distance_alternate=True,
    ),
    patches=patches,
    undocumented_commands_preserved=True,
    stock_command_bodies_identical=True,
    stock_dispatch_entries_identical=True,
    reserved_entries_unchanged=all(checks[k]['reserved_entries_unchanged'] for k in (0, 32)),
    vm_start_fixed={str(k): hex(v) for k, v in VM_START_FIXED.items()},
    vm_start_shift_image0=layouts[0]['new_vm_start'] - layouts[0]['old_vm_start'],
    vm_start_shift_image32=layouts[32]['new_vm_start'] - layouts[32]['old_vm_start'],
    vm_headroom_image0=layouts[0]['new_vm_start'] - layouts[0]['program_end'],
    vm_headroom_image32=layouts[32]['new_vm_start'] - layouts[32]['program_end'],
    vm_end_preserved=all(layouts[k]['vm_end_preserved'] == states[k]['appfiles'][2]['offset'] +
                         states[k]['appfiles'][2]['size'] for k in (0, 32)),
    image32_vm_shift=layouts[32]['new_vm_start'] - layouts[32]['old_vm_start'],
    mirrors=checks,
    limitations=[
        'This build executes structural assertions; independent audit and hardware coverage '
        'are recorded separately for the identified candidate.',
        'Hardware coverage belongs to the identified version; 26092431 requires '
        'independent audit and hardware validation.',
        'Read A603 again after OTA or factory reset and update HA when the key changes.',
        'The RX mailbox holds one candidate; senders repeat a signed frame during '
        'their transmit window and observe BTHome physical OUT feedback.',
        'VM ends and BTIF/EXIF positions stay fixed, but VM state preservation across '
        'arbitrary OTA or boundary changes is not guaranteed.',
        'The stock random-fill routine is reused; cryptographic strength is unproven.',
        'A604/A2 rotate the key through complete write+readback. An ambiguous VM write '
        'may have committed; reread A603 after a reported failure.',
    ])
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: report[k] for k in ('variant', 'version', 'output', 'output_sha256',
                                         'output_size', 'new_app_bytes', 'tail_end')},
                 ensure_ascii=False, indent=2))
print('tail sections:', json.dumps(report['tail_sections'], ensure_ascii=False))
