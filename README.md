# Serial Printer

Prints a replacement serial label on a Zebra printer. You pick the item, type or
scan a serial, check the preview, and press Enter. The label is a line of text
with a Code 128 barcode of the serial under it, in the design of the item's own
serial sticker (see [Items](#items-label-designs)).

The app draws the whole label at the printer's own dot size and sends it as ZPL,
so the preview is exactly what gets printed. The barcode is checked to decode
back to the typed serial.

## Setup (Windows PC with the Zebra)

1. Install **Python 3.10 or newer** from https://www.python.org/downloads/ and tick
   **"Add python.exe to PATH"** in the installer.
2. Install the Zebra driver (**ZDesigner**) so the printer shows up in Windows.
   A Zebra with a network port can be used by IP address instead.
3. Get this repo:
   ```
   git clone https://github.com/eugene317/serialprinter.git
   ```
4. Double-click **`start.bat`**. The first run creates `venv` and installs Flask and
   Pillow. Then it opens http://localhost:5003.

## First-time settings

Open **Printer and label settings** on the page. Settings are saved per PC in
`data/serial_label_settings.json`.

- **Printer**: pick the ZDesigner printer, or *Network Zebra* and enter its IP
  (port 9100). With *Auto*, the app uses the first printer whose name contains
  "Zebra" or "ZDesigner". It never falls back to an office printer.
- **Printer model**: every ZPL Zebra model is listed, split into big (industrial,
  e.g. ZT411, ZT610, 110Xi4) and small (desktop, e.g. ZD421, GK420, GX430t)
  printers. Picking one limits the resolution to what that model is made in.
  When you pick an installed printer, the model and dpi are filled in from its
  driver name (e.g. "ZDesigner ZD421-203dpi ZPL").
- **Printer resolution**: must match the printer (203, 300 or 600 dpi). It is on
  the printer's sticker or configuration printout.
- **Label width / height**: the size of the label as it comes out of the printer.
  The item's label is printed centred on it.
- **Rotate**: use this if the labels come out sideways.
- **Narrowest bar**: *Item's own* uses the item's bar size; pick a dot count only
  to override it.
- **Move right / Move down**: use these if the print is off-centre on the label.
- **Letter height / Bar height**: 0 means automatic (the item's proportions).
- **Darkness**: added to the printer's own darkness (-30 to +30, 0 = leave it).
  Too dark makes thin bars spread into the spaces, so raise it in small steps.
- **Print speed**: slower prints sharper (2 in/s is the sharpest).
  Darkness and speed go with each label only. Nothing is saved to the printer,
  but it keeps them until another job sets its own or it is turned off.

## Items (label designs)

Pick the item in the list next to the serial box. With no serial typed, the
preview shows the item's example label. The item is shared by all printers; the
printer settings (label size, position, darkness, speed) stay with the printer.

- **Bose QC 35**: `S/N:` and the serial in bold, heavy Arial-like letters,
  centred over a Code 128 barcode and running a little past both ends; bars 2.3
  times the letter height; narrowest bar 0.13 mm (1 dot at 203 dpi). Measured
  from the original earcup sticker next to test prints.
- **Sonos Play:1**: a Code 39 barcode of the 13-character serial (1-dot narrow
  bars, 3-dot wide ones, characters 2 dots apart: 31.7 mm long, 3.8 mm tall, as
  measured against the original) with `1402 B8 – E9 – 37 – 5C – 04 – 1A – 7`
  under it in bold condensed letters (Arial Narrow Bold narrowed to the
  barcode's width), as on the base sticker. Scan or type the serial (`B8E9375C041A7`, `B8-E9-37-5C-04-1A:7`).
  The 4-digit date code before it is not in the barcode, so a scan cannot give
  it: it comes from the **Date** box, which starts with `1402` (as on the
  original) and keeps the last code used - change it when a unit's original
  label shows another. Enter after the serial jumps to that box; Enter there
  prints (an emptied box prints without a date code).

A new item is added in `LAYOUTS` in `serial_label.py`, with proportions measured
from its original sticker; items still waiting for their design are listed in
`COMING_SOON`.

## Saved printers

With several network Zebras, list them in `data/serial_label_printers.json`
(kept per PC, like the settings). They show at the top of the **Printer** list;
picking one sets its IP, model, dpi and label size at once. Changes made on the
page while it is picked (label size, Move right, darkness...) are kept for that
printer.

```json
[
  {"name": "Printer 1S", "host": "192.168.1.204", "model": "S4M", "dpi": 203,
   "width_mm": 57.15, "height_mm": 31.75, "darkness": 10, "speed": 2}
]
```

Any setting left out gets its default (port 9100).

## Use

- Type or scan the serial. Enter (or the Print button) prints it. Serials are
  printed in upper case without spaces.
- Every print is logged in `data/serial_label_log.jsonl` and listed under
  **Printed**. Click a serial there to load it again.
- **Download ZPL** saves the label as a `.zpl` file. You can send it with Zebra
  Setup Utilities if direct printing does not work.
- `http://localhost:5003/?serial=077061Z8240B195AE` opens the page with that
  serial already filled in.

Without printing, from the command line:

```
venv\Scripts\python.exe serial_label.py 077061Z8240B195AE --png label.png --zpl label.zpl
```
