# Publishing Guardian to Steam via SteamPipe

The bridge between "built exe" and "live on Steam." Doesn't touch
anything until you actually run it — safe to read through before your
Steamworks account even clears.

## Before you start

You need, in this order:
1. An **approved Steamworks partner account** with Guardian's app
   created (Steamworks assigns the real **AppID** here).
2. A **Depot ID** under that app — Steamworks → your app → SteamPipe →
   Depots. It usually offers `AppID + 1` as the default; use whatever
   it actually shows you.
3. **`steamcmd`** installed — Valve's command-line tool for talking to
   SteamPipe. Download from
   [Steamworks' SteamCMD docs](https://partner.steamgames.com/doc/sdk/uploading)
   once you're logged into Steamworks (the exact download link/steps
   are gated behind partner login, so no direct link here).
4. A Steam account with **publish permissions** on this app — usually
   the same account you use for Steamworks itself, but large teams
   sometimes use a dedicated build account. Either way, this is a real
   Steam login, so `steamcmd` will prompt for it (and Steam Guard)
   interactively — nothing about that gets automated or stored here.

## 1. Fill in the real IDs

Open both `.vdf` files in this folder and swap `PLACEHOLDER_APPID` /
`PLACEHOLDER_DEPOTID` for the real numbers from Steamworks. That's the
only editing needed — everything else already points at the right
build output.

## 2. Build Guardian

```
cd ..
pyinstaller Guardian.spec
```

This has to happen fresh before every upload — SteamPipe uploads
whatever's sitting in `dist/Guardian/` at the moment you run the
build command below, not some cached idea of what Guardian is.

## 3. Upload

From this folder:

```
steamcmd +login <your_steam_username> +run_app_build app_build_guardian.vdf +quit
```

`steamcmd` will prompt for your password and Steam Guard code right
there in the terminal — this is the one point in the whole pipeline
that's genuinely interactive, on purpose. Nothing in these scripts
stores or automates that login.

If it succeeds, `steamcmd` prints a build ID and the new build shows
up under Steamworks → your app → Builds — sitting there, **not yet
live** on any public branch (that's what `"setlive": ""` in
`app_build_guardian.vdf` buys you). Promote it to `default` from the
Builds page in Steamworks once you've actually smoke-tested it.

## Iterating

Same three steps, every time: rebuild with PyInstaller, re-run the
`steamcmd` upload, promote when you're happy. Nothing here needs to
change between releases except the version you're actually shipping.

## Heads up: this build also has an in-app content-updater

Guardian checks GitHub in the background at startup and quietly
refreshes `style.qss` and the logo/icon art if a newer
`content_version.txt` is published — see `app_updater.py`. That's
genuinely useful for the direct-download build, where Steam isn't in
the picture at all, but it's worth thinking through for a Steam build
specifically: SteamPipe already owns getting players onto the latest
files, and having the app *also* silently patch itself from GitHub
means a Steam build could end up running content that never went
through a Steam build/verification pass — and "Verify integrity of
game files" in Steam could then flag those self-patched files as
modified.

Nothing here disables that automatically — there's currently no
reliable way for the app to detect "I'm running under Steam" without
adding real Steamworks SDK integration, which this project doesn't use
today. Worth deciding before this goes live on Steam: either bump
`content_version.txt` in lockstep with every Steam build so the two
sources never actually disagree, or add a real Steam-detection guard
that skips the automatic content check entirely (the manual "Check for
Content Updates" button in Config could stay either way, since that's
an explicit, on-purpose action). Flagging this now so it doesn't get
silently forgotten once Steamworks access actually exists.
