/* POST /api/team/ai  {team_id, action: 'issue' | 'revoke'}
 *   ->  {server, key, url} | {revoked: true} | {error}
 *
 * The "Connect your AI" and "Revoke" buttons on a person's page. For an Owner or Admin only
 * (see ../../_lib/team.js). The AI connector (tab 5) runs in the automations app, which holds
 * the secret that scrambles each link, so this step only checks the caller and passes the call
 * on to <OS_AUTOMATIONS_URL>/mcp/token, with the shared secret and the caller's own sign-in.
 * The automations app checks both again. Nothing is stored here, and the link is never logged.
 *
 * The automations app answers {server: <base>/mcp/, key, url: <server>s/<key>/}. The terminal
 * tools send the key in an "Authorization: Bearer" header to the server, so it stays out of
 * Modal's request log; Claude on the web takes only an address, so it gets the url. An
 * automations app from before link option 1 sends only the url: linkParts splits it.
 */
import { UUID_RE, admin, body, json, notSetUp, refuse, teamRow } from '../../_lib/team.js';

export async function onRequestPost({ request, env }) {
  const off = notSetUp(env);
  if (off) return off;
  try {
    const caller = await admin(request, env);
    if (caller instanceof Response) return caller;

    const b = await body(request);
    const id = String(b.team_id || '');
    const action = b.action === 'revoke' ? 'revoke' : b.action === 'issue' ? 'issue' : '';
    if (!UUID_RE.test(id) || !action) return refuse(400, 'Pick a person and an action first.');
    const person = await teamRow(env, 'id=eq.' + id);
    if (!person) return refuse(404, 'That person is not on the team list.');
    if (action === 'issue' && (person.status !== 'Active' || !person.can_sign_in)) {
      return refuse(409, person.full_name + ' cannot sign in, so they cannot connect an AI. Set them to Active and tick "Can sign in" first.');
    }

    const url = String(env.OS_AUTOMATIONS_URL || env.MODAL_ALERTS_URL || '').replace(/\/+$/, '');
    if (!url || !env.OS_SHARED_SECRET) {
      return refuse(409, 'The AI connector is not set up yet. Do tab 5 (the AI connector) first, then deploy the OS again.');
    }
    let res;
    try {
      res = await fetch(url + '/mcp/token', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-OS-Secret': env.OS_SHARED_SECRET,
          Authorization: request.headers.get('Authorization') || '',
        },
        body: JSON.stringify({ team_id: id, action }),
      });
    } catch (e) {
      return refuse(502, 'Could not reach the automations app. Check that it is deployed (tab 3), then try again.');
    }
    const out = await res.json().catch(() => null);
    if (!res.ok || !out) return refuse(res.ok ? 502 : res.status, (out && out.error) || 'The automations app said no (' + res.status + ').');
    if (action === 'issue') {
      const parts = out.server && out.key && out.url ? { server: String(out.server), key: String(out.key), url: String(out.url) }
        : linkParts(out.url);
      if (!parts) return refuse(502, 'The automations app sent no link. Try again.');
      return json(parts);
    }
    return json({ revoked: true });
  } catch (e) {
    return refuse(502, 'Something went wrong on the server. Try again in a minute.');
  }
}

/** <base>/mcp/s/<key>/ -> {server: <base>/mcp/, key, url: the link}, or null. */
export function linkParts(link) {
  const m = /^(https?:\/\/[^?#]+?)\/mcp\/s\/([^/?#]+)\/?$/.exec(String(link || ''));
  return m ? { server: m[1] + '/mcp/', key: m[2], url: m[0] } : null;
}
