/* medicine.js — list, edit, delete, enable/disable medicines. */

async function init() {
  const user = await requireAuth();
  if (!user) return;
  renderNavbar("/medicine.html");
  await loadMedicines();
}
init();

function timesLabel(m) {
  const parts = [];
  if (m.morning) parts.push(`Morning ${m.morning_time}`);
  if (m.afternoon) parts.push(`Afternoon ${m.afternoon_time}`);
  if (m.night) parts.push(`Night ${m.night_time}`);
  return parts.join(" • ") || "No times set";
}

async function loadMedicines() {
  try {
    const meds = await API.get("/api/medicines");
    const mount = document.getElementById("medicine-list");
    if (meds.length === 0) {
      mount.innerHTML = '<div class="empty-state">No medicines yet. <a href="/upload.html">Upload a prescription</a> to add some.</div>';
      return;
    }
    mount.innerHTML = meds.map((m) => `
      <div class="med-item" id="med-${m.id}">
        <div>
          <div class="med-name">${m.medicine_name} <span class="badge ${m.active ? "badge-on" : "badge-off"}">${m.active ? "Active" : "Disabled"}</span></div>
          <div class="med-meta">${m.dosage || ""} • ${m.food_instruction || ""} • ${m.start_date} → ${m.end_date}</div>
          <div class="med-meta">${timesLabel(m)}</div>
        </div>
        <div class="med-actions">
          <button class="btn btn-secondary btn-sm" data-edit="${m.id}">Edit</button>
          <button class="btn btn-outline btn-sm" data-toggle="${m.id}" data-active="${m.active}">${m.active ? "Disable" : "Enable"}</button>
          <button class="btn btn-danger btn-sm" data-delete="${m.id}">Delete</button>
        </div>
      </div>
    `).join("");

    mount.querySelectorAll("[data-toggle]").forEach((btn) => btn.addEventListener("click", async () => {
      const active = btn.dataset.active === "1" || btn.dataset.active === "true";
      try {
        await API.put(`/api/medicines/${btn.dataset.toggle}`, { active: active ? 0 : 1 });
        loadMedicines();
      } catch (e) { toast(e.message, "error"); }
    }));

    mount.querySelectorAll("[data-delete]").forEach((btn) => btn.addEventListener("click", async () => {
      if (!confirm("Delete this medicine and its reminders?")) return;
      try {
        await API.del(`/api/medicines/${btn.dataset.delete}`);
        toast("Medicine deleted.", "success");
        loadMedicines();
      } catch (e) { toast(e.message, "error"); }
    }));

    mount.querySelectorAll("[data-edit]").forEach((btn) => btn.addEventListener("click", () => openEditor(meds, btn.dataset.edit)));
  } catch (e) {
    toast(e.message, "error");
  }
}

function openEditor(meds, id) {
  const m = meds.find((x) => String(x.id) === String(id));
  const el = document.getElementById(`med-${id}`);
  el.outerHTML = `
    <div class="card" id="med-${id}" style="margin-bottom:12px;">
      <div class="card-row cols-2">
        <div class="field"><label>Medicine Name</label><input type="text" id="e-name-${id}" value="${m.medicine_name}"></div>
        <div class="field"><label>Dosage</label><input type="text" id="e-dosage-${id}" value="${m.dosage || ""}"></div>
      </div>
      <div class="card-row cols-3">
        <div class="field"><label>Morning</label><input type="time" id="e-morning-${id}" value="${m.morning_time}"></div>
        <div class="field"><label>Afternoon</label><input type="time" id="e-afternoon-${id}" value="${m.afternoon_time}"></div>
        <div class="field"><label>Night</label><input type="time" id="e-night-${id}" value="${m.night_time}"></div>
      </div>
      <div class="card-row cols-2">
        <div class="field"><label>Start Date</label><input type="date" id="e-start-${id}" value="${m.start_date}"></div>
        <div class="field"><label>End Date</label><input type="date" id="e-end-${id}" value="${m.end_date}"></div>
      </div>
      <div style="display:flex; gap:10px;">
        <button class="btn btn-primary btn-sm" id="e-save-${id}">Save Changes</button>
        <button class="btn btn-outline btn-sm" id="e-cancel-${id}">Cancel</button>
      </div>
    </div>`;

  document.getElementById(`e-cancel-${id}`).addEventListener("click", loadMedicines);
  document.getElementById(`e-save-${id}`).addEventListener("click", async () => {
    try {
      const res = await API.put(`/api/medicines/${id}`, {
        medicine_name: document.getElementById(`e-name-${id}`).value,
        dosage: document.getElementById(`e-dosage-${id}`).value,
        morning_time: document.getElementById(`e-morning-${id}`).value,
        afternoon_time: document.getElementById(`e-afternoon-${id}`).value,
        night_time: document.getElementById(`e-night-${id}`).value,
        start_date: document.getElementById(`e-start-${id}`).value,
        end_date: document.getElementById(`e-end-${id}`).value,
      });
      const extra = res.reminders_regenerated ? ` ${res.reminders_regenerated} upcoming reminder(s) rescheduled.` : "";
      toast(`Medicine updated.${extra}`, "success");
      loadMedicines();
    } catch (e) { toast(e.message, "error"); }
  });
}
