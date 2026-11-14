"""Minimal Xiaomi BLE V2 transport and protobuf codec.

Command fields were checked against Mi Fitness 3.59.2 with REA.
Frame layout is documented by cobanov/freeband (MIT).
No automatic Windows pairing, resetting, or account login is performed.
"""
from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass

RX = '0000005e-0000-1000-8000-00805f9b34fb'
TX = '0000005f-0000-1000-8000-00805f9b34fb'
START_SESSION = bytes.fromhex('0101030001000002020000fc03020020000402001027')

class ProtocolError(RuntimeError):
    pass

def varint(value: int) -> bytes:
    if not 0 <= value < 2**64:
        raise ValueError('Expected an unsigned 64-bit integer')
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])

def number(field: int, value: int) -> bytes:
    return varint(field << 3) + varint(value)

def blob(field: int, value: bytes) -> bytes:
    return varint((field << 3) | 2) + varint(len(value)) + value

def text(field: int, value: str) -> bytes:
    return blob(field, value.encode('utf-8'))

def read_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if position >= len(data):
            raise ProtocolError('Truncated protobuf integer')
        part = data[position]
        position += 1
        value |= (part & 127) << shift
        if part < 128:
            if value >= 2**64:
                raise ProtocolError('Oversized protobuf integer')
            return value, position
    raise ProtocolError('Invalid protobuf integer')


def parse(data: bytes) -> dict[int, int | bytes]:
    position = 0
    result = {}
    while position < len(data):
        tag, position = read_varint(data, position)
        field, wire_type = tag >> 3, tag & 7
        if field == 0:
            raise ProtocolError('Invalid protobuf field zero')
        if wire_type == 0:
            result[field], position = read_varint(data, position)
        elif wire_type == 2:
            length, position = read_varint(data, position)
            if length > len(data) - position:
                raise ProtocolError('Truncated protobuf field')
            result[field] = data[position:position+length]
            position += length
        elif wire_type in (1, 5):
            length = 8 if wire_type == 1 else 4
            if length > len(data) - position:
                raise ProtocolError('Truncated fixed-width field')
            result[field] = data[position:position+length]
            position += length
        else:
            raise ProtocolError(f'Unsupported protobuf wire type {wire_type}')
    return result

def nested(message: dict, field: int) -> dict:
    value = message.get(field)
    if not isinstance(value, bytes):
        raise ProtocolError(f'Missing message field {field}')
    return parse(value)

def required_bytes(message: dict, field: int) -> bytes:
    value = message.get(field)
    if not isinstance(value, bytes):
        raise ProtocolError(f'Missing byte field {field}')
    return value

def auth_command(subtype: int, field: int | None = None, body: bytes = b'') -> bytes:
    result = number(1, 1) + number(2, subtype)
    if field is not None:
        result += blob(3, blob(field, body))
    return result

def crc16(data: bytes) -> int:
    value = 0
    for part in data:
        value ^= part
        for _ in range(8):
            value = (value >> 1) ^ (0xa001 if value & 1 else 0)
    return value

def frame(kind: int, seq: int, data: bytes = b'') -> bytes:
    if len(data) > 65535:
        raise ProtocolError('Frame too large')
    return b'\xa5\xa5' + struct.pack('<BBHH', kind, seq, len(data), crc16(data)) + data

class FrameReader:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk: bytes):
        self.buffer.extend(chunk)
        packets = []
        while len(self.buffer) >= 2:
            if self.buffer[:2] != b'\xa5\xa5':
                del self.buffer[0]
                continue
            if len(self.buffer) < 8:
                break
            kind, seq, length, checksum = struct.unpack_from('<BBHH', self.buffer, 2)
            if kind & 15 > 3:
                del self.buffer[0]
                continue
            if len(self.buffer) < 8 + length:
                break
            payload = bytes(self.buffer[8:8+length])
            del self.buffer[:8+length]
            if crc16(payload) != checksum:
                raise ProtocolError('Frame checksum mismatch')
            packets.append((kind & 15, seq, payload))
        return packets

@dataclass
class BindingInfo:
    verify_mode: int
    oob_mode: int
    model: str
    mac: str
    serial: str
    did: str
    device_random: bytes

    @classmethod
    def from_response(cls, message):
        auth = nested(message, 3)
        if 3 in auth:
            raise ProtocolError(f'Device rejected binding query (code {auth[3]})')
        info = nested(auth, 12)
        def string(field):
            data = info.get(field, b'')
            if not isinstance(data, bytes):
                raise ProtocolError('Invalid device metadata')
            return data.decode('utf-8')
        return cls(int(info.get(1, 0)), int(info.get(5, 0)), string(4), string(3), string(2),
                   string(7), info.get(6, b''))

class BandTransport:
    def __init__(self, address: str, logger=None):
        self.address = address
        self.log = logger or (lambda **kwargs: None)
        self.seq = 0
        self.reader = FrameReader()
        self.raw_queue = asyncio.Queue()
        self.responses = asyncio.Queue()
        self.write_lock = asyncio.Lock()
        self.session_ready = asyncio.Event()
        self.client = None
        self.receiver = None
        self.pending_frames = {}
        self.resends = set()
        self.encryption_key = None
        self.decryption_key = None
        self.last_received = None

    async def __aenter__(self):
        from bleak import BleakClient, BleakScanner
        self.log(stage='ble_scanning')
        device = await BleakScanner.find_device_by_address(self.address, timeout=15)
        if device is None:
            raise ProtocolError('Hand band is not advertising; no pairing request was sent')
        self.client = BleakClient(device, timeout=25, winrt={'use_cached_services': False})
        self.log(stage='ble_device_found',address=device.address)
        try:
            self.log(stage='ble_connecting')
            await self.client.connect()
            self.log(stage='ble_connected')
            await asyncio.wait_for(self.client.start_notify(RX, self._receive), 25)
            self.receiver = asyncio.create_task(self._pump())
            await self._write(frame(2, 0, START_SESSION))
            await asyncio.wait_for(self.session_ready.wait(), 10)
            self.log(stage='message_channel_ready')
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    def _receive(self, _, value):
        try:
            for packet in self.reader.feed(bytes(value)):
                self.raw_queue.put_nowait(packet)
        except Exception as exc:
            self.responses.put_nowait(exc)

    async def _write(self, packet):
        async with self.write_lock:
            characteristic = self.client.services.get_characteristic(TX)
            if characteristic is None:
                raise ProtocolError('Xiaomi message characteristic is unavailable')
            size = characteristic.max_write_without_response_size
            for start in range(0, len(packet), size):
                await self.client.write_gatt_char(characteristic, packet[start:start+size], response=False)

    async def _pump(self):
        try:
            while True:
                kind, seq, payload = await self.raw_queue.get()
                # Record reception before attempting ACK; otherwise an ACK error hides the reply.
                self.log(stage='rx', kind=kind, sequence=seq, length=len(payload))
                if kind == 2:
                    if not payload or payload[0] != 2:
                        raise ProtocolError('Unexpected session negotiation response')
                    self.session_ready.set()
                elif kind == 1:
                    self.pending_frames.pop(seq, None)
                elif kind == 0:
                    if seq in self.pending_frames and seq not in self.resends:
                        self.resends.add(seq)
                        await self._write(self.pending_frames[seq])
                    else:
                        raise ProtocolError('Transport requested an unavailable retransmission')
                elif kind == 3:
                    if payload[:2] == b'\x01\x02' and self.decryption_key:
                        parsed = parse(self.crypt(self.decryption_key,payload[2:]))
                    elif payload[:2] != b'\x01\x01':
                        raise ProtocolError('Unexpected channel/encrypted response before binding')
                    else:
                        parsed = parse(payload[2:])
                    self.last_received = parsed
                    self.log(stage='application_rx',command_type=parsed.get(1),subtype=parsed.get(2))
                    await self._write(frame(1, seq))
                    self.responses.put_nowait(parsed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.responses.put_nowait(exc)

    @staticmethod
    def crypt(key, data):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        cipher = Cipher(algorithms.AES(key),modes.CTR(key)).encryptor()
        return cipher.update(data)+cipher.finalize()

    async def send_application(self, command, encrypted=False):
        seq = self.seq
        self.seq = (self.seq + 1) & 255
        if encrypted:
            if not self.encryption_key:
                raise ProtocolError('Authenticated channel key is missing')
            payload = b'\x01\x02'+self.crypt(self.encryption_key,command)
        else:
            payload = b'\x01\x01'+command
        packet = frame(3, seq, payload)
        self.pending_frames[seq] = packet
        self.resends.discard(seq)
        await self._write(packet)
        return seq

    async def request(self, command, expected_subtype, timeout=20, encrypted=False):
        await self.send_application(command,encrypted)
        deadline = asyncio.get_running_loop().time() + timeout
        while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
            try:
                reply = await asyncio.wait_for(self.responses.get(), remaining)
            except asyncio.TimeoutError as exc:
                raise ProtocolError(f'No application reply for command 1/{expected_subtype}; transport ACK is not success') from exc
            if isinstance(reply, Exception):
                raise reply
            if reply.get(1) == 1 and reply.get(2) == expected_subtype:
                return reply
            self.log(stage='unsolicited_response', command_type=reply.get(1), subtype=reply.get(2))
        raise ProtocolError('Response deadline exceeded')

    async def inspect(self):
        return BindingInfo.from_response(await self.request(auth_command(17, 11, number(1, 0)), 17))

    async def __aexit__(self, *_):
        if self.receiver is not None:
            self.receiver.cancel()
            await asyncio.gather(self.receiver, return_exceptions=True)
        if self.client is not None:
            try:
                await asyncio.wait_for(self.client.disconnect(), 10)
            except Exception:
                pass
