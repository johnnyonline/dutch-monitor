from ape import Contract, chain
from ape.contracts.base import ContractInstance
from ape.types import ContractLog
from ape_ethereum import multicall
from silverback import SilverbackBot, StateSnapshot

from bot.config import auctions, chain_key, enabled, explorer_base_url, factories, safe_name
from bot.tg import ERROR_GROUP_CHAT_ID, notify_group_chat

# =============================================================================
# Bot Configuration & Constants
# =============================================================================


bot = SilverbackBot()


# =============================================================================
# Startup / Shutdown
# =============================================================================


@bot.on_startup()
async def bot_startup(startup_state: StateSnapshot) -> None:
    await notify_group_chat(
        f"🟢 🥾 <b>{chain_key()} yKicks bot started successfully</b>",
        chat_id=ERROR_GROUP_CHAT_ID,
    )

    # TESTS

    # TEST on_deployed_new_auction
    # for factory in factories():
    # # TEST on_deployed_new_auction
    # logs = list(factory.DeployedNewAuction.range(22745429, 22978002))
    # for log in logs:
    #     await on_deployed_new_auction(log)

    # # TEST on_auction_kicked
    # for factory in factories():
    #     for auction in auctions(factory):
    #         event = auction._events_["AuctionKicked"][0]
    #         logs = list(event.range(23120295, 23120559))
    #         for log in logs:
    #             await on_auction_kicked(log, auction=auction)

    # # @todo -- here -- (1) test partial take (2) add expired no take (add to db on kick and remove on full take. then check kickable > 0, every 1 hour or so) (3) link txns instead of auction address
    # # TEST on_auction_take
    # for factory in factories():
    #     for auction in auctions(factory):
    #         want = Contract(auction.want())
    #         for token in enabled(auction):
    #             event = token._events_["Transfer"][0]
    #             logs = list(event.range(23120586, 23120588))
    #             for log in logs:
    #                 if log.get(event.abi.inputs[0].name) == auction.address:
    #                     await on_auction_take(log, auction=auction, token=token, want=want)


@bot.on_shutdown()
async def bot_shutdown() -> None:
    await notify_group_chat(
        f"🔴 🥾 <b>{chain_key()} yKicks bot shutdown successfully</b>",
        chat_id=ERROR_GROUP_CHAT_ID,
    )


# =============================================================================
# Chain Events
# =============================================================================


for factory in factories():

    @bot.on_(factory.DeployedNewAuction)
    async def on_deployed_new_auction(event: ContractLog) -> None:
        auction = Contract(event.auction)
        want = Contract(event.want)

        # Figure out the deployer address
        receipt = chain.provider.get_receipt(event.transaction_hash)
        deployer_addr = receipt.sender

        # Multicall for symbol + receiver
        want_symbol, receiver_addr = multicall.Call().add(want.symbol).add(auction.receiver)()

        await notify_group_chat(
            f"👀 <b>New Auction Deployed!</b>\n\n"
            f"<b>Want:</b> {want_symbol}\n"
            f"<b>Receiver:</b> {safe_name(receiver_addr)}\n"
            f"<b>Deployer:</b> {safe_name(deployer_addr)}\n\n"
            f"<a href='{explorer_base_url()}{auction.address}'>🔗 View Auction</a>"
        )

    for auction in auctions(factory):
        # Get the want token
        want = Contract(auction.want())

        @bot.on_(auction._events_["AuctionKicked"][0])  # For some strange reason can't use auction.AuctionKicked
        async def on_auction_kicked(event: ContractLog, auction: ContractInstance = auction) -> None:
            from_token = Contract(event.get("from"))
            available = int(event.available)

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
                f"<a href='{explorer_base_url()}{auction.address}'>🔗 View Auction</a>"
            )

        for token in enabled(auction):
            # Also for some strange reason can't always use token.Transfer
            event = token._events_["Transfer"][0]
            first_arg = event.abi.inputs[0].name  # from/_from/sender/whatever else smart devs thought of

            @bot.on_(event, filter_args={first_arg: auction.address})
            async def on_auction_take(
                event: ContractLog,
                auction: ContractInstance = auction,
                token: ContractInstance = token,
                want: ContractInstance = want,
            ) -> None:
                # Who took + how much
                _, taker, amount = (event.get(event.abi.inputs[i].name) for i in range(3))

                # Multicall
                call = multicall.Call()
                call.add(token.symbol)
                call.add(token.decimals)
                call.add(want.symbol)
                call.add(auction.available, token.address)
                call.add(auction.receiver)
                from_symbol, from_decimals, want_symbol, available, receiver = call()

                # If still has available tokens, notify with the “partially taken” message
                if int(available) > 0:
                    await notify_group_chat(
                        f"😐 <b>Auction partially taken!</b>\n\n"
                        f"<b>Swap:</b> {from_symbol} ➙ {want_symbol}\n"
                        f"<b>Remaining:</b> {int(available) / (10 ** int(from_decimals)):.5f} {from_symbol}\n"
                        f"<b>Taker:</b> {safe_name(taker)}\n"
                        f"<b>Receiver:</b> {safe_name(receiver)}\n\n"
                        f"<a href='{explorer_base_url()}{auction.address}'>🔗 View Auction</a>"
                    )
                else:
                    await notify_group_chat(
                        f"🥳 <b>Auction fully taken!</b>\n\n"
                        f"<b>Swap:</b> {from_symbol} ➙ {want_symbol}\n"
                        f"<b>Amount:</b> {amount / (10 ** int(from_decimals)):.2f} {from_symbol}\n"
                        f"<b>Taker:</b> {safe_name(taker)}\n"
                        f"<b>Receiver:</b> {safe_name(receiver)}\n\n"
                        f"<a href='{explorer_base_url()}{auction.address}'>🔗 View Auction</a>"
                    )
