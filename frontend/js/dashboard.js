/* dashboard.js */

async function init() {
  const user = await requireAuth();
  if (!user) return;
  renderNavbar("/dashboard.html");
  document.getElementById("greeting").textContent = `Hello, ${user.name.split(" ")[0]} 👋`;
  document.getElementById("today-date").textContent = new Date().toLocaleDateString(undefined, {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });
  await loadDashboard();
  setInterval(loadDashboard, 20000);
}
init();

async function loadDashboard() {
  try {
    const data = await API.get("/api/dashboard/stats");
    document.getElementById("stat-total").textContent = data.total_today;
    document.getElementById("stat-taken").textContent = data.taken;
    document.getElementById("stat-pending").textContent = data.pending;
    document.getElementById("stat-missed").textContent = data.missed;
    document.getElementById("adherence-badge").textContent = `${data.adherence}%`;

    const nextMount = document.getElementById("next-medicine");
    if (data.next_medicine) {
      const n = data.next_medicine;
      nextMount.innerHTML = `
        <div class="med-item">
          <div>
            <div class="med-name">Next: ${n.medicine_name}</div>
            <div class="med-meta">${n.dosage || ""} • ${n.reminder_time} • ${n.food_instruction || ""}</div>
          </div>
          ${fmtStatus(n.status)}
        </div>`;
    } else {
      nextMount.innerHTML = '<p class="muted">No more medicines scheduled for today. 🎉</p>';
    }

    const listMount = document.getElementById("todays-meds");
    if (data.todays_medicines.length === 0) {
      listMount.innerHTML = '<div class="empty-state">No medicines scheduled today. <a href="/upload.html">Upload a prescription</a> to get started.</div>';
    } else {
      listMount.innerHTML = data.todays_medicines.map((r) => `
        <div class="med-item" id="reminder-${r.id}">
          <div>
            <div class="med-name">${r.medicine_name}</div>
            <div class="med-meta">${r.dosage || ""} • ${r.reminder_time} • ${r.food_instruction || ""}</div>
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

      listMount.querySelectorAll("[data-taken]").forEach((btn) =>
        btn.addEventListener("click", () => confirmReminder(btn.dataset.taken, true, loadDashboard)));
      listMount.querySelectorAll("[data-nottaken]").forEach((btn) =>
        btn.addEventListener("click", () => confirmReminder(btn.dataset.nottaken, false, loadDashboard)));
    }

    const channels = data.channels;
    const chMount = document.getElementById("channels-row");
    chMount.innerHTML = Object.entries(channels).map(([name, on]) => `
      <span class="chip ${on ? "active" : ""}">${labelFor(name)}: ${on ? "Connected" : "Not Configured"}</span>
    `).join("");
  } catch (e) {
    toast(e.message, "error");
  }
}

function labelFor(name) {
  return { telegram: "Telegram", sms: "SMS", email: "Email", call: "Phone Call", browser: "Browser" }[name] || name;
}
