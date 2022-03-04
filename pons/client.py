from enum import Enum
from typing import Union, Any, Optional

import trio

from .contract import DeployedContract, CompiledContract
from .contract_abi import MethodCall
from .provider import Provider
from .signer import Signer
from .types import (
    Address, Wei, Block, TxHash, TxReceipt,
    encode_quantity, encode_data, encode_address, encode_wei, encode_tx_hash, encode_block,
    decode_quantity, decode_data, decode_address, decode_wei, decode_tx_hash)


class Client:

    def __init__(self, provider: Provider):
        self._provider = provider
        self._net_version: Optional[str] = None
        self._chain_id: Optional[int] = None

    def with_signer(self, signer: Signer):
        return SigningClient(self._provider, signer)

    async def net_version(self) -> str:
        if self._net_version is None:
            result = await self._provider.rpc_call('net_version')
            assert isinstance(result, str)
            self._net_version = result
        return self._net_version

    async def get_chain_id(self) -> int:
        if self._chain_id is None:
            result = await self._provider.rpc_call('eth_chainId')
            self._chain_id = decode_quantity(result)
        return self._chain_id

    async def get_balance(self, address: Address, block: Union[int, Block] = Block.LATEST) -> Wei:
        result = await self._provider.rpc_call(
            'eth_getBalance', encode_address(address), encode_block(block))
        return decode_wei(result)

    async def get_transaction_receipt(self, tx_hash: TxHash) -> Optional[TxReceipt]:
        result = await self._provider.rpc_call(
            'eth_getTransactionReceipt', encode_tx_hash(tx_hash))

        if not result:
            return None

        contract_address = result['contractAddress']

        return TxReceipt(
            succeeded=(decode_quantity(result['status']) == 1),
            contract_address=decode_address(contract_address) if contract_address else None,
            gas_used=decode_quantity(result['gasUsed']),
            )

    async def get_transaction_count(self, address: Address, block: Union[int, Block] = Block.LATEST) -> int:
        result = await self._provider.rpc_call(
            'eth_getTransactionCount', encode_address(address), encode_block(block))
        return decode_quantity(result)

    async def wait_for_transaction_receipt(self, tx_hash: TxHash) -> TxReceipt:
        while True:
            receipt = await self.get_transaction_receipt(tx_hash)
            if receipt:
                return receipt
            await trio.sleep(1)

    async def call(self,
                   contract_address: Address,
                   call: MethodCall,
                   block: Union[int, Block] = Block.LATEST) -> Any:

        encoded_args = call.encode()
        result = await self._provider.rpc_call(
            'eth_call',
            {
                'to': encode_address(contract_address),
                'data': encode_data(encoded_args)
            },
            encode_block(block))

        encoded_output = decode_data(result)
        return call.decode_output(encoded_output)

    async def send_raw_transaction(self, tx_bytes: bytes) -> TxHash:
        result = await self._provider.rpc_call('eth_sendRawTransaction', encode_data(tx_bytes))
        return decode_tx_hash(result)

    async def estimate_gas(self, contract_address: Address, call: MethodCall) -> Wei:
        encoded_args = call.encode()
        result = await self._provider.rpc_call(
            'eth_estimateGas',
            {
                'to': encode_address(contract_address),
                'data': encode_data(encoded_args)
            },
            encode_block(Block.LATEST))
        return decode_quantity(result)

    async def estimate_deploy(self, contract: CompiledContract, *args) -> int:
        encoded_args = contract.abi.constructor(*args).encode()
        tx = {
            'data': encode_data(contract.bytecode + encoded_args)
        }
        result = await self._provider.rpc_call(
            'eth_estimateGas',
            tx,
            encode_block(Block.LATEST))
        return decode_quantity(result)

    async def estimate_transfer(self, source_address: Address, destination_address: Address, amount: Wei) -> int:
        # TODO: source_address and amount are optional,
        # but if they are specified, we will fail here instead of later.
        tx = {
            'from': encode_address(source_address),
            'to': encode_address(destination_address),
            'value': encode_wei(amount),
        }
        result = await self._provider.rpc_call(
            'eth_estimateGas',
            tx,
            encode_block(Block.LATEST))
        return decode_quantity(result)

    async def estimate_transact(self, contract_address: Address, call: MethodCall) -> int:
        encoded_args = call.encode()
        tx = {
            'to': encode_address(contract_address),
            'data': encode_data(encoded_args),
        }
        result = await self._provider.rpc_call(
            'eth_estimateGas',
            tx,
            encode_block(Block.LATEST))
        return decode_quantity(result)

    async def gas_price(self):
        result = await self._provider.rpc_call('eth_gasPrice')
        return decode_wei(result)


class SigningClient(Client):

    def __init__(self, provider: Provider, signer: Signer):
        super().__init__(provider)
        self._signer = signer

    async def transfer(self, destination_address: Address, amount: Wei):
        chain_id = await self.get_chain_id()
        gas = await self.estimate_transfer(self._signer.address(), destination_address, amount)
        # TODO: implement gas strategies
        max_gas_price = await self.gas_price()
        max_tip = Wei.from_unit(1, 'gwei')
        nonce = await self.get_transaction_count(self._signer.address(), Block.LATEST)
        tx = {
            'type': 2, # EIP-2930 transaction
            'chainId': encode_quantity(chain_id),
            'to': encode_address(destination_address),
            'value': encode_wei(amount),
            'gas': encode_quantity(gas),
            'maxFeePerGas': encode_wei(max_gas_price),
            'maxPriorityFeePerGas': encode_wei(max_tip),
            'nonce': encode_quantity(nonce),
        }
        signed_tx = self._signer.sign_transaction(tx)
        tx_hash = await self.send_raw_transaction(signed_tx)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

    async def deploy(self, contract: CompiledContract, *args) -> DeployedContract:
        encoded_args = contract.abi.constructor(*args).encode()
        chain_id = await self.get_chain_id()
        gas = await self.estimate_deploy(contract, *args) # TODO: don't encode args twice
        # TODO: implement gas strategies
        max_gas_price = await self.gas_price()
        max_tip = Wei.from_unit(1, 'gwei')
        nonce = await self.get_transaction_count(self._signer.address(), Block.LATEST)
        tx = {
            'type': 2, # EIP-2930 transaction
            'chainId': encode_quantity(chain_id),
            'value': encode_quantity(0),
            'gas': encode_quantity(gas),
            'maxFeePerGas': encode_wei(max_gas_price),
            'maxPriorityFeePerGas': encode_wei(max_tip),
            'nonce': encode_quantity(nonce),
            'data': encode_data(contract.bytecode + encoded_args)
        }
        signed_tx = self._signer.sign_transaction(tx)
        tx_hash = await self.send_raw_transaction(signed_tx)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

        if not receipt.succeeded:
            raise Exception(receipt)

        return DeployedContract(contract.abi, receipt.contract_address)

    async def transact(self, contract_address: Address, call: MethodCall):
        encoded_args = call.encode()
        chain_id = await self.get_chain_id()
        gas = await self.estimate_transact(contract_address, call)
        # TODO: implement gas strategies
        max_gas_price = await self.gas_price()
        max_tip = Wei.from_unit(1, 'gwei')
        nonce = await self.get_transaction_count(self._signer.address(), Block.LATEST)
        tx = {
            'type': 2, # EIP-2930 transaction
            'chainId': encode_quantity(chain_id),
            'to': encode_address(contract_address),
            'value': encode_quantity(0),
            'gas': encode_quantity(gas),
            'maxFeePerGas': encode_wei(max_gas_price),
            'maxPriorityFeePerGas': encode_wei(max_tip),
            'nonce': encode_quantity(nonce),
            'data': encode_data(encoded_args)
        }
        signed_tx = self._signer.sign_transaction(tx)
        tx_hash = await self.send_raw_transaction(signed_tx)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

        if not receipt.succeeded:
            raise Exception(receipt)
