"""Read, install, or select a native watchface over an authenticated SPP V2 link."""
import argparse
import asyncio
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

from authentication import authenticate
from client import bluetooth_address, log, saved_connection
from secure_store import load
from spp_transport import SppTransport
from wire import ProtocolError, blob, frame, nested, number, parse, read_varint, text

ROOT = Path(__file__).resolve().parents[1]
PREPARE_STATUS = {1: 'busy', 2: 'already installed', 3: 'low storage',
                  4: 'low battery', 5: 'downgrade', 6: 'unsupported', 7: 'face limit'}


async def wait_reply(band, kind, subtype, timeout=20):
    async with asyncio.timeout(timeout):
        while True:
            reply = await band.responses.get()
            if isinstance(reply, Exception):
                raise reply
            if (reply.get(1), reply.get(2)) == (kind, subtype):
                if reply.get(100, 0):
                    raise ProtocolError(f'Device error {reply[100]} for {kind}/{subtype}')
                return reply


async def read_faces(band):
    await band.send_application(number(1, 4) + number(2, 0), encrypted=True)
    data = nested(await wait_reply(band, 4, 0), 6).get(1)
    if not isinstance(data, bytes):
        raise ProtocolError('Missing watchface list')
    faces = []
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        if tag != 10:
            raise ProtocolError('Unexpected watchface list field')
        size, offset = read_varint(data, offset)
        end = offset + size
        if end > len(data):
            raise ProtocolError('Truncated watchface list item')
        item = parse(data[offset:end])
        if not isinstance(item.get(1), bytes):
            raise ProtocolError('Missing watchface ID')
        faces.append({'id': item[1].decode(), 'name': item.get(2, b'').decode(),
                      'current': item.get(3) == 1, 'removable': item.get(4) == 1})
        offset = end
    return faces


async def select(band, face_id):
    await band.send_application(number(1, 4) + number(2, 1) + blob(6, text(2, face_id)),
                                encrypted=True)
    if nested(await wait_reply(band, 4, 1), 6).get(4) != 1:
        raise ProtocolError('Device did not acknowledge watchface selection')
    for _ in range(5):
        faces = await read_faces(band)
        if [item['id'] for item in faces if item['current']] == [face_id]:
            return faces
        await asyncio.sleep(0.5)
    raise ProtocolError('Watchface was not current on readback')


async def send_mass_part(band, total, part, data):
    seq = band.seq
    band.seq = (seq + 1) & 255
    payload = b'\x02\x01' + struct.pack('<HH', total, part) + data
    packet = frame(3, seq, payload)
    band.pending_frames[seq] = packet
    band.resends.discard(seq)
    await band._write(packet)
    async with asyncio.timeout(8):
        while seq in band.pending_frames:
            await asyncio.sleep(0.02)


async def install(band, package):
    data = package.read_bytes()
    if not 1000 < len(data) < 2_000_000 or data[:4] != bytes.fromhex('5aa53412'):
        raise ProtocolError('Invalid o66 watchface header or package size')
    face_id = data[0x28:0x31].split(b'\0', 1)[0]
    if not re.fullmatch(rb'[0-9]{1,9}', face_id):
        raise ProtocolError('Invalid numeric watchface ID in package header')
    ident = face_id.decode()
    before = await read_faces(band)
    active = [item['id'] for item in before if item['current']]
    if len(active) != 1:
        raise ProtocolError('Cannot identify the original current watchface')
    if any(item['id'] == ident for item in before):
        raise ProtocolError('Watchface ID is already installed')

    request = text(1, ident) + number(2, len(data)) + number(3, 65536)
    await band.send_application(number(1, 4) + number(2, 4) + blob(6, blob(6, request)),
                                encrypted=True)
    prep = nested(await wait_reply(band, 4, 4), 6)
    if 5 in prep:
        status = prep[5]
    else:
        detail = nested(prep, 9)
        if detail.get(1) != face_id:
            raise ProtocolError('Prepare reply watchface ID mismatch')
        status = detail.get(2)
    if status != 0:
        raise ProtocolError(f'Watchface preparation rejected: {PREPARE_STATUS.get(status, status)}')

    digest = hashlib.md5(data).digest()
    body = b'\x00\x10' + digest + struct.pack('<I', len(data)) + data
    body += struct.pack('<I', zlib.crc32(body))
    request = number(1, 16) + blob(2, digest) + number(3, len(data))
    await band.send_application(number(1, 22) + number(2, 0) + blob(24, blob(1, request)),
                                encrypted=True)
    reply = nested(nested(await wait_reply(band, 22, 0), 24), 2)
    if reply.get(1) != digest or reply.get(2) != 0:
        raise ProtocolError('MASS preparation rejected')
    fragment_size = reply.get(5, 0)
    if not 16 <= fragment_size <= 65535 or reply.get(4, 0) != 0:
        raise ProtocolError('Unexpected MASS fragment size or previous transfer')
    chunk = fragment_size - 6
    total = (len(body) + chunk - 1) // chunk
    if total > 65535:
        raise ProtocolError('Too many MASS fragments')
    log(stage='face_transfer_start', fragments=total, size=len(data))
    for i in range(total):
        await send_mass_part(band, total, i + 1, body[i * chunk:(i + 1) * chunk])

    result = nested(nested(await wait_reply(band, 4, 5, timeout=45), 6), 7)
    if result.get(1) != face_id or result.get(2) not in (2, 3):
        raise ProtocolError(f'Watchface installation rejected: {result.get(2)}')
    after = await read_faces(band)
    if sum(item['id'] == ident for item in after) != 1:
        raise ProtocolError('Installed watchface not found uniquely on readback')
    if not any(item['id'] == active[0] for item in after):
        raise ProtocolError('Previous watchface missing after installation')
    return await select(band, ident)


async def run(args):
    connection = saved_connection(load(args.session), args.address)
    async with SppTransport(args.address, log) as band:
        await authenticate(band, bytes.fromhex(connection['connection_key_hex']))
        if band.legacy:
            raise ProtocolError('This watchface client uses SPP V2')
        if args.command == 'install':
            faces = await install(band, args.package)
        elif args.command == 'select':
            faces = await select(band, args.id)
        else:
            faces = await read_faces(band)
    print(json.dumps(faces, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', required=True, type=bluetooth_address)
    parser.add_argument('--session', type=Path, default=ROOT / '.state/session.dpapi.json')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list')
    commands.add_parser('select').add_argument('id')
    commands.add_parser('install').add_argument('package', type=Path)
    try:
        asyncio.run(run(parser.parse_args()))
    except (ProtocolError, OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
