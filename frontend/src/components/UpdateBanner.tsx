import { useEffect, useState } from "react";
import { Download, X } from "lucide-react";
import { api } from "../api/client";

declare global {
  interface Window {
    pywebview?: { api?: { open_external?: (url: string) => void } };
  }
}

/** Opens in the user's real browser when running inside the desktop shell
 * (so a GitHub release page doesn't get trapped in the embedded webview);
 * falls back to a normal new tab in dev/browser contexts. */
function openExternal(url: string) {
  if (window.pywebview?.api?.open_external) window.pywebview.api.open_external(url);
  else window.open(url, "_blank", "noopener,noreferrer");
}

/** Checks GitHub Releases once per launch; silent no-op if offline or up to date. */
export function UpdateBanner() {
  const [info, setInfo] = useState<{ latest: string; url: string } | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    api.version()
      .then((v) => {
        if (v.update_available && v.latest && v.latest_url) {
          setInfo({ latest: v.latest, url: v.latest_url });
        }
      })
      .catch(() => {}); // offline or rate-limited — say nothing
  }, []);

  if (!info || dismissed) return null;

  return (
    <div className="flex items-center gap-3 bg-primary/15 border-b border-primary/30 px-4 py-2 text-sm">
      <Download size={16} className="text-primary shrink-0" />
      <span className="text-on-surface">
        TriFlow <span className="font-mono">{info.latest}</span> is available.
      </span>
      <button
        onClick={() => openExternal(info.url)}
        className="font-medium text-primary hover:underline"
      >
        Download
      </button>
      <button
        onClick={() => setDismissed(true)}
        className="ml-auto text-on-surface-variant hover:text-on-surface"
        title="Dismiss"
      >
        <X size={16} />
      </button>
    </div>
  );
}
