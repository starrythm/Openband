"""Store a Xiaomi service session using Windows current-user DPAPI."""
import base64
import ctypes
import json
import os
from pathlib import Path

class Blob(ctypes.Structure):
    _fields_ = [('size', ctypes.c_uint32), ('data', ctypes.POINTER(ctypes.c_ubyte))]

def _crypt(raw, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('This session store requires Windows DPAPI')
    source_buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    destination = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    if decrypt:
        success = library.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination))
    else:
        success = library.CryptProtectData(ctypes.byref(source), 'Mi Fitness desktop pairing session', None, None, None, 1, ctypes.byref(destination))
    if not success:
        raise RuntimeError('Windows could not protect/unprotect this session')
    try:
        return ctypes.string_at(destination.data, destination.size)
    finally:
        kernel = ctypes.WinDLL('kernel32')
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(destination.data, ctypes.c_void_p))

def save(path, value):
    encrypted = _crypt(json.dumps(value).encode('utf-8'))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.new')
    temporary.write_text(json.dumps({'version':1,'protection':'Windows current-user DPAPI',
                                     'payload':base64.b64encode(encrypted).decode('ascii')}),encoding='utf-8')
    temporary.replace(target)

def load(path):
    envelope = json.loads(Path(path).read_text(encoding='utf-8'))
    if envelope.get('version') != 1:
        raise RuntimeError('Unknown session format')
    return json.loads(_crypt(base64.b64decode(envelope['payload']), decrypt=True))

if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3 or sys.argv[1] not in ('save','helper-read'):
        raise SystemExit('Usage: secure_store.py save FILE (JSON on stdin)')
    if sys.argv[1] == 'save':
        save(sys.argv[2], json.load(sys.stdin))
        print('Session saved with Windows DPAPI')
    else:
        # Private IPC to login_helper.cjs; its stdout is captured, never logged.
        print(json.dumps(load(sys.argv[2])))
