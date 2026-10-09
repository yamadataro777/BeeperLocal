import { useEffect, useRef, useState } from 'react';
import { request } from './bridge';
import type { Message, Provider } from './types';

export function AttachmentMedia({ message, provider, conversationId, connected, onLoad }: { message: Message; provider: Provider; conversationId: string; connected: boolean; onLoad?: () => void }) {
  return <div className="attachment-list">{message.attachments?.map(a => <Attachment key={`${message.id}:${a.index}`} attachment={a} provider={provider} conversationId={conversationId} messageId={message.id} connected={connected} onLoad={onLoad}/>)}</div>;
}
function Attachment({ attachment, provider, conversationId, messageId, connected, onLoad }: { attachment: NonNullable<Message['attachments']>[number]; provider: Provider; conversationId: string; messageId: string; connected: boolean; onLoad?: () => void }) {
  const [media, setMedia] = useState('');
  const [state, setState] = useState('idle');
  const generation = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const label = { image: '画像', video: '動画', audio: '音声', file: 'ファイル' }[attachment.kind];
  useEffect(() => () => { generation.current++; clearTimeout(timer.current); }, []);
  useEffect(() => { if (attachment.local) void load(); }, [messageId, attachment.local]);
  async function load() {
    const current = ++generation.current;
    setState('loading');
    const until = Date.now() + 45000;
    async function poll(retry = false) {
      try {
        const result = await request<{ media: string | null; pending: boolean }>({ provider, op: 'attachment_media', conversationId, messageId, index: attachment.index, retry });
        if (current !== generation.current) return;
        if (result.media) { setMedia(result.media); setState('ready'); }
        else if (result.pending && Date.now() < until) timer.current = setTimeout(() => void poll(), 500);
        else setState('unavailable');
      } catch { if (current === generation.current) setState('unavailable'); }
    }
    await poll(true);
  }
  return <div className="attachment">{media ? attachment.kind === 'image' ? <img src={media} alt={attachment.name || '添付画像'} onLoad={onLoad}/> : attachment.kind === 'video' ? <video src={media} controls preload="metadata" onLoadedMetadata={onLoad}/> : <audio src={media} controls preload="metadata"/> : <><button className="secondary" disabled={(!connected && !attachment.local) || state === 'loading' || attachment.kind === 'file'} onClick={() => void load()}>{state === 'loading' ? '読み込み中…' : `${label}を表示`}</button>{attachment.name && <span>{attachment.name}</span>}{state === 'unavailable' && <p>取得できません。容量上限（4MB）・形式・配信期限を確認してください。</p>}{attachment.kind === 'file' && <p>この形式のプレビューには未対応です。</p>}</>}</div>;
}
