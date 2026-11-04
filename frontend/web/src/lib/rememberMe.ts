// "Remember me" for the web app (1C). The tokens live in localStorage, shared by
// every tab (see tokens.ts), so an unticked box can't simply move them to
// sessionStorage. Instead the sign-in marks itself as "this browser session
// only" and drops a session cookie (no Expires, gone when the browser closes).
// On the next boot, the mark without the cookie means the browser was closed:
// the session ends, as the identity's session-only refresh cookie does.
const SESSION_ONLY_KEY = "tara.sessionOnly";
const BROWSER_COOKIE = "tara_browser_session";

function hasBrowserCookie(): boolean {
  return document.cookie.split(";").some((part) => part.trim() === `${BROWSER_COOKIE}=1`);
}

function setBrowserCookie(on: boolean) {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = on
    ? `${BROWSER_COOKIE}=1; Path=/; SameSite=Strict${secure}`
    : `${BROWSER_COOKIE}=; Path=/; Max-Age=0; SameSite=Strict${secure}`;
}

/** Record the choice made at sign-in. */
export function rememberSignIn(remember: boolean) {
  try {
    if (remember) localStorage.removeItem(SESSION_ONLY_KEY);
    else localStorage.setItem(SESSION_ONLY_KEY, "1");
  } catch {
    // Storage blocked: tokens can't be kept either, nothing to remember.
  }
  setBrowserCookie(!remember);
}

/** True when a session-only sign-in outlived its browser session. */
export function browserSessionEnded(): boolean {
  try {
    return localStorage.getItem(SESSION_ONLY_KEY) === "1" && !hasBrowserCookie();
  } catch {
    return false;
  }
}

/** Forget the choice (sign-out, or the session ended). */
export function forgetSignIn() {
  try {
    localStorage.removeItem(SESSION_ONLY_KEY);
  } catch {
    // Nothing stored.
  }
  setBrowserCookie(false);
}
