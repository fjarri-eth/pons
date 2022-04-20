API
---

.. automodule:: pons


Clients
~~~~~~~

.. autoclass:: Client
   :members:

.. autoclass:: pons._client.ClientSession()
   :members:


Providers
~~~~~~~~~

.. autoclass:: pons._provider.Provider

.. autoclass:: HTTPProvider
   :show-inheritance:


Signers
~~~~~~~

.. autoclass:: Signer
   :members:

.. autoclass:: AccountSigner
   :show-inheritance:


Contract ABI
~~~~~~~~~~~~

.. autoclass:: ContractABI
   :members:

.. autoclass:: Constructor
   :members:
   :special-members: __call__

.. autoclass:: ReadMethod
   :show-inheritance:
   :members:
   :special-members: __call__

.. autoclass:: WriteMethod
   :show-inheritance:
   :members:
   :special-members: __call__

.. autoclass:: Fallback
   :members:

.. autoclass:: Receive
   :members:


Secondary classes
^^^^^^^^^^^^^^^^^

.. autoclass:: pons._contract_abi.ConstructorCall
   :members:

.. autoclass:: pons._contract_abi.ReadCall
   :members:

.. autoclass:: pons._contract_abi.WriteCall
   :members:


Utility classes
^^^^^^^^^^^^^^^

.. autoclass:: pons._contract_abi.Methods()
   :show-inheritance:
   :members:
   :special-members: __getattr__, __iter__

.. autoclass:: pons._contract_abi.Signature
   :members:

.. autoclass:: pons._contract_abi.Method
   :members:


Compiled and deployed contracts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: CompiledContract
   :members:

.. autoclass:: DeployedContract
   :members:


Secondary classes
^^^^^^^^^^^^^^^^^

.. autoclass:: pons._contract.BoundConstructor
   :members:
   :special-members: __call__

.. autoclass:: pons._contract.BoundConstructorCall
   :members:

.. autoclass:: pons._contract.BoundReadMethod
   :members:
   :special-members: __call__

.. autoclass:: pons._contract.BoundReadCall
   :members:

.. autoclass:: pons._contract.BoundWriteMethod
   :members:
   :special-members: __call__

.. autoclass:: pons._contract.BoundWriteCall
   :members:


Entities
~~~~~~~~

.. autoclass:: Amount
   :members:

.. autoclass:: Address
   :members:

.. autoclass:: Block()
   :members:

.. autoclass:: TxHash()
   :members:

.. autoclass:: TxReceipt()
   :members:


Solidity types
~~~~~~~~~~~~~~

.. autoclass:: pons._abi_types.Type

Type aliases are exported from the ``abi`` submodule.
Arrays can be obtained from ``Type`` objects by indexing them (either with an integer for a fixed-size array, or with ``...`` for a variable-sized array).

.. automodule:: pons.abi
   :members:
