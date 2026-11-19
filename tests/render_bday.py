import sys, os, time
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness
from PIL import Image

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)
fn, vi = harness.boot()
vi.settings["brightness"] = 4
vi.currentfont = 0

R = []
def check(n, c): R.append(c); print(("PASS " if c else "FAIL ") + n)

# parsing
check("BDAY:Grattis Anna! -> text", fn.birthday_text("BDAY:Grattis Anna!") == "Grattis Anna!")
check("case-insensitive + trims", fn.birthday_text("  bday:   Grattis Anna!  ") == "Grattis Anna!")
check("bare BDAY: -> None", fn.birthday_text("BDAY:   ") is None)
check("normal message -> None", fn.birthday_text("Heja VSK!") is None)

def to_img(img, scale=8):
    im = Image.new("RGB", (128, 32))
    for y in range(32):
        for x in range(128): im.putpixel((x, y), img[y][x])
    return im.resize((128 * scale, 32 * scale), Image.NEAREST)

def capture(msg, name, every=1, maxframes=400):
    frames = []; n = [0]
    def grab(*a, **k):
        n[0] += 1
        if n[0] % every == 0 and len(frames) < maxframes: frames.append(to_img(harness.compose(vi)))
    fn.refresh = grab
    fn.time.sleep = lambda s: None if False else _sleep(s)
    t0 = time.monotonic()
    fn._show_birthday(msg)
    fn.refresh = lambda *a, **k: None
    frames[0].save(os.path.join(OUT, name + ".png"))
    frames[0].save(os.path.join(OUT, name + ".gif"), save_all=True, append_images=frames[1:],
                   duration=60, loop=0)
    print(f"{name}: {len(frames)} frames, {time.monotonic()-t0:.1f}s")
    return frames

_real_sleep = time.sleep
def _sleep(s): _real_sleep(s)

vi.settings["bday_hold"] = 3
f1 = capture("Grattis Anna!", "bday_static", every=2)
check("static: band restored to normal row after", vi.tg2.y == 16)
f2 = capture("Grattis på födelsedagen Anna!", "bday_scroll", every=4)

# routing through rotate_station's call site
calls = []
fn._show_birthday = lambda m: calls.append(("bday", m))
fn._show_welcome = lambda m: calls.append(("welcome", m))
fn.get_sheet = lambda *a, **k: False
fn.get_weather = lambda *a, **k: (61, "12", "")
fn.prefetch_departures = lambda n: False
fn._switch_hold = lambda *a, **k: None
harness._setup_stations(vi)
vi.settings["welcome_every"] = 1; vi.settings["listmode"] = 0
for msg, want in [("BDAY:Grattis Anna!", ("bday", "Grattis Anna!")),
                  ("Heja VSK!", ("welcome", "Heja VSK!")),
                  ("BDAY:", None)]:
    calls.clear(); vi.sheet_msg = msg; vi.active_station = "1"; fn.rotate_station()
    check(f"route {msg!r} -> {want}", (calls[0] if calls else None) == want)

print(f"\n{sum(R)}/{len(R)} passed")
