"""Extract the reference o66 watchface from a local, verified 3.1.16 OTA."""
import argparse
import hashlib
import json
import struct
import zipfile
from pathlib import Path

OTA_SHA256 = '435fd32b5a23e4ed81f712a7047fdcd4a4577fdfffa7a9f38e0d8bac7a6470d9'


def aligned(offset):
    return (offset + 15) & ~15


def read_romfs(data, components):
    if not data.startswith(b'-rom1fs-'):
        raise ValueError('Expected a ROMFS image')
    limit = struct.unpack_from('>I', data, 8)[0]
    if not 16 < limit <= len(data):
        raise ValueError('Invalid ROMFS image size')
    offset = aligned(data.index(b'\0', 16, limit) + 1)
    seen = set()
    for index, name in enumerate(components):
        while offset:
            if offset in seen or offset + 16 > limit:
                raise ValueError('Invalid ROMFS entry chain')
            seen.add(offset)
            nxt, child, size, _ = struct.unpack_from('>4I', data, offset)
            end = data.index(b'\0', offset + 16, limit)
            if data[offset + 16:end].decode() == name:
                kind = nxt & 7
                if index == len(components) - 1 and kind == 2:
                    start = aligned(end + 1)
                    if start + size > limit:
                        raise ValueError('ROMFS file exceeds image')
                    return data[start:start + size]
                if kind != 1:
                    raise ValueError(f'Unexpected ROMFS entry type for {name}')
                offset = child
                break
            offset = nxt & ~15
        else:
            raise ValueError(f'Missing ROMFS entry {name}')
    raise ValueError('Expected a ROMFS file')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ota', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    with args.ota.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != OTA_SHA256:
            parser.error('OTA SHA-256 differs from the reviewed 3.1.16 archive')
        with zipfile.ZipFile(source) as ota:
            metadata = json.loads(ota.read('ota.json'))
            image = ota.read('watchface.bin')
    section, = [item for item in metadata['sections'] if item['location_path'] == 'watchface.bin']
    if hashlib.md5(image).hexdigest() != section['md5sum'].lower():
        parser.error('Watchface partition differs from the OTA manifest')
    face = read_romfs(image, ('120917353507', 'resource.bin'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(face)
    print(f'{args.output} ({len(face)} bytes)')


if __name__ == '__main__':
    main()
