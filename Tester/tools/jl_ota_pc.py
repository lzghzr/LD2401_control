"""Explicit PC BLE OTA entry point for LD2401; --mac/--trace are local inputs."""
import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path


AE01 = '0000ae01-0000-1000-8000-00805f9b34fb'
AE02 = '0000ae02-0000-1000-8000-00805f9b34fb'
AUTH_PASS = bytes.fromhex('0270617373')
TARGET_INFO = bytes.fromhex('fedcbac003000600ffffffff00ef')
PARAM_FF = bytes.fromhex('ffffffff00')


def rcsp_cmd(opcode, param=b'', sn=0):
    payload = bytes([sn]) + param
    return bytes([0xFE, 0xDC, 0xBA, 0xC0, opcode,
                  (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload + bytes([0xEF])


def rcsp_response(opcode, sn, data=b'', status=0):
    payload = bytes([status, sn]) + data
    return bytes([0xFE, 0xDC, 0xBA, 0x00, opcode,
                  (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload + bytes([0xEF])


class Conn:
    """One BLE connection to the module, with its own SN counter."""

    def __init__(self, mac, firmware, sn_start=0):
        self.mac = mac
        self.firmware = firmware
        self.sn = sn_start
        self.client = None
        self.rx = bytearray()
        self.trace = []

    # ---- plumbing ----
    @classmethod
    async def open(cls, mac, firmware, sn_start=0, attempts=10, delay=3.0):
        last = None
        for i in range(attempts):
            dev = await BleakScanner.find_device_by_address(mac, timeout=12.0)
            if dev is None:
                last = 'not advertising'
                await asyncio.sleep(delay)
                continue
            args = {'timeout': 25}
            if sys.platform.startswith('win'):
                args['winrt'] = {'use_cached_services': False}
            client = BleakClient(dev, **args)
            try:
                await client.connect()
            except Exception as exc:                       # noqa: BLE001
                last = repr(exc)
                await asyncio.sleep(delay)
                continue
            self = cls(mac, firmware, sn_start)
            self.client = client
            await client.start_notify(AE02, self.on_notify)
            await asyncio.sleep(0.8)
            print('   connected (attempt %d), mtu = %d' % (i + 1, client.mtu_size))
            return self
        raise RuntimeError('could not connect: %s' % last)

    def on_notify(self, sender, data):
        self.rx += data
        self.trace.append({'t': round(time.monotonic(), 2), 'rx': data.hex()})

    async def close(self):
        try:
            await self.client.disconnect()
        except Exception:                                   # noqa: BLE001
            pass

    async def write(self, frame, chunk=False):
        if not self.client.is_connected:
            print('   (device already gone, dropping this write)')
            return
        mtu = max(self.client.mtu_size - 3, 20)
        if chunk and len(frame) > mtu:
            for i in range(0, len(frame), mtu):
                await self.client.write_gatt_char(AE01, frame[i:i + mtu], response=False)
                await asyncio.sleep(0.004)
        else:
            await self.client.write_gatt_char(AE01, frame, response=False)

    async def wait_disconnect(self, timeout=20.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not self.client.is_connected:
                print('   device disconnected (expected: it is rebooting)')
                return True
            await asyncio.sleep(0.3)
        print('   WARNING: device did not disconnect within %.0fs' % timeout)
        return False

    # ---- reads ----
    async def read_auth(self, expect=None, timeout=4.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.rx:
                if self.rx[0] > 0x02:
                    del self.rx[:1]
                    continue
                need = 5 if self.rx[0] == 0x02 else 17
                if len(self.rx) >= need:
                    out = bytes(self.rx[:need])
                    del self.rx[:need]
                    if expect is None or out[0] == expect:
                        return out
                    continue
            await asyncio.sleep(0.02)
        return None

    async def read_frame(self, timeout=6.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            i = self.rx.find(b'\xfe\xdc\xba')
            if i >= 0 and len(self.rx) - i >= 7:
                ln = (self.rx[i + 5] << 8) | self.rx[i + 6]
                total = 7 + ln + 1
                if len(self.rx) - i >= total:
                    frame = bytes(self.rx[i:i + total])
                    del self.rx[:i + total]
                    return frame
            await asyncio.sleep(0.02)
        return None

    async def pump(self, idle=4.0, limit=240.0):
        """Serve whatever the device asks for until it goes quiet.

        The device pulls file blocks when *it* wants them, sometimes replying to
        a control command with a pull instead of a response, so every step runs
        through here instead of assuming a one-command-one-reply exchange.
        Returns (blocks_served, other_frames).
        """
        served, others = 0, []
        last = time.monotonic()
        end = time.monotonic() + limit
        while time.monotonic() < end:
            frame = await self.read_frame(3)
            if frame is None:
                if time.monotonic() - last > idle:
                    break
                continue
            last = time.monotonic()
            op, payload = frame[4], frame[7:-1]
            sn = payload[0] if payload else 0
            if op == 0xE5 and len(payload) >= 7:
                off = int.from_bytes(payload[1:5], 'big')
                ln = int.from_bytes(payload[5:7], 'big')
                data = self.firmware[off:off + ln] if self.firmware else b''
                await self.write(rcsp_response(0xE5, sn, data), chunk=True)
                served += 1
                if served % 50 == 0:
                    print('   served %d blocks (offset %d)' % (served, off))
            elif op == 0xE8:
                print('   0xE8 notify, echoing %s' % payload[1:].hex())
                await self.write(rcsp_response(0xE8, sn, payload[1:]))
            else:
                others.append((op, payload))
                print('   got 0x%02X: %s' % (op, payload.hex()))
        return served, others

    async def send(self, op, param=b'', idle=4.0):
        if not self.client.is_connected:
            print('   (skipping 0x%02X, device is rebooting)' % op)
            return 0, []
        self.sn += 1
        print('   -> 0x%02X (SN=%d) %s' % (op, self.sn, param.hex()))
        await self.write(rcsp_cmd(op, param, self.sn))
        return await self.pump(idle=idle)

    # ---- phases ----
    async def authenticate(self):
        self.rx.clear()
        await self.write(bytes([0x00]) + bytes(random.randrange(256) for _ in range(16)))
        reply = await self.read_auth(expect=0x01)
        assert reply, 'no answer to the auth challenge'
        await self.write(AUTH_PASS)
        dev = await self.read_auth(expect=0x00)
        assert dev, 'no answer to the pass frame'
        await self.write(bytes([0x00]) + dev[1:])      # ask the device for f(D16)
        enc = await self.read_auth(expect=0x01)
        assert enc, 'device oracle gave nothing'
        await self.write(bytes([0x01]) + enc[1:])
        ok = await self.read_auth(expect=0x02)
        assert ok and ok[1:] == b'pass', 'auth rejected'
        print('   authenticated')

    async def serve_pulls(self, idle=12.0, limit=300.0):
        served, idle_since = 0, time.monotonic()
        end = time.monotonic() + limit
        while time.monotonic() < end:
            frame = await self.read_frame(4)
            if frame is None:
                if time.monotonic() - idle_since > idle:
                    print('   pulls finished (%d blocks, no request for %.0fs)' % (served, idle))
                    return served
                continue
            idle_since = time.monotonic()
            op, payload = frame[4], frame[7:-1]
            sn = payload[0] if payload else 0
            if op == 0xE5 and len(payload) >= 7:
                off = int.from_bytes(payload[1:5], 'big')
                ln = int.from_bytes(payload[5:7], 'big')
                data = self.firmware[off:off + ln]
                await self.write(rcsp_response(0xE5, sn, data), chunk=True)
                served += 1
                if served % 25 == 0:
                    print('   served %d blocks (offset %d, %d bytes each)' % (served, off, len(data)))
            elif op == 0xE8:
                print('   0xE8 notify, echoing size %s' % payload[1:].hex())
                await self.write(rcsp_response(0xE8, sn, payload[1:]))
            else:
                print('   device op 0x%02X: %s' % (op, payload.hex()))
        print('   pull serving hit the %.0fs limit (%d blocks)' % (limit, served))
        return served

    async def enter_update(self, reboot_after=True):
        await self.cmd(0xE3)
        await self.cmd(0xE6)
        if reboot_after:
            await self.cmd(0xE7, b'\x00')


async def flash(mac, firmware, trace_path):
    print('=== connection 1: first round ===')
    c = await Conn.open(mac, firmware)
    tracelog = [c.trace]
    try:
        await c.authenticate()
        await c.send(0x03, PARAM_FF)
        await c.send(0xE1)
        served_send, _ = await c.send(0xE2, bytes([0]), idle=8.0)
        await c.send(0xE6, idle=3.0)
        await c.send(0x0B, bytes.fromhex('0001'), idle=2.0)
        await c.wait_disconnect()
    finally:
        await c.close()

    print('=== connection 2: enter update; the loader pulls the firmware ===')
    c = await Conn.open(mac, firmware, sn_start=c.sn)
    tracelog.append(c.trace)
    firmware_blocks = 0
    try:
        await c.authenticate()
        # Diagnostic: identify what came back after the first round. The loader
        # reports sdkType=2 and mandatoryUpgradeFlag=1; the application does not.
        ident, _ = await c.send(0x03, PARAM_FF, idle=3.0)
        # A device in the forced-update (uboot) state starts the transfer from
        # 0xE1/0xE2 and ignores 0xE3, exactly as the vendor app does in that
        # state; the in-application loader instead needs 0xE3. Send the 0xE1/0xE2
        # pair first and only fall through to 0xE3 if nothing was pulled.
        print('   conn2[A]: normal path - 0xE3 starts the firmware pull')
        served_send, _ = await c.send(0xE3, idle=12.0)
        served_send += (await c.pump(idle=8.0, limit=180.0))[0]
        if served_send:
            firmware_blocks = served_send
            print('   conn2[A]: served %d blocks' % served_send)
            await c.send(0xE6, idle=4.0)
            await c.send(0xE7, bytes([0]), idle=3.0)
        else:
            print('   conn2[B]: forced-update path - 0xE1/0xE2 with file info')
            _, others = await c.send(0xE1, idle=3.0)
            flag = bytes([0])
            for op, pl in others:
                if op == 0xE1 and len(pl) >= 8:
                    off = int.from_bytes(pl[2:6], 'big'); ln = int.from_bytes(pl[6:8], 'big')
                    if ln:
                        flag = firmware[off:off + ln]
                        print('   conn2[B]: 0xE2 carries %d bytes of file info at %d' % (len(flag), off))
            served_send, _ = await c.send(0xE2, flag, idle=12.0)
            served_send += (await c.pump(idle=20.0, limit=300.0))[0]
            print('   conn2[B]: served %d blocks' % served_send)
            await c.send(0xE3, idle=4.0)
            await c.send(0xE6, idle=4.0)
            await c.send(0xE7, bytes([0]), idle=3.0)
        await c.wait_disconnect()
    finally:
        await c.close()

    if firmware_blocks:
        print('=== flashed: %d blocks served in the update phase ===' % firmware_blocks)
    else:
        print('=== no pulls in the update phase; falling back to a loader round ===')
        c = await Conn.open(mac, firmware, sn_start=c.sn)
        tracelog.append(c.trace)
        try:
            await c.authenticate()
            await c.pump(idle=15.0, limit=120.0)
            await c.send(0xE6, idle=3.0)
            await c.send(0x0B, bytes.fromhex('0001'), idle=2.0)
            await c.send(0xE3, idle=6.0)
            await c.send(0xE6, idle=3.0)
            await c.send(0xE7, b'\x00', idle=2.0)
            await c.wait_disconnect()
        finally:
            await c.close()

    Path(trace_path).write_text(json.dumps(tracelog, indent=2), encoding='utf-8')
    print('traces saved to', trace_path)
    print('=== transfer finished; the device should be rebooting into the new firmware ===')
    await asyncio.sleep(3)
    dev = await BleakScanner.find_device_by_address(mac, timeout=8.0)
    print('post-flash advertising:', 'YES %r' % dev.name if dev else 'not seen yet')


async def main():
    global BleakClient, BleakScanner
    ap = argparse.ArgumentParser()
    ap.add_argument('--mac', required=True)
    ap.add_argument('--file', default=None)
    ap.add_argument('--auth-only', action='store_true')
    ap.add_argument('--handshake-only', action='store_true')
    ap.add_argument('--no-auth', action='store_true',
                    help='skip auth (the standalone loader does not require it)')
    ap.add_argument('--trace', type=Path, required=True, help='Local trace output (may contain private device data)')
    args = ap.parse_args()
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        ap.error('Install Tester/requirements.txt before device operations')
    args.trace.parent.mkdir(parents=True, exist_ok=True)

    firmware = Path(args.file).read_bytes() if args.file else None
    if firmware:
        print('firmware: %s (%d bytes)' % (args.file, len(firmware)))

    if args.auth_only or args.handshake_only:
        print('STEP 1: auth')
        c = await Conn.open(args.mac, firmware)
        try:
            if args.no_auth:
                print('   (auth skipped)')
            else:
                await c.authenticate()
            if args.auth_only:
                print('auth-only run: success')
                return 0
            print('STEP 2: opening OTA queries (transfer not started)')
            for name, op, param in (('0x03 target info', 0x03, PARAM_FF),
                                    ('0xE1 file offset', 0xE1, b''),
                                    ('0xE2 inquire', 0xE2, b'\x00')):
                served, others = await c.send(op, param, idle=5.0)
                if served == 0 and not others:
                    print('handshake-only run: %s not answered' % name)
                    return 2
            print('handshake-only run: all three queries answered')
            return 0
        finally:
            await c.close()

    assert firmware is not None, '--file is required for a real flash'
    await flash(args.mac, firmware, args.trace)
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
