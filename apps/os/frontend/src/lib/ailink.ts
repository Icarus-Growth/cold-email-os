/* What a person pastes into each AI tool to reach the OS's AI connector (tab 5, Step 4), with
 * the real server and key filled in. The lines are the ones tab 5 uses, word for word.
 *
 * No imports: tests/functions.test.mjs runs this file in Node as it is. */

/** One AI link: `server` (<OS_AUTOMATIONS_URL>/mcp/, not secret), `key` (secret) and `url`
 *  (<server>s/<key>/, the link for Claude on the web, secret). */
export interface AILinkParts { server: string; key: string; url: string }

export interface AISetup {
  tool: string;
  /** Where the lines go. */
  where: string;
  text: string;
}

/** Claude on the web shows these under its link (tab 5, Step 4, word for word). */
export const WEB_WARNING = "Modal's log keeps this link. Use it only if nobody else can open your Modal account.";
export const WEB_PLANS = "Custom connectors work on the Free (one connector at most), Pro and Max plans. On a Team or Enterprise plan only a Claude Owner can add one, for the whole Claude organization, so everyone there would act as you: use Claude Code, Codex or Hermes instead.";

/** How Claude on the web is connected (tab 5): the "Add custom connector" screen, no sign-in, the link. */
export const WEB_WHERE = 'Settings, Connectors, Add custom connector. Name: Agency OS. Pick "No sign-in". Paste this link as the URL. The link holds the key.';

/** The tools, Claude on the web first (most people use it). */
export function aiSetup(l: AILinkParts): AISetup[] {
  return [
    { tool: 'Claude on the web (claude.ai)', where: WEB_WHERE, text: l.url },
    { tool: 'Claude Code', where: 'Run this in a terminal.',
      text: 'claude mcp add --transport http --scope user agency-os "' + l.server + '" --header "Authorization: Bearer ' + l.key + '"' },
    { tool: 'Codex', where: 'Add these 3 lines to ~/.codex/config.toml. Then restart Codex.',
      text: '[mcp_servers.agency_os]\nurl = "' + l.server + '"\nhttp_headers = { "Authorization" = "Bearer ' + l.key + '" }' },
    { tool: 'Hermes', where: 'Add these lines to ~/.hermes/config.yaml, under mcp_servers:. Then restart Hermes. Check it with: hermes mcp test agency_os',
      text: 'agency_os:\n  url: "' + l.server + '"\n  headers:\n    Authorization: "Bearer ' + l.key + '"' },
  ];
}

/** The key as the screen shows it: dots and its last 4 characters ("••••••••3f9a"). */
export function maskKey(key: string): string {
  return '••••••••' + (key.length > 8 ? key.slice(-4) : '');
}

/** A line as the screen shows it: every copy of the key masked. The Copy button copies the real line. */
export function onScreen(text: string, key: string): string {
  return key ? text.split(key).join(maskKey(key)) : text;
}
