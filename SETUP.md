# Watchlist Sync Setup (Google Sheets)

A one-time setup, done by whoever's setting up the shared list for
Ascended (probably you). Takes about 10 minutes — less time than a
proper meditation, more lasting impact. Once it's done, every Guardian
install just needs two URLs pasted into Config — nobody else has to
touch Apps Script or the Sheet's sharing settings ever again.

## 1. Create the Sheet

1. Create a new Google Sheet. Name it whatever you like (e.g. "Ascended
   Guardian Watchlist").
2. Rename the first tab to exactly **`Watchlist`** (capital W — the
   script looks for this exact name; it's not being picky, it's just
   precise).
3. In row 1, add these column headers, in this exact order:

   ```
   user_id | display_name | reason | submitted_by | submitted_at | status | reviewed_by | reviewed_at | last_validated_at | category
   ```

That's the whole schema. Every row after row 1 is one watchlist entry.
`category` is one of `predator`, `stalker`, `troll`, `poi`, `vip`,
`creator`, or `other` — the first three are treated as genuine threats
and blink in Guardian's player list; the rest are informational tags
(VIP, Creator, Person of Interest) and just show a steady color, no
alarm. Not every flag is a warning. Leaving `category` blank on a row
is fine too — Guardian treats that the same as `other`.

`status` is one of `pending` (new submission awaiting review),
`approved` (live/blinking in Guardian), `cleared` (reviewed, not a
threat), `rejected` (reviewed, shouldn't be on the list), or
`pending_removal` (an approved entry someone's requested removing,
still live/blinking until an approver confirms it — see below), or
`removed` (a confirmed removal — the terminal state, same as
`cleared`/`rejected` but reached via the removal-request flow instead
of a fresh review).

## 2. Deploy the Apps Script (the write side)

This is what lets Guardian submit new entries and lets approvers
review them — a published Sheet alone is read-only, same as a diary
with the lock still on.

1. In the Sheet, go to **Extensions → Apps Script**.
2. Delete whatever placeholder code is there, and paste in the entire
   contents of `watchlist_sync.gs` (included alongside this file).
3. **Edit the `APPROVER_ALLOWLIST` array near the top** — replace the
   placeholder entries with the actual VRChat `usr_...` IDs of everyone
   allowed to approve/reject/clear entries. This is the actual
   permission check — anyone not on this list gets rejected by the
   script itself, no matter what Guardian shows them. Trust is
   specific, not implied.
4. Save the script (the disk icon, or Ctrl+S).
5. Click **Deploy → New deployment**.
6. Click the gear icon next to "Select type" and choose **Web app**.
7. Set:
   - **Execute as:** Me (your Google account)
   - **Who has access:** Anyone
8. Click **Deploy**. The first time, Google will ask you to authorize
   the script — click through the "Google hasn't verified this app"
   warning (normal for a script you wrote yourself; click
   **Advanced → Go to [project name] (unsafe)** → Allow).
9. Copy the **Web app URL** it gives you (looks like
   `https://script.google.com/macros/s/AKfycb.../exec`). This is your
   **Apps Script Web App URL** — paste it into Guardian's Config.

**Important:** every time you edit the script later (e.g. updating the
allowlist), you need to **Deploy → Manage deployments → edit (pencil
icon) → New version → Deploy** again. Just saving the script does NOT
update the live deployment — Google keeps "wrote it down" and "it's
actually live" as two separate moments, and so should you.

## 3. Publish the read-only CSV link

This is the URL Guardian polls to know who's currently approved.

1. Back in the Sheet itself, click **Share** (top right) and set
   general access to **"Anyone with the link" → Viewer**. (This only
   affects read access to the whole sheet — it does not let random
   people edit anything; editing only happens through the script and
   its allowlist.)
2. Grab your Sheet's ID from its URL — the long string between `/d/`
   and `/edit` in your browser's address bar:
   ```
   https://docs.google.com/spreadsheets/d/THIS_LONG_ID_HERE/edit
   ```
3. Your CSV URL is:
   ```
   https://docs.google.com/spreadsheets/d/THIS_LONG_ID_HERE/gviz/tq?tqx=out:csv&sheet=Watchlist
   ```
   Paste that into Guardian's Config as the **Sheet CSV URL**.

   **Common mistake to avoid:** the Share dialog's "Copy link" button
   gives you a link ending in `/edit?usp=sharing` — that's the normal
   link that opens the spreadsheet editor, NOT the CSV data Guardian
   needs. Easy mix-up, since that's the link the Share dialog trains
   you to copy for everything. **Guardian actually auto-detects and
   corrects this for you now** — paste that kind of link by mistake
   and it'll be silently converted to the right format before Guardian
   uses it. Worth knowing about anyway, in case you ever build the URL
   by hand somewhere else.

## 4. Test it

In Guardian, go to your username (top right) → **Config → Watchlist
Sync**, paste in both URLs, click **Save Sync Settings**, then
**Test Connection**. It should report how many approved entries it
found (0 is fine for a brand new sheet — everything starts empty).

Then open the **Watchlist** window and try **Add to Watchlist** on a
test entry — it should show up in the `Watchlist` tab of your Sheet
with `status = pending`. An approver can then either edit that row's
`status` cell directly in the Sheet, or (better, since it also stamps
`reviewed_by`/`reviewed_at` automatically) use the **Review Queue**
inside Guardian's Watchlist window.

## How the pieces fit together

- **Guardian reads** the sheet via the plain CSV link — no login, no
  script involved, just a file download. Only `status = approved` rows
  ever make it into the live blinking/caution-icon feature.
- **Guardian writes** (new submissions, approvals, rejections, clears)
  through the Apps Script Web App — the CSV link can't be written to,
  and the script is what actually enforces who's allowed to review.
- **`user_id` is the only thing ever matched on.** Display names get
  refreshed automatically over time as Guardian happens to see
  watchlisted players in-game, but names are never used to decide if
  two entries are "the same person" — names change, people don't stop
  being who they are.
