import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";

interface Breadcrumb {
  label: string;
  href?: string;
}

interface BreadcrumbContextType {
  items: Breadcrumb[];
  setBreadcrumbs: (items: Breadcrumb[]) => void;
}

const BreadcrumbContext = createContext<BreadcrumbContextType | undefined>(
  undefined,
);

export function BreadcrumbProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Breadcrumb[]>([]);

  const setBreadcrumbs = useCallback((items: Breadcrumb[]) => {
    setItems(items);
  }, []);

  return (
    <BreadcrumbContext.Provider value={{ items, setBreadcrumbs }}>
      {children}
    </BreadcrumbContext.Provider>
  );
}

/** Access the breadcrumb context (used by the layout header). */
// eslint-disable-next-line react-refresh/only-export-components
export function useBreadcrumbs() {
  const ctx = useContext(BreadcrumbContext);
  if (!ctx) {
    throw new Error("useBreadcrumbs must be used within BreadcrumbProvider");
  }
  return ctx;
}

/**
 * Set the header breadcrumb trail from any page component.
 * Cleans up automatically when the component unmounts.
 *
 * @example
 *   useSetBreadcrumbs([
 *     { label: 'Projects', href: '/projects' },
 *     { label: project.name },
 *   ]);
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useSetBreadcrumbs(items: Breadcrumb[]) {
  const { setBreadcrumbs } = useBreadcrumbs();
  useEffect(() => {
    setBreadcrumbs(items);
    return () => setBreadcrumbs([]);
  }, [setBreadcrumbs, items]);
}
