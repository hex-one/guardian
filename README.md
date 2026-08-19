# Guardian — v0.1 (formerly "Ascended QuickMOD")

Hey. Jasper Hex here.

Somewhere between a meditation session and a 3am debugging binge, this
became Guardian — a moderation tool for VRChat group instances that I
built the way I build everything: quietly, thoroughly, with the person
actually using it kept in mind the whole time. Moderation shouldn't
feel like triage. It should feel like tending something you care about.
Guardian watches your instance in real time and puts Note / Grp Kick /
Grp Ban one right-click away — no alt-tabbing to a browser mid-incident,
no losing your place, no scrambling.

Old-school gamer instinct runs underneath all of it: back before
dial-up was a sure thing, you didn't get to half-finish a build and
patch it later — you wrote the password down on paper and you got it
right the first time, because there wasn't a "later." That's still how
I work. Every bullet below is a real feature, tested against the real
thing, not a promise.

## What's in this version

- `dependency_check.py` — the gatekeeper. Runs before anything else, so
  if PySide6 or requests aren't installed yet, you get a clear
  copy-paste `pip install ...` command (in a small window AND printed
  to console) instead of a raw Python traceback the first time you run
  Guardian on a fresh machine. Only ever leans on Python's own standard
  library — has to work even when the actual dependencies are the very
  thing missing, same principle as keeping a candle lit before you
  trust the bigger fire.
- `player_entry.py` — the tracked state for one player in the list:
  present or departed, and when they connected. Someone leaving isn't
  erased from memory immediately anymore — see `main.py` below for why
  that matters.
- `log_watcher.py` — finds your VRChat log file and turns new lines
  into events (instance changed, player joined, player left). No GUI
  code, no VRChat login in here — just "read the log, tell me what
  happened," the same stillness I look for at the lake at 3am. **Now
  also parses each line's own timestamp** (VRChat writes one on every
  line) so join events carry a real connection time, not just "now" —
  used for the Connection Time sort and for catching up on startup.
  Tested the parsing logic against realistic sample log lines; it
  correctly picks out all three event types, every time.
- `vrchat_api.py` — talks to VRChat's web API. Handles the two-step
  login (password, then a 2FA code if your account has that on), and
  saves your session afterward so you're not re-logging-in every
  launch. **Never saves your password** — only the session cookies
  VRChat gives back, in `~/.ascended_quickmod/session.json` on your own
  PC. Treat that file like a saved password; it deserves the same
  respect. The `USER_AGENT` (app name + contact) is baked in here — no
  per-machine editing needed.
- `login_dialog.py` — the login window itself. Has a "Remember me on
  this PC" checkbox: checked (the default) saves your session cookie
  AND your username for next time; unchecked clears both. Your
  password is never saved either way. Every field/button already has a
  `.setObjectName(...)` set (`usernameInput`, `loginButton`,
  `rememberCheckbox`, etc.) so custom glow/hover QSS can target them
  directly whenever it's ready — no code changes needed on this end.
- `style.qss` — auto-loaded by `main.py` on startup if present. This is
  where the visual identity lives. Currently a bare-bones placeholder,
  just proving the loading mechanism actually works before dressing it
  up properly.
- `aar.py` — the "After Action Report" log. Every moderation action
  (note, kick, ban, unban) gets recorded locally in
  `~/.ascended_quickmod/aar_log.json`, including failed attempts and
  temp-ban expiry info. Separate from VRChat's own note history — this
  is your team's own pullable record, the campaign log nobody can edit
  out from under you.
- `note_lookup.py` — shared "fetch the current VRChat note, fall back
  to local AAR history if that fails" logic used by Note, Grp Kick, and
  Grp Ban dialogs, so all three start pre-filled with whatever's
  already on file for that player, not just Note.
- `kick_dialog.py` — right-click a player → Grp Kick opens this (group
  instances only, greyed out if you're known not to have permission).
  **Grp Kick From...**, right below it, does the same thing for ANY
  group you moderate, not just the one hosting your current instance —
  see `group_mod_cache.py` below for how that's made fast.
  **A real action**, same pattern as Ban (reason required, pre-filled
  from the player's current VRChat note, confirmation prompt, logs
  every attempt to the AAR) but without a duration — a kick removes
  their group membership; they can rejoin later per the group's own
  settings, no timer to track. This is genuinely the same thing VRCX's
  "Kick" button does in its group moderation panel — confirmed against
  the same endpoint, no guessing.
- `note_dialog.py` — right-click a player → Note opens this. **Fetches
  the actual current note from VRChat itself** (via `GET /users/{id}`,
  which includes your note on that player) and pre-fills it — reflects
  reality even if the note was set from the VRChat website, not just
  from here. If that live check fails, it falls back to the last note
  this app sent (from the local AAR log) rather than showing a blank
  box that could silently overwrite something — presence over
  assumption, always. Saves via VRChat's real `userNotes` API —
  creating and updating are the same call. Has a **"Personal note —
  exclude from AAR report" checkbox** (plain notes only, unchecked by
  default) — checking it still saves to VRChat as normal, it just
  skips the local AAR entry, for notes that are personal rather than
  moderation-related.
- `ban_dialog.py` — right-click a player → Grp Ban opens this (group
  instances only, greyed out if you're known not to have permission).
  This is a **real, destructive action** — actually bans the player
  from the group via VRChat's API. Requires a reason (pre-filled from
  the player's current note, same as Kick), a confirmation prompt
  before doing anything, and logs every attempt — success or failure —
  to the AAR. Has a "Temporary ban" option with a **number + unit
  picker** (Minutes/Hours/Days — 4 hours, 6 minutes, 21 days, whatever
  the moment calls for), not just whole days; checking it also saves
  the ban to `temp_bans.py` for automatic unbanning later. **Grp Ban
  From...**, same idea as Kick's, works against any group you
  moderate.
- `group_mod_cache.py` + `group_picker_dialog.py` — what makes "Grp
  Kick From"/"Grp Ban From" practical instead of a minutes-long wait.
  Checking "do I have moderation permission in group X" is a real,
  necessarily uncached network call per group (two, actually — the
  permission check itself, plus that group's own permission catalog,
  since VRChat's permission names aren't fixed across groups) — for
  someone in a couple hundred groups, that's genuinely a lot of
  requests. `group_mod_cache.py` runs that whole scan concurrently
  (bounded, not "all N groups in a burst," with basic retry/backoff
  since this is the first thing in this app to realistically risk
  VRChat's rate limiting) on a background thread at startup, and
  persists the result so a relaunch isn't a cold start either. The
  account menu's **Update Perms** re-runs it on demand. Each entry
  also carries the group's icon (fetched and cached the same way the
  status line's already does — reused, not re-fetched, wherever the
  same group shows up), shown right-aligned next to its name in the
  picker. Picking a group still gets one more fresh, uncached
  permission check right before the Kick/Ban dialog opens — the cache
  is a shortlist for the picker, not the last word on whether the
  action's actually allowed.
- `temp_bans.py` — tracks active temp bans locally (who, which group,
  when it expires) in `~/.ascended_quickmod/temp_bans.json`. Checked by
  two timers in `main.py`: a precise one retargeted at whichever ban
  expires soonest (plus a small buffer) every time the list changes —
  a ban placed, one unbanned early, one auto-expired, or the app
  starting up — and a flat 5-minute poll underneath it as a safety net
  in case the precise one ever gets out of sync. Either way, VRChat's
  real unban API gets called and the result logged to the AAR. Time
  keeps moving whether you're watching it or not — this makes sure
  something is.
- `aar_dialog.py` — the **Reports** menu: **View AAR** (tooltip "After
  Action Review", the whole log) plus four filtered views — **Show
  Bans**, **Show Kicks**, **Show Notes**, **Show WL** (each with a
  matching "Show X from the AAR" tooltip) — all five opening the SAME
  dialog, just constructed with a different `action_filter` from
  `aar.ACTION_CATEGORIES` (Bans covers both `ban` and `unban`, since
  they're the same ban's lifecycle; **WL covers the full watchlist
  lifecycle** — added, removed, a removal requested, and an approver's
  approved/rejected/cleared/confirmed-removal decision, seven action
  strings under one category). Every view keeps the full button row:
  **view, copy to clipboard, save to a `.md` file, Submit to Discord,
  or Clear**. Submit to Discord auto-picks if you've only configured
  one target (Config → Discord Integration), otherwise asks which;
  splits into multiple messages if the report is over Discord's
  2000-character limit rather than truncating it — half a record is
  worse than a few extra pings. **Clear on a filtered view only
  removes that category from the overall AAR** — clearing Show Kicks
  leaves every ban, note, and watchlist action exactly where it was;
  only View AAR's own Clear wipes everything. Always asks for
  confirmation first, wording scoped to match (never touches anything
  already applied on VRChat either way).
- Watchlist actions logging to the AAR at all is new — `watchlist_
  submit.py`'s shared add path (covers all three add entry points:
  right-click menu, Note dialog, the Watchlist window's manual-add
  form) and every deliberate remove (right-click, Note dialog,
  Watchlist window's Remove Selected) now write an entry, same as
  kick/ban/note always have. So does an approver's Approve/Reject/
  Clear/Confirm Removal decision in the Review Queue — that one
  genuinely wasn't logged before this pass, caught while building
  Show WL. Automatic, sync-driven changes (a background prune when the
  shared sheet says an entry's no longer active, a display-name
  refresh) are deliberately NOT logged — those aren't a mod's direct
  action, same reasoning kick/ban/note already followed.
- `image_utils.py` — tiny shared helper that fetches an image's raw
  bytes through the authenticated VRChat session. Kept Qt-free on
  purpose; callers turn the bytes into whatever they need (a QPixmap
  for the list delegate, a base64 data URI for inline `<img>` tags in
  rich text).
- `icon_row_delegate.py` (was `player_list_delegate.py`, renamed once
  it stopped being player-specific) — custom paint logic that draws
  small icon pixmaps at the **right edge** of a row. `QListWidgetItem`
  only supports `.setIcon()` at the left edge, so an icon at the end
  next to the text needed a real delegate rather than a built-in
  option. Reused by two lists: the player list shows one icon per
  group a player is in that you ALSO moderate (per
  `group_mod_cache.py`) — could be zero, one, or several, side by
  side, not just the group hosting the current instance — and the
  "Grp Kick From"/"Grp Ban From" pickers show one icon per row, that
  group's own. **Hovering any icon shows that group's name as a
  tooltip** — real per-icon hit-testing (`helpEvent`), not just one
  tooltip for the whole row, so a player in three of your groups shows
  three icons that each name their own group on hover.
- `permission_check.py` — figures out whether you can moderate the
  current group's instances, shown as a 🟢/🔴 traffic-light dot right
  before the group name, and used to grey out Grp Kick/Grp Ban (both
  in the right-click menu and the profile dialog) when you're known
  not to have permission there. Same approach for **Invite permission**
  separately. Matches against the group's own permission catalog (name
  + human-readable description) rather than a hardcoded guessed string,
  since VRChat doesn't publicly document a fixed name for this — more
  reliable, self-correcting if VRChat ever renames things. Hover the
  instance line (or a greyed-out menu item) for a plain-English
  explanation.
- `instance_info.py` — turns the raw instance string from the log into
  a human-friendly label (e.g. `wrld_c16e4dee-...:15867~group(...)`
  becomes "Idle Home — Group Public (US East)"). World/group names are
  looked up via the API and cached, so this only makes network calls
  the first time you see a given world or group. **The group icon now
  appears right after the group name** in the status line (fetched
  once per group, cached — icon art is static, unlike the permission
  check which is deliberately re-fetched every time). The raw ID stays
  visible too, smaller text under the friendly name — nothing hidden,
  logs and AAR entries still use the raw ID throughout.
- `trust_rank.py` — maps a player's VRChat tags to a Trust Rank and
  color (matches VRChat's own nameplate colors — Trusted User is
  purple, obviously the correct color for anything trustworthy, Known
  User orange, etc). Confirmed against VRChat's own tag documentation,
  including their confusing internal naming (the `system_trust_trusted`
  tag actually means "Known User" rank, not "Trusted User" — handled
  here so nothing else in the app has to carry that quirk around). Also
  has `RANK_SORT_ORDER`, used by the player list's "Sort by: Rank"
  option.
- `player_profile.py` — bundles trust rank, age verification, and
  VRC+ subscriber status (all three come from the same profile lookup,
  one cache entry covers all of them). Age-verified players get a 🪪
  badge, active VRC+ subscribers get a 💎 badge, right after their name
  in the list. A throwaway account will typically have neither — that's
  the point, a quick "how invested is this account" read at a glance.
  (The group membership icon(s) shown for actual group members are
  separate — that's each group's real icon art, drawn by
  `icon_row_delegate.py`, not a badge emoji.)
- `profile_dialog.py` — right-click a player → View Profile opens
  this. Loads everything VRChat's profile endpoint returns (trust rank,
  badges, pronouns, status, bio, join date, last login/platform,
  current note, avatar thumbnail) into a scrollable read-only view —
  always fetched fresh, never cached, since a profile view should show
  the present moment, not a memory of one. **Profile picture uses
  `iconUrl`** (VRChat's own pre-resolved picture) rather than
  `currentAvatarThumbnailImageUrl`/`userIcon` — those are often blank
  even on accounts with a clearly visible profile picture; confirmed
  against a real account where that was exactly the case. Has an
  **"Open Web Profile"** button (also in the right-click menu) that
  opens `vrchat.com/home/user/{id}` in the browser — no documented
  `vrchat://` deep link for opening a specific user's profile *in-game*
  the way VRCX's instance-invite launch link works (checked both
  VRChat's docs and VRCX's own source), so this is the closest real
  equivalent. **Display Name and User ID are click-to-copy** (hand
  cursor + hint on hover — click rather than pure hover-copy, since
  copying just from passing the mouse over text risked accidental
  copies while reading). Has a **Moderation** bar at the bottom with
  Note/Grp Kick/Grp Ban buttons — same dialogs as the right-click menu,
  reachable without closing the profile first, greyed out under the
  same no-group/no-permission rules.
- `discord_targets.py` — local storage for Discord webhook targets the
  AAR report can be sent to, in
  `~/.ascended_quickmod/discord_targets.json`. Each target is one
  Incoming Webhook (Discord's lightweight, officially supported way to
  post into ONE specific channel — no bot needed). A webhook URL is
  created from that channel's own settings and IS the credential, so
  treat that file like a saved password. Supporting multiple groups'
  Discords is just multiple named entries here, since each webhook is
  already tied to one specific channel — no lightweight "browse servers
  and channels" option without running a full bot (OAuth, guild/channel
  discovery, a bot token to manage), which felt like the wrong
  trade-off for what this needs to be.
- `discord_api.py` — sends text OR files to a Discord webhook.
  `send_report()` splits text over Discord's 2000-character limit into
  multiple sequential messages rather than truncating it — a
  moderation report silently losing its second half would be worse
  than a few extra messages in the channel. `send_file()` uploads an
  actual file as an attachment (used by the Watchlist's "Post to
  Discord") — needs a different request shape than plain text
  (multipart/form-data with a `payload_json` field alongside the file),
  confirmed against Discord's own file-upload docs before building it.
  Both surface Discord's rate-limit response (429 + `retry_after`)
  directly rather than silently retrying — no pretending everything's
  fine when it isn't.
- `appearance_settings.py` / `wallpaper_utils.py` — local storage and
  image processing for Config's Appearance section: wallpaper (player
  list only — automatically blurred + darkened via Qt's own
  `QGraphicsBlurEffect` so names/badges/rank colors stay readable on
  top, no extra image library needed; **falls back to the Ascended
  logo if you haven't set your own**), font family, font color, and
  the **player-list update interval** (in seconds — how often the log
  file gets re-checked). **Wallpaper Mode dropdown** — Fill (scale to
  cover, crop the overflow — the original behavior, no distortion but
  crops edges), Stretch (exact fit, ignoring aspect ratio — the one
  mode that CAN distort), Center (actual size, only scaled down if it
  wouldn't otherwise fit, never upscaled past its real resolution), or
  Tile (repeated at native size). All four still get the same
  blur/darken pass — composited first, then blurred as one canvas, so
  Tile doesn't get hard seams at each repeat's edge. **Font color
  deliberately never touches
  player trust-rank colors** — those come from each row's own
  `setForeground()`, which Qt honors over a general stylesheet color;
  confirmed with a live test (rank purple stayed rank purple even
  after applying a bright green font color app-wide — some colors mean
  something and shouldn't be overwritten by decoration). **Wallpaper
  reprocesses automatically as the window resizes** — a QSS
  `background-image` has no equivalent of CSS's `background-size:
  cover`, so growing the window past a pre-baked wallpaper's size used
  to leave gaps around it; `main.py`'s `resizeEvent` now debounces a
  re-apply (200ms after resizing actually stops, not every frame of a
  drag — reprocessing runs a real blur pass, not something to redo
  continuously while the mouse is still moving) so it always covers
  whatever size the list actually is.
- `invite_dialog.py` — right-click a player → Invite (group instances
  only, greyed out without invite permission). Sends a real group
  membership invite via `POST /groups/{id}/invites` — VRChat has no
  separate "invite to just this instance" web action, so this invites
  them to join the group, confirmed against the actual endpoint.
- `unban_dialog.py` — the **UN-Bans** menu (top-level, next to
  Reports — a direct click, not a dropdown). Lists every temp ban
  still pending auto-expiry, with time remaining shown in whichever
  unit is actually still useful — days while there's at least one
  left, then hours, then minutes as it gets close — multi-select, and
  a real early-unban action that logs to the AAR same as everything
  else. Second chances, tracked properly.
- `watchlist_categories.py` — different reasons for being on the
  watchlist get different treatment, not one generic caution sign:
  **Predator 🚨, Stalker 👁, Troll 🎭 are genuine threats and blink**
  (bright/dim, same mechanism as before); **PoI 🔍, VIP ⭐, Creator 🎨
  are informational tags and show a steady color, no alarm** — a VIP
  or a known creator showing up isn't a caution, so nothing flashes
  for them. Not every glow means danger. "Other" is the fallback for
  anything unrecognized (including entries saved before categories
  existed).
- `watchlist_submit.py` — the single shared "add this player to the
  watchlist" logic used by all three entry points (right-click menu,
  Note dialog, Watchlist window's manual-add form). **Fixes a real
  bug**: the right-click and Note dialog paths originally only ever
  did a local-only add, with zero connection to Sheets sync regardless
  of whether it was configured — only the Watchlist window's form
  actually submitted anything. All three now behave identically: if
  sync is configured, this does the fresh duplicate/cleared check and
  submits for real; if not, falls back to a local-only add, same as
  before sync existed.
- `import_review_dialog.py` — the batch review table shown after
  Import. See the Watchlist bullet below for the behavior; this file
  is the actual table UI (Include checkbox, editable User ID/Display
  Name/Reason/Category per row, live status column) plus the batch
  check and submit logic.
- `watchlist.py` / `watchlist_dialog.py` — the **Watchlist** menu
  (also top-level, next to UN-Bans). Flag a player for extra attention
  (with a category) from the right-click menu, from the Note dialog,
  or add one manually right from the Watchlist window itself — all
  three now go through `watchlist_submit.py` above. If a watchlisted
  player shows up in the current instance, their row shows their
  category's icon and color — blinking only for genuinely threatening
  categories (checked every ~600ms, but a no-op the moment nobody
  *blinking* is present, so VIPs/Creators sitting in the list cost
  nothing extra). Overrides both rank color and the departed-grey.
  **"Remove Selected" goes through the same approval gate as adding
  does** — doesn't delete anything directly, submits a removal request
  (flips the sheet row to `pending_removal`), and the player stays
  listed/blinking until an approver confirms it from the Review Queue
  (same principle as a new submission not going live until *it's*
  approved — fixes a real bug where a plain local delete would just
  get silently overwritten by the next sync). The Review Queue shows
  removal requests alongside new submissions (labeled distinctly), and
  its buttons adapt to context: Reject is disabled for a removal
  request (no sensible "reject the removal" outcome distinct from just
  denying it), and Clear relabels itself to **"Confirm Removal,"**
  sending a `removed` status rather than `cleared` for that case —
  Approve still just means "deny the removal, keep them listed" either
  way, no special-casing needed. Sync itself now properly **prunes**
  local entries the sheet says are no longer active (fixed the actual
  root cause: sync previously only ever added/updated, never removed,
  so nothing could ever actually leave the local list once synced) —
  entries the sheet has never heard of at all (genuinely local-only)
  are left untouched. Also supports multi-select removal, export as
  JSON, and **posting the whole list to Discord as a file attachment**
  (not pasted text) via `discord_api.send_file()`. **Sync Now only
  ever pulls** from the sheet down into Guardian — pushing (both new
  entries and removal requests) only happens automatically at the
  moment of the action, via `watchlist_submit.py`/
  `sheets_watchlist.request_removal()`. **Import opens a separate
  batch review window** (`import_review_dialog.py`) rather than adding
  entries directly — every imported row gets checked against a single
  fresh pull of the shared list (one network call covers the whole
  batch, not one per row), each field editable right in the table
  before submitting, rows already pending/approved/rejected on the
  shared list automatically skipped. A "cleared" row gets the same
  soft-warning treatment a single Add gets, just batched into one
  confirmation listing everyone affected instead of a popup per row.
- `sheets_watchlist.py` / `watchlist_sync_settings.py` /
  `watchlist_sync.gs` / `SETUP.md` — the shared, cross-team Watchlist
  backend. **Guardian only ever reads the sheet via its published CSV
  export** (no login needed) — a single shared Google Sheet's
  `Watchlist` tab holds every entry, with a `status` column
  (`pending`/`approved`/`cleared`/`rejected`/`pending_removal`/
  `removed`) and a `category` column (see `watchlist_categories.py`
  above); only `approved` rows count for the live blink feature.
  **Writes go through a separate Google Apps Script Web App**
  (`watchlist_sync.gs` — paste it in via Extensions → Apps Script, full
  walkthrough in `SETUP.md`), since the CSV export itself is read-only.
  Before submitting anything, Guardian does a **fresh pull** (never
  the local cache) specifically to catch someone else's very recent
  submission or a prior review — already `pending`/`approved` blocks
  the submission outright, `rejected` blocks it with an explanation,
  and a `cleared` entry shows a **soft warning** naming who cleared it
  and when, letting the mod decide whether to resubmit anyway (this
  reuses the existing row rather than creating a duplicate).
  **`user_id` is the only thing ever matched on** — display names
  drift, IDs don't; a player's display name gets opportunistically
  corrected (locally and pushed to the sheet) whenever Guardian happens
  to look them up during normal moderation and notices it's changed.
  **Review permission is a plain allowlist of VRChat user IDs baked
  directly into the Apps Script** — enforced server-side, so Guardian
  can't be tricked into letting an unauthorized reviewer
  approve/reject/clear anything. The Watchlist window's **Review
  Queue** section shows pending submissions with Approve/Reject/Clear
  buttons for anyone actually on that allowlist (others just get the
  script's rejection message back). A background timer (interval
  configurable in Config, default 10 minutes) pulls approved entries
  automatically; **Sync Now** in the Watchlist window does it on
  demand. Sync **upserts** rather than add-if-new — a category or
  reason correction made on the sheet after the fact actually
  propagates locally on the next sync, rather than a synced entry
  silently protecting its first-ever value forever.
- `config_dialog.py` — Guardian's settings window (account menu → your
  username → **Config...**, right above Sign Out). Four sections:
  **Watchlist Sync** (the two Google Sheets URLs, plus a Test
  Connection button), **Appearance** (wallpaper/font/font color/update
  interval, applied live via a signal `main.py` listens for — no
  restart needed), **Discord Integration** (add/remove webhook
  targets, with a **Test** button that sends a real, harmless test
  message to confirm a webhook actually works before you save it), and
  **Updates** (on-demand buttons that trigger the same content/app
  checks `app_updater.py` already runs automatically at startup — see
  below).
  **Appearance also has Overlay Mode** — built for pinning Guardian in
  VR via XSOverlay or OVR Toolkit's window capture (same feature, same
  reasoning, as Ascended STT's version). Withholds the player-list
  wallpaper entirely (a flat panel captures more reliably through
  generic desktop-window capture than a photo does) and switches
  structural borders — the player list, dropdowns, text inputs —
  over to whatever font color is already set, so the panel reads as
  one consistent color in a headset. Deliberately leaves the
  action-colored buttons and every trust-rank/watchlist color alone —
  those carry real moderation meaning, not just decoration, and this
  isn't the excuse to flatten that. Your wallpaper path isn't cleared;
  turning this back off restores it exactly as it was.
- `app_updater.py` — two independent checks, on purpose. Content
  (`style.qss`, the logo/icon files — everything else is Python baked
  straight into the exe, not loose data) is checked and applied fully
  automatically in the background at startup by comparing
  `content_version.txt` against GitHub, and self-heals before the
  window even opens if any of those files go missing entirely. The app
  itself can't self-replace its own running exe on Windows, so that
  check just compares `APP_VERSION` against GitHub's latest release
  and surfaces a dismissible banner with a link above the footer if
  there's something newer — same manual download-and-swap step as
  today, just not left to chance.
- `about_dialog.py` — opened by the footer's heart icon (see `main.py`
  below). Credits, an **Ascended VRChat Group** button, an **Ascended
  Discord** button, and a **☕ Buy us a coffee** donate button — same
  three links/donation blurb as the Ascended STT app, since it's the
  same community, the same funding, the same reason any of this exists
  at all.
- `startup_overlay.py` — a checklist overlay covering the whole content
  area (status line, instance list, footer — everything below the menu
  bar, which stays usable throughout) while the window's still getting
  ready, same idea as Ascended STT's loading screen (real steps, not a
  fake spinner), just native Qt widgets instead of HTML/CSS/JS since
  Guardian has no web layer. (Sizing this to just `player_list`'s own
  geometry instead was tried and reverted — it pushed the main window
  wider.) Loading settings → finding the VRChat log
  file → checking temp bans → syncing the watchlist → Ready, each with
  the same ○/●/✓/✕ pending/active/done/error icons STT's checklist
  uses. **Rows fade in one after another, staggered down the list**
  (`QGraphicsOpacityEffect` + `QPropertyAnimation` per row, since QSS
  alone can't animate opacity) rather than all appearing at once.
  Deliberately doesn't wait on "Update Perms"'s background scan or the
  app-update check — both were already designed to run silently after
  the window's usable, and making them block a checklist would undo
  that. Finishes with a **"LET'S GO!!!"** that cycles through the full
  RGB hue range for a full 3 seconds — long enough to actually watch
  it happen — before the overlay clears (same effect STT's version got
  — CSS `hue-rotate` there, a QTimer nudging a
  `QColor.fromHsv()` here, since QSS has no filter property).
- `main.py` — the actual app window, built with **PySide6** (Qt).
  Shows the login screen first, then a live list of who's in your
  current instance with a human-readable instance name, a **🟢/🔴
  permission traffic light**, and the **group's icon** shown next to
  the group name (group instances only — fetched fresh on every
  instance change for the permission check, icon cached since art
  doesn't change), **color-coded by trust rank** with
  **age-verified/VRC+ badges** and a **group-icon marker for members
  of the current group** (via a custom list-row delegate, since
  `QListWidgetItem` can only put an icon on the left), all looked up
  once per player and cached, not re-fetched every poll. **"Players in
  current instance:" shows a live count against the world's own
  capacity** ("12 / 40") — capacity comes from the SAME world lookup
  that already resolves the friendly instance name, cached alongside
  it (one request, not two), and the count only tallies players
  actually PRESENT, not departed entries still shown greyed out below
  them. Omits the "/ capacity" part entirely if it couldn't be
  resolved, rather than showing a placeholder for unknown data.
  **"Sort by:" dropdown** above the list — Name, Connection Time (newest first),
  Rank, or Status (present before departed). **Picking the same
  category twice in a row flips between ascending and descending**;
  switching to a different category always resets to its natural
  direction. **Players who leave stay in the list, greyed out, showing
  "— left Xh Ym ago"**, instead of vanishing immediately — a mod can
  still act on someone who just left (Grp Kick/Ban target group
  membership, not instance presence, so this still holds). Departed
  entries auto-prune after 6 hours (checked every 5 minutes, and this
  same tick refreshes the displayed "left X ago" time even when
  nobody's actually due for removal — fixed a bug where that text used
  to freeze at whatever it said the moment someone left; time keeps
  moving, the display should too). **Watchlisted players show their
  category's icon and color** wherever they appear in the list
  (blinking only for genuine-threat categories), including ones synced
  down from the shared Google Sheet if configured. Your username sits
  top-right in the menu bar as a dropdown — **Config** and **Sign
  Out** (deliberately two clicks for Sign Out, since it sits right
  next to the window's close button and a single-click link there was
  too easy to hit by accident — some doors deserve two knocks).
  **Reports menu** has View AAR Report (Submit to Discord lives there
  too — see `aar_dialog.py`); **UN-Bans** and **Watchlist** sit next
  to it as their own top-level items. Right-clicking a player gives
  **View Profile, Open Web Profile, Note, Invite, Grp Kick, Grp Ban,
  and a WatchList toggle — all real, wired up, and tested**;
  Invite/Grp Kick/Ban grey out (hover for why) when there's no group
  instance to act against, or permission says no. Badges never leak
  into note text, AAR entries, or dialog titles — only the plain
  display name does. Both the window's title-bar icon and the
  app-wide taskbar icon are set from `ascended_logo.png`; a proper
  multi-resolution `ascended_logo.ico` is also included for bundling
  into an executable. **A footer bar sits at the very bottom of the
  window**, matching Ascended STT's layout: a power icon (left,
  confirms before shutting Guardian down), a gear icon (left, opens
  Config), centered copyright text, and a heart icon (far right,
  opens `about_dialog.py`'s About/Support window). The three icon
  buttons' colors track Config's custom font color the same way STT's
  heart does — set directly on each button in `_apply_appearance()`
  rather than through `style.qss`, since a plain stylesheet rule there
  would lose to `style.qss`'s own `QToolButton` base color.

## How to run it

You'll need this on the same PC that runs VRChat (it needs to read
VRChat's log folder — Guardian watches, it doesn't summon).

1. Make sure you have Python 3.10+ installed (`python --version` to
   check).
2. Put all the `.py` files, `requirements.txt`, and `style.qss` in the
   same folder.
3. Open a terminal in that folder and install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Run it:
   ```
   python main.py
   ```
5. Log in with your VRChat username/password. If your account has 2FA
   on, you'll get a second screen for the code. Leave "Remember me on
   this PC" checked (the default) and you won't need to log in again
   next launch.
6. Launch VRChat (if it's not already running) and join a world. The
   player list should already show who's there when the app opens (it
   catches up from the log), and update live from there.

`log_watcher.py` has zero dependencies beyond Python's standard
library. `vrchat_api.py` needs `requests`; `main.py`/`login_dialog.py`
need PySide6.

## Building a standalone .exe

For handing Guardian to someone without Python installed — everyone
deserves to run this without setting up a whole dev environment first.
One-time setup:
```
pip install pyinstaller
```
Then, from this folder:
```
pyinstaller Guardian.spec
```
The finished package lands in `dist/Guardian/` — `Guardian.exe` plus
an `_internal/` folder next to it (icon baked into the exe, no console
window). It bundles PySide6/requests, so the target PC needs nothing
installed — `dependency_check.py` skips its pip-install check entirely
for a frozen build (`sys.frozen`), since there's nothing to
`pip install` inside a bundled exe anyway. **Ship the whole
`dist/Guardian/` folder together** (zip it up) — `Guardian.exe` alone
won't run without `_internal/` sitting next to it, same as a spellbook
without its components. `build/` is safe to delete and regenerate.
Local data (session, AAR log, watchlist, etc.) still lives in
`~/.ascended_quickmod/` either way, same as running from source.

This ships as a folder (`onedir`), not a single self-extracting exe
(`onefile`) — see the next section for why.

### Windows Defender / antivirus flagging

Same honest picture as our sibling project, [Ascended
STT](https://github.com/hex-one/Ascended-STT) — a genuinely common
issue for unsigned PyInstaller executables generally, not something
specific to Guardian having done anything wrong. I'd rather tell you
straight than let you find out from a scary popup. Worth understanding
*why* before deciding what to do about it.

**Why it happens:**

1. **No publisher identity.** An unsigned `.exe` has no verifiable
   "who made this" information. Windows SmartScreen and Defender's
   cloud reputation checks weigh this heavily — a brand-new, unsigned
   file starts with zero trust regardless of what it actually does.
   Same energy as a new player showing up to your server with no
   history — the game treats you as unknown, not as guilty.
2. **Runtime self-extraction** (a single-file exe that unpacks itself
   into a temp folder and runs from there) is a behavioral pattern
   malware droppers also use — this is why `Guardian.spec` builds
   `onedir` (a plain folder) rather than `onefile`, sidestepping that
   pattern entirely.
3. **Guardian specifically logs into VRChat with a username and
   password**, and sends them over the network as part of that login.
   That's the actual feature — VRChat's own official login API, the
   same one the real VRChat client and website use — but "a program
   that asks for credentials and sends them somewhere" is also exactly
   the surface-level shape of a credential-stealing tool, and
   heuristic engines can't tell intent from behavior alone. Worth
   restating plainly since it's the one thing worth being extra honest
   about: Guardian **never saves your password anywhere** — see
   `vrchat_api.py` — only the session cookies VRChat's API hands back
   *after* a successful login, stored locally in
   `~/.ascended_quickmod/session.json`. Treat that file like a saved
   password, but Guardian itself never holds your actual password past
   the moment you type it into the login screen. Trust, once earned,
   still has to be handled carefully — that's the whole design.

**What's already applied in `Guardian.spec`:** `upx=False` (no
compression — real, free mitigation against a known evasion-technique
false-positive trigger; trade-off is a larger folder on disk) and the
`onedir` layout described above.

**What would help further, with real trade-offs:** the actual fix is
**code signing** — a certificate from a Certificate Authority
(DigiCert, Sectigo, SSL.com, etc.), roughly $70–400+/year with
identity verification, giving Windows a verifiable publisher identity.
Even a signed exe starts with limited reputation on a brand-new
certificate; trust builds over time and downloads, same as anything
real does, not instantly. Free options: submit a build you believe is
a false positive at
[microsoft.com/en-us/wdsi/filesubmission](https://www.microsoft.com/en-us/wdsi/filesubmission)
(see `DEFENDER_SUBMISSION.md` for the full checklist and why it's a
per-build, not one-time, thing), or check
[virustotal.com](https://www.virustotal.com) before distributing to
see exactly which engines flag a given build and why.

**The honest bottom line:** there's no way to *guarantee* zero false
positives on a freshly built, unsigned executable — true of any
PyInstaller app, not a flaw specific to this one. The mitigations
already in the spec are real and free; code signing is the actual fix
if this needs to go out to people who aren't already expecting a
"just trust me" security prompt, but it's a cost/effort call only you
can make. I'll tell you what's true and let you decide — that's the
deal.

## Important: two different things are called "kick" in VRChat

There's an **instant instance kick** (removes someone from the room
right now) and a **Kick from the Group** (removes their group
membership; they can rejoin later per the group's settings). Only the
first one is Photon-only and out of reach — the second is a normal web
API call, and it's what VRCX's own "Kick" button actually does
(confirmed against the same endpoint VRCX uses). **Guardian's Kick is
the real group-kick**, same family as Ban.

(Mute — VRChat's "Force Mic Off" — was removed. It's purely a live
in-game/Photon action with no group-level web API equivalent, so
Guardian could only ever log the intent rather than actually do it,
and a promise Guardian couldn't keep wasn't worth keeping around.)

## Known things to expect

- **Display names, not user IDs, show in the list.** User IDs are
  still captured and used internally for every action (note/kick/ban),
  since VRChat's API works off IDs, not names.
- **Log parsing is confirmed working against a real VRChat log** —
  tested against actual output from your machine, including
  multi-instance session history and non-ASCII display names. The app
  also catches up on the current roster on startup instead of starting
  empty — you shouldn't have to wait to know who's already in the
  room.
- **VRChat only writes ONE current log file at a time**, and starts a
  new one each time you launch the game. If you restart VRChat while
  Guardian is running, restart Guardian too so it picks up the new
  file. (Auto-detecting a log rotation is a reasonable next
  improvement.)
- **Network calls (login, note fetch/save, ban, world/group/permission
  lookups) briefly freeze the window** while waiting on VRChat's
  servers — normally under a second, not worth fixing yet, but movable
  to background threads later if it ever feels laggy.
- **The temp-ban checker runs every 5 minutes**, not continuously — a
  ban set to expire won't be lifted the exact second it's due, just
  within a few minutes of it. Fine for day-granularity bans; flag it if
  you ever want tighter timing. **The departed-player pruner runs on
  the same 5-minute cadence** — someone who left 6 hours and 1 minute
  ago might stick around in the list for up to another 5 minutes before
  disappearing. The 6-hour retention window itself is a constant in
  `main.py` (`DEPARTED_RETENTION_HOURS`) for now, not a UI setting —
  flag it if you want that adjustable without editing code.
- **Connection times come from VRChat's own log timestamps**, which
  are local system time (no timezone marker in the log itself), so
  this is purely "how long ago, on this PC's clock" — not tied to any
  particular timezone standard. Accurate for anyone whose join line
  Guardian actually saw; if a join can't be found (very rare), it
  falls back to "whenever Guardian first noticed them."
- **Group membership icons only see PUBLIC group affiliations.**
  VRChat lets a member hide a specific group from showing on their
  profile — a real member who's done that for the current group won't
  get the icon, since there's no way to see past that setting from
  outside the group's own membership tools. Also worth knowing:
  checking membership adds one more API call per new player (on top of
  the one already made for trust rank/badges), so joining a group
  instance with a full room does a bit more work up front than a
  public instance — still only once per player per session, not
  repeated.
- **Wallpaper is processed once at the size the player list happened
  to be when you clicked Apply** — it does NOT automatically
  re-crop/re-blur if you resize the window afterward. Re-open Config
  and click Apply Appearance again if the crop looks off after a
  resize; auto-reprocessing on every resize event was more complexity
  than felt worth it for a first pass.
- **Invite sends a GROUP membership invite**, not an invite to just
  the current instance — VRChat's web API doesn't have a lightweight
  "invite to this specific instance" action separate from group
  membership, confirmed while building this.
- **Watchlist blinking only costs anything when someone watched is
  actually present** — the timer ticks every ~600ms regardless, but
  it's a cheap set-membership check that bails out immediately if
  nobody on the list is in the room, so this doesn't add ongoing
  overhead in the common case of an empty watchlist. No alarm rings in
  an empty room.
- **AAR export header now reads "Guardian APP"** instead of the old
  "Ascended QuickMOD" naming.
- **Editing the Apps Script requires a redeploy, not just a save.**
  Google treats "save" and "make the live deployment actually run the
  new code" as two separate steps — after editing `watchlist_sync.gs`
  (e.g. to update the approver allowlist), use Deploy → Manage
  deployments → edit → New version → Deploy, or the change won't take
  effect. Covered in `SETUP.md`.
- **Display-name revalidation only happens when Guardian independently
  looks a player up anyway** (the same per-player fetch that already
  gets their trust rank/badges, once per session) — not a separate
  background check hunting for name changes, so a watchlisted player
  who never shows up in an instance won't get their name refreshed
  until they do.

## What's next (in rough order)

1. **Your custom QSS** — drop it into `style.qss` whenever it's ready;
   it'll apply automatically. Flag it if you want glow effects
   specifically, since those need a small bit of Python
   (QGraphicsDropShadowEffect) alongside the QSS itself.
2. Anything else that comes up as the team actually uses this day to
   day. This project grows the way anything worth building does — one
   real need at a time, not a spec written in a vacuum.

Stay present. Watch the room. — Jasper
