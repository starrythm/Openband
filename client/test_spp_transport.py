import asyncio,hashlib,hmac,unittest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from spp_transport import SppTransport
from spp_codec import SppFrameReader,SppPacket,encode_packet
from authentication import authenticate,notify_test
from wire import parse,nested,auth_command,blob,number,ProtocolError

class FakeBandStream:
    def __init__(self,key):
        self.key=key;self.queue=asyncio.Queue();self.reader=SppFrameReader();self.messages=[];self.confirmed=False;self.closed=False
    async def connect(self):pass
    async def receive(self):return await self.queue.get()
    def close(self):self.closed=True
    async def send(self,data):
        for packet in self.reader.feed(data):
            if packet.channel==0:
                reply=encode_packet(SppPacket(0,1,packet.sequence,0,b'\x01\x00\x00',flag=0))
                # Exercise partial socket reads during version negotiation.
                await self.queue.put(reply[:4]);await self.queue.put(reply[4:]);continue
            if packet.data_type==2:
                command=parse(packet.payload)
                if command[2]==26:
                    app_nonce=nested(nested(command,3),30)[1];device_nonce=b'd'*16
                    self.material=HKDF(algorithm=hashes.SHA256(),length=64,salt=app_nonce+device_nonce,info=b'miwear-auth').derive(self.key)
                    signature=hmac.new(self.material[:16],device_nonce+app_nonce,hashlib.sha256).digest()
                    self.expected_signature=hmac.new(self.material[16:32],app_nonce+device_nonce,hashlib.sha256).digest()
                    reply=auth_command(26,31,blob(1,device_nonce)+blob(2,signature))
                else:
                    body=nested(nested(command,3),32)
                    if not hmac.compare_digest(body[1],self.expected_signature):raise AssertionError('Wrong app signature')
                    companion=AESCCM(self.material[16:32],tag_length=4).decrypt(self.material[36:40]+bytes(8),body[2],None)
                    if parse(companion)[1]!=0:raise AssertionError('Unexpected companion platform')
                    self.confirmed=True
                    reply=auth_command(27,33,number(1,1))
                await self.queue.put(encode_packet(SppPacket(2,2,packet.sequence,2,reply)))
            else:
                if not self.confirmed:raise AssertionError('Notification before authentication')
                counter=int.from_bytes(packet.payload[:2],'little')
                nonce=self.material[36:40]+bytes(4)+counter.to_bytes(4,'little')
                clear=AESCCM(self.material[16:32],tag_length=4).decrypt(nonce,packet.payload[2:],None)
                self.messages.append(parse(clear))

class SppIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_version_authentication_then_encrypted_notification(self):
        key=b'k'*16;band=SppTransport('test');stream=FakeBandStream(key);band.stream=stream
        async with band:
            self.assertTrue(band.legacy)
            await authenticate(band,key)
            await notify_test(band)
            self.assertTrue(stream.confirmed)
            self.assertEqual(stream.messages[0][1],7)
        self.assertTrue(stream.closed)
    async def test_wrong_binding_key_does_not_send_notification(self):
        band=SppTransport('test');stream=FakeBandStream(b'n'*16);band.stream=stream
        async with band:
            with self.assertRaises(ProtocolError):await authenticate(band,b'b'*16)
            self.assertFalse(stream.confirmed)
            self.assertFalse(stream.messages)
