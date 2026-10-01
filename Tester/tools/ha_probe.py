"""Inspect a live Home Assistant instance over its REST and WebSocket APIs.

Read-only: this tool lists what Home Assistant knows about the LD2401 integration
(installed version, config entries, entities, devices, ESPHome sender services) and
never calls a service or changes state.  Use it to decide what a real-instance run
can test before touching anything.

Credentials stay local.  `--token-file` reads a two-line file: the base URL on the
first line and a long-lived access token on the second.  Both are private; keep
them in the ignored local/ directory.

    python -B Tester/tools/ha_probe.py --token-file local/ha-token.txt
    python -B Tester/tools/ha_probe.py --token-file local/ha-token.txt --json local/ha-probe.json
"""
import argparse
import asyncio
import json
from pathlib import Path
import ssl
import sys

DOMAIN = 'ld2401_control'
BTHOME = 'bthome'


def read_credentials(path):
    lines = [line.strip() for line in Path(path).read_text(encoding='utf-8').splitlines()]
    lines = [line for line in lines if line and not line.startswith('#')]
    if len(lines) < 2:
        raise SystemExit('token file needs two lines: base URL, then access token')
    return lines[0].rstrip('/'), lines[1]


class HomeAssistant:
    def __init__(self, base, token, verify=True):
        self.base = base.rstrip('/')
        self.token = token
        self.verify = verify
        self._id = 0

    def _ssl(self):
        if self.base.startswith('https') and not self.verify:
            return ssl._create_unverified_context()  # noqa: SLF001 - explicit --insecure
        return None

    async def rest(self, session, path):
        url = self.base + path
        async with session.get(url, headers={'Authorization': 'Bearer ' + self.token},
                               ssl=self._ssl()) as response:
            response.raise_for_status()
            return await response.json()

    async def ws(self, session, commands):
        """Run WebSocket commands and return {type: result}."""
        url = self.base.replace('https://', 'wss://').replace('http://', 'ws://') + '/api/websocket'
        out, results = {}, {}
        async with session.ws_connect(url, ssl=self._ssl()) as socket:
            async def recv():
                return json.loads((await socket.receive()).data)

            hello = await recv()
            if hello.get('type') != 'auth_required':
                raise SystemExit('unexpected handshake: %r' % hello.get('type'))
            await socket.send_json({'type': 'auth', 'access_token': self.token})
            auth = await recv()
            if auth.get('type') != 'auth_ok':
                raise SystemExit('authentication failed: %r' % auth.get('message'))
            out['ha_version'] = auth.get('ha_version')
            ids = {}
            for index, (name, payload) in enumerate(commands, start=1):
                message = {'id': index, 'type': name}
                message.update(payload or {})
                ids[index] = name
                await socket.send_json(message)
            pending = len(commands)
            while pending:
                message = await recv()
                if message.get('type') != 'result':
                    continue
                pending -= 1
                name = ids.get(message.get('id'), '?')
                if not message.get('success'):
                    results[name] = {'error': (message.get('error') or {}).get('message')}
                else:
                    results[name] = message.get('result')
        out['results'] = results
        return out


def version_of(manifests, domain):
    for entry in manifests or []:
        if entry.get('domain') == domain:
            return entry.get('version'), entry.get('integration_type'), entry.get('disabled')
    return None, None, None


def as_list(result):
    """WebSocket results are lists on success and {'error': ...} on failure."""
    return result if isinstance(result, list) else []


def summarise(probe, config, states):
    results = probe['results']
    manifests = as_list(results.get('manifest/list'))
    installed, integration_type, disabled = version_of(manifests, DOMAIN)
    entries = as_list(results.get('config_entries/get'))
    registry = as_list(results.get('entity_registry/list'))
    devices = as_list(results.get('device_registry/list'))
    services = results.get('get_services')
    if not isinstance(services, dict):
        services = {}
    errors = {name: value['error'] for name, value in results.items()
              if isinstance(value, dict) and 'error' in value}

    our_entries = [e for e in entries if e.get('domain') == DOMAIN]
    bthome_entries = [e for e in entries if e.get('domain') == BTHOME]
    our_entities = [e for e in registry if e.get('platform') == DOMAIN]
    bluetooth_devices = [d for d in devices
                         if any(c[0] == 'bluetooth' for c in (d.get('connections') or []))]
    senders = sorted(name for name in (services.get('esphome') or {})
                     if name.endswith('ld2401_control_broadcast'))
    report = {
        'ha_version': probe.get('ha_version') or config.get('version'),
        'location_name': config.get('location_name'),
        'integration': {'domain': DOMAIN, 'installed_version': installed,
                        'integration_type': integration_type, 'disabled': disabled},
        'config_entries': {
            DOMAIN: [{'entry_id': e.get('entry_id'), 'title': e.get('title'),
                      'state': e.get('state'),
                      'address': (e.get('options') or e.get('data') or {}).get('address')}
                     for e in our_entries],
            BTHOME: [{'entry_id': e.get('entry_id'), 'title': e.get('title'),
                      'state': e.get('state')} for e in bthome_entries],
        },
        'entities': [{'entity_id': e.get('entity_id'), 'unique_id': e.get('unique_id'),
                      'platform': e.get('platform'), 'disabled': e.get('disabled_by'),
                      'device_id': e.get('device_id')} for e in our_entities],
        'entity_states': {s['entity_id']: s['state'] for s in states
                          if s['entity_id'].startswith(('select.ld2401', 'button.ld2401'))
                          or DOMAIN in str(s.get('attributes', {}).get('attribution', ''))},
        'bluetooth_devices': [{'name': d.get('name_by_user') or d.get('name'),
                               'connections': d.get('connections')} for d in bluetooth_devices],
        'esphome_senders': senders,
    }
    return report


async def main(args):
    import aiohttp
    base, token = ((args.base, args.token) if args.base and args.token
                   else read_credentials(args.token_file))
    client = HomeAssistant(base, token, verify=not args.insecure)
    commands = [
        ('manifest/list', None),
        ('config_entries/get', None),
        ('entity_registry/list', None),
        ('device_registry/list', None),
        ('get_services', None),
    ]
    async with aiohttp.ClientSession() as session:
        config = await client.rest(session, '/api/config')
        states = await client.rest(session, '/api/states')
        probe = await client.ws(session, commands)
    report = summarise(probe, config, states)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0


def main_cli():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', help='HA base URL, e.g. http://host:8123')
    ap.add_argument('--token', help='long-lived access token')
    ap.add_argument('--token-file', type=Path, default=Path('local/ha-token.txt'),
                    help='two lines: base URL, then access token')
    ap.add_argument('--insecure', action='store_true', help='do not verify TLS certificates')
    ap.add_argument('--json', type=Path, help='also write the report to this path')
    args = ap.parse_args()
    if not (args.base and args.token) and not args.token_file.is_file():
        ap.error('provide --base and --token, or a --token-file')
    return asyncio.run(main(args))


if __name__ == '__main__':
    sys.exit(main_cli())