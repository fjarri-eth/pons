import trio

from eth_utils import to_checksum_address

from .currency import Wei
from .contract import DeployedContract


class Client:

    def __init__(self, provider):
        self._provider = provider
        self._net_version = None

    def with_signer(self, account):
        return SigningClient(self._provider, account)

    async def net_version(self) -> int:
        if self._net_version is None:
            self._net_version = await self._provider.net_version()
        return self._net_version

    async def get_balance(self, address: 'Address', block_number='latest'):
        amount = await self._provider.get_balance(address, block_number)
        return Wei(amount)

    async def wait_for_transaction_receipt(self, tx_hash):
        while True:
            receipt = await self._provider.get_transaction_receipt(tx_hash)
            if receipt:
                return receipt
            await trio.sleep(1)

    async def call(self, contract_address, call):
        encoded_args = call.encode().hex()
        tx = {
            # TODO: 'from' - is it needed? Test with Infura
            'to': contract_address,
            'data': '0x' + encoded_args,
        }
        result = await self._provider.call(tx, 'latest')
        return call.decode_output(result)


class SigningClient(Client):

    def __init__(self, provider, account):
        super().__init__(provider)
        self._account = account

    async def transfer(self, destination_address: 'Address', amount: 'Amount'):
        nonce = await self._provider.get_transaction_count(self._account.address, 'latest')
        # TODO: it seems that all numbers should really be in hex
        tx = {
            'type': 2, # EIP-2930 transaction
            'chainId': 4, # Note: EthTester does not require it
            'to': destination_address,
            'value': int(amount),
            'gas': 30000,
            'maxFeePerGas': int(Wei.from_unit(250, 'gwei')),
            'maxPriorityFeePerGas': int(Wei.from_unit(2, 'gwei')),
            'nonce': nonce,
        }
        signed_tx = self._account.sign_transaction(tx)
        tx_hash = await self._provider.send_raw_transaction(signed_tx.rawTransaction)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

    async def deploy(self, contract: 'CompiledContract', *args):
        encoded_args = contract.abi.constructor(*args).encode().hex()

        nonce = await self._provider.get_transaction_count(self._account.address, 'latest')
        # TODO: it seems that all numbers should really be in hex
        tx = {
            'type': 2, # EIP-2930 transaction
            'chainId': 4, # Note: EthTester does not require it
            'value': 0,
            'gas': 1000000,
            'maxFeePerGas': int(Wei.from_unit(250, 'gwei')),
            'maxPriorityFeePerGas': int(Wei.from_unit(2, 'gwei')),
            'nonce': nonce,
            'data': contract.bytecode + encoded_args
        }
        signed_tx = self._account.sign_transaction(tx)
        tx_hash = await self._provider.send_raw_transaction(signed_tx.rawTransaction)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

        # EthereumTester returns `1`, Infura returns `0x1`
        if receipt['status'] not in (1, '0x1'):
            raise Exception(receipt)
        contract_address = receipt['contract_address'] if 'contract_address' in receipt else receipt['contractAddress']

        return DeployedContract(contract.abi, contract_address)

    async def transact(self, contract_address, call):
        encoded_args = call.encode().hex()

        nonce = await self._provider.get_transaction_count(self._account.address, 'latest')
        # TODO: it seems that all numbers should really be in hex
        tx = {
            'type': 2, # EIP-2930 transaction
            'chainId': 4, # Note: EthTester does not require it
            'to': to_checksum_address(contract_address),
            'value': 0,
            'gas': 100000,
            'maxFeePerGas': int(Wei.from_unit(250, 'gwei')),
            'maxPriorityFeePerGas': int(Wei.from_unit(2, 'gwei')),
            'nonce': nonce,
            'data': encoded_args
        }
        signed_tx = self._account.sign_transaction(tx)
        tx_hash = await self._provider.send_raw_transaction(signed_tx.rawTransaction)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

        if receipt['status'] not in (1, '0x1'):
            raise Exception(receipt)
