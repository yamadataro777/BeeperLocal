import { request } from './bridge';
import type { Conversation, Provider } from './types';

type Profile = { image: string | null; pending: boolean };
const images = new Map<string, string>();
const pending = new Map<string, Promise<Profile>>();
const generations = new Map<Provider, number>();
export const profileKey = (c: Conversation) => `${c.provider}:${c.id}:${c.avatarVersion ?? ''}`;
export const cachedProfile = (c: Conversation) => images.get(profileKey(c)) ?? null;
export function clearProfileCache(provider: Provider) {
  generations.set(provider, (generations.get(provider) ?? 0) + 1);
  for (const key of images.keys()) if (key.startsWith(`${provider}:`)) images.delete(key);
  for (const key of pending.keys()) if (key.startsWith(`${provider}:`)) pending.delete(key);
}
export async function fetchProfile(c: Conversation): Promise<Profile> {
  const key = profileKey(c), hit = images.get(key);
  if (hit) { images.delete(key); images.set(key, hit); return { image: hit, pending: false }; }
  const existing = pending.get(key);
  if (existing) return existing;
  const generation = generations.get(c.provider) ?? 0;
  const work = request<Profile>({ provider: c.provider, op: c.provider === 'slack' ? 'slack_profile' : 'avatar', conversationId: c.id }).then(value => {
    if (generation !== (generations.get(c.provider) ?? 0)) return { image: null, pending: false };
    if (value.image && /^data:image\/(jpeg|png|webp|gif);base64,/.test(value.image)) {
      images.set(key, value.image);
      while (images.size > 128) images.delete(images.keys().next().value!);
    }
    return value;
  }).finally(() => { if (pending.get(key) === work) pending.delete(key); });
  pending.set(key, work);
  return work;
}
