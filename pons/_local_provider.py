"""PyEVM-based provider for tests."""

import itertools
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any

from alysis import EVMVersion, Node, RPCNode
from eth_account import Account
from ethereum_rpc import Amount

from ._provider import JSON, Provider, ProviderSession
from ._signer import AccountSigner, Signer


class SnapshotID:
    """An ID of a snapshot in a :py:class:`LocalProvider`."""

    def __init__(self, id_: int):
        self.id_ = id_


class LocalProvider(Provider):
    """A provider maintaining its own chain state, useful for tests."""

    root: Signer
    """The signer for the pre-created account."""

    def __init__(
        self,
        *,
        root_balance: Amount,
        chain_id: int = 1,
        evm_version: EVMVersion = EVMVersion.CANCUN,
    ):
        self._local_node = Node(
            root_balance_wei=root_balance.as_wei(), chain_id=chain_id, evm_version=evm_version
        )
        self._rpc_node = RPCNode(self._local_node)
        self.root = AccountSigner(Account.from_key(self._local_node.root_private_key))
        self._default_address = self.root.address
        self._snapshot_counter = itertools.count()
        self._snapshots: dict[int, Node] = {}

    def disable_auto_mine_transactions(self) -> None:
        """Disable mining a new block after each transaction."""
        self._local_node.disable_auto_mine_transactions()

    def enable_auto_mine_transactions(self) -> None:
        """
        Enable mining a new block after each transaction.
        This is the default behavior.
        """
        self._local_node.enable_auto_mine_transactions()

    def take_snapshot(self) -> SnapshotID:
        """Creates a snapshot of the chain state internally and returns its ID."""
        snapshot_id = next(self._snapshot_counter)
        self._snapshots[snapshot_id] = deepcopy(self._local_node)
        return SnapshotID(snapshot_id)

    def revert_to_snapshot(self, snapshot_id: SnapshotID) -> None:
        """Restores the chain state to the snapshot with the given ID."""
        self._local_node = self._snapshots[snapshot_id.id_]
        self._rpc_node = RPCNode(self._local_node)

    def rpc(self, method: str, *args: Any) -> JSON:
        return self._rpc_node.rpc(method, *args)

    @asynccontextmanager
    async def session(self) -> AsyncIterator["LocalProviderSession"]:
        yield LocalProviderSession(self)


class LocalProviderSession(ProviderSession):
    def __init__(self, provider: LocalProvider):
        self._provider = provider

    async def rpc(self, method: str, *args: JSON) -> JSON:
        return self._provider.rpc(method, *args)
