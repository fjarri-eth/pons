"""
PyEVM-based provider for tests.
"""

from contextlib import asynccontextmanager, contextmanager
from typing import Union, List

from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend
from eth_tester.exceptions import TransactionNotFound, TransactionFailed
from eth.exceptions import Revert
from eth_utils.exceptions import ValidationError

from pons._provider import Provider, ProviderSession, RPCError, RPCErrorCode
from pons._entities import Amount, Address, encode_quantity, decode_quantity, encode_data


@contextmanager
def pyevm_errors_into_rpc_errors():
    try:
        yield
    except TransactionFailed as exc:
        (reason,) = exc.args
        if isinstance(reason, Revert):
            # TODO: unpack the data to get the revert reason
            # The standard `revert(string)` is a EIP838 error.
            raise RPCError(
                RPCErrorCode.EXECUTION_ERROR.value,
                "execution reverted",
                encode_data(reason.args[0]),
            )
        else:
            # TODO: what are the other possible reasons? Do they have the same error code?
            # Since I don't know how to hit this line, skipping coverage for it.
            raise RPCError(
                RPCErrorCode.EXECUTION_ERROR.value, "transaction failed", reason
            )  # pragma: no cover
    except ValidationError as exc:
        raise RPCError(RPCErrorCode.SERVER_ERROR.value, exc.args[0])


class EthereumTesterProvider(Provider):
    def __init__(self, root_balance_eth: int = 100):
        custom_genesis_state = PyEVMBackend.generate_genesis_state(
            num_accounts=1, overrides=dict(balance=Amount.ether(root_balance_eth).as_wei())
        )
        backend = PyEVMBackend(genesis_state=custom_genesis_state)
        self._ethereum_tester = EthereumTester(backend)
        self.root_account = Account.from_key(backend.account_keys[0])
        self._default_address = Address.from_hex(self.root_account.address)

    def disable_auto_mine_transactions(self):
        self._ethereum_tester.disable_auto_mine_transactions()

    def enable_auto_mine_transactions(self):
        self._ethereum_tester.enable_auto_mine_transactions()

    def rpc(self, method, *args):
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
        )
        return dispatch[method](*args)

    def net_version(self) -> str:
        return "0"

    def eth_chain_id(self) -> str:
        return encode_quantity(self._ethereum_tester.backend.chain.chain_id)

    def eth_get_balance(self, address: str, block: str) -> str:
        return encode_quantity(self._ethereum_tester.get_balance(address, block))

    def eth_get_transaction_count(self, address: str, block: str) -> str:
        return encode_quantity(self._ethereum_tester.get_nonce(address, block))

    def eth_send_raw_transaction(self, tx_hex: str) -> str:
        with pyevm_errors_into_rpc_errors():
            return self._ethereum_tester.send_raw_transaction(tx_hex)

    def eth_call(self, tx: dict, block: str) -> Union[List, str]:
        assert "from" not in tx
        # EthereumTester needs it for whatever reason
        tx["from"] = self._default_address.encode()
        return self._ethereum_tester.call(tx, block)

    def eth_get_transaction_receipt(self, tx_hash_hex):
        try:
            result = self._ethereum_tester.get_transaction_receipt(tx_hash_hex)
        except TransactionNotFound:
            return None

        # TODO: rename/encode the remaining fields. For now that's all we need.
        result = dict(
            contractAddress=result["contract_address"],
            status=encode_quantity(result["status"]),
            gasUsed=encode_quantity(result["gas_used"]),
        )
        return result

    def eth_estimate_gas(self, tx: dict, block: str) -> str:
        if "from" not in tx:
            tx["from"] = self._default_address.encode()
        tx["value"] = decode_quantity(tx["value"])

        with pyevm_errors_into_rpc_errors():
            gas = self._ethereum_tester.estimate_gas(tx, block)

        return encode_quantity(gas)

    def eth_gas_price(self):
        # The specific algorithm is not enforced in the standard,
        # but this is the logic Infura uses. Seems to work for them.
        block_info = self._ethereum_tester.get_block_by_number("latest", False)

        # Base fee plus 1 GWei
        return encode_quantity(block_info["base_fee_per_gas"] + 10**9)

    @asynccontextmanager
    async def session(self):
        yield EthereumTesterProviderSession(self)


class EthereumTesterProviderSession(ProviderSession):
    def __init__(self, provider):
        self._provider = provider

    async def rpc(self, method, *args):
        return self._provider.rpc(method, *args)
