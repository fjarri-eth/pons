"""PyEVM-based provider for tests."""

import ast
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterable, Iterator, Mapping, Union, cast

from eth.exceptions import Revert
from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend  # type: ignore[import-untyped]
from eth_tester.exceptions import (  # type: ignore[import-untyped]
    BlockNotFound,
    TransactionFailed,
    TransactionNotFound,
)
from eth_utils.exceptions import ValidationError

from . import abi
from ._abi_types import decode_args, encode_args, keccak
from ._entities import (
    Amount,
    rpc_decode_block,
    rpc_decode_quantity,
    rpc_encode_data,
    rpc_encode_quantity,
)
from ._provider import JSON, Provider, ProviderSession, RPCError, RPCErrorCode
from ._signer import AccountSigner, Signer

# The standard `revert(string)` is a EIP838 error.
_ERROR_SELECTOR = keccak(b"Error(string)")[:4]


@contextmanager
def pyevm_errors_into_rpc_errors() -> Iterator[None]:
    try:
        yield
    except TransactionFailed as exc:
        reason = exc.args[0]

        if isinstance(reason, Revert):
            # Happens when `require/revert` is called in a mutating method or a constructor.
            reason_data = reason.args[0]

        elif isinstance(reason, str):
            # Happens when `require/revert` is called in a view method.

            # Have to go through this procedure because eth-tester doesn't bother
            # to discriminate between legacy (string) reverts and reverts with custom types.
            try:
                # raises ValueError if it is not a Python literal
                reason_data = ast.literal_eval(reason)
            except (ValueError, SyntaxError):
                # Bring `reason_data` to what a `Revert` instance would contain in this case
                reason_data = _ERROR_SELECTOR + encode_args((abi.string, reason))

        else:
            # Shouldn't happen unless the API of eth-tester changes
            raise TypeError(
                "Unexpected `eth_tester.TransactionFailed` format. Please open an issue."
            ) from exc  # pragma: no cover

        if reason_data == b"":
            # Empty `revert()`, or `require()` without a message.

            # who knows why it's different in this specific case,
            # but that's how Infura and Quicknode work
            error = RPCErrorCode.SERVER_ERROR

            message = "execution reverted"
            data = None

        elif reason_data.startswith(_ERROR_SELECTOR):
            error = RPCErrorCode.EXECUTION_ERROR
            reason_message = decode_args([abi.string], reason_data[len(_ERROR_SELECTOR) :])[0]
            message = f"execution reverted: {reason_message!r}"
            data = rpc_encode_data(reason_data)

        else:
            error = RPCErrorCode.EXECUTION_ERROR
            message = "execution reverted"
            data = rpc_encode_data(reason_data)

        raise RPCError(error.value, message, data) from exc

    except ValidationError as exc:
        raise RPCError.invalid_parameter(exc.args[0]) from exc


def make_camel_case(key: str) -> str:
    # The RPC standard uses camelCase dictionary keys,
    # EthereumTester does not, for whatever reason.
    parts = key.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


Normalizable = Union[int, bytes, Iterable["Normalizable"], Mapping[str, "Normalizable"]]


def normalize_return_value(value: Normalizable) -> JSON:
    if isinstance(value, int):
        return rpc_encode_quantity(value)
    if isinstance(value, bytes):
        return rpc_encode_data(value)
    if isinstance(value, dict):
        return {make_camel_case(key): normalize_return_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_return_value(item) for item in value]
    return value


class SnapshotID:
    """An ID of a snapshot in a :py:class:`LocalProvider`."""

    def __init__(self, id_: int):
        self.id_ = id_


class LocalProvider(Provider):
    """A provider maintaining its own chain state, useful for tests."""

    # Disable py.test picking this class up.
    __test__ = False

    root_account: Signer
    """The signer for the pre-created account."""

    def __init__(self, *, root_balance: Amount):
        custom_genesis_state = PyEVMBackend.generate_genesis_state(
            num_accounts=1, overrides=dict(balance=root_balance.as_wei())
        )
        backend = PyEVMBackend(genesis_state=custom_genesis_state)
        self._ethereum_tester = EthereumTester(backend)
        self.root = AccountSigner(Account.from_key(backend.account_keys[0]))
        self._default_address = self.root.address

    def disable_auto_mine_transactions(self) -> None:
        """Disable mining a new block after each transaction."""
        self._ethereum_tester.disable_auto_mine_transactions()

    def enable_auto_mine_transactions(self) -> None:
        """
        Disable mining a new block after each transaction.
        This is the default behavior.
        """
        self._ethereum_tester.enable_auto_mine_transactions()

    def take_snapshot(self) -> SnapshotID:
        """Creates a snapshot of the chain state internally and returns its ID."""
        return SnapshotID(self._ethereum_tester.take_snapshot())

    def revert_to_snapshot(self, snapshot_id: SnapshotID) -> None:
        """Restores the chain state to the snapshot with the given ID."""
        self._ethereum_tester.revert_to_snapshot(snapshot_id.id_)

    def add_account(self, signer: AccountSigner) -> None:
        """Registers a new signer to allow it to be used in calls and transactions."""
        # There are gaps in how EthereumTester handles the accounts.
        # A random signer can be used to deploy and interact with contracts without being added
        # to the accounts, if we use `send_raw_transaction()` (which is exactly what we do).
        # But if `eth_call()` has an explicit "from" field, it must be in the accounts.
        self._ethereum_tester.add_account(signer.private_key.hex())

    def rpc(self, method: str, *args: Any) -> JSON:
        dispatch = dict(
            net_version=self.net_version,
            eth_chainId=self.eth_chain_id,
            eth_getBalance=self.eth_get_balance,
            eth_getTransactionReceipt=self.eth_get_transaction_receipt,
            eth_getTransactionCount=self.eth_get_transaction_count,
            eth_call=self.eth_call,
            eth_sendRawTransaction=self.eth_send_raw_transaction,
            eth_estimateGas=self.eth_estimate_gas,
            eth_gasPrice=self.eth_gas_price,
            eth_blockNumber=self.eth_block_number,
            eth_getTransactionByHash=self.eth_get_transaction_by_hash,
            eth_getBlockByHash=self.eth_get_block_by_hash,
            eth_getBlockByNumber=self.eth_get_block_by_number,
            eth_newBlockFilter=self.eth_new_block_filter,
            eth_newPendingTransactionFilter=self.eth_new_pending_transaction_filter,
            eth_newFilter=self.eth_new_filter,
            eth_getFilterChanges=self.eth_get_filter_changes,
        )
        if method not in dispatch:
            raise RPCError.method_not_found(method)

        try:
            result = dispatch[method](*args)  # type: ignore[operator]
        except TypeError as exc:
            raise RPCError.invalid_parameter(str(exc)) from exc

        return cast(JSON, result)

    def net_version(self) -> str:
        return "0"

    def eth_chain_id(self) -> str:
        return rpc_encode_quantity(self._ethereum_tester.backend.chain.chain_id)

    def eth_get_balance(self, address: str, block: str) -> str:
        return rpc_encode_quantity(self._ethereum_tester.get_balance(address, block))

    def eth_get_transaction_count(self, address: str, block: str) -> str:
        return rpc_encode_quantity(self._ethereum_tester.get_nonce(address, block))

    def eth_send_raw_transaction(self, tx_hex: str) -> str:
        with pyevm_errors_into_rpc_errors():
            return cast(str, self._ethereum_tester.send_raw_transaction(tx_hex))

    def eth_call(self, tx: Mapping[str, Any], block: str) -> JSON:
        # EthereumTester needs it for whatever reason
        if "from" not in tx:
            tx = dict(tx)
            tx["from"] = self._default_address.rpc_encode()

        with pyevm_errors_into_rpc_errors():
            return cast(JSON, self._ethereum_tester.call(tx, block))

    def eth_get_transaction_receipt(self, tx_hash: str) -> JSON:
        try:
            result = self._ethereum_tester.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            return None
        return normalize_return_value(result)

    def eth_estimate_gas(self, tx: Mapping[str, Any], block: str) -> str:
        tx = dict(tx)
        if "from" not in tx:
            tx["from"] = self._default_address.rpc_encode()
        tx["value"] = rpc_decode_quantity(tx["value"])

        with pyevm_errors_into_rpc_errors():
            gas = self._ethereum_tester.estimate_gas(tx, block)

        return rpc_encode_quantity(gas)

    def eth_gas_price(self) -> str:
        # The specific algorithm is not enforced in the standard,
        # but this is the logic Infura uses. Seems to work for them.
        block_info = self._ethereum_tester.get_block_by_number("latest", full_transactions=False)

        # Base fee plus 1 GWei
        return rpc_encode_quantity(block_info["base_fee_per_gas"] + 10**9)

    def eth_block_number(self) -> str:
        result = self._ethereum_tester.get_block_by_number("latest")["number"]
        return rpc_encode_quantity(result)

    def eth_get_transaction_by_hash(self, tx_hash: str) -> JSON:
        try:
            result = self._ethereum_tester.get_transaction_by_hash(
                tx_hash,
            )
        except TransactionNotFound:
            return None
        return normalize_return_value(result)

    def eth_get_block_by_hash(
        self, block_hash: str, with_transactions: bool  # noqa: FBT001
    ) -> JSON:
        try:
            result = self._ethereum_tester.get_block_by_hash(
                block_hash, full_transactions=with_transactions
            )
        except BlockNotFound:
            return None

        # Major providers still use "miner", but eth-tester is already using "coinbase" (see #44).
        # Replacing for now.
        if not ("miner" not in result and "coinbase" in result):  # pragma: no cover
            raise RuntimeError(
                "`eth-tester` changed its block info representation. "
                "Please open an issue (also see issue #44)."
            )
        result["miner"] = result["coinbase"]
        del result["coinbase"]

        return normalize_return_value(result)

    def eth_get_block_by_number(self, block: str, with_transactions: bool) -> JSON:  # noqa: FBT001
        try:
            result = self._ethereum_tester.get_block_by_number(
                rpc_decode_block(block), full_transactions=with_transactions
            )
        except BlockNotFound:
            return None

        # Major providers still use "miner", but eth-tester is already using "coinbase" (see #44).
        # Replacing for now.
        if not ("miner" not in result and "coinbase" in result):  # pragma: no cover
            raise RuntimeError(
                "`eth-tester` changed its block info representation. "
                "Please open an issue (also see issue #44)."
            )
        result["miner"] = result["coinbase"]
        del result["coinbase"]

        return normalize_return_value(result)

    def eth_new_block_filter(self) -> str:
        filter_id = self._ethereum_tester.create_block_filter()
        return rpc_encode_quantity(filter_id)

    def eth_new_pending_transaction_filter(self) -> str:
        filter_id = self._ethereum_tester.create_pending_transaction_filter()
        return rpc_encode_quantity(filter_id)

    def eth_new_filter(self, params: Mapping[str, Any]) -> str:
        address = params.get("address", None)
        topics = params.get("topics", None)
        filter_id = self._ethereum_tester.create_log_filter(
            from_block=rpc_decode_block(params["fromBlock"]),
            to_block=rpc_decode_block(params["toBlock"]),
            address=address,
            topics=topics,
        )
        return rpc_encode_quantity(filter_id)

    def eth_get_filter_changes(self, filter_id: str) -> JSON:
        results = self._ethereum_tester.get_only_filter_changes(rpc_decode_quantity(filter_id))
        results = normalize_return_value(results)
        # There's no public way to detect the type of the filter,
        # and we need to apply this transformation only for log filters.
        # Hence the hack.
        if results and isinstance(results[0], dict):
            for result in results:
                # returned by regular RPC providers, but not by EthereumTester
                result["removed"] = False
        return cast(JSON, results)

    @asynccontextmanager
    async def session(self) -> AsyncIterator["LocalProviderSession"]:
        yield LocalProviderSession(self)


class LocalProviderSession(ProviderSession):
    def __init__(self, provider: LocalProvider):
        self._provider = provider

    async def rpc(self, method: str, *args: JSON) -> JSON:
        return self._provider.rpc(method, *args)
