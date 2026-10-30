/* What this agency is: a cold email agency.
 *
 * The boards, their stage ladders, the fields on a card, the agency's own columns on the client
 * page and the weekly numbers. Change a stage here AND in the database, then run
 * `python3 tests/config_matches_db.py`. */
import type { AgencyConfig, Ladders } from './config';

/** The agency's own database lists. They must match the migrations exactly. */
export const LADDERS = {
  campaign_stage: [
    '0 - Backlog',
    '10 - List Building',
    '20 - Copywriting',
    '29 - Copy Amendments',
    '30 - Client Review',
    '39 - Client Changes',
    '40 - Ready To Launch',
    '50 - Live',
    '100 - Ended',
  ],
  campaign_channel: ['Email'],
  inbox_batch_stage: [
    '0 - Backlog',
    '10 - Approval Needed',
    '20 - Buying Domains',
    '30 - Setting Up Inboxes',
    '40 - Warming',
    '100 - Ready To Send',
  ],
} as const satisfies Ladders;

export const AGENCY: AgencyConfig = {
  agency: 'Cold Email',
  boards: [
    {
      table: 'campaigns',
      label: 'Campaigns',
      item: 'campaign',
      desc: 'One card is one campaign for one client, from list building to live.',
      nameKey: 'campaign_name',
      stageKey: 'stage',
      ladder: 'campaign_stage',
      closed: ['50 - Live', '100 - Ended'],
      clientRequired: true,
      card: ['client_id', 'assignee_id', 'due_date'],
      sections: [
        { title: 'Basic details', desc: 'What the campaign is, for which client, and who works on it.', fields: [
          { key: 'campaign_name', label: 'Campaign', type: 'text', required: true },
          { key: 'client_id', label: 'Client', type: 'client', required: true },
          { key: 'assignee_id', label: 'Assignee', type: 'person', desc: 'Who must act now.' },
          { key: 'reviewer_id', label: 'Reviewer', type: 'person', desc: 'Who checks the copy before the client sees it.' },
          { key: 'channel', label: 'Channel', type: 'choice', list: 'campaign_channel' },
        ] },
        { title: 'Campaign details', desc: 'For the campaign manager: the list, the angle, the copy and the dates.', fields: [
          { key: 'due_date', label: 'Due date', type: 'date' },
          { key: 'sending_tool', label: 'Sending tool', type: 'choice', options: ['Instantly', 'Smartlead', 'PlusVibe', 'Other'], desc: 'The copy checks follow this tool\'s spintax and merge fields.' },
          { key: 'angle', label: 'Angle', type: 'text' },
          { key: 'offer', label: 'Offer', type: 'text' },
          { key: 'list_url', label: 'Lead list', type: 'url' },
          { key: 'list_size', label: 'Leads in the list', type: 'int' },
          { key: 'copy_doc', label: 'Copy document', type: 'document', link: 'copy_doc_url', check: 'cold-email', desc: 'The emails of this campaign, checked for the sending tool above.' },
          { key: 'launch_date', label: 'Launch date', type: 'date' },
          { key: 'end_date', label: 'End date', type: 'date' },
        ] },
        { title: 'Feedback and notes', desc: 'For the copywriter: what the reviewer or the client asked to change.', fields: [
          { key: 'feedback_notes', label: 'Feedback', type: 'longtext' },
          { key: 'notes', label: 'Notes', type: 'longtext' },
        ] },
      ],
      create: ['campaign_name', 'client_id', 'assignee_id', 'due_date'],
    },
  ],
  lists: [
    {
      table: 'inbox_batches',
      label: 'Inbox batches',
      item: 'inbox batch',
      desc: 'One row is one batch of domains and inboxes bought for this client.',
      nameKey: 'batch_name',
      stageKey: 'stage',
      ladder: 'inbox_batch_stage',
      closed: ['100 - Ready To Send'],
      clientRequired: true,
      card: ['assignee_id', 'inbox_count', 'ready_on'],
      sections: [
        { title: 'Batch details', desc: 'For the person who buys and warms the inboxes.', fields: [
          { key: 'batch_name', label: 'Batch', type: 'text', required: true },
          { key: 'client_id', label: 'Client', type: 'client', required: true },
          { key: 'assignee_id', label: 'Assignee', type: 'person' },
          { key: 'domain_count', label: 'Domains', type: 'int' },
          { key: 'inbox_count', label: 'Inboxes', type: 'int' },
          { key: 'inbox_provider', label: 'Inbox provider', type: 'text' },
          { key: 'domain_registrar', label: 'Domain registrar', type: 'text' },
          { key: 'warmup_started_on', label: 'Warm-up started', type: 'date' },
          { key: 'ready_on', label: 'Ready to send on', type: 'date' },
          { key: 'due_date', label: 'Due date', type: 'date' },
        ] },
        { title: 'Notes', fields: [{ key: 'notes', label: 'Notes', type: 'longtext' }] },
      ],
      create: ['batch_name', 'client_id', 'domain_count', 'inbox_count'],
    },
  ],
  clientSections: [
    { title: 'People', desc: 'Who looks after this client in each role.', fields: [
      { key: 'account_manager_id', label: 'Account manager', type: 'person' },
      { key: 'campaign_manager_id', label: 'Campaign manager', type: 'person' },
    ] },
    { title: 'Cold email', desc: 'What the client sells, to whom, and the documents the team works from.', fields: [
      { key: 'target_market', label: 'Target market', type: 'text' },
      { key: 'offer_doc', label: 'Offer document', type: 'document', link: 'offer_doc_url' },
      { key: 'copy_doc', label: 'Copy document', type: 'document', link: 'copy_doc_url', check: 'cold-email', desc: 'The client\'s approved master copy.' },
      { key: 'sending_domains', label: 'Sending domains', type: 'text', desc: 'Names only, never logins.' },
    ] },
  ],
  metrics: [
    { key: 'emails_sent', label: 'Emails sent', format: 'int' },
    { key: 'replies', label: 'Replies', format: 'int' },
    { key: 'positive_replies', label: 'Positive replies', format: 'int' },
    { key: 'meetings_booked', label: 'Meetings booked', format: 'int' },
    { key: 'reply_rate', label: 'Reply rate', format: 'percent' },
    { key: 'bounce_rate', label: 'Bounce rate', format: 'percent' },
  ],
};
