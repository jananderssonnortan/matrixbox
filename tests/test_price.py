"""Targeted checks for the electricity price on the switch screen (real code, stubbed network)."""
import sys, io, time, contextlib
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)
R = []
def check(n, c): R.append(bool(c)); print(("PASS " if c else "FAIL ") + n)

fn, vi = harness.boot()
vi.settings["brightness"] = 4; vi.currentfont = 0; vi.settings["listmode"] = 0

# synthetic elprisetjustnu response: today's real SE3 hourly averages, 4 quarters each
hourly = [1.408,1.411,1.429,1.457,1.531,1.723,2.129,2.417,2.873,2.765,2.837,2.725,
          2.584,2.601,2.617,2.641,2.527,2.478,2.482,2.291,1.915,1.744,1.574,1.415]
def api_json(day="2026-11-19"):
    rows = []
    for h in range(24):
        for q in range(4):
            m = q * 15
            rows.append('{"SEK_per_kWh":%.5f,"EUR_per_kWh":0.1,"EXR":11.1,"time_start":"%sT%02d:%02d:00+01:00","time_end":"x"}'
                        % (hourly[h], day, h, m))
    return "[" + ",".join(rows) + "]"

urls = []
class Resp:
    def __init__(s, t): s.text = t
    def close(s): pass
def fake_get(url, timeout=None):
    urls.append(url); return Resp(api_json())
fn.requests.get = fake_get

def set_clock(s):            # pretend weather just told us local time s
    vi.wx_local = s; vi.wx_local_mono = time.monotonic()

# ---- parsing + local clock
pts = fn._parse_el(api_json())
check("parse: 96 points", len(pts) == 96)
check("parse: first 00:00 1.408", pts[0] == (0, 1.408))
check("parse: 08:45 = 2.873", (525, 2.873) in pts)
vi.wx_local = ""; check("no weather yet -> no clock", fn.local_now() is None)
set_clock("2026-11-19T23:50"); vi.wx_local_mono -= 20 * 60
check("clock rolls over midnight", fn.local_now() == ("2026-11-20", 10))
set_clock("2026-11-19T08:30"); vi.wx_local_mono -= 13 * 3600
check("clock > 12 h stale -> None", fn.local_now() is None)

# ---- fetch
set_clock("2026-11-19T14:05"); vi.el_day = ""; vi.el_timer = 0; urls.clear()
check("fetch blocked when budget used", fn.get_price(allow_fetch=False) is False and not urls)
check("fetch attempted", fn.get_price() is True)
check("URL", urls == ["https://www.elprisetjustnu.se/api/v1/prices/2026/11-19_SE3.json"])
check("cached for the day: no second fetch", fn.get_price() is False and len(urls) == 1)
check("now price 14:05 = 2.617", abs(fn.el_now() - 2.617) < 1e-9)
check("levels: green<=1.744 red>=2.617", abs(vi.el_lo - 1.744) < 1e-9 and abs(vi.el_hi - 2.617) < 1e-9)
check("14:05 is red", fn._el_level(fn.el_now()) == fn._EL_RED)
set_clock("2026-11-20T00:10")
check("new day without data -> hidden", fn.el_now() is None)
check("new day -> refetch", fn.get_price() is True and len(urls) == 2)
set_clock("2026-11-19T14:05"); vi.el_day = "2026-11-19"

def boom(url, timeout=None): raise OSError("net down")
fn.requests.get = boom; vi.el_day = ""; vi.el_timer = 0
with contextlib.redirect_stdout(io.StringIO()): fn.get_price()
check("failed fetch: no data, no crash", vi.el_day == "" and fn.el_now() is None)
check("failed fetch: 10 min backoff", fn.get_price() is False)
fn.requests.get = fake_get; vi.el_timer = 0; fn.get_price()

# ---- full switch screen through rotate_station
fn.prefetch_departures = lambda n: False
fn._switch_hold = lambda *a, **k: None
fn.get_sheet = lambda *a, **k: False
fn._show_welcome = fn._show_birthday = lambda *a, **k: None
harness._setup_stations(vi)
shots = []
def shot(label, clock, meal=None, wx=(3, "7", ""), peak=9):
    set_clock(clock)
    vi.dinner_meal = meal or ""; vi.dinner_day = vi.today if meal else ""
    fn.dinner_time_ok = (lambda: True) if meal else (lambda: False)
    fn.get_weather = lambda *a, **k: wx; vi.wx_peak = peak
    grab = {}
    def cap(*a, **k):
        if "img" not in grab: grab["img"] = harness.compose(vi)
    fn.refresh = cap
    vi.palette[3] = (1, 2, 3); vi.palette[5] = (4, 5, 6)
    vi.active_station = "1"
    with contextlib.redirect_stdout(io.StringIO()): fn.rotate_station()
    fn.refresh = lambda *a, **k: None
    shots.append((grab["img"], label))
    return grab["img"]

def has(img, rgb):
    return any(img[y][x] == rgb for y in range(16, 32) for x in range(64, 128))
G, A, Rr = fn._bri((40, 220, 60)), fn._bri((255, 170, 0)), fn._bri((200, 30, 30))
check("05:00 green shown", has(shot("05:00  El 1,72 kr  green", "2026-11-19T05:00"), G))
check("palette 3/5 restored after switch", vi.palette[3] == (1, 2, 3) and vi.palette[5] == (4, 5, 6))
check("20:00 amber shown", has(shot("20:00  El 1,92 kr  amber", "2026-11-19T20:00"), A))
check("14:00 red beside short meal", has(shot("14:00  Tacos + El 2,62 kr  red", "2026-11-19T14:05", meal="Tacos"), Rr))
check("storm warning: price hidden", not has(shot("20:00  storm: price hidden", "2026-11-19T20:00", wx=(95, "18", "STORM"), peak=22), A))
check("long meal: price hidden", not has(shot("16:00  long meal: price hidden", "2026-11-19T16:00", meal="Kycklinggryta med ris"), Rr))

scale = 8; W, H = 128 * scale, 32 * scale
out = Image.new("RGB", (W, (H + 40) * len(shots)), (40, 40, 40)); d = ImageDraw.Draw(out)
for k, (img, lab) in enumerate(shots):
    im = Image.new("RGB", (128, 32))
    for y in range(32):
        for x in range(128): im.putpixel((x, y), img[y][x])
    out.paste(im.resize((W, H), Image.NEAREST), (0, k * (H + 40) + 36)); d.text((8, k * (H + 40) + 8), lab, fill=(220, 220, 220))
out.save(OUT + "/price_real.png")
print(f"\n{sum(R)}/{len(R)} passed")
