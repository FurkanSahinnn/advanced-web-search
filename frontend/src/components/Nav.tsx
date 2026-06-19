import { Link, NavLink } from "react-router-dom";
import {
  Settings as SettingsIcon,
  Languages,
  BookOpen,
} from "lucide-react";
import { useLang } from "../lib/i18n";
import { cn } from "../lib/cn";

export function Nav() {
  const { t, lang, setLang } = useLang();

  return (
    <header className="sticky top-0 z-40 border-b border-[var(--color-border)] bg-[color-mix(in_srgb,var(--color-bg)_85%,transparent)] backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-4 px-4">
        <Link to="/" className="flex items-center gap-2">
          <img src="/logo.svg" alt="" className="h-8 w-8" />
          <div className="leading-none">
            <span className="text-sm font-bold tracking-tight text-[var(--color-fg)]">
              {t("app.title")}
            </span>
            <span className="ml-1.5 text-[11px] text-[var(--color-muted)]">
              {t("app.tagline")}
            </span>
          </div>
        </Link>

        <nav className="ml-4 flex items-center gap-1 text-sm">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              cn(
                "rounded-md px-3 py-1.5 transition-colors",
                isActive
                  ? "bg-[var(--color-surface-2)] text-[var(--color-fg)]"
                  : "text-[var(--color-muted)] hover:text-[var(--color-fg)]",
              )
            }
          >
            {t("nav.home")}
          </NavLink>
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors",
                isActive
                  ? "bg-[var(--color-surface-2)] text-[var(--color-fg)]"
                  : "text-[var(--color-muted)] hover:text-[var(--color-fg)]",
              )
            }
          >
            <SettingsIcon size={14} />
            {t("nav.settings")}
          </NavLink>
          <NavLink
            to="/about"
            className={({ isActive }) =>
              cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors",
                isActive
                  ? "bg-[var(--color-surface-2)] text-[var(--color-fg)]"
                  : "text-[var(--color-muted)] hover:text-[var(--color-fg)]",
              )
            }
          >
            <BookOpen size={14} />
            {t("nav.about")}
          </NavLink>
        </nav>

        <div className="ml-auto flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-0.5 text-xs">
          <Languages size={13} className="ml-1 text-[var(--color-faint)]" />
          {(["tr", "en"] as const).map((l) => (
            <button
              key={l}
              onClick={() => setLang(l)}
              className={cn(
                "rounded px-2 py-1 font-medium uppercase transition-colors",
                lang === l
                  ? "bg-[var(--color-accent)] text-[var(--color-accent-fg)]"
                  : "text-[var(--color-muted)] hover:text-[var(--color-fg)]",
              )}
            >
              {l}
            </button>
          ))}
        </div>
      </div>
    </header>
  );
}
