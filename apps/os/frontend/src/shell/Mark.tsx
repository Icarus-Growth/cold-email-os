/** The OS mark: the brand colour with a simple board glyph. Change the colour in theme.css. */
export function Mark({ size = 24, radius = 6 }: { size?: number; radius?: number }) {
  return (
    <svg aria-hidden width={size} height={size} viewBox="0 0 32 32" style={{ borderRadius: radius, display: 'block', flexShrink: 0 }}>
      <rect width="32" height="32" fill="var(--button-primary-bg)" />
      <rect x="7" y="8" width="5" height="16" rx="1.5" fill="var(--text-white)" />
      <rect x="13.5" y="8" width="5" height="11" rx="1.5" fill="var(--text-white)" opacity="0.8" />
      <rect x="20" y="8" width="5" height="7" rx="1.5" fill="var(--text-white)" opacity="0.6" />
    </svg>
  );
}
