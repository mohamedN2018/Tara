// Google Identity Services (the "Sign in with Google" button).
// The script is loaded only when the server reports Google sign-in as enabled,
// so a deployment without GOOGLE_CLIENT_ID never contacts Google.
// The nginx CSP allows exactly these GIS paths (script, button iframe, styles).

export const GIS_SRC = "https://accounts.google.com/gsi/client";

interface CredentialResponse {
  credential?: string;
}

interface GoogleAccountsId {
  initialize(config: {
    client_id: string;
    callback: (response: CredentialResponse) => void;
    ux_mode?: "popup" | "redirect";
    auto_select?: boolean;
    cancel_on_tap_outside?: boolean;
  }): void;
  renderButton(
    parent: HTMLElement,
    options: {
      type?: "standard" | "icon";
      theme?: "outline" | "filled_blue" | "filled_black";
      size?: "large" | "medium" | "small";
      text?: "signin_with" | "signup_with" | "continue_with" | "signin";
      shape?: "rectangular" | "pill" | "circle" | "square";
      width?: number;
      locale?: string;
    },
  ): void;
  disableAutoSelect(): void;
}

declare global {
  interface Window {
    google?: { accounts?: { id?: GoogleAccountsId } };
  }
}

let loading: Promise<GoogleAccountsId> | null = null;

/** Load the GIS script once; later calls share the same promise. */
export function loadGoogleIdentity(): Promise<GoogleAccountsId> {
  const ready = window.google?.accounts?.id;
  if (ready) return Promise.resolve(ready);
  loading ??= new Promise<GoogleAccountsId>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = GIS_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => {
      const id = window.google?.accounts?.id;
      if (id) resolve(id);
      else reject(new Error("Google Identity Services did not initialise."));
    };
    script.onerror = () => reject(new Error("Could not load Google Identity Services."));
    document.head.appendChild(script);
  }).catch((error: unknown) => {
    loading = null; // allow a retry (e.g. after going back online)
    document.querySelector(`script[src="${GIS_SRC}"]`)?.remove();
    throw error;
  });
  return loading;
}

export type GoogleButtonText = "signin_with" | "signup_with" | "continue_with";

/**
 * Render Google's button into `parent`. `onCredential` receives the ID token
 * (a JWT the identity service verifies; it is never stored in the browser).
 */
export async function renderGoogleButton(
  parent: HTMLElement,
  opts: {
    clientId: string;
    locale: string;
    text: GoogleButtonText;
    dark: boolean;
    width?: number;
    onCredential: (credential: string) => void;
  },
): Promise<void> {
  const id = await loadGoogleIdentity();
  id.initialize({
    client_id: opts.clientId,
    callback: (response) => {
      if (response.credential) opts.onCredential(response.credential);
    },
    ux_mode: "popup",
    auto_select: false,
    cancel_on_tap_outside: true,
  });
  parent.replaceChildren();
  id.renderButton(parent, {
    type: "standard",
    theme: opts.dark ? "filled_black" : "outline",
    size: "large",
    text: opts.text,
    shape: "pill",
    width: opts.width,
    locale: opts.locale,
  });
}

/** Test hook: forget a loaded or failed script. */
export function resetGoogleIdentityForTests(): void {
  loading = null;
}
