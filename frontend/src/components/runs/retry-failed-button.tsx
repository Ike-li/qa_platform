import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "../ui/button";
import { useRetryFailedRun } from "../../hooks/use-runs";

interface RetryFailedButtonProps {
  runId: string;
  failedCount: number;
}

/**
 * 只重跑失败用例的按钮。
 * - 无失败用例时不渲染（failedCount <= 0）。
 * - 非 pytest runner / 失败用例 > 200 等由后端返回 409，统一以 toast 提示后端消息。
 * - 成功后跳转到新生成的 Run 详情。
 */
export function RetryFailedButton({ runId, failedCount }: RetryFailedButtonProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { mutateAsync, isPending } = useRetryFailedRun(runId);

  if (failedCount <= 0) return null;

  const onRetryFailed = async () => {
    try {
      const nextRun = await mutateAsync();
      toast.success(t("runs.toast.retryFailedStarted"));
      void navigate(`/runs/${nextRun.id}`);
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || t("runs.toast.retryFailedFailed"));
    }
  };

  return (
    <Button
      type="button"
      size="sm"
      onClick={onRetryFailed}
      disabled={isPending}
      data-testid="retry-failed-button"
    >
      <RotateCcw className="mr-2 h-4 w-4" />
      {isPending
        ? t("runs.summary.retryingFailed")
        : t("runs.summary.retryFailed", { count: failedCount })}
    </Button>
  );
}
