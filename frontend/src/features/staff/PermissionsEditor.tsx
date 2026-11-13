import { strings } from '../../lib/strings';
import type { PermissionInfo } from './api';

const s = strings.staff;

/** Checkboxes for every permission. Owner-only codes are shown locked and can never be ticked. */
export function PermissionsEditor({
  catalogue,
  selected,
  onChange,
}: {
  catalogue: PermissionInfo[];
  selected: string[];
  onChange: (codes: string[]) => void;
}) {
  const toggle = (code: string, on: boolean) =>
    onChange(on ? [...selected, code].sort() : selected.filter((c) => c !== code));

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 text-sm text-slate-600">{s.permissionsIntro}</legend>
      {catalogue.map((permission) => {
        const locked = !permission.grantable;
        return (
          <label
            key={permission.code}
            className={`flex items-start gap-3 rounded-md border px-3 py-2 ${
              locked ? 'border-slate-100 bg-slate-50 text-slate-500' : 'border-slate-200'
            }`}
          >
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-teal-700"
              checked={!locked && selected.includes(permission.code)}
              disabled={locked}
              onChange={(event) => toggle(permission.code, event.target.checked)}
            />
            <span className="flex flex-col">
              <span className="text-sm">{permission.label}</span>
              <span className="font-mono text-xs text-slate-500">
                {permission.code}
                {locked && ` · ${s.ownerOnly}`}
                {!locked && permission.staff_default && ` · ${s.defaultOn}`}
              </span>
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}
