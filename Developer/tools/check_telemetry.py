"""Execute the actual telemetry C functions on a host LLVM target with fixtures.

Requires cryptography, llvmlite and the verified clang executable. This opens no
device and does not execute Q32S instructions; Q32S layout assertions are separate.
"""

import argparse
import ctypes
import os
from pathlib import Path
import re
import subprocess
import tempfile


def check(clang):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM
    from llvmlite import binding as llvm

    root = Path(__file__).resolve().parents[2]
    text = (root / "Developer/src/payload.c").read_text(encoding="utf-8")
    start = text.index("int ccm_encrypt(")
    end = text.index('\n__attribute__((noinline,section(".crypto")))\nstatic int reserve_record', start)
    template = re.search(r"const u8 plain_tpl\[14\] = .*?;", text).group()
    prefix = """
typedef unsigned char u8;
typedef unsigned int u32;
static volatile u8 held, pin;
static volatile u8 stock_len = 20;
static volatile u8 stock_adv[20] = { [14] = 2, [19] = 1 };
static volatile u8 *host_byte(unsigned address) {
  return address == 0x4514 ? &held : &pin;
}
#define B(a) (*host_byte(a))
#define ADVBUF stock_adv
#define ADVLEN (&stock_len)
u8 light_read(void) { return 37; }
unsigned adc_get_voltage(unsigned channel) { return 800; }
void set_inputs(u8 hold, u8 level) { held = hold; pin = level; }
extern int aes_block(const u8 *, const u8 *, u8 *);
"""
    source = prefix + template + "\n" + text[start:end]
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    pointer = ctypes.POINTER(ctypes.c_ubyte)

    @ctypes.CFUNCTYPE(ctypes.c_int, pointer, pointer, pointer)
    def aes_block(key, block, out):
        encryptor = Cipher(algorithms.AES(ctypes.string_at(key, 16)), modes.ECB()).encryptor()
        result = encryptor.update(ctypes.string_at(block, 16)) + encryptor.finalize()
        ctypes.memmove(out, result, 16)
        return 1

    llvm.add_symbol("aes_block", ctypes.cast(aes_block, ctypes.c_void_p).value)
    key = bytes(range(16))
    key_array = (ctypes.c_ubyte * 16)(*key)
    sizes = {0x05: 3, 0x0C: 2, 0x0F: 1, 0x10: 1, 0x21: 1, 0x23: 1, 0x40: 2}
    checked = 0
    with tempfile.TemporaryDirectory(prefix="ld2401 telemetry ") as directory:
        path = Path(directory)
        (path / "fixture.c").write_text(source, encoding="utf-8")
        for status in (False, True):
            command = [str(clang), "-target", "x86_64-pc-windows-msvc", "-S", "-emit-llvm", "-Os", "-fno-builtin"]
            if status:
                command += ["-DLD24_OUT_MODE_STATUS"]
            subprocess.run(command + [str(path / "fixture.c"), "-o", str(path / "fixture.ll")], check=True)
            ir = llvm.parse_assembly((path / "fixture.ll").read_text())
            ir.triple = llvm.get_default_triple()
            machine = llvm.Target.from_default_triple().create_target_machine()
            ir.data_layout = str(machine.target_data)
            engine = llvm.create_mcjit_compiler(ir, machine)
            engine.finalize_object()
            setter = ctypes.CFUNCTYPE(None, ctypes.c_ubyte, ctypes.c_ubyte)(engine.get_function_address("set_inputs"))
            build = ctypes.CFUNCTYPE(ctypes.c_ubyte, pointer, ctypes.c_uint32, ctypes.c_uint32, pointer)(engine.get_function_address("build_live"))
            for radar in (None, 0, 1, 2, 3):
                snapshot = 0 if radar is None else ((radar + 1) << 16) | 123
                for counter in (8192, 8193):
                    for hold in (0, 1):
                        for level in (0, 1):
                            setter(hold, level)
                            out = (ctypes.c_ubyte * 40)(*([0xA5] * 40))
                            length = build(key_array, counter, snapshot, out)
                            frame = bytes(out[:length])
                            assert frame[:3] == bytes.fromhex("020106")
                            assert frame[3] == length - 4 and frame[4:8] == bytes.fromhex("16d2fc41")
                            assert length <= 31 and bytes(out[length:]) == bytes([0xA5] * (40 - length))
                            assert frame[-8:-4] == counter.to_bytes(4, "little")
                            nonce = bytes.fromhex("020000000001d2fc41") + frame[-8:-4]
                            plain = AESCCM(key, tag_length=4).decrypt(nonce, frame[8:-8] + frame[-4:], None)
                            values, ids, pos = {}, [], 0
                            while pos < len(plain):
                                obj = plain[pos]
                                size = sizes[obj]
                                ids.append(obj)
                                values[obj] = int.from_bytes(plain[pos + 1:pos + 1 + size], "little")
                                pos += size + 1
                            assert pos == len(plain) and ids == sorted(ids)
                            assert values[0x05] == 37 << 8 and values[0x10] == level
                            assert (0x0F in values) == status
                            if status:
                                assert values[0x0F] == hold
                            if radar is None:
                                assert 0x21 not in values and 0x23 not in values and 0x40 not in values
                            else:
                                assert values[0x21] == radar & 1 and values[0x23] == (radar != 0)
                            if radar is not None and counter & 1:
                                assert values[0x40] == 1230 and 0x0C not in values
                            else:
                                assert values[0x0C] == 3200 and 0x40 not in values
                            assert len(plain) == (13 if radar is not None else 9) + (2 if status else 0)
                            checked += 1
            engine.close()
    print(f"PASS: {checked} actual C telemetry/CCM fixtures; AD bounds, MIC, object order and measurements")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clang", type=Path, default=Path(os.environ.get("JL_Q32S_BIN", "C:/JL/pi32/bin")) / "clang.exe")
    check(parser.parse_args().clang)
