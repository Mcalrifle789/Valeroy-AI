/* valeroy_hash.h - Valeroy AI credential hashing (C layer)
 *
 * Self-contained SHA-256 + HMAC-SHA256 + PBKDF2-HMAC-SHA256 with a
 * constant-time verifier. No external dependencies so it builds with any
 * C99 compiler on Windows, Linux or macOS.
 */
#ifndef VALEROY_HASH_H
#define VALEROY_HASH_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32) && defined(VALEROY_HASH_SHARED)
#  ifdef VALEROY_HASH_BUILD
#    define VH_API __declspec(dllexport)
#  else
#    define VH_API __declspec(dllimport)
#  endif
#else
#  define VH_API
#endif

#define VH_SHA256_DIGEST 32
#define VH_SHA256_BLOCK  64

typedef struct {
    uint32_t state[8];
    uint64_t bitlen;
    uint8_t  buf[VH_SHA256_BLOCK];
    size_t   buflen;
} vh_sha256_ctx;

VH_API void vh_sha256_init(vh_sha256_ctx *ctx);
VH_API void vh_sha256_update(vh_sha256_ctx *ctx, const uint8_t *data, size_t len);
VH_API void vh_sha256_final(vh_sha256_ctx *ctx, uint8_t out[VH_SHA256_DIGEST]);

VH_API void vh_hmac_sha256(const uint8_t *key, size_t keylen,
                           const uint8_t *msg, size_t msglen,
                           uint8_t out[VH_SHA256_DIGEST]);

/* Derive `dklen` bytes from `password` using PBKDF2-HMAC-SHA256. */
VH_API int vh_pbkdf2_sha256(const char *password, size_t passlen,
                            const uint8_t *salt, size_t saltlen,
                            uint32_t iterations,
                            uint8_t *out, size_t dklen);

/* Compare two buffers without leaking timing. Returns 1 on match. */
VH_API int vh_consttime_equal(const uint8_t *a, const uint8_t *b, size_t len);

/* Convenience: derive and hex-encode into `out_hex` (needs dklen*2+1 bytes). */
VH_API int vh_pbkdf2_sha256_hex(const char *password,
                                const char *salt_hex,
                                uint32_t iterations,
                                size_t dklen,
                                char *out_hex, size_t out_cap);

#ifdef __cplusplus
}
#endif
#endif /* VALEROY_HASH_H */
