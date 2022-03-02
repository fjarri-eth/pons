from abc import ABC, abstractmethod

from eth_account import Account

from .types import Address


class Signer(ABC):

    @abstractmethod
    def address(self) -> Address:
        pass

    @abstractmethod
    def sign_transaction(self, tx: dict) -> bytes:
        pass


class AccountSigner:

    def __init__(self, account: Account):
        self._account = account

    def address(self) -> Address:
        return Address.from_hex(self._account.address)

    def sign_transaction(self, tx: dict) -> bytes:
        return bytes(self._account.sign_transaction(tx).rawTransaction)
