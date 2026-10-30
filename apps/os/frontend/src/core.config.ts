/* The parts every agency has: the core lists, the Tasks board, the client page's core
 * sections, the team page and the OS settings. The agency's own parts are in agency.config.ts.
 *
 * LADDERS must match the database lists in apps/os/backend/supabase/migrations exactly.
 * tests/config_matches_db.py checks it. */
import type { FieldDef, Ladders, RecordDef, SectionDef } from './config';

export const CORE_LADDERS = {
  team_access: ['Owner', 'Admin', 'Member'],
  team_status: ['Active', 'Inactive'],
  client_status: ['Active', 'Paused', 'Ended'],
  onboarding_stage: [
    '0 - Paid',
    '10 - Contract Sent',
    '20 - Contract Signed',
    '30 - Set-Up',
    '40 - Call Booked',
    '50 - Call Taken',
    '100 - Onboarded',
  ],
  task_stage: [
    '-1 - Rejected',
    '0 - Backlog',
    '9 - Blocked',
    '10 - In Progress',
    '29 - Amendments',
    '30 - In Review',
    '100 - Complete',
  ],
  call_type: ['Sales', 'Onboarding', 'Check-In', 'Internal', 'Other'],
} as const satisfies Ladders;

/** The ad-hoc Tasks board. Every agency has it, first. */
export const TASKS_BOARD: RecordDef = {
  table: 'tasks',
  label: 'Tasks',
  item: 'task',
  desc: 'One card is one task for anyone on the team. Drag a card to move it; the move is saved at once.',
  nameKey: 'task_name',
  stageKey: 'stage',
  ladder: 'task_stage',
  closed: ['100 - Complete', '-1 - Rejected'],
  clientRequired: false,
  card: ['client_id', 'assignee_id', 'due_date'],
  sections: [
    { title: 'Basic details', desc: 'What the task is, for which client, and who does it.', fields: [
      { key: 'task_name', label: 'Task', type: 'text', required: true },
      { key: 'client_id', label: 'Client', type: 'client' },
      { key: 'assignee_id', label: 'Assignee', type: 'person', desc: 'Who must act now.' },
      { key: 'reviewer_id', label: 'Reviewer', type: 'person', desc: 'Who checks the work in review.' },
    ] },
    { title: 'Task details', desc: 'For the assignee: the deadline, the links and the notes to do the work.', fields: [
      { key: 'due_date', label: 'Due date', type: 'date' },
      { key: 'links', label: 'Links', type: 'longtext' },
      { key: 'notes', label: 'Notes', type: 'longtext' },
    ] },
  ],
  create: ['task_name', 'client_id', 'assignee_id', 'due_date'],
};

/** The client page sections every agency has. The agency's own sections go between
 *  "Onboarding" and "Notes" (agency.config.ts clientSections). */
export const CLIENT_BASIC: SectionDef = {
  title: 'Basic details',
  desc: 'Who the client is and how to reach them.',
  fields: [
    { key: 'client_name', label: 'Client name', type: 'text', required: true },
    { key: 'status', label: 'Status', type: 'choice', list: 'client_status' },
    { key: 'website', label: 'Website', type: 'url' },
    { key: 'contact_name', label: 'Main contact', type: 'text' },
    { key: 'contact_email', label: 'Contact email', type: 'email' },
    { key: 'contact_phone', label: 'Contact phone', type: 'phone' },
    { key: 'services', label: 'Services', type: 'tags', desc: 'What they buy from you, separated by commas.' },
    { key: 'start_date', label: 'Start date', type: 'date' },
    { key: 'end_date', label: 'End date', type: 'date' },
  ],
};

export const CLIENT_ONBOARDING: SectionDef = {
  title: 'Onboarding',
  desc: 'For the account manager: move the client to the next step as each one is done.',
  fields: [
    { key: 'onboarding_stage', label: 'Onboarding stage', type: 'choice', list: 'onboarding_stage' },
    { key: 'form_received_at', label: 'Form received', type: 'datetime', readOnly: true },
    { key: 'drive_folder_url', label: 'Drive folder', type: 'url' },
    { key: 'slack_channel_name', label: 'Slack channel', type: 'text' },
    { key: 'slack_channel_id', label: 'Slack channel ID', type: 'text',
      desc: 'The client\'s own channel. In Slack, right-click the channel, then View channel details: the ID is at the bottom and starts with C.' },
  ],
};

export const CLIENT_NOTES: SectionDef = {
  title: 'Notes',
  fields: [{ key: 'notes', label: 'Notes', type: 'longtext' }],
};

/** The columns the "For developers" section shows. Other ids and timestamps go there too. */
export const CLIENT_DEV: FieldDef[] = [
  { key: 'id', label: 'Client ID', type: 'text', readOnly: true },
  { key: 'form_code', label: 'Form code', type: 'text', readOnly: true },
  { key: 'onboarding_stage_changed_at', label: 'Stage changed at', type: 'datetime', readOnly: true },
  { key: 'created_at', label: 'Created at', type: 'datetime', readOnly: true },
  { key: 'updated_at', label: 'Updated at', type: 'datetime', readOnly: true },
  { key: 'is_example', label: 'Example row', type: 'bool', readOnly: true },
];

/** The fields on a client's "New client" form. */
export const CLIENT_CREATE = ['client_name', 'contact_name', 'contact_email', 'account_manager_id'];

/** The person page. Owners and Admins edit access; everyone edits the rest. */
export const TEAM_SECTIONS: SectionDef[] = [
  { title: 'Basic details', desc: 'Who the person is and what they do.', fields: [
    { key: 'full_name', label: 'Name', type: 'text', required: true },
    { key: 'email', label: 'Email', type: 'email', readOnly: true, desc: 'Their sign-in email. To change it, add them again with the new email.' },
    { key: 'job_title', label: 'Job title', type: 'text' },
    { key: 'phone', label: 'Phone', type: 'phone' },
    { key: 'capacity', label: 'Cards they can hold', type: 'int', desc: 'More open cards than this shows them as overloaded on the dashboard.' },
  ] },
  { title: 'Access', desc: 'For the owner and admins: who can sign in, and who can add people.', fields: [
    { key: 'access', label: 'Access', type: 'choice', list: 'team_access', desc: 'Owner and Admin can add people. Member cannot.' },
    { key: 'status', label: 'Status', type: 'choice', list: 'team_status' },
    { key: 'can_sign_in', label: 'Can sign in', type: 'bool', desc: 'Untick to take their access away. They keep their login but see nothing.' },
  ] },
  { title: 'Notes', fields: [{ key: 'notes', label: 'Notes', type: 'longtext' }] },
];

export const TEAM_DEV: FieldDef[] = [
  { key: 'id', label: 'Team ID', type: 'text', readOnly: true },
  { key: 'slack_user_id', label: 'Slack user ID', type: 'text' },
  { key: 'created_at', label: 'Created at', type: 'datetime', readOnly: true },
  { key: 'is_example', label: 'Example row', type: 'bool', readOnly: true },
];

/** The one settings row. Owners and Admins change it on the Team screen. */
export const SETTINGS_FIELDS: FieldDef[] = [
  { key: 'agency_name', label: 'Agency name', type: 'text', desc: 'Shown at the top of the side menu and in the sign-in message.' },
  { key: 'os_url', label: 'OS address', type: 'url', desc: 'For example https://app.youragency.com. Used in links and in the sign-in message.' },
  { key: 'onboarding_url', label: 'Form address', type: 'url', desc: 'For example https://onboarding.youragency.com. The "Copy form link" button needs it.' },
  { key: 'time_zone', label: 'Time zone', type: 'text', desc: 'For example Europe/London. The daily summary uses it.' },
  { key: 'stuck_after_days', label: 'Stuck after (days)', type: 'int', desc: 'A card that has not moved for this many days shows as stuck.' },
  { key: 'onboarding_stuck_after_days', label: 'Onboarding stuck after (days)', type: 'int', desc: 'A client whose onboarding has not moved for this many days needs attention.' },
  { key: 'daily_summary_hour', label: 'Daily summary hour', type: 'int', desc: '0 to 23, in your time zone.' },
];

/** A call on the client page. */
export const CALL_FIELDS: FieldDef[] = [
  { key: 'title', label: 'Title', type: 'text', required: true },
  { key: 'call_type', label: 'Type', type: 'choice', list: 'call_type' },
  { key: 'call_at', label: 'When', type: 'datetime' },
  { key: 'attendees', label: 'Who was there', type: 'text' },
  { key: 'recording_url', label: 'Recording', type: 'url' },
  { key: 'summary', label: 'Summary', type: 'longtext' },
  { key: 'action_items', label: 'Action items', type: 'longtext' },
  { key: 'transcript', label: 'Transcript', type: 'longtext' },
];
