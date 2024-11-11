API
===

.. automodule:: pons


Clients
-------

.. autoclass:: Client
   :members:

.. autoclass:: ClientSession()
   :members:


Providers
---------

.. autoclass:: Provider

.. autoclass:: HTTPProvider
   :show-inheritance:


Fallback providers
------------------

.. autoclass:: FallbackProvider
   :show-inheritance:

.. autoclass:: CycleFallback
   :show-inheritance:

.. autoclass:: PriorityFallback
   :show-inheritance:

.. autoclass:: FallbackStrategyFactory
   :members:

.. autoclass:: FallbackStrategy
   :members:


Errors
------

.. autoclass:: pons.ABIDecodingError

.. autoclass:: pons.RemoteError

.. autoclass:: pons.Unreachable

.. autoclass:: pons.ProtocolError

.. autoclass:: pons.TransactionFailed

.. autoclass:: pons.ProviderError()
   :show-inheritance:
   :members:

.. autoclass:: pons._client.ContractPanicReason
   :members:

.. autoclass:: pons.ContractPanic()
   :show-inheritance:
   :members:

.. autoclass:: pons.ContractLegacyError()
   :show-inheritance:
   :members:

.. autoclass:: pons.ContractError()
   :show-inheritance:
   :members:


Signers
-------

.. autoclass:: Signer
   :members:

.. autoclass:: AccountSigner
   :members:
   :show-inheritance:


Contract ABI
------------

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


Testing utilities
-----------------

``pons`` exposes several types useful for testing applications that connect to Ethereum RPC servers. Not intended for the production environment.

Install with the feature ``local-provider`` for it to be available.


.. autoclass:: LocalProvider
   :show-inheritance:
   :members: disable_auto_mine_transactions, enable_auto_mine_transactions, take_snapshot, revert_to_snapshot

.. autoclass:: SnapshotID

.. autoclass:: HTTPProviderServer
   :members:
   :special-members: __call__


Compiler
--------

Install with the feature ``compiler`` for it to be available.


.. autofunction:: compile_contract_file

.. autoclass:: EVMVersion
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

.. autoclass:: BoundMethodCall()
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

.. autoclass:: pons._contract_abi.Signature()
   :members: canonical_form

.. autoclass:: pons._contract_abi.Method
   :members:


Utility methods
---------------

.. autofunction:: pons.get_create_address

.. autofunction:: pons.get_create2_address


Compiled and deployed contracts
-------------------------------

.. autoclass:: CompiledContract
   :members:

.. autoclass:: DeployedContract
   :members:


Filter objects
--------------

.. autoclass:: pons._client.BlockFilter()

.. autoclass:: pons._client.PendingTransactionFilter()

.. autoclass:: pons._client.LogFilter()


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
