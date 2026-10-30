/* POST /api/team/resend  {team_id}  ->  {message, email, slack} | {error}
 *
 * The "Resend access" button on a person's page, for someone who lost their password or never
 * signed in. For an Owner or Admin only. It gives the login a new temporary password (making
 * the login if it is missing) and answers with the same ready message as "Add team member".
 * The person must still have "can sign in" ticked: this step never gives access back by itself.
 */
import { UUID_RE, admin, body, json, notSetUp, readyMessage, refuse, sendToSlack, setLogin, teamRow, tempPassword } from '../../_lib/team.js';

export async function onRequestPost({ request, env }) {
  const off = notSetUp(env);
  if (off) return off;
  try {
    const caller = await admin(request, env);
    if (caller instanceof Response) return caller;

    const b = await body(request);
    const id = String(b.team_id || '');
    if (!UUID_RE.test(id)) return refuse(400, 'Pick a person first.');
    const person = await teamRow(env, 'id=eq.' + id);
    if (!person) return refuse(404, 'That person is not on the team list.');
    if (person.status !== 'Active' || !person.can_sign_in) {
      return refuse(409, person.full_name + ' cannot sign in. Set them to Active and tick "Can sign in" first.');
    }
    if (person.access === 'Owner' && caller.access !== 'Owner') return refuse(403, 'Only an Owner can reset an Owner\'s access.');

    const password = tempPassword();
    try {
      await setLogin(env, person.email, person.full_name, password);
    } catch (e) {
      return refuse(502, 'Could not reset their login. Try again in a minute.');
    }
    const message = await readyMessage(env, request, person, password);
    const slack = await sendToSlack(env, person, message);
    return json({ message, email: person.email, slack });
  } catch (e) {
    return refuse(502, 'Something went wrong on the server. Try again in a minute.');
  }
}
