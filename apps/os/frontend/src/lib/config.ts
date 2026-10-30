/* Where the database is. Both values come from the .env file at the top of the repo (or the
 * Cloudflare Pages build settings) when the app is built: SUPABASE_URL and
 * SUPABASE_PUBLISHABLE_KEY. See vite.config.ts.
 *
 * The publishable key is made to sit in a browser: every table is team-only, so the key
 * alone reads nothing. The secret key must never go here or anywhere in src/. */
export const CONFIG = {
  SUPABASE_URL: __SUPABASE_URL__.replace(/\/+$/, ''),
  SUPABASE_PUBLISHABLE_KEY: __SUPABASE_PUBLISHABLE_KEY__,
} as const;

/** False when the app was built without the two values above. */
export const CONNECTED = !!(CONFIG.SUPABASE_URL && CONFIG.SUPABASE_PUBLISHABLE_KEY);
