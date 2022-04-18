from contextlib import asynccontextmanager
from enum import Enum
from typing import Union, Any, Optional, AsyncIterator

import trio

from ._contract import DeployedContract, CompiledContract, BoundConstructorCall, BoundReadCall, BoundWriteCall
from ._provider import Provider, ProviderSession
from ._signer import Signer
from ._entities import (
    Address, Amount, Block, TxHash, TxReceipt,
    encode_quantity, encode_data, encode_block, decode_quantity, decode_data)


class Client:
    """
    An Ethereum RPC client.
    """

    def __init__(self, provider: Provider):
        self._provider = provider
        self._net_version: Optional[str] = None
        self._chain_id: Optional[int] = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator['ClientSession']:
        """
        Opens a session to the client allowing the backend to optimize sequential requests.
        """
        async with self._provider.session() as provider_session:
            client_session = ClientSession(provider_session)
            yield client_session
            # TODO: incorporate cached values from the session back into the client


class ClientSession:
    """
    An open session to the provider.
    """

    def __init__(self, provider_session: ProviderSession):
        self._provider_session = provider_session
        self._net_version: Optional[str] = None
        self._chain_id: Optional[int] = None

    async def net_version(self) -> str:
        """
        Calls the  ``net_version`` RPC method.
        """
        if self._net_version is None:
            result = await self._provider_session.rpc('net_version')
            if not isinstance(result, str):
                raise RuntimeError("Expected a string from the RPC of net_version()")
            self._net_version = result
        return self._net_version

    async def get_chain_id(self) -> int:
        """
        Calls the ``eth_chainId`` RPC method.
        """
        if self._chain_id is None:
            result = await self._provider_session.rpc('eth_chainId')
            self._chain_id = decode_quantity(result)
        return self._chain_id

    async def get_balance(self, address: Address, block: Union[int, Block] = Block.LATEST) -> Amount:
        """
        Calls the ``eth_getBalance`` RPC method.
        """
        result = await self._provider_session.rpc(
            'eth_getBalance', address.encode(), encode_block(block))
        return Amount.decode(result)

    async def get_transaction_receipt(self, tx_hash: TxHash) -> Optional[TxReceipt]:
        """
        Calls the ``eth_getTransactionReceipt`` RPC method.
        """
        result = await self._provider_session.rpc('eth_getTransactionReceipt', tx_hash.encode())

        if not result:
            return None

        contract_address = result['contractAddress']

        return TxReceipt(
            succeeded=(decode_quantity(result['status']) == 1),
            contract_address=Address.decode(contract_address) if contract_address else None,
            gas_used=decode_quantity(result['gasUsed']),
            )

    async def get_transaction_count(self, address: Address, block: Union[int, Block] = Block.LATEST) -> int:
        """
        Calls the ``eth_getTransactionCount`` RPC method.
        """
        result = await self._provider_session.rpc(
            'eth_getTransactionCount', address.encode(), encode_block(block))
        return decode_quantity(result)

    async def wait_for_transaction_receipt(self, tx_hash: TxHash, poll_latency: float = 1.) -> TxReceipt:
        """
        Queries the transaction receipt waiting for ``poll_latency`` between each attempt.
        """
        while True:
            receipt = await self.get_transaction_receipt(tx_hash)
            if receipt:
                return receipt
            await trio.sleep(poll_latency)

    async def call(self, call: BoundReadCall, block: Union[int, Block] = Block.LATEST) -> Any:
        """
        Sends a prepared contact method call to the provided address.
        Returns the decoded output.
        """
        result = await self._provider_session.rpc(
            'eth_call',
            {
                'to': call.contract_address.encode(),
                'data': encode_data(call.data_bytes)
            },
            encode_block(block))

        encoded_output = decode_data(result)
        return call.decode_output(encoded_output)

    async def send_raw_transaction(self, tx_bytes: bytes) -> TxHash:
        """
        Sends a signed and serialized transaction.
        """
        result = await self._provider_session.rpc('eth_sendRawTransaction', encode_data(tx_bytes))
        return TxHash.decode(result)

    async def estimate_deploy(self, call: BoundConstructorCall, amount: Amount = Amount(0)) -> int:
        """
        Estimates the amount of gas required to deploy the contract with the given args.
        """
        tx = {
            'data': encode_data(call.data_bytes),
            'value': amount.encode(),
        }
        result = await self._provider_session.rpc(
            'eth_estimateGas',
            tx,
            encode_block(Block.LATEST))
        return decode_quantity(result)

    async def estimate_transfer(self, source_address: Address, destination_address: Address, amount: Amount) -> int:
        """
        Estimates the amount of gas required to transfer ``amount``.
        Raises an exception if there is not enough funds in ``source_address``.
        """
        # TODO: source_address and amount are optional,
        # but if they are specified, we will fail here instead of later.
        tx = {
            'from': source_address.encode(),
            'to': destination_address.encode(),
            'value': amount.encode(),
        }
        result = await self._provider_session.rpc(
            'eth_estimateGas',
            tx,
            encode_block(Block.LATEST))
        return decode_quantity(result)

    async def estimate_transact(self, call: BoundWriteCall, amount: Amount = Amount(0)) -> int:
        """
        Estimates the amount of gas required to transact with a contract.
        """
        tx = {
            'to': call.contract_address.encode(),
            'data': encode_data(call.data_bytes),
            'value': amount.encode(),
        }
        result = await self._provider_session.rpc(
            'eth_estimateGas',
            tx,
            encode_block(Block.LATEST))
        return decode_quantity(result)

    async def gas_price(self) -> Amount:
        """
        Calls the ``eth_gasPrice`` RPC method.
        """
        result = await self._provider_session.rpc('eth_gasPrice')
        return Amount.decode(result)

    async def transfer(self, signer: Signer, destination_address: Address, amount: Amount):
        """
        Transfers funds from the address of the attached signer to the destination address.
        Waits for the transaction to be confirmed.
        """
        chain_id = await self.get_chain_id()
        gas = await self.estimate_transfer(signer.address, destination_address, amount)
        # TODO: implement gas strategies
        max_gas_price = await self.gas_price()
        max_tip = Amount.gwei(1)
        nonce = await self.get_transaction_count(signer.address, Block.LATEST)
        tx = {
            'type': 2, # EIP-2930 transaction
            'chainId': encode_quantity(chain_id),
            'to': destination_address.encode(),
            'value': amount.encode(),
            'gas': encode_quantity(gas),
            'maxFeePerGas': max_gas_price.encode(),
            'maxPriorityFeePerGas': max_tip.encode(),
            'nonce': encode_quantity(nonce),
        }
        signed_tx = signer.sign_transaction(tx)
        tx_hash = await self.send_raw_transaction(signed_tx)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

    async def deploy(self, signer: Signer, call: BoundConstructorCall, amount: Amount = Amount(0)) -> DeployedContract:
        """
        Deploys the contract passing ``args`` to the constructor.
        Waits for the transaction to be confirmed.
        """
        if not call.payable and amount.as_wei() != 0:
            raise ValueError("This constructor does not accept an associated payment")

        chain_id = await self.get_chain_id()
        gas = await self.estimate_deploy(call, amount=amount)
        # TODO: implement gas strategies
        max_gas_price = await self.gas_price()
        max_tip = Amount.gwei(1)
        nonce = await self.get_transaction_count(signer.address, Block.LATEST)
        tx = {
            'type': 2, # EIP-2930 transaction
            'chainId': encode_quantity(chain_id),
            'value': amount.encode(),
            'gas': encode_quantity(gas),
            'maxFeePerGas': max_gas_price.encode(),
            'maxPriorityFeePerGas': max_tip.encode(),
            'nonce': encode_quantity(nonce),
            'data': encode_data(call.data_bytes)
        }
        signed_tx = signer.sign_transaction(tx)
        tx_hash = await self.send_raw_transaction(signed_tx)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

        if not receipt.succeeded:
            raise Exception(receipt)

        if receipt.contract_address is None:
            raise RuntimeError(
                "The transaction succeeded, but contractAddress is not present in the receipt")

        return DeployedContract(call.contract_abi, receipt.contract_address)

    async def transact(self, signer: Signer, call: BoundWriteCall, amount: Amount = Amount(0)):
        """
        Transacts with the contract using a prepared method call.
        Waits for the transaction to be confirmed.
        """
        if not call.payable and amount.as_wei() != 0:
            raise ValueError("This method does not accept an associated payment")

        chain_id = await self.get_chain_id()
        gas = await self.estimate_transact(call, amount=amount)
        # TODO: implement gas strategies
        max_gas_price = await self.gas_price()
        max_tip = Amount.gwei(1)
        nonce = await self.get_transaction_count(signer.address, Block.LATEST)
        tx = {
            'type': 2, # EIP-2930 transaction
            'chainId': encode_quantity(chain_id),
            'to': call.contract_address.encode(),
            'value': amount.encode(),
            'gas': encode_quantity(gas),
            'maxFeePerGas': max_gas_price.encode(),
            'maxPriorityFeePerGas': max_tip.encode(),
            'nonce': encode_quantity(nonce),
            'data': encode_data(call.data_bytes)
        }
        signed_tx = signer.sign_transaction(tx)
        tx_hash = await self.send_raw_transaction(signed_tx)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

        if not receipt.succeeded:
            raise Exception(receipt)
