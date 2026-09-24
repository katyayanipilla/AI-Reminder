# AI Medicine Reminder

## Fixes in this build

- **Reminders now actually honor the time you set and run for the full
  duration.** The upload/confirm screen was computing "today" and the
  duration's end date with `Date.toISOString()`, which converts to UTC
  first — for users ahead of UTC (e.g. India) this silently shifted the
  start date and dropped the last day of the course. Dates are now built
  from local calendar fields instead (`localDateStr()` in `app.js`).
- **Editing a medicine's time/days/date range now reschedules it.**
  Previously the edit screen updated the medicine record but left the
  already-generated reminder rows untouched, so the old time kept firing.
  Saving an edit now deletes the not-yet-sent future reminders and
  regenerates them from the medicine's current settings
  (`reminder_service.regenerate_future_reminders`).
- **Disabling a medicine now actually stops its reminders.** The due-
  reminders query didn't check the medicine's `active` flag, so a
  "Disabled" medicine kept notifying until its rows were separately
  cleaned up.
- **Browser notifications now poll on every page, not just
  Dashboard/Reminders**, so a reminder isn't missed just because you're on
  History/Settings/etc. when it fires.
- **OCR now extracts every medicine line instead of only the first one
  that matched a strict format.** The parser previously required a name
  and a recognized dose unit (mg/ml/tablet/...) on the same line, so
  numbered lists, `Tab./Cap./Inj.` prefixes, bare-number dosages, and
  `1-0-1`-style timing codes (very common on Indian prescriptions) caused
  a medicine to be silently dropped. It's now line-by-line with graceful
  fallbacks, flags anything it had to guess with `needs_verification`
  instead of dropping it, and applies basic image preprocessing
  (grayscale, autocontrast, upscaling, `--psm 6`) to improve Tesseract's
  accuracy on prescription photos.


A full-stack medicine reminder web app: upload a prescription, verify the
OCR-extracted medicine details, and get reminded by Telegram, SMS, Email, an
automated phone call, and/or your browser — with follow-ups and missed-dose
tracking, all driven by a background scheduler so it works even when no
browser tab is open.

> ⚠️ **Medical safety note:** this app only organizes and reminds you about
> medicines already prescribed by a doctor. It does not diagnose conditions,
> change dosages, recommend stopping medication, or replace professional
> medical advice. Always verify extracted details against your original
> prescription.

## Architecture

```
Registration → Prescription Upload → OCR Processing → Medicine Information
→ User Verification → Create Reminder → SQLite Database → APScheduler
→ Reminder Time Reached → Notification Service (Telegram / SMS / Email / Call / Browser)
→ Taken / Not Taken → History → Dashboard
```

- **Backend:** Flask + SQLite, with APScheduler running inside the Flask
  process to check due reminders every 20 seconds, independent of the
  frontend.
- **OCR:** Tesseract via `pytesseract`, with a regex-based field extractor.
  If Tesseract isn't installed, the app automatically falls back to demo
  data so you can still fully demo the flow.
- **Notifications:** each channel (Telegram, SMS, Email, automated call, browser)
  is its own module in `backend/`. Every channel is optional — the app
  never crashes if a provider isn't configured, and the dashboard/settings
  page shows which ones are live.

## Project structure

```
AI_Medicine_Reminder/
├── backend/            Flask app, database, services, scheduler
├── frontend/            HTML/CSS/JS pages
├── uploads/              saved prescription images
├── .env.example
└── README.md
```

## Setup

### 1. Install Python dependencies

```bash
cd AI_Medicine_Reminder/backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

The core app (registration, upload, reminders, browser notifications,
dashboard, history, statistics) works with just the first block of
`requirements.txt`. The bottom block (`pytesseract`, `Pillow`, `twilio`) is
only needed if you want real OCR / SMS / voice-call functionality — without
them the app runs fine and gracefully falls back to demo data / "not
configured" messages.

To use real OCR, you also need the Tesseract binary itself (not just the
Python wrapper):

```bash
# Debian/Ubuntu
sudo apt-get install tesseract-ocr
# macOS
brew install tesseract
```

### 2. Configure environment variables (all optional)

```bash
cd ..
cp .env.example backend/.env
```

Edit `backend/.env` and fill in whichever credentials you want to enable
(Telegram bot token, Twilio SMS, Twilio Voice, SMTP email). Leave any of them blank and
that channel simply reports as "Not Configured" in the app — nothing
breaks.

### 3. Run the app

```bash
cd backend
python app.py
```

Open your browser at:

```
http://127.0.0.1:5000
```

### 4. (Optional) Telegram setup

1. Create a bot via [@BotFather](https://t.me/BotFather) to get a
   `TELEGRAM_BOT_TOKEN`.
2. Each user finds their own numeric chat ID (e.g. via
   [@userinfobot](https://t.me/userinfobot)) and pastes it into
   Registration or Settings.
3. If you want Taken/Not Taken buttons inside Telegram itself to work, set
   a public webhook once the app is deployed somewhere reachable:
   `POST https://api.telegram.org/bot<token>/setWebhook?url=<your-public-url>/telegram/webhook`

### 5. (Optional) SMS / Automated Call via Twilio

Create a free trial account at [twilio.com](https://www.twilio.com), grab
your Account SID, Auth Token, and phone numbers, and put them in
`backend/.env`. Automated calls additionally need `PUBLIC_BASE_URL` — a URL
Twilio's servers can reach (e.g. an `ngrok` tunnel to your localhost) so it
can fetch the call script.

### 6. (Optional) Email via SMTP

Works with any SMTP provider — Gmail, Outlook, a college mail server, etc.
Fill in `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY` (`tls` or `ssl`),
`SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM` in `backend/.env`.

For Gmail specifically: use `smtp.gmail.com`, port `587`, `tls`, and — since
Google blocks your normal password for this — generate a 16-character
[App Password](https://myaccount.google.com/apppasswords) and use that as
`SMTP_PASSWORD`.

## Demo Mode

For a quick presentation without a real prescription:

1. Register an account.
2. Go to **Reminders → Demo Mode** and click **Load Sample Patient Data**
   to add sample medicines (Paracetamol, Vitamin Tablet).
3. Use **Test Reminder in 1 / 2 / 5 minutes** to fire a live reminder
   through your selected notification channels, so you can demo the full
   Reminder → Notify → Taken/Not Taken → History flow on the spot.

## Database

SQLite file `backend/database.db` is created automatically on first run,
with four tables: `users`, `medicines`, `reminders`, and `history` (plus an
internal `pending_browser_notifications` queue used for browser push). See
`backend/database.py` for the full schema.


## Email / SMS delivery, follow-ups and OCR (troubleshooting notes)

- **Email / SMS not arriving?** Fill in the `SMTP_*` (Gmail needs a 16-character
  *App Password*, `SMTP_FROM` = your Gmail address) and `TWILIO_*` values in
  `backend/.env`, **restart the server**, then open *Settings -> Send Test
  Notification*. Any failure is shown with the real provider error and is also
  printed in the server console. Twilio trial accounts can only text numbers you
  have verified in the Twilio console. Phone numbers typed without a country
  code get `DEFAULT_COUNTRY_CODE` (default `+91`).
- **Channel choice:** the method(s) ticked on the upload page are stored on each
  reminder and used when it fires (the account-level preference is only the
  fallback).
- **Follow-ups:** if a reminder isn't answered with Taken / Not Taken within the
  follow-up time (default **5 minutes**, changeable in Settings), it is sent
  again, and keeps repeating every interval until you answer (max
  `MAX_FOLLOWUPS`, default 6, then the dose is marked *Missed*). Every day and
  time slot up to the end date gets its own reminder. Email and SMS include a
  Taken / Not Taken link; set `PUBLIC_BASE_URL` so it opens on your phone.
- **OCR:** each prescription is read in several passes (different layout modes
  and image clean-ups) and the results are merged, wrapped schedule lines are
  attached to the medicine above them, and PDFs are supported (`PyMuPDF`).
  Always verify the list before confirming.
