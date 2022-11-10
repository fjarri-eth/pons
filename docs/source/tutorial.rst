.. _tutorial:

Tutorial
========


Async support
-------------

While the examples and tests use ``trio``, ``pons`` is ``anyio``-based and supports all the corresponding backends.


Sessions
--------

All calls to the provider in ``pons`` happen within a session.
It translates to the usage of a single session in the backend HTTP request library, so the details are implementation-dependent, but in general it means that multiple requests will happen faster.
For example, in a session an SSL handshake only happens once, and it is a somewhat slow process.

Correspondingly, all the main functionality of the library is concentrated in the :py:class:`~pons._client.ClientSession` class.


Signers
-------

Any operation that entails writing information into the blockchain takes a :py:class:`~pons.Signer` object.
For now, only signers created from ``eth_account.Account`` are supported, but one can define their own class backed by, say, a hardware signer, using the abstract :py:class:`~pons.Signer` class.


Amounts and addresses
---------------------

Native currency amounts and network addresses are typed in ``pons``.
All methods expect and return only :py:class:`~pons.Amount` and :py:class:`~pons.Address` objects --- no integers or strings allowed.

In an application using ``pons`` one can superclass these classes to distinguish between different types of currencies, or addresses from different networks.
Note though that all the arithmetic and comparison functions require **strict** type equality and raise an exception if it is not the case, to protect from accidental usage of addresses/amounts from wrong domains.


Contract ABI
------------

Contract ABI can be declared in two different ways in ``pons``.
The first one can be used when you have a JSON ABI definition, for example installed as a JS package, or obtained from compiling a contract.

::

    from pons import ContractABI

    cabi = ContractABI.from_json(json_abi)
    print(cabi)

This will show a brief summary of the ABI in a C-like code.

::

    {
        constructor(uint256 _v1, uint256 _v2) nonpayable
        fallback() nonpayable
        receive() payable
        function getState(uint256 _x) returns (uint256)
        function testStructs((uint256,uint256) inner_in, ((uint256,uint256),uint256) outer_in) returns ((uint256,uint256) inner_out, ((uint256,uint256),uint256) outer_out)
        function v1() returns (uint256)
        function v2() returns (uint256)
        function setState(uint256 _v1) nonpayable
    }

Alternatively, one can define only the methods they need directly in Python code:

::

    from pons import ContractABI, abi, Constructor, WriteMethod, ReadMethod

    inner_struct = abi.struct(inner1=abi.uint(256), inner2=abi.uint(256))
    outer_struct = abi.struct(inner=inner_struct, outer1=abi.uint(256))
    cabi = ContractABI(
        constructor=Constructor(inputs=dict(_v1=abi.uint(256), _v2=abi.uint(256))),
        write=[
            WriteMethod(name='setState', inputs=dict(_v1=abi.uint(256)))
        ],
        read=[
            ReadMethod(name='getState', inputs=dict(_x=abi.uint(256)), outputs=abi.uint(256)),
            ReadMethod(
                name='testStructs',
                inputs=dict(inner_in=inner_struct, outer_in=outer_struct),
                outputs=dict(inner_out=inner_struct, outer_out=outer_struct),
                )
            ]
        )

    print(cabi)

::

    {
        constructor(uint256 _v1, uint256 _v2) nonpayable
        function getState(uint256 _x) returns (uint256)
        function testStructs((uint256,uint256) inner_in, ((uint256,uint256),uint256) outer_in) returns ((uint256,uint256) inner_out, ((uint256,uint256),uint256) outer_out)
        function setState(uint256 _v1) nonpayable
    }


Contract methods
----------------

All the enumerated methods have corresponding objects that can be accessed via :py:class:`~pons.ContractABI` fields (see the API reference for details).
For example,

::

    print(cabi.read.getState)

::

    function getState(uint256 _x) returns (uint256)

With a specific method object one can create a contract call by, naturally, calling the object.
The arguments are processed the same as in Python functions, so one can either use positional arguments, keyword ones (if the parameter names are present in the contract ABI), or mix the two.

::

    call = cabi.read.getState(1)
    call = cabi.read.getState(_x=1)

Note that the arguments are checked and encoded on call creation, so any inconsistency will result in a raised exception:

::

    call = cabi.read.getState(1, 2)

::

    Traceback (most recent call last):
    ...
    TypeError: too many positional arguments

::

    call = cabi.read.getState("a")

::

    Traceback (most recent call last):
    ...
    TypeError: `uint256` must correspond to an integer, got str


Deploying contracts
-------------------

In order to deploy a contract one needs its ABI and bytecode.
At the moment ``pons`` does not expose the compiler interface, so it has to come from a third party library, for example `py-solcx <https://solcx.readthedocs.io/en/latest/>`_.
With that, create a :py:class:`~pons.CompiledContract` object and use :py:meth:`~pons._client.ClientSession.deploy`:

::

    compiled_contract = CompiledContract(cabi, bytecode)
    deployed_contract = await session.deploy(signer, compiled_contract.constructor(arg1, arg2))

This will result in a :py:class:`~pons.DeployedContract` object encapsulating the contract address and its ABI and allowing one to interact with the contract.

Alternatively, a :py:class:`~pons.DeployedContract` object can be created with a known address if the contract is already deployed:

::

    deployed_contract = DeployedContract(cabi, Address.from_hex("0x<contract_address>"))


Interacting with deployed contracts
-----------------------------------

A :py:class:`~pons.DeployedContract` object wraps all ABI method objects into "bound" state, similarly to how Python methods are bound to class instances.
It means that all the method calls created from this object have the contract address inside them, so that it does not need to be provided every time.

For example, to call a non-mutating contract method via :py:meth:`~pons._client.ClientSession.eth_call`:

::

    call = deployed_contract.read.getState(1)
    result = await session.eth_call(call)

Note that when the :py:class:`~pons.ContractABI` object is created from the JSON ABI, even if the method returns a single value, it is still represented as a list of one element in the JSON, so the ``result`` will be a list too.
If the ABI is declared programmatically, one can provide a single output value instead of the list, and then ``pons`` will unpack that list.

Naturally, a mutating call requires a signer to be provided:

::

    call = deployed_contract.write.setState(1)
    await session.transact(signer, call)
