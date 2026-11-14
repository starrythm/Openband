import copy,unittest
from metadata import select_connection,refresh_connection
from wire import ProtocolError

class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.session={'phone_id':'client','band':{'status':'bound','address':'02:0A:0B:0C:0D:01','model':'test.model','did':'target','device_key':'binding-key-preserved'}}
        self.devices={'list':[{'sid':'target','model':'test.model','detail':{'mac':'020a0b0c0d01','phone_id':'client','encrypt_key':'ab'*16}}]}
        self.products={'list':[{'model':'test.model','pd_type':7}]}
    def test_uses_normal_key_without_replacing_binding_key(self):
        class Gateway:
            def read_metadata(_,kind):return self.devices if kind=='devices' else self.products
        result=refresh_connection(self.session,self.session['band']['address'],Gateway())
        self.assertEqual(result['transport'],'spp')
        self.assertEqual(result['connection_key_hex'],'ab'*16)
        self.assertEqual(self.session['band']['device_key'],'binding-key-preserved')
    def test_rejects_changed_server_identity(self):
        for field,value in [('sid','other'),('model','other')]:
            d=copy.deepcopy(self.devices);d['list'][0][field]=value
            with self.assertRaises(ProtocolError):select_connection(self.session,self.session['band']['address'],d,self.products)
    def test_rejects_other_client_and_missing_key(self):
        for field,value in [('phone_id','other'),('encrypt_key','')]:
            d=copy.deepcopy(self.devices);d['list'][0]['detail'][field]=value
            with self.assertRaises(ProtocolError):select_connection(self.session,self.session['band']['address'],d,self.products)
    def test_rejects_ambiguous_target(self):
        self.devices['list']*=2
        with self.assertRaises(ProtocolError):select_connection(self.session,self.session['band']['address'],self.devices,self.products)
    def test_rejects_unknown_transport(self):
        self.products['list'][0]['pd_type']=999
        with self.assertRaises(ProtocolError):select_connection(self.session,self.session['band']['address'],self.devices,self.products)
