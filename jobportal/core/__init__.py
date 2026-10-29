"""Shared building blocks the rest of JobPortal uses.

    config     where data lives, the server address, and DEFAULT_SETTINGS (every setting with its default)
    settings   reads and saves the user's settings, which are stored in the database and merged over the defaults
    db         the SQLite database: its tables, upgrades for older databases, and small query helpers
    bus        live updates to the dashboard (the Server-Sent Events stream)
    osutil     Windows, macOS and Linux differences: opening files, notifications, finding the PDF engine
    textutil   text helpers: HTML to text, duplicate detection, dates, location matching, keyword coverage
    levels     experience levels (internship to lead) and the title filters and search words they imply
    genres     work-type genres and employer industries, with keyword classifiers

Core knows nothing about web pages, job boards or the AI, so any package may import it. The one exception goes the other
way: settings.py reads the default AI hunt missions from ai/prompts.py (inside a function, to avoid an import loop)."""
