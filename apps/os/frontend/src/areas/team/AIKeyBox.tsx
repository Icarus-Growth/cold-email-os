/* The lines a person pastes into their AI tool (tab 5), shown once after "Connect your AI".
 *
 * The key is never on screen in full: every line shows it as dots and its last 4 characters,
 * and the Copy button next to the line copies the real line. So a screenshot of this box can
 * go into a chat and give nobody access. Claude on the web comes first.
 *
 * No store imports: tests/aikey.test.mjs renders this file to HTML and looks for the key. */
import { Copy } from 'lucide-react';
import { Button } from '../../ui/Button';
import { aiSetup, maskKey, onScreen, WEB_PLANS, WEB_WARNING, type AILinkParts } from '../../lib/ailink';

/** One line as the screen shows it, and a Copy button that copies the real line. */
export function CopyRow({ label, text, secret, onCopy }: { label: string; text: string; secret: string; onCopy: (text: string, done: string) => void }) {
  return (
    <div className="flex items-start gap-2">
      <pre className="flex-1 min-w-0 whitespace-pre-wrap break-all rounded-[10px] bg-ground border border-line px-3 py-2 text-[12.5px] leading-[18px] text-ink font-mono" data-copy>{onScreen(text, secret)}</pre>
      <Button size="sm" icon={Copy} aria-label={'Copy ' + label} onClick={() => onCopy(text, 'Copied ' + label + '.')}>Copy</Button>
    </div>
  );
}

/** Everything inside the "AI key for <name>" box. */
export function AIKeyLines({ name, link, onCopy }: { name: string; link: AILinkParts; onCopy: (text: string, done: string) => void }) {
  return (
    <div className="space-y-4" data-ai-link>
      <p className="text-[13px] text-ink2">
        This is the only time the key is given. Press Copy next to {name}'s AI tool and send the line to {name} directly,
        never in a shared channel or a document. The screen shows only the last 4 characters of the key ({maskKey(link.key)}),
        so a screenshot of this box gives nobody access.
      </p>
      {aiSetup(link).map((s, i) => (
        <section key={s.tool} className={'space-y-1.5' + (i ? ' border-t border-line2 pt-3' : '')} data-tool={s.tool}>
          <h3 className="text-[13.5px] font-semibold text-ink">{s.tool}</h3>
          <p className="text-[12.5px] text-muted">{s.where}</p>
          <CopyRow label={'the lines for ' + s.tool} text={s.text} secret={link.key} onCopy={onCopy} />
          {link.url === s.text && <>
            <p className="text-[12.5px] text-[var(--warn)]" data-web-warning>{WEB_WARNING}</p>
            <p className="text-[12px] text-muted" data-web-plans>{WEB_PLANS}</p>
          </>}
        </section>
      ))}
      <section className="space-y-1.5 border-t border-line2 pt-3" data-basics>
        <h3 className="text-[13.5px] font-semibold text-ink">Another AI tool</h3>
        <p className="text-[12.5px] text-muted">Give it the server address and the key, sent as "Authorization: Bearer" and the key.</p>
        <CopyRow label="the server address" text={link.server} secret={link.key} onCopy={onCopy} />
        <CopyRow label="the key" text={link.key} secret={link.key} onCopy={onCopy} />
        <p className="text-[12.5px] text-muted">Keep the key (and the link for Claude on the web, if used) in a password manager.</p>
      </section>
      <p className="text-[12.5px] text-bad font-medium">
        The key and the link for Claude on the web work like a password. Anyone who has one can read and change the
        OS as {name}, with their access. If one leaks, press "Revoke".
      </p>
    </div>
  );
}
