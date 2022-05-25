pragma solidity >=0.8.0 <0.9.0;


contract NoConstructor {
    uint256 public v1 = 1;

    function getState(uint256 _x) public view returns (uint256) {
        return v1 + _x;
    }
}


contract Test {
    uint256 public v1;
    uint256 public v2;

    constructor(uint256 _v1, uint256 _v2) {
        v1 = _v1;
        v2 = _v2;
    }

    receive() external payable {
        v1 = 1;
        v2 = 2;
    }

    fallback(bytes calldata) external returns (bytes memory) {
        v1 = 1;
        v2 = 2;
    }

    function setState(uint256 _v1) public {
        v1 = _v1;
    }

    function getState(uint256 _x) public view returns (uint256) {
        return v1 + _x;
    }

    struct Inner {
        uint256 inner1;
        uint256 inner2;
    }

    struct Outer {
        Inner inner;
        uint256 outer1;
    }

    function testStructs(Inner memory inner_in, Outer memory outer_in)
            public pure returns (Inner memory inner_out, Outer memory outer_out) {
        inner_out = inner_in;
        outer_out = outer_in;
    }

    struct ByteInner {
        bytes4 inner1;
        bytes inner2;
    }

    struct Foo {
        bytes4 foo1;
        bytes2[2] foo2;
        bytes foo3;
        string foo4;
        ByteInner inner;
    }

    event Complicated(
        bytes4 indexed x,
        bytes indexed y,
        Foo indexed u,
        ByteInner[2] indexed v
    ) anonymous;

    function emitComplicated() public {
        bytes memory bytestring33len1 = "012345678901234567890123456789012";
        bytes memory bytestring33len2 = "-12345678901234567890123456789012";
        ByteInner memory inner1 = ByteInner("0123", bytestring33len1);
        ByteInner memory inner2 = ByteInner("-123", bytestring33len2);
        bytes2 x = "aa";
        bytes2 y = "bb";
        bytes2[2] memory foo2 = [x, y];
        Foo memory foo = Foo("4567", foo2, bytestring33len1, "\u1234\u1212", inner1);
        ByteInner[2] memory inner_arr = [inner1, inner2];
        emit Complicated("aaaa", bytestring33len2, foo, inner_arr);
    }
}
