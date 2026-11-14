"""Offline protocol regression checks; no Bluetooth or Xiaomi account calls."""
import asyncio
import base64
import hashlib
import hmac
import struct
import unittest
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.decrepit.ciphers.algorithms import ARC4
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
import cloud_crypto
from binding import PskBinder,b64encode
from wire import BindingInfo,FrameReader,ProtocolError,auth_command,blob,crc16,frame,nested,number,parse

class WireTests(unittest.TestCase):
    def test_crc_known_check_value(self):
        self.assertEqual(crc16(b'123456789'),0xbb3d)

    def test_query_matches_recovered_field_layout(self):
        self.assertEqual(auth_command(17,11,number(1,0)).hex(),'080110111a045a020800')

    def test_fragmented_frames_and_bad_crc(self):
        packet=frame(3,4,b'\x01\x01'+auth_command(17))
        reader=FrameReader()
        self.assertEqual(reader.feed(b'noise'+packet[:6]),[])
        self.assertEqual(reader.feed(packet[6:]),[(3,4,b'\x01\x01'+auth_command(17))])
        damaged=bytearray(packet);damaged[-1]^=1
        with self.assertRaises(ProtocolError): FrameReader().feed(damaged)

    def test_truncated_proto_rejected(self):
        with self.assertRaises(ProtocolError): parse(bytes.fromhex('1a05ff'))

    def test_cloud_cipher_matches_independent_library(self):
        key=bytes(range(32));data=bytes(range(256))*5
        reference=Cipher(ARC4(key),mode=None).encryptor()
        reference.update(bytes(1024))
        cipher=cloud_crypto.RC4Stream(key,1024)
        self.assertEqual(cipher.update(data[:77])+cipher.update(data[77:]),reference.update(data))

    def test_nonce_layout(self):
        nonce=cloud_crypto.make_nonce(now_ms=600000,random_bytes=bytes(range(8)))
        self.assertEqual(base64.b64decode(nonce),bytes(range(8))+struct.pack('>I',10))

class FakeCloud:
    def __init__(self,ret=1):self.calls=[];self.ret=ret
    def call(self,path,payload,query=None):
        self.calls.append(path)
        if path=='bind/hello':
            assert payload['model']=='test.band' and payload['sn']=='TEST-SERIAL'
            return {'bind_index':'test-index','bind_did':'test-did','pub_s':b64encode(b'p'*64),
                    'sign_s':b64encode(b's'*32),'random_s':b64encode(b'r'*16)}
        if path=='bind/ecdh':
            return {'device_key':b64encode(bytes(range(16))),'bind_key':'test-bind-key','oob_code':123456}
        if path=='bind/bind':return {'ret':self.ret}
        raise AssertionError(path)

class FakeBand:
    address='00:00:00:00:00:01'
    def __init__(self,bad_signature=False):self.calls=[];self.bad_signature=bad_signature
    async def inspect(self):return BindingInfo(1,3,'test.band',self.address,'TEST-SERIAL','',b'r'*16)
    async def request(self,command,expected_subtype,timeout=20):
        self.calls.append(expected_subtype)
        if expected_subtype==18:
            return {1:1,2:18,3:blob(14,blob(1,b'd'*64)+blob(2,b's'*32))}
        if expected_subtype==19:
            data=nested(nested(parse(command),3),15)
            assert data[3]==b'test-bind-key'
            assert hmac.compare_digest(data[2],hmac.new(bytes(range(16)),data[1]+b'123456',hashlib.sha256).digest())
            random=b'n'*16
            signature=hmac.new(bytes(range(16)),random+b'123456',hashlib.sha256).digest()
            if self.bad_signature:signature=bytes(32)
            return {1:1,2:19,3:blob(16,blob(1,random)+blob(2,signature)+blob(3,b'bind-sign'))}
        if expected_subtype==25:
            payload=nested(nested(parse(command),3),29)
            clear=AESCCM(bytes(range(16)),tag_length=4).decrypt(bytes(range(0x10,0x1c)),payload[1],b'bind-data')
            assert parse(clear)[1]==b'test-user'
            return {1:1,2:25}
        raise AssertionError(expected_subtype)

class BindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_and_encrypted_account(self):
        band=FakeBand();cloud=FakeCloud()
        result=await PskBinder(band,cloud,{'user_id':'test-user','phone_id':'test-phone'}).bind()
        self.assertEqual(band.calls,[18,19,25])
        self.assertEqual(cloud.calls,['bind/hello','bind/ecdh','bind/bind'])
        self.assertEqual(result['did'],'test-did')

    async def test_bad_device_signature_never_confirms_cloud(self):
        cloud=FakeCloud();band=FakeBand(True)
        with self.assertRaises(ProtocolError):
            await PskBinder(band,cloud,{'user_id':'test-user','phone_id':'test-phone'}).bind()
        self.assertNotIn('bind/bind',cloud.calls)
        self.assertNotIn(25,band.calls)

    async def test_ret_zero_is_failure(self):
        cloud=FakeCloud(0);band=FakeBand()
        with self.assertRaises(ProtocolError):
            await PskBinder(band,cloud,{'user_id':'test-user','phone_id':'test-phone'}).bind()
        self.assertNotIn(25,band.calls)

if __name__=='__main__':unittest.main()
