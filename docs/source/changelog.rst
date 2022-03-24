Changelog
---------


Unreleased
~~~~~~~~~~

Changed
^^^^^^^

- Merged ``SigningClient`` into ``Client``, with the methods of the former now requiring an explicit ``Signer`` argument. (PR_1_)
- Exposed provider sessions via ``Client.session()`` context manager; all the client methods were moved to the returned session object. (PR_1_)

Fixed
^^^^^

- Multiple fixes for typing of methods. (PR_1_)

.. _PR_1: https://github.com/fjarri/pons/pull/1


0.2.0 (19-03-2022)
~~~~~~~~~~~~~~~~~~

Initial release.
