"""
process_check.py

One question, one function: is VRChat.exe actually still running? Every
other feature in this app only ever reads the log file -- this is the
first thing that reaches out to the OS itself, and only for this one
narrow purpose. Needed to tell "the log went quiet because nothing's
happening right now" apart from "the log went quiet because the game
is dead" -- see main.py's _check_for_silent_crash.

Windows-only, same as the rest of Guardian. Uses `tasklist` (already on
every Windows box, no new dependency) rather than pulling in psutil for
one boolean check.
"""

import subprocess

VRCHAT_PROCESS_NAME = "VRChat.exe"
TASKLIST_TIMEOUT = 5


def is_vrchat_running() -> bool:
    """
    True if VRChat.exe shows up in the process list, OR if the check
    itself couldn't be trusted (tasklist missing, timed out, whatever).
    Defaulting to "assume it's still running" on any uncertainty is
    deliberate -- this function exists to gate a crash accusation, and
    an accusation built on "we couldn't actually tell" is worse than
    just staying quiet.
    """
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {VRCHAT_PROCESS_NAME}", "/NH"],
            capture_output=True, text=True, timeout=TASKLIST_TIMEOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return True

    if result.returncode != 0:
        return True

    return VRCHAT_PROCESS_NAME.lower() in result.stdout.lower()
