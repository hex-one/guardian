# Guardian — Steam store page copy

Ready to paste into Steamworks once the AppID exists. Steam's store
page editor uses its own lightweight markup (`[b]`, `[i]`, `[list]`,
`[*]`, `[h1]`, `[url=...]`, etc.) rather than Markdown — the section
breaks and bullets below translate directly; swap `**bold**` for
`[b]bold[/b]` and so on when you paste. Exact field character limits
and current image-asset specs (capsule/header/hero art) are Valve's to
publish, not mine to guess at — check Steamworks' own docs for
whatever's current when you're actually filling the page in.

---

## Short description (search results / library blurb)

> Real-time VRChat group moderation. Watch who's in your instance, and
> put Note, Kick, and Ban one right-click away — free and open source.

(163 characters — comfortably under Steam's short-description limit
even after a round of edits.)

## About This Game (main store page body)

**Guardian watches your VRChat group instance so you don't have to
squint at a log file to do it yourself.**

Built for moderation teams who need to know who's in the room, right
now, without alt-tabbing to a browser mid-incident. Guardian reads
VRChat's own log in real time and gives you a live, color-coded player
list — trust rank, age-verification and VRC+ badges, group-membership
icons — the moment someone joins.

**Moderation, one right-click away:**
[list]
[*] **Note** — pulls the player's actual current VRChat note before
you write a new one, so you're never overwriting something you didn't
know was there.
[*] **Grp Kick / Grp Ban** — the real thing, through VRChat's own
group-moderation API. Requires a reason, confirms before doing
anything destructive, and logs every attempt — success or failure —
to a local audit trail.
[*] **Temporary bans** with a real number-and-unit picker (4 hours, 6
minutes, 21 days — whatever the moment calls for), auto-lifted the
moment they expire.
[*] **Watchlist** with category-specific icons (Predator, Stalker,
Troll blink; VIP, Creator, PoI just show steady) and optional
cross-team sync via a shared Google Sheet, so your whole mod team is
watching the same list.
[/list]

**Built to stay out of your way:**
[list]
[*] Players who leave stay visible, greyed out, so you can still act
on someone who just walked out.
[*] A green/red traffic light shows whether you actually have
moderation permission in the current group — before you try something
that'll just fail.
[*] After Action Report (AAR) logging keeps a local, pullable record
of every action taken — separate from VRChat's own note history,
built to be posted straight to your team's Discord.
[*] **Overlay Mode** — pin Guardian in VR via XSOverlay or OVR
Toolkit's window capture. Skips the wallpaper, borders match your
font color, tested clean in an actual headset.
[/list]

**Free. Open source. GPL-3.0.** Guardian is built for the Ascended
VRChat community and shared with anyone who wants it — the full
source is on GitHub, no strings attached.

## System requirements

- **OS:** Windows 10/11 (64-bit)
- **Other:** Needs to run on the same PC as VRChat (reads VRChat's
  local log file). A VRChat account with group-moderation permissions
  is required to actually use the moderation actions — Guardian works
  fine as a read-only player-list viewer without them.

## Tags (suggested)

Utilities, VR, Moderation, Social, Free to Play

## Legal / EULA note

GPL-3.0 licensed — see the repository's `LICENSE` file. Steam's own
partner-agreement legal boilerplate applies on top of that; nothing
here overrides what Valve requires on the store-page legal tab.
