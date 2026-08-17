"""
note_lookup.py

Shared helper: "check VRChat for the current note on this player, and fall
back to our own local AAR history if that check fails." note_dialog.py had
this logic inline already (it was the first dialog built); kick_dialog.py
and ban_dialog.py use this shared version so all three dialogs start
pre-filled with whatever's already on file, instead of only Note doing it.
What one part learns, the whole app should remember.
"""

import aar


def fetch_current_note(client, target_user_id: str) -> tuple[str, str]:
    """
    Returns (note_text, status_message).
      - note_text is "" if there's nothing to pre-fill.
      - status_message is meant to go straight into a status QLabel.
    """
    result = client.get_user(target_user_id)

    if result.status == "success":
        if result.note:
            return result.note, "Existing VRChat note loaded below — you can edit it before continuing."
        return "", "No existing note on file for this player yet."

    # Live fetch failed -- fall back to our local record rather than
    # showing a blank box that could silently overwrite an existing note.
    previous_note = aar.latest_note_for_user(target_user_id)
    if previous_note:
        return previous_note, (
            f"Couldn't reach VRChat to check the current note ({result.error_message}) -- "
            f"showing the last note sent from this app instead."
        )
    return "", f"Couldn't check for an existing note: {result.error_message}"
