from abc import ABC, abstractmethod
from functools import cached_property
from typing import Mapping

from eth_account.signers.base import BaseAccount

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

    @abstractmethod
    def sign_transaction(self, tx_dict: Mapping) -> bytes:
        """
        Signs the given JSON transaction and returns the RLP-packed transaction
        along with the signature.
        """


class AccountSigner(Signer):
    """
    A signer wrapper for ``eth_account.BaseAccount`` implementors.
    """

    def __init__(self, account: BaseAccount):
        self._account = account

    @cached_property
    def address(self) -> Address:
        return Address.from_hex(self._account.address)

    def sign_transaction(self, tx_dict: Mapping) -> bytes:
        return bytes(self._account.sign_transaction(tx_dict).rawTransaction)
