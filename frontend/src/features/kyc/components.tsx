import { zodResolver } from '@hookform/resolvers/zod';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { CaptureInput } from '../../components/CaptureInput';
import { MaskedValue } from '../../components/MaskedValue';
import { SecureDocument } from '../../components/SecureDocument';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { useToast } from '../../components/ui/useToast';
import { containsAadhaarLike, NO_FULL_NUMBER_MESSAGE } from '../../lib/aadhaar';
import { errorMessage } from '../../lib/errors';
import { formatDate, formatDateTime } from '../../lib/format';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import type { KycStatus } from '../drivers/api';
import {
  decideAttempt,
  fetchEligibility,
  reopenAttempt,
  saveIdentity,
  saveLicence,
  startAttempt,
  submitAttempt,
  uploadAttemptDocument,
  type Attempt,
  type CheckType,
  type Decision,
  type IdDocumentType,
} from './api';

const k = strings.kyc;

const noFullNumber = (schema: z.ZodString) =>
  schema.refine((value) => !containsAadhaarLike(value), NO_FULL_NUMBER_MESSAGE);

// --- Status ------------------------------------------------------------------------------------------

const STATUS_TONE: Record<string, string> = {
  approved: 'bg-teal-50 text-teal-900 border-teal-200',
  rejected: 'bg-red-50 text-red-900 border-red-200',
  expired: 'bg-red-50 text-red-900 border-red-200',
  resubmission_required: 'bg-amber-50 text-amber-900 border-amber-200',
  submitted: 'bg-sky-50 text-sky-900 border-sky-200',
  under_review: 'bg-sky-50 text-sky-900 border-sky-200',
};

export function StatusBadge({ status }: { status: KycStatus | null }) {
  const label = status ? (k.statusLabels[status] ?? status) : k.notStarted;
  const tone = (status && STATUS_TONE[status]) ?? 'bg-slate-50 text-slate-700 border-slate-200';
  return (
    <span className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${tone}`}>
      {label}
    </span>
  );
}

// --- Documents -------------------------------------------------------------------------------------

export function AttemptDocuments({
  attempt,
  canView = true,
}: {
  attempt: Attempt;
  /** Owner or current manager only (D46): the images show masked values in full. */
  canView?: boolean;
}) {
  if (attempt.documents.length === 0) {
    return <p className="text-sm text-slate-600">{k.noDocuments}</p>;
  }
  if (!canView) {
    return <p className="text-sm text-slate-600">{k.documentsManagerOnly}</p>;
  }
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {attempt.documents.map((document) => {
        const label = strings.documents.labels[document.doc_type] ?? document.doc_type;
        return (
          <li key={document.id} className="flex flex-col gap-1">
            <p className="text-xs font-medium text-slate-700">{label}</p>
            <SecureDocument
              documentId={document.id}
              mimeType={document.mime_type}
              label={label}
              className="max-h-80 w-full object-contain"
            />
          </li>
        );
      })}
    </ul>
  );
}

function DetailRow({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex justify-between gap-3 border-b border-slate-100 py-1 text-sm">
      <dt className="text-slate-600">{label}</dt>
      <dd className="text-right text-slate-900">{value || '—'}</dd>
    </div>
  );
}

/** Details of one attempt. Masked values show "Show" for the owner and current manager (D45). */
export function AttemptDetails({
  attempt,
  canReveal = false,
}: {
  attempt: Attempt;
  canReveal?: boolean;
}) {
  const idd = attempt.identity_details;
  const lic = attempt.licence_details;
  // An older attempt is revealed by id; the current one by field alone.
  const attemptId = attempt.is_current ? undefined : attempt.id;
  const masked = (fields: string[], field: string) => fields.includes(field);
  return (
    <dl>
      {idd && (
        <>
          <DetailRow label={k.documentType} value={k.idTypes[idd.document_type]} />
          <DetailRow label={k.idLast4} value={idd.id_last4} />
          <DetailRow label={k.nameOnDocument} value={idd.name_on_document} />
          {masked(idd.masked_fields, 'id_dob_or_yob') && (
            <MaskedValue
              driverId={attempt.driver_id}
              field="id_dob_or_yob"
              label={k.dobOrYob}
              canReveal={canReveal}
              attemptId={attemptId}
            />
          )}
          {masked(idd.masked_fields, 'id_gender') && (
            <MaskedValue
              driverId={attempt.driver_id}
              field="id_gender"
              label={k.gender}
              canReveal={canReveal}
              attemptId={attemptId}
            />
          )}
        </>
      )}
      {lic && (
        <>
          <MaskedValue
            driverId={attempt.driver_id}
            field="licence_number"
            label={k.licenceNumber}
            canReveal={canReveal}
            attemptId={attemptId}
            masked={lic.licence_number_masked}
          />
          <DetailRow label={k.nameOnLicence} value={lic.name_on_licence} />
          {masked(lic.masked_fields, 'licence_date_of_birth') && (
            <MaskedValue
              driverId={attempt.driver_id}
              field="licence_date_of_birth"
              label={k.licenceDob}
              canReveal={canReveal}
              attemptId={attemptId}
              format={formatDate}
            />
          )}
          <DetailRow
            label={k.validNonTransport}
            value={lic.valid_until_non_transport ? formatDate(lic.valid_until_non_transport) : null}
          />
          <DetailRow
            label={k.validTransport}
            value={lic.valid_until_transport ? formatDate(lic.valid_until_transport) : null}
          />
          <DetailRow label={k.vehicleClasses} value={lic.vehicle_classes.join(', ')} />
          <DetailRow label={k.issuingAuthority} value={lic.issuing_authority} />
        </>
      )}
    </dl>
  );
}

export function AttemptHistory({ attempt }: { attempt: Attempt }) {
  return (
    <ol className="flex flex-col gap-1 text-sm">
      {attempt.events.map((event) => (
        <li key={event.id} className="text-slate-700">
          <span className="text-slate-500">{formatDateTime(event.at)}</span> ·{' '}
          {k.statusLabels[event.to_status] ?? event.to_status}
          {event.actor ? ` · ${event.actor.name}` : ''}
          {event.reason ? ` · ${event.reason}` : ''}
        </li>
      ))}
    </ol>
  );
}

// --- Capture: identity and licence ------------------------------------------------------------------

const identitySchema = z.object({
  document_type: z.enum(['masked_aadhaar', 'voter_id', 'passport']),
  id_last4: z.string().regex(/^\d{4}$/, k.idLast4Invalid),
  name_on_document: noFullNumber(z.string().trim().min(1, strings.drivers.nameRequired).max(200)),
  // Masked (D45): not pre-filled; blank keeps the saved value. The first save needs it.
  dob_or_yob: z.string().regex(/^(\d{4}(-\d{2}-\d{2})?)?$/, k.dobOrYobInvalid),
});
type IdentityForm = z.infer<typeof identitySchema>;

const optionalDate = z.string().regex(/^(\d{4}-\d{2}-\d{2})?$/);

const licenceSchema = z
  .object({
    // Masked (D45): not pre-filled; blank keeps the saved number. The first save needs it.
    licence_number: noFullNumber(z.string().trim().max(40)),
    name_on_licence: noFullNumber(z.string().trim().min(1, strings.drivers.nameRequired).max(200)),
    date_of_birth: optionalDate,
    issue_date: optionalDate,
    valid_until_non_transport: optionalDate,
    valid_until_transport: optionalDate,
    vehicle_classes: noFullNumber(z.string().trim().min(1, k.vehicleClassesRequired).max(300)),
    issuing_authority: noFullNumber(z.string().trim().max(200)),
  })
  .refine((v) => v.valid_until_non_transport || v.valid_until_transport, {
    message: k.validityRequired,
    path: ['valid_until_non_transport'],
  });
type LicenceForm = z.infer<typeof licenceSchema>;

const DOC_TYPES: Record<CheckType, { key: string; label: string }[]> = {
  identity: [
    { key: 'id_front', label: k.idFront },
    { key: 'id_back', label: k.idBack },
  ],
  licence: [
    { key: 'licence_front', label: k.licenceFront },
    { key: 'licence_back', label: k.licenceBack },
  ],
};

/**
 * Capture one check by manual review: details, uploads and submit. Starts a draft attempt the
 * first time something is saved, so every step is kept on the server (a draft per step).
 */
export function KycCheckEditor({
  driverId,
  checkType,
  attempt,
  acceptedIdTypes,
  defaultName,
  onChanged,
}: {
  driverId: number;
  checkType: CheckType;
  attempt: Attempt | null;
  acceptedIdTypes: IdDocumentType[];
  defaultName: string;
  onChanged: () => Promise<unknown> | void;
}) {
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const isDraft = attempt?.status === 'draft';
  const canStartNew =
    attempt === null || attempt.status === 'resubmission_required' || attempt.status === 'expired';

  const ensureDraft = async (): Promise<number> => {
    if (attempt && isDraft) return attempt.id;
    const created = await startAttempt(driverId, checkType);
    return created.id;
  };

  const upload = async (docType: string, file: Blob, name: string) => {
    setError(null);
    setUploading(docType);
    try {
      const attemptId = await ensureDraft();
      await uploadAttemptDocument(attemptId, docType, file, name);
      await onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setUploading(null);
    }
  };

  const submit = async () => {
    if (!attempt) return;
    setError(null);
    setSubmitting(true);
    try {
      await submitAttempt(attempt.id);
      toast.show({ message: k.submitted_, tone: 'success' });
      await onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSubmitting(false);
    }
  };

  if (attempt && !isDraft && !canStartNew) {
    // Submitted, under review or decided: show what was sent.
    return (
      <div className="flex flex-col gap-3">
        <p className="flex items-center gap-2 text-sm">
          {strings.drivers.attempt(attempt.attempt_no)} <StatusBadge status={attempt.status} />
        </p>
        {/* The editor is shown only to the owner or the current manager (D46). */}
        <AttemptDetails attempt={attempt} canReveal />
        <AttemptDocuments attempt={attempt} />
      </div>
    );
  }

  const uploadedTypes = new Set(attempt && isDraft ? attempt.documents.map((d) => d.doc_type) : []);
  return (
    <div className="flex flex-col gap-4">
      {attempt && !isDraft && (
        <Alert tone="info">
          {strings.drivers.attempt(attempt.attempt_no)}: {k.statusLabels[attempt.status]}
          {attempt.decision_reason ? ` — ${attempt.decision_reason}` : ''}
        </Alert>
      )}
      {error && <Alert>{error}</Alert>}
      {checkType === 'identity' ? (
        <IdentityFormFields
          attempt={isDraft ? attempt : null}
          acceptedIdTypes={acceptedIdTypes}
          defaultName={defaultName}
          onSave={async (values) => {
            const attemptId = await ensureDraft();
            await saveIdentity(attemptId, values);
            await onChanged();
          }}
        />
      ) : (
        <LicenceFormFields
          attempt={isDraft ? attempt : null}
          defaultName={defaultName}
          onSave={async (values) => {
            const attemptId = await ensureDraft();
            await saveLicence(attemptId, values);
            await onChanged();
          }}
        />
      )}
      {checkType === 'identity' && <Alert tone="info">{k.maskedWarning}</Alert>}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {DOC_TYPES[checkType].map((doc) => (
          <CaptureInput
            key={doc.key}
            label={doc.label}
            allowPdf
            hint={strings.capture.documentHint}
            busy={uploading === doc.key}
            done={uploadedTypes.has(doc.key)}
            onFile={(file, name) => void upload(doc.key, file, name)}
          />
        ))}
      </div>
      {attempt && isDraft && <AttemptDocuments attempt={attempt} />}
      {attempt && isDraft && (
        <div className="flex justify-end">
          <Button onClick={submit} loading={submitting}>
            {k.submit}
          </Button>
        </div>
      )}
    </div>
  );
}

function IdentityFormFields({
  attempt,
  acceptedIdTypes,
  defaultName,
  onSave,
}: {
  attempt: Attempt | null;
  acceptedIdTypes: IdDocumentType[];
  defaultName: string;
  onSave: (values: Parameters<typeof saveIdentity>[1]) => Promise<void>;
}) {
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const saved = attempt?.identity_details;
  const form = useForm<IdentityForm>({
    resolver: zodResolver(identitySchema),
    defaultValues: {
      document_type: saved?.document_type ?? acceptedIdTypes[0] ?? 'masked_aadhaar',
      id_last4: saved?.id_last4 ?? '',
      name_on_document: saved?.name_on_document ?? defaultName,
      dob_or_yob: '',
    },
  });
  const { errors, isSubmitting } = form.formState;
  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    if (!saved && !values.dob_or_yob) {
      form.setError('dob_or_yob', { message: k.dobOrYobRequired });
      return;
    }
    try {
      await onSave({ ...values, dob_or_yob: values.dob_or_yob || null });
      toast.show({ message: k.detailsSaved, tone: 'success' });
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
      <Select
        label={k.documentType}
        options={acceptedIdTypes.map((value) => ({ value, label: k.idTypes[value] ?? value }))}
        {...form.register('document_type')}
      />
      <Input
        label={k.idLast4}
        hint={k.idLast4Hint}
        inputMode="numeric"
        maxLength={4}
        autoComplete="off"
        error={errors.id_last4?.message}
        {...form.register('id_last4')}
      />
      <Input
        label={k.nameOnDocument}
        error={errors.name_on_document?.message}
        {...form.register('name_on_document')}
      />
      <Input
        label={k.dobOrYob}
        inputMode="numeric"
        autoComplete="off"
        hint={saved ? k.savedKeepBlank : undefined}
        error={errors.dob_or_yob?.message}
        {...form.register('dob_or_yob')}
      />
      <div className="flex justify-end sm:col-span-2">
        <Button type="submit" variant="secondary" loading={isSubmitting}>
          {k.saveDetails}
        </Button>
      </div>
    </form>
  );
}

function LicenceFormFields({
  attempt,
  defaultName,
  onSave,
}: {
  attempt: Attempt | null;
  defaultName: string;
  onSave: (values: Parameters<typeof saveLicence>[1]) => Promise<void>;
}) {
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const saved = attempt?.licence_details;
  const form = useForm<LicenceForm>({
    resolver: zodResolver(licenceSchema),
    defaultValues: {
      licence_number: '',
      name_on_licence: saved?.name_on_licence ?? defaultName,
      date_of_birth: '',
      issue_date: saved?.issue_date ?? '',
      valid_until_non_transport: saved?.valid_until_non_transport ?? '',
      valid_until_transport: saved?.valid_until_transport ?? '',
      vehicle_classes: saved?.vehicle_classes.join(', ') ?? '',
      issuing_authority: saved?.issuing_authority ?? '',
    },
  });
  const { errors, isSubmitting } = form.formState;
  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    if (!saved && values.licence_number.length < 6) {
      form.setError('licence_number', { message: k.licenceNumberRequired });
      return;
    }
    try {
      await onSave({
        licence_number: values.licence_number || null,
        name_on_licence: values.name_on_licence,
        date_of_birth: values.date_of_birth || null,
        issue_date: values.issue_date || null,
        valid_until_non_transport: values.valid_until_non_transport || null,
        valid_until_transport: values.valid_until_transport || null,
        vehicle_classes: values.vehicle_classes
          .split(',')
          .map((c) => c.trim())
          .filter(Boolean),
        issuing_authority: values.issuing_authority.trim() || null,
      });
      toast.show({ message: k.detailsSaved, tone: 'success' });
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
        label={k.licenceNumber}
        hint={saved ? `${saved.licence_number_masked} · ${k.savedKeepBlank}` : undefined}
        autoComplete="off"
        autoCapitalize="characters"
        error={errors.licence_number?.message}
        {...form.register('licence_number')}
      />
      <Input
        label={k.nameOnLicence}
        error={errors.name_on_licence?.message}
        {...form.register('name_on_licence')}
      />
      <Input
        label={k.licenceDob}
        type="date"
        hint={saved?.masked_fields.includes('licence_date_of_birth') ? k.savedKeepBlank : undefined}
        {...form.register('date_of_birth')}
      />
      <Input label={k.issueDate} type="date" {...form.register('issue_date')} />
      <Input
        label={k.validNonTransport}
        type="date"
        error={errors.valid_until_non_transport?.message}
        {...form.register('valid_until_non_transport')}
      />
      <Input label={k.validTransport} type="date" {...form.register('valid_until_transport')} />
      <Input
        label={k.vehicleClasses}
        error={errors.vehicle_classes?.message}
        {...form.register('vehicle_classes')}
      />
      <Input
        label={k.issuingAuthority}
        error={errors.issuing_authority?.message}
        {...form.register('issuing_authority')}
      />
      <div className="flex justify-end sm:col-span-2">
        <Button type="submit" variant="secondary" loading={isSubmitting}>
          {k.saveDetails}
        </Button>
      </div>
    </form>
  );
}

// --- Decision (rule 12, answer 2) ----------------------------------------------------------------------

export function DecisionPanel({
  attempt,
  canDecide,
  onChanged,
}: {
  attempt: Attempt;
  /** The owner or the driver's current manager (D46); kyc.decide is checked as well. */
  canDecide: boolean;
  onChanged: () => Promise<unknown> | void;
}) {
  const { user } = useAuth();
  const toast = useToast();
  const [ticks, setTicks] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Decision | null>(null);
  const [reopenOpen, setReopenOpen] = useState(false);

  const decidable = attempt.is_current && ['submitted', 'under_review'].includes(attempt.status);
  const reopenable = attempt.is_current && ['approved', 'rejected'].includes(attempt.status);
  const allRequired = attempt.checklist.every((item) => !item.required || ticks[item.key]);

  const decide = async (decision: Decision) => {
    setError(null);
    if (decision !== 'approve' && !reason.trim()) {
      setError(k.reasonRequired);
      return;
    }
    if (decision === 'reject' || decision === 'resubmit') {
      if (containsAadhaarLike(reason)) {
        setError(NO_FULL_NUMBER_MESSAGE);
        return;
      }
    }
    setBusy(decision);
    try {
      await decideAttempt(attempt.id, decision, ticks, reason.trim() || null);
      toast.show({ message: k.decided, tone: 'success' });
      await onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  if (!decidable) {
    return (
      <div className="flex flex-col gap-2 text-sm">
        <p className="flex items-center gap-2">
          <StatusBadge status={attempt.status} />
          {attempt.reviewed_by && attempt.reviewed_at && (
            <span className="text-slate-600">
              {k.decidedBy(attempt.reviewed_by.name, formatDateTime(attempt.reviewed_at))}
            </span>
          )}
        </p>
        {attempt.decision_reason && <p className="text-slate-700">{attempt.decision_reason}</p>}
        {reopenable && can(user, 'kyc.reopen') && (
          <div>
            <Button variant="secondary" onClick={() => setReopenOpen(true)}>
              {k.reopen}
            </Button>
          </div>
        )}
        {reopenOpen && (
          <ReopenDialog
            attemptId={attempt.id}
            onClose={() => setReopenOpen(false)}
            onDone={async () => {
              setReopenOpen(false);
              toast.show({ message: k.reopened, tone: 'success' });
              await onChanged();
            }}
          />
        )}
      </div>
    );
  }

  if (!can(user, 'kyc.decide')) {
    return <StatusBadge status={attempt.status} />;
  }
  if (!canDecide) {
    return (
      <div className="flex flex-col gap-1 text-sm">
        <StatusBadge status={attempt.status} />
        <p className="text-slate-600">{k.decideManagerOnly}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-semibold text-slate-900">{k.checklist}</legend>
        {attempt.checklist.map((item) => (
          <label key={item.key} className="flex items-start gap-2 text-sm text-slate-800">
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-teal-700"
              checked={ticks[item.key] ?? false}
              onChange={(event) => setTicks({ ...ticks, [item.key]: event.target.checked })}
            />
            <span>
              {item.label}
              {!item.required && <span className="text-slate-500"> {k.optional}</span>}
            </span>
          </label>
        ))}
      </fieldset>
      <Input
        label={k.decisionReason}
        value={reason}
        maxLength={500}
        onChange={(event) => setReason(event.target.value)}
      />
      {error && <Alert>{error}</Alert>}
      {!allRequired && <p className="text-xs text-slate-600">{k.approveNeedsTicks}</p>}
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <Button
          disabled={!allRequired}
          loading={busy === 'approve'}
          onClick={() => decide('approve')}
        >
          {k.approve}
        </Button>
        <Button
          variant="secondary"
          loading={busy === 'resubmit'}
          onClick={() => decide('resubmit')}
        >
          {k.askAgain}
        </Button>
        <Button variant="danger" loading={busy === 'reject'} onClick={() => decide('reject')}>
          {k.reject}
        </Button>
      </div>
    </div>
  );
}

function ReopenDialog({
  attemptId,
  onClose,
  onDone,
}: {
  attemptId: number;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    if (!reason.trim()) {
      setError(k.reasonRequired);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await reopenAttempt(attemptId, reason.trim());
      await onDone();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };
  return (
    <Dialog
      open
      title={k.reopenTitle}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {strings.drivers.cancel}
          </Button>
          <Button loading={busy} onClick={run}>
            {k.reopen}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p>{k.reopenBody}</p>
        <Input
          label={strings.drivers.reason}
          value={reason}
          maxLength={500}
          onChange={(event) => setReason(event.target.value)}
        />
        {error && <Alert>{error}</Alert>}
      </div>
    </Dialog>
  );
}

// --- Eligibility -------------------------------------------------------------------------------------

export function EligibilityPanel({ driverId }: { driverId: number }) {
  const query = useQuery({
    queryKey: ['eligibility', driverId],
    queryFn: () => fetchEligibility(driverId),
  });
  if (!query.data) return null;
  const result = query.data;
  return (
    <div
      className={`rounded-lg border p-3 text-sm ${
        result.ok ? 'border-teal-200 bg-teal-50 text-teal-900' : 'border-amber-200 bg-amber-50'
      }`}
    >
      <p className="font-semibold">{strings.drivers.eligibility}</p>
      {result.ok ? (
        <p>{strings.drivers.eligible}</p>
      ) : (
        <>
          <p>{strings.drivers.notEligible}</p>
          <ul className="list-disc pl-5" data-testid="eligibility-reasons">
            {result.reasons.map((reason) => (
              <li key={reason}>{k.reasonsCodes[reason] ?? reason}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
