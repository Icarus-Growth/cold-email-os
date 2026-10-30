/* The shape of agency.config.ts, and the helpers the screens use to read it.
 *
 * agency.config.ts says what this agency is: its boards, their stage ladders, the fields on a
 * card, the agency's own columns on the client page and the report numbers. The screens read
 * only that file and core.config.ts (the parts every agency has). Nothing else names a table.
 *
 * A ladder here must match the database exactly (same stages, same order).
 * tests/config_matches_db.py checks it. Change a stage in the database and here together.
 */

/** How a field is shown and edited. */
export type FieldType =
  | 'text'       // one line
  | 'longtext'   // rich text (notes, feedback, briefs)
  | 'url'        // a link: the address and an "Open" button
  | 'email' | 'phone'
  | 'date'       // a day
  | 'datetime'   // a day and a time
  | 'month'      // the first day of a month, shown as "Oct 2026"
  | 'int' | 'number' | 'money' | 'percent'
  | 'bool'       // a tick box
  | 'person'     // a team member (a column that ends in _id and points at team)
  | 'client'     // a client (client_id)
  | 'choice'     // one value from `list` (a database list, see LADDERS), or from `options`
  | 'tags'       // several words (a text[] column)
  | 'document';  // copy written in the OS editor (the documents table, migration 0013): no column on the row

export interface FieldDef {
  /** The column. */
  key: string;
  label: string;
  type: FieldType;
  /** For 'choice': the name of the list in LADDERS. */
  list?: string;
  /** For 'choice' on a text column: the choices, when the database keeps no list. */
  options?: string[];
  /** For 'document': the link column kept for "paste a link instead" (none for some fields). */
  link?: string;
  /** For 'document': the extra check under the readability numbers. */
  check?: 'cold-email' | 'ad-script' | 'caption' | 'email-copy';
  /** One line of help under the label. */
  desc?: string;
  /** Shown, never edited (the database fills it). */
  readOnly?: boolean;
  /** Needed on the "New" form. */
  required?: boolean;
}

/** A section of a record: a title, a line saying who it is for, then its fields. */
export interface SectionDef {
  title: string;
  desc?: string;
  fields: FieldDef[];
  /** Starts folded. */
  closed?: boolean;
}

/** A checklist inside a card (email marketing: the emails of a flow or a campaign calendar). */
export interface ChecklistDef {
  table: string;
  label: string;
  /** The column on the checklist row that points at the card. */
  parentKey: string;
  nameKey: string;
  statusKey: string;
  /** The list in LADDERS that holds the statuses, first to last. The last one is "done". */
  statusList: string;
  orderKey: string;
}

/** A table whose rows move through a ladder of stages: a board, or a list with no board. */
export interface RecordDef {
  table: string;
  /** The tab name ("Campaigns"). */
  label: string;
  /** One row, in words ("campaign"). */
  item: string;
  /** One line under the tab name: what one card is and who moves it. */
  desc: string;
  /** The column that names the card. */
  nameKey: string;
  /** The stage column. */
  stageKey: string;
  /** The name of the ladder in LADDERS (the database's own list name). */
  ladder: string;
  /** Stages that count as finished: they leave the dashboard. Same as the database view v_open_cards. */
  closed: string[];
  /** Every card must belong to a client. */
  clientRequired: boolean;
  /** The three fields on the face of a card (after its name). Never more than three. */
  card: string[];
  /** The sections of the card's panel, after "Stage". */
  sections: SectionDef[];
  /** The fields on the "New" form, in order. The name is always first. */
  create: string[];
  checklist?: ChecklistDef;
}

/** One report number. */
export interface MetricDef { key: string; label: string; format: 'int' | 'money' | 'percent' | 'number' | 'url' }

export interface AgencyConfig {
  /** "Cold Email", "Ads", "Content", "Email Marketing". */
  agency: string;
  /** The project boards, after Tasks (one tab each on the Tasks screen). */
  boards: RecordDef[];
  /** Tables with stages but no board. Each shows as a list on the client page. */
  lists: RecordDef[];
  /** The agency's own sections on the client page (the people in each role, the agency columns). */
  clientSections: SectionDef[];
  /** The weekly report numbers shown on the client page (weekly_metrics). */
  metrics: MetricDef[];
}

/** Every database list the screens use, by its database name. */
export type Ladders = Record<string, readonly string[]>;
