/* Smartlead. From third-party sources: confirm in Smartlead's own editor.
 * Spintax {a|b}; merge {{first_name}}; single braces around a name make spintax by mistake. */
import type { SenderRules } from './types.ts';

export const SMARTLEAD: SenderRules = {
  tool: 'Smartlead',
  source: 'third-party sources (confirm in Smartlead\'s editor)',
  spintax: 'single',
  mergeCase: 'snake',
  fallback: false,
  needFallbackOnFirstName: false,
  oneVariablePerSpintax: false,
  emptyOption: false,
  liquid: false,
  fields: ['first_name', 'last_name', 'email', 'company_name', 'website', 'phone_number', 'location', 'linkedin_profile',
    'company_url', 'job_title'],
};
