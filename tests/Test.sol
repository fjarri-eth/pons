pragma solidity >=0.8.0 <0.9.0;


contract Test {
    uint256 public v1;
    uint256 public v2;

    constructor(uint256 _v1, uint256 _v2) {
        v1 = _v1;
        v2 = _v2;
    }

    function setState(uint256 _v1) public {
        v1 = _v1;
    }

    function getState(uint256 _x) public view returns (uint256) {
        return v1 + _x;
    }
}
