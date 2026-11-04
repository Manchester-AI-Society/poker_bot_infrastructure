import sys

from .cli import main

# Guarded: worker processes started with "spawn" (Windows, macOS)
# re-import this module and must not run the CLI again.
if __name__ == "__main__":
    sys.exit(main())
