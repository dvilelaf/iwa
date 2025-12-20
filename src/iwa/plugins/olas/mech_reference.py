"""Olas Mech Ecosystem - Contract Reference

This module documents all mech and marketplace contracts in the Olas ecosystem
and their relationship with activity checkers for staking rewards.

=============================================================================
MECH CONTRACTS
=============================================================================

1. LEGACY MECH (Direct Requests)
   Address: 0x77af31De935740567Cf4fF1986D04B2c964A786a
   ABI: mech.json
   Usage: Direct requests via request() -> deliver()
   Functions:
     - request(data) -> requestId
     - deliver(requestId, data)
     - getRequestsCount(multisig) -> count  # Used by legacy activity checker

2. MARKETPLACE MECHS (Via MechMarketplace)
   Address: 0x601024E27f1C67B28209E24272CED8A31fc8151F (Priority Mech)
   ABI: mech_new.json
   Usage: Requests via MechMarketplace.request() -> mech.deliverToMarketplace()
   Functions:
     - requestFromMarketplace(...) -> called by marketplace
     - deliverToMarketplace(...) -> delivers via marketplace
     - mechMarketplace -> address of associated marketplace
     - NO getRequestsCount() - tracking done by marketplace


=============================================================================
MARKETPLACE CONTRACTS
=============================================================================

1. OLD MECH MARKETPLACE (v1 / Beta)
   Address: 0x4554fE75c1f5576c1d7F765B2A036c199Adae329
   Total Requests: ~1.87M
   Used by: Pearl Beta Marketplace activity checker (0x7Ec96996Cd...)
   Status: LEGACY / DEPRECATED

2. NEW MECH MARKETPLACE (v2 / Current)
   Address: 0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB
   Total Requests: ~782K
   ABI: mech_marketplace.json
   Status: ACTIVE / CURRENT
   Note: This is the one we use in ServiceManager.send_mech_request()


=============================================================================
ACTIVITY CHECKERS
=============================================================================

Activity checkers determine which requests count for staking liveness rewards.

1. LEGACY ACTIVITY CHECKER (MechActivityChecker)
   Address: 0x87E6a97bD97D41904B1125A014B16bec50C6A89D
   Tracks: agentMech.getRequestsCount(multisig)
   Mech: 0x77af31De... (Legacy Mech)
   Used by: ALL TRADER staking contracts (Hobbyist, Expert 1-18)
   Effect: ONLY Legacy mech requests count for rewards

2. MARKETPLACE ACTIVITY CHECKER (MechMarketplaceActivityChecker)
   Address: 0x7Ec96996Cd146B91779f01419db42E67463817a0
   Tracks: mechMarketplace.getRequestsCount(multisig) (OLD marketplace)
   Marketplace: 0x4554fE75... (OLD Marketplace)
   Used by: Pearl Beta - Mech Marketplace staking contract
   Effect: ONLY OLD marketplace requests count (NOT the new marketplace!)


=============================================================================
STAKING CONTRACT COMPATIBILITY
=============================================================================

| Staking Contract      | Min OLAS | Activity Checker | Requests That Count |
|-----------------------|----------|------------------|---------------------|
| Hobbyist 1-2          | 50-250   | Legacy           | Legacy mech only    |
| Expert 1-18           | 100-500  | Legacy           | Legacy mech only    |
| Pearl Beta Marketplace| 20       | Marketplace      | OLD marketplace only|


=============================================================================
STAKING DEPOSIT + BOND MECHANICS
=============================================================================

When staking a service, the TOTAL OLAS required is split 50/50:

  minStakingDeposit: Goes to the staking contract as collateral
  agentBond:         Goes to Token Utility as operator bond

Example for Hobbyist 1 (100 OLAS total):
  - minStakingDeposit: 50 OLAS (stored in staking contract)
  - agentBond: 50 OLAS (stored in Token Utility for agent ID)
  - Total: 100 OLAS

Both are stored in the Token Utility contract:
  - mapServiceIdTokenDeposit(serviceId) -> (token, deposit)
  - getAgentBond(serviceId, agentId) -> bond

| Contract Name         | Min Deposit | Agent Bond | Total OLAS |
|-----------------------|-------------|------------|------------|
| Hobbyist 1 (100 OLAS) | 50          | 50         | 100        |
| Hobbyist 2 (500 OLAS) | 250         | 250        | 500        |
| Expert (1k OLAS)      | 500         | 500        | 1000       |
| Expert 3 (2k OLAS)    | 1000        | 1000       | 2000       |
| Expert 4+ (10k OLAS)  | 5000        | 5000       | 10000      |


=============================================================================
IMPORTANT FINDINGS
=============================================================================

⚠️ The NEW marketplace (0x735FAAb1...) that we use has NO STAKING CONTRACT
   that tracks its requests for liveness rewards yet!

⚠️ For TRADER staking rewards, you MUST use use_marketplace=False

⚠️ Pearl Beta Mech Marketplace uses the OLD marketplace, not the new one

"""

# Export contract addresses for easy reference
MECH_ECOSYSTEM = {
    "gnosis": {
        # Mech contracts
        "legacy_mech": "0x77af31De935740567Cf4fF1986D04B2c964A786a",
        "priority_mech": "0x601024E27f1C67B28209E24272CED8A31fc8151F",
        # Marketplace contracts
        "old_marketplace": "0x4554fE75c1f5576c1d7F765B2A036c199Adae329",  # v1, deprecated
        "new_marketplace": "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB",  # v2, current
        # Activity checkers
        "legacy_activity_checker": "0x87E6a97bD97D41904B1125A014B16bec50C6A89D",
        "marketplace_activity_checker": "0x7Ec96996Cd146B91779f01419db42E67463817a0",
        # Staking with marketplace support (uses OLD marketplace)
        "pearl_beta_marketplace_staking": "0xDaF34eC46298b53a3d24CBCb431E84eBd23927dA",
    }
}
