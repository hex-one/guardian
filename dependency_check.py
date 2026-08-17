"""
dependency_check.py

Checked FIRST, before anything else in main.py imports PySide6/requests --
that ordering matters: if PySide6 itself is the thing that's missing, we
can't use PySide6 to tell the user that. This file only ever uses Python's
standard library (importlib, tkinter, sys) so it can never itself fail to
import, no matter what's missing. Light the candle before you trust the
bigger fire.

--------------------------------------------------------------------------
BEGINNER NOTES:

- `importlib.util.find_spec(name)` checks whether a package COULD be
  imported without actually importing it -- exactly what we need here.
  Actually importing a missing package raises ImportError immediately,
  which is the crash we're trying to avoid.

- tkinter ships built into Python itself (unlike PySide6/requests, which
  need `pip install`), so it's a safe fallback for showing a message even
  when literally nothing else third-party is available yet.

- This only ever checks for what's ACTUALLY missing, not blindly telling
  someone to reinstall everything -- if you're only missing one package,
  that's all the command will mention.
--------------------------------------------------------------------------
"""

import sys
import importlib.util

# (import name, pip install name) -- usually identical, but kept as pairs
# in case a future dependency's package name differs from its import name.
REQUIRED_PACKAGES = [
    ("PySide6", "PySide6"),
    ("requests", "requests"),
]


def ensure_dependencies():
    """
    Call this before importing anything else third-party. Returns silently
    if everything's present. If something's missing, shows the user
    exactly what to run, then exits the program -- there's no reasonable
    way to continue without the missing package(s) anyway.
    """
    # A PyInstaller-frozen build already has everything bundled in --
    # there's no `pip install` to point someone at, and find_spec() has
    # nothing useful to check against a frozen import system anyway.
    if getattr(sys, "frozen", False):
        return

    missing = [pip_name for import_name, pip_name in REQUIRED_PACKAGES
               if importlib.util.find_spec(import_name) is None]

    if not missing:
        return

    _show_missing_dependencies(missing)
    sys.exit(1)


def _show_missing_dependencies(missing: list):
    install_command = f"pip install {' '.join(missing)}"
    message = (
        "Guardian needs a few Python packages that aren't installed yet:\n\n"
        f"    {', '.join(missing)}\n\n"
        "Open a terminal in this folder and run:\n\n"
        f"    {install_command}\n\n"
        "(or, to install everything Guardian needs at once:\n"
        "    pip install -r requirements.txt\n)\n\n"
        "Then run Guardian again."
    )

    # Print to the console either way -- if Guardian was launched from a
    # terminal, this alone is often the most convenient place to read it.
    print("\n" + message + "\n")

    # ALSO try a small window, for anyone who launched Guardian by
    # double-clicking it rather than from a terminal (no console visible
    # in that case). tkinter is the one thing we can rely on here, since
    # it's part of Python itself -- everything else might be exactly
    # what's missing.
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title("Guardian \u2014 Missing Requirements")
        root.resizable(False, False)

        label = tk.Label(root, text="Guardian needs a few packages installed first:", justify="left")
        label.pack(padx=16, pady=(16, 8), anchor="w")

        command_box = tk.Entry(root, width=50)
        command_box.insert(0, install_command)
        command_box.configure(state="readonly")
        command_box.pack(padx=16, pady=4)

        def copy_command():
            root.clipboard_clear()
            root.clipboard_append(install_command)
            copy_button.configure(text="Copied!")

        copy_button = tk.Button(root, text="Copy Command", command=copy_command)
        copy_button.pack(padx=16, pady=(4, 8))

        hint = tk.Label(
            root,
            text="Run that in a terminal from this folder, then start Guardian again.",
            justify="left", wraplength=340,
        )
        hint.pack(padx=16, pady=(0, 16), anchor="w")

        close_button = tk.Button(root, text="Close", command=root.destroy)
        close_button.pack(pady=(0, 16))

        root.mainloop()
    except Exception:
        # No display available, tkinter itself missing/broken, etc -- the
        # console message above is already printed, so there's still a
        # way for the user to see what to do even if this window fails.
        pass
