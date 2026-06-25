import { NavLink, Outlet } from "react-router-dom";
import { LayoutDashboard, Dumbbell, CalendarDays, TrendingUp, Settings } from "lucide-react";
import { GarminStatusBadge } from "./GarminStatusBadge";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/workout", label: "Workout", icon: Dumbbell, end: false },
  { to: "/calendar", label: "Calendar", icon: CalendarDays, end: false },
  { to: "/performance", label: "Performance", icon: TrendingUp, end: false },
  { to: "/settings", label: "Settings", icon: Settings, end: false },
];

function Wordmark() {
  return (
    <div className="flex items-center gap-2 px-2">
      <img src="/triathlon_logo.png" alt="TriFlow" className="h-8 w-8 object-contain" />
      <span className="font-display font-extrabold tracking-tight text-lg text-on-surface">
        TRI<span className="text-primary">FLOW</span>
      </span>
    </div>
  );
}

export function Layout() {
  return (
    <div className="min-h-full md:flex">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex md:flex-col md:w-60 shrink-0 border-r border-outline-variant/40 bg-surface-container-low p-4 gap-6">
        <Wordmark />
        <nav className="flex flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-primary/15 text-primary"
                    : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto">
          <GarminStatusBadge />
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 min-w-0 pb-20 md:pb-0">
        <Outlet />
      </main>

      {/* Mobile bottom nav */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 z-10 border-t border-outline-variant/40 bg-surface-container-low grid grid-cols-5">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex flex-col items-center gap-1 py-2 text-[11px] ${
                isActive ? "text-primary" : "text-on-surface-variant"
              }`
            }
          >
            <Icon size={20} />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
