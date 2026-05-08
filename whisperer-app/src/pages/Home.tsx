import { Btn, Card, Eyebrow, Icon, KeyCombo, Pill, SectionTitle, Select } from "../primitives";
import { NavKey } from "../data";
import { EngineState } from "../chrome";
import type { BridgeOption, DictationBackup } from "../App";

export default function HomePage({
  engineState,
  setEngineState,
  model,
  setModel,
  models,
  gpu,
  setGpu,
  gpus,
  onNav,
  activeMode,
  dictationKeys,
  dictationBackup,
  onTranscribeLastDictation,
  apiKeys,
}: {
  engineState: EngineState;
  setEngineState: (s: EngineState) => void;
  model: string;
  setModel: (v: string) => void;
  models: BridgeOption[];
  gpu: string;
  setGpu: (v: string) => void;
  gpus: BridgeOption[];
  onNav: (k: NavKey) => void;
  activeMode: string;
  dictationKeys: string[];
  dictationBackup: DictationBackup;
  onTranscribeLastDictation: () => void;
  apiKeys: Record<string, { saved?: boolean; masked?: string }>;
}) {
  const statusText =
    engineState === "running" ? "Engine ready" :
    engineState === "loading" ? "Warming up" :
    "Engine stopped";

  const quickActions: { title: string; detail: string; keys: string[] | null; page: NavKey; iconName: "mic" | "config" | "modes" | "vocab" | "history" }[] = [
    { title: "Dictate anywhere", detail: "Hold the dictation shortcut to speak into the active app.", keys: dictationKeys, page: "home", iconName: "mic" },
    { title: "Modes", detail: "Adjust formatting and context behavior.", keys: null, page: "modes", iconName: "modes" },
    { title: "Vocabulary", detail: "Manage learned words and replacement rules.", keys: null, page: "vocabulary", iconName: "vocab" },
    { title: "History", detail: "Review real dictations saved by Whisperer.", keys: null, page: "history", iconName: "history" },
  ];
  const missingNvidiaKey = gpu === "nvidia_api" && !apiKeys.nvidia?.saved;
  const missingGroqKey = (gpu === "groq_api" || gpu === "grok_api") && !apiKeys.groq?.saved;
  const missingApiKey = missingNvidiaKey || missingGroqKey;

  return (
    <div className="page-enter scroll page-shell">
      {missingApiKey && (
        <Card padding={0} style={{ marginBottom: 18, borderColor: "rgba(190, 105, 46, 0.35)" }}>
          <div style={{ padding: "14px 18px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <span style={{ width: 30, height: 30, display: "grid", placeItems: "center", background: "var(--bg-sunken)", border: "1px solid var(--line-soft)", borderRadius: 8, color: "var(--rec)" }}>
              <Icon name="config" size={15} />
            </span>
            <div style={{ flex: 1, minWidth: 260 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>
                {missingNvidiaKey ? "Add an NVIDIA API key to use the default transcription device." : "Add a Groq API key to use this transcription device."}
              </div>
              <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 3 }}>
                The app can open without downloading local models, but dictation needs the selected API key before it can transcribe.
              </div>
            </div>
            <Btn variant="primary" icon="config" onClick={() => onNav("configuration")}>Open settings</Btn>
          </div>
        </Card>
      )}
      <Card padding={0} style={{ marginBottom: 18 }}>
        <div style={{ padding: "20px 22px 16px", borderBottom: "1px solid var(--line-soft)" }}>
          <Eyebrow>Engine</Eyebrow>
          <h1 style={{ fontSize: 26, fontWeight: 500, letterSpacing: "-0.015em", margin: "6px 0 12px", color: "var(--ink)" }}>
            {statusText}
          </h1>
          <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--ink-2)", fontSize: 12.5, flexWrap: "wrap" }}>
            <Pill tone={engineState === "running" ? "ok" : "neutral"}>
              <span style={{ width: 6, height: 6, borderRadius: 6, background: engineState === "running" ? "var(--ok)" : "var(--ink-3)" }} />
              {engineState === "running" ? "Ready" : engineState === "loading" ? "Loading" : "Stopped"}
            </Pill>
            <Pill tone="accent">{activeMode}</Pill>
            <span>Hold</span>
            <KeyCombo keys={dictationKeys} />
            <span>to dictate</span>
          </div>
        </div>

        <div style={{ padding: "14px 22px", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {engineState === "stopped" ? (
            <Btn variant="primary" icon="play" onClick={() => {
              if (window.whisperer?.startEngine) {
                setEngineState("loading");
                window.whisperer.startEngine();
              }
            }}>Start engine</Btn>
          ) : (
            <Btn variant="secondary" icon="stop" onClick={() => {
              if (window.whisperer?.stopEngine) window.whisperer.stopEngine();
            }}>Stop engine</Btn>
          )}
          <Btn
            variant="secondary"
            icon="copy"
            disabled={!dictationBackup.available || dictationBackup.busy}
            onClick={onTranscribeLastDictation}
          >
            {dictationBackup.busy ? "Transcribing..." : "Transcribe last dictation"}
          </Btn>
          {(dictationBackup.status || dictationBackup.error) && (
            <span style={{ fontSize: 11.5, color: dictationBackup.error ? "var(--rec)" : "var(--ink-3)" }}>
              {dictationBackup.error || dictationBackup.status}
            </span>
          )}
          <span style={{ width: 1, height: 22, background: "var(--line)" }} />
          <span style={{ fontSize: 12, color: "var(--ink-3)" }}>Model</span>
          <Select value={model} onChange={setModel} options={models} width={280} />
          <span style={{ fontSize: 12, color: "var(--ink-3)", marginLeft: 6 }}>Speech Engine</span>
          <Select value={gpu} onChange={setGpu} options={gpus} width={280} />
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>Changing either restarts the engine.</span>
        </div>
      </Card>

      <SectionTitle>Shortcuts</SectionTitle>
      <Card padding={0}>
        {quickActions.map((a, i) => (
          <button
            key={a.title}
            onClick={() => onNav(a.page)}
            data-no-drag
            style={{
              display: "flex",
              alignItems: "center",
              gap: 14,
              padding: "14px 18px",
              background: "transparent",
              border: "none",
              borderTop: i === 0 ? "none" : "1px solid var(--line-soft)",
              width: "100%",
              textAlign: "left",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            <span style={{ width: 30, height: 30, display: "grid", placeItems: "center", background: "var(--bg-sunken)", border: "1px solid var(--line-soft)", borderRadius: 8, color: "var(--ink-2)" }}>
              <Icon name={a.iconName} size={15} />
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 500, color: "var(--ink)", letterSpacing: "-0.005em" }}>{a.title}</div>
              <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 2 }}>{a.detail}</div>
            </div>
            {a.keys ? <KeyCombo keys={a.keys} /> : <Icon name="chevron" size={14} />}
          </button>
        ))}
      </Card>
    </div>
  );
}
