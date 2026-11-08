#!/usr/bin/env python3
"""One-shot, read-only ASA RCON diagnostic.

This script intentionally has no polling loop and accepts no arbitrary command.
It sends only ListPlayers and GetChat, in that order, after authentication.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys

from src.ark_service import SourceRconClient


HOST_DEFAULT = "192.168.1.10"
PORT_DEFAULT = 27020
TIMEOUT_DEFAULT = 5.0
ALLOWED_COMMANDS = ("ListPlayers", "GetChat")

log = logging.getLogger("ark-rcon-diagnostic")


def _redacted_error(exc: BaseException) -> str:
    """Return a safe error label without including exception arguments."""
    return type(exc).__name__


def _run_command(client, command: str) -> str:
    if command not in ALLOWED_COMMANDS:
        raise ValueError("command is not in the diagnostic allowlist")
    return str(client.run(command) or "")


def _print_response(command: str, response: str) -> None:
    if response:
        print(f"[{command}]\n{response}")
    else:
        print(f"[{command}] empty response")


def main(
    *,
    host: str = HOST_DEFAULT,
    port: int = PORT_DEFAULT,
    timeout: float = TIMEOUT_DEFAULT,
    password: str | None = None,
) -> int:
    if not password:
        log.error("ARK_RCON_PASSWORD is not set; no connection attempted")
        return 2

    log.info("Connecting to configured ARK RCON endpoint %s:%d", host, port)

    try:
        with SourceRconClient(host, port, password, timeout) as client:
            for command in ALLOWED_COMMANDS:
                try:
                    response = _run_command(client, command)
                except (socket.timeout, TimeoutError):
                    log.error("%s timed out", command)
                    return 1
                except (ConnectionError, OSError):
                    log.error("%s failed because the connection closed", command)
                    return 1
                except Exception as exc:
                    log.error("%s failed: %s", command, _redacted_error(exc))
                    return 1
                _print_response(command, response)
    except (socket.timeout, TimeoutError):
        log.error("RCON connection timed out")
        return 1
    except (ConnectionError, OSError):
        log.error("RCON connection failed or was disconnected")
        return 1
    except Exception as exc:
        # Authentication failures and library-specific protocol errors are
        # intentionally reported by type only; never print their arguments.
        log.error("RCON authentication or protocol failure: %s", _redacted_error(exc))
        return 1

    log.warning("GetChat may read or advance the server chat buffer; do not poll it continuously without verifying ASA behavior.")
    return 0


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        log.error("python-dotenv is unavailable; no connection attempted")
        sys.exit(2)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("ARK_RCON_HOST", HOST_DEFAULT))
    parser.add_argument("--port", type=int, default=int(os.getenv("ARK_RCON_PORT", PORT_DEFAULT)))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("ARK_RCON_TIMEOUT", TIMEOUT_DEFAULT)))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main(host=args.host, port=args.port, timeout=args.timeout, password=os.getenv("ARK_RCON_PASSWORD")))
