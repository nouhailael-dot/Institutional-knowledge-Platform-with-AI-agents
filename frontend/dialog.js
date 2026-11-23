// Compass's own pop-ups (GHUS, 23 Nov 2026), in place of the browser's confirm()
// and alert() boxes ("ghus-compass.onrender.com indique…"): centered on the
// page, in the platform's colors, light and dark.
//
//   if (!(await askConfirm("Cancel this request?", {ok: "Cancel request", danger: true}))) return;
//   await showMessage("The upload failed.");
//
// Enter confirms, Escape or a click outside cancels; focus returns to where it was.

const STYLE_ID = "compass-dialog-style";
const CSS = `
.cdlg-backdrop{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;padding:16px;
  background:rgba(15,23,42,.45);animation:cdlg-in .12s ease-out}
.cdlg{width:min(460px,100%);background:var(--surface,#fff);color:var(--ink,#1f2937);border:1px solid var(--line,#e5e7eb);
  border-radius:14px;box-shadow:0 20px 50px rgba(15,23,42,.25);padding:22px 22px 18px;font:inherit}
.cdlg h2{margin:0 0 8px;font-size:17px;line-height:1.3}
.cdlg p{margin:0;white-space:pre-line;line-height:1.5;font-size:14.5px;color:var(--ink,#1f2937)}
.cdlg-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:20px;flex-wrap:wrap}
.cdlg-actions button{font:inherit;font-weight:600;font-size:14px;border-radius:9px;padding:9px 18px;cursor:pointer;
  border:1px solid var(--line,#d0d5dd);background:var(--surface,#fff);color:var(--ink,#1f2937)}
.cdlg-actions .cdlg-ok{background:var(--accent,#d9480f);border-color:var(--accent,#d9480f);color:#fff}
.cdlg-actions .cdlg-ok.danger{background:#b42318;border-color:#b42318}
.cdlg-actions button:focus-visible{outline:2px solid var(--accent,#d9480f);outline-offset:2px}
@keyframes cdlg-in{from{opacity:0}to{opacity:1}}
`;

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.appendChild(style);
}

/** The pop-up itself; resolves true (OK) or false (Cancel, Escape, outside click). */
function open({title, message, ok, cancel, danger}) {
  ensureStyle();
  const before = document.activeElement;
  return new Promise((resolve) => {
    const backdrop = document.createElement("div");
    backdrop.className = "cdlg-backdrop";
    const box = document.createElement("div");
    box.className = "cdlg";
    box.setAttribute("role", cancel ? "alertdialog" : "dialog");
    box.setAttribute("aria-modal", "true");
    if (title) {
      const h = document.createElement("h2");
      h.id = "cdlg-title";
      h.textContent = title;
      box.appendChild(h);
      box.setAttribute("aria-labelledby", "cdlg-title");
    }
    const p = document.createElement("p");
    p.id = "cdlg-message";
    p.textContent = String(message ?? "");
    box.appendChild(p);
    box.setAttribute("aria-describedby", "cdlg-message");
    const actions = document.createElement("div");
    actions.className = "cdlg-actions";
    let no = null;
    if (cancel) {
      no = document.createElement("button");
      no.type = "button";
      no.textContent = cancel;
      actions.appendChild(no);
    }
    const yes = document.createElement("button");
    yes.type = "button";
    yes.className = "cdlg-ok" + (danger ? " danger" : "");
    yes.textContent = ok;
    actions.appendChild(yes);
    box.appendChild(actions);
    backdrop.appendChild(box);

    function close(answer) {
      document.removeEventListener("keydown", onKey, true);
      backdrop.remove();
      if (before && typeof before.focus === "function") before.focus();
      resolve(answer);
    }
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(false); }
      else if (e.key === "Enter" && document.activeElement !== no) { e.preventDefault(); close(true); }
      else if (e.key === "Tab") {                         // focus stays inside the pop-up
        const buttons = [no, yes].filter(Boolean);
        const at = buttons.indexOf(document.activeElement);
        e.preventDefault();
        buttons[(at + (e.shiftKey ? buttons.length - 1 : 1)) % buttons.length].focus();
      }
    }
    yes.addEventListener("click", () => close(true));
    if (no) no.addEventListener("click", () => close(false));
    backdrop.addEventListener("mousedown", (e) => { if (e.target === backdrop) close(false); });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(backdrop);
    yes.focus();
  });
}

/** A question with OK and Cancel; true when confirmed. */
export function askConfirm(message, {title = "", ok = "OK", cancel = "Cancel", danger = false} = {}) {
  return open({title, message, ok, cancel, danger});
}

/** A message with one OK button. */
export function showMessage(message, {title = "", ok = "OK"} = {}) {
  return open({title, message, ok, cancel: null, danger: false}).then(() => undefined);
}
