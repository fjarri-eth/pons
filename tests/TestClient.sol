pragma solidity >=0.8.0 <0.9.0;


contract EmptyContract {
    uint256 public state;

    constructor(uint256 _state) {
        state = _state;
    }
}

contract Storage {
    uint x;
    mapping(address => uint) y;
    constructor(uint256 _x, address _y_key, uint256 _y_val) {
        x = _x;
        y[_y_key] = _y_val;
    }
}

contract BasicContract {
    uint256 public state;

    constructor(uint256 _state) {
        state = _state;
    }

    function setState(uint256 _x) public {
        state = _x;
    }

    function doubleStateAndCheck(uint256 _x) public {
        state = state * 2;
        if (state == _x) {
            revert("Check succeeded");
        }
    }

    function payableSetState(uint256 _x) public payable {
        state = _x;
    }

    function faultySetState(uint256 _x) public {
        if (_x == 0) {
            revert("Wrong value");
        }
        state = _x;
    }

    function getState(uint256 _x) public view returns (uint256) {
        return state + _x;
    }

    function getSender() public view returns (address) {
        return msg.sender;
    }

    event Deposit(
        address indexed from,
        bytes4 indexed id,
        uint value
    );

    event Deposit2(
        address indexed from,
        bytes4 indexed id,
        uint value,
        uint value2
    );

    function deposit(bytes4 id) public payable {
        emit Deposit(msg.sender, id, msg.value);
    }

    function deposit2(bytes4 id) public payable {
        emit Deposit2(msg.sender, id, msg.value, msg.value + 1);
    }

    event Event1(
        uint32 indexed value
    );

    event Event2(
        uint32 value
    );

    function emitMultipleEvents(uint32 x) public {
        emit Event1(x);
        emit Event1(x + 1);
        emit Event2(x + 2);
        emit Event2(x + 3);
    }
}

contract PayableConstructor {
    uint256 public state;

    constructor(uint256 _state) payable {
        state = _state;
    }
}


contract TestErrors {
    error CustomError(uint256 x);

    error AnonymousFieldError(uint256);

    uint256 state;

    constructor(uint256 x) {
        state = raiseError(x);
    }

    function raiseError(uint256 x) internal view returns (uint256) {
        require(x != 0); // a `require` without an error message
        require(x != 1, "require(string)");

        if (x == 2) {
            revert(); // empty revert (legacy syntax)
        }
        else if (x == 3) {
            revert("revert(string)"); // revert with a message (legacy syntax)
        }
        else if (x == 4) {
            revert CustomError(x);
        }
        return x;
    }

    function raisePanic(uint256 x) internal view returns (uint256) {
        if (x == 0) {
            assert(false); // panic 0x01
        }
        else if (x == 1) {
            x = x - 2; // panic 0x11 (over/underflow)
        }

        return x;
    }

    function viewError(uint256 x) public view returns (uint256) {
        return raiseError(x);
    }

    function transactError(uint256 x) public {
        state = raiseError(x);
    }

    function viewPanic(uint256 x) public view returns (uint256) {
        return raisePanic(x);
    }

    function transactPanic(uint256 x) public {
        state = raisePanic(x);
    }

    function raiseAnonymousFieldError(uint256 x) public view returns (uint256) {
        revert AnonymousFieldError(x);
    }
}
