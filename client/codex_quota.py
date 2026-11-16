"""Display the local Codex account's rate limits and balance on the band."""
import argparse
import asyncio
from datetime import datetime
import hmac
import json
import math
from pathlib import Path
import re
import shutil

from authentication import authenticate
from client import bluetooth_address, saved_connection
from quickapps import SESSION, TARGETS, QuickAppTransport, read_apps, select_app
from secure_store import load
from wire import ProtocolError, blob, nested, number, text

PACKAGE = TARGETS["codex-quota"].package
WINDOWS = (300, 10080)


def watch_snapshot(result):
    primary = result.get("rateLimits") or {}
    codex = (result.get("rateLimitsByLimitId") or {}).get("codex") or primary
    windows = []
    for key in ("primary", "secondary"):
        source = codex.get(key)
        if not isinstance(source, dict) or source.get("windowDurationMins") not in WINDOWS:
            continue
        used = source.get("usedPercent")
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used):
            continue
        reset = ""
        if source.get("resetsAt") is not None:
            try:
                reset = datetime.fromtimestamp(source["resetsAt"]).astimezone().strftime("%m/%d %H:%M")
            except (TypeError, ValueError, OSError, OverflowError):
                pass
        windows.append({"minutes": source["windowDurationMins"],
                        "remaining": min(100, max(0, 100-used)), "reset": reset})

    credit_source = codex.get("credits")
    if credit_source is None:
        credit_source = primary.get("credits")
    credits = None
    if isinstance(credit_source, dict):
        balance = credit_source.get("balance")
        match = re.fullmatch(r"(-?[0-9]+)(?:\.[0-9]+)?", str(balance).strip())
        credits = {"balance": str(int(match[1])) if match else None,
                   "unlimited": credit_source.get("unlimited") is True}
    return {"op": "quota", "windows": windows, "credits": credits}


class LocalCodex:
    def __init__(self):
        self.process = None
        self.request_id = 0

    async def start(self):
        command = shutil.which("codex")
        if not command:
            raise RuntimeError("Install Codex CLI and sign in on this Windows account first")
        self.process = await asyncio.create_subprocess_exec(
            command, "app-server", "--listen", "stdio://",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=1024 * 1024,
        )
        await self._call("initialize", {"clientInfo": {
            "name": "openband_quota", "title": "Openband Quota", "version": "0.6.0",
        }})
        await self._send({"method": "initialized", "params": {}})

    async def _send(self, message):
        self.process.stdin.write((json.dumps(message)+"\n").encode("utf-8"))
        await self.process.stdin.drain()

    async def _call(self, method, params=None):
        self.request_id += 1
        message = {"id": self.request_id, "method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)
        async with asyncio.timeout(20):
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    raise RuntimeError("Codex app-server stopped")
                response = json.loads(line)
                if response.get("id") == message["id"]:
                    if response.get("error") or not isinstance(response.get("result"), dict):
                        raise RuntimeError("Codex app-server did not return a result")
                    return response["result"]

    async def quota(self):
        return watch_snapshot(await self._call("account/rateLimits/read"))

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()


class QuotaBridge:
    def __init__(self, band, reader, identity):
        self.band = band
        self.reader = reader
        self.fingerprint = bytes.fromhex(identity["fingerprint"])
        self.basic = text(1, PACKAGE) + blob(2, self.fingerprint)

    def matches(self, basic):
        fingerprint = basic.get(2)
        return (basic.get(1) == PACKAGE.encode("utf-8") and isinstance(fingerprint, bytes)
                and hmac.compare_digest(fingerprint, self.fingerprint))

    async def send_ready(self):
        status = blob(1, self.basic) + number(2, 1)
        await self.band.send_application(number(1, 20) + number(2, 7) + blob(22, blob(8, status)),
                                         encrypted=True)

    async def send_quota(self):
        try:
            reply = await self.reader.quota()
        except (ValueError, RuntimeError, OSError, TimeoutError):
            reply = {"op": "error", "message": "读取额度失败"}
        data = json.dumps(reply, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        body = blob(1, self.basic) + blob(2, data)
        await self.band.send_application(number(1, 20) + number(2, 8) + blob(22, blob(9, body)),
                                         encrypted=True)
        print("Quota snapshot sent" if reply["op"] == "quota" else "Quota unavailable", flush=True)

    async def dispatch(self, packet):
        if packet.get(1) != 20:
            return
        data = nested(packet, 22)
        if packet.get(2) == 6 and self.matches(nested(data, 5)):
            await self.send_ready()
            await self.send_quota()
        elif packet.get(2) == 9:
            request = nested(data, 9)
            raw = request.get(2)
            if not self.matches(nested(request, 1)) or not isinstance(raw, bytes) or len(raw) > 1024:
                return
            try:
                message = json.loads(raw)
            except (ValueError, UnicodeError):
                return
            if isinstance(message, dict) and message.get("op") == "quota":
                await self.send_quota()

    async def run(self):
        await self.send_ready()
        print("Connected. Open Codex on the band.", flush=True)
        while True:
            packet = await self.band.responses.get()
            if isinstance(packet, Exception):
                raise packet
            await self.dispatch(packet)


async def serve(args):
    connection = saved_connection(load(args.session), args.address)
    reader = LocalCodex()
    try:
        await reader.start()
        while True:
            try:
                async with QuickAppTransport(args.address) as band:
                    if band.legacy:
                        raise ValueError("The quota app requires an SPP V2 session")
                    await authenticate(band, bytes.fromhex(connection["connection_key_hex"]))
                    identity = select_app(await read_apps(band), PACKAGE)
                    if not identity or not isinstance(identity["version"], int) or identity["version"] < 8:
                        raise ValueError("Install the Codex quota Quick App before running the bridge")
                    await QuotaBridge(band, reader, identity).run()
            except (ProtocolError, OSError, TimeoutError) as error:
                print(f"Band connection unavailable ({type(error).__name__}). Retrying in 10 s.", flush=True)
                await asyncio.sleep(10)
    finally:
        await reader.close()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--address", required=True, type=bluetooth_address)
    cli.add_argument("--session", type=Path, default=SESSION)
    try:
        asyncio.run(serve(cli.parse_args()))
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, RuntimeError) as error:
        cli.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
