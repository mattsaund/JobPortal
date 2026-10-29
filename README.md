# JobPortal

JobPortal is our capstone project for **CMSC 495 7304**. It's a desktop app that finds jobs for you and gets every
application ready to send.

> This README is a work in progress. We'll keep updating it as the project moves along.

## Why we built it

Looking for a job as a student takes forever. You check ten different sites, read the same posting twice, and rewrite your
resume for every application. We wanted one app that handles the boring parts, so you can spend your time on the
applications that are actually worth it.

## How it works

You give JobPortal three things:

1. **Your resume.** PDF, Word, ODT, RTF, Markdown or plain text. You can also paste it in.
2. **Answers to the standard job questions.** Contact info, work authorization, education, the roles and levels you want,
   and where you want to work. Most of these fill in from your resume.
3. **Answers to questions it asks along the way.** When a job wants something your profile doesn't show, JobPortal asks
   you about it. Your answer makes every application after that better.

That's all it learns from. JobPortal doesn't read anything else about you.

Then it searches LinkedIn, company career sites, job lists, Hacker News, Reddit, Mastodon, Bluesky, RSS feeds and USAJobs
in the locations you pick: specific states and cities, remote, or nationwide. AI agents also dig through places normal job
boards miss. Every job gets scored against your profile, and the best ones get a full package:

- a resume tailored to that job
- a cover letter
- outreach emails and the people to send them to
- interview prep and a company brief

Nothing is ever sent, posted or applied for without you.

## Download

Get the newest version from the [Releases page](https://github.com/mattsaund/JobPortal/releases). There's nothing else to
install.

| System | File | How to install |
|---|---|---|
| Windows 10 or 11 | `JobPortal-Windows-Setup.exe` | Double-click it. It installs JobPortal, adds Start menu and desktop shortcuts, and opens it. If SmartScreen warns, click More info, then Run anyway. |
| macOS (Apple Silicon) | `JobPortal-macOS.dmg` | Open it and drag JobPortal into Applications. If macOS blocks it, open System Settings, Privacy & Security, and click Open Anyway. |
| Linux (x86_64) | `JobPortal-Linux-x86_64.AppImage` | Make it executable (`chmod +x`), then run it. The first run adds it to your app menu. |

The only thing you need is a ChatGPT Go, Plus or Pro plan. JobPortal signs in with your ChatGPT account, so there's no API
key to set up.

The apps aren't code-signed yet. That's why Windows and macOS warn you the first time you open them.

## Using it

1. **Set up.** Continue with ChatGPT, import your resume, check the pre-filled questions, and build your profile.
2. **Pick where to search.** States, cities, remote or nationwide.
3. **Run a search.** Leads show up live as they qualify.
4. **Open a lead.** See why it fits, edit the resume and cover letter, and download PDF or Word files.
5. **Apply.** Use the lead's Apply button. The tracker reminds you when to follow up.

There's more in the sidebar:

| Page | What it's for |
|---|---|
| Tracker | your applications on a board, from Saved to Offer |
| Resumes | resume versions you want to keep and reuse |
| Analysis | how your fit compares with what the market wants |
| Dream list | the companies and roles you care most about |
| Equity mining | your most valuable next moves, ranked |
| Sources | every place JobPortal searches, which you can turn on or off |
| Settings | AI models, filters, the resume playbook and your data |

## Screenshots

_Coming soon._

## Project status

- [x] Resume import and the standard job questions
- [x] Job search across boards, feeds and AI agents, in the locations you choose
- [x] Tailored resumes, cover letters and full application packages
- [x] Sign in with ChatGPT
- [x] One-click apps for Windows, macOS and Linux
- [ ] User testing with classmates
- [ ] Screenshots and a demo video
- [ ] Final presentation

## To do

- [ ] Add profile editing and creation
- [ ] Job listing saving
- [ ] Get a good color scheme
- [ ] Pick a good font
- [ ] Get a good logo
- [ ] Change the name (maybe?)
- [ ] Simplify the UI: fewer buttons and fewer words. Sleek, simple and easy to use.

## Built with

- **Python** and **FastAPI** for the local server
- **Plain JavaScript, HTML and CSS** for the dashboard (no build step)
- **SQLite** for storage
- **OpenAI's Responses API** through Sign in with ChatGPT
- **pywebview** for the app window and **PyInstaller** for the release apps

## Your data

Everything stays on your computer, in one folder:

| System | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\JobPortal` |
| macOS | `~/Library/Application Support/JobPortal` |
| Linux | `~/.local/share/JobPortal` |

Settings, Your data shows the exact path. To start over, quit JobPortal and delete that folder.

- The app's server only talks to your own computer. Other websites can't change anything in it.
- Each AI task sends OpenAI only what it needs. Your answers about gender, race, veteran status and disability are never
  sent. They only fill in the copy-and-paste kit for application forms.
- Tailored resumes can reorder and reword things, but they never make up experience, dates, numbers or skills.

## Working on JobPortal

Start with [CONTRIBUTING.md](CONTRIBUTING.md). It has the team list, what to install, a map of the code and how to run the
tests. Everything else, from how the code works to our school documents and design ideas, is in
[documentation/](documentation/).

## License

MIT. See [LICENSE](LICENSE).
