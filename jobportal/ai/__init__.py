"""Everything that talks to ChatGPT.

- client.py sends every AI request. run() performs one AI task and returns its JSON result.
- signin.py handles Sign in with ChatGPT. It gets and refreshes the tokens that let client.py use the user's own plan.
- prompts.py holds the system prompts, the result schemas and the default AI hunt missions that callers pass to run().

Other packages import them as `from jobportal.ai import client as ai, prompts`."""
