# Whisperer

Whisperer is a Windows-first dictation app with a PyQt launcher, a persistent
Python engine process, a React dashboard embedded in the PyQt window, and a
native overlay for hotkey dictation feedback.

## Quick Start

```powershell
cd "Q:\Whisperer Windows"
.\Launch Whisperer.bat
```

For development without the batch file:

```powershell
python launcher.py
```

The launcher owns the main window, tray icon, and engine process. The engine
loads the selected STT model, handles hotkeys, records audio, updates the
overlay, transcribes, and pastes output.

## Build

The current PyInstaller build uses `whisperer.spec` and embeds the built React
dashboard from `whisperer-app/dist`.

```powershell
cd "Q:\Whisperer Windows"
npm --prefix whisperer-app install
npm --prefix whisperer-app run build
pyinstaller --noconfirm whisperer.spec
```

Output: `dist\Whisperer\Whisperer.exe`

To build the optional installer after PyInstaller finishes:

```powershell
iscc installer.iss
```

## Version 6.0.8

Whisperer 6.0.8 fixes a first-run microphone selection issue found while
testing 6.0.7. When no explicit input device is configured, Whisperer now avoids
obvious virtual or streaming capture endpoints such as Steam Streaming
Microphone, virtual cables, and NVIDIA virtual audio when a real microphone,
line input, or audio interface input is available. Explicit user-selected
microphones still win.

## Version 6.0.7

Whisperer 6.0.7 adds another public-install hardening pass. The installer now
uses a setup mutex, removes stale debug/model/frontend payloads left by older
upgrades before copying the new bundle, and copies the installer log to
`%LOCALAPPDATA%\Whisperer\logs\installer-latest.log` even when setup exits
outside the normal success path.

Frozen startup now checks for the required Qt WebEngine, platform plugin, V8
snapshot, locale, and React dashboard files before Qt loads. If an install is
incomplete or antivirus software quarantined a required file, Whisperer writes
`startup-integrity.log` and shows a direct reinstall/diagnostics message instead
of falling through to a blank window.

## Version 6.0.6

Whisperer 6.0.6 is a final packaging polish pass for public installs. The
PyInstaller bundle now excludes unused Qt WebEngine debug/devtools/QML payloads
while preserving the resources needed for the embedded dashboard, which lowers
download size and reduces install surface area. Release smoke checks now derive
the expected installer version from `config.py` and fail if debug Qt payloads or
model weights creep back into the bundle.

The optional Vosk live-preview downloader now uses a timeout-aware request and
validates archive paths before extraction. Diagnostics collection also captures
more machine-level context for cases where the app cannot get far enough to
write normal launcher logs.

## Version 6.0.5

Whisperer 6.0.5 adds always-on startup diagnostics for severely broken
installations. The launcher, Qt shell, embedded Chromium/WebEngine renderer,
React mount probe, engine launch, engine stdout, and fatal Python faults now
write logs under `%LOCALAPPDATA%\Whisperer\logs` as soon as the process starts.
If that folder cannot be created, Whisperer falls back to the user's temp
folder. Blank WebEngine windows now show a diagnostic page instead of staying
silent. The installer also adds Start Menu shortcuts to open the log folder,
launch Whisperer in diagnostic mode, and collect a scrubbed diagnostics zip.

This release also fixes the frozen WebEngine renderer crash by preserving Qt's
V8 snapshot resources in the PyInstaller bundle. The installer is per-user by
default, writes an Inno setup log, avoids recursive uninstall deletes, blocks
unsupported 32-bit/older Windows installs, and includes complete Open With
entries for the supported media extensions. Built dashboard assets use stable
local filenames and no remote font dependency.

Public auto-update installs now require a valid Authenticode signature on the
downloaded installer. Unsigned local test builds can still be installed
manually, but public releases should be signed before publication.

## Version 6.0.4

Whisperer 6.0.4 fixes installed builds that could appear to do nothing on
Windows 10 by keeping the UI inside the bundled EXE instead of handing off to a
random system Python. The default API engine path also runs from the bundle.

## Version 6.0.3

Whisperer 6.0.3 keeps the normal waveform as the default overlay while leaving
Light Wave available as an experimental Appearance option.

## Version 6.0.2

Whisperer 6.0.2 makes NVIDIA API Parakeet the default device for lightweight
first launch. Local GPU model downloads now require confirmation when the model
is not already cached.

## Version 6.0.1

Whisperer 6.0.1 adds an experimental Light Wave overlay visualizer that can be
selected from Configuration > Appearance while keeping the native waveform
available as a fallback.

## Version 6.0.0

Whisperer 6.0.0 adds the low-latency Parakeet streaming path, adaptive
streaming finalization, smaller microphone chunks for faster partials, a
known-good paste fast path, and an STT provider benchmark in Configuration.

## Version 5.5.5

Whisperer 5.5.5 adds update checks in Configuration so the app can see the
latest GitHub release and launch a downloaded Windows installer when a release
asset is available.

The live overlay update path now targets a 60 Hz feed cadence, and microphone
capture uses smaller audio blocks so the waveform reacts with less visual lag.

## Version 5.5.4

Whisperer 5.5.4 adds hosted speech-to-text backends for users who do not have a
fast local GPU. In Configuration, the GPU selector can now choose a local RTX
5090, a local RTX 4080, Groq API (Whisper), or NVIDIA API (Parakeet).

The Configuration screen stores Groq and NVIDIA API keys in the Windows
credential vault, shows masked saved-key placeholders, and includes test buttons
for validating each provider before starting the engine. Groq uses the Whisper
API, while NVIDIA uses the hosted Parakeet API with chunked long-form handling so
long dictations do not lose the end of the recording.

As of May 2, 2026, Groq provides free API key access with free-plan speech
limits, and NVIDIA's Parakeet NIM page offers free API access for development.
Provider limits and terms still apply, but this means high-quality, high-speed
dictation can be used without a strong local GPU.

## Project Structure

```text
core/                 Engine helpers: audio, STT, settings, modes, history, output
data/                 Local SQLite data used during development
models/               Local model cache; intentionally ignored by Git
rules/                App-specific formatting rules
scripts/              Diagnostics and startup helpers
ui/main_window.py     PyQt host for the embedded React dashboard
ui/overlay.py         Dictation overlay pill
ui/tray.py            System tray integration
whisperer-app/src/    React dashboard source
whisperer-app/dist/   Built dashboard loaded by PyQt
launcher.py           UI launcher and single-instance entrypoint
main.py               Engine process entrypoint
whisperer.spec        PyInstaller build recipe
```

## Notes

- `models/` is intentionally kept out of Git because it contains large local
  caches for Parakeet, Whisper, Vosk, and related runtimes.
- The full Vosk model that used to live at the repository root is no longer
  used. Live preview only loads a cached small Vosk model under `models/vosk`.
  Whisperer will not download that optional model unless
  `WHISPERER_ENABLE_VOSK_DOWNLOAD=1` is set.
- Generated folders such as `build/`, `dist/`, `node_modules/`, and old Electron
  release outputs can be regenerated and are ignored.
