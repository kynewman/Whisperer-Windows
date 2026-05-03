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
  used. Live preview uses the smaller auto-managed model under `models/vosk`.
- Generated folders such as `build/`, `dist/`, `node_modules/`, and old Electron
  release outputs can be regenerated and are ignored.
