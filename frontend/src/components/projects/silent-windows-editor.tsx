import { CalendarClock, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import type { SilentWindowFormValue } from "./silent-windows-utils";

export function SilentWindowsEditor({
  windows,
  error,
  isSaving,
  onAdd,
  onChange,
  onRemove,
  onSave,
}: {
  windows: SilentWindowFormValue[];
  error: string | null;
  isSaving: boolean;
  onAdd: () => void;
  onChange: (index: number, key: keyof SilentWindowFormValue, value: string) => void;
  onRemove: (index: number) => void;
  onSave: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="rounded-xl border border-hairline bg-surface-1 p-6 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-lg font-medium">
          <CalendarClock className="h-5 w-5 text-primary" />
          {t('projects.silentWindows.title')}
        </h3>
        <Button type="button" variant="outline" size="sm" onClick={onAdd}>
          <Plus className="mr-2 h-4 w-4" />
          {t('projects.silentWindows.add')}
        </Button>
      </div>

      <div className="space-y-3">
        {windows.length === 0 ? (
          <div className="rounded-md border border-dashed border-hairline p-4 text-sm text-ink-tertiary">
            {t('projects.silentWindows.empty')}
          </div>
        ) : (
          windows.map((window, index) => (
            <div key={index} className="grid gap-3 rounded-md border border-hairline bg-canvas p-3">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor={`silent_start_${index}`}>{t('projects.silentWindows.start')}</Label>
                  <Input
                    id={`silent_start_${index}`}
                    type="datetime-local"
                    value={window.start_at}
                    onChange={(event) => onChange(index, "start_at", event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor={`silent_end_${index}`}>{t('projects.silentWindows.end')}</Label>
                  <Input
                    id={`silent_end_${index}`}
                    type="datetime-local"
                    value={window.end_at}
                    onChange={(event) => onChange(index, "end_at", event.target.value)}
                  />
                </div>
              </div>
              <div className="flex items-end gap-3">
                <div className="flex-1 space-y-2">
                  <Label htmlFor={`silent_reason_${index}`}>{t('projects.silentWindows.reason')}</Label>
                  <Input
                    id={`silent_reason_${index}`}
                    value={window.reason}
                    maxLength={200}
                    onChange={(event) => onChange(index, "reason", event.target.value)}
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => onRemove(index)}
                  aria-label={t('projects.silentWindows.remove')}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))
        )}
      </div>

      {error && <p className="text-xs text-status-failed">{error}</p>}

      <div className="flex justify-end pt-2">
        <Button type="button" disabled={isSaving} onClick={onSave}>
          {isSaving ? t('projects.settings.saving') : t('projects.settings.saveChanges')}
        </Button>
      </div>
    </div>
  );
}
