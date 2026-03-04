from ape.contracts.base import ContractContainer
from ethpm_types import ContractType

# Anonymous event sources (not bound to a specific address, so from_addresses is respected)

factory_events = ContractContainer(
    ContractType(
        abi=[
            {
                "anonymous": False,
                "name": "DeployedNewAuction",
                "type": "event",
                "inputs": [
                    {"indexed": True, "name": "auction", "type": "address"},
                    {"indexed": True, "name": "want", "type": "address"},
                ],
            }
        ]
    )
)

auction_events = ContractContainer(
    ContractType(
        abi=[
            {
                "anonymous": False,
                "name": "AuctionKicked",
                "type": "event",
                "inputs": [
                    {"indexed": True, "name": "from", "type": "address"},
                    {"indexed": False, "name": "available", "type": "uint256"},
                ],
            }
        ]
    )
)
