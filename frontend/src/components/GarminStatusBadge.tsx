import { useEffect, useState } from "react";
import { api } from "../api/client";

export function GarminStatusBadge() {
  const [connected, setConnected] = useState<boolean | null>(null);

  useEffect(() => {
    api.garminStatus()
      .then((s) => setConnected(s.connected))
      .catch(() => setConnected(false));
  }, []);

  const dot =
    connected === null ? "#ffd34f" : connected ? "#4ae176" : "#ffb4ab";
  const label =
    connected === null ? "Checking…" : connected ? "Garmin synced" : "Garmin offline";

  return (
    <div className="flex items-center gap-2 rounded-md border border-outline-variant/40 bg-surface-container px-3 py-2">
      <span
        className="h-2.5 w-2.5 rounded-full"
        style={{ backgroundColor: dot, boxShadow: `0 0 8px ${dot}` }}
      />
      <span className="font-mono text-xs text-on-surface-variant">{label}</span>
    </div>
  );
}
