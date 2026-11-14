"""Compare the watch Lua approximations against the original engine's JS port."""
import datetime, json, math, random, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
observer = json.loads((ROOT/'watchface/observer.example.json').read_text(encoding='utf-8'))
random.seed(20261027)
start = int(datetime.datetime(2026,1,1,tzinfo=datetime.timezone.utc).timestamp())
end = int(datetime.datetime(2029,1,1,tzinfo=datetime.timezone.utc).timestamp())
epochs = [start + (end-start)*i//40 + random.randrange(86400) for i in range(40)]
input_text = ''.join(str(t)+'\n' for t in epochs)
cmd_lua = ['node', 'node_modules/fengari-node-cli/src/lua-cli.js', 'watchface/tests/sky-eval.lua',
           str(observer['latitude']), str(observer['longitude'])] + [str(t) for t in epochs]
cmd_ref = ['node', 'watchface/tests/reference.js']
def run(cmd):
    p = subprocess.run(cmd, cwd=ROOT, input=input_text, text=True, capture_output=True, timeout=90, check=True)
    return [line.strip().split(',') for line in p.stdout.splitlines() if line.strip()]

actual, expected = run(cmd_lua), run(cmd_ref)
assert len(actual) == len(expected) == len(epochs)*9
summary = {}
for a,b in zip(actual,expected):
    assert a[:2] == b[:2]
    az1,alt1,phase1,mag1 = map(float,a[2:]); az2,alt2,phase2,mag2 = map(float,b[2:])
    r = math.pi/180
    c = math.sin(alt1*r)*math.sin(alt2*r) + math.cos(alt1*r)*math.cos(alt2*r)*math.cos((az1-az2)*r)
    delta = math.degrees(math.acos(max(-1,min(1,c))))
    stat = summary.setdefault(a[1], {'max_deg':0,'visible_max_deg':0,'max_phase':0,'max_magnitude':0})
    stat['max_deg'] = max(stat['max_deg'],delta)
    if alt2 >= 0: stat['visible_max_deg'] = max(stat['visible_max_deg'],delta)
    if phase2 >= 0: stat['max_phase'] = max(stat['max_phase'],abs(phase1-phase2))
    if mag2 > -90: stat['max_magnitude'] = max(stat['max_magnitude'],abs(mag1-mag2))
for v in summary.values():
    for k in v: v[k] = round(v[k],4)
print(json.dumps({'sample_count':len(epochs),'years':'2026-2028','comparison':summary},ensure_ascii=False,indent=2))
assert max(x['visible_max_deg'] for x in summary.values()) < 1.0
assert summary['Moon']['max_phase'] < 0.03
assert summary['Moon']['max_magnitude'] < 0.05
