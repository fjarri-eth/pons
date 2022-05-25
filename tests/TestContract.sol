pragma solidity >=0.8.0 <0.9.0;


contract JsonAbiTest {
    uint256 public v1;

    constructor(uint256 _v1, uint256 _v2) payable {
        v1 = _v1 + _v2;
    }

    receive() external payable {
    }

    fallback(bytes calldata) external payable returns (bytes memory) {
    }

    function setState(uint256 _v1) public payable {
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

    event Foo(
        uint indexed x,
        bytes indexed y,
        bytes4 u,
        bytes v
    ) anonymous;
}
