Changelog
---------


0.6.0 (11-05-2023)
~~~~~~~~~~~~~~~~~~

Changed
^^^^^^^

- Parameter names and fields coinciding with Python keywords have ``_`` appended to them on the creation of ABI objects. (PR_47_)


Added
^^^^^

- Added support for Python 3.11. (PR_47_)


Fixed
^^^^^

- Support the existence of outputs in the JSON ABI of a mutating method. (PR_47_)


.. _PR_47: https://github.com/fjarri/pons/pull/47


0.5.1 (14-11-2022)
~~~~~~~~~~~~~~~~~~

Fixed
^^^^^

- A bug in processing keyword arguments to contract calls. (PR_42_)


.. _PR_42: https://github.com/fjarri/pons/pull/42


0.5.0 (14-09-2022)
~~~~~~~~~~~~~~~~~~

Changed
^^^^^^^

- Bumped dependencies: ``eth-account>=0.6``, ``eth-utils>=2``, ``eth-abi>=3``. (PR_40_)


Fixed
^^^^^

- Return type of classmethods of ``Amount`` and ``Address`` now provides correct information to ``mypy`` in dependent projects. (PR_37_)


.. _PR_37: https://github.com/fjarri/pons/pull/37
.. _PR_40: https://github.com/fjarri/pons/pull/40


0.4.2 (05-06-2022)
~~~~~~~~~~~~~~~~~~

Added
^^^^^

- ``__repr__``/``__eq__``/``__hash__`` implementations for multiple entities. (PR_32_)
- ``eth_get_transaction_by_hash()``, ``eth_block_number()``, ``eth_get_block_by_hash()``, ``eth_get_block_by_number()`` and corresponding entities. (PR_32_)
- ``eth_new_block_filter()``, ``eth_new_pending_transaction_filter()``, ``eth_new_filter()``, ``eth_get_filter_changes()`` for low-level event filtering support. (PR_32_)
- ``iter_blocks()``, ``iter_pending_transactions()``, ``iter_events()`` for high-level event filtering support. (PR_32_)
- More fields in ``TxReceipt``. (PR_32_)
- ``Error`` class for Contract ABI, and support of ``type="error"`` declarations in JSON ABI. (PR_33_)
- Error data parsing and matching it with known errors from the ABI when calling ``estimate_transact()`` and ``estimate_deploy()``. (PR_33_)


Fixed
^^^^^

- Removed ``TxReceipt`` export (making an exception here and not counting it as a breaking change, since nobody would have any use for creating one manually). (PR_32_)


.. _PR_32: https://github.com/fjarri/pons/pull/32
.. _PR_33: https://github.com/fjarri/pons/pull/33


0.4.1 (01-05-2022)
~~~~~~~~~~~~~~~~~~

Added
^^^^^

- ``anyio`` support instead of just ``trio``. (PR_27_)
- Raise ``ABIDecodingError`` on mismatch between the declared contract ABI and the bytestring returned from ``ethCall``. (PR_29_)
- Support for gas overrides in ``transfer()``, ``transact()``, and ``deploy()``. (PR_30_)


.. _PR_27: https://github.com/fjarri/pons/pull/27
.. _PR_29: https://github.com/fjarri/pons/pull/29
.. _PR_30: https://github.com/fjarri/pons/pull/30


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
