# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
OptiShield: Autonomous Parametric Insurance & Multi-Source Event Adjudication Protocol on GenLayer.

Enables instant, trustless parametric insurance (flight disruptions, weather disasters, SLA outages).
Claims are adjudicated without centralized claims adjusters: GenLayer validators independently
fetch official authority web data (FAA, FlightAware, NOAA, cloud status pages), evaluate claim validity
via neural consensus, and deterministically release instant indemnity payouts to policyholders.
"""

from genlayer import *
from dataclasses import dataclass
import json


@allow_storage
@dataclass
class InsurancePolicy:
    policy_id: u256
    policyholder: Address
    event_type: str  # "FLIGHT_CANCELLATION", "WEATHER_DISASTER", "CLOUD_SLA"
    target_identifier: str  # e.g., "UA894", "HURRICANE_BERYL", "AWS_US_EAST_1"
    coverage_payout: u256
    premium_paid: u256
    is_active: bool
    is_claimed: bool
    created_at_block: u256


@allow_storage
@dataclass
class ClaimRecord:
    claim_id: u256
    policy_id: u256
    evidence_url: str
    incident_description: str
    status: str  # "PENDING", "APPROVED", "REJECTED"
    consensus_confidence: u32
    settled_payout: u256
    adjudication_rationale: str


class OptiShield(gl.Contract):
    """Autonomous Parametric Insurance Protocol on GenLayer."""

    policies: TreeMap[u256, InsurancePolicy]
    claims: TreeMap[u256, ClaimRecord]
    policy_counter: u256
    claim_counter: u256
    underwriting_pool: u256
    protocol_owner: Address

    def __init__(self):
        self.policy_counter = u256(0)
        self.claim_counter = u256(0)
        self.underwriting_pool = u256(0)
        self.protocol_owner = gl.message.sender_address

    @gl.public.write.payable
    def fund_underwriting_pool(self) -> None:
        """Liquidity providers fund the insurance underwriting reserve."""
        deposit = gl.message.value
        if deposit == u256(0):
            raise gl.vm.UserError("Must deposit GEN to fund underwriting pool.")
        self.underwriting_pool = self.underwriting_pool + deposit

    @gl.public.write.payable
    def purchase_policy(
        self,
        event_type: str,
        target_identifier: str,
        coverage_amount: u256,
    ) -> u256:
        """
        User purchases parametric coverage by paying a 5% risk premium.
        Coverage is guaranteed by the protocol underwriting reserve.
        """
        premium = gl.message.value
        required_premium = coverage_amount // u256(20)  # 5% premium

        if premium < required_premium:
            raise gl.vm.UserError("Insufficient premium paid for requested coverage.")

        # Ensure underwriting pool can cover maximum indemnity
        if coverage_amount > self.underwriting_pool:
            raise gl.vm.UserError("Requested coverage exceeds available underwriting pool capacity.")

        policy_id = self.policy_counter
        self.policy_counter = self.policy_counter + u256(1)

        # Add premium to underwriting pool
        self.underwriting_pool = self.underwriting_pool + premium

        self.policies[policy_id] = InsurancePolicy(
            policy_id=policy_id,
            policyholder=gl.message.sender_address,
            event_type=event_type,
            target_identifier=target_identifier,
            coverage_payout=coverage_amount,
            premium_paid=premium,
            is_active=True,
            is_claimed=False,
            created_at_block=u256(1),
        )

        return policy_id

    @gl.public.write
    def file_and_adjudicate_claim(
        self,
        policy_id: u256,
        authority_evidence_url: str,
        claimant_notes: str,
    ) -> u256:
        """
        Policyholder files claim. GenLayer validators independently fetch official
        live web data (FAA/NOAA/FlightStats), evaluate claim validity under the
        Equivalence Principle, and deterministically disburse the payout on finality.
        """
        policy = self.policies.get(policy_id, None)
        if policy is None or not policy.is_active:
            raise gl.vm.UserError("Policy does not exist or is inactive.")

        if gl.message.sender_address != policy.policyholder:
            raise gl.vm.UserError("Only the verified policyholder can file a claim.")

        if policy.is_claimed:
            raise gl.vm.UserError("Claim has already been filed and settled for this policy.")

        claim_id = self.claim_counter
        self.claim_counter = self.claim_counter + u256(1)

        event_type = policy.event_type
        target_id = policy.target_identifier
        coverage_val = policy.coverage_payout
        policyholder_addr = str(policy.policyholder)

        # Non-deterministic consensus block
        def leader_fn() -> dict:
            live_authority_data = ""
            if authority_evidence_url and authority_evidence_url.startswith("http"):
                try:
                    res = gl.nondet.web.get(authority_evidence_url)
                    live_authority_data = res.body.decode("utf-8", errors="replace")[:3000] if hasattr(res, "body") else str(res)[:3000]
                except Exception:
                    live_authority_data = "Authority web endpoint fetch returned error."

            prompt = f"""
            You are the OptiShield Parametric Insurance Adjudication Engine on GenLayer.
            Evaluate if the submitted claim qualifies for immediate payout under policy terms.

            === POLICY SPECIFICATION ===
            - Event Type: {event_type}
            - Covered Target: {target_id}

            === CLAIMANT NOTES ===
            {claimant_notes}

            === LIVE AUTHORITY DATA EXTRACTED FROM {authority_evidence_url} ===
            {live_authority_data}

            Evaluate:
            1. "is_valid": boolean true if authority data verifies the covered event occurred (e.g. flight cancelled/delayed >3h, hurricane category >=3, cloud downtime verified).
            2. "confidence": integer 0 to 100 representing evidentiary certainty.
            3. "status": "APPROVED" if (is_valid == true and confidence >= 85), else "REJECTED".
            4. "rationale": concise 1-2 sentence technical assessment.

            Respond ONLY with a JSON object matching this schema:
            {{
                "is_valid": bool,
                "confidence": int,
                "status": "APPROVED"|"REJECTED",
                "rationale": "string"
            }}
            """
            analysis = gl.nondet.exec_prompt(prompt, response_format="json")
            if not isinstance(analysis, dict):
                raise gl.vm.UserError("Adjudicator must return a JSON dictionary.")
            return analysis

        def validator_fn(leaders_res: gl.vm.Result) -> bool:
            """Validators independently verify authority web data under Equivalence Principle."""
            if not isinstance(leaders_res, gl.vm.Return):
                return False

            lead = leaders_res.calldata
            if not isinstance(lead, dict):
                return False

            for k in ["is_valid", "confidence", "status", "rationale"]:
                if k not in lead:
                    return False

            val = leader_fn()

            # Status verdict must match exactly
            if lead.get("status") != val.get("status"):
                return False

            # Boolean validity must agree
            if bool(lead.get("is_valid")) != bool(val.get("is_valid")):
                return False

            # Confidence tolerance within ±6 points
            l_conf = int(lead.get("confidence", 0))
            v_conf = int(val.get("confidence", 0))
            if abs(l_conf - v_conf) > 6:
                return False

            return True

        # Run multi-validator consensus
        verdict = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        status_str = str(verdict.get("status", "REJECTED"))
        conf_val = u32(int(verdict.get("confidence", 0)))
        rationale_str = str(verdict.get("rationale", ""))

        payout_awarded = u256(0)

        # Deterministic Financial Settlement Gate
        if status_str == "APPROVED" and conf_val >= u32(85):
            policy.is_active = False
            policy.is_claimed = True

            # Deduct payout from underwriting pool
            if coverage_val <= self.underwriting_pool:
                self.underwriting_pool = self.underwriting_pool - coverage_val
                payout_awarded = coverage_val
            else:
                payout_awarded = self.underwriting_pool
                self.underwriting_pool = u256(0)

            # Instant indemnity payout to policyholder on finality
            @gl.evm.contract_interface
            class _Recipient:
                class View:
                    pass
                class Write:
                    pass

            _Recipient(Address(policyholder_addr)).emit_transfer(value=payout_awarded)

        self.policies[policy_id] = policy

        self.claims[claim_id] = ClaimRecord(
            claim_id=claim_id,
            policy_id=policy_id,
            evidence_url=authority_evidence_url,
            incident_description=claimant_notes,
            status=status_str,
            consensus_confidence=conf_val,
            settled_payout=payout_awarded,
            adjudication_rationale=rationale_str,
        )

        return claim_id

    @gl.public.view
    def get_policy(self, policy_id: u256) -> dict:
        """View coverage and status of a policy."""
        p = self.policies.get(policy_id, None)
        if p is None:
            raise gl.vm.UserError("Policy not found.")
        return {
            "policy_id": int(p.policy_id),
            "policyholder": str(p.policyholder),
            "event_type": p.event_type,
            "target_identifier": p.target_identifier,
            "coverage_payout": str(p.coverage_payout),
            "premium_paid": str(p.premium_paid),
            "is_active": p.is_active,
            "is_claimed": p.is_claimed,
        }

    @gl.public.view
    def get_claim(self, claim_id: u256) -> dict:
        """View claim status and validator consensus rationale."""
        c = self.claims.get(claim_id, None)
        if c is None:
            raise gl.vm.UserError("Claim not found.")
        return {
            "claim_id": int(c.claim_id),
            "policy_id": int(c.policy_id),
            "evidence_url": c.evidence_url,
            "status": c.status,
            "consensus_confidence": int(c.consensus_confidence),
            "settled_payout": str(c.settled_payout),
            "adjudication_rationale": c.adjudication_rationale,
        }

    @gl.public.view
    def get_protocol_stats(self) -> dict:
        """View overall protocol reserves and coverage stats."""
        return {
            "underwriting_pool": str(self.underwriting_pool),
            "total_policies": int(self.policy_counter),
            "total_claims": int(self.claim_counter),
        }
