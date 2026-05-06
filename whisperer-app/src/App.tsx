import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Sidebar, TitleBar, EngineState } from "./chrome";
import { NAV_ITEMS, NavKey } from "./data";
import HomePage from "./pages/Home";
import ModesPage from "./pages/Modes";
import VocabPage from "./pages/Vocabulary";
import ConfigPage from "./pages/Configuration";
import SoundPage from "./pages/Sound";
import HistoryPage from "./pages/History";
import StatsPage from "./pages/Stats";
import type { MicOption } from "./primitives";

type Theme = "light" | "dark" | "sun";
type ResolvedTheme = "light" | "dark";
type Accent = "moss" | "sage" | "clay" | "copper" | "plum" | "slate";
type Density = "comfortable" | "compact";
type Wallpaper = "warm" | "cool" | "mono" | "sage";

export interface Tweaks {
  theme: Theme;
  accent: Accent;
  density: Density;
  wallpaper: Wallpaper;
}

export type BridgeOption = { value: string; label: string; hint?: string };
export type AppSettings = Record<string, any>;
export type MicLevel = { db: number; level: number; error?: string };
export type DictationBackup = {
  available: boolean;
  busy: boolean;
  status?: string;
  error?: string;
  sizeBytes?: number;
  durationSeconds?: number;
  modifiedAt?: string;
};
export type VocabularySnapshot = {
  wordCount: number;
  words: Array<{ word: string; count: number; source?: string; context?: string; last_seen?: string }>;
  rules: Array<{ id: number; match_text: string; replace_with: string; enabled: number; whole_word: number; case_sensitive: number }>;
  error?: string;
};
export type HistoryItem = {
  id: number;
  startedAt: string;
  app: string;
  windowTitle: string;
  mode: string;
  duration: number;
  words: number;
  text: string;
  rawText: string;
  finalText: string;
  error?: string;
  status: "ok" | "error";
  pasteSucceeded?: number | null;
  pasteMethod?: string;
  sttProvider?: string;
  sttModel?: string;
  audioPath?: string;
};
export type HistorySnapshot = {
  items: HistoryItem[];
  totals: { today: number; words: number; minutes: number };
  stats?: {
    totalDictations: number;
    totalWords: number;
    totalMinutes: number;
    topWords: Array<{ word: string; count: number }>;
    last7Days: Array<{ date: string; label: string; words: number; minutes: number; dictations: number }>;
  };
  error?: string;
};
export type ModeItem = {
  id: number;
  name: string;
  description: string;
  builtin: boolean;
  enabled: boolean;
  stt: string;
  sttModel: string;
  format: string;
  formattingPrompt: string;
  llm: boolean;
  llmProvider: string;
  llmModel: string;
  llmPrompt: string;
  pasteMethod: string;
  autoSend: boolean;
  ctxOcr: boolean;
  ctxSelectedText: boolean;
  ctxClipboard: boolean;
  auto: Array<{ id: number; type: string; value: string; priority: number; enabled: boolean }>;
};

export interface AppSnapshot {
  version?: string;
  engineState?: EngineState;
  settings?: AppSettings;
  models?: BridgeOption[];
  gpus?: BridgeOption[];
  microphones?: MicOption[];
  inputChannels?: BridgeOption[];
  selectedModel?: string;
  selectedGpu?: string;
  selectedMicrophone?: string;
  selectedInputChannel?: string;
  activeMode?: string;
  shortcuts?: Record<string, string[]>;
  micLevel?: MicLevel;
  dictationBackup?: DictationBackup;
  apiKeys?: Record<string, { saved?: boolean; masked?: string }>;
  vocabulary?: VocabularySnapshot;
  history?: HistorySnapshot;
  modesData?: ModeItem[];
  createdModeId?: number;
}

const DEFAULT_TWEAKS: Tweaks = {
  theme: "light",
  accent: "moss",
  density: "comfortable",
  wallpaper: "warm",
};

const DEFAULT_MODELS: BridgeOption[] = [
  { value: "nvidia/parakeet-tdt-0.6b-v2", label: "NVIDIA Parakeet TDT 0.6B RNNT streaming" },
  { value: "nvidia/parakeet-ctc-0.6b", label: "NVIDIA Parakeet CTC 0.6B (RNNT streaming)" },
  { value: "nvidia/parakeet-unified-en-0.6b", label: "NVIDIA Parakeet Unified 0.6B (RNNT streaming)" },
  { value: "deepdml/faster-whisper-large-v3-turbo-ct2", label: "Whisper v3 Turbo" },
  { value: "large-v3", label: "Whisper Large v3" },
];

const API_GPU_VALUES = new Set(["groq_api", "grok_api", "nvidia_api"]);
const DEFAULT_GPUS: BridgeOption[] = [
  { value: "nvidia_api", label: "NVIDIA API Parakeet" },
  { value: "groq_api", label: "Groq API (Whisper)" },
];
const DEFAULT_MICROPHONES: MicOption[] = [{ value: "default", label: "System default microphone", hint: "Auto" }];
const DEFAULT_CHANNELS: BridgeOption[] = [{ value: "0", label: "Channel 1" }];
const DEFAULT_MIC_LEVEL: MicLevel = { db: -96, level: 0 };
const DEFAULT_DICTATION_BACKUP: DictationBackup = { available: false, busy: false };
const DEFAULT_API_KEYS: Record<string, { saved?: boolean; masked?: string }> = {};
const DEFAULT_VOCABULARY: VocabularySnapshot = { wordCount: 0, words: [], rules: [] };
const DEFAULT_HISTORY: HistorySnapshot = { items: [], totals: { today: 0, words: 0, minutes: 0 } };
const DEFAULT_MODES: ModeItem[] = [];

const THEMES: Theme[] = ["light", "dark", "sun"];
const ACCENTS: Accent[] = ["moss", "sage", "clay", "copper", "plum", "slate"];
const DENSITIES: Density[] = ["comfortable", "compact"];

const TIMEZONE_COORDS: Record<string, { lat: number; lon: number }> = {
  "America/Los_Angeles": { lat: 34.0522, lon: -118.2437 },
  "America/Vancouver": { lat: 49.2827, lon: -123.1207 },
  "America/Denver": { lat: 39.7392, lon: -104.9903 },
  "America/Phoenix": { lat: 33.4484, lon: -112.074 },
  "America/Chicago": { lat: 41.8781, lon: -87.6298 },
  "America/New_York": { lat: 40.7128, lon: -74.006 },
  "America/Anchorage": { lat: 61.2181, lon: -149.9003 },
  "Pacific/Honolulu": { lat: 21.3069, lon: -157.8583 },
  "Europe/London": { lat: 51.5072, lon: -0.1276 },
  "Europe/Paris": { lat: 48.8566, lon: 2.3522 },
};

function normalizeDegrees(value: number) {
  return ((value % 360) + 360) % 360;
}

function dayOfYear(date: Date) {
  const start = Date.UTC(date.getFullYear(), 0, 0);
  const current = Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
  return Math.floor((current - start) / 86400000);
}

function solarEvent(date: Date, lat: number, lon: number, sunrise: boolean): Date | null {
  const n = dayOfYear(date);
  const lngHour = lon / 15;
  const t = n + ((sunrise ? 6 : 18) - lngHour) / 24;
  const meanAnomaly = 0.9856 * t - 3.289;
  const trueLongitude = normalizeDegrees(
    meanAnomaly
      + 1.916 * Math.sin(meanAnomaly * Math.PI / 180)
      + 0.02 * Math.sin(2 * meanAnomaly * Math.PI / 180)
      + 282.634
  );
  let rightAscension = Math.atan(0.91764 * Math.tan(trueLongitude * Math.PI / 180)) * 180 / Math.PI;
  rightAscension = normalizeDegrees(rightAscension);
  rightAscension += Math.floor(trueLongitude / 90) * 90 - Math.floor(rightAscension / 90) * 90;
  rightAscension /= 15;
  const sinDec = 0.39782 * Math.sin(trueLongitude * Math.PI / 180);
  const cosDec = Math.cos(Math.asin(sinDec));
  const cosH = (
    Math.cos(90.833 * Math.PI / 180)
    - sinDec * Math.sin(lat * Math.PI / 180)
  ) / (cosDec * Math.cos(lat * Math.PI / 180));
  if (cosH > 1 || cosH < -1) return null;
  const hourAngle = (sunrise ? 360 - Math.acos(cosH) * 180 / Math.PI : Math.acos(cosH) * 180 / Math.PI) / 15;
  const localMean = hourAngle + rightAscension - 0.06571 * t - 6.622;
  const utcHour = ((localMean - lngHour) % 24 + 24) % 24;
  const targetYear = date.getFullYear();
  const targetMonth = date.getMonth();
  const targetDate = date.getDate();
  let event = new Date(Date.UTC(targetYear, targetMonth, targetDate) + utcHour * 3600000);

  for (let i = 0; i < 2; i += 1) {
    const eventDay = new Date(event);
    if (
      eventDay.getFullYear() === targetYear
      && eventDay.getMonth() === targetMonth
      && eventDay.getDate() === targetDate
    ) {
      break;
    }
    event = new Date(event.getTime() + (eventDay < date ? 86400000 : -86400000));
  }
  return event;
}

function resolveSunTheme(now = new Date()): ResolvedTheme {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  const coords = TIMEZONE_COORDS[zone] || { lat: 34.0522, lon: -118.2437 };
  const sunrise = solarEvent(now, coords.lat, coords.lon, true);
  const sunset = solarEvent(now, coords.lat, coords.lon, false);
  if (!sunrise || !sunset) {
    const hour = now.getHours() + now.getMinutes() / 60;
    return hour >= 7 && hour < 18 ? "light" : "dark";
  }
  return now >= sunrise && now < sunset ? "light" : "dark";
}

function normalizeUiTweaks(ui: Record<string, any> | undefined, current: Tweaks): Tweaks {
  const rawAccent = String(ui?.accent ?? current.accent);
  const accentAliases: Record<string, Accent> = {
    cyan: "sage",
    amber: "copper",
    green: "moss",
    violet: "plum",
    mono: "slate",
  };
  const accent = ACCENTS.includes(rawAccent as Accent) ? rawAccent as Accent : accentAliases[rawAccent] || current.accent;
  const theme = THEMES.includes(ui?.theme) ? ui?.theme as Theme : current.theme;
  const density = DENSITIES.includes(ui?.density) ? ui?.density as Density : current.density;
  return { ...current, theme, accent, density };
}

function parseSnapshot(raw: string | AppSnapshot | undefined): AppSnapshot | null {
  if (!raw) return null;
  if (typeof raw !== "string") return raw;
  try {
    return JSON.parse(raw) as AppSnapshot;
  } catch {
    return null;
  }
}

export default function App() {
  const [activePage, setActivePage] = useState<NavKey>("home");
  const [engineState, setEngineState] = useState<EngineState>("stopped");
  const [version, setVersion] = useState("6.0.7");
  const [settings, setSettings] = useState<AppSettings>({});
  const [models, setModels] = useState<BridgeOption[]>(DEFAULT_MODELS);
  const [gpus, setGpus] = useState<BridgeOption[]>(DEFAULT_GPUS);
  const [microphones, setMicrophones] = useState<MicOption[]>(DEFAULT_MICROPHONES);
  const [inputChannels, setInputChannels] = useState<BridgeOption[]>(DEFAULT_CHANNELS);
  const [model, setModelState] = useState(DEFAULT_MODELS[0].value);
  const [gpu, setGpuState] = useState("nvidia_api");
  const [mic, setMicState] = useState("default");
  const [inputChannel, setInputChannelState] = useState("0");
  const [shortcuts, setShortcuts] = useState<Record<string, string[]>>({ dictation: ["Ctrl", "Left Windows"] });
  const [micLevel, setMicLevel] = useState<MicLevel>(DEFAULT_MIC_LEVEL);
  const [dictationBackup, setDictationBackup] = useState<DictationBackup>(DEFAULT_DICTATION_BACKUP);
  const [apiKeys, setApiKeys] = useState<Record<string, { saved?: boolean; masked?: string }>>(DEFAULT_API_KEYS);
  const [vocabulary, setVocabulary] = useState<VocabularySnapshot>(DEFAULT_VOCABULARY);
  const [history, setHistory] = useState<HistorySnapshot>(DEFAULT_HISTORY);
  const [modesData, setModesData] = useState<ModeItem[]>(DEFAULT_MODES);
  const [activeMode, setActiveMode] = useState("Voice");
  const [tweaks, setTweaks] = useState<Tweaks>(DEFAULT_TWEAKS);
  const [sunTheme, setSunTheme] = useState<ResolvedTheme>(() => resolveSunTheme());
  const [resizeHandleVisible, setResizeHandleVisible] = useState(false);
  const pageFetchTs = useRef<Record<string, number>>({});

  const selectPage = useCallback((page: NavKey) => {
    setActivePage((current) => current === page ? current : page);
  }, []);

  const applySnapshot = useCallback((raw: string | AppSnapshot | undefined) => {
    const snapshot = parseSnapshot(raw);
    if (!snapshot) return;
    if (snapshot.version) setVersion(snapshot.version);
    if (snapshot.engineState) setEngineState(snapshot.engineState);
    if (snapshot.settings) {
      setSettings(snapshot.settings);
      setTweaks((current) => normalizeUiTweaks(snapshot.settings?.ui, current));
    }
    if (snapshot.models?.length) setModels(snapshot.models);
    if (snapshot.gpus?.length) setGpus(snapshot.gpus);
    if (snapshot.microphones?.length) setMicrophones(snapshot.microphones);
    if (snapshot.inputChannels?.length) setInputChannels(snapshot.inputChannels);
    if (snapshot.selectedModel) setModelState(snapshot.selectedModel);
    if (snapshot.selectedGpu) setGpuState(snapshot.selectedGpu);
    if (snapshot.selectedMicrophone) setMicState(snapshot.selectedMicrophone);
    if (snapshot.selectedInputChannel) setInputChannelState(snapshot.selectedInputChannel);
    if (snapshot.activeMode) setActiveMode(snapshot.activeMode);
    if (snapshot.shortcuts) setShortcuts(snapshot.shortcuts);
    if (snapshot.micLevel) setMicLevel(snapshot.micLevel);
    if (snapshot.dictationBackup) setDictationBackup(snapshot.dictationBackup);
    if (snapshot.apiKeys) setApiKeys(snapshot.apiKeys);
    if (snapshot.vocabulary) setVocabulary(snapshot.vocabulary);
    if (snapshot.history) setHistory(snapshot.history);
    if (snapshot.modesData) setModesData(snapshot.modesData);
  }, []);

  const requestSnapshot = useCallback(() => {
    window.whisperer?.appSnapshot?.().then(applySnapshot).catch(() => {});
  }, [applySnapshot]);

  const requestVocabulary = useCallback(() => {
    window.whisperer?.vocabularySnapshot?.().then(applySnapshot).catch(() => {});
  }, [applySnapshot]);

  const requestHistory = useCallback(() => {
    window.whisperer?.historySnapshot?.().then(applySnapshot).catch(() => {});
  }, [applySnapshot]);

  const requestModes = useCallback(() => {
    window.whisperer?.modesSnapshot?.().then(applySnapshot).catch(() => {});
  }, [applySnapshot]);

  useEffect(() => {
    const onReady = () => requestSnapshot();
    const onState = (e: Event) => {
      const detail = (e as CustomEvent<string>).detail;
      if (detail === "running" || detail === "loading" || detail === "stopped") {
        setEngineState(detail);
      }
    };
    const onSettings = (e: Event) => applySnapshot((e as CustomEvent<string>).detail);
    window.addEventListener("whisperer:ready", onReady);
    window.addEventListener("whisperer:engineState", onState as EventListener);
    window.addEventListener("whisperer:settings", onSettings as EventListener);
    requestSnapshot();
    return () => {
      window.removeEventListener("whisperer:ready", onReady);
      window.removeEventListener("whisperer:engineState", onState as EventListener);
      window.removeEventListener("whisperer:settings", onSettings as EventListener);
    };
  }, [applySnapshot, requestSnapshot]);

  useEffect(() => {
    const id = window.setTimeout(() => {
      const fetchKey = activePage === "stats" ? "history" : activePage;
      const now = Date.now();
      if (now - (pageFetchTs.current[fetchKey] || 0) < 2500) return;
      pageFetchTs.current[fetchKey] = now;
      if (activePage === "vocabulary") requestVocabulary();
      if (activePage === "history" || activePage === "stats") requestHistory();
      if (activePage === "modes") requestModes();
    }, 140);
    return () => window.clearTimeout(id);
  }, [activePage, requestVocabulary, requestHistory, requestModes]);

  useEffect(() => {
    let timer = 0;
    const markScrolling = (event: Event) => {
      const target = event.target as HTMLElement | null;
      const scroller = target?.closest?.(".scroll");
      if (!scroller) return;
      scroller.classList.add("is-scrolling");
      window.clearTimeout(timer);
      timer = window.setTimeout(() => scroller.classList.remove("is-scrolling"), 700);
    };
    document.addEventListener("scroll", markScrolling, true);
    return () => {
      document.removeEventListener("scroll", markScrolling, true);
      window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    const resolvedTheme: ResolvedTheme = tweaks.theme === "sun" ? sunTheme : tweaks.theme;
    document.body.dataset.theme = resolvedTheme;
    document.body.dataset.density = tweaks.density;
    const accents: Record<Accent, { solid: string; softLight: string; softDark: string; inkLight: string; inkDark: string }> = {
      moss: { solid: "#5f8f6b", softLight: "rgba(95,143,107,0.15)", softDark: "rgba(95,143,107,0.28)", inkLight: "#466f51", inkDark: "#9bc7a5" },
      sage: { solid: "#5f8d86", softLight: "rgba(95,141,134,0.15)", softDark: "rgba(95,141,134,0.28)", inkLight: "#456e68", inkDark: "#9ac7c0" },
      clay: { solid: "#a67b5d", softLight: "rgba(166,123,93,0.16)", softDark: "rgba(166,123,93,0.30)", inkLight: "#7d5c45", inkDark: "#d1a88c" },
      copper: { solid: "#b2874d", softLight: "rgba(178,135,77,0.17)", softDark: "rgba(178,135,77,0.30)", inkLight: "#806238", inkDark: "#dbb77a" },
      plum: { solid: "#9a6b8e", softLight: "rgba(154,107,142,0.16)", softDark: "rgba(154,107,142,0.30)", inkLight: "#744e6a", inkDark: "#cca1c2" },
      slate: { solid: "#747f93", softLight: "rgba(116,127,147,0.15)", softDark: "rgba(116,127,147,0.30)", inkLight: "#586274", inkDark: "#b0bacb" },
    };
    const a = accents[tweaks.accent];
    document.documentElement.style.setProperty("--accent", a.solid);
    document.documentElement.style.setProperty("--accent-soft", resolvedTheme === "dark" ? a.softDark : a.softLight);
    document.documentElement.style.setProperty("--accent-ink", resolvedTheme === "dark" ? a.inkDark : a.inkLight);

    document.body.style.background = "var(--bg-desktop)";
  }, [tweaks, sunTheme]);

  useEffect(() => {
    const update = () => setSunTheme(resolveSunTheme());
    update();
    const id = window.setInterval(update, 60000);
    return () => window.clearInterval(id);
  }, []);

  const modelLabel = useCallback((value: string) => {
    return models.find((item) => item.value === value)?.label || value;
  }, [models]);

  const needsLocalModelDownloadConfirm = useCallback(async (modelValue: string) => {
    if (API_GPU_VALUES.has(gpu) || !window.whisperer?.modelCacheStatus) return false;
    try {
      const payload = JSON.parse(await window.whisperer.modelCacheStatus(modelValue));
      return !payload.cached;
    } catch {
      return true;
    }
  }, [gpu]);

  const confirmLocalModelDownload = useCallback((modelValue: string) => {
    return window.confirm(
      `${modelLabel(modelValue)} is not downloaded locally yet.\n\n` +
      "Whisperer will download the model before it can use a local GPU. Continue?"
    );
  }, [modelLabel]);

  const setModel = useCallback(async (value: string) => {
    if (await needsLocalModelDownloadConfirm(value)) {
      if (!confirmLocalModelDownload(value)) return;
    }
    setModelState(value);
    window.whisperer?.setModel?.(value).then(applySnapshot).catch(() => {});
  }, [applySnapshot, confirmLocalModelDownload, needsLocalModelDownloadConfirm]);

  const setGpu = useCallback(async (value: string) => {
    if (!API_GPU_VALUES.has(value)) {
      if (window.whisperer?.localEngineStatus) {
        try {
          const status = JSON.parse(await window.whisperer.localEngineStatus(model));
          if (!status.available) {
            window.alert(status.message || "Local GPU transcription is not available in this installation.");
            requestSnapshot();
            return;
          }
        } catch {
          window.alert("Whisperer could not verify the local GPU runtime on this computer.");
          requestSnapshot();
          return;
        }
      }
    }
    if (!API_GPU_VALUES.has(value) && window.whisperer?.modelCacheStatus) {
      try {
        const payload = JSON.parse(await window.whisperer.modelCacheStatus(model));
        if (!payload.cached && !confirmLocalModelDownload(model)) return;
      } catch {
        if (!confirmLocalModelDownload(model)) return;
      }
    }
    setGpuState(value);
    window.whisperer?.setGpu?.(value).then(applySnapshot).catch(() => {});
  }, [applySnapshot, confirmLocalModelDownload, model, requestSnapshot]);

  const setMic = useCallback((value: string) => {
    setMicState(value);
    window.whisperer?.setMicrophone?.(value).then(applySnapshot).catch(() => {});
  }, [applySnapshot]);

  const setInputChannel = useCallback((value: string) => {
    setInputChannelState(value);
    window.whisperer?.setInputChannel?.(value).then(applySnapshot).catch(() => {});
  }, [applySnapshot]);

  const setSetting = useCallback((section: string, key: string, value: unknown) => {
    setSettings((current) => ({ ...current, [section]: { ...(current[section] || {}), [key]: value } }));
    window.whisperer?.setSetting?.(section, key, value).then(applySnapshot).catch(() => {});
  }, [applySnapshot]);

  const setShortcut = useCallback((name: string, value: string) => {
    setShortcuts((current) => ({ ...current, [name]: value.split("+").map((part) => part.trim()).filter(Boolean) }));
    window.whisperer?.setShortcut?.(name, value).then(applySnapshot).catch(() => {});
  }, [applySnapshot]);

  const transcribeLastDictation = useCallback(() => {
    window.whisperer?.transcribeLastDictation?.().then(applySnapshot).catch(() => {});
  }, [applySnapshot]);

  const pageTitle = NAV_ITEMS.find((n) => n.key === activePage)?.label || "";
  const densityScale = tweaks.density === "compact" ? 0.96 : 1;
  const dictationKeys = shortcuts.dictation?.length ? shortcuts.dictation : ["Ctrl", "Left Windows"];
  const versionShort = useMemo(() => version.replace(/^v/i, ""), [version]);

  const startWindowDrag = (event: React.MouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest("[data-no-drag], button, input, select, textarea, a, [role='switch']")) return;

    const scroller = target.closest(".scroll") as HTMLElement | null;
    if (scroller) {
      const rect = scroller.getBoundingClientRect();
      const styles = window.getComputedStyle(scroller);
      const canScrollY = scroller.scrollHeight > scroller.clientHeight && styles.overflowY !== "hidden";
      const canScrollX = scroller.scrollWidth > scroller.clientWidth && styles.overflowX !== "hidden";
      const gutter = 18;
      if ((canScrollY && event.clientX >= rect.right - gutter) || (canScrollX && event.clientY >= rect.bottom - gutter)) return;
    }

    window.whisperer?.startDrag?.();
  };

  const startWindowResize = (event: React.MouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    window.whisperer?.startResize?.();
  };

  return (
    <div
      onMouseDown={startWindowDrag}
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        background: "var(--bg)",
        border: "none",
        borderRadius: 0,
        boxShadow: "none",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        backdropFilter: "none",
        fontSize: `${densityScale * 100}%`,
      }}
    >
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <Sidebar
          active={activePage}
          onSelect={selectPage}
          version={versionShort}
        />

        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, background: "var(--bg)" }}>
          <TitleBar
            pageTitle={pageTitle}
            micName={mic}
            micOptions={microphones}
            onMicChange={setMic}
          />
          <div style={{ flex: 1, minHeight: 0, overflow: "hidden", position: "relative" }}>
            {activePage === "home" && (
              <HomePage
                engineState={engineState}
                setEngineState={setEngineState}
                model={model}
                setModel={setModel}
                models={models}
                gpu={gpu}
                setGpu={setGpu}
                gpus={gpus}
                onNav={selectPage}
                activeMode={activeMode}
                dictationKeys={dictationKeys}
                dictationBackup={dictationBackup}
                onTranscribeLastDictation={transcribeLastDictation}
                apiKeys={apiKeys}
              />
            )}
            {activePage === "modes" && <ModesPage modes={modesData} applySnapshot={applySnapshot} />}
            {activePage === "vocabulary" && <VocabPage vocabulary={vocabulary} applySnapshot={applySnapshot} />}
            {activePage === "configuration" && (
              <ConfigPage
                tweaks={tweaks}
                setTweaks={setTweaks}
                settings={settings}
                apiKeys={apiKeys}
                shortcuts={shortcuts}
                setSetting={setSetting}
                setShortcut={setShortcut}
              />
            )}
            {activePage === "sound" && (
              <SoundPage
                settings={settings}
                microphones={microphones}
                mic={mic}
                setMic={setMic}
                inputChannels={inputChannels}
                inputChannel={inputChannel}
                setInputChannel={setInputChannel}
                setSetting={setSetting}
              />
            )}
            {activePage === "history" && <HistoryPage history={history} applySnapshot={applySnapshot} />}
            {activePage === "stats" && <StatsPage history={history} />}
          </div>
        </div>
      </div>
      <div
        data-no-drag
        onMouseEnter={() => setResizeHandleVisible(true)}
        onMouseLeave={() => setResizeHandleVisible(false)}
        onMouseDown={startWindowResize}
        title="Resize"
        style={{
          position: "absolute",
          right: 0,
          bottom: 0,
          width: 38,
          height: 38,
          zIndex: 30,
          cursor: "nwse-resize",
          WebkitAppRegion: "no-drag",
        } as React.CSSProperties}
      >
        <span
          style={{
            position: "absolute",
            right: 6,
            bottom: 6,
            width: 10,
            height: 10,
            clipPath: "polygon(100% 0, 100% 100%, 0 100%)",
            background: "var(--ink-4)",
            opacity: resizeHandleVisible ? 0.38 : 0,
            transform: resizeHandleVisible ? "translate(0, 0)" : "translate(3px, 3px)",
            transition: "opacity 140ms ease, transform 180ms cubic-bezier(.16,1,.3,1)",
            pointerEvents: "none",
          }}
        />
      </div>
    </div>
  );
}
