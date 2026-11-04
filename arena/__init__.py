"""Local competition harness: runs bots as subprocesses, in-process rules.

The server in ``server/`` is not used here. A match is played by the
rules code in ``game/`` driven directly by :mod:`arena.table`, with each
bot living in its own child process (:mod:`arena.bothost`).
"""

__version__ = "0.1.0"
