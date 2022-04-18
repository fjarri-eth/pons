Changelog
---------


Unreleased
~~~~~~~~~~

Under construction.


0.3.0 (03-04-2022)
~~~~~~~~~~~~~~~~~~

Changed
^^^^^^^

- Merged ``SigningClient`` into ``Client``, with the methods of the former now requiring an explicit ``Signer`` argument. (PR_1_)
- Exposed provider sessions via ``Client.session()`` context manager; all the client methods were moved to the returned session object. (PR_1_)
- Added type/value checks when normalizing contract arguments. (PR_4_)
- Unpacking contract call results into specific types. (PR_4_)

Added
^^^^^

- Allowed one to declare ABI via Python calls instead of JSON. (PR_4_)
- Support for binding of contract arguments to named parameters. (PR_4_)

Fixed
^^^^^

- Multiple fixes for typing of methods. (PR_1_)
- Fixed the handling of array-of-array ABI types. (PR_2_)
- Replaced assertions with more informative exceptions. (PR_3_)


.. _PR_1: https://github.com/fjarri/pons/pull/1
.. _PR_2: https://github.com/fjarri/pons/pull/2
.. _PR_3: https://github.com/fjarri/pons/pull/3
.. _PR_4: https://github.com/fjarri/pons/pull/4


0.2.0 (19-03-2022)
~~~~~~~~~~~~~~~~~~

Initial release.
