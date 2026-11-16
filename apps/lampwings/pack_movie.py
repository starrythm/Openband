"""Encode and check a full-resolution 30 fps AVI for the bounded Vela reader."""
import base64
import argparse
import json
from pathlib import Path
import statistics
import struct
import subprocess
import zlib

from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "lampwings.mp4"
TARGET = ROOT / "watch/src/common"
BLOCK = 48 * 1024
CLIP_LIMIT = 6 * 1024 * 1024
FRAME_LIMIT = 16 * 1024
PROFILES = {
    "compact": (1_940_000, ((26,.6),(27,.6),(28,.6),(29,.6),(28,.75),(31,.75))),
    "high": (3_746_000, ((12,0),(13,0),(14,0),(15,0))),
}


def chunks(data, start, end):
    while start + 8 <= end:
        tag, length = struct.unpack_from("<4sI", data, start)
        pos = start + 8
        stop = pos + length
        if stop > end:
            raise ValueError("Truncated AVI chunk")
        yield tag, pos, stop
        start = stop + (length & 1)


def frames(data):
    if data[:4] != b"RIFF" or data[8:12] != b"AVI ":
        raise ValueError("Not an AVI")
    if struct.unpack_from("<I", data, 4)[0] + 8 != len(data):
        raise ValueError("Invalid RIFF size")
    top_level = list(chunks(data, 12, len(data)))
    movi_start, movi_end = next(
        (pos, stop) for tag, pos, stop in top_level if tag == b"LIST" and data[pos:pos+4] == b"movi"
    )
    idx_start, idx_end = next((pos, stop) for tag, pos, stop in top_level if tag == b"idx1")
    images = []
    last_end = movi_start + 4
    for i in range(idx_start, idx_end, 16):
        tag, _, relative, length = struct.unpack_from("<4sIII", data, i)
        header = movi_start + relative
        start = header + 8
        end = start + length
        if (tag not in (b"00dc", b"00db") or header < last_end or end > movi_end
                or data[header:header+4] != tag or struct.unpack_from("<I", data, header+4)[0] != length
                or data[start:start+2] != b"\xff\xd8" or data[end-2:end] != b"\xff\xd9"):
            raise ValueError("Invalid MJPEG frame index")
        last_end = end + (length & 1)
        images.append((start,length))
    return images


def measure(entries):
    sizes = sorted(length for _, length in entries)
    return {"frames": len(sizes), "median_frame_bytes": round(statistics.median(sizes)),
            "p95_frame_bytes": sizes[int((len(sizes)-1)*.95)], "max_frame_bytes": max(sizes)}


def estimate_resources(data):
    return sum(len(zlib.compress(base64.b64encode(data[pos:pos+BLOCK]),6)) + 150
               for pos in range(0,len(data),BLOCK))


def align_avi(data):
    """Keep JPEG payloads untouched but align their base64 phase across frames."""
    movi_start = next(pos for tag, pos, _ in chunks(data, 12, len(data))
                      if tag == b"LIST" and data[pos:pos+4] == b"movi")
    prefix = data[:movi_start-8]
    movi = bytearray(b"movi")
    index = bytearray()
    for start, length in frames(data):
        position = movi_start + len(movi)
        if position % 3:
            padding = next(n for n in (0,2,4) if (position+8+n) % 3 == 0)
            movi.extend(b"JUNK" + struct.pack("<I",padding) + bytes(padding))
        tag = data[start-8:start-4]
        index.extend(struct.pack("<4sIII",tag,16,len(movi),length))
        movi.extend(data[start-8:start+length+(length&1)])
    aligned = bytearray(prefix)
    aligned.extend(b"LIST" + struct.pack("<I",len(movi)) + movi)
    aligned.extend(b"idx1" + struct.pack("<I",len(index)) + index)
    struct.pack_into("<I",aligned,4,len(aligned)-8)
    return bytes(aligned)


def encode_candidate(out, quality, huffman, blur):
    resize = "scale=212:520:flags=lanczos"
    if blur:
        resize += f",gblur=sigma={blur}:steps=2"
    subprocess.run([
        get_ffmpeg_exe(),"-y","-hide_banner","-loglevel","error","-i",str(SOURCE),
        "-map","0:v:0","-an","-vf",resize+",setsar=1","-r","30",
        "-c:v","mjpeg","-q:v",str(quality),"-pix_fmt","yuvj420p",
        "-huffman",huffman,"-threads","1",str(out),
    ],check=True)


def package(profile):
    clip = ROOT / "lampwings-watch.avi"
    picked = None
    resource_budget, candidates = PROFILES[profile]
    for quality, blur in candidates:
        huffman = "default"
        encode_candidate(clip,quality,huffman,blur)
        data=align_avi(clip.read_bytes())
        entries=frames(data)
        stats=measure(entries)
        projected=estimate_resources(data)
        print(f"q={quality} blur={blur}  AVI={len(data):,}  packed≈{projected:,}  p95={stats['p95_frame_bytes']:,}",flush=True)
        if (projected < resource_budget and len(data) <= CLIP_LIMIT
                and stats["max_frame_bytes"] <= FRAME_LIMIT and stats["frames"] == 900):
            picked = {"quantizer": quality, "blur":blur, "huffman":huffman, "avi_bytes":len(data),
                      "projected_resource_bytes":projected, **stats}
            break
    if picked is None:
        raise RuntimeError("The full-size film could not fit the existing RPK transfer budget")
    clip.write_bytes(data)

    target = TARGET / "media"
    target.mkdir(parents=True,exist_ok=True)
    generated=set()
    for index,pos in enumerate(range(0,len(data),BLOCK)):
        file = target / f"part-{index}.txt"
        file.write_bytes(base64.b64encode(data[pos:pos+BLOCK]))
        generated.add(file)
    for old in target.glob("part-*.txt"):
        if old not in generated:
            old.unlink()
    (TARGET/"resource-size.js").write_text(f"export const size = {len(data)}\nexport const blockBytes = {BLOCK}\n",
                                          encoding="utf-8")
    start,length=entries[30]
    (TARGET/"poster.jpg").write_bytes(data[start:start+length])
    with Image.open(TARGET/"poster.jpg") as poster:
        if poster.size != (212,520):
            raise ValueError("Poster or video dimensions changed")
        badge=poster.convert("RGB")
        icon=badge.crop((56,333,156,433)).resize((72,72),Image.Resampling.LANCZOS)
        icon.save(TARGET/"icon.png",optimize=True)
    picked["resources"]=len(generated)
    (ROOT/"encoding-report.json").write_text(
        json.dumps({"profile":profile,"target_fps":30,"dimensions":[212,520],"duration_seconds":30,
                    "film":picked},indent=2),encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile",choices=PROFILES,default="high")
    package(parser.parse_args().profile)
