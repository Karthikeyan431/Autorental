import { zodResolver } from '@hookform/resolvers/zod';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type InputHTMLAttributes, type ReactNode } from 'react';
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
import { errorMessage } from '../../lib/errors';
import { formatDateTime, formatRupees } from '../../lib/format';
import { paiseToRupeesInput, parseRupeesToPaise } from '../../lib/money';
import { strings } from '../../lib/strings';
import {
  fetchCurrentSettings,
  fetchSettingsVersions,
  saveSettings,
  type SettingsValues,
  type SettingsVersion,
} from './api';

const t = strings.settings;

const time = z.string().regex(/^\d{2}:\d{2}$/, t.rentDueTimeRequired);
const wholeNumber = z
  .string()
  .trim()
  .regex(/^\d{1,6}$/, t.wholeNumber);

const schema = z.object({
  rent_due_time: time,
  due_day_offset: wholeNumber,
  weekly_pay_day: z.string().regex(/^[1-7]$/),
  weekly_mdr_warning_rupees: z
    .string()
    .refine((v) => parseRupeesToPaise(v) !== null, t.amountInvalid),
  business_name: z.string().trim().max(200),
  business_address: z.string().trim().max(500),
  business_upi_id: z.string().trim().max(200),
  upi_payee_name: z.string().trim().max(200),
  pay_request_time: time,
  whatsapp_template: z.string().trim().min(1).max(1000),
  licence_alert_days: wholeNumber,
  vehicle_alert_days: wholeNumber,
  escalation_suggest_after_days: wholeNumber,
  staff_limit: wholeNumber.refine((v) => Number(v) >= 1, t.atLeastOne),
  reveal_limit_per_hour: wholeNumber.refine((v) => Number(v) >= 1, t.atLeastOne),
  max_backdate_days: wholeNumber,
  advance_adjustments_enabled: z.boolean(),
  refunds_enabled: z.boolean(),
  permitted_licence_classes: z.string().max(500),
  accepted_id_types: z
    .array(z.enum(['masked_aadhaar', 'voter_id', 'passport']))
    .min(1, t.acceptedIdTypesRequired),
});
type Form = z.infer<typeof schema>;

const EMPTY: Form = {
  rent_due_time: '',
  due_day_offset: '0',
  weekly_pay_day: '1',
  weekly_mdr_warning_rupees: '2000',
  business_name: '',
  business_address: '',
  business_upi_id: '',
  upi_payee_name: '',
  pay_request_time: '08:00',
  whatsapp_template: '',
  licence_alert_days: '30',
  vehicle_alert_days: '30',
  escalation_suggest_after_days: '1',
  staff_limit: '10',
  reveal_limit_per_hour: '30',
  max_backdate_days: '7',
  advance_adjustments_enabled: true,
  refunds_enabled: false,
  permitted_licence_classes: '',
  accepted_id_types: ['masked_aadhaar'],
};

function toForm(v: SettingsValues): Form {
  return {
    rent_due_time: v.rent_due_time.slice(0, 5),
    due_day_offset: String(v.due_day_offset),
    weekly_pay_day: String(v.weekly_pay_day),
    weekly_mdr_warning_rupees: paiseToRupeesInput(v.weekly_mdr_warning_paise),
    business_name: v.business_name ?? '',
    business_address: v.business_address ?? '',
    business_upi_id: v.business_upi_id ?? '',
    upi_payee_name: v.upi_payee_name ?? '',
    pay_request_time: v.pay_request_time.slice(0, 5),
    whatsapp_template: v.whatsapp_template,
    licence_alert_days: String(v.licence_alert_days),
    vehicle_alert_days: String(v.vehicle_alert_days),
    escalation_suggest_after_days: String(v.escalation_suggest_after_days),
    staff_limit: String(v.staff_limit),
    reveal_limit_per_hour: String(v.reveal_limit_per_hour),
    max_backdate_days: String(v.max_backdate_days),
    advance_adjustments_enabled: v.advance_adjustments_enabled,
    refunds_enabled: v.refunds_enabled,
    permitted_licence_classes: v.permitted_licence_classes.join(', '),
    accepted_id_types: v.accepted_id_types ?? ['masked_aadhaar'],
  };
}

function toValues(f: Form): Partial<SettingsValues> {
  const textOrNull = (value: string) => value.trim() || null;
  const values: Partial<SettingsValues> = {
    rent_due_time: `${f.rent_due_time}:00`,
    due_day_offset: Number(f.due_day_offset),
    weekly_pay_day: Number(f.weekly_pay_day),
    weekly_mdr_warning_paise: parseRupeesToPaise(f.weekly_mdr_warning_rupees) ?? 0,
    business_name: textOrNull(f.business_name),
    business_address: textOrNull(f.business_address),
    business_upi_id: textOrNull(f.business_upi_id),
    upi_payee_name: textOrNull(f.upi_payee_name),
    pay_request_time: `${f.pay_request_time}:00`,
    licence_alert_days: Number(f.licence_alert_days),
    vehicle_alert_days: Number(f.vehicle_alert_days),
    escalation_suggest_after_days: Number(f.escalation_suggest_after_days),
    staff_limit: Number(f.staff_limit),
    reveal_limit_per_hour: Number(f.reveal_limit_per_hour),
    max_backdate_days: Number(f.max_backdate_days),
    advance_adjustments_enabled: f.advance_adjustments_enabled,
    refunds_enabled: f.refunds_enabled,
    permitted_licence_classes: f.permitted_licence_classes
      .split(',')
      .map((c) => c.trim())
      .filter(Boolean),
    accepted_id_types: f.accepted_id_types,
  };
  if (f.whatsapp_template.trim()) values.whatsapp_template = f.whatsapp_template.trim();
  return values;
}

/** Only the fields that differ from the current version (all of them for the first version). */
function changedValues(
  current: SettingsValues | null,
  next: Partial<SettingsValues>,
): Partial<SettingsValues> {
  if (!current) return next;
  const changes: Partial<SettingsValues> = {};
  for (const [key, value] of Object.entries(next) as [keyof SettingsValues, unknown][]) {
    if (JSON.stringify(current[key]) !== JSON.stringify(value)) {
      (changes as Record<string, unknown>)[key] = value;
    }
  }
  return changes;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="grid grid-cols-1 gap-4 rounded-lg border border-slate-200 bg-white p-4 md:grid-cols-2">
      <legend className="px-1 text-sm font-semibold text-slate-800">{title}</legend>
      {children}
    </fieldset>
  );
}

function Checkbox({ label, ...rest }: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="flex items-center gap-2 text-sm text-slate-800">
      <input type="checkbox" className="size-4 accent-teal-700" {...rest} />
      {label}
    </label>
  );
}

function SettingsForm({ current }: { current: SettingsVersion | null }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [pending, setPending] = useState<Partial<SettingsValues> | null>(null);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const form = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: current ? toForm(current) : EMPTY,
  });
  const { errors } = form.formState;

  const onSubmit = form.handleSubmit((values) => {
    setError(null);
    const changes = changedValues(current, toValues(values));
    if (Object.keys(changes).length === 0) {
      toast.show({ message: t.nothingChanged, tone: 'info' });
      return;
    }
    setPending(changes);
  });

  const confirm = async () => {
    if (!pending) return;
    setSaving(true);
    try {
      const saved = await saveSettings({ ...pending, reason: reason.trim() || null });
      queryClient.setQueryData(['settings', 'current'], saved);
      void queryClient.invalidateQueries({ queryKey: ['settings'] });
      form.reset(toForm(saved));
      toast.show({ message: t.saved, tone: 'success' });
      setPending(null);
      setReason('');
    } catch (e) {
      setError(errorMessage(e));
      setPending(null);
    } finally {
      setSaving(false);
    }
  };

  const weekdays = strings.weekdays.map((label, index) => ({
    value: String(index + 1),
    label,
  }));

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
      {!current && <Alert tone="info">{t.none}</Alert>}
      {error && <Alert>{error}</Alert>}
      <Section title={t.sections.rent}>
        <Input
          label={t.rentDueTime}
          type="time"
          error={errors.rent_due_time?.message}
          {...form.register('rent_due_time')}
        />
        <Input
          label={t.dueDayOffset}
          inputMode="numeric"
          error={errors.due_day_offset?.message}
          {...form.register('due_day_offset')}
        />
        <Select label={t.weeklyPayDay} options={weekdays} {...form.register('weekly_pay_day')} />
        <Input
          label={t.weeklyMdrWarning}
          inputMode="decimal"
          error={errors.weekly_mdr_warning_rupees?.message}
          {...form.register('weekly_mdr_warning_rupees')}
        />
      </Section>
      <Section title={t.sections.business}>
        <Input
          label={t.businessName}
          error={errors.business_name?.message}
          {...form.register('business_name')}
        />
        <Input
          label={t.businessAddress}
          error={errors.business_address?.message}
          {...form.register('business_address')}
        />
        <Input
          label={t.businessUpiId}
          error={errors.business_upi_id?.message}
          {...form.register('business_upi_id')}
        />
        <Input
          label={t.upiPayeeName}
          error={errors.upi_payee_name?.message}
          {...form.register('upi_payee_name')}
        />
      </Section>
      <Section title={t.sections.payRequests}>
        <Input
          label={t.payRequestTime}
          type="time"
          error={errors.pay_request_time?.message}
          {...form.register('pay_request_time')}
        />
        <div className="md:col-span-2">
          <label htmlFor="whatsapp-template" className="text-sm font-medium text-slate-800">
            {t.whatsappTemplate}
          </label>
          <textarea
            id="whatsapp-template"
            rows={3}
            className="mt-1 w-full rounded-md border border-slate-300 p-3 text-sm"
            {...form.register('whatsapp_template')}
          />
        </div>
      </Section>
      <Section title={t.sections.alerts}>
        <Input
          label={t.licenceAlertDays}
          inputMode="numeric"
          error={errors.licence_alert_days?.message}
          {...form.register('licence_alert_days')}
        />
        <Input
          label={t.vehicleAlertDays}
          inputMode="numeric"
          error={errors.vehicle_alert_days?.message}
          {...form.register('vehicle_alert_days')}
        />
        <Input
          label={t.escalationSuggestAfterDays}
          inputMode="numeric"
          error={errors.escalation_suggest_after_days?.message}
          {...form.register('escalation_suggest_after_days')}
        />
        <Input
          label={t.permittedLicenceClasses}
          error={errors.permitted_licence_classes?.message}
          {...form.register('permitted_licence_classes')}
        />
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium text-slate-800">{t.acceptedIdTypes}</legend>
          {(['masked_aadhaar', 'voter_id', 'passport'] as const).map((value) => (
            <Checkbox
              key={value}
              label={strings.kyc.idTypes[value] ?? value}
              value={value}
              {...form.register('accepted_id_types')}
            />
          ))}
          {errors.accepted_id_types?.message && (
            <p className="text-xs font-medium text-red-700">{errors.accepted_id_types.message}</p>
          )}
        </fieldset>
      </Section>
      <Section title={t.sections.staffAndAdvance}>
        <Input
          label={t.staffLimit}
          inputMode="numeric"
          error={errors.staff_limit?.message}
          {...form.register('staff_limit')}
        />
        <Input
          label={t.revealLimit}
          inputMode="numeric"
          error={errors.reveal_limit_per_hour?.message}
          {...form.register('reveal_limit_per_hour')}
        />
        <Input
          label={t.maxBackdateDays}
          inputMode="numeric"
          error={errors.max_backdate_days?.message}
          {...form.register('max_backdate_days')}
        />
        <div className="flex flex-col justify-center gap-2">
          <Checkbox
            label={t.advanceAdjustmentsEnabled}
            {...form.register('advance_adjustments_enabled')}
          />
          <Checkbox label={t.refundsEnabled} {...form.register('refunds_enabled')} />
        </div>
      </Section>
      <div className="flex justify-end">
        <Button type="submit">{t.save}</Button>
      </div>

      <Dialog
        open={pending !== null}
        title={t.confirmTitle}
        onClose={() => setPending(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setPending(null)}>
              {strings.staff.cancel}
            </Button>
            <Button loading={saving} onClick={() => void confirm()}>
              {t.confirm}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <p>{t.confirmBody}</p>
          <Input
            label={t.reason}
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
      </Dialog>
    </form>
  );
}

function History() {
  const [page, setPage] = useState(1);
  const versions = useQuery({
    queryKey: ['settings', 'versions', page],
    queryFn: () => fetchSettingsVersions(page),
  });
  const columns: Column<SettingsVersion>[] = [
    { key: 'from', header: t.effectiveFrom, render: (v) => formatDateTime(v.effective_from) },
    { key: 'by', header: t.changedBy, render: (v) => v.created_by_name ?? t.system },
    { key: 'due', header: t.rentDueTime, render: (v) => v.rent_due_time.slice(0, 5) },
    { key: 'limit', header: t.staffLimit, align: 'right', render: (v) => v.staff_limit },
    {
      key: 'mdr',
      header: t.mdrWarningShort,
      align: 'right',
      render: (v) => formatRupees(v.weekly_mdr_warning_paise),
    },
  ];
  if (versions.isPending) return <Loading />;
  if (versions.isError) return <ErrorState onRetry={() => void versions.refetch()} />;
  return (
    <Table
      caption={t.history}
      columns={columns}
      rows={versions.data.items}
      getRowKey={(v) => v.id}
      pagination={{
        page: versions.data.page,
        pageSize: versions.data.page_size,
        total: versions.data.total,
        onPageChange: setPage,
      }}
    />
  );
}

export default function SettingsPage() {
  const current = useQuery({ queryKey: ['settings', 'current'], queryFn: fetchCurrentSettings });
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.settings}</h1>
      <p className="text-sm text-slate-600">{t.intro}</p>
      {current.isPending && <Loading />}
      {current.isError && <ErrorState onRetry={() => void current.refetch()} />}
      {current.isSuccess && (
        <SettingsForm key={current.data?.id ?? 'none'} current={current.data} />
      )}
      <h2 className="mt-4 text-lg font-semibold text-slate-900">{t.history}</h2>
      <History />
    </section>
  );
}
