"""Serial label (2026-10-15): prints a product's serial label on a Zebra
printer - the line "SN: <serial>" with a Code 128 barcode of the serial under
it, the same layout as the Bose earcup serial sticker (STICKER below).

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
import socket
import sys
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, "data", "serial_label_settings.json")
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
    "bar_dots": 0,         # narrowest bar in printer dots; 0 = auto
    "text_mm": 0.0,        # letter height; 0 = auto
    "bars_mm": 0.0,        # bar height; 0 = auto
    "prefix": "SN: ",
    "shift_x_mm": 0.0,     # moves everything right/down if the printer is off
    "shift_y_mm": 0.0,
}

# The Bose earcup sticker, measured from a photo, in units of its barcode
# width: label 1.30 x 0.195, barcode centred, capital letters 0.046 tall
# starting at the barcode's left edge, 0.019 above bars 0.085 tall, Arial-like
# letters spaced 0.18 of their height apart. The text then runs ~86% of the
# barcode for a 17-character serial.
STICKER = {"length": 1.30, "height": 0.195, "cap": 0.046, "gap": 0.019, "bars": 0.085, "tracking": 0.18}

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
QUIET = 10  # quiet zone each side, in modules (Code 128 minimum)


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
    s["height_mm"] = min(max(s["height_mm"], 4.0), 150.0)
    s["bar_dots"] = min(max(s["bar_dots"], 0), 10)
    s["text_mm"] = min(max(s["text_mm"], 0.0), 20.0)
    s["bars_mm"] = min(max(s["bars_mm"], 0.0), 50.0)
    s["port"] = min(max(s["port"], 1), 65535)
    s["prefix"] = s["prefix"][:20]
    s["shift_x_mm"] = min(max(s["shift_x_mm"], -20.0), 20.0)
    s["shift_y_mm"] = min(max(s["shift_y_mm"], -20.0), 20.0)
    return s


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return normalize_settings(json.load(f))
    except (OSError, ValueError):
        return normalize_settings({})


def save_settings(raw):
    s = normalize_settings(raw)
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    return s


def _font(size):
    """Arial is the closest to the Bose sticker's letters."""
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _text_mask(text, cap, max_width):
    """The text as mode "L" (255 = ink) with capitals `cap` dots tall, drawn at
    printer size without smoothing so small letters stay crisp, letters spaced
    like the sticker - closer together, then squeezed, if wider than `max_width`."""
    lo, hi = 2, 4 * cap + 8
    while lo < hi:  # the largest font size whose "H" is at most `cap` dots tall
        mid = (lo + hi + 1) // 2
        top, bottom = _font(mid).getbbox("H", anchor="ls")[1::2]
        lo, hi = (mid, hi) if bottom - top <= cap else (lo, mid - 1)
    font = _font(lo)
    advances = [font.getlength(c) for c in text]
    gaps = max(len(text) - 1, 1)
    spacing = max(0.0, min(STICKER["tracking"] * cap, (max_width - sum(advances)) / gaps))
    im = Image.new("L", (int(sum(advances) + spacing * gaps) + 4 * cap, 4 * cap), 0)
    draw = ImageDraw.Draw(im)
    draw.fontmode = "1"
    x = 2 * cap
    for char, advance in zip(text, advances):
        draw.text((round(x), 3 * cap), char, font=font, fill=255, anchor="ls")
        x += advance + spacing
    im = im.crop(im.getbbox())
    if im.width > max_width:
        im = im.resize((max_width, im.height), Image.LANCZOS).point(lambda v: 255 if v >= 128 else 0)
    return im


def render(serial, settings=None):
    """The label as a mode "1" image in printer dots, before rotation, plus facts
    for the page and warnings when the label is too small for a good barcode."""
    s = normalize_settings(settings if settings is not None else load_settings())
    serial = clean_serial(serial)
    dpmm = s["dpi"] / 25.4
    dots = lambda mm: int(round(mm * dpmm))
    width, height = dots(s["width_mm"]), dots(s["height_mm"])
    widths = code128_widths(serial)
    modules = sum(widths)
    warnings = []

    # Like the sticker the barcode runs ~77% of the label, on whole printer dots.
    edge = dots(0.5)  # printers do not print well right at the label edge
    fit = (width - 2 * edge) // (modules + 2 * QUIET)
    if s["bar_dots"]:
        bar = s["bar_dots"]
        if bar > fit:
            warnings.append(f"Bar width {bar} dots does not fit this label with quiet zones (max {max(fit, 0)}).")
    else:
        bar = min(fit, max(1, int(0.80 * width / modules)), max(1, dots(0.5)))
    if bar < 1:
        raise ValueError(f"The label is too short for this serial: {s['width_mm']:g} mm at {s['dpi']} dpi "
                         f"needs at least {(modules + 2 * QUIET) / dpmm + 1:.0f} mm.")
    if bar == 1 and s["dpi"] < 300:
        warnings.append(f"Narrowest bar is 1 dot ({25.4 / s['dpi']:.2f} mm) - may be hard to scan. "
                        f"A {(modules + 2 * QUIET) * 2 / dpmm + 1:.0f} mm wide label or a 300 dpi printer gives 2-dot bars.")
    bar_w = modules * bar

    # Heights in proportion to the barcode width, as on the sticker; all shrunk
    # together when the label is lower than that.
    cap = dots(s["text_mm"]) if s["text_mm"] else max(round(STICKER["cap"] * bar_w), 9)
    bars = dots(s["bars_mm"]) if s["bars_mm"] else round(STICKER["bars"] * bar_w)
    gap = max(2, round(STICKER["gap"] * bar_w))
    avail = height - 2 * dots(0.4)
    if cap + gap + bars > avail:
        k = avail / (cap + gap + bars)
        cap, gap = max(round(cap * k), 7), max(round(gap * k), 1)
        bars = avail - cap - gap
        if bars < 4:
            raise ValueError(f"The label is too low for text and barcode: {s['height_mm']:g} mm.")
    if bars < dots(2.0):
        warnings.append(f"Bars are only {bars / dpmm:.1f} mm tall - a taller label scans more easily.")

    text = s["prefix"] + serial
    mask = _text_mask(text, cap, bar_w)
    x0 = (width - bar_w) // 2 + dots(s["shift_x_mm"])
    y0 = (height - (mask.height + gap + bars)) // 2 + dots(s["shift_y_mm"])
    img = Image.new("1", (width, height), 1)
    draw = ImageDraw.Draw(img)
    img.paste(0, (x0, y0, x0 + mask.width, y0 + mask.height), mask)
    x, top = x0, y0 + mask.height + gap
    for k, w in enumerate(widths):
        if k % 2 == 0:
            draw.rectangle([x, top, x + w * bar - 1, top + bars - 1], fill=0)
        x += w * bar

    info = {
        "serial": serial, "dots": [width, height], "modules": modules, "barDots": bar,
        "barMm": round(bar / dpmm, 3), "barcodeMm": round(bar_w / dpmm, 1),
        "barcodeHeightMm": round(bars / dpmm, 1), "textMm": round(cap / dpmm, 1),
        # the label size that gives exactly the sticker's proportions with these bars
        "stickerMm": [round(bar_w * STICKER["length"] / dpmm, 1), round(bar_w * STICKER["height"] / dpmm, 1)],
    }
    return img, info, warnings


def to_zpl(img, rotate=0, copies=1):
    """One ZPL label: the picture as an ASCII-hex graphic field, black dots = 1."""
    if rotate:
        img = img.rotate(-rotate, expand=True)  # PIL turns counter-clockwise
    width, height = img.size
    ink = img.convert("L").point(lambda v: 0 if v else 255).convert("1", dither=Image.Dither.NONE)
    row = (width + 7) // 8
    data = ink.tobytes()
    total = row * height
    return (f"^XA\n^PW{width}\n^LL{height}\n^LH0,0\n"
            f"^FO0,0^GFA,{total},{total},{row},{data.hex().upper()}^FS\n"
            f"^PQ{int(copies)}\n^XZ\n")


def label_zpl(serial, copies=1, settings=None):
    s = normalize_settings(settings if settings is not None else load_settings())
    img, info, warnings = render(serial, s)
    return to_zpl(img, s["rotate"], copies), info, warnings


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
        return f"{s['host']}:{s['port']}"
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
             "copies": copies, "printer": printer}
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
            f.write(to_zpl(image, settings["rotate"]))
    print(json.dumps(facts, indent=2))
    for note in notes:
        print("WARNING:", note, file=sys.stderr)
