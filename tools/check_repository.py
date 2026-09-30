"""Check source distribution layout, imports and optional host protocol parity.

This performs no device operations and does not import Home Assistant.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', '.esphome', '__pycache__', 'build', 'local', 'vendor'}


def check(protocol=False):
    failures = []
    def require(ok, message):
        if not ok:
            failures.append(message)

    files = sorted(p for p in ROOT.rglob('*') if p.is_file()
                   and not any(part in SKIP for part in p.relative_to(ROOT).parts))
    integration = ROOT / 'custom_components/ld2401_control'
    require([p.name for p in (ROOT / 'custom_components').iterdir() if p.is_dir()]
            == ['ld2401_control'], 'HACS requires one integration directory')
    manifest = json.loads((integration / 'manifest.json').read_text(encoding='utf-8'))
    for field in ('domain', 'name', 'version', 'documentation', 'issue_tracker', 'codeowners'):
        require(bool(manifest.get(field)), 'Missing integration manifest field: ' + field)
    require(manifest['domain'] == integration.name, 'Integration domain/directory mismatch')
    require(manifest.get('documentation') == 'https://github.com/lzghzr/ld2401_control', 'Repository URL mismatch')
    require((ROOT / 'LICENSE').is_file(), 'Missing LICENSE')
    require(json.loads((ROOT / 'hacs.json').read_text()).get('render_readme') is True, 'Missing HACS README setting')
    source_map = json.loads((ROOT / 'metadata/copied-sources.json').read_text())
    for record in source_map['files']:
        path = ROOT / record['path']
        require(path.is_file(), 'Missing copied source: ' + record['path'])
        if 'distribution_sha256' in record:
            require(hashlib.sha256(path.read_bytes()).hexdigest() == record['distribution_sha256'],
                    'Copied source changed from packaged identity: ' + record['path'])
    role_sources = json.loads((ROOT / 'metadata/role-tool-sources.json').read_text(encoding='utf-8'))
    for record in role_sources['files']:
        path = ROOT / record['path']
        require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == record['distribution_sha256'],
                'Role tool changed from packaged identity: ' + record['path'])

    sys.path.insert(0, str(ROOT / 'Developer/tools'))
    for name in ('ufw_format', 'flash_layout', 'ufw_container', 'ld24_elf_sections'):
        __import__(name)
    subprocess.run([sys.executable, '-B', str(ROOT / 'Developer/tools/build.py'), '--help'],
                   cwd=ROOT / 'docs', check=True, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, '-B', str(ROOT / 'Tester/tools/jl_ota_pc.py'), '--help'],
                   cwd=ROOT / 'docs', check=True, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, '-B', str(ROOT / 'Tester/tools/a6.py'), '--self-test'],
                   cwd=ROOT / 'docs', check=True)
    subprocess.run([sys.executable, '-B', str(ROOT / 'Auditor/tools/selftest.py')],
                   cwd=ROOT / 'docs', check=True)
    for tool in ('capture_ble.py', 'decode_capture.py', 'control_frame.py'):
        subprocess.run([sys.executable, '-B', str(ROOT / 'Tester/tools' / tool), '--help'],
                       cwd=ROOT / 'docs', stdout=subprocess.DEVNULL, check=True)

    ownership = json.loads((ROOT / 'metadata/file-ownership.json').read_text())['rules']
    require(set(ownership.values()) <= {'Developer', 'Auditor', 'Tester', 'Maintainer'},
            'Unknown role in file ownership rules')
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        require(any(rel.startswith(rule) if rule.endswith('/') else rel == rule
                    for rule in ownership), 'File has no assigned role: ' + rel)
        require(path.suffix.lower() not in {'.ufw', '.apk', '.elf', '.bin', '.o', '.pyc'},
                'Generated/vendor binary in source distribution: ' + rel)
        require(not path.name.startswith('secrets.'), 'Private secrets file in distribution: ' + rel)
        text = path.read_text(encoding='utf-8')
        if path.suffix == '.py':
            compile(text, rel, 'exec')
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level and node.module:
                    base = path.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    target = base.joinpath(*node.module.split('.'))
                    require(target.with_suffix('.py').is_file() or (target / '__init__.py').is_file(),
                            'Broken relative import in ' + rel + ': ' + node.module)
        elif path.suffix == '.json':
            json.loads(text)
        elif path.suffix == '.md':
            for link in re.findall(r'\]\(([^\s)]+)', text):
                if '://' in link or link.startswith('#'):
                    continue
                target = (path.parent / link.split('#')[0]).resolve()
                require(target.exists(), 'Broken document link in ' + rel + ': ' + link)
        # Local absolute home/workspace paths and network addresses belong in local files.
        require(not re.search(r'(?i)[A-Z]:[\\/](?:Users|AgentWorkspace)[\\/]', text),
                'Personal absolute path in ' + rel)
        require(not re.search(r'(?i)https?://[^\s/]+\.(?:lan|local)(?:[/:]|\b)', text),
                'Private network URL in ' + rel)

    package = (ROOT / 'esphome/ld2401_control.yaml').read_text()
    include_match = re.search(r'^\s*-\s+(.+\.h)\s*$', package, re.MULTILINE)
    require(bool(include_match) and (ROOT / 'esphome' / include_match.group(1).strip()).is_file(),
            'Missing ESPHome advertiser include')
    require('action: ld2401_control_broadcast' in package, 'ESPHome/HA action mismatch')
    require('!include ld2401_control.yaml' in (ROOT / 'esphome/ld2401_sender.example.yaml').read_text(),
            'Broken ESPHome package include')
    if protocol:
        subprocess.run([sys.executable, '-B', str(ROOT / 'Tester/tools/check_protocol.py')],
                       cwd=ROOT / 'docs', check=True)
        subprocess.run([sys.executable, '-B', str(ROOT / 'Tester/tools/check_capture.py')],
                       cwd=ROOT / 'docs', check=True)
    if failures:
        raise SystemExit('\n'.join(failures))
    print('PASS: %d public files; syntax, JSON, imports, tool entries, links, source identities%s' %
          (len(files), ', protocol parity' if protocol else ''))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', action='store_true', help='Also compare codecs (requires cryptography)')
    check(parser.parse_args().protocol)
