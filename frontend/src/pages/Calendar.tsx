import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import type { PlanRangeDay, WorkoutSummary, GoogleStatus } from "../api/types";
import { Card, SectionTitle, MonoLabel } from "../components/Card";
import { SPORT_COLOR, SPORT_LABEL, fmtDuration } from "../lib/format";

// ── date helpers (local, no tz surprises) ─────────────────────────────────────
function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}
function addDays(d: Date, n: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}
function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}
function mondayOnOrBefore(d: Date): Date {
  const x = new Date(d);
  const dow = (x.getDay() + 6) % 7; // 0 = Monday
  return addDays(x, -dow);
}
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function Calendar() {
  const [cursor, setCursor] = useState(() => startOfMonth(new Date()));
  const [byDate, setByDate] = useState<Record<string, WorkoutSummary[]>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [gStatus, setGStatus] = useState<GoogleStatus | null>(null);
  const [gBusy, setGBusy] = useState(false);
  const [gMsg, setGMsg] = useState<string | null>(null);

  const monthStart = startOfMonth(cursor);
  const monthEnd = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
  const gridStart = mondayOnOrBefore(monthStart);
  const gridDays = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i)); // 6 weeks

  const loadMonth = useCallback(() => {
    setError(null);
    api.planRange(iso(gridStart), iso(gridDays[41]))
      .then((r) => {
        const map: Record<string, WorkoutSummary[]> = {};
        r.days.forEach((d: PlanRangeDay) => { map[d.date] = d.sessions; });
        setByDate(map);
      })
      .catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursor]);

  useEffect(() => { loadMonth(); }, [loadMonth]);
  useEffect(() => { api.googleStatus().then(setGStatus).catch(() => setGStatus(null)); }, []);

  const todayIso = iso(new Date());
  const monthLabel = cursor.toLocaleDateString(undefined, { month: "long", year: "numeric" });

  async function connectGoogle() {
    setGBusy(true); setGMsg("Opening Google sign-in… approve it in the browser window.");
    try {
      setGStatus(await api.googleConnect());
      setGMsg("Connected to Google Calendar.");
    } catch (e) {
      setGMsg(String(e));
    } finally { setGBusy(false); }
  }

  async function pushMonth() {
    setGBusy(true); setGMsg(null);
    try {
      const r = await api.googlePush(iso(monthStart), iso(monthEnd));
      setGMsg(`Pushed ${r.pushed} workout${r.pushed === 1 ? "" : "s"} to “${r.calendar}”`
        + (r.deleted ? ` (replaced ${r.deleted}).` : "."));
    } catch (e) {
      setGMsg(String(e));
    } finally { setGBusy(false); }
  }

  const selectedSessions = selected ? byDate[selected] ?? [] : [];

  return (
    <div className="p-5 md:p-8 max-w-[1200px] mx-auto flex flex-col gap-6">
      {/* header */}
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <MonoLabel>Training Calendar</MonoLabel>
          <h1 className="font-display font-extrabold text-3xl md:text-4xl tracking-tight mt-1">
            {monthLabel}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <NavBtn onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>‹</NavBtn>
          <button
            onClick={() => setCursor(startOfMonth(new Date()))}
            className="rounded-btn border border-outline-variant/50 text-on-surface-variant hover:text-primary hover:border-primary font-mono text-xs px-3 py-1.5"
          >
            Today
          </button>
          <NavBtn onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>›</NavBtn>
        </div>
      </header>

      {error && <div className="text-error font-mono text-sm">Failed to load: {error}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* month grid */}
        <div className="lg:col-span-3">
          <Card className="p-3">
            <div className="grid grid-cols-7 gap-1 mb-1">
              {WEEKDAYS.map((w) => (
                <div key={w} className="text-center font-mono text-[11px] uppercase tracking-wider text-on-surface-variant py-1">
                  {w}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-1">
              {gridDays.map((d) => {
                const key = iso(d);
                const inMonth = d.getMonth() === cursor.getMonth();
                const sessions = byDate[key] ?? [];
                const isToday = key === todayIso;
                const isSel = key === selected;
                return (
                  <button
                    key={key}
                    onClick={() => setSelected(key)}
                    className={`min-h-[84px] rounded-btn border p-1.5 text-left flex flex-col gap-1 transition-colors ${
                      isSel ? "border-primary" : "border-outline-variant/30 hover:border-outline-variant/60"
                    } ${inMonth ? "bg-surface-container" : "bg-surface-container-lowest/40"}`}
                  >
                    <span className={`font-mono text-xs ${
                      isToday ? "text-on-primary bg-primary rounded-full w-5 h-5 flex items-center justify-center"
                        : inMonth ? "text-on-surface" : "text-outline"
                    }`}>
                      {d.getDate()}
                    </span>
                    <div className="flex flex-col gap-0.5 overflow-hidden">
                      {sessions.slice(0, 3).map((s, i) => (
                        <span
                          key={i}
                          className="truncate rounded-[3px] px-1 py-0.5 text-[10px] font-mono leading-tight"
                          style={{ backgroundColor: SPORT_COLOR[s.sport] + "26", color: SPORT_COLOR[s.sport] }}
                          title={`${s.title} · ${fmtDuration(s.duration_min)}`}
                        >
                          {s.title}
                        </span>
                      ))}
                      {sessions.length > 3 && (
                        <span className="text-[10px] font-mono text-outline">+{sessions.length - 3} more</span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </Card>
        </div>

        {/* sidebar: selected day + Google */}
        <div className="flex flex-col gap-6">
          <Card className="flex flex-col gap-3">
            <SectionTitle>{selected ? new Date(selected + "T00:00:00").toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" }) : "Select a day"}</SectionTitle>
            {selected && selectedSessions.length === 0 && (
              <p className="text-on-surface-variant text-sm">No sessions planned.</p>
            )}
            {selectedSessions.map((s, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className="h-8 w-1.5 rounded-full shrink-0" style={{ backgroundColor: SPORT_COLOR[s.sport] }} />
                <div className="min-w-0 flex-1">
                  <div className="font-medium truncate">{s.title}</div>
                  <div className="font-mono text-xs text-on-surface-variant">
                    {SPORT_LABEL[s.sport]} · {fmtDuration(s.duration_min)}
                  </div>
                </div>
                <span className="font-mono text-sm">{s.planned_tss}</span>
              </div>
            ))}
          </Card>

          <GooglePanel
            status={gStatus}
            busy={gBusy}
            msg={gMsg}
            monthLabel={cursor.toLocaleDateString(undefined, { month: "long" })}
            onConnect={connectGoogle}
            onPush={pushMonth}
            onDisconnect={async () => { setGStatus(await api.googleDisconnect()); setGMsg(null); }}
          />
        </div>
      </div>
    </div>
  );
}

function NavBtn({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="rounded-btn border border-outline-variant/50 text-on-surface-variant hover:text-primary hover:border-primary font-mono text-lg w-8 h-8"
    >
      {children}
    </button>
  );
}

function GooglePanel({
  status, busy, msg, monthLabel, onConnect, onPush, onDisconnect,
}: {
  status: GoogleStatus | null;
  busy: boolean;
  msg: string | null;
  monthLabel: string;
  onConnect: () => void;
  onPush: () => void;
  onDisconnect: () => void;
}) {
  const dot = !status?.configured ? "#859490" : status.connected ? "#4ae176" : "#ffd34f";
  const label = !status?.configured ? "Not set up"
    : status.connected ? "Connected" : "Not connected";

  return (
    <Card className="flex flex-col gap-3">
      <SectionTitle>Google Calendar</SectionTitle>
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: dot, boxShadow: `0 0 8px ${dot}` }} />
        <span className="font-mono text-sm text-on-surface-variant">{label}</span>
      </div>

      {!status?.configured && (
        <p className="text-on-surface-variant text-sm">
          Add your OAuth client secret to <code>backend/.secrets/google_client_secret.json</code> to
          enable pushing workouts to Google Calendar.
        </p>
      )}

      {status?.configured && !status.connected && (
        <button
          onClick={onConnect}
          disabled={busy}
          className="rounded-btn bg-primary text-on-primary font-mono text-sm font-medium px-4 py-2 hover:brightness-110 disabled:opacity-50"
        >
          {busy ? "Connecting…" : "Connect Google Calendar"}
        </button>
      )}

      {status?.connected && (
        <div className="flex flex-col gap-2">
          <button
            onClick={onPush}
            disabled={busy}
            className="rounded-btn bg-primary text-on-primary font-mono text-sm font-medium px-4 py-2 hover:brightness-110 disabled:opacity-50"
          >
            {busy ? "Pushing…" : `Push ${monthLabel} to Google`}
          </button>
          <button
            onClick={onDisconnect}
            disabled={busy}
            className="font-mono text-xs text-outline hover:text-error self-start"
          >
            Disconnect
          </button>
          <p className="font-mono text-[11px] text-outline">
            Writes to a dedicated “TriFlow Training” calendar; re-pushing replaces that month's entries.
          </p>
        </div>
      )}

      {msg && <p className="font-mono text-xs text-on-surface-variant">{msg}</p>}
    </Card>
  );
}
