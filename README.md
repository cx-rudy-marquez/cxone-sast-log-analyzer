# Checkmarx One – SAST Log Viewer

A lightweight Flask app that exchanges a Checkmarx refresh token for an access token, fetches a SAST scan’s raw engine log and scan metadata, parses the log for key insights, and renders a sleek, single-page HTML report (no iframes).

The report is themed to match the Checkmarx “Scheduling Console” look & feel and includes download support for an offline HTML report.

---

## Features

- **Scan lookup by ID** — enter a `scan_id` and generate a full report.
- **Token exchange** — uses your `CX_API_KEY` (refresh token) to obtain a Bearer token.
- **Endpoints used**
  - `POST https://deu.iam.checkmarx.net/auth/realms/{CX_TENANT}/protocol/openid-connect/token` (exchange refresh → access token)
  - `GET  {CX_AST_BASE}/api/scans/{scan_id}` (project name, branch, SAST timing and LOC)
  - `GET  {CX_AST_BASE}/api/logs/{scan_id}/sast` (raw SAST log)
- **Cards in the report**
  - **Coverage (Files / LOC)** and **Parsing Summary** (with red donuts if coverage < 97%).
  - **Language mode & language lists** (identified vs. scanned) using the CSV-based “Per-Language Parse Statistics” when present. Shows a count of scanned languages and per-language identified/scanned tallies.
  - **Vulnerabilities** — severity-badged list of only Critical/High/Medium with results; “Top 10” if there are at least 10 items; clearer color contrast between High and Medium. (Pie removed to maximize list space.)
  - **Sanity Check** — single table with the **top 3 “Inputs”, “Outputs”, “Sanitize”** queries for the dominant language.
  - **Statistics per Language** — parsed from the “Per-Language Parse Statistics” CSV block.
  - **Files with Parsing Issues** — heuristic extraction of file paths from parsing-error lines, now recognizing SQL messages (e.g., “RecognitionException”, “No PLSQL statements found”). This section is collapsible and paginated (20 rows/page) for large datasets.
  - **Excluded Files/Folders** — counts plus explicit filename/folder exclusions. Also parses the “Exclude Files” block to list name-based dropped files.
  - **Raw Log** — last section for reference.
- **Download** — `/download/<scan_id>` returns the rendered HTML as a file.


## Requirements

- **Python** 3.10+ (tested on macOS and Linux)
- A Checkmarx One tenant with API access
- A **refresh token** (provided as `CX_API_KEY`)
- Internet access to Checkmarx IAM and AST APIs


## Quick Start

```bash
git clone <this-repo> CxOneLogViewer
cd CxOneLogViewer

# (Recommended) create a clean virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install deps
pip install -r requirements.txt

# Create a .env file (see below), then run:
python app.py
```

Open `http://localhost:8500` and paste your `scan_id` to generate the report.  
Use the **Download** button (or open `/download/<scan_id>`) to save the HTML report.


## Environment

Create a `.env` file in the project root with:

```
CX_TENANT=cx_ps_rudy_marquez
CX_AST_BASE=https://deu.ast.checkmarx.net
CX_API_KEY=YOUR_REFRESH_TOKEN_HERE
```

> **Note:** `CX_API_KEY` must be a **refresh token**. The app exchanges it for an access token (Bearer) against the IAM endpoint. Treat it as a secret; don’t commit it.


## Project Structure

```
CxOneLogViewer/
├─ app.py                    # Flask app (routes, token exchange, API calls)
├─ report_renderer.py        # Parsing + HTML rendering (self-contained, no iframes)
├─ templates/
│  ├─ index.html             # Home page (scan_id form)
│  └─ error.html             # Friendly error page
├─ requirements.txt
├─ .env                      # Your environment variables (not committed)
└─ README.md                 # This file
```


## How it Works

1. **Token exchange**  
   `app.py` posts to IAM to exchange `CX_API_KEY` (refresh token) → `access_token`.

2. **Fetch scan metadata** (`/api/scans/{scan_id}`)  
   Extracts `projectName`, `branch`, and SAST `startDate`, `endDate`, `loc` from `statusDetails`.

3. **Fetch raw log** (`/api/logs/{scan_id}/sast`)  
   Gets the text log used by `report_renderer.py` parsers.

4. **Parse and render**  
   `report_renderer.py` turns the log into a single HTML document matching the suite style.


## Key Parsers

- **Coverage & Parsing Summary:** after the `Scan Accuracy` block:
  - Total/Good/Partial/Bad files, LOC breakdown, DOM objects
  - Donuts (red if coverage < 97%)
  - Language mode + lists from:
    - `MULTI_LANGUAGE_MODE is set to ...`
    - `All languages identified but not scanned: ...`
    - `Languages that will be scanned: ...`

- **Vulnerabilities:** after `*** Results Summary ***`
  - Only `Critical | High | Medium`
  - Totals pie (from positive results) + list (top 10 only if >= 10; otherwise only items with results)

- **Sanity Check:** after `General Queries Summary`
  - Dominant language = one with most scanned files
  - Top 3 of each category (“Inputs”, “Outputs”, “Sanitize”)

- **Statistics per Language:** after the *Per-Language Parse Statistics* header, read CSV lines like:  
  `per-language-parse-statistics,language,total-files,good-files,partially-good-files,bad-files,file-coverage%,...`

- **Files with Parsing Issues:** heuristic scan of lines with keywords (`failed to parse`, `parsing error`, `partially good file`, `recognitionexception`, `no plsql statements found`, etc.) extracting full file paths; data is shown in a collapsible, paginated table (20 per page).

## Recent changes

- Vulnerabilities card: removed pie, expanded list area, improved High/Medium color separation.
- Parsing Summary: prefers CSV-based per-language stats; shows scanned language count and per-language identified/scanned lines.
- Exclusions: parses “Exclude Files” block and lists name-based dropped files explicitly.
- Files with Parsing Issues: detects SQL parsing messages and supports collapsible + pagination UI for large sets.


## Troubleshooting

- **405 Method Not Allowed** when fetching logs  
  Ensure the app uses **GET** for `/api/logs/{scan_id}/sast`. (This project does.)

- **"no such group"** on report page  
  This typically occurs when the log format differs and a regex didn’t match. Update to the latest `report_renderer.py` or share a sample log so the pattern can be extended.

- **No such file or directory: .venv/bin/python3.13** on macOS  
  Your virtualenv may point to a different Python version than installed. Recreate the venv with your active Python:
  ```bash
  rm -rf .venv
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```

- **Blank data in a card**  
  Usually means the relevant section wasn’t present in the log. The UI will show `—` or a small empty state.


## Customization

- **Colors & theme**: adjust CSS tokens inside `render_html` in `report_renderer.py` (the `:root{}` block).
- **Donut threshold**: in `donut_svg`, change `bad_threshold` (default `0.97`).
- **Parsers**: extend or tune regexes in `report_renderer.py` to match your engine versions.


## Deployment

- **Production WSGI** (example):
  ```bash
  pip install gunicorn
  gunicorn -w 2 -b 0.0.0.0:8500 app:app
  ```
- **Containerize** (outline):
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  EXPOSE 8500
  CMD ["python", "app.py"]
  ```

Ensure the container gets `CX_TENANT`, `CX_AST_BASE`, and `CX_API_KEY` as environment variables.


## Security Notes

- Keep your `.env` out of version control.
- The server never stores your tokens; they’re used in-memory per request.
- If you deploy, prefer HTTPS and restrict access appropriately.


## License

MIT — see `LICENSE` (or choose a license that fits your org).


## Acknowledgements

- Checkmarx One (AST & IAM) APIs
- Flask and Jinja2

---

**Happy scanning.** If you hit a log format we don’t parse yet, open an issue with a sanitized sample and we can extend the patterns quickly.
