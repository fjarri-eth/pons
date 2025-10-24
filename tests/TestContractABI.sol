pragma solidity >=0.8.0 <0.9.0;


// A contract with various possible edge cases to test the conversion to/from JSON
contract RoundTrip {
    // A public field will generate a getter method
    uint256 public field;

    constructor(uint256 x) payable {
        field = x;
    }

    receive() external payable {
    }

    // Note that the argument and the return type will not be present
    // in the JSON ABI returned by `solc`.
    fallback(bytes calldata) external payable returns (bytes memory) {
    }

    // Regular methods

    function pureMethod(uint256 y) public view returns (uint256) {
        revert();
    }

    function viewMethod(uint256 y) public view returns (uint256) {
        revert();
    }

    function nonpayableMethod(uint256 y) public returns (uint256) {
        revert();
    }

    function payableMethod(uint256 y) public payable returns (uint256) {
        revert();
    }

    // A method with some unnamed arguments

    function unnamedArgsMethod(uint256, address) public view returns (uint256) {
        revert();
    }

    function partiallyNamedArgsMethod(uint256 y, address) public view returns (uint256) {
        revert();
    }

    function partiallyNamedArgsAndReturnsMethod(uint256, address y) public view returns (uint256 z, uint256) {
        revert();
    }

    // Overloaded method

    function overloadedMethod(uint256 x) public view returns (uint256) {
        revert();
    }

    function overloadedMethod(uint256 x, address y) public view returns (uint256) {
        revert();
    }

    // Event with some fields indexed
    event regularEvent(
        uint32 indexed x,
        uint256 y
    );

    // Anonymous event
    event anonymousEvent(
        uint32 x,
        uint256 indexed y
    ) anonymous;

    // An event with partially named fields
    event partiallyNamedFieldsEvent(
        uint32 x,
        uint256,
        uint32 indexed y,
        uint256 indexed
        );

    // Error with all fields named
    error regularError(uint256 x, address y);

    // Errors with some unnamed fields

    error unnamedFieldsError(uint256, address);

    error partiallyNamedFieldsError(uint256, address y);
}
