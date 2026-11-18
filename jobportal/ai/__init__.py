"""Everything that talks to the AI.

- client.py sends every AI request, to the provider the user picked. run() performs one AI task and returns its JSON result.
- providers.py lists the providers (ChatGPT, OpenRouter and the API key services), keeps the keys and knows which one is in use.
- signin.py handles Sign in with ChatGPT. It gets and refreshes the tokens that let client.py use the user's own plan.
- prompts.py holds the system prompts, the result schemas and the default AI hunt missions that callers pass to run().

Other packages import them as `from jobportal.ai import client as ai, prompts`."""
