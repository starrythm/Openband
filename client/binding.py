"""PSK/OOB=3 binding flow reconstructed from the official APK.

Every cloud result must come from an authenticated Xiaomi session. This module
does not fabricate server signatures or treat a BLE transport ACK as success.
"""
import asyncio
import base64
import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from wire import ProtocolError, auth_command, blob, nested, number, parse, required_bytes, text, varint

def b64encode(value):
    # Android Base64 flags 10 == URL_SAFE | NO_WRAP (padding remains).
    return base64.urlsafe_b64encode(value).decode('ascii')

def b64decode(value):
    if not isinstance(value, str):
        raise ProtocolError('Missing base64 server field')
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)

def one_auth_payload(reply):
    auth = nested(reply, 3)
    if 3 in auth:
        raise ProtocolError(f'Hand band rejected the operation (code {auth[3]})')
    messages = [value for value in auth.values() if isinstance(value, bytes)]
    if len(messages) != 1:
        raise ProtocolError('Unexpected authentication response payload')
    return parse(messages[0])

class PskBinder:
    def __init__(self, band, cloud, session, logger=None, save_pending=None):
        self.band = band
        self.cloud = cloud
        self.session = session
        self.log = logger or (lambda **kwargs: None)
        self.save_pending = save_pending

    async def bind(self):
        info = await self.band.inspect()
        self.log(stage='binding_mode', verify_mode=info.verify_mode, oob_mode=info.oob_mode)
        if info.verify_mode != 1 or info.oob_mode != 3:
            raise ProtocolError('This client currently supports only the observed PSK/OOB=3 mode')
        if not info.model or not info.serial:
            raise ProtocolError('Incomplete device metadata')
        hello = {
            'mode':info.verify_mode, 'model':info.model,
            'mac':self.band.address, 'randomMac':self.band.address,
            'node_id':'', 'sn':info.serial, 'did':info.did,
            'random_d':b64encode(info.device_random),
            'is_support_find':False, 'phone_id':self.session['phone_id'],
        }
        self.log(stage='cloud_hello')
        result = await asyncio.to_thread(self.cloud.call, 'bind/hello', hello)
        bind_index, bind_did = result.get('bind_index'), result.get('bind_did')
        if not isinstance(bind_index, str) or not isinstance(bind_did, str):
            raise ProtocolError('Server did not return a binding session')
        server_public = b64decode(result.get('pub_s'))
        server_signature = b64decode(result.get('sign_s'))
        server_random = b64decode(result.get('random_s'))
        if not server_public or not server_signature or not server_random:
            raise ProtocolError('Server authentication material is empty')
        self.log(stage='device_verifies_server')
        request = blob(1, server_public)+blob(2, server_signature)+blob(3, server_random)
        reply = one_auth_payload(await self.band.request(auth_command(18,13,request),18))
        self.log(stage='cloud_verifies_device')
        result = await asyncio.to_thread(self.cloud.call, 'bind/ecdh', {
            'bind_index':bind_index, 'bind_did':bind_did,
            'pub_d':b64encode(required_bytes(reply,1)),
            'sign_d':b64encode(required_bytes(reply,2)),
        })
        device_key = b64decode(result.get('device_key'))
        if len(device_key) != 16:
            raise ProtocolError('Unexpected device key length')
        if self.save_pending:
            self.save_pending({'address':self.band.address, 'device_key':b64encode(device_key),
                               'did':bind_did, 'model':info.model, 'status':'not_yet_bound'})
        bind_key = result.get('bind_key')
        code = result.get('oob_code')
        if not isinstance(bind_key,str) or not isinstance(code,int) or not 0 <= code <= 999999:
            raise ProtocolError('Invalid OOB confirmation data')
        oob = f'{code:06d}'.encode('ascii')
        app_random = os.urandom(16)
        signature = hmac.new(device_key,app_random+oob,hashlib.sha256).digest()
        request = blob(1,app_random)+blob(2,signature)+blob(3,bind_key.encode('utf-8'))
        self.log(stage='awaiting_hand_band_confirmation', message='Confirm the request on your hand band')
        reply = one_auth_payload(await self.band.request(auth_command(19,15,request),19,timeout=75))
        device_random, device_signature = required_bytes(reply,1), required_bytes(reply,2)
        expected = hmac.new(device_key,device_random+oob,hashlib.sha256).digest()
        if not hmac.compare_digest(expected,device_signature):
            raise ProtocolError('Device confirmation signature did not verify')
        self.log(stage='cloud_confirms_binding')
        result = await asyncio.to_thread(self.cloud.call, 'bind/bind', {
            'bind_index':bind_index, 'bind_did':bind_did,
            'bind_sign':b64encode(required_bytes(reply,3)),
        }, {'locale':'zh_CN'})
        # BindResult.isSuccess() in this APK returns ret == 1, not ret == 0.
        if result.get('ret') != 1:
            raise ProtocolError('Server has not confirmed binding success')
        # id0: device_type=Android; OS version is a protobuf float; capabilities=0.
        companion = number(1,0)+varint((2<<3)|5)+struct.pack('<f',35.0)+text(3,'Openband Windows')
        account = text(1,str(self.session['user_id']))+blob(2,companion)
        ciphertext = AESCCM(device_key,tag_length=4).encrypt(bytes(range(0x10,0x1c)),account,b'bind-data')
        self.log(stage='device_commits_binding')
        reply = await self.band.request(auth_command(25,29,blob(1,ciphertext)),25)
        auth = nested(reply,3) if 3 in reply else {}
        if 3 in auth and auth[3] != 0:
            raise ProtocolError(f'Device did not commit binding (code {auth[3]})')
        self.log(stage='binding_completed')
        return {'address':self.band.address,'device_key':b64encode(device_key),'did':bind_did,'model':info.model}
