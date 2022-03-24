"""
PyEVM-based provider for tests.
"""

from contextlib import asynccontextmanager
from typing import Union, List

from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend

from pons.provider import Provider, ProviderSession
from pons.types import Amount, Address, encode_quantity, encode_address, encode_amount, decode_quantity


class EthereumTesterProvider(Provider):

    def __init__(self, root_balance_eth: int = 100):
        custom_genesis_state = PyEVMBackend.generate_genesis_state(
            num_accounts=1,
            overrides=dict(balance=Amount.ether(root_balance_eth).as_wei()))
        backend = PyEVMBackend(genesis_state=custom_genesis_state)
        self._ethereum_tester = EthereumTester(backend)
        self.root_account = Account.from_key(backend.account_keys[0])
        self._default_address = Address.from_hex(self.root_account.address)

    async def rpc(self, method, *args):
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
            eth_getBlockByNumber=self.eth_get_block_by_number,
            )
        return await dispatch[method](*args)

    async def net_version(self) -> str:
        return "0"

    async def eth_chain_id(self) -> str:
        return encode_quantity(self._ethereum_tester.backend.chain.chain_id)

    async def eth_get_balance(self, address: str, block: str) -> str:
        return encode_quantity(self._ethereum_tester.get_balance(address, block))

    async def eth_get_transaction_count(self, address: str, block: str) -> str:
        return encode_quantity(self._ethereum_tester.get_nonce(address, block))

    async def eth_send_raw_transaction(self, tx_hex: str) -> str:
        return self._ethereum_tester.send_raw_transaction(tx_hex)

    async def eth_call(self, tx: dict, block: str) -> Union[List, str]:
        if 'from' not in tx:
            tx['from'] = encode_address(self._default_address)
        return self._ethereum_tester.call(tx, block)

    async def eth_get_transaction_receipt(self, tx_hash_hex):
        result = self._ethereum_tester.get_transaction_receipt(tx_hash_hex)
        result['contractAddress'] = result.pop('contract_address')
        result['status'] = encode_quantity(result.pop('status'))
        result['gasUsed'] = encode_quantity(result.pop('gas_used'))
        return result

    async def eth_estimate_gas(self, tx: dict, block: str) -> str:
        if 'from' not in tx:
            tx['from'] = encode_address(self._default_address)
        if 'value' in tx:
            tx['value'] = decode_quantity(tx['value'])
        return encode_quantity(self._ethereum_tester.estimate_gas(tx, block))

    async def eth_gas_price(self):
        # The specific algorithm is not enforced in the standard,
        # but this is the logic Infura uses. Seems to work for them.
        block_info = self._ethereum_tester.get_block_by_number('latest', False)

        # Base fee plus 1 GWei
        return encode_quantity(block_info['base_fee_per_gas'] + 10**9)

    async def eth_get_block_by_number(self, block: str, full_transactions: bool) -> str:
        result = self._ethereum_tester.get_block_by_number(block, True)
        result['timestamp'] = encode_quantity(result['timestamp'])
        for tx_info in result['transactions']:
            tx_info['gas'] = encode_quantity(tx_info['gas'])
            tx_info['gasPrice'] = encode_amount(tx_info.pop('gas_price'))

        return result

    @asynccontextmanager
    async def session(self):
        yield EthereumTesterProviderSession(self)


class EthereumTesterProviderSession(ProviderSession):

    def __init__(self, provider):
        self._provider = provider

    async def rpc(self, method, *args):
        return await self._provider.rpc(method, *args)
