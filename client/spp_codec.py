"""Xiaomi classic-Bluetooth SPP framing and legacy application crypto.

Recovered from com.mi.health 3.59.2: SppVersionReader, spp.b,
SppTaskQueueV1, TransportV1, CipherApiCall and tp5. The initial version
query always uses this legacy framing; versions 2/3 then select TransportV2.
Evidence/source excerpts are retained in work/spp-source and
work/spp-agent-readversion.json. This module performs no I/O.
"""
from dataclasses import dataclass
import struct
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from wire import ProtocolError

SPP_UUID = '00001101-0000-1000-8000-00805f9b34fb'
MAGIC = b'\xba\xdc\xfe'
MAX_BODY = 0x7fff  # The official parser reads the length as a signed Java short.

@dataclass(frozen=True)
class SppPacket:
    channel: int
    opcode: int
    sequence: int
    data_type: int
    payload: bytes = b''
    need_response: bool = False
    flag: int = 1

def encode_packet(packet: SppPacket) -> bytes:
    if not 0 <= packet.channel <= 15 or packet.flag not in (0,1):
        raise ProtocolError('Invalid SPP header')
    if any(not 0 <= v <= 255 for v in (packet.opcode,packet.sequence,packet.data_type)):
        raise ProtocolError('Invalid SPP byte field')
    if not isinstance(packet.payload,bytes) or len(packet.payload)+3 > MAX_BODY:
        raise ProtocolError('Invalid SPP payload size')
    header=packet.channel | (int(packet.need_response)<<14) | (packet.flag<<15)
    return (MAGIC + struct.pack('<HHBBB',header,len(packet.payload)+3,
            packet.opcode,packet.sequence,packet.data_type)+packet.payload+b'\xef')

class SppFrameReader:
    """Parse fragmented/coalesced RFCOMM reads, resynchronizing malformed frames."""
    def __init__(self):
        self.buffer=bytearray()

    def feed(self,data: bytes) -> list[SppPacket]:
        self.buffer.extend(data)
        packets=[]
        while True:
            offset=self.buffer.find(MAGIC)
            if offset<0:
                # A read can end inside the three-byte preamble.
                tail=2 if self.buffer.endswith(MAGIC[:2]) else 1 if self.buffer.endswith(MAGIC[:1]) else 0
                if tail: self.buffer[:]=self.buffer[-tail:]
                else: self.buffer.clear()
                break
            if offset: del self.buffer[:offset]
            if len(self.buffer)<7:break
            header,length=struct.unpack_from('<HH',self.buffer,3)
            if header & 0x3ff0 or not 3<=length<=MAX_BODY:
                del self.buffer[0]
                continue
            total=length+8
            if len(self.buffer)<total:break
            if self.buffer[total-1]!=0xef:
                del self.buffer[0]
                continue
            packets.append(SppPacket(header&15,self.buffer[7],self.buffer[8],
                self.buffer[9],bytes(self.buffer[10:total-1]),bool(header&0x4000),(header>>15)&1))
            del self.buffer[:total]
        return packets

def version_query(sequence: int = 1) -> bytes:
    return encode_packet(SppPacket(0,0,sequence,0,need_response=True))

def parse_version(packet: SppPacket) -> tuple[int,...]:
    if packet.channel!=0 or not packet.payload:
        raise ProtocolError('Not an SPP version response')
    # Real version bytes are positive; rejecting signed values avoids making an
    # unsupported transport selection from malformed or unrelated payloads.
    if len(packet.payload)>16 or any(x>127 for x in packet.payload):
        raise ProtocolError('Invalid SPP version bytes')
    return tuple(packet.payload)

def application_packet(command: bytes, sequence: int, encrypted: bool = False) -> bytes:
    # API type100 auth -> channel2/dataType2; type101 normal -> channel2/dataType1.
    # Caller supplies ciphertext when encrypted=True; this function does not encrypt.
    return encode_packet(SppPacket(2,2,sequence,1 if encrypted else 2,command))

def response_ack(packet: SppPacket) -> bytes:
    if packet.opcode not in (0,2,4):
        raise ProtocolError('SPP response requested for unsupported opcode')
    return encode_packet(SppPacket(packet.channel,packet.opcode+1,packet.sequence,0,flag=0))

class SppV1Cipher:
    """Official type101 SPP V1 AES-CCM, including asymmetric counter framing."""
    def __init__(self,device_key: bytes,app_key: bytes,device_iv: bytes,app_iv: bytes):
        if len(device_key)!=16 or len(app_key)!=16 or len(device_iv)!=4 or len(app_iv)!=4:
            raise ProtocolError('Invalid SPP session key/IV sizes')
        self._read=AESCCM(device_key,tag_length=4)
        self._write=AESCCM(app_key,tag_length=4)
        self._device_iv=device_iv
        self._app_iv=app_iv
        self.counter=0

    def encrypt(self,plaintext: bytes) -> bytes:
        if self.counter>=0xffffffff:
            raise ProtocolError('SPP session counter exhausted; reconnect required')
        self.counter+=1
        nonce=self._app_iv+bytes(4)+struct.pack('<I',self.counter)
        return struct.pack('<H',self.counter&0xffff)+self._write.encrypt(nonce,plaintext,None)

    def decrypt(self,ciphertext: bytes) -> bytes:
        try:
            return self._read.decrypt(self._device_iv+bytes(8),ciphertext,None)
        except Exception:
            raise ProtocolError('SPP message authentication failed') from None
