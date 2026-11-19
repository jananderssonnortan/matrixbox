"""
Off-device test harness for the 'departures' app.

Runs the UNMODIFIED app code on normal Python by mocking the CircuitPython
hardware layer (displayio / microcontroller / ampule / wifi / requests), then:

  * asserts pure logic (dinner time-gate, station rotation), and
  * composites the display tilegrids so render output can be checked / saved.

Usage:
    python3 tests/harness.py            # run assertions, print PASS/FAIL
    python3 tests/harness.py --render   # also write PNGs/GIF to tests/out/

No device or network needed.
"""
import sys, os, types, tempfile, contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, "apps", "departures")
LIB = os.path.join(ROOT, "lib")
OUT = os.path.join(HERE, "out")

# ------------------------------------------------------------------ mock hardware
def _to_rgb(v):
    if isinstance(v, (tuple, list)):
        return tuple(int(c) for c in v) if len(v) == 3 else (0, 0, 0)
    v = int(v); return (v >> 16 & 255, v >> 8 & 255, v & 255)

class Bitmap:
    def __init__(self, w, h, n=0):
        self.width, self.height = int(w), int(h)
        self._px = [[0] * self.width for _ in range(self.height)]
    def __getitem__(self, k):
        x, y = k
        return self._px[y][x] if 0 <= y < self.height and 0 <= x < self.width else 0
    def __setitem__(self, k, val):
        x, y = k
        if 0 <= y < self.height and 0 <= x < self.width: self._px[y][x] = int(val)
    def fill(self, v):
        for r in self._px:
            for i in range(len(r)): r[i] = int(v)

class Palette:
    def __init__(self, n, dither=False):
        self._c = [(0, 0, 0)] * int(n); self._transparent = set()
    def __setitem__(self, i, v): self._c[i] = _to_rgb(v)
    def __getitem__(self, i): return self._c[i]
    def __len__(self): return len(self._c)
    def make_transparent(self, i): self._transparent.add(i)
    def make_opaque(self, i): self._transparent.discard(i)

class Group(list):
    def __init__(self, *a, **k):
        super().__init__(); self.hidden = False; self.x = 0; self.y = 0

class TileGrid:
    def __init__(self, bitmap, pixel_shader=None, x=0, y=0, **k):
        self.bitmap = bitmap; self.pixel_shader = pixel_shader
        self.x = int(x); self.y = int(y); self.hidden = False

def _install_mocks():
    displayio = types.ModuleType("displayio")
    displayio.Bitmap, displayio.Palette = Bitmap, Palette
    displayio.Group, displayio.TileGrid = Group, TileGrid
    displayio.release_displays = lambda: None
    mc = types.ModuleType("microcontroller")
    mc.cpu = types.SimpleNamespace(temperature=40.0, frequency=240000000)
    mc.reset = lambda: None
    am = types.ModuleType("ampule"); am.routes = []
    am.route = lambda *a, **k: (lambda f: f); am.listen = lambda *a, **k: None
    ch = types.ModuleType("createhtml")   # stub: breaks the web import chain
    for n, m in [("displayio", displayio), ("microcontroller", mc),
                 ("ampule", am), ("createhtml", ch)]:
        sys.modules[n] = m

# __main__ globals the app imports (`from __main__ import ...`)
wifi = types.SimpleNamespace(radio=types.SimpleNamespace(
    connected=True, ap_active=False, ipv4_address="192.168.1.113",
    mac_address=b"\x01\x02\x03\x04\x05\x06", tx_power=9.0))
display = types.SimpleNamespace(width=128, height=32, rotation=0, root_group=None,
                                auto_refresh=False, refresh=lambda *a, **k: None)
matrix = types.SimpleNamespace(width=128, height=32)
pool = types.SimpleNamespace(socket=lambda *a, **k: None)
requests = types.SimpleNamespace(get=lambda *a, **k: types.SimpleNamespace(text="", close=lambda: None))

def boot():
    """Import the real app modules under the mock layer. Returns (functions, varinit)."""
    _install_mocks()
    # the app does `from __main__ import wifi/pool/requests/display/matrix`;
    # inject them onto __main__ so this works whether run directly or imported.
    import __main__ as _m
    _m.wifi, _m.pool, _m.requests = wifi, pool, requests
    _m.display, _m.matrix = display, matrix
    sys.path[:0] = [APP, LIB]
    os.chdir(tempfile.mkdtemp())
    open("settings.txt", "w").write("{}")   # app fills defaults
    with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
        import functions, varinit
    functions.refresh = lambda *a, **k: None
    functions.disp_init(); functions.colors()
    # keep the real implementations around: tests stub these, and a later test may need the
    # genuine one back (e.g. the fetch-budget test, which must exercise real network calls).
    functions._orig = {n: getattr(functions, n) for n in
                       ("get_weather", "get_sheet", "get_dinner", "_show_welcome", "_switch_hold")}
    return functions, varinit

# ------------------------------------------------------------------ compositor
def compose(varinit, W=128, H=32):
    img = [[(0, 0, 0)] * W for _ in range(H)]
    def draw(node, ox, oy):
        if getattr(node, "hidden", False): return
        gx, gy = ox + getattr(node, "x", 0), oy + getattr(node, "y", 0)
        if isinstance(node, TileGrid):
            b, p = node.bitmap, node.pixel_shader
            for by in range(b.height):
                for bx in range(b.width):
                    idx = b[bx, by]
                    if idx == 0 or (p is not None and idx in getattr(p, "_transparent", ())): continue
                    x, y = gx + bx, gy + by
                    if 0 <= x < W and 0 <= y < H: img[y][x] = p[idx] if p else (255, 255, 255)
        else:
            for c in node: draw(c, gx, gy)
    if varinit.display.root_group: draw(varinit.display.root_group, 0, 0)
    return img

def _nonblack(img, y0, y1):
    return sum(1 for y in range(y0, y1) for px in img[y] if px != (0, 0, 0))

def _has_color(img, rgb, y0, y1):
    return any(img[y][x] == rgb for y in range(y0, y1) for x in range(len(img[y])))

def _canned_departures(num="1", **k):
    return [["0", "118", "Vallingby", "4", "1"], ["0", "118", "Hallonbergen", "10", "2"],
            ["0", "118", "Vallingby", "17", "1"], ["0", "19", "Hasselby", "25", "1"]]

def _setup_stations(varinit):
    s = varinit.settings["stations"]
    s["1"].update(mystation="Tabylundsvagen", siteid="3875", operator="sl")
    s["2"].update(mystation="Koppargarden",   siteid="3880", operator="sl")
    varinit.active_station = "1"

# ------------------------------------------------------------------ tests
RESULTS = []
def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)

def test_dinner_time_gate(fn, vi):
    # (day, HH:MM, expected in-window?)  window is 13:00 < t < 19:00, EVERY day
    vi.settings["dinner_start"] = "13:00"; vi.settings["dinner_end"] = "19:00"
    table = [("Tue", "12:59", False), ("Tue", "13:00", False), ("Tue", "13:01", True),
             ("Tue", "16:30", True),  ("Tue", "18:59", True),  ("Tue", "19:00", False),
             ("Tue", "19:30", False), ("Tue", "09:00", False),
             ("Sat", "16:00", True),  ("Sun", "16:00", True),   # weekends included now
             ("Sat", "20:00", False)]
    ok = True
    for day, t, exp in table:
        vi.today = day; vi._currenttime = t
        got = fn.dinner_time_ok()
        if got != exp:
            ok = False; print(f"   gate mismatch: {day} {t} expected {exp} got {got}")
    check("dinner time-gate table (13:00-19:00, every day incl. weekends)", ok)

    # the window is configurable via settings (and empty values fall back to the default)
    vi.settings["dinner_start"] = "13:00"; vi.settings["dinner_end"] = "23:00"
    vi.today = "Tue"; vi._currenttime = "20:08"
    check("dinner gate: widened end time includes 20:08", fn.dinner_time_ok())
    vi.settings["dinner_start"] = ""; vi.settings["dinner_end"] = ""
    check("dinner gate: blank settings fall back to 13:00-19:00", not fn.dinner_time_ok())
    vi.settings["dinner_start"] = "13:00"; vi.settings["dinner_end"] = "19:00"

def test_rotation(fn, vi):
    _setup_stations(vi)
    check("configured_stations = ['1','2']", fn.configured_stations() == ["1", "2"])
    vi.active_station = "1"; a = fn.next_station()
    vi.active_station = a;   b = fn.next_station()
    check("rotation alternates 1<->2", a == "2" and b == "1")

def test_departures_top_line(fn, vi):
    _setup_stations(vi); fn.get_departure = _canned_departures
    vi.currentfont = 0
    vi.scrollsum = fn.renderstring(fn.reformat_data(fn.get_departure(num="1")), large=True)
    vi.tg2.x = vi.if_long
    img = compose(vi)
    check("departures: top line shows the next departure (non-empty)", _nonblack(img, 0, 15) > 20)

def test_dinner_screen(fn, vi):
    _setup_stations(vi)
    vi.today = "Tue"; vi._currenttime = "16:30"
    vi.settings["dinner_url"] = ""                     # url gate makes get_sheet a no-op
    vi.dinner_meal = "Smashed burger tortilla"; vi.dinner_day = vi.today; vi.sheet_msg = ""
    grab = {}
    fn._switch_hold = lambda sec, flash=False: grab.setdefault("img", compose(vi))
    vi.active_station = "1"
    fn.rotate_station()
    img = grab.get("img")
    check("dinner screen renders", img is not None)
    if img:
        check("dinner: station name on top line (non-empty)", _nonblack(img, 0, 15) > 20)
        check("dinner: meal on row 2 in cyan (palette 8)", _has_color(img, (80, 210, 255), 16, 32))

def _wx_json(ctemp, ccode, gust, day_high, temps24, codes24, hour=0):
    import json
    htimes = ["2026-07-16T%02d:00" % i for i in range(len(temps24))]
    return types.SimpleNamespace(
        text=json.dumps({
            "current": {"time": "2026-07-16T%02d:00" % hour,
                        "temperature_2m": ctemp, "weather_code": ccode, "wind_gusts_10m": gust},
            "hourly": {"time": htimes, "weather_code": codes24, "temperature_2m": temps24},
            "daily": {"temperature_2m_max": [day_high]}}),
        close=lambda: None)

def test_weather_parse(fn, vi):
    vi.settings["weather"] = 1
    def run(hour, ctemp, ccode, gust, day_high, temps24, codes24):
        vi._currenttime = "%02d:00" % hour
        fn.requests = types.SimpleNamespace(get=lambda *a, **k: _wx_json(ctemp, ccode, gust, day_high, temps24, codes24, hour))
        vi.wx_code = None; vi.wx_timer = 0
        code, temp, warn = fn.get_weather()
        return code, temp, warn, vi.wx_peak

    # upcoming condition: cloudy now, rain in the next couple hours -> rain code chosen
    codes = [3] * 24; codes[11] = 61; codes[12] = 61
    code, temp, _, _ = run(10, 12.3, 3, 5.0, 15, [12] * 24, codes)
    check("weather parse: upcoming condition picks rain (61) over cloud (3)", code == 61)
    check("weather parse: current temp rounded", temp == "12")

    # temp profile that rises to 24 at 14:00 then falls
    temps = [10 + (i if i <= 14 else 28 - i) for i in range(24)]   # peak 24 at hour 14
    _, _, _, peak_am = run(8, temps[8], 3, 4.0, 24, temps, [3] * 24)
    check("weather parse: morning -> day high (24) shown as peak", peak_am == 24)
    _, _, _, peak_pm = run(20, temps[20], 3, 4.0, 24, temps, [3] * 24)
    check("weather parse: after the peak has passed -> no peak shown", peak_pm is None)

    # warnings (independent of the hourly indexing)
    _, _, warn_s, _ = run(12, 9.0, 3, 22.0, 12, [9] * 24, [3] * 24)
    check("weather parse: gust >= 21 -> STORM", warn_s == "STORM")
    _, _, warn_b, _ = run(12, 11.0, 3, 16.0, 12, [11] * 24, [3] * 24)
    check("weather parse: gust 14-21 -> BLÅST", warn_b == "BL\xc5ST")
    for t, exp in [(28, "VARMT AF"), (27, ""), (-10, "KYLA"), (-9, "")]:
        _, _, w, _ = run(12, float(t), 3, 4.0, t, [t] * 24, [3] * 24)
        check("weather threshold: %d°C -> %r" % (t, exp), w == exp)

    # HETT/KYLA should fire on the upcoming day peak, not just the current reading
    hot = [22] * 24; hot[13] = 30; hot[14] = 31; hot[15] = 30
    _, _, w_hot, _ = run(8, 22.0, 3, 4.0, 31, hot, [3] * 24)
    check("weather threshold: cool now (22) but peak 31 ahead -> VARMT AF", w_hot == "VARMT AF")
    cool = [31 if i <= 13 else 18 for i in range(24)]   # hot earlier, cooled off by evening
    _, _, w_eve, _ = run(20, 18.0, 3, 4.0, 31, cool, [3] * 24)
    check("weather threshold: peak already passed by evening -> no HETT", w_eve == "")
    cold = [2] * 24; cold[3] = -11; cold[4] = -12
    _, _, w_cold, _ = run(1, 2.0, 3, 4.0, 5, cold, [3] * 24)
    check("weather threshold: mild now (2) but -12 ahead -> KYLA", w_cold == "KYLA")

def test_weather_timezone(fn, vi):
    # The device clock (_currenttime) is UTC from the HTTP header; open-meteo timestamps are
    # local. In the evening that skew used to drag the afternoon peak back into the "upcoming"
    # window and trip a false HETT. Indexing by the API's own time must prevent that.
    vi.settings["weather"] = 1
    t = [18, 17, 17, 18, 19, 20, 22, 24, 26, 28, 29, 30, 31, 31, 31, 31, 31, 30, 30, 29, 28, 26, 24, 22]
    vi._currenttime = "19:00"                        # stale/UTC device hour (2h behind local)
    fn.requests = types.SimpleNamespace(get=lambda *a, **k: _wx_json(26, 3, 4.0, 31, t, [3] * 24, 21))
    vi.wx_code = None; vi.wx_timer = 0
    _, temp, warn = fn.get_weather()
    check("weather tz: evening (local 21:00) -> no false HETT", warn == "")
    check("weather tz: peak hidden once passed in the evening", vi.wx_peak is None)
    check("weather tz: current temp still correct", temp == "26")

def test_weather_switch_screen(fn, vi):
    _setup_stations(vi)
    vi.today = "Tue"; vi._currenttime = "20:00"          # OUTSIDE dinner window -> weather path
    vi.settings["dinner_url"] = ""; vi.sheet_msg = ""    # url gate -> get_sheet no-op, no message
    fn.get_weather = lambda *a, **k:(61, "12", "")              # rain, no warning
    grab = {}
    fn._switch_hold = lambda sec, flash=False: grab.setdefault("img", compose(vi))
    vi.active_station = "1"
    fn.rotate_station()
    img = grab.get("img")
    check("weather screen renders (switch screen shown outside dinner window)", img is not None)
    if img:
        check("weather: station name on top line", _nonblack(img, 0, 15) > 20)
        check("weather: rain/temp on row 2 (weather blue 120,200,255)", _has_color(img, (120, 200, 255), 16, 32))
        check("weather: no warning red when calm", not _has_color(img, (255, 40, 20), 16, 32))

def test_weather_warning_screen(fn, vi):
    _setup_stations(vi)
    vi.today = "Tue"; vi._currenttime = "20:00"
    vi.settings["dinner_url"] = ""; vi.sheet_msg = ""
    fn.get_weather = lambda *a, **k:(82, "18", "SKYFALL")       # heavy rain warning
    grab = {}
    fn._switch_hold = lambda sec, flash=False: grab.setdefault("img", compose(vi))
    vi.active_station = "1"
    fn.rotate_station()
    img = grab.get("img")
    check("weather warning renders", img is not None)
    if img:
        check("warning: red label present to the right (255,40,20)", _has_color(img, (255, 40, 20), 16, 32))
        check("weather: not the dinner cyan (80,210,255)", not _has_color(img, (80, 210, 255), 16, 32))

# ------------------------------------------------------------------ optional render dump
def test_welcome(fn, vi):
    import time as _t
    _setup_stations(vi)
    vi.today = "Tue"; vi._currenttime = "20:00"
    fn.get_weather = lambda *a, **k:(61, "12", "")          # weather path; keeps rotate_station happy
    vi.settings["dinner_url"] = ""; vi.sheet_msg = ""   # url gate -> get_sheet no-op; use welcome_msg
    fn._switch_hold = lambda sec, flash=False: None
    _sleep = fn.time.sleep; fn.time.sleep = lambda *a: None   # don't actually wait out the scroll

    # 1) the rainbow greeting renders with rainbow colours
    frames = []
    _refresh = fn.refresh
    fn.refresh = lambda *a, **k: frames.append(compose(vi))
    fn._show_welcome("Hej")
    fn.refresh = _refresh
    best = max(frames, key=lambda im: _nonblack(im, 0, 32)) if frames else None
    check("custom: message renders (non-black pixels present)", best is not None and _nonblack(best, 0, 32) > 15)
    if best:
        check("custom: green banner background present", _has_color(best, (15, 150, 25), 0, 32))
        check("custom: white message text present", _has_color(best, (240, 240, 240), 0, 32))

    # 2) cadence: with welcome_every=2, the greeting shows on every 2nd switch only
    calls = {"n": 0}
    _show = fn._show_welcome
    fn._show_welcome = lambda msg: calls.__setitem__("n", calls["n"] + 1)
    vi.sheet_msg = "Hej"; vi.settings["welcome_every"] = 2; vi.welcome_count = 0
    vi.active_station = "1"; fn.rotate_station()
    check("welcome: not shown on 1st switch", calls["n"] == 0)
    vi.active_station = "1"; fn.rotate_station()
    check("welcome: shown on 2nd switch", calls["n"] == 1)

    # 3) blank message = off
    fn._show_welcome = lambda msg: calls.__setitem__("n", calls["n"] + 1)
    vi.sheet_msg = ""; vi.welcome_count = 0
    vi.active_station = "1"; fn.rotate_station(); vi.active_station = "1"; fn.rotate_station()
    check("welcome: blank message never shows", calls["n"] == 1)

    fn._show_welcome = _show; fn.time.sleep = _sleep
    vi.sheet_msg = ""

def test_no_dinner_fallback(fn, vi):
    _setup_stations(vi)
    fn.get_weather = lambda *a, **k:(61, "12", "")
    AMBER, CYAN = (255, 170, 30), (80, 210, 255)
    def run(day, t, url, csv=None, fail=False, known_day=None):
        # drives the real fetch path: csv is what the published sheet returns
        vi.today = day; vi._currenttime = t
        vi.settings["dinner_url"] = url; vi.sheet_msg = ""
        vi.dinner_meal = ""; vi.dinner_day = known_day if known_day is not None else day
        if fail:
            def _boom(*a, **k): raise OSError("network down")
            fn.requests = types.SimpleNamespace(get=_boom)
        else:
            fn.requests = types.SimpleNamespace(
                get=lambda *a, **k: types.SimpleNamespace(text=(csv or ""), close=lambda: None))
        vi.dinner_fetch_timer = 0
        grab = {}
        fn._switch_hold = lambda sec, flash=False: grab.setdefault("img", compose(vi))
        vi.active_station = "1"; fn.rotate_station()
        return grab.get("img")

    img = run("Wed", "16:30", "")                       # feature not configured -> no nag
    check("no-dinner: nothing shown when no sheet URL is set", img is not None and not _has_color(img, AMBER, 16, 32))

    img = run("Wed", "16:30", "http://x", csv="")       # sheet fetched, cells empty -> fallback
    check("no-dinner: amber fallback shown when today has no meal", img is not None and _has_color(img, AMBER, 16, 32))
    check("no-dinner: fallback is not the meal cyan", img is not None and not _has_color(img, CYAN, 16, 32))

    img = run("Wed", "16:30", "http://x", fail=True, known_day="Tue")   # today's answer unknown
    check("no-dinner: no fallback while today's answer is unknown", img is not None and not _has_color(img, AMBER, 16, 32))

    img = run("Wed", "20:00", "http://x", csv="")       # outside the dinner window
    check("no-dinner: no fallback outside the dinner window", img is not None and not _has_color(img, AMBER, 16, 32))

    img = run("Wed", "16:30", "http://x", csv="Tacos\n")   # a real meal still wins
    check("no-dinner: a real meal still shows in cyan", img is not None and _has_color(img, CYAN, 16, 32))
    vi.dinner_meal = ""; vi.dinner_day = ""; vi.settings["dinner_url"] = ""

def test_fetch_budget(fn, vi):
    # Every switch already pays for a blocking departures fetch, so at most ONE of
    # {sheet, weather} may fetch per switch; the loser retries on the next switch.
    _setup_stations(vi)
    fn.get_weather = fn._orig["get_weather"]           # undo earlier stubs: we need real fetches
    fn.get_sheet = fn._orig["get_sheet"]
    vi.today = "Tue"; vi._currenttime = "20:00"        # outside dinner window -> weather path
    vi.settings["dinner_url"] = "http://x"; vi.settings["weather"] = 1
    vi.dinner_fetch_timer = 0; vi.wx_timer = 0        # both due
    vi.dinner_meal = ""; vi.sheet_msg = ""
    fn._switch_hold = lambda sec, flash=False: None
    calls = []
    def _get(url, *a, **k):
        calls.append("wx" if "open-meteo" in str(url) else "sheet")
        if "open-meteo" in str(url):
            return _wx_json(12, 3, 4.0, 15, [12] * 24, [3] * 24, 20)
        return types.SimpleNamespace(text="Tacos\nHej", close=lambda: None)
    fn.requests = types.SimpleNamespace(get=_get)

    vi.active_station = "1"; fn.rotate_station()
    check("budget: only one background fetch on a switch", len(calls) == 1)
    first = calls[0] if calls else None

    vi.active_station = "1"; fn.rotate_station()       # next switch: the loser gets its turn
    check("budget: the skipped fetch happens on the next switch",
          len(calls) == 2 and calls[1] != first)

    # a skipped fetch must not lose its cached value or burn its poll timer
    vi.dinner_meal = "Pannkakor"; vi.dinner_fetch_timer = 0
    did = fn.get_sheet(allow_fetch=False)
    check("budget: skipped sheet reports no fetch", did is False)
    check("budget: skipped sheet keeps its cached meal", vi.dinner_meal == "Pannkakor")
    check("budget: skipped sheet did not burn its poll timer", vi.dinner_fetch_timer == 0)
    vi.settings["dinner_url"] = ""; vi.dinner_meal = ""; vi.dinner_day = ""

def test_sheet_message(fn, vi):
    # One CSV, two rows: row1 meal -> dinner_meal, row2 message -> sheet_msg (positional)
    vi.settings["dinner_url"] = "http://x/menu.csv"
    def feed(csv):
        fn.requests = types.SimpleNamespace(get=lambda *a, **k: types.SimpleNamespace(text=csv, close=lambda: None))
        vi.dinner_fetch_timer = 0; vi.dinner_meal = ""; vi.sheet_msg = ""
        fn.get_sheet()

    feed("Smashed burger tortilla\nHeja VSK!")
    check("sheet: row1 -> meal", vi.dinner_meal == "Smashed burger tortilla")
    check("sheet: row2 -> message", vi.sheet_msg == "Heja VSK!")

    feed("\nHeja VSK!")                       # empty meal, message still present (positional)
    check("sheet: empty meal keeps message on row2", vi.dinner_meal == "" and vi.sheet_msg == "Heja VSK!")

    feed("Pannkakor")                          # only a meal, no message row
    check("sheet: no row2 -> message blank", vi.dinner_meal == "Pannkakor" and vi.sheet_msg == "")

    feed('"Fisk, potatis"\n"Heja ""VSK"""')    # quoted cells with commas / escaped quotes
    check("sheet: quoted meal unwrapped", vi.dinner_meal == "Fisk, potatis")
    check("sheet: quoted message unwrapped", vi.sheet_msg == 'Heja "VSK"')

    # A successful fetch with nothing planned must CLEAR the meal, not keep yesterday's.
    vi.today = "Wed"
    feed("Kottbullar\n")
    check("sheet: meal cached with today's stamp", vi.dinner_meal == "Kottbullar" and vi.dinner_day == "Wed")
    fn.requests = types.SimpleNamespace(get=lambda *a, **k: types.SimpleNamespace(text="", close=lambda: None))
    vi.dinner_fetch_timer = 0; fn.get_sheet()      # next day, empty sheet
    check("sheet: empty body clears the meal (no stale carry-over)", vi.dinner_meal == "")

    # a FAILED fetch keeps the last good value (that's what the cache is for)
    vi.dinner_meal = "Pyttipanna"; vi.dinner_day = "Wed"
    def _boom(*a, **k): raise OSError("network down")
    fn.requests = types.SimpleNamespace(get=_boom)
    vi.dinner_fetch_timer = 0; fn.get_sheet()
    check("sheet: failed fetch keeps the cached meal", vi.dinner_meal == "Pyttipanna")

    # ...but a meal fetched on a previous day is never rendered
    _setup_stations(vi)
    vi.settings["dinner_url"] = ""                 # url gate -> get_sheet no-op
    vi._currenttime = "16:30"                      # inside the dinner window
    fn.get_weather = lambda *a, **k:(61, "12", "")
    vi.dinner_meal = "Gamla pannkakor"; vi.dinner_day = "Tue"; vi.today = "Wed"
    grab = {}
    fn._switch_hold = lambda sec, flash=False: grab.setdefault("img", compose(vi))
    vi.active_station = "1"; fn.rotate_station()
    img = grab.get("img")
    check("sheet: stale meal from another day is not shown (weather instead)",
          img is not None and not _has_color(img, (80, 210, 255), 16, 32))
    vi.dinner_meal = ""; vi.dinner_day = ""

    # the sheet message is the sole source of the greeting
    _setup_stations(vi)
    vi.today = "Tue"; vi._currenttime = "20:00"
    fn.get_weather = lambda *a, **k:(61, "12", "")
    fn._switch_hold = lambda sec, flash=False: None
    vi.settings["dinner_url"] = ""             # url gate -> get_sheet no-op; use staged sheet_msg
    calls = {"msg": None, "n": 0}
    _show = fn._show_welcome
    fn._show_welcome = lambda msg: (calls.__setitem__("msg", msg), calls.__setitem__("n", calls["n"] + 1))
    vi.settings["welcome_every"] = 1
    vi.sheet_msg = "Heja VSK!"; vi.welcome_count = 0
    vi.active_station = "1"; fn.rotate_station()
    check("sheet: row-2 message shown as the greeting", calls["msg"] == "Heja VSK!" and calls["n"] == 1)
    vi.sheet_msg = ""; vi.welcome_count = 0
    vi.active_station = "1"; fn.rotate_station()
    check("sheet: blank message shows nothing", calls["n"] == 1)
    fn._show_welcome = _show
    vi.settings["dinner_url"] = ""; vi.sheet_msg = ""

def render_all(fn, vi):
    try:
        from PIL import Image
    except ImportError:
        print("(PIL not installed; skipping --render)"); return
    os.makedirs(OUT, exist_ok=True)
    def save(img, name, scale=10):
        im = Image.new("RGB", (128, 32))
        for y in range(32):
            for x in range(128): im.putpixel((x, y), img[y][x])
        im.resize((128 * scale, 32 * scale), Image.NEAREST).save(os.path.join(OUT, name))
        print("wrote", os.path.join(OUT, name))
    _setup_stations(vi); fn.get_departure = _canned_departures
    vi.currentfont = 0
    vi.scrollsum = fn.renderstring(fn.reformat_data(fn.get_departure(num="1")), large=True)
    vi.tg2.x = vi.if_long; save(compose(vi), "departures.png")
    vi.tg2.x = -60;        save(compose(vi), "departures_mid.png")
    vi.today = "Tue"; vi._currenttime = "16:30"; vi.settings["dinner_url"] = ""
    vi.dinner_meal = "Smashed burger tortilla"; vi.dinner_day = "Tue"; vi.sheet_msg = ""
    grab = {}; fn._switch_hold = lambda sec, flash=False: grab.setdefault("img", compose(vi))
    vi.active_station = "1"; fn.rotate_station()
    if grab.get("img"): save(grab["img"], "dinner.png")
    # "nothing planned" fallback (inside the window, sheet fetched but empty)
    vi.today = "Tue"; vi._currenttime = "16:30"
    vi.dinner_meal = ""; vi.dinner_day = "Tue"; vi.settings["dinner_url"] = "http://x"; vi.sheet_msg = ""
    fn.requests = types.SimpleNamespace(get=lambda *a, **k: types.SimpleNamespace(text="", close=lambda: None))
    vi.dinner_fetch_timer = 0
    grab = {}; fn._switch_hold = lambda sec, flash=False: grab.setdefault("img", compose(vi))
    vi.active_station = "1"; fn.rotate_station()
    if grab.get("img"): save(grab["img"], "no_dinner.png")
    # weather switch screen (outside dinner window)
    vi.today = "Tue"; vi._currenttime = "20:00"
    vi.dinner_meal = ""; vi.dinner_day = ""; vi.settings["dinner_url"] = ""; vi.sheet_msg = ""
    fn.get_weather = lambda *a, **k:(61, "12", "")
    grab = {}; fn._switch_hold = lambda sec, flash=False: grab.setdefault("img", compose(vi))
    vi.active_station = "1"; fn.rotate_station()
    if grab.get("img"): save(grab["img"], "weather.png")
    # full-screen rainbow welcome (grab the frame with the most lit pixels)
    _sleep = fn.time.sleep; fn.time.sleep = lambda *a: None
    frames = []; _refresh = fn.refresh
    fn.refresh = lambda *a, **k: frames.append(compose(vi))
    fn._show_welcome("Välkommen Familjen Larsson")
    fn.refresh = _refresh; fn.time.sleep = _sleep
    if frames: save(max(frames, key=lambda im: _nonblack(im, 0, 32)), "welcome.png")

# ------------------------------------------------------------------ main
def main():
    fn, vi = boot()
    vi.settings["brightness"] = 4     # factor 5 -> _bri() scales colours 1:1 with the base values
    test_dinner_time_gate(fn, vi)
    test_rotation(fn, vi)
    test_departures_top_line(fn, vi)
    test_dinner_screen(fn, vi)
    test_weather_parse(fn, vi)
    test_weather_timezone(fn, vi)
    test_weather_switch_screen(fn, vi)
    test_weather_warning_screen(fn, vi)
    test_welcome(fn, vi)
    test_no_dinner_fallback(fn, vi)
    test_fetch_budget(fn, vi)
    test_sheet_message(fn, vi)
    if "--render" in sys.argv:
        render_all(fn, vi)
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
