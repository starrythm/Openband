"""Render 灯与翅膀, a portrait short designed for the Band 10 capsule screen."""
import argparse
from functools import lru_cache
import math
from pathlib import Path
import random
import subprocess
import wave

from imageio_ffmpeg import get_ffmpeg_exe
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
W, H, SCALE, FPS = 212, 520, 2, 30
SIZE = W * SCALE, H * SCALE
LENGTHS = (4.6, 3.9, 4.1, 4.5, 3.8, 4.5, 4.6)
STARTS = tuple(np.cumsum((0,) + LENGTHS))
DURATION = 30
INK = "#12223a"
GOLD = (255, 198, 111)
MINT = (154, 246, 221)
TAU = math.tau


def clamp(v):
    return max(0.0, min(1.0, v))


def ease(v):
    u = clamp(v)
    return u * u * (3 - 2 * u)


def tween(a, b, v):
    return a + (b - a) * clamp(v)


def mix(a, b, u):
    return tuple(round(tween(x, y, u)) for x, y in zip(a, b))


def px(x):
    return round(x * SCALE)


def pts(points):
    return [(px(x), px(y)) for x, y in points]


def oval(draw, x, y, rx, ry, fill, outline=None, width=1):
    draw.ellipse(pts(((x-rx, y-ry), (x+rx, y+ry))), fill=fill, outline=outline, width=max(1, px(width)))


def rounded(draw, x, y, w, h, r, fill, outline=None, width=1):
    draw.rounded_rectangle(pts(((x, y), (x+w, y+h))), radius=px(r),
                           fill=fill, outline=outline, width=max(1, px(width)))


def polygon(draw, points, fill, outline=None):
    draw.polygon(pts(points), fill=fill, outline=outline)


def line(draw, points, fill, width=1):
    draw.line(pts(points), fill=fill, width=max(1, px(width)), joint="curve")


def star(draw, x, y, radius, color):
    r = radius
    polygon(draw, ((x, y-r), (x+r*.22, y-r*.24), (x+r*.72, y), (x+r*.22, y+r*.22),
                   (x, y+r), (x-r*.22, y+r*.24), (x-r*.72, y), (x-r*.22, y-r*.24)), color)


@lru_cache(maxsize=96)
def glow_sprite(radius, color, power):
    y, x = np.mgrid[-px(radius):px(radius)+1, -px(radius):px(radius)+1]
    distance = np.hypot(x, y) / px(radius)
    alpha = np.maximum(0, 1 - distance) ** 2.1 * power
    rgb = np.broadcast_to(np.array(color, dtype=np.uint8), (*alpha.shape, 3))
    return Image.fromarray(np.dstack((rgb, np.uint8(alpha))), "RGBA")


def glow(img, x, y, r, color=GOLD, alpha=204):
    sprite = glow_sprite(round(r), color, round(alpha / 12) * 12)
    img.alpha_composite(sprite, (px(x-r), px(y-r)))


def lamp(img, x, y, size=1, lit=1):
    if lit:
        glow(img, x, y, max(8, round(26 * size)), GOLD, round(210 * lit))
    d = ImageDraw.Draw(img)
    oval(d, x, y, 7.8*size, 9*size, "#432e42", "#c68856", .95*size)
    oval(d, x, y+.4*size, 5.5*size, 6.8*size, mix((63, 75, 91), (255, 212, 126), lit))
    if lit > .10:
        star(d, x, y-1, 4.6*size, "#fff5c9")
    line(d, [(x-4.5*size, y-8*size), (x+4.5*size, y-8*size)], "#f1b57a", 1.25*size)


STYLES = {
    "port": ((11, 15, 48), (92, 59, 92), (45, 27, 47), 136, 251),
    "canal": ((12, 24, 55), (37, 76, 100), (19, 31, 77), 47, 258),
    "fall": ((14, 22, 43), (46, 75, 97), (17, 29, 54), 147, 240),
    "rescue": ((10, 20, 37), (41, 84, 103), (12, 23, 44), 163, 306),
    "tower": ((15, 24, 61), (68, 81, 114), (18, 23, 54), 47, 204),
    "flock": ((14, 23, 64), (95, 88, 120), (21, 30, 66), 101, 195),
    "home": ((55, 45, 92), (247, 153, 120), (97, 70, 104), 168, 223),
}


@lru_cache(maxsize=16)
def painted_sky(name):
    top, center, bottom, cx, cy = STYLES[name]
    y, x = np.mgrid[0:SIZE[1], 0:SIZE[0]] / SCALE
    a = np.clip(y/cy, 0, 1)[..., None]
    b = np.clip((y-cy)/(H-cy), 0, 1)[..., None]
    color = (np.array(top) + (np.array(center)-top)*a) * (1-b) + np.array(bottom)*b
    bokeh = np.exp(-((x-cx)/85)**2 - ((y-cy)/147)**2)
    tint = np.array((17, 11, 13) if name not in ("fall", "rescue") else (4, 15, 19))
    color = color + bokeh[..., None]*tint
    return Image.fromarray(np.uint8(np.clip(color, 0, 255))).convert("RGBA")


@lru_cache(maxsize=32)
def cloud_field(seed):
    rng = random.Random(seed)
    return [(rng.randint(-110, 245), rng.randint(20, 300), rng.randint(45, 106),
             rng.randint(7, 21), rng.random()) for _ in range(14)]


def clouds(img, t, seed, colors, speed=9):
    d = ImageDraw.Draw(img)
    for x0, y, rx, ry, var in cloud_field(seed):
        x = (x0 + t*speed*(.5+var)) % 422 - 105
        base = mix(colors[0], colors[1], var)
        polygon(d, ((x-rx, y+ry*.68), (x-rx*.72, y+ry*.18), (x-rx*.51, y-ry*.21),
                    (x-rx*.24, y-ry*.17), (x-rx*.10, y-ry*.7), (x+rx*.24, y-ry*.9),
                    (x+rx*.50, y-ry*.45), (x+rx, y+ry*.4), (x+rx*.76, y+ry*.74)), base)
        line(d, [(x-rx*.65, y+ry*.34), (x-rx*.15, y+ry*.32), (x+rx*.4,y+ry*.17)],
             mix(base, colors[1], .18))


@lru_cache(maxsize=16)
def seeded_particles(seed, count):
    rng = random.Random(seed)
    return [(rng.uniform(0, 234), rng.uniform(0, 550), rng.uniform(.58, 1.65), rng.random())
            for _ in range(count)]


def rain(img, t, seed, heavy=.8):
    d = ImageDraw.Draw(img)
    for a, b, speed, shape in seeded_particles(seed, round(47*heavy)):
        x = (a - t * (39 + 38*speed)) % 237 - 8
        y = (b + t * (115 + 134*speed)) % 555 - 20
        color = mix((63, 93, 123), (142, 174, 195), shape * heavy)
        line(d, ((x, y), (x-3.6*speed, y+8.6*speed)), color, .62)


def drifters(img, t, seed, count, low, span, color):
    d = ImageDraw.Draw(img)
    for x, y, speed, f in seeded_particles(seed, count):
        xpos = 15 + (x + t*speed*3) % 182
        ypos = low + (y + t*speed*4) % span
        if math.sin(t*3+f*TAU) > -.18:
            star(d, xpos, ypos, .65+f*1.2, color)


def water(img, t, start, width=1, storm=False, sun=False):
    d = ImageDraw.Draw(img)
    far, near = ((64, 66, 107), (26, 43, 74)) if sun else ((27, 67, 91), (12, 28, 52))
    d.rectangle((0, px(start), SIZE[0], SIZE[1]), fill=near)
    band = 22 if storm else 14
    for i in range(band):
        f = (i+.3)/band
        y = start + (H-start)*f
        color = mix(far, near, f)
        advance = t*(13+17*f)
        waves = [(x, y + math.sin((x+advance)*.055+i*1.87)*(.85+f*2.5))
                 for x in range(-8, W+9, 6)]
        polygon(d, waves + [(W,H), (0,H)], color)
        for j in range(4):
            x = (27 + 47*j + 23*i + advance*(1 if j%2 else -1)) % 215
            length = (9+5*j)*(f+.45)*width
            high = mix(color, (114, 161, 179) if not sun else (243, 133, 120), .31+.08*(j%2))
            line(d, [(x,y+4), (x+length*.38,y+3.4), (x+length,y+4.5)], high, .75)


def city(img, t, base, seed, illuminated=1, dawn=False, shift=0):
    d = ImageDraw.Draw(img)
    rng = random.Random(seed)
    for layer in range(3):
        x = -38 - shift*(layer+1)/3
        baseline = base - (2-layer)*22
        for k in range(18):
            w = rng.randint(12, 28)
            h = rng.randint(22, 79) * (.85+layer*.11)
            y = baseline - h
            hull = [(34,43,74),(32,37,66),(22,27,54)][layer]
            if dawn:
                hull = mix(hull, (85, 54, 85), .36)
            roof = mix(hull, (146, 111, 157), .21)
            if k%3 != 2:
                polygon(d, ((x-2,y), (x+w*.5,y-9-rng.random()*9), (x+w+2,y), (x+w,baseline), (x,baseline)), hull)
                line(d, [(x-2,y), (x+w*.5,y-11), (x+w+1,y)], roof, .8)
            else:
                rounded(d, x, y, w, h, 1.4, hull)
                line(d, [(x-1, y), (x+w+1, y)], roof, 1)
                line(d, [(x+w*.74,y),(x+w*.74,y-11)], roof)
            line(d, [(x+w-1,y),(x+w-1,baseline)], roof, .6)
            for row in range(2 + (h > 49)):
                for col in range(1 + (w > 17)):
                    wx, wy = x+4+col*7, y+9+row*11
                    salt = rng.random()
                    power = ease(illuminated*1.7-salt*.66)
                    color = mix(mix(hull, (105,122,161), .27), (255, 187+(row*5), 112), power)
                    rounded(d, wx, wy, 3.5, 4.5, .85, color)
            x += w + 3
        polygon(d, [(0,baseline),(212,baseline),(212,baseline+5),(0,baseline+7)], hull)


def beams(img, x, y, t, amount, heading=None):
    if amount <= .01:
        return
    overlay = Image.new("RGBA", SIZE)
    d = ImageDraw.Draw(overlay)
    tilt = math.sin(t*.95)*.34-.12 if heading is None else heading
    for degrees, width, strength in ((tilt, .31, 35), (tilt, .15, 64), (tilt, .045, 80)):
        points = [(x,y), (x+330*math.cos(degrees-width), y+330*math.sin(degrees-width)),
                  (x+330*math.cos(degrees+width), y+330*math.sin(degrees+width))]
        polygon(d, points, (255, 223, 146, round(strength * clamp(amount))))
    img.alpha_composite(overlay)
    glow(img, x, y, 34, GOLD, round(180*clamp(amount)))


def lighthouse(img, x, y, s, lit=0, t=0, balcony=True):
    d = ImageDraw.Draw(img)
    def xy(points):
        return [(x + a*s, y + b*s) for a, b in points]
    polygon(d, xy(((-27,0),(-13,-202),(14,-202),(29,0))), "#272d50", "#424968")
    polygon(d, xy(((-27,0),(-13,-202),(-3,-202),(-7,0))), "#3c4266")
    for row in (42, 89, 135, 169):
        left = -27+row*.069
        right = 29-row*.069
        polygon(d, xy(((left,-row),(left+1.6,-row-10),(right-2,-row-10),(right,-row))), "#514962")
        line(d, xy(((left,-row),(right,-row))), "#ac7883", .9*s)
    for yy in (56, 118, 158):
        rounded(d, x-3.5*s, y-yy*s, 7*s, 15*s, 3.5*s, "#181e39")
        if lit > .05:
            rounded(d,x-1.25*s, y-(yy-1)*s,2.5*s,11*s,1*s,mix((43,54,79),(233,154,87),lit))
    polygon(d, xy(((-24,-206),(-17,-216),(18,-216),(25,-206),(20,-197),(-20,-197))), "#715671", "#b8868b")
    rounded(d, x-17*s, y-255*s, 34*s, 40*s, 4*s, "#2f3e61", "#ac8795", 1.1*s)
    rounded(d, x-13*s, y-251*s, 26*s, 29*s, 3*s, mix((26,47,66),(255,187,102),lit), "#685a76", .9*s)
    for k in (-8,0,8):
        line(d, xy(((k,-250),(k,-223))), "#a18a96", .8*s)
    polygon(d, xy(((-21,-255),(-11,-265),(0,-276),(10,-265),(21,-255))), "#463a58", "#b086a0")
    line(d, xy(((0,-276),(0,-286))), "#a98fab", 1*s)
    oval(d, x, y-287*s, 2*s, 2*s, "#efbb9c")
    if balcony:
        line(d, xy(((-25,-204),(-26,-196),(26,-196),(25,-204))), "#e2a196", 1*s)
        for k in (-20,-12,-4,4,12,20):
            line(d, xy(((k,-205),(k,-196))), "#9b738d", .85*s)
    if lit:
        beams(img, x, y-237*s, t, lit, -2.73+math.sin(t*1.9)*.34)


def slope(d, y, color, trim, rock=False):
    profile = [(0,y+2),(21,y-3),(40,y-2),(58,y-8),(82,y-6),(111,y+1),(136,y+6),
               (158,y+4),(186,y+9),(212,y+5)]
    polygon(d, profile + [(W,H),(0,H)], color)
    line(d, profile, trim, 1.8)
    for x in range(6, 210, 8 if rock else 11):
        h = 2 + ((x*37) % 7)
        line(d, [(x,y+18+(x%5)), (x+h,y+14+(x%5)), (x+h+5,y+18+(x%5))], trim, .7)


def robot(img, x, y, scale=1, phase=0, face=1, hold=1, reach=0, sad=False, bob=True):
    s = scale
    hop = abs(math.sin(phase)) * 3 * s if bob else 0
    y -= hop
    d = ImageDraw.Draw(img)
    def p(a,b):
        return x + face*a*s, y + b*s
    def shape(points, fill, outline=None):
        polygon(d, [p(a,b) for a,b in points], fill, outline)
    def trace(points, fill, width=1):
        line(d, [p(a,b) for a,b in points], fill, width*s)
    def bulb(a,b,rx,ry,fill,outline=None,width=1):
        q,r = p(a,b)
        oval(d,q,r,rx*s,ry*s,fill,outline,width*s)
    oval(d,x,y+4*s,21*s,4.4*s,"#182238")
    stride = math.sin(phase)*7.3
    for side in (-1,1):
        a = side*9
        foot = a + side*stride
        yfoot = -max(0, math.cos(phase)*side)*3.7
        trace(((a,-22),(a+side*.33*stride,-10),(foot,yfoot-2)), "#243249", 5.2)
        trace(((a,-19),(foot,yfoot-3)), "#91afad", 1.25)
        bulb(foot+1.2,yfoot-1,6.2,3.1,"#c78561","#483646",.8)
    shape(((-14,-47),(10,-47),(17,-39),(13,-19),(-10,-17),(-17,-23),(-19,-37)), "#b96854", INK)
    shape(((-13,-43),(9,-44),(14,-39),(10,-22),(-8,-21),(-13,-25)), "#d4875c")
    trace(((-12,-26),(-4,-23),(9,-25)), "#f4be90", .85)
    bulb(-1,-33,7.7,7.6,"#774f52","#f1bf89",1.3)
    bulb(-1,-33,4.9,4.9,mix((46,63,77),(148,245,205),hold))
    if hold:
        front = p(-1,-33)
        star(d,front[0],front[1],2.8*s,"#ecffd9")
    trace(((-16,-38),(-23,-29+stride*.2),(-23,-22+stride*.5)), "#29384e",4.0)
    bulb(-23,-22+stride*.5,3.6,3.3,"#e4a97e")
    trace(((15,-38),(21+4*reach,-31-4*reach),(22+10*reach,-23-15*reach)), "#29384e",4.0)
    bulb(22+10*reach,-23-15*reach,3.9,3.6,"#efb48b")
    bulb(0,-53,23,17,"#d98f68",INK,1.8)
    bulb(0,-54,20,14,"#f1b481")
    bulb(3,-53,16.7,11.3,"#213447","#976674",1.0)
    bulb(-19,-53,5,6,"#a25e62",INK,.85)
    trace(((-7,-69),(-10,-76),(-6,-80)), "#d59681", 1.4)
    bulb(-6,-80,2.5,2.5,"#b3f3d4")
    for eye in (-2,10):
        yy = -53 + (1.8 if sad else -.8)
        bulb(eye,yy,3.05,1.5 if sad else 3.65,"#c7ffe5")
        bulb(eye+1.15,yy+.15,1.15,1.15,"#5eaab0")
    trace(((0,-46),(6,-45),(9,-46)), "#a5eac3", .8)


def bird(img, x, y, scale, clock, flip=1, folded=False, color=(244, 243, 214)):
    s = scale
    d = ImageDraw.Draw(img)
    angle = 0.35 + 0.65*math.sin(clock * 16)
    raise_wing = -7 - 12*angle if not folded else -4
    def shape(points, fill, outline=None):
        polygon(d, [(x+a*s*flip, y+b*s) for a,b in points], fill, outline)
    shape(((-17,-1),(-1,-4),(7,-9),(12,-5),(18,-3),(11,0),(6,5),(-7,7)), color, "#6b8faa")
    shape(((-4,-2),(-18,raise_wing-2),(-4,raise_wing-5),(9,-4),(5,.7)), mix(color, (132,191,202),.35))
    shape(((-4,-2),(4,-1),(-8,9),(-18,5)), mix(color, (109,156,186),.38))
    shape(((10,-5),(18,-3),(10,-1)), "#fab77b")
    oval(d, x+9*s*flip, y-4.8*s, 1.05*s, 1.05*s, "#2e5366")


@lru_cache(maxsize=12)
def font(size, bold=False):
    path = Path("C:/Windows/Fonts") / ("msyhbd.ttc" if bold else "msyh.ttc")
    return ImageFont.truetype(str(path), px(size))


def lettering(img, y, value, size, color, opacity=1, bold=False):
    if opacity <= 0:
        return
    overlay = Image.new("RGBA", SIZE)
    d = ImageDraw.Draw(overlay)
    d.text((px(106),px(y+1.4)),value,font=font(size,bold),fill=(18,26,51,round(115*opacity)),anchor="mm")
    d.text((px(106),px(y)),value,font=font(size,bold),fill=(*color,round(255*opacity)),anchor="mm")
    img.alpha_composite(overlay)


def port(t):
    img = painted_sky("port").copy()
    clouds(img,t,8,((32,35,65),(84,58,98)),15)
    power = 1 - ease((t-1.60)/.52)
    power = max(power, .63 * math.exp(-((t-2.25)/.15)**2))
    city(img,t,408,25,1-ease((t-2.25)/1.05)*.87,shift=t*2)
    water(img,t,411,.83)
    lighthouse(img,163,398,.56,power,t,False)
    d=ImageDraw.Draw(img)
    slope(d,452,"#222a45","#58667b")
    for x in (-4,18,47,181,202):
        line(d,[(x,459),(x+4,441),(x+2,431)],"#728494",1.5)
    if t < 2.75:
        d=ImageDraw.Draw(img)
        rounded(d,79,409,20,42,4,"#293754","#625e7d")
        lamp(img,89,407,.64,.92)
    walk=ease((t-3.13)/1.40)
    x=tween(119,182,walk)
    grip=ease((t-2.48)/.48)
    robot(img,x,454,.71,walk*9,1 if t>3.04 else -1,hold=grip,reach=math.sin(grip*math.pi)*.8)
    if t>2.75:
        lamp(img,x+16,430,.67)
    if 1.56 < t < 2.00:
        d=ImageDraw.Draw(img)
        if int(t*21)%3 != 1:
            line(d,[(153,31),(141,97),(151,86),(126,162)],"#afcbea",1.3)
    title=ease(t/.36)*(1-ease((t-1.57)/.48))
    lettering(img,145,"灯与翅膀",31,(255,230,188),title,True)
    return img


def canal(t):
    img=painted_sky("canal").copy()
    clouds(img,t,29,((17,31,63),(43,69,98)),11)
    city(img,t,317,66,.29,shift=8+t*7)
    lighthouse(img,166,306,.47,0,t,False)
    water(img,t,335,1.18)
    d=ImageDraw.Draw(img)
    bridge=[(-5,408),(17,390),(65,363),(104,371),(147,400),(215,423),(215,457),(143,420),(102,387),
            (66,381),(19,410),(-5,431)]
    polygon(d,bridge,"#544458","#987478")
    for j in range(16):
        x=13*j
        y=366+abs(x-70)*.43
        line(d,[(x,y),(x+4,y+18)],"#3b3449",1.6)
        if j%3==0:
            line(d,[(x,y+5),(x,y-17)],"#a38086",2.2)
    line(d,[(0,389),(45,364),(68,353),(103,356),(143,382),(211,410)],"#a38086",1.3)
    x=tween(16,134,ease(t/3.79))
    y=369+abs(x-70)*.42
    robot(img,x,y,.74,t*7.1,1,1,0)
    lamp(img,x+17,y-21,.62)
    wiggle=math.sin(t*9)*5
    d=ImageDraw.Draw(img)
    line(d,[(135,159),(143,217),(156+wiggle,260)],"#bda298",1.1)
    line(d,[(122,132),(212,157)],"#a3848f",2.4)
    bird(img,157+wiggle,263+3*math.sin(t*8),.83,t,-1)
    rain(img,t,19,.41)
    return img


def rock_bank(img, y, edge):
    d=ImageDraw.Draw(img)
    poly=[(0,y-71),(16,y-54),(45,y-57),(62,y-29),(edge-20,y-20),(edge,y+1),
          (edge-10,y+17),(edge-35,y+29),(0,y+45)]
    polygon(d,poly,"#252c46","#657789")
    polygon(d,[(0,y-47),(28,y-51),(51,y-27),(61,y-20),(edge-17,y-15),(edge,y+1),(48,y+5),(0,y+21)],"#41445c")
    line(d,[(1,y-26),(35,y-17),(45,y-6),(73,y-3)],"#79717f",1.2)


def splash(img, t, x, y, size):
    if t < 0 or t > 1.24:
        return
    d=ImageDraw.Draw(img)
    pulse=1-ease(t/1.24)
    oval(d,x,y,(6+t*18)*size,(2+t*6)*size,None,mix((56,110,133),(189,236,231),pulse),1.05)
    for j in range(11):
        angle=(j-5)*.27
        dx=math.sin(angle)*(9+t*19)*size
        dy=(3+23*math.sin(t*2.3))*(.5+(j%3)*.21)*size
        oval(d,x+dx,y-dy,1.05*size,(1.2+pulse*1.1)*size,"#aed9df")


def fall(t):
    img=painted_sky("fall").copy()
    clouds(img,t,13,((18,31,53),(46,64,88)),22)
    lighthouse(img,181,320,.35,0,t,False)
    water(img,t,307,1.2,storm=True)
    rock_bank(img,430,105)
    d=ImageDraw.Draw(img)
    wind=math.sin(t*10)*4
    snapping=ease((t-1.16)/.47)
    x=tween(150+wind,151,ease((t-1.25)/1.15))
    y=tween(196+2*wind,392,((clamp((t-1.24)/.83))**1.65))
    if t>2.10:
        y=392+4*math.sin(t*9)
    line(d,[(104,105),(138,137),(149+wind*(1-snapping),tween(195,153,snapping))],"#c7a993",1.6)
    bird(img,x,y,1.13,t,-1,t>2.06)
    splash(img,t-2.05,152,394,1.16)
    rush=ease((t-.86)/1.2)
    reach=ease((t-2.4)/.9)
    bot_x=tween(38,74,rush)
    robot(img,bot_x,423,.85,rush*7,1,1,reach,sad=t>1.9)
    lamp(img,bot_x+17+reach*10,405-reach*13,.72)
    rain(img,t,26,1)
    if .77<t<.95:
        d=ImageDraw.Draw(img)
        line(d,[(188,44),(173,113),(185,101),(158,169)],"#c7def4",1.1)
    return img


def rescue(t):
    img=painted_sky("rescue").copy()
    clouds(img,t,13,((14,27,53),(43,70,89)),18)
    water(img,t,299,1.35,storm=True)
    rock_bank(img,423,108)
    boat=ease((t-.22)/1.04)
    drag=ease((t-1.54)/1.42)
    airborne=ease((t-3.00)/1.34)
    lx=tween(tween(103,151,boat),98,drag)
    ly=tween(tween(381,395,boat),386,drag)-math.sin(boat*math.pi)*17
    lit=1-ease((t-1.79)/.55)
    robot(img,70-drag*9,420,1.02,drag*4,1,lit,1,sad=drag<.79)
    d=ImageDraw.Draw(img)
    rope_y=360
    line(d,[(92-drag*8,rope_y),(105,rope_y+9),(lx-8,ly-7),(lx,ly)],"#c29582",1.35)
    lamp(img,lx,ly,.96,lit)
    bx=tween(153,lx+3,drag)
    by=tween(386+3*math.sin(t*7),ly-15,drag)
    bx=tween(bx,173,airborne)
    by=tween(by,144,airborne)
    bird(img,bx,by,1.07-airborne*.24,t,1,t<3.0)
    splash(img,t-1.20,151,393,.66)
    splash(img,t-1.86,142,395,.84)
    rain(img,t,26,.99-.44*airborne)
    return img


def tower(t):
    img=painted_sky("tower").copy()
    clouds(img,t,17,((16,28,54),(56,68,102)),13)
    d=ImageDraw.Draw(img)
    polygon(d,[(0,404),(29,371),(62,388),(79,362),(114,369),(174,351),(212,380),(212,520),(0,520)],
            "#26304f")
    lighthouse(img,147,521,1.19,0,t)
    travel=ease((t-.14)/2.2)
    for step in range(11):
        x=13+step*8.1
        y=493-step*14
        polygon(d,[(x,y),(x+31,y-3),(x+36,y+3),(x+34,y+7),(x,y+10)],"#615576","#95778d")
        line(d,[(x,y+5),(x+33,y+1)],"#453d60",1)
    robot(img,tween(35,110,travel),tween(483,341,travel),.68,travel*17,1,0,
          ease((t-1.72)/.42)*(1-ease((t-2.74)/.62)),sad=t>2)
    if t>2.22:
        lamp(img,129,312,.59,0)
    rain(img,t,12,.6*(1-ease(t/2.8)))
    if t>2.97:
        onset=ease((t-2.97)/.7)
        x=tween(205,175,onset)
        y=tween(145,117,onset)
        glow(img,x,y+3,13,GOLD,150)
        bird(img,x,y,.63,t,-1)
        d=ImageDraw.Draw(img)
        star(d,x,y+7,2.8,"#fff2b6")
    return img


def flock(t):
    img=painted_sky("flock").copy()
    clouds(img,t,33,((22,38,69),(72,68,116)),8)
    d=ImageDraw.Draw(img)
    for x,y,s,_ in seeded_particles(24,22):
        if y<300:
            oval(d,x,y,s*.4,s*.4,"#abbccf")
    ignite=ease((t-2.5)/.69)
    lighthouse(img,108,510,1.30,ignite,t)
    for idx in range(13):
        delta=t-idx*.125
        if delta < -.27:
            continue
        arrival=ease((delta+.27)/2.55)
        phase=delta*2.96+idx*.43
        r=(1-arrival)*(78+(idx%3)*5)+7
        x=108+math.cos(phase)*r
        y=202+math.sin(phase)*r*.57-(idx%5)*5
        if ignite > .2:
            leave=ease((t-2.86-idx*.05)/1.5)
            x+=math.cos(idx*1.7)*100*leave
            y-=105*leave
        fade=clamp((t-idx*.03+.38))
        glow(img,x,y+5,10,GOLD,110*fade)
        bird(img,x,y,.42+.09*(idx%3),delta+.13*idx,1 if math.sin(phase)<0 else -1,
             color=(251,237,213))
        d=ImageDraw.Draw(img)
        if ignite<.89:
            star(d,x,y+6,3,"#fff3bd")
    robot(img,135,248,.62,0,-1,.15*ignite,0,sad=ignite<.3,bob=False)
    if ignite:
        glow(img,108,201,round(35+18*ignite),GOLD,180*ignite)
        d=ImageDraw.Draw(img)
        star(d,108,201,6+2*math.sin(t*7),"#fff7c7")
        drifters(img,t,87,25,141,198,"#f8d2a4")
    return img


def home(t):
    img=Image.blend(painted_sky("port"),painted_sky("home"),.48+.52*ease(t/2.9))
    rise=ease((t-.05)/3.25)
    d=ImageDraw.Draw(img)
    oval(d,155,251-44*rise,34,34,"#f1bb98")
    glow(img,155,251-44*rise,66,(255,178,130),125)
    clouds(img,t,51,((91,72,111),(160,111,138)),6)
    city(img,t,409,25,.30+.7*ease(t/1.8),dawn=True,shift=0)
    water(img,t,411,.89,sun=True)
    lighthouse(img,162,397,.56,1,t,False)
    d=ImageDraw.Draw(img)
    slope(d,451,"#313454","#af7687")
    for i in range(7):
        x=4+i*30
        height=5+(i*7)%13
        line(d,[(x,494),(x+9,470-height),(x+11,462-height)],"#ab8599",1.1)
        oval(d,x+11,462-height,1.8,1.55,"#e8a886")
    robot(img,86,452,.91,0,1,1,0,bob=False)
    settle=ease(t/1.3)
    x=tween(164,117,settle)
    y=tween(370,389,settle)
    bird(img,x,y,.93,t,-1,t>1.25)
    spark=ease((t-.97)/.97)
    if .0<spark<1:
        sx, sy=tween(113,85,spark),tween(395,422,spark)
        glow(img,sx,sy,18,GOLD,165)
        star(ImageDraw.Draw(img),sx,sy,4,"#fff0bb")
    if t>1.84:
        glow(img,85,422,24,GOLD,95)
    drifters(img,t,75,19,225,206,(255,222,172))
    lettering(img,131,"借出去的光，",18,(255,239,216),ease((t-2.10)/.57))
    lettering(img,160,"飞了回来。",23,(255,244,219),ease((t-2.59)/.53),True)
    return img


SHOTS=(port, canal, fall, rescue, tower, flock, home)


def frame(seconds):
    index = min(len(SHOTS)-1, int(np.searchsorted(STARTS[1:], seconds, side="right")))
    local = seconds - STARTS[index]
    img = SHOTS[index](local)
    if index and local < .133:
        previous = SHOTS[index-1](LENGTHS[index-1] + local)
        img = Image.blend(previous,img,ease(local/.133))
    return img.convert("RGB")


def soundtrack(path):
    sr=44100
    n=np.arange(sr*DURATION)/sr
    music=np.zeros(len(n))
    rng=np.random.default_rng(412)
    water_noise=rng.normal(0,1,len(n))
    low=np.zeros_like(water_noise)
    for stride in (2, 13, 53, 159):
        source=water_noise[::stride]
        low+=np.interp(np.arange(len(n)),np.arange(len(source))*stride,source)/(5+stride**.18)
    storm=np.clip((n-4)/5,0,1)*np.clip((22-n)/5,0,1)
    music+=low*(.005+.038*storm)

    def note(at, hz, length, gain=.08, attack=.013):
        start=round(at*sr)
        t=np.arange(min(round(length*sr),len(music)-start))/sr
        if not len(t):
            return
        end=np.clip((length-t)/(.21*length),0,1)
        env=np.minimum(1,t/attack)*np.exp(-2.2*t/length)*end
        y=np.sin(TAU*hz*t)+.27*np.sin(TAU*hz*2.01*t)+.11*np.sin(TAU*hz*3.99*t)
        music[start:start+len(t)]+=y*env*gain

    motif=(261.63,329.63,392,440,523.25)
    for start, choice, gain in ((.32,(0,1,2,3),.05),(4.8,(1,2,1,0),.048),(9.0,(0,2,1,0),.034),
                                (14.8,(0,1,2),.04),(19.2,(0,1,2),.037),(22.3,(0,1,2,3,4),.075),
                                (25.3,(4,3,2,1),.066),(27.7,(0,1,2,4),.055)):
        note(start, motif[choice[0]]*.5,2.1,gain*.8,.12)
        for k,i in enumerate(choice):
            note(start+k*.27,motif[i],1.9,gain)
    for at,to in ((10.57,82),(13.8,126),(14.34,139),(22.94,659.25),(27.20,783.99)):
        note(at,to,.5,.095,.02)
    for k in (0.0,.12,.23):
        note(23.0+k,523.25*(1+k*.5),2.4,.055,.04)
    output=np.clip(music*np.minimum(1,n/.2)*np.clip((30-n)/.7,0,1),-.86,.86)
    with wave.open(str(path),"wb") as f:
        f.setparams((1,2,sr,0,"NONE",""))
        f.writeframes(np.int16(output*32767).tobytes())


def encode(mp4):
    audio=ROOT/"score.wav"
    soundtrack(audio)
    args=[get_ffmpeg_exe(),"-hide_banner","-loglevel","error","-y","-f","rawvideo",
          "-pixel_format","rgb24","-video_size",f"{SIZE[0]}x{SIZE[1]}","-framerate",str(FPS),
          "-i","pipe:0","-i",str(audio),"-map","0:v:0","-map","1:a:0",
          "-c:v","libx264","-preset","fast","-crf","16","-pix_fmt","yuv420p",
          "-c:a","aac","-b:a","112k","-movflags","+faststart","-shortest",str(mp4)]
    with subprocess.Popen(args,stdin=subprocess.PIPE) as encoder:
        for idx in range(DURATION*FPS):
            encoder.stdin.write(frame(idx/FPS).tobytes())
            if idx%150==0:
                print(f"Rendered {idx // FPS:02d} / {DURATION} seconds",flush=True)
        encoder.stdin.close()
        if encoder.wait():
            raise RuntimeError("FFmpeg could not finish the film")


def contact_sheet():
    images=[frame(t).resize((127,312),Image.Resampling.LANCZOS)
            for t in (0.9,3.65,6.8,9.75,11.85,14.1,16.55,19.6,22.4,24.1,27,29.8)]
    tile=145,339
    page=Image.new("RGB",(tile[0]*6+12,tile[1]*2+12),"#121926")
    d=ImageDraw.Draw(page)
    for i,(img,t) in enumerate(zip(images,(0.9,3.65,6.8,9.75,11.85,14.1,16.55,19.6,22.4,24.1,27,29.8))):
        x,y=13+(i%6)*tile[0],9+(i//6)*tile[1]
        page.paste(img,(x,y))
        d.text((x,y+315),f"{t:04.1f} s",font=font(7),fill="#becada")
    page.save(ROOT/"storyboard.png")


if __name__ == "__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--stills", action="store_true")
    args=cli.parse_args()
    contact_sheet()
    if not args.stills:
        encode(ROOT/"lampwings.mp4")
