# AI Job Scout — UK visa-sponsor job radar

**In one line:** it visits the official hiring systems of companies that **hold a UK Skilled Worker sponsor licence**, pulls the jobs they're advertising right now, and — once you add your resume — scores every job for fit and tells you what's missing.

> **Why this beats searching the whole web:** every company it looks at is **licensed to sponsor a UK Skilled Worker visa**. You're not filtering thousands of jobs that will never sponsor you.
> (A licence ≠ every role will definitely sponsor — always confirm in the JD or interview.)

> **Not looking for AI jobs?** It ships tuned for AI/ML roles, but it's **industry-agnostic** — change a few keywords and it finds nursing, accounting, marketing, engineering… ([see below](#not-looking-for-ai-jobs-switch-to-your-industry)).

> **You don't need to be technical.** Follow the steps and click along. If any step throws an error, **copy the whole error message**, paste it into any AI assistant (ChatGPT, Claude, Gemini…) and ask "what do I do?" — that's your universal help button.

---

## Two ways to run it

| | **On your own computer** | **Hosted for a group** |
|---|---|---|
| Who it's for | Just you | You + friends, each with their own account |
| Login | None | Login required; optional self-serve signup |
| Data | All local, one user | Per-account and isolated, on your server |
| Setup | Install Python, run one command | Docker Compose |
| Cost | Free | A small cloud VM + your own API keys |

Start with the local install — the hosted setup is the [same app with a few env vars](#host-it-for-a-group-multi-user).

---

# Run it on your own computer

You install once. After that, starting it is one step.

## Windows

### Step 1 — Install Python (once)
1. Open https://www.python.org/downloads/
2. Click the big yellow **Download Python 3.x** button, then run the downloaded file.
3. ⚠️ **The step everyone misses**: at the **bottom** of the installer there's a checkbox **"Add python.exe to PATH"** — **tick it**, then click **Install Now**.
   (Skip it and you'll later see "not recognized as an internal or external command" — just reinstall and tick the box.)
4. Click Close.

### Step 2 — Download this tool (once)
1. On this project's GitHub page: green **Code** button → **Download ZIP**.
2. Find the zip in Downloads, **right-click → Extract All**, extract it to your **Desktop**.
3. You'll get a folder called `AI-Job-Scout`.

### Step 3 — Start it
1. Open the `AI-Job-Scout` folder.
2. Click the **address bar** at the top of the window, clear it, type **`cmd`**, press Enter.
   → A black window (the command line) opens. That's just where you type commands.
3. Paste this and press Enter (takes a minute or two the first time):
   ```
   pip install -r requirements.txt
   ```
4. Then paste this and press Enter:
   ```
   python app.py
   ```
5. When you see `AI Job Scout running: http://127.0.0.1:5050`, it worked.
6. Open your browser at **http://127.0.0.1:5050** 🎉

> **Don't close the black window** — it *is* the server. Leave it open (minimising is fine) while you use the tool.

## macOS

1. **Install Python**: https://www.python.org/downloads/ → download the macOS version → run the `.pkg`.
2. **Download the tool**: GitHub → **Code → Download ZIP** → unzip to your Desktop.
3. **Open Terminal**: in Finder, right-click the `AI-Job-Scout` folder → Services → **New Terminal at Folder**.
4. Run these in order (`pip3`/`python3`, not `pip`/`python`):
   ```
   pip3 install -r requirements.txt
   python3 app.py
   ```
5. Open **http://127.0.0.1:5050**. Leave Terminal open.

## Opening it later (no reinstall)

**Windows: double-click `Start-Job-Scout.bat`** — it starts the server and opens your browser. Leave the black window open; close it to stop.

Manual (macOS, or if the .bat won't run):
1. Open the folder → type `cmd` in the address bar (macOS: right-click → New Terminal at Folder).
2. Run **`python app.py`** (macOS: `python3 app.py`).
3. Open **http://127.0.0.1:5050**.

**To stop it:** close that window.

## Stuck? Find your case

| What you see | What to do |
|---|---|
| `python is not recognized` / `command not found` | You didn't tick **Add to PATH**. Reinstall Python with the box ticked, or restart your computer. On macOS use `python3`. |
| `pip is not recognized` | Same fix. Or use `python -m pip install -r requirements.txt` (macOS: `python3 -m pip …`). |
| `Address already in use` | It's already running in another window. Use that one, or close the extras. |
| Browser says "can't reach / connection refused" | The black window must still be open and say "running". The address must be exactly `http://127.0.0.1:5050`. |
| Uploading a PDF resume fails | Your PDF is probably a **scan (an image)**. Export a text PDF from Word, or paste the text instead (Settings → Paste resume). |
| Anything else | **Copy the whole error**, paste it into ChatGPT / Claude / Gemini, ask how to fix it. Genuinely the fastest route. |

---

# How to use it (in this order)

### 1. Import the company list
- Download the official sponsor list: search gov.uk for **"register of licensed sponsors workers"** and grab the CSV (updated weekly, ~120k companies).
- In the tool: **Toolbox → Import company list → Choose file**, pick that CSV.
  It automatically keeps only the **Skilled Worker** rows and records each company's town.
- Got your own target list instead? The same button takes an **Excel or CSV** of company names — those get tagged **Curated**.
- Re-importing is safe: duplicates are merged, not doubled.

> A set of well-known employers is [built in](#built-in-employers-no-setup-needed), so you can try the tool before importing anything.

### 2. Build the job library
- **Toolbox → Build the job library → Run**. This probes every company for a public hiring system. It takes a few hours the first time — **it's the only slow step, and you only do it once**.
- **You can stop it whenever you want.** Progress is saved continuously, and the next run **picks up where it left off** instead of starting over.
- Afterwards, your everyday button is **Toolbox → Scan new jobs** (a few minutes) — it refreshes jobs from the companies already known to have a hiring system.
- **Toolbox → Find missed companies** is an occasional top-up: it re-checks companies where nothing was found the first time. Also stoppable and resumable.

### 3. Add your resume
- On the resume card, click **Upload resume** (PDF / Word / TXT). It scores **every job** for fit and lists the skills you're missing.
- If a PDF won't parse (scans don't), go to **Settings → Paste resume** and paste the text.

### 4. Review, shortlist, get advice
- Each job row starts with its **match score** (green = strong, amber = medium). After scoring, jobs sort by match by default.
- **Click a job row** to open its details: see exactly which skills you're missing, then generate **resume tips for that job** and **networking outreach drafts** (LinkedIn note / follow-up DM / cold email) — needs an [LLM key](#resume-tips).
- **Save** the ones you like → manage them under **Applications**: move each through *To apply → Applied → Interviewing → Offer/Rejected*, open the posting, find recruiters, look up emails.
  Applying stays manual on purpose — a tailored resume beats any auto-spam tool (which also risks getting your accounts banned).
- **Resume gaps** shows the skills most worth adding across *all* your matched jobs.
- **Toolbox → Export to Excel** to take it all with you.

---

# Host it for a group (multi-user)

The same app runs as a small multi-user site, so friends can each sign up and get **their own private workspace**.

- **Each account is fully isolated**: its own resume, its own scans and matched jobs, its own Applications board and hidden list. Nobody sees anyone else's data.
- **Shared underneath**: the company directory and the "which hiring system does this company use" cache. That's deliberate — it means the slow discovery work is done once for everyone instead of ~120k companies per person.
- **All AI calls run on the host's API key**, so every account has **per-day caps**.

```bash
cp api_keys.example.json data/api_keys.json   # fill in your keys
docker compose up -d --build
```

Multi-user mode switches on automatically when the app is exposed (`HOST=0.0.0.0`, which the Docker image sets) or when you set `APP_MULTIUSER=1`. Put a reverse proxy with HTTPS in front of it.

### Configuration (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `5050` | Bind address. Docker uses `0.0.0.0:8080`. |
| `APP_MULTIUSER` | off | Force multi-user mode (auto-on when `HOST=0.0.0.0`). |
| `APP_USER` / `APP_PASSWORD` | — | Seeds the owner account. The owner is **exempt from the caps**. |
| `REGISTRATION_OPEN` | **off** | Allow public self-serve signup. Off = only existing accounts can log in. |
| `LLM_DAILY_CAP` | `100` | Max AI calls per account per day. |
| `SCAN_DAILY_CAP` | `10` | Max scans per account per day. |
| `WORKABLE_CONC` | `12` | Concurrency for Workable probes — the throughput gate of *Find missed companies*. Raise it if you see no rate-limiting; lower it if you do. |
| `DEEP_WORKERS` | `48` | Worker threads for *Find missed companies*. |
| `DEEP_NICHE` | off | Also probe Recruitee/Personio during *Find missed companies*. Far slower for a very small extra yield — off by default. |

> ⚠️ **`REGISTRATION_OPEN=1` on a public URL means anyone who finds it can create an account and spend against your API key** (within the per-day caps, but there's no cap on how many people sign up). Only turn it on if you're comfortable with that, keep the caps low, and don't publish the URL.

Passwords are stored salted and hashed (pbkdf2) in `data/users.json` — never in plain text.

---

# Not looking for AI jobs? Switch to your industry

At heart this tool "scans company hiring systems for jobs whose title or body matches **your keywords**" — the AI focus is just the default keyword set. Go to **Settings → Job keywords**, replace them, save, and re-scan.

| Industry | Keywords to try |
|---|---|
| Nursing / healthcare | nurse, healthcare assistant, clinical, care worker |
| Accounting / finance | accountant, financial analyst, audit, tax, bookkeeper |
| Marketing / ops | marketing, social media, content, brand, growth |
| Engineering | mechanical engineer, civil engineer, electrical engineer |
| Education | teacher, lecturer, teaching assistant |
| Supply chain | supply chain, logistics, procurement, warehouse |

> Not sure which keywords? Ask any AI assistant: "I'm looking for UK visa-sponsor jobs in the XX industry, suggest a set of keywords."

---

# Platforms it can't scrape — and how to cover them

This tool only reads the **public endpoints of companies' own hiring systems**. These are blind spots you'll search yourself:

| Platform | Why / what to do |
|---|---|
| **LinkedIn** | Scraping is prohibited. Each company card gives you a one-click LinkedIn recruiter search. |
| **Indeed / Glassdoor** | Search them yourself. |
| **Totaljobs / CV-Library / Reed website** | Major UK-native sites worth browsing directly. |
| **In-house systems** (Google, Amazon, Meta, Microsoft, big banks) | No public API to read. Use the Google-search link on the company card. |

Every company card includes one-click **LinkedIn recruiter search / Hunter email lookup / Google job search** links, so you can cover these manually and find contacts along the way. (The tool won't crawl contacts for you — it just hands you the search entry points.)

**Want broader coverage automatically?** (optional, free tiers) Copy `api_keys.example.json` to `data/api_keys.json`, fill in any of these, then use **Toolbox → Add jobs from job boards**:

| Source | Sign-up | What it adds |
|---|---|---|
| **Adzuna** | https://developer.adzuna.com/ | UK-wide aggregation (~1000 calls/month) |
| **Reed** | https://www.reed.co.uk/developers | One of the largest UK-native job sites |
| **Jooble** | https://jooble.org/api/about | Aggregates many UK sites; broad top-up |
| **JSearch (RapidAPI)** | https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch | ⭐ Pulls **Google for Jobs**, which covers **LinkedIn / Indeed / Glassdoor / ZipRecruiter** — exactly the blind spots above. Free tier ~200 calls/month. |

> To dent the LinkedIn/Indeed blind spot, `rapidapi_key` (JSearch) is the one that matters — it's the only source that reaches those aggregators. No free official API connects directly to the full LinkedIn/Indeed feed; Google for Jobs is the practical approximation.
> There's also **Toolbox → Social hiring posts (Hacker News)** for "Who is hiring" threads.

---

# Built-in employers (no setup needed)

A set of well-known employers ships pre-loaded and gets scanned on first launch:

- **AI/ML names** (mostly Greenhouse/Lever/Ashby, auto-detected): Anthropic, OpenAI, Cohere, Hugging Face, DeepMind, Databricks, Palantir, Wayve, Faculty, Quantexa, Synthesia, Stability AI, ElevenLabs, Speechmatics, Graphcore, Monzo, Wise, Revolut, and more.
- **Large enterprises on Workday** (addresses built in): NVIDIA, Salesforce, Adobe, Dell, Mastercard, Capital One, Autodesk, AstraZeneca, Sanofi, and more.

> Workday addresses are **best-effort** presets. If one breaks (the company moved), it's skipped and **no other company is affected**.
>
> ❗ **Google / Amazon / Meta / Microsoft / JPMorgan** and similar run **in-house systems with no public API** — no tool can read those. Use the Google/LinkedIn search links on the company card.

---

# Resume tips

Once your resume is in and scoring has finished, **Resume gaps** aggregates **all matched jobs** and ranks the skills most worth adding — e.g. `research·83 (27)` means it's missing from 83 jobs, 27 of them medium-match (where adding it gains the most). It also mines JD phrasings your skill list might miss.

**Want written suggestions generated in the tool?** Add an LLM key to `data/api_keys.json`:
- **ChatGPT**: `openai_api_key` (default model `gpt-4o`, or the `OPENAI_API_KEY` env var)
- **Claude**: `anthropic_api_key`
- Filled both? Pick with `llm_provider` (`openai` / `anthropic`). Unset defaults to ChatGPT.

You'll get an actionable checklist: what to add first, where in the resume and how to word it, which experiences to rewrite. **It won't invent experience you don't have.**

**Tailoring for one specific job:** click a job row to open its details → **Generate resume tips for this job**. It combines that JD's text + your gaps + your full resume into advice for that single role (terms to add, experiences to rewrite, a cover-letter opener). Without an LLM key, the **Copy prompt** button still hands you the full prompt to paste into ChatGPT/Claude yourself.

---

# Privacy

**Running locally (the default):** everything — the company list, your resume, the jobs — stays **on your own computer** in the `data/` folder. Nothing is uploaded anywhere. `data/` is git-ignored and never syncs to GitHub.

**Running hosted (multi-user):** each account's data lives on **your server** under `data/users/<account>/`, isolated per account. Still no third party — but as the host, that server is your responsibility.

---

<details>
<summary><b>Advanced: how the match score works, coverage, and data files</b></summary>

### The match score

Each job is scored 0–100 as an "ATS match" using **Jobscan-style rules**. It's **not** an ML accuracy figure — it's an explainable weighted score:

| Component | Weight | What it looks at |
|---|---|---|
| Must-have skill coverage | 55% | How many JD-required skills appear in your resume |
| Nice-to-have coverage | 20% | Coverage of nice-to-have skills |
| Seniority match | 10% | The role's level/years vs. yours |
| Domain match | 10% | Whether the direction fits (NLP / recommendation / risk…) |
| JD-fetch confidence | 5% | Whether the full JD was read, or only the title |

Jobs that **explicitly don't sponsor / demand too many years / require security clearance** get a warning flag.

To measure accuracy yourself: put 30–50 "resume + JD + human label" rows in `eval/dataset.jsonl` and run `python eval/run_eval.py`.

### Hiring systems covered

Auto-detected: **Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio**.
**Workday** (large enterprises/banks) needs a host/site entry — see `data/slug_overrides.json`.
Plus the **Adzuna / Reed / Jooble / JSearch** aggregators (free keys; JSearch reaches LinkedIn/Indeed/Glassdoor via Google for Jobs).

*Find missed companies* probes **Workable only** by default — measured against a real 121k-company cache, Workable costs ~16% of the time and finds ~93% of what that pass finds, while Recruitee/Personio burn most of the clock for a fraction of a percent. Set `DEEP_NICHE=1` for the thorough (much slower) version.

### Data files (`data/`, git-ignored)

| File | What's in it |
|---|---|
| `companies.json` | The company directory (shared by all accounts) |
| `ats_cache.json` | Which hiring system each company uses = your sweep progress (shared) |
| `users/<account>/state.json` | One per account: resume, jobs, first-seen dates, match scores, applications. Running locally, the account is `local`. |
| `users.json` | Accounts, salted+hashed (multi-user only) |
| `api_keys.json` | All your keys |
| `slug_overrides.json` | Manual hiring-page overrides |

An older single-user `data/state.json` is migrated into `users/<owner>/state.json` automatically on first start; the original is left untouched as a backup.

### For developers

Dependencies in `requirements.txt`. Tests: `pytest tests/`. Evaluation scripts in `eval/`.
It's a single-process Flask app with in-memory state and background scan threads — **run one instance only** (don't scale to multiple workers/replicas).

</details>
