"""Send an already-signed LD2401 control frame through a deployed ESPHome node.

The Bindkey never reaches this tool: `control_frame.py` derives the signed frame
locally from a captured authenticated counter, and the node only broadcasts the
bytes it is handed.  The node answers through `api.respond`, so a refused frame
(bluetooth not active, bad payload) is reported as a failure instead of a silent
success.

    python -B Tester/tools/send_control.py --host <node> --apikey-file local/esphome.key \
        --payload 0201061affd6054c43...
    python -B Tester/tools/send_control.py --host <node> --apikey-file local/esphome.key --list

Host names and API keys are private: keep them in the ignored local/ directory and
pass them on the command line or through a file.
"""
import argparse
import asyncio
import sys
from pathlib import Path

ACTION = 'ld2401_control_broadcast'
PORT = 6053


def actions_from(services):
    """Return {lowercased action name: service} for the node's exposed actions."""
    out = {}
    for service in services:
        name = str(getattr(service, 'name', '')).lower()
        if name:
            out[name] = service
    return out


async def run(args):
    try:
        from aioesphomeapi import APIClient
    except ImportError:
        raise SystemExit('aioesphomeapi is missing: pip install aioesphomeapi')

    apikey = args.apikey
    if args.apikey_file:
        apikey = Path(args.apikey_file).read_text(encoding='utf-8').strip()
    if not apikey:
        raise SystemExit('pass --apikey or --apikey-file (local file, never committed)')

    client = APIClient(args.host, args.port, None, noise_psk=apikey)
    await client.connect(login=True)
    try:
        _entities, services = await client.list_entities_services()
        actions = actions_from(services)
        if args.list:
            for name in sorted(actions):
                print(name)
            return 0
        service = actions.get(ACTION)
        if service is None:
            print('node does not expose %s; available: %s'
                  % (ACTION, ', '.join(sorted(actions)) or 'none'))
            return 2
        print('-> %s payload=%s (%d bytes)'
              % (ACTION, args.payload, len(args.payload) // 2))
        response = await client.execute_service(service, {'payload': args.payload},
                                                return_response=True)
        success = getattr(response, 'success', None)
        error = getattr(response, 'error_message', '') or ''
        print('<- success=%s%s' % (success, ' error=%r' % error if error else ''))
        # A node without api.respond returns no response object at all; that is
        # the documented fire-and-forget case, not a failure.
        return 0 if success in (True, None) else 1
    finally:
        await client.disconnect()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', required=True, help='ESPHome node host or address')
    ap.add_argument('--port', type=int, default=PORT)
    ap.add_argument('--apikey', help='node API key (prefer --apikey-file)')
    ap.add_argument('--apikey-file', type=Path, help='local file holding the API key')
    ap.add_argument('--payload', help='60 hex characters (30 bytes) from control_frame.py')
    ap.add_argument('--list', action='store_true', help='list the node actions and exit')
    args = ap.parse_args()
    if not args.list:
        if not args.payload:
            ap.error('--payload is required unless --list is given')
        try:
            raw = bytes.fromhex(args.payload)
        except ValueError:
            ap.error('--payload must be hexadecimal')
        if len(raw) != 30:
            ap.error('--payload must be 30 bytes (60 hex characters), got %d' % len(raw))
    return asyncio.run(run(args))


if __name__ == '__main__':
    sys.exit(main())