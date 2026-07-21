import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { Performance } from "./pages/Performance";
import { Settings } from "./pages/Settings";
import { Workout } from "./pages/Workout";
import { Calendar } from "./pages/Calendar";
import { Onboarding } from "./pages/Onboarding";
import { api } from "./api/client";
import type { AthleteProfile } from "./api/types";

export default function App() {
  const [profile, setProfile] = useState<AthleteProfile | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  useEffect(() => {
    api.profile().then(setProfile).catch((e) => setLoadErr(String(e)));
  }, []);

  if (loadErr) return <div className="p-8 text-error font-mono text-sm">Failed to load: {loadErr}</div>;
  if (!profile) return <div className="p-8 text-on-surface-variant">Loading…</div>;

  // First launch: no sidebar/nav yet, just the wizard. Once it saves a
  // profile with onboarding_complete, this flips straight into the real app.
  if (!profile.onboarding_complete) {
    return <Onboarding onComplete={setProfile} />;
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="workout" element={<Workout />} />
          <Route path="calendar" element={<Calendar />} />
          <Route path="performance" element={<Performance />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
