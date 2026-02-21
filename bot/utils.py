import json
import os
from datetime import datetime
from typing import Any, Dict, cast

from bot.tg import ERROR_GROUP_CHAT_ID, notify_group_chat

DEBUG = os.getenv("DEBUG", False)


# =============================================================================
# State
# =============================================================================


def _load() -> Dict[str, Any]:
    try:
        with open("bot/state.json") as f:
            return cast(Dict[str, Any], json.load(f))
    except FileNotFoundError:
        return {"active_auctions": [], "last_take_check_block": 0}


def _save(state: Dict[str, Any]) -> None:
    with open("bot/state.json", "w") as f:
        json.dump(state, f)


def get_active_auctions() -> list:
    return _load()["active_auctions"]


def add_auction(auction_addr: str, token_addr: str) -> None:
    state = _load()
    pair = [auction_addr, token_addr]
    if pair not in state["active_auctions"]:
        state["active_auctions"].append(pair)
        _save(state)


def remove_auction(pair: list) -> None:
    state = _load()
    state["active_auctions"].remove(pair)
    _save(state)


def get_last_take_check_block() -> int:
    return _load()["last_take_check_block"]


def set_last_take_check_block(block: int) -> None:
    state = _load()
    state["last_take_check_block"] = block
    _save(state)


# =============================================================================
# Helpers
# =============================================================================


async def debug(msg: str) -> None:
    if DEBUG:
        print(f"DEBUG: {msg}. Time: {datetime.now()}")
        await notify_group_chat(f"DEBUG: {msg}", chat_id=ERROR_GROUP_CHAT_ID)


def decode_auction_kicked(tx_hash: str, log_index: int, address: str) -> Dict[str, Any]:
    from ape import networks
    from web3._utils.events import get_event_data

    AUCTION_KICKED_ABI = {
        "anonymous": False,
        "name": "AuctionKicked",
        "type": "event",
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": False, "name": "available", "type": "uint256"},
        ],
    }

    w3 = networks.active_provider.web3
    receipt = w3.eth.get_transaction_receipt(tx_hash)

    try:
        raw_log = next(
            log for log in receipt["logs"] if log["logIndex"] == log_index and log["address"].lower() == address.lower()
        )
    except StopIteration:
        raise ValueError("Matching AuctionKicked log not found in receipt")

    return cast(Dict[str, Any], get_event_data(w3.codec, AUCTION_KICKED_ABI, raw_log)["args"])
