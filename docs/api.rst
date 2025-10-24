API
===

.. module:: pons


Clients
-------

.. autoclass:: Client
   :members:

.. autoclass:: ClientSession()
   :members:

.. autoclass:: ClientSessionRPC()
   :members:


Providers
---------

.. autoclass:: Provider
   :show-inheritance:

.. autoclass:: ProviderPath()


HTTP
^^^^

Install the feature ``http-provider`` for the ``http_provider`` module to be available.

.. autoclass:: pons.http_provider.HTTPProvider
   :show-inheritance:

.. autoclass:: pons.http_provider.HTTPError()
   :show-inheritance:
   :members:


Fallback providers
------------------

.. autoclass:: FallbackProvider
   :show-inheritance:
   :members: errors

.. autoclass:: CycleFallback
   :show-inheritance:

.. autoclass:: PriorityFallback
   :show-inheritance:

.. autoclass:: FallbackStrategyFactory
   :show-inheritance:
   :members:

.. autoclass:: FallbackStrategy
   :show-inheritance:
   :members:


Errors
------

Provider level
^^^^^^^^^^^^^^

.. autoclass:: ProviderError
   :show-inheritance:
   :members:

.. autoclass:: InvalidResponse
   :show-inheritance:

.. autoclass:: Unreachable
   :show-inheritance:

.. autoclass:: ProtocolError
   :show-inheritance:


Client level
^^^^^^^^^^^^

.. autoclass:: BadResponseFormat
   :show-inheritance:

.. autoclass:: ABIDecodingError
   :show-inheritance:

.. autoclass:: TransactionFailed
   :show-inheritance:

.. autoclass:: pons._client.ContractPanicReason
   :members:

.. autoclass:: ContractPanic()
   :show-inheritance:
   :members:

.. autoclass:: ContractLegacyError()
   :show-inheritance:
   :members:

.. autoclass:: ContractError()
   :show-inheritance:
   :members:


Signers
-------

.. autoclass:: Signer
   :show-inheritance:
   :members:

.. autoclass:: AccountSigner
   :show-inheritance:
   :members:


Contract ABI
------------

.. class:: ABI_JSON

   A JSON-ifiable object (``bool``, ``int``, ``float``, ``str``, ``None``,
   iterable of ``JSON``, or mapping of ``str`` to ``JSON``).

.. autoclass:: ContractABI
   :members:

.. autoclass:: Mutability
   :members:

.. autoclass:: Constructor
   :members:
   :special-members: __call__

.. autoclass:: Method
   :members:
   :special-members: __call__

.. autoclass:: MultiMethod
   :members:
   :special-members: __call__

.. autoclass:: Event
   :members:

.. autoclass:: Error
   :members:

.. autoclass:: Fallback
   :members:

.. autoclass:: Receive
   :members:

.. autoclass:: Fields
   :members:

.. autoclass:: EventFields
   :members:
   :show-inheritance:

.. autoclass:: FieldValues
   :members:
   :special-members: __getitem__, __getattr__


Testing utilities
-----------------

``pons`` exposes several types useful for testing applications that connect to Ethereum RPC servers. Not intended for the production environment.

Install the feature ``local-provider`` for the ``local_provider`` module to be available.

.. autoclass:: pons.local_provider.LocalProvider
   :show-inheritance:
   :members: disable_auto_mine_transactions, enable_auto_mine_transactions, take_snapshot, revert_to_snapshot, root

.. autoclass:: pons.local_provider.SnapshotID()

Install the feature ``http-provider-server`` for the ``http_provider_server`` module to be available.

.. autoclass:: pons.http_provider_server.HTTPProviderServer
   :members:
   :special-members: __call__


Compiler
--------

Install with the feature ``compiler`` for it to be available.


.. autofunction:: pons.compiler.compile_contract_file

.. autoclass:: pons.compiler.EVMVersion
   :members:


Multicall contract
------------------

The library includes a helper for interacting with the Multicall contract (https://github.com/mds1/multicall3).


.. autoclass:: Multicall
   :members:

.. autoclass:: BoundMultiMethodCall
   :show-inheritance:
   :members:

.. autoclass:: BoundMultiMethodValueCall
   :show-inheritance:
   :members:



Secondary classes
-----------------

The instances of these classes are not created by the user directly, but rather found as return values, or attributes of other objects.


.. autoclass:: ConstructorCall()
   :members:

.. autoclass:: MethodCall()
   :members:

.. autoclass:: EventFilter()
   :members:

.. autoclass:: BoundConstructor()
   :members:
   :special-members: __call__

.. autoclass:: BoundConstructorCall()
   :members:

.. autoclass:: BoundMethod()
   :members:
   :special-members: __call__

.. autoclass:: BaseBoundMethodCall()
   :members:

.. autoclass:: BoundMethodCall()
   :show-inheritance:
   :members:

.. autoclass:: BoundEvent()
   :members:
   :special-members: __call__

.. autoclass:: BoundEventFilter()
   :members:


Utility classes
---------------

.. autoclass:: pons._contract_abi.Methods()
   :members:
   :special-members: __getattr__, __iter__

.. class:: pons._contract_abi.MethodType

   Generic method type parameter.


Utility methods
---------------

.. autofunction:: get_create_address

.. autofunction:: get_create2_address


Compiled and deployed contracts
-------------------------------

.. autoclass:: CompiledContract
   :members:

.. autoclass:: DeployedContract
   :members:


Filter objects
--------------

.. autoclass:: BlockFilter()

.. autoclass:: PendingTransactionFilter()

.. autoclass:: LogFilter()


Solidity types
--------------

Type aliases are exported from the ``abi`` submodule.
Arrays can be obtained from ``Type`` objects by indexing them (either with an integer for a fixed-size array, or with ``...`` for a variable-sized array).

Helper aliases are exported from ``pons.abi`` submodule:

.. autofunction:: pons.abi.uint

.. autofunction:: pons.abi.int

.. autofunction:: pons.abi.bytes

.. autodata:: pons.abi.address
   :no-value:

.. autodata:: pons.abi.string
   :no-value:

.. autodata:: pons.abi.bool
   :no-value:

.. autofunction:: pons.abi.struct


Actual type objects, for reference:

.. autoclass:: pons._abi_types.Type

.. autoclass:: pons._abi_types.UInt

.. autoclass:: pons._abi_types.Int

.. autoclass:: pons._abi_types.Bytes

.. autoclass:: pons._abi_types.AddressType

.. autoclass:: pons._abi_types.String

.. autoclass:: pons._abi_types.Bool

.. autoclass:: pons._abi_types.Struct
