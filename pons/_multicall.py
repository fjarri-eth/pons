from collections.abc import Iterable
from typing import Any

from ethereum_rpc import Address, Amount

from . import abi
from ._contract import BaseBoundMethodCall, BoundMethodCall, DeployedContract
from ._contract_abi import ContractABI, Method, Mutability

_Call3 = abi.struct(target=abi.address, allowFailure=abi.bool, callData=abi.bytes())
_Call3Value = abi.struct(
    target=abi.address, allowFailure=abi.bool, value=abi.uint(256), callData=abi.bytes()
)
_Result = abi.struct(success=abi.bool, returnData=abi.bytes())

_MULTICALL3_ABI = ContractABI(
    methods=[
        Method(
            name="aggregate3",
            mutability=Mutability.PAYABLE,
            inputs=dict(calls=_Call3[...]),
            outputs=_Result[...],
        ),
        Method(
            name="aggregate3Value",
            mutability=Mutability.PAYABLE,
            inputs=dict(calls=_Call3Value[...]),
            outputs=_Result[...],
        ),
    ],
)


class BoundMultiMethodCall(BaseBoundMethodCall):
    def __init__(
        self,
        calls: Iterable[BoundMethodCall],
        multicall3_address: Address,
        *,
        allow_failure: bool = False,
    ):
        multicall3_deployed = DeployedContract(_MULTICALL3_ABI, multicall3_address)
        unstructured = [[call.contract_address, allow_failure, call.data_bytes] for call in calls]

        self._calls = list(calls)
        self._call = multicall3_deployed.method.aggregate3(unstructured)

        self._contract_address = multicall3_address

        self._mutating = any(call.mutating for call in calls)
        self._payable = any(call.payable for call in calls)
        self._contract_abi = multicall3_deployed.abi

    @property
    def contract_abi(self) -> ContractABI:
        return self._contract_abi

    @property
    def data_bytes(self) -> bytes:
        return self._call.data_bytes

    @property
    def payable(self) -> bool:
        return self._payable

    @property
    def mutating(self) -> bool:
        return self._mutating

    @property
    def contract_address(self) -> Address:
        return self._contract_address

    def decode_output(self, output_bytes: bytes) -> list[Any]:
        decoded_results = []
        results = self._call.decode_output(output_bytes)
        for call, result in zip(self._calls, results, strict=True):
            decoded = call.decode_output(result["returnData"])
            decoded_results.append((result["success"], decoded))
        return decoded_results


class BoundMultiMethodValueCall(BoundMethodCall):
    def __init__(
        self,
        calls: Iterable[tuple[BoundMethodCall, Amount]],
        multicall3_address: Address,
        *,
        allow_failure: bool = False,
    ):
        multicall3_deployed = DeployedContract(_MULTICALL3_ABI, multicall3_address)
        unstructured = [
            [call.contract_address, allow_failure, amount.as_wei(), call.data_bytes]
            for call, amount in calls
        ]

        self._calls = list(calls)
        self._call = multicall3_deployed.method.aggregate3Value(unstructured)

        self._contract_address = multicall3_address

        self._mutating = any(call.mutating for call, _ in calls)
        self._payable = any(call.payable for call, _ in calls)
        self._contract_abi = multicall3_deployed.abi

    @property
    def contract_abi(self) -> ContractABI:
        return self._contract_abi

    @property
    def data_bytes(self) -> bytes:
        return self._call.data_bytes

    @property
    def payable(self) -> bool:
        return self._payable

    @property
    def mutating(self) -> bool:
        return self._mutating

    @property
    def contract_address(self) -> Address:
        return self._contract_address

    def decode_output(self, output_bytes: bytes) -> list[Any]:
        decoded_results = []
        results = self._call.decode_output(output_bytes)
        for (call, _amount), result in zip(self._calls, results, strict=True):
            decoded = call.decode_output(result["returnData"])
            decoded_results.append((result["success"], decoded))
        return decoded_results


class Multicall:
    """A helper for interacting with the Multicall contract (v3)."""

    def __init__(self, multicall3_address: Address):
        self._multicall3_deployed = DeployedContract(_MULTICALL3_ABI, multicall3_address)

    def aggregate(
        self, calls: Iterable[BoundMethodCall], *, allow_failure: bool = False
    ) -> BoundMultiMethodCall:
        """
        Creates an aggregated call out of provided ``calls``.
        The return value is a list of tuples ``(success: bool, result: Any)``
        in the same order as ``calls``.

        If at least one of the calls is mutating, the resulting call will be mutating as well.

        If ``allow_failure`` is ``False``, a contract error in one of the calls will result in
        a contract error being raised.
        If it is ``True``, any contract errors will be recorded in the corresponding return values,
        but no exception will be raised.

        .. note::

            If ``allow_failure`` is ``True``, and one of the calls reverts,
            the successful calls will not be reverted as well.
        """
        return BoundMultiMethodCall(
            calls, self._multicall3_deployed.address, allow_failure=allow_failure
        )

    def aggregate_value(
        self, calls: Iterable[tuple[BoundMethodCall, Amount]], *, allow_failure: bool = False
    ) -> BoundMultiMethodValueCall:
        """
        Same as :py:meth:`aggregate`, but takes an associated amount that will be passed
        to the corresponding method.
        The sum of the amounts must be lesser or equal to the amount passed with the invocation
        of the aggregated call.
        """
        return BoundMultiMethodValueCall(
            calls, self._multicall3_deployed.address, allow_failure=allow_failure
        )
