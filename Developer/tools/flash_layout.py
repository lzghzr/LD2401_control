"""Rebuild the application area and fixed reserved regions."""
import struct
from ufw_format import crc, sfc

def fix_header(data, offset):
    struct.pack_into('<H', data, offset, crc(data[offset+2:offset+32]))


def file_bytes(state, name):
    e = next(e for e in state['appfiles'] if e['name'] == name)
    start = state['base'] + e['offset']
    return bytes(state['plain'][start:start+e['size']])


def check_reserved_layout(old, new, vm_start):
    """Assert each reserved entry's policy and return reportable evidence."""
    names = {'VM', 'PRCT', 'BTIF', 'EXIF'}
    before = [e for e in old['appfiles'] if e['flags'] & 0x10]
    after = [e for e in new['appfiles'] if e['flags'] & 0x10]
    assert len(before) == len(after) == len(names), 'reserved entry count changed'
    assert {e['name'] for e in before} == {e['name'] for e in after} == names, 'reserved entry names changed'
    original = {e['name']: e for e in before}
    current = {e['name']: e for e in after}
    checks = {}
    for name in sorted(names):
        a, b = original[name], current[name]
        for field in ('header', 'flags', 'reserved', 'last', 'data_crc'):
            assert a[field] == b[field], f'{name} {field} changed'
        if name == 'VM':
            policy = 'fixed start; preserve original end'
            assert b['offset'] == vm_start, 'VM start differs from fixed boundary'
            assert b['size'] > 0 and b['offset'] + b['size'] == a['offset'] + a['size'], 'VM end changed'
        elif name == 'PRCT':
            policy = 'start at zero; end at VM start'
            assert b['offset'] == 0 and b['size'] == vm_start, 'PRCT must end at VM start'
        else:
            policy = 'preserve original offset and size'
            assert (a['offset'], a['size']) == (b['offset'], b['size']), f'{name} moved or resized'
        checks[name] = dict(policy=policy, passed=True,
                            before=dict(offset=a['offset'], size=a['size']),
                            after=dict(offset=b['offset'], size=b['size']))
    return checks


def transplant_image(old, donor, alignment, app_payload=None):
    base = old['base']
    assert len(old['areas']) == len(donor['areas']) == 2
    assert old['areas'][0]['offset'] == donor['areas'][0]['offset'] == 0x1e00120
    assert old['app']['offset'] == donor['app']['offset'] == 288
    # Retain the original directory (including BTIF/EXIF); replace actual file data.
    area = bytearray(old['plain'][base:base+288])
    for name in ('app.bin', 'cfg_tool.bin'):
        e = next(e for e in old['appfiles'] if e['name'] == name)
        payload = app_payload if name == 'app.bin' and app_payload is not None else file_bytes(donor, name)
        h = e['header'] - base
        struct.pack_into('<HII', area, h+2, crc(payload), len(area), len(payload))
        area.extend(payload)
        fix_header(area, h)
    app_area_size = len(area)
    extra = donor['areas'][1]
    assert extra['name'] == 'p11_code.bin' and extra['last']
    area.extend(donor['plain'][extra['header']:extra['header']+extra['size']])
    end = base + len(area)
    flash_size = max(len(old['flash']), (end+alignment-1)//alignment*alignment)
    vm = next(e for e in old['appfiles'] if e['name'] == 'VM')
    vm_end = vm['offset'] + vm['size']
    assert flash_size < vm_end
    for e in old['appfiles']:
        h = e['header'] - base
        if e['name'] == 'VM':
            struct.pack_into('<II', area, h+4, flash_size, vm_end-flash_size)
            fix_header(area, h)
        elif e['name'] == 'PRCT':
            struct.pack_into('<II', area, h+4, 0, flash_size)
            fix_header(area, h)
    struct.pack_into('<I', area, 8, app_area_size)
    struct.pack_into('<H', area, 2, crc(area[32:app_area_size]))
    fix_header(area, 0)
    flash = bytearray(old['flash'][:base]) + area
    flash.extend(b'\xff'*(flash_size-len(flash)))
    sfc(flash, base, end, base, old['key'])
    assert flash[:base] == old['flash'][:base]
    return bytes(flash), {'base': base, 'program_end': end, 'flash_size': flash_size,
                         'old_vm_start': vm['offset'], 'new_vm_start': flash_size,
                         'vm_end_preserved': vm_end, 'new_vm_size': vm_end-flash_size}
