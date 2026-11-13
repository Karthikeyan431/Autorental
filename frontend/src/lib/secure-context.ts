/**
 * True only when the browser says this page is not a secure context (plain http, not
 * localhost). Browsers then remove crypto.randomUUID, crypto.subtle, navigator.locks and
 * navigator.mediaDevices, and refuse Secure cookies.
 */
export function isInsecureContext(win: Window | undefined = globalThis.window): boolean {
  return win?.isSecureContext === false;
}
