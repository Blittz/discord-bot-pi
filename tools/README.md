# Local diagnostics

`ark_rcon_diagnostic.py` is a one-shot ASA RCON diagnostic. It sends only
`ListPlayers` and `GetChat` after authentication. It does not accept arbitrary
RCON commands and has no polling mode.

The script reads `ARK_RCON_PASSWORD` from the process environment. Optional
non-secret settings are `ARK_RCON_HOST`, `ARK_RCON_PORT`, and
`ARK_RCON_TIMEOUT`. Keep the password in the service's protected environment
or another root-readable secret store; do not add it to `.env` backups, source,
logs, shell history, or Git.

The diagnostic uses only the Python standard library plus the already-installed
`python-dotenv` package; no additional RCON dependency is required. It loads
the password from the existing `.env` when run from the repository directory.
