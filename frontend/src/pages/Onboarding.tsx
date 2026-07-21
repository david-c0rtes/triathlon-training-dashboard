import { useEffect, useState, Fragment } from "react";
import { api } from "../api/client";
import type { AthleteProfile, RaceTypeOption } from "../api/types";
import { Field, TextInput, NumInput, inputCls } from "../components/FormControls";
import { GarminSync } from "../components/GarminSync";
import { mmssToSec, hhmmToSec } from "../lib/format";

interface LegForm {
  discipline: string;
  km: string;
}

interface ProfileForm {
  name: string;
  raceDate: string;
  raceType: string;
  customLegs: LegForm[];
  goal: string;
  targetFinish: string;
  weeklyHours: number;
  ftp: number;
  runPace: string;
  lthr: number;
  swimCss: string;
  maxHr: number;
}

function blankForm(): ProfileForm {
  const raceDate = new Date();
  raceDate.setDate(raceDate.getDate() + 12 * 7); // a plausible default: 12 weeks out
  return {
    name: "",
    raceDate: raceDate.toISOString().slice(0, 10),
    raceType: "middle_tri",
    customLegs: [{ discipline: "swim", km: "" }, { discipline: "bike", km: "" }, { discipline: "run", km: "" }],
    goal: "finish",
    targetFinish: "",
    weeklyHours: 8,
    ftp: 200,
    runPace: "5:00",
    lthr: 160,
    swimCss: "1:40",
    maxHr: 185,
  };
}

export function Onboarding({ onComplete }: { onComplete: (p: AthleteProfile) => void }) {
  const [step, setStep] = useState<"welcome" | "profile">("welcome");
  const [profile, setProfile] = useState<AthleteProfile | null>(null);
  const [raceTypes, setRaceTypes] = useState<RaceTypeOption[]>([]);
  const [form, setForm] = useState<ProfileForm>(blankForm());
  const [status, setStatus] = useState<"idle" | "saving" | "error">("idle");
  const [errMsg, setErrMsg] = useState("");

  useEffect(() => {
    api.profile().then(setProfile).catch(() => {});
    api.raceTypes().then(setRaceTypes).catch(() => {});
  }, []);

  const set = <K extends keyof ProfileForm>(k: K, v: ProfileForm[K]) => setForm({ ...form, [k]: v });

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
  const legOptions = (i: number): string[] => {
    const all = ["swim", "bike", "run"];
    return i === 0 ? all : all.filter((d) => d !== form.customLegs[i - 1].discipline);
  };

  const paceOk = mmssToSec(form.runPace) !== null && mmssToSec(form.swimCss) !== null;

  async function finalize() {
    if (!profile) return;
    if (!form.name.trim()) { setStatus("error"); setErrMsg("Enter your name."); return; }
    if (!paceOk) { setStatus("error"); setErrMsg("Pace must be mm:ss (e.g. 4:45)."); return; }

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
        limiter_discipline: null,
      },
      thresholds: {
        ftp_watts: form.ftp,
        run_threshold_pace_sec_per_km: mmssToSec(form.runPace)!,
        run_lthr: form.lthr || null,
        swim_css_sec_per_100m: mmssToSec(form.swimCss)!,
        max_hr: form.maxHr || null,
      },
      fitness: profile.fitness,
      onboarding_complete: true,
      // Sport split / strength frequency aren't collected here — sensible
      // defaults now, refinable any time in Settings.
      preferences: {
        sport_distribution: { swim: 0.15, bike: 0.40, run: 0.30, strength: 0.15 },
        strength_sessions_per_week: 2,
        measured_tss_per_hour: profile.preferences.measured_tss_per_hour,
      },
    };
    try {
      const saved = await api.saveProfile(payload);
      onComplete(saved);
    } catch (e) {
      setStatus("error"); setErrMsg(String(e));
    }
  }

  if (step === "welcome") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface p-6">
        <div className="max-w-md text-center flex flex-col items-center gap-6">
          <img src="/triathlon_logo.png" alt="TriFlow" className="h-16 w-16 object-contain" />
          <div>
            <h1 className="font-display font-extrabold text-4xl tracking-tight text-on-surface">
              Welcome to <span className="text-primary">TriFlow</span>
            </h1>
            <p className="text-on-surface-variant mt-3">Train smarter. Race faster.</p>
          </div>
          <p className="text-on-surface-variant text-sm">
            Let's set up your athlete profile — your race, your training hours, and your current
            benchmarks — so TriFlow can build your personalized plan.
          </p>
          <button
            onClick={() => setStep("profile")}
            className="rounded bg-primary text-on-primary font-medium px-6 py-3 hover:brightness-110"
          >
            Get Started
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface overflow-y-auto">
      <div className="max-w-2xl mx-auto p-6 md:p-10 flex flex-col gap-8">
        <div>
          <span className="font-mono text-xs uppercase tracking-wider text-on-surface-variant">Step 2 of 2</span>
          <h1 className="font-display font-extrabold text-3xl tracking-tight text-on-surface mt-1">
            Create your athlete profile
          </h1>
          <p className="text-on-surface-variant text-sm mt-2">
            This drives every plan TriFlow builds for you — you can always refine it later in Settings.
          </p>
        </div>

        {status === "error" && <p className="text-error font-mono text-sm">{errMsg}</p>}

        <section className="flex flex-col gap-4">
          <h2 className="font-display font-semibold text-lg text-on-surface">About you</h2>
          <Field label="Your name"><TextInput value={form.name} onChange={(v) => set("name", v)} /></Field>
        </section>

        <section className="flex flex-col gap-4 pt-4 border-t border-outline-variant/30">
          <h2 className="font-display font-semibold text-lg text-on-surface">Your race</h2>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Race date">
              <input type="date" className={inputCls} value={form.raceDate} onChange={(e) => set("raceDate", e.target.value)} />
            </Field>
            <Field label="Event type">
              <select className={inputCls} value={form.raceType} onChange={(e) => set("raceType", e.target.value)}>
                {raceTypes.map((rt) => <option key={rt.key} value={rt.key}>{rt.label}</option>)}
                <option value="custom">Custom distance…</option>
              </select>
            </Field>
            <Field label="Race goal">
              <select className={inputCls} value={form.goal} onChange={(e) => set("goal", e.target.value)}>
                <option value="finish">Finish</option>
                <option value="target_time">Target time</option>
                <option value="compete">Compete</option>
              </select>
            </Field>
            {form.goal === "target_time" && (
              <Field label="Target finish (h:mm)">
                <TextInput value={form.targetFinish} onChange={(v) => set("targetFinish", v)} placeholder="4:45" />
              </Field>
            )}
            <Field label="Weekly training hours">
              <NumInput value={form.weeklyHours} onChange={(v) => set("weeklyHours", v)} step={0.5} />
            </Field>
          </div>

          {form.raceType === "custom" && (
            <div className="pt-2">
              <p className="text-on-surface-variant text-xs mb-3">
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
                      {legOptions(i).map((d) => <option key={d} value={d}>{d[0].toUpperCase() + d.slice(1)}</option>)}
                    </select>
                    <input
                      type="number" step={0.1} min={0} className={inputCls}
                      value={leg.km} placeholder="km" disabled={!leg.discipline}
                      onChange={(e) => setLegKm(i, e.target.value)}
                    />
                  </Fragment>
                ))}
              </div>
            </div>
          )}
        </section>

        <section className="flex flex-col gap-4 pt-4 border-t border-outline-variant/30">
          <div className="flex items-center justify-between">
            <h2 className="font-display font-semibold text-lg text-on-surface">Your benchmarks</h2>
            <GarminSync
              currentFtp={form.ftp}
              currentLthr={form.lthr}
              currentRunPace={form.runPace}
              onApply={(patch) => setForm({
                ...form,
                ...(patch.ftp != null ? { ftp: patch.ftp } : {}),
                ...(patch.lthr != null ? { lthr: patch.lthr } : {}),
                ...(patch.runPace != null ? { runPace: patch.runPace } : {}),
              })}
            />
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Bike FTP (watts)"><NumInput value={form.ftp} onChange={(v) => set("ftp", v)} /></Field>
            <Field label="Max HR (bpm)"><NumInput value={form.maxHr} onChange={(v) => set("maxHr", v)} /></Field>
            <Field label="Run threshold pace (mm:ss /km)"><TextInput value={form.runPace} onChange={(v) => set("runPace", v)} placeholder="4:45" /></Field>
            <Field label="Run LTHR (bpm)"><NumInput value={form.lthr} onChange={(v) => set("lthr", v)} /></Field>
            <Field label="Swim CSS (mm:ss /100m)"><TextInput value={form.swimCss} onChange={(v) => set("swimCss", v)} placeholder="1:35" /></Field>
          </div>
        </section>

        <div className="pt-2 pb-10 flex justify-end">
          <button
            onClick={finalize}
            disabled={status === "saving"}
            className="rounded bg-primary text-on-primary font-medium px-6 py-3 hover:brightness-110 disabled:opacity-60"
          >
            {status === "saving" ? "Finalizing…" : "Finalize Profile"}
          </button>
        </div>
      </div>
    </div>
  );
}
