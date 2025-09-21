pragma solidity >=0.8.0 <0.9.0;


contract TestMulticall {

    uint256 public x1;
    uint256 public x2;

    constructor() payable {
        x1 = 1;
        x2 = 2;
    }

    function write1(uint256 _x1) public payable {
        x1 = _x1;
    }

    function write2(uint256 _x2) public payable {
        x2 = _x2;
    }

    function write2_error() public payable {
        x2 = 999;
        revert("Revert");
    }

    function read_error() public view {
        revert("Revert");
    }

    function write1_value() public payable {
        x1 = msg.value;
    }

    function write2_value() public payable {
        x2 = msg.value;
    }
}
