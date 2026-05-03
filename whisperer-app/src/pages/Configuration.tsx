import { useEffect, useState } from "react";
import { Btn, Card, Eyebrow, Icon, Input, KeyCombo, Row, SectionTitle, Select, Toggle } from "../primitives";
import { SHORTCUTS } from "../data";
import type { AppSettings, Tweaks } from "../App";

export default function ConfigPage({
  tweaks,
  setTweaks,
  settings: appSettings,
  apiKeys,
  shortcuts,
  setSetting,
  setShortcut,
}: {
  tweaks: Tweaks;
  setTweaks: (t: Tweaks) => void;
  settings: AppSettings;
  apiKeys: Record<string, { saved?: boolean; masked?: string }>;
  shortcuts: Record<string, string[]>;
  setSetting: (section: string, key: string, value: unknown) => void;
  setShortcut: (name: string, value: string) => void;
}) {
  const [settings, setSettings] = useState({
    launchOnLogin: Boolean(appSettings.startup?.launch_on_login ?? false),
    autoStartEngine: Boolean(appSettings.startup?.auto_start_engine ?? true),
    retainAudio: Boolean(appSettings.privacy?.store_audio_history ?? false),
    retainHistory: Boolean(appSettings.privacy?.retain_history ?? true),
    enginePreload: String(appSettings.performance?.engine_preload ?? "app_start"),
    autoSendEnter: Boolean(appSettings.paste?.auto_send_enter ?? false),
    restoreClipboard: Boolean(appSettings.paste?.restore_clipboard ?? false),
    pasteMethod: String(appSettings.paste?.method ?? "clipboard_paste"),
    ollamaUrl: String(appSettings.llm?.ollama_url ?? "http://localhost:11434"),
    openaiCompatUrl: String(appSettings.llm?.openai_compat_url ?? "http://localhost:8000"),
  });
  const [recordingShortcut, setRecordingShortcut] = useState(false);
  const [draftShortcut, setDraftShortcut] = useState<string[]>([]);
  const [purgeOpen, setPurgeOpen] = useState(false);
  const [purgeText, setPurgeText] = useState("");
  const [groqApiKey, setGroqApiKey] = useState("");
  const [groqKeyStatus, setGroqKeyStatus] = useState("");
  const groqKeyMasked = apiKeys.groq?.masked || "";
  const [nvidiaApiKey, setNvidiaApiKey] = useState("");
  const [nvidiaKeyStatus, setNvidiaKeyStatus] = useState("");
  const nvidiaKeyMasked = apiKeys.nvidia?.masked || "";

  useEffect(() => {
    setSettings((current) => ({
      ...current,
      launchOnLogin: Boolean(appSettings.startup?.launch_on_login ?? false),
      autoStartEngine: Boolean(appSettings.startup?.auto_start_engine ?? true),
      retainAudio: Boolean(appSettings.privacy?.store_audio_history ?? false),
      retainHistory: Boolean(appSettings.privacy?.retain_history ?? true),
      enginePreload: String(appSettings.performance?.engine_preload ?? "app_start"),
      autoSendEnter: Boolean(appSettings.paste?.auto_send_enter ?? false),
      restoreClipboard: Boolean(appSettings.paste?.restore_clipboard ?? false),
      pasteMethod: String(appSettings.paste?.method ?? "clipboard_paste"),
      ollamaUrl: String(appSettings.llm?.ollama_url ?? "http://localhost:11434"),
      openaiCompatUrl: String(appSettings.llm?.openai_compat_url ?? "http://localhost:8000"),
    }));
  }, [appSettings]);

  const set = <K extends keyof typeof settings>(k: K, v: (typeof settings)[K]) => {
    setSettings((s) => ({ ...s, [k]: v }));
    if (k === "launchOnLogin") setSetting("startup", "launch_on_login", v);
    if (k === "autoStartEngine") setSetting("startup", "auto_start_engine", v);
    if (k === "pasteMethod") setSetting("paste", "method", v);
    if (k === "restoreClipboard") setSetting("paste", "restore_clipboard", v);
    if (k === "autoSendEnter") setSetting("paste", "auto_send_enter", v);
    if (k === "retainHistory") setSetting("privacy", "retain_history", v);
    if (k === "retainAudio") setSetting("privacy", "store_audio_history", v);
    if (k === "enginePreload") setSetting("performance", "engine_preload", v);
    if (k === "ollamaUrl") setSetting("llm", "ollama_url", v);
    if (k === "openaiCompatUrl") setSetting("llm", "openai_compat_url", v);
  };
  const setT = <K extends keyof Tweaks>(k: K, v: Tweaks[K]) => {
    setTweaks({ ...tweaks, [k]: v });
    setSetting("ui", k, v);
  };

  const saveGroqApiKey = () => {
    const value = groqApiKey.trim();
    if (!value || !window.whisperer?.setApiKey) return;
    window.whisperer.setApiKey("groq", value)
      .then(() => {
        setGroqApiKey("");
        setGroqKeyStatus("Saved");
        window.setTimeout(() => setGroqKeyStatus(""), 2200);
      })
      .catch(() => setGroqKeyStatus("Could not save"));
  };

  const testGroqApiKey = () => {
    if (!window.whisperer?.testApiKey) return;
    setGroqKeyStatus("Testing...");
    window.whisperer.testApiKey("groq")
      .then((payload) => {
        try {
          const result = JSON.parse(payload);
          setGroqKeyStatus(result.ok ? (result.message || "Key works") : (result.error || "Test failed"));
        } catch {
          setGroqKeyStatus("Test failed");
        }
      })
      .catch(() => setGroqKeyStatus("Test failed"));
  };

  const saveNvidiaApiKey = () => {
    const value = nvidiaApiKey.trim();
    if (!value || !window.whisperer?.setApiKey) return;
    window.whisperer.setApiKey("nvidia", value)
      .then(() => {
        setNvidiaApiKey("");
        setNvidiaKeyStatus("Saved");
        window.setTimeout(() => setNvidiaKeyStatus(""), 2200);
      })
      .catch(() => setNvidiaKeyStatus("Could not save"));
  };

  const testNvidiaApiKey = () => {
    if (!window.whisperer?.testApiKey) return;
    setNvidiaKeyStatus("Testing...");
    window.whisperer.testApiKey("nvidia")
      .then((payload) => {
        try {
          const result = JSON.parse(payload);
          setNvidiaKeyStatus(result.ok ? (result.message || "Key works") : (result.error || "Test failed"));
        } catch {
          setNvidiaKeyStatus("Test failed");
        }
      })
      .catch(() => setNvidiaKeyStatus("Test failed"));
  };

  const labelToHotkey = (key: string) => {
    const lookup: Record<string, string> = {
      Ctrl: "ctrl",
      Alt: "alt",
      Shift: "shift",
      "Left Windows": "left windows",
      "Right Windows": "right windows",
      Windows: "windows",
      Esc: "escape",
      Space: "space",
      Left: "left",
      Right: "right",
      Up: "up",
      Down: "down",
    };
    return lookup[key] || key.toLowerCase();
  };

  const comboFromEvent = (event: KeyboardEvent) => {
    const keys: string[] = [];
    if (event.ctrlKey) keys.push("Ctrl");
    if (event.altKey) keys.push("Alt");
    if (event.shiftKey) keys.push("Shift");
    if (event.metaKey) keys.push(event.code === "MetaRight" ? "Right Windows" : "Left Windows");
    const modifierKeys = new Set(["Control", "Shift", "Alt", "Meta", "OS"]);
    if (!modifierKeys.has(event.key)) {
      const named: Record<string, string> = {
        Escape: "Esc",
        " ": "Space",
        ArrowLeft: "Left",
        ArrowRight: "Right",
        ArrowUp: "Up",
        ArrowDown: "Down",
      };
      keys.push(named[event.key] || (event.key.length === 1 ? event.key.toUpperCase() : event.key));
    }
    return Array.from(new Set(keys)).slice(0, 4);
  };

  useEffect(() => {
    if (!recordingShortcut) return;
    const onKeyDown = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
      const combo = comboFromEvent(event);
      if (combo.length) setDraftShortcut(combo);
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [recordingShortcut]);

  const commitShortcut = () => {
    if (!draftShortcut.length) return;
    setShortcut("dictation", draftShortcut.map(labelToHotkey).join("+"));
    setRecordingShortcut(false);
  };

  const dictationKeys = recordingShortcut
    ? (draftShortcut.length ? draftShortcut : ["Press keys"])
    : (shortcuts.dictation?.length ? shortcuts.dictation : ["Ctrl", "Left Windows"]);

  const closePurge = () => {
    setPurgeOpen(false);
    setPurgeText("");
  };

  const confirmPurge = () => {
    if (purgeText !== "PURGE") return;
    window.whisperer?.purgeHistory?.();
    closePurge();
  };

  return (
    <div className="page-enter scroll page-shell">
      <div style={{ marginBottom: 22 }}>
        <Eyebrow>Configuration</Eyebrow>
        <h1 style={{ fontSize: 28, fontWeight: 500, letterSpacing: "-0.025em", margin: "6px 0 6px" }}>Configuration</h1>
        <p style={{ color: "var(--ink-2)", fontSize: 13.5, margin: 0, maxWidth: 620, lineHeight: 1.5 }}>
          Shortcuts, paste behavior, privacy, providers, and startup.
        </p>
      </div>

      <SectionTitle>Appearance</SectionTitle>
      <Card style={{ marginBottom: 18 }}>
        <Row title="Theme" subtitle="Follow daylight or pick a fixed mode."
             control={<Select value={tweaks.theme} onChange={(v) => setT("theme", v as Tweaks["theme"])} options={[{ value: "sun", label: "Sun" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} width={140} />} />
        <Row title="Accent" subtitle="Used for active states, buttons, and the live waveform."
             control={<Select value={tweaks.accent} onChange={(v) => setT("accent", v as Tweaks["accent"])} options={[{ value: "moss", label: "Moss" }, { value: "sage", label: "Sage" }, { value: "clay", label: "Clay" }, { value: "copper", label: "Copper" }, { value: "plum", label: "Plum" }, { value: "slate", label: "Slate" }]} width={160} />} />
        <Row title="Density" subtitle="Slightly tighter spacing on smaller displays."
             control={<Select value={tweaks.density} onChange={(v) => setT("density", v as Tweaks["density"])} options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} width={160} />}
             divider={false} />
      </Card>

      <SectionTitle>Keyboard shortcuts</SectionTitle>
      <Card style={{ marginBottom: 18 }}>
        <Row
          title="Dictation hotkey"
          subtitle={recordingShortcut ? "Press up to four keys, then save." : "Hold while speaking. Release to transcribe and paste."}
          control={
            <div style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <KeyCombo keys={dictationKeys} />
              {recordingShortcut ? (
                <>
                  <Btn size="sm" variant="accent" onClick={commitShortcut} disabled={!draftShortcut.length}>Save</Btn>
                  <Btn size="sm" variant="ghost" onClick={() => { setRecordingShortcut(false); setDraftShortcut([]); }}>Cancel</Btn>
                </>
              ) : (
                <Btn size="sm" variant="secondary" onClick={() => { setDraftShortcut([]); setRecordingShortcut(true); }}>Change</Btn>
              )}
            </div>
          }
        />
        {SHORTCUTS.filter((s) => s.key !== "dictation").map((s, i, arr) => (
          <Row key={s.key} title={s.label} subtitle={s.hint} divider={i < arr.length - 1} control={<KeyCombo keys={shortcuts[s.key] || s.combo} />} />
        ))}
      </Card>

      <SectionTitle>Paste behavior</SectionTitle>
      <Card style={{ marginBottom: 18 }}>
        <Row title="Default paste method" subtitle="How the final text is delivered to the active application."
             control={<Select value={settings.pasteMethod} onChange={(v) => set("pasteMethod", v)} options={[{ value: "clipboard_paste", label: "Clipboard paste (Ctrl+V)" }, { value: "simulate_keys", label: "Simulate keystrokes" }, { value: "copy_only", label: "Copy only (no paste)" }]} width={240} />} />
        <Row title="Restore previous clipboard" subtitle="Put your old clipboard contents back after pasting."
             control={<Toggle checked={settings.restoreClipboard} onChange={(v) => set("restoreClipboard", v)} />} />
        <Row title="Auto-send Enter after paste" subtitle="Submit chat messages automatically. Avoid in code editors."
             control={<Toggle checked={settings.autoSendEnter} onChange={(v) => set("autoSendEnter", v)} />} divider={false} />
      </Card>

      <SectionTitle>Privacy</SectionTitle>
      <Card style={{ marginBottom: 18 }}>
        <div style={{ display: "flex", gap: 14, padding: "12px 0 16px", borderBottom: "1px solid var(--line-soft)" }}>
          <Icon name="shield" size={18} stroke={1.5} />
          <div style={{ flex: 1, fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.5 }}>
            Whisperer is local-first. Audio and transcripts stay on this device unless you enable a cloud provider in a mode.
          </div>
        </div>
        <Row title="Retain transcription history" subtitle="Keep a searchable log of past dictations. Stored locally."
             control={<Toggle checked={settings.retainHistory} onChange={(v) => set("retainHistory", v)} />} />
        <Row title="Keep audio recordings" subtitle="Save the original WAV alongside each transcript. Off by default."
             control={<Toggle checked={settings.retainAudio} onChange={(v) => set("retainAudio", v)} />} />
        <Row title="Purge all history" subtitle="Permanently delete every dictation, audio file, and context entry."
             control={<Btn variant="danger" icon="trash" onClick={() => setPurgeOpen(true)}>Purge history</Btn>} divider={false} />
      </Card>

      <SectionTitle>Cloud & local AI providers</SectionTitle>
      <Card style={{ marginBottom: 18 }} padding={0}>
        <div style={{ padding: "12px 18px", borderBottom: "1px solid var(--line-soft)", background: "var(--bg-sunken)", display: "flex", alignItems: "center", gap: 10 }}>
          <Icon name="info" size={14} />
          <span style={{ fontSize: 12, color: "var(--ink-2)" }}>Cloud providers are only used by modes that opt in. API keys stay in Windows Credential Manager.</span>
        </div>
        <div style={{ padding: "14px 18px", background: "var(--bg-sunken)" }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink-3)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 10 }}>Local LLM endpoints</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <div>
              <div style={{ fontSize: 12, color: "var(--ink-2)", marginBottom: 5 }}>Ollama URL</div>
              <Input value={settings.ollamaUrl} onChange={(v) => set("ollamaUrl", v)} />
            </div>
            <div>
              <div style={{ fontSize: 12, color: "var(--ink-2)", marginBottom: 5 }}>OpenAI-compatible URL</div>
              <Input value={settings.openaiCompatUrl} onChange={(v) => set("openaiCompatUrl", v)} />
            </div>
          </div>
        </div>
        <div style={{ padding: "14px 18px", borderTop: "1px solid var(--line-soft)" }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink-3)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 10 }}>Speech-to-text APIs</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto auto", gap: 10, alignItems: "end" }}>
            <div>
              <div style={{ fontSize: 12, color: "var(--ink-2)", marginBottom: 5 }}>Groq API key</div>
              <Input value={groqApiKey} onChange={setGroqApiKey} type="password" placeholder={groqKeyMasked || "Paste API key"} />
              {groqKeyMasked && (
                <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 5 }}>
                  Saved key: {groqKeyMasked}
                </div>
              )}
            </div>
            <Btn variant="secondary" icon="check" disabled={!groqApiKey.trim()} onClick={saveGroqApiKey}>Save</Btn>
            <Btn variant="secondary" icon="reveal" onClick={testGroqApiKey}>Test</Btn>
            <span style={{ minWidth: 150, fontSize: 12, color: groqKeyStatus.includes("failed") || groqKeyStatus.includes("No ") || groqKeyStatus.includes("rejected") || groqKeyStatus.includes("Could not") ? "var(--rec)" : "var(--ink-3)" }}>{groqKeyStatus}</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto auto", gap: 10, alignItems: "end", marginTop: 14 }}>
            <div>
              <div style={{ fontSize: 12, color: "var(--ink-2)", marginBottom: 5 }}>NVIDIA API key</div>
              <Input value={nvidiaApiKey} onChange={setNvidiaApiKey} type="password" placeholder={nvidiaKeyMasked || "Paste API key"} />
              {nvidiaKeyMasked && (
                <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 5 }}>
                  Saved key: {nvidiaKeyMasked}
                </div>
              )}
            </div>
            <Btn variant="secondary" icon="check" disabled={!nvidiaApiKey.trim()} onClick={saveNvidiaApiKey}>Save</Btn>
            <Btn variant="secondary" icon="reveal" onClick={testNvidiaApiKey}>Test</Btn>
            <span style={{ minWidth: 150, fontSize: 12, color: nvidiaKeyStatus.includes("failed") || nvidiaKeyStatus.includes("No ") || nvidiaKeyStatus.includes("rejected") || nvidiaKeyStatus.includes("Could not") ? "var(--rec)" : "var(--ink-3)" }}>{nvidiaKeyStatus}</span>
          </div>
        </div>
      </Card>

      <SectionTitle>Startup & updates</SectionTitle>
      <Card style={{ marginBottom: 18 }}>
        <Row title="Start Whisperer when Windows starts" subtitle="Add or remove Whisperer from your Windows login items."
             control={<Toggle checked={settings.launchOnLogin} onChange={(v) => set("launchOnLogin", v)} />} />
        <Row title="Start engine when Whisperer opens" subtitle="Warm the transcription engine automatically after launch."
             control={<Toggle checked={settings.autoStartEngine} onChange={(v) => set("autoStartEngine", v)} />} />
        <Row title="Engine preload" subtitle="When the transcription model gets loaded into memory."
             control={<Select value={settings.enginePreload} onChange={(v) => set("enginePreload", v)} options={[{ value: "app_start", label: "When app starts" }, { value: "login", label: "On login" }, { value: "off", label: "Manual" }]} width={200} />} />
      </Card>
      {purgeOpen && (
        <div
          data-no-drag
          role="dialog"
          aria-modal="true"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 100,
            display: "grid",
            placeItems: "center",
            background: "rgba(0,0,0,0.24)",
          }}
        >
          <Card
            padding={0}
            style={{
              width: 430,
              maxWidth: "calc(100vw - 48px)",
              boxShadow: "var(--shadow-menu)",
              overflow: "hidden",
            }}
          >
            <div style={{ padding: "18px 20px 14px", borderBottom: "1px solid var(--line-soft)" }}>
              <Eyebrow>Confirm</Eyebrow>
              <h2 style={{ margin: "6px 0 6px", fontSize: 19, fontWeight: 550, color: "var(--ink)", letterSpacing: "-0.015em" }}>
                Purge History
              </h2>
              <p style={{ margin: 0, color: "var(--ink-2)", fontSize: 13, lineHeight: 1.45 }}>
                Type PURGE to permanently delete every dictation.
              </p>
            </div>
            <div style={{ padding: 20 }}>
              <Input value={purgeText} onChange={setPurgeText} autoFocus />
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
                <Btn variant="ghost" onClick={closePurge}>Cancel</Btn>
                <Btn variant="danger" icon="trash" disabled={purgeText !== "PURGE"} onClick={confirmPurge}>Purge</Btn>
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
