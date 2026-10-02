"""Read-only bundled-Core smoke. Only counts, booleans and fixed codes leave this process."""
import asyncio
import json
from pathlib import Path
import sys

async def main():
    bundle = Path(sys.argv[1]).resolve()
    p = await asyncio.create_subprocess_exec(str(bundle/'Contents/MacOS/beeperlocal-core'),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, limit=8*1024*1024)
    result = {'login_started':False, 'messages_sent':0}
    async def call(i, request):
        p.stdin.write((json.dumps({'id':i,'request':request})+'\n').encode())
        await p.stdin.drain()
        while True:
            raw = await asyncio.wait_for(p.stdout.readline(),120)
            if not raw: raise RuntimeError('IPC_STOPPED')
            data = json.loads(raw)
            if data.get('id') == i: return data
            if data.get('event') == 'fatal': raise RuntimeError('CORE_FATAL')
    try:
        ping = await call(1, {'op':'ping'})
        result['ping'] = ping.get('result')
        snap = await call(2, {'op':'snapshot'})
        result['saved_conversation_count'] = len(snap.get('result',{}).get('conversations',[]))
        result['snapshot_error'] = snap.get('error')
        login = await call(3, {'op':'line_login_status'})
        result['login_stage'] = login.get('result',{}).get('stage')
        connection = await call(4, {'op':'connect'})
        result['connect_ok'] = connection.get('ok')
        result['connect_error'] = connection.get('error')
        rows = connection.get('result',{}).get('conversations',[])
        result['current_conversation_count'] = len(rows)
        times = [r['lastMessageAt'] for r in rows if r.get('lastMessageAt')]
        result['dated_conversation_count'] = len(times)
        result['ordered_descending'] = times == sorted(times,reverse=True)
        result['profile_image_count'] = sum(bool(r.get('avatarVersion')) for r in rows)
        sample = [r for r in rows if r.get('avatarVersion')][:3]
        loaded = 0
        sequence = 5
        for record in sample:
            for attempt in range(40):
                sequence += 1
                avatar = await call(sequence, {'op':'avatar','conversationId':record['id']})
                value = avatar.get('result', {})
                if value.get('image'):
                    loaded += 1
                    break
                if not value.get('pending'): break
                await asyncio.sleep(.25)
        result['image_sample_attempted'] = len(sample)
        result['image_sample_loaded'] = loaded
    except Exception:
        result['smoke_error'] = 'IPC_SMOKE_FAILED'
    finally:
        p.stdin.close()
        try: await asyncio.wait_for(p.wait(),15)
        except TimeoutError: p.terminate(); await p.wait()
    print(json.dumps(result))
    if len(sys.argv)>2: Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')

asyncio.run(main())
