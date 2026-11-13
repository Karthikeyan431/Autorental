import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { useToast } from '../../components/ui/useToast';
import { containsAadhaarLike, NO_FULL_NUMBER_MESSAGE } from '../../lib/aadhaar';
import { errorMessage } from '../../lib/errors';
import { strings } from '../../lib/strings';
import {
  createVehicle,
  updateVehicle,
  type FuelType,
  type PaperState,
  type Vehicle,
  type VehicleStatus,
} from './api';

const t = strings.autos;

const TONES: Record<string, string> = {
  available: 'bg-teal-50 text-teal-900 border-teal-200',
  rented: 'bg-sky-50 text-sky-900 border-sky-200',
  maintenance: 'bg-amber-50 text-amber-900 border-amber-200',
  inactive: 'bg-slate-50 text-slate-700 border-slate-200',
  ok: 'bg-teal-50 text-teal-900 border-teal-200',
  expiring: 'bg-amber-50 text-amber-900 border-amber-200',
  expired: 'bg-red-50 text-red-900 border-red-200',
};

function Badge({ tone, label }: { tone: string; label: string }) {
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${TONES[tone] ?? ''}`}
    >
      {label}
    </span>
  );
}

export function VehicleStatusBadge({ status }: { status: VehicleStatus }) {
  return <Badge tone={status} label={t.statusLabels[status] ?? status} />;
}

export function PaperStateBadge({ state }: { state: PaperState }) {
  return <Badge tone={state} label={t.paperStates[state] ?? state} />;
}

const noFullNumber = (schema: z.ZodString) =>
  schema.refine((value) => !containsAadhaarLike(value), NO_FULL_NUMBER_MESSAGE);

const vehicleSchema = z.object({
  registration_number: z
    .string()
    .transform((v) => v.replace(/[\s-]+/g, '').toUpperCase())
    .pipe(
      z
        .string()
        .regex(/^[A-Z0-9]{4,12}$/, t.registrationInvalid)
        // A registration always has letters; an all-digit value could be an Aadhaar number.
        .refine((v) => !/^\d+$/.test(v), t.registrationInvalid),
    ),
  make: noFullNumber(z.string().trim().min(1, t.required).max(100)),
  model: noFullNumber(z.string().trim().min(1, t.required).max(100)),
  year: z.string().regex(/^((19[89]\d)|(20\d\d)|2100)?$/, t.yearInvalid),
  fuel_type: z.enum(['', 'cng', 'lpg', 'petrol', 'diesel', 'electric']),
  notes: noFullNumber(z.string().trim().max(1000)),
});
type VehicleForm = z.input<typeof vehicleSchema>;
type VehicleValues = z.output<typeof vehicleSchema>;

/** Add an auto, or edit one (`vehicle`). The registration number is normalised as typed. */
export function VehicleFormDialog({
  vehicle,
  onClose,
  onSaved,
}: {
  vehicle: Vehicle | null;
  onClose: () => void;
  onSaved: (saved: Vehicle) => Promise<void> | void;
}) {
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<VehicleForm, unknown, VehicleValues>({
    resolver: zodResolver(vehicleSchema),
    defaultValues: {
      registration_number: vehicle?.registration_number ?? '',
      make: vehicle?.make ?? '',
      model: vehicle?.model ?? '',
      year: vehicle?.year ? String(vehicle.year) : '',
      fuel_type: vehicle?.fuel_type ?? '',
      notes: vehicle?.notes ?? '',
    },
  });
  const { errors, isSubmitting } = form.formState;
  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    const input = {
      registration_number: values.registration_number,
      make: values.make,
      model: values.model,
      year: values.year ? Number(values.year) : null,
      fuel_type: (values.fuel_type || null) as FuelType | null,
      notes: values.notes || null,
    };
    try {
      const saved = vehicle ? await updateVehicle(vehicle.id, input) : await createVehicle(input);
      toast.show({ message: t.saved, tone: 'success' });
      await onSaved(saved);
    } catch (e) {
      setError(errorMessage(e));
    }
  });
  return (
    <Dialog
      open
      title={vehicle ? vehicle.registration_number : t.addTitle}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t.cancel}
          </Button>
          <Button loading={isSubmitting} onClick={() => void onSubmit()}>
            {t.save}
          </Button>
        </>
      }
    >
      <form noValidate onSubmit={onSubmit} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {error && (
          <div className="sm:col-span-2">
            <Alert>{error}</Alert>
          </div>
        )}
        <Input
          label={t.registration}
          hint={t.registrationHint}
          autoCapitalize="characters"
          autoComplete="off"
          error={errors.registration_number?.message}
          {...form.register('registration_number')}
        />
        <Input label={t.make} error={errors.make?.message} {...form.register('make')} />
        <Input label={t.model} error={errors.model?.message} {...form.register('model')} />
        <Input
          label={t.year}
          inputMode="numeric"
          error={errors.year?.message}
          {...form.register('year')}
        />
        <Select
          label={t.fuel}
          options={[
            { value: '', label: '—' },
            ...(['cng', 'lpg', 'petrol', 'diesel', 'electric'] as const).map((value) => ({
              value,
              label: t.fuelTypes[value] ?? value,
            })),
          ]}
          {...form.register('fuel_type')}
        />
        <Input label={t.notes} error={errors.notes?.message} {...form.register('notes')} />
      </form>
    </Dialog>
  );
}
