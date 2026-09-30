/* 26092430: full-width RX context pointer and authenticated OUT control. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
#define B(a) (*(volatile u8 *)(a))
#define H(a) (*(volatile u16 *)(a))
#define W(a) (*(volatile u32 *)(a))
#define ADVBUF ((const volatile u8 *)0x4644)   /* stock advertising data buffer */
#define ADVLEN ((volatile u8 *)0x468c)         /* 20 without AF30, 24 with it */
#define VM_KEY 0x4cu
#define VM_MISSING (-252)
#define VM_EMPTY_FLAGS 0x526du
#define VM_KEY_SLOT 0x51b0u
#define SAVE_EVERY 8192u
#define TICK_MS 500u
#define U32_MAX 0xffffffffu
#define RECORD_MAGIC 0x344b424cu /* "LBK4" in little-endian VM bytes */
#define RECORD_SCHEMA 1u
#define RECORD_SIZE 32u
#define RX_CONTEXT W(0x465c) /* aligned 32-bit pointer; lock remains at 0x4660 */
#define RX_MAX_LAG 120u       /* 60 seconds at the existing 500 ms cadence */

extern u8 light_read(void);
extern unsigned adc_get_voltage(unsigned);
extern unsigned stock_report_mode(void);
extern int COMMAND(int, int, ...);
extern void *stock_malloc(u32);
extern void stock_free(void *);
extern int vm_read(u32, void *, u32);
extern int vm_write(u32, const void *, u32);
extern void stock_factory_defaults(void);
extern u16 stock_timer_add(void *, void (*)(void *), u32);
extern int aes_block(const u8 *, const u8 *, u8 *);
extern void stock_random_fill(u8 *, u32);
extern int state_lock_try(void);
extern void state_lock_release(void);
extern int rx_control_parse(const u8 *, unsigned, const u8 *, u8 *);
extern int rx_control_auth(const u8 *, const u8 *);

struct ctx {
  u32 counter;                /* last counter consumed this boot */
  u32 high;                   /* inclusive persisted range limit for this key */
  u8 key[16];
  u8 state_valid;
  u8 retry_wait;
  u8 retry_level;
  u8 scan_queued;
  u8 rx_pending;
  u32 rx_last;
  u32 rx_floor;              /* previous boot's reserved high-water mark */
  u8 rx_body[21];
  u8 buf[32];                 /* COMMAND queues the pointer; keep it alive in ctx */
  volatile u32 snapshot;      /* state+1 in bits 16.., distance cm in bits 0..15 */
};
typedef char ctx_rx_last_offset_must_stay_32[(__builtin_offsetof(struct ctx,rx_last)==32) ? 1 : -1];

struct vm_record {
  u32 magic;
  u16 schema;
  u16 length;
  u8 key[16];
  u32 high;
  u32 crc;
};
typedef char vm_record_size_must_be_32[(sizeof(struct vm_record)==RECORD_SIZE) ? 1 : -1];
typedef char vm_record_crc_offset_must_be_28[(__builtin_offsetof(struct vm_record,crc)==28) ? 1 : -1];

enum record_status { REC_IO=-1, REC_BAD=0, REC_VALID=1, REC_LEGACY=2, REC_EMPTY=3 };

__attribute__((section(".cdata")))
const u8 plain_tpl[14] = {5,0,0,0, 0x0c,0,0, 0x21,0, 0x23,0, 0x40,0,0};

__attribute__((noinline,section(".crypto")))
static void copy_bytes(u8 *dst, const u8 *src, unsigned n) {
  unsigned i;
  for (i=0;i<n;i++) dst[i]=src[i];
}

__attribute__((noinline,section(".crypto")))
static int bytes_equal(const u8 *a, const u8 *b, unsigned n) {
  unsigned i;
  u8 diff=0;
  for (i=0;i<n;i++) diff |= a[i] ^ b[i];
  return diff == 0;
}

__attribute__((noinline,section(".guard")))
unsigned ready(void) {
  u8 n = B(0x468c);
  return !B(0x4510) && B(0x47c6)==0x20 &&
    W(0x47bc)==0x4684 && W(0x4684)==0x4644 && (n==20 || n==24);
}

/* The aligned 0x465c..0x465f word is beyond the stock 20/24-byte ADV.
   Store the complete heap address. All live callers check ready() first;
   refresh_start uses the startup-zeroed slot to prevent duplicate timers. */
__attribute__((noinline,section(".crypto")))
static struct ctx *rx_context(void) {
  return (struct ctx *)RX_CONTEXT;
}

/* Called by the E2 advertising-report hook. The event packet belongs to the
   BLE stack; copy only one bounded candidate and leave crypto for the tick. */
__attribute__((noinline,section(".crypto")))
void rx_capture(const u8 *report) {
  struct ctx *c;
  u8 length;
  if (!report || !ready()) return;
  c = rx_context();
  length = report[0x0b];
  if (length > 31 || !state_lock_try()) return;
  c = rx_context();
  if (c && c->state_valid && !c->rx_pending &&
      rx_control_parse(report+0x0c, length, (const u8 *)(ADVBUF+*ADVLEN-6), c->rx_body)) {
    c->rx_pending = 1;
  }
  state_lock_release();
}

__attribute__((noinline,section(".capture")))
unsigned report_hook(void) {
  unsigned mode=stock_report_mode();
  unsigned state, cm;
  struct ctx *c;
  if (!ready()) return mode;
  c=rx_context();
  if (!c) return mode;
  state = B(0x2d38);
  if (state > 3) return mode;
  /* Odd-address distance cannot be loaded with an aligned halfword read. */
  cm = B(0x2d3f) | ((unsigned)B(0x2d40) << 8);
  c->snapshot=cm | ((state+1) << 16);
  return mode;
}

/* Standard reflected CRC-32/ISO-HDLC over every versioned record field before crc. */
__attribute__((noinline,section(".crypto")))
static u32 record_crc(const u8 *p, unsigned n) {
  u32 c=0xffffffffu;
  unsigned i, bit;
  for (i=0;i<n;i++) {
    c ^= p[i];
    for (bit=0;bit<8;bit++) c = (c >> 1) ^ ((c & 1) ? 0xedb88320u : 0u);
  }
  return c ^ 0xffffffffu;
}

__attribute__((noinline,section(".crypto")))
static int invalid_key(const u8 *key) {
  unsigned i;
  u8 all0=0xff, allf=0xff;
  for (i=0;i<16;i++) { all0 &= (u8)~key[i]; allf &= key[i]; }
  return all0 == 0xff || allf == 0xff;
}

__attribute__((noinline,section(".crypto")))
static int record_valid(const struct vm_record *r) {
  if (r->magic != RECORD_MAGIC || r->schema != RECORD_SCHEMA ||
      r->length != RECORD_SIZE || invalid_key(r->key)) return 0;
  return r->crc == record_crc((const u8 *)r, RECORD_SIZE-4);
}

/* The audited VM reader returns -252 for both an absent slot and a record-data
   CRC failure. The slot index and factory-cleared flag distinguish a genuine
   empty slot. Other negative results, including VM-not-initialized (-250), are
   I/O/state errors and must never authorize an overwrite. A 4-byte record is old. */
__attribute__((noinline,section(".crypto")))
static int read_record(struct vm_record *r) {
  int n=vm_read(VM_KEY, r, RECORD_SIZE);
  if (n == RECORD_SIZE) return record_valid(r) ? REC_VALID : REC_BAD;
  if (n == 4) return REC_LEGACY;
  if (n == VM_MISSING) {
    if (H(VM_KEY_SLOT) == 0 && (B(VM_EMPTY_FLAGS) & 1)) return REC_EMPTY;
    return REC_BAD;
  }
  if (n < 0) return REC_IO;
  /* Any other nonnegative byte count means a present but unexpected record. */
  return REC_BAD;
}

__attribute__((noinline,section(".crypto")))
static void seal_record(struct vm_record *r) {
  r->magic = RECORD_MAGIC;
  r->schema = RECORD_SCHEMA;
  r->length = RECORD_SIZE;
  r->crc = record_crc((const u8 *)r, RECORD_SIZE-4);
}

/* vm_write can report a length without proving the Flash write completed. */
__attribute__((noinline,section(".crypto")))
static int save_record(struct vm_record *r) {
  struct vm_record back;
  seal_record(r);
  if (vm_write(VM_KEY, r, RECORD_SIZE) != RECORD_SIZE) return 0;
  if (vm_read(VM_KEY, &back, RECORD_SIZE) != RECORD_SIZE) return 0;
  if (!record_valid(&back) || !bytes_equal((const u8 *)r, (const u8 *)&back, RECORD_SIZE)) return 0;
  return 1;
}

/* The factory RNG helper fills 16 bytes in four-byte chunks with a delay. It has
   no established CSPRNG guarantee; bound retries and reject obvious bad output. */
__attribute__((noinline,section(".crypto")))
static int random_key(u8 *key, const u8 *old, int have_old) {
  unsigned attempt;
  for (attempt=0;attempt<8;attempt++) {
    stock_random_fill(key, 16);
    if (invalid_key(key)) continue;
    if (have_old && bytes_equal(key, old, 16)) continue;
    return 1;
  }
  return 0;
}

__attribute__((noinline,section(".crypto")))
static int create_record(struct vm_record *r) {
  unsigned i;
  for (i=0;i<sizeof(*r);i++) ((u8 *)r)[i]=0;
  r->high=0;
  if (!random_key(r->key, (const u8 *)0, 0)) return 0;
  return save_record(r);
}

/* First A603 or first timer tick migrates empty/legacy VM once to a fresh key. */
__attribute__((noinline,section(".crypto")))
static int load_or_migrate(struct vm_record *r) {
  int status=read_record(r);
  if (status == REC_VALID) return 1;
  if (status == REC_LEGACY || status == REC_EMPTY) return create_record(r);
  return 0;
}

/* Called only while state_lock is held. Rotated state is copied to RAM only after
   the versioned record has been written and read back byte-for-byte. */
__attribute__((noinline,section(".crypto")))
static int rotate_record(u8 *out) {
  struct vm_record old, next;
  int status=read_record(&old);
  int have_old=(status == REC_VALID);
  unsigned i;
  /* Explicit A604/A2 can replace a CRC-corrupt or malformed record with a fresh
     random key. The failed VM read does not expose the old key bytes, so duplicate
     exclusion in this one recovery case is probabilistic under the stock RNG. */
  if (status == REC_IO) return 0;
  if (status != REC_VALID && status != REC_BAD &&
      status != REC_LEGACY && status != REC_EMPTY) return 0;
  for (i=0;i<sizeof(next);i++) ((u8 *)&next)[i]=0;
  next.high=0;
  if (!random_key(next.key, old.key, have_old)) return 0;
  if (!save_record(&next)) return 0;
  if (out) copy_bytes(out, next.key, 16);
  return 1;
}

/* A603 is read-only for current-format state; only empty/legacy migration writes. */
__attribute__((noinline,section(".crypto")))
int bindkey_read(u8 *out) {
  struct vm_record r;
  int ok=0;
  if (!state_lock_try()) return 0;
  if (load_or_migrate(&r)) { copy_bytes(out, r.key, 16); ok=1; }
  state_lock_release();
  return ok;
}

/* A604 and A2 share this one durable rotate transaction. */
__attribute__((noinline,section(".crypto")))
int bindkey_rotate(u8 *out) {
  int ok;
  if (!state_lock_try()) return 0;
  ok=rotate_record(out);
  state_lock_release();
  return ok;
}

/* A2 must reset factory settings even if secure key rotation cannot be verified.
   Its caller uses this return value to choose the stock success or error reply. */
__attribute__((noinline,section(".crypto")))
int a2_factory_reset(void) {
  int key_ok=bindkey_rotate((u8 *)0);
  stock_factory_defaults();
  return key_ok;
}

/* AES-CCM over one padded block (plaintext <= 16 bytes), L=2, MIC=4, no AAD. */
__attribute__((noinline,section(".crypto")))
int ccm_encrypt(const u8 *key, const u8 *nonce, const u8 *plain, u8 n, u8 *ct, u8 *mic) {
  u8 b[16], x[16], s[16];
  unsigned i;
  for (i=0;i<16;i++) b[i] = 0;
  b[0] = 9;
  for (i=0;i<13;i++) b[1+i] = nonce[i];
  b[15] = n;
  if (!aes_block(key, b, x)) return 0;
  for (i=0;i<16;i++) b[i] = (i<n) ? plain[i] : 0;
  for (i=0;i<16;i++) b[i] ^= x[i];
  if (!aes_block(key, b, x)) return 0;
  for (i=0;i<16;i++) b[i] = 0;
  b[0] = 1;
  for (i=0;i<13;i++) b[1+i] = nonce[i];
  if (!aes_block(key, b, s)) return 0;
  for (i=0;i<4;i++) mic[i] = x[i] ^ s[i];
  b[15] = 1;
  if (!aes_block(key, b, s)) return 0;
  for (i=0;i<n;i++) ct[i] = plain[i] ^ s[i];
  return 1;
}

__attribute__((noinline,section(".crypto")))
u8 build_frame_impl(u32 counter, const u8 *key, const u8 *plain, u8 n, u8 *out) {
  u8 nonce[13], ct[16], mic[4];
  unsigned i;
  {
    const volatile u8 *mac = ADVBUF + (*ADVLEN) - 6;
    for (i=0;i<6;i++) nonce[i] = mac[i];
  }
  nonce[6] = 0xd2; nonce[7] = 0xfc; nonce[8] = 0x41;
  nonce[9]  = counter;        nonce[10] = counter >> 8;
  nonce[11] = counter >> 16;  nonce[12] = counter >> 24;
  if (!ccm_encrypt(key, nonce, plain, n, ct, mic)) return 0;
  out[0]=2; out[1]=1; out[2]=6;
  out[3] = 12 + n; out[4] = 0x16; out[5] = 0xd2; out[6] = 0xfc; out[7] = 0x41;
  for (i=0;i<n;i++) out[8+i] = ct[i];
  for (i=0;i<4;i++) out[8+n+i] = counter >> (8*i);
  for (i=0;i<4;i++) out[12+n+i] = mic[i];
  return 16 + n;
}

__attribute__((noinline,section(".crypto")))
u8 build_live(const u8 *key, u32 counter, u32 snapshot, u8 *out) {
  u8 plain[14];
  unsigned s, i, v, st, mm;
  u8 n = 9;
  /* BTHome 0x10 is a one-byte power binary sensor. Read the physical OUT pin,
     since the logic-side cache does not reflect manual A6 overrides reliably. */
  for (i=0;i<4;i++) plain[i] = plain_tpl[i];
  plain[2] = light_read();
  s = snapshot;
  if (s >> 16) {
    st = (s >> 16) - 1;
    /* The 31-byte legacy AD limit leaves room for OUT only if voltage and
       distance share this slot. Counter parity alternates the two objects. */
    if (counter & 1) {
      plain[4] = 0x10;
      plain[5] = B(0x1e5000) & 1;
      plain[6] = 0x21;
      plain[7] = st & 1;
      plain[8] = 0x23;
      plain[9] = (st != 0);
      plain[10] = 0x40;
      mm = (s & 0xffff) * 10;
      plain[11] = mm; plain[12] = mm >> 8;
    } else {
      plain[4] = 0x0c;
      v = adc_get_voltage(0x5000d) * 4;
      plain[5] = v; plain[6] = v >> 8;
      plain[7] = 0x10;
      plain[8] = B(0x1e5000) & 1;
      plain[9] = 0x21;
      plain[10] = st & 1;
      plain[11] = 0x23;
      plain[12] = (st != 0);
    }
    n = 13;
  } else {
    /* There is no valid distance yet, so keep voltage available continuously. */
    plain[4] = 0x0c;
    v = adc_get_voltage(0x5000d) * 4;
    plain[5] = v; plain[6] = v >> 8;
    plain[7] = 0x10;
    plain[8] = B(0x1e5000) & 1;
  }
  return build_frame_impl(counter, key, plain, n, out);
}

__attribute__((noinline,section(".crypto")))
static int reserve_record(struct vm_record *r) {
  if (r->high > U32_MAX - SAVE_EVERY) return 0;
  r->high += SAVE_EVERY;
  return save_record(r);
}

__attribute__((noinline,section(".crypto")))
static void schedule_retry(struct ctx *c) {
  if (c->retry_level < 6) c->retry_level++;
  c->retry_wait=(u8)(1u << c->retry_level);
}

__attribute__((noinline,section(".crypto")))
static void clear_retry(struct ctx *c) {
  c->retry_wait=0;
  c->retry_level=0;
}

/* Invoked only with the shared state lock held. The message counter is sampled
   from a previously transmitted BTHome frame and must be recent and unused. */
__attribute__((noinline,section(".crypto")))
static void rx_apply_pending(struct ctx *c) {
  u32 seen, gpio;
  u8 command;
  const u8 *m=c->rx_body;
  if (!c->rx_pending) return;
  c->rx_pending=0;
  seen=(u32)m[7] | ((u32)m[8]<<8) | ((u32)m[9]<<16) | ((u32)m[10]<<24);
  if (!seen || seen <= c->rx_floor || seen <= c->rx_last || seen > c->counter ||
      c->counter-seen > RX_MAX_LAG || !rx_control_auth(c->key,m)) return;
  c->rx_last=seen;
  command=m[11];
  if (command==2) {
    B(0x4514)=0;                 /* return OUT to stock automatic control */
    return;
  }
  B(0x4514)=1;                   /* mirror the original A6 manual hold */
  gpio=W(0x1e5000);
  if (command) gpio|=1u;
  else gpio&=~1u;
  W(0x1e5000)=gpio;
}

/* The original B2 command proves that these two enqueue calls enable scanning
   without blocking the UART. Run them outside the VM/crypto lock. */
__attribute__((noinline,section(".crypto")))
static void rx_start_scan(struct ctx *c) {
  /* 0x4345 is the stock B2 scan-state byte: the handler at 0x1e0152e sets
     state 1 before queuing the scan, and the report handler at 0x1e04c82
     consumes reports only while it is 1, then changes it to 2 on a MAC match.
     Skip our scan while that stock B2 operation is active. This is reverse-
     engineered behavior, not a documented SDK contract; a stuck 1 suppresses
     our receive scan. See docs/firmware-implementation.md (B2 scan state). */
  if (!c->state_valid || c->scan_queued || !ready() || B(0x4345)==1) return;
  if (COMMAND(0x0d,3,0,0x10,0x10) != 0) return;
  if (COMMAND(0x0c,1,1) == 0) {
    c->scan_queued=1;
  }
}

__attribute__((noinline,section(".crypto")))
void bthome_tick(void *p) {
  struct ctx *c=(struct ctx *)p;
  struct vm_record r;
  u32 next;
  u8 len;
  int same;
  if (c->retry_wait) { c->retry_wait--; return; }
  if (!ready() || !state_lock_try()) return;
  if (!load_or_migrate(&r)) goto failed;
  same = c->state_valid && bytes_equal(c->key, r.key, 16);
  if (!same) {
    copy_bytes(c->key, r.key, 16);
    c->counter = r.high;
    c->high = r.high;
    c->state_valid = 1;
    c->rx_last=0;
    c->rx_floor=r.high;
    c->rx_pending=0;
  } else if (r.high < c->high) {
    /* Same-key rollback or corruption: never reuse a previously reserved range. */
    goto failed;
  } else if (r.high > c->high) {
    /* Another owner reserved a range, or a prior commit completed ambiguously. */
    c->counter = r.high;
    c->high = r.high;
  }
  if (c->counter >= r.high) {
    if (!reserve_record(&r)) goto failed;
    c->high = r.high;
  }
  if (c->counter == U32_MAX) goto done;
  rx_apply_pending(c);
  next = c->counter + 1;
  if (next > c->high) goto failed;
  /* Consume before crypto/COMMAND; failures may skip but never reuse this nonce. */
  c->counter = next;
  len = build_live(c->key, next, c->snapshot, c->buf);
  if (!len) goto failed;
  COMMAND(3, 2, len, c->buf);
  clear_retry(c);
  goto done;
 failed:
  schedule_retry(c);
 done:
  state_lock_release();
  rx_start_scan(c);
}

__attribute__((noinline,section(".crypto")))
u16 refresh_start(void *priv, void (*callback)(void *), u32 period) {
  u16 original=stock_timer_add(priv, callback, period); /* keep stock 6000 ms timer */
  struct ctx *c;
  if (RX_CONTEXT) return original;
  c=(struct ctx *)stock_malloc(sizeof(struct ctx));
  if (c) {
    c->counter=0;
    c->high=0;
    c->state_valid=0;
    c->retry_wait=0;
    c->retry_level=0;
    c->scan_queued=0;
    c->rx_pending=0;
    c->rx_last=0;
    c->rx_floor=0;
    c->snapshot=0;
    if (!stock_timer_add(c, bthome_tick, TICK_MS)) stock_free(c);
    else {
      __asm__ volatile ("csync" ::: "memory");
      RX_CONTEXT=(u32)c; /* publish only after initialization and timer success */
      __asm__ volatile ("csync" ::: "memory");
    }
  }
  return original;
}
