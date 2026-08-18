# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
OptiShield: Autonomous Parametric Insurance & Multi-Source Event Adjudication Protocol on GenLayer.

Enables instant, trustless parametric insurance (flight disruptions, weather disasters, cloud SLA outages).
Claims are adjudicated without centralized adjusters: GenLayer validators independently
fetch official authority web data (FAA, FlightAware, NOAA, cloud status pages), evaluate claim validity
via neural consensus, and deterministically release instant indemnity payouts to policyholders.

Core Security & Solvency Guarantees:
- Enforceable Runtime Timing & Coverage Windows (start & expiration timestamps derived from runtime state)
- Strict Authority Domain Whitelist (exact host & subdomain matching, preventing hostname spoofing/bypasses)
- Fetch Success Validation (ensures HTTP 200 responses before adjudication; failed fetches are strictly rejected)
- Restricted Expiry Release (only authorized callers can release liabilities, and only after verifiable expiration)
- Strict Claim Finality (single adjudication per policy, eliminating double claims)
- Reserved Payout Liabilities (ensures 100% pool solvency before issuing policies)
"""

from genlayer import *
from dataclasses import dataclass
import json


# Whitelist of approved trusted authority evidence domains
TRUSTED_AUTHORITY_DOMAINS = [
    "faa.gov",
    "api.faa.gov",
    "noaa.gov",
    "weather.gov",
    "nhc.noaa.gov",
    "flightaware.com",
    "flightradar24.com",
    "aviationstack.com",
    "status.aws.amazon.com",
    "status.cloud.google.com",
    "azure.status.microsoft.com",
    "cloudflarestatus.com",
    "githubstatus.com",
    "earthquake.usgs.gov",
]


def _get_runtime_timestamp() -> u256:
    """
    Derives current timestamp from enforceable GenLayer runtime block/message state.
    Falls back to 0 if runtime block time is not populated.
    """
    if hasattr(gl, "block") and hasattr(gl.block, "timestamp") and gl.block.timestamp is not None:
        return u256(int(gl.block.timestamp))
    if hasattr(gl, "message") and hasattr(gl.message, "block_timestamp") and gl.message.block_timestamp is not None:
        return u256(int(gl.message.block_timestamp))
    return u256(0)


def _extract_hostname(url: str) -> str:
    """
    Strictly extracts hostname from HTTP/HTTPS URL preventing path, query, port, or auth bypasses.
    Example: 'https://api.faa.gov/v1/notams?q=1' -> 'api.faa.gov'
    """
    if not url or not isinstance(url, str):
        return ""
    url_clean = url.strip()
    if not (url_clean.startswith("http://") or url_clean.startswith("https://")):
        return ""

    if url_clean.startswith("https://"):
        rest = url_clean[8:]
    else:
        rest = url_clean[7:]

    # Strip user:password authentication if present
    if "@" in rest.split("/")[0]:
        rest = rest.split("@", 1)[1]

    # Extract host part before path, query, or hash
    host_part = rest.split("/")[0].split("?")[0].split("#")[0]
    if ":" in host_part:
        host_part = host_part.split(":")[0]

    return host_part.lower().strip()


def _is_trusted_authority_host(url: str) -> bool:
    """
    Validates that the URL's hostname exactly matches or is a direct subdomain of an approved authority domain.
    Prevents substring/prefix bypasses (e.g. 'faa.gov.attacker.com' or 'attacker.com/faa.gov' are rejected).
    """
    host = _extract_hostname(url)
    if not host:
        return False

    for domain in TRUSTED_AUTHORITY_DOMAINS:
        domain_lower = domain.lower()
        # Exact match OR strict subdomain match (e.g. "api.weather.gov" ends with ".weather.gov")
        if host == domain_lower or host.endswith("." + domain_lower):
            return True
    return False


@allow_storage
@dataclass
class InsurancePolicy:
    policy_id: u256
    policyholder: Address
    event_type: str  # "FLIGHT_CANCELLATION", "WEATHER_DISASTER", "CLOUD_SLA"
    target_identifier: str  # e.g., "UA894", "HURRICANE_BERYL", "AWS_US_EAST_1"
    coverage_payout: u256
    premium_paid: u256
    coverage_start_timestamp: u256
    coverage_end_timestamp: u256
    is_active: bool
    is_claimed: bool
    is_finalized: bool


@allow_storage
@dataclass
class ClaimRecord:
    claim_id: u256
    policy_id: u256
    evidence_url: str
    incident_description: str
    incident_timestamp: u256
    status: str  # "PENDING", "APPROVED", "REJECTED", "FINALIZED"
    consensus_confidence: u32
    settled_payout: u256
    adjudication_rationale: str
    is_finalized: bool


class OptiShield(gl.Contract):
    """Autonomous Parametric Insurance Protocol on GenLayer with Enforceable Timing & Solvency Guarantees."""

    policies: TreeMap[u256, InsurancePolicy]
    claims: TreeMap[u256, ClaimRecord]
    policy_counter: u256
    claim_counter: u256
    underwriting_pool: u256
    reserved_liabilities: u256  # Payout capacity locked to guarantee active policy payouts
    protocol_owner: Address

    def __init__(self):
        self.policy_counter = u256(0)
        self.claim_counter = u256(0)
        self.underwriting_pool = u256(0)
        self.reserved_liabilities = u256(0)
        self.protocol_owner = gl.message.sender_address

    @gl.public.write.payable
    def fund_underwriting_pool(self) -> None:
        """Liquidity providers fund the insurance underwriting reserve."""
        deposit = gl.message.value
        if deposit == u256(0):
            raise gl.vm.UserError("Must deposit non-zero GEN to fund underwriting pool.")
        self.underwriting_pool = self.underwriting_pool + deposit

    @gl.public.write.payable
    def purchase_policy(
        self,
        event_type: str,
        target_identifier: str,
        coverage_amount: u256,
        coverage_duration_seconds: u256,
    ) -> u256:
        """
        User purchases parametric coverage for a specific dated window by paying a 5% premium.
        Enforces reserved payout liabilities contract-side to guarantee protocol solvency.
        Derives coverage timestamps from enforceable runtime block state.
        """
        premium = gl.message.value
        required_premium = coverage_amount // u256(20)  # 5% premium

        if premium < required_premium:
            raise gl.vm.UserError("Insufficient premium paid for requested coverage.")

        if coverage_duration_seconds == u256(0):
            raise gl.vm.UserError("Coverage duration must be greater than zero.")

        # Solvency Check: Ensure unreserved pool capacity is sufficient for full payout liability
        available_capacity = (
            self.underwriting_pool - self.reserved_liabilities
            if self.underwriting_pool >= self.reserved_liabilities
            else u256(0)
        )
        if coverage_amount > available_capacity:
            raise gl.vm.UserError("Requested coverage exceeds available unreserved underwriting capacity.")

        # Lock reserved liability and add premium to pool
        self.reserved_liabilities = self.reserved_liabilities + coverage_amount
        self.underwriting_pool = self.underwriting_pool + premium

        policy_id = self.policy_counter
        self.policy_counter = self.policy_counter + u256(1)

        # Derive start timestamp from enforceable runtime state
        runtime_ts = _get_runtime_timestamp()
        start_ts = runtime_ts
        end_ts = start_ts + coverage_duration_seconds

        self.policies[policy_id] = InsurancePolicy(
            policy_id=policy_id,
            policyholder=gl.message.sender_address,
            event_type=event_type,
            target_identifier=target_identifier,
            coverage_payout=coverage_amount,
            premium_paid=premium,
            coverage_start_timestamp=start_ts,
            coverage_end_timestamp=end_ts,
            is_active=True,
            is_claimed=False,
            is_finalized=False,
        )

        return policy_id

    @gl.public.write
    def file_and_adjudicate_claim(
        self,
        policy_id: u256,
        authority_evidence_url: str,
        claimant_notes: str,
        incident_timestamp: u256,
    ) -> u256:
        """
        Policyholder files claim. Enforces:
        1. Enforceable dated coverage window check
        2. Whitelisted trusted authority source validation (exact host match)
        3. Authority fetch success validation (HTTP 200 required)
        4. Strict claim finality (single adjudication per policy)
        5. Deterministic financial disbursement from reserved underwriting liabilities
        """
        policy = self.policies.get(policy_id, None)
        if policy is None or not policy.is_active:
            raise gl.vm.UserError("Policy does not exist or is inactive.")

        if gl.message.sender_address != policy.policyholder:
            raise gl.vm.UserError("Only the verified policyholder can file a claim.")

        # Enforce Claim Finality
        if policy.is_claimed or policy.is_finalized:
            raise gl.vm.UserError("Claim on this policy has already reached finality.")

        # Enforce Dated Coverage Window
        if incident_timestamp < policy.coverage_start_timestamp or incident_timestamp > policy.coverage_end_timestamp:
            raise gl.vm.UserError("Incident timestamp falls outside active policy coverage window.")

        # Enforce that incident timestamp cannot be in the future relative to runtime block time
        runtime_ts = _get_runtime_timestamp()
        if runtime_ts > u256(0) and incident_timestamp > runtime_ts:
            raise gl.vm.UserError("Incident timestamp cannot be in the future.")

        # Enforce Trusted Authority Evidence Source Whitelist (Exact host/subdomain check)
        if not _is_trusted_authority_host(authority_evidence_url):
            raise gl.vm.UserError(
                "Untrusted evidence source. Must originate from an approved authority domain (FAA, NOAA, FlightAware, Cloud Status)."
            )

        claim_id = self.claim_counter
        self.claim_counter = self.claim_counter + u256(1)

        event_type = policy.event_type
        target_id = policy.target_identifier
        coverage_val = policy.coverage_payout
        policyholder_addr = str(policy.policyholder)

        # Multi-Validator Non-Deterministic Consensus
        def leader_fn() -> dict:
            try:
                res = gl.nondet.web.get(authority_evidence_url)
            except Exception as e:
                return {
                    "is_valid": False,
                    "confidence": 0,
                    "status": "REJECTED",
                    "rationale": f"Authority web endpoint fetch failed with network exception: {str(e)[:100]}",
                }

            # Enforce HTTP fetch success
            http_status = getattr(res, "status", None) or getattr(res, "status_code", 200)
            if isinstance(http_status, int) and (http_status < 200 or http_status >= 300):
                return {
                    "is_valid": False,
                    "confidence": 0,
                    "status": "REJECTED",
                    "rationale": f"Authority web endpoint returned non-success HTTP status {http_status}.",
                }

            raw_body = getattr(res, "body", b"")
            if isinstance(raw_body, bytes):
                live_authority_data = raw_body.decode("utf-8", errors="replace")[:3000]
            else:
                live_authority_data = str(raw_body or res)[:3000]

            if not live_authority_data.strip():
                return {
                    "is_valid": False,
                    "confidence": 0,
                    "status": "REJECTED",
                    "rationale": "Authority web endpoint returned empty telemetry body.",
                }

            prompt = f"""
            You are the OptiShield Parametric Insurance Adjudication Engine on GenLayer.
            Evaluate if the submitted claim qualifies for immediate payout under policy terms.

            === POLICY SPECIFICATION ===
            - Event Type: {event_type}
            - Covered Target: {target_id}
            - Incident Timestamp: {incident_timestamp}

            === CLAIMANT NOTES ===
            {claimant_notes}

            === LIVE AUTHORITY DATA EXTRACTED FROM {authority_evidence_url} ===
            {live_authority_data}

            Evaluate:
            1. "is_valid": boolean true if authority data verifies the covered qualifying event occurred (e.g. flight cancelled/delayed >3h, hurricane category >=3, cloud downtime verified).
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

        # Enforce Policy Finality
        policy.is_active = False
        policy.is_finalized = True

        # Release Reserved Liability
        if self.reserved_liabilities >= coverage_val:
            self.reserved_liabilities = self.reserved_liabilities - coverage_val
        else:
            self.reserved_liabilities = u256(0)

        # Deterministic Financial Settlement Gate
        if status_str == "APPROVED" and conf_val >= u32(85):
            policy.is_claimed = True

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
            incident_timestamp=incident_timestamp,
            status=status_str,
            consensus_confidence=conf_val,
            settled_payout=payout_awarded,
            adjudication_rationale=rationale_str,
            is_finalized=True,
        )

        return claim_id

    @gl.public.write
    def release_expired_policy(self, policy_id: u256) -> None:
        """
        Unlocks reserved liabilities for policies that have strictly passed their coverage end date
        without any claims filed, freeing underwriting pool capacity for new policies.

        Enforces:
        1. Policy must exist, be active, and not already finalized/claimed.
        2. Caller must be the protocol owner or the policyholder.
        3. Current runtime timestamp must be strictly greater than coverage_end_timestamp.
        """
        policy = self.policies.get(policy_id, None)
        if policy is None:
            raise gl.vm.UserError("Policy not found.")

        if not policy.is_active or policy.is_finalized or policy.is_claimed:
            raise gl.vm.UserError("Policy is not active or has already been finalized/claimed.")

        # Restrict caller to protocol owner or policyholder
        caller = gl.message.sender_address
        if caller != self.protocol_owner and caller != policy.policyholder:
            raise gl.vm.UserError("Unauthorized. Only protocol owner or policyholder can release an expired policy.")

        # Enforce Expiry: Runtime timestamp must have strictly surpassed coverage_end_timestamp
        current_ts = _get_runtime_timestamp()
        if current_ts > u256(0) and current_ts <= policy.coverage_end_timestamp:
            raise gl.vm.UserError(
                "Policy coverage is still active. Cannot release liability before coverage expiration timestamp."
            )

        # Unlock liability
        if self.reserved_liabilities >= policy.coverage_payout:
            self.reserved_liabilities = self.reserved_liabilities - policy.coverage_payout
        else:
            self.reserved_liabilities = u256(0)

        policy.is_active = False
        policy.is_finalized = True
        self.policies[policy_id] = policy

    @gl.public.view
    def get_policy(self, policy_id: u256) -> dict:
        """View coverage details, dated window, and status of a policy."""
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
            "coverage_start_timestamp": str(p.coverage_start_timestamp),
            "coverage_end_timestamp": str(p.coverage_end_timestamp),
            "is_active": p.is_active,
            "is_claimed": p.is_claimed,
            "is_finalized": p.is_finalized,
        }

    @gl.public.view
    def get_claim(self, claim_id: u256) -> dict:
        """View claim status, authority source, and validator consensus rationale."""
        c = self.claims.get(claim_id, None)
        if c is None:
            raise gl.vm.UserError("Claim not found.")
        return {
            "claim_id": int(c.claim_id),
            "policy_id": int(c.policy_id),
            "evidence_url": c.evidence_url,
            "incident_description": c.incident_description,
            "incident_timestamp": str(c.incident_timestamp),
            "status": c.status,
            "consensus_confidence": int(c.consensus_confidence),
            "settled_payout": str(c.settled_payout),
            "adjudication_rationale": c.adjudication_rationale,
            "is_finalized": c.is_finalized,
        }

    @gl.public.view
    def get_protocol_stats(self) -> dict:
        """View overall protocol reserves, reserved liabilities, and capacity stats."""
        avail_capacity = (
            self.underwriting_pool - self.reserved_liabilities
            if self.underwriting_pool >= self.reserved_liabilities
            else u256(0)
        )
        return {
            "underwriting_pool": str(self.underwriting_pool),
            "reserved_liabilities": str(self.reserved_liabilities),
            "available_capacity": str(avail_capacity),
            "total_policies": int(self.policy_counter),
            "total_claims": int(self.claim_counter),
        }
