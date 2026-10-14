# Serial Printer

Prints a replacement serial label on a Zebra printer. You type or scan a serial,
check the preview, and press Enter. The label has the line `SN: <serial>` with a
Code 128 barcode of the serial under it, laid out like the Bose earcup serial
sticker.

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
  The barcode is placed in whole printer dots, so its length can only change in
  steps. Below the preview, the page shows the label size that gives the exact
  sticker proportions:

  | Printer | Narrowest bar | Barcode (17-character serial) | Label for the sticker look |
  |---|---|---|---|
  | 300 dpi | 2 dots, 0.17 mm | 33.9 mm | about 44 x 7 mm (same as the Bose sticker) |
  | 203 dpi | 1 dot, 0.125 mm | 25 mm | about 33 x 5 mm (small, harder to scan) |
  | 203 dpi | 2 dots, 0.25 mm | 50 mm | about 65 x 10 mm |

- **Rotate**: use this if the labels come out sideways.
- **Move right / Move down**: use these if the print is off-centre on the label.
- **Letter height / Bar height**: 0 means automatic (sticker proportions).
- **Text before serial**: `SN: ` by default.

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
