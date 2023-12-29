from abc import ABC, abstractmethod
from functools import cached_property
from typing import Mapping

from eth_account import Account
from eth_account.signers.base import BaseAccount

from ._entities import Address
from ._provider import JSON


class Signer(ABC):
    """The base class for transaction signers."""

    @property
    @abstractmethod
    def address(self) -> Address:
        """Returns the address corresponding to the signer's private key."""

    @abstractmethod
    def sign_transaction(self, tx_dict: Mapping[str, JSON]) -> bytes:
        """
        Signs the given JSON transaction and returns the RLP-packed transaction
        along with the signature.
        """


class AccountSigner(Signer):
    """A signer wrapper for ``eth_account.BaseAccount`` implementors."""

    def __init__(self, account: BaseAccount):
        self._account = account

    @staticmethod
    def create() -> "AccountSigner":
        """Creates an account with a random private key."""
        return AccountSigner(Account.create())

    @property
    def account(self) -> BaseAccount:
        """Returns the account object used to create this signer."""
        return self._account

    @cached_property
    def address(self) -> Address:
        return Address.from_hex(self._account.address)

    def sign_transaction(self, tx_dict: Mapping[str, JSON]) -> bytes:
        # Ignoring the type since BaseAccount.sign_transaction is untyped
        return bytes(self._account.sign_transaction(tx_dict).rawTransaction)  # type: ignore[no-untyped-call]
