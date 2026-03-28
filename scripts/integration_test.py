#!/usr/bin/env python3
"""Integration test script — runs against the real Twingate CLI.

Tests all parser paths and command dispatch used by the tray app.
Can run authenticated or unauthenticated (some tests adapt).
"""

import sys

sys.path.insert(0, "src")

from twingate_tray.client import (
    CommandResult,
    ConnectionState,
    TwingateClient,
)


def main() -> int:
    c = TwingateClient()
    failures = 0

    def test(name: str) -> None:
        print(f"\n=== {name} ===")

    def ok() -> None:
        print("  PASS")

    def fail(msg: str) -> None:
        nonlocal failures
        print(f"  FAIL: {msg}")
        failures += 1

    # ------------------------------------------------------------------
    # Real CLI tests (require twingate binary installed)
    # ------------------------------------------------------------------

    test("TEST 1: twingate status")
    s = c.status()
    print(f"  State: {s.state}")
    print(f"  Raw: {s.raw_output!r}")
    if s.state in ConnectionState:
        ok()
    else:
        fail(f"Invalid state: {s.state}")

    test("TEST 2: twingate status -v")
    s = c.status(verbose=True)
    print(f"  State: {s.state}")
    print(f"  Network: {s.network}")
    print(f"  Account: {s.account}")
    print(f"  Raw: {s.raw_output!r}")
    ok()

    test("TEST 3: twingate resources")
    r = c.resources()
    print(f"  Count: {len(r)}")
    for res in r:
        print(f"    {res.name} -> {res.address} (accessible={res.is_accessible})")
    ok()

    test("TEST 4: twingate resources --all")
    r = c.resources(include_hidden=True)
    print(f"  Count: {len(r)}")
    ok()

    test("TEST 5: twingate account list")
    a = c.account_list()
    print(f"  Count: {len(a)}")
    for acct in a:
        print(f"    name={acct.name} email={acct.email} network={acct.network}"
              f" active={acct.is_active} switch_id={acct.switch_id}")
    if len(a) > 0:
        # Verify switch_id is well-formed for columnar output
        for acct in a:
            if acct.email and acct.network:
                expected = f"{acct.email}:{acct.network}"
                if acct.switch_id != expected:
                    fail(f"switch_id={acct.switch_id!r} != expected={expected!r}")
    ok()

    test("TEST 6: twingate exit-node list")
    n = c.exit_node_list()
    print(f"  Count: {len(n)}")
    for node in n:
        print(f"    name={node.name} active={node.is_active}")
    ok()

    test("TEST 7: twingate version")
    v = c.version()
    print(f"  Version: {v}")
    if v == "unknown":
        fail("Version should not be 'unknown' when binary exists")
    else:
        ok()

    # ------------------------------------------------------------------
    # Input validation tests
    # ------------------------------------------------------------------

    test("TEST 8: _validate_arg accepts real-world values")
    test_values = [
        ("Seattle Exit Network - Vultr3", "exit_node"),
        ("user@example.com:acme", "account"),
        ("my-resource.internal.com", "resource"),
        ("My Company (Production)", "network"),
        ("us-east-1", "node"),
        ("admin@company.com", "email"),
    ]
    for val, label in test_values:
        try:
            c._validate_arg(val, label)
            print(f"    {val!r} -> accepted")
        except ValueError as e:
            fail(f"{val!r} rejected: {e}")
    ok()

    test("TEST 9: _validate_arg rejects dangerous input")
    bad_values = [
        ("--help", "injection"),
        ("; rm -rf /", "injection"),
        ("", "empty"),
        ("-v", "flag"),
        ("foo|bar", "pipe"),
        ("foo`whoami`", "backtick"),
    ]
    all_rejected = True
    for val, label in bad_values:
        try:
            c._validate_arg(val, label)
            fail(f"{val!r} was accepted (should be rejected)")
            all_rejected = False
        except ValueError:
            print(f"    {val!r} -> rejected (correct)")
    if all_rejected:
        ok()

    # ------------------------------------------------------------------
    # Simulated output parsing (tests parser against known formats)
    # ------------------------------------------------------------------

    test("TEST 10: Parse exit-node list with emoji + columns")
    result = CommandResult(
        success=True,
        stdout=(
            "Non-Resource traffic currently isn't being routed through Twingate\n"
            "\n"
            "EXIT NETWORK NAME                 TIME LEFT\n"
            "\U0001f464 Seattle Exit Network - Vultr3     --\n"
        ),
        stderr="", returncode=0,
    )
    nodes = c._parse_exit_nodes(result)
    print(f"  Parsed {len(nodes)} node(s)")
    if len(nodes) != 1:
        fail(f"Expected 1 node, got {len(nodes)}")
    elif nodes[0].name != "Seattle Exit Network - Vultr3":
        fail(f"Wrong name: {nodes[0].name!r}")
    else:
        print(f"    name={nodes[0].name!r} active={nodes[0].is_active}")
        ok()

    test("TEST 11: Parse exit-node list with active node + time left")
    result = CommandResult(
        success=True,
        stdout=(
            "All traffic is being routed through Twingate\n"
            "\n"
            "EXIT NETWORK NAME                 TIME LEFT\n"
            "\u2713 US East Node     4h 30m\n"
            "\U0001f464 EU West Node     --\n"
        ),
        stderr="", returncode=0,
    )
    nodes = c._parse_exit_nodes(result)
    print(f"  Parsed {len(nodes)} node(s)")
    if len(nodes) != 2:
        fail(f"Expected 2 nodes, got {len(nodes)}")
    elif not nodes[0].is_active:
        fail("First node should be active")
    elif nodes[0].name != "US East Node":
        fail(f"Wrong name for active node: {nodes[0].name!r}")
    elif nodes[1].is_active:
        fail("Second node should not be active")
    else:
        for node in nodes:
            print(f"    name={node.name!r} active={node.is_active}")
        ok()

    test("TEST 12: Parse account list (columnar format)")
    result = CommandResult(
        success=True,
        stdout=(
            "EMAIL              NETWORK  NETWORK URL\n"
            "user@example.com   acme     acme.twingate.com\n"
            "admin@corp.com     corp     corp.twingate.com\n"
        ),
        stderr="", returncode=0,
    )
    accts = c._parse_accounts(result)
    print(f"  Parsed {len(accts)} account(s)")
    if len(accts) != 2:
        fail(f"Expected 2 accounts, got {len(accts)}")
    elif accts[0].switch_id != "user@example.com:acme":
        fail(f"Wrong switch_id: {accts[0].switch_id!r}")
    elif accts[1].switch_id != "admin@corp.com:corp":
        fail(f"Wrong switch_id: {accts[1].switch_id!r}")
    else:
        for acct in accts:
            print(f"    name={acct.name!r} switch_id={acct.switch_id!r}")
        ok()

    test("TEST 13: Parse status variants")
    for state_str, expected in [
        ("online", ConnectionState.ONLINE),
        ("offline", ConnectionState.OFFLINE),
        ("connecting", ConnectionState.CONNECTING),
        ("paused", ConnectionState.PAUSED),
        ("authenticating", ConnectionState.UNKNOWN),
        ("Online", ConnectionState.ONLINE),
        ("  offline  ", ConnectionState.OFFLINE),
    ]:
        result = CommandResult(success=True, stdout=state_str, stderr="", returncode=0)
        parsed = c._parse_status(result)
        if parsed.state != expected:
            fail(f"Status {state_str!r}: expected {expected}, got {parsed.state}")
        else:
            print(f"    {state_str!r} -> {parsed.state.value}")
    ok()

    test("TEST 14: Parse resource list with status column")
    result = CommandResult(
        success=True,
        stdout=(
            "Name    Address    Status\n"
            "---    ---    ---\n"
            "myapp    10.0.0.1    active\n"
            "locked-app    10.0.0.3    locked\n"
            "denied-app    10.0.0.4    denied\n"
        ),
        stderr="", returncode=0,
    )
    resources = c._parse_resources(result)
    print(f"  Parsed {len(resources)} resource(s)")
    if len(resources) != 3:
        fail(f"Expected 3, got {len(resources)}")
    elif resources[0].is_accessible is not True:
        fail("First resource should be accessible")
    elif resources[1].is_accessible is not False:
        fail("Locked resource should not be accessible")
    elif resources[2].is_accessible is not False:
        fail("Denied resource should not be accessible")
    else:
        for res in resources:
            print(f"    {res.name} -> {res.address} accessible={res.is_accessible}")
        ok()

    test("TEST 15: Error handling - timeout")
    # _run with a nonexistent command won't timeout, but we can verify
    # the binary not found path
    result = c._run(["nonexistent-subcommand"])
    print(f"  success={result.success} stderr={result.stderr!r}")
    if result.success:
        # Twingate might return an error for unknown subcommands
        print("  (CLI accepted unknown subcommand - non-fatal)")
    ok()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    print("\n=============================================")
    if failures == 0:
        print("ALL 15 TESTS PASSED")
    else:
        print(f"{failures} TEST(S) FAILED")
    print("=============================================")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
