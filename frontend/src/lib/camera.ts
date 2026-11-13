/**
 * Phone capture (Week 3 decision D38).
 *
 * The main way to take a photo is `<input type="file" accept="image/*" capture="environment">`,
 * which opens the phone's camera app and works even over plain http. The live in-page camera
 * (getUserMedia) only works in a secure context (https, including the LAN dev server started by
 * scripts\dev.ps1 -Lan, or localhost), so it is offered only there and hidden otherwise.
 */
export function canUseLiveCamera(win: Window = window): boolean {
  return (
    win.isSecureContext === true && typeof win.navigator.mediaDevices?.getUserMedia === 'function'
  );
}
