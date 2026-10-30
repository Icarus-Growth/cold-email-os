import React from 'react';
import { ExternalLink, type LucideIcon } from 'lucide-react';

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger';

const BASE = 'inline-flex items-center justify-center gap-1.5 whitespace-nowrap font-medium rounded-[10px] transition-colors disabled:opacity-50 disabled:cursor-default';
const SIZE = { sm: 'h-[30px] px-2.5 text-[12.5px]', md: 'h-[36px] px-3.5 text-[13.5px]' };
const VARIANT: Record<ButtonVariant, string> = {
  // The brand fill. ONE per view: the thing to do next.
  primary: 'bg-primary text-white hover:bg-primaryhover',
  // White with a hairline: every other button.
  secondary: 'bg-card text-ink2 border border-line hover:bg-ground',
  // White with a dark line: the page header's "New X".
  outline: 'bg-card text-ink border border-[var(--text-primary)] hover:bg-ground',
  ghost: 'text-ink2 hover:bg-taccent',
  danger: 'bg-card border border-line text-[var(--os-danger)] hover:bg-tbad',
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: 'sm' | 'md';
  icon?: LucideIcon;
}

/** A button. variant: primary (brand fill, one per view) | secondary | outline | ghost | danger. */
export function Button({ variant = 'secondary', size = 'md', icon: Icon, className = '', children, type = 'button', ...rest }: ButtonProps) {
  return (
    <button type={type} className={`${BASE} ${SIZE[size]} ${VARIANT[variant]} ${className}`} {...rest}>
      {Icon && <Icon size={size === 'sm' ? 13 : 15} />}
      {children}
    </button>
  );
}

/** A square icon-only button (close, menu). Always pass a `label` for screen readers. */
export function IconButton({ icon: Icon, label, className = '', ...rest }: { icon: LucideIcon; label: string } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" aria-label={label} title={label}
      className={`inline-flex items-center justify-center w-[30px] h-[30px] rounded-[8px] text-muted border border-line bg-card hover:bg-ground ${className}`} {...rest}>
      <Icon size={14} />
    </button>
  );
}

/** A button that opens a URL in a new tab ("Open document"). Stops the click reaching a row underneath. */
export function LinkButton({ href, children = 'Open document', size = 'sm', className = '' }: { href: string; children?: React.ReactNode; size?: 'sm' | 'md'; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
      className={`${BASE} ${SIZE[size]} ${VARIANT.secondary} no-underline ${className}`}>
      {children}<ExternalLink size={12} />
    </a>
  );
}
