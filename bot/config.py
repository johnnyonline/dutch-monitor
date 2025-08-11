from collections.abc import Mapping, Sequence
from typing import TypedDict, cast

from ape import Contract, chain, networks
from ape.contracts.base import ContractInstance


class NetworkCfg(TypedDict):
    factories: Sequence[str]
    explorer: str
    known_addresses: dict[str, str]


NETWORKS: Mapping[str, NetworkCfg] = {
    "ethereum": {
        "factories": [
            "0xCfA510188884F199fcC6e750764FAAbE6e56ec40",
            "0xa3A3702d81Fd317FA1B8735227e29dc756C976C5",
        ],
        "explorer": "https://etherscan.io/address/",
        "known_addresses": {
            "0xEf77cc176c748d291EfB6CdC982c5744fC7211c8": "yRoboTreasury",
            "0x16388463d60FFE0661Cf7F1f31a7D658aC790ff7": "SMS",
        },
    },
    "base": {
        "factories": [
            "0xCfA510188884F199fcC6e750764FAAbE6e56ec40",
        ],
        "explorer": "https://basescan.org/address/",
        "known_addresses": {},
    },
}


def chain_key() -> str:
    return cast(str, chain.provider.network.ecosystem.name.lower())


def cfg() -> NetworkCfg:
    return NETWORKS.get(chain_key(), NETWORKS["ethereum"])


def factories() -> list[ContractInstance]:
    return [Contract(address) for address in cfg()["factories"]]


def auctions(factory: ContractInstance) -> list[ContractInstance]:
    return [Contract(address) for address in factory.getAllAuctions()]


def explorer_base_url() -> str:
    return cfg()["explorer"]


def known_address_name(address: str) -> str:
    return cfg()["known_addresses"].get(address.lower(), address)


def safe_name(address: str) -> str:
    # Try contract name
    try:
        return str(Contract(address).name())
    except Exception:
        pass

    # Try ENS
    try:
        ens_name = networks.active_provider.web3.ens.name(address)
        if ens_name:
            return str(ens_name)
    except Exception:
        pass

    # Fallback
    return known_address_name(address)
