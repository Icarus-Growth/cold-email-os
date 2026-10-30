import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/* The two values the browser needs, read from the .env file at the top of the repo, or from
 * the build settings on Cloudflare Pages (those win). Only these two reach the browser:
 * the secret key is never read here. */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '../../..');

export default defineConfig(({ mode }) => {
  const file = loadEnv(mode, REPO, 'SUPABASE_');
  const url = process.env.SUPABASE_URL || file.SUPABASE_URL || '';
  const key = process.env.SUPABASE_PUBLISHABLE_KEY || file.SUPABASE_PUBLISHABLE_KEY || '';
  if (/^sb_secret_/.test(key) || /service_role/.test(Buffer.from(key.split('.')[1] || '', 'base64').toString())) {
    throw new Error('SUPABASE_PUBLISHABLE_KEY holds the SECRET key. Put the publishable key there instead. The secret key must never reach a browser.');
  }
  return {
    plugins: [react(), tailwindcss()],
    // Absolute paths, so a deep link such as /board/tasks/<id> still finds the app's files.
    base: '/',
    define: {
      __SUPABASE_URL__: JSON.stringify(url),
      __SUPABASE_PUBLISHABLE_KEY__: JSON.stringify(key),
    },
    // apps/os, so the dev server may read ../automations/alert_rules.json (My Work's who-acts-next).
    server: { port: 5173, host: '127.0.0.1', fs: { allow: [path.resolve(HERE, '..')] } },
    // The copy editor's part (Tiptap + Markdown, about 570 kB) loads only when a document opens.
    build: { outDir: 'dist', emptyOutDir: true, sourcemap: false, chunkSizeWarningLimit: 650 },
  };
});
