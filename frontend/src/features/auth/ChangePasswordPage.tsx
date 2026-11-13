import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router';
import { z } from 'zod';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { useToast } from '../../components/ui/useToast';
import { ApiError } from '../../lib/api';
import { strings } from '../../lib/strings';
import { changePassword } from './api';
import { homePath, useAuth } from './auth-context';

const t = strings.auth;

const schema = z
  .object({
    current: z.string().min(1, t.passwordRequired),
    next: z.string().min(10, t.passwordTooShort),
    again: z.string(),
  })
  .refine((v) => v.next === v.again, { path: ['again'], message: t.passwordsDiffer });

/** Change your own password. Forced after a reset (`must_change_password`). */
export default function ChangePasswordPage() {
  const { user, updateUser, signOut } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { current: '', next: '', again: '' },
  });
  const { errors, isSubmitting } = form.formState;
  const forced = user?.must_change_password ?? false;

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      await changePassword(values.current, values.next);
      if (user) {
        const updated = { ...user, must_change_password: false };
        updateUser(updated);
        toast.show({ message: t.passwordChanged, tone: 'success' });
        navigate(homePath(updated), { replace: true });
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.common.somethingWentWrong);
      form.reset({ current: '', next: '', again: '' });
    }
  });

  return (
    <section className="mx-auto flex w-full max-w-md flex-col gap-4">
      <h1 className="text-2xl font-semibold text-slate-900">{t.changePasswordTitle}</h1>
      {forced && <Alert tone="info">{t.changePasswordForced}</Alert>}
      {error && <Alert>{error}</Alert>}
      <form
        noValidate
        onSubmit={onSubmit}
        className="flex flex-col gap-4 rounded-lg border border-slate-200 bg-white p-5"
      >
        <Input
          label={t.currentPassword}
          type="password"
          autoComplete="current-password"
          error={errors.current?.message}
          {...form.register('current')}
        />
        <Input
          label={t.newPassword}
          type="password"
          autoComplete="new-password"
          hint={t.passwordHint}
          error={errors.next?.message}
          {...form.register('next')}
        />
        <Input
          label={t.confirmPassword}
          type="password"
          autoComplete="new-password"
          error={errors.again?.message}
          {...form.register('again')}
        />
        <Button type="submit" loading={isSubmitting}>
          {t.savePassword}
        </Button>
        {forced && (
          <Button variant="ghost" onClick={() => void signOut()}>
            {t.signOut}
          </Button>
        )}
      </form>
    </section>
  );
}
