# Project Brief: Invoice Fraud Checks for Accounts-Payable Teams (Hong Kong focus)

> Read this whole file before writing any code. It is the source of truth for scope,
> architecture, and rules. If something here conflicts with a request in chat, ask.

---

## 1. Context

- **Event:** iFX Hack Hong Kong 2026 (one day, at HKU). Theme: "Build the Future of Finance with AI."
- **Team:** small team. One person owns the frontend/UI; backend is basic Python.
  New to AWS.
- **Judging (out of 100):**
  - Does it work? (35%): live, real, no fake features or dead buttons
  - Is it worth building? (35%): real problem, real business case
  - Can you pitch it? (15%): 3 min pitch + 2 min Q&A
  - Is it clever? (15%)
- **Implication:** a small thing that truly works beats a big thing that half-works.
  Every button in the UI must do something real. Anything simulated must be labelled.

---

## 2. The Product (one sentence)

**Before an accounts-payable (AP) clerk pays a supplier invoice, this tool reads the invoice,
checks it against the company's own records and public Hong Kong data, and returns a fraud
risk score with the exact reasons, so fake and duplicate invoices are caught before the money leaves.**

- **User:** the AP team of a small/mid-size company in Hong Kong that pays international suppliers.
- **Problem:** fake invoices, duplicate invoices, and "the supplier changed its bank account"
  scams (business email compromise) look exactly like real invoices. AP clerks process many
  invoices and don't have time to cross-check each one by hand.
- **Why it's fintech:** the output is a payment decision (Approve / Review / Hold payment)
  backed by an auditable risk score.
- **Why not just upload the invoice to a chatbot?** A chatbot can read the invoice, but it
  doesn't have the company's vendor master, invoice history or purchase orders, can't do
  reliable, repeatable scoring, and leaves no audit trail. Pitch line:
  *"A chatbot can read the invoice. It can't read your ledger."*

---

## 3. The Demo Flow (this is what must work live)

1. User **uploads one invoice** (PDF or image), or picks a named sample.
2. AI **extracts the fields** → shown in an editable form with source snippets (human checks).
3. Backend runs **deterministic checks** against synthetic company records
   (vendor master, invoice history, purchase orders) and, if available, the
   **live HK Companies Registry open data**.
4. Backend computes a **risk score 0–100** and an **action** (Approve / Review / Hold payment).
5. UI shows the **verdict, every check (passed and failed) with evidence**, a recommended next
   step, and an **AI-written plain-language summary** of the reasons.
6. User can edit a field and **re-run checks**.

---

## 4. Scope

### MUST (build first, in this order)
1. Invoice upload → AI extraction → editable fields
2. Checks engine (deterministic Python, no AI): duplicates, bank details, vendor identity,
   PO match, arithmetic, approval-threshold gaming
3. Risk score + action + verdict UI + AI summary
4. Synthetic data files loaded from `/data`, plus 6–8 sample invoices (one per fraud pattern)

### SHOULD (only after MUST works end to end)
5. HK Companies Registry check (recently incorporated / recently renamed), live with cached fallback
6. PDF metadata check (edited in an image tool, modified long after creation)
7. Vendor context panel (past invoice amounts chart with this invoice marked)

### COULD (only if everything above is solid)
8. Sanctions screening via OpenSanctions (API not yet verified, check docs first)
9. Session history list (in memory only, no database)

### WON'T (do not build tomorrow)
- User accounts, login, databases, deployment, batch/queue processing, multiple AWS services,
  Scameter integration (no public API; pitch-only), Thai/DBD anything, autonomous agents,
  actually paying or blocking payments.

---

## 5. Architecture

Keep it to **one Python process** serving both API and frontend. No Node build step.

```
project/
├── CLAUDE.md
├── README.md                 # how to run + "AI tools used" + what is real vs mocked
├── requirements.txt
├── .env.example              # AI_PROVIDER, AWS_REGION, ANTHROPIC_API_KEY, model IDs
├── .gitignore                # .env, venv, __pycache__, data/hk_registry_cache/*.csv
├── venv/                     # already created (Python 3.12), not committed
├── app/
│   ├── main.py               # FastAPI app, routes, serves /static
│   ├── extract.py            # document → text/image → AI → structured JSON
│   ├── checks.py             # each fraud check as a small pure function (NO AI)
│   ├── scoring.py            # combine check results → score + action (NO AI)
│   ├── explain.py            # AI summary written AFTER scoring
│   ├── llm.py                # provider wrapper: Bedrock (boto3) OR Anthropic API
│   ├── hk_registry.py        # data.gov.hk Companies Registry weekly CSVs + cache
│   ├── pdf_meta.py           # (should) PDF metadata check
│   └── data_loader.py
├── tests/
│   └── test_checks.py        # one test per check, hand-checked
├── data/
│   ├── vendors.csv
│   ├── invoice_history.csv
│   ├── purchase_orders.csv
│   ├── scoring_rules.json
│   ├── hk_registry_cache/    # downloaded weekly CSVs (fallback when offline)
│   └── sample_invoices/      # 6–8 synthetic invoices (PDF + one image)
└── static/
    └── index.html            # single-page UI (Tailwind CDN + vanilla JS + Chart.js CDN)
```

**Backend:** FastAPI + Uvicorn. `pdfplumber` (or `pypdf`) for PDF text and metadata.
Fuzzy matching with the standard library `difflib` (no extra dependency).
**Frontend:** one `index.html`, Tailwind via CDN, vanilla JS `fetch()`, Chart.js via CDN.
**Fallback UI:** if the HTML frontend is fighting us by midday, switch to Streamlit calling
the same Python functions. The backend logic must not depend on the UI choice.

### AI provider (`llm.py`)
- One function: `call_llm(system: str, user_content) -> str`.
- `AI_PROVIDER=bedrock` → `boto3` `bedrock-runtime` (Converse API). Model ID from env var.
- `AI_PROVIDER=anthropic` → `anthropic` Python SDK. Model from env var.
- **Do not hard-code model IDs.** Check current docs for valid IDs. If unsure, say so.
- If Bedrock access isn't working within ~30 minutes at the venue, switch provider and move on.

### API endpoints
| Method | Path | Does |
|---|---|---|
| POST | `/api/extract` | multipart file → extracted fields JSON (+ file hash, PDF metadata) |
| POST | `/api/check` | fields JSON (+ file hash) → full check result JSON |
| GET | `/api/samples` | list sample invoices with display names |
| GET | `/api/samples/{name}` | return one sample file (UI then sends it to `/api/extract`) |
| GET | `/api/vendors/{vendor_id}/history` | past invoices for the vendor context panel |
| GET | `/api/registry/{br_number}` | HK registry lookup (live, else cached, labelled as such) |

---

## 6. Data Contracts

**The frontend and backend are built in parallel. Agree these shapes first and don't change
them without telling the other person.** The UI can be built against a hard-coded example.

### Extraction output (`/api/extract`)
The AI must return **only JSON** matching this. Every field can be `null` if not found.
Never invent values; missing is better than wrong.

```json
{
  "document_type": "invoice | credit_note | other",
  "vendor_name": "string | null",
  "vendor_br_number": "8-digit HK Business Registration number | null",
  "vendor_address": "string | null",
  "vendor_email": "string | null",
  "vendor_phone": "string | null",
  "invoice_number": "string | null",
  "invoice_date": "YYYY-MM-DD | null",
  "due_date": "YYYY-MM-DD | null",
  "currency": "ISO code e.g. HKD, USD | null",
  "po_reference": "string | null",
  "line_items": [
    { "description": "string", "quantity": "number | null",
      "unit_price": "number | null", "amount": "number | null" }
  ],
  "subtotal": "number | null",
  "tax": "number | null",
  "total": "number | null",
  "bank_name": "string | null",
  "bank_account_name": "string | null",
  "bank_account_number": "string | null",
  "fields_source": { "<field_name>": "short snippet of the document text it came from" }
}
```
- Validate with Pydantic. If parsing fails, retry once, then return an error the UI can show.
- The backend (not the AI) adds `file_sha256` and, for PDFs, `pdf_metadata` alongside the fields.

### Check result output (`/api/check`)
```json
{
  "score": 78,
  "action": "approve | review | hold",
  "summary": "AI-written plain-language summary, generated AFTER scoring",
  "vendor_match": { "vendor_id": "V003", "name": "Acme Trading Ltd", "match_type": "exact | lookalike | none" },
  "checks": [
    {
      "id": "bank_mismatch",
      "name": "Bank details match vendor record",
      "status": "pass | warn | fail | skipped",
      "points": 45,
      "reason": "Account ••••4471 differs from ••••9920 on file",
      "evidence": { "invoice_value": "...", "record_value": "...", "record_date": "..." },
      "next_step": "Call the vendor on the phone number in your records (not the one on this invoice) to confirm."
    }
  ],
  "data_sources": [ { "name": "HK Companies Registry (data.gov.hk)", "status": "live | cached | unavailable", "as_of": "YYYY-MM-DD" } ],
  "assumptions": ["list every placeholder threshold or weight used"]
}
```
- **Every check appears in `checks`, including passed and skipped ones.** A list of green
  checks is part of the proof that the tool actually checked something.
- `skipped` = the check couldn't run (e.g. no PO reference extracted, registry unavailable).
  Skipped checks add 0 points and say why.
- `next_step` text comes from `scoring_rules.json`, not from the AI.

---

## 7. Checks Engine (`checks.py` + `scoring.py`: deterministic, NO AI)

The AI extracts and explains. **Python decides the score.**

Each check is a small pure function: `(fields, records) -> CheckResult`. All thresholds,
weights and next-step texts live in `scoring_rules.json`, not in code.

| id | Check | Fires when (placeholder thresholds) |
|---|---|---|
| `dup_exact` | Exact duplicate | same vendor + same normalised invoice number in history |
| `dup_fuzzy_number` | Tweaked invoice number | normalised numbers differ but similarity ≥ 0.85 (e.g. `INV-1001` vs `INV-1001A`) |
| `dup_amount` | Same amount, same vendor | same vendor + same total within 30 days |
| `dup_file` | Same file sent again | `file_sha256` already seen (history or this session) |
| `bank_mismatch` | Bank details changed | invoice account ≠ vendor master account |
| `bank_shared` | Account used by another vendor | invoice account belongs to a different vendor |
| `vendor_unknown` | Not an approved vendor | no exact or lookalike match in vendor master |
| `vendor_lookalike` | Lookalike vendor | name similarity ≥ 0.85 but not exact, or email domain differs from record |
| `po_missing` | No PO reference | `po_reference` is null |
| `po_not_found` | PO doesn't exist | PO number not in `purchase_orders.csv` |
| `po_vendor_mismatch` | PO belongs to someone else | PO exists but for a different vendor |
| `po_over_amount` | Invoice exceeds PO | total > remaining PO balance (+ small tolerance) |
| `arithmetic` | Totals don't add up | Σ line amounts ≠ subtotal, or subtotal + tax ≠ total (tolerance 0.01) |
| `threshold_gaming` | Just under approval limit | total within 5% below an approval limit (e.g. HKD 50,000) |
| `hk_new_company` | (should) Recently incorporated | BR number registered < 90 days ago in HK registry data |
| `hk_name_change` | (should) Recently renamed | name changed < 90 days ago in HK registry data |
| `pdf_edited` | (should) Edited document | PDF producer is an image editor, or modified long after creation |

**Scoring**
```
score  = min(100, Σ points of checks with status fail or warn)
action = approve  if score < 25
         review   if 25 ≤ score < 60
         hold     if score ≥ 60
```
- Normalise invoice numbers before comparing: uppercase, strip spaces, `-`, `/`, `#`, leading "INV".
- Vendor name matching: lowercase, strip "ltd", "limited", "co", punctuation; then `difflib` ratio.
- Weights are placeholders, chosen so each single serious fraud pattern
  (exact duplicate, bank change) alone lands in Review or Hold. Document the reasoning
  in `scoring_rules.json`.
- Write unit tests for every check with hand-checked inputs, and one test per sample invoice
  asserting the expected action.

---

## 8. Data (`/data`)

**All company data is synthetic. Never present it as real company data.**

- `vendors.csv`: ~10 fictional vendors, mostly HK plus a few international (e.g. Shenzhen,
  Singapore, Germany): vendor_id, name, br_number (8 digits, fake), address, email,
  phone, bank_name, bank_account_number, bank_account_name, bank_verified_date,
  vendor_since, approval_status.
- `invoice_history.csv`: ~150–200 past invoices: invoice_id, vendor_id, invoice_number,
  invoice_date, currency, total, po_reference, paid_date, file_sha256 (some blank).
  Must include the "original" invoices that the duplicate samples copy.
- `purchase_orders.csv`: po_number, vendor_id, po_date, approved_by, currency, approved_amount,
  invoiced_to_date. Mostly HKD.
- `scoring_rules.json`: every weight, threshold, tolerance, approval limit and next-step text,
  each tagged `"source": "placeholder"`.
- `sample_invoices/`: generate with a script (e.g. reportlab), varied layouts, plus one
  phone-photo-style image. Display names describe the pattern:
  1. ✓ Clean invoice (expect Approve)
  2. Duplicate with tweaked number
  3. Bank details changed
  4. Lookalike vendor
  5. No matching PO
  6. Bad arithmetic
  7. Brand-new HK company (uses a BR number that is in the real recent-registrations CSV,
     shown with a fictional vendor name on screen, and only if the HK registry check is built)
  8. Messy photo with a missing field (shows the human-review step)

### HK Companies Registry open data (real, verified 2026-10-04)
- Published on data.gov.hk (CKAN API) under organisation `hk-cr`.
  Dataset: `hk-cr-crdata-list-newly-registered-companies-2526`, "List of Newly Incorporated /
  Registered / Re-domiciled Companies and Companies which have changed Names (2024.12.30 – Current)".
- Discover files via
  `https://data.gov.hk/en-data/api/3/action/package_search?fq=organization:hk-cr`.
  Files look like `https://www.cr.gov.hk/docs/wrpt/RNC063/RNC063F_YYYYMMDD.csv` (weekly).
- CSV: UTF-8 with BOM. Columns: `Seq, Current Corporate Name / Other Corporate Name,
  Current Approved Name for Carrying on Business in H.K., BR Number, Date of Registration,
  Date of Change of name`. Dates are `DD-MM-YYYY`. A company can appear twice
  (English and Chinese name rows, same BR number).
- **Limits (say this honestly):** this is only *recent* registrations and name changes, not
  the full register. "Not found" means "not in recent registrations", never "company doesn't exist".
  Directors/addresses need the paid e-search service; we don't use it.
- Download on startup if online; otherwise read `data/hk_registry_cache/`. The UI must show
  whether data was live or cached, and as of which date.

### Scameter (HK Police): pitch only
- No public API found (web search and app only; banks get access through HKMA).
  Do NOT build or imply an integration. Mention it as a production integration path.

---

## 9. Frontend Design (`static/index.html`)

Goal: looks like a credible fintech product, not a homework assignment. Simple > flashy.

### Layout
```
┌───────────────────────────────────────────────────────────────────┐
│  <Product name>      [Upload invoice]  [Try a sample ▾]           │
├──────────────────────────────┬────────────────────────────────────┤
│  INVOICE PREVIEW             │  VERDICT                           │
│                              │  78 / 100   ● HOLD PAYMENT         │
│                              │  AI summary sentence               │
│                              │  [score breakdown bar]             │
│  EXTRACTED FIELDS (editable) │  CHECKS (all, passed + failed)     │
│  ...                         │  ✗ Bank details mismatch    +45 ▸  │
│  [Re-run checks]             │  ✓ PO matched (PO-2231)      0  ▸  │
│                              │  VENDOR CONTEXT (should)           │
│                              │  RECOMMENDED NEXT STEPS            │
└──────────────────────────────┴────────────────────────────────────┘
```

### Blocks
1. **Verdict:** big score, coloured action badge (Approve green / Review amber / Hold red),
   AI summary sentence, horizontal stacked bar of points per failed check (Chart.js).
2. **Checks list:** every check with ✓ / ⚠ / ✗ / – (skipped), name, points. Click to expand
   evidence, shown side by side with differences highlighted:
   bank account invoice vs record; duplicate vs matched past invoice; PO amount vs invoice;
   lookalike vs real vendor name; recomputed line-item table; registry registration date.
3. **Extracted fields:** editable; ⓘ tooltip with the source snippet; amber if missing,
   red if a check flagged it; **Re-run checks** button re-calls `/api/check`.
4. **Invoice preview:** the uploaded PDF/image (an `<embed>`/`<img>` is enough).
5. **Recommended next steps:** `next_step` text from each failed check.
6. **Vendor context (should):** vendor since, invoice count, typical amount, bank last
   verified; small chart of past invoice amounts with this invoice highlighted.
7. **Data sources:** small badges, e.g. "HK Registry: live (data.gov.hk, as of …)" or "cached".
8. **Footer:** "Demo data: synthetic unless marked. AI extracted · Python scored · Human decides."

### Rules
- **Sample dropdown** uses the descriptive names from section 8, so the demo never depends on finding a file.
- **States:** loading spinners on every async call, readable error messages, no dead buttons.
- **Style:** neutral palette, one accent colour (plus green/amber/red only for status), generous
  spacing, system font stack, amounts right-aligned with thousands separators and currency (HKD etc.).

---

## 10. Rules for Claude Code

1. Work in **small steps**. After each step, tell me how to run/test it, then stop.
2. **Explain** what you wrote in plain language. I must be able to explain every part to judges.
3. **No secrets in code.** Use `.env` (gitignored). Never print keys.
4. **Do not invent APIs, endpoints, or model IDs.** If unsure about a library's current API
   (Bedrock Converse, data.gov.hk, OpenSanctions, etc.), say so and check docs or ask me.
5. **AI never decides the score or the action.** AI extracts fields and writes the summary only.
6. **No fake features.** If something isn't implemented, the button doesn't exist.
   Anything simulated is labelled in the UI.
7. Keep dependencies minimal. Prefer readable code over clever code.
8. Don't add features outside section 4 unless I ask.
9. Run Python via the project venv: `.\venv\Scripts\python.exe` (system Python isn't on PATH).

---

## 11. Build Order and Checkpoints

| # | Step | Done when |
|---|---|---|
| 0 | Env + skeleton (FastAPI serves a hello page) | page loads at localhost |
| 1 | `llm.py` with one provider working | a test prompt returns text |
| 2 | Synthetic data + `checks.py` + `scoring.py` + tests | tests pass with hand-checked expectations |
| 3 | Sample invoices generated + `/api/extract` | JSON matches schema for all samples |
| 4 | `/api/check` | each sample gets its expected action |
| 5 | Frontend: upload → fields → verdict + checks | full flow works in browser |
| 6 | Evidence panels + AI summary + next steps | looks presentable |
| — | **FEATURE FREEZE if it's past mid-afternoon** | |
| 7 | HK registry check (should) | live download works, cached fallback works offline |
| 8 | PDF metadata + vendor context (should) | edited-PDF sample is flagged; chart shows |
| 9 | Demo hardening | full run-through 3× without errors; backup video recorded |

Frontend can start at step 0 in parallel, using a hard-coded copy of the section 6 JSON.

---

## 12. Pitch (3 min) and Q&A Prep

**Structure:** problem (20s) → live demo (~2 min) → business case (30s) → what's next (10s).

- **Hook:** "The most dangerous invoice is the one that looks exactly like a real one."
- **Demo:** clean invoice → Approve; bank details changed → Hold, with evidence; duplicate with
  tweaked number → caught; (if built) brand-new HK company → flagged from live registry data.
- **Be explicit about what's real vs mocked:** company records are synthetic; extraction,
  checks, scoring and the HK registry data are real.
- **What's next:** connect to real accounting systems (Xero, QuickBooks, SAP) for vendor master
  and history; Scameter / bank-account screening via banking partners; learn from AP decisions;
  more registries.

**Likely questions, with honest answers ready:**
- What if the AI extracts the wrong number? → Human reviews every field with the source snippet;
  AI never sets the score; edit and re-run.
- Why not just use ChatGPT? → It doesn't have your vendor master, history or POs, gives
  different answers each time, and leaves no audit trail.
- False positives? → Every flag shows its evidence and points; weights are configurable;
  "Review" is a prompt to check, not an accusation.
- Who pays? → AP teams at SMEs and mid-size companies; per-invoice or subscription.
  (Hypothesis, not yet validated.)
- Doesn't this exist? → Large enterprises have AP automation suites with fraud modules;
  target is smaller companies that don't. (Verify with mentors; don't claim no competitors.)
- Why Hong Kong? → Trade hub with heavy cross-border supplier payments; open registry data
  for new companies. (Get a sourced fraud statistic before using any number in the pitch.)
- Data privacy? → Demo uses synthetic data. If on Bedrock: inputs aren't used to train models
  and stay in-region; production would add access controls. Do NOT claim "fully compliant."

---

## 13. Open Questions (resolve before/at the event)

- [ ] Are pre-written code and AI coding tools allowed? (ask organisers)
- [ ] Are AWS credits / Bedrock access provided?
- [ ] Product name
- [ ] One sourced HK statistic on invoice / business email compromise fraud for the pitch
- [ ] OpenSanctions API terms and endpoints (only if we reach COULD)
- [ ] Confirm data.gov.hk registry download still works on demo day (cache a copy the night before)
