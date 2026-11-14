-- Exercise the generated watchface without a physical device.
local fake_time=tonumber(arg[2])
local original_date=os.date
os.time=function() return fake_time end
os.date=function(fmt, t) return original_date(fmt,t or fake_time) end
local objects, callbacks = {}, {}
local function make(kind,parent,props)
  local obj={kind=kind,props=props or {},flags={}}
  function obj:set(p) for k,v in pairs(p) do self.props[k]=v end end
  function obj:add_flag(f) self.flags[f]=true end
  function obj:clear_flag(f) self.flags[f]=false end
  objects[#objects+1]=obj
  return obj
end
package.preload.lvgl=function()
  return {Object=function(parent,props) return make('rect',parent,props) end,
    Label=function(parent,props) return make('label',parent,props) end,
    Font=function(name,size) return size end, OPA=function(v) return v end,
    FLAG={SCROLLABLE=1,EVENT_BUBBLE=2,HIDDEN=3}}
end
package.preload.dataman=function()
  return {subscribe=function(name,obj,cb) callbacks[name]=cb end}
end
assert(loadfile(arg[1]))()
assert(callbacks.timeSecond,'Missing clock subscription')
fake_time=fake_time+tonumber(arg[3] or '0')
callbacks.timeSecond(nil,0)
if ScreenStateChangedCB then ScreenStateChangedCB('OFF','ON','test') end
for _,o in ipairs(objects) do
  local p=o.props
  local txt=(p.text or ''):gsub('|','/'):gsub('\n',' ')
  print(table.concat({o.kind,p.x or 0,p.y or 0,p.w or 0,p.h or 0,
    p.radius or 0,p.bg_color or p.text_color or 0,p.bg_opa or 100,
    o.flags[3] and 1 or 0,p.text_font or 0,txt},'|'))
end
