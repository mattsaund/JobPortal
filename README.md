# JobPortal

JobPortal finds jobs for you and prepares every application. You give it three things:

1. **Your resume.** Import a PDF, Word, ODT, RTF, Markdown or text file, or paste it.
2. **Answers to the standard job questions.** Contact details, work authorization, education, the roles and levels you want,
   and where you can work. Most are pre-filled from your resume.
3. **Answers to questions it asks along the way.** When a posting wants something your profile doesn't show, JobPortal asks.
   Each answer improves your profile and every future application.

JobPortal then searches LinkedIn, company career sites, job lists, Hacker News, Reddit, Mastodon, Bluesky, RSS feeds and
USAJobs. AI agents also search social media, comment threads, recruiters and local news. Every job is scored against your
profile. The best ones get a full package: a tailored resume, cover letter, outreach emails, contacts, interview prep and a
company brief.

It runs on your computer (Windows, macOS or Linux) and starts with zero data. Its AI runs on your own ChatGPT plan through
Sign in with ChatGPT. Nothing is sent, posted or applied for without you.

Built as the capstone project for **CMSC 495 7304**.

## Download

Get the latest version from the [Releases page](https://github.com/mattsaund/JobPortal/releases).

| System | File | First run |
|---|---|---|
| Windows 10 or 11 | `JobPortal-Windows.exe` | If SmartScreen warns, click More info, then Run anyway. |
| macOS (Apple Silicon) | `JobPortal-macOS.dmg` | Drag JobPortal to Applications and open it. If macOS blocks it, open System Settings, Privacy & Security, and click Open Anyway. |
| Linux (x86_64) | `JobPortal-Linux-x86_64.AppImage` | Make it executable (`chmod +x`), then run it. It opens in your browser. |

When JobPortal runs in a browser tab, closing the tab leaves it running so searches can finish. Settings, Your data has a
Quit button.

The apps aren't code-signed yet, which is why each system warns the first time.

## What you need

| What | Why |
|---|---|
| A ChatGPT Go, Plus or Pro plan | the AI behind profiles, scoring, research and writing |
| Chrome, Edge or Chromium | turning resumes and cover letters into PDFs |
| LibreOffice (optional) | importing old `.doc` resumes |

## Using it

1. **Set up.** The first screen walks you through four steps: Continue with ChatGPT, import your resume, check the pre-filled
   questions, and build your profile.
2. **Run a search.** Leads appear live as they qualify.
3. **Open a lead.** See the fit, edit the tailored resume and cover letter, export PDF or DOCX, and copy answers for the form.
4. **Answer questions** in Profile, Questions. Answers are added to your profile automatically.
5. **Apply** with the lead's Apply button. The tracker keeps follow-ups on schedule.

Other pages: **Equity mining** ranks your best next moves. **Tracker** is a board from Saved to Offer. **Resumes** keeps
resumes you want to reuse. **Analysis** compares your fit with market demand. **Dream list** flags the companies and roles you
care about. **Sources** controls every search source and AI mission.

## ChatGPT usage

- Sign in from the setup screen, the sidebar or Settings. Your browser opens OpenAI's sign-in page, then returns to JobPortal.
- ChatGPT shares only your name and email with JobPortal.
- AI usage counts against your ChatGPT plan. JobPortal shows the tokens it uses.
- You can set a weekly cap for JobPortal in ChatGPT settings. When the cap is reached, runs pause and queued leads wait.
- Settings lets you pick the model and the reasoning effort for each kind of task.

## Run from source

You need Python 3.11 or newer. Clone the repository, then run the start script. The first run creates `.venv` and installs
everything.

```bash
./run.sh            # macOS and Linux
```

```powershell
.\run.ps1           # Windows (or double-click run.bat)
```

Or install it yourself with `pip install -e .` to get a `jobportal` command.

| Command | Does |
|---|---|
| `jobportal` | open the app |
| `jobportal --browser` | open it in your browser instead of a window |
| `jobportal --server` | run only the server (the dashboard is at http://127.0.0.1:8788) |
| `jobportal --background` | run the server detached, so searches continue with the window closed |
| `jobportal --stop` | stop a server started with `--server` or `--background` |
| `jobportal --doctor` | check Python, the ChatGPT sign-in, the PDF browser and the window toolkit |
| `--port 8790` | use another port (or set `JOBPORTAL_PORT`) |
| `--data-dir PATH` | keep the data somewhere else (or set `JOBPORTAL_HOME`) |

On Linux, a window of its own needs GTK WebKit or Qt WebEngine. Install your distribution's PyGObject and WebKit2GTK 4.1
packages and `run.sh` uses them. Otherwise JobPortal opens in your browser. `packaging/linux/install-desktop-entry.sh` adds it
to your app menu.

## Where your data lives

Your data never goes in the program folder. Everything is kept in one place:

| System | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\JobPortal` |
| macOS | `~/Library/Application Support/JobPortal` |
| Linux | `~/.local/share/JobPortal` |

Settings, Your data shows the exact path. To start over, quit JobPortal and delete that folder.

## Privacy and safety

- The server listens on 127.0.0.1 only and refuses requests for any other host name.
- Each AI task sends OpenAI only what it needs. Voluntary self-identification answers (gender, race, veteran and disability
  status) are never sent. They only fill in the Application kit for copying.
- ChatGPT tokens stay in the data folder. They never reach the dashboard, logs or URLs.
- AI agents can only return results, fetch public web pages and use OpenAI's web search when your account allows it. They
  can't reach your computer or local network. Text on web pages is treated as data, never as instructions.
- Tailoring may reorder, rephrase and choose what to show. It may not invent experience, dates, metrics or skills.
- Nothing is ever sent, posted or submitted automatically.

## Project layout

```
jobportal/            the Python package
  main.py             HTTP API and dashboard server (FastAPI)
  onboarding.py       setup: resume import, the standard questions, pre-fill
  profile.py          the profile: build, updates from answers, questions, voice
  pipeline.py         a search run: collect, filter, triage, build packages
  collectors/         one module per source family, plus the AI hunt
  ai.py               every AI request (OpenAI Responses API)
  openai_auth.py      Sign in with ChatGPT
  prompts.py          every AI prompt and output schema
  render.py           resumes and cover letters to HTML, PDF and DOCX
  extract.py          text from PDF, DOCX, ODT, RTF and text files
  osutil.py           everything that differs between Windows, macOS and Linux
  desktop.py, cli.py  the app window and the command line
  static/             the dashboard (vanilla JavaScript, no build step)
packaging/            app icons, the PyInstaller spec and Linux desktop files
tests/                pytest suite (runs on all three systems in CI)
run.sh, run.ps1, run.bat   start scripts for running from source
```

More detail is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
