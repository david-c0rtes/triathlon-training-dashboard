import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Field, inputCls } from "./FormControls";

/** Link/unlink panel for a Garmin account — shared by Settings and onboarding. */
export function GarminConnect({ onStatusChange }: { onStatusChange?: (connected: boolean) => void }) {
  const [conn, setConn] = useState<boolean | null>(null);
  const [link, setLink] = useState({ email: "", password: "", mfaCode: "" });
  const [needMfa, setNeedMfa] = useState(false);
  const [state, setState] = useState<"idle" | "working" | "error">("idle");
  const [err, setErr] = useState("");

  useEffect(() => {
    api.garminStatus()
      .then((s) => { setConn(s.connected); onStatusChange?.(s.connected); })
      .catch(() => { setConn(false); onStatusChange?.(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function linkGarmin() {
    setState("working"); setErr("");
    try {
      await api.garminLink(link.email, link.password, needMfa ? link.mfaCode : undefined);
      setConn(true);
      onStatusChange?.(true);
      setLink({ email: "", password: "", mfaCode: "" });
      setNeedMfa(false);
      setState("idle");
    } catch (e) {
      const msg = String(e instanceof Error ? e.message : e);
      if (msg.includes("mfa_required")) {
        setNeedMfa(true);
        setState("idle");
        setErr("Garmin sent you a one-time code — enter it below and link again.");
      } else {
        setState("error");
        setErr(msg);
      }
    }
  }

  async function unlinkGarmin() {
    if (!window.confirm("Unlink Garmin? Workouts already on your watch stay there; sync and publish stop working until you link again.")) return;
    try {
      await api.garminUnlink();
      setConn(false);
      onStatusChange?.(false);
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span
          className="h-2.5 w-2.5 rounded-full"
          style={{
            backgroundColor: conn === null ? "#ffd34f" : conn ? "#4ae176" : "#ffb4ab",
            boxShadow: `0 0 8px ${conn === null ? "#ffd34f" : conn ? "#4ae176" : "#ffb4ab"}`,
          }}
        />
        <span className="font-mono text-sm text-on-surface-variant">
          Garmin {conn === null ? "— checking…" : conn ? "linked" : "not linked"}
        </span>
        {conn && (
          <button
            onClick={unlinkGarmin}
            className="ml-auto rounded border border-outline-variant/50 text-xs font-medium px-2.5 py-1.5 hover:border-error hover:text-error"
          >
            Unlink
          </button>
        )}
      </div>

      {conn === false && (
        <div className="flex flex-col gap-3 max-w-md">
          <Field label="Garmin email">
            <input type="email" autoComplete="off" className={inputCls} value={link.email}
              onChange={(e) => setLink({ ...link, email: e.target.value })} />
          </Field>
          <Field label="Garmin password">
            <input type="password" autoComplete="off" className={inputCls} value={link.password}
              onChange={(e) => setLink({ ...link, password: e.target.value })} />
          </Field>
          {needMfa && (
            <Field label="One-time MFA code">
              <input type="text" inputMode="numeric" autoComplete="off" className={inputCls} value={link.mfaCode}
                onChange={(e) => setLink({ ...link, mfaCode: e.target.value })} placeholder="123456" />
            </Field>
          )}
          <button
            onClick={linkGarmin}
            disabled={state === "working" || !link.email || !link.password || (needMfa && !link.mfaCode)}
            className="rounded bg-primary text-on-primary font-medium px-4 py-2 hover:brightness-110 disabled:opacity-50 w-fit"
          >
            {state === "working" ? "Linking…" : "Link Garmin"}
          </button>
          <p className="text-[11px] text-on-surface-variant">
            Your credentials are used once, on this computer, to obtain a session token — they are
            never stored. Only the token is kept, in your local app data.
          </p>
        </div>
      )}
      {err && <p className={`font-mono text-xs mt-2 ${state === "error" ? "text-error" : "text-on-surface-variant"}`}>{err}</p>}
    </div>
  );
}
