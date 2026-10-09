import { useEffect, useRef, useState } from 'react';
import { request } from './bridge';

type Profile = { name: string | null; image: string | null; pending: boolean };

export function SlackMessageProfile({ conversationId, messageId, connected, outgoing }: {
  conversationId: string; messageId: string; connected: boolean; outgoing: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [profile, setProfile] = useState<Profile>({ name: null, image: null, pending: false });
  useEffect(() => {
    let disposed = false, started = false, attempts = 0;
    let timer: ReturnType<typeof setTimeout>;
    const fetch = async () => {
      try {
        const next = await request<Profile>({ provider: 'slack', op: 'slack_profile', conversationId, messageId });
        if (disposed) return;
        setProfile(previous => ({ ...next, image: next.image ?? previous.image, name: next.name ?? previous.name }));
        if (next.pending && ++attempts < 120) timer = setTimeout(fetch, 500);
      } catch { /* Messages remain usable when profiles are unavailable. */ }
    };
    const observer = new IntersectionObserver(entries => {
      if (!started && entries.some(e => e.isIntersecting)) { started = true; void fetch(); observer.disconnect(); }
    }, { rootMargin: '80px' });
    if (ref.current) observer.observe(ref.current);
    return () => { disposed = true; clearTimeout(timer); observer.disconnect(); };
  }, [conversationId, messageId, connected]);
  const name = profile.name || (outgoing ? 'あなた' : 'Slackメンバー');
  return <div ref={ref} className="sender-profile"><span className="avatar compact">{profile.image
    ? <img src={profile.image} alt={`${name}のプロフィール画像`} onError={() => setProfile(p => ({ ...p, image: null }))}/>
    : Array.from(name)[0]}</span><span className="sender-name">{name}</span></div>;
}
