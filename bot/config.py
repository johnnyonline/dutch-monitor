from collections.abc import Mapping, Sequence
from typing import TypedDict, cast

from ape import Contract, chain
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
    return [Contract(addr) for addr in cfg()["factories"]]


def explorer_base_url() -> str:
    return cfg()["explorer"]


def known_address_name(addr: str) -> str:
    return cfg()["known_addresses"].get(addr.lower(), addr)


def safe_name(contract: ContractInstance) -> str:
    try:
        return cast(str, contract.name())
    except Exception:
        return known_address_name(contract.address)
