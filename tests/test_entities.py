import os

import pytest

from pons import Amount, Address, TxHash, Block, BlockHash
from pons._entities import (
    rpc_encode_quantity,
    rpc_encode_data,
    rpc_encode_block,
    rpc_decode_quantity,
    rpc_decode_data,
    rpc_decode_block,
    RPCDecodingError,
    LogTopic,
    LogEntry,
    TxReceipt,
    BlockInfo,
)


def test_amount():
    # Conversions
    assert Amount.wei(100).as_wei() == 100
    assert Amount.wei(100).as_gwei() == 100 / 10**9
    assert Amount.wei(100).as_ether() == 100 / 10**18
    assert Amount.gwei(100).as_wei() == 100 * 10**9
    assert Amount.ether(100).as_wei() == 100 * 10**18

    with pytest.raises(TypeError, match="Amount must be an integer, got float"):
        Amount.wei(100.0)

    # other constructors cast to integer
    assert Amount.gwei(100.0).as_wei() == 100 * 10**9
    assert Amount.ether(100.0).as_wei() == 100 * 10**18

    with pytest.raises(ValueError, match="Amount must be non-negative, got -100"):
        Amount.wei(-100)

    # Encoding
    assert Amount.wei(100).rpc_encode() == "0x64"
    assert Amount.rpc_decode("0x64") == Amount.wei(100)

    assert Amount.wei(100) + Amount.wei(50) == Amount.wei(150)
    assert Amount.wei(100) - Amount.wei(50) == Amount.wei(50)
    assert Amount.wei(100) * 2 == Amount.wei(200)
    assert Amount.wei(100) // 2 == Amount.wei(50)
    assert Amount.wei(100) > Amount.wei(50)
    assert not Amount.wei(50) > Amount.wei(50)
    assert Amount.wei(100) >= Amount.wei(50)
    assert Amount.wei(50) >= Amount.wei(50)
    assert Amount.wei(50) < Amount.wei(100)
    assert not Amount.wei(50) < Amount.wei(50)
    assert Amount.wei(50) <= Amount.wei(100)
    assert Amount.wei(50) <= Amount.wei(50)

    # The type is hashable
    amount_set = {Amount.wei(100), Amount.wei(100), Amount.wei(50)}
    assert len(amount_set) == 2

    class MyAmount(Amount):
        pass

    assert repr(Amount.wei(100)) == "Amount(100)"
    assert repr(MyAmount.wei(100)) == "MyAmount(100)"

    with pytest.raises(TypeError, match="Incompatible types: Amount and int"):
        Amount.wei(100) + 100

    # Type checking is strict, subclasses are considered different types
    with pytest.raises(TypeError, match="Incompatible types: Amount and MyAmount"):
        Amount.wei(100) + MyAmount.wei(100)

    with pytest.raises(TypeError, match="Expected an integer, got float"):
        Amount.wei(100) * 2.0

    with pytest.raises(TypeError, match="Expected an integer, got float"):
        Amount.wei(100) // 2.0


def test_address():

    random_addr = b"dv\xbbCQ,\xfe\xd0\xbfF\x8aq\x07OK\xf9\xa1i\x88("
    random_addr_checksum = "0x6476Bb43512CFed0bF468a71074F4bF9A1698828"

    assert bytes(Address(random_addr)) == random_addr
    assert bytes(Address.from_hex(random_addr_checksum)) == random_addr
    assert bytes(Address.from_hex(random_addr_checksum.lower())) == random_addr

    assert Address(random_addr).checksum == random_addr_checksum

    assert Address(random_addr).rpc_encode() == random_addr_checksum
    assert Address.rpc_decode(random_addr_checksum) == Address(random_addr)
    assert Address(random_addr) == Address(random_addr)
    assert Address(random_addr) != Address(os.urandom(20))

    class MyAddress(Address):
        pass

    assert str(Address(random_addr)) == random_addr_checksum
    assert repr(Address(random_addr)) == f"Address.from_hex({random_addr_checksum})"
    assert repr(MyAddress(random_addr)) == f"MyAddress.from_hex({random_addr_checksum})"

    # The type is hashable
    addr_set = {Address(random_addr), Address(os.urandom(20)), Address(random_addr)}
    assert len(addr_set) == 2

    with pytest.raises(TypeError, match="Address must be a bytestring, got str"):
        Address(random_addr_checksum)

    with pytest.raises(ValueError, match="Address must be 20 bytes long, got 19"):
        Address(random_addr[:-1])

    with pytest.raises(ValueError, match="Address must be 20 bytes long, got 19"):
        Address(random_addr[:-1])

    with pytest.raises(TypeError, match="Incompatible types: MyAddress and Address"):
        # For whatever reason the the values are switched places in `__eq__()`
        Address(random_addr) == MyAddress(random_addr)

    # This error comes from eth_utils, we don't care about the phrasing,
    # but want to detect if the type changes.
    with pytest.raises(ValueError):
        Address.from_hex(random_addr_checksum[:-1])

    with pytest.raises(RPCDecodingError, match="Address must be 20 bytes long, got 19"):
        Address.rpc_decode("0x" + random_addr[:-1].hex())


def test_typed_data():
    # This is not covered by Address tests, since it overrides those methods
    data = os.urandom(32)
    tx_hash = TxHash(data)
    assert repr(tx_hash) == f'TxHash(bytes.fromhex("{data.hex()}"))'
    assert tx_hash.rpc_encode() == "0x" + data.hex()


def test_typed_data_lengths():
    # Just try to create the corresponding types,
    # it will cover their respective length methods.
    # Everything else is in the base class which is tested elsewhere
    TxHash(os.urandom(32))
    BlockHash(os.urandom(32))
    LogTopic(os.urandom(32))


def test_decode_tx_receipt():

    address = Address(os.urandom(20))

    tx_receipt_json = {
        "transactionHash": "0xf105e4ee72d1538a4e10ee9584581e2b6f13cd9be82acd14e8edd65d954483c5",
        "blockHash": "0x3f62ac76f9551dbf878c334657ce19a86881734cbf53f8ecd9c3afb9a22d5bee",
        "blockNumber": "0xa38696",
        "contractAddress": address.rpc_encode(),
        "cumulativeGasUsed": "0x43641c",
        "effectiveGasPrice": "0x45463c1c",
        "from": "0x8d75f6db12c444e290db995f2650a68159364e25",
        "gasUsed": "0x55f0",
        "status": "0x1",
        "to": None,
        "transactionIndex": "0x18",
        "type": "0x0",
    }

    tx_receipt = TxReceipt.rpc_decode(tx_receipt_json)

    assert tx_receipt.succeeded
    assert tx_receipt.contract_address == address

    tx_receipt_json["contractAddress"] = None
    tx_receipt_json["to"] = address.rpc_encode()
    tx_receipt_json["status"] = "0x0"

    tx_receipt = TxReceipt.rpc_decode(tx_receipt_json)

    assert not tx_receipt.succeeded
    assert tx_receipt.contract_address is None
    assert tx_receipt.to == address


def test_encode_decode_quantity():
    assert rpc_encode_quantity(100) == "0x64"
    assert rpc_decode_quantity("0x64") == 100

    with pytest.raises(RPCDecodingError, match="Encoded quantity must be a string"):
        rpc_decode_quantity(100)

    with pytest.raises(RPCDecodingError, match="Encoded quantity must start with `0x`"):
        rpc_decode_quantity("616263")

    with pytest.raises(RPCDecodingError, match="Could not convert encoded quantity to an integer"):
        rpc_decode_quantity("0xefgh")


def test_encode_decode_data():
    assert rpc_encode_data(b"abc") == "0x616263"
    assert rpc_decode_data("0x616263") == b"abc"

    with pytest.raises(RPCDecodingError, match="Encoded data must be a string"):
        rpc_decode_data(616263)

    with pytest.raises(RPCDecodingError, match="Encoded data must start with `0x`"):
        rpc_decode_data("616263")

    with pytest.raises(RPCDecodingError, match="Could not convert encoded data to bytes"):
        rpc_decode_data("0xefgh")


def test_encode_decode_block():
    assert rpc_encode_block(Block.LATEST) == "latest"
    assert rpc_encode_block(Block.EARLIEST) == "earliest"
    assert rpc_encode_block(Block.PENDING) == "pending"
    assert rpc_encode_block(123) == "0x7b"
    assert rpc_decode_block("latest") == "latest"
    assert rpc_decode_block("earliest") == "earliest"
    assert rpc_decode_block("pending") == "pending"
    assert rpc_decode_block("0x7b") == 123


def test_decode_block_info():

    json_result = {
        "baseFeePerGas": "0xbcdaf1db6",
        "difficulty": "0x2c72989f9145c8",
        "gasLimit": "0x1cb2a73",
        "gasUsed": "0x50c7cc",
        "hash": "0x477a8386bbcc43f54b0231317d6a95f62ab10909d2d985ac5957633090ae69a8",
        "miner": "0x7f101fe45e6649a6fb8f3f8b43ed03d353f2b90c",
        "nonce": "0x2c4139002b04ac83",
        "number": "0xda5f7a",
        "parentHash": "0xa6fc86d8fc22aa8c164fa713b010b71a9071a2b2bc75f39cd6ec1256a4291e33",
        "size": "0x65ad",
        "timestamp": "0x6220267c",
        "totalDifficulty": "0x911c203aa627addcf39",
        "transactions": [
            {
                "blockHash": "0x477a8386bbcc43f54b0231317d6a95f62ab10909d2d985ac5957633090ae69a8",
                "blockNumber": "0xda5f7a",
                "from": "0x4ac69ded1859e5ead2bf2ed8875d9c65012ce198",
                "gas": "0x5208",
                "gasPrice": "0x13b9b49c00",
                "hash": "0x62581a4b947c113ecfb463df4d268c9f5791d95c91993e052a110731e8542140",
                "input": "0x",
                "nonce": "0x7",
                "to": "0xe925433cf352cdc9c80df0a84641f3906758f4dc",
                "transactionIndex": "0x0",
                "type": "0x0",
                "value": "0x6851a3a375d1ec",
            },
            {
                "blockHash": "0x477a8386bbcc43f54b0231317d6a95f62ab10909d2d985ac5957633090ae69a8",
                "blockNumber": "0xda5f7a",
                "from": "0xf1fb5dea21337feb46963c29d04a95f6ca8b71e6",
                "gas": "0xd0b3",
                "gasPrice": "0xcf7b50fb6",
                "hash": "0x4eeae930617ad553af25a809f11051451e7f4a2597af6e8eae6ed446b94d6532",
                "maxFeePerGas": "0xcfad7001d",
                "maxPriorityFeePerGas": "0x12a05f200",
                "nonce": "0x1317",
                "to": "0x2e9d63788249371f1dfc918a52f8d799f4a38c94",
                "transactionIndex": "0x3",
                "type": "0x2",
                "value": "0x0",
            },
        ],
    }

    # Parse output with the transaction info
    block_info = BlockInfo.rpc_decode(json_result)
    assert block_info.transactions[0].block_hash == BlockHash.rpc_decode(
        json_result["transactions"][0]["blockHash"]
    )
    assert block_info.transaction_hashes[0] == TxHash.rpc_decode(
        json_result["transactions"][0]["hash"]
    )

    # Parse output without the transaction info
    json_result["transactions"] = [
        json_result["transactions"][0]["hash"],
        json_result["transactions"][1]["hash"],
    ]
    block_info = BlockInfo.rpc_decode(json_result)
    assert block_info.transactions is None
    assert block_info.transaction_hashes[0] == TxHash.rpc_decode(json_result["transactions"][0])

    # Parse output without any transactions
    json_result["transactions"] = []
    block_info = BlockInfo.rpc_decode(json_result)
    assert block_info.transactions == ()
    assert block_info.transaction_hashes == ()


def test_decode_log_entry():
    log_entry_json = {
        "address": "0x6ef0f6ca7a8f01e02593df24f7097889a249c31e",
        "topics": [
            "0x8be0079c531659141344cd1fd0a4f28419497f9722a3daafe3b4186f6b6457e0",
            "0x0000000000000000000000000000000000000000000000000000000000000000",
            "0x000000000000000000000000e2b8651bf50913057ff47fc4f02a8e12146083b8",
        ],
        "data": "0x",
        "blockNumber": "0xa386df",
        "transactionHash": "0x7c0301cec59c65dce24fe7bd007dd4ab1dbe6c7c0f029deb76f4fb2d4c004379",
        "transactionIndex": "0x0",
        "blockHash": "0x14fb839d874ee80c020e7f087f8e57d4c6a94d6af1e6c7c9544d1ef219b0873b",
        "logIndex": "0x0",
        "removed": False,
    }

    log_entry = LogEntry.rpc_decode(log_entry_json)
    assert log_entry.data == b""
