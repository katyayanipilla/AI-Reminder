/* statistics.js */

async function init() {
  const user = await requireAuth();
  if (!user) return;
  renderNavbar("/statistics.html");
  await loadStats();
}
init();

async function loadStats() {
  try {
    const data = await API.get("/api/statistics");
    document.getElementById("adherence-num").textContent = `${data.adherence}%`;
    document.getElementById("stat-total-meds").textContent = data.total_medicines;
    document.getElementById("stat-total-reminders").textContent = data.total_reminders;
    document.getElementById("stat-taken").textContent = data.taken;
    document.getElementById("stat-missed").textContent = data.missed;
    document.getElementById("legend-taken").textContent = data.taken;
    document.getElementById("legend-pending").textContent = data.pending;
    document.getElementById("legend-missed").textContent = data.missed;

    const circumference = 2 * Math.PI * 60;
    const offset = circumference * (1 - data.adherence / 100);
    const ring = document.getElementById("ring-progress");
    ring.setAttribute("stroke-dasharray", circumference.toFixed(1));
    ring.setAttribute("stroke-dashoffset", offset.toFixed(1));

    const total = Math.max(data.taken + data.pending + data.missed, 1);
    const bar = document.getElementById("bar-chart");
    bar.innerHTML = `
      <div style="flex:${data.taken}; background:#2E8B57; min-width:${data.taken ? 4 : 0}px;"></div>
      <div style="flex:${data.pending}; background:#C98A1F; min-width:${data.pending ? 4 : 0}px;"></div>
      <div style="flex:${data.missed}; background:#C0392B; min-width:${data.missed ? 4 : 0}px;"></div>
    `;
  } catch (e) {
    toast(e.message, "error");
  }
}
