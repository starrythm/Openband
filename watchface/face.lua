-- Native Lua watch face for Xiaomi Smart Band 10, 212 x 520 pixels.
-- The build supplies the sky module and observer coordinates.
local lvgl = require('lvgl')
local dataman = require('dataman')
local W, H, horizon = 212, 520, 405
local sky_top, sky_height = 86, 300
local background, grid, dim = 0x000008, 0x55aad2, 0x4682a5
local white = 0xe8edf6
local bodies = {
  { name='SUN', color=0xffbe00, radius=7 },
  { name='MOON', color=0xd2dcff, radius=6 },
  { name='MERCURY', color=0xafa596, radius=4 },
  { name='VENUS', color=0xffe19b, radius=6 },
  { name='MARS', color=0xff461e, radius=5 },
  { name='JUPITER', color=0xebb269, radius=6 },
  { name='SATURN', color=0xe6cd7d, radius=6 },
  { name='URANUS', color=0x73dce1, radius=5 },
  { name='NEPTUNE', color=0x4b73ff, radius=5 },
}
local stars = {
 {14,35,1},{31,62,1},{48,28,2},{66,86,1},{82,46,1},{99,104,2},{116,34,1},{134,73,1},
 {151,24,2},{169,97,1},{187,51,1},{207,114,2},{226,39,1},{22,127,1},{43,151,2},{61,112,1},
 {78,139,1},{96,68,1},{114,157,2},{132,119,1},{149,145,1},{166,57,2},{183,132,1},{201,79,1},
 {219,156,2},{27,94,1},{54,43,1},{72,163,1},{105,126,1},{141,42,1},{176,160,1},{214,67,1}
}
local function round(x) return math.floor(x + .5) end
local function clamp(x,a,b) return math.max(a,math.min(b,x)) end
local root = lvgl.Object(nil, {w=W,h=H,pad_all=0,border_width=0,outline_width=0,
  bg_color=background,bg_opa=lvgl.OPA(100)})
root:clear_flag(lvgl.FLAG.SCROLLABLE)
root:add_flag(lvgl.FLAG.EVENT_BUBBLE)
local function rect(x,y,w,h,color,radius)
  local o=lvgl.Object(root, {x=x,y=y,w=w,h=h,radius=radius or 0,pad_all=0,
    border_width=0,outline_width=0,bg_color=color,bg_opa=lvgl.OPA(100)})
  o:clear_flag(lvgl.FLAG.SCROLLABLE)
  return o
end
local function label(x,y,text,size,color)
  return lvgl.Label(root, {x=x,y=y,text=text,text_color=color or white,
    text_font=lvgl.Font('MiSans-Regular',size),pad_all=0,border_width=0})
end
local labelFonts={[12]=lvgl.Font('MiSans-Regular',12),[13]=lvgl.Font('MiSans-Regular',13)}
local function show(o, visible)
  if visible then o:clear_flag(lvgl.FLAG.HIDDEN) else o:add_flag(lvgl.FLAG.HIDDEN) end
end

label(72,25,'MICRO STAR',14,dim)
local clock = label(51,43,'00:00',38,white)
local star_objs={}
for i,star in ipairs(stars) do
  local x=round(7+star[1]*198/240)
  local y=round(sky_top+star[2]*270/180)
  local size=star[3]==2 and 3 or 2
  star_objs[i]=rect(x,y,size,size,0xced7e8,size)
end
rect(5,horizon,202,1,grid)
local ticks={8,57,106,155,204}
local dirs={'N','W','S','E','N'}
local degrees={'360','270','180','90','0'}
for i,x in ipairs(ticks) do
  rect(x,horizon-3,1,7,dim)
  label(clamp(x-5,4,198),horizon+9,dirs[i],16,dim)
  local dx = i==1 and 0 or (i==5 and 3 or 10)
  label(clamp(x-dx,2,198),horizon+30,degrees[i],12,0x376987)
end
-- Allocate once and update only positions and visibility on refresh.
local marks={}
for i,b in ipairs(bodies) do
  marks[i]={shadow=rect(0,0,2,2,background,10),dot=rect(0,0,2,2,b.color,10),
            stem=rect(0,0,7,2,b.color),labelBg=rect(0,0,2,2,background),
            name=label(0,0,b.name,13,b.color)}
  if i==7 then marks[i].ring=rect(0,0,2,2,b.color,4) end
end
local data,last_calc,last_clock = nil,0,''
local boxes={}
local function overlaps(x,y,w,h)
  if x < 2 or y < sky_top or x+w > W-2 or y+h > horizon-5 then return true end
  for _,b in ipairs(boxes) do
    if x < b.x+b.w+3 and x+w+3 > b.x and y < b.y+b.h+3 and y+h+3 > b.y then return true end
  end
  return false
end
-- Conservative widths for 13px Latin glyphs. The 4% reserve keeps labels
-- separated when MiSans renders slightly wider than the desktop preview.
local glyphWidths={A=9,B=8,C=9,D=10,E=7,F=7,G=10,H=10,I=4,J=5,K=8,L=7,M=13,
  N=11,O=11,P=8,Q=11,R=8,S=8,T=7,U=10,V=9,W=13,X=8,Y=8,Z=8,
  ['(']=4,[')']=4,[' ']=4,['+']=10,['-']=6,['.']=3,['%']=12}
local function labelWidth(s)
  local n=0
  for j=1,#s do n=n+(glyphWidths[s:sub(j,j)] or 8) end
  return math.ceil(n*1.04+2)
end
local function details(i,b)
  local n=bodies[i].name
  if b.alt<4 then return n end
  if i==2 then return string.format('%s (A%03.0f H%+03.0f %2.0f%% M%+.1f)',n,b.az,b.alt,b.phase*100,b.mag) end
  return string.format('%s (A%03.0f H%+03.0f)',n,b.az,b.alt)
end
local function tryPlacement(x,y,w,h)
  x=clamp(round(x),2,W-w-2)
  y=clamp(round(y),sky_top,horizon-h-5)
  if overlaps(x,y,w,h) then return nil end
  return {x=x,y=y,w=w,h=h}
end
local function update_map(now)
  data=sky.compute(now,latitude,longitude)
  last_calc=now
  local depth=clamp(-data[1].alt/12,0,1)
  local n=round(depth*#stars)
  local brightness=55+round(150*depth)
  for i,o in ipairs(star_objs) do
    show(o,i<=n and depth>0)
    if i<=n then o:set({bg_opa=lvgl.OPA(clamp(round((brightness+(i-1)%3*12)*100/255),0,100))}) end
  end
  boxes={}
  for i,b in ipairs(data) do
    local m,style=marks[i],bodies[i]
    local visible=b.alt>0
    show(m.shadow,visible); show(m.dot,visible); show(m.stem,visible)
    show(m.name,false); show(m.labelBg,false)
    if m.ring then show(m.ring,visible) end
    if visible then
      local x=round(8+(360-(b.az%360))*196/360)
      local y=round(horizon-sky_height*math.sin(clamp(b.alt,0,90)*math.pi/180))
      local v=clamp(b.alt/4,0,1); v=v*v*(3-2*v)
      local r=math.max(1,round(style.radius*v))
      m.shadow:set({x=x-r-2,y=y-r-2,w=2*r+5,h=2*r+5,radius=r+3})
      m.dot:set({x=x-r,y=y-r,w=2*r+1,h=2*r+1,radius=r+1})
      m.stem:set({x=x-3,y=horizon-1,w=7,h=2})
      if m.ring then m.ring:set({x=x-r-3,y=y-1,w=2*r+7,h=3,radius=2}) end
      boxes[#boxes+1]={x=x-r-4,y=y-r-4,w=2*r+9,h=2*r+9}
    end
  end
  -- The label placement searches around each body, then progressively
  -- farther away, then scans the chart. Markers and earlier labels are reserved.
  for i,b in ipairs(data) do
    if b.alt>=1.25 then
      local x=round(8+(360-(b.az%360))*196/360)
      local y=round(horizon-sky_height*math.sin(clamp(b.alt,0,90)*math.pi/180))
      local v=clamp(b.alt/4,0,1); v=v*v*(3-2*v)
      local radius=math.max(1,round(bodies[i].radius*v))
      local content=details(i,b)
      local width,height=labelWidth(content),16
      -- An unusually long value gets a smaller font rather than being clipped.
      local fontSize=13
      if width>W-4 then fontSize=12; width=math.ceil(width*12/13) end
      local center=x-width/2
      local left=x-radius-3-width
      local right=x+radius+3
      local above=y-radius-height-3
      local below=y+radius+3
      local extraBelow=y+radius+height+4
      local middle=y-height/2
      local candidates
      if i==1 then
        candidates={{center,above},{left,above},{right,above},{center,below},
                    {left,below},{right,below},{right,middle},{left,middle}}
      elseif i>=3 then
        candidates={{center,extraBelow},{right,extraBelow},{left,extraBelow},{center,above},
                    {right,above},{left,above},{right,middle},{left,middle}}
      else
        candidates={{right,middle},{left,middle},{center,above},{center,below},
                    {right,above},{left,above},{right,below},{left,below}}
      end
      local box=nil
      for _,p in ipairs(candidates) do
        box=tryPlacement(p[1],p[2],width,height)
        if box then break end
      end
      for distance=10,150,10 do
        if box then break end
        for _,trialY in ipairs({above-distance,below+distance}) do
          for _,trialX in ipairs({center,right,left}) do
            box=tryPlacement(trialX,trialY,width,height)
            if box then break end
          end
          if box then break end
        end
      end
      for trialY=sky_top,horizon-height-6,2 do
        if box then break end
        for _,trialX in ipairs({2,(W-width)/2,W-width-2}) do
          box=tryPlacement(trialX,trialY,width,height)
          if box then break end
        end
      end
      if box then
        local mark=marks[i]
        mark.labelBg:set({x=box.x-1,y=box.y-1,w=box.w+2,h=box.h+2})
        mark.name:set({x=box.x,y=box.y,text=content,text_font=labelFonts[fontSize]})
        show(mark.labelBg,true); show(mark.name,true)
        boxes[#boxes+1]=box
      end
    end
  end
end
local function update(now)
  local s=os.date('%H:%M',now)
  if s~=last_clock then clock:set({text=s});last_clock=s end
  if not data or now-last_calc>=30 or now<last_calc then update_map(now) end
end
update(os.time())
dataman.subscribe('timeSecond',clock,function() update(os.time()) end)
function ScreenStateChangedCB(pre,now,reason)
  if pre~='ON' and now=='ON' then update(os.time()) end
end
