import { useEffect, useState, Fragment } from "react";
import type { ReactNode } from "react";
import { Save } from "lucide-react";
import { api } from "../api/client";
import type { AthleteProfile, ZonesResponse, ZoneOut, RaceTypeOption } from "../api/types";
import { Card, SectionTitle, MonoLabel } from "../components/Card";
import { secToMmss, mmssToSec, secToHhmm, hhmmToSec } from "../lib/format";

interface LegForm {
  discipline: string; // "swim" | "bike" | "run" | "" (none, leg 3 only)
  km: string;
}

interface FormState {
  name: string;
  raceDate: string;
  raceType: string;
  customLegs: LegForm[]; // always length 3
  goal: string;
  targetFinish: string; // h:mm
  weeklyHours: number;
  limiter: string;
  ftp: number;
  runPace: string;      // mm:ss /km
  lthr: number;
  swimCss: string;      // mm:ss /100m
  maxHr: number;
  dist: { swim: number; bike: number; run: number; strength: number }; // percentages
  strengthSessions: number;
}

export function Settings() {
  const [profile, setProfile] = useState<AthleteProfile | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [zones, setZones] = useState<ZonesResponse | null>(null);
  const [raceTypes, setRaceTypes] = useState<RaceTypeOption[]>([]);
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [errMsg, setErrMsg] = useState("");

  useEffect(() => {
    api.profile().then((p) => { setProfile(p); setForm(toForm(p)); }).catch((e) => setErrMsg(String(e)));
    api.zones().then(setZones).catch(() => {});
    api.raceTypes().then(setRaceTypes).catch(() => {});
  }, []);

  if (errMsg && !form) return <div className="p-8 text-error font-mono text-sm">Failed to load: {errMsg}</div>;
  if (!form || !profile) return <div className="p-8 text-on-surface-variant">Loading…</div>;

  const distTotal = form.dist.swim + form.dist.bike + form.dist.run + form.dist.strength;
  const distOk = distTotal === 100;
  const paceOk = mmssToSec(form.runPace) !== null && mmssToSec(form.swimCss) !== null;

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm({ ...form, [k]: v });
  const setDist = (k: keyof FormState["dist"], v: number) =>
    setForm({ ...form, dist: { ...form.dist, [k]: v } });

  // Update a custom leg's discipline; clear the next leg if it would now repeat.
  const setLegDiscipline = (i: number, v: string) => {
    const legs = form.customLegs.map((l) => ({ ...l }));
    legs[i].discipline = v;
    if (i < 2 && legs[i + 1].discipline === v) legs[i + 1].discipline = "";
    setForm({ ...form, customLegs: legs });
  };
  const setLegKm = (i: number, v: string) => {
    const legs = form.customLegs.map((l) => ({ ...l }));
    legs[i].km = v;
    setForm({ ...form, customLegs: legs });
  };
  // Disciplines available for a row: exclude the previous leg's discipline.
  const legOptions = (i: number): string[] => {
    const all = ["swim", "bike", "run"];
    return i === 0 ? all : all.filter((d) => d !== form.customLegs[i - 1].discipline);
  };

  async function save() {
    if (!form || !profile) return;
    if (!distOk) { setStatus("error"); setErrMsg("Sport distribution must total 100%."); return; }
    if (!paceOk) { setStatus("error"); setErrMsg("Pace must be mm:ss (e.g. 4:45)."); return; }

    // Build / validate custom legs
    let customLegs: { discipline: string; distance_m: number }[] | null = null;
    if (form.raceType === "custom") {
      if (!form.customLegs[0].discipline || !form.customLegs[1].discipline) {
        setStatus("error"); setErrMsg("A custom race needs at least 2 legs (the first two boxes)."); return;
      }
      const chosen = form.customLegs.filter((l, i) => i < 2 || !!l.discipline);
      for (const l of chosen) {
        const km = parseFloat(l.km);
        if (!km || km <= 0) { setStatus("error"); setErrMsg("Each chosen leg needs a distance in km."); return; }
      }
      for (let i = 0; i < chosen.length - 1; i++) {
        if (chosen[i].discipline === chosen[i + 1].discipline) {
          setStatus("error"); setErrMsg("A discipline cannot repeat in consecutive legs."); return;
        }
      }
      customLegs = chosen.map((l) => ({ discipline: l.discipline, distance_m: Math.round(parseFloat(l.km) * 1000) }));
    }

    setStatus("saving"); setErrMsg("");
    const payload: AthleteProfile = {
      name: form.name,
      goals: {
        race_date: form.raceDate,
        race_type: form.raceType,
        custom_legs: customLegs,
        goal: form.goal,
        target_finish_seconds: form.goal === "target_time" ? hhmmToSec(form.targetFinish) : null,
        weekly_hours_available: form.weeklyHours,
        limiter_discipline: form.limiter || null,
      },
      thresholds: {
        ftp_watts: form.ftp,
        run_threshold_pace_sec_per_km: mmssToSec(form.runPace)!,
        run_lthr: form.lthr || null,
        swim_css_sec_per_100m: mmssToSec(form.swimCss)!,
        max_hr: form.maxHr || null,
      },
      fitness: profile.fitness,
      preferences: {
        sport_distribution: {
          swim: form.dist.swim / 100, bike: form.dist.bike / 100,
          run: form.dist.run / 100, strength: form.dist.strength / 100,
        },
        strength_sessions_per_week: form.strengthSessions,
        measured_tss_per_hour: profile.preferences.measured_tss_per_hour,
      },
    };
    try {
      const saved = await api.saveProfile(payload);
      setProfile(saved);
      setZones(await api.zones());
      setStatus("saved");
      setTimeout(() => setStatus("idle"), 2500);
    } catch (e) {
      setStatus("error"); setErrMsg(String(e));
    }
  }

  return (
    <div className="p-5 md:p-8 max-w-[900px] mx-auto flex flex-col gap-6">
      <header className="flex items-center justify-between">
        <div>
          <MonoLabel>Athlete profile</MonoLabel>
          <h1 className="font-display font-extrabold text-3xl md:text-4xl tracking-tight mt-1">Settings</h1>
        </div>
        <button
          onClick={save}
          disabled={status === "saving"}
          className="flex items-center gap-2 rounded bg-primary text-on-primary font-medium px-4 py-2 hover:brightness-110 disabled:opacity-60"
        >
          <Save size={16} />
          {status === "saving" ? "Saving…" : status === "saved" ? "Saved ✓" : "Save"}
        </button>
      </header>
      {status === "error" && <p className="text-error font-mono text-sm">{errMsg}</p>}

      {/* Goals & race */}
      <Card>
        <SectionTitle>Goals &amp; Race</SectionTitle>
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Athlete name"><TextInput value={form.name} onChange={(v) => set("name", v)} /></Field>
          <Field label="Race date"><input type="date" className={inputCls} value={form.raceDate} onChange={(e) => set("raceDate", e.target.value)} /></Field>
          <Field label="Race type">
            <select className={inputCls} value={form.raceType} onChange={(e) => set("raceType", e.target.value)}>
              {raceTypes.map((rt) => <option key={rt.key} value={rt.key}>{rt.label}</option>)}
              <option value="custom">Custom distance…</option>
            </select>
            {raceTypes.find((rt) => rt.key === form.raceType) && (
              <span className="font-mono text-[11px] text-on-surface-variant mt-1">
                {raceTypes.find((rt) => rt.key === form.raceType)!.description}
              </span>
            )}
          </Field>
          <Field label="Goal">
            <select className={inputCls} value={form.goal} onChange={(e) => set("goal", e.target.value)}>
              <option value="finish">Finish</option>
              <option value="target_time">Target time</option>
              <option value="compete">Compete</option>
            </select>
          </Field>
          {form.goal === "target_time" && (
            <Field label="Target finish (h:mm)"><TextInput value={form.targetFinish} onChange={(v) => set("targetFinish", v)} placeholder="4:45" /></Field>
          )}
          <Field label="Weekly training hours"><NumInput value={form.weeklyHours} onChange={(v) => set("weeklyHours", v)} step={0.5} /></Field>
          <Field label="Limiter discipline">
            <select className={inputCls} value={form.limiter} onChange={(e) => set("limiter", e.target.value)}>
              <option value="">None</option>
              <option value="swim">Swim</option>
              <option value="bike">Bike</option>
              <option value="run">Run</option>
            </select>
          </Field>
        </div>

        {form.raceType === "custom" && (
          <div className="mt-5 pt-4 border-t border-outline-variant/30">
            <MonoLabel>Custom distance — legs in order</MonoLabel>
            <p className="text-on-surface-variant text-xs mt-1 mb-3">
              Fill at least the first 2 legs. Leg 3 is optional (leave it “None” for an aquathlon / aquabike).
              A discipline can’t repeat in consecutive legs.
            </p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 max-w-md">
              <span className="font-mono text-[11px] text-on-surface-variant">Discipline</span>
              <span className="font-mono text-[11px] text-on-surface-variant">Distance (km)</span>
              {form.customLegs.map((leg, i) => (
                <Fragment key={i}>
                  <select className={inputCls} value={leg.discipline} onChange={(e) => setLegDiscipline(i, e.target.value)}>
                    {i === 2 && <option value="">— None —</option>}
                    {legOptions(i).map((d) => (
                      <option key={d} value={d}>{d[0].toUpperCase() + d.slice(1)}</option>
                    ))}
                  </select>
                  <input
                    type="number" step={0.1} min={0} className={inputCls}
                    value={leg.km} placeholder="km"
                    disabled={!leg.discipline}
                    onChange={(e) => setLegKm(i, e.target.value)}
                  />
                </Fragment>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* Thresholds & zones */}
      <Card>
        <SectionTitle>Thresholds</SectionTitle>
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Bike FTP (watts)"><NumInput value={form.ftp} onChange={(v) => set("ftp", v)} /></Field>
          <Field label="Max HR (bpm)"><NumInput value={form.maxHr} onChange={(v) => set("maxHr", v)} /></Field>
          <Field label="Run threshold pace (mm:ss /km)"><TextInput value={form.runPace} onChange={(v) => set("runPace", v)} placeholder="4:45" /></Field>
          <Field label="Run LTHR (bpm)"><NumInput value={form.lthr} onChange={(v) => set("lthr", v)} /></Field>
          <Field label="Swim CSS (mm:ss /100m)"><TextInput value={form.swimCss} onChange={(v) => set("swimCss", v)} placeholder="1:35" /></Field>
        </div>

        {zones && (
          <div className="mt-5 pt-4 border-t border-outline-variant/30">
            <MonoLabel>Derived zones (read-only)</MonoLabel>
            <div className="grid md:grid-cols-2 gap-x-8 gap-y-4 mt-3">
              <ZoneTable title="Bike Power" zones={zones.bike_power} unit="W" fmt={(v) => `${Math.round(v)}`} />
              <ZoneTable title="Bike HR" zones={zones.bike_hr} unit="bpm" fmt={(v) => `${Math.round(v)}`} />
              <ZoneTable title="Run HR" zones={zones.run_hr} unit="bpm" fmt={(v) => `${Math.round(v)}`} />
              <ZoneTable title="Run Pace" zones={zones.run_pace} unit="/km" fmt={secToMmss} pace />
              <ZoneTable title="Swim Pace" zones={zones.swim_pace} unit="/100m" fmt={secToMmss} pace />
            </div>
          </div>
        )}
      </Card>

      {/* Sport distribution & strength */}
      <Card>
        <SectionTitle>Sport Distribution &amp; Strength</SectionTitle>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {(["swim", "bike", "run", "strength"] as const).map((s) => (
            <Field key={s} label={`${s[0].toUpperCase()}${s.slice(1)} %`}>
              <NumInput value={form.dist[s]} onChange={(v) => setDist(s, v)} />
            </Field>
          ))}
        </div>
        <div className="flex items-center justify-between mt-3">
          <span className={`font-mono text-sm ${distOk ? "text-secondary" : "text-error"}`}>
            Total: {distTotal}% {distOk ? "✓" : "(must equal 100%)"}
          </span>
        </div>
        <div className="mt-4 max-w-xs">
          <Field label="Strength sessions / week"><NumInput value={form.strengthSessions} onChange={(v) => set("strengthSessions", v)} /></Field>
        </div>
      </Card>
    </div>
  );
}

// ── helpers ───────────────────────────────────────────────────────────────────

function toForm(p: AthleteProfile): FormState {
  const d = p.preferences.sport_distribution;
  const presetLegs = ["swim", "bike", "run"];
  const cl = p.goals.custom_legs ?? [];
  const hasCustom = cl.length > 0;
  const customLegs: LegForm[] = [0, 1, 2].map((i) =>
    cl[i]
      ? { discipline: cl[i].discipline, km: String(cl[i].distance_m / 1000) }
      : { discipline: hasCustom ? "" : presetLegs[i], km: "" }
  );
  return {
    name: p.name,
    raceDate: p.goals.race_date,
    raceType: p.goals.race_type,
    customLegs,
    goal: p.goals.goal,
    targetFinish: secToHhmm(p.goals.target_finish_seconds),
    weeklyHours: p.goals.weekly_hours_available,
    limiter: p.goals.limiter_discipline ?? "",
    ftp: p.thresholds.ftp_watts,
    runPace: secToMmss(p.thresholds.run_threshold_pace_sec_per_km),
    lthr: p.thresholds.run_lthr ?? 0,
    swimCss: secToMmss(p.thresholds.swim_css_sec_per_100m),
    maxHr: p.thresholds.max_hr ?? 0,
    dist: {
      swim: Math.round((d.swim ?? 0) * 100),
      bike: Math.round((d.bike ?? 0) * 100),
      run: Math.round((d.run ?? 0) * 100),
      strength: Math.round((d.strength ?? 0) * 100),
    },
    strengthSessions: p.preferences.strength_sessions_per_week,
  };
}

const inputCls =
  "w-full bg-surface-container-high border border-outline-variant/50 rounded px-3 py-2 text-on-surface " +
  "focus:outline-none focus:border-primary text-sm";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-on-surface-variant">{label}</span>
      {children}
    </label>
  );
}

function TextInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return <input type="text" className={inputCls} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />;
}

function NumInput({ value, onChange, step }: { value: number; onChange: (v: number) => void; step?: number }) {
  return <input type="number" step={step ?? 1} className={inputCls} value={Number.isNaN(value) ? "" : value} onChange={(e) => onChange(parseFloat(e.target.value))} />;
}

function ZoneTable({ title, zones, unit, fmt, pace }: {
  title: string; zones: ZoneOut[]; unit: string; fmt: (v: number) => string; pace?: boolean;
}) {
  return (
    <div>
      <div className="font-mono text-xs text-on-surface-variant mb-1">{title}</div>
      <div className="flex flex-col gap-0.5">
        {zones.map((z) => {
          const lo = fmt(z.low);
          const hi = z.high == null ? null : fmt(z.high);
          // for pace, smaller seconds = faster, so sort the displayed pair ascending
          let range: string;
          if (hi == null) range = pace ? `≥ ${lo}` : `${lo}+`;
          else range = pace ? `${fmt(Math.min(z.low, z.high!))}–${fmt(Math.max(z.low, z.high!))}` : `${lo}–${hi}`;
          return (
            <div key={z.number} className="flex justify-between text-sm">
              <span className="text-on-surface-variant">{z.name}</span>
              <span className="font-mono">{range} {unit}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
