# AI Job Scout — UK visa-sponsor job radar

**In one line:** it automatically visits the official hiring systems of companies that **hold a UK Skilled Worker sponsor licence**, pulls the jobs they are currently advertising, sorts them by freshness, and — once you upload your resume — scores each job for fit and suggests improvements.

> By default it looks for **AI / Machine Learning** roles, but **change a few keywords and it finds any industry** (nursing, accounting, marketing, engineering… see below).
> The big advantage: every company here is **licensed to sponsor a UK Skilled Worker visa**, which is far more efficient than applying blindly across the whole web.
> (Note: holding a licence ≠ every role will definitely sponsor you — always confirm from the JD or in the interview.)

> **You don't need to be technical.** Just follow the steps below and click along. If you get stuck on any step, **copy the whole error message** on screen, open any **AI assistant** (ChatGPT, Claude, Gemini, etc.), paste it and ask "what do I do?" — it will walk you through it. That's your universal help button.

---

# 🚀 First-time setup: three steps to run

You only install once. After that, opening it takes just the last small step (see "Opening it later").

## 🪟 Windows

### Step 1: Install Python (once)
1. Open https://www.python.org/downloads/
2. Click the big yellow **"Download Python 3.x"** button, then double-click the downloaded file.
3. ⚠️ **The most important step**: at the **bottom** of the installer window there's a checkbox **"Add python.exe to PATH"** — **make sure it's ticked**, then click **Install Now**.
   (If you forget to tick it, you'll later see "not recognized as an internal or external command" — just reinstall and tick the box.)
4. Click Close when done.

### Step 2: Download this tool (once)
1. On this project's GitHub page, click the green **"Code"** button → **"Download ZIP"**.
2. Find the zip in your Downloads folder, **right-click → "Extract All"**, and extract it to your **Desktop** so it's easy to find.
3. You'll get a folder called `AI-Job-Scout`.

### Step 3: Launch
1. Open the `AI-Job-Scout` folder.
2. Click the **address bar at the top** of the window (the one showing the folder path), clear it, type **`cmd`**, and press Enter.
   → A **black window** (the command line) pops up. Don't worry — it's just where you type commands.
3. In the black window, **paste this line**, press Enter, and wait for it to finish (a minute or two the first time):
   ```
   pip install -r requirements.txt
   ```
4. When that's done, **paste this line** and press Enter:
   ```
   python app.py
   ```
5. When you see something like `AI Job Scout running: http://127.0.0.1:5050`, it worked.
6. Open your browser, type **http://127.0.0.1:5050** and press Enter → the tool's interface appears 🎉

> **Don't close that black window** — closing it stops the tool. Just leave it open while you use the tool.

## 🍎 macOS

1. **Install Python**: go to https://www.python.org/downloads/, download the macOS version, double-click the `.pkg` and click through the installer.
2. **Download the tool**: on GitHub, **Code → Download ZIP**, double-click to unzip it to your Desktop, giving you the `AI-Job-Scout` folder.
3. **Open Terminal**: in Finder, **right-click** the `AI-Job-Scout` folder → "Services" → "**New Terminal at Folder**".
4. In Terminal, run these in order (use `pip3`/`python3` instead of `pip`/`python`):
   ```
   pip3 install -r requirements.txt
   python3 app.py
   ```
5. Open **http://127.0.0.1:5050** in your browser. Don't close the Terminal window.

---

# 🔁 Opening it later (no reinstall)

**Easiest on Windows: double-click `Start-Job-Scout.bat` in the folder** —
it starts the server and opens your browser automatically, no typing needed. The black window that pops up is the website's server; leave it open while you use the tool (you can minimize it), and close it when you want to stop.

Manual method (macOS / if the .bat won't open):

1. Open the `AI-Job-Scout` folder → type `cmd` in the address bar and press Enter (macOS: right-click → open Terminal at folder).
2. Run **`python app.py`** (macOS: `python3 app.py`).
3. Open **http://127.0.0.1:5050** in your browser.

**To stop it**: just close that black window / Terminal.

---

# 🆘 Stuck? Find your case (99% of issues are here)

| What you see on screen | What it means / what to do |
|---|---|
| `python is not recognized...` / `command not found` | You forgot to tick **Add to PATH** when installing Python. Reinstall Python and tick the box, or restart your computer and retry. On macOS use `python3`. |
| `pip is not recognized...` | Same as above. You can also use `python -m pip install -r requirements.txt` (macOS: `python3 -m pip …`). |
| `Address already in use` / port in use | The tool is already running in another black window. Close the extra windows, or just use the one already open. |
| Browser says "can't reach / connection refused" | Make sure the black window is still open and shows "running"; the address must be **exactly** `http://127.0.0.1:5050`. |
| Uploading a PDF resume fails | Your PDF may be a **scanned image**. Save a **text-based PDF** from Word, or just **paste** your resume text in directly. |
| Any other error you don't understand | **Copy the whole thing**, paste it into any **AI assistant** (ChatGPT / Claude / Gemini) and ask how to fix it. Really — this is the easiest route. |

---

# 📖 After install, how to use it (in this order)

### ① First give it a list of licensed sponsor companies
- On gov.uk, search **"register of licensed sponsors workers"** and download the official CSV (updated weekly, ~120k companies).
- Back in the tool, expand **"⚙️ Advanced"** and enter the CSV **file path** to import it.
- You can also drop in your own company list (Excel / CSV / paste directly); those get marked **⭐Curated**.

### ② Scan for jobs
- **🔄 Scan new jobs**: your everyday button — a few minutes, fetches new jobs from known companies.
- **🌊 Full sweep**: **run once the first time** (~10+ hours, stoppable anytime and resumes automatically next time) to probe every company. You won't need to run it again after that.

### ③ Upload your resume
- Drop in a **PDF / Word / txt** resume; the tool automatically computes a **match score** for every job and lists which skills you're missing.

### ④ Review / pick jobs / get advice
- The left of each job row is the **match-score block** (green = high, amber = medium); after scoring, jobs sort by match by default.
- **Click any job row to expand it**: see which skills you're missing → generate that job's **✍️ resume-improvement tips** and
  **💬 networking outreach drafts** in one click (LinkedIn application notes / follow-up DMs / cold emails, generated personally, ready to copy).
- Save ones you like with **☆ Save** → manage them in the top **📌 Applications** board: change status (To apply → Applied → Interviewing → Offer/Rejected), open the application page, find recruiters, look up emails. The actual applying stays manual — every application uses a tailored resume, which beats any "auto-spam" tool (which also risks getting your account banned).
- Click **📥 Export** to save as Excel; click **🎯 Resume tips** on the resume card to see "the skills most worth adding across all jobs".

---

# 🔁 Not looking for AI jobs? Switch to your industry

At heart this tool "scans company hiring systems for jobs whose title or body contains **your chosen keywords**" — **it's industry-agnostic**. Expand **"⚙️ Advanced → Job keywords"**, change them to your terms, save, and re-scan. Examples:

| Industry | Keywords to use |
|---|---|
| Nursing / healthcare | nurse, healthcare assistant, clinical, care worker |
| Accounting / finance | accountant, financial analyst, audit, tax, bookkeeper |
| Marketing / ops | marketing, social media, content, brand, growth |
| Engineering | mechanical engineer, civil engineer, electrical engineer |
| Education | teacher, lecturer, teaching assistant |
| Supply chain | supply chain, logistics, procurement, warehouse |

> Not sure which keywords? Ask any **AI assistant**: "I'm looking for UK visa-sponsor jobs in the XX industry, suggest a set of keywords."

---

# 🤖 Want to change something? Let an AI assistant help (no coding needed)

You don't need to learn programming. Use any **AI coding assistant**, or just send the project folder to ChatGPT / Claude etc., and describe what you want in **plain English**, for example:

- "Change the job keywords to nurse / healthcare related ones."
- "I only want to see London jobs, hide all other regions."
- "Weight the match score more toward years of experience."
- "Add a feature to sort by salary."
- "It errored on startup, here's the error: (paste) — fix it for me."

You just describe the **result you want**; the AI edits the code and explains it. Tip: ask it to run `pytest tests/` afterward to confirm nothing broke.

---

# 🌐 Platforms it can't scrape — search / apply on these yourself

The tool only reads the public endpoints of companies' **official hiring systems**. The platforms below are **blind spots** you'll need to search yourself:

| Platform | Notes |
|---|---|
| **LinkedIn** | Scraping is prohibited; search it yourself (the tool gives a one-click "LinkedIn recruiter search" link per company). |
| **Indeed** | The biggest aggregator; search it yourself. |
| **Glassdoor** | Search it yourself. |
| **Totaljobs / CV-Library / Reed website** | Major UK-native sites worth browsing yourself. |
| **In-house systems** (Google, Amazon, big banks, etc.) | Not detectable; use the "Google search" link on the company card to check manually. |

> Every company card includes one-click links for **LinkedIn recruiter search / Hunter email lookup / Google job search**, to help you cover these platforms manually and find HR contacts along the way (the tool won't crawl contacts for you — it just gives you the search entry points).

**Want broader, faster coverage?** (optional, free sign-up) Copy `api_keys.example.json` to `data/api_keys.json` and fill in the free keys for the **four aggregator sources** below (the more you add, the broader the coverage), then click **🌐 Add jobs from job boards** on the page to sweep relevant UK jobs in seconds and automatically flag which companies are on the sponsor register:

| Source | Sign-up | What it adds |
|---|---|---|
| **Adzuna** | https://developer.adzuna.com/ | UK-wide job aggregation (~1000 calls/month) |
| **Reed** | https://www.reed.co.uk/developers | One of the largest UK-native job sites |
| **Jooble** | https://jooble.org/api/about | Aggregates many UK job sites; broad top-up |
| **JSearch (RapidAPI)** | https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch | ⭐Pulls **Google for Jobs**, covering **LinkedIn / Indeed / Glassdoor / ZipRecruiter** — exactly the "blind spots" table above. Fill in `rapidapi_key` (free tier ~200 calls/month). |

> **To cover the LinkedIn/Indeed blind spots, configure `rapidapi_key` (JSearch)** — it's the only source that can pull those big aggregators' jobs in automatically.
> Cover the rest manually via the "LinkedIn recruiter search / Google search" links on each company card.
> Bottom line: **no free official API connects directly to the full LinkedIn/Indeed feed**; JSearch via Google for Jobs is the most practical approximation.

---

# 🏢 Built-in big-tech / AI employers (no configuration)

The tool **ships with a set of well-known employers** pre-loaded; they're added to your list and scanned on first launch, so you don't have to add them manually:

- **AI/ML standouts** (mostly on Greenhouse/Lever/Ashby, auto-detected): Anthropic, OpenAI, Cohere, Hugging Face, DeepMind, Databricks, Palantir, Wayve, Faculty, Quantexa, Synthesia, Stability AI, ElevenLabs, Speechmatics, Graphcore, Monzo, Wise, Revolut, and more.
- **Workday large enterprises** (in-house/Workday systems, direct addresses built in): NVIDIA, Salesforce, Adobe, Dell, Mastercard, Capital One, Autodesk, AstraZeneca, Sanofi, and more.

> ⚠️ Workday addresses are **best-effort** presets: if one can't be fetched (the company changed its address), it **doesn't affect other companies** — the tool just skips it.
> To fix one: use "manual override" on its company card to enter the new `host`/`site` (saved to `data/slug_overrides.json`, overriding the built-in).
>
> ❗ **Google / Amazon / Meta / Microsoft / JPMorgan** and others use **in-house hiring systems (not Workday)** with no public API to fetch — these can only be checked manually via the "Google search / LinkedIn search" links on the company card. That's a hard limit no tool gets around.

---

# ✍️ Cross-platform resume tips

After you upload a resume and scoring finishes, click **🎯 Resume tips** on the resume card: the tool aggregates **all matched jobs** and tells you, ranked by impact, "the skills most worth adding" — e.g. `research·83 (🎯27)` means this skill is missing from 83 jobs, 27 of which are medium-match (where adding it gains the most). It also uses **corpus mining** to list phrasings that appear frequently in JDs but your skill list might miss.

Want **prose suggestions** generated right inside the tool: add an LLM key to `data/api_keys.json` —
**for ChatGPT** fill `openai_api_key` (default model `gpt-4o`, or set the `OPENAI_API_KEY` env var),
**for Claude** fill `anthropic_api_key`. If you fill both, choose with `llm_provider` (`openai` / `anthropic`); if unset it defaults to ChatGPT.
Once configured, the button becomes **✍️ Generate tips with ChatGPT**, giving you an actionable checklist: which items to add first, where in the resume to add each and how to word it, which experiences to rewrite. **It won't invent experience you don't have.**

## 🎯 Tailoring your resume for a single job

Beyond "cross-platform" tips, you can get tailored advice for **one specific job**: on a job card, click the **match %** badge to expand it, and use **✍️ Tailor my resume for this job with ChatGPT** — it takes this **JD body + your resume's gaps + your full resume** and generates advice specific to that one job (which terms to add, which experiences to rewrite, an opening line for a cover letter), shown right on the card. Without an LLM key, the **📋 Copy prompt** button next to it still copies the full prompt so you can paste it into ChatGPT / Claude and generate it manually.

---

# 👥 Host it for a group (multi-user)

By default the tool is **single-user and local** (no login). If you want to host it on a server so **friends can each register and use their own copy**, it also runs multi-user:

- **Multi-user mode** turns on automatically when the app is exposed (`HOST=0.0.0.0`, e.g. in Docker) or when you set `APP_MULTIUSER=1`. It then **requires login**, with a proper login/register page (passwords are salted+hashed in `data/users.json`, never stored in plain text).
- **Each account is fully isolated**: its own resume, its own scans, its own matched jobs, applications board, hidden list — people can't see each other's data. Only the underlying **company directory and probe caches are shared** (so the ~120k-company list isn't duplicated per person).
- **Self-serve registration** is **off by default** (only existing accounts can log in). Set `REGISTRATION_OPEN=1` to let anyone with the URL create an account.
- **All AI calls run on the host's API key.** Because of that, each account has **per-day caps** — `LLM_DAILY_CAP` (default 100) and `SCAN_DAILY_CAP` (default 10) — to prevent runaway spend. The owner account (the `APP_USER` you set) is exempt.

Environment variables (e.g. in a `.env` / Docker):

| Var | Purpose |
|---|---|
| `APP_MULTIUSER=1` | Force multi-user mode (auto-on when `HOST=0.0.0.0`) |
| `APP_USER` / `APP_PASSWORD` | Seed the owner account (cap-exempt) |
| `REGISTRATION_OPEN=1` | Allow public self-serve registration (default off) |
| `LLM_DAILY_CAP` / `SCAN_DAILY_CAP` | Per-user daily limits (default 100 / 10) |

> ⚠️ Open registration + shared API key means strangers who find the URL can sign up and spend against your key (within the caps). Only set `REGISTRATION_OPEN=1` when you're comfortable with that, and keep the caps sensible.

---

# 🔒 Privacy

Running it **locally** (the default): all data (the company list, your resume, the jobs fetched) lives **only on your own computer** in the `data/` folder and is never uploaded to any server. `data/` is git-ignored and won't be synced to GitHub.

Running it **hosted (multi-user)**: each account's data lives on **your server** under `data/users/<account>/`, isolated per account. It's still never sent to any third party — but as the host, you are responsible for that server.

---

<details>
<summary><b>🧠 Advanced: how the match score works / which systems are covered (for the curious, optional)</b></summary>

After you upload a resume, the tool scores each job 0–100 as an "ATS match" using **Jobscan-style rules**. This is **not** a machine-learning accuracy figure — it's an explainable weighted score:

| Component | Weight | What it looks at |
|---|---|---|
| Must-have skill coverage | 55% | How many JD-required skills appear in your resume |
| Nice-to-have skill coverage | 20% | Coverage of nice-to-have skills |
| Seniority match | 10% | The role's level/years vs. your years |
| Domain match | 10% | Whether the direction fits (NLP/recommendation/risk…) |
| JD-fetch confidence | 5% | Whether the full JD was fetched or only the title |

It also adds a ⚠️ warning to jobs that "explicitly don't sponsor / require too many years / require security clearance".
To validate accuracy, prepare 30–50 "resume + JD + human label" rows in `eval/dataset.jsonl` and run `python eval/run_eval.py`.

**Hiring systems covered**: Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Personio (auto-detected);
Workday (large enterprises/banks, needs manual host/site config, see `data/slug_overrides.json`); and the Adzuna / Reed / Jooble / JSearch(RapidAPI) aggregators (need free keys; JSearch covers LinkedIn/Indeed/Glassdoor via Google for Jobs).

**For developers**: dependencies in `requirements.txt`; automated tests `pytest tests/`; evaluation scripts in `eval/`.
Data files live in `data/`: `companies.json` (the shared list), `ats_cache.json` (probe cache = full-sweep progress),
`slug_overrides.json` (manual overrides), `api_keys.json` (all keys). Per-user state (jobs / first-seen dates / match scores / resume) lives in `state.json` for local single-user, or under `data/users/<account>/state.json` when hosted multi-user; accounts are in `data/users.json` (hashed).

</details>
