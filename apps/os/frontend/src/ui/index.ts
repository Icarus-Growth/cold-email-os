/* The shared UI kit. Screens import from 'src/ui' (this file) only. */

// Buttons — Button (variant primary = brand fill, ONE per view), IconButton, LinkButton ("Open document").
export { Button, IconButton, LinkButton } from './Button';
export type { ButtonProps, ButtonVariant } from './Button';

// Status — Tag (pill), StagePill (stage + glyph), stageTone, Dot (client colour), Avatar (initials), StageGlyph.
export { Tag, StagePill, stageTone, Dot, Avatar, StageGlyph } from './Tag';
export type { TagTone } from './Tag';

// Field rows — FieldRow (label left / value right), FieldValue, FieldLink, LinkRow (url + Open button),
// Field (renders a FieldSpec), linkField (FieldSpec for a URL column).
export { FieldRow, FieldValue, FieldLink, LinkRow, Field, linkField } from './Field';
export type { FieldSpec, ValueTone } from './Field';

// Sections — Section / Sections (record groups: meta | done | current | todo, top-right button + warning),
// Card / CardHeader (soft white blocks).
export { Section, Sections, Card, CardHeader } from './Section';
export type { SectionSpec, SectionButton } from './Section';

// Records — RecordPanel (H's floating right panel, 480–760px, full width on phones), RecordPage (record as a page).
export { RecordPanel, RecordPage } from './RecordPanel';
export type { RecordPanelProps } from './RecordPanel';

// Editors — TextInput / TextArea (save on blur, never overwritten while focused), Toggle, Select (large = big single select).
export { TextInput, TextArea, Toggle, Select } from './Inputs';
// Rich text — RichText (bold, italics, bullets, numbers, link; cleaned HTML; saves on blur), RichView (read-only).
export { RichText, RichView } from './RichText';

// Overlays — Modal, Drawer, ToastHost (the shell mounts it; call toast() from lib/ui).
export { Modal, Drawer, ToastHost } from './Overlay';
// One Escape for the app: closes the top layer only (confirm, drill, drawer, phone menu, modal, panel).
export { useEscapeLayer } from './escape';
export type { EscapeLayer } from './escape';

// Board — KanbanBoard (B's look: every stage a column, drag between columns, three-field cards).
export { KanbanBoard } from './KanbanBoard';
export type { BoardCard, CardField, KanbanBoardProps } from './KanbanBoard';

// Table — DataTable (E's look: resize, re-order, add/hide columns saved per login per browser; optional
// row groups with a folding header, a red or amber row edge), rawCell.
export { DataTable, rawCell } from './DataTable';
export type { Column, Cell, DataTableProps, TableGroup } from './DataTable';

// Dashboard — Scorecard / ScoreGrid (4 x 2, key cards tinted, tone only with a threshold),
// BarChart (horizontal per-stage bars, one colour per client, count at the end, click to drill), ClientKey.
export { Scorecard, ScoreGrid, BarChart, ClientKey } from './Charts';
export type { ScoreSpec, Bar, BarChartProps } from './Charts';

// Filters — FilterPill (one choice or all), DatePill, And;
// ChoicePill (one choice from plain words, first = default), MultiPill (tick several).
export { FilterPill, DatePill, And, ChoicePill, MultiPill } from './Filters';
// Sort — SortPill (field + direction, or the list's default order), sortList (empties last), readSort / writeSort.
export { SortPill, sortList, readSort, writeSort } from './Sort';
export type { SortChoice, SortDir, SortValue } from './Sort';
// Due dates — RangePill (a date filter counted in days: Late, Today, Next 7 days, Between two dates, No due date)
// and its day helpers.
export { RangePill, DATE_LABEL, dayKey, dayDate, dayOf, addDays, resolveRange } from './DueDate';
export type { DayRange } from './DueDate';

// Bits — Notice (plain message instead of content), Foot (page footnote), Stack (vertical spacing).
export { Notice, Foot, Stack } from './Empty';
