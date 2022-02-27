from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend
import httpx

from .currency import Wei


class EthereumTesterProvider:

    def __init__(self, root_balance=100):
        state_overrides = {'balance': int(Wei.from_unit(root_balance, 'ether'))}
        custom_genesis_state = PyEVMBackend.generate_genesis_state(num_accounts=1)
        backend = PyEVMBackend(genesis_state=custom_genesis_state)
        self._ethereum_tester = EthereumTester(backend)
        self.root_account = Account.from_key(backend.account_keys[0])

    async def net_version(self):
        return 0

    async def get_balance(self, address, block_number):
        return self._ethereum_tester.get_balance(address, block_number)

    async def get_transaction_count(self, address, block_number):
        return self._ethereum_tester.get_nonce(address, block_number)

    async def send_raw_transaction(self, tx_bytes):
        assert isinstance(tx_bytes, bytes)
        return self._ethereum_tester.send_raw_transaction(tx_bytes.hex())

    async def call(self, tx, block_number):
        if 'from' not in tx:
            # EthereumTester needs this
            tx['from'] = self.root_account.address
        return self._ethereum_tester.call(tx, block_number)

    async def get_transaction_receipt(self, transaction_hash):
        return self._ethereum_tester.get_transaction_receipt(transaction_hash)


class HTTPProvider:

    def __init__(self, url):
        self._url = url

    async def _rpc_call(self, method, *args):
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

    async def net_version(self):
        result = await self._rpc_call('net_version') # note: returns a string
        return result

    async def get_balance(self, address, block_number):
        result = await self._rpc_call('eth_getBalance', address, block_number)
        return int(result, 16)

    async def get_transaction_count(self, address, block_number):
        result = await self._rpc_call('eth_getTransactionCount', address, block_number)
        return int(result, 16)

    async def send_raw_transaction(self, tx_bytes):
        assert isinstance(tx_bytes, bytes)
        result = await self._rpc_call('eth_sendRawTransaction', tx_bytes.hex())
        return bytes.fromhex(result[2:])

    async def call(self, tx, block_number):
        result = await self._rpc_call('eth_call', tx, block_number)
        return result

    async def get_transaction_receipt(self, tx_hash):
        result = await self._rpc_call('eth_getTransactionReceipt', '0x' + tx_hash.hex())
        return result
