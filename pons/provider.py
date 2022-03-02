from abc import ABC, abstractmethod
from typing import Any, Union, List

from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend
import httpx

from .types import Wei, Address, encode_quantity, encode_address


class Provider(ABC):

    @abstractmethod
    async def rpc_call(self, method: str, *args) -> Any:
        ...


class EthereumTesterProvider(Provider):

    def __init__(self, root_balance: Wei = 100):
        state_overrides = {'balance': int(Wei.from_unit(root_balance, 'ether'))}
        custom_genesis_state = PyEVMBackend.generate_genesis_state(num_accounts=1)
        backend = PyEVMBackend(genesis_state=custom_genesis_state)
        self._ethereum_tester = EthereumTester(backend)
        self.root_account = Account.from_key(backend.account_keys[0])
        self._default_address = Address.from_hex(self.root_account.address)

    async def rpc_call(self, method, *args):
        dispatch = dict(
            net_version=self.net_version,
            eth_chainId=self.eth_chain_id,
            eth_getBalance=self.eth_get_balance,
            eth_getTransactionReceipt=self.eth_get_transaction_receipt,
            eth_getTransactionCount=self.eth_get_transaction_count,
            eth_call=self.eth_call,
            eth_sendRawTransaction=self.eth_send_raw_transaction,
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
        result['status'] = encode_quantity(result['status'])
        return result


class HTTPProvider:

    def __init__(self, url):
        self._url = url

    async def rpc_call(self, method, *args):
        json = {
            "jsonrpc": "2.0",
            "method": method,
            "params": list(args),
            "id": 0
            }
        async with httpx.AsyncClient() as client:
            response = await client.post(self._url, json=json)
        response_json = response.json()
        if 'error' in response_json:
            code = response_json['error']['code']
            message = response_json['error']['message']
            raise RuntimeError(f"RPC error {code}: {message}")
        if 'result' not in response_json:
            raise Exception(response_json)
        return response_json['result']
