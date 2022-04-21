from eth_account import Account
import pytest
import trio

from pons import Client, AccountSigner, Address, Amount


async def test_payment(test_provider):

    client = Client(provider=test_provider)

    root_account = test_provider.root_account
    root_signer = AccountSigner(root_account)

    acc1 = Account.create()

    root_address = Address.from_hex(root_account.address)
    acc1_address = Address.from_hex(acc1.address)

    # Fund the deployer account
    async with client.session() as session:
        root_balance = await session.get_balance(root_address)
        to_transfer = Amount.ether(10)
        await session.transfer(root_signer, acc1_address, to_transfer)
        # TODO: check that block has changed
        root_balance_after = await session.get_balance(root_address)
        acc1_balance_after = await session.get_balance(acc1_address)
        assert acc1_balance_after == to_transfer
        assert root_balance - root_balance_after > to_transfer
