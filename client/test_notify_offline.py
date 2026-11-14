"""Offline notification routing tests; no DPAPI/Bluetooth/cloud calls permitted."""
import asyncio
import copy
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import client
from wire import ProtocolError

ADDRESS='02:0A:0B:0C:0D:01'

def profile():
    # Synthetic fixture only; never read or decrypt the real session file.
    return {'sid':'miothealth','phone_id':'synthetic-client',
      'band':{'status':'bound','address':ADDRESS,'model':'fixture.band','did':'fixture-device',
        'connection':{'address':ADDRESS,'model':'fixture.band','did':'fixture-device',
          'phone_id':'synthetic-client','transport':'spp','product_type':6,
          'connection_key_hex':'00'*16}}}

class NotifyOfflineTests(unittest.IsolatedAsyncioTestCase):
    async def run_notify(self,session,expect_error=False):
        events=[];calls=[]
        class NoCloud:
            def __init__(self,*args,**kwargs):
                raise AssertionError('Notification must not instantiate cloud gateway')
        class NoBind:
            def __init__(self,*args,**kwargs):
                raise AssertionError('Notification must not bind')
        class FakeTransport:
            def __init__(self,address,logger):
                calls.append(('transport',address))
            async def __aenter__(self):return self
            async def __aexit__(self,*args):calls.append(('closed',))
        async def authenticate(band,key):
            self.assertEqual(key,bytes(16))
            calls.append(('auth',))
        async def notify(band):calls.append(('notification',))
        def no_save(*args):raise AssertionError('Notify must not rewrite session')
        modules={'secure_store':types.SimpleNamespace(load=lambda path:copy.deepcopy(session),save=no_save),
          'cloud':types.SimpleNamespace(CloudGateway=NoCloud),
          'binding':types.SimpleNamespace(PskBinder=NoBind),
          'authentication':types.SimpleNamespace(authenticate=authenticate,notify_test=notify),
          'spp_transport':types.SimpleNamespace(SppTransport=FakeTransport)}
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'synthetic-session.marker';marker.write_text('fixture')
            args=types.SimpleNamespace(command='notify',address=ADDRESS,session=str(marker),test_notification=False)
            with patch.dict('sys.modules',modules),patch.object(client,'log',lambda **v:events.append(v)), \
                 patch.object(client.asyncio,'sleep',new=AsyncMock()):
                if expect_error:
                    with self.assertRaisesRegex(ProtocolError,'explicit refresh'):
                        await client.run(args)
                else:await client.run(args)
        self.assertNotIn('00'*16,json.dumps(events),'Never log connection key')
        return calls,events

    async def test_cached_profile_works_without_cloud_credentials(self):
        session=profile();session.pop('sid')
        calls,events=await self.run_notify(session)
        self.assertEqual(calls,[('transport',ADDRESS),('auth',),('notification',),('closed',)])
        self.assertTrue(any(e.get('cloud_refresh') is False for e in events))

    async def test_expired_cloud_values_are_irrelevant(self):
        session=profile();session.update(service_token='expired',ssecurity='expired',c_user_id='expired')
        calls,_=await self.run_notify(session)
        self.assertIn(('notification',),calls)

    async def test_missing_profile_never_falls_back_to_cloud(self):
        session=profile();del session['band']['connection']
        calls,_=await self.run_notify(session,True);self.assertEqual(calls,[])

    async def test_missing_local_file_does_not_start_login(self):
        def forbidden(*args):raise AssertionError('No load/save/cloud on missing file')
        modules={'secure_store':types.SimpleNamespace(load=forbidden,save=forbidden),
                 'cloud':types.SimpleNamespace(CloudGateway=forbidden)}
        with patch.dict('sys.modules',modules),patch.object(Path,'is_file',return_value=False):
            with self.assertRaisesRegex(ProtocolError,'explicit refresh'):
                await client.run(types.SimpleNamespace(command='notify',address=ADDRESS,session='fixture',test_notification=False))

    async def test_mismatched_profile_address_is_rejected(self):
        session=profile();session['band']['connection']['address']='02:00:00:00:00:02'
        calls,_=await self.run_notify(session,True);self.assertEqual(calls,[])

    async def test_mismatched_binding_address_is_rejected(self):
        session=profile();session['band']['address']='02:00:00:00:00:02'
        calls,_=await self.run_notify(session,True);self.assertEqual(calls,[])

    async def test_invalid_profiles_cannot_send(self):
        changes=[('connection_key_hex','bad'),('transport','ble'),('product_type',5),
          ('model','another.model'),('did','another-device'),('phone_id','another-client')]
        for key,value in changes:
            with self.subTest(field=key):
                session=profile();session['band']['connection'][key]=value
                calls,_=await self.run_notify(session,True);self.assertEqual(calls,[])

    async def test_unconfirmed_binding_is_rejected(self):
        session=profile();session['band']['status']='not_yet_bound'
        calls,_=await self.run_notify(session,True);self.assertEqual(calls,[])

    async def test_missing_client_identity_is_rejected(self):
        session=profile();del session['phone_id']
        calls,_=await self.run_notify(session,True);self.assertEqual(calls,[])

    def test_profile_validation_normalizes_mac_case(self):
        session=profile()
        self.assertIs(client.saved_connection(session,ADDRESS.lower()),session['band']['connection'])

    async def test_explicit_refresh_still_uses_cloud_and_saves(self):
        session=profile();calls=[]
        class Gateway:
            def __init__(self,value):calls.append('cloud')
        def refresh(value,address,gateway):
            calls.append('refresh')
            self.assertEqual(address,ADDRESS)
            return value['band']['connection']
        def save(path,value):calls.append('save')
        class NoTransport:
            def __init__(self,*args):raise AssertionError('refresh should not open Bluetooth')
        modules={'secure_store':types.SimpleNamespace(load=lambda path:session,save=save),
          'authentication':types.SimpleNamespace(authenticate=AsyncMock(),notify_test=AsyncMock()),
          'binding':types.SimpleNamespace(PskBinder=object),
          'cloud':types.SimpleNamespace(CloudGateway=Gateway),
          'metadata':types.SimpleNamespace(refresh_connection=refresh),
          'spp_transport':types.SimpleNamespace(SppTransport=NoTransport)}
        with patch.dict('sys.modules',modules),patch.object(Path,'is_file',return_value=True), \
             patch.object(client,'log'):
            await client.run(types.SimpleNamespace(command='refresh',address=ADDRESS,session='fixture',test_notification=False))
        self.assertEqual(calls,['cloud','refresh','save'])

    async def test_explicit_bind_keeps_binding_then_refresh_then_auth_order(self):
        session=profile();session.pop('band');calls=[]
        class Gateway:
            def __init__(self,value):calls.append('cloud')
        class FakeTransport:
            def __init__(self,*args):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        class Binder:
            def __init__(self,*args):pass
            async def bind(self):
                calls.append('bind')
                value=copy.deepcopy(profile()['band']);value.pop('status');value.pop('connection')
                return value
        def refresh(value,address,gateway):
            self.assertEqual(value['band']['status'],'bound')
            calls.append('refresh')
            value['band']['connection']=profile()['band']['connection']
            return value['band']['connection']
        async def authenticate(*args):calls.append('auth')
        modules={'secure_store':types.SimpleNamespace(load=lambda path:session,save=lambda *args:None),
          'authentication':types.SimpleNamespace(authenticate=authenticate,notify_test=AsyncMock()),
          'binding':types.SimpleNamespace(PskBinder=Binder),
          'cloud':types.SimpleNamespace(CloudGateway=Gateway),
          'metadata':types.SimpleNamespace(refresh_connection=refresh),
          'spp_transport':types.SimpleNamespace(SppTransport=FakeTransport)}
        with patch.dict('sys.modules',modules),patch.object(Path,'is_file',return_value=True), \
             patch.object(client,'BandTransport',FakeTransport),patch.object(client,'log'):
            await client.run(types.SimpleNamespace(command='bind',address=ADDRESS,session='fixture',test_notification=False))
        self.assertEqual(calls,['cloud','bind','cloud','refresh','auth'])

if __name__=='__main__':unittest.main()
