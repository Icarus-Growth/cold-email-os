/* PlusVibe (was Pipl.ai). Partly confirmed.
 * Merge {{first_name}}; spintax {a|b}; one variable per spintax block; an empty option || is
 * allowed; Liquid blocks ({% if first_name %}) name fields without braces. */
import type { SenderRules } from './types.ts';

export const PLUSVIBE: SenderRules = {
  tool: 'PlusVibe',
  source: 'PlusVibe help (partly confirmed)',
  spintax: 'single',
  mergeCase: 'snake',
  fallback: false,
  needFallbackOnFirstName: false,
  oneVariablePerSpintax: true,
  emptyOption: true,
  liquid: true,
  fields: ['first_name', 'last_name', 'email', 'company_name', 'website', 'phone', 'linkedin', 'job_title', 'city', 'country'],
};
