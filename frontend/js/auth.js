/* auth.js — handles the register.html and login.html forms. */

function showFormAlert(message, type = "error") {
  const el = document.getElementById("form-alert");
  if (!el) return;
  el.innerHTML = `<div class="alert alert-${type}">${message}</div>`;
}

const registerForm = document.getElementById("register-form");
if (registerForm) {
  registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prefs = ["pref-telegram", "pref-sms", "pref-email", "pref-call", "pref-browser"]
      .filter((id) => document.getElementById(id).checked)
      .map((id) => document.getElementById(id).value);

    if (prefs.length === 0) {
      showFormAlert("Please choose at least one notification method.");
      return;
    }

    const payload = {
      name: document.getElementById("name").value.trim(),
      phone: document.getElementById("phone").value.trim(),
      email: document.getElementById("email").value.trim(),
      password: document.getElementById("password").value,
      notification_preference: prefs.join(","),
      telegram_chat_id: document.getElementById("telegram_chat_id").value.trim() || null,
      emergency_contact_name: document.getElementById("em_name").value.trim() || null,
      emergency_contact_phone: document.getElementById("em_phone").value.trim() || null,
    };

    try {
      await API.post("/api/register", payload);
      window.location.href = "/upload.html";
    } catch (err) {
      showFormAlert(err.message);
    }
  });
}

const loginForm = document.getElementById("login-form");
if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      identifier: document.getElementById("identifier").value.trim(),
      password: document.getElementById("password").value,
    };
    try {
      await API.post("/api/login", payload);
      window.location.href = "/dashboard.html";
    } catch (err) {
      showFormAlert(err.message);
    }
  });
}
