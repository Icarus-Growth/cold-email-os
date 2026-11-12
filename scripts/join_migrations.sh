#!/bin/sh
# Tab 1, Step 10: join the change files into one starting file.
#
#   sh scripts/join_migrations.sh
#
# Run it from anywhere inside the repo, after `.env` is loaded into the terminal
# (set -a; . ./.env; set +a). It works the same in sh, bash and zsh.
#
# What it does, in this order:
#   1. Joins every numbered change file (0001_... and up) in
#      apps/os/backend/supabase/migrations/ into one starting file,
#      <YYYYMMDDHHMMSS>_baseline.sql (the time now, in UTC).
#   2. Moves the old files to archive/: the change files to archive/migrations/,
#      docs/examples/add_examples.sql to archive/examples/, docs/interview/ to
#      archive/interview/, the sql-editor/ folder to archive/sql-editor/.
#      It uses `git mv` in a git repo, so the history shows a move.
#   3. Tells the database tool that the old files are replaced by the new one
#      (supabase migration repair), then checks that nothing is left to push.
#
# It checks everything before it changes anything. If step 3 fails (for
# example the access token ran out), fix that and run it again: it carries on
# from step 3 and does not join twice.
#
# For the tests: SUPABASE_CMD replaces the `supabase` command, and
# JOIN_NOW replaces the time now (YYYYMMDDHHMMSS).

# zsh: behave like sh (split words, no error on a pattern with no match).
if [ -n "${ZSH_VERSION:-}" ]; then emulate sh; fi
set -eu

say() { printf '%s\n' "$*"; }
stop() { printf 'STOPPED: %s\n' "$*" >&2; exit 1; }

# The repo root: the folder above scripts/.
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
cd "$root"

workdir=apps/os/backend
mig=$workdir/supabase/migrations
arch=archive/migrations
[ -d "$mig" ] || stop "There is no $mig folder. Run this from the OS repo."

# The supabase command: SUPABASE_CMD, else supabase, else npx.
sb() {
  if [ -n "${SUPABASE_CMD:-}" ]; then
    $SUPABASE_CMD "$@"
  elif command -v supabase >/dev/null 2>&1; then
    supabase "$@"
  else
    npx --yes supabase "$@"
  fi
}

in_git=no
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then in_git=yes; fi

# Move one file or folder. git mv for a tracked path, else mv.
move() {
  if [ "$in_git" = yes ] && git ls-files --error-unmatch "$1" >/dev/null 2>&1; then
    git mv "$1" "$2"
  else
    mv "$1" "$2"
  fi
}

# The numbered change files, in number order. One name per line.
old_files() {
  find "$mig" -maxdepth 1 -type f -name '[0-9][0-9][0-9][0-9]_*.sql' | sed 's|.*/||' | sort
}
baselines() {
  find "$mig" -maxdepth 1 -type f -name '[0-9]*_baseline.sql' | sed 's|.*/||' | sort
}

olds=$(old_files)
bases=$(baselines)
nbases=0
if [ -n "$bases" ]; then nbases=$(printf '%s\n' "$bases" | wc -l | tr -d ' '); fi

if [ -n "$olds" ]; then
  # ---- Steps 1 and 2: join, then move ---------------------------------------
  [ "$nbases" -eq 0 ] || stop "A starting file ($bases) is already in $mig, and numbered change files are still there too. Nothing was changed. Ask for help before you go on."

  # Check every move first, so nothing moves half way.
  while IFS= read -r f; do
    [ ! -e "$arch/$f" ] || stop "$arch/$f is already there. Nothing was changed."
  done <<EOF
$olds
EOF
  if [ -e docs/examples/add_examples.sql ] && [ -e archive/examples/add_examples.sql ]; then
    stop "archive/examples/add_examples.sql is already there. Nothing was changed."
  fi
  if [ -d docs/interview ] && [ -e archive/interview ]; then
    stop "archive/interview is already there. Nothing was changed."
  fi
  if [ -d $workdir/supabase/sql-editor ] && [ -e archive/sql-editor ]; then
    stop "archive/sql-editor is already there. Nothing was changed."
  fi

  stamp=${JOIN_NOW:-$(date -u +%Y%m%d%H%M%S)}
  case "$stamp" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) stop "The time must be 14 numbers (YYYYMMDDHHMMSS), not '$stamp'." ;;
  esac
  base=$mig/${stamp}_baseline.sql
  tmp=$mig/.${stamp}_baseline.sql.part

  {
    say "-- Joined from the files in archive/migrations/. To delete the example rows, run docs/examples/delete_examples.sql."
    while IFS= read -r f; do
      say ""
      say "-- ============================================================================="
      say "-- From $f"
      say "-- ============================================================================="
      cat "$mig/$f"
      # A file that does not end with a new line must not join onto the next one.
      if [ -n "$(tail -c 1 "$mig/$f")" ]; then say ""; fi
    done <<EOF
$olds
EOF
  } > "$tmp"
  mv "$tmp" "$base"
  n=$(printf '%s\n' "$olds" | wc -l | tr -d ' ')
  say "1. Joined $n change files into $base."

  mkdir -p "$arch"
  while IFS= read -r f; do
    move "$mig/$f" "$arch/$f"
  done <<EOF
$olds
EOF
  if [ -e docs/examples/add_examples.sql ]; then
    mkdir -p archive/examples
    move docs/examples/add_examples.sql archive/examples/add_examples.sql
  fi
  if [ -d docs/interview ]; then move docs/interview archive/interview; fi
  if [ -d $workdir/supabase/sql-editor ]; then move $workdir/supabase/sql-editor archive/sql-editor; fi
  if [ -f archive/sql-editor/mark_baseline.sql ]; then
    sed "s/<YYYYMMDDHHMMSS>/$stamp/" archive/sql-editor/mark_baseline.sql > archive/sql-editor/.mark_baseline.part
    mv archive/sql-editor/.mark_baseline.part archive/sql-editor/mark_baseline.sql
  fi
  say "2. Moved the old files to archive/ (change files, add_examples.sql, interview/, sql-editor/)."
else
  # ---- A second run: carry on at step 3 ---------------------------------------
  [ "$nbases" -eq 1 ] || stop "There are no numbered change files in $mig and no single starting file. Nothing to join."
  base=$mig/$bases
  stamp=${bases%%_*}
  say "1-2. Already done: $base is the starting file."
fi

# ---- Step 3: tell the database tool ---------------------------------------------
nums=$(find "$arch" -maxdepth 1 -type f -name '[0-9][0-9][0-9][0-9]_*.sql' 2>/dev/null | sed 's|.*/||' | cut -d_ -f1 | sort)
[ -n "$nums" ] || stop "No old change files in $arch, so there is nothing to mark."
set --
while IFS= read -r v; do set -- "$@" "$v"; done <<EOF
$nums
EOF

if [ -z "${SUPABASE_ACCESS_TOKEN:-}" ] && [ -z "${SUPABASE_CMD:-}" ]; then
  stop "SUPABASE_ACCESS_TOKEN is not loaded. Run: set -a; . ./.env; set +a   Then run this again."
fi

sb migration repair --linked --status reverted "$@" --workdir "$workdir" --yes \
  || stop "Marking the old files failed. Read the error above, fix it (an expired token: make a new one), then run this again."
sb migration repair --linked --status applied "$stamp" --workdir "$workdir" --yes \
  || stop "Marking the starting file failed. Read the error above, fix it, then run this again."
say "3. Told the database tool: the $# old files are replaced by $stamp."

list=$(sb migration list --linked --workdir "$workdir") || stop "Could not read the migration list. Read the error above."
printf '%s\n' "$list"
push=$(sb db push --linked --dry-run --workdir "$workdir" --yes 2>&1) || { printf '%s\n' "$push"; stop "The check push failed. Read the error above."; }
printf '%s\n' "$push"
case "$push" in
  *"up to date"*) ;;
  *) stop "The database tool still wants to push something. Show this to your helper before you go on." ;;
esac
say "PASS: one starting file ($stamp), and the database is up to date."
