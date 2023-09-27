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

.. autoclass:: pons._provider.Provider

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

.. autoclass:: pons.TransactionFailed

.. autoclass:: pons._client.ProviderErrorCode
   :members:

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

.. autoclass:: Event
   :members:

.. autoclass:: Error
   :members:

.. autoclass:: Fallback
   :members:

.. autoclass:: Receive
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


Compiled and deployed contracts
-------------------------------

.. autoclass:: CompiledContract
   :members:

.. autoclass:: DeployedContract
   :members:


Entities
--------

.. autoclass:: Amount
   :members:

.. class:: pons._entities.CustomAmount

   A type derived from :py:class:`Amount`.

.. autoclass:: Address
   :members:

.. class:: pons._entities.CustomAddress

   A type derived from :py:class:`Address`.

.. autoclass:: Block()
   :members:

.. autoclass:: TxHash
   :members:

.. autoclass:: BlockHash
   :members:

.. autoclass:: pons._entities.TxReceipt()
   :members:

.. autoclass:: pons._entities.BlockInfo()
   :members:

.. autoclass:: pons._entities.TxInfo()
   :members:

.. autoclass:: pons._entities.BlockFilter()

.. autoclass:: pons._entities.PendingTransactionFilter()

.. autoclass:: pons._entities.LogFilter()

.. autoclass:: pons._entities.LogTopic()

.. autoclass:: pons._entities.LogEntry()
   :members:

.. class:: JSON

   A JSON-ifiable object (``bool``, ``int``, ``float``, ``str``, ``None``,
   iterable of ``JSON``, or mapping of ``str`` to ``JSON``).


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
