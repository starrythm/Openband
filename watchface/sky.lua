-- Offline low-precision solar-system positions for a fixed observer.
-- Orbital elements and perturbations: Paul Schlyter, "How to compute
-- planetary positions", https://www.stjarnhimlen.se/comp/ppcomp.html
-- Compared separately against Astronomy Engine.
local sky = {}
local pi, sin, cos, sqrt, atan, asin = math.pi, math.sin, math.cos, math.sqrt, math.atan, math.asin
local rad, deg = pi / 180, 180 / pi
local function norm(x) return x % 360 end
local function sd(x) return sin(x * rad) end
local function cd(x) return cos(x * rad) end
local function ad(y, x) return atan(y, x) * deg end
local function clamp(x, lo, hi) return math.max(lo, math.min(hi, x)) end

local function elements(name, d)
  if name == 'Sun' then return 0, 0, 282.9404+4.70935e-5*d, 1, .016709-1.151e-9*d, 356.0470+.9856002585*d end
  if name == 'Moon' then return 125.1228-.0529538083*d, 5.1454, 318.0634+.1643573223*d, 60.2666, .0549, 115.3654+13.0649929509*d end
  if name == 'Mercury' then return 48.3313+3.24587e-5*d, 7.0047+5e-8*d, 29.1241+1.01444e-5*d, .387098, .205635+5.59e-10*d, 168.6562+4.0923344368*d end
  if name == 'Venus' then return 76.6799+2.46590e-5*d, 3.3946+2.75e-8*d, 54.8910+1.38374e-5*d, .723330, .006773-1.302e-9*d, 48.0052+1.6021302244*d end
  if name == 'Mars' then return 49.5574+2.11081e-5*d, 1.8497-1.78e-8*d, 286.5016+2.92961e-5*d, 1.523688, .093405+2.516e-9*d, 18.6021+.5240207766*d end
  if name == 'Jupiter' then return 100.4542+2.76854e-5*d, 1.3030-1.557e-7*d, 273.8777+1.64505e-5*d, 5.20256, .048498+4.469e-9*d, 19.8950+.0830853001*d end
  if name == 'Saturn' then return 113.6634+2.38980e-5*d, 2.4886-1.081e-7*d, 339.3939+2.97661e-5*d, 9.55475, .055546-9.499e-9*d, 316.9670+.0334442282*d end
  if name == 'Uranus' then return 74.0005+1.3978e-5*d, .7733+1.9e-8*d, 96.6612+3.0565e-5*d, 19.18171-1.55e-8*d, .047318+7.45e-9*d, 142.5905+.011725806*d end
  if name == 'Neptune' then return 131.7806+3.0173e-5*d, 1.7700-2.55e-7*d, 272.8461-6.027e-6*d, 30.05826+3.313e-8*d, .008606+2.15e-9*d, 260.2471+.005995147*d end
  error('unknown body')
end

local function orbit(name, d)
  local N, inc, w, a, e, M = elements(name, d)
  N, w, M = norm(N), norm(w), norm(M)
  local m = M * rad
  local E = m + e * sin(m) * (1 + e * cos(m))
  for _=1,6 do E = E - (E - e*sin(E) - m) / (1 - e*cos(E)) end
  local xv, yv = a*(cos(E)-e), a*sqrt(1-e*e)*sin(E)
  local v, r = ad(yv,xv), sqrt(xv*xv+yv*yv)
  local x = r*(cd(N)*cd(v+w)-sd(N)*sd(v+w)*cd(inc))
  local y = r*(sd(N)*cd(v+w)+cd(N)*sd(v+w)*cd(inc))
  local z = r*sd(v+w)*sd(inc)
  return {x=x,y=y,z=z,r=r,lon=norm(ad(y,x)),lat=ad(z,sqrt(x*x+y*y)),M=M,N=N,w=w}
end

local function perturb(p, name, d, sun)
  local lon, lat, r = p.lon, p.lat, p.r
  if name == 'Moon' then
    local mm, ms = p.M, sun.M
    local D = norm(p.M + p.w + p.N - (sun.M + sun.w))
    local F = norm(p.M + p.w)
    lon = lon - 1.274*sd(mm-2*D) + .658*sd(2*D) - .186*sd(ms)
      - .059*sd(2*mm-2*D) - .057*sd(mm-2*D+ms) + .053*sd(mm+2*D)
      + .046*sd(2*D-ms) + .041*sd(mm-ms) - .035*sd(D) - .031*sd(mm+ms)
      - .015*sd(2*F-2*D) + .011*sd(mm-4*D)
    lat = lat - .173*sd(F-2*D) - .055*sd(mm-F-2*D) - .046*sd(mm+F-2*D)
      + .033*sd(F+2*D) + .017*sd(2*mm+F)
    r = r - .58*cd(mm-2*D) - .46*cd(2*D)
  elseif name == 'Jupiter' or name == 'Saturn' or name == 'Uranus' then
    local _,_,_,_,_,mj = elements('Jupiter',d)
    local _,_,_,_,_,ms = elements('Saturn',d)
    local _,_,_,_,_,mu = elements('Uranus',d)
    mj, ms, mu = norm(mj), norm(ms), norm(mu)
    if name == 'Jupiter' then
      lon = lon - .332*sd(2*mj-5*ms-67.6) - .056*sd(2*mj-2*ms+21)
        + .042*sd(3*mj-5*ms+21) - .036*sd(mj-2*ms) + .022*cd(mj-ms)
        + .023*sd(2*mj-3*ms+52) - .016*sd(mj-5*ms-69)
    elseif name == 'Saturn' then
      lon = lon + .812*sd(2*mj-5*ms-67.6) - .229*cd(2*mj-4*ms-2)
        + .119*sd(mj-2*ms-3) + .046*sd(2*mj-6*ms-69) + .014*sd(mj-3*ms+32)
      lat = lat - .020*cd(2*mj-4*ms-2) + .018*sd(2*mj-6*ms-49)
    else
      lon = lon + .040*sd(ms-2*mu+6) + .035*sd(ms-3*mu+33) - .015*sd(mj-mu+20)
    end
  end
  p.lon, p.lat, p.r = norm(lon), lat, r
  p.x, p.y, p.z = r*cd(lon)*cd(lat), r*sd(lon)*cd(lat), r*sd(lat)
  return p
end

local function horizontal(x, y, z, d, epoch, latitude, longitude, units)
  local ob = 23.4393 - 3.563e-7*d
  local xe, ye, ze = x, y*cd(ob)-z*sd(ob), y*sd(ob)+z*cd(ob)
  local jd = epoch / 86400 + 2440587.5
  local T = (jd - 2451545.0) / 36525
  local lst = norm(280.46061837 + 360.98564736629*(jd-2451545) + .000387933*T*T - T*T*T/38710000 + longitude)
  local gclat = latitude - .1924*sd(2*latitude)
  local rho = .99833 + .00167*cd(2*latitude)
  local earth = units == 'earth' and 1 or (1 / 23454.79)
  xe = xe - earth*rho*cd(gclat)*cd(lst)
  ye = ye - earth*rho*cd(gclat)*sd(lst)
  ze = ze - earth*rho*sd(gclat)
  local ra = norm(ad(ye,xe))
  local dec = ad(ze,sqrt(xe*xe+ye*ye))
  local ha = norm(lst-ra)
  local xh = cd(ha)*cd(dec)*sd(latitude)-sd(dec)*cd(latitude)
  local yh = sd(ha)*cd(dec)
  local zh = cd(ha)*cd(dec)*cd(latitude)+sd(dec)*sd(latitude)
  local az = norm(ad(yh,xh)+180)
  local alt = ad(zh,sqrt(xh*xh+yh*yh))
  -- Match the original application's normal refraction convention.
  local hd = math.max(alt, -1)
  local refr = (1.02 / math.tan((hd + 10.3/(hd+5.11))*rad)) / 60
  if alt < -1 then refr = refr * (alt + 90) / 89 end
  alt = alt + refr
  return az, alt
end

local function magnitude(name, r, R, sun_r, d, gx, gy, gz)
  local f = math.acos(clamp((r*r + R*R - sun_r*sun_r)/(2*r*R), -1, 1))*deg
  local common = 5 * (math.log(r*R)/math.log(10))
  -- Match the original project's Astronomy Engine visual magnitude models.
  local x = f/100
  if name == 'Mercury' then return -.60+common+x*(4.98+x*(-4.88+x*3.02)) end
  if name == 'Venus' then
    if f < 163.6 then return -4.47+common+x*(1.03+x*(.57+x*.13)) end
    return .98+common-1.02*x
  end
  if name == 'Mars' then return -1.52+common+1.60*x end
  if name == 'Jupiter' then return -9.40+common+.50*x end
  if name == 'Saturn' then
    local lon, lat = ad(gy,gx), ad(gz,sqrt(gx*gx+gy*gy))
    local B = asin(sd(lat)*cd(28.06)-cd(lat)*sd(28.06)*sd(lon-(169.51+3.82e-5*d)))
    local rings = -2.6*math.abs(sin(B)) + 1.2*sin(B)^2
    return -9+common+.044*f+rings
  end
  if name == 'Uranus' then return -7.19+common+.25*x end
  return -6.87+common
end

local names = {'Sun','Moon','Mercury','Venus','Mars','Jupiter','Saturn','Uranus','Neptune'}
function sky.compute(epoch, latitude, longitude)
  assert(type(epoch)=='number' and latitude >= -90 and latitude <= 90 and longitude >= -180 and longitude <= 180)
  local d = epoch/86400 - 10956
  local sun = orbit('Sun',d)
  local result = {}
  for _, name in ipairs(names) do
    local p = name == 'Sun' and sun or perturb(orbit(name,d),name,d,sun)
    local gx, gy, gz = p.x, p.y, p.z
    if name ~= 'Sun' and name ~= 'Moon' then gx,gy = gx+sun.x,gy+sun.y end
    local az, alt = horizontal(gx,gy,gz,d,epoch,latitude,longitude,name == 'Moon' and 'earth' or 'au')
    local item = {name=name, az=az, alt=alt}
    if name == 'Moon' then
      item.phase = (1 - cd(p.lon - sun.lon)*cd(p.lat))/2
      -- Astronomy Engine's lunar visual-magnitude model, using the same
      -- low-precision geocentric/heliocentric geometry as this port.
      local mx,my,mz=p.x/23454.79,p.y/23454.79,p.z/23454.79
      local hx,hy,hz=mx-sun.x,my-sun.y,mz
      local geo=sqrt(mx*mx+my*my+mz*mz)
      local helio=sqrt(hx*hx+hy*hy+hz*hz)
      local phase_angle=math.acos(clamp((mx*hx+my*hy+mz*hz)/(geo*helio),-1,1))
      local mean_moon_au=385000.6/149597870.7
      item.mag=-12.717+1.49*math.abs(phase_angle)+.0431*phase_angle^4
        +5*math.log(helio*geo/mean_moon_au)/math.log(10)
    elseif name ~= 'Sun' then
      local R = sqrt(gx*gx+gy*gy+gz*gz)
      item.mag = magnitude(name,p.r,R,sun.r,d,gx,gy,gz)
    end
    result[#result+1] = item
  end
  return result
end
return sky
