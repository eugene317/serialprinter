"""Serial Printer (2026-10-15): pick the item, type or scan a serial, see the
label, press Enter and the Zebra prints the item's serial label - e.g. Bose
QC 35: "S/N:<serial>" with its Code 128 barcode (serial_label.py draws it).

It keeps data/serial_label_settings.json (printer, label size) and logs every
print to data/serial_label_log.jsonl. Run it on the PC the Zebra is plugged
into, or point it at a network Zebra by IP.

Run: start.bat, or venv\\Scripts\\python.exe app.py   ->  http://localhost:5003
"""

import base64
import io
import os

from flask import Flask, Response, jsonify, render_template_string, request

import serial_label

app = Flask(__name__)
app.json.sort_keys = False  # keep ZEBRA_MODELS in its own order on the page
PORT = 5003


def _error(e, status=400):
    return jsonify({"ok": False, "error": str(e)}), status


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    s = serial_label.save_settings(request.get_json(force=True)) if request.method == "POST" \
        else serial_label.load_settings()
    try:
        printers = serial_label.windows_printers()
    except OSError:
        printers = []
    return jsonify({"settings": s, "printers": printers, "saved": os.path.exists(serial_label.SETTINGS),
                    "models": serial_label.ZEBRA_MODELS, "profiles": serial_label.load_printers(),
                    "layouts": [{"name": n, "example": l["example"], "dateCode": l.get("date_code", "")}
                                for n, l in serial_label.LAYOUTS.items()],
                    "soon": serial_label.COMING_SOON,
                    "picked": serial_label.pick_printer(s["printer"], printers)})


@app.route("/api/preview", methods=["POST"])
def api_preview():
    # "guess": the item the serial belongs to, so the page can switch to it
    serial = request.get_json(force=True).get("serial", "")
    guess = serial_label.guess_layout(serial)
    try:
        img, info, warnings = serial_label.render(serial)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e), "guess": guess}), 400
    buf = io.BytesIO()
    img.save(buf, "PNG")
    s = serial_label.load_settings()
    info.update(widthMm=s["width_mm"], heightMm=s["height_mm"], dpi=s["dpi"], rotate=s["rotate"])
    return jsonify({"ok": True, "png": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
                    "info": info, "warnings": warnings, "guess": guess})


@app.route("/api/print", methods=["POST"])
def api_print():
    body = request.get_json(force=True)
    guess = serial_label.guess_layout(body.get("serial", ""))
    if guess and guess != serial_label.load_settings()["layout"]:  # e.g. a Sonos serial scanned under QC 35
        return jsonify({"ok": False, "guess": guess, "error": f"This is a {guess} serial - the item is "
                        f"switched to {guess}. Check the label, then print."}), 400
    try:
        entry, info, warnings = serial_label.print_label(body.get("serial", ""), body.get("copies") or 1)
    except ValueError as e:
        return _error(e)
    except OSError as e:
        return _error(f"Printing failed: {e}", 500)
    return jsonify({"ok": True, "printed": entry, "warnings": warnings})


@app.route("/api/zpl")
def api_zpl():
    try:
        zpl, info, _ = serial_label.label_zpl(request.args.get("serial", ""), int(request.args.get("copies") or 1))
    except ValueError as e:
        return _error(e)
    return Response(zpl, mimetype="text/plain",
                    headers={"Content-Disposition": f'attachment; filename="SN_{info["serial"]}.zpl"'})


@app.route("/api/log")
def api_log():
    return jsonify(serial_label.recent_prints())


@app.route("/")
def index():
    return render_template_string(PAGE)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Serial Printer</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --text:#1c2128; --muted:#5f6b7a; --line:#e2e6eb;
          --ok:#1f8a4c; --warn:#b7791f; --bad:#c0392b; --info:#2463b8; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#14171c; --card:#1d2229; --text:#e6e9ee; --muted:#9aa5b3; --line:#2e353f;
            --ok:#3fbf75; --warn:#e0a845; --bad:#ef6b5b; --info:#6aa3f0; }
  }
  * { box-sizing:border-box; }
  [hidden] { display:none !important; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  main { max-width:860px; margin:0 auto; padding:20px 16px 40px; }
  h1 { font-size:20px; margin:0 0 2px; }
  h2 { font-size:15px; margin:0 0 8px; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:16px; }
  form { display:flex; gap:8px; flex-wrap:wrap; }
  input, select { font:inherit; padding:12px 14px; border:1px solid var(--line); border-radius:10px;
          background:var(--card); color:var(--text); min-width:0; }
  #serial { flex:3 1 260px; font-family:ui-monospace, Consolas, monospace; font-size:18px; letter-spacing:.5px; }
  #copies { flex:0 0 90px; }
  #layout { flex:1 1 170px; font-weight:600; }
  #date { flex:0 0 150px; font-family:ui-monospace, Consolas, monospace; font-size:18px; }
  #date.need { border-color:var(--warn); box-shadow:0 0 0 2px color-mix(in srgb, var(--warn) 35%, transparent); }
  option:disabled { color:var(--muted); }
  button { font:inherit; padding:12px 22px; border:0; border-radius:10px; background:var(--info);
           color:#fff; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  button.ghost { background:transparent; color:var(--muted); border:1px solid var(--line); padding:6px 10px; font-size:13px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px; margin-top:16px; }
  .stage { display:flex; justify-content:center; padding:18px 8px; background:repeating-linear-gradient(
           45deg, transparent 0 8px, color-mix(in srgb, var(--line) 45%, transparent) 8px 16px); border-radius:10px; }
  .stage img { display:block; width:100%; background:#fff;
               box-shadow:0 0 0 1px #b9c0c8, 0 2px 8px rgba(0,0,0,.12); border-radius:3px; }
  .empty { color:var(--muted); padding:28px 0; text-align:center; }
  .muted { color:var(--muted); font-size:13px; }
  .msg { margin-top:10px; font-size:14px; }
  .msg.ok { color:var(--ok); } .msg.bad { color:var(--bad); } .msg.warn { color:var(--warn); }
  details summary { cursor:pointer; font-weight:600; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(180px, 1fr)); gap:12px; margin-top:14px; }
  .grid label { display:flex; flex-direction:column; gap:4px; font-size:13px; color:var(--muted); }
  .grid input, .grid select { padding:8px 10px; font-size:14px; }
  .grid .wide { grid-column:1 / -1; }
  ul { list-style:none; margin:0; padding:0; }
  li { display:flex; gap:12px; align-items:baseline; padding:7px 0; border-top:1px solid var(--line); font-size:13px; }
  li:first-child { border-top:0; }
  li .sn { font-family:ui-monospace, Consolas, monospace; font-size:14px; cursor:pointer; color:var(--info); }
  li .when { color:var(--muted); margin-left:auto; white-space:nowrap; }
</style>
</head>
<body>
<main>
  <h1>Serial Printer</h1>
  <div class="sub">Pick the item, type or scan the serial, check the label, then press Enter or Print.
    The Zebra prints the serial with its barcode in the design of the item's own sticker.</div>

  <form id="f">
    <select id="layout" title="Item"></select>
    <input id="serial" placeholder="Serial" autofocus autocomplete="off" spellcheck="false">
    <input id="date" placeholder="Date: 1402" title="4-digit date code from the original label, e.g. 1402"
           maxlength="4" inputmode="numeric" autocomplete="off" hidden>
    <input id="copies" type="number" min="1" max="50" value="1" title="Copies">
    <button id="print">Print</button>
  </form>

  <div class="card">
    <div class="stage"><div id="labelbox" style="width:100%;max-width:520px"><div class="empty" id="empty">The label shows here</div>
      <img id="preview" alt="Label preview" hidden></div></div>
    <div id="info" class="muted" style="margin-top:10px"></div>
    <div id="warn" class="msg warn"></div>
    <div id="status" class="msg"></div>
  </div>

  <details class="card" id="settingsCard">
    <summary>Printer and label settings</summary>
    <div class="grid">
      <label class="wide">Printer
        <select id="printer"></select></label>
      <label class="net">Printer IP address <input id="host" placeholder="192.168.1.50"></label>
      <label class="net">Port <input id="port" type="number" min="1" max="65535"></label>
      <label>Printer model
        <select id="model"></select></label>
      <label>Printer resolution
        <select id="dpi"></select></label>
      <label>Label width (mm) <input id="width_mm" type="number" step="0.5" min="10" max="200"></label>
      <label>Label height (mm) <input id="height_mm" type="number" step="0.5" min="4" max="300"></label>
      <label>Rotate
        <select id="rotate"><option value="0">0°</option><option value="90">90°</option>
          <option value="180">180°</option><option value="270">270°</option></select></label>
      <label>Narrowest bar
        <select id="bar_dots"><option value="0">Item's own</option><option value="1">1 dot</option><option value="2">2 dots</option>
          <option value="3">3 dots</option><option value="4">4 dots</option><option value="5">5 dots</option></select></label>
      <label>Letter height (mm, 0 = auto) <input id="text_mm" type="number" step="0.1" min="0" max="20"></label>
      <label>Bar height (mm, 0 = auto) <input id="bars_mm" type="number" step="0.1" min="0" max="50"></label>
      <label>Move right (mm) <input id="shift_x_mm" type="number" step="0.25" min="-20" max="20"></label>
      <label>Move down (mm) <input id="shift_y_mm" type="number" step="0.25" min="-20" max="20"></label>
      <label>Darkness (+/- on the printer's, 0 = leave it) <input id="darkness" type="number" step="1" min="-30" max="30"></label>
      <label>Print speed
        <select id="speed"><option value="0">Printer's own</option><option value="2">2 in/s (sharpest)</option>
          <option value="3">3 in/s</option><option value="4">4 in/s</option><option value="6">6 in/s</option></select></label>
      <div class="wide" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button type="button" class="ghost" id="refresh">Refresh printer list</button>
        <button type="button" class="ghost" id="download">Download ZPL</button>
        <span class="muted" id="saved"></span>
      </div>
    </div>
  </details>

  <div class="card">
    <h2>Printed</h2>
    <ul id="log"><li class="muted">Nothing printed yet.</li></ul>
  </div>
</main>

<script>
const $ = id => document.getElementById(id);
const FIELDS = ["layout", "host", "port", "model", "dpi", "width_mm", "height_mm", "rotate", "bar_dots", "text_mm", "bars_mm", "shift_x_mm", "shift_y_mm", "darkness", "speed"];
let timer = null, seq = 0, models = {}, picked = null, profiles = [], layouts = [];

async function post(url, body) {
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  return r.json();
}
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]); }
function setStatus(text, kind) { $("status").textContent = text; $("status").className = "msg " + (kind || ""); }

function modelDpis(model) {
  for (const group of Object.values(models)) if (model in group) return group[model];
  return null;
}

function fillDpi(model, value) {
  const allowed = modelDpis(model) || [203, 300, 600];
  $("dpi").innerHTML = allowed.map(v => `<option value="${v}">${v} dpi (${Math.round(v / 25.4)} dots/mm)</option>`).join("");
  $("dpi").value = allowed.includes(+value) ? value : allowed[0];
}

// ZDesigner driver names carry the model and resolution, e.g. "ZDesigner ZD421-203dpi ZPL".
function detect(name) {
  const flat = t => t.toUpperCase().replace(/[\s-]/g, "");
  let model = "";
  for (const group of Object.values(models))
    for (const m of Object.keys(group))
      if (flat(name).includes(flat(m)) && m.length > model.length) model = m;
  return {model, dpi: (name.match(/(203|300|600)\s*dpi/i) || [])[1]};
}

function fillSettings(d) {
  const s = d.settings;
  models = d.models; picked = d.picked; profiles = d.profiles || []; layouts = d.layouts || [];
  $("layout").innerHTML = layouts.map(l => `<option value="${esc(l.name)}">${esc(l.name)}</option>`).join("") +
    (d.soon || []).map(n => `<option disabled>${esc(n)} - coming soon</option>`).join("");
  const group = (title, g) => `<optgroup label="${title}">` + Object.entries(g).map(([m, dpis]) =>
    `<option value="${esc(m)}">${esc(m)} (${dpis.join("/")} dpi)</option>`).join("") + `</optgroup>`;
  $("model").innerHTML = `<option value="">Not sure / other Zebra</option>` +
    group("Big printers (industrial)", models.big) + group("Small printers (desktop)", models.small);
  fillDpi(s.model, s.dpi);
  const opts = [`<option value="win:">Auto - first Zebra printer${d.picked && !s.printer ? " (" + esc(d.picked) + ")" : ""}</option>`]
    .concat(d.printers.map(p => `<option value="win:${esc(p)}">${esc(p)}</option>`))
    .concat([`<option value="net">Network Zebra (IP address)</option>`]);
  if (s.printer && !d.printers.includes(s.printer))
    opts.splice(1, 0, `<option value="win:${esc(s.printer)}">${esc(s.printer)} (not installed here)</option>`);
  const inches = mm => +(mm / 25.4).toFixed(2);
  if (profiles.length)
    opts.unshift(`<optgroup label="Saved Zebra printers">` + profiles.map(p =>
      `<option value="pro:${esc(p.name)}">${esc(p.name)} - ${esc(p.model || "Zebra")} ${p.dpi} dpi - ${esc(p.host)}` +
      ` - ${inches(p.width_mm)} x ${inches(p.height_mm)} in</option>`).join("") + `</optgroup>`);
  $("printer").innerHTML = opts.join("");
  $("printer").value = s.send === "network" ? (s.profile ? "pro:" + s.profile : "net") : "win:" + s.printer;
  FIELDS.forEach(k => { $(k).value = s[k]; });
  $("date").hidden = !needsDate();
  if (needsDate() && !$("date").value.trim()) $("date").value = needsDate();  // the item's usual code, e.g. 1402
  document.querySelectorAll(".net").forEach(el => el.hidden = s.send !== "network");
  if (s.send === "windows" && !d.picked)
    setStatus(d.printers.length ? "No Zebra printer picked - choose it in Printer and label settings." :
              "No printers installed on this PC.", "bad");
  else if (!d.saved)
    setStatus("First time on this PC: pick the printer, its model or resolution (dpi), and the label size below.", "warn");
  if (!d.saved) $("settingsCard").open = true;
}

async function loadSettings() { fillSettings(await (await fetch("/api/settings")).json()); }

async function saveSettings() {
  const p = $("printer").value, body = {};
  FIELDS.forEach(k => { body[k] = $(k).value; });
  body.send = p.startsWith("win:") ? "windows" : "network";
  body.printer = p.startsWith("win:") ? p.slice(4) : "";
  body.profile = p.startsWith("pro:") ? p.slice(4) : "";
  setStatus("");
  fillSettings(await post("/api/settings", body));
  $("saved").textContent = "Saved.";
  setTimeout(() => { $("saved").textContent = ""; }, 1500);
  preview();
}

// Items like Sonos print a date code that their barcode does not hold, so a scan
// cannot give it: it is typed in its own box and sent before the serial.
function needsDate() {  // the item's usual date code, or "" when it has none
  const item = layouts.find(l => l.name === $("layout").value);
  return item && item.dateCode || "";
}
function withDate(typed) {  // only before a bare serial; one typed with its date code is left as it is
  const date = $("date").value.trim();
  return needsDate() && date && typed.replace(/[\s:-]/g, "").length === 13 ? date + " " + typed : typed;
}
function switchItem(name) {  // a serial of another item puts that item's design on
  $("layout").value = name;
  saveSettings();
  $("serial").focus();
}

async function preview() {
  // with no serial typed, the item's example shows how its label prints
  const typed = $("serial").value.trim(), mine = ++seq;
  const item = layouts.find(l => l.name === $("layout").value);
  const serial = withDate(typed) || (item ? item.example : "");
  if (!serial) {
    $("preview").hidden = true; $("empty").hidden = false; $("empty").textContent = "The label shows here";
    $("info").textContent = ""; $("warn").textContent = ""; return;
  }
  const r = await post("/api/preview", {serial});
  if (mine !== seq) return;
  if (typed && r.guess && r.guess !== $("layout").value) {
    switchItem(r.guess);
    setStatus(`Item switched to ${r.guess} - this serial is one of its.`, "warn");
    return;
  }
  const noDate = typed && needsDate() && !$("date").value.trim() && r.ok && r.info.serial.replace(/[-:]/g, "").length === 13 ?
    ["No date code - the 4 digits before the serial on the original label (e.g. 1402) are not in its barcode; " +
     "type them in the Date box."] : [];
  $("date").classList.toggle("need", noDate.length > 0);
  $("warn").textContent = noDate.concat(r.warnings || []).join(" ");
  if (!r.ok) {
    $("preview").hidden = true; $("empty").hidden = false; $("empty").textContent = r.error; $("info").textContent = ""; return;
  }
  const i = r.info;
  $("preview").src = r.png; $("preview").hidden = false; $("empty").hidden = true;
  $("labelbox").style.maxWidth = Math.min(760, i.widthMm * 14) + "px";
  $("info").textContent = (typed ? "" : `Example print-out for ${i.layout} - type or scan the serial to print yours. `) +
    `${i.layout}: ${i.serial} - label ${i.widthMm} x ${i.heightMm} mm at ${i.dpi} dpi${i.rotate ? ", rotated " + i.rotate + "°" : ""}` +
    ` - ${i.symbology}, narrowest bar ${i.barDots} dot${i.barDots > 1 ? "s" : ""} (${i.barMm} mm)` +
    `${i.wideDots ? ", wide " + i.wideDots + " dots" : ""}, barcode ${i.barcodeMm} x ${i.barcodeHeightMm} mm,` +
    ` letters ${i.textMm} mm. The original sticker's size with these bars: a ${i.stickerMm[0]} x ${i.stickerMm[1]} mm label.`;
}

async function doPrint() {
  const serial = withDate($("serial").value.trim());
  if (!serial) return;
  $("print").disabled = true; setStatus("Printing...");
  try {
    const r = await post("/api/print", {serial, copies: +$("copies").value || 1});
    if (r.ok) {
      const p = r.printed;
      setStatus(`Printed ${p.copies} x ${p.serial} on ${p.printer}.`, "ok");
      loadLog(); $("serial").select();
    } else if (r.guess && r.guess !== $("layout").value) {
      switchItem(r.guess);
      setStatus(r.error, "warn");
    } else setStatus(r.error, "bad");
  } catch (e) { setStatus("Printing failed: " + e, "bad"); }
  $("print").disabled = false; $("serial").focus();
}

async function loadLog() {
  const rows = await (await fetch("/api/log")).json();
  $("log").innerHTML = rows.length ? rows.map(r =>
    `<li><span class="sn" data-sn="${esc(r.serial)}">${esc(r.serial)}</span>` +
    `<span class="muted">${r.item ? esc(r.item) + " - " : ""}${r.copies} x - ${esc(r.printer)}</span>` +
    `<span class="when">${esc(r.time.replace("T", " "))}</span></li>`).join("") : `<li class="muted">Nothing printed yet.</li>`;
}

$("f").onsubmit = e => {
  e.preventDefault();
  // a scanner's Enter after the serial moves on to the date code; Enter there prints
  if (needsDate() && document.activeElement === $("serial") && $("serial").value.trim()) {
    $("date").focus(); $("date").select(); return;
  }
  doPrint();
};
$("serial").oninput = $("date").oninput = () => { setStatus(""); clearTimeout(timer); timer = setTimeout(preview, 150); };
FIELDS.forEach(k => { $(k).onchange = saveSettings; });
$("printer").onchange = () => {
  const p = $("printer").value, name = p === "win:" ? picked : p.slice(4);
  const mine = p.startsWith("pro:") && profiles.find(x => x.name === name);
  if (mine) {  // a saved printer brings its own IP, model, dpi, label size and fine-tuning
    $("model").value = mine.model;
    fillDpi(mine.model, mine.dpi);
    FIELDS.forEach(k => { if (k in mine && k !== "model" && k !== "dpi") $(k).value = mine[k]; });
  } else if (p.startsWith("win:") && name) {
    const d = detect(name);
    if (d.model) $("model").value = d.model;
    fillDpi($("model").value, d.dpi || $("dpi").value);
  }
  saveSettings();
};
$("model").onchange = () => { fillDpi($("model").value, $("dpi").value); saveSettings(); };
$("refresh").onclick = loadSettings;
$("download").onclick = () => {
  const serial = withDate($("serial").value.trim());
  if (serial) location.href = `/api/zpl?serial=${encodeURIComponent(serial)}&copies=${+$("copies").value || 1}`;
};
$("log").onclick = e => {
  const sn = e.target.dataset && e.target.dataset.sn;
  if (!sn) return;
  const split = needsDate() && /^(\d{4})(\w{13})$/.exec(sn);  // a logged Sonos serial keeps its date code in front
  if (split) $("date").value = split[1];
  $("serial").value = split ? split[2] : sn;
  preview(); $("serial").focus();
};
const fromUrl = new URLSearchParams(location.search).get("serial");  // e.g. /?serial=077061Z8240B195AE
if (fromUrl) $("serial").value = fromUrl;
loadSettings().then(preview); loadLog();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    # host 0.0.0.0 so a phone on the same Wi-Fi can scan into it too, like the other apps.
    app.run(host="0.0.0.0", port=PORT, debug=False)
