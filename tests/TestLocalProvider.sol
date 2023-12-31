pragma solidity >=0.8.0 <0.9.0;


contract BasicContract {
    uint256 public state;

    constructor() {
        state = 123;
    }

    function getState(uint256 _x) public view returns (uint256) {
        return state + _x;
    }
}
