"""Keep the shared HUD alive when an individual Codex session ends."""

from __future__ import annotations


def main() -> None:
    """Do not stop the HUD: it is shared by all Codex sessions on this desktop.

    The SessionStart hook already uses a process-wide mutex and PID file to
    reuse one HUD across sessions. Killing that process here made the HUD
    disappear whenever Codex recycled a session, even though the desktop app
    was still open. The detached HUD owns its own lifetime and can be closed
    explicitly by the user or when the host process exits.
    """

    return


if __name__ == "__main__":
    main()
