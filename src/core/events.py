import asyncio
from typing import Callable, Awaitable, List

class EventBus:
    def __init__(self):
        self._subscribers: List[Callable[[dict], Awaitable[None]]] = []

    def subscribe(self, callback: Callable[[dict], Awaitable[None]]):
        self._subscribers.append(callback)

    async def publish(self, event: dict):
        for subscriber in self._subscribers:
            asyncio.create_task(subscriber(event))

event_bus = EventBus()
