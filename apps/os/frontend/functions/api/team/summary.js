/* POST /api/team/summary  {}  ->  {sent: true} | {error}
 *
 * The "Send today's summary" button on the Dashboard. For an Owner or Admin only (see
 * ../../_lib/team.js). It asks the automations app to post the daily summary now, whatever the
 * hour: POST <OS_AUTOMATIONS_URL>/summary-now with the shared secret. This is choice 3 in tab 3
 * when the free Modal plan's 5 scheduled jobs are used up and the hourly timer is off.
 * The automations app answers at once and posts the summary in the background.
 */
import { admin, json, notSetUp, refuse } from '../../_lib/team.js';

export async function onRequestPost({ request, env }) {
  const off = notSetUp(env);
  if (off) return off;
  try {
    const caller = await admin(request, env);
    if (caller instanceof Response) return caller;

    const url = String(env.OS_AUTOMATIONS_URL || env.MODAL_ALERTS_URL || '').replace(/\/+$/, '');
    if (!url || !env.OS_SHARED_SECRET) {
      return refuse(409, 'The automations are not set up yet. Do tab 3 (automations) first, then deploy the OS again.');
    }
    let res;
    try {
      res = await fetch(url + '/summary-now', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-OS-Secret': env.OS_SHARED_SECRET },
        body: '{}',
      });
    } catch (e) {
      return refuse(502, 'Could not reach the automations app. Check that it is deployed (tab 3), then try again.');
    }
    const out = await res.json().catch(() => null);
    if (res.status === 401) {
      return refuse(502, 'The automations app turned the call away. OS_SHARED_SECRET is not the same in the OS and in the automations app. Put the same value in both, then deploy both again.');
    }
    if (res.status === 404) {
      return refuse(502, 'The automations app has no "send the summary now" step yet. Deploy it again (tab 3), then try again.');
    }
    if (!res.ok || !out || out.ok === false) {
      return refuse(502, (out && out.error) || 'The automations app said no (' + res.status + ').');
    }
    return json({ sent: true });
  } catch (e) {
    return refuse(502, 'Something went wrong on the server. Try again in a minute.');
  }
}
