# User testing guide

Two checks on the To do list need people and real computers: trying the whole flow on a few classmates' resumes, and
checking desktop alerts on a real Windows PC and a real Mac. This guide is for whoever runs them.

## Keep classmates' information private

- Each person tests on their own computer, or in a data folder of their own: `JobPortal --data-dir ./trial-NAME` (from
  source: `./run.sh --data-dir ./trial-NAME`). Nothing mixes with your own JobPortal.
- Each person connects their own AI account, or a free option (OpenRouter's free models, or a Gemini key on its free
  tier). Never share your own sign-in or key.
- Never commit or share anyone's resume, documents, leads or screenshots of them. `.gitignore` blocks databases but not
  documents, so check `git status`.
- When the trial is over, delete the trial data folder (Settings, Data, Open the folder shows where it is).

## 1. The whole flow on a classmate's resume

Try at least three people in different fields (for example healthcare, a trade, and tech or design), and at least one with
no resume (the resume builder).

| Step | What to check |
|---|---|
| Connect the AI | The welcome makes the choices clear. Sign-in or the key works the first time. |
| Add the resume and documents | The best resume becomes the main one. "What it read" matches the resume. |
| No resume: the resume builder | The questions make sense. The resume it writes uses only what they wrote. |
| Answer the questions | Nothing the resume covers is asked again. Required questions come first. |
| The profile build | It finishes in a few minutes. Settings, Profile reads right. |
| Run a search | Leads arrive in their area and their field, at their level. |
| Open the best lead | The tailored resume and cover letter are truthful and fit the job. Contacts and email templates are there. |
| Tracker and Next moves | Moving a lead works. After three weeks with no reply, Next moves suggests a follow-up. |
| Search on a schedule | Turn it on with a time a few minutes away, and a search starts at that time. |

For each person, write down:

- their field and level (not their name)
- how many leads were good fits, and how many were wrong (wrong place, wrong field, wrong level)
- anything confusing, slow, or wrong in a tailored resume or cover letter
- what they'd want added

Put what you found in a GitHub issue, without anyone's personal details, and link it from the README's To do list.

## 2. Desktop alerts on a real Windows PC and a real Mac

v0.3.0 changed how alerts are sent (a security fix), and only stand-ins have tested it. On each computer:

1. Open Settings, Appearance, and turn on Desktop alerts.
2. Click **Send a test alert**. An alert titled "JobPortal test alert" should show within a few seconds.
3. Leave JobPortal in the background (another window in front) and run a search. Its results should show as alerts.
4. Optional: in Settings, Search, turn on Search on a schedule with background searching, pick a time a few minutes away,
   and close JobPortal. When that search finds new jobs, an alert says so.

If an alert doesn't show:

- **Windows:** open Settings, System, Notifications, and check that notifications are on, Do not disturb is off, and
  Windows PowerShell may send notifications (JobPortal's alerts come through it).
- **macOS:** open System Settings, Notifications, and check that Script Editor may send notifications (JobPortal's
  alerts come through AppleScript), and that Focus is off.

Write down the system version and what happened, and check off the item in the README's To do list once both computers
work.
