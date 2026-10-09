import { useEffect, useRef, useState } from 'react';
import { request } from './bridge';
import type { Message } from './types';

type Preview = { image: string | null; pending: boolean };
export function LineMedia({ message, conversationId, connected, onLoad }: { message: Message; conversationId: string; connected: boolean; onLoad?: () => void }) {
  const container = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const [image, setImage] = useState<string | null>(null);
  const [loading, setLoading] = useState(connected);
  const [attempt, setAttempt] = useState(0);
  const sticker = message.media?.kind === 'sticker';
  const label = sticker ? 'スタンプ' : '画像';

  useEffect(() => {
    let disposed = false, started = false, polls = 0;
    let timer: ReturnType<typeof setTimeout>;
    setImage(null);
    setLoading(connected);
    dialog.current?.close();
    if (!connected) return;
    const fetch = async () => {
      try {
        const result = await request<Preview>({ op: 'line_media', conversationId, messageId: message.id, retry: attempt > 0 && polls === 0 });
        if (disposed) return;
        if (result.image && /^data:image\/(png|jpeg);base64,/.test(result.image)) {
          setImage(result.image); setLoading(false);
        } else if (result.pending && ++polls < 600) {
          timer = setTimeout(fetch, 500);
        } else setLoading(false);
      } catch { if (!disposed) setLoading(false); }
    };
    const observer = new IntersectionObserver(entries => {
      if (!started && entries.some(e => e.isIntersecting)) { started = true; void fetch(); observer.disconnect(); }
    }, { rootMargin: '100px' });
    if (container.current) observer.observe(container.current);
    return () => { disposed = true; clearTimeout(timer); observer.disconnect(); };
  }, [message.id, conversationId, connected, attempt]);

  return <div ref={container} className={`line-media ${sticker ? 'sticker' : 'photo'}`}>
    {image ? <button className="media-open" aria-label={`${label}を拡大`} onClick={() => dialog.current?.showModal()}>
      <img src={image} alt={`LINEの${label}`} onLoad={onLoad} onError={() => { setImage(null); setLoading(false); }}/>
    </button> : <div className="media-placeholder" role="status"><span>{label}</span><small>{loading ? '読み込み中…' : connected ? `${label}を取得できませんでした` : 'LINEへ接続すると表示できます'}</small>
      {!loading && connected && <><small>保存期限や通信状態をご確認ください</small><button onClick={() => setAttempt(n => n + 1)}>再読み込み</button></>}
    </div>}
    <dialog ref={dialog} className="media-dialog" aria-label={`${label}の拡大表示`} onClick={e => { if (e.target === e.currentTarget) dialog.current?.close(); }}>
      <button className="media-close" aria-label="拡大表示を閉じる" onClick={() => dialog.current?.close()}>×</button>
      {image && <img src={image} alt={`拡大したLINEの${label}`}/>}
    </dialog>
  </div>;
}
