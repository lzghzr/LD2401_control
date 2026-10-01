"""Install or back up the LD2401 integration on a live Home Assistant instance.

Uses the `ha_file_explorer` HTTP API (`/ha_file_explorer-api`), which reads and
writes paths relative to the Home Assistant config directory:

    GET  /ha_file_explorer-api?path=<rel>&act=content      -> file text
    GET  /ha_file_explorer-api?path=<rel>                  -> directory listing
    POST /ha_file_explorer-api   {"path": <rel>, "data": ...}  -> save file

That makes a real-instance run reproducible instead of hand-copied: `pull` records
what is deployed, `push` installs the repository copy after verifying it, and
`verify` compares the two by SHA-256.  `push` never deletes anything and refuses to
run without a fresh `pull` directory, so a previous deployment stays recoverable.

Credentials and everything downloaded stay local: `--token-file` is the two-line
HA credential file and the default backup directory is under the ignored local/.

    python -B Tester/tools/ha_deploy.py --token-file local/ha-token.txt --insecure pull
    python -B Tester/tools/ha_deploy.py --token-file local/ha-token.txt --insecure verify
    python -B Tester/tools/ha_deploy.py --token-file local/ha-token.txt --insecure push
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ha_probe import HomeAssistant                                   # noqa: E402

API = '/ha_file_explorer-api'
REMOTE_ROOT = 'custom_components/ld2401_control'
LOCAL_ROOT = Path('custom_components/ld2401_control')
SKIP = {'__pycache__'}


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def local_files():
    return {path.relative_to(LOCAL_ROOT).as_posix(): path.read_text(encoding='utf-8')
            for path in sorted(LOCAL_ROOT.rglob('*'))
            if path.is_file() and not any(part in SKIP for part in path.parts)}


class Client:
    def __init__(self, base, token, verify):
        self.ha = HomeAssistant(base, token, verify=verify)
        self.headers = {'Authorization': 'Bearer ' + token}

    async def _get(self, session, params):
        async with session.get(self.ha.base + API, headers=self.headers,
                               ssl=self.ha._ssl(), params=params) as response:
            response.raise_for_status()
            return await response.json()

    async def listing(self, session, rel):
        body = await self._get(session, {'path': rel, 'act': ''})
        data = body.get('data') if isinstance(body, dict) else body
        return data or []

    async def content(self, session, rel):
        body = await self._get(session, {'path': rel, 'act': 'content'})
        data = body.get('data') if isinstance(body, dict) else body
        return data if isinstance(data, str) else json.dumps(data)

    async def save(self, session, rel, text):
        async with session.post(self.ha.base + API, headers=self.headers,
                                ssl=self.ha._ssl(),
                                json={'path': rel, 'data': text}) as response:
            response.raise_for_status()
            return await response.json()

    async def walk(self, session, rel):
        """Every file under rel, as {path relative to rel: text}."""
        out = {}
        for item in await self.listing(session, rel):
            name = item.get('name')
            if not name or name in SKIP:
                continue
            child = '%s/%s' % (rel, name)
            if item.get('type') == 'dir':
                out.update(await self.walk(session, child))
            else:
                out[child[len(REMOTE_ROOT):].lstrip('/')] = await self.content(session, child)
        return out


def credentials(args):
    lines = [l.strip() for l in args.token_file.read_text(encoding='utf-8').splitlines()
             if l.strip() and not l.startswith('#')]
    return lines[0], lines[1]


async def run(args):
    import aiohttp
    base, token = credentials(args)
    client = Client(base, token, verify=not args.insecure)
    async with aiohttp.ClientSession() as session:
        if args.action == 'pull':
            installed = await client.walk(session, REMOTE_ROOT)
            manifest = {}
            for rel, text in sorted(installed.items()):
                target = args.dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding='utf-8')
                manifest[rel] = {'sha256': digest(text), 'bytes': len(text)}
            (args.dir / 'installed-manifest.json').write_text(
                json.dumps(manifest, indent=2), encoding='utf-8')
            print('pulled %d files to %s' % (len(installed), args.dir))
            for rel in sorted(manifest):
                print('   %-24s %s' % (rel, manifest[rel]['sha256'][:16]))
            return 0

        if args.action == 'verify':
            installed = await client.walk(session, REMOTE_ROOT)
            wanted = local_files()
            same = differ = missing = extra = 0
            for rel, text in sorted(wanted.items()):
                if rel not in installed:
                    print('   MISSING on HA : %s' % rel)
                    missing += 1
                elif installed[rel] == text:
                    same += 1
                else:
                    print('   DIFFERS       : %s (local %s, HA %s)'
                          % (rel, digest(text)[:12], digest(installed[rel])[:12]))
                    differ += 1
            for rel in sorted(set(installed) - set(wanted)):
                print('   only on HA    : %s' % rel)
                extra += 1
            print('identical=%d differ=%d missing=%d extra=%d' % (same, differ, missing, extra))
            return 0 if differ == 0 and missing == 0 else 1

        # push
        if not (args.dir / 'installed-manifest.json').is_file():
            print('refusing to push without a --dir backup from `pull` first')
            return 2
        wanted = local_files()
        deployed = 0
        for rel, text in sorted(wanted.items()):
            result = await client.save(session, '%s/%s' % (REMOTE_ROOT, rel), text)
            if result.get('code') != 0:
                print('   FAILED %s: %s' % (rel, result))
                return 1
            deployed += 1
            print('   pushed %-24s %s' % (rel, digest(text)[:16]))
        installed = await client.walk(session, REMOTE_ROOT)
        mismatched = [rel for rel, text in wanted.items() if installed.get(rel) != text]
        print('pushed %d files; read-back mismatches: %s'
              % (deployed, mismatched or 'none'))
        return 0 if not mismatched else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', choices=('pull', 'push', 'verify'))
    ap.add_argument('--token-file', type=Path, default=Path('local/ha-token.txt'))
    ap.add_argument('--insecure', action='store_true')
    ap.add_argument('--dir', type=Path, default=Path('local/ha-installed'),
                    help='backup directory written by pull and required by push')
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == '__main__':
    sys.exit(main())