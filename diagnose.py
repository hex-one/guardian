"""
diagnose.py

Run this instead of main.py to figure out WHY the player list isn't
populating. It doesn't open any window -- it just prints information to
the terminal so we can see what's actually happening. Diagnostics before
debugging -- know the problem before you fight it.

Usage:
    python diagnose.py
"""

import os
from log_watcher import find_latest_log_file, parse_line

print("=" * 70)
print("STEP 1: Can we find the log file at all?")
print("=" * 70)

log_path = find_latest_log_file()

if log_path is None:
    appdata_low = os.path.expandvars(r"%USERPROFILE%\AppData\LocalLow")
    expected_dir = os.path.join(appdata_low, "VRChat", "VRChat")
    print(f"NOT FOUND. We looked in: {expected_dir}")
    print("Things to check:")
    print("  - Does that folder actually exist on your PC?")
    print("  - Are there files in it named like 'output_log_*.txt'?")
    print("  - Is VRChat actually installed via Steam/standalone on THIS PC")
    print("    (not a different drive/user account)?")
    raise SystemExit(0)

print(f"FOUND: {log_path}")
print(f"File size: {os.path.getsize(log_path):,} bytes")
print(f"Last modified: {os.path.getmtime(log_path)}")

print()
print("=" * 70)
print("STEP 2: Does the file actually have content, and can we read it?")
print("=" * 70)

with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
    all_lines = f.readlines()

print(f"Total lines in file: {len(all_lines)}")

if not all_lines:
    print("File is EMPTY. Has VRChat actually joined a world yet since launch?")
    raise SystemExit(0)

print()
print("Last 15 lines in the file (raw, exactly as VRChat wrote them):")
print("-" * 70)
for line in all_lines[-15:]:
    print(repr(line))
print("-" * 70)

print()
print("=" * 70)
print("STEP 3: Do any lines in the WHOLE file match our parser?")
print("=" * 70)

matched = 0
for line in all_lines:
    event = parse_line(line)
    if event:
        matched += 1
        print(f"  MATCHED ({event.kind}): {line.strip()}")

print()
if matched == 0:
    print("ZERO lines matched. This tells us the regex patterns in")
    print("log_watcher.py don't match your VRChat version's exact log format.")
    print()
    print("Next step: look at the raw lines printed in STEP 2 above -- find a")
    print("line that mentions a player joining/leaving, or joining a world,")
    print("and send it to me (redact your own username/ID if you'd rather).")
    print("I'll adjust the regex patterns to match exactly.")
else:
    print(f"{matched} lines matched out of {len(all_lines)} total.")
    print("Parsing IS working on the file as a whole. If main.py's list is")
    print("still empty, the issue is likely that main.py started watching")
    print("AFTER these events already happened (it only watches for NEW")
    print("lines from the moment it starts) -- try leaving main.py running")
    print("and then leave/rejoin the instance to generate a fresh event.")
