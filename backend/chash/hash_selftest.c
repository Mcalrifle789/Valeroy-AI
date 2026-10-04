/* hash_selftest.c - known-answer tests for the Valeroy C hashing layer.
 *
 * Vectors are the same ones the Rust core asserts on, so a mismatch between the
 * two implementations fails the build rather than drifting silently.
 */
#include "valeroy_hash.h"

#include <stdio.h>
#include <string.h>

static int failures = 0;

static void to_hex(const uint8_t *bytes, size_t n, char *out)
{
    static const char HEX[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < n; ++i) {
        out[i * 2]     = HEX[(bytes[i] >> 4) & 0xf];
        out[i * 2 + 1] = HEX[bytes[i] & 0xf];
    }
    out[n * 2] = '\0';
}

static void check(const char *name, const char *got, const char *want)
{
    if (strcmp(got, want) == 0) {
        printf("  ok   %s\n", name);
    } else {
        printf("  FAIL %s\n       got  %s\n       want %s\n", name, got, want);
        ++failures;
    }
}

static void test_sha256(void)
{
    uint8_t digest[VH_SHA256_DIGEST];
    char hex[VH_SHA256_DIGEST * 2 + 1];
    vh_sha256_ctx ctx;

    vh_sha256_init(&ctx);
    vh_sha256_update(&ctx, (const uint8_t *)"", 0);
    vh_sha256_final(&ctx, digest);
    to_hex(digest, sizeof(digest), hex);
    check("sha256(\"\")", hex,
          "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");

    vh_sha256_init(&ctx);
    vh_sha256_update(&ctx, (const uint8_t *)"abc", 3);
    vh_sha256_final(&ctx, digest);
    to_hex(digest, sizeof(digest), hex);
    check("sha256(\"abc\")", hex,
          "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");

    /* Multi-block input exercises the buffering path. */
    vh_sha256_init(&ctx);
    vh_sha256_update(&ctx,
        (const uint8_t *)"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq", 56);
    vh_sha256_final(&ctx, digest);
    to_hex(digest, sizeof(digest), hex);
    check("sha256(56-byte input)", hex,
          "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
}

static void test_hmac(void)
{
    uint8_t mac[VH_SHA256_DIGEST];
    char hex[VH_SHA256_DIGEST * 2 + 1];

    /* RFC 4231 test case 2 */
    vh_hmac_sha256((const uint8_t *)"Jefe", 4,
                   (const uint8_t *)"what do ya want for nothing?", 28, mac);
    to_hex(mac, sizeof(mac), hex);
    check("hmac-sha256 rfc4231 case2", hex,
          "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843");

    /* RFC 4231 test case 1 */
    {
        uint8_t key[20];
        memset(key, 0x0b, sizeof(key));
        vh_hmac_sha256(key, sizeof(key), (const uint8_t *)"Hi There", 8, mac);
        to_hex(mac, sizeof(mac), hex);
        check("hmac-sha256 rfc4231 case1", hex,
              "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7");
    }

    /* Key longer than the block size takes the hash-the-key branch. */
    {
        uint8_t key[131];
        memset(key, 0xaa, sizeof(key));
        vh_hmac_sha256(key, sizeof(key),
                       (const uint8_t *)"Test Using Larger Than Block-Size Key - Hash Key First",
                       54, mac);
        to_hex(mac, sizeof(mac), hex);
        check("hmac-sha256 rfc4231 case6", hex,
              "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54");
    }
}

static void test_pbkdf2(void)
{
    uint8_t dk[32];
    char hex[65];

    vh_pbkdf2_sha256("password", 8, (const uint8_t *)"salt", 4, 1, dk, sizeof(dk));
    to_hex(dk, sizeof(dk), hex);
    check("pbkdf2-sha256 c=1", hex,
          "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b");

    vh_pbkdf2_sha256("password", 8, (const uint8_t *)"salt", 4, 2, dk, sizeof(dk));
    to_hex(dk, sizeof(dk), hex);
    check("pbkdf2-sha256 c=2", hex,
          "ae4d0c95af6b46d32d0adff928f06dd02a303f8ef3c251dfd6e2d85a95474c43");

    vh_pbkdf2_sha256("password", 8, (const uint8_t *)"salt", 4, 4096, dk, sizeof(dk));
    to_hex(dk, sizeof(dk), hex);
    check("pbkdf2-sha256 c=4096", hex,
          "c5e478d59288c841aa530db6845c4c8d962893a001ce4e11a4963873aa98134a");

    /* dklen that is not a multiple of the digest size. */
    {
        uint8_t short_dk[20];
        char short_hex[41];
        vh_pbkdf2_sha256("passwd", 6, (const uint8_t *)"salt", 4, 1,
                         short_dk, sizeof(short_dk));
        to_hex(short_dk, sizeof(short_dk), short_hex);
        check("pbkdf2-sha256 dklen=20", short_hex,
              "55ac046e56e3089fec1691c22544b605f9418521");
    }
}

static void test_hex_helper(void)
{
    char out[65];
    int rc = vh_pbkdf2_sha256_hex("password", "73616c74" /* "salt" */, 1, 32,
                                 out, sizeof(out));
    if (rc != 0) {
        printf("  FAIL vh_pbkdf2_sha256_hex returned %d\n", rc);
        ++failures;
        return;
    }
    check("pbkdf2 hex helper", out,
          "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b");

    /* Odd-length salt must be rejected rather than silently truncated. */
    if (vh_pbkdf2_sha256_hex("password", "abc", 1, 32, out, sizeof(out)) == 0) {
        printf("  FAIL odd-length salt was accepted\n");
        ++failures;
    } else {
        printf("  ok   odd-length salt rejected\n");
    }

    /* Undersized output buffer must be rejected. */
    if (vh_pbkdf2_sha256_hex("password", "73616c74", 1, 32, out, 8) == 0) {
        printf("  FAIL undersized buffer was accepted\n");
        ++failures;
    } else {
        printf("  ok   undersized buffer rejected\n");
    }
}

static void test_consttime(void)
{
    const uint8_t a[4] = {1, 2, 3, 4};
    const uint8_t b[4] = {1, 2, 3, 4};
    const uint8_t c[4] = {1, 2, 3, 5};

    if (vh_consttime_equal(a, b, 4) == 1) {
        printf("  ok   consttime equal matches\n");
    } else {
        printf("  FAIL consttime equal did not match\n");
        ++failures;
    }
    if (vh_consttime_equal(a, c, 4) == 0) {
        printf("  ok   consttime equal rejects difference\n");
    } else {
        printf("  FAIL consttime equal accepted a difference\n");
        ++failures;
    }
}

int main(void)
{
    printf("valeroy chash selftest\n");
    test_sha256();
    test_hmac();
    test_pbkdf2();
    test_hex_helper();
    test_consttime();

    if (failures == 0) {
        printf("all C hashing tests passed\n");
        return 0;
    }
    printf("%d C hashing test(s) failed\n", failures);
    return 1;
}
