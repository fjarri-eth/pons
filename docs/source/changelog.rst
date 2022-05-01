Changelog
---------


Unreleased
~~~~~~~~~~

Added
^^^^^

- ``anyio`` support instead of just ``trio``. (PR_27_)
- Raise ``ABIDecodingError`` on mismatch between the declared contract ABI and the bytestring returned from ``ethCall``. (PR_29_)


.. _PR_27: https://github.com/fjarri/pons/pull/27
.. _PR_29: https://github.com/fjarri/pons/pull/29


0.4.0 (23-04-2022)
~~~~~~~~~~~~~~~~~~

Changed
^^^^^^^

- Added type/value checks when normalizing contract arguments. (PR_4_)
- Unpacking contract call results into specific types. (PR_4_)
- ``Address.as_checksum()`` renamed to ``Address.checksum`` (a cached property). (PR_5_)
- ``ContractABI`` and related types reworked. (PR_5_)


Added
^^^^^

- Allowed one to declare ABI via Python calls instead of JSON. (PR_4_)
- Support for binding of contract arguments to named parameters. (PR_4_)
- An ``abi.struct()`` function to create struct types in contract definitions. (PR_5_)
- Hashing, more comparisons and arithmetic functions for ``Amount``. (PR_5_)
- Hashing and equality for ``TxHash``. (PR_5_)
- An empty nonpayable constructor is created for a contract if none is specified. (PR_5_)
- ``RemoteError`` and ``Unreachable`` exception types to report errors from client sessions in a standardized way. (PR_5_)


.. _PR_4: https://github.com/fjarri/pons/pull/4
.. _PR_5: https://github.com/fjarri/pons/pull/5


0.3.0 (03-04-2022)
~~~~~~~~~~~~~~~~~~

Changed
^^^^^^^

- Merged ``SigningClient`` into ``Client``, with the methods of the former now requiring an explicit ``Signer`` argument. (PR_1_)
- Exposed provider sessions via ``Client.session()`` context manager; all the client methods were moved to the returned session object. (PR_1_)


Fixed
^^^^^

- Multiple fixes for typing of methods. (PR_1_)
- Fixed the handling of array-of-array ABI types. (PR_2_)
- Replaced assertions with more informative exceptions. (PR_3_)


.. _PR_1: https://github.com/fjarri/pons/pull/1
.. _PR_2: https://github.com/fjarri/pons/pull/2
.. _PR_3: https://github.com/fjarri/pons/pull/3


0.2.0 (19-03-2022)
~~~~~~~~~~~~~~~~~~

Initial release.
