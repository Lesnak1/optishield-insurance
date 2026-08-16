import json
import pytest


def test_flight_cancellation_claim_and_instant_payout(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Test complete lifecycle of OptiShield:
    1. Protocol owner (Alice) seeds underwriting pool with 200 GEN.
    2. Traveler (Bob) purchases 40 GEN flight delay/cancellation insurance for flight UA894 paying 2 GEN premium (5%).
    3. Flight UA894 is cancelled due to blizzard. Bob files claim with FAA/FlightAware live status URL.
    4. GenLayer validators fetch live authority data, reach consensus on APPROVED (conf: 98),
       and deterministically transfer 40 GEN indemnity payout directly to Bob.
    """
    contract = direct_deploy("contracts/optishield.py")

    # Step 1: Alice funds pool with 200 GEN
    direct_vm.sender = direct_alice
    direct_vm.value = 200 * 10**18
    contract.fund_underwriting_pool()

    stats = contract.get_protocol_stats()
    assert stats["underwriting_pool"] == str(200 * 10**18)

    # Step 2: Bob purchases 40 GEN policy paying 2 GEN premium
    direct_vm.sender = direct_bob
    coverage_val = 40 * 10**18
    premium_val = 2 * 10**18  # 5%
    direct_vm.value = premium_val

    pol_id = contract.purchase_policy(
        "FLIGHT_CANCELLATION",
        "UA894",
        coverage_val,
    )
    assert pol_id == 0

    pol = contract.get_policy(pol_id)
    assert pol["policyholder"].lower() == str(direct_bob).lower()
    assert pol["coverage_payout"] == str(coverage_val)
    assert pol["is_active"] is True
    assert pol["is_claimed"] is False

    # Step 3: Mock live authority data and multi-validator neural consensus
    direct_vm.mock_web(
        r".*flightaware\.com/api/status/UA894.*",
        {
            "status": 200,
            "body": json.dumps({
                "flight_number": "UA894",
                "status": "CANCELLED",
                "reason": "Severe Weather / Blizzard Alert",
                "scheduled_departure": "2026-08-16T18:00:00Z",
            }),
        },
    )

    direct_vm.mock_llm(
        r".*OptiShield Parametric Insurance Adjudication Engine.*",
        json.dumps({
            "is_valid": True,
            "confidence": 98,
            "status": "APPROVED",
            "rationale": "Official FlightAware telemetry confirms flight UA894 was officially CANCELLED due to blizzard.",
        }),
    )

    # Step 4: Bob files claim
    direct_vm.sender = direct_bob
    direct_vm.value = 0
    claim_id = contract.file_and_adjudicate_claim(
        pol_id,
        "https://flightaware.com/api/status/UA894",
        "Flight UA894 was cancelled at gate due to blizzard.",
    )
    assert claim_id == 0

    # Step 5: Verify claim APPROVED, payout recorded, and policy settled
    claim = contract.get_claim(claim_id)
    assert claim["status"] == "APPROVED"
    assert claim["consensus_confidence"] == 98
    assert claim["settled_payout"] == str(coverage_val)
    assert "confirms flight UA894 was officially CANCELLED" in claim["adjudication_rationale"]

    pol_after = contract.get_policy(pol_id)
    assert pol_after["is_active"] is False
    assert pol_after["is_claimed"] is True


def test_fraudulent_claim_rejection(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Test that claims with normal flight arrivals are REJECTED without disbursing pool funds."""
    contract = direct_deploy("contracts/optishield.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 100 * 10**18
    contract.fund_underwriting_pool()

    direct_vm.sender = direct_bob
    direct_vm.value = 1 * 10**18  # 5% of 20 GEN
    pol_id = contract.purchase_policy("FLIGHT_CANCELLATION", "LH450", 20 * 10**18)

    # Mock normal on-time flight arrival
    direct_vm.mock_web(
        r".*",
        {"status": 200, "body": json.dumps({"flight_number": "LH450", "status": "ON_TIME_LANDED"})},
    )
    direct_vm.mock_llm(
        r".*",
        json.dumps({
            "is_valid": False,
            "confidence": 99,
            "status": "REJECTED",
            "rationale": "Flight LH450 landed on schedule without qualifying delay or disruption.",
        }),
    )

    claim_id = contract.file_and_adjudicate_claim(pol_id, "https://authority.com/LH450", "Flight was fine.")

    claim = contract.get_claim(claim_id)
    assert claim["status"] == "REJECTED"
    assert claim["settled_payout"] == "0"


def test_insufficient_premium_revert(direct_vm, direct_deploy, direct_alice, direct_bob):
    """Test that purchasing coverage with less than 5% premium reverts immediately."""
    contract = direct_deploy("contracts/optishield.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 100 * 10**18
    contract.fund_underwriting_pool()

    direct_vm.sender = direct_bob
    direct_vm.value = int(0.5 * 10**18)  # Needs 1 GEN for 20 GEN coverage

    with direct_vm.expect_revert("Insufficient premium paid for requested coverage."):
        contract.purchase_policy("WEATHER_DISASTER", "HURRICANE_BERYL", 20 * 10**18)
