import struct
import unittest
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from spp_codec import (SppPacket,SppFrameReader,SppV1Cipher,encode_packet,
                       version_query,parse_version,application_packet,response_ack)
from wire import ProtocolError

class SppCodecTests(unittest.TestCase):
    def test_official_initial_version_query(self):
        self.assertEqual(version_query(),bytes.fromhex('badcfe00c00300000100ef'))

    def test_fragmented_vector_and_coalesced_response(self):
        # Hand-written field vector: channel0, flag0, opcode1, SN1, payload1.0.0.
        raw=bytes.fromhex('badcfe00000600010100010000ef')
        reader=SppFrameReader()
        self.assertEqual(reader.feed(b'noise'+raw[:2]),[])
        self.assertEqual(reader.feed(raw[2:8]),[])
        result=reader.feed(raw[8:]+raw)
        self.assertEqual(len(result),2)
        self.assertEqual(parse_version(result[0]),(1,0,0))

    def test_invalid_header_and_trailer_resynchronize(self):
        valid=version_query()
        bad=bytearray(valid);bad[4]|=1
        broken=valid[:-1]+b'\x00'
        self.assertEqual(len(SppFrameReader().feed(bytes(bad)+broken+valid)),1)

    def test_auth_and_encrypted_application_types(self):
        reader=SppFrameReader()
        auth,normal=reader.feed(application_packet(b'abc',2)+application_packet(b'xyz',3,True))
        self.assertEqual((auth.channel,auth.opcode,auth.data_type,auth.need_response),(2,2,2,False))
        self.assertEqual(normal.data_type,1)

    def test_response_ack_does_not_request_another_ack(self):
        p=SppPacket(2,2,9,1,b'x',True)
        ack=SppFrameReader().feed(response_ack(p))[0]
        self.assertEqual((ack.opcode,ack.sequence,ack.flag,ack.need_response,ack.payload),(3,9,0,False,b''))
        with self.assertRaises(ProtocolError):response_ack(SppPacket(2,3,9,0))

    def test_ccm_counter_rollover_and_receiver_nonce(self):
        dk=bytes(range(16));ak=bytes(range(16,32));di=b'DEV!';ai=b'APP!'
        cipher=SppV1Cipher(dk,ak,di,ai)
        first=cipher.encrypt(b'notice')
        self.assertEqual(first[:2],b'\x01\x00')
        self.assertEqual(AESCCM(ak,tag_length=4).decrypt(ai+bytes(4)+b'\x01\x00\x00\x00',first[2:],None),b'notice')
        cipher.counter=0xffff
        rollover=cipher.encrypt(b'next')
        self.assertEqual(rollover[:2],b'\x00\x00')
        self.assertEqual(AESCCM(ak,tag_length=4).decrypt(ai+bytes(4)+struct.pack('<I',65536),rollover[2:],None),b'next')
        inbound=AESCCM(dk,tag_length=4).encrypt(di+bytes(8),b'reply',None)
        self.assertEqual(cipher.decrypt(inbound),b'reply')
        with self.assertRaises(ProtocolError):cipher.decrypt(inbound[:-1]+bytes([inbound[-1]^1]))

if __name__=='__main__':unittest.main()
