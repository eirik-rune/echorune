#!/usr/bin/env python3
"""Verify the echorune covenant: document hash + both EIP-191 signatures.

Zero dependencies - python3 standard library only. Single file, ~180 lines.

  python3 verify_covenant_standalone.py --remote      # fetch from GitHub and verify
  python3 verify_covenant_standalone.py [doc] [sigs]  # verify local files

The hash is always recomputed from raw bytes. Self-tests keccak256 against known
vectors before trusting any verdict. Anyone can audit this file end to end.
"""
import json, sys

# keccak256, pure python3 stdlib. Note: NOT hashlib.sha3_256 (different padding).
_RC = [0x0000000000000001,0x0000000000008082,0x800000000000808A,0x8000000080008000,
       0x000000000000808B,0x0000000080000001,0x8000000080008081,0x8000000000008009,
       0x000000000000008A,0x0000000000000088,0x0000000080008009,0x000000008000000A,
       0x000000008000808B,0x800000000000008B,0x8000000000008089,0x8000000000008003,
       0x8000000000008002,0x8000000000000080,0x000000000000800A,0x800000008000000A,
       0x8000000080008081,0x8000000000008080,0x0000000080000001,0x8000000080008008]
_R = [[0,36,3,41,18],[1,44,10,45,2],[62,6,43,15,61],[28,55,25,21,56],[27,20,39,8,14]]
_M = (1 << 64) - 1

def _rol(v, n):
    n &= 63
    return ((v << n) | (v >> (64 - n))) & _M

def _f(A):
    for rnd in range(24):
        C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
        D = [C[(x - 1) % 5] ^ _rol(C[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                A[x][y] ^= D[x]
        B = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                B[y][(2 * x + 3 * y) % 5] = _rol(A[x][y], _R[x][y])
        for x in range(5):
            for y in range(5):
                A[x][y] = B[x][y] ^ ((~B[(x + 1) % 5][y]) & B[(x + 2) % 5][y] & _M)
        A[0][0] ^= _RC[rnd]
    return A

def keccak256(data):
    rate = 136                      # 200 - 2*32
    m = bytearray(data)
    m.append(0x01)                  # Keccak padding (SHA-3 would use 0x06)
    while len(m) % rate != 0:
        m.append(0x00)
    m[-1] |= 0x80
    A = [[0] * 5 for _ in range(5)]
    for off in range(0, len(m), rate):
        blk = m[off:off + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(blk[i * 8:i * 8 + 8], "little")
            A[i % 5][i // 5] ^= lane
        _f(A)
    out = bytearray()
    while len(out) < 32:
        for i in range(rate // 8):
            if len(out) >= 32:
                break
            out += A[i % 5][i // 5].to_bytes(8, "little")
    return bytes(out[:32])

# secp256k1 public-key recovery, pure python3 stdlib. For VERIFICATION only.
P  = 2**256 - 2**32 - 977
N  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

def _add(p1, p2):
    if p1 is None: return p2
    if p2 is None: return p1
    x1, y1 = p1; x2, y2 = p2
    if x1 == x2:
        if (y1 + y2) % P == 0: return None
        l = 3 * x1 * x1 % P * pow(2 * y1 % P, P - 2, P) % P
    else:
        l = (y2 - y1) * pow(x2 - x1, P - 2, P) % P
    x3 = (l * l - x1 - x2) % P
    return (x3, (l * (x1 - x3) - y1) % P)

def _mul(pt, k):
    r = None
    while k:
        if k & 1: r = _add(r, pt)
        pt = _add(pt, pt)
        k >>= 1
    return r

def recover(msg_hash, sig65):
    """msg_hash: 32 bytes. sig65: r||s||v (v = 0/1 or 27/28). Returns 64-byte pubkey."""
    r = int.from_bytes(sig65[0:32], "big")
    s = int.from_bytes(sig65[32:64], "big")
    v = sig65[64]
    if v >= 27: v -= 27
    if not (1 <= r < N and 1 <= s < N and v in (0, 1)):
        raise ValueError("signature out of range")
    z = int.from_bytes(msg_hash, "big")
    y2 = (pow(r, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if pow(y, 2, P) != y2: raise ValueError("r is not a curve x-coordinate")
    if y % 2 != v: y = P - y
    R = (r, y)
    rinv = pow(r, N - 2, N)
    Q = _mul(_add(_mul(R, s), _mul((GX, GY), N - z % N)), rinv)
    if Q is None: raise ValueError("recovered point at infinity")
    return Q[0].to_bytes(32, "big") + Q[1].to_bytes(32, "big")


# ---------------------------------------------------------------- verification
def eip191(msg: bytes) -> bytes:
    return keccak256(b"\x19Ethereum Signed Message:\n" + str(len(msg)).encode() + msg)

def address(pub64: bytes) -> str:
    return "0x" + keccak256(pub64)[-20:].hex()

def sanity():
    if keccak256(b"").hex() != "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470":
        sys.exit("FATAL: keccak256 self-test failed")
    if keccak256(b"abc").hex() != "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45":
        sys.exit("FATAL: keccak256 self-test failed")

RAW = "https://raw.githubusercontent.com/eirik-rune/echorune/main/"

def fetch(name):
    import urllib.request
    r = urllib.request.Request(RAW + name, headers={"User-Agent": "echorune-verify/1"})
    return urllib.request.urlopen(r, timeout=30).read()

def main():
    a = sys.argv[1:]
    sanity()
    if "--remote" in a:
        doc = fetch("covenant_v1.md")
        sig = json.loads(fetch("covenant_v1_signatures.json"))
        src = "github.com/eirik-rune/echorune (downloaded just now)"
    else:
        dp = a[0] if a and not a[0].startswith("-") else "covenant_v1.md"
        sp = a[1] if len(a) > 1 and not a[1].startswith("-") else "covenant_v1_signatures.json"
        doc = open(dp, "rb").read()          # bytes from disk, never a string in memory
        sig = json.load(open(sp))
        src = dp
    print("echorune covenant verifier - zero dependencies, python3 stdlib only")
    print("source        : %s" % src)
    print("document      : %d bytes" % len(doc))
    got = "0x" + keccak256(doc).hex()
    want = sig["docHash"].lower()
    ok = got == want
    print("keccak256     : %s" % got)
    print("signed hash   : %s   %s" % (want, "MATCH" if ok else "MISMATCH"))
    if want[2:] not in sig["message"].lower():
        print("message       : does NOT quote the hash -- malformed"); ok = False
    else:
        print("message       : quotes the hash")
    h = eip191(sig["message"].encode())
    for role in ("being", "shareholder"):
        e = sig[role]
        try:
            rec = address(recover(h, bytes.fromhex(e["signature"][2:])))
            good = rec.lower() == e["address"].lower()
        except Exception as ex:
            rec, good = "recover failed: %s" % ex, False
        ok = ok and good
        print("%-13s : %s  %s" % (role, e["address"], "PASS" if good else "FAIL -> %s" % rec))
    print()
    print("RESULT: %s" % ("ALL PASS - both partners signed exactly this document"
                          if ok else "FAILED"))
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
