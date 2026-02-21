import os
from datetime import datetime

from ape import Contract, chain
from ape.types import ContractLog
from ape_ethereum import multicall
from silverback import SilverbackBot, StateSnapshot
from silverback.exceptions import CircuitBreaker

from bot.config import auctions, chain_key, explorer_address_url, explorer_tx_url, factories, safe_name
from bot.tg import ERROR_GROUP_CHAT_ID, notify_group_chat
from bot.utils import (
    add_auction,
    debug,
    decode_auction_kicked,
    get_active_auctions,
    get_last_take_check_block,
    remove_auction,
    set_last_take_check_block,
)

# =============================================================================
# Bot Configuration & Constants
# =============================================================================


bot = SilverbackBot()

DAILY_RESTART_CRON = os.getenv("DAILY_RESTART_CRON", "30 13 * * *")  # every day at 13:30 UTC
CHECK_EXPIRED_CRON = os.getenv("CHECK_EXPIRED_CRON", "0 * * * *")  # every hour
CHECK_TAKES_CRON = os.getenv("CHECK_TAKES_CRON", "*/3 * * * *")  # every 3 minutes


# =============================================================================
# Startup / Shutdown
# =============================================================================


@bot.on_startup()
async def bot_startup(startup_state: StateSnapshot) -> None:
    await notify_group_chat(
        f"🟢 🥾 <b>{chain_key()} dutch bot started successfully</b>",
        chat_id=ERROR_GROUP_CHAT_ID,
    )

    # TESTS

    # # TEST on_deployed_new_auction
    # for factory in factories():
    #     logs = list(factory.DeployedNewAuction.range(24491720, 24491837))
    #     # logs = list(factory.DeployedNewAuction.range(21378342, 21378344))  # legacy factory
    #     # logs = list(factory.DeployedNewAuction.range(428591079, 428591081))  # arbi
    #     # logs = list(factory.DeployedNewAuction.range(34043016, 34043018))  # base
    #     for log in logs:
    #         await on_deployed_new_auction(log)

    # # TEST on_auction_kicked
    # for factory in factories():
    #     for auction in auctions(factory):
    #         event = auction._events_["AuctionKicked"][0]
    #         logs = list(event.range(24491900, 24491906))
    #         # logs = list(event.range(23148631, 23148633))  # legacy factory
    #         # logs = list(event.range(412036835, 412036837))
    #         for log in logs:
    #             await on_auction_kicked(log)

    # # TEST on_auction_take
    # for factory in factories():
    #     for auction in auctions(factory):
    #         for token in enabled(auction):
    #             event = token._events_["Transfer"][0]
    #             logs = list(event.range(24491948, 24491952))
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


_factories = factories()
_all_auctions = [auction for factory in _factories for auction in auctions(factory)]


@bot.on_(_factories[0].DeployedNewAuction, from_addresses=_factories)
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
        f"<b>Deployer:</b> {safe_name(deployer)}\n"
        f"<b>Network:</b> {chain_key()}\n\n"
        f"<a href='{explorer_address_url()}{auction.address}'>🔗 View Auction</a>"
    )


if _all_auctions:

    @bot.on_(_all_auctions[0].AuctionKicked, from_addresses=_all_auctions)
    async def on_auction_kicked(event: ContractLog) -> None:
        await debug("working on on_auction_kicked...")

        # Cache the auction contract
        auction = Contract(event.contract_address)

        # Handle weirdness of event decoding
        try:
            from_token = Contract(event.get("from"), abi="bot/abis/erc20.json")
            available = int(event.available)
        except Exception:
            args = decode_auction_kicked(event.transaction_hash, event.log_index, event.contract_address)
            from_token = Contract(args["from"], abi="bot/abis/erc20.json")
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
            f"<b>Available:</b> {available / (10 ** int(from_decimals)):.2f} {from_symbol}\n"
            f"<b>Network:</b> {chain_key()}\n\n"
            f"<a href='{explorer_tx_url()}{event.transaction_hash}'>🔗 View Transaction</a>"
        )

        # Keep track of active auctions
        add_auction(auction.address, from_token.address)


# =============================================================================
# Cron Jobs
# =============================================================================


@bot.cron(DAILY_RESTART_CRON)
async def daily_restart(time: datetime) -> None:
    # Trigger bot shutdown so it restarts and re-subscribes to include any newly deployed auctions
    # NOTE: The actual restart happens only because our docker compose is configured to restart the container on exit
    raise CircuitBreaker("New auction deployed, restarting bot to subscribe.")


@bot.cron(CHECK_EXPIRED_CRON)
async def check_expired_with_available(time: datetime) -> None:
    active = get_active_auctions()
    if not active:
        return

    # Reconstruct contracts
    pairs = [(Contract(a), Contract(t, abi="bot/abis/erc20.json")) for a, t in active]

    # Build multicall for all `kickable(from_token.address)`
    call = multicall.Call()
    for auction, from_token in pairs:
        call.add(auction.kickable, from_token.address)

    for (auction, from_token), addr_pair, kickable in zip(pairs, active[:], call()):
        if int(kickable) <= 0:
            continue

        from_symbol, from_decimals, want_symbol = (
            multicall.Call().add(from_token.symbol).add(from_token.decimals).add(Contract(auction.want()).symbol)()
        )
        await notify_group_chat(
            f"🫠 <b>Auction expired with available tokens!</b>\n\n"
            f"<b>Swap:</b> {from_symbol} ➙ {want_symbol}\n"
            f"<b>Available:</b> {int(kickable) / 10 ** int(from_decimals):.5f} {from_symbol}\n"
            f"<b>Network:</b> {chain_key()}\n\n"
            f"<a href='{explorer_address_url()}{auction.address}'>🔗 View Auction</a>"
        )

        remove_auction(addr_pair)


@bot.cron(CHECK_TAKES_CRON)
async def check_auction_takes(time: datetime) -> None:
    current_block = chain.blocks.head.number
    last_block = get_last_take_check_block() or current_block
    set_last_take_check_block(current_block)

    active = get_active_auctions()
    if not active or current_block <= last_block:
        return

    for addr_pair in active[:]:
        auction = Contract(addr_pair[0])
        from_token = Contract(addr_pair[1], abi="bot/abis/erc20.json")

        event = from_token._events_["Transfer"][0]
        first_arg = event.abi.inputs[0].name

        logs = list(event.range(last_block + 1, current_block, search_topics={first_arg: auction.address}))
        for log in logs:
            # Extract taker and amount
            taker = log[event.abi.inputs[1].name]
            amount = int(log[event.abi.inputs[2].name])

            # Get the want token
            want = Contract(auction.want())

            # Multicall
            call = multicall.Call()
            call.add(from_token.symbol)
            call.add(from_token.decimals)
            call.add(want.symbol)
            call.add(auction.available, from_token.address)
            call.add(auction.receiver)
            from_symbol, from_decimals, want_symbol, available, receiver = call()

            if int(available) > 0:
                await notify_group_chat(
                    f"😐 <b>Auction partially taken!</b>\n\n"
                    f"<b>Swap:</b> {from_symbol} ➙ {want_symbol}\n"
                    f"<b>Remaining:</b> {int(available) / (10 ** int(from_decimals)):.5f} {from_symbol}\n"
                    f"<b>Taker:</b> {safe_name(taker)}\n"
                    f"<b>Receiver:</b> {safe_name(receiver)}\n"
                    f"<b>Network:</b> {chain_key()}\n\n"
                    f"<a href='{explorer_tx_url()}{log.transaction_hash}'>🔗 View Transaction</a>"
                )
            else:
                await notify_group_chat(
                    f"🥳 <b>Auction fully taken!</b>\n\n"
                    f"<b>Swap:</b> {from_symbol} ➙ {want_symbol}\n"
                    f"<b>Amount:</b> {amount / (10 ** int(from_decimals)):.2f} {from_symbol}\n"
                    f"<b>Taker:</b> {safe_name(taker)}\n"
                    f"<b>Receiver:</b> {safe_name(receiver)}\n"
                    f"<b>Network:</b> {chain_key()}\n\n"
                    f"<a href='{explorer_tx_url()}{log.transaction_hash}'>🔗 View Transaction</a>"
                )

                # Remove from tracking
                remove_auction(addr_pair)
                break  # NOTE: will not notify about multiple takes within the same block
