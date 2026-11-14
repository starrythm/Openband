"""Xiaomi SPP version negotiation, legacy application frames, and V2 sessions."""
import asyncio
from wire import BandTransport,ProtocolError,FrameReader,frame,START_SESSION,parse
from windows_spp import RfcommStream
from spp_codec import (SppFrameReader,version_query,parse_version,encode_packet,
    application_packet,response_ack,SppV1Cipher)

class SppTransport(BandTransport):
    def __init__(self,address,logger=None):
        super().__init__(address,logger)
        self.stream=RfcommStream(address,self.log)
        self.stream_reader=None
        self.legacy_reader=SppFrameReader()
        self.legacy=True
        self.spp_sequence=2
        self.cipher=None

    async def __aenter__(self):
        try:
            await self.stream.connect()
            await self.stream.send(version_query(1))
            self.log(stage='spp_version_query_sent')
            async def get_version():
                while True:
                    for packet in self.legacy_reader.feed(await self.stream.receive()):
                        if packet.need_response:
                            await self._write(response_ack(packet))
                        if packet.channel==0 and packet.payload:
                            return parse_version(packet)
            version=await asyncio.wait_for(get_version(),12)
            self.log(stage='spp_version_received',version=list(version))
            self.legacy=version[0] not in (2,3)
            if self.legacy:
                self.stream_reader=asyncio.create_task(self._read_legacy())
            else:
                self.reader=FrameReader()
                self.receiver=asyncio.create_task(self._pump())
                self.stream_reader=asyncio.create_task(self._read_v2())
                await self._write(frame(2,0,START_SESSION))
                await asyncio.wait_for(self.session_ready.wait(),10)
            self.log(stage='message_channel_ready',transport='spp',framing='v1' if self.legacy else 'v2')
            return self
        except BaseException:
            await self.__aexit__(None,None,None);raise

    async def _write(self,data):
        async with self.write_lock:await self.stream.send(data)

    async def _read_v2(self):
        try:
            while True:
                for packet in self.reader.feed(await self.stream.receive()):
                    self.raw_queue.put_nowait(packet)
        except asyncio.CancelledError:raise
        except Exception as exc:self.responses.put_nowait(exc)

    async def _read_legacy(self):
        try:
            while True:
                for packet in self.legacy_reader.feed(await self.stream.receive()):
                    if packet.need_response:await self._write(response_ack(packet))
                    if packet.channel not in (1,2) or packet.opcode!=2:continue
                    data=packet.payload
                    if packet.data_type==1:
                        if self.cipher is None:raise ProtocolError('Encrypted SPP data before authentication keys')
                        data=self.cipher.decrypt(data)
                    elif packet.data_type!=2:
                        raise ProtocolError('Unsupported SPP application data type')
                    value=parse(data);self.last_received=value
                    self.log(stage='application_rx',command_type=value.get(1),subtype=value.get(2))
                    self.responses.put_nowait(value)
        except asyncio.CancelledError:raise
        except Exception as exc:self.responses.put_nowait(exc)

    def set_session_keys(self,device_key,app_key,device_iv,app_iv):
        self.decryption_key,self.encryption_key=device_key,app_key
        self.cipher=SppV1Cipher(device_key,app_key,device_iv,app_iv)

    async def send_application(self,command,encrypted=False):
        if not self.legacy:return await super().send_application(command,encrypted)
        if encrypted:
            if self.cipher is None:raise ProtocolError('SPP session keys unavailable')
            command=self.cipher.encrypt(command)
        seq=self.spp_sequence;self.spp_sequence=(seq+1)&255
        await self._write(application_packet(command,seq,encrypted=encrypted))
        return seq

    async def __aexit__(self,*_):
        self.stream.close()
        tasks=[task for task in (self.stream_reader,self.receiver) if task is not None]
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
