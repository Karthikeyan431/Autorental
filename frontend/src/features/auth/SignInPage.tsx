import { zodResolver } from '@hookform/resolvers/zod';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useForm, type UseFormRegisterReturn } from 'react-hook-form';
import { Navigate, useLocation, useNavigate } from 'react-router';
import { z } from 'zod';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { ApiError } from '../../lib/api';
import { errorMessage } from '../../lib/errors';
import { strings } from '../../lib/strings';
import {
  confirmTotp,
  login,
  startTotpSetup,
  submitTotp,
  type Enrolled,
  type SignedIn,
  type TotpSetup,
} from './api';
import { homePath, useAuth } from './auth-context';

const t = strings.auth;

type Step =
  | { kind: 'password' }
  | { kind: 'totp'; challenge: string }
  | { kind: 'setup'; challenge: string }
  | { kind: 'recovery'; result: Enrolled };

function Card({ title, intro, children }: { title: string; intro?: string; children: ReactNode }) {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-slate-50 px-4 py-10">
      <section className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-sm font-semibold text-teal-900">{strings.appName}</p>
        <h1 className="mt-2 text-2xl font-semibold text-slate-900">{title}</h1>
        {intro && <p className="mt-2 text-sm text-slate-600">{intro}</p>}
        <div className="mt-6 flex flex-col gap-4">{children}</div>
      </section>
    </main>
  );
}

const passwordSchema = z.object({
  login: z.string().trim().min(1, t.loginRequired),
  password: z.string().min(1, t.passwordRequired),
});

function PasswordStep({
  notice,
  onSignedIn,
  onChallenge,
}: {
  notice: string | null;
  onSignedIn: (result: SignedIn) => void;
  onChallenge: (step: Step) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof passwordSchema>>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { login: '', password: '' },
  });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      const result = await login(values.login, values.password);
      if (result.status === 'ok') onSignedIn(result);
      else if (result.status === 'totp_required')
        onChallenge({ kind: 'totp', challenge: result.challenge_token });
      else onChallenge({ kind: 'setup', challenge: result.challenge_token });
    } catch (e) {
      setError(errorMessage(e));
      form.resetField('password');
    }
  });

  return (
    <Card title={t.signInTitle} intro={t.signInIntro}>
      {notice && <Alert tone="info">{notice}</Alert>}
      {error && <Alert>{error}</Alert>}
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
        <Input
          label={t.login}
          autoComplete="username"
          inputMode="email"
          error={errors.login?.message}
          {...form.register('login')}
        />
        <Input
          label={t.password}
          type="password"
          autoComplete="current-password"
          error={errors.password?.message}
          {...form.register('password')}
        />
        <Button type="submit" loading={isSubmitting}>
          {t.signIn}
        </Button>
      </form>
    </Card>
  );
}

const codeSchema = z.object({ code: z.string().regex(/^\d{6}$/, t.codeInvalid) });
const recoverySchema = z.object({
  recovery_code: z
    .string()
    .trim()
    .regex(/^[a-zA-Z0-9]{5}-?[a-zA-Z0-9]{5}$/, t.recoveryCodeInvalid),
});

function CodeInput({
  error,
  registration,
}: {
  error: string | undefined;
  registration: UseFormRegisterReturn<'code'>;
}) {
  return (
    <Input
      label={t.code}
      inputMode="numeric"
      autoComplete="one-time-code"
      maxLength={6}
      error={error}
      {...registration}
    />
  );
}

function TotpStep({
  challenge,
  onSignedIn,
  onRestart,
}: {
  challenge: string;
  onSignedIn: (result: SignedIn) => void;
  onRestart: (notice: string) => void;
}) {
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const codeForm = useForm<{ code: string }>({
    resolver: zodResolver(codeSchema),
    defaultValues: { code: '' },
  });
  const recoveryForm = useForm<{ recovery_code: string }>({
    resolver: zodResolver(recoverySchema),
    defaultValues: { recovery_code: '' },
  });

  async function send(entry: { code: string } | { recovery_code: string }) {
    setError(null);
    try {
      onSignedIn(await submitTotp(challenge, entry));
    } catch (e) {
      if (
        e instanceof ApiError &&
        (e.code === 'CHALLENGE_INVALID' || e.code === 'ACCOUNT_LOCKED')
      ) {
        onRestart(e.message);
        return;
      }
      setError(errorMessage(e));
      codeForm.resetField('code');
    }
  }

  return (
    <Card title={t.totpTitle} intro={useRecovery ? undefined : t.totpIntro}>
      {error && <Alert>{error}</Alert>}
      {useRecovery ? (
        <form
          noValidate
          onSubmit={recoveryForm.handleSubmit((v) => send({ recovery_code: v.recovery_code }))}
          className="flex flex-col gap-4"
        >
          <Input
            label={t.recoveryCode}
            autoComplete="off"
            error={recoveryForm.formState.errors.recovery_code?.message}
            {...recoveryForm.register('recovery_code')}
          />
          <Button type="submit" loading={recoveryForm.formState.isSubmitting}>
            {t.verify}
          </Button>
        </form>
      ) : (
        <form
          noValidate
          onSubmit={codeForm.handleSubmit((v) => send({ code: v.code }))}
          className="flex flex-col gap-4"
        >
          <CodeInput
            error={codeForm.formState.errors.code?.message}
            registration={codeForm.register('code')}
          />
          <Button type="submit" loading={codeForm.formState.isSubmitting}>
            {t.verify}
          </Button>
        </form>
      )}
      <Button variant="ghost" onClick={() => setUseRecovery((value) => !value)}>
        {useRecovery ? t.useAppCode : t.useRecoveryCode}
      </Button>
      <Button variant="ghost" onClick={() => onRestart('')}>
        {t.backToSignIn}
      </Button>
    </Card>
  );
}

function SetupStep({
  challenge,
  onEnrolled,
  onRestart,
}: {
  challenge: string;
  onEnrolled: (result: Enrolled) => void;
  onRestart: (notice: string) => void;
}) {
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ code: string }>({
    resolver: zodResolver(codeSchema),
    defaultValues: { code: '' },
  });

  useEffect(() => {
    let cancelled = false;
    startTotpSetup(challenge)
      .then((value) => {
        if (!cancelled) setSetup(value);
      })
      .catch((e: unknown) => {
        if (!cancelled) onRestart(errorMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [challenge, onRestart]);

  const onSubmit = form.handleSubmit(async ({ code }) => {
    setError(null);
    try {
      onEnrolled(await confirmTotp(challenge, code));
    } catch (e) {
      if (
        e instanceof ApiError &&
        (e.code === 'CHALLENGE_INVALID' || e.code === 'ACCOUNT_LOCKED')
      ) {
        onRestart(e.message);
        return;
      }
      setError(errorMessage(e));
      form.resetField('code');
    }
  });

  return (
    <Card title={t.setupTitle} intro={t.setupIntro}>
      {!setup ? (
        <Loading />
      ) : (
        <>
          <img
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(setup.qr_svg)}`}
            alt={t.qrAlt}
            className="mx-auto size-56 rounded border border-slate-200 bg-white p-2"
          />
          <div className="text-sm text-slate-700">
            <p>{t.secretLabel}</p>
            <p className="mt-1 font-mono text-base break-all select-all" data-testid="totp-secret">
              {setup.secret.match(/.{1,4}/g)?.join(' ')}
            </p>
          </div>
          {error && <Alert>{error}</Alert>}
          <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
            <CodeInput
              error={form.formState.errors.code?.message}
              registration={form.register('code')}
            />
            <Button type="submit" loading={form.formState.isSubmitting}>
              {t.confirmSetup}
            </Button>
          </form>
        </>
      )}
      <Button variant="ghost" onClick={() => onRestart('')}>
        {t.backToSignIn}
      </Button>
    </Card>
  );
}

function RecoveryStep({ result, onDone }: { result: Enrolled; onDone: () => void }) {
  const [saved, setSaved] = useState(false);
  return (
    <Card title={t.recoveryTitle} intro={t.recoveryIntro}>
      <ol className="grid grid-cols-2 gap-2 rounded-md border border-slate-200 bg-slate-50 p-4 font-mono text-sm">
        {result.recovery_codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ol>
      <label className="flex items-center gap-2 text-sm text-slate-800">
        <input
          type="checkbox"
          className="size-4 accent-teal-700"
          checked={saved}
          onChange={(event) => setSaved(event.target.checked)}
        />
        {t.recoverySaved}
      </label>
      <Button disabled={!saved} onClick={onDone}>
        {t.continue}
      </Button>
    </Card>
  );
}

export default function SignInPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [step, setStep] = useState<Step>({ kind: 'password' });
  const [notice, setNotice] = useState<string | null>(null);

  const from = (location.state as { from?: string } | null)?.from;

  function finish(result: SignedIn) {
    auth.completeSignIn(result);
    navigate(from && from !== '/sign-in' ? from : homePath(result.user), { replace: true });
  }

  // Stable, so the setup step does not ask for a new secret on every render.
  const restart = useCallback((message: string) => {
    setNotice(message || null);
    setStep({ kind: 'password' });
  }, []);

  if (auth.state.status === 'loading') {
    return (
      <Card title={t.signInTitle}>
        <Loading label={t.restoring} />
      </Card>
    );
  }
  if (auth.state.status === 'signedIn' && step.kind !== 'recovery') {
    return <Navigate to={homePath(auth.state.user)} replace />;
  }

  switch (step.kind) {
    case 'password':
      return <PasswordStep notice={notice} onSignedIn={finish} onChallenge={setStep} />;
    case 'totp':
      return <TotpStep challenge={step.challenge} onSignedIn={finish} onRestart={restart} />;
    case 'setup':
      return (
        <SetupStep
          challenge={step.challenge}
          onEnrolled={(result) => setStep({ kind: 'recovery', result })}
          onRestart={restart}
        />
      );
    case 'recovery':
      return <RecoveryStep result={step.result} onDone={() => finish(step.result)} />;
  }
}
