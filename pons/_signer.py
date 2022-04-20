from abc import ABC, abstractmethod
from functools import cached_property

from eth_account.account import LocalAccount

from ._entities import Address


class Signer(ABC):
    """
    The base class for transaction signers.
    """

    @property
    @abstractmethod
    def address(self) -> Address:
        """
        Returns the address corresponding to the signer's private key.
        """
        pass

    @abstractmethod
    def sign_transaction(self, tx: dict) -> bytes:
        """
        Signs the given JSON transaction and returns the RLP-packed transaction
        along with the signature.
        """
        pass


class AccountSigner(Signer):
    """
    A signer wrapper for ``eth_account.LocalAccount``.
    """

    def __init__(self, account: LocalAccount):
        self._account = account

    @cached_property
    def address(self) -> Address:
        return Address.from_hex(self._account.address)

    def sign_transaction(self, tx: dict) -> bytes:
        return bytes(self._account.sign_transaction(tx).rawTransaction)