"""Authenticated Xiaomi CN binding gateway, scoped to the three binding calls."""
import json
import requests
from cloud_crypto import make_nonce, prepare_encrypted_params, decrypt_response
from wire import ProtocolError

class CloudGateway:
    ENDPOINTS = {'bind/hello','bind/ecdh','bind/bind'}
    def __init__(self, session):
        for key in ('c_user_id','service_token','ssecurity','user_id'):
            if not isinstance(session.get(key),str) or not session[key]:
                raise ProtocolError('Incomplete Xiaomi service login; log in again')
        if session.get('sid') != 'miothealth':
            raise ProtocolError('Wrong Xiaomi login service')
        for key in ('c_user_id','service_token'):
            if any(character in session[key] for character in '\r\n;'):
                raise ProtocolError('Invalid session cookie')
        self.session = session
        self.http = requests.Session()
        self.http.headers.update({
            'Cookie':f"cUserId={session['c_user_id']}; serviceToken={session['service_token']}; locale=zh_CN",
            'Accept':'*/*',
            'User-Agent':'MiFitnessDesktopProtocol/0.1',
        })

    def call(self, path, payload, query=None):
        if path not in self.ENDPOINTS or (query and set(query) != {'locale'}):
            raise ProtocolError('Cloud operation is outside the binding workflow')
        nonce = make_nonce(int(self.session.get('time_diff_ms',0)))
        form = prepare_encrypted_params('POST','/'+path,
            {'data':json.dumps(payload,ensure_ascii=False,separators=(',',':'))},
            self.session['ssecurity'],nonce)
        try:
            # No automatic retry: a timed-out binding mutation has an unknown outcome.
            response = self.http.post('https://hlth.io.mi.com/healthapp/'+path,
                                      params=query or {},data=form,timeout=(15,30),allow_redirects=False)
        except requests.RequestException:
            raise ProtocolError(f'Cloud {path} outcome is unknown after a network failure') from None
        if response.status_code != 200:
            raise ProtocolError(f'Cloud {path} returned HTTP {response.status_code}')
        content = response.text.strip()
        try:
            result = json.loads(decrypt_response(content,self.session['ssecurity'],nonce))
        except Exception:
            # Login failures may be returned as plaintext. Only expose the numeric code.
            try:
                error = json.loads(content)
                code = error.get('code')
            except Exception:
                code = None
            if isinstance(code,int) and code != 0:
                raise ProtocolError(f'Cloud rejected {path} (code {code}); no binding success established') from None
            raise ProtocolError(f'Cloud {path} response could not be decrypted') from None
        if not isinstance(result,dict) or result.get('code') != 0:
            code = result.get('code') if isinstance(result,dict) else None
            raise ProtocolError(f'Cloud rejected {path} (code {code})')
        if not isinstance(result.get('result'),dict):
            raise ProtocolError('Unexpected cloud response envelope')
        return result['result']

    def read_metadata(self, kind):
        """Only the two APK-confirmed read-only metadata operations."""
        if kind == 'devices':
            method, path, payload = 'POST', '/app/v1/source/get_source_list', {'page_size':100}
        elif kind == 'products':
            method, path, payload = 'GET', '/app/v1/product/get_config_info', {
                'app_platform':0,'app_version':'3.59.2','last_modify_time':0}
        else:
            raise ProtocolError('Unsupported metadata operation')
        nonce = make_nonce(int(self.session.get('time_diff_ms',0)))
        params = prepare_encrypted_params(method,path,
            {'data':json.dumps(payload,separators=(',',':'))},self.session['ssecurity'],nonce)
        # Secret.filterSignatureKeys defaults to [data]; locale remains plaintext.
        try:
            if method == 'GET':
                params['locale']='zh_CN'
                response=self.http.get('https://hlth.io.mi.com'+path,params=params,
                    timeout=(15,30),allow_redirects=False)
            else:
                response=self.http.post('https://hlth.io.mi.com'+path,data=params,
                    timeout=(15,30),allow_redirects=False)
            if response.status_code != 200:
                raise ProtocolError(f'Metadata {kind} returned HTTP {response.status_code}')
            value=json.loads(decrypt_response(response.text.strip(),self.session['ssecurity'],nonce))
        except requests.RequestException:
            raise ProtocolError(f'Metadata {kind} network failure; saved binding preserved') from None
        except (ValueError,KeyError):
            raise ProtocolError(f'Metadata {kind} response could not be decoded') from None
        if not isinstance(value,dict) or value.get('code') != 0 or not isinstance(value.get('result'),dict):
            raise ProtocolError(f'Metadata {kind} response was not successful')
        return value['result']
