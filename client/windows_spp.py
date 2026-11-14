"""Windows system bond and RFCOMM stream for the explicitly selected band."""
import asyncio
import socket
from wire import ProtocolError

SPP_UUID='00001101-0000-1000-8000-00805f9b34fb'

def rfcomm_channel(data):
    """Parse SDP ProtocolDescriptorList; never guess an RFCOMM channel."""
    def element(offset,end):
        if offset>=end:raise ProtocolError('Truncated SDP descriptor')
        header=data[offset];offset+=1;kind=header>>3;size=header&7
        if size<5:length=1<<size
        else:
            width=1<<(size-5)
            if offset+width>end:raise ProtocolError('Truncated SDP length')
            length=int.from_bytes(data[offset:offset+width],'big');offset+=width
        stop=offset+length
        if stop>end:raise ProtocolError('Truncated SDP value')
        if kind in (6,7):
            value=[]
            while offset<stop:
                child,offset=element(offset,stop);value.append(child)
        else:value=data[offset:stop]
        return (kind,value),stop
    root,end=element(0,len(data))
    if end!=len(data) or root[0]!=6:raise ProtocolError('Invalid SDP protocol list')
    for kind,protocol in root[1]:
        if kind!=6 or len(protocol)<2:continue
        if protocol[0]==(3,b'\x00\x03') and protocol[1][0]==1:
            channel=int.from_bytes(protocol[1][1],'big')
            if 1<=channel<=30:return channel
    raise ProtocolError('SPP service has no valid RFCOMM channel')

async def system_pair(address,log):
    from winrt.windows.devices.bluetooth import BluetoothDevice
    from winrt.windows.devices.enumeration import DevicePairingKinds
    from bleak.backends.winrt.client import FutureLike
    device=await asyncio.wait_for(FutureLike(BluetoothDevice.from_bluetooth_address_async(int(address.replace(':',''),16))),10)
    if not device:raise ProtocolError('Windows cannot resolve the selected classic Bluetooth device')
    try:
        pairing=device.device_information.pairing
        if pairing.is_paired:
            log(stage='windows_bond_present');return
        custom=pairing.custom
        def requested(sender,args):
            if args.pairing_kind==DevicePairingKinds.CONFIRM_ONLY:
                log(stage='windows_pair_confirmation');args.accept()
            elif args.pairing_kind==DevicePairingKinds.CONFIRM_PIN_MATCH:
                # User verifies the displayed number on their band and approves there.
                log(stage='windows_pair_pin',pin=args.pin,message='Compare this number on your band before approving')
                args.accept()
        token=custom.add_pairing_requested(requested)
        try:
            log(stage='windows_pairing_started')
            result=await asyncio.wait_for(FutureLike(custom.pair_async(
                DevicePairingKinds.CONFIRM_ONLY|DevicePairingKinds.CONFIRM_PIN_MATCH)),60)
            log(stage='windows_pairing_result',status=result.status.name)
            if result.status.name not in ('PAIRED','ALREADY_PAIRED'):
                raise ProtocolError('Windows system pairing failed: '+result.status.name)
        finally:custom.remove_pairing_requested(token)
    finally:device.close()

class RfcommStream:
    def __init__(self,address,log):self.address=address;self.log=log;self.socket=None

    async def connect(self):
        from winrt.windows.devices.bluetooth import BluetoothDevice,BluetoothCacheMode
        from winrt.windows.storage.streams import DataReader
        from bleak.backends.winrt.client import FutureLike
        await system_pair(self.address,self.log)
        device=await asyncio.wait_for(FutureLike(BluetoothDevice.from_bluetooth_address_async(int(self.address.replace(':',''),16))),10)
        if not device:raise ProtocolError('Selected Bluetooth device unavailable after pairing')
        try:
            result=await asyncio.wait_for(FutureLike(device.get_rfcomm_services_with_cache_mode_async(BluetoothCacheMode.UNCACHED)),20)
            if result.error.name!='SUCCESS':raise ProtocolError('SPP service lookup failed: '+result.error.name)
            services=[s for s in result.services if str(s.service_id.uuid).lower()==SPP_UUID]
            if len(services)!=1:raise ProtocolError('Official SPP service not available; refusing to guess a channel')
            attrs=await asyncio.wait_for(FutureLike(services[0].get_sdp_raw_attributes_async(BluetoothCacheMode.UNCACHED)),15)
            if 4 not in attrs:raise ProtocolError('SPP service has no protocol descriptor')
            buffer=attrs[4];reader=DataReader.from_buffer(buffer)
            try:
                raw=bytearray(buffer.length);reader.read_bytes(raw)
            finally:reader.close()
            channel=rfcomm_channel(bytes(raw))
        finally:device.close()
        self.socket=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_STREAM,socket.BTPROTO_RFCOMM)
        self.socket.settimeout(20)
        self.log(stage='spp_connecting',channel=channel)
        try:await asyncio.to_thread(self.socket.connect,(self.address,channel))
        except Exception:
            self.close();raise
        self.socket.settimeout(3)
        self.log(stage='spp_socket_connected')

    async def send(self,data):
        await asyncio.to_thread(self.socket.sendall,data)
    async def receive(self):
        while self.socket is not None:
            try:data=await asyncio.to_thread(self.socket.recv,4096)
            except TimeoutError:continue
            if not data:raise ProtocolError('SPP connection closed by peer')
            return data
        raise ProtocolError('SPP stream closed')
    def close(self):
        if self.socket is not None:self.socket.close();self.socket=None
