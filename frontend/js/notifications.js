/* notifications.js — powers settings.html */

async function init() {
  const user = await requireAuth();
  if (!user) return;
  renderNavbar("/settings.html");
  await loadSettings();
}
init();

async function loadSettings() {
  try {
    const s = await API.get("/api/settings/notifications");
    const prefs = (s.notification_preference || "").split(",").map((p) => p.trim());
    document.getElementById("opt-telegram").checked = prefs.includes("telegram");
    document.getElementById("opt-sms").checked = prefs.includes("sms");
    document.getElementById("opt-email").checked = prefs.includes("email");
    document.getElementById("opt-call").checked = prefs.includes("call");
    document.getElementById("opt-browser").checked = prefs.includes("browser");
    document.getElementById("opt-sound").checked = prefs.includes("sound");
    document.getElementById("telegram-chat-id").value = s.telegram_chat_id || "";
    document.getElementById("followup-minutes").value = s.follow_up_minutes || 5;
    document.getElementById("miss-alert").checked = !!s.miss_alert_enabled;
    document.getElementById("em-name").value = s.emergency_contact_name || "";
    document.getElementById("em-phone").value = s.emergency_contact_phone || "";

    const statusMount = document.getElementById("channel-status");
    statusMount.innerHTML = Object.entries(s.channels).map(([name, on]) => `
      <span class="chip ${on ? "active" : ""}">${labelFor(name)}: ${on ? "Connected" : "Not Configured"}</span>
    `).join("");
  } catch (e) {
    toast(e.message, "error");
  }
}

function labelFor(name) {
  return { telegram: "Telegram", sms: "SMS", email: "Email", call: "Phone Call", browser: "Browser" }[name] || name;
}

document.getElementById("save-settings-btn").addEventListener("click", async () => {
  const selected = ["opt-telegram", "opt-sms", "opt-email", "opt-call", "opt-browser", "opt-sound"]
    .filter((id) => document.getElementById(id).checked)
    .map((id) => id.replace("opt-", ""));

  if (selected.filter((s) => s !== "sound").length === 0) {
    toast("Please select at least one notification method.", "error");
    return;
  }

  try {
    await API.post("/api/settings/notifications", {
      notification_preference: selected.join(","),
      telegram_chat_id: document.getElementById("telegram-chat-id").value.trim() || null,
      follow_up_minutes: parseInt(document.getElementById("followup-minutes").value, 10),
      miss_alert_enabled: document.getElementById("miss-alert").checked,
      emergency_contact_name: document.getElementById("em-name").value.trim() || null,
      emergency_contact_phone: document.getElementById("em-phone").value.trim() || null,
    });
    toast("Settings saved.", "success");
  } catch (e) {
    toast(e.message, "error");
  }
});

document.getElementById("test-notify-btn").addEventListener("click", async () => {
  const btn = document.getElementById("test-notify-btn");
  btn.disabled = true;
  try {
    // Uses the *saved* settings, so save first if you just changed channels.
    const res = await API.post("/api/settings/test_notification", {});
    const entries = Object.entries(res.report || {});
    if (entries.length === 0) {
      toast("Select Email, SMS or Telegram and save settings first.", "info");
    }
    entries.forEach(([channel, r]) => {
      if (r.ok) toast(`${labelFor(channel)}: test sent ✅`, "success");
      else toast(`${labelFor(channel)} failed: ${r.reason || "unknown error"}`, "error");
    });
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
  }
});
