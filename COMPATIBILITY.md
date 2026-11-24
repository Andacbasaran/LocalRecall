# OS & Desktop Environment Compatibility Matrix

LocalRecall v1.0.0 runs natively across **Windows**, **macOS**, and **Linux** using pure CPU inference (`0 MB VRAM`). Below are tested capabilities, permissions, and known platform notes.

## Operating Systems

| Platform | Architecture | Capture (`mss`) | Active Window & Privacy Shield | Idle Sleep | Global Hotkey | Autostart | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Windows 11 / 10** | `x86_64` | ✅ Native | ✅ Win32 API (`QueryFullProcessImageNameW`) | ✅ `GetLastInputInfo` | ✅ `Ctrl+Shift+Space` (Win32 `RegisterHotKey`) | ✅ `HKCU\...\Run` | **Full Support** |
| **macOS 12+ (Monterey – Sequoia)** | `arm64` (M1–M4) / `x86_64` | ✅ Native (requires TCC Screen Recording) | ✅ `NSWorkspace` / `lsappinfo` / `osascript` | ✅ `CoreGraphics` | ✅ `Cmd+Shift+Space` (`QShortcut` / Cocoa) | ✅ `LaunchAgents` plist | **Full Support** |
| **Linux (X11)** | `x86_64` / `aarch64` | ✅ Native | ✅ `xdotool` / `xprop` + `/proc/<pid>/comm` | ✅ `xprintidle` / `libXss` | ✅ In-app + DE shortcut | ✅ XDG `~/.config/autostart` | **Full Support** |
| **Linux (Wayland)** | `x86_64` / `aarch64` | ⚠️ XWayland / Portal dependent | ⚠️ Limited by compositor isolation | ⚠️ Compositor dependent | ⚠️ Bind via DE shortcut | ✅ XDG `~/.config/autostart` | **Partial (X11 Recommended)** |

## Platform Setup Notes

### Windows 10 / 11
- **Multi-Monitor Capture:** Select a specific monitor (`Monitor 1`, `Monitor 2`) or **`All Monitors` (`monitor_index=0`)** in *Settings & Engine* to capture your entire virtual desktop.
- **SmartScreen Notice:** Because v1.0.0 is freshly released open-source software, Windows SmartScreen may show an *Unknown Publisher* prompt until code reputation builds or SignPath.io signing is active. Verify `SHA256SUMS.txt` and click *More info → Run anyway*.

### macOS (Apple Silicon M1–M4 & Intel)
- **Screen Recording Permission (Required):** Without permission, macOS only exposes the desktop wallpaper to screen capture APIs. Enable LocalRecall in:
  *System Settings → Privacy & Security → Screen & System Audio Recording*, then restart LocalRecall.
- **First Launch (Unsigned Open-Source App):** If Gatekeeper shows an unverified developer warning, either click **Open Anyway** in *System Settings → Privacy & Security*, or run:
  ```bash
  xattr -cr "/Applications/LocalRecall.app"
  ```
- **Window Title Detection:** Active app names are detected automatically via `NSWorkspace` / `lsappinfo` with zero extra prompts. Granting *Accessibility* permission additionally enables exact frontmost window titles via `System Events` (helpful for browser Incognito/Private tab title detection).

### Linux (Ubuntu, Fedora, Arch, Debian)
- **Recommended System Packages (X11):**
  ```bash
  # Ubuntu / Debian
  sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libdbus-1-3 libxcb-cursor0 xdotool xprintidle
  ```
- **Wayland Sessions:** Wayland intentionally isolates window metadata and raw framebuffer grabs between apps. For full active-window Privacy Shield matching and instant `mss` capture, run an X11 session or bind a desktop-environment shortcut to launch/focus LocalRecall.
- **Headless / CI Testing:** Supported cleanly with `QT_QPA_PLATFORM=offscreen`.

## Built-In Password Manager & Privacy Guard Coverage

LocalRecall normalizes process names across `.exe`, `.app`, full paths, and mixed casing. Blocked out of the box:

- **Password Managers:** `1Password`, `Bitwarden`, `KeePass`, `KeePassXC`, `LastPass`, `Dashlane`, `NordPass`, `ProtonPass`, `Enpass`
- **OS Credential Agents:** `Keychain Access`, `Passwords`, `SecurityAgent` (macOS); `CredentialUIBroker`, `LockApp`, `LogonUI` (Windows); `gnome-keyring`, `gnome-keyring-daemon`, `kwalletd5`, `kwalletd6` (Linux)
- **Private Browser Sessions (Title Keywords):** `Incognito`, `InPrivate`, `Gizli`, `Private Browsing`, `Private Window`, `Tor Browser`
- **Automatic PII & Secrets:** Luhn-validated credit cards, API keys (`sk-`, `ghp_`, `github_pat_`, `AKIA`, `AIza`, `xox*`, JWT), IBAN, US SSN, Turkish TCKN, and 6-digit OTP/2FA codes.

> Tested LocalRecall on a new OS, compositor, or password manager? Open a [Compatibility Report](https://github.com/Andacbasaran/LocalRecall/issues/new?template=compatibility_report.yml) or PR!
