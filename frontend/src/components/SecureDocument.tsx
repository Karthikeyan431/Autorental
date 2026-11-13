import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { fetchDocumentBlob } from '../features/drivers/api';
import { strings } from '../lib/strings';
import { Button } from './ui/Button';

const d = strings.documents;

/**
 * Shows a document fetched with the access token and kept only in memory. There is never a
 * public URL. Every fetch is logged by
 * the server. PDFs are never shown inline: they are offered as a download.
 */
export function SecureDocument({
  documentId,
  mimeType,
  label,
  className = '',
}: {
  documentId: number;
  mimeType: string;
  label: string;
  className?: string;
}) {
  if (mimeType === 'application/pdf') {
    return <PdfDownload documentId={documentId} label={label} />;
  }
  return <SecureImage documentId={documentId} label={label} className={className} />;
}

export function SecureImage({
  documentId,
  label,
  className = '',
}: {
  documentId: number;
  label: string;
  className?: string;
}) {
  // Kept in memory as a data URL (never a public URL). Each fetch is logged by the server.
  const query = useQuery({
    queryKey: ['document', documentId],
    queryFn: async () => blobToDataUrl(await fetchDocumentBlob(documentId)),
    staleTime: Infinity,
    gcTime: 60_000,
  });
  const url = query.data ?? null;

  if (query.isError) return <p className="text-sm text-red-700">{d.failed}</p>;
  if (!url) return <p className="text-sm text-slate-500">{d.loading}</p>;
  return (
    <img src={url} alt={label} className={`rounded-md border border-slate-200 ${className}`} />
  );
}

function PdfDownload({ documentId, label }: { documentId: number; label: string }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const download = async () => {
    setBusy(true);
    setFailed(false);
    try {
      const blob = await fetchDocumentBlob(documentId);
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = `${label.replace(/\s+/g, '-').toLowerCase()}-${documentId}.pdf`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col items-start gap-1">
      <Button variant="secondary" loading={busy} onClick={download}>
        {d.downloadPdf}: {label}
      </Button>
      {failed && <p className="text-sm text-red-700">{d.failed}</p>}
    </div>
  );
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error('read failed'));
    reader.readAsDataURL(blob);
  });
}
