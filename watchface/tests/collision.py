"""Check live layout, including label/marker and label/label separation."""
import datetime as dt
import json
import random
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
observer=json.loads((ROOT/'watchface/observer.example.json').read_text(encoding='utf-8'))
LUA='node_modules/fengari-node-cli/src/lua-cli.js'
FACE='build/watchface/native-face/images/_lua/microstar/main.lua'
MOCK='watchface/tests/mock-ui.lua'
names=['SUN','MOON','MERCURY','VENUS','MARS','JUPITER','SATURN','URANUS','NEPTUNE']

def run(cmd):
    return subprocess.run(cmd,cwd=ROOT,text=True,encoding='utf-8',capture_output=True,timeout=20,check=True).stdout

base=int(dt.datetime(2026,1,1,tzinfo=dt.timezone.utc).timestamp())
if '--sampled' in sys.argv:
    rng=random.Random(20261027)
    epochs=[base+rng.randrange(0,730*86400)+61 for _ in range(24)]
else:
    epochs=[base+i*3600+61 for i in range(24)]
positions={t:{} for t in epochs}
raw=run(['node',LUA,'watchface/tests/sky-eval.lua',
         str(observer['latitude']),str(observer['longitude'])]+list(map(str,epochs)))
for line in raw.splitlines():
    t,name,az,alt,phase,mag=line.split(',')
    positions[int(t)][name.upper()]=float(alt)

def overlap(a,b):
    ax,ay,aw,ah=a; bx,by,bw,bh=b
    return ax<bx+bw and ax+aw>bx and ay<by+bh and ay+ah>by

total=0
for epoch in epochs:
    raw=run(['node',LUA,MOCK,FACE,str(epoch-61),'61'])
    rows=[r.split('|',10) for r in raw.splitlines()]
    groups={}
    for i,r in enumerate(rows):
        if r[0]!='label': continue
        name=r[10].split(' ',1)[0]
        if name not in names: continue
        groups[name]=(r,rows[i-1],rows[i-4])
    assert set(groups)==set(names)
    backgrounds=[]
    shadows=[]
    for name,(label,bg,shadow) in groups.items():
        alt=positions[epoch][name]
        if shadow[8]=='0':
            shadows.append((name,tuple(map(int,shadow[1:5]))))
        if alt>=1.25:
            assert label[8]=='0',f'{epoch}: missing {name} at {alt}'
            if alt>=4:
                assert re.search(r'\(A\d{3} H[+-]\d+',label[10]),label[10]
                if name=='MOON': assert re.search(r'% M[+-][\d.]+\)$',label[10])
                else: assert ' M' not in label[10]
            backgrounds.append((name,tuple(map(int,bg[1:5]))))
            assert int(label[2])<405 and int(label[1])>=2
        else:
            assert label[8]=='1',f'{epoch}: unexpected label {name}'
    for i,(name,a) in enumerate(backgrounds):
        for other,b in backgrounds[i+1:]:
            assert not overlap(a,b),f'{epoch}: {name} collides with {other}'
        for marker,b in shadows:
            assert not overlap(a,b),f'{epoch}: {name} covers the {marker} marker'
    assert not any(r[0]=='label' and r[8]=='0' and int(r[2])>=440 for r in rows)
    total+=len(backgrounds)
print(f'PASS: {len(epochs)} sky layouts, {total} visible labels, no label/marker collisions')
