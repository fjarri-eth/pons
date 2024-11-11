Changelog
---------


0.8.0 (2024-05-28)
~~~~~~~~~~~~~~~~~~

Changed
^^^^^^^

- Added an explicit ``typing_extensions`` dependency. (PR_57_)
- Various boolean arguments are now keyword-only to prevent usage errors. (PR_57_)
- Field names clashing with Python built-ins (``hash``, ``type``, ``id``) are suffixed with an underscore. (PR_57_)
- ``AccountSigner`` takes ``LocalSigner`` specifically and not just any ``BaseSigner``. (PR_62_)
- ``ClientSession.estimate_transact()`` and ``estimate_deploy()`` now require a ``sender_address`` parameter. (PR_62_)
- Switched to ``alysis`` from ``eth-tester`` for the backend of ``LocalProvider``. (PR_70_)
- Bumped the minimum Python version to 3.10. (PR_72_)
- The entities are now dataclasses instead of namedtuples. (PR_75_)
- Bumped ``eth-account`` to ``0.13``. (PR_76_)
- Use the types from ``ethereum-rpc``. (PR_77_)


Added
^^^^^

- ``Client.transact()`` takes an optional ``return_events`` argument, allowing one to get "return values" from the transaction via events. (PR_52_)
- Exposed ``ClientSession``, ``ConstructorCall``, ``MethodCall``, ``EventFilter``, ``BoundConstructor``, ``BoundConstructorCall``, ``BoundMethod``, ``BoundMethodCall``, ``BoundEvent``, ``BoundEventFilter`` from the top level. (PR_56_)
- Various methods that had a default ``Amount(0)`` for a parameter can now take ``None``. (PR_57_)
- Support for overloaded methods via ``MultiMethod``. (PR_59_)
- Expose ``HTTPProviderServer``, ``LocalProvider``, ``compile_contract_file`` that can be used for tests of Ethereum-using applications. These are gated behind optional features. (PR_54_)
- ``LocalProvider.take_snapshot()`` and ``revert_to_snapshot()``. (PR_61_)
- ``AccountSigner.private_key`` property. (PR_62_)
- ``LocalProvider.add_account()`` method. (PR_62_)
- An optional ``sender_address`` parameter of ``ClientSession.eth_call()``. (PR_62_)
- Expose ``Provider`` at the top level. (PR_63_)
- ``eth_getCode`` support (as ``ClientSession.eth_get_code()``). (PR_64_)
- ``eth_getStorageAt`` support (as ``ClientSession.eth_get_storage_at()``). (PR_64_)
- Support for the ``logs`` field in ``TxReceipt``. (PR_68_)
- ``ClientSession.eth_get_logs()`` and ``eth_get_filter_logs()``. (PR_68_)
- Support for a custom block number in gas estimation methods. (PR_70_)
- ``LocalProvider`` accepts an ``evm_version`` parameter. (PR_78_)
- ``get_create2_address()``. (PR_80_)
- ``get_create_address()``. (PR_80_)


Fixed
^^^^^

- Process unnamed arguments in JSON entries correctly (as positional arguments). (PR_51_)
- More robust error handling in HTTP provider. (PR_63_)
- The transaction tip being set larger than the max gas price (which some providers don't like). (PR_64_)
- Decoding error when fetching pending transactions. (PR_65_)
- Decoding error when fetching pending blocks. (PR_67_)
- Get the default nonce based on the pending block, not the latest one. (PR_68_)
- Using ``eth_getLogs`` instead of creating a filter in ``transact()``. (PR_70_)
- Expect the block number to be non-null even for pending blocks, since that's what providers return. (PR_70_)


.. _PR_51: https://github.com/fjarri-eth/pons/pull/51
.. _PR_52: https://github.com/fjarri-eth/pons/pull/52
.. _PR_54: https://github.com/fjarri-eth/pons/pull/54
.. _PR_56: https://github.com/fjarri-eth/pons/pull/56
.. _PR_57: https://github.com/fjarri-eth/pons/pull/57
.. _PR_59: https://github.com/fjarri-eth/pons/pull/59
.. _PR_61: https://github.com/fjarri-eth/pons/pull/61
.. _PR_62: https://github.com/fjarri-eth/pons/pull/62
.. _PR_63: https://github.com/fjarri-eth/pons/pull/63
.. _PR_64: https://github.com/fjarri-eth/pons/pull/64
.. _PR_65: https://github.com/fjarri-eth/pons/pull/65
.. _PR_67: https://github.com/fjarri-eth/pons/pull/67
.. _PR_68: https://github.com/fjarri-eth/pons/pull/68
.. _PR_70: https://github.com/fjarri-eth/pons/pull/70
.. _PR_72: https://github.com/fjarri-eth/pons/pull/72
.. _PR_75: https://github.com/fjarri-eth/pons/pull/75
.. _PR_76: https://github.com/fjarri-eth/pons/pull/76
.. _PR_77: https://github.com/fjarri-eth/pons/pull/77
.. _PR_78: https://github.com/fjarri-eth/pons/pull/78
.. _PR_80: https://github.com/fjarri-eth/pons/pull/80


0.7.0 (09-07-2023)
~~~~~~~~~~~~~~~~~~

Changed
^^^^^^^

- ``ReadMethod`` and ``WriteMethod`` were merged into ``Method`` (with the corresponding merge of ``ContractABI`` routing objects and various bound calls). (PR_50_)


Added
^^^^^

- ``Block.SAFE`` and ``Block.FINALIZED`` values. (PR_48_)
- ``FallbackProvider``, two strategies for it (``CycleFallback`` and ``PriorityFallback``), and a framework for creating user-defined strategies (``FallbackStrategy`` and ``FallbackStrategyFactory``). (PR_49_)
- ``Mutability`` enum for defining contract method mutability. (PR_50_)


.. _PR_48: https://github.com/fjarri-eth/pons/pull/48
.. _PR_49: https://github.com/fjarri-eth/pons/pull/49
.. _PR_50: https://github.com/fjarri-eth/pons/pull/50



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


.. _PR_47: https://github.com/fjarri-eth/pons/pull/47


0.5.1 (14-11-2022)
~~~~~~~~~~~~~~~~~~

Fixed
^^^^^

- A bug in processing keyword arguments to contract calls. (PR_42_)


.. _PR_42: https://github.com/fjarri-eth/pons/pull/42


0.5.0 (14-09-2022)
~~~~~~~~~~~~~~~~~~

Changed
^^^^^^^

- Bumped dependencies: ``eth-account>=0.6``, ``eth-utils>=2``, ``eth-abi>=3``. (PR_40_)


Fixed
^^^^^

- Return type of classmethods of ``Amount`` and ``Address`` now provides correct information to ``mypy`` in dependent projects. (PR_37_)


.. _PR_37: https://github.com/fjarri-eth/pons/pull/37
.. _PR_40: https://github.com/fjarri-eth/pons/pull/40


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


.. _PR_32: https://github.com/fjarri-eth/pons/pull/32
.. _PR_33: https://github.com/fjarri-eth/pons/pull/33


0.4.1 (01-05-2022)
~~~~~~~~~~~~~~~~~~

Added
^^^^^

- ``anyio`` support instead of just ``trio``. (PR_27_)
- Raise ``ABIDecodingError`` on mismatch between the declared contract ABI and the bytestring returned from ``ethCall``. (PR_29_)
- Support for gas overrides in ``transfer()``, ``transact()``, and ``deploy()``. (PR_30_)


.. _PR_27: https://github.com/fjarri-eth/pons/pull/27
.. _PR_29: https://github.com/fjarri-eth/pons/pull/29
.. _PR_30: https://github.com/fjarri-eth/pons/pull/30


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


.. _PR_4: https://github.com/fjarri-eth/pons/pull/4
.. _PR_5: https://github.com/fjarri-eth/pons/pull/5


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


.. _PR_1: https://github.com/fjarri-eth/pons/pull/1
.. _PR_2: https://github.com/fjarri-eth/pons/pull/2
.. _PR_3: https://github.com/fjarri-eth/pons/pull/3


0.2.0 (19-03-2022)
~~~~~~~~~~~~~~~~~~

Initial release.
