/* Instantly. Confirmed: help.instantly.ai, "Using Spintax".
 * Spintax {{RANDOM | a | b}}; merge {{firstName}} (camelCase); fallback {{firstName | there}};
 * merge fields may sit inside spintax. */
import type { SenderRules } from './types.ts';

export const INSTANTLY: SenderRules = {
  tool: 'Instantly',
  source: 'help.instantly.ai, "Using Spintax" (confirmed)',
  spintax: 'random',
  mergeCase: 'camel',
  fallback: true,
  needFallbackOnFirstName: true,
  oneVariablePerSpintax: false,
  emptyOption: false,
  liquid: false,
  fields: ['firstName', 'lastName', 'email', 'companyName', 'website', 'phone', 'personalization', 'location', 'jobTitle',
    'sendingAccountFirstName', 'accountSignature'],
};
