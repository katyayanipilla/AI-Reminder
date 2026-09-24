/* history.js — filterable history table. */

let currentRange = "today";

async function init() {
  const user = await requireAuth();
  if (!user) return;
  renderNavbar("/history.html");
  await loadHistory();
}
init();

function dateStr(d) { return localDateStr(d); }

function rangeToDates(range) {
  const today = new Date();
  if (range === "today") return { start: dateStr(today), end: dateStr(today) };
  if (range === "yesterday") {
    const y = new Date(today); y.setDate(y.getDate() - 1);
    return { start: dateStr(y), end: dateStr(y) };
  }
  if (range === "7" || range === "30") {
    const past = new Date(today); past.setDate(past.getDate() - (parseInt(range, 10) - 1));
    return { start: dateStr(past), end: dateStr(today) };
  }
  return { start: null, end: null }; // all time
}

document.querySelectorAll("#date-filters .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll("#date-filters .chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    currentRange = chip.dataset.range;
    document.getElementById("custom-date").value = "";
    loadHistory();
  });
});
document.getElementById("status-filter").addEventListener("change", loadHistory);
document.getElementById("custom-date").addEventListener("change", loadHistory);

async function loadHistory() {
  try {
    const customDate = document.getElementById("custom-date").value;
    let start, end;
    if (customDate) {
      start = customDate; end = customDate;
    } else {
      const r = rangeToDates(currentRange);
      start = r.start; end = r.end;
    }
    const status = document.getElementById("status-filter").value;

    const params = new URLSearchParams();
    if (start) params.set("start_date", start);
    if (end) params.set("end_date", end);
    if (status) params.set("status", status);

    const rows = await API.get(`/api/history?${params.toString()}`);
    const body = document.getElementById("history-body");
    const empty = document.getElementById("history-empty");
    if (rows.length === 0) {
      body.innerHTML = "";
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";
    body.innerHTML = rows.map((r) => `
      <tr>
        <td>${(r.scheduled_time || "").slice(0, 10)}</td>
        <td>${r.medicine_name}</td>
        <td>${r.dosage || ""}</td>
        <td>${(r.scheduled_time || "").slice(11, 16) || "–"}</td>
        <td>${r.taken_time ? r.taken_time.slice(11, 16) : "–"}</td>
        <td>${fmtStatus(r.status)}</td>
      </tr>
    `).join("");
  } catch (e) {
    toast(e.message, "error");
  }
}
