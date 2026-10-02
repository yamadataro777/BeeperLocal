"""Cancellable retry waits that expire promptly after the Mac wakes up."""
import asyncio
import time


async def wait_for_retry(delay: float):
    # macOS monotonic timers can pause during sleep. Wall time also bounds the
    # wait, while the monotonic deadline prevents a clock correction extending it.
    wall_deadline = time.time() + delay
    monotonic_deadline = time.monotonic() + delay
    while True:
        remaining = min(wall_deadline - time.time(),
                        monotonic_deadline - time.monotonic())
        if remaining <= 0:
            return
        await asyncio.sleep(min(remaining, 5))
