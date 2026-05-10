import React, { CSSProperties, ReactNode, useEffect, useMemo, useRef, useState } from "react";

// ─── Icons ────────────────────────────────────────────────────────────────────
export type IconName =
  | "home" | "modes" | "vocab" | "config" | "sound" | "history" | "stats"
  | "mic" | "play" | "stop" | "plus" | "search" | "chevron" | "chevdown"
  | "check" | "copy" | "trash" | "edit" | "dot" | "minimize" | "maximize"
  | "close" | "filter" | "reveal" | "lock" | "info" | "shield" | "cpu"
  | "wave" | "menu";

export const Icon = ({
  name,
  size = 16,
  stroke = 1.5,
  className = "",
}: {
  name: IconName;
  size?: number;
  stroke?: number;
  className?: string;
}) => {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: stroke,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className,
  };
  switch (name) {
    case "home":      return <svg {...common}><path d="M4 11l8-7 8 7v9a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z"/></svg>;
    case "modes":     return <svg {...common}><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.5 6h7M8.5 18h7M6 8.5v7M18 8.5v7"/></svg>;
    case "vocab":     return <svg {...common}><path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/></svg>;
    case "config":    return <svg {...common}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>;
    case "sound":     return <svg {...common}><path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/></svg>;
    case "history":   return <svg {...common}><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 7v5l3 2"/></svg>;
    case "stats":     return <svg {...common}><path d="M4 19V5"/><path d="M4 19h16"/><rect x="7" y="11" width="3" height="5" rx="1.2"/><rect x="12" y="7" width="3" height="9" rx="1.2"/><rect x="17" y="9" width="3" height="7" rx="1.2"/></svg>;
    case "mic":       return <svg {...common}><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/></svg>;
    case "play":      return <svg {...common}><path d="M6 4l14 8-14 8z" fill="currentColor"/></svg>;
    case "stop":      return <svg {...common}><rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor"/></svg>;
    case "plus":      return <svg {...common}><path d="M12 5v14M5 12h14"/></svg>;
    case "search":    return <svg {...common}><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>;
    case "chevron":   return <svg {...common}><path d="M9 6l6 6-6 6"/></svg>;
    case "chevdown":  return <svg {...common}><path d="M6 9l6 6 6-6"/></svg>;
    case "check":     return <svg {...common}><path d="M5 12l4 4L19 6"/></svg>;
    case "copy":      return <svg {...common}><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/></svg>;
    case "trash":     return <svg {...common}><path d="M4 7h16M9 7V4h6v3M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/></svg>;
    case "edit":      return <svg {...common}><path d="M4 20l4-1 11-11-3-3L5 16zM14 6l3 3"/></svg>;
    case "dot":       return <svg {...common}><circle cx="12" cy="12" r="4" fill="currentColor"/></svg>;
    case "minimize":  return <svg {...common}><path d="M5 12h14"/></svg>;
    case "maximize":  return <svg {...common}><rect x="5" y="5" width="14" height="14" rx="1.5"/></svg>;
    case "close":     return <svg {...common}><path d="M6 6l12 12M18 6L6 18"/></svg>;
    case "filter":    return <svg {...common}><path d="M4 5h16l-6 8v6l-4-2v-4z"/></svg>;
    case "reveal":    return <svg {...common}><path d="M3 12l4-4M3 12l4 4M3 12h12M21 5v14"/></svg>;
    case "lock":      return <svg {...common}><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>;
    case "info":      return <svg {...common}><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/></svg>;
    case "shield":    return <svg {...common}><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/></svg>;
    case "cpu":       return <svg {...common}><rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/></svg>;
    case "wave":      return <svg {...common}><path d="M3 12h2M7 9v6M10 6v12M13 9v6M16 4v16M19 9v6M21 12h0"/></svg>;
    case "menu":      return <svg {...common}><path d="M4 6h16M4 12h16M4 18h16"/></svg>;
    default:          return null;
  }
};

// ─── Card / Eyebrow / SectionTitle ──────────────────────────────────────────
export const Card = ({
  children,
  style,
  className = "",
  padding = "var(--card-padding, 18px)",
}: {
  children: ReactNode;
  style?: CSSProperties;
  className?: string;
  padding?: number | string;
}) => (
  <div
    data-no-drag
    className={className}
    style={{
      background: "var(--card)",
      border: "1px solid var(--line)",
      borderRadius: "var(--radius)",
      boxShadow: "var(--shadow-card)",
      padding,
      ...style,
    }}
  >
    {children}
  </div>
);

export const Eyebrow = ({ children }: { children: ReactNode }) => (
  <div style={{ textTransform: "uppercase", letterSpacing: "0.14em", fontSize: 10.5, fontWeight: 600, color: "var(--ink-3)" }}>
    {children}
  </div>
);

export const SectionTitle = ({ children, right }: { children: ReactNode; right?: ReactNode }) => (
  <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 10 }}>
    <h2 style={{ fontSize: 13, fontWeight: 600, color: "var(--ink-2)", margin: 0, letterSpacing: "-0.005em" }}>{children}</h2>
    {right}
  </div>
);

// ─── Btn ─────────────────────────────────────────────────────────────────────
type BtnVariant = "primary" | "secondary" | "ghost" | "accent" | "danger" | "rec";
type BtnSize = "sm" | "md" | "lg";

export const Btn = ({
  children,
  variant = "secondary",
  size = "md",
  onClick,
  disabled,
  icon,
  style,
}: {
  children?: ReactNode;
  variant?: BtnVariant;
  size?: BtnSize;
  onClick?: () => void;
  disabled?: boolean;
  icon?: IconName;
  style?: CSSProperties;
}) => {
  const sizes = ({ sm: { h: 26, fs: 12, px: 10 }, md: { h: 32, fs: 13, px: 13 }, lg: { h: 38, fs: 14, px: 16 } } as const)[size];
  const base: CSSProperties = {
    height: sizes.h,
    fontSize: sizes.fs,
    padding: `0 ${sizes.px}px`,
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    border: "1px solid transparent",
    borderRadius: 8,
    cursor: disabled ? "not-allowed" : "pointer",
    fontWeight: 500,
    letterSpacing: "-0.005em",
    transition: "background 120ms, border 120ms, color 120ms, transform 80ms",
    opacity: disabled ? 0.45 : 1,
  };
  const variants: Record<BtnVariant, CSSProperties> = {
    primary:   { background: "var(--ink)",    color: "var(--bg)",    border: "1px solid var(--ink)" },
    secondary: { background: "var(--card)",   color: "var(--ink-1)", border: "1px solid var(--line)" },
    ghost:     { background: "transparent",   color: "var(--ink-1)", border: "1px solid transparent" },
    accent:    { background: "var(--accent)", color: "white",        border: "1px solid var(--accent)" },
    danger:    { background: "var(--card)",   color: "var(--rec)",   border: "1px solid var(--line)" },
    rec:       { background: "var(--rec)",    color: "white",        border: "1px solid var(--rec)" },
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{ ...base, ...variants[variant], ...style }}
      onMouseDown={(e) => !disabled && (e.currentTarget.style.transform = "translateY(1px)")}
      onMouseUp={(e) => !disabled && (e.currentTarget.style.transform = "")}
      onMouseLeave={(e) => !disabled && (e.currentTarget.style.transform = "")}
    >
      {icon && <Icon name={icon} size={sizes.fs + 2} />}
      {children}
    </button>
  );
};

// ─── Toggle ──────────────────────────────────────────────────────────────────
export const Toggle = ({
  checked,
  onChange,
  size = "md",
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  size?: "sm" | "md";
}) => {
  const w = size === "sm" ? 28 : 34;
  const h = size === "sm" ? 16 : 20;
  const knob = h - 4;
  const inset = 2;
  const travel = w - knob - inset * 2;
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      style={{
        width: w,
        height: h,
        boxSizing: "border-box",
        borderRadius: h,
        border: "1px solid var(--line)",
        padding: 0,
        appearance: "none",
        background: checked ? "var(--accent)" : "var(--bg-sunken)",
        position: "relative",
        cursor: "pointer",
        transition: "background 160ms, border-color 160ms",
      }}
    >
      <span
        style={{
          position: "absolute",
          top: "50%",
          left: inset,
          width: knob,
          height: knob,
          borderRadius: knob,
          background: "white",
          boxShadow: "0 1px 2px rgba(0,0,0,0.2)",
          transform: `translate(${checked ? travel : 0}px, -50%)`,
          transition: "transform 160ms cubic-bezier(.2,.7,.2,1), box-shadow 160ms",
        }}
      />
    </button>
  );
};

// ─── Select ──────────────────────────────────────────────────────────────────
export type SelectOption = string | { value: string; label: string; hint?: string };

export const Select = ({
  value,
  onChange,
  options,
  width = "auto",
  small = false,
}: {
  value: string;
  onChange: (v: string) => void;
  options: SelectOption[];
  width?: number | string;
  small?: boolean;
}) => {
  const h = small ? 28 : 32;
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  const normalized = useMemo(
    () => options.map((o) => typeof o === "string" ? { value: o, label: o } : o),
    [options]
  );
  const current = useMemo(
    () => normalized.find((o) => o.value === value) || normalized[0],
    [normalized, value]
  );
  const currentLabel = current?.label || "";
  const shortLabel = currentLabel.length > 32 ? currentLabel.slice(0, 30) + "..." : currentLabel;
  return (
    <div ref={ref} style={{ position: "relative", display: "inline-flex", width }} data-no-drag>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          height: h,
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          padding: "0 10px 0 12px",
          background: open ? "var(--card)" : "var(--bg-sunken)",
          border: "1px solid var(--line-soft)",
          borderRadius: 999,
          fontFamily: "inherit",
          fontSize: small ? 12 : 13,
          color: "var(--ink-1)",
          cursor: "pointer",
          letterSpacing: "-0.005em",
        }}
      >
        <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{shortLabel}</span>
        <Icon name="chevdown" size={12} />
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: h + 6,
            right: 0,
            minWidth: typeof width === "number" ? width : 220,
            maxHeight: 280,
            overflowY: "auto",
            background: "var(--menu-bg)",
            border: "1px solid var(--line)",
            borderRadius: 12,
            boxShadow: "var(--shadow-menu)",
            padding: 6,
            zIndex: 200,
          }}
        >
          {normalized.map((o) => {
            const active = o.value === value;
            return (
              <button
                key={o.value}
                type="button"
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 9,
                  width: "100%",
                  padding: "8px 10px",
                  background: active ? "var(--menu-active)" : "transparent",
                  border: "none",
                  borderRadius: 8,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  textAlign: "left",
                }}
              >
                <span style={{ width: 14, display: "grid", placeItems: "center", color: active ? "var(--accent)" : "transparent" }}>
                  <Icon name="check" size={13} stroke={2} />
                </span>
                <span style={{ flex: 1, minWidth: 0, fontSize: 12.5, color: "var(--ink)", fontWeight: active ? 500 : 400, letterSpacing: "-0.005em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{o.label}</span>
                {o.hint && <span style={{ fontSize: 10.5, color: "var(--ink-3)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 600 }}>{o.hint}</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

// ─── Input ───────────────────────────────────────────────────────────────────
export const Input = ({
  value,
  onChange,
  placeholder,
  icon,
  style,
  type = "text",
  onBlur,
  autoFocus = false,
  disabled = false,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  icon?: IconName;
  style?: CSSProperties;
  type?: string;
  onBlur?: () => void;
  autoFocus?: boolean;
  disabled?: boolean;
}) => (
  <div style={{ position: "relative", display: "flex", alignItems: "center", ...style }}>
    {icon && (
      <span style={{ position: "absolute", left: 10, color: "var(--ink-3)", display: "flex" }}>
        <Icon name={icon} size={15} />
      </span>
    )}
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
      placeholder={placeholder}
      autoFocus={autoFocus}
      disabled={disabled}
      style={{
        width: "100%",
        height: 32,
        padding: icon ? "0 11px 0 32px" : "0 11px",
        background: "var(--card)",
        border: "1px solid var(--line)",
        borderRadius: 8,
        fontFamily: "inherit",
        fontSize: 13,
        color: "var(--ink)",
        opacity: disabled ? 0.58 : 1,
        outline: "none",
        letterSpacing: "-0.005em",
      }}
    />
  </div>
);

// ─── Pill ────────────────────────────────────────────────────────────────────
type PillTone = "neutral" | "accent" | "rec" | "ok" | "soft";
export const Pill = ({
  children,
  tone = "neutral",
  style,
}: {
  children: ReactNode;
  tone?: PillTone;
  style?: CSSProperties;
}) => {
  const tones: Record<PillTone, { bg: string; border: string; ink: string }> = {
    neutral: { bg: "var(--bg-sunken)", border: "var(--line)", ink: "var(--ink-2)" },
    accent:  { bg: "var(--accent-soft)", border: "var(--accent-soft)", ink: "var(--accent-ink)" },
    rec:     { bg: "var(--rec-soft)", border: "var(--rec-soft)", ink: "var(--rec)" },
    ok:      { bg: "var(--bg-sunken)", border: "var(--line)", ink: "var(--ok)" },
    soft:    { bg: "transparent", border: "var(--line)", ink: "var(--ink-2)" },
  };
  const t = tones[tone];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        height: 22,
        padding: "0 9px",
        background: t.bg,
        border: `1px solid ${t.border}`,
        borderRadius: 999,
        fontSize: 11.5,
        fontWeight: 500,
        color: t.ink,
        letterSpacing: "-0.005em",
        ...style,
      }}
    >
      {children}
    </span>
  );
};

// ─── Keycap / KeyCombo ──────────────────────────────────────────────────────
export const Keycap = ({ children }: { children: ReactNode }) => (
  <kbd
    className="mono"
    style={{
      display: "inline-flex",
      alignItems: "center",
      height: 22,
      minWidth: 22,
      padding: "0 7px",
      background: "var(--card)",
      border: "1px solid var(--line)",
      borderBottom: "1px solid var(--line)",
      borderRadius: 5,
      fontSize: 11,
      color: "var(--ink-1)",
      fontWeight: 500,
      boxShadow: "var(--keycap-shadow)",
    }}
  >
    {children}
  </kbd>
);

export const KeyCombo = ({ keys }: { keys: string[] }) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
    {keys.map((k, i) => (
      <React.Fragment key={i}>
        <Keycap>{k}</Keycap>
        {i < keys.length - 1 && <span style={{ color: "var(--ink-3)", fontSize: 11 }}>+</span>}
      </React.Fragment>
    ))}
  </span>
);

// ─── Waveform ────────────────────────────────────────────────────────────────
export const Waveform = ({
  active,
  bars = 28,
  height = 22,
  color = "var(--ink-2)",
  level,
  animated = true,
  style,
}: {
  active?: boolean;
  bars?: number;
  height?: number;
  color?: string;
  level?: number;
  animated?: boolean;
  style?: CSSProperties;
}) => {
  const seedHeights = useMemo(() => {
    return Array.from({ length: bars }, (_, i) => {
      const x = i / bars;
      const env = Math.sin(x * Math.PI) * 0.7 + 0.3;
      return 0.25 + 0.55 * Math.abs(Math.sin(i * 0.9 + 1.2)) * env + 0.15 * Math.abs(Math.cos(i * 1.7));
    });
  }, [bars]);

  const [, force] = useState(0);
  useEffect(() => {
    if (!active || !animated) return;
    const id = setInterval(() => force((t) => t + 1), 90);
    return () => clearInterval(id);
  }, [active, animated]);

  const t = Date.now() / 220;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2.5, height, ...style }}>
      {/*
        Use one timestamp per render. Static decorative waveforms opt out of the
        timer entirely, which keeps the WebEngine UI quiet while idle.
      */}
      {seedHeights.map((h0, i) => {
        const inputLevel = typeof level === "number" ? Math.max(0, Math.min(1, level)) : undefined;
        const live = inputLevel !== undefined
          ? Math.max(0.1, inputLevel * (animated ? 0.55 + 0.45 * Math.abs(Math.sin(t + i * 0.55)) : 1))
          : active && animated ? 0.35 + 0.65 * Math.abs(Math.sin(t + i * 0.55)) : active ? 0.34 : 0.18;
        const h = Math.max(0.12, h0 * live);
        return (
          <span
            key={i}
            style={{
              display: "block",
              width: 2.2,
              height: `${h * height}px`,
              background: color,
              borderRadius: 2,
              opacity: active ? 0.95 : 0.45,
              transition: "height 110ms cubic-bezier(.2,.7,.2,1), opacity 200ms",
            }}
          />
        );
      })}
    </div>
  );
};

export const SparkWave = ({
  seed = 1,
  bars = 22,
  height = 14,
  color = "var(--ink-3)",
}: {
  seed?: number;
  bars?: number;
  height?: number;
  color?: string;
}) => {
  const heights = useMemo(
    () =>
      Array.from({ length: bars }, (_, i) => {
        const x = i / bars;
        const env = Math.sin(x * Math.PI);
        return 0.18 + Math.abs(Math.sin(seed * 1.7 + i * 0.8)) * 0.7 * env + 0.1;
      }),
    [seed, bars]
  );
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 1.6, height }}>
      {heights.map((h, i) => (
        <span key={i} style={{ width: 1.6, height: `${Math.max(0.12, h) * height}px`, background: color, borderRadius: 1.5 }} />
      ))}
    </div>
  );
};

// ─── Row / Stat ──────────────────────────────────────────────────────────────
export const Row = ({
  title,
  subtitle,
  control,
  divider = true,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  control?: ReactNode;
  divider?: boolean;
}) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: 16,
      padding: "var(--row-pad-y) 0",
      borderBottom: divider ? "1px solid var(--line-soft)" : "none",
    }}
  >
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 13, color: "var(--ink)", fontWeight: 500, letterSpacing: "-0.005em" }}>{title}</div>
      {subtitle && <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 2, lineHeight: 1.4 }}>{subtitle}</div>}
    </div>
    <div style={{ flex: "0 0 auto" }}>{control}</div>
  </div>
);

export const Stat = ({ value, caption, suffix }: { value: ReactNode; caption: ReactNode; suffix?: ReactNode }) => (
  <div>
    <div style={{ fontSize: 28, fontWeight: 500, letterSpacing: "-0.025em", color: "var(--ink)", lineHeight: 1, fontFamily: '"Inter Tight", sans-serif', fontFeatureSettings: '"tnum"' }}>
      {value}
      {suffix && <span style={{ fontSize: 14, color: "var(--ink-3)", marginLeft: 3, fontWeight: 400 }}>{suffix}</span>}
    </div>
    <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 6, letterSpacing: "0.005em" }}>{caption}</div>
  </div>
);

// ─── MicDropdown ────────────────────────────────────────────────────────────
export type MicOption = { value: string; label: string; hint?: string };

const FALLBACK_MIC_OPTIONS: MicOption[] = [
  { value: "default", label: "System default microphone", hint: "Auto" },
];

export const MicDropdown = ({
  value,
  onChange,
  options = FALLBACK_MIC_OPTIONS,
}: {
  value: string;
  onChange: (v: string) => void;
  options?: MicOption[];
}) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  const current = useMemo(
    () => options.find((o) => o.value === value) || options[0] || FALLBACK_MIC_OPTIONS[0],
    [options, value]
  );
  const currentLabel = current?.label || "System default microphone";
  const shortLabel = currentLabel.length > 28 ? currentLabel.slice(0, 26) + "..." : currentLabel;
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 7,
          height: 28,
          padding: "0 10px 0 12px",
          background: open ? "var(--card)" : "var(--bg-sunken)",
          border: "1px solid var(--line-soft)",
          borderRadius: 999,
          fontFamily: "inherit",
          fontSize: 12,
          color: "var(--ink-1)",
          cursor: "pointer",
          letterSpacing: "-0.005em",
          transition: "background 120ms",
        }}
      >
        <span>{shortLabel}</span>
        <Icon name="chevdown" size={11} />
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: 34,
            right: 0,
            minWidth: 240,
            background: "var(--menu-bg)",
            border: "1px solid var(--line)",
            borderRadius: 12,
            boxShadow: "var(--shadow-menu)",
            padding: 6,
            zIndex: 50,
          }}
        >
          <div style={{ padding: "6px 10px 8px", fontSize: 10.5, fontWeight: 600, color: "var(--ink-3)", textTransform: "uppercase", letterSpacing: "0.12em" }}>
            Input device
          </div>
          {options.map((o) => {
            const active = o.value === value;
            return (
              <button
                key={o.value}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  width: "100%",
                  padding: "8px 10px",
                  background: active ? "var(--menu-active)" : "transparent",
                  border: "none",
                  borderRadius: 8,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  textAlign: "left",
                }}
                onMouseEnter={(e) => {
                  if (!active) e.currentTarget.style.background = "var(--menu-active)";
                }}
                onMouseLeave={(e) => {
                  if (!active) e.currentTarget.style.background = "transparent";
                }}
              >
                <span style={{ width: 14, display: "grid", placeItems: "center", color: active ? "var(--ink)" : "transparent" }}>
                  <Icon name="check" size={13} stroke={2} />
                </span>
                <span style={{ flex: 1, fontSize: 12.5, color: "var(--ink)", fontWeight: active ? 500 : 400, letterSpacing: "-0.005em" }}>{o.label}</span>
                {o.hint && <span style={{ fontSize: 10.5, color: "var(--ink-3)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 600 }}>{o.hint}</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
