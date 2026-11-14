"""Build and preview the native watchface; no device or network access."""
import argparse
import datetime as dt
import json
import math
import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--observer-file', type=Path, help='Local JSON with latitude and longitude')
args = parser.parse_args()
observer_file = args.observer_file or HERE / 'observer.example.json'
try:
    observer = json.loads(observer_file.read_text(encoding='utf-8-sig'))
    latitude, longitude = observer['latitude'], observer['longitude']
    for value, bound in ((latitude, 90), (longitude, 180)):
        if type(value) not in (int, float) or not -bound <= value <= bound or not math.isfinite(value):
            raise ValueError
except (OSError, KeyError, TypeError, ValueError):
    parser.error('Expected numeric latitude and longitude within valid ranges in the observer JSON')

build_dir = 'watchface-local' if args.observer_file else 'watchface'
FACE = ROOT / 'build' / build_dir / 'native-face'
IMAGE_DIR = FACE / 'images'
SCRIPT = IMAGE_DIR / '_lua/microstar/main.lua'
ID = '826104732'

SCRIPT.parent.mkdir(parents=True, exist_ok=True)
sky = (HERE / 'sky.lua').read_text(encoding='utf-8')
ui = (HERE / 'face.lua').read_text(encoding='utf-8')
SCRIPT.write_text('-- Generated from sky.lua and face.lua; edit those sources.\n'
                  f'local latitude, longitude = {latitude}, {longitude}\n'
                  'local sky = (function()\n' + sky + '\nend)()\n' + ui, encoding='utf-8')
definition = {'name': 'Micro Star 2', 'id': ID, 'previewImg': 'preview',
              'elementsNormal': [{'x': 0, 'y': 0, 'jsFileName': '_lua/microstar/main.lua',
                                  'type': 'type_element_lua'}]}
(FACE / 'wfDef.json').write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding='utf-8')

def preview(epoch, filename):
    cmd = ['node', 'node_modules/fengari-node-cli/src/lua-cli.js',
           'watchface/tests/mock-ui.lua', str(SCRIPT.relative_to(ROOT)), str(epoch)]
    result = subprocess.run(cmd, cwd=ROOT, text=True, encoding='utf-8', capture_output=True,
                            timeout=30, check=True, env={**os.environ, 'TZ': 'UTC'})
    im=Image.new('RGBA',(212,520),(0,0,8,255)); draw=ImageDraw.Draw(im)
    fontpath=Path('C:/Windows/Fonts/msyh.ttc')
    elements=[]
    for line in result.stdout.splitlines():
        fields=line.split('|',10)
        if len(fields)!=11: raise ValueError('Invalid mock output: '+line)
        kind=fields[0]; x,y,w,h,radius,color,opa,hidden,size=map(int,fields[1:10]); text=fields[10]
        if hidden: continue
        rgb=((color>>16)&255,(color>>8)&255,color&255)
        if kind=='rect' and w and h:
            if opa<100:
                rgb=tuple(round(c*opa/100) for c in rgb)
            draw.rounded_rectangle((x,y,x+w-1,y+h-1),radius=radius,fill=rgb)
        elif kind=='label' and text:
            font=ImageFont.truetype(str(fontpath),max(size,1)) if fontpath.is_file() else ImageFont.load_default(size=max(size,1))
            draw.text((x,y-2),text,font=font,fill=rgb)
        elements.append((kind,x,y,w,h,text))
    assert any(e[-1] == 'MICRO STAR' for e in elements)
    assert any('(A' in e[-1] and ' H' in e[-1] for e in elements)
    # The capsule mask is used for desktop previews only; the screen clips the face.
    mask=Image.new('L',im.size,0); ImageDraw.Draw(mask).rounded_rectangle((0,0,211,519),radius=105,fill=255)
    im.putalpha(mask)
    im.save(filename)
    return elements

night = int(dt.datetime(2026,1,1,0,0,tzinfo=dt.timezone.utc).timestamp())
day = int(dt.datetime(2026,1,1,12,0,tzinfo=dt.timezone.utc).timestamp())
preview(night, FACE.parent / 'preview-night.png')
preview(day, FACE.parent / 'preview-day.png')
preview(night, IMAGE_DIR / 'preview.png')
print('Built Lua source and mock previews; face id', ID, 'script bytes', SCRIPT.stat().st_size)
