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
  used. Live preview uses the smaller auto-managed model under `models/vosk`.
- Generated folders such as `build/`, `dist/`, `node_modules/`, and old Electron
  release outputs can be regenerated and are ignored.
