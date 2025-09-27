from pathlib import Path

import pytest
from ethereum_rpc import Amount

from pons import (
    AccountSigner,
    ClientSession,
    CompiledContract,
    ContractLegacyError,
    DeployedContract,
    Multicall,
    compile_contract_file,
)


@pytest.fixture
def multicall_compiled() -> CompiledContract:
    path = Path(__file__).resolve().parent / "Multicall3.sol"
    compiled = compile_contract_file(path)
    return compiled["Multicall3"]


@pytest.fixture
def target_compiled() -> CompiledContract:
    path = Path(__file__).resolve().parent / "TestMulticall.sol"
    compiled = compile_contract_file(path)
    return compiled["TestMulticall"]


@pytest.fixture
async def multicall(
    session: ClientSession, root_signer: AccountSigner, multicall_compiled: CompiledContract
) -> Multicall:
    multicall_deployed = await session.deploy(root_signer, multicall_compiled.constructor())
    return Multicall(multicall_deployed.address)


@pytest.fixture
async def target(
    session: ClientSession, root_signer: AccountSigner, target_compiled: CompiledContract
) -> DeployedContract:
    return await session.deploy(root_signer, target_compiled.constructor())


async def test_multicall_read(
    session: ClientSession, multicall: Multicall, target: DeployedContract
) -> None:
    results = await session.call(multicall.aggregate([target.method.x1(), target.method.x2()]))
    assert results[0] == (True, (1,))
    assert results[1] == (True, (2,))


async def test_multicall_write(
    session: ClientSession,
    root_signer: AccountSigner,
    multicall: Multicall,
    target: DeployedContract,
) -> None:
    await session.transact(
        root_signer, multicall.aggregate([target.method.write1(3), target.method.write2(4)])
    )
    assert await session.call(target.method.x1()) == (3,)
    assert await session.call(target.method.x2()) == (4,)


async def test_multicall_read_error(
    session: ClientSession, multicall: Multicall, target: DeployedContract
) -> None:
    # For now `eth_call` does not decode contract errors, so we get the low-level one.
    with pytest.raises(ContractLegacyError, match="Multicall3: call failed"):
        await session.call(
            multicall.aggregate([target.method.x1(), target.method.read_error()]),
        )

    results = await session.call(
        multicall.aggregate([target.method.x1(), target.method.read_error()], allow_failure=True),
    )
    assert results[0] == (True, (1,))  # successful call
    assert results[1] == (False, ())  # errored call


async def test_multicall_write_error(
    session: ClientSession,
    root_signer: AccountSigner,
    multicall: Multicall,
    target: DeployedContract,
) -> None:
    with pytest.raises(ContractLegacyError, match="Multicall3: call failed"):
        await session.transact(
            root_signer,
            multicall.aggregate([target.method.write1(3), target.method.write2_error()]),
        )

    # The values remained unchanged
    assert await session.call(target.method.x1()) == (1,)
    assert await session.call(target.method.x2()) == (2,)

    await session.transact(
        root_signer,
        multicall.aggregate(
            [target.method.write1(3), target.method.write2_error()], allow_failure=True
        ),
    )

    # The successful call updated the value
    assert await session.call(target.method.x1()) == (3,)

    # The reverted call did not update the value
    assert await session.call(target.method.x2()) == (2,)


async def test_multicall_read_value(
    session: ClientSession, multicall: Multicall, target: DeployedContract
) -> None:
    results = await session.call(
        multicall.aggregate_value(
            [(target.method.x1(), Amount.wei(0)), (target.method.x2(), Amount.wei(0))]
        )
    )
    assert results[0] == (True, (1,))
    assert results[1] == (True, (2,))


async def test_multicall_write_value(
    session: ClientSession,
    root_signer: AccountSigner,
    multicall: Multicall,
    target: DeployedContract,
) -> None:
    await session.transact(
        root_signer,
        multicall.aggregate_value(
            [
                (target.method.write1_value(), Amount.wei(100)),
                (target.method.write2_value(), Amount.wei(200)),
            ]
        ),
        amount=Amount.wei(300),
    )
    assert await session.call(target.method.x1()) == (100,)
    assert await session.call(target.method.x2()) == (200,)


async def test_multicall_write_value_insufficient_funds(
    session: ClientSession,
    root_signer: AccountSigner,
    multicall: Multicall,
    target: DeployedContract,
) -> None:
    with pytest.raises(ContractLegacyError, match="Multicall3: call failed"):
        await session.transact(
            root_signer,
            multicall.aggregate_value(
                [
                    (target.method.write1_value(), Amount.wei(100)),
                    (target.method.write2_value(), Amount.wei(200)),
                ]
            ),
            amount=Amount.wei(200),
        )
