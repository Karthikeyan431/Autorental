import { useEffect, useId, useRef, useState, type ChangeEvent } from 'react';

import { canUseLiveCamera } from '../lib/camera';
import { strings } from '../lib/strings';
import { Button } from './ui/Button';
import { Dialog } from './ui/Dialog';

const c = strings.capture;

/**
 * Photo or document capture for phones (D38).
 *
 * "Take photo" is a file input with capture="environment": on a phone it opens the camera app,
 * and it works over plain http (the LAN dev server). "Choose file" picks an existing file. The
 * live in-page camera (getUserMedia) is offered only in a secure context; otherwise it is hidden.
 */
export function CaptureInput({
  label,
  onFile,
  allowPdf = false,
  busy = false,
  done = false,
  hint,
}: {
  label: string;
  onFile: (file: Blob, name: string) => void;
  allowPdf?: boolean;
  busy?: boolean;
  done?: boolean;
  hint?: string;
}) {
  const id = useId();
  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [liveOpen, setLiveOpen] = useState(false);
  const live = canUseLiveCamera();

  const picked = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = ''; // the same file can be chosen again after an error
    if (file) onFile(file, file.name || 'photo.jpg');
  };

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between gap-2">
        <p id={`${id}-label`} className="text-sm font-medium text-slate-800">
          {label}
        </p>
        {done && (
          <span className="text-xs font-medium text-teal-800">✓ {strings.kyc.uploaded}</span>
        )}
      </div>
      <div className="flex flex-wrap gap-2" aria-labelledby={`${id}-label`} role="group">
        <Button
          onClick={() => cameraRef.current?.click()}
          loading={busy}
          aria-label={`${c.takePhoto}: ${label}`}
        >
          {busy ? c.uploading : c.takePhoto}
        </Button>
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
          aria-label={`${c.chooseFile}: ${label}`}
        >
          {c.chooseFile}
        </Button>
        {live && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => setLiveOpen(true)}
            aria-label={`${c.liveCamera}: ${label}`}
          >
            {c.liveCamera}
          </Button>
        )}
      </div>
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        data-testid="capture-camera"
        onChange={picked}
      />
      <input
        ref={fileRef}
        type="file"
        accept={allowPdf ? 'image/jpeg,image/png,application/pdf' : 'image/jpeg,image/png'}
        className="hidden"
        data-testid="capture-file"
        onChange={picked}
      />
      {hint && <p className="text-xs text-slate-600">{hint}</p>}
      {liveOpen && (
        <LiveCameraDialog
          onClose={() => setLiveOpen(false)}
          onCapture={(blob) => {
            setLiveOpen(false);
            onFile(blob, 'camera.jpg');
          }}
        />
      )}
    </div>
  );
}

function LiveCameraDialog({
  onClose,
  onCapture,
}: {
  onClose: () => void;
  onCapture: (blob: Blob) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: 'environment' }, audio: false })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          void videoRef.current.play();
        }
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  const capture = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d')?.drawImage(video, 0, 0);
    canvas.toBlob((blob) => blob && onCapture(blob), 'image/jpeg', 0.9);
  };

  return (
    <Dialog
      open
      title={c.cameraTitle}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {c.cancel}
          </Button>
          <Button onClick={capture} disabled={failed}>
            {c.capture}
          </Button>
        </>
      }
    >
      {failed ? (
        <p role="alert">{c.cameraFailed}</p>
      ) : (
        <video ref={videoRef} playsInline muted className="w-full rounded-md bg-slate-900" />
      )}
    </Dialog>
  );
}
