import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { Performance } from "./pages/Performance";
import { Settings } from "./pages/Settings";
import { Workout } from "./pages/Workout";
import { Calendar } from "./pages/Calendar";

export default function App() {
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
