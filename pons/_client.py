from contextlib import asynccontextmanager
from functools import wraps
from typing import Union, Any, Optional, AsyncIterator

import anyio

from ._contract import (
    DeployedContract,
    BoundConstructorCall,
    BoundReadCall,
    BoundWriteCall,
)
from ._provider import (
    Provider,
    ProviderSession,
    UnexpectedResponse,
    RPCError,
    RPCErrorCode,
)
from ._signer import Signer
from ._entities import (
    Address,
    Amount,
    Block,
    TxHash,
    TxReceipt,
    encode_quantity,
    encode_data,
    encode_block,
    decode_quantity,
    decode_data,
    RPCDecodingError,
)


class Client:
    """
    An Ethereum RPC client.
    """

    def __init__(self, provider: Provider):
        self._provider = provider
        self._net_version: Optional[str] = None
        self._chain_id: Optional[int] = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator["ClientSession"]:
        """
        Opens a session to the client allowing the backend to optimize sequential requests.
        """
        async with self._provider.session() as provider_session:
            client_session = ClientSession(provider_session)
            yield client_session
            # TODO: incorporate cached values from the session back into the client


class RemoteError(Exception):
    """
    A base of all errors occurring on the provider's side.
    Encompasses both errors returned via HTTP status codes
    and the ones returned via the JSON response.
    """


class BadResponseFormat(RemoteError):
    """
    Raised if the RPC provider returned an unexpectedly formatted response.
    """


class TransactionFailed(RemoteError):
    """
    Raised if the transaction was submitted successfully,
    but the final receipt indicates a failure.
    """


class ProviderError(RemoteError):
    """
    A general problem with fulfilling the request at the provider's side.
    """


class ExecutionFailed(ProviderError):
    """
    Raised if the transaction failed during execution.
    """

    def __init__(self, message: str, data: Optional[bytes]):
        super().__init__(message, data)
        self.message = message
        self.data = data

    def __str__(self):
        return f"Execution failed: {self.message}" + (
            f" (data: {self.data.hex()})" if self.data else ""
        )


def rpc_call(method_name):
    """
    Catches various response formatting errors and returns them in a unified way.
    """

    def _wrapper(func):
        @wraps(func)
        async def _wrapped(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
            except (RPCDecodingError, UnexpectedResponse) as exc:
                raise BadResponseFormat(f"{method_name}: {exc}") from exc
            except RPCError as exc:
                if exc.code == RPCErrorCode.EXECUTION_ERROR:
                    data = decode_data(exc.data) if exc.data else None
                    raise ExecutionFailed(exc.message, data) from exc
                else:
                    raise ProviderError(exc.server_code, exc.message, exc.data) from exc
            return result

        return _wrapped

    return _wrapper


class ClientSession:
    """
    An open session to the provider.
    """

    def __init__(self, provider_session: ProviderSession):
        self._provider_session = provider_session
        self._net_version: Optional[str] = None
        self._chain_id: Optional[int] = None

    @rpc_call("net_version")
    async def net_version(self) -> str:
        """
        Calls the ``net_version`` RPC method.
        """
        if self._net_version is None:
            result = await self._provider_session.rpc("net_version")
            if not isinstance(result, str):
                raise RPCDecodingError("expected a string result")
            self._net_version = result
        return self._net_version

    @rpc_call("eth_chainId")
    async def eth_chain_id(self) -> int:
        """
        Calls the ``eth_chainId`` RPC method.
        """
        if self._chain_id is None:
            result = await self._provider_session.rpc("eth_chainId")
            self._chain_id = decode_quantity(result)
        return self._chain_id

    @rpc_call("eth_getBalance")
    async def eth_get_balance(
        self, address: Address, block: Union[int, Block] = Block.LATEST
    ) -> Amount:
        """
        Calls the ``eth_getBalance`` RPC method.
        """
        result = await self._provider_session.rpc(
            "eth_getBalance", address.encode(), encode_block(block)
        )
        return Amount.decode(result)

    @rpc_call("eth_getTransactionReceipt")
    async def eth_get_transaction_receipt(self, tx_hash: TxHash) -> Optional[TxReceipt]:
        """
        Calls the ``eth_getTransactionReceipt`` RPC method.
        """
        result = await self._provider_session.rpc_dict(
            "eth_getTransactionReceipt", tx_hash.encode()
        )
        if not result:
            return None

        contract_address = result["contractAddress"]

        return TxReceipt(
            succeeded=(decode_quantity(result["status"]) == 1),
            contract_address=Address.decode(contract_address) if contract_address else None,
            gas_used=decode_quantity(result["gasUsed"]),
        )

    @rpc_call("eth_getTransactionCount")
    async def eth_get_transaction_count(
        self, address: Address, block: Union[int, Block] = Block.LATEST
    ) -> int:
        """
        Calls the ``eth_getTransactionCount`` RPC method.
        """
        result = await self._provider_session.rpc(
            "eth_getTransactionCount", address.encode(), encode_block(block)
        )
        return decode_quantity(result)

    async def wait_for_transaction_receipt(
        self, tx_hash: TxHash, poll_latency: float = 1.0
    ) -> TxReceipt:
        """
        Queries the transaction receipt waiting for ``poll_latency`` between each attempt.
        """
        while True:
            receipt = await self.eth_get_transaction_receipt(tx_hash)
            if receipt:
                return receipt
            await anyio.sleep(poll_latency)

    @rpc_call("eth_call")
    async def eth_call(self, call: BoundReadCall, block: Union[int, Block] = Block.LATEST) -> Any:
        """
        Sends a prepared contact method call to the provided address.
        Returns the decoded output.
        """
        result = await self._provider_session.rpc(
            "eth_call",
            {
                "to": call.contract_address.encode(),
                "data": encode_data(call.data_bytes),
            },
            encode_block(block),
        )

        encoded_output = decode_data(result)
        return call.decode_output(encoded_output)

    @rpc_call("eth_sendRawTransaction")
    async def _eth_send_raw_transaction(self, tx_bytes: bytes) -> TxHash:
        """
        Sends a signed and serialized transaction.
        """
        result = await self._provider_session.rpc("eth_sendRawTransaction", encode_data(tx_bytes))
        return TxHash.decode(result)

    @rpc_call("eth_estimateGas")
    async def estimate_deploy(self, call: BoundConstructorCall, amount: Amount = Amount(0)) -> int:
        """
        Estimates the amount of gas required to deploy the contract with the given args.
        """
        tx = {
            "data": encode_data(call.data_bytes),
            "value": amount.encode(),
        }
        result = await self._provider_session.rpc("eth_estimateGas", tx, encode_block(Block.LATEST))
        return decode_quantity(result)

    @rpc_call("eth_estimateGas")
    async def estimate_transfer(
        self, source_address: Address, destination_address: Address, amount: Amount
    ) -> int:
        """
        Estimates the amount of gas required to transfer ``amount``.
        Raises an exception if there is not enough funds in ``source_address``.
        """
        # source_address and amount are optional,
        # but if they are specified, we will fail here instead of later.
        tx = {
            "from": source_address.encode(),
            "to": destination_address.encode(),
            "value": amount.encode(),
        }
        result = await self._provider_session.rpc("eth_estimateGas", tx, encode_block(Block.LATEST))
        return decode_quantity(result)

    @rpc_call("eth_estimateGas")
    async def estimate_transact(self, call: BoundWriteCall, amount: Amount = Amount(0)) -> int:
        """
        Estimates the amount of gas required to transact with a contract.
        """
        tx = {
            "to": call.contract_address.encode(),
            "data": encode_data(call.data_bytes),
            "value": amount.encode(),
        }
        result = await self._provider_session.rpc("eth_estimateGas", tx, encode_block(Block.LATEST))
        return decode_quantity(result)

    @rpc_call("eth_gasPrice")
    async def eth_gas_price(self) -> Amount:
        """
        Calls the ``eth_gasPrice`` RPC method.
        """
        result = await self._provider_session.rpc("eth_gasPrice")
        return Amount.decode(result)

    async def broadcast_transfer(
        self,
        signer: Signer,
        destination_address: Address,
        amount: Amount,
        gas: Optional[int] = None,
    ) -> TxHash:
        """
        Broadcasts the fund transfer transaction, but does not wait for it to be processed.
        If ``gas`` is ``None``, the required amount of gas is estimated first,
        otherwise the provided value is used.
        """
        chain_id = await self.eth_chain_id()
        if gas is None:
            gas = await self.estimate_transfer(signer.address, destination_address, amount)
        # TODO: implement gas strategies
        max_gas_price = await self.eth_gas_price()
        max_tip = Amount.gwei(1)
        nonce = await self.eth_get_transaction_count(signer.address, Block.LATEST)
        tx = {
            "type": 2,  # EIP-2930 transaction
            "chainId": encode_quantity(chain_id),
            "to": destination_address.encode(),
            "value": amount.encode(),
            "gas": encode_quantity(gas),
            "maxFeePerGas": max_gas_price.encode(),
            "maxPriorityFeePerGas": max_tip.encode(),
            "nonce": encode_quantity(nonce),
        }
        signed_tx = signer.sign_transaction(tx)
        return await self._eth_send_raw_transaction(signed_tx)

    async def transfer(
        self,
        signer: Signer,
        destination_address: Address,
        amount: Amount,
        gas: Optional[int] = None,
    ):
        """
        Transfers funds from the address of the attached signer to the destination address.
        If ``gas`` is ``None``, the required amount of gas is estimated first,
        otherwise the provided value is used.
        Waits for the transaction to be confirmed.
        """
        tx_hash = await self.broadcast_transfer(signer, destination_address, amount, gas=gas)
        receipt = await self.wait_for_transaction_receipt(tx_hash)
        if not receipt.succeeded:
            raise TransactionFailed(f"Transfer failed (receipt: {receipt})")

    async def deploy(
        self,
        signer: Signer,
        call: BoundConstructorCall,
        amount: Amount = Amount(0),
        gas: Optional[int] = None,
    ) -> DeployedContract:
        """
        Deploys the contract passing ``args`` to the constructor.
        If ``gas`` is ``None``, the required amount of gas is estimated first,
        otherwise the provided value is used.
        Waits for the transaction to be confirmed.
        """
        if not call.payable and amount.as_wei() != 0:
            raise ValueError("This constructor does not accept an associated payment")

        chain_id = await self.eth_chain_id()
        if gas is None:
            gas = await self.estimate_deploy(call, amount=amount)
        # TODO: implement gas strategies
        max_gas_price = await self.eth_gas_price()
        max_tip = Amount.gwei(1)
        nonce = await self.eth_get_transaction_count(signer.address, Block.LATEST)
        tx = {
            "type": 2,  # EIP-2930 transaction
            "chainId": encode_quantity(chain_id),
            "value": amount.encode(),
            "gas": encode_quantity(gas),
            "maxFeePerGas": max_gas_price.encode(),
            "maxPriorityFeePerGas": max_tip.encode(),
            "nonce": encode_quantity(nonce),
            "data": encode_data(call.data_bytes),
        }
        signed_tx = signer.sign_transaction(tx)
        tx_hash = await self._eth_send_raw_transaction(signed_tx)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

        if not receipt.succeeded:
            raise TransactionFailed(f"Deploy failed (receipt: {receipt})")

        if receipt.contract_address is None:
            raise BadResponseFormat(
                f"The deploy transaction succeeded, but `contractAddress` is not present "
                f"in the receipt ({receipt})"
            )

        return DeployedContract(call.contract_abi, receipt.contract_address)

    async def transact(
        self,
        signer: Signer,
        call: BoundWriteCall,
        amount: Amount = Amount(0),
        gas: Optional[int] = None,
    ):
        """
        Transacts with the contract using a prepared method call.
        If ``gas`` is ``None``, the required amount of gas is estimated first,
        otherwise the provided value is used.
        Waits for the transaction to be confirmed.
        """
        if not call.payable and amount.as_wei() != 0:
            raise ValueError("This method does not accept an associated payment")

        chain_id = await self.eth_chain_id()
        if gas is None:
            gas = await self.estimate_transact(call, amount=amount)
        # TODO: implement gas strategies
        max_gas_price = await self.eth_gas_price()
        max_tip = Amount.gwei(1)
        nonce = await self.eth_get_transaction_count(signer.address, Block.LATEST)
        tx = {
            "type": 2,  # EIP-2930 transaction
            "chainId": encode_quantity(chain_id),
            "to": call.contract_address.encode(),
            "value": amount.encode(),
            "gas": encode_quantity(gas),
            "maxFeePerGas": max_gas_price.encode(),
            "maxPriorityFeePerGas": max_tip.encode(),
            "nonce": encode_quantity(nonce),
            "data": encode_data(call.data_bytes),
        }
        signed_tx = signer.sign_transaction(tx)
        tx_hash = await self._eth_send_raw_transaction(signed_tx)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

        if not receipt.succeeded:
            raise TransactionFailed(f"Transact failed (receipt: {receipt})")
