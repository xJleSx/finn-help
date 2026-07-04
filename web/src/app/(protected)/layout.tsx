"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AuthGuard } from "@/components/AuthGuard";
import { useAuth } from "@/hooks/useAuth";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: "◈" },
  { href: "/instruments", label: "Инструменты", icon: "▤" },
  { href: "/alerts", label: "Алерты", icon: "⚡" },
  { href: "/paper", label: "Paper", icon: "⟐" },
];

export default function ProtectedLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <Shell>{children}</Shell>
    </AuthGuard>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen bg-gray-950">
      <aside className="fixed left-0 top-0 bottom-0 w-56 bg-gray-900/50 border-r border-white/5 backdrop-blur-sm z-40 hidden lg:flex flex-col">
        <div className="p-5 border-b border-white/5">
          <Link href="/dashboard" className="text-lg font-light tracking-tight">
            Fin<span className="text-amber-400 font-medium">Advisor</span>
          </Link>
          <p className="text-[10px] text-gray-600 mt-0.5">AI финансовый ассистент</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {navItems.map((item) => {
            const isActive = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition ${
                  isActive
                    ? "bg-amber-400/10 text-amber-400"
                    : "text-gray-400 hover:text-white hover:bg-white/5"
                }`}
              >
                <span className="text-xs">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="p-4 border-t border-white/5">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-6 h-6 rounded-full bg-amber-400/20 flex items-center justify-center">
              <span className="text-xs text-amber-400 font-medium">
                {user?.username?.charAt(0).toUpperCase() || "?"}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-white truncate">{user?.username}</p>
              <p className="text-[10px] text-gray-600">{user?.risk_profile === "conservative" ? "Консервативный" : user?.risk_profile === "aggressive" ? "Агрессивный" : "Умеренный"}</p>
            </div>
          </div>
          <button
            onClick={logout}
            className="w-full text-xs text-gray-500 hover:text-red-400 transition text-left px-1 py-1"
          >
            Выйти
          </button>
        </div>
      </aside>

      <main className="lg:ml-56 min-h-screen">
        <header className="sticky top-0 z-30 bg-gray-950/80 backdrop-blur-sm border-b border-white/5 px-4 lg:px-8 py-3 flex items-center justify-between lg:hidden">
          <Link href="/dashboard" className="text-sm font-light">
            Fin<span className="text-amber-400 font-medium">Advisor</span>
          </Link>
          <div className="flex items-center gap-3">
            <nav className="flex gap-2">
              {navItems.map((item) => {
                const isActive = pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`px-2.5 py-1 rounded-lg text-xs transition ${
                      isActive ? "bg-amber-400/10 text-amber-400" : "text-gray-500"
                    }`}
                  >
                    {item.icon} {item.label}
                  </Link>
                );
              })}
            </nav>
            <button onClick={logout} className="text-xs text-gray-500 hover:text-red-400 transition">
              Выйти
            </button>
          </div>
        </header>
        <div className="p-4 lg:p-8">{children}</div>
      </main>
    </div>
  );
}
