Pons, an async Ethereum RPC client
==================================

.. highlight:: python

A quick usage example:

::

   import trio

   from eth_account import Account
   from pons import Client, HTTPProvider, AccountSigner, Address, Amount

   async def main():

      provider = HTTPProvider("<your provider's https endpoint>")
      client = Client(provider)

      acc = Account.from_key("0x<your secret key>")
      signer = AccountSigner(acc)

      async with client.session() as session:
         my_balance = await session.eth_get_balance(signer.address)
         print(my_balance)

         another_address = Address.from_hex("0x<some address>")
         await session.transfer(signer, another_address, Amount.ether(1.5))

         my_balance = await session.eth_get_balance(signer.address)
         print(my_balance)


   trio.run(main)


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

