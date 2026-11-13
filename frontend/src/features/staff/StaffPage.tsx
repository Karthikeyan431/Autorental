import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { ErrorState } from '../../components/ui/ErrorState';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { Select } from '../../components/ui/Select';
import { Table, type Column } from '../../components/ui/Table';
import { useToast } from '../../components/ui/useToast';
import { ApiError } from '../../lib/api';
import { errorMessage } from '../../lib/errors';
import { formatDateTime } from '../../lib/format';
import { strings } from '../../lib/strings';
import type { User } from '../auth/api';
import { fetchCurrentSettings } from '../settings/api';
import {
  countActiveStaff,
  createStaff,
  deactivateStaff,
  listStaff,
  permissionCatalogue,
  reactivateStaff,
  resetStaffPassword,
  setStaffPermissions,
  updateStaff,
  type StaffInput,
} from './api';
import { PermissionsEditor } from './PermissionsEditor';

const s = strings.staff;

type Status = 'active' | 'inactive' | 'all';
type Action =
  | { kind: 'create' }
  | { kind: 'edit'; user: User }
  | { kind: 'deactivate'; user: User }
  | { kind: 'reactivate'; user: User }
  | { kind: 'reset'; user: User }
  | { kind: 'permissions'; user: User }
  | { kind: 'temporary'; name: string; password: string };

const staffSchema = z.object({
  name: z.string().trim().min(1, s.nameRequired).max(100),
  mobile: z
    .string()
    .trim()
    .refine((v) => /^(\+?91|0)?[6-9]\d{9}$/.test(v.replace(/[\s-]/g, '')), s.mobileInvalid),
  email: z.union([z.literal(''), z.email(s.emailInvalid)]),
});
type StaffForm = z.infer<typeof staffSchema>;

function StaffFormDialog({
  user,
  onClose,
  onSaved,
}: {
  user: User | null;
  onClose: () => void;
  onSaved: (result: { name: string; temporaryPassword?: string }) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const form = useForm<StaffForm>({
    resolver: zodResolver(staffSchema),
    defaultValues: {
      name: user?.name ?? '',
      mobile: user?.mobile.replace(/^\+91/, '') ?? '',
      email: user?.email ?? '',
    },
  });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    const input: StaffInput = {
      name: values.name,
      mobile: values.mobile,
      email: values.email || null,
    };
    try {
      if (user) {
        const saved = await updateStaff(user.id, input);
        onSaved({ name: saved.name });
      } else {
        const created = await createStaff(input);
        onSaved({ name: created.user.name, temporaryPassword: created.temporary_password });
      }
    } catch (e) {
      setError(errorMessage(e));
    }
  });

  return (
    <Dialog open title={user ? s.editTitle(user.name) : s.addTitle} onClose={onClose}>
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
        {error && <Alert>{error}</Alert>}
        <Input label={s.name} error={errors.name?.message} {...form.register('name')} />
        <Input
          label={s.mobile}
          inputMode="tel"
          error={errors.mobile?.message}
          {...form.register('mobile')}
        />
        <Input
          label={s.email}
          type="email"
          error={errors.email?.message}
          {...form.register('email')}
        />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {s.cancel}
          </Button>
          <Button type="submit" loading={isSubmitting}>
            {s.save}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function ConfirmDialog({
  title,
  body,
  confirmLabel,
  danger,
  withReason,
  onClose,
  onConfirm,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  danger?: boolean;
  withReason?: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };
  return (
    <Dialog
      open
      title={title}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {s.cancel}
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} loading={busy} onClick={run}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p>{body}</p>
        {withReason && (
          <Input
            label={s.reason}
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
        )}
        {error && <Alert>{error}</Alert>}
      </div>
    </Dialog>
  );
}

function TemporaryPasswordDialog({
  name,
  password,
  onClose,
}: {
  name: string;
  password: string;
  onClose: () => void;
}) {
  return (
    <Dialog
      open
      title={s.temporaryTitle}
      onClose={onClose}
      footer={<Button onClick={onClose}>{s.temporaryDone}</Button>}
    >
      <p>{s.temporaryIntro(name)}</p>
      <p
        className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-center font-mono text-lg select-all"
        data-testid="temporary-password"
      >
        {password}
      </p>
    </Dialog>
  );
}

function PermissionsDialog({
  user,
  onClose,
  onSaved,
}: {
  user: User;
  onClose: () => void;
  onSaved: () => void;
}) {
  const catalogue = useQuery({ queryKey: ['permission-catalogue'], queryFn: permissionCatalogue });
  const [selected, setSelected] = useState<string[]>([...user.permissions].sort());
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => setStaffPermissions(user.id, selected),
    onSuccess: onSaved,
    onError: (e) => setError(errorMessage(e)),
  });
  return (
    <Dialog
      open
      title={s.permissionsTitle(user.name)}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {s.cancel}
          </Button>
          <Button loading={save.isPending} disabled={!catalogue.data} onClick={() => save.mutate()}>
            {s.save}
          </Button>
        </>
      }
    >
      <div className="max-h-[60vh] overflow-y-auto pr-1">
        {error && <Alert>{error}</Alert>}
        {catalogue.isPending && <Loading />}
        {catalogue.isError && <ErrorState message={errorMessage(catalogue.error)} />}
        {catalogue.data && (
          <PermissionsEditor
            catalogue={catalogue.data}
            selected={selected}
            onChange={setSelected}
          />
        )}
      </div>
    </Dialog>
  );
}

export default function StaffPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [searchText, setSearchText] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<Status>('active');
  const [action, setAction] = useState<Action | null>(null);

  const list = useQuery({
    queryKey: ['staff', { page, search, status }],
    queryFn: () => listStaff({ page, search, status }),
  });
  const activeCount = useQuery({ queryKey: ['staff', 'active-count'], queryFn: countActiveStaff });
  const settings = useQuery({ queryKey: ['settings', 'current'], queryFn: fetchCurrentSettings });

  const close = () => setAction(null);
  const done = (message: string) => {
    void queryClient.invalidateQueries({ queryKey: ['staff'] });
    toast.show({ message, tone: 'success' });
    close();
  };

  const onSearch = (event: FormEvent) => {
    event.preventDefault();
    setPage(1);
    setSearch(searchText);
  };

  const columns: Column<User>[] = [
    {
      key: 'name',
      header: s.name,
      render: (u) => (
        <span className="flex flex-col">
          <span className="font-medium">{u.name}</span>
          {u.must_change_password && <span className="text-xs text-amber-700">{s.mustChange}</span>}
        </span>
      ),
    },
    {
      key: 'mobile',
      header: s.mobile,
      render: (u) => <span className="whitespace-nowrap">{u.mobile}</span>,
    },
    { key: 'email', header: s.emailColumn, render: (u) => u.email ?? '—' },
    {
      key: 'status',
      header: s.status,
      render: (u) => (
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            u.is_active ? 'bg-teal-50 text-teal-800' : 'bg-slate-100 text-slate-600'
          }`}
        >
          {u.is_active ? s.active : s.inactive}
        </span>
      ),
    },
    {
      key: 'last',
      header: s.lastSignIn,
      render: (u) => (
        <span className="whitespace-nowrap">
          {u.last_login_at ? formatDateTime(u.last_login_at) : s.never}
        </span>
      ),
    },
    {
      key: 'actions',
      header: s.actions,
      render: (u) => (
        <div className="flex flex-wrap gap-1">
          <Button variant="ghost" onClick={() => setAction({ kind: 'edit', user: u })}>
            {s.edit}
          </Button>
          <Button variant="ghost" onClick={() => setAction({ kind: 'permissions', user: u })}>
            {s.permissions}
          </Button>
          <Button variant="ghost" onClick={() => setAction({ kind: 'reset', user: u })}>
            {s.resetPassword}
          </Button>
          {u.is_active ? (
            <Button variant="ghost" onClick={() => setAction({ kind: 'deactivate', user: u })}>
              {s.deactivate}
            </Button>
          ) : (
            <Button variant="ghost" onClick={() => setAction({ kind: 'reactivate', user: u })}>
              {s.reactivate}
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.staff}</h1>
          {activeCount.data !== undefined && (
            <p className="text-sm text-slate-600">
              {s.summary(activeCount.data, settings.data?.staff_limit ?? null)}
            </p>
          )}
        </div>
        <Button onClick={() => setAction({ kind: 'create' })}>{s.add}</Button>
      </div>

      <form onSubmit={onSearch} className="flex flex-wrap items-end gap-3">
        <div className="min-w-56 flex-1">
          <Input
            label={s.search}
            type="search"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
        </div>
        <Select
          label={s.show}
          value={status}
          onChange={(event) => {
            setPage(1);
            setStatus(event.target.value as Status);
          }}
          options={[
            { value: 'active', label: s.filterActive },
            { value: 'inactive', label: s.filterInactive },
            { value: 'all', label: s.filterAll },
          ]}
        />
        <Button type="submit" variant="secondary">
          {s.searchButton}
        </Button>
      </form>

      {list.isPending && <Loading />}
      {list.isError && (
        <ErrorState
          message={errorMessage(list.error)}
          requestId={list.error instanceof ApiError ? list.error.requestId : null}
          onRetry={() => void list.refetch()}
        />
      )}
      {list.data && (
        <Table
          caption={strings.pages.staff}
          columns={columns}
          rows={list.data.items}
          getRowKey={(u) => u.id}
          pagination={{
            page: list.data.page,
            pageSize: list.data.page_size,
            total: list.data.total,
            onPageChange: setPage,
          }}
        />
      )}

      {action?.kind === 'create' && (
        <StaffFormDialog
          user={null}
          onClose={close}
          onSaved={({ name, temporaryPassword }) => {
            void queryClient.invalidateQueries({ queryKey: ['staff'] });
            toast.show({ message: s.created, tone: 'success' });
            setAction({ kind: 'temporary', name, password: temporaryPassword ?? '' });
          }}
        />
      )}
      {action?.kind === 'edit' && (
        <StaffFormDialog user={action.user} onClose={close} onSaved={() => done(s.saved)} />
      )}
      {action?.kind === 'permissions' && (
        <PermissionsDialog
          user={action.user}
          onClose={close}
          onSaved={() => done(s.permissionsSaved)}
        />
      )}
      {action?.kind === 'deactivate' && (
        <ConfirmDialog
          title={s.deactivateTitle(action.user.name)}
          body={s.deactivateBody}
          confirmLabel={s.deactivate}
          danger
          withReason
          onClose={close}
          onConfirm={async (reason) => {
            await deactivateStaff(action.user.id, reason);
            done(s.deactivated);
          }}
        />
      )}
      {action?.kind === 'reactivate' && (
        <ConfirmDialog
          title={s.reactivateTitle(action.user.name)}
          body={s.reactivateBody}
          confirmLabel={s.reactivate}
          onClose={close}
          onConfirm={async () => {
            await reactivateStaff(action.user.id);
            done(s.reactivated);
          }}
        />
      )}
      {action?.kind === 'reset' && (
        <ConfirmDialog
          title={s.resetTitle(action.user.name)}
          body={s.resetBody}
          confirmLabel={s.resetPassword}
          danger
          onClose={close}
          onConfirm={async () => {
            const result = await resetStaffPassword(action.user.id);
            void queryClient.invalidateQueries({ queryKey: ['staff'] });
            setAction({
              kind: 'temporary',
              name: action.user.name,
              password: result.temporary_password,
            });
          }}
        />
      )}
      {action?.kind === 'temporary' && (
        <TemporaryPasswordDialog name={action.name} password={action.password} onClose={close} />
      )}
    </section>
  );
}
