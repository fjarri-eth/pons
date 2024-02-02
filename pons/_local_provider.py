"""PyEVM-based provider for tests."""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from alysis import Node, RPCNode
from alysis import RPCError as AlysisRPCError
from eth_account import Account

from ._entities import Amount
from ._provider import JSON, Provider, ProviderSession, RPCError
from ._signer import AccountSigner, Signer


class SnapshotID:
    """An ID of a snapshot in a :py:class:`LocalProvider`."""

    def __init__(self, id_: int):
        self.id_ = id_


class LocalProvider(Provider):
    """A provider maintaining its own chain state, useful for tests."""

    root: Signer
    """The signer for the pre-created account."""

    def __init__(self, *, root_balance: Amount, chain_id: int = 1):
        self._local_node = Node(root_balance_wei=root_balance.as_wei(), chain_id=chain_id)
        self._rpc_node = RPCNode(self._local_node)
        self.root = AccountSigner(Account.from_key(self._local_node.root_private_key))
        self._default_address = self.root.address

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
        return SnapshotID(self._local_node.take_snapshot())

    def revert_to_snapshot(self, snapshot_id: SnapshotID) -> None:
        """Restores the chain state to the snapshot with the given ID."""
        self._local_node.revert_to_snapshot(snapshot_id.id_)

    def rpc(self, method: str, *args: Any) -> JSON:
        try:
            return self._rpc_node.rpc(method, *args)
        except AlysisRPCError as exc:
            raise RPCError(exc.code.value, exc.message, exc.data) from exc

    @asynccontextmanager
    async def session(self) -> AsyncIterator["LocalProviderSession"]:
        yield LocalProviderSession(self)


class LocalProviderSession(ProviderSession):
    def __init__(self, provider: LocalProvider):
        self._provider = provider

    async def rpc(self, method: str, *args: JSON) -> JSON:
        return self._provider.rpc(method, *args)
