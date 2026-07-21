import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { GarminMaxMetrics } from "../api/types";
import { MonoLabel } from "./Card";
import { secToMmss } from "../lib/format";

/**
 * "Sync from Garmin" button + review-before-applying panel for FTP/LTHR/pace —
 * shared by Settings and onboarding. Never writes anything itself: `onApply`
 * just pre-fills the caller's own form field, same as clicking it by hand.
 */
export function GarminSync({ currentFtp, currentLthr, currentRunPace, onApply }: {
  currentFtp: number;
  currentLthr: number;
  currentRunPace: string; // mm:ss /km, for display only
  onApply: (patch: { ftp?: number; lthr?: number; runPace?: string }) => void;
}) {
  const [garmin, setGarmin] = useState<GarminMaxMetrics | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [err, setErr] = useState("");

  async function sync() {
    setState("loading"); setErr("");
    try {
      setGarmin(await api.garminMaxMetrics());
      setState("idle");
    } catch (e) {
      setState("error"); setErr(String(e));
    }
  }

  return (
    <div>
      <button
        onClick={sync}
        disabled={state === "loading"}
        className="flex items-center gap-1.5 rounded border border-outline-variant/50 text-xs font-medium px-2.5 py-1.5 hover:bg-surface-container-high disabled:opacity-60"
      >
        <RefreshCw size={13} className={state === "loading" ? "animate-spin" : ""} />
        {state === "loading" ? "Syncing…" : "Sync from Garmin"}
      </button>
      {state === "error" && <p className="text-error font-mono text-xs mt-2">{err}</p>}

      {garmin && (
        <div className="mt-4">
          <MonoLabel>Garmin sync — review before applying</MonoLabel>
          <div className="flex flex-col gap-2 mt-3">
            <GarminField
              label="Bike FTP"
              current={`${currentFtp} W`}
              garminValue={garmin.ftp_watts}
              plausible={garmin.ftp_plausible}
              format={(v) => `${v} W`}
              extra={garmin.ftp_source ? ` (${garmin.ftp_source.toLowerCase()}${garmin.ftp_date ? `, ${garmin.ftp_date}` : ""})` : ""}
              onUse={() => onApply({ ftp: garmin.ftp_watts! })}
            />
            <GarminField
              label="Run LTHR"
              current={`${currentLthr} bpm`}
              garminValue={garmin.run_lthr}
              plausible={garmin.run_lthr_plausible}
              format={(v) => `${v} bpm`}
              extra={garmin.run_lthr_auto_detected ? " (auto-detected)" : ""}
              onUse={() => onApply({ lthr: garmin.run_lthr! })}
            />
            <GarminField
              label="Run threshold pace"
              current={`${currentRunPace} /km`}
              garminValue={garmin.run_threshold_pace_sec_per_km}
              plausible={garmin.run_pace_plausible}
              format={(v) => `${secToMmss(v)} /km`}
              onUse={() => onApply({ runPace: secToMmss(garmin.run_threshold_pace_sec_per_km!) })}
            />
            {garmin.vo2max_running != null && (
              <p className="text-xs text-on-surface-variant font-mono mt-1">
                VO2max running (informational): {garmin.vo2max_running}
              </p>
            )}
          </div>
          <p className="text-[11px] text-on-surface-variant mt-3">
            “Use” pre-fills the field below — nothing is saved until you submit. Swim CSS and Max HR aren’t
            available from Garmin and stay manual.
          </p>
        </div>
      )}
    </div>
  );
}

function GarminField({ label, current, garminValue, plausible, format, onUse, extra }: {
  label: string;
  current: string;
  garminValue: number | null;
  plausible: boolean;
  format: (v: number) => string;
  onUse: () => void;
  extra?: string;
}) {
  const has = garminValue != null;
  const bad = has && !plausible;
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-on-surface-variant w-36 shrink-0">{label}</span>
      <span className="font-mono text-xs w-24 shrink-0">{current}</span>
      <span className="text-on-surface-variant">→</span>
      <span className={`font-mono text-xs flex-1 ${bad ? "text-error" : "text-on-surface-variant"}`}>
        {has ? `${format(garminValue)}${extra ?? ""}${bad ? " — looks implausible, skipped" : ""}` : "not available from Garmin"}
      </span>
      {has && !bad && (
        <button onClick={onUse} className="text-xs font-medium text-primary hover:underline shrink-0">Use</button>
      )}
    </div>
  );
}
