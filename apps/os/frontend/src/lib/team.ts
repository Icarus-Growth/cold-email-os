/* The two server steps of the Team screen. Both run on Cloudflare (functions/api/team/),
 * which holds the Supabase secret key; the browser never sees it.
 *
 *   POST /api/team/add     {full_name, email, access, job_title}
 *   POST /api/team/resend  {team_id}
 *   POST /api/team/ai      {team_id, action: 'issue' | 'revoke'}   (the AI connector link)
 *
 * Each checks that the caller is an Owner or Admin, makes (or resets) the login with a random
 * temporary password, and answers with the ready message to copy, once. When the Slack
 * automations are set up, the same message also goes to the person as a Slack direct message. */
import * as Auth from './auth';
import type { AILinkParts } from './ailink';
export type { AILinkParts };

export interface AccessResult {
  /** The message to copy and send: the OS address, the email and the temporary password. */
  message: string;
  email: string;
  /** 'sent': the Slack message went out. 'off': Slack is not set up yet. 'failed': it did not go out. */
  slack: 'sent' | 'off' | 'failed';
}

async function call<T = AccessResult>(path: string, body: unknown): Promise<T> {
  await Auth.fresh();
  let res: Response;
  try {
    res = await fetch('/api/team/' + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + Auth.token() },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error('Could not reach the server step. Check your connection and try again.');
  }
  const d = await res.json().catch(() => null);
  if (!d) throw new Error('The server step did not answer. It runs only on the deployed OS (Cloudflare Pages), not on a local copy.');
  if (!res.ok) throw new Error(d.error || 'That did not work (HTTP ' + res.status + ').');
  return d as T;
}

/** Add a person: their team row, their login and a temporary password. */
export function addMember(person: { full_name: string; email: string; access: string; job_title?: string }): Promise<AccessResult> {
  return call('add', person);
}

/** A new temporary password for someone who lost theirs or never signed in. */
export function resendAccess(teamId: string): Promise<AccessResult> {
  return call('resend', { team_id: teamId });
}

/** A new private link for this person's AI (tab 5). Shown once; a new one replaces the old. */
export function connectAI(teamId: string): Promise<AILinkParts> {
  return call<AILinkParts>('ai', { team_id: teamId, action: 'issue' });
}

/** Kill this person's AI link. Their AI stops working with the OS. */
export function revokeAI(teamId: string): Promise<{ revoked: boolean }> {
  return call<{ revoked: boolean }>('ai', { team_id: teamId, action: 'revoke' });
}
