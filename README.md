# 🔒 SaveVault

**SaveVault** is a Windows desktop application that backs up your game save files to your own Google Drive. No third-party servers, no subscriptions — your saves go directly to a `Save Games/` folder in your personal Google Drive.

---

## Features

- 🔐 OAuth 2.0 sign-in with Google (drive.file scope — only sees files it creates)
- 📁 Track multiple games with individual save directories
- ☁ Automatic sync to `Save Games/<Game Name>/` in your Drive
- ⚡ Conflict detection — if both sides changed, you choose which to keep
- 🔄 Sync All with one click, or sync individual games
- 🖥 Modern dark-themed UI built with CustomTkinter

---

## Privacy Statement

SaveVault requests the `drive.file` scope only. This means:

- It can **only** read and write files that it created.
- It **cannot** browse, read, or modify any other files in your Google Drive.
- No credentials, save files, or metadata are ever sent to any server other than Google's own APIs.
- No telemetry, no analytics, no external network calls beyond Google Drive.

Your saves stay between you and your Google account.

---

## Requirements

- Windows 10/11 (64-bit)
- Python 3.10+ (if running from source)
- A Google account

---

## Setting Up Google Cloud Credentials

SaveVault needs OAuth client credentials from Google Cloud Console. These are **free** and remain entirely under your control.

### Step 1 — Create a Google Cloud Project

1. Go to [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. Click the project dropdown at the top → **New Project**
3. Give it a name (e.g. "SaveVault") and click **Create**

### Step 2 — Enable the Google Drive API

1. In your new project, navigate to **APIs & Services → Library**
2. Search for **"Google Drive API"**
3. Click it and press **Enable**

### Step 3 — Configure the OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**
2. Choose **External** and click **Create**
3. Fill in:
   - **App name**: SaveVault
   - **User support email**: your email
   - **Developer contact**: your email
4. Click **Save and Continue** through the Scopes screen (no extra scopes needed here)
5. On the **Test users** screen, click **Add Users** and add your own Google account
6. Click **Save and Continue**

> ⚠️ While the app is in "Testing" mode, only accounts listed as Test Users can sign in. This is fine for personal use.

### Step 4 — Create OAuth Credentials

1. Go to **APIs & Services → Credentials**
2. Click **+ Create Credentials → OAuth client ID**
3. Select **Desktop app** as the application type
4. Give it a name (e.g. "SaveVault Desktop") and click **Create**
5. A dialog shows your **Client ID** and **Client Secret** — copy both

### Step 5 — Add Credentials to SaveVault

Open `src/auth.py` and replace the placeholder constants near the top:

```python
# src/auth.py  (around line 38)
_CLIENT_ID = "YOUR_CLIENT_ID.apps.googleusercontent.com"   # ← replace
_CLIENT_SECRET = "YOUR_CLIENT_SECRET"                       # ← replace
```

Paste your actual Client ID and Client Secret from Step 4.

---

## Running from Source

### 1. Install Python 3.10+

Download from [https://www.python.org/downloads/](https://www.python.org/downloads/).  
Make sure to check **"Add Python to PATH"** during installation.

### 2. Clone the repository

```bash
git clone https://github.com/yourname/savevault.git
cd savevault
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add your OAuth credentials

Edit `src/auth.py` as described in **Step 5** above.

### 5. Run

```bash
python main.py
```

On first launch, a browser window will open for Google sign-in. After authenticating, SaveVault saves a token to `~/.savevault/token.json` so you won't need to sign in again.

---

## Adding Games

1. Click **＋ Add Game** in the left panel
2. Enter the game name (used as the Drive subfolder name)
3. Click **Browse…** and select the folder containing your save files
4. Click **Add Game** — SaveVault creates the Drive folder immediately

---

## Syncing

- **Sync This Game** — syncs the currently selected game
- **Sync All** — syncs every tracked game sequentially
- If a file was changed on both sides since the last sync, a **Conflict Resolution** dialog appears where you choose which version to keep

---

## Building the .exe with PyInstaller

After adding your credentials and testing that the app runs from source:

```bash
pip install pyinstaller
pyinstaller build.spec
```

The output will be at:

```
dist/SaveVault.exe
```

This is a single, portable executable with no external dependencies. Copy it anywhere and run it.

> **Note:** The `.exe` embeds your OAuth credentials. Do not share it publicly unless you want others to use your Google Cloud quota.

---

## File Locations

| File | Purpose |
|------|---------|
| `~/.savevault/config.json` | Tracked games, local paths, Drive folder IDs |
| `~/.savevault/token.json`  | OAuth token (auto-refreshed, delete to sign out) |

---

## Project Structure

```
savevault/
├── main.py                  Entry point
├── requirements.txt         Python dependencies
├── build.spec               PyInstaller build config
├── README.md                This file
├── assets/
│   └── icon.ico             Application icon
└── src/
    ├── app.py               Root CTk App class (sign-in flow, lifecycle)
    ├── auth.py              Google OAuth 2.0 (token storage, refresh)
    ├── drive.py             Google Drive API wrapper
    ├── sync.py              Diff engine + sync plan execution
    ├── storage.py           Config persistence (~/.savevault/config.json)
    └── ui/
        ├── main_window.py   Main window layout + sync orchestration
        ├── game_list.py     Left panel: scrollable game list
        ├── add_game_dialog.py  Add game modal
        ├── sync_dialog.py   Conflict resolution modal
        └── link_dialog.py   Startup dialog for unlinked Drive saves
```

---

## Troubleshooting

**"OAuth credentials not configured"**  
→ You haven't replaced the placeholder constants in `src/auth.py`. See Step 5 above.

**"Access blocked: SaveVault has not completed the Google verification process"**  
→ Your app is in Testing mode. Add your Google account as a Test User in the OAuth consent screen (Step 3, Test users).

**Sign-in browser window doesn't open**  
→ Try running from a terminal (`python main.py`) to see error output. Ensure your firewall allows localhost connections.

**Files not appearing in the file table**  
→ The local path may not exist or the Drive folder ID may be missing. Try removing and re-adding the game.

---

## License

MIT — do whatever you want, but please don't use this to violate Google's Terms of Service.
