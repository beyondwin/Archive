use kernel_protocol::ExecutionRequest;

#[test]
fn reads_shared_kernel_request_fixture() {
    let text = include_str!("../../../../../tests/fixtures/contracts/valid-kernel-request.json");
    let request: ExecutionRequest = serde_json::from_str(text).expect("fixture should parse");

    assert_eq!(request.schema, "kernel.execution_request.v1");
    assert_eq!(request.request_id, "exec_demo");
    assert_eq!(
        request.argv,
        vec!["printf".to_string(), "hello".to_string()]
    );
}
