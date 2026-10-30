/* POST /api/team/add  {full_name, email, access, job_title}  ->  {message, email, slack} | {error}
 *
 * The "Add team member" button. For an Owner or Admin only (see ../../_lib/team.js):
 *   1. puts the person on the team table, Active, with "can sign in" ticked;
 *   2. makes their login with a random temporary password (works with sign-ups off);
 *   3. answers with the ready message to copy, once;
 *   4. when the automations are set up, also sends that message as a Slack direct message.
 */
import { ACCESS, EMAIL_RE, admin, body, json, notSetUp, readyMessage, refuse, sb, sendToSlack, setLogin, teamRow, tempPassword } from '../../_lib/team.js';

export async function onRequestPost({ request, env }) {
  const off = notSetUp(env);
  if (off) return off;
  try {
    const caller = await admin(request, env);
    if (caller instanceof Response) return caller;

    const b = await body(request);
    const fullName = String(b.full_name || '').trim().slice(0, 120);
    const email = String(b.email || '').trim().toLowerCase();
    const access = ACCESS.indexOf(b.access) > -1 ? b.access : 'Member';
    const jobTitle = String(b.job_title || '').trim().slice(0, 120);
    if (!fullName) return refuse(400, 'Type their name.');
    if (!EMAIL_RE.test(email)) return refuse(400, 'That does not look like an email address.');
    if (access === 'Owner' && caller.access !== 'Owner') return refuse(403, 'Only an Owner can add another Owner.');

    const before = await teamRow(env, 'email=eq.' + encodeURIComponent(email));
    if (before && before.access === 'Owner' && caller.access !== 'Owner') return refuse(403, 'That person is an Owner. Only an Owner can change their access.');

    // 1. The team row (made, or brought back with sign-in on).
    const row = { full_name: fullName, email, access, can_sign_in: true, status: 'Active' };
    if (jobTitle) row.job_title = jobTitle;
    const saved = await sb(env, '/rest/v1/team?on_conflict=email', { body: row, prefer: 'resolution=merge-duplicates,return=representation' });
    if (!saved.ok) return refuse(502, 'Could not save them on the team list (' + saved.status + '). Try again.');
    const person = (await saved.json())[0] || row;

    // 2. The login.
    const password = tempPassword();
    try {
      await setLogin(env, email, fullName, password);
    } catch (e) {
      return refuse(502, 'They are on the team list, but their login could not be made. Press "Resend access" on their page to try again.');
    }

    // 3 and 4. The message.
    const message = await readyMessage(env, request, person, password);
    const slack = await sendToSlack(env, person, message);
    return json({ message, email, slack });
  } catch (e) {
    return refuse(502, 'Something went wrong on the server. Try again in a minute.');
  }
}
