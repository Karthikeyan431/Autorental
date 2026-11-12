import { useId, type InputHTMLAttributes } from 'react';

import { Field } from './Field';
import { controlClass, describedBy } from './field-utils';

export type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: string;
  error?: string;
};

export function Input({ label, hint, error, id, className = '', ...rest }: InputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  return (
    <Field id={inputId} label={label} hint={hint} error={error}>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(inputId, hint, error)}
        className={`${controlClass} ${className}`}
        {...rest}
      />
    </Field>
  );
}
