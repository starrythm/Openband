import asyncio
import hashlib
import json
import struct
import unittest
from unittest.mock import patch
import zlib

from codex_quota import PACKAGE, QuotaBridge, watch_snapshot
from quickapps import install
from wire import blob, nested, number, parse, text


def command(kind, subtype, field, payload):
    return parse(number(1, kind) + number(2, subtype) + blob(field, payload))


class FakeBand:
    def __init__(self):
        self.responses = asyncio.Queue()
        self.pending_frames = {}
        self.resends = set()
        self.seq = 0
        self.sent = []
        self.writes = []

    async def send_application(self, data, encrypted=False):
        self.sent.append((parse(data), encrypted))

    async def _write(self, frame):
        self.pending_frames.pop(frame[3])
        self.writes.append(frame)


class QuickAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_install_confirms_version_and_transfers_every_byte(self):
        band = FakeBand()
        rpk = bytes(range(96))
        digest = hashlib.md5(rpk).digest()
        movie = "com.codex.lampwings"
        installed = text(1, movie) + blob(2, b"\x05\x06") + number(3, 2) + text(5, "灯与翅膀")
        unrelated = text(1, "com.example.other") + blob(2, b"\x01") + number(3, 1)
        setup = blob(1, digest) + number(2, 0) + number(4, 0) + number(5, 48)
        for reply in [
            command(20, 0, 22, blob(1, blob(1, unrelated))),
            command(20, 1, 22, blob(3, number(1, 0))),
            command(22, 0, 24, blob(2, setup)),
            command(20, 2, 22, blob(4, number(1, 0))),
            command(20, 0, 22, blob(1, blob(1, installed) + blob(1, unrelated))),
        ]:
            band.responses.put_nowait(reply)
        with patch("quickapps.read_rpk", return_value=(rpk, 2)), patch("quickapps.remember") as remember:
            found = await install(band, "02:00:00:00:00:01", "lampwings", update=False)
        self.assertEqual(found["version"], 2)
        remember.assert_called_once_with("02:00:00:00:00:01", found)
        self.assertTrue(all(encrypted for _, encrypted in band.sent))
        body = b"".join(frame[14:] for frame in band.writes)
        self.assertEqual(body[:18], b"\x00\x40" + digest)
        self.assertEqual(body[18:22], struct.pack("<I", len(rpk)))
        self.assertEqual(body[22:-4], rpk)
        self.assertEqual(body[-4:], struct.pack("<I", zlib.crc32(body[:-4])))

    async def test_quota_push_is_scoped_to_installed_identity(self):
        snapshot = watch_snapshot({
            "rateLimits": {"credits": {"balance": "1234.87"}},
            "rateLimitsByLimitId": {"codex": {
                "primary": {"usedPercent": 32, "windowDurationMins": 300, "resetsAt": 1735689600},
                "secondary": {"usedPercent": 19, "windowDurationMins": 10080},
            }},
        })

        class Reader:
            async def quota(self):
                return snapshot

        band = FakeBand()
        bridge = QuotaBridge(band, Reader(), {"fingerprint": "aabbcc"})
        await bridge.dispatch(command(20, 6, 22, blob(5, text(1, PACKAGE) + blob(2, b"wrong"))))
        self.assertEqual(band.sent, [])
        await bridge.dispatch(command(20, 6, 22, blob(5, bridge.basic)))
        self.assertEqual([p[2] for p, _ in band.sent], [7, 8])
        message, encrypted = band.sent[-1]
        self.assertTrue(encrypted)
        reply = json.loads(nested(nested(message, 22), 9)[2])
        self.assertEqual([row["remaining"] for row in reply["windows"]], [68, 81])
        self.assertTrue(reply["windows"][0]["reset"])
        self.assertEqual(reply["credits"]["balance"], "1234")
