"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { API_MODE, ApiError, post } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";
import { Duck } from "../duck";
import { FIELD, Field, PRIMARY_BTN, SECONDARY_BTN } from "./stub-parts";

/**
 * Log in / sign up. With the backend there is no password: a one-time link by email (`POST /auth/link`) or Google
 * (`GET /auth/google/start`); the session is the `quack_session` cookie. On mocks submitting just opens the app.
 */
export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const t = useT().stubs.auth;
  const live = useT().live;
  const router = useRouter();
  const id = useId();
  const signup = mode === "signup";
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (form: FormData) => {
    if (!API_MODE) {
      router.push("/");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await post("/auth/link", { email: String(form.get("email") ?? "").trim() });
      setSent(true);
    } catch (e) {
      setError(e instanceof ApiError && e.code === "RATE_LIMITED" ? live.rateLimited : e instanceof ApiError && e.status < 500 ? e.message : live.serverDown);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex h-full overflow-y-auto bg-cloth px-4 py-10">
      <div className="m-auto w-full max-w-[400px]">
        <Duck className="size-14" />
        <h1 className="mt-4 font-serif text-[28px] leading-tight font-bold text-paper">{signup ? t.signupTitle : t.loginTitle}</h1>
        <p className="mt-2 text-body text-paper-dim">{API_MODE ? live.linkBody : signup ? t.signupBody : t.loginBody}</p>

        {sent ? (
          <p role="status" className="mt-6 text-body text-paper">
            {live.linkSent}
          </p>
        ) : (
          <form
            className="mt-2"
            onSubmit={(e) => {
              e.preventDefault();
              void submit(new FormData(e.currentTarget));
            }}
          >
            <Field id={`${id}-email`} label={t.email}>
              <input id={`${id}-email`} name="email" type="email" required autoComplete="email" placeholder={t.emailPh} className={FIELD} />
            </Field>
            {error && (
              <p role="alert" className="mt-4 text-small text-st-confused">
                {error}
              </p>
            )}
            <button type="submit" disabled={busy} className={`${PRIMARY_BTN} mt-6 w-full`}>
              {busy ? live.linkSending : API_MODE ? live.linkSend : signup ? t.signup : t.login}
            </button>
            {API_MODE && (
              <>
                <p className="my-3 text-center text-small text-paper-dim">{live.orWord}</p>
                {/* a full page navigation on purpose: the backend answers with a redirect to Google */}
                <a href="/api/auth/google/start" className={`${SECONDARY_BTN} w-full`}>
                  {live.google}
                </a>
              </>
            )}
          </form>
        )}

        <p className="mt-5 text-small text-paper-dim">
          {signup ? t.haveAccount : t.noAccount}{" "}
          <Link href={signup ? "/login" : "/signup"} className="text-paper underline decoration-seam underline-offset-4 hover:decoration-paper-dim">
            {signup ? t.toLogin : t.toSignup}
          </Link>
        </p>
      </div>
    </main>
  );
}
