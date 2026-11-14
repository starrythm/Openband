import unittest
from windows_spp import rfcomm_channel
from wire import ProtocolError
class SdpTests(unittest.TestCase):
    def test_observed_protocol_descriptor(self):
        self.assertEqual(rfcomm_channel(bytes.fromhex('350c350319010035051900030805')),5)
    def test_does_not_guess_channel(self):
        for data in (b'',bytes.fromhex('350c3503190100350519000308'),bytes.fromhex('350c350319010035051900030800')):
            with self.assertRaises(ProtocolError):rfcomm_channel(data)
