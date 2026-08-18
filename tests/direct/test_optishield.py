import json
import pytest


def test_flight_cancellation_claim_and_instant_payout(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Test complete lifecycle of OptiShield:
    1. Protocol owner (Alice) seeds underwriting pool with 200 GEN.
    2. Traveler (Bob) purchases 40 GEN flight delay/cancellation insurance for flight UA894 for 7 days (604800s) paying 2 GEN premium (5%).
    3. Flight UA894 is cancelled due to blizzard. Bob files claim with official FlightAware status URL and valid incident timestamp.
    4. GenLayer validators fetch live authority data (HTTP 200), reach consensus on APPROVED (conf: 98),
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
    duration_secs = 604800  # 7 days
    direct_vm.value = premium_val

    pol_id = contract.purchase_policy(
        "FLIGHT_CANCELLATION",
        "UA894",
        coverage_val,
        duration_secs,
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

    # Step 4: Bob files claim with valid incident timestamp
    direct_vm.sender = direct_bob
    direct_vm.value = 0
    incident_ts = int(pol["coverage_start_timestamp"]) + 3600

    claim_id = contract.file_and_adjudicate_claim(
        pol_id,
        "https://flightaware.com/api/status/UA894",
        "Flight UA894 was cancelled at gate due to blizzard.",
        incident_ts,
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
    duration_secs = 604800
    pol_id = contract.purchase_policy("FLIGHT_CANCELLATION", "LH450", 20 * 10**18, duration_secs)

    pol = contract.get_policy(pol_id)
    incident_ts = int(pol["coverage_start_timestamp"]) + 7200

    # Mock normal on-time flight arrival from trusted domain
    direct_vm.mock_web(
        r".*flightradar24\.com/api/LH450.*",
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

    claim_id = contract.file_and_adjudicate_claim(
        pol_id,
        "https://flightradar24.com/api/LH450",
        "Flight was fine.",
        incident_ts,
    )

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
        contract.purchase_policy("WEATHER_DISASTER", "HURRICANE_BERYL", 20 * 10**18, 604800)


def test_untrusted_authority_domain_bypass_reverts(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Test that substring/spoofed URLs are strictly rejected by the authority hostname validator."""
    contract = direct_deploy("contracts/optishield.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 100 * 10**18
    contract.fund_underwriting_pool()

    direct_vm.sender = direct_bob
    direct_vm.value = 1 * 10**18
    pol_id = contract.purchase_policy("FLIGHT_CANCELLATION", "UA100", 20 * 10**18, 604800)
    pol = contract.get_policy(pol_id)
    incident_ts = int(pol["coverage_start_timestamp"]) + 1000

    # 1. Substring domain spoofing (attacker subdomain)
    with direct_vm.expect_revert("Untrusted evidence source"):
        contract.file_and_adjudicate_claim(
            pol_id,
            "https://faa.gov.attacker.com/telemetry",
            "Spoofed FAA subdomain",
            incident_ts,
        )

    # 2. Path-based spoofing
    with direct_vm.expect_revert("Untrusted evidence source"):
        contract.file_and_adjudicate_claim(
            pol_id,
            "https://evil.com/faa.gov/telemetry",
            "Path spoofing",
            incident_ts,
        )

    # 3. Query-param spoofing
    with direct_vm.expect_revert("Untrusted evidence source"):
        contract.file_and_adjudicate_claim(
            pol_id,
            "https://evil.com/telemetry?ref=flightaware.com",
            "Query spoofing",
            incident_ts,
        )


def test_incident_outside_coverage_window_reverts(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Test that filing a claim with an incident timestamp outside the policy coverage window reverts."""
    contract = direct_deploy("contracts/optishield.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 100 * 10**18
    contract.fund_underwriting_pool()

    direct_vm.sender = direct_bob
    direct_vm.value = 1 * 10**18
    duration = 3600  # 1 hour
    pol_id = contract.purchase_policy("CLOUD_SLA", "AWS_US_EAST_1", 20 * 10**18, duration)
    pol = contract.get_policy(pol_id)

    # Incident timestamp far after coverage expiration
    past_expiration_ts = int(pol["coverage_end_timestamp"]) + 10000

    with direct_vm.expect_revert("Incident timestamp falls outside active policy coverage window."):
        contract.file_and_adjudicate_claim(
            pol_id,
            "https://status.aws.amazon.com/rss/all.rss",
            "AWS Outage occurred after policy expired",
            past_expiration_ts,
        )


def test_unauthorized_expiry_release_reverts(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Test that arbitrary third-party callers cannot release active policies."""
    contract = direct_deploy("contracts/optishield.py")

    direct_vm.sender = direct_alice  # Protocol owner
    direct_vm.value = 100 * 10**18
    contract.fund_underwriting_pool()

    direct_vm.sender = direct_bob  # Policyholder
    direct_vm.value = 1 * 10**18
    pol_id = contract.purchase_policy("FLIGHT_CANCELLATION", "UA894", 20 * 10**18, 604800)

    # Charlie (random third-party attacker) attempts to release Bob's policy
    direct_charlie = "0x9999999999999999999999999999999999999999"
    direct_vm.sender = direct_charlie

    with direct_vm.expect_revert("Unauthorized. Only protocol owner or policyholder can release an expired policy."):
        contract.release_expired_policy(pol_id)
