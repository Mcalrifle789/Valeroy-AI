//! Dependency-free crypto primitives for the Valeroy core.
//!
//! SHA-256, HMAC-SHA256, PBKDF2-HMAC-SHA256 and ChaCha20. The credential vault
//! uses encrypt-then-MAC: ChaCha20 for confidentiality, HMAC-SHA256 for
//! integrity, with both keys derived from one 32-byte data key.

const K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

pub const SHA256_LEN: usize = 32;
const SHA256_BLOCK: usize = 64;

pub struct Sha256 {
    state: [u32; 8],
    buf: [u8; SHA256_BLOCK],
    buflen: usize,
    bitlen: u64,
}

impl Default for Sha256 {
    fn default() -> Self {
        Self::new()
    }
}

impl Sha256 {
    pub fn new() -> Self {
        Sha256 {
            state: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f,
                0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
            ],
            buf: [0u8; SHA256_BLOCK],
            buflen: 0,
            bitlen: 0,
        }
    }

    fn compress(&mut self, block: &[u8]) {
        let mut m = [0u32; 64];
        for i in 0..16 {
            m[i] = u32::from_be_bytes([
                block[i * 4],
                block[i * 4 + 1],
                block[i * 4 + 2],
                block[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = m[i - 15].rotate_right(7) ^ m[i - 15].rotate_right(18) ^ (m[i - 15] >> 3);
            let s1 = m[i - 2].rotate_right(17) ^ m[i - 2].rotate_right(19) ^ (m[i - 2] >> 10);
            m[i] = m[i - 16]
                .wrapping_add(s0)
                .wrapping_add(m[i - 7])
                .wrapping_add(s1);
        }

        let mut v = self.state;
        for i in 0..64 {
            let s1 = v[4].rotate_right(6) ^ v[4].rotate_right(11) ^ v[4].rotate_right(25);
            let ch = (v[4] & v[5]) ^ ((!v[4]) & v[6]);
            let t1 = v[7]
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(m[i]);
            let s0 = v[0].rotate_right(2) ^ v[0].rotate_right(13) ^ v[0].rotate_right(22);
            let maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);
            let t2 = s0.wrapping_add(maj);

            v[7] = v[6];
            v[6] = v[5];
            v[5] = v[4];
            v[4] = v[3].wrapping_add(t1);
            v[3] = v[2];
            v[2] = v[1];
            v[1] = v[0];
            v[0] = t1.wrapping_add(t2);
        }
        for i in 0..8 {
            self.state[i] = self.state[i].wrapping_add(v[i]);
        }
    }

    pub fn update(&mut self, data: &[u8]) {
        for &byte in data {
            self.buf[self.buflen] = byte;
            self.buflen += 1;
            if self.buflen == SHA256_BLOCK {
                let block = self.buf;
                self.compress(&block);
                self.bitlen = self.bitlen.wrapping_add(512);
                self.buflen = 0;
            }
        }
    }

    pub fn finalize(mut self) -> [u8; SHA256_LEN] {
        let bits = self.bitlen.wrapping_add((self.buflen as u64) * 8);
        let mut i = self.buflen;
        self.buf[i] = 0x80;
        i += 1;
        if i > 56 {
            while i < SHA256_BLOCK {
                self.buf[i] = 0;
                i += 1;
            }
            let block = self.buf;
            self.compress(&block);
            i = 0;
        }
        while i < 56 {
            self.buf[i] = 0;
            i += 1;
        }
        self.buf[56..64].copy_from_slice(&bits.to_be_bytes());
        let block = self.buf;
        self.compress(&block);

        let mut out = [0u8; SHA256_LEN];
        for i in 0..8 {
            out[i * 4..i * 4 + 4].copy_from_slice(&self.state[i].to_be_bytes());
        }
        out
    }
}

pub fn sha256(data: &[u8]) -> [u8; SHA256_LEN] {
    let mut h = Sha256::new();
    h.update(data);
    h.finalize()
}

pub fn hmac_sha256(key: &[u8], msg: &[u8]) -> [u8; SHA256_LEN] {
    let mut k = [0u8; SHA256_BLOCK];
    if key.len() > SHA256_BLOCK {
        k[..SHA256_LEN].copy_from_slice(&sha256(key));
    } else {
        k[..key.len()].copy_from_slice(key);
    }

    let mut ipad = [0x36u8; SHA256_BLOCK];
    let mut opad = [0x5cu8; SHA256_BLOCK];
    for i in 0..SHA256_BLOCK {
        ipad[i] ^= k[i];
        opad[i] ^= k[i];
    }

    let mut inner = Sha256::new();
    inner.update(&ipad);
    inner.update(msg);
    let inner = inner.finalize();

    let mut outer = Sha256::new();
    outer.update(&opad);
    outer.update(&inner);
    outer.finalize()
}

pub fn pbkdf2_sha256(password: &[u8], salt: &[u8], iterations: u32, dklen: usize) -> Vec<u8> {
    let mut out = Vec::with_capacity(dklen);
    let mut counter: u32 = 1;
    while out.len() < dklen {
        let mut block = Vec::with_capacity(salt.len() + 4);
        block.extend_from_slice(salt);
        block.extend_from_slice(&counter.to_be_bytes());

        let mut u = hmac_sha256(password, &block);
        let mut t = u;
        for _ in 1..iterations {
            u = hmac_sha256(password, &u);
            for i in 0..SHA256_LEN {
                t[i] ^= u[i];
            }
        }
        let take = (dklen - out.len()).min(SHA256_LEN);
        out.extend_from_slice(&t[..take]);
        counter += 1;
    }
    out
}

/// Timing-safe comparison.
pub fn consttime_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for i in 0..a.len() {
        diff |= a[i] ^ b[i];
    }
    diff == 0
}

/* ------------------------------------------------------------------ *
 * ChaCha20 (RFC 8439)
 * ------------------------------------------------------------------ */

fn quarter_round(s: &mut [u32; 16], a: usize, b: usize, c: usize, d: usize) {
    s[a] = s[a].wrapping_add(s[b]);
    s[d] = (s[d] ^ s[a]).rotate_left(16);
    s[c] = s[c].wrapping_add(s[d]);
    s[b] = (s[b] ^ s[c]).rotate_left(12);
    s[a] = s[a].wrapping_add(s[b]);
    s[d] = (s[d] ^ s[a]).rotate_left(8);
    s[c] = s[c].wrapping_add(s[d]);
    s[b] = (s[b] ^ s[c]).rotate_left(7);
}

fn chacha20_block(key: &[u8; 32], counter: u32, nonce: &[u8; 12]) -> [u8; 64] {
    let mut s = [0u32; 16];
    s[0] = 0x6170_7865;
    s[1] = 0x3320_646e;
    s[2] = 0x7962_2d32;
    s[3] = 0x6b20_6574;
    for i in 0..8 {
        s[4 + i] = u32::from_le_bytes([
            key[i * 4],
            key[i * 4 + 1],
            key[i * 4 + 2],
            key[i * 4 + 3],
        ]);
    }
    s[12] = counter;
    for i in 0..3 {
        s[13 + i] = u32::from_le_bytes([
            nonce[i * 4],
            nonce[i * 4 + 1],
            nonce[i * 4 + 2],
            nonce[i * 4 + 3],
        ]);
    }

    let mut w = s;
    for _ in 0..10 {
        quarter_round(&mut w, 0, 4, 8, 12);
        quarter_round(&mut w, 1, 5, 9, 13);
        quarter_round(&mut w, 2, 6, 10, 14);
        quarter_round(&mut w, 3, 7, 11, 15);
        quarter_round(&mut w, 0, 5, 10, 15);
        quarter_round(&mut w, 1, 6, 11, 12);
        quarter_round(&mut w, 2, 7, 8, 13);
        quarter_round(&mut w, 3, 4, 9, 14);
    }

    let mut out = [0u8; 64];
    for i in 0..16 {
        let v = w[i].wrapping_add(s[i]);
        out[i * 4..i * 4 + 4].copy_from_slice(&v.to_le_bytes());
    }
    out
}

/// ChaCha20 keystream XOR. Symmetric: same call encrypts and decrypts.
pub fn chacha20_xor(key: &[u8; 32], nonce: &[u8; 12], data: &mut [u8]) {
    let mut counter: u32 = 1;
    let mut offset = 0;
    while offset < data.len() {
        let block = chacha20_block(key, counter, nonce);
        let n = (data.len() - offset).min(64);
        for i in 0..n {
            data[offset + i] ^= block[i];
        }
        offset += n;
        counter = counter.wrapping_add(1);
    }
}

/* ------------------------------------------------------------------ *
 * Sealed box: encrypt-then-MAC with subkeys split from one data key
 * ------------------------------------------------------------------ */

fn subkeys(data_key: &[u8; 32]) -> ([u8; 32], [u8; 32]) {
    let enc = hmac_sha256(data_key, b"valeroy-vault-encryption-v1");
    let mac = hmac_sha256(data_key, b"valeroy-vault-authentication-v1");
    (enc, mac)
}

/// Seals `plaintext` into `nonce || ciphertext || tag`.
pub fn seal(data_key: &[u8; 32], nonce: &[u8; 12], plaintext: &[u8]) -> Vec<u8> {
    let (enc_key, mac_key) = subkeys(data_key);
    let mut ct = plaintext.to_vec();
    chacha20_xor(&enc_key, nonce, &mut ct);

    let mut signed = Vec::with_capacity(12 + ct.len());
    signed.extend_from_slice(nonce);
    signed.extend_from_slice(&ct);
    let tag = hmac_sha256(&mac_key, &signed);

    let mut out = signed;
    out.extend_from_slice(&tag);
    out
}

/// Opens a sealed box, verifying the tag before decrypting.
pub fn open(data_key: &[u8; 32], sealed: &[u8]) -> Option<Vec<u8>> {
    if sealed.len() < 12 + SHA256_LEN {
        return None;
    }
    let (enc_key, mac_key) = subkeys(data_key);
    let split = sealed.len() - SHA256_LEN;
    let (signed, tag) = sealed.split_at(split);

    let expected = hmac_sha256(&mac_key, signed);
    if !consttime_eq(&expected, tag) {
        return None;
    }

    let mut nonce = [0u8; 12];
    nonce.copy_from_slice(&signed[..12]);
    let mut pt = signed[12..].to_vec();
    chacha20_xor(&enc_key, &nonce, &mut pt);
    Some(pt)
}

pub fn to_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        s.push(HEX[(b >> 4) as usize] as char);
        s.push(HEX[(b & 0x0f) as usize] as char);
    }
    s
}

pub fn from_hex(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 {
        return None;
    }
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(s.len() / 2);
    let nib = |c: u8| -> Option<u8> {
        match c {
            b'0'..=b'9' => Some(c - b'0'),
            b'a'..=b'f' => Some(c - b'a' + 10),
            b'A'..=b'F' => Some(c - b'A' + 10),
            _ => None,
        }
    };
    for pair in bytes.chunks(2) {
        out.push((nib(pair[0])? << 4) | nib(pair[1])?);
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha256_known_vectors() {
        assert_eq!(
            to_hex(&sha256(b"")),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            to_hex(&sha256(b"abc")),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn hmac_rfc4231_case2() {
        // key = "Jefe", data = "what do ya want for nothing?"
        assert_eq!(
            to_hex(&hmac_sha256(b"Jefe", b"what do ya want for nothing?")),
            "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
        );
    }

    #[test]
    fn pbkdf2_rfc6070_style_vector() {
        // PBKDF2-HMAC-SHA256, P="password", S="salt", c=1, dkLen=32
        assert_eq!(
            to_hex(&pbkdf2_sha256(b"password", b"salt", 1, 32)),
            "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b"
        );
        // c=2
        assert_eq!(
            to_hex(&pbkdf2_sha256(b"password", b"salt", 2, 32)),
            "ae4d0c95af6b46d32d0adff928f06dd02a303f8ef3c251dfd6e2d85a95474c43"
        );
    }

    #[test]
    fn seal_then_open_roundtrips() {
        let key = [7u8; 32];
        let nonce = [9u8; 12];
        let sealed = seal(&key, &nonce, b"sk-secret-api-key");
        assert_eq!(open(&key, &sealed).unwrap(), b"sk-secret-api-key");
    }

    #[test]
    fn open_rejects_tampering() {
        let key = [7u8; 32];
        let nonce = [9u8; 12];
        let mut sealed = seal(&key, &nonce, b"sk-secret-api-key");
        let last = sealed.len() - 1;
        sealed[last] ^= 0x01;
        assert!(open(&key, &sealed).is_none());
    }

    #[test]
    fn open_rejects_wrong_key() {
        let sealed = seal(&[7u8; 32], &[9u8; 12], b"payload");
        assert!(open(&[8u8; 32], &sealed).is_none());
    }

    #[test]
    fn hex_roundtrips() {
        assert_eq!(from_hex(&to_hex(&[0, 1, 254, 255])).unwrap(), vec![0, 1, 254, 255]);
        assert!(from_hex("xyz").is_none());
    }
}
