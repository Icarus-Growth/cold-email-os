/* What one sending tool accepts. One file per tool (instantly.ts, smartlead.ts, plusvibe.ts):
 * when a tool changes its syntax, the fix is one line there. index.ts runs the checks. */

export interface SenderRules {
  tool: 'Instantly' | 'Smartlead' | 'PlusVibe';
  /** Where the rules come from, and how sure we are. */
  source: string;
  /** 'random' = {{RANDOM | a | b}}, 'single' = {a|b}. */
  spintax: 'random' | 'single';
  /** How a merge field is written inside {{ }}: firstName or first_name. */
  mergeCase: 'camel' | 'snake';
  /** {{firstName | there}}: a fallback after a bar. */
  fallback: boolean;
  /** Flag a first name with no fallback. */
  needFallbackOnFirstName: boolean;
  /** At most one merge field in one spintax block. */
  oneVariablePerSpintax: boolean;
  /** {a||b}: an empty option is allowed. */
  emptyOption: boolean;
  /** {% if first_name %}: Liquid blocks name fields without braces. */
  liquid: boolean;
  /** The tool's standard lead fields, written the tool's way. Others must be a column in the lead list. */
  fields: string[];
}
