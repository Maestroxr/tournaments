# Google sign-in

The tournament login and signup pages use Google Identity Services. The backend validates Google's ID token using `google-auth`, including signature, issuer, audience and expiry. Django CSRF protection and a single-use, ten-minute session nonce protect the callback. No client secret is needed for this ID-token flow.

## Enable

1. In Google Cloud / Google Auth Platform, configure Branding, Audience and a **Web application** OAuth client. For testing, add permitted test users when required by the project's audience configuration.
2. Add the exact frontend origins to **Authorized JavaScript origins**, for example `http://localhost:5175` and `http://127.0.0.1:5175` for local development, and the real HTTPS production origin. Include the port, but no `/tournaments` path. Prefer localhost for local Google testing.
3. Put the public client ID in the backend environment: `GOOGLE_CLIENT_ID=...apps.googleusercontent.com`. Restart the backend. The frontend fetches this public configuration from the server; no separate frontend environment variable is needed.
4. Install updated backend requirements and run `python manage.py migrate` from `tournaments/` using the backend virtual environment.
5. Test a new Google account, complete username and phone, sign out, then sign in again. Test both login and signup pages and the production domain before release.

The button stays hidden when `GOOGLE_CLIENT_ID` is empty. The official Google-rendered dark button appears when enabled. A cancelled Google chooser leaves the normal form available. If CSP is set at the reverse proxy, allow Google's GIS script, frames and connections following the linked setup guide. A restrictive Cross-Origin-Opener-Policy may need `same-origin-allow-popups` for popup-based browsers.

## Account behavior

- A new Google identity completes username and phone before any user account is created. Its password is unusable.
- Google `sub`, not email, identifies returning users. Disabled users remain blocked.
- Existing email accounts are never silently linked. The user is directed to their existing password/reset flow. Explicit account linking is not included.
- Gmail and verified Workspace email addresses are accepted as verified. Other email addresses receive the site's normal verification email before the account becomes active.
- Pending signup data expires after ten minutes. Google ID tokens are neither stored nor logged.

## Validation

Run `python manage.py test frontend.test_google_auth frontend.test_accounts` and the frontend GoogleSignIn/LoginView tests. These tests mock the external provider; a real Google popup and token exchange still require a configured OAuth client.

References: [Google setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid), [server verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token), [JavaScript API](https://developers.google.com/identity/gsi/web/reference/js-reference).
