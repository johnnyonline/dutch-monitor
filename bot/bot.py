import os
from datetime import datetime
from typing import Any, Dict, cast

from ape import Contract, chain
from ape.types import ContractLog
from ape_ethereum import multicall
from silverback import SilverbackBot, StateSnapshot
from silverback.exceptions import CircuitBreaker

from bot.config import auctions, chain_key, enabled, explorer_address_url, explorer_tx_url, factories, safe_name
from bot.tg import ERROR_GROUP_CHAT_ID, notify_group_chat

# =============================================================================
# Bot Configuration & Constants
# =============================================================================


bot = SilverbackBot()

DEBUG = os.getenv("DEBUG", False)
DAILY_RESTART_CRON = os.getenv("DAILY_RESTART_CRON", "30 13 * * *")  # every day at 13:30 UTC
EXPIRED_AUCTION_CRON = os.getenv("EXPIRED_AUCTION_CRON", "0 * * * *")  # every hour


# =============================================================================
# Startup / Shutdown
# =============================================================================


@bot.on_startup()
async def bot_startup(startup_state: StateSnapshot) -> None:
    await notify_group_chat(
        f"🟢 🥾 <b>{chain_key()} dutch bot started successfully</b>",
        chat_id=ERROR_GROUP_CHAT_ID,
    )

    # Set `bot.state` values
    bot.state.active_auctions = []

    # TESTS

    # # TEST on_deployed_new_auction
    # for factory in factories():
    #     # logs = list(factory.DeployedNewAuction.range(22745429, 22978002))
    #     # logs = list(factory.DeployedNewAuction.range(21378342, 21378344))  # legacy factory
    #     logs = list(factory.DeployedNewAuction.range(358476615, 358476617))  # arbi
    #     for log in logs:
    #         await on_deployed_new_auction(log)

    # # TEST on_auction_kicked
    # for factory in factories():
    #     for auction in auctions(factory):
    #         event = auction._events_["AuctionKicked"][0]
    #         # logs = list(event.range(23120295, 23120559))
    #         # logs = list(event.range(23148631, 23148633))  # legacy factory
    #         logs = list(event.range(23156665, 23156667))
    #         for log in logs:
    #             await on_auction_kicked(log)

    # # TEST on_auction_take
    # for factory in factories():
    #     for auction in auctions(factory):
    #         for token in enabled(auction):
    #             event = token._events_["Transfer"][0]
    #             logs = list(event.range(23126809, 23126811))
    #             for log in logs:
    #                 if log.get(event.abi.inputs[0].name) == auction.address:
    #                     await on_auction_take(log, token=token)


@bot.on_shutdown()
async def bot_shutdown() -> None:
    await notify_group_chat(
        f"🔴 🥾 <b>{chain_key()} dutch bot shutdown successfully</b>",
        chat_id=ERROR_GROUP_CHAT_ID,
    )


# =============================================================================
# Chain Events
# =============================================================================


for factory in factories():

    @bot.on_(factory.DeployedNewAuction)
    async def on_deployed_new_auction(event: ContractLog) -> None:
        await debug("working on on_deployed_new_auction...")

        auction = Contract(event.auction)
        want = Contract(event.want)

        # Figure out the deployer address
        receipt = chain.provider.get_receipt(event.transaction_hash)
        deployer = receipt.sender

        # Multicall for symbol + receiver
        want_symbol, receiver = multicall.Call().add(want.symbol).add(auction.receiver)()

        await notify_group_chat(
            f"👀 <b>New Auction Deployed!</b>\n\n"
            f"<b>Want:</b> {want_symbol}\n"
            f"<b>Receiver:</b> {safe_name(receiver)}\n"
            f"<b>Deployer:</b> {safe_name(deployer)}\n\n"
            f"<a href='{explorer_address_url()}{auction.address}'>🔗 View Auction</a>"
        )

    for auction in auctions(factory):

        @bot.on_(auction._events_["AuctionKicked"][0])  # For some strange reason can't use auction.AuctionKicked
        async def on_auction_kicked(event: ContractLog) -> None:
            await debug("working on on_auction_kicked...")

            # Cache the auction contract
            auction = Contract(event.contract_address)

            # Handle weirdness of event decoding
            try:
                from_token = Contract(event.get("from"))
                available = int(event.available)
            except Exception:
                args = decode_auction_kicked(event.transaction_hash, event.log_index, event.contract_address)
                from_token = Contract(args["from"])
                available = int(args["available"])

            # Get the want token
            want = Contract(auction.want())

            # Multicall for symbol + decimals
            call = multicall.Call()
            call.add(from_token.symbol)
            call.add(from_token.decimals)
            call.add(want.symbol)
            from_symbol, from_decimals, want_symbol = call()

            await notify_group_chat(
                f"🥾 <b>Auction kicked!</b>\n\n"
                f"<b>Swap:</b> {from_symbol} ➙ {want_symbol}\n"
                f"<b>Available:</b> {available / (10 ** int(from_decimals)):.2f} {from_symbol}\n\n"
                f"<a href='{explorer_tx_url()}{event.transaction_hash}'>🔗 View Transaction</a>"
            )

            # Keep track of active auctions
            pair = (auction, from_token)
            if pair not in bot.state.active_auctions:
                bot.state.active_auctions.append(pair)

        for token in enabled(auction):
            # Also for some strange reason can't always use token.Transfer
            event = token._events_["Transfer"][0]
            first_arg = event.abi.inputs[0].name  # from/_from/sender/whatever else smart devs thought of

            @bot.on_(event, filter_args={first_arg: auction.address})
            async def on_auction_take(event: ContractLog) -> None:
                await debug("working on on_auction_take...")

                # From and who took + how much
                auction, taker, amount = (event.get(event.abi.inputs[i].name) for i in range(3))

                # The from token
                token = Contract(event.contract_address)

                # Initialize the auction variable
                auction = Contract(auction)

                # Get the want token
                want = Contract(auction.want())

                # Multicall
                call = multicall.Call()
                call.add(token.symbol)
                call.add(token.decimals)
                call.add(want.symbol)
                call.add(auction.available, token.address)
                call.add(auction.receiver)
                from_symbol, from_decimals, want_symbol, available, receiver = call()

                if int(available) > 0:
                    # If still has available tokens, notify with the “partially taken” message
                    await notify_group_chat(
                        f"😐 <b>Auction partially taken!</b>\n\n"
                        f"<b>Swap:</b> {from_symbol} ➙ {want_symbol}\n"
                        f"<b>Remaining:</b> {int(available) / (10 ** int(from_decimals)):.5f} {from_symbol}\n"
                        f"<b>Taker:</b> {safe_name(taker)}\n"
                        f"<b>Receiver:</b> {safe_name(receiver)}\n\n"
                        f"<a href='{explorer_tx_url()}{event.transaction_hash}'>🔗 View Transaction</a>"
                    )
                else:
                    # Otherwise, notify with the “fully taken” message
                    await notify_group_chat(
                        f"🥳 <b>Auction fully taken!</b>\n\n"
                        f"<b>Swap:</b> {from_symbol} ➙ {want_symbol}\n"
                        f"<b>Amount:</b> {amount / (10 ** int(from_decimals)):.2f} {from_symbol}\n"
                        f"<b>Taker:</b> {safe_name(taker)}\n"
                        f"<b>Receiver:</b> {safe_name(receiver)}\n\n"
                        f"<a href='{explorer_tx_url()}{event.transaction_hash}'>🔗 View Transaction</a>"
                    )

                    # Remove from tracking if present
                    pair = (auction, token)
                    if pair in bot.state.active_auctions:
                        bot.state.active_auctions.remove(pair)


# =============================================================================
# Cron Jobs
# =============================================================================


@bot.cron(DAILY_RESTART_CRON)
async def daily_restart(time: datetime) -> None:
    # Trigger bot shutdown so it restarts and re-subscribes to include any newly deployed auctions
    # NOTE: The actual restart happens only because our docker compose is configured to restart the container on exit
    raise CircuitBreaker("New auction deployed, restarting bot to subscribe.")


@bot.cron(EXPIRED_AUCTION_CRON)
async def check_expired_with_available(time: datetime) -> None:
    # Skip if no active auctions
    if not bot.state.active_auctions:
        return

    # Build multicall for all `kickable(from_token.address)`
    call = multicall.Call()
    for auction, from_token in bot.state.active_auctions:
        call.add(auction.kickable, from_token.address)

    # Execute multicall
    results = call()

    # Iterate over results alongside active_auctions
    for (auction, from_token), kickable in zip(bot.state.active_auctions[:], results):
        kickable = int(kickable)
        if kickable > 0:
            from_symbol, from_decimals, want_symbol = (
                multicall.Call().add(from_token.symbol).add(from_token.decimals).add(Contract(auction.want()).symbol)()
            )
            await notify_group_chat(
                f"🫠 <b>Auction expired with available tokens!</b>\n\n"
                f"<b>Swap:</b> {from_symbol} ➙ {want_symbol}\n"
                f"<b>Available:</b> {kickable / 10 ** int(from_decimals):.5f} {from_symbol}\n\n"
                f"<a href='{explorer_address_url()}{auction.address}'>🔗 View Auction</a>"
            )

            # Remove from tracking
            bot.state.active_auctions.remove((auction, from_token))


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
