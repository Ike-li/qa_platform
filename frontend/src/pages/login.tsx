import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../hooks/use-auth";
import api from "../lib/api";
import i18n from "../i18n";

function createLoginSchema() {
  return z.object({
    username: z.string().min(1, i18n.t('validation.usernameRequired')),
    password: z.string().min(1, i18n.t('validation.passwordRequired')),
  });
}

type LoginFormValues = z.infer<ReturnType<typeof createLoginSchema>>;

export default function Login() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  const loginSchema = createLoginSchema();

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
  });

  const onSubmit = async (data: LoginFormValues) => {
    try {
      setError(null);
      const response = await api.post("/auth/login", {
        username: data.username,
        password: data.password,
      });
      login(response.data.access_token);
      navigate("/projects");
    } catch (err: unknown) {
      const axiosError = err as { response?: { data?: { detail?: string } } };
      setError(axiosError.response?.data?.detail || t('auth.loginFailed'));
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-4 text-ink">
      <div className="w-full max-w-sm rounded-xl border border-hairline bg-surface-1 p-8">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">{t('auth.signInTitle')}</h1>
          <p className="mt-2 text-sm text-ink-subtle">{t('auth.signInSubtitle')}</p>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {error && (
            <div className="rounded-md bg-status-failed/10 p-3 text-sm text-status-failed">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label htmlFor="username" className="text-sm font-medium text-ink-muted">{t('auth.username')}</label>
            <input
              id="username"
              type="text"
              {...register("username")}
              className="w-full rounded-md border border-hairline-strong bg-surface-1 px-3 py-2 text-sm placeholder:text-ink-tertiary focus:border-primary-focus focus:outline-none focus:ring-1 focus:ring-primary-focus"
              placeholder="admin"
            />
            {errors.username && <p className="text-xs text-status-failed">{errors.username.message}</p>}
          </div>

          <div className="space-y-2">
            <label htmlFor="password" className="text-sm font-medium text-ink-muted">{t('auth.password')}</label>
            <input
              id="password"
              type="password"
              {...register("password")}
              className="w-full rounded-md border border-hairline-strong bg-surface-1 px-3 py-2 text-sm placeholder:text-ink-tertiary focus:border-primary-focus focus:outline-none focus:ring-1 focus:ring-primary-focus"
              placeholder="••••••••"
            />
            {errors.password && <p className="text-xs text-status-failed">{errors.password.message}</p>}
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover focus:outline-none focus:ring-2 focus:ring-primary-focus focus:ring-offset-2 focus:ring-offset-canvas disabled:opacity-50"
          >
            {isSubmitting ? t('auth.signingIn') : t('auth.signIn')}
          </button>
        </form>
      </div>
    </div>
  );
}
