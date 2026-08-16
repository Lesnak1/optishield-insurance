import { createClient, createAccount, type Address } from 'genlayer-js';
import { testnetBradbury } from 'genlayer-js/chains';

export const OPTISHIELD_ADDRESS: Address = '0xd9F9C1c91aeb2022bdBaA9b7a535b9796b8fB8F6';

export function getGenLayerClient(privateKey?: `0x${string}`) {
  return createClient({
    chain: testnetBradbury,
    account: privateKey ? createAccount(privateKey) : createAccount(),
  });
}

/**
 * Purchases a parametric insurance policy by paying a 5% premium.
 */
export async function purchasePolicy(
  client: ReturnType<typeof getGenLayerClient>,
  eventType: string,
  targetIdentifier: string,
  coverageAmountGen: number
) {
  const coverageWei = BigInt(coverageAmountGen) * BigInt(10 ** 18);
  const premiumWei = coverageWei / BigInt(20); // 5%

  const txHash = await client.writeContract({
    address: OPTISHIELD_ADDRESS,
    functionName: 'purchase_policy',
    args: [eventType, targetIdentifier, coverageWei],
    value: premiumWei,
  });

  return txHash;
}

/**
 * Files an incident claim triggering live authority web fetching and validator consensus.
 */
export async function fileClaim(
  client: ReturnType<typeof getGenLayerClient>,
  policyId: bigint,
  authorityEvidenceUrl: string,
  claimantNotes: string
) {
  const txHash = await client.writeContract({
    address: OPTISHIELD_ADDRESS,
    functionName: 'file_and_adjudicate_claim',
    args: [policyId, authorityEvidenceUrl, claimantNotes],
  });

  return txHash;
}

/**
 * Queries protocol reserves and total policies.
 */
export async function getProtocolStats(
  client: ReturnType<typeof getGenLayerClient>
) {
  return await client.readContract({
    address: OPTISHIELD_ADDRESS,
    functionName: 'get_protocol_stats',
    args: [],
  });
}
