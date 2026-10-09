import { useEffect, useRef, useState, type ReactNode } from 'react';

export type ImageDraft = { dataUrl: string; digest: string; name: string };

export function ImageComposer({ children, disabled, blocked, pending, uncertain, send, changed, recipient }: {
  children: ReactNode; disabled: boolean; blocked: boolean; pending: string[]; uncertain?: string;
  send: (image: ImageDraft) => Promise<boolean>; changed: (hasImage: boolean) => void; recipient: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const lock = useRef(false), generation = useRef(0);
  const [draft, setDraft] = useState<ImageDraft | null>(null);
  const [error, setError] = useState('');
  const [reading, setReading] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [sending, setSending] = useState(false);
  const ambiguous = !!draft && (pending.includes(draft.digest) || uncertain === draft.digest);
  useEffect(() => { changed(!!draft || reading); }, [draft, reading]);
  useEffect(() => () => { generation.current++; changed(false); }, []);

  async function choose(files: FileList | File[]) {
    if (disabled || lock.current) return;
    const current = ++generation.current;
    setError(''); setConfirmed(false); setReading(false);
    if (files.length !== 1) { setError('画像は1枚ずつ選択してください。'); return; }
    const file = files[0];
    if (!['image/png', 'image/jpeg'].includes(file.type)) { setError('JPEGまたはPNGの画像を選択してください。'); return; }
    if (!file.size || file.size > 4 * 1024 * 1024) { setError('画像は4MB以内で選択してください。'); return; }
    setReading(true);
    try {
      const bytes = await file.arrayBuffer();
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2, '0')).join('');
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject();
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      if (current === generation.current) setDraft({ dataUrl, digest, name: file.name });
    } catch { if (current === generation.current) setError('画像を読み込めませんでした。別の画像で試してください。'); }
    finally { if (current === generation.current) setReading(false); }
  }

  async function submit() {
    if (!draft || disabled || blocked || reading || lock.current || (ambiguous && !confirmed)) return;
    lock.current = true; setSending(true);
    try { if (await send(draft)) setDraft(null); else setConfirmed(false); }
    finally { lock.current = false; setSending(false); }
  }

  return <section className="composer" aria-label="メッセージを作成"
    onDragOver={event => { if (event.dataTransfer.types.includes('Files')) event.preventDefault(); }}
    onDrop={event => { if (event.dataTransfer.files.length) { event.preventDefault(); void choose(event.dataTransfer.files); } }}
    onPaste={event => { if (event.clipboardData.files.length) { event.preventDefault(); void choose(event.clipboardData.files); } }}>
    {children}
    <div className="image-composer-tools"><input ref={input} type="file" accept="image/jpeg,image/png" aria-label="送信する画像" hidden onChange={event => { if (event.target.files?.length) void choose(event.target.files); event.target.value = ''; }}/>
      <button className="secondary" disabled={disabled || reading || sending} onClick={() => input.current?.click()}>画像を選択</button>
      <span>{reading ? '画像を読み込み中…' : 'JPEG・PNG / 4MBまで · 貼り付け・ドロップも使えます'}</span>
    </div>
    {error && <p className="error-text" role="alert">{error}</p>}
    {draft && <div className="image-draft"><img src={draft.dataUrl} alt="送信前の画像プレビュー"/>
      <div><strong>{recipient} に画像を送信</strong><span className="image-filename">{draft.name}</span><p>選択した画像1枚を送信します。入力中の文章は下書きに残ります。</p>
        <div className="image-draft-actions"><button className="secondary" disabled={disabled || sending} onClick={() => { generation.current++; setDraft(null); setError(''); }}>画像を外す</button>
          <button className="primary" disabled={disabled || blocked || reading || sending || (ambiguous && !confirmed)} onClick={() => void submit()}>{sending ? '画像を送信中…' : 'この画像を送信'}</button></div>
      </div></div>}
    {ambiguous && <label className="retry-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>この画像は送信済みの可能性があります。履歴・相手側で未着を確認して再送します。</label>}
  </section>;
}
