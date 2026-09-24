/* reminders.js — today's reminder list + demo-mode tools. */

let selectedTestMinutes = 1;

async function init() {
  const user = await requireAuth();
  if (!user) return;
  renderNavbar("/reminders.html");
  await loadReminders();
  setInterval(loadReminders, 20000);
}
init();

async function loadReminders() {
  try {
    const rows = await API.get("/api/reminders/today");
    const mount = document.getElementById("reminders-list");
    if (rows.length === 0) {
      mount.innerHTML = '<div class="empty-state">No reminders today. <a href="/upload.html">Upload a prescription</a> to create some.</div>';
      return;
    }
    mount.innerHTML = rows.map((r) => `
      <div class="med-item">
        <div>
          <div class="med-name">${r.medicine_name}</div>
          <div class="med-meta">${r.dosage || ""} • ${r.reminder_time} • ${r.food_instruction || ""} • via ${r.notification_method}</div>
        </div>
        <div style="display:flex; align-items:center; gap:12px;">
          ${fmtStatus(r.status)}
          ${r.status === "Pending" || r.status === "Not Taken" ? `
            <div class="med-actions">
              <button class="btn btn-taken btn-sm" data-taken="${r.id}">TAKEN</button>
              <button class="btn btn-nottaken btn-sm" data-nottaken="${r.id}">NOT TAKEN</button>
            </div>` : ""}
        </div>
      </div>
    `).join("");
    mount.querySelectorAll("[data-taken]").forEach((btn) =>
      btn.addEventListener("click", () => confirmReminder(btn.dataset.taken, true, loadReminders)));
    mount.querySelectorAll("[data-nottaken]").forEach((btn) =>
      btn.addEventListener("click", () => confirmReminder(btn.dataset.nottaken, false, loadReminders)));
  } catch (e) {
    toast(e.message, "error");
  }
}

document.getElementById("seed-btn").addEventListener("click", async () => {
  try {
    const res = await API.post("/api/demo/seed");
    toast(`Sample data loaded — ${res.reminders_created} reminders created.`, "success");
    loadReminders();
  } catch (e) { toast(e.message, "error"); }
});

document.querySelectorAll("#test-minutes .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll("#test-minutes .chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    selectedTestMinutes = parseInt(chip.dataset.min, 10);
  });
});

document.getElementById("test-reminder-btn").addEventListener("click", async () => {
  try {
    const res = await API.post("/api/demo/test_reminder", { minutes: selectedTestMinutes });
    document.getElementById("test-reminder-status").textContent =
      `Test reminder scheduled for ${res.fires_at}. Keep this tab open (or use Telegram/SMS if configured) to see it fire.`;
    toast("Test reminder scheduled.", "success");
  } catch (e) { toast(e.message, "error"); }
});
