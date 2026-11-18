# Installing JobPortal

This guide covers installing JobPortal on Windows, macOS and Linux, the first run, where your data lives, updating,
uninstalling, and running it from the source code. The [user manual](USER_MANUAL.md) covers using it.

## What you need

- A computer with Windows 10 or 11, macOS (Apple Silicon or Intel), or 64-bit Linux.
- An account with an AI JobPortal can use. Any one of these works:
  - a ChatGPT Go, Plus or Pro plan (one click to sign in)
  - an OpenRouter account (sign in from JobPortal, with free models that have a daily limit)
  - an API key from Google Gemini (it has a free tier), Claude (Anthropic), OpenAI, Mistral, Groq, DeepSeek or xAI, or
    from any other service with an OpenAI-compatible chat API

Your own account pays for what the AI uses, and you can set a spending limit there.

## Download and install

Get the newest version from the [Releases page](https://github.com/mattsaund/JobPortal/releases).

| System | File | How to install |
|---|---|---|
| Windows 10 or 11 | `JobPortal-Windows-Setup.exe` | Double-click it. It installs JobPortal for your user, adds Start menu and desktop shortcuts, and opens it. |
| macOS (Apple Silicon) | `JobPortal-macOS.dmg` | Open it and drag JobPortal into Applications. |
| macOS (Intel) | `JobPortal-macOS-Intel.dmg` | The same, for Macs with an Intel processor. |
| Linux (x86_64) | `JobPortal-Linux-x86_64.AppImage` | Make it executable (`chmod +x JobPortal-Linux-x86_64.AppImage`), then run it. The first run adds it to your app menu. |

Everything JobPortal needs comes inside the download, including what it uses to print resumes to PDF.

### The first open warns you

The apps aren't code-signed yet, so each system asks before it opens an app from an unknown developer.

- **Windows:** if SmartScreen says it protected your PC, click More info, then Run anyway.
- **macOS:** if macOS says it can't check the app, open System Settings, Privacy & Security, scroll down and click Open
  Anyway, then open JobPortal again.
- **Linux:** nothing to approve. Without Chrome, Edge, Chromium or Brave installed, JobPortal opens in a browser tab
  instead of a window of its own.

## The first time you open it

1. **Connect your AI.** Click Continue with ChatGPT, or under "No ChatGPT plan?" sign in with OpenRouter or add an API key.
2. **Add your resume** with any certificates, licenses, cover letters, awards or transcripts. No resume? Click "No
   resume? Answer a few questions and JobPortal writes one."
3. **Answer the questions** Home asks, one at a time. JobPortal fills in what your resume already says.
4. **Run a search**, or turn on Search on a schedule in Settings, Search.

## Where your data lives

Everything JobPortal keeps (your profile, leads, documents, tailored files, sign-ins and keys) stays in one folder on your
computer. Settings, Data, Open the folder shows it.

| System | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\JobPortal` |
| macOS | `~/Library/Application Support/JobPortal` |
| Linux | `~/.local/share/JobPortal` |

## Searching in the background

When you turn on Search on a schedule with "Keep searching after you close JobPortal", JobPortal keeps a small server
running after its window closes, and adds itself to the programs your system starts when you log in:

| System | Where the login item is |
|---|---|
| Windows | the `JobPortal` value in `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` |
| macOS | `~/Library/LaunchAgents/io.github.mattsaund.jobportal.plist` |
| Linux | `~/.config/autostart/jobportal-background.desktop` |

Turning background searching off removes the login item, and the background server quits a few minutes later. Settings,
Data has a Quit button while it runs.

## Updating

Download the new version and install it the same way, over the old one. Your data stays, because it lives in the data
folder, not in the app.

## Uninstalling

1. Turn off background searching in Settings, Search, so the login item is removed.
2. Remove the app:
   - **Windows:** Settings, Apps, Installed apps, JobPortal, Uninstall.
   - **macOS:** drag JobPortal from Applications to the Trash.
   - **Linux:** delete the AppImage, and `~/.local/share/applications/jobportal.desktop` for the app menu entry.
3. To delete your data too, delete the data folder above. That also forgets your sign-ins and keys on this computer.

## Running from the source code

You need Python 3.11 or newer and Git.

```bash
git clone https://github.com/mattsaund/JobPortal.git
cd JobPortal
./run.sh          # macOS and Linux
.\run.ps1         # Windows PowerShell (or run.bat)
```

The first run creates a Python environment in `.venv` and installs JobPortal into it. Later runs start right away. To work
on the code, install the developer tools with `pip install -e ".[dev]"` and see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Troubleshooting

- **Check everything at once:** run JobPortal with `--doctor` (`./run.sh --doctor`, or the installed app's program with
  `--doctor`). It checks Python, the data folder, the AI's sign-in or key, the login item, the PDF engine, the window
  toolkit and the port.
- **Another program uses port 8788:** start JobPortal with `--port 8790`.
- **The AI says to connect it:** open Settings, AI, check which AI is picked, and sign in or save its key again.
- **"Out of credit" or "limiting how many requests":** your AI account reached a limit. Add credit or wait, and searching
  goes on by itself.
- **PDF downloads don't work from source:** install Chrome, Edge, Chromium or Brave. The downloaded apps already have
  what they need.
