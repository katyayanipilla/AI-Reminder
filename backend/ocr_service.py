"""
ocr_service.py
Extracts medicine information from an uploaded prescription image using
Tesseract OCR (via pytesseract), then parses the raw text with regex
heuristics into structured fields. Anything the parser is not confident
about is flagged with needs_verification = True so the UI can highlight it.

If Tesseract is not installed on the machine, we fall back to a demo
extraction so the app is still fully demonstrable (Demo Mode / college
expo use case called out in the spec).

Parsing strategy (see extract_from_text / _parse_line):
  Real prescriptions vary a lot in formatting, and OCR text is noisy. The
  old version of this parser only kept a line if a single strict regex
  matched a name *and* a recognisable dose unit (mg/ml/tablet/...) on that
  exact line - anything written differently (a "Tab." / "Cap." / numbered
  prefix, a bare number as dosage, a "1-0-1" style timing code instead of
  words, or a missing unit) was silently skipped, so prescriptions with
  several medicines often only produced one. This version instead treats
  every plausible medicine line as a candidate, strips common prefixes,
  and falls back gracefully field-by-field - a line only gets dropped if it
  clearly isn't a medicine line at all (patient/doctor/date/address/etc
  header text). Anything the parser had to guess at is flagged with
  needs_verification so the user can double check it, rather than the
  medicine disappearing entirely.
"""
import os
import re
import logging
from difflib import SequenceMatcher

logger = logging.getLogger("ocr_service")

# --- frequency text -> (label, (morning, afternoon, night), uncertain) ------
# Longer/more specific keys are checked first (see _parse_frequency) so e.g.
# "twice a day" doesn't get short-circuited by a bare "1" match.
FREQ_MAP = {
    "once a day": ("Once a day", (False, False, True)),
    "twice a day": ("Twice a day", (True, False, True)),
    "thrice a day": ("3 times a day", (True, True, True)),
    "3 times a day": ("3 times a day", (True, True, True)),
    "4 times a day": ("4 times a day", (True, True, True)),
    "two times a day": ("Twice a day", (True, False, True)),
    "bedtime": ("Once a day (night)", (False, False, True)),
    "qid": ("4 times a day", (True, True, True)),
    "tds": ("3 times a day", (True, True, True)),
    "bd": ("Twice a day", (True, False, True)),
    "od": ("Once a day", (False, False, True)),
    "hs": ("Once a day (night)", (False, False, True)),
    "sos": ("As needed", (False, False, True)),
    "once": ("Once a day", (False, False, True)),
    "twice": ("Twice a day", (True, False, True)),
    "thrice": ("3 times a day", (True, True, True)),
    "3": ("3 times a day", (True, True, True)),
    "2": ("Twice a day", (True, False, True)),
    "1": ("Once a day", (False, False, True)),
}

# Dose amount + unit, e.g. "500 mg", "5ml", "1 tablet", "2 tabs", "10 drops".
DOSE_RE = (
    r"\d+(?:\.\d+)?\s?"
    r"(?:mg|mcg|ug|ml|g|gm|iu|units?|tabs?|tablets?|caps?|capsules?|drops?|puffs?|tsp|tbsp|sachets?)"
)

# Full "name + dose" line, e.g. "Paracetamol 500mg twice a day for 5 days".
# A name is 1-4 words, each starting with a letter (digits allowed inside a
# word so "Vitamin B12" / "Calcium D3" / "Omega-3" are not lost).
_NAME = r"[A-Za-z][A-Za-z0-9\-]*(?:\s+[A-Za-z][A-Za-z0-9\-]*){0,3}?"

MED_LINE_RE = re.compile(
    r"(?P<name>" + _NAME + r"(?:\s+\d{1,2}(?=\s+\d))?)\s+"
    r"(?P<dose>" + DOSE_RE + r")\b"
    r"(?:.*?(?P<freq>\d\s*times?\s*a\s*day|once\s*a\s*day|twice\s*a\s*day|"
    r"thrice\s*a\s*day|od|bd|tds|qid|hs|sos))?"
    r"(?:.*?(?P<duration>\d+\s*days?))?",
    re.IGNORECASE,
)

# Fallback: name + a bare number with no recognisable unit, e.g. "Azithromycin 500".
NAME_BARE_NUM_RE = re.compile(r"^(?P<name>" + _NAME + r")\s+(?P<dose>\d+(?:\.\d+)?)\b")

# Last resort: just the leading name portion of a line, up to the first digit
# group or end of line (covers lines with no dose information at all).
NAME_ONLY_RE = re.compile(r"^(?P<name>" + _NAME + r")(?=\s+\d|\s*$|\s+(?:od|bd|tds|qid|hs|sos|once|twice|thrice|after|before|with|for|x)\b)", re.IGNORECASE)

# Standalone frequency lookup, used whenever the main name+dose regex
# didn't fire (e.g. a bare-number or name-only fallback still deserves a
# chance to pick up an "OD"/"BD"/"TDS" sitting later in the same line).
FREQ_TOKEN_RE = re.compile(
    r"\b(\d\s*times?\s*a\s*day|once\s*a\s*day|twice\s*a\s*day|thrice\s*a\s*day|"
    r"od|bd|tds|qid|hs|sos)\b",
    re.IGNORECASE,
)

# Morning-afternoon-night timing code, e.g. "1-0-1", "1-1-1", "0-0-1".
# Extremely common on Indian prescriptions and far more reliable than
# guessing from free text when present, so it takes priority when found.
CODE_RE = re.compile(r"\b(\d)\s*[-+]\s*(\d)\s*[-+]\s*(\d)\b")

FOOD_RE = re.compile(r"(after food|before food|with food|empty stomach)", re.IGNORECASE)

DURATION_RE = re.compile(r"(\d+)\s*days?\b", re.IGNORECASE)
DURATION_WEEKS_RE = re.compile(r"(\d+)\s*(?:weeks?|wks?)\b", re.IGNORECASE)
DURATION_MONTHS_RE = re.compile(r"(\d+)\s*months?\b", re.IGNORECASE)

# Words that describe *when* to take a medicine, for prescriptions written
# as "morning and night" instead of 1-0-1 / BD.
SLOT_WORDS = {
    "morning": 0, "am": 0, "breakfast": 0,
    "afternoon": 1, "noon": 1, "lunch": 1,
    "night": 2, "bedtime": 2, "evening": 2, "dinner": 2,
}
DURATION_SHORT_RE = re.compile(r"(?:x|for)\s*(\d+)\s*d\b", re.IGNORECASE)

# Strip common leading bullets/numbering/drug-form prefixes before parsing.
PREFIX_RE = re.compile(
    r"^(?:\d{1,2}[\.\)]\s*|[-•*]\s*|"
    r"tab(?:let)?s?\.?\s+|cap(?:sule)?s?\.?\s+|syp\.?\s+|susp\.?\s+|inj(?:ection)?\.?\s+|"
    r"oint(?:ment)?\.?\s+|drops?\.?\s+)",
    re.IGNORECASE,
)

# Lines that are clearly prescription metadata, not a medicine - skipped
# outright so they don't get mistaken for a drug name.
HEADER_SKIP_RE = re.compile(
    r"^(patient|name\s*:|age\b|sex\b|gender\b|date\s*:|address|diagnosis|dr\.?\s|doctor|"
    r"hospital|clinic|signature|reg(?:istration)?\.?\s*no|contact|phone|mobile|"
    r"follow[- ]?up|next\s*visit|weight\b|height\b|\bbp\b|blood\s*pressure|temp\b|pulse\b|"
    r"chief\s*complaint|vitals|\bopd\b|ip\s*no|uhid|prescription\b|department|consultant|"
    r"referred|advice\s*:|investigation|^rx\s*$)",
    re.IGNORECASE,
)

# Clinic/hospital letterhead text often doesn't start with a give-away word
# (e.g. "City Care Clinic", "Sunrise Hospital Pvt Ltd") - checked anywhere
# in the line rather than only at the start.
LETTERHEAD_RE = re.compile(
    r"\b(clinic|hospital|nursing home|healthcare|medical center|medical centre|"
    r"mbbs|md\b|mmc\b|pvt\.?\s*ltd|diagnostics|pathology|laboratory)\b",
    re.IGNORECASE,
)

NOISE_WORDS = {"rx", "patient", "date", "dr", "age", "sex"}



# Leading verbs that are part of the sentence, not the medicine name
# ("Apply Betnovate cream twice a day").
LEADING_VERB_RE = re.compile(r"^(?:take|apply|use|put|instil+|continue|give)\s+", re.IGNORECASE)
# Lines that start with these are advice, not a medicine.
ADVICE_WORDS = {
    "drink", "avoid", "rest", "diet", "review", "advice", "note", "repeat", "follow",
    "return", "kindly", "please", "plenty", "hydration", "steam", "gargle", "warm",
    "consult", "test", "tests", "report", "reports", "bed", "exercise", "signature",
}
# Words that can appear on a *continuation* line ("1-0-1 x 5 days",
# "after food for 5 days") but are not a medicine name.
KNOWN_WORDS = {
    "days", "day", "times", "time", "tablet", "tablets", "capsule", "capsules", "after",
    "before", "food", "daily", "morning", "night", "afternoon", "evening", "with", "water",
    "stomach", "empty", "once", "twice", "thrice", "weeks", "week", "months", "month",
    "drops", "drop", "sachet", "sachets", "meals", "meal", "breakfast", "lunch", "dinner",
    "bedtime", "continue", "then", "daily", "each", "every",
}
CONTINUATION_START = {
    "once", "twice", "thrice", "od", "bd", "tds", "qid", "hs", "sos", "x", "for", "after",
    "before", "with", "empty", "morning", "afternoon", "night", "evening", "daily", "every",
}


def _is_continuation(line):
    """True for a wrapped line that only carries schedule info for the medicine
    above it ("1-0-1 x 5 days", "after food"), so it can be merged into that
    medicine instead of being dropped or mistaken for a new one."""
    words = re.findall(r"[A-Za-z]+", line.lower())
    unknown = [w for w in words if len(w) >= 4 and w not in KNOWN_WORDS]
    if unknown:
        return False
    if line[0].isdigit():
        return True
    return bool(words) and words[0] in CONTINUATION_START


def _duration_days(text):
    m = DURATION_RE.search(text) or DURATION_SHORT_RE.search(text)
    if m:
        return int(m.group(1))
    m = DURATION_WEEKS_RE.search(text)
    if m:
        return int(m.group(1)) * 7
    m = DURATION_MONTHS_RE.search(text)
    if m:
        return int(m.group(1)) * 30
    return None


def _slots_from_words(text):
    """(morning, afternoon, night) from words like 'morning and night'; None if absent."""
    found = set()
    for w in re.findall(r"[a-z]+", text.lower()):
        if w in SLOT_WORDS:
            found.add(SLOT_WORDS[w])
    if not found:
        return None
    return tuple(i in found for i in range(3))


def _clean_line(raw_line):
    """Strip OCR debris, bullets/numbering and drug-form prefixes from a line."""
    line = re.sub(r"^[^A-Za-z0-9]+", "", raw_line).strip()
    while True:
        stripped = PREFIX_RE.sub("", line, count=1).strip(" -:|")
        if stripped == line:
            break
        line = stripped
    # A lone stray letter before the name ("e Paracetamol") is OCR noise.
    line = re.sub(r"^[A-Za-z]\s+(?=[A-Za-z]{3,})", "", line)
    return line


def _configure_tesseract_path():
    """On Windows, Tesseract is usually installed but not on PATH. Use
    TESSERACT_CMD from .env, or the default install locations."""
    import pytesseract
    candidates = [os.environ.get("TESSERACT_CMD", "").strip(),
                  r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]
    for c in candidates:
        if c and os.path.isfile(c):
            pytesseract.pytesseract.tesseract_cmd = c
            return


def _tesseract_available():
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


def _load_images(path):
    """Open the upload as a list of PIL images (one per page for a PDF)."""
    from PIL import Image

    if path.lower().endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
            pages = []
            with fitz.open(path) as doc:
                for page in doc:
                    pix = page.get_pixmap(dpi=300)
                    pages.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            return pages
        except ImportError:
            pass
        try:
            from pdf2image import convert_from_path  # needs poppler installed
            return convert_from_path(path, dpi=300)
        except ImportError:
            raise RuntimeError("PDF prescriptions need PyMuPDF: pip install PyMuPDF")
    return [Image.open(path)]


def _otsu_threshold(gray):
    hist = gray.histogram()
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    sum_b = w_b = 0
    best, threshold = 0.0, 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between > best:
            best, threshold = between, t
    return threshold


def _prepared_variants(img):
    """Two cleaned-up versions of the page: high-contrast grayscale, and a
    black/white (Otsu) version that helps on shadowed phone photos."""
    from PIL import ImageOps, ImageFilter

    img = ImageOps.exif_transpose(img).convert("L")
    img = ImageOps.autocontrast(img)
    # Tesseract struggles with small text; upscale modest-resolution photos.
    if img.width and img.width < 2000:
        scale = 2000 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    gray = img.filter(ImageFilter.SHARPEN)
    t = _otsu_threshold(gray)
    bw = gray.point(lambda px: 255 if px > t else 0, mode="L")
    return [gray, bw]


# Several passes with different layout modes + preprocessing, results merged.
# One pass in one layout mode drops lines on many prescriptions (tables,
# handwriting-style spacing, shadows); the union of passes catches them.
#   psm 6  = uniform block of text, line by line (best for lists)
#   psm 4  = single column of variable-size text
#   psm 11 = sparse text, finds text anywhere on the page
OCR_PASSES = [(0, "--oem 3 --psm 6"), (0, "--oem 3 --psm 4"),
              (1, "--oem 3 --psm 6"), (0, "--oem 3 --psm 11")]


def _run_tesseract_passes(image_path):
    """Return the raw OCR text of every pass, first pass first."""
    import pytesseract

    texts = []
    for page in _load_images(image_path):
        variants = _prepared_variants(page)
        for idx, (variant_no, config) in enumerate(OCR_PASSES):
            try:
                text = pytesseract.image_to_string(variants[variant_no], config=config)
            except Exception:  # noqa: BLE001 - keep whatever the other passes found
                logger.exception("OCR pass %s failed", config)
                continue
            if idx >= len(texts):
                texts.append(text)
            else:
                texts[idx] += "\n" + text  # multi-page PDF: same pass, next page
    return texts


def _label_for_slots(slots):
    count = sum(1 for s in slots if s)
    return {0: "As needed", 1: "Once a day", 2: "Twice a day", 3: "3 times a day"}.get(
        count, "As directed"
    )


def _parse_frequency(freq_text):
    if not freq_text:
        return None, (False, False, True), True  # default: once at night, flag for review
    key = re.sub(r"\s+", " ", freq_text.strip().lower())
    for token in sorted(FREQ_MAP, key=len, reverse=True):
        if token in key:
            label, slots = FREQ_MAP[token]
            return label, slots, False
    return freq_text, (False, False, True), True


def _default_times(slots):
    morning, afternoon, night = slots
    return {
        "morning": morning, "afternoon": afternoon, "night": night,
        "morning_time": "08:00", "afternoon_time": "14:00", "night_time": "20:00",
    }


def _duration_from(text, fallback_days):
    days = _duration_days(text)
    return f"{days or fallback_days} Days"


def _parse_line(line, default_duration_days):
    """Turn one cleaned prescription line into a structured medicine dict,
    or None if the line doesn't look like a medicine at all."""
    line = LEADING_VERB_RE.sub("", line).strip()
    if len(line) < 3:
        return None
    first_word = re.split(r"\W+", line.lower(), maxsplit=1)[0]
    if first_word in ADVICE_WORDS:
        return None

    code_m = CODE_RE.search(line)
    m = MED_LINE_RE.search(line)

    dose_uncertain = False
    if m:
        name = m.group("name").strip(" -:").title()
        dose = (m.group("dose") or "").upper()
        freq_text = m.group("freq")
    else:
        bare_m = NAME_BARE_NUM_RE.match(line)
        if bare_m:
            name = bare_m.group("name").strip(" -:").title()
            dose = bare_m.group("dose")  # no unit recognised - flagged below
            dose_uncertain = True
        else:
            name_m = NAME_ONLY_RE.match(line)
            if not name_m:
                return None
            name = name_m.group("name").strip(" -:").title()
            dose = ""
            dose_uncertain = True
        # The name+dose regex didn't fire, but an OD/BD/TDS-style token may
        # still be sitting later in the line - look for it independently
        # rather than giving up on frequency entirely.
        freq_m = FREQ_TOKEN_RE.search(line)
        freq_text = freq_m.group(1) if freq_m else None

    if len(name) < 3 or name.lower() in NOISE_WORDS or name.split()[0].lower() in ADVICE_WORDS:
        return None

    word_slots = _slots_from_words(line)
    if code_m and any(g != "0" for g in code_m.groups()):
        slots = tuple(g != "0" for g in code_m.groups())
        freq_label, freq_uncertain = _label_for_slots(slots), False
    elif not freq_text and word_slots:
        slots = word_slots
        freq_label, freq_uncertain = _label_for_slots(slots), False
    else:
        freq_label, slots, freq_uncertain = _parse_frequency(freq_text)

    food_m = FOOD_RE.search(line)
    return {
        "medicine_name": name,
        "dosage": dose,
        "frequency": freq_label or "Once a day",
        "food_instruction": food_m.group(1).title() if food_m else None,  # else filled from whole prescription
        "duration": _duration_from(line, default_duration_days),
        **_default_times(slots),
        "needs_verification": bool(freq_uncertain or dose_uncertain or not dose),
    }


def _logical_lines(raw_text):
    """Clean OCR lines and glue wrapped schedule lines onto the medicine
    above them ("Tab. Augmentin 625" + "1-0-1 x 5 days")."""
    logical = []
    previous_open = False
    for raw_line in raw_text.splitlines():
        if not raw_line.strip():
            continue
        line = _clean_line(raw_line.strip())
        if len(line) < 3:
            continue
        if HEADER_SKIP_RE.search(line) or LETTERHEAD_RE.search(line):
            previous_open = False  # header text must not be glued onto a medicine
            continue
        if not re.search(r"[A-Za-z]{2,}", line) and not CODE_RE.search(line):
            continue  # no real word here - can't be a medicine line
        if previous_open and _is_continuation(line):
            logical[-1] += " " + line
            continue
        if _is_continuation(line):
            continue  # schedule text with no medicine to attach to
        logical.append(line)
        previous_open = True
    return logical


def extract_from_text(raw_text):
    """Parse OCR raw text into a list of structured medicine dicts.
    Every line that plausibly names a medicine produces an entry (flagged
    needs_verification if any field had to be guessed) instead of being
    silently dropped when it doesn't match one exact format."""
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    full_text = " ".join(lines)

    food_match = FOOD_RE.search(full_text)
    food_instruction = food_match.group(1).title() if food_match else None
    default_duration_days = _duration_days(full_text) or 5

    medicines = []
    for line in _logical_lines(raw_text):
        entry = _parse_line(line, default_duration_days)
        if not entry:
            continue
        if _find_similar(medicines, entry["medicine_name"]) is not None:
            continue  # same medicine OCR'd twice - keep first
        entry["food_instruction"] = entry["food_instruction"] or food_instruction or "After Food"
        medicines.append(entry)
    return medicines


def _norm_name(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _find_similar(medicines, name):
    """Index of an entry whose name is (nearly) the same - OCR passes spell
    the same drug slightly differently ("Amoxicilin" / "Amoxicillin")."""
    n = _norm_name(name)
    for i, existing in enumerate(medicines):
        e = _norm_name(existing["medicine_name"])
        if n == e or (len(n) >= 5 and len(e) >= 5 and (n in e or e in n)):
            return i
        if SequenceMatcher(None, n, e).ratio() >= 0.85:
            return i
    return None


def _quality(entry):
    return (not entry["needs_verification"]) * 2 + bool(entry["dosage"])


def merge_passes(pass_texts):
    """Union of the medicines found by every OCR pass.
    Pass 1 is trusted for everything it found. Later passes add medicines the
    first one missed - but only when they carry a dose, so stray words that a
    looser layout mode invents don't turn into fake medicines. When two
    passes found the same medicine, the more complete reading wins."""
    merged = []
    for idx, text in enumerate(pass_texts):
        for entry in extract_from_text(text):
            i = _find_similar(merged, entry["medicine_name"])
            if i is None:
                if idx == 0 or entry["dosage"]:
                    merged.append(entry)
            elif _quality(entry) > _quality(merged[i]):
                merged[i] = entry
    return merged


def _demo_fallback():
    """Used when Tesseract isn't installed, or OCR found nothing usable."""
    return [
        {
            "medicine_name": "Paracetamol", "dosage": "500 MG", "frequency": "3 times a day",
            "food_instruction": "After Food", "duration": "5 Days",
            "morning": True, "afternoon": True, "night": True,
            "morning_time": "08:00", "afternoon_time": "14:00", "night_time": "20:00",
            "needs_verification": True,
        },
        {
            "medicine_name": "Amoxicillin", "dosage": "250 MG", "frequency": "Twice a day",
            "food_instruction": "After Food", "duration": "5 Days",
            "morning": True, "afternoon": False, "night": True,
            "morning_time": "08:00", "afternoon_time": "14:00", "night_time": "20:00",
            "needs_verification": True,
        },
    ]


def process_prescription(image_path):
    """
    Main entry point. Returns:
        {
          "medicines": [ {...}, ... ],
          "raw_text": "...",
          "engine": "tesseract" | "tesseract-no-match" | "demo-fallback",
        }
    """
    if not _tesseract_available():
        msg = ("OCR is not installed: run 'pip install pytesseract Pillow' in the same "
               "Python environment that runs app.py, then restart.")
        logger.error(msg)
        if os.environ.get("OCR_DEMO_MODE") == "1":  # opt-in only; never fake a real prescription
            return {"medicines": _demo_fallback(), "raw_text": "", "engine": "demo-fallback"}
        return {"medicines": [], "raw_text": "", "engine": "unavailable", "error": msg}

    _configure_tesseract_path()
    try:
        pass_texts = _run_tesseract_passes(image_path)
    except Exception as exc:  # noqa: BLE001 - OCR engine failures shouldn't crash the app
        logger.exception("Tesseract OCR failed: %s", exc)
        msg = str(exc)
        if "not installed" in msg.lower() or "not in your path" in msg.lower():
            msg = ("The Tesseract program is not installed. Install it (Windows: "
                   "github.com/UB-Mannheim/tesseract/wiki), then set TESSERACT_CMD in backend/.env "
                   "if it is not in C:\\Program Files\\Tesseract-OCR.")
        return {"medicines": [], "raw_text": "", "engine": "tesseract-error", "error": msg}

    raw_text = "\n".join(t for t in pass_texts if t.strip())
    logger.debug("OCR raw text (pass 1):\n%s", pass_texts[0] if pass_texts else "")
    medicines = merge_passes(pass_texts)
    logger.info("OCR found %d medicine(s): %s", len(medicines), [m["medicine_name"] for m in medicines])

    if not medicines:
        # Don't invent medicines for a real prescription - the user can add
        # them manually on the verification screen.
        return {"medicines": [], "raw_text": raw_text, "engine": "tesseract-no-match"}
    return {"medicines": medicines, "raw_text": raw_text, "engine": "tesseract"}
