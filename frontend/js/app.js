/* app.js — shared helpers used on every page: API wrapper, navbar,
   toast messages, and the browser-notification polling loop. */

const API = {
  async _req(method, url, body) {
    const opts = { method, headers: {}, credentials: "same-origin" };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(url, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
      const message = (data && data.error) || `Request failed (${res.status})`;
      throw new Error(message);
    }
    return data;
  },
  get(url) { return this._req("GET", url); },
  post(url, body) { return this._req("POST", url, body); },
  put(url, body) { return this._req("PUT", url, body); },
  del(url) { return this._req("DELETE", url); },
};

function toast(message, type = "info") {
  let region = document.getElementById("toast-region");
  if (!region) {
    region = document.createElement("div");
    region.id = "toast-region";
    document.body.appendChild(region);
  }
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  region.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function fmtStatus(status) {
  const map = {
    Taken: '<span class="badge badge-taken">🟢 Taken</span>',
    Pending: '<span class="badge badge-pending">🟡 Pending</span>',
    Missed: '<span class="badge badge-missed">🔴 Missed</span>',
    "Not Taken": '<span class="badge badge-nottaken">⚪ Not Taken</span>',
  };
  return map[status] || `<span class="badge">${status}</span>`;
}

/* ------------------------------------------------------------- navbar -- */
const NAV_ITEMS = [
  { href: "/dashboard.html", label: "Dashboard" },
  { href: "/upload.html", label: "Upload Prescription" },
  { href: "/medicine.html", label: "Medicines" },
  { href: "/history.html", label: "History" },
  { href: "/statistics.html", label: "Statistics" },
  { href: "/settings.html", label: "Settings" },
  { href: "/profile.html", label: "Profile" },
];

function renderNavbar(activeHref) {
  const mount = document.getElementById("navbar");
  if (!mount) return;
  const path = activeHref || window.location.pathname;
  const links = NAV_ITEMS.map(
    (item) =>
      `<a href="${item.href}" class="${path === item.href ? "active" : ""}">${item.label}</a>`
  ).join("");
  mount.innerHTML = `
    <div class="container">
      <a class="brand" href="/dashboard.html"><span class="pill-dot"></span> AI Medicine Reminder</a>
      <div class="nav-links">
        ${links}
        <button class="nav-logout" id="logout-btn" type="button">Log out</button>
      </div>
    </div>`;
  document.getElementById("logout-btn").addEventListener("click", async () => {
    try {
      await API.post("/api/logout");
    } finally {
      window.location.href = "/login.html";
    }
  });
}

/* Redirect to login if the session has expired; call at top of protected pages.
   Also starts browser-notification polling (see below) so reminders are
   delivered no matter which page the user is currently on, not just the
   dashboard or reminders page. */
let _pollingStarted = false;
async function requireAuth() {
  try {
    const user = await API.get("/api/me");
    if (!_pollingStarted) {
      _pollingStarted = true;
      startNotificationPolling();
    }
    return user;
  } catch (e) {
    window.location.href = "/login.html";
    return null;
  }
}

/* Format a Date as a local YYYY-MM-DD string (no UTC conversion). Use this
   instead of `date.toISOString().slice(0, 10)` anywhere a *local calendar
   day* is intended - toISOString() converts to UTC first, which silently
   shifts the date by a day for users east/west of UTC (e.g. in India, any
   local time before 5:30 AM becomes "yesterday" in UTC). That mismatch is
   what caused reminders to start a day early/late and lose their last day. */
function localDateStr(d) {
  const dt = d || new Date();
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const day = String(dt.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/* ------------------------------------------------------- taken/not-taken */
async function confirmReminder(reminderId, taken, onDone) {
  try {
    const endpoint = taken ? "taken" : "not_taken";
    const res = await API.post(`/api/reminders/${reminderId}/${endpoint}`);
    toast(
      taken ? "✅ Medicine taken successfully." : "Marked as not taken. A follow-up reminder has been scheduled.",
      taken ? "success" : "info"
    );
    if (onDone) onDone(res);
  } catch (e) {
    toast(e.message, "error");
  }
}

/* --------------------------------------------------- browser notifications */
let alarmAudioCtx = null;
function playAlarmBeep() {
  try {
    alarmAudioCtx = alarmAudioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const osc = alarmAudioCtx.createOscillator();
    const gain = alarmAudioCtx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.001, alarmAudioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.15, alarmAudioCtx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, alarmAudioCtx.currentTime + 0.5);
    osc.connect(gain).connect(alarmAudioCtx.destination);
    osc.start();
    osc.stop(alarmAudioCtx.currentTime + 0.55);
    setTimeout(() => {
      if (!alarmAudioCtx) return;
      const osc2 = alarmAudioCtx.createOscillator();
      const gain2 = alarmAudioCtx.createGain();
      osc2.type = "sine";
      osc2.frequency.value = 660;
      gain2.gain.setValueAtTime(0.001, alarmAudioCtx.currentTime);
      gain2.gain.exponentialRampToValueAtTime(0.15, alarmAudioCtx.currentTime + 0.02);
      gain2.gain.exponentialRampToValueAtTime(0.001, alarmAudioCtx.currentTime + 0.5);
      osc2.connect(gain2).connect(alarmAudioCtx.destination);
      osc2.start();
      osc2.stop(alarmAudioCtx.currentTime + 0.55);
    }, 350);
  } catch (e) { /* audio not available */ }
}

function requestBrowserPermission() {
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
}

async function pollBrowserNotifications() {
  try {
    const items = await API.get("/api/notifications/pending");
    items.forEach((n) => {
      playAlarmBeep();
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification(n.title, { body: n.body });
      } else {
        toast(`${n.title} — ${n.body}`, "info");
      }
    });
  } catch (e) { /* not logged in / offline - ignore */ }
}

function startNotificationPolling() {
  requestBrowserPermission();
  pollBrowserNotifications();
  setInterval(pollBrowserNotifications, 15000);
}
