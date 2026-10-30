# Contributing to JobPortal

Welcome to the team. This is the guide for everyone working on JobPortal for CMSC 495 7304: who's doing what, what to
install, how the code is laid out, how to test it, and the rules we agreed on. If something here is wrong or missing, fix it
in a pull request like any other change.

## The team

| Name | Role |
|---|---|
| `Matthew Saunders` | `Lead Architect` |
| `Joshua Pitter` | `Lead Architect` |
| `<NAME>` | `<ROLE>` |
| `<NAME>` | `<ROLE>` |
| `<NAME>` | `<ROLE>` |
| `<NAME>` | `<ROLE>` |
| `<NAME>` | `<ROLE>` |
| `<NAME>` | `<ROLE>` |

## What you need to install

People who just use JobPortal install nothing (the release apps bring everything). To work on the code, you need:

| What | Why | Where to get it |
|---|---|---|
| Git | version control | [git-scm.com](https://git-scm.com/downloads) |
| Python 3.11 or newer (3.12 matches the release builds) | runs JobPortal | [python.org](https://www.python.org/downloads/). On Windows, check "Add python.exe to PATH". |
| A code editor | VS Code with the Python extension works well | [code.visualstudio.com](https://code.visualstudio.com/) |
| A GitHub account with access to this repo | the repo is private | ask the repo owner to add you |
| Google Chrome, Microsoft Edge or Chromium | PDF export when running from source | Windows already has Edge |

Optional:

| What | Why |
|---|---|
| A ChatGPT Go, Plus or Pro plan | trying the real AI by hand. The automated tests never need it. |
| LibreOffice | importing old `.doc` resumes |
| [uv](https://docs.astral.sh/uv/) | faster Python environments |
| Linux only: PyGObject and WebKit2GTK 4.1 (Arch: `python-gobject webkit2gtk-4.1`, Debian and Ubuntu: `python3-gi gir1.2-webkit2-4.1`, Fedora: `python3-gobject webkit2gtk4.1`) | a native app window when running from source. Without them it opens in a Chromium browser's app mode or a tab. |

Everything else (FastAPI, pywebview, pypdf, python-docx and the rest) installs automatically.

## Get it running

1. Clone the repo:

   ```bash
   git clone https://github.com/mattsaund/JobPortal.git
   cd JobPortal
   ```

2. Start JobPortal. The first run creates a Python environment in `.venv` and installs everything into it.

   ```bash
   ./run.sh            # macOS and Linux
   ```

   ```powershell
   .\run.ps1           # Windows (or double-click run.bat)
   ```

3. Install the developer tools (pytest and ruff) into the same environment:

   ```bash
   .venv/bin/pip install -e ".[dev]"            # Windows: .venv\Scripts\pip install -e ".[dev]"
   ```

4. Run `jobportal --doctor` (or `./run.sh --doctor`) to check that everything is found.

Use a throwaway data folder while you develop, so test data never mixes with a real job search:

```bash
jobportal --data-dir ./dev-data --port 8790 --browser     # dev-data/ is ignored by git
```

The command line:

| Command | What it does |
|---|---|
| `jobportal` | open the app |
| `jobportal --browser` | open it in your browser instead of a window |
| `jobportal --server` | run only the server (the dashboard is at http://127.0.0.1:8788) |
| `jobportal --background` | run the server detached, so searches keep going with the window closed |
| `jobportal --stop` | stop a server started with `--server` or `--background` |
| `jobportal --doctor` | check Python, the ChatGPT sign-in, the PDF engine and the window toolkit |
| `--port 8790` | use another port (or set `JOBPORTAL_PORT`) |
| `--data-dir PATH` | keep the data somewhere else (or set `JOBPORTAL_HOME`) |

## New to the code? Start here

1. Get JobPortal running with a scratch data folder (see "Get it running" above) and click through every page.
2. Read "How it works" below the project map. It takes five minutes and saves hours later.
3. Pick an item from the To do list in the README and tell the team you're taking it.
4. Find the files to change with the project map and the "Common changes" table, make a branch, make the change, add a
   test, and open a pull request.

Ask in the group chat whenever you're stuck. Everyone on the team is learning this codebase too.

## Project map

```
JobPortal/
├── jobportal/                  the app, as a Python package
│   ├── __init__.py             the version number
│   ├── __main__.py             makes "python -m jobportal" work
│   ├── app/                    starting the program
│   │   ├── cli.py              command line options (--server, --stop, --doctor, ...)
│   │   ├── desktop.py          the app window (native, browser app mode or a tab) and the Linux app menu entry
│   │   └── doctor.py           the --doctor check
│   ├── web/                    the local web server
│   │   ├── server.py           the FastAPI app: startup, the two safety checks, the dashboard files
│   │   ├── routes/             the HTTP API, one file per area (leads, candidate, documents, library, search, ...)
│   │   ├── common.py           helpers the routes share
│   │   └── static/             the dashboard
│   │       ├── index.html      the page shell and the list of scripts, in load order
│   │       ├── style.css       all the styles
│   │       └── js/             core.js, live.js, layout.js, pages/ (one file per page), main.js, and components/ for
│   │                           pieces several pages share (search area, answers form, settings form, file drops)
│   ├── candidate/              what JobPortal knows about the user
│   │   ├── onboarding.py       setup: importing the resume and the standard questions
│   │   ├── profile.py          the profile: building it, updating it, questions along the way, writing voice
│   │   └── library.py          saved resumes (storage only, they never feed the profile)
│   ├── search/                 finding jobs
│   │   ├── pipeline.py         a search run: collect, filter, score with AI, queue packages
│   │   ├── packages.py         work on one lead: build its package, rework its resume, add a job by hand
│   │   ├── plan.py             what to search for: levels, roles, queries, dream companies
│   │   ├── sources.py          the checks on the Sources page
│   │   └── collectors/         one file per kind of source (LinkedIn, company boards, feeds, GitHub lists, AI hunt)
│   ├── ai/                     ChatGPT
│   │   ├── client.py           every AI request (OpenAI's Responses API)
│   │   ├── signin.py           Sign in with ChatGPT
│   │   └── prompts.py          every prompt and the shape of each AI answer
│   ├── documents/              resumes and other files
│   │   ├── extract.py          reading imported files (PDF, DOCX, ODT, RTF, text)
│   │   ├── render.py           resumes and cover letters to HTML, PDF and DOCX
│   │   ├── resumecheck.py      resume checks: format, length, keywords, truthful skills
│   │   ├── exports.py          downloads: single files, the package zip, emails
│   │   └── revise.py           AI edits by instruction
│   ├── insights/               the Analysis (analysis.py) and Equity mining (crm.py) pages
│   ├── core/                   shared building blocks
│   │   ├── background.py       background work (package builds, profile updates) and stopping it at shutdown
│   │   ├── config.py           folders, the port and every default setting
│   │   ├── settings.py         reading and saving settings
│   │   ├── db.py               the SQLite database
│   │   ├── bus.py              live updates to the dashboard
│   │   ├── osutil.py           everything that differs between Windows, macOS and Linux
│   │   ├── textutil.py         text helpers, including location matching
│   │   ├── levels.py           experience levels and the title filters they create
│   │   └── genres.py           work genres and industries
│   └── resources/              files read at run time (the resume playbook, the Linux desktop entry)
├── tests/                      pytest tests and a fictional sample resume
├── packaging/                  how the release apps are built: PyInstaller spec, Windows installer, PDF engine, icons
├── documentation/              school documents, and logo, color and font ideas
├── .github/workflows/          CI (tests on every push) and Release (builds the apps when a version tag is pushed)
└── run.sh, run.ps1, run.bat    start scripts for running from source
```

## How it works

- **A click, start to finish.** A page in `web/static/js/pages/` calls the API. `web/server.py` checks that the request
  comes from this computer and from the dashboard itself. Then the route in `web/routes/` hands the work to the package that
  does it, which reads and writes the database (`core/db.py`) and asks the AI (`ai/client.py`).
- **Long work runs in the background.** Building a package or updating the profile starts with `core/background.py`, and
  the request returns right away. Progress and results come back as live events: `core/bus.py` sends them, `/api/events`
  streams them, and `web/static/js/live.js` updates the page.
- **The profile's inputs** are the resume, any extra documents (`candidate/documents.py`), the standard questions and the
  questions asked along the way (`candidate/`). Saved resumes, leads and web results never feed it.
- **A search run** (`search/pipeline.py`): the collectors find jobs, the rule filters drop what doesn't fit your levels and
  locations, the AI scores the rest, and the best ones get a package (`search/packages.py`).
- **The dashboard** is plain JavaScript with no build step. `index.html` loads the scripts in order (core, live, layout,
  components, pages, then main), so code that runs at load time can only use files loaded before it. Each page registers
  its own buttons with `onAction()`.
- **The packages stack in layers:** `core`, then `ai`, then `candidate` and `documents`, then `search` and `insights`, then
  `web`, then `app`. A lower package never imports a higher one at the top of a file. When it has to, it imports inside the
  function, which keeps import loops out.

## Testing

### The automated tests

```bash
python -m pytest                     # every test, about 3 seconds
python -m pytest tests/test_api.py   # one file
python -m pytest -k downloads        # tests whose name contains "downloads"
python -m ruff check .               # lint, including import order
python -m ruff check . --fix         # fix what ruff can fix by itself
```

- Tests never talk to OpenAI. They use the `fake_ai` fixture in `tests/conftest.py` or the mock OpenAI in `tests/test_ai.py`.
- Every test starts from an empty data folder, exactly like a fresh install.
- Tests use fictional people only (Jordan Rivera, `example.com`). `tests/fixtures/sample_resume.md` is a fake resume.
- CI runs the lint, the tests, `jobportal --doctor`, a server smoke test and the start scripts on Linux, macOS and Windows
  for every push and pull request, with Python 3.11, 3.13 and 3.14. A red CI blocks merging.

| Test file | What it covers |
|---|---|
| `test_api.py` | the HTTP API: setup, downloads, leads, the Dream list, sources, security checks, Quit |
| `test_ai.py` | Sign in with ChatGPT and the AI request loop, against a mock OpenAI |
| `test_profile.py` | building and updating the profile, and that only the resume and answers feed it |
| `test_onboarding.py` | resume import, pre-filling the questions, saving answers |
| `test_extract.py`, `test_render.py` | reading resume files, rendering resumes, PDF export |
| `test_core.py` | config, settings, the database, live updates, location matching and other text helpers |
| `test_levels.py` | experience levels and title filters |
| `test_search.py` | the rule filters (levels, locations, the Dream list), dedupe, triage and building packages |
| `test_platform.py` | cross-platform pieces: the command line, the app window, the PDF engine lookup |

Add or update a test with every bug fix and every feature.

### Testing by hand

- Run with a scratch data folder and another port: `jobportal --data-dir ./dev-data --port 8790 --browser`.
- Import `tests/fixtures/sample_resume.md` to try setup without using your own resume.
- Without signing in to ChatGPT, anything that needs AI shows a "Sign in with ChatGPT first" error. That's expected. To try
  the AI, sign in with your own ChatGPT account.
- After changing the dashboard, click through every page you touched with the browser's developer console open (F12). Any
  red error there is a bug.

## How we work

- Pull `main` before you start. Make a branch for each change, like `feature/interview-tips` or `fix/pdf-timeout`.
- Keep pull requests small and focused, and fill in the pull request template.
- CI must be green, and one teammate reviews before merging. Ask for a second review on anything that changes prompts, the
  database or the setup flow.
- Commit messages are short and say what changed, like "Add a deadline filter to the Leads page".

## Rules

1. **No personal data in the repo.** JobPortal starts empty. Never commit a real resume, a database, generated documents or
   anyone's contact details. `.gitignore` blocks databases, but not documents, so check `git status` before you commit.
2. **Only the user's own material teaches JobPortal about them:** the main resume, any extra documents they add (other
   resumes, certificates, cover letters, awards), the standard questions and the questions asked along the way. Don't add
   other ways to feed the profile.
3. **Keep it cross-platform.** Anything that touches the operating system (opening files and links, notifications, finding
   programs) goes through `jobportal/core/osutil.py`. Use `pathlib` for paths and pass `encoding="utf-8"` whenever you read
   or write text. Keep `run.sh` and `run.ps1` doing the same thing.
4. **Keep the AI truthful.** Prompts may let the AI choose, reorder and rephrase, but never invent. If the profile is
   missing something, the fix is a question for the user (`profile.ask`), not a guess.
5. **Keep it safe.** The server only answers requests from this computer. Don't add endpoints that run commands or read
   arbitrary files. ChatGPT tokens never leave the data folder.
6. **Write plainly.** In UI text, comments and docs: short sentences, American English, no em dashes and no middle dots as
   separators.
7. **Match the code around you.** Absolute imports (`from jobportal.core import db`), the existing naming, and comments that
   explain why. The dashboard is plain JavaScript with no build step: each page registers its own buttons with `onAction()`.

## Common changes

| To | Edit |
|---|---|
| change or add a standard question | `QUESTIONS` in `candidate/onboarding.py` |
| change what the AI writes | the prompt in `ai/prompts.py` |
| add a job source | a collector in `search/collectors/`, listed in `search/collectors/__init__.py`, with defaults in `core/config.py` |
| add a company job board | the Sources page, or `ATS_BOARDS` in `core/config.py` |
| change resume layouts | `RESUME_THEMES` and `_DOCX_THEMES` in `documents/render.py` (keep `FIT_SCALES` in step with the copy in `web/static/js/pages/lead.js`), and the playbook in `resources/resume_playbook.md` |
| add an API endpoint | the matching file in `web/routes/` |
| change a dashboard page | its file in `web/static/js/pages/` |
| add something that differs by operating system | `core/osutil.py` |

## Releases

1. Bump `__version__` in `jobportal/__init__.py`, and update "What's new" in `packaging/release-notes.md`.
2. Commit, then push a version tag: `git tag v0.3.0 && git push origin v0.3.0`.
3. The Release workflow builds the Windows installer, the macOS disk image and the Linux AppImage, checks that each one
   starts and prints a PDF, and publishes them on the Releases page.

The macOS and Linux apps carry their own PDF engine (`packaging/fetch_pdf_engine.py`). The Windows installer is built with
Inno Setup from `packaging/windows/jobportal.iss`. To build the app for your own system:

```bash
pip install -e ".[build]"
pyinstaller --noconfirm packaging/jobportal.spec     # the app lands in dist/
```
