"""GraphQL query strings for OLAS subgraphs.

All queries use the id_gt pagination pattern for query_all().
"""

# ---------------------------------------------------------------------------
# Service Registry
# ---------------------------------------------------------------------------

SERVICES_PAGINATED = """
query Services($lastId: String!, $pageSize: Int!) {
  services(first: $pageSize, where: {id_gt: $lastId}, orderBy: id) {
    id
    multisig
    agentIds
    creationTimestamp
    configHash
    creator { id }
  }
}
"""

SERVICES_BY_AGENT_ID = """
query ServicesByAgentId($lastId: String!, $pageSize: Int!, $agentId: Int!) {
  services(
    first: $pageSize
    where: {id_gt: $lastId, agentIds_contains: [$agentId]}
    orderBy: id
  ) {
    id
    multisig
    agentIds
    creationTimestamp
    configHash
    creator { id }
  }
}
"""

SERVICE_BY_ID = """
query ServiceById($serviceId: ID!) {
  service(id: $serviceId) {
    id
    multisig
    agentIds
    creationTimestamp
    configHash
    creator { id }
  }
}
"""

SERVICES_BY_CREATOR = """
query ServicesByCreator($creator: Bytes!) {
  creators(where: {id: $creator}) {
    id
    services {
      id
      multisig
      agentIds
      creationTimestamp
      configHash
    }
  }
}
"""

MULTISIG_LOOKUP = """
query MultisigLookup($multisig: Bytes!) {
  multisigs(where: {id: $multisig}) {
    id
    serviceId
    creator
    agentIds
    creationTimestamp
  }
}
"""

DAILY_AGENT_PERFORMANCE = """
query DailyAgentPerformance($agentId: Int!, $since: BigInt!) {
  dailyAgentPerformances(
    where: {agentId: $agentId, dayTimestamp_gte: $since}
    orderBy: dayTimestamp
    orderDirection: desc
    first: 1000
  ) {
    id
    dayTimestamp
    agentId
    txCount
    activeMultisigCount
  }
}
"""

GLOBAL_STATS = """
{
  globals {
    id
    txCount
    lastUpdated
    totalOperators
  }
}
"""

# ---------------------------------------------------------------------------
# Staking
# ---------------------------------------------------------------------------

STAKING_CONTRACTS_PAGINATED = """
query StakingContracts($lastId: String!, $pageSize: Int!) {
  stakingContracts(first: $pageSize, where: {id_gt: $lastId}, orderBy: id) {
    id
    instance
    implementation
    maxNumServices
    rewardsPerSecond
    minStakingDeposit
    minStakingDuration
    maxNumInactivityPeriods
    livenessPeriod
    timeForEmissions
    numAgentInstances
    agentIds
    threshold
    configHash
    activityChecker
    serviceRegistry
    metadataHash
  }
}
"""

STAKING_CONTRACTS_BY_AGENT_ID = """
query StakingContractsByAgentId($lastId: String!, $pageSize: Int!, $agentId: BigInt!) {
  stakingContracts(
    first: $pageSize
    where: {id_gt: $lastId, agentIds_contains: [$agentId]}
    orderBy: id
  ) {
    id
    instance
    implementation
    maxNumServices
    rewardsPerSecond
    minStakingDeposit
    minStakingDuration
    maxNumInactivityPeriods
    livenessPeriod
    timeForEmissions
    numAgentInstances
    agentIds
    threshold
    configHash
    activityChecker
    serviceRegistry
    metadataHash
  }
}
"""

STAKING_SERVICE_INFO = """
query StakingServiceInfo($serviceId: ID!) {
  service(id: $serviceId) {
    id
    currentOlasStaked
    olasRewardsEarned
    blockNumber
    blockTimestamp
  }
}
"""

STAKING_REWARD_CLAIMS_BY_SERVICE = """
query StakingRewardClaimsByService($serviceId: BigInt!) {
  rewardClaimeds(
    where: {serviceId: $serviceId}
    orderBy: blockTimestamp
    orderDirection: desc
    first: 1000
  ) {
    id
    epoch
    serviceId
    owner
    multisig
    reward
    blockNumber
    blockTimestamp
    transactionHash
  }
}
"""

SERVICE_STAKED_EVENTS = """
query ServiceStakedEvents($serviceId: BigInt!) {
  serviceStakeds(where: {serviceId: $serviceId}, orderBy: blockTimestamp, orderDirection: desc) {
    id
    epoch
    serviceId
    owner
    multisig
    blockTimestamp
    transactionHash
  }
}
"""

SERVICE_UNSTAKED_EVENTS = """
query ServiceUnstakedEvents($serviceId: BigInt!) {
  serviceUnstakeds(where: {serviceId: $serviceId}, orderBy: blockTimestamp, orderDirection: desc) {
    id
    epoch
    serviceId
    owner
    multisig
    reward
    blockTimestamp
    transactionHash
  }
}
"""

SERVICE_INACTIVITY_WARNINGS = """
query ServiceInactivityWarnings($serviceId: BigInt!) {
  serviceInactivityWarnings(
    where: {serviceId: $serviceId}
    orderBy: blockTimestamp
    orderDirection: desc
  ) {
    id
    epoch
    serviceId
    serviceInactivity
    blockTimestamp
    transactionHash
  }
}
"""

SERVICES_EVICTED = """
query ServicesEvicted($serviceId: BigInt!) {
  servicesEvicteds(
    where: {serviceIds_contains: [$serviceId]}
    orderBy: blockTimestamp
    orderDirection: desc
  ) {
    id
    epoch
    serviceIds
    owners
    multisigs
    serviceInactivity
    blockTimestamp
    transactionHash
  }
}
"""

ACTIVE_SERVICE_CHECKPOINT = """
query ActiveServiceCheckpoint($contractAddress: Bytes!) {
  checkpoints(
    where: {contractAddress: $contractAddress}
    orderBy: epoch
    orderDirection: desc
    first: 1
  ) {
    id
    epoch
    serviceIds
    rewards
    availableRewards
    epochLength
    blockNumber
    blockTimestamp
    transactionHash
    contractAddress
  }
}
"""

STAKING_GLOBAL = """
{
  globals {
    id
    cumulativeOlasStaked
    cumulativeOlasUnstaked
    currentOlasStaked
    totalRewards
    lastActiveDayTimestamp
  }
}
"""

# ---------------------------------------------------------------------------
# Protocol Registry (Ethereum only — Autonolas subgraph)
# ---------------------------------------------------------------------------

PROTOCOL_SERVICES_PAGINATED = """
query ProtocolServices($lastId: String!, $pageSize: Int!) {
  services(first: $pageSize, where: {id_gt: $lastId}, orderBy: id) {
    id
    serviceId
    publicId
    state
    agentIds
    threshold
    securityDeposit
    numberOfInstances
    maxNumberOfInstances
    multisig
    instances
    packageHash
    metadataHash
    description
    owner
  }
}
"""

PROTOCOL_SERVICE_BY_ID = """
query ProtocolServiceById($serviceId: BigInt!) {
  services(where: {serviceId: $serviceId}) {
    id
    serviceId
    publicId
    state
    agentIds
    threshold
    securityDeposit
    numberOfInstances
    maxNumberOfInstances
    multisig
    instances
    packageHash
    metadataHash
    description
    owner
  }
}
"""

PROTOCOL_GLOBAL = """
{
  globals {
    id
    totalBuilders
    totalAgents
    totalComponents
    totalServices
  }
}
"""

PROTOCOL_AGENTS_PAGINATED = """
query ProtocolAgents($lastId: String!, $pageSize: Int!) {
  units(first: $pageSize, where: {id_gt: $lastId, packageType: agent}, orderBy: id) {
    id
    tokenId
    publicId
    description
    owner
    packageHash
    image
    metadataHash
    block
    txHash
  }
}
"""

PROTOCOL_COMPONENTS_PAGINATED = """
query ProtocolComponents($lastId: String!, $pageSize: Int!) {
  units(first: $pageSize, where: {id_gt: $lastId, packageType_not: agent}, orderBy: id) {
    id
    tokenId
    publicId
    packageType
    description
    owner
    packageHash
    image
    metadataHash
    block
    txHash
  }
}
"""

PROTOCOL_BUILDERS_PAGINATED = """
query Builders($lastId: String!, $pageSize: Int!) {
  builders(first: $pageSize, where: {id_gt: $lastId}, orderBy: id) {
    id
  }
}
"""

# ---------------------------------------------------------------------------
# Staking — additional entities
# ---------------------------------------------------------------------------

STAKING_CHECKPOINTS = """
query StakingCheckpoints($limit: Int!) {
  checkpoints(first: $limit, orderBy: blockTimestamp, orderDirection: desc) {
    id
    epoch
    availableRewards
    serviceIds
    rewards
    epochLength
    blockNumber
    transactionHash
    blockTimestamp
    contractAddress
  }
}
"""

STAKING_DEPOSITS = """
query StakingDeposits($limit: Int!) {
  deposits(first: $limit, orderBy: blockTimestamp, orderDirection: desc) {
    id
    sender
    amount
    balance
    availableRewards
    blockNumber
    blockTimestamp
    transactionHash
  }
}
"""

STAKING_WITHDRAWS = """
query StakingWithdraws($limit: Int!) {
  withdraws(first: $limit, orderBy: blockTimestamp, orderDirection: desc) {
    id
    to
    amount
    blockNumber
    blockTimestamp
    transactionHash
  }
}
"""

STAKING_REWARD_CLAIMS = """
query RewardClaims($limit: Int!) {
  rewardClaimeds(first: $limit, orderBy: blockTimestamp, orderDirection: desc) {
    id
    epoch
    serviceId
    owner
    multisig
    reward
    blockNumber
    blockTimestamp
    transactionHash
  }
}
"""

STAKING_DAILY_TRENDS = """
query DailyTrends($limit: Int!) {
  cumulativeDailyStakingGlobals(first: $limit, orderBy: timestamp, orderDirection: desc) {
    id
    timestamp
    block
    totalRewards
    numServices
    medianCumulativeRewards
  }
}
"""

STAKING_SERVICE_STAKED_RECENT = """
query RecentServiceStaked($limit: Int!) {
  serviceStakeds(first: $limit, orderBy: blockTimestamp, orderDirection: desc) {
    id
    epoch
    serviceId
    owner
    multisig
    blockTimestamp
    transactionHash
  }
}
"""

STAKING_SERVICE_UNSTAKED_RECENT = """
query RecentServiceUnstaked($limit: Int!) {
  serviceUnstakeds(first: $limit, orderBy: blockTimestamp, orderDirection: desc) {
    id
    epoch
    serviceId
    owner
    multisig
    reward
    blockTimestamp
    transactionHash
  }
}
"""

STAKING_SERVICE_INACTIVITY_RECENT = """
query RecentInactivity($limit: Int!) {
  serviceInactivityWarnings(first: $limit, orderBy: blockTimestamp, orderDirection: desc) {
    id
    epoch
    serviceId
    serviceInactivity
    blockTimestamp
    transactionHash
  }
}
"""

STAKING_EVICTIONS_RECENT = """
query RecentEvictions($limit: Int!) {
  servicesEvicteds(first: $limit, orderBy: blockTimestamp, orderDirection: desc) {
    id
    epoch
    serviceIds
    owners
    multisigs
    serviceInactivity
    blockTimestamp
    transactionHash
  }
}
"""

# ---------------------------------------------------------------------------
# Tokenomics
# ---------------------------------------------------------------------------

TOKENOMICS_TOKEN = """
{
  tokens(first: 1) {
    id
    balance
    holderCount
  }
}
"""

TOKENOMICS_TOP_HOLDERS = """
query TopHolders($limit: Int!) {
  tokenHolders(first: $limit, orderBy: balance, orderDirection: desc) {
    id
    balance
  }
}
"""

TOKENOMICS_RECENT_TRANSFERS = """
query RecentTransfers($limit: Int!) {
  transfers(first: $limit, orderBy: blockTimestamp, orderDirection: desc) {
    id
    from
    to
    value
    blockNumber
    blockTimestamp
    transactionHash
  }
}
"""
