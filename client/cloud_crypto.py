"""Offline Mi Fitness 3.59.2 cloud-envelope primitives; no networking or credentials IO.

Recovered from REA sources zi4.c/b, di4.a/b/c, o0l and m0l.
Important: fields in one request share a continuous RC4 stream, in sorted-key order.
This is protocol compatibility code, not a recommendation to use RC4 in new systems.
"""
from __future__ import annotations
import base64
import hashlib
import os
import struct
import time
from collections.abc import Mapping
from urllib.parse import urlsplit


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


class RC4Stream:
    """Standard RC4 KSA/PRGA, with explicit continuous state and optional drop."""
    def __init__(self, key: bytes, drop: int = 0):
        if not key:
            raise ValueError('Empty RC4 key')
        self.s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + self.s[i] + key[i % len(key)]) & 255
            self.s[i], self.s[j] = self.s[j], self.s[i]
        self.i = self.j = 0
        if drop:
            self.update(bytes(drop))

    def update(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        s = self.s
        i, j = self.i, self.j
        for pos, value in enumerate(data):
            i = (i + 1) & 255
            j = (j + s[i]) & 255
            s[i], s[j] = s[j], s[i]
            out[pos] = value ^ s[(s[i] + s[j]) & 255]
        self.i, self.j = i, j
        return bytes(out)


def make_nonce(time_diff_ms: int = 0, *, now_ms: int | None = None,
               random_bytes: bytes | None = None) -> str:
    if now_ms is None:
        now_ms = time.time_ns() // 1_000_000
    random_bytes = os.urandom(8) if random_bytes is None else random_bytes
    if len(random_bytes) != 8:
        raise ValueError('Nonce requires eight random bytes')
    minute = (now_ms + time_diff_ms) // 60_000
    return _b64(random_bytes + struct.pack('>I', minute & 0xffffffff))


def signed_nonce(security_b64: str, nonce_b64: str) -> str:
    security = base64.b64decode(security_b64, validate=True)
    nonce = base64.b64decode(nonce_b64, validate=True)
    if not security or len(nonce) != 12:
        raise ValueError('Invalid cloud session material')
    return _b64(hashlib.sha256(security + nonce).digest())


def _key_order(key: str) -> bytes:
    # Match Java String/TreeMap ordering, also for non-ASCII keys.
    return key.encode('utf-16-be', errors='surrogatepass')


def sign(method: str, path: str, params: Mapping[str, str],
         signed_nonce_b64: str) -> str:
    if not signed_nonce_b64:
        raise ValueError('Missing signed nonce')
    parts = [method.upper(), urlsplit(path).path]
    parts.extend(f'{key}={params[key]}' for key in sorted(params, key=_key_order))
    parts.append(signed_nonce_b64)
    return _b64(hashlib.sha1('&'.join(parts).encode('utf-8')).digest())


def prepare_encrypted_params(method: str, signing_path: str,
                             params: Mapping[str, str], security_b64: str,
                             nonce_b64: str | None = None) -> dict[str, str]:
    """Prepare fields for the default encrypted-response @Secret path.

    For /healthapp/bind/hello pass signing_path='/bind/hello'.
    Only filtered fields (normally {'data': json_text}) belong in params.
    Any locale URL query stays outside this map. The returned mapping already
    contains _nonce; do not add the ssecurity/signedNonce to the HTTP body.
    """
    nonce_b64 = nonce_b64 or make_nonce()
    if not signing_path.startswith('/'):
        signing_path = '/' + signing_path
    plain = {}
    for key, value in params.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError('Cloud parameters must be strings')
        if key and value:
            plain[key] = value
    sn = signed_nonce(security_b64, nonce_b64)
    plain['rc4_hash__'] = sign(method, signing_path, plain, sn)
    cipher = RC4Stream(base64.b64decode(sn), drop=1024)
    encrypted = {key: _b64(cipher.update(plain[key].encode('utf-8')))
                 for key in sorted(plain, key=_key_order)}
    encrypted['signature'] = sign(method, signing_path, encrypted, sn)
    encrypted['_nonce'] = nonce_b64
    return encrypted


def decrypt_response(content_b64: str, security_b64: str, nonce_b64: str) -> str:
    # Response starts a separate stream, rather than continuing the request stream.
    key = base64.b64decode(signed_nonce(security_b64, nonce_b64))
    return RC4Stream(key, drop=1024).update(
        base64.b64decode(content_b64, validate=True)).decode('utf-8')
