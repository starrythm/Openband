"""Post-binding authentication and one test notification.

This is separate from PSK first binding. Fields and algorithms match REA's
WearAuthV2 findings and the Freeband BLE V2 protocol documentation.
"""
import datetime
import hashlib
import hmac
import os
import struct
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from wire import ProtocolError, auth_command, blob, nested, number, required_bytes, text, varint

async def authenticate(band, key, phone_id=''):
    app_nonce = os.urandom(16)
    reply = await band.request(auth_command(26,30,blob(1,app_nonce)),26)
    challenge = nested(nested(reply,3),31)
    device_nonce = required_bytes(challenge,1)
    device_signature = required_bytes(challenge,2)
    if len(device_nonce) != 16 or len(device_signature) != 32:
        raise ProtocolError('Unexpected authentication challenge sizes')
    material = HKDF(algorithm=hashes.SHA256(),length=64,salt=app_nonce+device_nonce,
                    info=b'miwear-auth').derive(key)
    read_key, write_key = material[:16], material[16:32]
    suffix = None
    # The APK supports both an empty optional identity and a configured identity.
    for candidate in [b''] + ([phone_id.encode('utf-8')] if phone_id else []):
        expected = hmac.new(read_key,device_nonce+app_nonce+candidate,hashlib.sha256).digest()
        if hmac.compare_digest(expected,device_signature):
            suffix = candidate
            break
    if suffix is None:
        raise ProtocolError('Stored key/identity does not match the hand band challenge')
    app_signature = hmac.new(write_key,app_nonce+device_nonce+suffix,hashlib.sha256).digest()
    companion = number(1,0)+varint((2<<3)|5)+struct.pack('<f',35.0)+text(3,'Openband Windows')
    cipher = AESCCM(write_key,tag_length=4).encrypt(material[36:40]+bytes(8),companion,None)
    reply = await band.request(auth_command(27,32,blob(1,app_signature)+blob(2,cipher)),27)
    auth = nested(reply,3)
    if 3 in auth and auth[3] != 0:
        raise ProtocolError(f'Authentication rejected (code {auth[3]})')
    confirmation = nested(auth,33)
    if confirmation.get(1) != 1:
        raise ProtocolError('Device did not confirm application authentication')
    if hasattr(band,'set_session_keys'):
        band.set_session_keys(read_key,write_key,material[32:36],material[36:40])
    else:
        band.encryption_key, band.decryption_key = write_key, read_key
    band.log(stage='application_authenticated')

async def notify_test(band):
    timestamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%dT%H%M%S')
    item = (text(1,'local.openband.bandtest')+text(2,'Openband')+text(3,'电脑连接测试')
            +text(4,'')+text(5,'这是一条蓝牙测试消息')+text(6,timestamp)+number(7,1))
    command = number(1,7)+number(2,0)+blob(9,blob(3,blob(1,item)))
    await band.send_application(command,encrypted=True)
    band.log(stage='test_notification_written',display_confirmed=False)
