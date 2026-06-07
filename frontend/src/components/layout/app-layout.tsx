import { useState, useEffect, useCallback } from "react";
import { Outlet, NavLink, Link } from "react-router-dom";
import {
  FolderGit2,
  PlayCircle,
  Settings,
  Menu,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Search
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../hooks/use-auth";
import { useBreadcrumbs } from "../../hooks/use-breadcrumb";
import { CommandPalette } from "./command-palette";
import { LanguageSwitcher } from "../language-switcher";
import { cn } from "../../lib/utils";

const SIDEBAR_KEY = "qa-sidebar-open";

function loadSidebarPreference(): boolean {
  try {
    const stored = localStorage.getItem(SIDEBAR_KEY);
    if (stored !== null) return stored === "true";
  } catch { /* localStorage unavailable */ }
  return window.innerWidth >= 1024;
}

export function AppLayout() {
  const { t } = useTranslation();
  const [sidebarOpen, setSidebarOpen] = useState(loadSidebarPreference);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { logout } = useAuth();
  const { items: breadcrumbs } = useBreadcrumbs();

  const toggleSidebar = useCallback(() => {
    setSidebarOpen((prev) => {
      const next = !prev;
      try { localStorage.setItem(SIDEBAR_KEY, String(next)); } catch { /* noop */ }
      return next;
    });
  }, []);

  // Auto collapse sidebar on small screens
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 1024) {
        setSidebarOpen(false);
      } else {
        setSidebarOpen(loadSidebarPreference());
      }
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-canvas text-ink">
      {/* Mobile Sidebar Overlay */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-40 bg-canvas/80 backdrop-blur-sm md:hidden"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex flex-col border-r border-hairline bg-canvas transition-all duration-300 md:relative md:translate-x-0",
          sidebarOpen ? "w-[220px]" : "w-[68px]",
          mobileMenuOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        )}
      >
        <div className="flex h-14 items-center justify-between border-b border-hairline px-4">
          {(sidebarOpen || mobileMenuOpen) && <span className="font-semibold tracking-tight text-ink">{t('common.appName')}</span>}
          <button
            onClick={() => {
              if (window.innerWidth < 768) {
                setMobileMenuOpen(false);
              } else {
                toggleSidebar();
              }
            }}
            className="flex h-8 w-8 items-center justify-center rounded-md text-ink-subtle hover:bg-surface-1 hover:text-ink md:flex"
            aria-label={(sidebarOpen || mobileMenuOpen) ? t('nav.collapseSidebar') : t('nav.expandSidebar')}
          >
            {(sidebarOpen || mobileMenuOpen) ? <ChevronLeft className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
        </div>

        <nav className="flex-1 space-y-1 p-2">
          <NavItem to="/projects" icon={<FolderGit2 className="h-4 w-4" />} label={t('nav.projects')} isOpen={sidebarOpen || mobileMenuOpen} onClick={() => setMobileMenuOpen(false)} />
          <NavItem to="/runs" icon={<PlayCircle className="h-4 w-4" />} label={t('nav.runs')} isOpen={sidebarOpen || mobileMenuOpen} onClick={() => setMobileMenuOpen(false)} />
          <NavItem to="/settings" icon={<Settings className="h-4 w-4" />} label={t('nav.settings')} isOpen={sidebarOpen || mobileMenuOpen} onClick={() => setMobileMenuOpen(false)} />
        </nav>

        <div className="border-t border-hairline p-2">
          <LanguageSwitcher isOpen={sidebarOpen || mobileMenuOpen} />
          <button
            onClick={logout}
            className={cn(
              "flex w-full items-center rounded-md px-3 py-2 text-sm font-medium text-ink-subtle hover:bg-surface-1 hover:text-ink transition-colors",
              !(sidebarOpen || mobileMenuOpen) && "justify-center px-0"
            )}
          >
            <LogOut className="h-4 w-4 shrink-0" />
            {(sidebarOpen || mobileMenuOpen) && <span className="ml-3 truncate">{t('auth.logOut')}</span>}
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top Nav */}
        <header className="flex h-14 items-center justify-between border-b border-hairline bg-canvas px-6">
          <div className="flex items-center gap-4">
            <button
              className="md:hidden text-ink-subtle hover:text-ink"
              onClick={() => setMobileMenuOpen(true)}
              aria-label={t('nav.openMenu')}
            >
              <Menu className="h-5 w-5" />
            </button>
            <div className="flex items-center gap-2 text-sm text-ink-muted hidden sm:flex">
              {breadcrumbs.length > 0 ? (
                breadcrumbs.map((crumb, i) => (
                  <span key={i} className="flex items-center gap-2">
                    {i > 0 && <ChevronRight className="h-3 w-3 text-ink-tertiary" />}
                    {crumb.href ? (
                      <Link to={crumb.href} className="hover:text-ink transition-colors">
                        {crumb.label}
                      </Link>
                    ) : (
                      <span className="text-ink">{crumb.label}</span>
                    )}
                  </span>
                ))
              ) : (
                <span>{t('common.overview')}</span>
              )}
            </div>
          </div>

          <div className="flex items-center">
            <div className="flex items-center gap-2 text-sm text-ink-subtle hidden sm:flex border border-hairline bg-surface-1 rounded-md px-2 py-1">
              <Search className="h-3.5 w-3.5" />
              <span className="opacity-50">{t('nav.pressKey')}</span>
              <kbd className="font-mono text-[10px] bg-surface-2 px-1 rounded">⌘K</kbd>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto bg-canvas p-4 sm:p-6">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
      </div>

      <CommandPalette />
    </div>
  );
}

function NavItem({ to, icon, label, isOpen, onClick }: { to: string; icon: React.ReactNode; label: string; isOpen: boolean; onClick?: () => void }) {
  return (
    <NavLink
      to={to}
      onClick={onClick}
      className={({ isActive }) => cn(
        "flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors",
        isActive
          ? "bg-surface-2 text-ink"
          : "text-ink-subtle hover:bg-surface-1 hover:text-ink",
        !isOpen && "justify-center px-0"
      )}
      title={!isOpen ? label : undefined}
    >
      <span className="shrink-0">{icon}</span>
      {isOpen && <span className="ml-3 truncate">{label}</span>}
    </NavLink>
  );
}
