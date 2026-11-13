import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { containsAadhaarLike, NO_FULL_NUMBER_MESSAGE } from '../../lib/aadhaar';
import { errorMessage } from '../../lib/errors';
import { strings } from '../../lib/strings';
import { createDriver, updateDriver, type Driver, type DriverInput } from './api';

const t = strings.drivers;

const MOBILE = /^(\+?91|0)?[6-9]\d{9}$/;
const mobileOk = (v: string) => MOBILE.test(v.replace(/[\s-]/g, ''));
const text = (max: number, required?: string) => {
  const base = z.string().trim().max(max);
  return (required ? base.min(1, required) : base).refine(
    (v) => !containsAadhaarLike(v),
    NO_FULL_NUMBER_MESSAGE,
  );
};

const DATE = /^\d{4}-\d{2}-\d{2}$/;

const baseSchema = z.object({
  full_name: text(120, t.nameRequired),
  mobile: z.string().trim().refine(mobileOk, t.mobileInvalid),
  alt_mobile: z
    .string()
    .trim()
    .refine((v) => v === '' || mobileOk(v), t.mobileInvalid),
  address: text(500, t.addressRequired),
  date_of_birth: z.string().regex(DATE, t.dobRequired),
  emergency_name: text(120),
  emergency_mobile: z
    .string()
    .trim()
    .refine((v) => v === '' || mobileOk(v), t.mobileInvalid),
  payment_rhythm: z.enum(['daily', 'weekly']),
});
// Editing: the masked fields are not pre-filled and blank keeps the current value (N17).
const editSchema = baseSchema.extend({
  address: text(500),
  date_of_birth: z.string().refine((v) => v === '' || DATE.test(v), t.dobRequired),
});
type Form = z.infer<typeof baseSchema>;

const local = (mobile: string | null) => (mobile ?? '').replace(/^\+91/, '');

/** Register (no driver yet) or edit a driver's details. */
export function DriverDetailsForm({
  driver,
  submitLabel,
  onSaved,
  onCancel,
}: {
  driver: Driver | null;
  submitLabel: string;
  onSaved: (driver: Driver) => void;
  onCancel?: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  // On edit, only the owner and the current manager may change the masked fields (N17).
  const showMasked = driver === null || driver.can_reveal;
  const form = useForm<Form>({
    resolver: zodResolver(driver ? editSchema : baseSchema),
    defaultValues: {
      full_name: driver?.full_name ?? '',
      mobile: local(driver?.mobile ?? null),
      alt_mobile: local(driver?.alt_mobile ?? null),
      address: '',
      date_of_birth: '',
      emergency_name: driver?.emergency_name ?? '',
      emergency_mobile: local(driver?.emergency_mobile ?? null),
      payment_rhythm: driver?.payment_rhythm ?? 'daily',
    },
  });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    const input: DriverInput = {
      full_name: values.full_name,
      mobile: values.mobile,
      alt_mobile: values.alt_mobile || null,
      address: values.address.trim() || null,
      date_of_birth: values.date_of_birth || null,
      emergency_name: values.emergency_name || null,
      emergency_mobile: values.emergency_mobile || null,
      payment_rhythm: values.payment_rhythm,
    };
    try {
      if (driver) {
        // Never send the masked fields when blank (keep) or when this user may not change them.
        const { address, date_of_birth, ...rest } = input;
        const changes: Partial<DriverInput> = { ...rest };
        if (showMasked && address) changes.address = address;
        if (showMasked && date_of_birth) changes.date_of_birth = date_of_birth;
        onSaved(await updateDriver(driver.id, changes));
      } else {
        onSaved(await createDriver(input));
      }
    } catch (e) {
      setError(errorMessage(e));
    }
  });

  return (
    <form noValidate onSubmit={onSubmit} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {error && (
        <div className="sm:col-span-2">
          <Alert>{error}</Alert>
        </div>
      )}
      <Input
        label={t.fullName}
        autoComplete="off"
        error={errors.full_name?.message}
        {...form.register('full_name')}
      />
      <Input
        label={t.mobile}
        inputMode="tel"
        error={errors.mobile?.message}
        {...form.register('mobile')}
      />
      <Input
        label={t.altMobile}
        inputMode="tel"
        error={errors.alt_mobile?.message}
        {...form.register('alt_mobile')}
      />
      {showMasked ? (
        <>
          <Input
            label={t.dateOfBirth}
            type="date"
            hint={driver ? t.leaveBlank : undefined}
            error={errors.date_of_birth?.message}
            {...form.register('date_of_birth')}
          />
          <div className="sm:col-span-2">
            <Input
              label={t.address}
              autoComplete="off"
              hint={driver ? t.leaveBlank : undefined}
              error={errors.address?.message}
              {...form.register('address')}
            />
          </div>
        </>
      ) : (
        <p className="text-xs text-slate-600 sm:col-span-2">{t.maskedEditOwnerOnly}</p>
      )}
      <Input
        label={t.emergencyName}
        error={errors.emergency_name?.message}
        {...form.register('emergency_name')}
      />
      <Input
        label={t.emergencyMobile}
        inputMode="tel"
        error={errors.emergency_mobile?.message}
        {...form.register('emergency_mobile')}
      />
      <Select
        label={t.paymentRhythm}
        options={[
          { value: 'daily', label: t.daily },
          { value: 'weekly', label: t.weekly },
        ]}
        {...form.register('payment_rhythm')}
      />
      <div className="flex justify-end gap-2 sm:col-span-2">
        {onCancel && (
          <Button variant="secondary" onClick={onCancel}>
            {t.cancel}
          </Button>
        )}
        <Button type="submit" loading={isSubmitting}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
