"""Reserved layout assertions reject drift outside VM/PRCT relocation policies."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
# Load the small builder helpers without executing the command-line builder.
spec = importlib.util.spec_from_file_location('ufw_format', TOOLS / 'ufw_format.py')
ufw_format = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ufw_format)
sys.modules['ufw_format'] = ufw_format
spec = importlib.util.spec_from_file_location('developer_flash_layout', TOOLS / 'flash_layout.py')
flash_layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash_layout)


def states():
    old = {'appfiles': [
        dict(name=name, offset=offset, size=size, header=32 * index,
             flags=0x10, reserved=0, last=index == 3, data_crc=0)
        for index, (name, offset, size) in enumerate([
            ('VM', 100, 100), ('PRCT', 0, 100), ('BTIF', 200, 10), ('EXIF', 210, 10),
        ])
    ]}
    new = deepcopy(old)
    new['appfiles'][0].update(offset=120, size=80)
    new['appfiles'][1].update(size=120)
    return old, new


def test_reserved_policies_allow_vm_prct_relocation():
    old, new = states()
    checks = flash_layout.check_reserved_layout(old, new, 120)
    assert set(checks) == {'VM', 'PRCT', 'BTIF', 'EXIF'}
    assert all(value['passed'] for value in checks.values())
    assert checks['VM']['after'] == {'offset': 120, 'size': 80}


@pytest.mark.parametrize('index,field,value', [
    (0, 'offset', 121), (0, 'size', 81),
    (1, 'offset', 1), (1, 'size', 121),
    (2, 'offset', 201), (2, 'size', 11),
    (3, 'offset', 211), (3, 'size', 11),
    (2, 'flags', 0), (3, 'name', 'OTHER'),
])
def test_reserved_policies_reject_boundary_or_entry_drift(index, field, value):
    old, new = states()
    new['appfiles'][index][field] = value
    with pytest.raises(AssertionError):
        flash_layout.check_reserved_layout(old, new, 120)
