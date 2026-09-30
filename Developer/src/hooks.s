/* Inherited stock hook set; only the advertising version block changes per build.
   Placeholders substituted by build.py: %%VSEQ%% (sequence), %%VMON%% (month),
   %%VYY%% (year).  The block writes <seq> 24 <month> <year> - sp+53 keeps the factory 0x24
   (company-id byte), which is why versions here are always 260924xx.  These four bytes
   must equal the UART A0 stamp patched at 0x1e1b488; verify.py checks exactly that. */
.section .frame_hook,"ax",@progbits
 call report_hook
.section .scanrsp_hook,"ax",@progbits
 call scanrsp_hook
.section .a6_branch,"ax",@progbits
 goto a6_tail
.section .fe_fix,"ax",@progbits
/* Keep the user's manual OUT-hold flag at 0x4514 across FE. The original store
   clears it when leaving config mode; this equivalent-width store clears only
   the config-session byte at 0x4388. Preserve these exact four bytes. */
 .short 0xf916
 .short 0x0048
.section .start_hook,"ax",@progbits
 call refresh_start
.section .rx_report_hook,"ax",@progbits
 call rx_report_shim
.section .rxshim,"ax",@progbits
.globl rx_report_shim
rx_report_shim:
 [--sp] = rets
 r0 = r4
 call rx_capture
 r0 = b[r11 + 0x5] (u)
 {pc} = [sp++]
.section .a2_hook,"ax",@progbits
 goto a2_tail_hook
/* Advertising manufacturer version: <seq> 24 <month> <year>.
   sp+53 keeps the factory 0x24 (the company-id byte the build reuses), which is
   why every version in this project is 260924xx and only the sequence moves.
   These four bytes MUST equal the UART A0 stamp patched at 0x1e1b488. */
.section .version,"ax",@progbits
 r1 = %%VSEQ%%
 b[sp+52] = r1
 r2 = %%VYY%%
 b[sp+53] = r0
 r1 = %%VMON%%
 b[sp+54] = r1
 r1 = b[r8 + 464] (u)
 b[sp+55] = r2
 r3 = b[sp+72] (u)
 r2 = b[sp+73] (u)
 b[sp+56] = r1

.section .a6,"ax",@progbits
.globl a6_tail
a6_tail:
 if (r0 == 0x1) goto a6_reject
 if (r0 == 0x0) goto a6_low
 if (r0 == 0x3) goto a6_key
 if (r0 == 0x4) goto a6_rotate
 if (r0 != 0x2) goto a6_reject
 r1 = 0
 b[r10 + 0x1d4] = r1
 r0 = sp + 30
 r1 = 0x1
 r2 = 0xa6
 r3 = 0x0
 goto a6_responder
a6_low:
 r1 = 1
 b[r10 + 0x1d4] = r1
 goto a6_low_continue
a6_key:
 r0 = sp + 32
 call bindkey_read
 if (r0 == 0) goto a6_reject
 r0 = sp + 32
 r1 = 0x8
 r2 = 0xa6
 r3 = 0x0
 goto a6_responder
a6_rotate:
 r0 = sp + 32
 call bindkey_rotate
 if (r0 == 0) goto a6_reject
 r0 = sp + 32
 r1 = 0x8
 r2 = 0xa6
 r3 = 0x0
 goto a6_responder
a6_reject:
 goto a6_reject_path

/* A2 always executes factory defaults. a2_factory_reset returns success only if
   the new key was durably written and read back; otherwise report the stock error. */
.section .a2,"ax",@progbits
.globl a2_tail_hook
a2_tail_hook:
 call a2_factory_reset
 if (r0 != 0) goto a2_rotated
 goto a2_error_path
a2_rotated:
 goto a2_success

/* One-byte lock acquisition. The saved ICFG value is restored on both paths;
   the short masked window only protects test/set, never VM or crypto work. */
.section .lock,"ax",@progbits
.globl state_lock_try
state_lock_try:
 [--sp] = {rets, r5-r4}
 r4 = icfg
 r5 = r4
 r5 &= 0xfffffcff
 icfg = r5
 csync
 r1 = 0x468c
 r0 = b[r1 + 0] (u)
 if (r0 == 20) goto lock_length_ok
 if (r0 != 24) goto lock_busy
lock_length_ok:
 r1 = 0x4660
 r0 = b[r1 + 0] (u)
 if (r0 != 0) goto lock_busy
 r0 = 1
 b[r1 + 0] = r0
 csync
 goto lock_restore
lock_busy:
 r0 = 0
lock_restore:
 icfg = r4
 csync
 {pc, r5-r4} = [sp++]

.globl state_lock_release
state_lock_release:
 r1 = 0x4660
 r0 = 0
 csync
 b[r1 + 0] = r0
 csync
 rts

/* Hardware AES-128 single block, register block 0x1E4300.
   Validated on device: key/data words little-endian, results read in reverse
   register order and unpacked big-endian. Return r0=1 on success, r0=0 if
   either bounded poll expires. */
.section .aes,"ax",@progbits
.globl aes_block
aes_block:
 [--sp] = {rets, r7-r4}
 r3 = 0x1e4300
 r6 = 4
aes_key:
 r4 = b[r0 + 0] (u)
 r5 = b[r0 + 1] (u)
 r5 = r5 << 8
 r4 |= r5
 r5 = b[r0 + 2] (u)
 r5 = r5 << 16
 r4 |= r5
 r5 = b[r0 + 3] (u)
 r5 = r5 << 24
 r4 |= r5
 [r3 + 8] = r4
 r0 += 4
 r6 += -1
 if (r6 != 0) goto aes_key
 [r3 + 0] = 16
 r7 = 0x20000
aes_kw:
 r4 = [r3 + 0]
 r4 &= 0x20
 if (r4 == 0) goto aes_data
 r7 += -1
 if (r7 == 0) goto aes_fail
 goto aes_kw
aes_data:
 r6 = 4
aes_dl:
 r4 = b[r1 + 0] (u)
 r5 = b[r1 + 1] (u)
 r5 = r5 << 8
 r4 |= r5
 r5 = b[r1 + 2] (u)
 r5 = r5 << 16
 r4 |= r5
 r5 = b[r1 + 3] (u)
 r5 = r5 << 24
 r4 |= r5
 [r3 + 4] = r4
 r1 += 4
 r6 += -1
 if (r6 != 0) goto aes_dl
 [r3 + 0] = 1
 r7 = 0x20000
aes_dw:
 r4 = [r3 + 0]
 r4 &= 0x4
 if (r4 == 0) goto aes_out
 r7 += -1
 if (r7 == 0) goto aes_fail
 goto aes_dw
aes_out:
 r0 = [r3 + 0x18]
 r1 = r0 >> 24
 b[r2 + 0] = r1
 r1 = r0 >> 16
 b[r2 + 1] = r1
 r1 = r0 >> 8
 b[r2 + 2] = r1
 b[r2 + 3] = r0
 r0 = [r3 + 0x14]
 r1 = r0 >> 24
 b[r2 + 4] = r1
 r1 = r0 >> 16
 b[r2 + 5] = r1
 r1 = r0 >> 8
 b[r2 + 6] = r1
 b[r2 + 7] = r0
 r0 = [r3 + 0x10]
 r1 = r0 >> 24
 b[r2 + 8] = r1
 r1 = r0 >> 16
 b[r2 + 9] = r1
 r1 = r0 >> 8
 b[r2 + 10] = r1
 b[r2 + 11] = r0
 r0 = [r3 + 0xc]
 r1 = r0 >> 24
 b[r2 + 12] = r1
 r1 = r0 >> 16
 b[r2 + 13] = r1
 r1 = r0 >> 8
 b[r2 + 14] = r1
 b[r2 + 15] = r0
 r0 = 1
 goto aes_done
aes_fail:
 r0 = 0
aes_done:
 {pc, r7-r4} = [sp++]
