import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Btn, Card, Eyebrow, Icon, Input, SectionTitle, Select, Stat } from "../primitives";
import type { AppSnapshot, VocabularySnapshot } from "../App";

const RULE_SCOPE_OPTIONS = [
  { value: "global", label: "All apps" },
  { value: "app", label: "App contains" },
  { value: "window", label: "Window contains" },
];

export default function VocabPage({
  vocabulary,
  applySnapshot,
}: {
  vocabulary: VocabularySnapshot;
  applySnapshot: (raw: string | AppSnapshot | undefined) => void;
}) {
  const [q, setQ] = useState("");
  const [newWord, setNewWord] = useState("");
  const [newMatch, setNewMatch] = useState("");
  const [newReplace, setNewReplace] = useState("");
  const [newScopeType, setNewScopeType] = useState("global");
  const [newScopeValue, setNewScopeValue] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState<"word" | "rule" | "">("");
  const searchSeq = useRef(0);
  const deferredQ = useDeferredValue(q);
  const lc = deferredQ.toLowerCase();

  useEffect(() => {
    const query = deferredQ.trim();
    const search = window.whisperer?.searchVocabulary;
    if (!search) return;

    const seq = searchSeq.current + 1;
    searchSeq.current = seq;
    const timeout = window.setTimeout(() => {
      search(query)
        .then((raw) => {
          if (searchSeq.current === seq) applySnapshot(raw);
        })
        .catch(() => {});
    }, query ? 140 : 0);

    return () => window.clearTimeout(timeout);
  }, [deferredQ, applySnapshot]);
  const words = useMemo(
    () => (vocabulary.words || []).filter(
      (v) => !deferredQ
        || v.word.toLowerCase().includes(lc)
        || (v.source || "").toLowerCase().includes(lc)
        || (v.context || "").toLowerCase().includes(lc)
    ),
    [vocabulary.words, deferredQ, lc]
  );
  const replacements = useMemo(
    () => (vocabulary.rules || []).filter(
      (v) => !deferredQ
        || v.match_text.toLowerCase().includes(lc)
        || (v.replace_with || "").toLowerCase().includes(lc)
        || (v.scope_type || "global").toLowerCase().includes(lc)
        || (v.scope_value || "").toLowerCase().includes(lc)
    ),
    [vocabulary.rules, deferredQ, lc]
  );
  const visibleWords = words.slice(0, deferredQ ? 140 : 80);
  const hiddenWords = Math.max(0, words.length - visibleWords.length);
  const visibleReplacements = replacements.slice(0, deferredQ ? 120 : 70);
  const hiddenReplacements = Math.max(0, replacements.length - visibleReplacements.length);

  const addWord = () => {
    const word = newWord.trim();
    if (!word || busy) return;
    const add = window.whisperer?.addVocabularyWord;
    if (!add) {
      setStatus("Vocabulary editing is not available in this build.");
      return;
    }
    searchSeq.current += 1;
    setBusy("word");
    setStatus("");
    setNewWord("");
    setQ("");
    add(word)
      .then((raw) => {
        applySnapshot(raw);
        setStatus(`Added "${word}".`);
        window.whisperer?.vocabularySnapshot?.().then(applySnapshot).catch(() => {});
      })
      .catch(() => setStatus("Could not add the vocabulary word."))
      .finally(() => setBusy(""));
  };

  const addRule = () => {
    const match = newMatch.trim();
    const scopeValue = newScopeType === "global" ? "" : newScopeValue.trim();
    if (!match || busy) return;
    if (newScopeType !== "global" && !scopeValue) {
      setStatus("Add an app or window match for this scoped rule.");
      return;
    }
    const add = window.whisperer?.addReplacementRule;
    if (!add) {
      setStatus("Replacement rules are not available in this build.");
      return;
    }
    searchSeq.current += 1;
    setBusy("rule");
    setStatus("");
    setNewMatch("");
    setNewReplace("");
    if (newScopeType !== "global") setNewScopeValue("");
    setQ("");
    add(match, newReplace, newScopeType, scopeValue)
      .then((raw) => {
        applySnapshot(raw);
        setStatus(`Added replacement rule for "${match}".`);
        window.whisperer?.vocabularySnapshot?.().then(applySnapshot).catch(() => {});
      })
      .catch(() => setStatus("Could not add the replacement rule."))
      .finally(() => setBusy(""));
  };

  const scopeLabel = (type?: string, value?: string) => {
    if (!type || type === "global" || !value) return "All apps";
    return type === "window" ? `Window: ${value}` : `App: ${value}`;
  };

  return (
    <div className="page-enter scroll" style={{ padding: "22px 28px 40px", overflow: "auto", height: "100%" }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 16, marginBottom: 18 }}>
        <div style={{ flex: 1 }}>
          <Eyebrow>Dictionary</Eyebrow>
          <h1 style={{ fontSize: 28, fontWeight: 500, letterSpacing: "-0.025em", margin: "6px 0 6px" }}>Vocabulary</h1>
          <p style={{ color: "var(--ink-2)", fontSize: 13.5, margin: 0, maxWidth: 620, lineHeight: 1.5 }}>
            Names, jargon, and replacement rules from your local Whisperer database.
          </p>
        </div>
      </div>

      <Card padding={0} style={{ marginBottom: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", padding: "16px 22px" }}>
          <div><Stat value={vocabulary.wordCount + replacements.length} caption="Total entries" /></div>
          <div style={{ borderLeft: "1px solid var(--line-soft)", paddingLeft: 22 }}>
            <Stat value={vocabulary.wordCount} caption="Vocabulary words" />
          </div>
          <div style={{ borderLeft: "1px solid var(--line-soft)", paddingLeft: 22 }}>
            <Stat value={vocabulary.rules.length} caption="Replacement rules" />
          </div>
        </div>
      </Card>

      <Input icon="search" placeholder="Search vocabulary..." value={q} onChange={setQ} style={{ marginBottom: status ? 8 : 16 }} />
      {status && (
        <div style={{ fontSize: 12.5, color: status.startsWith("Could not") ? "var(--rec)" : "var(--ink-3)", marginBottom: 16 }}>
          {status}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <div>
          <SectionTitle>Vocabulary words</SectionTitle>
          <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginBottom: 8, marginTop: -6, lineHeight: 1.5 }}>
            Words collected from manual entries, OCR, and past transcriptions.
          </div>
          <Card padding={0}>
            <div style={{ display: "flex", gap: 8, padding: 12, borderBottom: "1px solid var(--line-soft)" }}>
              <Input placeholder="Add Codex, RTX 5090, WriterDuet..." value={newWord} onChange={setNewWord} style={{ flex: 1 }} />
              <Btn variant="ghost" size="sm" icon="plus" onClick={addWord} disabled={busy === "word"}>Add term</Btn>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1.4fr 70px 90px",
                padding: "11px 16px",
                borderBottom: "1px solid var(--line)",
                fontSize: 11,
                fontWeight: 600,
                color: "var(--ink-3)",
                textTransform: "uppercase",
                letterSpacing: "0.12em",
                background: "var(--bg-sunken)",
              }}
            >
              <span>Word</span>
              <span style={{ textAlign: "right" }}>Uses</span>
              <span style={{ textAlign: "right" }}>Source</span>
            </div>
            {visibleWords.map((v, i) => (
              <div
                key={`${v.word}-${i}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1.4fr 70px 90px",
                  padding: "11px 16px",
                  alignItems: "center",
                  borderTop: i === 0 ? "none" : "1px solid var(--line-soft)",
                }}
              >
                <span className="mono" style={{ fontSize: 13, color: "var(--ink)", fontWeight: 500 }}>{v.word}</span>
                <span className="mono" style={{ fontSize: 12, color: "var(--ink-3)", textAlign: "right" }}>{v.count}</span>
                <span style={{ fontSize: 12, color: "var(--ink-3)", textAlign: "right" }}>{v.source || "unknown"}</span>
              </div>
            ))}
            {hiddenWords > 0 && (
              <div style={{ padding: "14px 16px", textAlign: "center", color: "var(--ink-3)", fontSize: 12.5, borderTop: "1px solid var(--line-soft)" }}>
                Showing {visibleWords.length} of {words.length}. Search to narrow the list.
              </div>
            )}
            {words.length === 0 && (
              <div style={{ padding: "32px 20px", textAlign: "center", color: "var(--ink-3)", fontSize: 12.5 }}>No vocabulary words.</div>
            )}
          </Card>
        </div>

        <div>
          <SectionTitle>Replacement rules</SectionTitle>
          <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginBottom: 8, marginTop: -6, lineHeight: 1.5 }}>
            Find a phrase and replace it before paste, either everywhere or only in matching apps.
          </div>
          <Card padding={0}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 150px minmax(110px, 1fr) auto", gap: 8, padding: 12, borderBottom: "1px solid var(--line-soft)", alignItems: "center" }}>
              <Input placeholder="Find" value={newMatch} onChange={setNewMatch} />
              <Input placeholder="Replace with" value={newReplace} onChange={setNewReplace} />
              <Select value={newScopeType} onChange={setNewScopeType} options={RULE_SCOPE_OPTIONS} width="100%" small />
              <Input
                placeholder={newScopeType === "window" ? "Gmail, Timeline..." : newScopeType === "app" ? "resolve.exe, chrome..." : "Everywhere"}
                value={newScopeValue}
                onChange={setNewScopeValue}
                disabled={newScopeType === "global"}
              />
              <Btn variant="ghost" size="sm" icon="plus" onClick={addRule} disabled={busy === "rule"}>Add rule</Btn>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 24px 1fr 120px 70px",
                padding: "11px 16px",
                borderBottom: "1px solid var(--line)",
                fontSize: 11,
                fontWeight: 600,
                color: "var(--ink-3)",
                textTransform: "uppercase",
                letterSpacing: "0.12em",
                background: "var(--bg-sunken)",
                alignItems: "center",
              }}
            >
              <span>Find</span>
              <span></span>
              <span>Replace with</span>
              <span>Scope</span>
              <span style={{ textAlign: "right" }}>Enabled</span>
            </div>
            {visibleReplacements.map((v, i) => (
              <div
                key={v.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 24px 1fr 120px 70px",
                  padding: "11px 16px",
                  alignItems: "center",
                  gap: 4,
                  borderTop: i === 0 ? "none" : "1px solid var(--line-soft)",
                }}
              >
                <span className="mono" style={{ fontSize: 12.5, color: "var(--ink-1)" }}>{v.match_text}</span>
                <span style={{ display: "grid", placeItems: "center", color: "var(--ink-4)" }}>
                  <Icon name="chevron" size={12} />
                </span>
                <span className="mono" style={{ fontSize: 12.5, color: "var(--accent-ink)", fontWeight: 500 }}>{v.replace_with}</span>
                <span style={{ fontSize: 12, color: "var(--ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{scopeLabel(v.scope_type, v.scope_value)}</span>
                <span style={{ fontSize: 12, color: "var(--ink-3)", textAlign: "right" }}>{v.enabled ? "yes" : "no"}</span>
              </div>
            ))}
            {hiddenReplacements > 0 && (
              <div style={{ padding: "14px 16px", textAlign: "center", color: "var(--ink-3)", fontSize: 12.5, borderTop: "1px solid var(--line-soft)" }}>
                Showing {visibleReplacements.length} of {replacements.length}. Search to narrow the list.
              </div>
            )}
            {replacements.length === 0 && (
              <div style={{ padding: "32px 20px", textAlign: "center", color: "var(--ink-3)", fontSize: 12.5 }}>No replacement rules.</div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
