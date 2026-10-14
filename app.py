"""Serial Printer (2026-10-15): type or scan a serial, see the label, press
Enter and the Zebra prints "SN: <serial>" with its Code 128 barcode
(serial_label.py draws it, same layout as the Bose earcup sticker).

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
                    "models": serial_label.ZEBRA_MODELS,
                    "picked": serial_label.pick_printer(s["printer"], printers)})


@app.route("/api/preview", methods=["POST"])
def api_preview():
    try:
        img, info, warnings = serial_label.render(request.get_json(force=True).get("serial", ""))
    except ValueError as e:
        return _error(e)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    s = serial_label.load_settings()
    info.update(widthMm=s["width_mm"], heightMm=s["height_mm"], dpi=s["dpi"], rotate=s["rotate"])
    return jsonify({"ok": True, "png": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
                    "info": info, "warnings": warnings})


@app.route("/api/print", methods=["POST"])
def api_print():
    body = request.get_json(force=True)
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
  <div class="sub">Type or scan the serial, check the label, then press Enter or Print. The Zebra prints
    "SN: serial" with its Code 128 barcode, same layout as the Bose earcup sticker.</div>

  <form id="f">
    <input id="serial" placeholder="Serial" autofocus autocomplete="off" spellcheck="false">
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
      <label>Label height (mm) <input id="height_mm" type="number" step="0.5" min="4" max="150"></label>
      <label>Rotate
        <select id="rotate"><option value="0">0°</option><option value="90">90°</option>
          <option value="180">180°</option><option value="270">270°</option></select></label>
      <label>Narrowest bar
        <select id="bar_dots"><option value="0">Auto</option><option value="1">1 dot</option><option value="2">2 dots</option>
          <option value="3">3 dots</option><option value="4">4 dots</option><option value="5">5 dots</option></select></label>
      <label>Letter height (mm, 0 = auto) <input id="text_mm" type="number" step="0.1" min="0" max="20"></label>
      <label>Bar height (mm, 0 = auto) <input id="bars_mm" type="number" step="0.1" min="0" max="50"></label>
      <label>Text before serial <input id="prefix"></label>
      <label>Move right (mm) <input id="shift_x_mm" type="number" step="0.25" min="-20" max="20"></label>
      <label>Move down (mm) <input id="shift_y_mm" type="number" step="0.25" min="-20" max="20"></label>
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
const FIELDS = ["host", "port", "model", "dpi", "width_mm", "height_mm", "rotate", "bar_dots", "text_mm", "bars_mm", "prefix", "shift_x_mm", "shift_y_mm"];
let timer = null, seq = 0, models = {}, picked = null;

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
  models = d.models; picked = d.picked;
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
  $("printer").innerHTML = opts.join("");
  $("printer").value = s.send === "network" ? "net" : "win:" + s.printer;
  FIELDS.forEach(k => { $(k).value = s[k]; });
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
  body.send = p === "net" ? "network" : "windows";
  body.printer = p === "net" ? "" : p.slice(4);
  setStatus("");
  fillSettings(await post("/api/settings", body));
  $("saved").textContent = "Saved.";
  setTimeout(() => { $("saved").textContent = ""; }, 1500);
  preview();
}

async function preview() {
  const serial = $("serial").value.trim(), mine = ++seq;
  if (!serial) {
    $("preview").hidden = true; $("empty").hidden = false; $("empty").textContent = "The label shows here";
    $("info").textContent = ""; $("warn").textContent = ""; return;
  }
  const r = await post("/api/preview", {serial});
  if (mine !== seq) return;
  $("warn").textContent = (r.warnings || []).join(" ");
  if (!r.ok) {
    $("preview").hidden = true; $("empty").hidden = false; $("empty").textContent = r.error; $("info").textContent = ""; return;
  }
  const i = r.info;
  $("preview").src = r.png; $("preview").hidden = false; $("empty").hidden = true;
  $("labelbox").style.maxWidth = Math.min(760, i.widthMm * 14) + "px";
  $("info").textContent = `${i.serial} - label ${i.widthMm} x ${i.heightMm} mm at ${i.dpi} dpi${i.rotate ? ", rotated " + i.rotate + "°" : ""}` +
    ` - Code 128, narrowest bar ${i.barDots} dot${i.barDots > 1 ? "s" : ""} (${i.barMm} mm), barcode ${i.barcodeMm} x ${i.barcodeHeightMm} mm,` +
    ` letters ${i.textMm} mm. Exact Bose sticker proportions with these bars: a ${i.stickerMm[0]} x ${i.stickerMm[1]} mm label.`;
}

async function doPrint() {
  const serial = $("serial").value.trim();
  if (!serial) return;
  $("print").disabled = true; setStatus("Printing...");
  try {
    const r = await post("/api/print", {serial, copies: +$("copies").value || 1});
    if (r.ok) {
      const p = r.printed;
      setStatus(`Printed ${p.copies} x ${p.serial} on ${p.printer}.`, "ok");
      loadLog(); $("serial").select();
    } else setStatus(r.error, "bad");
  } catch (e) { setStatus("Printing failed: " + e, "bad"); }
  $("print").disabled = false; $("serial").focus();
}

async function loadLog() {
  const rows = await (await fetch("/api/log")).json();
  $("log").innerHTML = rows.length ? rows.map(r =>
    `<li><span class="sn" data-sn="${esc(r.serial)}">${esc(r.serial)}</span><span class="muted">${r.copies} x - ${esc(r.printer)}</span>` +
    `<span class="when">${esc(r.time.replace("T", " "))}</span></li>`).join("") : `<li class="muted">Nothing printed yet.</li>`;
}

$("f").onsubmit = e => { e.preventDefault(); doPrint(); };
$("serial").oninput = () => { setStatus(""); clearTimeout(timer); timer = setTimeout(preview, 150); };
FIELDS.forEach(k => { $(k).onchange = saveSettings; });
$("printer").onchange = () => {
  const p = $("printer").value, name = p === "win:" ? picked : p.slice(4);
  if (p !== "net" && name) {
    const d = detect(name);
    if (d.model) $("model").value = d.model;
    fillDpi($("model").value, d.dpi || $("dpi").value);
  }
  saveSettings();
};
$("model").onchange = () => { fillDpi($("model").value, $("dpi").value); saveSettings(); };
$("refresh").onclick = loadSettings;
$("download").onclick = () => {
  const serial = $("serial").value.trim();
  if (serial) location.href = `/api/zpl?serial=${encodeURIComponent(serial)}&copies=${+$("copies").value || 1}`;
};
$("log").onclick = e => {
  const sn = e.target.dataset && e.target.dataset.sn;
  if (sn) { $("serial").value = sn; preview(); $("serial").focus(); }
};
loadSettings(); loadLog();
const fromUrl = new URLSearchParams(location.search).get("serial");  // e.g. /?serial=077061Z8240B195AE
if (fromUrl) { $("serial").value = fromUrl; preview(); }
</script>
</body>
</html>
"""


if __name__ == "__main__":
    # host 0.0.0.0 so a phone on the same Wi-Fi can scan into it too, like the other apps.
    app.run(host="0.0.0.0", port=PORT, debug=False)
