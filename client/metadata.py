"""Validate account/device identity before selecting a normal connection key."""
import re
from wire import ProtocolError

def mac(value):
    return str(value).replace(':','').replace('-','').upper()

def select_connection(session,address,devices,products):
    bound=session.get('band',{})
    if bound.get('status')!='bound' or mac(bound.get('address'))!=mac(address):
        raise ProtocolError('No confirmed binding for target address')
    entries=devices.get('list',[])
    targets=[v for v in entries if isinstance(v,dict) and
             mac(v.get('detail',{}).get('mac'))==mac(address)]
    if len(targets)!=1:
        raise ProtocolError('Target device missing or ambiguous in returned device page')
    device=targets[0]; detail=device.get('detail',{})
    if device.get('model')!=bound.get('model') or str(device.get('sid'))!=str(bound.get('did')):
        raise ProtocolError('Server device identity differs from saved binding')
    if detail.get('phone_id')!=session.get('phone_id'):
        raise ProtocolError('Server binding belongs to a different client identity')
    key=detail.get('encrypt_key')
    if not isinstance(key,str) or not re.fullmatch(r'[0-9a-fA-F]{32}',key):
        raise ProtocolError('Server did not return a valid normal connection key')
    matches=[]
    def visit(value):
        if isinstance(value,dict):
            if value.get('model')==bound['model'] and 'pd_type' in value:matches.append(value)
            for item in value.values():visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(products)
    if len(matches)!=1:raise ProtocolError('Product connection profile missing or ambiguous')
    product=matches[0]
    # Only verified dual-mode branch is supported here. Do not guess other type mappings.
    if product['pd_type'] not in (6,7):
        raise ProtocolError('Normal connection transport for product type is not implemented')
    return {'connection_key_hex':key.lower(),'product_type':product['pd_type'],
            'transport':'spp','model':bound['model'],'address':address,
            'did':bound['did'],'phone_id':session['phone_id']}

def refresh_connection(session,address,gateway):
    connection=select_connection(session,address,gateway.read_metadata('devices'),
                                 gateway.read_metadata('products'))
    session['band']['connection']=connection
    return connection
