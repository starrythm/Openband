"""Windows client for one explicitly selected Xiaomi Smart Band."""
import argparse
import asyncio
import json
import re
import sys
import uuid
from pathlib import Path
from wire import BandTransport, ProtocolError

def log(**event):
    print(json.dumps(event,ensure_ascii=False),flush=True)

def saved_connection(session,address):
    """Validate an existing profile locally; never refresh, bind, or log secrets."""
    from metadata import mac
    def invalid():
        raise ProtocolError('Saved connection profile is missing or invalid; run explicit refresh before notify')
    if not isinstance(session,dict):invalid()
    bound=session.get('band')
    if not isinstance(bound,dict):invalid()
    connection=bound.get('connection')
    if not isinstance(connection,dict):invalid()
    if (not isinstance(address,str) or not re.fullmatch(r'[0-9A-F]{12}',mac(address))
            or bound.get('status')!='bound' or mac(bound.get('address'))!=mac(address)
            or mac(connection.get('address'))!=mac(address)):
        invalid()
    if (connection.get('transport')!='spp' or type(connection.get('product_type')) is not int
            or connection['product_type'] not in (6,7)):
        invalid()
    if (not isinstance(bound.get('model'),str) or not bound['model']
            or connection.get('model')!=bound['model']):
        invalid()
    if (not isinstance(bound.get('did'),(str,int)) or isinstance(bound['did'],bool)
            or not str(bound['did']) or str(connection.get('did'))!=str(bound['did'])):
        invalid()
    if (not isinstance(session.get('phone_id'),str) or not session['phone_id']
            or connection.get('phone_id')!=session['phone_id']):
        invalid()
    key=connection.get('connection_key_hex')
    if not isinstance(key,str) or not re.fullmatch(r'[0-9a-fA-F]{32}',key):invalid()
    return connection

async def run(args):
    if args.command == 'probe':
        async with BandTransport(args.address,log) as band:
            info = await band.inspect()
            log(stage='probe_complete',verify_mode=info.verify_mode,oob_mode=info.oob_mode,
                model=info.model,device_metadata_present=bool(info.serial and info.mac))
        return
    from secure_store import load,save
    if not args.session or not Path(args.session).is_file():
        if args.command=='notify':
            raise ProtocolError('Saved local session file is missing; restore the existing profile or run explicit refresh before notify')
        raise ProtocolError('A Xiaomi miothealth login session is required; complete the manual login window first')
    session = load(args.session)
    if args.command!='notify' and session.get('sid') != 'miothealth':
        raise ProtocolError('Unexpected service session')
    from authentication import authenticate,notify_test
    if args.command=='notify':
        connection=saved_connection(session,args.address)
        log(stage='normal_connection_profile_loaded',transport=connection['transport'],
            product_type=connection['product_type'],cloud_refresh=False)
    else:
        if args.command=='bind':
            if session.get('band',{}).get('status')=='bound':
                raise ProtocolError('Binding already exists; use notify instead of binding again')
            session.setdefault('phone_id',uuid.uuid4().hex)
            save(args.session,session)
        elif not session.get('phone_id'):
            raise ProtocolError('Saved client identity missing; refusing to replace it')
        from binding import PskBinder
        def save_pending(value):
            session['pending_binding'] = value
            save(args.session,session)
        from cloud import CloudGateway
        if args.command == 'bind':
            async with BandTransport(args.address,log) as band:
                binder = PskBinder(band,CloudGateway(session),session,log,save_pending)
                result = await binder.bind()
                result['status']='bound'
                session['band']=result
                session.pop('pending_binding',None)
                save(args.session,session)
        from metadata import refresh_connection
        log(stage='refreshing_normal_connection_profile')
        connection=await asyncio.to_thread(refresh_connection,session,args.address,CloudGateway(session))
        save(args.session,session)
        log(stage='normal_connection_profile_saved',transport=connection['transport'],
            product_type=connection['product_type'],binding_key_preserved=True)
        if args.command=='refresh':return
    from spp_transport import SppTransport
    async with SppTransport(args.address,log) as band:
        # SPP WearAuthV2 receives a null optional HMAC identity; phone_id is not it.
        await authenticate(band,bytes.fromhex(connection['connection_key_hex']))
        if args.command == 'notify' or args.test_notification:
            await notify_test(band)
            await asyncio.sleep(12)
        log(stage='completed',application_authenticated=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['probe','bind','notify','refresh'])
    parser.add_argument('--address', required=True, type=bluetooth_address)
    parser.add_argument('--session', type=Path, default=Path(__file__).resolve().parents[1] / '.state/session.dpapi.json',
                        help='DPAPI session file created by login_helper_v2.cjs')
    parser.add_argument('--test-notification',action='store_true')
    args=parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log(stage='interrupted')
        return 130
    except ProtocolError as exc:
        log(stage='failed',error=str(exc))
        return 2
    except Exception as exc:
        # External exceptions may contain request headers or data; keep them out of logs.
        log(stage='failed',error_type=type(exc).__name__)
        return 1
    return 0

def bluetooth_address(value):
    from metadata import mac
    digits = mac(value)
    if not re.fullmatch(r'[0-9A-F]{12}', digits):
        raise argparse.ArgumentTypeError('Enter a 12-digit Bluetooth address')
    return ':'.join(digits[i:i+2] for i in range(0, 12, 2))

if __name__ == '__main__':
    sys.exit(main())
