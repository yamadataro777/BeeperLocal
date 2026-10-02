import { useEffect, useRef, useState } from 'react';
import { request } from './bridge';
import type { Conversation } from './types';
export function Avatar({ conversation, compact = false, tone = 0, connected = true }: { conversation: Conversation; compact?: boolean; tone?: number; connected?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [image, setImage] = useState<string | null>(null);
  useEffect(() => {
    setImage(null);
    if (conversation.provider !== 'line' || !conversation.avatarVersion || !connected) return;
    let disposed = false, started = false, attempts = 0;
    let timer: ReturnType<typeof setTimeout>;
    const fetch = async () => {
      try {
        const result = await request<{ image: string | null; pending: boolean }>({ op: 'avatar', conversationId: conversation.id });
        if (disposed) return;
        if (result.image) setImage(result.image);
        else if (result.pending && ++attempts < 120) timer = setTimeout(fetch, 500);
      } catch { /* Initials remain available when a profile image cannot be fetched. */ }
    };
    const observer = new IntersectionObserver(entries => {
      if (!started && entries.some(e => e.isIntersecting)) { started = true; void fetch(); observer.disconnect(); }
    }, { rootMargin: '80px' });
    if (ref.current) observer.observe(ref.current);
    return () => { disposed = true; clearTimeout(timer); observer.disconnect(); };
  }, [conversation.id, conversation.avatarVersion, connected]);
  return <span ref={ref} className={`avatar tone-${tone % 4} ${compact ? 'compact' : ''}`}>{image ? <img src={image} alt={`${conversation.title}のプロフィール画像`} onError={() => setImage(null)}/> : Array.from(conversation.title.trim())[0] || 'L'}</span>;
}
