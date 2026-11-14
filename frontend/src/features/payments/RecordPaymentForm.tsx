import { useQuery } from '@tanstack/react-query';
import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';

import { CaptureInput } from '../../components/CaptureInput';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { useToast } from '../../components/ui/useToast';
import { newRequestId } from '../../lib/api';
import { businessToday } from '../../lib/dates';
import { errorMessage } from '../../lib/errors';
import { parseRupeesToPaise } from '../../lib/money';
import { strings } from '../../lib/strings';
import { listDrivers } from '../drivers/api';
import { recordPayment, type PaymentMethod, type PaymentPurpose } from './api';

const r = strings.payments.record;

/**
 * Staff record a cash or UPI payment with a proof photo (D57 decisions 1 and 3). Any staff
 * member with `payments.record` may record for any driver. The idempotency key is made once per
 * form, so a double tap records one payment.
 */
export function RecordPaymentForm({ initialDriverId }: { initialDriverId: string | null }) {
  const toast = useToast();
  const navigate = useNavigate();
  const idempotencyKey = useMemo(() => newRequestId(), []);
  const [search, setSearch] = useState('');
  const [driverId, setDriverId] = useState(initialDriverId ?? '');
  const [amount, setAmount] = useState('');
  const [method, setMethod] = useState<PaymentMethod>('cash');
  const [purpose, setPurpose] = useState<PaymentPurpose>('rent');
  const [reference, setReference] = useState('');
  const [receivedOn, setReceivedOn] = useState(businessToday());
  const [proof, setProof] = useState<{ file: Blob; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const drivers = useQuery({
    queryKey: ['drivers', 'payment-picker', search],
    queryFn: () => listDrivers({ page: 1, search, status: '', managedBy: '', kyc: '' }),
  });
  const options = [
    { value: '', label: r.chooseDriver },
    ...(drivers.data?.items ?? []).map((d) => ({
      value: String(d.id),
      label: `${d.full_name} (${d.code})`,
    })),
  ];
  if (initialDriverId && !options.some((o) => o.value === initialDriverId)) {
    options.push({ value: initialDriverId, label: `#${initialDriverId}` });
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const paise = parseRupeesToPaise(amount);
    if (!driverId) return setError(r.chooseDriver);
    if (paise === null || paise <= 0) return setError(r.amountInvalid);
    if (method === 'upi' && !reference.trim()) return setError(r.referenceRequired);
    if (!proof) return setError(r.proofRequired);
    setBusy(true);
    setError(null);
    try {
      const payment = await recordPayment(
        {
          driver_id: Number(driverId),
          amount_paise: paise,
          method,
          purpose,
          reference,
          received_on: receivedOn,
          idempotency_key: idempotencyKey,
        },
        proof.file,
        proof.name,
      );
      toast.show({ message: r.saved, tone: 'success' });
      void navigate(`/payments/${payment.id}`);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="flex max-w-xl flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4"
      aria-label={r.title}
    >
      <p className="text-sm text-slate-600">{r.help}</p>
      {error && <Alert>{error}</Alert>}
      <Input
        label={r.driverHint}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <Select
        label={r.driver}
        value={driverId}
        options={options}
        onChange={(event) => setDriverId(event.target.value)}
      />
      <Input
        label={r.amount}
        inputMode="decimal"
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
      />
      <Select
        label={r.method}
        value={method}
        options={(['cash', 'upi'] as const).map((value) => ({
          value,
          label: r.methods[value] ?? value,
        }))}
        onChange={(event) => setMethod(event.target.value as PaymentMethod)}
      />
      <Select
        label={r.purpose}
        value={purpose}
        options={(['rent', 'advance_deposit'] as const).map((value) => ({
          value,
          label: r.purposes[value] ?? value,
        }))}
        onChange={(event) => setPurpose(event.target.value as PaymentPurpose)}
      />
      {method === 'upi' && (
        <Input
          label={r.reference}
          hint={r.referenceHint}
          value={reference}
          onChange={(event) => setReference(event.target.value)}
        />
      )}
      <Input
        label={r.receivedOn}
        type="date"
        max={businessToday()}
        value={receivedOn}
        onChange={(event) => setReceivedOn(event.target.value)}
      />
      <CaptureInput
        label={r.proof}
        onFile={(file, name) => setProof({ file, name })}
        done={proof !== null}
        hint={proof ? r.proofAdded : undefined}
      />
      <div>
        <Button type="submit" loading={busy}>
          {r.save}
        </Button>
      </div>
    </form>
  );
}
