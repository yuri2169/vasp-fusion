/** Why the analyst confirmed or dismissed a lead.
 *
 * A bare click records a decision nobody can review later. The reason and the
 * analyst's name travel with the verdict into the feedback table. A dialog
 * rather than an inline row editor, so the queue table, the focus view and the
 * case file all behave the same way.
 */
import { useEffect, useRef, useState } from 'react';
import { Button, Chip } from '../ui';

const REASONS: Record<'confirmed' | 'dismissed', string[]> = {
  confirmed: ['confirmed pattern', 'other'],
  dismissed: ['exchange payout', 'licit pass-through', 'insufficient evidence', 'other'],
};

export function ReasonChooser({ entity, verdict, onSave, onCancel }: {
  entity: string; verdict: 'confirmed' | 'dismissed';
  onSave: (reason: string) => void; onCancel: () => void;
}) {
  const [reason, setReason] = useState(REASONS[verdict][0]);
  const [note, setNote] = useState('');
  const first = useRef<HTMLDivElement>(null);

  useEffect(() => {
    first.current?.querySelector('button')?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);

  const save = () => onSave(note.trim() ? `${reason}: ${note.trim()}` : reason);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/25 no-print"
         onClick={(e) => { e.stopPropagation(); onCancel(); }}
         onKeyDown={(e) => e.stopPropagation()}>
      <div role="dialog" aria-modal="true"
           aria-label={`Reason to ${verdict === 'confirmed' ? 'confirm' : 'dismiss'} ${entity}`}
           onClick={(e) => e.stopPropagation()}
           className="w-[26rem] max-w-[calc(100vw-2rem)] bg-surface border border-ink p-4">
        <div className="colhead">{verdict === 'confirmed' ? 'confirm' : 'dismiss'} · reason</div>
        <div className="mono text-md font-semibold text-ink mt-1">{entity}</div>
        <div ref={first} className="flex flex-wrap gap-1 mt-3">
          {REASONS[verdict].map((r) => (
            <Chip key={r} layer="confirm"
                  active={reason === r} onClick={() => setReason(r)}>{r}</Chip>
          ))}
        </div>
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={150}
               onKeyDown={(e) => { if (e.key === 'Enter') save(); }}
               placeholder="note (optional)" aria-label="Note"
               className="mt-3 h-8 w-full bg-surface border border-rule px-2 text-sm
                          placeholder:text-ink-dim focus:border-ink outline-none" />
        <div className="flex justify-end gap-2 mt-3">
          <Button variant="ghost" onClick={onCancel}>cancel</Button>
          <Button variant={verdict === 'confirmed' ? 'primary' : 'default'} onClick={save}>
            {verdict === 'confirmed' ? 'confirm' : 'dismiss'}
          </Button>
        </div>
      </div>
    </div>
  );
}
