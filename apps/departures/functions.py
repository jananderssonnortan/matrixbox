from __main__ import wifi, pool, requests
import varinit, createhtml, microcontroller, json, ipaddress
from varinit import *
import random

mac = [hex(i) for i in wifi.radio.mac_address]
id = "".join(mac)
#ap_name = "t-skylt" + id[-2:]; varinit.ap_name = ap_name
ap_name = "matrixbox-" + "".join(mac).replace("0x","")[:3] # mac-id för hotspot


def pwd_gen(): return id.replace("0x","")[:8]
def cls(__screen, _refresh=False):
    __screen.fill(0)
    if _refresh: refresh()
def reset():
    displayio.release_displays()
    microcontroller.reset()
def strlen(_string):
    if isinstance(_string, str): _string = _string.lower()
    return sum(fonts[varinit.currentfont][c][0] for c in _string)

def _rotation_slot_count():
    # How many station slots this panel actually uses (matches the UI's screen buttons).
    w = varinit.if_long
    if w > 128: return 3
    if w > 64: return 2
    return 1

def configured_stations():
    # Ordered station slots with a real siteid, bounded to what this panel uses.
    out = []
    for i in range(1, _rotation_slot_count() + 1):
        k = str(i)
        try:
            if str(varinit.settings["stations"][k]["siteid"]) not in ("", "0", "00", "000"):
                out.append(k)
        except: pass
    return out or ["1"]

def next_station():
    # Peek the next configured slot without switching to it.
    lst = configured_stations()
    if len(lst) < 2: return varinit.active_station
    cur = varinit.active_station if varinit.active_station in lst else lst[0]
    return lst[(lst.index(cur) + 1) % len(lst)]

# --- little burger icon for the meal row ('b' bun, 'g' lettuce, 'p' patty) ---
_BURGER = [
    " bbbbbb ",
    "bbbbbbbb",
    "gggggggg",
    "pppppppp",
    "bbbbbbbb",
    " bbbbbb ",
]

def _blit_icon(bmp, rows, x0, y0, colormap):
    # colormap: char -> palette index. Chars not in the map are transparent.
    W = bmp.width; H = bmp.height
    for dy in range(len(rows)):
        row = rows[dy]
        for dx in range(len(row)):
            c = colormap.get(row[dx])
            if c is not None:
                x = x0 + dx; y = y0 + dy
                if 0 <= x < W and 0 <= y < H:
                    bmp[x, y] = c

def _fill_rect(bmp, x0, y0, x1, y1, c):
    for x in range(x0, x1):
        for y in range(y0, y1):
            if 0 <= x < bmp.width and 0 <= y < bmp.height:
                bmp[x, y] = c

def _draw_degree(bmp, x, y, c):
    # small hollow ring used as the ° symbol (the font has no degree glyph)
    for ox, oy in ((0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2), (2, 2)):
        px, py = x + ox, y + oy
        if 0 <= px < bmp.width and 0 <= py < bmp.height: bmp[px, py] = c

def _draw_paren(bmp, x, y, c, left=True):
    # 2x6 pixel bracket (the font has '(' but no ')', so draw both for consistency)
    pts = ((1, 0), (0, 1), (0, 2), (0, 3), (0, 4), (1, 5)) if left else \
          ((0, 0), (1, 1), (1, 2), (1, 3), (1, 4), (0, 5))
    for ox, oy in pts:
        px, py = x + ox, y + oy
        if 0 <= px < bmp.width and 0 <= py < bmp.height: bmp[px, py] = c

# --- weather sprites (row-2 icons). chars: o sun-disc, r ray, c cloud, b rain, w snow, y bolt ---
_WX_SUN = ["..r..r..r..", "...r.r.r...", ".r..ooo..r.", "....ooo....", "...ooooo...",
           "rr.ooooo.rr", "...ooooo...", "....ooo....", ".r..ooo..r.", "...r.r.r...", "..r..r..r.."]
_WX_CLOUD = ["...........", "...cccc....", "..cccccc...", ".cccccccc..", "cccccccccc.",
             ".cccccccc..", "...........", "...........", "...........", "...........", "..........."]
_WX_PARTLY = ["..r........", ".r.r.......", "..ooo......", ".ooooocccc.", "..ooocccccc",
              "..cccccccc.", ".cccccccc..", "...........", "...........", "...........", "..........."]
_WX_RAIN = ["...........", "...cccc....", "..cccccc...", ".cccccccc..", "cccccccccc.",
            ".cccccccc..", "...........", "..b..b..b..", ".b..b..b...", "b..b..b....", "..........."]
_WX_SNOW = ["...........", "...cccc....", "..cccccc...", ".cccccccc..", "cccccccccc.",
            ".cccccccc..", "...........", "..w..w..w..", ".w..w..w...", "..w..w..w..", "..........."]
_WX_THUNDER = ["...........", "...cccc....", "..cccccc...", ".cccccccc..", "cccccccccc.",
               ".cccccccc..", "....yy.....", "...yy......", "..yyyyy....", "....yy.....", "...yy......"]
_WX_COLORMAP = {"o": 4, "r": 9, "c": 6, "b": 8, "w": 2, "y": 1}

def _wx_sprite(code):
    if code == 0: return _WX_SUN
    if code in (1, 2): return _WX_PARTLY
    if code in (3, 45, 48): return _WX_CLOUD
    if (71 <= code <= 77) or code in (85, 86): return _WX_SNOW
    if 95 <= code <= 99: return _WX_THUNDER
    if (51 <= code <= 67) or (80 <= code <= 82): return _WX_RAIN
    return _WX_CLOUD

def _wx_severity(c):
    if 95 <= c <= 99: return 5
    if (71 <= c <= 77) or c in (85, 86): return 4
    if (51 <= c <= 67) or (80 <= c <= 82): return 3
    if c in (3, 45, 48): return 2
    if c in (1, 2): return 1
    return 0

def _wx_warning(code, temp, gust, hi=None, lo=None, wind=None):
    # Short extreme-weather label (or "") from the upcoming code, mean wind and gust (m/s) and temps.
    # hi/lo are the day's upcoming high/low so HETT/KYLA fire on the forecast peak, not just now.
    # Wind warnings key on the mean wind; model gusts run high (an ordinary breezy day shows
    # 15-17 m/s gusts), so gusts only count well above that.
    if hi is None: hi = temp
    if lo is None: lo = temp
    w = wind if wind is not None else 0
    g = gust if gust is not None else 0
    if code in (95, 96, 99): return "ÅSKA"              # thunderstorm
    if w >= 20 or g >= 28: return "STORM"               # storm-force wind
    if code in (75, 86): return "SNÖFALL"               # heavy snow
    if code in (65, 67, 82): return "SKYFALL"           # heavy rain / cloudburst
    if w >= 12 or g >= 21: return "BLÅST"               # strong wind
    if hi >= 28: return "VARMT AF"                      # peak of the day, even if cooler now
    if lo <= -10: return "KYLA"
    return ""

def get_weather(allow_fetch=True):
    # Upcoming weather for the next 0-2h + current temp + extreme warning, via open-meteo (no key).
    # Returns (weather_code, temp_str, warning) or (None, None, ""). Cached ~20 min; keep-last-good.
    if not int(varinit.settings.get("weather", 1)): return (None, None, "")
    # low priority: attempt at most once every 30 min (whether it succeeds or fails), so a
    # flaky network can never make it refetch on every switch and tax the chip.
    if varinit.wx_timer and time.monotonic() - varinit.wx_timer < 1800:
        return (varinit.wx_code, varinit.wx_temp, varinit.wx_warn)
    if not allow_fetch:   # another fetch already ran on this switch; try again on the next one
        return (varinit.wx_code, varinit.wx_temp, varinit.wx_warn)
    varinit.wx_timer = time.monotonic()   # mark the attempt up front
    lat = varinit.settings.get("weather_lat", "59.36")   # Vallingby
    lon = varinit.settings.get("weather_lon", "17.87")
    try:
        url = ("https://api.open-meteo.com/v1/forecast?latitude=" + str(lat) +
               "&longitude=" + str(lon) +
               "&current=temperature_2m,weather_code,wind_speed_10m,wind_gusts_10m"
               "&hourly=weather_code,temperature_2m&daily=temperature_2m_max"
               "&forecast_days=1&wind_speed_unit=ms&timezone=auto")   # m/s (default is km/h!); today only
        resp = requests.get(url, timeout=5); d = json.loads(resp.text); resp.close()   # give up on a stall
        cur = d["current"]
        # open-meteo's local wall clock ("YYYY-MM-DDTHH:MM", timezone=auto, DST-correct).
        # The device clock (_currenttime) is HH:MM only, so local_now() derives the local date and time from this anchor.
        try:
            varinit.wx_local = str(cur.get("time", ""))
            varinit.wx_local_mono = time.monotonic()
        except: pass
        temp = int(round(cur["temperature_2m"]))
        try: gust = float(cur.get("wind_gusts_10m"))
        except: gust = None
        try: wind = float(cur.get("wind_speed_10m"))
        except: wind = None
        # Index the hourly arrays by the API's OWN local timestamps, not the device clock.
        # (hourly/current times are in the location's timezone; the device's _currenttime is
        # UTC from the HTTP date header, so using it mis-slices by the tz offset -> false HETT.)
        htimes = d["hourly"].get("time", [])
        chour = str(cur.get("time", ""))[:13]        # "YYYY-MM-DDTHH"
        h = 0
        for _i, _t in enumerate(htimes):
            if str(_t)[:13] == chour: h = _i; break
        else:
            try: h = int(str(varinit._currenttime).split(":")[0])   # fallback: device hour
            except: h = 0
        hcodes = [int(c) for c in d["hourly"]["weather_code"]]
        near = [int(cur["weather_code"])] + hcodes[h + 1:h + 3]   # now + next ~2h -> upcoming condition
        varinit.wx_code = max(near, key=_wx_severity)
        varinit.wx_temp = str(temp)   # number only; the degree mark is drawn as pixels (font lacks it)
        # today's forecast high, shown only while it's still ahead (hidden once it has passed)
        hi = lo = temp
        try:
            dh = int(round(float(d["daily"]["temperature_2m_max"][0])))
            htemps = [float(t) for t in d["hourly"]["temperature_2m"]]
            remaining = htemps[h:] if h < len(htemps) else []
            ahead = bool(remaining) and max(remaining) >= dh - 0.5
            varinit.wx_peak = dh if (ahead and dh > temp) else None
            if remaining:                       # upcoming high/low drive HETT/KYLA
                hi = max(temp, int(round(max(remaining))))
                lo = min(temp, int(round(min(remaining))))
        except: varinit.wx_peak = None
        varinit.wx_warn = _wx_warning(varinit.wx_code, temp, gust, hi=hi, lo=lo, wind=wind)
    except Exception:
        pass
    return (varinit.wx_code, varinit.wx_temp, varinit.wx_warn)

def _switch_hold(seconds, flash=False):
    # Hold the switch screen; if flash, blink palette slot 10 (the warning colour) for attention.
    t = last = time.monotonic(); on = True
    while time.monotonic() < t + seconds:
        try:
            if not varinit.button.value: return
        except: pass
        if flash and time.monotonic() - last > 0.4:
            on = not on
            try: varinit.palette[10] = (255, 40, 20) if on else (55, 8, 4)
            except: pass
            refresh(); last = time.monotonic()
        time.sleep(0.05)

def _recolor_row2(from_idx=1, to_idx=8, x0=14):
    for _x in range(x0, min(bottom.width, 128)):
        for _y in range(bottom.height):
            if bottom[_x, _y] == from_idx: bottom[_x, _y] = to_idx

def _bri(rgb):
    # Scale a full-brightness colour by the user's brightness setting so the switch/custom
    # screens track the same knob as the departures text (colors(): value = base*(brightness+1);
    # /5 treats the given rgb as the value at max brightness ~4).
    f = int(varinit.settings.get("brightness", 0)) + 1
    return (min(255, rgb[0] * f // 5), min(255, rgb[1] * f // 5), min(255, rgb[2] * f // 5))

def _render_meal(meal):
    # row 2: burger icon + today's meal (bright cyan)
    varinit.tg2.x = 0
    varinit.palette[4] = _bri((255, 170, 30))   # bun
    varinit.palette[6] = _bri((40, 40, 70))     # icon background
    varinit.palette[7] = _bri((60, 255, 60))    # lettuce
    varinit.palette[8] = _bri((80, 210, 255))   # meal text
    varinit.palette[9] = _bri((255, 90, 20))    # patty
    renderstring(meal, 0, 0, smallfont=True, _cls=bottom, target_bmp=bottom, target_offs=5, start_x=14)
    _recolor_row2(1, 8, 14)
    _fill_rect(bottom, 2, 4, 12, 12, 6)
    _blit_icon(bottom, _BURGER, 3, 5, {"b": 4, "g": 7, "p": 9})

def _render_weather(allow_fetch=True):
    # row 2: upcoming-weather icon + temp, plus an extreme-weather warning to the right.
    # Returns (drawn, has_warning).
    code, temp, warn = get_weather(allow_fetch=allow_fetch)
    if code is None: return False, False
    varinit.tg2.x = 0
    varinit.palette[2] = _bri((235, 235, 245))  # snow / white
    varinit.palette[4] = _bri((255, 210, 0))    # sun disc
    varinit.palette[6] = _bri((150, 150, 165))  # cloud grey
    varinit.palette[8] = _bri((120, 200, 255))  # rain / temp text
    varinit.palette[9] = _bri((255, 140, 0))    # sun rays / bolt-ish
    _blit_icon(bottom, _wx_sprite(code), 1, 2, _WX_COLORMAP)
    # current temp: "12" + degree ring + "C"  ->  "12°C"
    w1 = int(renderstring(temp, 0, 0, smallfont=True, _cls=None, target_bmp=bottom, target_offs=5, start_x=15))
    w2 = int(renderstring("C", 0, 0, smallfont=True, _cls=None, target_bmp=bottom, target_offs=5, start_x=w1 + 5))
    right = w2
    # today's high in (parens) - only while still ahead
    peak = varinit.wx_peak
    lpx = rpx = None
    if peak is not None:
        lpx = w2 + 4
        w3 = int(renderstring(str(peak), 0, 0, smallfont=True, _cls=None, target_bmp=bottom, target_offs=5, start_x=lpx + 3))
        rpx = w3 + 1
        right = rpx + 3
    _recolor_row2(1, 8, 15)                     # colour the digits + 'C' blue
    _draw_degree(bottom, w1 + 1, 4, 8)          # ° after the current number
    if peak is not None:
        _draw_paren(bottom, lpx, 5, 8, True)    # (
        _draw_paren(bottom, rpx, 5, 8, False)   # )
    if warn:
        varinit.palette[10] = (255, 40, 20)   # dedicated warning slot (blinks via _switch_hold)
        wx = right + 7
        renderstring(warn, 0, 0, smallfont=True, _cls=None, target_bmp=bottom, target_offs=5, start_x=wx)
        _recolor_row2(1, 10, wx)
    return True, bool(warn)

# --- electricity spot price: "El 2,62 kr" on switch-screen row 2, traffic-light coloured ---
# Source: elprisetjustnu.se (open, no key), one fetch per local day. Shown at the right end of
# row 2 only when it fits beside the weather/meal; hidden otherwise (warnings, long meals).
_EL_GREEN, _EL_AMBER, _EL_RED = 3, 5, 11    # 3/5 are free on the switch screen (restored after);
                                            # red shares 11 with the SL badge, same colour
_EL_OFF = 400                               # scratch x in the 1280-wide bottom bitmap for measuring

def local_now():
    # (date "YYYY-MM-DD", minute-of-day) in local time, from the last weather fetch's wall clock
    # plus elapsed monotonic time. None until weather has been fetched once (or if > 12 h stale).
    try:
        s = varinit.wx_local
        el = time.monotonic() - varinit.wx_local_mono
        if not s or el > 12 * 3600: return None
        y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
        mins = int(s[11:13]) * 60 + int(s[14:16]) + int(el // 60)
        t = time.localtime(time.mktime((y, mo, d, 0, 0, 0, 0, 0, -1)) + mins * 60)
        return ("%04d-%02d-%02d" % (t[0], t[1], t[2]), t[3] * 60 + t[4])
    except Exception:
        return None

def _parse_el(txt):
    # [(start_minute_local, SEK_per_kWh), ...] without json.loads (19 KB / 96 dicts is heavy).
    # Entries are ordered {"SEK_per_kWh":x, ..., "time_start":"YYYY-MM-DDTHH:MM:SS+01:00", ...}.
    out = []; i = 0
    while True:
        i = txt.find('"SEK_per_kWh":', i)
        if i < 0: break
        i += 14; j = txt.find(",", i)
        p = float(txt[i:j])
        k = txt.find('"time_start":"', j)
        if k < 0: break
        hm = txt[k + 25:k + 30]                   # "HH:MM" after '"time_start":"YYYY-MM-DDT'
        out.append((int(hm[:2]) * 60 + int(hm[3:5]), p))
        i = k
    return out

def _el_next_day(day):
    # "YYYY-MM-DD" -> the following date (noon anchor keeps DST shifts away from midnight)
    t = time.localtime(time.mktime((int(day[0:4]), int(day[5:7]), int(day[8:10]), 12, 0, 0, 0, 0, -1)) + 86400)
    return "%04d-%02d-%02d" % (t[0], t[1], t[2])

def get_price(allow_fetch=True):
    # Today's prices once per local day, and from 13:00 (when the next day is published)
    # tomorrow's, so the bars can run past midnight; at midnight tomorrow simply becomes today.
    # A failure (or tomorrow not out yet) retries after 10 min. Returns True if it attempted a
    # fetch, so the caller can keep to one background fetch per switch.
    if not int(varinit.settings.get("el_price", 1)): return False
    now = local_now()
    if not now: return False
    day, mins = now
    days = getattr(varinit, "el_days", {})
    want = day if day not in days else None
    if not want and mins >= 13 * 60:
        nxt = _el_next_day(day)
        if nxt not in days: want = nxt
    if not want: return False
    t = getattr(varinit, "el_timer", 0)
    if t and time.monotonic() - t < 600: return False
    if not allow_fetch: return False
    varinit.el_timer = time.monotonic()
    zone = str(varinit.settings.get("el_zone", "SE3"))
    url = "https://www.elprisetjustnu.se/api/v1/prices/" + want[:4] + "/" + want[5:] + "_" + zone + ".json"
    try:
        resp = requests.get(url, timeout=5); txt = resp.text; resp.close()
        pts = _parse_el(txt)
        if len(pts) >= 20:
            keep = {k: v for k, v in days.items() if k >= day}   # drop past days
            keep[want] = pts
            varinit.el_days = keep
            varinit.el_timer = 0                      # back-off is only for failures
    except Exception as e:
        print("el:", e)
    return True

def _el_at(pts, minute):
    cur = None
    for m, p in pts:
        if m <= minute: cur = p
        else: break
    return cur

def el_now():
    # Current price, or None if we don't have today's data.
    now = local_now()
    if not now: return None
    e = getattr(varinit, "el_days", {}).get(now[0])
    return _el_at(e, now[1]) if e else None

def _el_limit(key, default):
    try: return float(str(varinit.settings.get(key, default)).replace(",", "."))
    except: return default

def _el_level(p, ref):
    # Colour by what waiting would save: p's distance (SEK/kWh, spot excl. VAT) above ref, the
    # cheapest hour coming up. Green = about as cheap as it gets, red = worth waiting. A flat
    # day stays green/amber however its prices spread.
    d = p - ref
    if d >= _el_limit("el_red", 0.6): return _EL_RED
    if d < _el_limit("el_green", 0.2): return _EL_GREEN
    return _EL_AMBER

def _el_hours(n):
    # [(price, colour) or None] x n: the current quarter-hour, then the means of the next n-1
    # whole hours, all coloured against the cheapest of them. None where prices are unknown.
    day, mins = local_now()
    days = varinit.el_days
    vals = [_el_at(days[day], mins)]
    tomorrow = _el_next_day(day)
    for k in range(1, n):
        h = mins // 60 + k
        e = days.get(day if h < 24 else tomorrow)
        h %= 24
        q = [v for m, v in e if h * 60 <= m < h * 60 + 60] if e else []
        vals.append(sum(q) / len(q) if q else None)
    ref = min(v for v in vals if v is not None)
    return [(v, _el_level(v, ref)) if v is not None else None for v in vals]

def _small_width(txt):
    # (width, baseline_y) of txt in the small font, measured off-screen in `bottom`.
    w = int(renderstring(txt, 0, 0, smallfont=True, _cls=None, target_bmp=bottom, target_offs=5,
                         start_x=_EL_OFF)) - _EL_OFF
    base = 0
    for x in range(_EL_OFF, _EL_OFF + w):
        for y in range(bottom.height):
            if bottom[x, y]:
                if y > base: base = y
                bottom[x, y] = 0
    return w, base

_EL_BARS = 8                                # hours shown as bars (current quarter + 7)
_EL_BAR_W = 3                               # bar width; 1 px gap between bars

def _render_price():
    # Right end of row 2: bars for the next hours (height = price, colour = level, white mark
    # under "now") followed by the current price, e.g. "2,65". Falls back to "El 2,65 kr" and
    # then to nothing when there is no room. Returns True if something was drawn.
    try:
        p = el_now()
        if p is None: return False
        W = varinit.if_long
        used = -1                                     # rightmost pixel already on row 2
        for x in range(W - 1, -1, -1):
            for y in range(bottom.height):
                if bottom[x, y]: used = x; break
            if used >= 0: break
        ip, dp = ("%.2f" % p).split(".")
        hrs = _el_hours(_EL_BARS)
        c = hrs[0][1]
        bars_w = _EL_BARS * (_EL_BAR_W + 1) - 1
        if int(varinit.settings.get("el_bars", 1)):
            layouts = ([ip, None, dp], bars_w + 4), (["El ", ip, None, dp, " kr"], 0)
        else:
            layouts = ((["El ", ip, None, dp, " kr"], 0),)
        for parts, lead in layouts:                  # None = hand-drawn comma (font's is blank)
            ws = []; base = 0
            for s in parts:
                if s is None: ws.append(3); continue
                w, b = _small_width(s); ws.append(w)
                if s == ip: base = b
            x = W - 2 - sum(ws) - lead
            if x - used >= 5: break
        else:
            return False                              # no room: weather warning / long meal wins
        varinit.palette[_EL_GREEN] = _bri((40, 220, 60))
        varinit.palette[_EL_AMBER] = _bri((255, 170, 0))
        if lead: _el_draw_bars(x, hrs)
        x += lead; x0 = x
        for s, w in zip(parts, ws):
            if s is None:
                bottom[x + 1, base] = 1; bottom[x + 1, base + 1] = 1; bottom[x, base + 2] = 1
            else:
                renderstring(s, 0, 0, smallfont=True, _cls=None, target_bmp=bottom, target_offs=5, start_x=x)
            x += w
        for xx in range(x0, x):
            for y in range(bottom.height):
                if bottom[xx, y] == 1: bottom[xx, y] = c
        return True
    except Exception as e:
        print("el render:", e)
        return False

def _el_draw_bars(x, hrs):
    # heights 1..12 px in proportion to the price from zero, so small differences look small;
    # the top is the highest price shown but at least 1 kr, so a cheap day stays low.
    # Baseline row 13, the "now" mark (white, slot 2 on the switch screen) on row 15.
    top = max([h[0] for h in hrs if h] + [1.0])
    for i, h in enumerate(hrs):
        if not h: continue
        hgt = max(1, int(round(max(h[0], 0) / top * 12)))
        bx = x + i * (_EL_BAR_W + 1)
        for dx in range(_EL_BAR_W):
            for y in range(14 - hgt, 14):
                bottom[bx + dx, y] = h[1]
    for dx in range(_EL_BAR_W):
        bottom[x + dx, 15] = 2

# custom-message banner colours (palette slots 2/3; 1 = departures text, restored after)
_CUSTOM_GREEN = (15, 150, 25)     # banner background (true green, no blue tint)
_CUSTOM_WHITE = (240, 240, 240)   # message text

def _show_welcome(msg):
    # Full-screen: scroll the custom message across once, slowly (so long text reads),
    # as white text on a green banner.
    try:
        saved = [varinit.palette[i] for i in range(2, 8)]   # preserve shared palette slots
        cls(top); cls(bottom)
        width = int(renderstring(msg, large=True, _cls=bottom))   # renders glyphs (index 1) into bottom
        GREEN, WHITE = 2, 3
        varinit.palette[GREEN] = _bri(_CUSTOM_GREEN)
        varinit.palette[WHITE] = _bri(_CUSTOM_WHITE)
        span = min(bottom.width, width + 2)
        for x in range(span):                       # glyph pixels -> white, everything else -> green banner
            for y in range(bottom.height):
                bottom[x, y] = WHITE if bottom[x, y] else GREEN
        varinit.tg2.y = 8                           # centre the single line on the 32px panel
        varinit.tg2.x = varinit.if_long
        while varinit.tg2.x > -width:
            try:
                if not varinit.button.value: break  # let the button bail out
            except: pass
            varinit.tg2.x -= 1
            refresh()
            time.sleep(0.012)                       # ~4-5s total for a long message
        varinit.tg2.y = 16
        cls(top); cls(bottom)
        for i, v in enumerate(saved):
            varinit.palette[i + 2] = v              # restore slots so other screens are unaffected
    except Exception:
        pass

# --- birthday card: sheet row 2 starting with "BDAY:" (any case) ---
# 'f' flame, 'c' candle, 'i' icing/plate, 'k' cake, 's' sprinkles. 14x16, fills the band height.
_CAKE = [
    "              ",
    "   f   f   f  ",
    "   f   f   f  ",
    "   c   c   c  ",
    "   c   c   c  ",
    "   c   c   c  ",
    " iiiiiiiiiiii ",
    " iiiiiiiiiiii ",
    " kiikkiikkiik ",
    " kkkkkkkkkkkk ",
    " kskkkskkkskk ",
    " kkkkkkkkkkkk ",
    " kkkskkkskkks ",
    " kkkkkkkkkkkk ",
    "iiiiiiiiiiiiii",
    "              ",
]
_CAKE_W = 14
_CAKE_GAP = 4
_BDAY_BG = (0, 70, 230)         # pulsing background at its peak (royal blue)
_BDAY_CAKE = (255, 130, 0)      # orange sponge, pops against the blue
_BDAY_SPRINKLE = (0, 230, 255)  # cyan
_BDAY_CANDLE = (255, 40, 40)    # red (a blue candle would vanish on the blue band)
_BDAY_FLAMES = ((255, 200, 0), (255, 120, 0), (255, 240, 140))

def birthday_text(msg):
    # "BDAY:Grattis Anna!" -> "Grattis Anna!"; anything else -> None. Text is shown as written.
    s = (msg or "").strip()
    if s[:5].upper() != "BDAY:": return None
    return s[5:].strip() or None

def _show_birthday(msg):
    # Cake + message on a slowly pulsing blue band. Static and centred when it fits the
    # panel, otherwise cake and text scroll through once. Only palette entries change per
    # frame (no pixel loops), so the pulse and the candle flicker cost almost nothing.
    try:
        saved = [varinit.palette[i] for i in range(2, 8)]
        BG, TEXT, CAKE, SPRK, CNDL, FLAME = 2, 3, 4, 5, 6, 7
        W = varinit.if_long
        cls(top); cls(bottom)
        text_x = _CAKE_W + _CAKE_GAP
        total = int(renderstring(msg, large=True, _cls=bottom, start_x=text_x))
        static = total <= W
        x0 = (W - total) // 2 if static else 0
        if x0:
            # shift the rendered row right so the card sits centred in the bitmap
            for x in range(total - 1, -1, -1):
                for y in range(bottom.height):
                    bottom[x + x0, y] = bottom[x, y]
                    bottom[x, y] = 0
        span = min(bottom.width, W if static else total + 2)
        for x in range(span):                     # glyphs -> white, everything else -> band
            for y in range(bottom.height):
                bottom[x, y] = TEXT if bottom[x, y] else BG
        _blit_icon(bottom, _CAKE, x0, 0, {"f": FLAME, "c": CNDL, "i": TEXT, "k": CAKE, "s": SPRK})
        varinit.palette[TEXT] = _bri(_CUSTOM_WHITE)
        varinit.palette[CAKE] = _bri(_BDAY_CAKE)
        varinit.palette[SPRK] = _bri(_BDAY_SPRINKLE)
        varinit.palette[CNDL] = _bri(_BDAY_CANDLE)
        varinit.palette[FLAME] = _bri(_BDAY_FLAMES[0])
        varinit.tg2.y = 8
        varinit.tg2.x = 0 if static else W
        t0 = last_flame = time.monotonic()
        hold = float(varinit.settings.get("bday_hold", 6))
        while True:
            now = time.monotonic()
            if static:
                if now - t0 > hold: break
            else:
                if varinit.tg2.x <= -total: break
                varinit.tg2.x -= 1
            try:
                if not varinit.button.value: break
            except: pass
            # triangle wave, 1.6 s period, 25%..100% of the peak colour
            ph = ((now - t0) % 1.6) / 1.6
            f = 0.25 + 0.75 * (1 - abs(2 * ph - 1))
            varinit.palette[BG] = _bri((int(_BDAY_BG[0] * f), int(_BDAY_BG[1] * f), int(_BDAY_BG[2] * f)))
            if now - last_flame > 0.1:
                varinit.palette[FLAME] = _bri(random.choice(_BDAY_FLAMES))
                last_flame = now
            refresh()
            time.sleep(0.03 if static else 0.012)
        varinit.tg2.y = 16
        varinit.tg2.x = 0
        cls(top); cls(bottom)
        for i, v in enumerate(saved):
            varinit.palette[i + 2] = v
    except Exception as e:
        print("birthday:", e)

# stylized "SL" badge (white 'w' on SL-red 'r') in front of the station name
_SL = [
    "rrrrrrrrrrrr",
    "rrrrrrrrrrrr",
    "rrrrrrrrrrrr",
    "rrwwwrrwrrrr",
    "rrwrrrrwrrrr",
    "rrwwwrrwrrrr",
    "rrrrwrrwrrrr",
    "rrrrwrrwrrrr",
    "rrwwwrrwwwrr",
    "rrrrrrrrrrrr",
    "rrrrrrrrrrrr",
    "rrrrrrrrrrrr",
]

def rotate_station():
    # Switch to the next station and show the upcoming-station switch screen:
    # row 1 = SL badge + the station about to show; row 2 = the meal during the dinner
    # window, otherwise upcoming weather + temp. Then the normal departures screen loads.
    nxt = next_station()
    varinit.active_station = nxt
    if not int(varinit.settings["listmode"]):
        try:
            _name = varinit.settings["stations"][nxt]["mystation"][:16]
            renderstring(_name, 1, 0, large=True, _cls=top, start_x=15)   # name after the SL badge
            varinit.palette[2] = _bri((235, 235, 245))    # station-name letters
            varinit.palette[11] = _bri((200, 30, 30))     # SL red badge
            _blit_icon(top, _SL, 0, 2, {"r": 11, "w": 2})   # 12x12 square badge, vertically centred
            cls(bottom)
            # Keep two blocking fetches off one switch: every switch already pays for a
            # departures fetch, so if the sheet fetched here, weather waits for the next switch
            # (it keeps its cached value and its poll timer, so it's only ~15s later).
            _fetched = get_sheet()           # refresh meal + custom message (cached ~15 min)
            shown = False; warn = False
            # only show a meal we fetched TODAY (never a stale one from a previous day);
            # no meal planned -> weather + price, same as outside the dinner window
            if dinner_time_ok() and varinit.dinner_day == varinit.today and varinit.dinner_meal:
                _render_meal(varinit.dinner_meal); shown = True
            _wt = getattr(varinit, "wx_timer", 0)
            if not shown:
                _, warn = _render_weather(allow_fetch=not _fetched)
            elif not getattr(varinit, "wx_local", ""):
                get_weather(allow_fetch=not _fetched)   # meal showing, but the price needs the local clock
            _fetched = _fetched or getattr(varinit, "wx_timer", 0) != _wt   # weather fetched this switch?
            # electricity price at the right end of row 2 (daily fetch, only if nothing else fetched)
            _p35 = (varinit.palette[_EL_GREEN], varinit.palette[_EL_AMBER])
            get_price(allow_fetch=not _fetched)
            _render_price()
            refresh()
            # Spend the hold on the incoming station's fetch, then hold out whatever time
            # is left, less the time the departures take to draw (the switch screen stays up
            # while they draw, see below): the screen stays up just as long overall.
            _hold = int(varinit.settings.get("dinner_hold", 3))
            _t0 = time.monotonic()
            prefetch_departures(nxt)
            _draw = min(1.5, getattr(varinit, "dep_render_s", 0))
            _switch_hold(max(0, _hold - _draw - (time.monotonic() - _t0)), flash=warn)
            # clear row 2 as well before handing slots 3/5 back: the main loop redraws once
            # before the departures replace it, and the price would flash in the wrong colours
            cls(top); cls(bottom)
            varinit.palette[_EL_GREEN], varinit.palette[_EL_AMBER] = _p35   # system-message colours back
            # occasional custom message (white on green, scrolls once), driven solely by
            # the sheet row-2 message (blank = off)
            _wmsg = varinit.sheet_msg
            if _wmsg and _wmsg.strip():
                varinit.welcome_count += 1
                _every = max(1, int(varinit.settings.get("welcome_every", 3)))
                if varinit.welcome_count % _every == 0:
                    _bday = birthday_text(_wmsg)
                    if _bday: _show_birthday(_bday)
                    elif not (_wmsg.strip()[:5].upper() == "BDAY:"):   # bare "BDAY:" = nothing
                        _show_welcome(_wmsg.strip())
        except Exception:
            pass
    # normal screen: stock render draws the next departure on top + scrolls the rest.
    varinit.currentfont = 0
    varinit.active_message = False
    varinit.shared["scroll_timer"] = 0
    if not int(varinit.settings["listmode"]) and varinit.display.width > 64:
        # Draw the departures now, with no refresh in between: the panel keeps showing the
        # switch screen until the main loop's next refresh, which then shows the departures
        # straight away instead of a black panel for the ~1 s the render takes.
        _t = time.monotonic()
        scroll_mode(reveal=False)
        varinit.dep_render_s = time.monotonic() - _t
    return nxt

def temperature_check():
    if round(microcontroller.cpu.temperature) > varinit.temperature_threshold: 
        print("Temp-warning: ", round(microcontroller.cpu.temperature))
        if not varinit.temperature_timer: varinit.temperature_timer = time.monotonic()
        elif time.monotonic() > varinit.temperature_timer + 60*2: 
            print("Temperature fail! Restarting...")
            import safemode
    else: varinit.temperature_timer = False

def ping_screen():
    while varinit.ping:
        start_time = time.monotonic()
        _data = fetch_data("data.t-skylt.se",90,"/get_departures?country=se&operator=sl&station=9001", )
        end_time = time.monotonic()
        varinit.ping_list.append(int(end_time - start_time))
        print("temp: ", str(round(microcontroller.cpu.temperature)))
        if len(varinit.ping_list) > 5: varinit.ping_list.pop(0)
        sysprint(str(varinit.ping_list), 0, color="red", shading=True, _refresh=True, ontop=True)
    return True

def ad_message():
    varinit.ad_timer = time.monotonic()
    data = fetch_data(host="data.t-skylt.se", port=89, args="/settings?ad")
    ad = json.loads(data)
    return str(ad[1]) if ad[0] else False

def dinner_time_ok():
    # True every day inside the dinner window (settings dinner_start/dinner_end, default
    # 13:00-19:00). Uses the same clock as check_timer().
    try:
        _s = str(varinit.settings.get("dinner_start", "") or "13:00")
        _e = str(varinit.settings.get("dinner_end", "") or "19:00")
        return compare_time(_s) < compare_time(varinit._currenttime) < compare_time(_e)
    except: return False

def get_sheet(allow_fetch=True):
    # Returns True if it actually performed a network fetch (the caller uses that to keep two
    # blocking fetches off the same switch screen).
    # One published CSV, two rows (single column, NO header):
    #   row 1 = today's meal  ->  varinit.dinner_meal
    #   row 2 = an optional custom message  ->  varinit.sheet_msg
    # Row 2 lets a sheet formula switch on a greeting for a window (e.g. "Heja VSK!" in
    # the hours before kickoff) and blank it otherwise. Rows are read POSITIONALLY, so an
    # empty meal with a present message still works. Polled every ~15 min.
    # A SUCCESSFUL fetch always replaces the cache, even when the cells are empty: an empty
    # meal cell means "nothing planned today", NOT "keep yesterday's". Only a failed fetch
    # (exception) keeps the previous values, and dinner_day stamps the day they belong to.
    url = varinit.settings.get("dinner_url", "")
    if not url: return False
    if varinit.dinner_fetch_timer and time.monotonic() - varinit.dinner_fetch_timer < 900:
        return False
    if not allow_fetch: return False   # a fetch already ran this switch; retry on the next one
    varinit.dinner_fetch_timer = time.monotonic()   # mark the attempt up front
    try:
        resp = requests.get(url, timeout=5)   # give up on a stall rather than hang the loop
        txt = resp.text
        resp.close()
        lines = (txt or "").replace("\r", "").split("\n")
        def _cell(i):
            if i >= len(lines): return ""
            v = lines[i].strip()
            if len(v) >= 2 and v[0] == '"' and v[-1] == '"': v = v[1:-1].replace('""', '"')
            return v.strip()
        varinit.dinner_meal = _cell(0)
        varinit.sheet_msg = _cell(1)
        varinit.dinner_day = varinit.today   # the day these values are valid for
    except Exception:
        pass       # failed fetch: keep cached, retry on the next poll
    return True    # a fetch was attempted (success or failure), so it cost us the time

def get_dinner():
    get_sheet()
    return varinit.dinner_meal

def check_button():
    if varinit.last_button_state:
        if not varinit.button.value:
            varinit.time.sleep(varinit.debounce_delay)
            if not varinit.button.value:
                varinit.shared["nightcount"] = 0
                x = 0 
                while not varinit.button.value and x < varinit.button_delay * 2: x+=1
                if x > varinit.button_delay and not varinit.group.hidden:
                    varinit.exit = True
                else:
                    if int(varinit.settings.get("button_mode", 0)):
                        varinit.deviations_timer = time.monotonic()
                        if varinit.display.width > 64 and varinit.display.height <= 32:
                            varinit.settings["listmode"] = 1 - int(varinit.settings["listmode"])
                        switch(_screen=True)
                    else:
                        nightcheck(_switch=True, turnon=varinit.group.hidden); refresh()
    varinit.last_button_state = varinit.button.value

def check_timer():
    try:
        for day in varinit.settings["timer"]:
            if varinit.settings["timer"][day] and day[:3] == varinit.today:
                if compare_time(varinit.settings["timer"][day][0]) == compare_time(varinit.settings["timer"][day][1]): return True
                if compare_time(varinit.settings["timer"][day][0]) < compare_time(varinit._currenttime) < compare_time(varinit.settings["timer"][day][1].replace("00:00","24:00")):
                    print(varinit.settings["timer"][day][0], "<", varinit._currenttime, "<", varinit.settings["timer"][day][1])
                    return True
                else: return False
    except Exception as e:
        print(e)
        return True
    return True

def compare_time(time1):
    return time.struct_time(["","","",time1.split(":")[0],time1.split(":")[1],"","","",""])


def version_delay(slowdown=False):
    try:
        if slowdown:
            if slowdown == 1:
                if varinit.cpver == 9 and varinit.if_long > 128: microcontroller.cpu.frequency = 80000000
            elif slowdown == 2:
                if varinit.cpver == 9 and varinit.if_long > 128: microcontroller.cpu.frequency = 180000000
            return
    except: pass
    wifi.radio.stop_ap()
    wifi.radio.tx_power = 17.0
    #wifi.radio.tx_power = 13.0
    
    varinit.button_delay = 20000 #varinit.debounce_delay = 0.5  
    try: microcontroller.cpu.frequency = 180000000
    except: pass
    return 100

def reset_scroll(_delay=0):
    varinit.deviations_timer = time.monotonic()
    varinit.shared["scroll_timer"] = 0
    time.sleep(_delay)
    if varinit.first_start: return
    varinit.shared["loop_counter"] = 0

def sysprint(_string, line, color=True, cls=False, shading=False, _refresh=True, ontop=False, _delay=0):
    _invertcolor = 2 if shading else 0
    renderstring(_string + " ", line, smallfont=True, sys_msg=color, shading=shading, shade=False, invertcolor=_invertcolor, _cls=cls, ontop=ontop)
    refresh() if _refresh else None
    time.sleep(_delay)

def switch(_screen=True, _cls=False, force=False, wifi_screen=False):
    def bounce(direction):
        for x in range(32):
            varinit.tg1.y -= -direction
            varinit.tg2.y -= -direction
            varinit.tg3.y -= -direction
            refresh()
    if _cls: cls(_cls)
    if _screen: 
        direction = -1 if force and not varinit.tg3.y == 0 or not varinit.tg3.y == 0 else 1
        if direction == -1: 
            cls(topbottom)
            if not force: list_splash(_settings=varinit.shared["startup"])
            if wifi_screen: update_screen()
        else:
            renderstring(varinit.text[4]+ varinit.settings["stations"][varinit.active_station]["mystation"][:16], 1, 0,large=True, _cls=top)
        bounce(direction)
    cls(bottom, _refresh=True)
    reset_scroll()

def load_text():
    
    http = "" if int(varinit.settings["long"]) == -1 else "http://"
    if not varinit.settings["no_more_departures"]: varinit.settings["no_more_departures"] = dicts.language[settings["language"]]["display"]["no_more_departures"]
    return ["((% "+dicts.language[settings["language"]]["display"]["sign"],#+" v" + settings["version"] + "     ",                   
            "WIFI: " + settings["ssid"] + "      ",
            dicts.language[settings["language"]]["display"]["your_settings"],
            http,
            "((% ",
            "",
            varinit.settings["no_more_departures"] + " "*200,
            dicts.language[settings["language"]]["display"]["check_connection"] + ": http://",
            "Besök t-skylt.se för driftstatus",
            dicts.language[settings["language"]]["display"]["_north_south"],
            dicts.language[settings["language"]]["display"]["_north"],
            dicts.language[settings["language"]]["display"]["_south"]]

def colors():
    varinit.group.hidden = False
    factor = int(varinit.settings["brightness"])+1
    if not varinit.settings["color"]: _color = (factor*50,factor*20,0)
    elif varinit.settings["color"] == 1: _color = (factor*40,factor*20,0)
    elif varinit.settings["color"] == 2: _color = (factor*20,factor*20,factor*20)
    varinit.palette[1] = _color
    try: varinit.dest_palette[1] = _color
    except: pass
    try:
        varinit.overlay_palette[1] = _color
        varinit.overlay_palette[2] = varinit.palette[2]
    except: pass

def get_deviations():
    if not len(varinit.deviations_list):
        data = fetch_data(host="data.t-skylt.se", port=89, args="/v1/messages?future=false&transport_mode=METRO&transport_mode=TRAM&transport_mode=TRAIN&transport_mode=SHIP")
        data = json.loads(data)
        for all in data:
            importance = all["priority"]["importance_level"] * all["priority"]["influence_level"] * all["priority"]["urgency_level"]
            if importance > 20:
                try: 
                    if "Närtrafiken" in all["scope"]["lines"][0]["name"]: continue
                    if not all["scope"]["lines"][0]["name"] + ": " + all["message_variants"][0]["header"] in varinit.deviations_list:
                        varinit.deviations_list.append(all["scope"]["lines"][0]["name"] + ": " + all["message_variants"][0]["header"])
                except: pass
    print(*varinit.deviations_list, sep='\n')
    return varinit.deviations_list.pop(0)

def convert_date(dt):
    if_gmt = 60 * (60*2) if "GMT" in dt else 0
    print("■ RFC1123: ", dt)
    try: varinit.today = dt.split(",")[0].replace(" ", "")
    except: pass
    for x in dicts.weekday:
        try: dt = dt.split(x)[1][2:]
        except: continue
    _date = dt.split()[0][:2]
    __month = dt.split(_date + " ")[1][:3]
    _month = dicts.month[__month]
    _year = dt.split(__month + " ")[1][:4]
    _hour = dt.split(_year + " ")[1][:2]
    _minute = dt.split(_hour + ":")[1][:2]
    _second = dt.split(_minute + ":")[1][:2]
    
    if not varinit.first_start: varinit._currenttime = (_hour + ":" + _minute)
    _newtime = time.mktime(time.struct_time((int(_year), int(_month), int(_date), int(_hour), int(_minute), int(_second), 0, 0, -1)))
    return _newtime + if_gmt

def manual_dns():
    try:
        print("Attempting manual DNS settings:")
        with open("no_dhcp") as f: no_dhcp = json.loads(f.read())
        for lines in no_dhcp: print(lines, no_dhcp[lines])
        print("---------------------------------------")
        wifi.radio.stop_dhcp()
        new_ip = no_dhcp["ip"]
        new_netmask = no_dhcp["netmask"]
        new_gateway = no_dhcp["gateway"]
        new_dns = no_dhcp["dns"] if len(no_dhcp["dns"]) > 5 else "8.8.8.8"
        wifi.radio.set_ipv4_address(ipv4=ipaddress.IPv4Address(new_ip), netmask=ipaddress.IPv4Address(new_netmask), gateway=ipaddress.IPv4Address(new_gateway), ipv4_dns=ipaddress.IPv4Address(new_dns)) # 
        print("Setting new IP: ", new_ip)
    except: pass

def wifiattempt(errmsg=True, _timeout=None, skipversion=False):
    _timeout = 5
    if "no_dhcp" in os.listdir(): manual_dns()
    #if varinit.settings["ssid"] == "my_ssid": return
    if wifi.radio.connected == True: return
    try:
        wifi.radio.enabled = True
        wifi.radio.connect(ssid=varinit.settings["ssid"], password=varinit.settings["password"].replace("%23","#"), timeout=_timeout)
        print("Connected to ", varinit.settings["ssid"])
        if not varinit.first_start: sysprint(varinit.settings["ssid"], 100, cls=topbottom)
    except Exception as e: 
        print("WIFI fail for " + varinit.settings["ssid"] + ": ", e)
        varinit.network_delay = 20 if "authentication" in str(e).lower() else 5
        if errmsg:
            if not varinit.first_start: sysprint(str(e), 100, _refresh=True, cls=topbottom, _delay=1)

def check_version():
    try: 
        try: 
            ver_txt = json.loads(fetch_data(host="t-skylt.se", port=80, args="/update/ver.txt",filetype="text"))
            varinit.new_ver = ver_txt["ver"]
            print(varinit.new_ver)
        except: print("Failed to download ver.txt")
        
        if float(varinit.new_ver) > float(varinit.settings["version"]): varinit.new_version_available = 1
        else: print("No new version available")
        #try: varinit.dicts.country_and_operators = ver_txt["country_and_operators"]
        #except: print("Failed to append Operators/Countries")
        try: varinit.ad_delay = ver_txt["ad_delay"]
        except: print("Failed to set advertisement-delay, using default: ", varinit.ad_delay)
        try: varinit.temperature_threshold = ver_txt["temperature_threshold"]
        except: print("Failed to set temperature_threshold, using default: ", varinit.temperature_threshold)
        try: varinit.socket_timeout = ver_txt["socket_timeout"]
        except: print("Failed to set socket_timeout, using default: ", varinit.socket_timeout)
    except:
        varinit.new_version_available = 0
        print("Failed to verify latest version")

def start_ap():
    try:
        #wifi.radio.start_ap(ssid=varinit.ap_name, password=str(pwd_gen()), authmode=(wifi.AuthMode.PSK, wifi.AuthMode.WPA2))
        ap_name = "matrixbox-" + "".join([hex(i) for i in wifi.radio.mac_address]).replace("0x","")[:3] # mac-id för hotspot
        ap_name = str(ap_name)
        wifi.radio.start_ap(ssid=ap_name)
        #wifi.radio.start_dhcp_ap() # Removed DHCP, maybe causing bug http://None ?
        print("Started AP: ", varinit.ap_name)#,pwd_gen())
    except Exception as e: print("Failed to start AP: ", e)

def scan():
    netlist = []
    for networks in wifi.radio.start_scanning_networks(start_channel=1, stop_channel=14):
        if not networks.ssid == varinit.settings["ssid"]: netlist.append(networks.ssid)
        print(networks.ssid)
    wifi.radio.stop_scanning_networks()
    return(netlist)

def disp_init():
    varinit.tg1, varinit.tg2 = displayio.TileGrid(top, pixel_shader=palette), displayio.TileGrid(bottom, pixel_shader=palette)
    varinit.tg3 = displayio.TileGrid(topbottom, pixel_shader=palette)
    varinit.group = displayio.Group()
    tg1group, tg2group = displayio.Group(), displayio.Group()
    tg1group.append(varinit.tg1); tg2group.append(varinit.tg2)
    varinit.group.append(tg1group); varinit.group.append(tg2group)
    tg3group = displayio.Group()
    tg3group.append(varinit.tg3)
    varinit.group.append(tg3group)
    varinit.tg1.x = 0; varinit.tg1.y = 0
    varinit.tg2.x = varinit.if_long; varinit.tg2.y = 16
    varinit.tg3.y = 32
    varinit.palette[2] = (50,50,50)    # vit
    varinit.palette[3] = 0x000765      # morkbla
    varinit.palette[4] = (100,0,0)     # rod
    varinit.palette[5] = (20,20,20)    # grå
    varinit.palette[6] = (20,20,20)    # grå
    varinit.palette[7] = (0,20,0)    # grå
    varinit.display.root_group = varinit.group
    varinit.text = load_text()
    # Destination text smooth-scroll TileGrids (one bitmap per row, transparent background)
    _max_rows = max(8, varinit.if_tall // 6)
    _dest_bmp_w = max(400, varinit.if_long * 3)
    _dest_palette = displayio.Palette(2)
    _dest_palette[0] = 0x000000
    _dest_palette.make_transparent(0)
    _dest_palette[1] = 0xFF6600  # will be updated by colors()
    varinit.dest_palette = _dest_palette
    varinit.dest_bmps = [displayio.Bitmap(_dest_bmp_w, 13, 2) for _ in range(_max_rows)]
    varinit.dest_tgs = [displayio.TileGrid(varinit.dest_bmps[i], pixel_shader=_dest_palette, x=0, y=0) for i in range(_max_rows)]
    _dest_tg_group = displayio.Group()
    for _dtg in varinit.dest_tgs:
        _dtg.hidden = True
        _dest_tg_group.append(_dtg)
    varinit.group.append(_dest_tg_group)
    # Overlay TileGrid: line ID + minutes text drawn on top of dest TileGrids (transparent bg)
    varinit.overlay_palette = displayio.Palette(10)
    for _i in range(10): varinit.overlay_palette[_i] = varinit.palette[_i]
    varinit.overlay_palette.make_transparent(0)
    varinit.overlay_bmp = displayio.Bitmap(topbottom.width, topbottom.height, 10)
    varinit.overlay_tg = displayio.TileGrid(varinit.overlay_bmp, pixel_shader=varinit.overlay_palette, x=0, y=0)
    varinit.overlay_tg.hidden = True
    _overlay_group = displayio.Group()
    _overlay_group.append(varinit.overlay_tg)
    varinit.group.append(_overlay_group)
    varinit.dest_scroll_state = {}  # row_x -> {"overflow": int, "pos": int, "pause_end": float, "start_x": int}
    #if varinit.if_long > 128: varinit.palette[2] = (50,30,0)      # svart


def refresh(times = 2):
    if cpver == 9 and microcontroller.cpu.frequency == 160000000:
        if varinit.if_long > 128: return display.refresh(minimum_frames_per_second=0)
        if varinit.tg2.x > 64:
            time.sleep(0.001) ########## REMOVED for smoother scroll
        display.refresh(minimum_frames_per_second=0)
        delay = 0.002
        if not int(varinit.settings["scroll"]): return
        if varinit.tg2.x > 64:
            time.sleep(0.001) ########## REMOVED for smoother scroll
        for i in range(2 + int(varinit.settings["scroll"])):
            if varinit.cpver == 9: time.sleep(delay)
            display.refresh(minimum_frames_per_second=0)
    else:
        for i in range(times): display.refresh(minimum_frames_per_second=0)

def lights(switch):    
    varinit.group.hidden = True
    if switch: colors()

def nightcheck(force=False, _switch=False, turnon=False):
    if not check_timer(): 
        varinit.group.hidden = 1
        return


    if _switch: varinit.on_off_counter = 1 - varinit.on_off_counter
    if turnon: 
        varinit.group.hidden = 1 - varinit.group.hidden
        varinit.shared["nightcount"] = 0
        return
    
    if force: return lights(True)
    elif varinit.on_off_counter == 0 or int(varinit.settings["sleep"]) == 1 and varinit.shared["nightcount"] > 1:
        if not varinit.group.hidden: return lights(False)
    else: lights(True)
    
def fetch_data(host, port=80, args="", headers = "", filetype="text"):
    if varinit.if_long > 128 and not int(varinit.settings["listmode"]): version_delay(slowdown=1)
    
    data = ""
    cache = ""
    try: _from = binascii.hexlify(varinit.settings["stations"]["1"]["mystation"]).decode("utf-8")
    except: _from = binascii.hexlify(bytearray(varinit.settings["stations"]["1"]["mystation"])).decode("utf-8")
    headers = "User-Agent: " + str(id) + "\r\n"
    headers += "Accept: application/json\r\n" + "Content-Type: application/json\r\n" + "Host: " + host + "\r\n" + "Version: " + str(varinit.settings["version"]) + "\r\n"
    headers += "Uptime: " + str(round((time.monotonic() - varinit.starttime)/60)) + "\r\n"
    headers += "OS-Version: " + str(varinit.cpver) + "\r\n"
    headers += "Country: " + str(varinit.settings["stations"]["1"]["country"]) + "\r\n"
    headers += "Operator: " + str(varinit.settings["stations"]["1"]["operator"]) + "\r\n"
    headers += "Siteid: " + str(varinit.settings["stations"]["1"]["siteid"]) + "\r\n"
    headers += "From: " + str(_from) + "\r\n"
    headers += "Version: " + "d" + str(varinit.version) + "\r\n"
    headers += "User: " + str(varinit.settings["user"]) + "\r\n"
    headers += "Temperature: " + str(round(microcontroller.cpu.temperature))
    print("-Fetching------------------------------------------------ ")
    print("■ HOST: ", host)
    print("■ ARGS: ", args)
    print("■ PORT: ", port)
    print("■ FILETYPE: ", filetype)
    request = b"GET " + args + " HTTP/1.0\r\n" + headers + "\r\n\r\n"
    try:
        #with pool.socket(pool.AF_INET, pool.SOCK_STREAM) as s:
        with pool.socket() as s:
            cache = bytearray(1024)                                # MAX FILESIZE
            #s.setblocking(False)
            s.settimeout(min(varinit.socket_timeout, 8))   # cap the stall window (watchdog safety)
            s.connect((host, port))
            sent = s.sendall(request)
            #buff = bytearray(512)
            buff = bytearray(512)
            data = s.recv_into(buff)
            while data:
                cache += buff[:data]
                data = s.recv_into(buff)
    except Exception as e: 
        print("Socket error: ", e)
        #if "-2" in str(e): reset()
        #if "-2" in str(e): wifi.radio.enabled = False                  ######## TESTAR
            
    except: print("Socket error")
    try:
        if filetype == "binary":
            separator = b'\r\n\r\n'
            index = cache.find(separator)
            if index != -1: cache = cache[index+len(separator):]
            return cache
        x = cache.decode("utf-8")
        data = x.split("\r\n\r\n",1)[1]
    except: print("Reading error")
    
    try:
        date = x.split("Date:",1)[1]
        date = date.split("\r\n")[0]
        varinit.currenttime = convert_date(date)
    except: pass
    print("--------------------------------------------------------- ")
    if varinit.if_long > 128 and not int(varinit.settings["listmode"]): version_delay(slowdown=2)
    #print("DATA ", data)
    return data

def sort_by_minutes(lst):
    def get_minutes(sub_lst): return int(sub_lst[3].split()[0])
    lst.sort(key=get_minutes)
    return lst

def sort_by_hours(lst):
    def __sort(lst):
        return sorted(lst, key=lambda x: x[3])

    if "23:" in str(lst):
        lst = json.dumps(lst)
        lst = json.loads(lst.replace("00:", "24:"))
        lst = __sort(lst)
        lst = json.dumps(lst)
        lst = json.loads(lst.replace("24:", "00:"))
        return lst
    return __sort(lst)


def _converttime(ts, age = 0): return time.mktime(time.struct_time((int(ts[:4]),int(ts[5:7]),int(ts[8:10]),int(ts[11:13]),int(ts[14:16]),int(ts[17:19]) + int(age),0,-1,-1)))

def traffic_parser(data, traffic_type, num="1"):
    ## Vänder "DIRECTION" på BUSES och TRAINS ##############
    stn = varinit.settings["stations"][num]
    direction = int(stn["direction"])
    night_buses_only = int(stn["buses_option"])
    if traffic_type in ("TRAIN", "BUS", "TRAM") and direction:
        direction = 3 - direction
    ########################################################
    print(" >>", traffic_type)
    dataout = []
    _maxdest = int(varinit.settings["maxdest"])
    if int(varinit.settings["listmode"]): _maxdest = varinit.if_tall // 8
    #show_lines = varinit.settings["show_lines"]
    #has_line_filter = isinstance(show_lines, list) and len(show_lines) > 0
    clocktime = varinit.settings["clocktime"]
    rt_indicator = varinit.settings["rt_indicator"]
    offset = int(stn["offset"])
    try: 
        if not data["departures"] and "msg" in data:
            return [["1", data["msg"], "***","",""]]
    except: pass
    for all in data["departures"]:
        if len(dataout) > _maxdest: break
        line = all["line"]
        if traffic_type != line["transport_mode"]: continue
        if traffic_type == "BUS" and stn["operator"] == "sl" and night_buses_only:
            if str(line["id"])[-2:-1] != "9":
                continue
        if len(str(varinit.settings["show_lines"])) > 4:
            print(str(varinit.settings["show_lines"]))
            if not all["line"]["id"].lower() in varinit.settings["show_lines"]: continue
        difference = _converttime(all["expected"]) - varinit.currenttime
        if difference < 0: continue
        minsleft = str(round(difference/60))
        if int(minsleft[:2]) > offset:  
            if line["transport_mode"] == "ZET":
                if int(line["id"]) < 18:
                    line["transport_mode"] = "TRAM"
                else: line["transport_mode"] = "BUS"

            if not int(all["direction_code"]) or not int(direction) or int(direction) == int(all["direction_code"]):
                _minsleft = str(all["expected"].split("T")[1][:5]) if clocktime else minsleft
                if line["id"] == "0": line["id"] = ""
                try: 
                    delay = all["deviations"][0] if rt_indicator else ""
                except: delay = ""
                dep = ["0", str(line["id"]), delay + all["destination"], _minsleft, str(all["direction_code"])]
                _strip_dest = varinit.settings.get("strip_dest", [])
                if isinstance(_strip_dest, list):
                    for _sd in _strip_dest:
                        if _sd: dep[2] = dep[2].replace(_sd, "").strip()
                if traffic_type != "METRO":
                    if line["transport_mode"] == traffic_type:
                        dep[2] = dep[2].split('(')[0]
                        dataout.append(dep)
                elif line["transport_mode"] == traffic_type:
                    if stn["operator"] != "sl":
                        dataout.append(dep)
                    else:
                        line_id = int(line["id"])
                        if (int(stn["green"]) and line_id in (17, 18, 19)) or \
                           (int(stn["red"]) and line_id in (13, 14)) or \
                           (int(stn["blue"]) and line_id in (10, 11)):
                            dataout.append(dep)
    return dataout

def prefetch_departures(num):
    # Pull the incoming station's departures JSON early and park it in the same cache
    # get_departure() reads from. Called from the switch screen so the network round
    # trip happens while the hold is on screen.
    try:
        stn = varinit.settings["stations"][num]
    except: return False
    # Nothing useful to fetch for an unconfigured slot; get_departure() shows its own
    # prompt for these and we must not set the cache flag on its behalf.
    try:
        if str(stn["siteid"]) in ("", "0", "00", "000") or not stn["operator"]: return False
    except: return False
    try:
        temperature_check()
        _data = fetch_data(host="data.t-skylt.se", port=90,
                           args='/get_departures?country=' + stn["country"] +
                                '&operator=' + stn["operator"] +
                                "&station=" + str(stn["siteid"]))
        if not _data: return False
        varinit.cached_departure_data[num] = json.loads(_data)
        varinit.use_cached_data = True
        print("■ Prefetched station", num)
        return True
    except Exception as e:
        # Never let a prefetch miss break the switch: get_departure() just fetches
        # normally afterwards, exactly like before.
        print("Prefetch failed:", type(e).__name__, e)
        return False

def get_departure(num = "1", dataout = [["1", "^ Data error","","",""]]):
    
    if varinit.settings["stations"][num]["siteid"] == "00" or not varinit.settings["stations"][num]["operator"]: return [["1", dicts.language[varinit.settings["language"]]["settings"]["select_operator"], "***","",""]]
    if varinit.settings["stations"][num]["siteid"] == "0": return [["1", dicts.language[varinit.settings["language"]]["settings"]["search"], "***","",""]]
    if varinit.settings["stations"][num]["siteid"] == "000": return [["1", dicts.language[varinit.settings["language"]]["display"]["select_station"], "***","",""]]
    if time.monotonic() > varinit.show_station_timer + varinit.show_station_interval and not varinit.shared["nightcount"]:
        if "demo" in os.listdir() or int(settings["show_my_station"]):
            _out = varinit.text[4]+ settings["stations"][num]["mystation"]
            if "demo" in os.listdir(): _out = "%-Skylt.se"
            if not varinit.settings["listmode"]: renderstring(_out, 1,0,1, _cls=top)
            else: renderstring(_out, 100, 0, 1)
        varinit.show_station_timer = time.monotonic()
    if varinit.use_cached_data and num in varinit.cached_departure_data:
        data = varinit.cached_departure_data[num]
        varinit.use_cached_data = False
        print("■ Using cached data for station", num)
    else:
      try: 
        temperature_check()
        _data = fetch_data(host="data.t-skylt.se", port=90, args='/get_departures?country=' + varinit.settings["stations"][num]["country"] + '&operator=' + varinit.settings["stations"][num]["operator"] + "&station=" + str(varinit.settings["stations"][num]["siteid"]))
        if _data: data = json.loads(_data)
        else: 
            varinit.active_message = True
            if str(wifi.radio.ipv4_address) == "0.0.0.0":   ########
                pass#wifi.radio.enabled = False                  ######## TESTAR
            return [["1", "-","","",""]]
      except Exception as e: 
        cls(topbottom)
        print(e)
        varinit.active_message = True
        errno = type(e).__name__
        try:
            if varinit.settings["debug"]: return [["1", str(errno) + " " + str(e),"","",""]] 
        except: pass
        err_msg = "*"
        if errno == "TypeError": err_msg = "**"
        if errno == "ValueError": err_msg = "***"#dicts.language[varinit.settings["language"]]["display"]["decoding_error"]
        print("Avkodningsfel: ", errno)
        return [["1", err_msg,"","",""]]
      except: 
        cls(topbottom)
        varinit.active_message = True
        print("Avkodningsfel.")
        return [["1", "^ Unknown error: 1","","",""]]
      varinit.cached_departure_data[num] = data
    try:
        dataout = []
        print("■", varinit.settings["stations"][num]["mystation"], varinit.settings["stations"][num]["siteid"])
        for t_types in varinit.traffic_dict:
            if varinit.settings["stations"][num][t_types]: dataout.extend(traffic_parser(data, t_types, num))
        if not varinit.settings["clocktime"]: dataout = sort_by_minutes(dataout)[slice(varinit.settings["maxdest"])]
        else: dataout = sort_by_hours(dataout)[slice(varinit.settings["maxdest"])]
        print(*dataout, sep='\n')
    except Exception as e: 
        print(e)
        cls(topbottom)
        try:
            if not data["departures"] and "msg" in data: return [["1", data["msg"], "***","",""]]
        except: pass
        return [["1", dicts.language[varinit.settings["language"]]["settings"]["no_data"],"***","",""]]
    return dataout

def reformat_data(trainlist):
    def top_screen_filter(tlist):
        try: tlist[1] = tlist[1][:varinit.settings["line_length"]]
        except: pass
        if not varinit.settings["clocktime"]: tlist[3] += varinit.settings["mins"]
        spacing = "((((((((("
        if varinit.if_long == 128:
            spacing = "((("
            if tlist[2] in station_names_dict:
                tlist[2] = station_names_dict[tlist[2]]
            else: 
                for items in dicts.replace_list_destinations:
                    if strlen(tlist[2]) > 75: tlist[2] = tlist[2].replace(items[0], items[1])

        # Keep the top row non-scrolling text from colliding with minutes-left text.
        # Measure widths with the top-row (large) font so fitting is stable.
        def _strlen_top(s):
            f = fonts[0]
            total = 0
            for c in s:
                if c in f:
                    total += f[c][0]
                else:
                    total += f["_"][0]
            return total

        max_left_w = max(0, varinit.if_long - _strlen_top(tlist[3]))

        # First consume extra gap before touching destination text.
        while len(spacing) > 1 and _strlen_top(tlist[1] + spacing + tlist[2]) > max_left_w:
            spacing = spacing[:-1]

        max_dest_w = max_left_w - _strlen_top(tlist[1] + spacing)
        if max_dest_w < 0:
            max_dest_w = 0

        if _strlen_top(tlist[2]) > max_dest_w:
            if max_dest_w <= 0:
                tlist[2] = ""
            else:
                trimmed = tlist[2]
                while trimmed and _strlen_top(trimmed + ".") > max_dest_w:
                    trimmed = trimmed[:-1]
                tlist[2] = trimmed + ("." if trimmed and trimmed != tlist[2] else "")

        offs = varinit.if_long - (strlen(tlist[3]) + strlen(tlist[1] + spacing + tlist[2]))
        if int(trainlist[0][0]): return trainlist
        
        #if varinit.if_long > 128: renderstring(tlist[1] + spacing + tlist[2] + ("(" * offs) + tlist[3], 1)
        #else:
        #    offs = 128 - strlen(tlist[3])
        #    renderstring(offs*"(" + tlist[3], 1)
        #    renderstring(tlist[1] + spacing + tlist[2], 1)
        
        offs = max(0, varinit.if_long - strlen(tlist[3]))
        renderstring(offs*"(" + tlist[3], 1)
        renderstring(tlist[1] + spacing + tlist[2], 1)

        return trainlist[1:]
    spacing = "" if varinit.if_long == 128 else "(("
    if not len(trainlist):                                                                             
        cls(top)
        cls(bottom)
        return varinit.text[6]
    if trainlist[0][0] == "1": return trainlist[0][1] + "  " + trainlist[0][2] + "  " + trainlist[0][3]  
    elif int(varinit.settings["listmode"]): return trainlist
    else: return "         ".join(["  ".join([a[1][:varinit.settings["line_length"]] + (spacing * 2), a[2] + (6 * spacing), a[3] + (varinit.settings["mins"] if not varinit.settings["clocktime"] else "") + (spacing * 10)]) for a in top_screen_filter(trainlist[0])])

def renderstring(_string, screen_partition = 0, min = 0, slow = 0, invertcolor = 0, shading=False, smallfont=False, sys_msg=False, shade=False, large=False, _cls=False, _refresh=False, ontop=False, block=False, logo=False, mini=False, start_x=0, clip_x=None, target_bmp=None, target_offs=None):
    
    if varinit.settings["long"] == -1: 
        mini = True
    if varinit.rotated:
        mini = True
    if varinit.display.width <= 64:
        mini = True
    
    if sys_msg: font_before = varinit.currentfont
    cls(_cls) if _cls else None
    #print("LEN: ", len(_string), _string, type(_string))
    if dicts.language[varinit.settings["language"]]["display"]["no_more_departures"] in _string: varinit.shared["nightcount"] += 1 
    elif str(_string) == "-" or str(_string) == "*": pass # testing
    else:
        if varinit.shared["nightcount"] > 1: varinit.on_off_counter = 1
        varinit.shared["nightcount"] = 0
    nightcheck()
    _color = False
    offs = 2
    pixwidth = start_x
    
    if not ontop and not varinit.settings["listmode"] and sys_msg:
        varinit.currentfont = 1
        varinit.tg3.y = 0
        
    if ontop: 
        screen_partition = 1
        if varinit.settings["listmode"]: offs = 0
    elif smallfont: varinit.currentfont = 1
    elif large: varinit.currentfont = 0
    
    
    if varinit.currentfont or screen_partition > 2: screen_location = [topbottom, topbottom, topbottom, topbottom]
    else: screen_location = [bottom, top, top, bottom]
    
    if screen_partition > 2: 
        _row_step = 6 if mini else (13 if varinit.currentfont == 0 else 8)
        offs = int(str(screen_partition)[1:]) * _row_step
        screen_partition = 0
    
    
    if sys_msg == "red": _color = (0,4)
    elif sys_msg == "blue": _color = (0,3)
    elif sys_msg == "green": _color = (0,7)
    elif sys_msg == "white": _color = (0,2)
    elif sys_msg == "yellow": _color = (0,1)
    
    font = fonts[varinit.currentfont]
    if smallfont == True: font = fonts[1]
    shade = False
    shading_width = 15
    _write_bmp = target_bmp if target_bmp is not None else screen_location[screen_partition]
    _write_offs = target_offs if target_offs is not None else offs
    
    if not sys_msg and int(varinit.settings["listcolor"]): shade = True
    if not sys_msg and wifi.radio.connected == False: 
        shade = True
        shading_width = 8
    
    
    for character in _string:
        if mini: 
            character = character.lower()
            varinit.currentfont = 2
            font = fonts[varinit.currentfont]
        
        if not character in font: character = "_"
        
        for width in range(font[character][0]):
            for height in range(font["fontheight"]):
                invertedwidth = font[character][0] - width
                if isinstance(font[character][1],int):
                    try: color = (font[character][height+1] >> invertedwidth) & 1
                    except: color = color
                    
                    #if logo and color == 1: color = 5
                    #if invertcolor and int(varinit.settings["listmode"]) and pixwidth > 98: color = 1 - color
                    if invertcolor == 2: color = 1 - color
                    if _color:
                        if not int(color): color = _color[0]
                        else: color = _color[1]
                    if clip_x is None or width + pixwidth < clip_x:
                        try: _write_bmp[width+pixwidth,(height)+_write_offs] = color
                        except: pass
                else: 
                    __color = int(font[character][height+1][width])
                    if varinit.settings["long"] == 1:
                        if __color == 5: __color = 1
                    
                    if clip_x is None or width + pixwidth < clip_x:
                        try: _write_bmp[width+pixwidth,(height)+_write_offs] = __color
                        except: pass
            if slow: varinit.display.refresh(minimum_frames_per_second=0)
        if isinstance(font[character][1],int):
            pixwidth += font[character][0]
        else: pixwidth += len(font[character][1])
    if _refresh: refresh()
    if sys_msg: varinit.currentfont = font_before
    return(pixwidth)

def scroll_mode(reveal=True):
    # reveal=False draws without refreshing, so the panel keeps its current frame until
    # the caller's next refresh.
    if varinit.matrix.height == 64: microcontroller.cpu.frequency = 180000000
    if varinit.if_long > 128: version_delay(slowdown=2)
    nightcheck()
    varinit.tg1.y, varinit.tg2.y, varinit.tg3.y = 0, 16, 32
    direction = varinit.text[9]
    scroll_buff = varinit.text[1]
    if varinit.shared["loop_counter"] == -7: reset()
    elif varinit.shared["loop_counter"] == -5:
        varinit.font = varinit.fonts[0]
        _logo = varinit.text[0]# if "boot.py" in os.listdir() else "% DEBUG"
        
        renderstring(_logo, 1, 0, 1, large=True, block=True, logo=True)
        wifiattempt()
        #check_version()
        varinit.first_start = False
        if varinit.settings["long"] == -1:
            varinit.settings["listmode"] = 1

        if varinit.new_version_available == 1: scroll_buff += " -    ^ " + dicts.language[varinit.settings["language"]]["display"]["new_version_available"] + str(varinit.new_ver)
        varinit.scrollsum = renderstring(scroll_buff, _cls=bottom)
        
    elif varinit.shared["loop_counter"] == -4:        
        if "textfil.txt" in os.listdir():
            
            try:
                varinit.scrollsum = renderstring(varinit.textfil.pop(0), _cls=bottom)
            except: 
                renderstring("Läser in text...", 1, 0, large=True, _cls=top)
                varinit.scrollsum = renderstring("***", _cls=bottom)
                with open("textfil.txt") as f:
                    varinit.textfil = f.read().splitlines()
                print(varinit.textfil)
                renderstring("", 1, 0, large=True, _cls=top)
            varinit.shared["loop_counter"] = -5
            
            print("TEXT")
        else:
            renderstring(str(varinit.text[2]), 1, 0, large=True)
            varinit.scrollsum = renderstring(varinit.text[3]+str(wifi.radio.ipv4_address)+"         ", _cls=bottom)


    elif varinit.shared["loop_counter"] == -3:   
        
        
        renderstring(varinit.text[4]+ varinit.settings["stations"][varinit.active_station]["mystation"][:16], 1, 0, large=True, _cls=top)
        if varinit.settings["direction"] == 1: direction = varinit.text[10]
        elif varinit.settings["direction"] == 2: direction = varinit.text[11]
        ifoffset = " + " + str(varinit.settings["stations"][varinit.active_station]["offset"]) + varinit.settings["mins"] if int(varinit.settings["stations"][varinit.active_station]["offset"]) else ""
        varinit.text[5] = direction + "   >   " + str(varinit.settings["maxdest"]) + dicts.language[varinit.settings["language"]]["display"]["departures"] + ifoffset
        varinit.scrollsum = renderstring(varinit.text[5], large=True, _cls=bottom)
        varinit.shared["loop_counter"] = -2
    varinit.tg2.x = varinit.if_long
    varinit.shared["loop_counter"]+=1
    if varinit.shared["loop_counter"] > 0:
        if varinit.active_message == True:
            reset_scroll()
            varinit.active_message = False
        elif time.monotonic() > varinit.shared["scroll_timer"] + updatedelay:
            cls(bottom, _refresh=reveal)
            if time.monotonic() > varinit.ad_timer + varinit.ad_delay * 60 and varinit.shared["nightcount"] < 2:
                try:
                    ad = ad_message()
                    if ad: 
                        varinit.scrollsum = renderstring(reformat_data([["1", ad,"***","",""]]), large=True, _cls=bottom)
                        varinit.active_message = True
                    else: varinit.scrollsum = renderstring(reformat_data(get_departure(num=varinit.active_station)), large=True)
                except: varinit.scrollsum = renderstring(reformat_data(get_departure(num=varinit.active_station)), large=True)
            
            elif time.monotonic() > varinit.deviations_timer + (varinit.deviations_delay * 60) \
                and int(varinit.settings["show_msgs"]) and varinit.shared["nightcount"] < 2 \
                and varinit.settings["stations"][varinit.active_station]["operator"] == "sl":
                try: varinit.scrollsum = renderstring(reformat_data([["1", get_deviations(),"***","",""]]), large=True, _cls=bottom)
                except: varinit.scrollsum = renderstring(reformat_data([["1", " ","***","",""]]), large=True, _cls=bottom)
                varinit.deviations_timer = time.monotonic()
                varinit.active_message = True
            else: varinit.scrollsum = renderstring(reformat_data(get_departure(num=varinit.active_station)), large=True)
            rnd = random.randint(0, 10)
            varinit.shared["scroll_timer"] = time.monotonic() + rnd
            print("RND: ", rnd)
 
def list_mode(mini=False, half=False):
    mini = varinit.settings["mini"]

    #### debug
    #mini = True
    if varinit.rotated:
        mini = True
        half = False
    elif varinit.display.width <= 64:
        mini = True
        half = False
    elif varinit.settings["multiple"]: 
        half = True
        mini = True
    if varinit.settings["long"] == -1 and not varinit.rotated: 
        mini = True
        half = True
     


    if varinit.if_long > 128: version_delay(slowdown=1)
    large_list = not mini and not half and not varinit.rotated and int(varinit.settings.get("large_list", 0))
    xs_line_id = varinit.display.width <= 64 and not varinit.rotated and int(varinit.settings.get("xs_line_id", 0))
    varinit.currentfont = 1
    if mini: varinit.currentfont = 2
    elif large_list: varinit.currentfont = 0
    extrarow = 1 if mini else 0
    varinit.tg1.y, varinit.tg2.y, varinit.tg3.y = extrarow + 0-32, extrarow + 16-32, extrarow + 0

    _dest_scroll = int(varinit.settings.get("dest_scroll", 0))
    _now = time.monotonic()
    cls(topbottom)
    # Hide dest TileGrids and overlay; will be shown per-row if dest_scroll active
    try:
        for _dtg in varinit.dest_tgs: _dtg.hidden = True
        varinit.overlay_tg.hidden = True
        varinit.overlay_bmp.fill(0)
        varinit.dest_scroll_state = {}
    except: pass

    if varinit.shared["startup"]:
        list_splash()
        varinit.shared["startup"] = False
        return time.monotonic() - varinit.updatedelay + 2
    if varinit.shared["loop_counter"] == -7: reset()
    if time.monotonic() > varinit.ad_timer + varinit.ad_delay * 60 and varinit.shared["nightcount"] < 2:
        try: 
            ad = ad_message()
            if ad:
                index = 0
                for i in range(0, 4):
                    _ad = ad[index:index+15].lstrip(" ")
                    renderstring(str(_ad), 100+i, shading=True, smallfont=True)
                    refresh()
                    index += 15
            else: return 0
        except: pass
        return time.monotonic() - varinit.updatedelay + 2
    
    # trainlist = reformat_data(get_departure(num=varinit.active_station))
    ### DEBUG
    
    _r = 1
    try:
        if varinit.settings["multiple"]:
            if varinit.settings["long"] == 0: _r = 2
            if varinit.settings["long"] == 1: _r = 3
        else: _r = 1
    except: pass
    
    for i in range(_r):
        _fnum = str(i+1) if int(varinit.settings.get("multiple", 0)) else varinit.active_station
        print("Fetching: ", _fnum)
        varinit.traindata[i+1] = reformat_data(get_departure(num = _fnum))
        if not half or i+1 == _r: break
        
    
    
    
    try:
    
        if varinit.settings["long"] == -1: num = 1
        if varinit.settings["long"] == 0: num = 2
        if varinit.settings["long"] == 1: num = 3

        #num=varinit.no_of_screens_flag
        
        for record in varinit.traindata:
            print(record)
            trainlist = varinit.traindata[record]
            if isinstance(trainlist, list):
                trainlist = [row[:] for row in trainlist if isinstance(row, list)]
            if int(record) > _r: continue
            if not half and "str" in str(type(trainlist)): 
                sysprint("".join(trainlist[:30]), 100)
                if dicts.language[settings["language"]]["display"]["no_more_departures"] in trainlist: return time.monotonic()
                return time.monotonic() - varinit.updatedelay + 2
            elif "str" in str(type(trainlist)): 
                print(trainlist)
                #sysprint("".join(trainlist[:30]), 100)
                trainlist = [["","",trainlist[:40],"",""]]
                    #continue
                #if dicts.language[settings["language"]]["display"]["no_more_departures"] in trainlist: 
                #    return time.monotonic()
                #if not half: return time.monotonic() - varinit.updatedelay + 2
        
            if large_list and isinstance(trainlist, list):
                _max_lw = 0
                for _a in trainlist:
                    if isinstance(_a, list) and len(_a) > 1:
                        _w = strlen(_a[1][:varinit.settings["line_length"]])
                        if _w > _max_lw: _max_lw = _w
                line_col = _max_lw + 6
            else:
                line_col = 0
            for x, all in enumerate(trainlist):
                
                
                all[2] = all[2].split('(')[0].split(" via")[0]#.lower()
                _strip_dest = varinit.settings.get("strip_dest", [])
                if isinstance(_strip_dest, list):
                    for _sd in _strip_dest:
                        if _sd: all[2] = all[2].replace(_sd, "").strip()
                if strlen(all[2]) > 82 and varinit.if_long == 128:
                    for items in dicts.replace_list_destinations:
                        all[2] = all[2].replace(items[0], items[1])
                    try: all[2] = station_names_dict[all[2]]
                    except: pass

                mins_cut = 23 - len(varinit.settings["mins"]) - (int(varinit.settings["line_length"]))

                if len(all[3]) > 1:
                       mins_cut -= 1

                if_not_clocktime = varinit.settings["mins"] if all[3] \
                and not varinit.settings["clocktime"] else ""

                all[3] += if_not_clocktime

                _full_dest_w = 0
                _max_px = 0
                _line_col_w = 0
                if varinit.rotated or varinit.display.width <= 64:
                    _w = varinit.if_long if varinit.rotated else varinit.display.width
                    _max_px = _w - strlen(all[3])
                    if not varinit.rotated and xs_line_id:
                        _max_px -= strlen(all[1][:varinit.settings["line_length"]]) + 2
                    while len(all[2]) > 0 and strlen(all[2]) > _max_px:
                        all[2] = all[2][:-1]
                elif large_list:
                    _max_px = varinit.if_long - strlen(all[3]) - line_col
                    _font = fonts[varinit.currentfont]
                    while len(all[2]) > 0 and sum(_font.get(c, _font['_'])[0] for c in all[2]) > max(0, _max_px):
                        all[2] = all[2][:-1]
                elif not half:
                    _line_col_w = strlen(varinit.settings["line_length"] * ("((((" if mini else "(((((("))
                    _max_px = varinit.if_long - strlen(all[3]) - _line_col_w - 2
                    _full_dest_w = strlen(all[2])
                    if not (_dest_scroll and _full_dest_w > max(0, _max_px)):
                        while len(all[2]) > 0 and strlen(all[2]) > max(0, _max_px):
                            all[2] = all[2][:-1]
                if half: 
                    all[2] = all[2][:15 - len(varinit.settings["mins"])]
                    if varinit.settings["clocktime"]:
                        all[2] = all[2][:11]
                mins = all[2]
                if not varinit.settings["clocktime"]: all[1] = "1(1(" if all[1] == "11" else all[1]

                if mini: all[2] = mins
                all[1] = all[1][:varinit.settings["line_length"]]
                
                line = all[1]
                dest = all[2]
                
                if varinit.rotated:
                    offs = varinit.if_long - strlen(all[3])
                elif varinit.display.width <= 64:
                    offs = varinit.display.width - strlen(all[3])
                else: offs = varinit.if_long - strlen(all[3])
                if half: 
                    all[3] = all[3].replace(" " + if_not_clocktime,"")
                    offs = 64 - strlen(all[3])

                    

                minsleft = offs*"(" + all[3]
                
                inv = 0

                if half: minsleft = minsleft.replace(" " + if_not_clocktime, "")
                
                if half: multiple_offset = int(num - 1) * (" " * 64)
                    
                
                else: multiple_offset = ""
        
                min_color = "white" if varinit.settings.get("listcolor_time", 0) or varinit.rotated else "yellow"
                lin_color = "yellow" if not varinit.settings["listcolor"] else "white"
                if varinit.rotated or varinit.display.width <= 64:
                    added_space = ""
                    line = ""
                    if not varinit.rotated and xs_line_id:
                        line = all[1][:varinit.settings["line_length"]]
                        added_space = (strlen(line) + 2) * "("
                elif mini:
                    added_space = varinit.settings["line_length"] * "(((("
                    if half: added_space = ""
                else: added_space = varinit.settings["line_length"] * "(((((("
                if not varinit.settings["line_length"]: 
                    added_space = ""
                    line = ""

                
                if large_list:
                    _lpart = 100 + x
                    _dest_pad = line_col * "("
                    renderstring(multiple_offset + minsleft, _lpart, 0, 0, inv, sys_msg=min_color)
                    renderstring(multiple_offset + _dest_pad + dest, _lpart, 0, 0, inv)
                    if not half and not varinit.rotated: renderstring(multiple_offset + line, _lpart, 0, 0, inv, sys_msg=lin_color)
                    if x > 4: continue
                else:
                    _use_tg = (_dest_scroll and not half and not varinit.rotated
                               and varinit.display.width > 64
                               and _full_dest_w > max(0, _max_px))
                    if _use_tg:
                        # TileGrid smooth scroll: dest in dest_bmp, line+mins in overlay_bmp
                        _row_step = 6 if mini else 8
                        _overflow = _full_dest_w - _max_px
                        varinit.dest_bmps[x].fill(0)
                        renderstring(dest, 100+x, 0, 0, inv, mini=mini,
                                     target_bmp=varinit.dest_bmps[x], target_offs=0)
                        varinit.dest_tgs[x].x = _line_col_w
                        varinit.dest_tgs[x].y = extrarow + x * _row_step
                        varinit.dest_tgs[x].hidden = False
                        varinit.dest_scroll_state[x] = {
                            "overflow": _overflow, "pos": 0,
                            "pause_end": _now + x * 0.8 + 2.0, "start_x": _line_col_w
                        }
                        renderstring(multiple_offset + minsleft, 100+x, 0, 0, inv, mini=mini,
                                     sys_msg=min_color, target_bmp=varinit.overlay_bmp)
                        if not half and not varinit.rotated and (varinit.display.width > 64 or xs_line_id):
                            renderstring(multiple_offset + line, 100+x, 0, 0, inv, mini=mini,
                                         sys_msg=lin_color, target_bmp=varinit.overlay_bmp)
                        varinit.overlay_tg.y = extrarow
                        varinit.overlay_tg.hidden = False
                    else:
                        renderstring(multiple_offset + minsleft, 100+x, 0, 0, inv, mini=mini, sys_msg=min_color)
                        renderstring(multiple_offset + added_space + dest, 100+x, 0, 0, inv, mini=mini)
                        if not half and not varinit.rotated and (varinit.display.width > 64 or xs_line_id):
                            renderstring(multiple_offset + line, 100+x, 0, 0, inv, mini=mini, sys_msg=lin_color)
                    if x > varinit.if_tall // 8 - 1: continue
            num -= 1
            
    except Exception as e: print("ERROR ", e)
    refresh()

    return time.monotonic()

def list_splash(_settings=False):
    direction = varinit.text[9]
    lastrow = 103 if int(varinit.settings["long"]) == -1 else 102
    extra_space = " " if int(varinit.settings["long"]) == -1 else ""
    if varinit.settings["direction"] == 1: direction = varinit.text[10]
    if varinit.settings["direction"] == 2: direction = varinit.text[11]
    varinit.text[5] = extra_space + direction
    if varinit.shared["startup"] == 1 or _settings:
        sysprint(extra_space + varinit.text[2], lastrow, _refresh=False)
        sysprint(varinit.text[3]+str(wifi.radio.ipv4_address), lastrow+1, _refresh=False)
    else:
        if int(varinit.settings["stations"]["1"]["offset"]):
            sysprint(str(dicts.language[settings["language"]]["display"]["hiding"]) + str(varinit.settings["stations"]["1"]["offset"]) + varinit.settings["mins"], 102, _refresh=False)
    sysprint("%"+str(varinit.settings["stations"]["1"]["mystation"]), 100, _refresh=False)
    sysprint(varinit.text[5], 101, _refresh=True)

def update_screen():
    
    lastrow = 103 if int(varinit.settings["long"]) == -1 else 102
        
    if wifi.radio.connected == True: return
    renderstring("1. " + dicts.language[varinit.settings["language"]]["display"]["connect_to"], 100, shading=True, smallfont=True, _cls=topbottom)
    renderstring("1. ", 100, shading=True, smallfont=True, sys_msg="white")

    macid = "matrixbox-" + "".join([hex(i) for i in wifi.radio.mac_address]).replace("0x","")[:3] # mac-id för hotspot
    renderstring(str(macid), 101, shading=True, smallfont=True)
    #renderstring("t-skylt" + id[-2:], 101, shading=True, smallfont=True)
    
    renderstring("2. " + dicts.language[varinit.settings["language"]]["display"]["go_to"], lastrow,shading=True, smallfont=True)
    
    renderstring("2. ", lastrow,shading=True, smallfont=True, sys_msg="white")
    
    renderstring("http://" + str(wifi.radio.ipv4_address_ap), lastrow+1,shading=True, smallfont=True, _refresh=True)

def savesettings(_settings=varinit.settings, saved=dicts.language[varinit.settings["language"]]["display"]["saving"]):
    varinit.group.hidden = True; refresh()
    try:
        with open("settings.txt", "w") as f:
            f.write(json.dumps(_settings))
        print("Saved!")
    except: saved = "Read only"
    varinit.group.hidden = False; refresh()
    sysprint(saved, 0, color="red", shading=True, _refresh=True, ontop=True)
    reset_scroll(_delay=0.5)

try: 
    import font_mini
    dicts.font_mini = font_mini
    varinit.fonts.append(font_mini.font_mini)
    #print(len(varinit.fonts))
except:
    print("Not imported: font_mini")
    print("Attempting download...")
