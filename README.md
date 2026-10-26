# 🔒 SaveVault

**Never lose a save game again.**

SaveVault backs up your game save files directly to your own Google Drive — no third-party servers, no subscriptions, no accounts to create. Just sign in with Google and your saves are safe.

---

## Download

Grab the latest `SaveVault.exe` from the [Releases page](../../releases). No installation needed — just run it.

**Requirements:** Windows 10 or 11 (64-bit) · A Google account · That's it.

---

## How It Works

1. **Sign in** with your Google account
2. **Add a game** — give it a name and point SaveVault at the folder where it stores saves
3. **Click Sync** — your saves upload to a `Save Games/<Game Name>/` folder in your Drive
4. On any other PC, sign in again and sync back down

SaveVault mirrors your entire save folder structure — including all subfolders — exactly as it is on your machine.

---

## Your Data, Your Drive

SaveVault uses Google's `drive.file` permission scope. This means:

- ✅ It can **only** see files that it created — nothing else in your Drive
- ✅ Your saves go directly from your PC to your Google account — no middleman
- ✅ No telemetry, no analytics, no external servers of any kind
- ✅ Delete the app and your saves stay in your Drive forever

---

## Adding a Game

1. Click **＋ Add Game** in the left panel
2. Type the game name (this becomes the folder name in your Drive)
3. Click **Browse…** and select the folder where the game stores its saves
4. Click **Add Game**

Not sure where a game stores its saves? Check [PCGamingWiki](https://www.pcgamingwiki.com) — it lists save locations for thousands of games.

---

## Syncing

- **Sync This Game** — syncs only the selected game
- **Sync All** — syncs every tracked game one after another
- If a file changed on **both** your PC and Drive since the last sync, SaveVault asks you which version to keep — file by file, with timestamps shown for both sides

---

## Restoring Saves on a New PC

1. Install SaveVault and sign in with the same Google account
2. SaveVault detects your existing `Save Games/` folder in Drive automatically
3. A dialog asks you to link each game to its local save path on the new machine
4. Hit **Sync** — your saves come back down

---

## Troubleshooting

**"Access blocked" or "Error 403: access_denied" when signing in**
→ Click **Advanced** → **Go to SaveVault (unsafe)** on the Google warning screen.
This appears because the app hasn't gone through Google's formal review process yet.
It is safe — Google shows this for all unreviewed apps regardless of what they do.

**Sign-in browser window doesn't open**
→ Check that your firewall or antivirus isn't blocking localhost connections.
Try temporarily disabling it to confirm, then add an exception for SaveVault.

**Files not showing up after sync**
→ Make sure the local path still exists and hasn't moved. Remove and re-add the game
if the path has changed.

**Saves aren't all backed up**
→ Make sure you selected the correct root folder for that game's saves.
SaveVault backs up everything inside that folder including all subfolders.

---

## Want to Build It Yourself?

If you'd prefer to use your own Google Cloud credentials instead of the ones bundled
in this release — for example, if you want to host this for a group of friends on
your own quota — see **[INSTRUCTIONS.txt](INSTRUCTIONS.txt)** for a full step-by-step
guide to building SaveVault from source with your own credentials.

---

## License

MIT — free to use, modify, and distribute.
