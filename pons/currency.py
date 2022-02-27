from eth_utils import to_wei


class Wei:

    @classmethod
    def from_unit(cls, quantity, unit):
        return cls(to_wei(quantity, unit))

    def __init__(self, wei):
        self.wei = wei

    def __int__(self):
        return self.wei

    def __eq__(self, other):
        return type(self) == type(other) and self.wei == other.wei

    def __sub__(self, other):
        assert type(other) == type(self)
        return Wei(self.wei - other.wei)

    def __gt__(self, other):
        assert type(other) == type(self)
        return self.wei > other.wei

    def __str__(self):
        return f"{self.wei / 10**18} ETH"
