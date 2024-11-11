pragma solidity >=0.8.0 <0.9.0;


contract ToDeploy {
    uint256 public state;

    constructor(uint256 _state) {
        state = _state;
    }

    function getState() public view returns (uint256) {
        return state;
    }
}


contract Create2Deployer {
    event Deployed(
        address deployedAddress
    );

    function deploy(bytes memory bytecode, bytes32 _salt) public payable {
        address addr;
        bool success = true;

        assembly {
            addr := create2(
                callvalue(),
                add(bytecode, 0x20), // Skip the first 32 bytes, which is the size of `bytecode`
                mload(bytecode), // Load the size of code contained in the first 32 bytes
                _salt
            )

            if iszero(extcodesize(addr)) {
                success := false
            }
        }

        if (!success) {
            revert("Failed to deploy the contract");
        }

        emit Deployed(addr);
    }
}
