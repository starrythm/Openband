"""Send a saved Openband health export to an explicitly configured receiver."""
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZIP_DEFLATED, ZipFile

TABLE_FILES = (
    "每分钟记录.csv", "每日汇总.csv", "心率.csv", "压力.csv", "血氧.csv",
    "睡眠汇总.csv", "睡眠阶段.csv", "手动测量.csv", "导出统计.json",
)


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def package_capture(snapshot: Path, destination):
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if manifest.get("format") != "openband-health-v1" or not isinstance(files, dict) or not files:
        raise ValueError("This folder does not contain an Openband health capture with data")

    entries = ["manifest.json"]
    for key in sorted(files):
        if not re.fullmatch("[0-9a-f]{14}", key):
            raise ValueError("The capture manifest has an invalid health file ID")
        entries.append(f"raw/{key}.bin")
        decoded = f"decoded/{key}.json"
        if (snapshot / decoded).is_file():
            entries.append(decoded)
    entries.extend(name for name in TABLE_FILES if (snapshot / name).is_file())

    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for entry in entries:
            path = snapshot / entry
            if not path.is_file() or not path.resolve().is_relative_to(snapshot.resolve()):
                raise ValueError("A capture file is missing or points outside the snapshot")
            archive.write(path, entry)


def upload_snapshot(snapshot: Path, url: str) -> int:
    endpoint = urlsplit(url)
    if (endpoint.scheme != "https" or not endpoint.hostname
            or endpoint.username is not None or endpoint.password is not None
            or endpoint.fragment or any(ch.isspace() for ch in url)):
        raise ValueError("Supply an HTTPS URL without credentials or a fragment")

    headers = {"Content-Type": "application/zip"}
    token = os.environ.get("OPENBAND_HEALTH_TOKEN")
    if token:
        if any(not 33 <= ord(char) <= 126 for char in token):
            raise ValueError("OPENBAND_HEALTH_TOKEN contains characters not allowed in a bearer token")
        headers["Authorization"] = f"Bearer {token}"

    with TemporaryFile() as stream:
        package_capture(snapshot, stream)
        headers["Content-Length"] = str(stream.tell())
        stream.seek(0)
        request = Request(url, data=stream, headers=headers, method="POST")
        try:
            with build_opener(RejectRedirects()).open(request, timeout=60) as reply:
                if not 200 <= reply.status < 300:
                    raise RuntimeError(f"Receiver returned HTTP {reply.status}")
                return reply.status
        except HTTPError as error:
            raise RuntimeError(f"Receiver returned HTTP {error.code}") from None
        except (URLError, TimeoutError) as error:
            raise RuntimeError(f"HTTPS upload failed ({type(error).__name__})") from None
