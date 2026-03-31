from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

import websockets


class PokerBotSDK:
    def __init__(self, api_key: str, ws_url: str) -> None:
        self.api_key = api_key
        self.ws_url = ws_url
        self.connection: Optional[websockets.WebSocketClientProtocol] = None
        self.current_match_id: Optional[str] = None
        self.current_turn_id: Optional[int] = None

    async def connect(self) -> None:
        self.connection = await websockets.connect(
            self.ws_url,
            extra_headers={"Authorization": f"Bearer {self.api_key}"},
        )
        await self.listen_forever()

    async def listen_forever(self) -> None:
        if self.connection is None:
            raise RuntimeError("Not connected")

        async for raw_message in self.connection:
            message = json.loads(raw_message)
            await self.on_message(message)

    async def on_message(self, message: Dict[str, Any]) -> None:
        msg_type = message.get("type")
        if msg_type == "your_turn":
            self.current_match_id = message.get("match_id")
            self.current_turn_id = message.get("turn_id")
            await self.on_turn(message.get("state", {}))
            return
        if msg_type == "action":
            await self.on_action(message)
            return
        if msg_type == "showdown":
            await self.on_showdown(message)
            return
        if msg_type == "timeout":
            await self.on_timeout(message)
            return
        await self.on_misc(message)

    async def on_turn(self, state: Dict[str, Any]) -> None:
        raise NotImplementedError("Override on_turn in your bot")

    async def on_action(self, message: Dict[str, Any]) -> None:
        print("Action:", message)

    async def on_showdown(self, message: Dict[str, Any]) -> None:
        print("Showdown:", message)

    async def on_timeout(self, message: Dict[str, Any]) -> None:
        print("Timeout:", message)

    async def on_misc(self, message: Dict[str, Any]) -> None:
        print("Event:", message)

    def get_legal_actions(self, state: Dict[str, Any]) -> list[str]:
        return state.get("legal_actions", [])

    def get_pot_size(self, state: Dict[str, Any]) -> int:
        return int(state.get("pot", 0))

    def get_stack_sizes(self, state: Dict[str, Any]) -> Dict[str, int]:
        stacks: Dict[str, int] = {}
        for player in state.get("players", []):
            player_id = player.get("id")
            if player_id is not None:
                stacks[str(player_id)] = int(player.get("stack", 0))
        return stacks

    async def submit_action(
        self, action: str, amount: Optional[int] = None
    ) -> None:
        if self.connection is None:
            raise RuntimeError("Not connected")
        if self.current_match_id is None or self.current_turn_id is None:
            raise RuntimeError("No active turn")

        payload: Dict[str, Any] = {
            "type": "action",
            "match_id": self.current_match_id,
            "turn_id": self.current_turn_id,
            "action": action,
        }
        if amount is not None:
            payload["amount"] = amount

        await self.connection.send(json.dumps(payload))

    async def fold(self) -> None:
        await self.submit_action("fold")

    async def check(self) -> None:
        await self.submit_action("check")

    async def call(self) -> None:
        await self.submit_action("call")

    async def bet(self, amount: int) -> None:
        await self.submit_action("bet", amount=amount)

    async def raise_to(self, amount: int) -> None:
        await self.submit_action("raise_to", amount=amount)


class PassiveBot(PokerBotSDK):
    async def on_turn(self, state: Dict[str, Any]) -> None:
        legal = self.get_legal_actions(state)
        if "check" in legal:
            await self.check()
        elif "call" in legal:
            await self.call()
        else:
            await self.fold()


async def main() -> None:
    bot = PassiveBot(api_key="dev-key-1", ws_url="ws://localhost:8000/v1/ws")
    await bot.connect()


if __name__ == "__main__":
    asyncio.run(main())
