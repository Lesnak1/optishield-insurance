import { createClient, createAccount, generatePrivateKey, type Address } from 'genlayer-js';
import { testnetBradbury, studionet, localnet } from 'genlayer-js/chains';

/**
 * OptiShield GenLayer Client Integration
 * Provides complete TypeScript bindings for all intelligent contract methods on GenLayer:
 * - fund_underwriting_pool (Payable, adds capital to underwriting reserve)
 * - purchase_policy (Payable, reserves payout liabilities and locks dated coverage)
 * - file_and_adjudicate_claim (Triggers multi-validator LLM consensus against live authority data)
 * - release_expired_policy (Releases liabilities for expired unclaimed policies)
 * - get_policy (Read-only view of policy state and coverage dates)
 * - get_claim (Read-only view of claim adjudication and consensus confidence)
 * - get_protocol_stats (Read-only view of pool solvency, reserves, and capacity)
 */

export const DEFAULT_OPTISHIELD_ADDRESS: Address = '0xd9F9C1c91aeb2022bdBaA9b7a535b9796b8fB8F6';

export interface PolicyState {
  policy_id: number;
  policyholder: string;
  event_type: string;
  target_identifier: string;
  coverage_payout: string;
  premium_paid: string;
  coverage_start_timestamp: string;
  coverage_end_timestamp: string;
  is_active: boolean;
  is_claimed: boolean;
  is_finalized: boolean;
}

export interface ClaimState {
  claim_id: number;
  policy_id: number;
  evidence_url: string;
  incident_description: string;
  incident_timestamp: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'FINALIZED';
  consensus_confidence: number;
  settled_payout: string;
  adjudication_rationale: string;
  is_finalized: boolean;
}

export interface ProtocolStats {
  underwriting_pool: string;
  reserved_liabilities: string;
  available_capacity: string;
  total_policies: number;
  total_claims: number;
}

export type SupportedChain = 'testnetBradbury' | 'studionet' | 'localnet';

export function getChainConfig(chainType: SupportedChain = 'testnetBradbury') {
  switch (chainType) {
    case 'studionet':
      return studionet;
    case 'localnet':
      return localnet;
    case 'testnetBradbury':
    default:
      return testnetBradbury;
  }
}

export function getGenLayerClient(
  privateKey?: `0x${string}`,
  chainType: SupportedChain = 'testnetBradbury'
) {
  const account = privateKey ? createAccount(privateKey) : createAccount(generatePrivateKey());
  const chain = getChainConfig(chainType);

  return createClient({
    chain,
    account,
  });
}

/**
 * Funds the protocol underwriting reserve.
 */
export async function fundUnderwritingPool(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  depositGenAmount: string | number
): Promise<`0x${string}`> {
  const depositWei = BigInt(Math.floor(Number(depositGenAmount) * 1e18));

  const txHash = await client.writeContract({
    address: contractAddress,
    functionName: 'fund_underwriting_pool',
    args: [],
    value: depositWei,
  });

  return txHash as `0x${string}`;
}

/**
 * Purchases a parametric insurance policy with dated coverage and reserved payout liability.
 */
export async function purchasePolicy(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  eventType: string,
  targetIdentifier: string,
  coverageGenAmount: string | number,
  durationSeconds: number = 86400 * 7 // Default 7 days
): Promise<`0x${string}`> {
  const coverageWei = BigInt(Math.floor(Number(coverageGenAmount) * 1e18));
  const premiumWei = coverageWei / BigInt(20); // 5% premium

  const txHash = await client.writeContract({
    address: contractAddress,
    functionName: 'purchase_policy',
    args: [eventType, targetIdentifier, coverageWei, BigInt(durationSeconds)],
    value: premiumWei,
  });

  return txHash as `0x${string}`;
}

/**
 * Files an incident claim triggering live authority web fetching and validator consensus.
 */
export async function fileAndAdjudicateClaim(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  policyId: bigint | number,
  authorityEvidenceUrl: string,
  claimantNotes: string,
  incidentTimestamp: bigint | number = Math.floor(Date.now() / 1000)
): Promise<`0x${string}`> {
  const txHash = await client.writeContract({
    address: contractAddress,
    functionName: 'file_and_adjudicate_claim',
    args: [BigInt(policyId), authorityEvidenceUrl, claimantNotes, BigInt(incidentTimestamp)],
  });

  return txHash as `0x${string}`;
}

/**
 * Releases reserved liabilities for an expired unclaimed policy.
 */
export async function releaseExpiredPolicy(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  policyId: bigint | number
): Promise<`0x${string}`> {
  const txHash = await client.writeContract({
    address: contractAddress,
    functionName: 'release_expired_policy',
    args: [BigInt(policyId)],
  });

  return txHash as `0x${string}`;
}

/**
 * Queries policy details from contract storage.
 */
export async function getPolicy(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  policyId: bigint | number
): Promise<PolicyState> {
  const data = await client.readContract({
    address: contractAddress,
    functionName: 'get_policy',
    args: [BigInt(policyId)],
  });

  return data as unknown as PolicyState;
}

/**
 * Queries claim state and multi-validator adjudication verdict.
 */
export async function getClaim(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  claimId: bigint | number
): Promise<ClaimState> {
  const data = await client.readContract({
    address: contractAddress,
    functionName: 'get_claim',
    args: [BigInt(claimId)],
  });

  return data as unknown as ClaimState;
}

/**
 * Queries protocol reserves, reserved liabilities, and available capacity.
 */
export async function getProtocolStats(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address
): Promise<ProtocolStats> {
  const data = await client.readContract({
    address: contractAddress,
    functionName: 'get_protocol_stats',
    args: [],
  });

  return data as unknown as ProtocolStats;
}

/**
 * Waits for transaction finality and consensus receipt on GenLayer.
 */
export async function waitForTransactionReceipt(
  client: ReturnType<typeof getGenLayerClient>,
  hash: `0x${string}`
) {
  return await client.waitForTransactionReceipt({ hash });
}
