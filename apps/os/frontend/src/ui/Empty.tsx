import React from 'react';

/** A plain message in place of content: "No client selected", "Loading batches…", a missing table. */
export function Notice({ title, children, tone }: { title: React.ReactNode; children?: React.ReactNode; tone?: 'bad' | null }) {
  return (
    <div className="rounded-[14px] border border-dashed border-[var(--border-primary_hover)] bg-card px-6 py-8 text-center" data-notice>
      <div className={`text-[14px] font-medium ${tone === 'bad' ? 'text-bad' : 'text-ink2'}`}>{title}</div>
      {children && <div className="text-[13px] text-muted mt-1">{children}</div>}
    </div>
  );
}

/** A footnote under a page ("Every stage on the ladder gets a column, empty or not."). */
export function Foot({ children }: { children: React.ReactNode }) {
  return <p className="text-[12.5px] text-muted mt-3">{children}</p>;
}

/** A page body that stacks its blocks with even spacing. */
export function Stack({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`flex flex-col gap-3 min-w-0 ${className}`}>{children}</div>;
}
