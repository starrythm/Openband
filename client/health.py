"""Copy available Xiaomi Band 10 activity files over an existing SPP bond."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import struct
import zlib

from authentication import authenticate
from client import bluetooth_address, saved_connection
from health_tables import make_tables
from health_upload import upload_snapshot
from secure_store import load
from spp_transport import SppTransport
from windows_spp import RfcommStream
from wire import ProtocolError, blob, frame, nested, number, parse

from activity_ref import ChunkAssembler, FormatError, kind_of, open_file, parse_file, parse_id_list

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 32 * 1024 * 1024


def report(stage, **fields):
    print(json.dumps({"stage": stage, **fields}, ensure_ascii=False), flush=True)


class HealthTransport(SppTransport):
    def __init__(self, address):
        super().__init__(address)
        self.stream = RfcommStream(address, self.log, allow_new_pairing=False)
        self.activity = asyncio.Queue()

    async def _pump(self):
        try:
            while True:
                kind, seq, payload = await self.raw_queue.get()
                if kind == 2:
                    if not payload or payload[0] != 2:
                        raise ProtocolError("Unexpected session negotiation")
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
                    if len(payload) < 2 or payload[0] & 15 not in (1, 5):
                        continue
                    channel, opcode = payload[0] & 15, payload[1]
                    if opcode == 2 and self.decryption_key:
                        data = self.crypt(self.decryption_key, payload[2:])
                    elif opcode == 1 and channel == 1:
                        data = payload[2:]
                    elif opcode == 1 and self.decryption_key:
                        data = payload[2:]
                    else:
                        continue
                    if channel == 1:
                        self.last_received = parse(data)
                        self.responses.put_nowait(self.last_received)
                    else:
                        self.activity.put_nowait(data)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.responses.put_nowait(error)
            self.activity.put_nowait(error)


def fitness_command(subtype, health=b""):
    return number(1, 8) + number(2, subtype) + (blob(10, health) if health else b"")


async def list_ids(link, subtype):
    today = blob(5, number(1, 0)) if subtype == 1 else b""
    await link.send_application(fitness_command(subtype, today), encrypted=True)
    async with asyncio.timeout(12):
        while True:
            reply = await link.responses.get()
            if isinstance(reply, Exception):
                raise reply
            if (reply.get(1), reply.get(2)) != (8, subtype):
                continue
            if reply.get(100, 0) != 0:
                raise ProtocolError(f"List command returned status {reply[100]}")
            data = nested(reply, 10).get(2, b"")
            if not isinstance(data, bytes) or len(data) % 7:
                raise ProtocolError("Invalid length of health file list")
            return parse_id_list(data)


async def request_file(link, requested, save, empty_ids):
    # The activity stream uses transport ACKs. The separate 8/5 command
    # marks a file synced on the band, so this copy flow never sends it.
    await link.send_application(fitness_command(3, blob(2, requested)), encrypted=True)
    assembler = ChunkAssembler()
    other_files = []
    timeout = 8
    async with asyncio.timeout(45):
        while True:
            try:
                chunk = await asyncio.wait_for(link.activity.get(), timeout=timeout)
            except TimeoutError:
                if other_files:
                    return other_files
                raise
            timeout = 8
            if isinstance(chunk, Exception):
                raise chunk
            if len(chunk) < 4:
                raise FormatError("Short activity chunk")
            total, index = struct.unpack_from("<HH", chunk)
            if not 1 <= index <= total or len(assembler.buf) + len(chunk) > MAX_FILE_BYTES:
                raise FormatError("Invalid activity chunk range or file size")
            data = assembler.feed(chunk)
            if data is None:
                continue
            if len(data) == 12 and zlib.crc32(data[:-4]) == int.from_bytes(data[-4:], "little"):
                # Some responses contain only the file ID, padding and CRC.
                actual = data[:7]
                empty_ids.add(actual.hex())
                if actual == requested:
                    return other_files
                other_files.append(actual.hex())
                timeout = 1
                continue
            fid, _, _, _ = open_file(data)
            actual = fid.to_bytes()
            save(actual, data)
            if actual == requested:
                return other_files
            other_files.append(actual.hex())
            timeout = 1


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def capture(address, session, output):
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    (output / "decoded").mkdir()
    result = {
        "started_at": datetime.now().astimezone().isoformat(),
        "format": "openband-health-v1",
        "source": "Xiaomi wearable over authenticated Windows SPP",
        "lists": {}, "files": {}, "errors": [], "different_returned_ids": {},
    }
    known, empty_ids = {}, set()

    def save(file_id, raw):
        key = file_id.hex()
        path = output / "raw" / f"{key}.bin"
        if path.exists() and path.read_bytes() == raw:
            return
        fid, _, _, _ = open_file(raw)
        entry = {"kind": kind_of(fid), "bytes": len(raw), "crc32_verified": True}
        path.write_bytes(raw)
        try:
            parsed = parse_file(raw)
            write_json(output / "decoded" / f"{key}.json", parsed)
            entry["decoded"] = parsed.get("data") is not None
        except FormatError as error:
            entry["decoded"] = False
            entry["parse_error"] = str(error)
        result["files"][key] = entry
        report("file_verified", **{k: entry[k] for k in ("kind", "bytes", "decoded")})

    try:
        connection = saved_connection(load(session), address)
        async with HealthTransport(address) as link:
            if link.legacy:
                raise ProtocolError("Health file streaming requires the SPP V2 framing")
            await authenticate(link, bytes.fromhex(connection["connection_key_hex"]))
            report("authenticated")
            for subtype, label in ((1, "today"), (2, "history")):
                try:
                    ids = await list_ids(link, subtype)
                    known.update((fid.to_bytes(), fid) for fid in ids)
                    counts = {"count": len(ids), "kinds": dict(Counter(kind_of(fid) for fid in ids))}
                    result["lists"][label] = {**counts, "ids": [fid.to_bytes().hex() for fid in ids]}
                    report("list_received", list=label, **counts)
                except (TimeoutError, ProtocolError) as error:
                    result["lists"][label] = {"error": str(error) or type(error).__name__}
                    report("list_error", list=label, **result["lists"][label])
            for key, _ in sorted(known.items(), key=lambda item: item[1].fetch_key()):
                if key.hex() in result["files"] or key.hex() in empty_ids:
                    continue
                try:
                    other_files = await request_file(link, key, save, empty_ids)
                    if other_files:
                        result["different_returned_ids"][key.hex()] = other_files
                except (TimeoutError, FormatError, ProtocolError) as error:
                    reason = str(error) or type(error).__name__
                    result["errors"].append({"file_id": key.hex(), "error": reason})
                    report("file_error", kind=kind_of(known[key]), error_type=type(error).__name__)
    except (OSError, ValueError, KeyError, ProtocolError, TimeoutError) as error:
        result["connection_error"] = str(error) or type(error).__name__
        report("export_error", error_type=type(error).__name__)
    finally:
        result["unique_listed_files"] = len(known)
        result["matched_listed_files"] = sum(key.hex() in result["files"] for key in known)
        result["empty_crc_verified_responses"] = sorted(empty_ids)
        result["unresolved_listed_ids"] = sorted(
            key.hex() for key in known if key.hex() not in result["files"] and key.hex() not in empty_ids
        )
        result["verified_files"] = len(result["files"])
        result["finished_at"] = datetime.now().astimezone().isoformat()
        write_json(output / "manifest.json", result)
    report("finished", listed=len(known), verified=len(result["files"]), errors=len(result["errors"]))
    return 0 if result["files"] and not result["unresolved_listed_ids"] and not result["errors"] and all(
        "count" in result["lists"].get(label, {}) for label in ("today", "history")
    ) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("capture", help="copy health files and make local CSV tables")
    get.add_argument("--address", required=True, type=bluetooth_address)
    get.add_argument("--session", type=Path, default=ROOT / ".state" / "session.dpapi.json")
    get.add_argument("--out", type=Path, help="new capture folder; default: .state/health/<timestamp>")
    tables = commands.add_parser("tables", help="rebuild CSV tables from a local capture")
    tables.add_argument("snapshot", type=Path)
    upload = commands.add_parser("upload", help="POST this capture as a ZIP to your HTTPS receiver")
    upload.add_argument("snapshot", type=Path)
    upload.add_argument("--url", required=True)
    args = parser.parse_args()
    try:
        if args.command == "capture":
            snapshot = args.out
            if snapshot is None:
                snapshot = ROOT / ".state" / "health" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            status = asyncio.run(capture(args.address, args.session, snapshot))
            if (snapshot / "manifest.json").is_file():
                report("local_export", path=str(snapshot), **make_tables(snapshot))
            return status
        if args.command == "tables":
            report("local_export", path=str(args.snapshot), **make_tables(args.snapshot))
        else:
            response = upload_snapshot(args.snapshot, args.url)
            report("upload_http_response", status=response)
        return 0
    except (RuntimeError, ValueError, OSError, ProtocolError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
