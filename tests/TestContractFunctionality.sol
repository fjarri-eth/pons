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

    function setStateAndReturn(uint256 _v1) public returns (uint256) {
        v1 = v1 + _v1;
        return v1;
    }

    function setState(uint256 _v1) public {
        v1 = _v1;
    }

    function getState(uint256 _x) public view returns (uint256) {
        return v1 + _x;
    }

    function overloaded(uint256 _x, uint256 _y) public pure returns (uint256) {
        return _y + _x;
    }

    function overloaded(uint256 _x) public view returns (uint256) {
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
        bytes10 inner2;
    }

    struct Foo {
        bytes4 foo1;
        bytes2[2] foo2;
        bytes6 foo3;
        ByteInner inner;
    }

    event Complicated(
        bytes4 indexed x,
        bytes8 indexed y,
        Foo indexed u,
        ByteInner[2] indexed v
    ) anonymous;

    function emitComplicated() public {
        bytes2 x = "aa";
        bytes2 y = "bb";
        emit Complicated(
            "aaaa",
            "55555555",
            Foo(
                "4567", [x, y],
                "444444",
                ByteInner("0123", "3333333333")
            ),
            [
                ByteInner("0123", "1111111111"),
                ByteInner("-123", "2222222222")
            ]);
    }

    error MyError(address sender);
}
