from ape import Contract, chain
from ape.contracts.base import ContractInstance
from ape.types import ContractLog
from ape_ethereum import multicall
from silverback import SilverbackBot, StateSnapshot

from bot.config import auctions, chain_key, explorer_base_url, factories, safe_name
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

    # FOR TESTS
    for factory in factories():
        # # TEST on_deployed_new_auction
        # logs = list(factory.DeployedNewAuction.range(22745429, 22978002))
        # for log in logs:
        #     await on_deployed_new_auction(log)

        # TEST on_auction_kicked
        for auction in auctions(factory):
            event = auction._events_["AuctionKicked"][0]
            logs = list(event.range(23120295, 23120559))
            for log in logs:
                await on_auction_kicked(log, auction=auction)


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

        @bot.on_(auction._events_["AuctionKicked"][0])  # For some strange reason can't use `auction.AuctionKicked`
        async def on_auction_kicked(event: ContractLog, auction: ContractInstance = auction) -> None:
            from_token = Contract(event.get("from"))
            available = int(event.available)

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
                f"<a href='{explorer_base_url()}{auction.address}'>🔗 View Auction</a>"
            )
