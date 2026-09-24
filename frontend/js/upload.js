/* upload.js — prescription upload, OCR trigger, and the editable
   verification table that leads into reminder creation. */

let selectedFile = null;
let medicines = []; // working list the user verifies/edits

async function init() {
  const user = await requireAuth();
  if (!user) return;
  renderNavbar("/upload.html");
  // Pre-tick the channels from the account's notification preference.
  const prefs = (user.notification_preference || "browser").split(",").map((p) => p.trim());
  document.querySelectorAll("[id^='nm-']").forEach((cb) => { cb.checked = prefs.includes(cb.value); });
}
init();

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const previewArea = document.getElementById("preview-area");
const previewImg = document.getElementById("preview-img");

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) handleFile(fileInput.files[0]);
});

function handleFile(file) {
  const ext = file.name.split(".").pop().toLowerCase();
  if (!["jpg", "jpeg", "png", "pdf"].includes(ext)) {
    toast("Please upload a JPG, JPEG, PNG or PDF file.", "error");
    return;
  }
  selectedFile = file;
  if (ext === "pdf") {
    previewImg.style.display = "none";
  } else {
    previewImg.style.display = "block";
    previewImg.src = URL.createObjectURL(file);
  }
  previewArea.style.display = "block";
}

document.getElementById("remove-btn").addEventListener("click", () => {
  selectedFile = null;
  fileInput.value = "";
  previewArea.style.display = "none";
});

document.getElementById("analyze-btn").addEventListener("click", async () => {
  if (!selectedFile) return;
  const btn = document.getElementById("analyze-btn");
  btn.disabled = true;
  btn.textContent = "Analyzing…";
  try {
    const formData = new FormData();
    formData.append("file", selectedFile);
    const res = await fetch("/api/upload", { method: "POST", body: formData, credentials: "same-origin" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Upload failed");

    medicines = data.medicines.map((m) => ({
      medicine_name: m.medicine_name,
      dosage: m.dosage,
      frequency: m.frequency,
      food_instruction: m.food_instruction,
      duration_days: parseInt((m.duration || "5").match(/\d+/)?.[0] || "5", 10),
      morning: !!m.morning, afternoon: !!m.afternoon, night: !!m.night,
      morning_time: m.morning_time || "08:00",
      afternoon_time: m.afternoon_time || "14:00",
      night_time: m.night_time || "20:00",
      needs_verification: !!m.needs_verification,
    }));
    document.getElementById("step-results").style.display = "block";
    renderMedicines();
    document.getElementById("step-results").scrollIntoView({ behavior: "smooth" });
    if (medicines.length === 0) {
      toast("No medicines could be read from this file. Try a clearer/straighter photo, or add them manually.", "error");
    } else {
      toast(`Extracted ${medicines.length} medicine(s) — please check the list against your prescription.`, "success");
    }
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Analyze Prescription";
  }
});

document.getElementById("add-med-btn").addEventListener("click", () => {
  medicines.push({
    medicine_name: "", dosage: "", frequency: "", food_instruction: "After Food",
    duration_days: 5, morning: true, afternoon: false, night: true,
    morning_time: "08:00", afternoon_time: "14:00", night_time: "20:00",
    needs_verification: false,
  });
  renderMedicines();
});

function renderMedicines() {
  const mount = document.getElementById("medicines-editor");
  if (medicines.length === 0) {
    mount.innerHTML = '<div class="empty-state">No medicines yet. Add one manually or upload a prescription.</div>';
    return;
  }
  mount.innerHTML = medicines.map((m, i) => `
    <div class="card" style="margin-bottom:16px;">
      ${m.needs_verification ? '<div class="alert alert-warn" style="margin-bottom:14px;">Please double-check this entry — OCR was not fully confident.</div>' : ""}
      <div class="card-row cols-2">
        <div class="field">
          <label>Medicine Name</label>
          <input type="text" value="${escapeHtml(m.medicine_name)}" data-i="${i}" data-f="medicine_name">
        </div>
        <div class="field">
          <label>Dosage</label>
          <input type="text" value="${escapeHtml(m.dosage)}" data-i="${i}" data-f="dosage">
        </div>
      </div>
      <div class="card-row cols-2">
        <div class="field">
          <label>Food Instruction</label>
          <select data-i="${i}" data-f="food_instruction">
            <option ${m.food_instruction === "After Food" ? "selected" : ""}>After Food</option>
            <option ${m.food_instruction === "Before Food" ? "selected" : ""}>Before Food</option>
            <option ${m.food_instruction === "With Food" ? "selected" : ""}>With Food</option>
            <option ${m.food_instruction === "Empty Stomach" ? "selected" : ""}>Empty Stomach</option>
          </select>
        </div>
        <div class="field">
          <label>Duration (days)</label>
          <input type="number" min="1" value="${m.duration_days}" data-i="${i}" data-f="duration_days">
        </div>
      </div>

      <fieldset>
        <legend>Reminder Times</legend>
        <div class="card-row cols-3">
          <div>
            <div class="checkbox-row">
              <input type="checkbox" id="m${i}-morning" ${m.morning ? "checked" : ""} data-i="${i}" data-f="morning">
              <label for="m${i}-morning">Morning</label>
            </div>
            <input type="time" value="${m.morning_time}" data-i="${i}" data-f="morning_time">
          </div>
          <div>
            <div class="checkbox-row">
              <input type="checkbox" id="m${i}-afternoon" ${m.afternoon ? "checked" : ""} data-i="${i}" data-f="afternoon">
              <label for="m${i}-afternoon">Afternoon</label>
            </div>
            <input type="time" value="${m.afternoon_time}" data-i="${i}" data-f="afternoon_time">
          </div>
          <div>
            <div class="checkbox-row">
              <input type="checkbox" id="m${i}-night" ${m.night ? "checked" : ""} data-i="${i}" data-f="night">
              <label for="m${i}-night">Night</label>
            </div>
            <input type="time" value="${m.night_time}" data-i="${i}" data-f="night_time">
          </div>
        </div>
      </fieldset>

      <button class="btn btn-outline btn-sm" data-del="${i}" type="button">Delete Medicine</button>
    </div>
  `).join("");

  mount.querySelectorAll("input, select").forEach((el) => {
    const evt = el.type === "checkbox" ? "change" : "input";
    el.addEventListener(evt, (e) => {
      const i = parseInt(e.target.dataset.i, 10);
      const f = e.target.dataset.f;
      medicines[i][f] = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    });
  });
  mount.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", () => {
      medicines.splice(parseInt(btn.dataset.del, 10), 1);
      renderMedicines();
    });
  });
}

function escapeHtml(str) {
  return (str || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

document.getElementById("confirm-btn").addEventListener("click", async () => {
  if (medicines.length === 0) {
    toast("Add at least one medicine before creating reminders.", "error");
    return;
  }
  for (const m of medicines) {
    if (!m.medicine_name.trim()) { toast("Every medicine needs a name.", "error"); return; }
    if (!m.morning && !m.afternoon && !m.night) { toast(`Select at least one reminder time for ${m.medicine_name}.`, "error"); return; }
  }

  const methods = [...document.querySelectorAll("[id^='nm-']")].filter((c) => c.checked).map((c) => c.value);
  if (methods.length === 0) { toast("Select at least one notification method.", "error"); return; }

  const today = new Date();
  const payloadMeds = medicines.map((m) => {
    // Build dates from local calendar fields (not toISOString(), which
    // converts to UTC first and can shift "today" to the wrong day and
    // quietly drop the last day of the reminder duration - see localDateStr
    // in app.js for details).
    const start = localDateStr(today);
    const endDate = new Date(today.getFullYear(), today.getMonth(), today.getDate() + (m.duration_days - 1));
    const end = localDateStr(endDate);
    return {
      medicine_name: m.medicine_name.trim(),
      dosage: m.dosage, food_instruction: m.food_instruction, frequency: m.frequency,
      morning: m.morning, afternoon: m.afternoon, night: m.night,
      morning_time: m.morning_time, afternoon_time: m.afternoon_time, night_time: m.night_time,
      start_date: start, end_date: end, needs_verification: m.needs_verification,
    };
  });

  const btn = document.getElementById("confirm-btn");
  btn.disabled = true;
  btn.textContent = "Creating reminders…";
  try {
    const res = await API.post("/api/medicines/confirm", {
      medicines: payloadMeds,
      notification_method: methods.join(","),
    });
    toast(`${res.reminders_created} reminder(s) created.`, "success");
    window.location.href = "/dashboard.html";
  } catch (err) {
    toast(err.message, "error");
    btn.disabled = false;
    btn.textContent = "Confirm & Create Reminder";
  }
});
