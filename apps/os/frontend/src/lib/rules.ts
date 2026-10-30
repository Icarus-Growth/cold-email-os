/* The Slack alert rules (apps/os/automations/alert_rules.json), read when the app is built.
 * My Work uses them to say who acts next on a card: the person the alert for its stage tags.
 * After a change to that file, put the OS live again so My Work follows it. */
import file from '../../../automations/alert_rules.json';
import type { Rule } from '../areas/home/work';

export const RULES: Rule[] = ((file as { rules?: Rule[] }).rules || []);
