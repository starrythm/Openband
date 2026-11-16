"""Install the repository's Vela Quick Apps over an existing Windows bond."""
import argparse
import asyncio
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import struct
from zipfile import BadZipFile, ZipFile
import zlib

from authentication import authenticate
from client import bluetooth_address, saved_connection
from secure_store import load
from spp_transport import SppTransport
from watchfaces import send_mass_part, wait_reply
from windows_spp import RfcommStream
from wire import ProtocolError, blob, frame, nested, number, parse, read_varint, text

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / ".state/session.dpapi.json"


@dataclass(frozen=True)
class Target:
    package: str
    max_bytes: int
    bytecode: bool = False


TARGETS = {
    "lampwings": Target("com.codex.lampwings", 3_850_000, bytecode=True),
    "codex-quota": Target("com.codex.bandviewer", 2_000_000),
}


class QuickAppTransport(SppTransport):
    """Keep control-channel reads separate from unsolicited binary streams."""

    def __init__(self, address):
        super().__init__(address)
        self.stream = RfcommStream(address, self.log, allow_new_pairing=False)

    async def _pump(self):
        try:
            while True:
                kind, seq, payload = await self.raw_queue.get()
                if kind == 2:
                    if not payload or payload[0] != 2:
                        raise ProtocolError("Unexpected SPP V2 negotiation response")
                    self.session_ready.set()
                elif kind == 1:
                    self.pending_frames.pop(seq, None)
                elif kind == 0:
                    if seq not in self.pending_frames or seq in self.resends:
                        raise ProtocolError("Unavailable frame retransmission")
                    self.resends.add(seq)
                    await self._write(self.pending_frames[seq])
                elif kind == 3:
                    await self._write(frame(1, seq))
                    if len(payload) < 2 or payload[0] & 15 != 1:
                        continue
                    if payload[1] == 2 and self.decryption_key:
                        data = self.crypt(self.decryption_key, payload[2:])
                    elif payload[1] == 1:
                        data = payload[2:]
                    else:
                        raise ProtocolError("Unexpected Quick App channel encoding")
                    self.last_received = parse(data)
                    self.responses.put_nowait(self.last_received)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.responses.put_nowait(error)


def _app_entries(data):
    offset = 0
    while offset < len(data):
        key, offset = read_varint(data, offset)
        field, codec = key >> 3, key & 7
        if field == 0:
            raise ProtocolError("Invalid app list field")
        if codec == 0:
            _, offset = read_varint(data, offset)
        elif codec == 2:
            length, offset = read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ProtocolError("Truncated app list entry")
            if field == 1:
                yield parse(data[offset:end])
            offset = end
        elif codec in (1, 5):
            offset += 8 if codec == 1 else 4
            if offset > len(data):
                raise ProtocolError("Truncated app list field")
        else:
            raise ProtocolError("Unexpected app list wire type")


async def read_apps(band):
    await band.send_application(number(1, 20) + number(2, 0), encrypted=True)
    response = await wait_reply(band, 20, 0)
    raw = nested(response, 22).get(1, b"")
    if not isinstance(raw, bytes):
        raise ProtocolError("Malformed app list")
    apps = []
    for item in _app_entries(raw):
        package, fingerprint = item.get(1), item.get(2)
        if not isinstance(package, bytes) or not isinstance(fingerprint, bytes) or not fingerprint:
            raise ProtocolError("Incomplete installed app identity")
        apps.append({"package": package.decode("utf-8"), "fingerprint": fingerprint.hex(),
                     "version": item.get(3), "name": item.get(5, b"").decode("utf-8")})
    return apps


def select_app(apps, package):
    found = [entry for entry in apps if entry["package"] == package]
    if len(found) > 1:
        raise ProtocolError("Multiple apps have the requested package ID")
    return found[0] if found else None


def state_file(package):
    return ROOT / ".state" / "apps" / f"{package}.json"


def remember(address, entry):
    path = state_file(entry["package"])
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".new")
    pending.write_text(json.dumps({"address": address, **entry}, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    pending.replace(path)


def read_rpk(app):
    target = TARGETS[app]
    watch = ROOT / "apps" / app / "watch"
    source = json.loads((watch / "src/manifest.json").read_text(encoding="utf-8"))
    path = watch / "dist" / f"{target.package}.debug.{source['versionName']}.rpk"
    if not 0 < path.stat().st_size <= target.max_bytes:
        raise ProtocolError("RPK is empty or exceeds this app's configured transfer budget")
    data = path.read_bytes()
    with ZipFile(BytesIO(data)) as zip_file:
        manifest = json.loads(zip_file.read("manifest.json"))
        if (manifest.get("package"), manifest.get("versionCode")) != (target.package, source["versionCode"]):
            raise ProtocolError("RPK manifest does not match the selected app")
        if target.bytecode and "pages/index/index.jsc" not in zip_file.namelist():
            raise ProtocolError("The video app must be built with Vela bytecode enabled")
        if zip_file.testzip() is not None:
            raise ProtocolError("RPK data failed CRC validation")
    return data, manifest["versionCode"]


async def install(band, address, app, update):
    package = TARGETS[app].package
    data, version = read_rpk(app)
    current = select_app(await read_apps(band), package)
    if current:
        if not update or not state_file(package).is_file():
            raise ProtocolError("App already exists. Record its identity, then use --update")
        saved = json.loads(state_file(package).read_text(encoding="utf-8"))
        if (saved != {"address": address, **current}
                or not isinstance(current.get("version"), int)
                or current["version"] >= version):
            raise ProtocolError("Update identity or version check failed")

    request = text(1, package) + number(2, version) + number(3, len(data))
    await band.send_application(number(1, 20) + number(2, 1) + blob(22, blob(2, request)), encrypted=True)
    prepared = nested(nested(await wait_reply(band, 20, 1), 22), 3)
    if prepared.get(1) != 0:
        raise ProtocolError(f"Quick App preparation failed: {prepared.get(1)}")

    digest = hashlib.md5(data).digest()
    transfer = number(1, 64) + blob(2, digest) + number(3, len(data))
    await band.send_application(number(1, 22) + number(2, 0) + blob(24, blob(1, transfer)), encrypted=True)
    accepted = nested(nested(await wait_reply(band, 22, 0), 24), 2)
    fragment_size = accepted.get(5, 0)
    if (accepted.get(1) != digest or accepted.get(2) != 0
            or accepted.get(4, 0) != 0 or not 16 <= fragment_size <= 65535):
        raise ProtocolError("MASS setup failed or returned an unexpected offset")

    body = b"\x00\x40" + digest + struct.pack("<I", len(data)) + data
    body += struct.pack("<I", zlib.crc32(body))
    stride = fragment_size - 6
    total = (len(body) + stride - 1) // stride
    if not 1 <= total <= 65535:
        raise ProtocolError("Unexpected fragment count")
    print(f"Transferring {len(data):,} bytes in {total} fragments", flush=True)
    for index, offset in enumerate(range(0, len(body), stride), start=1):
        await send_mass_part(band, total, index, body[offset:offset+stride])
    result = nested(nested(await wait_reply(band, 20, 2, timeout=40), 22), 4)
    if result.get(1) != 0:
        raise ProtocolError(f"Quick App installation failed: {result.get(1)}")
    installed = select_app(await read_apps(band), package)
    if not installed or installed["version"] != version:
        raise ProtocolError("Expected Quick App version was not found on readback")
    remember(address, installed)
    return installed


async def run(args):
    connection = saved_connection(load(args.session), args.address)
    async with QuickAppTransport(args.address) as band:
        if band.legacy:
            raise ProtocolError("Quick Apps require SPP V2 on this device")
        await authenticate(band, bytes.fromhex(connection["connection_key_hex"]))
        if args.command == "install":
            entry = await install(band, args.address, args.app, args.update)
        else:
            entry = await read_apps(band)
            if args.command == "remember":
                entry = select_app(entry, TARGETS[args.app].package)
                if not entry:
                    raise ProtocolError("The selected app is not installed")
                remember(args.address, entry)
        print(json.dumps(entry, indent=2, ensure_ascii=False))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--address", required=True, type=bluetooth_address)
    cli.add_argument("--session", type=Path, default=SESSION)
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    commands.add_parser("remember").add_argument("app", choices=TARGETS)
    deploy = commands.add_parser("install")
    deploy.add_argument("app", choices=TARGETS)
    deploy.add_argument("--update", action="store_true")
    try:
        asyncio.run(run(cli.parse_args()))
    except (ProtocolError, OSError, ValueError, RuntimeError, BadZipFile) as error:
        cli.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
