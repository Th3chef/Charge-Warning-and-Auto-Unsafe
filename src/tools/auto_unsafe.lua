-- HD2-Addon: mods/chef/railgun_auto_unsafe
-- Railgun Warning & Auto Unsafe - Auto unsafe mode (optional part; Bingus Shared Loader v15+ addon).
-- Every new Railgun you pick up starts in Unsafe mode instead of Safe. It is set once per Railgun: switch back to
-- Safe yourself and it stays Safe. Only your own Railgun is touched.
-- How: the weapon component keeps a small mode entry per weapon (12 bytes: +0 fire mode - the Railgun: 5 = Safe,
-- 6 = Unsafe - and +5 a flag byte with 16 set in Unsafe), which the game copies into the weapon record (+24) every
-- frame. Every quarter second the addon looks up your helldiver's support weapon; when it is a Railgun it hasn't
-- seen yet and in Safe mode, it writes Unsafe into the mode entry once (and the copy), then checks the game took it.
-- A weapon only counts as a Railgun when its entity type is the RS-422 Railgun's (resource hash 2e9d0bdc48b09e60, the
-- same in every game build): other charge weapons such as the Arc Thrower use the same fire mode numbers, and switching
-- those to "unsafe" made them overload and blow up. Anything that can't be confirmed as the Railgun is left alone.
-- (Found with two read-only diagnostics, Oct 2026 game: writing only the copy was undone by the game within 0.1 s.) Everything it needs is found by scanning the game's code at start-up, so a game patch
-- that moves things around doesn't break it; if something isn't found it stays off and says so in its log
-- (RailgunAutoUnsafe.log next to the other Bingus mods' logs).
if rawget(_G, 'RailgunAutoUnsafe') then return end
local VERSION = '@@VERSION@@'
local TESTER = @@TESTER@@                -- tester builds (numbered tests and the release Tester): extra lines in the log
local TEST_BUILD = @@TESTBUILD@@            -- numbered test builds log into the Logs\test folder; releases and the Tester don't
local RAU = { status = 'starting', set = 0, seen = 0 }
rawset(_G, 'RailgunAutoUnsafe', RAU)

local ffi = require('ffi')
local bit = require('bit')
for _, d in ipairs({
  'typedef struct { void *base; void *alloc_base; uint32_t alloc_protect; uint16_t partition; uint16_t pad; size_t size; uint32_t state; uint32_t protect; uint32_t type; } RauRegion;',
  'void *RauGetModuleHandleA(const char *name) __asm__("GetModuleHandleA");',
  'void *RauGetCurrentProcess(void) __asm__("GetCurrentProcess");',
  'int RauReadProcessMemory(void *process, const void *address, void *buffer, size_t size, size_t *done) __asm__("ReadProcessMemory");',
  'int RauWriteProcessMemory(void *process, void *address, const void *buffer, size_t size, size_t *done) __asm__("WriteProcessMemory");',
  'size_t RauVirtualQuery(const void *address, void *region, size_t size) __asm__("VirtualQuery");',
}) do pcall(ffi.cdef, d) end
local K32 = ffi.load('kernel32')
local PROCESS = K32.RauGetCurrentProcess()
local T0 = os.clock()

-- the Railgun's fire modes in its weapon record (found with the Railgun Mode Finder diagnostic, Oct 2026 game)
local MODE_AT, SAFE, UNSAFE = 24, 5, 6
local WEAPON_STRIDE = 1008
local STATES_AT, STATE_STRIDE, FLAG_AT, UNSAFE_FLAG = 96, 12, 5, 16   -- the weapon component's mode entries
local POLL_SECONDS = 0.25
-- what a Railgun is: its entity type (resource hash of the weapon entity's name; it never changes with a game patch)
local function type_bytes(hex) return (hex:gsub('..', function(x) return string.char(tonumber(x, 16)) end):reverse()) end
local RAILGUN_TYPE = type_bytes('2e9d0bdc48b09e60')
local TYPE_NAMES = { [RAILGUN_TYPE] = 'RS-422 Railgun', [type_bytes('96de9cd50f7306e6')] = 'ARC-3 Arc Thrower' }
local OWNER_ROW_COUNT, OWNER_ROW_SIZE = 2048, 24    -- the game's owner table (2048 rows of 24 bytes; type at +0, id at +8)
local TYPE_TRIES = 8                                -- polls to wait for a new weapon's owner row before leaving it alone

-- ---------------------------------------------------------------------------------------------- log
local LOGFILE
do
  local base = os.getenv('LOCALAPPDATA')
  if base then
    local dir = base .. '\\CowboyBingus\\Helldivers2\\Logs' .. (TEST_BUILD and '\\test' or '')
    local f = io.open(dir .. '\\RailgunAutoUnsafe.log', 'a')
    if f then f:close(); LOGFILE = dir .. '\\RailgunAutoUnsafe.log' else LOGFILE = base .. '\\RailgunAutoUnsafe.log' end
  end
end
local notes, events, dirty = {}, {}, true
local function note(s) if #notes < 40 then notes[#notes + 1] = s end; dirty = true end
local function event(s)
  events[#events + 1] = string.format('%8.1fs  %s', os.clock() - T0, s)
  if #events > 40 then table.remove(events, 1) end
  dirty = true
end
local function write_log()
  dirty = false
  if not LOGFILE then return end
  local f = io.open(LOGFILE, 'w')
  if not f then return end
  f:write('Railgun Warning & Auto Unsafe - Auto unsafe mode ' .. VERSION .. (TESTER and ' (tester)' or '') .. '\n')
  f:write('started ' .. os.date('%Y-%m-%d %H:%M') .. ', running for ' .. string.format('%.0f', os.clock() - T0) .. ' s\n')
  for _, n in ipairs(notes) do f:write(n .. '\n') end
  f:write(string.format('status: %s\nRailguns set to Unsafe: %d (Railguns seen: %d)\n', tostring(RAU.status), RAU.set, RAU.seen))
  f:write('recent events:\n')
  for _, e in ipairs(events) do f:write('  ' .. e .. '\n') end
  f:close()
end

-- ---------------------------------------------------------------------------------------------- memory
local DONE = ffi.new('size_t[1]')
local SMALL = ffi.new('uint8_t[4096]')
local function read(addr, n)
  if type(addr) ~= 'number' or addr < 65536 or n <= 0 then return nil end
  local buf = n <= 4096 and SMALL or ffi.new('uint8_t[?]', n)
  if K32.RauReadProcessMemory(PROCESS, ffi.cast('const void *', addr), buf, n, DONE) == 0 or DONE[0] ~= n then return nil end
  return ffi.string(buf, n)
end
local function u32(s, o) local a, b, c, d = s:byte(o + 1, o + 4); return a + b * 256 + c * 65536 + d * 16777216 end
local function u64(s, o) return u32(s, o) + u32(s, o + 4) * 4294967296 end
local function si32(t, o) local v = u32(t, o); return v >= 2147483648 and v - 4294967296 or v end
local function need(v, what) if v == nil or v == false then error(what, 0) end return v end
local function rd(addr, n, what) return need(read(addr, n), what) end
local function rptr(addr, what)
  local s = rd(addr, 8, what)
  local p = u64(s, 0)
  need(p >= 65536 and p < 140737488355328, what)
  return p
end
local REGION = ffi.new('RauRegion[1]')
local function writable(addr, n)
  if K32.RauVirtualQuery(ffi.cast('const void *', addr), REGION, ffi.sizeof('RauRegion')) == 0 then return false end
  local r = REGION[0]
  local base = tonumber(ffi.cast('uintptr_t', r.base))
  -- committed, private, plain read/write memory only, and the whole value inside that region
  return r.state == 0x1000 and r.type == 0x20000 and r.protect == 0x04 and addr + n <= base + tonumber(r.size)
end
local function write_u8(addr, v)
  if not writable(addr, 1) then return false end
  local b = ffi.new('uint8_t[1]', v)
  if K32.RauWriteProcessMemory(PROCESS, ffi.cast('void *', addr), b, 1, DONE) == 0 or DONE[0] ~= 1 then return false end
  local back = read(addr, 1)
  return back ~= nil and back:byte(1) == v
end
local function write_u32(addr, v)
  if not writable(addr, 4) then return false end
  local b = ffi.new('uint32_t[1]', v)
  if K32.RauWriteProcessMemory(PROCESS, ffi.cast('void *', addr), b, 4, DONE) == 0 or DONE[0] ~= 4 then return false end
  local back = read(addr, 4)
  return back ~= nil and u32(back, 0) == v
end

-- the game's component managers keep an open-addressing map { slots*, capacity, empty key, multiplier }
local function map_lookup(addr, key, max_capacity)
  local h = rd(addr, 20, 'map header')
  local cap, empty, mult = u32(h, 8), u32(h, 12), u32(h, 16)
  if cap == 0 then return nil end
  need(cap <= max_capacity and bit.band(cap, cap - 1) == 0, 'map capacity')
  local slots = u64(h, 0)
  local mlo = mult % 65536
  local hash = (key * mlo + (key * ((mult - mlo) / 65536) % 65536) * 65536) % 4294967296
  for i = 0, math.min(cap, 128) - 1 do
    local e = rd(slots + 8 * bit.band(hash + i, cap - 1), 8, 'map slot')
    local k = u32(e, 0)
    if k == key then
      local v = u32(e, 4)
      return v ~= 4294967295 and v or nil
    end
    if k == empty then return nil end
  end
  error('map probe', 0)
end

-- ---------------------------------------------------------------------------------------------- finding things
-- wildcarded code patterns (shared with Smarter Guard Dogs & Sentries): each global must be found exactly once and
-- every pattern that matches must agree
local PATTERNS = {
  players = { { p = '488b05????????488d542448488b88e8000000', disp_at = 3, size = 7 }, { p = '488b15????????0fb6e883ba8400000000', disp_at = 3, size = 7 }, { p = '488b05????????3998840000000f86????????488b80e8000000488d542438448b4008e8????????8b4424383b05????????0f84????????4c8b0d????????48896c2430', disp_at = 3, size = 7 } },
  owners = { { p = '488b0d????????8b5008e8????????eb??488bcfe8????????ba5f218b6f488bcf', disp_at = 3, size = 7 }, { p = '488b0d????????8b5008e8????????bad8040000488bcbe8????????488b4308c74008ffffffff4883c4205bc3cccccc', disp_at = 3, size = 7 }, { p = '488b0d????????8b5008e8????????bad8040000488bcb4883c420', disp_at = 3, size = 7 } },
  equipment = { { p = '4c8b05????????33db8bcb458b4830458b5038', disp_at = 3, size = 7 }, { p = '4c8b0d????????48896c24304889742440', disp_at = 3, size = 7 }, { p = '4c8b0d????????48896c24404889742448458b4130458b5938', disp_at = 3, size = 7 } },
  weapons = { { p = '488b3d????????458bda8b77388b6f40', disp_at = 3, size = 7 }, { p = '4c8b1d????????4533f63b15????????', disp_at = 3, size = 7 }, { p = '488b3d????????413bd274??448b5738', disp_at = 3, size = 7 } },
}
local OWNER_INDEX = '458b93????????33d248895c241041????????????48896c2418410fafd8418d6aff488974242048893c244585d274??498bbb????????418bb3????????6666660f1f840000000000'
local OWNER_ROWS = '8b4104488d0c40488d85????????488d04c8eb??488d05????????'
local AVATAR_TYPE = ('4d1c334d294dfa97'):gsub('..', function(x) return string.char(tonumber(x, 16)) end):reverse()

-- game.dll's code section and a key for this game build (link time stamp, image size, code section place and size)
local function code_info(base)
  local hdr = rd(base, 4096, 'game.dll header')
  local pe = u32(hdr, 0x3c)
  local count, optsize = hdr:byte(pe + 7) + hdr:byte(pe + 8) * 256, hdr:byte(pe + 21) + hdr:byte(pe + 22) * 256
  for i = 0, count - 1 do
    local s = pe + 24 + optsize + 40 * i
    local vsize, rva, flags = u32(hdr, s + 8), u32(hdr, s + 12), u32(hdr, s + 36)
    if bit.band(flags, 0x20000000) ~= 0 and vsize > 0x100000 then
      return rva, vsize, string.format('%08x-%08x-%08x-%08x', u32(hdr, pe + 8), u32(hdr, pe + 0x50), rva, vsize)
    end
  end
  error('no code section', 0)
end

-- does the code at this offset match the pattern (?? = any byte)?
local function matches(bytes, p)
  if not bytes or #bytes ~= #p / 2 then return false end
  for k = 0, #p / 2 - 1 do
    local h = p:sub(2 * k + 1, 2 * k + 2)
    if h ~= '??' and bytes:byte(k + 1) ~= tonumber(h, 16) then return false end
  end
  return true
end

local function find_once(text, p)
  local segs, cur_off, cur = {}, nil, {}
  local n = #p / 2
  for k = 0, n - 1 do
    local h = p:sub(2 * k + 1, 2 * k + 2)
    if h == '??' then
      if cur_off then segs[#segs + 1] = { cur_off, table.concat(cur) }; cur_off, cur = nil, {} end
    else cur_off = cur_off or k; cur[#cur + 1] = string.char(tonumber(h, 16)) end
  end
  if cur_off then segs[#segs + 1] = { cur_off, table.concat(cur) } end
  local anchor = 1
  for j = 2, #segs do if #segs[j][2] > #segs[anchor][2] then anchor = j end end
  local a, init, found, count = segs[anchor], 1, nil, 0
  while true do
    local s = string.find(text, a[2], init, true)
    if not s then break end
    local start = s - 1 - a[1]
    local ok = start >= 0 and start + n <= #text
    if ok then
      for j, seg in ipairs(segs) do
        if j ~= anchor and text:sub(start + seg[1] + 1, start + seg[1] + #seg[2]) ~= seg[2] then ok = false; break end
      end
    end
    if ok then count = count + 1; found = start; if count > 1 then return nil end end
    init = s + 1
  end
  return found
end

local G = {}
local CACHE = os.getenv('LOCALAPPDATA') and (os.getenv('LOCALAPPDATA') .. '\\RailgunAutoUnsafe.cache')
-- what each found item is: { pattern, how its value is read } (a value is an address, or an offset for the owner table)
local function items()
  local list = {}
  for name, pats in pairs(PATTERNS) do
    for k, p in ipairs(pats) do
      list[#list + 1] = { key = name .. ' ' .. k, name = name, p = p.p, value = function(b, rva, o) return rva + o + p.size + si32(b, p.disp_at) end }
    end
  end
  list[#list + 1] = { key = 'owner_index 1', name = 'owner_index', p = OWNER_INDEX, value = function(b) return u32(b, 3) - 8 end }
  list[#list + 1] = { key = 'owner_rows 1', name = 'owner_rows', p = OWNER_ROWS, value = function(b) return u32(b, 10) - 8 end }
  return list
end
local function apply(gbase, values)
  for name in pairs(PATTERNS) do G[name] = gbase + values[name] end
  G.owner_index, G.owner_rows = values.owner_index, values.owner_rows
end

-- the cache: a line with the build key, then 'name k offset' for one place each item was found. On load every place is read
-- back and must still match its pattern; anything off and it scans the code again (a patch can't make it use stale places).
local function from_cache(gbase, rva, key)
  if not CACHE then return false end
  local f = io.open(CACHE, 'r')
  if not f then return false end
  local first, at = f:read('*l'), {}
  for line in f:lines() do
    local item, o = line:match('^(%S+ %d+) (%d+)$')
    if item then at[item] = tonumber(o) end
  end
  f:close()
  if first ~= 'key ' .. key then return false end
  local values = {}
  for _, it in ipairs(items()) do
    local o = at[it.key]
    if o and not values[it.name] then
      local b = read(gbase + rva + o, #it.p / 2)
      if not matches(b, it.p) then return false end
      values[it.name] = it.value(b, rva, o)
    end
  end
  for name in pairs(PATTERNS) do if not values[name] then return false end end
  if not (values.owner_index and values.owner_rows) then return false end
  apply(gbase, values)
  return true
end

local function find_layout()
  local game = K32.RauGetModuleHandleA('game.dll')
  need(game ~= nil, 'game.dll not loaded')
  local gbase = tonumber(ffi.cast('uintptr_t', game))
  local t = os.clock()
  local rva, vsize, key = code_info(gbase)
  if from_cache(gbase, rva, key) then note(string.format('game addresses: from the cache (%.2f s)', os.clock() - t)); return end
  local text = rd(gbase + rva, vsize, 'game code')
  local values, found = {}, {}
  for _, it in ipairs(items()) do
    local o = find_once(text, it.p)
    if o then
      local v = it.value(text:sub(o + 1, o + #it.p / 2), rva, o)
      need(not values[it.name] or values[it.name] == v, it.name .. ': patterns disagree')
      if not values[it.name] then values[it.name] = v; found[#found + 1] = it.key .. ' ' .. o end
    end
  end
  for name in pairs(PATTERNS) do need(values[name], name .. ': not found') end
  need(values.owner_index, 'owner map: not found')
  need(values.owner_rows, 'owner rows: not found')
  apply(gbase, values)
  note(string.format('game addresses: found by scanning the game code (%.2f s)', os.clock() - t))
  if CACHE then
    local f = io.open(CACHE, 'w')
    if f then f:write('key ' .. key .. '\n' .. table.concat(found, '\n') .. '\n'); f:close() end
  end
end

-- your helldiver's support weapon: entity id, or nil + why
local function my_support_weapon()
  local players = rptr(G.players, 'players')
  local pp = rd(players + 132, 808, 'players')     -- +132 players, +136 local players ... +936 your helldiver (one read)
  need(u32(pp, 0) <= 4 and u32(pp, 4) <= 4, 'player count')
  if u32(pp, 0) == 0 or u32(pp, 4) == 0 then return nil, 'no local player yet' end
  local avatar = u32(pp, 804)
  if avatar == 32767 then return nil, 'no helldiver' end
  local owners = rptr(G.owners, 'owners')
  local e = map_lookup(owners + G.owner_index, avatar, 1048576)
  if not e then return nil, 'no helldiver' end
  need(e < 262144, 'owner index')
  local me = rd(owners + G.owner_rows + e * 24, 24, 'owner row')
  if me:sub(1, 8) ~= AVATAR_TYPE or bit.band(me:byte(21), 3) ~= 1 then return nil, 'helldiver is not ours' end
  local equipment = rptr(G.equipment, 'equipment')
  local q = map_lookup(equipment + 40, u32(me, 8), 8192)
  if not q then return nil, 'no loadout' end
  need(q < 4096, 'equipment index')
  local slot = rd(rptr(equipment + 80, 'equipment slots') + q * 48, 12, 'equipment slot')
  local id = u32(slot, 8)                          -- +0 primary, +4 secondary, +8 support weapon, +12 backpack
  if id == 0 or id == 4294967295 then return nil, 'no support weapon' end
  return id
end


-- what kind of weapon an entity is: its 8-byte type from the game's owner table, or nil + why. Only rows whose id (+8) is
-- the weapon and that are marked as ours (byte 20 & 3 == 1, as for your helldiver) count, and they must all agree; a
-- weapon with no such row, or rows that disagree, is never treated as a Railgun.
local function hexof(t)
  local h = {}
  for i = #t, 1, -1 do h[#h + 1] = string.format('%02x', t:byte(i)) end
  return table.concat(h)
end
local function weapon_type(id)
  local owners = rptr(G.owners, 'owners')
  local all = rd(owners + G.owner_rows, OWNER_ROW_COUNT * OWNER_ROW_SIZE, 'owner rows')
  local found, rows, mine = nil, 0, 0
  for r = 0, OWNER_ROW_COUNT - 1 do
    local o = r * OWNER_ROW_SIZE
    if u32(all, o + 8) == id then
      rows = rows + 1
      if bit.band(all:byte(o + 21), 3) == 1 then
        local t = all:sub(o + 1, o + 8)
        mine = mine + 1
        if found and found ~= t then return nil, 'rows disagree (' .. hexof(found) .. ' / ' .. hexof(t) .. ')', rows, mine end
        found = found or t
      end
    end
  end
  if not found then return nil, rows > 0 and 'its owner row is not marked as ours' or 'no owner row', rows, 0 end
  return found, nil, rows, mine
end
local function type_name(t) return TYPE_NAMES[t] or ('type ' .. hexof(t)) end

-- ---------------------------------------------------------------------------------------------- the rule
local handled = {}                                 -- weapon ids already dealt with (Railguns set or seen in Unsafe,
                                                   -- and weapons that are not Railguns)
local tries = {}                                   -- weapon id -> polls spent waiting for its owner row
local current, last_why = nil, nil
local PRUNE_SECONDS, next_prune = 5, 0
-- (sweep) Railguns that no longer exist are forgotten, so a new Railgun that gets an old one's id is still set
local function prune(wm)
  for id in pairs(handled) do
    local ok, wi = pcall(map_lookup, wm + 48, id, 32768)
    if ok and not wi then handled[id] = nil end
  end
  for id in pairs(tries) do
    local ok, wi = pcall(map_lookup, wm + 48, id, 32768)
    if ok and not wi then tries[id] = nil end
  end
end
local pending = nil                                -- { id, addr, at }: check that the game kept Unsafe
local function poll()
  if pending and os.clock() >= pending.at then
    local now_mode = u32(rd(pending.addr, 4, 'fire mode'), 0)
    if now_mode == UNSAFE then event(string.format('Railgun %d: the game kept Unsafe', pending.id))
    else event(string.format('Railgun %d: the game put mode %d back', pending.id, now_mode)) end
    pending = nil
  end
  if (next(handled) or next(tries)) and os.clock() >= next_prune then  -- (also while you hold no support weapon)
    next_prune = os.clock() + PRUNE_SECONDS
    pcall(function() prune(rptr(G.weapons, 'weapons')) end)
  end
  local id, why = my_support_weapon()
  if not id then
    if why ~= last_why then last_why = why; if TESTER then event('waiting: ' .. why) end end
    current = nil
    return
  end
  last_why = nil
  local wm = rptr(G.weapons, 'weapons')
  if id == current then return end
  if handled[id] then current = id; return end
  local wi = map_lookup(wm + 48, id, 32768)
  if not wi then return end                        -- (no weapon record yet: tried again next poll)
  need(wi < 16384, 'weapon index')
  local addr = rptr(wm + 88, 'weapon records') + wi * WEAPON_STRIDE + MODE_AT
  local mode = u32(rd(addr, 4, 'fire mode'), 0)
  if mode == 0 then return end                     -- (sweep: record not filled in yet - looked at again next poll)
  current = id
  if mode ~= SAFE and mode ~= UNSAFE then
    if TESTER then event(string.format('support weapon %d: fire mode %d, not a Railgun - left alone', id, mode)) end
    return
  end
  -- the fire mode numbers alone don't make it a Railgun (the Arc Thrower uses them too): check its entity type
  local wtype, twhy, rows, mine = weapon_type(id)
  if not wtype then
    tries[id] = (tries[id] or 0) + 1
    if tries[id] < TYPE_TRIES then current = nil; return end   -- (its row may not be there yet: looked at again next poll)
    handled[id] = true; tries[id] = nil
    event(string.format('support weapon %d: fire mode %d, could not confirm it is a Railgun (%s) - left alone', id, mode, twhy))
    return
  end
  tries[id] = nil
  if TESTER then
    event(string.format('support weapon %d: %s, fire mode %d (owner rows %d, of them ours %d)', id, type_name(wtype), mode,
      rows, mine))
  end
  if wtype ~= RAILGUN_TYPE then
    handled[id] = true
    event(string.format('support weapon %d: %s, not a Railgun - left alone', id, type_name(wtype)))
    return
  end
  handled[id] = true
  RAU.seen = RAU.seen + 1
  if mode == UNSAFE then event(string.format('Railgun %d already in Unsafe', id)); return end
  -- the mode entry must agree with the record's copy, or the layout isn't what this was built for: then do nothing
  local st = rptr(wm + STATES_AT, 'weapon mode entries') + wi * STATE_STRIDE
  local e = rd(st, STATE_STRIDE, 'mode entry')
  if u32(e, 0) ~= mode or bit.band(e:byte(FLAG_AT + 1), UNSAFE_FLAG) ~= 0 then
    event(string.format('Railgun %d: mode entry reads %d (flags %d), not Safe - layout changed? left alone', id, u32(e, 0), e:byte(FLAG_AT + 1)))
    return
  end
  -- all three places must be writable before the first write, so it can never be left half switched
  if not (writable(st, FLAG_AT + 1) and writable(addr, 4)) then
    event(string.format('Railgun %d: could not set Unsafe (memory not writable) - left alone', id))
    return
  end
  if write_u32(st, UNSAFE) and write_u8(st + FLAG_AT, bit.bor(e:byte(FLAG_AT + 1), UNSAFE_FLAG)) and write_u32(addr, UNSAFE) then
    RAU.set = RAU.set + 1
    event(string.format('Railgun %d set to Unsafe', id))
    if TESTER then pending = { id = id, addr = addr, at = os.clock() + 0.5 } end
  else
    event(string.format('Railgun %d: could not set Unsafe (memory not writable)', id))
  end
end

-- ---------------------------------------------------------------------------------------------- hook
local started, broken, next_poll, next_log, last_error = false, false, 0, 0, nil
local function tick()
  if broken then return end
  local now = os.clock()
  if not started then
    started = true
    local ok, e = pcall(find_layout)
    if not ok then broken = true; RAU.status = 'off: could not find the game addresses (' .. tostring(e) .. ')'; write_log(); return end
    RAU.status = 'active'
  end
  if now >= next_poll then
    next_poll = now + POLL_SECONDS
    local ok, e = pcall(poll)
    -- (read errors are normal while the game is still loading: each different one is logged once in a row)
    if not ok then current = nil; if e ~= last_error then last_error = e; event('read error: ' .. tostring(e)) end
    else last_error = nil end
  end
  if dirty and now >= next_log then next_log = now + 2; write_log() end
end

local game_update, game_shutdown = rawget(_G, 'update'), rawget(_G, 'shutdown')
if type(game_update) ~= 'function' then RAU.status = 'off: game update function not found'; write_log(); return end
rawset(_G, 'update', function(...)
  local ok, e = pcall(tick)
  if not ok then broken = true; RAU.status = 'off: ' .. tostring(e); pcall(write_log) end
  return game_update(...)
end)
rawset(_G, 'shutdown', function(...)
  RAU.status = 'closed'; pcall(write_log)
  if type(game_shutdown) == 'function' then return game_shutdown(...) end
end)
write_log()
