/* Emit the legacy 10-byte HLK manufacturer AD and the complete 17-byte name.
   The original advertising frame remains untouched in RAM. */
typedef unsigned char u8;
extern void *stock_memcpy(void *, const void *, unsigned);
extern void stock_scanrsp(u8, const void *);

#ifdef HOST_TEST
extern const u8 *scanrsp_test_adv;
extern u8 scanrsp_test_alen;
extern u8 scanrsp_test_otaflag;
#define SCANRSP_ADV scanrsp_test_adv
#define SCANRSP_ALEN scanrsp_test_alen
#define SCANRSP_OTAF scanrsp_test_otaflag
#else
#define B(a) (*(volatile u8 *)(a))
#define SCANRSP_ADV ((const u8 *)0x4644)
#define SCANRSP_ALEN B(0x468c)
#define SCANRSP_OTAF B(0x4510)
#endif

__attribute__((section(".scanrsp"),noinline))
void scanrsp_hook(u8 len, const u8 *src) {
    const u8 *adv;
    const u8 *hlk;
    u8 alen;
    u8 out[27];

    if (SCANRSP_OTAF) {
        stock_scanrsp(len, src);
        return;
    }

    adv = SCANRSP_ADV;
    alen = SCANRSP_ALEN;
    if (!adv || !src || (alen != 20 && alen != 24) || len != 30 ||
        src[0] != 12 || src[1] != 255 || src[13] != 16 || src[14] != 9) {
        stock_scanrsp(len, src);
        return;
    }

    hlk = adv + alen - 17; /* HLK manufacturer AD is last in the adv frame. */
    if (hlk[0] != 16 || hlk[1] != 255 || hlk[2] != 1 || hlk[3] != 36) {
        stock_scanrsp(len, src);
        return;
    }

    out[0] = 9;
    out[1] = hlk[1];
    out[2] = hlk[2];
    out[3] = hlk[3];
    out[4] = hlk[5];
    out[5] = hlk[4];
    out[6] = hlk[7];
    out[7] = hlk[6];
    out[8] = hlk[9];
    out[9] = hlk[8];
    stock_memcpy(out + 10, src + 13, 17);
    stock_scanrsp(27, out);
}
