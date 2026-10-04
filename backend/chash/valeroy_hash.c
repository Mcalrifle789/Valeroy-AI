/* valeroy_hash.c - Valeroy AI credential hashing (C layer) */
#include "valeroy_hash.h"

#include <string.h>

#define VH_MAX_SALT 128

#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))
#define CH(x, y, z)  (((x) & (y)) ^ (~(x) & (z)))
#define MAJ(x, y, z) (((x) & (y)) ^ ((x) & (z)) ^ ((y) & (z)))
#define EP0(x) (ROR(x, 2) ^ ROR(x, 13) ^ ROR(x, 22))
#define EP1(x) (ROR(x, 6) ^ ROR(x, 11) ^ ROR(x, 25))
#define SIG0(x) (ROR(x, 7) ^ ROR(x, 18) ^ ((x) >> 3))
#define SIG1(x) (ROR(x, 17) ^ ROR(x, 19) ^ ((x) >> 10))

static const uint32_t K[64] = {
    0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,
    0x923f82a4u,0xab1c5ed5u,0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,
    0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,0xe49b69c1u,0xefbe4786u,
    0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
    0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,
    0x06ca6351u,0x14292967u,0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,
    0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,0xa2bfe8a1u,0xa81a664bu,
    0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
    0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,
    0x5b9cca4fu,0x682e6ff3u,0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,
    0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u
};

static void vh_sha256_block(vh_sha256_ctx *ctx, const uint8_t *data)
{
    uint32_t m[64], a, b, c, d, e, f, g, h, t1, t2;
    int i;

    for (i = 0; i < 16; ++i) {
        m[i] = ((uint32_t)data[i * 4] << 24) | ((uint32_t)data[i * 4 + 1] << 16) |
               ((uint32_t)data[i * 4 + 2] << 8) | ((uint32_t)data[i * 4 + 3]);
    }
    for (; i < 64; ++i)
        m[i] = SIG1(m[i - 2]) + m[i - 7] + SIG0(m[i - 15]) + m[i - 16];

    a = ctx->state[0]; b = ctx->state[1]; c = ctx->state[2]; d = ctx->state[3];
    e = ctx->state[4]; f = ctx->state[5]; g = ctx->state[6]; h = ctx->state[7];

    for (i = 0; i < 64; ++i) {
        t1 = h + EP1(e) + CH(e, f, g) + K[i] + m[i];
        t2 = EP0(a) + MAJ(a, b, c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    ctx->state[0] += a; ctx->state[1] += b; ctx->state[2] += c; ctx->state[3] += d;
    ctx->state[4] += e; ctx->state[5] += f; ctx->state[6] += g; ctx->state[7] += h;
}

void vh_sha256_init(vh_sha256_ctx *ctx)
{
    ctx->bitlen = 0;
    ctx->buflen = 0;
    ctx->state[0] = 0x6a09e667u; ctx->state[1] = 0xbb67ae85u;
    ctx->state[2] = 0x3c6ef372u; ctx->state[3] = 0xa54ff53au;
    ctx->state[4] = 0x510e527fu; ctx->state[5] = 0x9b05688cu;
    ctx->state[6] = 0x1f83d9abu; ctx->state[7] = 0x5be0cd19u;
}

void vh_sha256_update(vh_sha256_ctx *ctx, const uint8_t *data, size_t len)
{
    size_t i;
    for (i = 0; i < len; ++i) {
        ctx->buf[ctx->buflen++] = data[i];
        if (ctx->buflen == VH_SHA256_BLOCK) {
            vh_sha256_block(ctx, ctx->buf);
            ctx->bitlen += 512;
            ctx->buflen = 0;
        }
    }
}

void vh_sha256_final(vh_sha256_ctx *ctx, uint8_t out[VH_SHA256_DIGEST])
{
    size_t i = ctx->buflen;
    uint64_t bits = ctx->bitlen + (uint64_t)ctx->buflen * 8;

    ctx->buf[i++] = 0x80;
    if (i > 56) {
        while (i < VH_SHA256_BLOCK) ctx->buf[i++] = 0;
        vh_sha256_block(ctx, ctx->buf);
        i = 0;
    }
    while (i < 56) ctx->buf[i++] = 0;

    for (i = 0; i < 8; ++i)
        ctx->buf[56 + i] = (uint8_t)(bits >> (56 - 8 * i));
    vh_sha256_block(ctx, ctx->buf);

    for (i = 0; i < 8; ++i) {
        out[i * 4]     = (uint8_t)(ctx->state[i] >> 24);
        out[i * 4 + 1] = (uint8_t)(ctx->state[i] >> 16);
        out[i * 4 + 2] = (uint8_t)(ctx->state[i] >> 8);
        out[i * 4 + 3] = (uint8_t)(ctx->state[i]);
    }
}

void vh_hmac_sha256(const uint8_t *key, size_t keylen,
                    const uint8_t *msg, size_t msglen,
                    uint8_t out[VH_SHA256_DIGEST])
{
    uint8_t k[VH_SHA256_BLOCK], inner[VH_SHA256_DIGEST];
    uint8_t pad[VH_SHA256_BLOCK];
    vh_sha256_ctx ctx;
    size_t i;

    memset(k, 0, sizeof(k));
    if (keylen > VH_SHA256_BLOCK) {
        vh_sha256_init(&ctx);
        vh_sha256_update(&ctx, key, keylen);
        vh_sha256_final(&ctx, k);
    } else {
        memcpy(k, key, keylen);
    }

    for (i = 0; i < VH_SHA256_BLOCK; ++i) pad[i] = (uint8_t)(k[i] ^ 0x36);
    vh_sha256_init(&ctx);
    vh_sha256_update(&ctx, pad, VH_SHA256_BLOCK);
    vh_sha256_update(&ctx, msg, msglen);
    vh_sha256_final(&ctx, inner);

    for (i = 0; i < VH_SHA256_BLOCK; ++i) pad[i] = (uint8_t)(k[i] ^ 0x5c);
    vh_sha256_init(&ctx);
    vh_sha256_update(&ctx, pad, VH_SHA256_BLOCK);
    vh_sha256_update(&ctx, inner, VH_SHA256_DIGEST);
    vh_sha256_final(&ctx, out);

    memset(k, 0, sizeof(k));
    memset(pad, 0, sizeof(pad));
}

int vh_pbkdf2_sha256(const char *password, size_t passlen,
                     const uint8_t *salt, size_t saltlen,
                     uint32_t iterations,
                     uint8_t *out, size_t dklen)
{
    uint8_t u[VH_SHA256_DIGEST], t[VH_SHA256_DIGEST];
    uint8_t block[VH_MAX_SALT + 4];
    size_t blocklen, done = 0;
    uint32_t counter = 1, iter;
    int i;

    if (!password || !salt || !out || iterations == 0 || dklen == 0)
        return -1;
    if (saltlen > VH_MAX_SALT)
        return -1;

    blocklen = saltlen + 4;
    memcpy(block, salt, saltlen);

    while (done < dklen) {
        size_t chunk;
        block[saltlen]     = (uint8_t)(counter >> 24);
        block[saltlen + 1] = (uint8_t)(counter >> 16);
        block[saltlen + 2] = (uint8_t)(counter >> 8);
        block[saltlen + 3] = (uint8_t)(counter);

        vh_hmac_sha256((const uint8_t *)password, passlen, block, blocklen, u);
        memcpy(t, u, VH_SHA256_DIGEST);

        for (iter = 1; iter < iterations; ++iter) {
            vh_hmac_sha256((const uint8_t *)password, passlen,
                           u, VH_SHA256_DIGEST, u);
            for (i = 0; i < VH_SHA256_DIGEST; ++i) t[i] ^= u[i];
        }

        chunk = dklen - done;
        if (chunk > VH_SHA256_DIGEST) chunk = VH_SHA256_DIGEST;
        memcpy(out + done, t, chunk);
        done += chunk;
        ++counter;
    }

    memset(u, 0, sizeof(u));
    memset(t, 0, sizeof(t));
    return 0;
}

int vh_consttime_equal(const uint8_t *a, const uint8_t *b, size_t len)
{
    uint8_t diff = 0;
    size_t i;
    if (!a || !b) return 0;
    for (i = 0; i < len; ++i) diff |= (uint8_t)(a[i] ^ b[i]);
    return diff == 0;
}

static int vh_hex_nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int vh_pbkdf2_sha256_hex(const char *password,
                         const char *salt_hex,
                         uint32_t iterations,
                         size_t dklen,
                         char *out_hex, size_t out_cap)
{
    static const char HEX[] = "0123456789abcdef";
    uint8_t salt[VH_MAX_SALT], dk[VH_MAX_SALT];
    size_t saltlen = 0, i, hexlen;

    if (!password || !salt_hex || !out_hex) return -1;
    if (dklen == 0 || dklen > sizeof(dk)) return -1;

    hexlen = strlen(salt_hex);
    if (hexlen % 2 != 0 || hexlen / 2 > sizeof(salt)) return -1;
    for (i = 0; i < hexlen; i += 2) {
        int hi = vh_hex_nibble(salt_hex[i]);
        int lo = vh_hex_nibble(salt_hex[i + 1]);
        if (hi < 0 || lo < 0) return -1;
        salt[saltlen++] = (uint8_t)((hi << 4) | lo);
    }

    if (out_cap < dklen * 2 + 1) return -1;
    if (vh_pbkdf2_sha256(password, strlen(password), salt, saltlen,
                         iterations, dk, dklen) != 0)
        return -1;

    for (i = 0; i < dklen; ++i) {
        out_hex[i * 2]     = HEX[(dk[i] >> 4) & 0xf];
        out_hex[i * 2 + 1] = HEX[dk[i] & 0xf];
    }
    out_hex[dklen * 2] = '\0';
    memset(dk, 0, sizeof(dk));
    return 0;
}
