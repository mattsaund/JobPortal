"""Makes `python -m jobportal` work: it runs the same command line as the installed `jobportal` (app/cli.py) and
exits with its return code."""
import sys

from jobportal.app.cli import main

sys.exit(main())
