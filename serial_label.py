"""Serial label (2026-10-15): prints a product's serial label on a Zebra
printer - a line of text and a barcode of the serial, in the design of the
item's own serial sticker (LAYOUTS below: the Bose QC 35 earcup sticker
"S/N:<serial>" over Code 128, the Sonos Play:1 base sticker's Code 39).

The whole label is drawn here as a 1-bit picture at the printer's own dot size
and sent as one ZPL graphic (^GFA). So the preview app.py shows is
exactly what the printer prints, and every bar lands on whole printer dots, the
same as the printer's own ^BC barcode would.

Printing goes to a Windows printer (the ZDesigner driver passes raw ZPL
through) or to a network Zebra on port 9100. Settings live in
data/serial_label_settings.json, every print is logged to
data/serial_label_log.jsonl.

CLI (no printing):  venv\\Scripts\\python.exe serial_label.py 077061Z8240B195AE --png label.png --zpl label.zpl
"""

import json
import os
import re
import socket
import sys
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, "data", "serial_label_settings.json")
PRINTERS = os.path.join(HERE, "data", "serial_label_printers.json")
LOG = os.path.join(HERE, "data", "serial_label_log.jsonl")

DEFAULTS = {
    "send": "windows",     # "windows" (printer below) or "network" (host:port)
    "printer": "",         # Windows printer name; "" = the first Zebra/ZDesigner found
    "host": "",
    "port": 9100,
    "model": "",           # Zebra model from ZEBRA_MODELS; only limits the dpi choice
    "dpi": 300,
    "width_mm": 44.0,      # label size as it comes out of the printer; 44 x 7 mm at
    "height_mm": 7.0,      # 300 dpi is the Bose sticker with its own bar size
    "rotate": 0,           # 90/180/270 when the label is fed the other way round
    "layout": "Bose QC 35",  # the item's label design, from LAYOUTS
    "bar_dots": 0,         # narrowest bar in printer dots; 0 = the item's own
    "text_mm": 0.0,        # letter height; 0 = auto
    "bars_mm": 0.0,        # bar height; 0 = auto
    "shift_x_mm": 0.0,     # moves everything right/down if the printer is off
    "shift_y_mm": 0.0,
    "darkness": 0,         # ^MD, added to the printer's own darkness (-30..30); 0 = leave it
    "speed": 0,            # ^PR print speed in inches/second; 0 = leave it; slower prints sharper
    "profile": "",         # the saved network Zebra (PRINTERS) in use; "" = none
}

# What each saved printer keeps for itself; the item (layout) is shared.
PRINTER_KEYS = ("host", "port", "model", "dpi", "width_mm", "height_mm", "rotate", "bar_dots",
                "text_mm", "bars_mm", "shift_x_mm", "shift_y_mm", "darkness", "speed")

def _sonos_serial(serial):
    """Sonos: 12 hex characters (the MAC) and a check character, typed with or
    without - and : (B8-E9-37-5C-04-1A:7), optionally after the 4-digit date
    code (1402). The barcode holds the 13 characters; the text shows the date
    code and the serial in pairs."""
    s = serial.replace("-", "").replace(":", "")
    date, s = (s[:4], s[4:]) if len(s) == 17 and s[:4].isdigit() else ("", s)
    if len(s) != 13 or any(c not in "0123456789ABCDEF" for c in s[:12]) or not s[12].isalnum():
        raise ValueError("A Sonos serial is 12 hex characters and a check character, e.g. B8-E9-37-5C-04-1A-7, "
                         "optionally after the date code: 1402 B8-E9-37-5C-04-1A-7.")
    pairs = [s[i:i + 2] for i in range(0, 12, 2)] + [s[12]]
    return s, (date + "  " if date else "") + " – ".join(pairs)


# Item label designs: a line of text and a barcode of the serial, in proportions
# measured from the item's original sticker, in units of its barcode width.
# "parse" turns the typed serial into (barcode data, text); "bar_mm" is the
# narrowest bar (Code 39 wide bars are "ratio" times that, characters
# "char_gap" narrow bars apart); the text goes
# "above" or "below" the barcode, centred on it or starting at its left edge,
# in the first of "font" found, strokes widened by "stroke" of the letter
# height. "pattern" is what the item's serials look like (- and : left out), so
# a serial typed or scanned under the wrong item is put under its own item.
# The page shows "example" when no serial is typed, and for items with
# a "date_code" a box for the 4-digit date code (sent before the serial), filled
# with that code to start with - the code is printed on the sticker but not in
# its barcode, so a scan cannot give it.
#
# Bose QC 35 earcup sticker, measured from photos of the original next to prints
# (2026-10-14): "S/N:" and the serial in bold Arial-like letters printed heavy,
# centred over a Code 128 barcode and spread to run 1.08 of its width, a little
# past both ends; capitals 0.040 tall, 0.015 above bars 0.092 tall (2.3 times
# the letters); label 1.30 x 0.195; narrowest bar 0.13 mm, which is 1 dot at
# 203 dpi, as on the original.
#
# Sonos Play:1 base sticker, measured from an original next to a print of known
# size (2026-10-14): Code 39 of the 13-character serial only (read back from a
# photo: B8E9375C041A7), ~31.6 mm long - 1-dot narrow bars, 3-dot wide ones and
# characters 2 dots apart give 31.7 mm at 203 dpi; bars 0.118 tall; under them,
# 0.006 lower, "1402  B8 – E9 – ... – 7" in bold condensed letters 0.060 tall
# (Arial Narrow Bold narrowed to fit, ink 80), starting at the barcode's left
# edge and running its whole width.
LAYOUTS = {
    "Bose QC 35": {"parse": lambda serial: (serial, "S/N:" + serial), "symbology": "Code 128",
                   "bar_mm": 0.13, "text": "above", "align": "center",
                   "font": ("arialbd.ttf", "DejaVuSans-Bold.ttf"), "stroke": 0.11,
                   "cap": 0.040, "gap": 0.015, "bars": 0.092, "span": 1.08, "length": 1.30, "height": 0.195,
                   "example": "077061Z8240B195AE", "pattern": r"\d{6}Z[0-9A-Z]{10}"},
    "Sonos Play:1": {"parse": _sonos_serial, "symbology": "Code 39", "bar_mm": 0.13, "ratio": 3.0, "char_gap": 2,
                     "text": "below", "align": "left",
                     "font": ("arialnb.ttf", "DejaVuSansCondensed-Bold.ttf", "arialbd.ttf"), "stroke": 0,
                     "ink": 80, "cap": 0.060, "gap": 0.006, "bars": 0.118, "span": 1.0, "length": 1.10, "height": 0.25,
                     "example": "1402B8E9375C041A7", "date_code": "1402", "pattern": r"(\d{4})?[0-9A-F]{12}[0-9A-Z]"},
}
COMING_SOON = ()  # item names listed greyed out on the page until their design is added

# ZPL Zebra printers and the print resolutions each is made in. The page lists
# them as big (industrial) and small (desktop) printers; picking one limits the
# dpi choice. EPL-only models (plain LP/TLP 2844) cannot print ZPL, so only
# their -Z versions are here.
ZEBRA_MODELS = {
    "big": {
        "ZT111": [203, 300], "ZT211": [203, 300], "ZT220": [203, 300], "ZT230": [203, 300],
        "ZT231": [203, 300], "ZT410": [203, 300, 600], "ZT411": [203, 300, 600],
        "ZT420": [203, 300], "ZT421": [203, 300], "ZT510": [203, 300],
        "ZT610": [203, 300, 600], "ZT620": [203, 300], "105SL Plus": [203, 300],
        "110Xi4": [203, 300, 600], "140Xi4": [203], "170Xi4": [203, 300], "220Xi4": [203, 300],
        "ZM400": [203, 300, 600], "ZM600": [203, 300], "S4M": [203, 300],
    },
    "small": {
        "ZD220": [203], "ZD230": [203], "ZD410": [203, 300], "ZD411": [203, 300],
        "ZD420": [203, 300], "ZD421": [203, 300], "ZD500": [203, 300], "ZD510": [300],
        "ZD611": [203, 300], "ZD620": [203, 300], "ZD621": [203, 300], "ZD888": [203],
        "GK420": [203], "GX420": [203], "GX430t": [300], "GC420": [203], "GT800": [203, 300],
        "LP 2844-Z": [203], "TLP 2844-Z": [203], "TLP 3844-Z": [300],
    },
}

# Code 128 bar/space widths in modules for values 0-106 (103-105 = Start A/B/C,
# 106 = Stop). Each symbol starts with a bar.
PATTERNS = (
    "212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 "
    "221312 231212 112232 122132 122231 113222 123122 123221 223211 221132 "
    "221231 213212 223112 312131 311222 321122 321221 312212 322112 322211 "
    "212123 212321 232121 111323 131123 131321 112313 132113 132311 211313 "
    "231113 231311 112133 112331 132131 113123 113321 133121 313121 211331 "
    "231131 213113 213311 213131 311123 311321 331121 312113 312311 332111 "
    "314111 221411 431111 111224 111422 121124 121421 141122 141221 112214 "
    "112412 122114 122411 142112 142211 241211 221114 413111 241112 134111 "
    "111242 121142 121241 114212 124112 124211 411212 421112 421211 212141 "
    "214121 412121 111143 111341 131141 114113 114311 411113 411311 113141 "
    "114131 311141 411131 211412 211214 211232 2331112"
).split()
START_B, START_C, CODE_B, CODE_C, STOP = 104, 105, 100, 99, 106
QUIET = 10  # quiet zone each side, in narrow bars (Code 128 and Code 39 minimum)

# Code 39: each character is 5 bars and 4 spaces, 1 = wide; characters are
# separated by a narrow space and framed by "*".
CODE39 = dict(zip("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. *$/+%", (
    "000110100 100100001 001100001 101100000 000110001 100110000 001110000 000100101 100100100 001100100 "
    "100001001 001001001 101001000 000011001 100011000 001011000 000001101 100001100 001001100 000011100 "
    "100000011 001000011 101000010 000010011 100010010 001010010 000000111 100000110 001000110 000010110 "
    "110000001 011000001 111000000 010010001 110010000 011010000 010000101 110000100 011000100 010010100 "
    "010101000 010100010 010001010 000101010").split()))


def clean_serial(text):
    """Serials are printed upper case with no spaces; only printable ASCII fits Code 128 B."""
    serial = "".join((text or "").split()).upper()
    if not serial:
        raise ValueError("Type or scan a serial.")
    if len(serial) > 40:
        raise ValueError("Serial is longer than 40 characters.")
    bad = sorted({c for c in serial if not 33 <= ord(c) <= 126})
    if bad:
        raise ValueError(f"Serial has characters a barcode cannot hold: {''.join(bad)}")
    return serial


def guess_layout(serial):
    """The one item whose serials look like this one, or None."""
    s = re.sub(r"[\s:-]", "", (serial or "").upper())
    hits = [name for name, look in LAYOUTS.items() if re.fullmatch(look["pattern"], s)]
    return hits[0] if len(hits) == 1 else None


def code128_values(data):
    """Symbol values (start, data, check) using subsets B and C, fewest symbols.

    best[i][s] = symbols needed for data[i:] while in subset s (0 = B, 1 = C);
    a switch costs one symbol. Ties keep the current subset."""
    n = len(data)
    pair = [i + 1 < n and data[i].isdigit() and data[i + 1].isdigit() for i in range(n)]
    inf = float("inf")
    best = [[0, 0] for _ in range(n + 2)]
    move = [[0, 0] for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        stay_b, to_c = 1 + best[i + 1][0], (2 + best[i + 2][1]) if pair[i] else inf
        best[i][0], move[i][0] = (stay_b, 0) if stay_b <= to_c else (to_c, 1)
        stay_c, to_b = (1 + best[i + 2][1]) if pair[i] else inf, 2 + best[i + 1][0]
        best[i][1], move[i][1] = (stay_c, 1) if stay_c <= to_b else (to_b, 0)

    subset = 1 if pair[0] and best[0][1] < best[0][0] else 0
    values = [START_C if subset else START_B]
    i = 0
    while i < n:
        if move[i][subset] != subset:
            subset = move[i][subset]
            values.append(CODE_C if subset else CODE_B)
        if subset:
            values.append(int(data[i:i + 2]))
            i += 2
        else:
            values.append(ord(data[i]) - 32)
            i += 1
    values.append((values[0] + sum(k * v for k, v in enumerate(values[1:], 1))) % 103)
    return values


def code128_widths(data):
    """Alternating bar/space widths in modules, first one a bar, Stop included."""
    return [int(w) for v in code128_values(data) + [STOP] for w in PATTERNS[v]]


def barcode_dots(data, symbology, narrow, wide=0, char_gap=1):
    """Alternating bar/space widths in printer dots, first one a bar; Code 39
    characters are `char_gap` narrow bars apart."""
    if symbology != "Code 39":
        return [w * narrow for w in code128_widths(data)]
    bad = sorted({c for c in data if c not in CODE39 or c == "*"})
    if bad:
        raise ValueError(f"Serial has characters Code 39 cannot hold: {''.join(bad)}")
    dots = []
    for c in "*" + data + "*":
        dots += [wide if b == "1" else narrow for b in CODE39[c]] + [narrow * char_gap]
    return dots[:-1]


def normalize_settings(raw):
    s = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        if key not in (raw or {}):
            continue
        value = raw[key]
        try:
            s[key] = type(default)(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            s[key] = default
    s["send"] = s["send"] if s["send"] in ("windows", "network") else "windows"
    s["dpi"] = s["dpi"] if s["dpi"] in (203, 300, 600) else 203
    dpis = next((group[s["model"]] for group in ZEBRA_MODELS.values() if s["model"] in group), None)
    if dpis is None:
        s["model"] = ""
    elif s["dpi"] not in dpis:
        s["dpi"] = dpis[0]
    s["rotate"] = s["rotate"] if s["rotate"] in (0, 90, 180, 270) else 0
    s["width_mm"] = min(max(s["width_mm"], 10.0), 200.0)
    s["height_mm"] = min(max(s["height_mm"], 4.0), 300.0)
    s["bar_dots"] = min(max(s["bar_dots"], 0), 10)
    s["text_mm"] = min(max(s["text_mm"], 0.0), 20.0)
    s["bars_mm"] = min(max(s["bars_mm"], 0.0), 50.0)
    s["port"] = min(max(s["port"], 1), 65535)
    s["layout"] = s["layout"] if s["layout"] in LAYOUTS else DEFAULTS["layout"]
    s["shift_x_mm"] = min(max(s["shift_x_mm"], -20.0), 20.0)
    s["shift_y_mm"] = min(max(s["shift_y_mm"], -20.0), 20.0)
    s["darkness"] = min(max(s["darkness"], -30), 30)
    s["speed"] = min(max(s["speed"], 0), 14)
    s["profile"] = s["profile"][:60] if s["send"] == "network" else ""
    return s


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return normalize_settings(json.load(f))
    except (OSError, ValueError):
        return normalize_settings({})


def load_printers():
    """The saved network Zebras in their own order, each {"name", PRINTER_KEYS...};
    keys left out of the file get the defaults."""
    try:
        with open(PRINTERS, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return []
    printers = []
    for p in raw if isinstance(raw, list) else []:
        if isinstance(p, dict) and p.get("name"):
            s = normalize_settings(p)
            printers.append(dict({"name": str(p["name"])}, **{k: s[k] for k in PRINTER_KEYS}))
    return printers


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def save_settings(raw):
    """Saves the settings; with a saved printer in use, a change made on the page
    (label size, Move right, darkness...) is kept for that printer too."""
    s = normalize_settings(raw)
    printers = load_printers()
    mine = next((p for p in printers if p["name"] == s["profile"]), None)
    if mine is None:
        s["profile"] = ""
    elif any(mine[k] != s[k] for k in PRINTER_KEYS):
        mine.update({k: s[k] for k in PRINTER_KEYS})
        _write_json(PRINTERS, printers)
    _write_json(SETTINGS, s)
    return s


def _font(size, names):
    """The first of the item's fonts found (Arial family on Windows). Pillow's
    own search matches file names case by case, and Windows keeps some upper
    case (ARIALN.TTF), so the Windows Fonts folder is tried directly too."""
    fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in names:
        for path in (name, os.path.join(fonts, name)):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _text_mask(text, cap, width, look):
    """The text as mode "L" (255 = ink) with capitals `cap` dots tall, drawn at
    printer size without smoothing so small letters stay crisp, every stroke
    widened like the sticker's heavy print, letters spread to run `width` dots
    like the sticker (at most half a capital apart). Letters wider than that
    are drawn 4 times larger and narrowed to fit, keeping the strokes even;
    the item's "ink" (0-255, lower = bolder) sets where the smooth edges become
    printer dots."""
    lo, hi = 2, 4 * cap + 8
    while lo < hi:  # the largest font size whose "H" is at most `cap` dots tall
        mid = (lo + hi + 1) // 2
        top, bottom = _font(mid, look["font"]).getbbox("H", anchor="ls")[1::2]
        lo, hi = (mid, hi) if bottom - top <= cap else (lo, mid - 1)
    font = _font(lo, look["font"])
    extra = round(look["stroke"] * cap)  # dots added to the right of every stroke
    advances = [font.getlength(c) for c in text]
    gaps = max(len(text) - 1, 1)
    spacing = max(0.0, min(0.5 * cap, (width - extra - sum(advances)) / gaps))

    def draw(k, crisp):
        f = _font(lo * k, look["font"]) if k > 1 else font
        im = Image.new("L", (int((sum(advances) + spacing * gaps + 4 * cap) * k), 4 * cap * k), 0)
        d = ImageDraw.Draw(im)
        if crisp:
            d.fontmode = "1"
        x = 2 * cap * k
        for char, advance in zip(text, advances):
            d.text((round(x), 3 * cap * k), char, font=f, fill=255, anchor="ls")
            x += (advance + spacing) * k
        return im.crop(im.getbbox())

    im = draw(1, True)
    if im.width + extra > width:
        ink = look.get("ink", 128)
        return draw(4, False).resize((width, im.height), Image.LANCZOS).point(lambda v: 255 if v >= ink else 0)
    if extra:
        heavy = Image.new("L", (im.width + extra, im.height), 0)
        for dx in range(extra + 1):
            heavy.paste(255, (dx, 0), im)
        im = heavy
    return im


def render(serial, settings=None):
    """The label as a mode "1" image in printer dots, before rotation, plus facts
    for the page and warnings when the label is too small for a good barcode."""
    s = normalize_settings(settings if settings is not None else load_settings())
    look = LAYOUTS[s["layout"]]
    serial = clean_serial(serial)
    data, text = look["parse"](serial)
    dpmm = s["dpi"] / 25.4
    dots = lambda mm: int(round(mm * dpmm))
    width, height = dots(s["width_mm"]), dots(s["height_mm"])
    warnings = []

    # The item's own bar sizes on whole printer dots; when the label is too
    # short for them with quiet zones, a smaller wide:narrow ratio (Code 39),
    # then narrower bars.
    edge = dots(0.5)  # printers do not print well right at the label edge
    want = s["bar_dots"] or max(1, round(look["bar_mm"] * dpmm))
    ratio = look.get("ratio", 0)
    for bar, wide in [(n, w) for n in range(want, 0, -1)
                      for w in (range(int(ratio * n + 0.5), 2 * n - 1, -1) if ratio else [0])]:
        widths = barcode_dots(data, look["symbology"], bar, wide, look.get("char_gap", 1))
        if sum(widths) + 2 * QUIET * bar <= width - 2 * edge:
            break
    else:
        raise ValueError(f"The label is too short for this serial: {s['width_mm']:g} mm at {s['dpi']} dpi "
                         f"needs at least {(sum(widths) + 2 * QUIET * bar) / dpmm + 1:.0f} mm.")
    if bar < want:
        warnings.append(f"The label is too narrow for {want}-dot bars with quiet zones - printing {bar}-dot bars.")
    if ratio and wide < int(ratio * bar + 0.5):
        warnings.append(f"Wide bars are {wide / bar:g} times the narrow ones (the item's {ratio:g}) to fit the label.")
    if bar == 1 and s["dpi"] < 300:
        warnings.append(f"Narrowest bar is 1 dot ({25.4 / s['dpi']:.2f} mm) - check that a print scans.")
    bar_w = sum(widths)

    # Heights in proportion to the barcode width, as on the sticker; the bars
    # grow with the letters when these are raised to the smallest readable
    # size, so they keep the sticker's look; all shrunk together when the label
    # is lower than that.
    sticker_cap = look["cap"] * bar_w
    cap = dots(s["text_mm"]) if s["text_mm"] else max(round(sticker_cap), 9)
    bars = dots(s["bars_mm"]) if s["bars_mm"] else round(look["bars"] * bar_w * max(cap / sticker_cap, 1))
    gap = max(2, round(look["gap"] * bar_w))
    avail = height - 2 * dots(0.4)
    if cap + gap + bars > avail:
        k = avail / (cap + gap + bars)
        cap, gap = max(round(cap * k), 7), max(round(gap * k), 1)
        bars = avail - cap - gap
        if bars < 4:
            raise ValueError(f"The label is too low for text and barcode: {s['height_mm']:g} mm.")
    if bars < dots(2.0):
        warnings.append(f"Bars are only {bars / dpmm:.1f} mm tall - a taller label scans more easily.")

    mask = _text_mask(text, cap, min(round(look["span"] * bar_w), width - 2 * edge), look)
    x0 = (width - bar_w) // 2 + dots(s["shift_x_mm"])
    y0 = (height - (mask.height + gap + bars)) // 2 + dots(s["shift_y_mm"])
    img = Image.new("1", (width, height), 1)
    draw = ImageDraw.Draw(img)
    tx = x0 + (bar_w - mask.width) // 2 if look["align"] == "center" else x0
    ty, top = (y0, y0 + mask.height + gap) if look["text"] == "above" else (y0 + bars + gap, y0)
    img.paste(0, (tx, ty, tx + mask.width, ty + mask.height), mask)
    x = x0
    for k, w in enumerate(widths):
        if k % 2 == 0:
            draw.rectangle([x, top, x + w - 1, top + bars - 1], fill=0)
        x += w

    info = {
        "serial": serial, "layout": s["layout"], "symbology": look["symbology"], "dots": [width, height],
        "barDots": bar, "wideDots": wide,
        "barMm": round(bar / dpmm, 3), "barcodeMm": round(bar_w / dpmm, 1),
        "barcodeHeightMm": round(bars / dpmm, 1), "textMm": round(cap / dpmm, 1),
        # the label size that gives exactly the sticker's proportions with these bars
        "stickerMm": [round(bar_w * look["length"] / dpmm, 1), round(bar_w * look["height"] / dpmm, 1)],
    }
    return img, info, warnings


def to_zpl(img, rotate=0, copies=1, darkness=0, speed=0):
    """One ZPL label: the picture as an ASCII-hex graphic field, black dots = 1.
    Darkness (^MD) and speed (^PR) go with the label only when set; nothing is
    saved to the printer, which keeps them until a job sets its own or it is
    turned off."""
    if rotate:
        img = img.rotate(-rotate, expand=True)  # PIL turns counter-clockwise
    width, height = img.size
    ink = img.convert("L").point(lambda v: 0 if v else 255).convert("1", dither=Image.Dither.NONE)
    box = ink.getbbox() or (0, 0, 1, 1)  # only the printed part, placed by ^FO - a 4x6" label stays small
    part = ink.crop(box)
    row = (part.width + 7) // 8
    data = part.tobytes()
    total = row * part.height
    tune = (f"^MD{int(darkness)}\n" if darkness else "") + (f"^PR{int(speed)}\n" if speed else "")
    return (f"^XA\n^PW{width}\n^LL{height}\n^LH0,0\n{tune}"
            f"^FO{box[0]},{box[1]}^GFA,{total},{total},{row},{data.hex().upper()}^FS\n"
            f"^PQ{int(copies)}\n^XZ\n")


def label_zpl(serial, copies=1, settings=None):
    s = normalize_settings(settings if settings is not None else load_settings())
    img, info, warnings = render(serial, s)
    return to_zpl(img, s["rotate"], copies, s["darkness"], s["speed"]), info, warnings


# --- printing ---------------------------------------------------------------

def _winspool():
    import ctypes
    from ctypes import wintypes

    class DOC_INFO_1(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR),
                    ("pDatatype", wintypes.LPWSTR)]

    class PRINTER_INFO_4(ctypes.Structure):
        _fields_ = [("pPrinterName", wintypes.LPWSTR), ("pServerName", wintypes.LPWSTR),
                    ("Attributes", wintypes.DWORD)]

    ws = ctypes.WinDLL("winspool.drv", use_last_error=True)
    H, DW, PDW = wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
    ws.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(H), ctypes.c_void_p]
    ws.StartDocPrinterW.argtypes = [H, DW, ctypes.POINTER(DOC_INFO_1)]
    ws.StartDocPrinterW.restype = DW
    ws.WritePrinter.argtypes = [H, ctypes.c_void_p, DW, PDW]
    for name in ("StartPagePrinter", "EndPagePrinter", "EndDocPrinter", "ClosePrinter"):
        getattr(ws, name).argtypes = [H]
    ws.EnumPrintersW.argtypes = [DW, wintypes.LPWSTR, DW, ctypes.c_void_p, DW, PDW, PDW]
    return ctypes, wintypes, ws, DOC_INFO_1, PRINTER_INFO_4


def windows_printers():
    """Names of the printers installed on this PC (local and connected)."""
    if os.name != "nt":
        return []
    ctypes, wintypes, ws, _, PRINTER_INFO_4 = _winspool()
    flags = 2 | 4  # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    needed, count = wintypes.DWORD(), wintypes.DWORD()
    ws.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(count))
    if not needed.value:
        return []
    buf = ctypes.create_string_buffer(needed.value)
    if not ws.EnumPrintersW(flags, None, 4, buf, needed, ctypes.byref(needed), ctypes.byref(count)):
        raise ctypes.WinError(ctypes.get_last_error())
    items = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_4))
    return sorted(items[i].pPrinterName for i in range(count.value))


def pick_printer(name, printers):
    """The saved printer, or the first Zebra one - never an office printer, which
    would print the ZPL as pages of text."""
    if name:
        return name if name in printers else None
    return next((p for p in printers if any(k in p.lower() for k in ("zdesigner", "zebra"))), None)


def _print_windows(printer, data, output_file=None):
    ctypes, wintypes, ws, DOC_INFO_1, _ = _winspool()
    handle = wintypes.HANDLE()
    if not ws.OpenPrinterW(printer, ctypes.byref(handle), None):
        raise OSError(f"Cannot open printer {printer!r}: {ctypes.WinError(ctypes.get_last_error())}")
    try:
        doc = DOC_INFO_1("Serial label", output_file, "RAW")
        if not ws.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
            raise OSError(f"Printer {printer!r} refused the job: {ctypes.WinError(ctypes.get_last_error())}")
        try:
            ws.StartPagePrinter(handle)
            written = wintypes.DWORD()
            ok = ws.WritePrinter(handle, data, len(data), ctypes.byref(written))
            ws.EndPagePrinter(handle)
            if not ok or written.value != len(data):
                raise OSError(f"Sending to {printer!r} failed: {ctypes.WinError(ctypes.get_last_error())}")
        finally:
            ws.EndDocPrinter(handle)
    finally:
        ws.ClosePrinter(handle)


def send(zpl, settings=None):
    """Sends ZPL to the configured printer; returns the printer it went to."""
    s = normalize_settings(settings if settings is not None else load_settings())
    data = zpl.encode("ascii")
    if s["send"] == "network":
        if not s["host"]:
            raise ValueError("Set the printer's IP address in the settings.")
        with socket.create_connection((s["host"], s["port"]), timeout=5) as sock:
            sock.sendall(data)
        where = f"{s['host']}:{s['port']}"
        return f"{s['profile']} ({where})" if s["profile"] else where
    printers = windows_printers()
    printer = pick_printer(s["printer"], printers)
    if not printer:
        raise ValueError(f"Printer {s['printer']!r} is not installed on this PC." if s["printer"] else
                         "No Zebra printer found on this PC - pick the printer in the settings.")
    _print_windows(printer, data)
    return printer


def print_label(serial, copies=1):
    s = load_settings()
    copies = min(max(int(copies), 1), 50)
    zpl, info, warnings = label_zpl(serial, copies, s)
    printer = send(zpl, s)
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "serial": info["serial"],
             "item": info["layout"], "copies": copies, "printer": printer}
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry, info, warnings


def recent_prints(limit=30):
    try:
        with open(LOG, encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except OSError:
        return []
    return [json.loads(line) for line in reversed(lines) if line.strip()]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Render a serial label (no printing).")
    ap.add_argument("serial")
    ap.add_argument("--png", help="save the label picture here")
    ap.add_argument("--zpl", help="save the ZPL here")
    args = ap.parse_args()
    settings = load_settings()
    image, facts, notes = render(args.serial, settings)
    if args.png:
        image.save(args.png)
    if args.zpl:
        with open(args.zpl, "w", encoding="ascii") as f:
            f.write(to_zpl(image, settings["rotate"], 1, settings["darkness"], settings["speed"]))
    print(json.dumps(facts, indent=2))
    for note in notes:
        print("WARNING:", note, file=sys.stderr)
