local sky = dofile('watchface/sky.lua')
local latitude, longitude = assert(tonumber(arg[1])), assert(tonumber(arg[2]))
for index = 3, #arg do
  local epoch = tonumber(arg[index])
  local result = sky.compute(epoch, latitude, longitude)
  for _, item in ipairs(result) do
    print(string.format('%d,%s,%.9f,%.9f,%.9f,%.9f', epoch, item.name,
      item.az, item.alt, item.phase or -1, item.mag or -100))
  end
end
