import { useEffect, useMemo, useState } from "react";
import { Btn, Card, Eyebrow, Input, Pill, Row, SectionTitle, Select, Toggle } from "../primitives";
import type { AppSnapshot, ModeItem } from "../App";

function parseSnapshot(raw: string | AppSnapshot | undefined): AppSnapshot | null {
  if (!raw) return null;
  if (typeof raw !== "string") return raw;
  try {
    return JSON.parse(raw) as AppSnapshot;
  } catch {
    return null;
  }
}

export default function ModesPage({
  modes,
  applySnapshot,
}: {
  modes: ModeItem[];
  applySnapshot: (raw: string | AppSnapshot | undefined) => void;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const [draft, setDraft] = useState<ModeItem | null>(null);
  const [dirty, setDirty] = useState(false);
  const [newModeNeedsSaveId, setNewModeNeedsSaveId] = useState<number | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ModeItem | null>(null);
  const [ruleType, setRuleType] = useState("process");
  const [ruleValue, setRuleValue] = useState("");
  const [rulePriority, setRulePriority] = useState("0");

  useEffect(() => {
    if (selected === null && modes.length) setSelected(modes[0].id);
    if (selected !== null && modes.length && !modes.some((mode) => mode.id === selected)) setSelected(modes[0].id);
  }, [modes, selected]);

  const mode = useMemo(() => modes.find((m) => m.id === selected) || modes[0], [modes, selected]);

  useEffect(() => {
    if (!mode) return;
    setDraft({ ...mode, auto: [...mode.auto] });
    setDirty(mode.id === newModeNeedsSaveId);
    if (mode.id === newModeNeedsSaveId) setNewModeNeedsSaveId(null);
  }, [mode?.id, newModeNeedsSaveId]);

  useEffect(() => {
    if (!mode || dirty) return;
    setDraft({ ...mode, auto: [...mode.auto] });
  }, [mode, dirty]);

  const working = draft || mode;

  const edit = (patch: Partial<ModeItem>) => {
    setDraft((current) => current ? { ...current, ...patch } : current);
    setDirty(true);
  };

  const updateImmediate = (patch: Partial<ModeItem>) => {
    if (!mode) return;
    window.whisperer?.updateMode?.(mode.id, patch).then(applySnapshot).catch(() => {});
  };

  const saveDraft = () => {
    if (!mode || !working) return;
    const patch: Partial<ModeItem> = {
      name: working.name.trim() || mode.name,
      description: working.description,
      format: working.format,
      formattingPrompt: working.formattingPrompt,
      stt: working.stt,
      sttModel: working.sttModel,
      llm: working.llm,
      llmProvider: working.llmProvider,
      llmModel: working.llmModel,
      llmPrompt: working.llmPrompt,
      pasteMethod: working.pasteMethod,
      autoSend: working.autoSend,
      ctxOcr: working.ctxOcr,
      ctxSelectedText: working.ctxSelectedText,
      ctxClipboard: working.ctxClipboard,
      enabled: working.enabled,
    };
    window.whisperer?.updateMode?.(mode.id, patch)
      .then((snapshot) => {
        applySnapshot(snapshot);
        setDirty(false);
      })
      .catch(() => {});
  };

  const addMode = () => {
    window.whisperer?.addMode?.("New Mode")
      .then((snapshot) => {
        applySnapshot(snapshot);
        const parsed = parseSnapshot(snapshot);
        const created = Number((parsed as AppSnapshot & { createdModeId?: number })?.createdModeId || 0);
        if (created) {
          setNewModeNeedsSaveId(created);
          setSelected(created);
        }
      })
      .catch(() => {});
  };

  const deleteMode = () => {
    if (!mode) return;
    setPendingDelete(mode);
  };

  const confirmDeleteMode = () => {
    if (!pendingDelete) return;
    window.whisperer?.deleteMode?.(pendingDelete.id)
      .then((snapshot) => {
        setPendingDelete(null);
        applySnapshot(snapshot);
      })
      .catch(() => setPendingDelete(null));
  };

  const addRule = () => {
    if (!mode || !ruleValue.trim()) return;
    window.whisperer?.addAutoRule?.(mode.id, ruleType, ruleValue.trim(), Number(rulePriority) || 0)
      .then((snapshot) => {
        applySnapshot(snapshot);
        setRuleValue("");
      })
      .catch(() => {});
  };

  const deleteRule = (ruleId: number) => {
    window.whisperer?.deleteAutoRule?.(ruleId).then(applySnapshot).catch(() => {});
  };

  if (!mode || !working) {
    return (
      <div className="page-enter" style={{ padding: "40px 28px", color: "var(--ink-3)" }}>
        No modes are available.
      </div>
    );
  }

  return (
    <div className="page-enter" style={{ display: "flex", height: "100%", position: "relative" }}>
      <div className="scroll" style={{ width: 280, flex: "0 0 280px", borderRight: "1px solid var(--line)", background: "var(--bg-2)", padding: "16px 12px", overflow: "auto" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "0 6px 12px" }}>
          <Eyebrow>{modes.length} modes</Eyebrow>
          <Btn size="sm" variant="ghost" icon="plus" onClick={addMode}>New</Btn>
        </div>
        {modes.map((m) => {
          const isActive = m.id === mode.id;
          return (
            <button
              key={m.id}
              onClick={() => setSelected(m.id)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "10px 12px",
                marginBottom: 2,
                background: isActive ? "var(--card)" : "transparent",
                border: "1px solid",
                borderColor: isActive ? "var(--accent)" : "transparent",
                borderRadius: 9,
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ width: 6, height: 6, borderRadius: 6, background: m.enabled ? "var(--accent)" : "var(--ink-4)" }} />
                <span style={{ fontSize: 13, fontWeight: 500, color: isActive ? "var(--accent-ink)" : "var(--ink)", letterSpacing: "-0.005em" }}>{m.name}</span>
                {m.builtin && <Pill tone="soft" style={{ height: 18, fontSize: 10, padding: "0 7px" }}>built-in</Pill>}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 3, paddingLeft: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.description}</div>
            </button>
          );
        })}
      </div>

      <div className="scroll" style={{ flex: 1, overflow: "auto", padding: "22px 28px 40px" }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 22 }}>
          <div style={{ flex: 1 }}>
            <Eyebrow>{mode.builtin ? "Built-in mode" : "Custom mode"}</Eyebrow>
            <h1 style={{ fontSize: 28, fontWeight: 500, letterSpacing: "-0.025em", margin: "6px 0 6px" }}>{working.name}</h1>
            <p style={{ color: "var(--ink-2)", fontSize: 13.5, margin: 0, maxWidth: 600, lineHeight: 1.5 }}>{working.description}</p>
          </div>
          {dirty && <Btn variant="accent" icon="check" onClick={saveDraft}>Save</Btn>}
          <Btn variant={working.enabled ? "secondary" : "primary"} onClick={() => {
            const nextEnabled = !working.enabled;
            setDraft((current) => current ? { ...current, enabled: nextEnabled } : current);
            setDirty(false);
            updateImmediate({ enabled: nextEnabled });
          }}>
            {working.enabled ? "Disable" : "Enable"}
          </Btn>
          <Btn variant="danger" icon="trash" onClick={deleteMode}>Delete</Btn>
        </div>

        <SectionTitle>Mode settings</SectionTitle>
        <Card style={{ marginBottom: 14 }}>
          <Row title="Name" subtitle="Shown in the overlay and history." control={<Input value={working.name} onChange={(v) => edit({ name: v })} style={{ width: 240 }} />} />
          <Row title="Description" subtitle="A short note for yourself." control={<Input value={working.description} onChange={(v) => edit({ description: v })} style={{ width: 380 }} />} />
          <Row
            title="Output format"
            subtitle="How the final text is shaped."
            control={<Select value={working.format} onChange={(v) => edit({ format: v })} options={[{ value: "plain", label: "Plain text" }, { value: "markdown", label: "Markdown" }, { value: "code", label: "Code" }]} width={190} />}
          />
          <Row
            title="Formatting prompt"
            subtitle="Instructions used when this mode performs text cleanup."
            control={
              <textarea
                value={working.formattingPrompt || ""}
                onChange={(event) => edit({ formattingPrompt: event.target.value } as Partial<ModeItem>)}
                style={{
                  width: 420,
                  height: 82,
                  resize: "vertical",
                  background: "var(--card)",
                  color: "var(--ink)",
                  border: "1px solid var(--line)",
                  borderRadius: 8,
                  padding: "9px 10px",
                  font: "inherit",
                  fontSize: 12.5,
                  lineHeight: 1.4,
                }}
              />
            }
          />
          <Row
            title="Speech-to-text provider"
            subtitle="The model family used before formatting."
            control={<Select value={working.stt} onChange={(v) => edit({ stt: v })} options={[{ value: "local", label: "Local" }, { value: "nvidia_parakeet", label: "NVIDIA Parakeet" }, { value: "openai_whisper", label: "OpenAI speech" }, { value: "groq_whisper", label: "Groq Whisper" }, { value: "deepgram", label: "Deepgram" }]} width={210} />}
          />
          <Row title="STT model override" subtitle="Optional provider-specific model name."
               control={<Input value={working.sttModel || ""} onChange={(v) => edit({ sttModel: v } as Partial<ModeItem>)} style={{ width: 260 }} />} />
          <Row
            title="LLM post-processing"
            subtitle={working.llm ? "An LLM rewrites the raw transcript using the mode prompt." : "Off - paste the raw transcript after replacements."}
            control={<Toggle checked={working.llm} onChange={(v) => edit({ llm: v })} />}
          />
          <Row title="LLM provider" subtitle="Used only when LLM post-processing is enabled."
               control={<Select value={working.llmProvider || "ollama"} onChange={(v) => edit({ llmProvider: v } as Partial<ModeItem>)} options={[{ value: "ollama", label: "Ollama" }, { value: "openai_compat", label: "OpenAI-compatible" }, { value: "openai", label: "OpenAI" }, { value: "anthropic", label: "Anthropic" }]} width={210} />} />
          <Row title="LLM model" subtitle="Optional model name for the selected provider."
               control={<Input value={working.llmModel || ""} onChange={(v) => edit({ llmModel: v } as Partial<ModeItem>)} style={{ width: 260 }} />} />
          <Row title="LLM prompt" subtitle="Detailed rewrite instructions for this mode."
               control={
                 <textarea
                   value={working.llmPrompt || ""}
                   onChange={(event) => edit({ llmPrompt: event.target.value } as Partial<ModeItem>)}
                   style={{
                     width: 420,
                     height: 82,
                     resize: "vertical",
                     background: "var(--card)",
                     color: "var(--ink)",
                     border: "1px solid var(--line)",
                     borderRadius: 8,
                     padding: "9px 10px",
                     font: "inherit",
                     fontSize: 12.5,
                     lineHeight: 1.4,
                   }}
                 />
               } />
          <Row
            title="Paste method"
            subtitle="How final text is delivered to the active app."
            control={<Select value={working.pasteMethod} onChange={(v) => edit({ pasteMethod: v })} options={[{ value: "clipboard_paste", label: "Clipboard paste" }, { value: "simulate_keys", label: "Simulate keystrokes" }, { value: "copy_only", label: "Copy only" }]} width={210} />}
          />
          <Row title="Auto-send Enter" subtitle="Submit after paste for chat-style apps."
               control={<Toggle checked={Boolean(working.autoSend)} onChange={(v) => edit({ autoSend: v })} />} />
          <Row title="OCR context" subtitle="Allow this mode to use screen text as context."
               control={<Toggle checked={Boolean(working.ctxOcr)} onChange={(v) => edit({ ctxOcr: v })} />} />
          <Row title="Selected text context" subtitle="Copy selected text before dictation and restore the clipboard."
               control={<Toggle checked={Boolean(working.ctxSelectedText)} onChange={(v) => edit({ ctxSelectedText: v })} />} />
          <Row title="Clipboard context" subtitle="Let this mode consider recent clipboard text."
               control={<Toggle checked={Boolean(working.ctxClipboard)} onChange={(v) => edit({ ctxClipboard: v })} />} divider={false} />
        </Card>

        <SectionTitle>Auto-activation</SectionTitle>
        <Card padding={0} style={{ marginBottom: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 18px", borderBottom: "1px solid var(--line-soft)" }}>
            <Select value={ruleType} onChange={setRuleType} options={[{ value: "process", label: "Process" }, { value: "window_title", label: "Window title" }, { value: "exe_path", label: "Exe path" }]} width={150} small />
            <Input value={ruleValue} onChange={setRuleValue} placeholder="contains..." style={{ flex: 1 }} />
            <Input value={rulePriority} onChange={setRulePriority} placeholder="0" type="number" style={{ width: 74 }} />
            <Btn size="sm" variant="accent" icon="plus" onClick={addRule} disabled={!ruleValue.trim()}>Add</Btn>
          </div>
          {mode.auto.length === 0 ? (
            <div style={{ padding: "22px", color: "var(--ink-3)", fontSize: 12.5 }}>
              No auto-activation rules for this mode.
            </div>
          ) : (
            mode.auto.map((rule, i) => (
              <div
                key={rule.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  padding: "12px 18px",
                  borderTop: i === 0 ? "none" : "1px solid var(--line-soft)",
                }}
              >
                <Pill tone="soft">{rule.type || "rule"}</Pill>
                <span className="mono" style={{ fontSize: 12.5, color: "var(--ink-1)" }}>{rule.value}</span>
                <span style={{ flex: 1 }} />
                <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>priority {rule.priority}</span>
                {!rule.enabled && <Pill tone="soft">disabled</Pill>}
                <Btn size="sm" variant="ghost" icon="trash" onClick={() => deleteRule(rule.id)} />
              </div>
            ))
          )}
        </Card>
      </div>
      {pendingDelete && (
        <div
          data-no-drag
          style={{
            position: "absolute",
            inset: 0,
            zIndex: 500,
            display: "grid",
            placeItems: "center",
            background: "rgba(0,0,0,0.28)",
          }}
        >
          <Card style={{ width: 360, boxShadow: "var(--shadow-menu)" }}>
            <Eyebrow>Delete mode</Eyebrow>
            <h2 style={{ margin: "8px 0 6px", fontSize: 18, fontWeight: 600, color: "var(--ink)" }}>
              Delete {pendingDelete.name}?
            </h2>
            <p style={{ margin: "0 0 18px", fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>
              This removes the mode and any auto-activation rules attached to it.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <Btn variant="secondary" onClick={() => setPendingDelete(null)}>Cancel</Btn>
              <Btn variant="danger" icon="trash" onClick={confirmDeleteMode}>Delete</Btn>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
