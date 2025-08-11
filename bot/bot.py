from ape import Contract, chain
from ape.types import ContractLog
from ape_ethereum import multicall
from silverback import SilverbackBot, StateSnapshot

from bot.config import chain_key, explorer_base_url, factories, safe_name
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


@bot.on_shutdown()
async def bot_shutdown() -> None:
    await notify_group_chat(
        f"🔴  <b>{chain_key()} yKicks bot shutdown successfully</b>",
        chat_id=ERROR_GROUP_CHAT_ID,
    )


# =============================================================================
# Chain Events
# =============================================================================


for factory in factories():

    @bot.on_(factory.DeployedNewAuction)
    async def on_deployed_new_auction(event: ContractLog) -> None:
        print(event)
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
