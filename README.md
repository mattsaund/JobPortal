# JobPortal

JobPortal finds jobs for you and prepares every application. You give it three things:

1. **Your resume.** Import a PDF, Word, ODT, RTF, Markdown or text file (or paste it).
2. **Answers to the standard job questions.** The ones almost every application asks: contact details, work authorization,
   education, the roles and levels you want, where you can work. Most of them are pre-filled from your resume.
3. **Answers to questions it asks along the way.** When a posting wants a skill your profile doesn't show, or a bullet would
   be stronger with a number, JobPortal asks. Every answer makes your profile, and every future application, better.

From that, it builds your profile and hunts through every avenue it can reach: LinkedIn, company career sites, community job
lists, Hacker News, Reddit, Mastodon, Bluesky, RSS feeds, USAJobs, and AI agents that search social media, comment threads,
recruiters, local news and contract awards. Every job is scored against your profile, and the best ones get a full
application package: a resume written for that job, a cover letter, outreach emails, contacts, interview prep and a company
brief.

It runs on your own computer (Windows, macOS or Linux) and starts with zero data. Nothing is sent, posted or applied for
without you.

Built as the capstone project for **CMSC 495 7304**.

## Requirements

| What | Why | Get it |
|---|---|---|
| Python 3.11 or newer | runs JobPortal | [python.org/downloads](https://www.python.org/downloads/) (Windows: tick "Add python.exe to PATH") |
| Claude Code, logged in | the AI behind profiles, scoring, research and writing | [claude.com/claude-code](https://claude.com/claude-code), then run `claude` once to log in |
| Chrome, Edge or Chromium | turns resumes and cover letters into PDFs | Edge comes with Windows; most Macs and Linux desktops have Chrome or Chromium |
| LibreOffice (optional) | only for importing old `.doc` resumes | [libreoffice.org](https://www.libreoffice.org/) |

JobPortal uses your Claude subscription through Claude Code, so there is no API key to set up.

## Install and run

Clone the repository, then start it with the script for your system. The first run creates a virtual environment in `.venv`
and installs everything; later runs start right away.

**Windows:** double-click `run.bat`, or in PowerShell:

```powershell
.\run.ps1
```

**macOS and Linux:**

```bash
./run.sh
```

JobPortal opens in its own window (Edge WebView2 on Windows, WebKit on macOS, GTK or Qt on Linux). If no window toolkit is
available it opens in your default browser instead; everything works the same there.

Prefer to manage Python yourself? `pip install -e .` gives you a `jobportal` command on every system.

Check your setup at any time:

```bash
./run.sh --doctor        # Windows: .\run.ps1 --doctor
```

### Command line

| Command | Does |
|---|---|
| `jobportal` | open the app |
| `jobportal --browser` | open it in your browser instead of a window |
| `jobportal --server` | run only the server in this terminal (the dashboard is at http://127.0.0.1:8788) |
| `jobportal --background` | run the server detached, so searches keep going with the window closed |
| `jobportal --stop` | stop a server started with `--server` or `--background` |
| `jobportal --doctor` | check Python, Claude Code, the PDF browser and the window toolkit |
| `--port 8790` | use another port (or set `JOBPORTAL_PORT`) |
| `--data-dir PATH` | keep the data somewhere else (or set `JOBPORTAL_HOME`) |

The scripts pass these through: `./run.sh --browser`, `.\run.ps1 --doctor`.

### Linux: native window

On Linux the window needs GTK WebKit or Qt WebEngine. Install your distribution's packages for PyGObject and WebKit2GTK 4.1
(Debian and Ubuntu: `python3-gi gir1.2-webkit2-4.1`; Fedora: `python3-gobject webkit2gtk4.1`; Arch: `python-gobject
webkit2gtk-4.1`) and `run.sh` picks them up automatically. Or use Qt: `.venv/bin/pip install "pywebview[qt]"`.
To add JobPortal to your app menu, run `packaging/linux/install-desktop-entry.sh`.

## Using it

1. **Set up.** The first screen walks you through importing your resume, checking the pre-filled standard questions, and
   building your profile (a few minutes).
2. **Run a search.** Leads appear live as they qualify. "Everything" runs every source; you can also run just the job boards,
   just the AI hunt, or just the package queue.
3. **Open a lead** to see the fit, the tailored resume and cover letter (edit them, revise with AI, export PDF or DOCX), emails,
   contacts, company intel, interview prep and copy-ready answers for the application form.
4. **Answer questions** in Profile, Questions. Answers are added to your profile automatically, and any lead can be reworked
   with them in one click.
5. **Apply** through the lead's Apply button. The tracker keeps follow-ups on schedule.

Other pages: **Equity mining** ranks your best next moves, **Tracker** is a drag-and-drop board from Saved to Offer,
**Resumes** keeps resumes you want to reuse, **Analysis** compares your fit with market demand across work types,
**Dream list** flags companies and roles you care most about, and **Sources** controls every search source and AI mission.

## Where your data lives

JobPortal never stores your data in the code folder. Everything (database, imported resume, generated documents) goes in one
folder:

| System | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\JobPortal` |
| macOS | `~/Library/Application Support/JobPortal` |
| Linux | `~/.local/share/JobPortal` |

Settings, Your data shows the exact path with a button that opens it. To start over from zero, quit JobPortal and delete that
folder. To keep a separate profile (for testing, or a second person), use `--data-dir` or `JOBPORTAL_HOME`.

## Privacy and safety

- The server listens on 127.0.0.1 only and refuses requests addressed to any other host name.
- Your data stays on your computer. Each AI task sends Claude only what it needs, through your own Claude Code login.
  Voluntary self-identification answers (gender, race, veteran and disability status) are never sent to the AI; they only
  fill in the Application kit for copying.
- The AI agents get web search and web fetch only: no shell and no file access. Text on web pages is treated as data, never
  as instructions. Everything from the web is escaped in the dashboard.
- Tailoring may reorder, rephrase and choose what to show. It may not invent experience, dates, metrics or skills, and gaps
  become questions for you instead of guesses.
- Nothing is ever sent, posted or submitted automatically.

## Cost and usage

The sidebar shows your Claude 5-hour and 7-day usage. Runs pause on their own near the 5-hour limit (configurable), and queued
leads wait for the next run. Each stage's model and effort are in Settings. Rough API-equivalent costs (covered by a Claude
subscription): a profile build about $0.50, one application package with research about $1, triage about $0.10 per 20
jobs, one AI hunt mission $1 to $3.

## Project layout

```
jobportal/            the Python package
  main.py             HTTP API and dashboard server (FastAPI)
  onboarding.py       setup: resume import, the standard questions, pre-fill
  profile.py          the profile: build, updates from answers, questions, voice
  pipeline.py         a search run: collect, filter, triage, build packages
  collectors/         one module per source family, plus the AI hunt
  prompts.py          every AI prompt and output schema
  render.py           resumes and cover letters to HTML, PDF and DOCX
  extract.py          text from PDF, DOCX, ODT, RTF and text files
  osutil.py           everything that differs between Windows, macOS and Linux
  desktop.py, cli.py  the app window and the command line
  static/             the dashboard (vanilla JavaScript, no build step)
tests/                pytest suite (runs on all three systems in CI)
run.sh, run.ps1, run.bat   start scripts
```

More detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests and the few rules that keep JobPortal working on every system.

## License

[MIT](LICENSE)
