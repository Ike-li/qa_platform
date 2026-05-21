import { useEffect, useState, useCallback } from "react";
import { X, Loader2 } from "lucide-react";
import { Button } from "../ui/button";

interface ArtifactPreviewProps {
  url: string;
  onClose: () => void;
}

export function ArtifactPreview({ url, onClose }: ArtifactPreviewProps) {
  const [loading, setLoading] = useState(true);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [handleKeyDown]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative flex h-[90vh] w-[90vw] flex-col rounded-xl border border-hairline bg-surface-1 shadow-2xl">
        {/* Toolbar */}
        <div className="flex items-center justify-between border-b border-hairline px-4 py-2">
          <span className="text-sm font-medium text-ink">Allure Report</span>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close preview">
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Content */}
        <div className="relative flex-1">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          )}
          <iframe
            src={url}
            title="Allure Report Preview"
            className="h-full w-full border-0"
            sandbox="allow-scripts"
            referrerPolicy="no-referrer"
            onLoad={() => setLoading(false)}
          />
        </div>
      </div>
    </div>
  );
}
