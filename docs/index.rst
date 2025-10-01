Pons, an async Ethereum RPC client
==================================

.. highlight:: python

A quick usage example:

.. testsetup::

    import os
    import trio
    import pons
    import eth_account
    import ethereum_rpc

    from ethereum_rpc import Amount
    from pons import LocalProvider, HTTPProviderServer

    # Run examples with our test server in the background

    orig_trio_run = trio.run

    def mock_trio_run(func):
        async def wrapper():
            await run_with_server(func)

        orig_trio_run(wrapper)

    trio.run = mock_trio_run

    # This variable will be set when the server is started

    http_provider = None
    pons.HTTPProvider = lambda uri: http_provider

    # This variable will be set when the LocalProvider is created

    root_signer = None
    orig_Account_from_key = eth_account.Account.from_key

    def mock_Account_from_key(private_key_hex):
        if private_key_hex == "0x<your secret key>":
            return root_signer.account
        else:
            return orig_Account_from_key(private_key_hex)

    eth_account.Account.from_key = mock_Account_from_key

    # So that we don't have to use real addresses

    orig_Address_from_hex = ethereum_rpc.Address.from_hex

    def mock_Address_from_hex(address_hex):
        if address_hex == "0x<another_address>":
            return Address(os.urandom(20))
        else:
            return orig_Address_from_hex(address_hex)

    ethereum_rpc.Address.from_hex = mock_Address_from_hex

    # This function will start a test server and fill in some global variables

    async def run_with_server(func):
        global root_signer
        global http_provider

        local_provider = LocalProvider(root_balance=Amount.ether(100))
        root_signer = local_provider.root

        async with trio.open_nursery() as nursery:
            handle = HTTPProviderServer(local_provider)
            http_provider = handle.http_provider
            await nursery.start(handle)
            await func()
            await handle.shutdown()

.. testcode::

    import trio

    from eth_account import Account
    from ethereum_rpc import Address, Amount
    from pons import Client, HTTPProvider, AccountSigner

    async def main():

        provider = HTTPProvider("<your provider's https endpoint>")
        client = Client(provider)

        acc = Account.from_key("0x<your secret key>")
        signer = AccountSigner(acc)

        async with client.session() as session:
            my_balance = await session.get_balance(signer.address)
            print("My balance:", my_balance.as_ether(), "ETH")

            another_address = Address.from_hex("0x<another_address>")
            await session.transfer(signer, another_address, Amount.ether(1.5))

            another_balance = await session.get_balance(another_address)
            print("Another balance:", another_balance.as_ether(), "ETH")

    trio.run(main)

.. testoutput::

    My balance: 100.0 ETH
    Another balance: 1.5 ETH


For more usage information, proceed to :ref:`tutorial`.


.. toctree::
   :maxdepth: 2
   :caption: Contents:

   tutorial
   api
   changelog


Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

