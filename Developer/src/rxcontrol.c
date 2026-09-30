/* Authenticated control advertisements. No state or hardware writes live here. */
typedef unsigned char u8;

extern int aes_block(const u8 *key, const u8 *input, u8 *output);

/* AES-128(bindkey, label) is the per-device control CMAC key. */
__attribute__((section(".rxconst")))
const u8 rx_control_label[16] = {
  'L','D','2','4','-','C','T','R','L','-','K','E','Y','-','v','1'
};

__attribute__((noinline,section(".rxcode")))
static void rx_control_double(u8 block[16]) {
  unsigned i;
  u8 carry = block[0] >> 7;
  for (i = 0; i < 15; i++)
    block[i] = (u8)((block[i] << 1) | (block[i + 1] >> 7));
  block[15] = (u8)((block[15] << 1) ^ (0x87u & (u8)(0u - carry)));
}

/* Returns 1 and copies a valid 21-byte candidate; leaves body untouched on 0. */
__attribute__((noinline,section(".rxcode")))
int rx_control_parse(const u8 *adv, unsigned adv_len,
                     const u8 target_mac[6], u8 body[21]) {
  unsigned pos = 0, i;
  const u8 *candidate = 0;
  if (!adv || !target_mac || !body || adv_len > 31u) return 0;

  while (pos < adv_len) {
    unsigned ad_len = adv[pos++];
    const u8 *ad;
    u8 diff;
    if (ad_len == 0) {
      /* A zero terminator is only valid with zero-filled remaining capacity. */
      while (pos < adv_len) if (adv[pos++] != 0) return 0;
      break;
    }
    if (ad_len > adv_len - pos) return 0;
    ad = adv + pos;
    if (ad_len == 26u && ad[0] == 0xffu &&
        ad[1] == 0xd6u && ad[2] == 0x05u &&
        ad[3] == 0x4cu && ad[4] == 0x43u) {
      const u8 *p = ad + 5;
      diff = 0;
      for (i = 0; i < 6; i++) diff |= p[1 + i] ^ target_mac[i];
      if (p[0] == 1u && diff == 0 && p[11] <= 2u && p[12] == 0u) {
        if (candidate) return 0; /* ambiguous duplicate addressed frames */
        candidate = p;
      }
    }
    pos += ad_len;
  }
  if (!candidate) return 0;
  for (i = 0; i < 21; i++) body[i] = candidate[i];
  return 1;
}

/* CMAC of the first 13 body bytes, compared with the leading eight tag bytes. */
__attribute__((noinline,section(".rxcode")))
int rx_control_auth(const u8 bindkey[16], const u8 body[21]) {
  u8 key[16], block[16], subkey[16], tag[16];
  unsigned i;
  u8 diff = 0;
  int ok = 0;
  if (!bindkey || !body) return 0;

  if (!aes_block(bindkey, rx_control_label, key)) goto done;
  for (i = 0; i < 16; i++) block[i] = 0;
  if (!aes_block(key, block, subkey)) goto done;
  rx_control_double(subkey); /* K1, for complete blocks */
  rx_control_double(subkey); /* K2, for the padded 13-byte block */
  for (i = 0; i < 13; i++) block[i] = body[i] ^ subkey[i];
  block[13] = 0x80u ^ subkey[13];
  block[14] = subkey[14];
  block[15] = subkey[15];
  if (!aes_block(key, block, tag)) goto done;
  for (i = 0; i < 8; i++) diff |= tag[i] ^ body[13 + i];
  ok = diff == 0;

done:
  /* These stack buffers contain the derived key and CMAC material. */
  for (i = 0; i < 16; i++) {
    ((volatile u8 *)key)[i] = 0;
    ((volatile u8 *)block)[i] = 0;
    ((volatile u8 *)subkey)[i] = 0;
    ((volatile u8 *)tag)[i] = 0;
  }
  return ok;
}
