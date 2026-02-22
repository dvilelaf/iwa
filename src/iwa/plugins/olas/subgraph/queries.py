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
query StakingContracts($lastId: Bytes!, $pageSize: Int!) {
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
query StakingContractsByAgentId($lastId: Bytes!, $pageSize: Int!, $agentId: BigInt!) {
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
    olasRewardsClaimed
    latestStakingContract
    totalEpochsParticipated
    blockTimestamp
  }
}
"""

STAKING_REWARDS_HISTORY = """
query StakingRewardsHistory($serviceId: String!) {
  serviceRewardsHistories(
    where: {service: $serviceId}
    orderBy: epoch
    orderDirection: desc
    first: 1000
  ) {
    id
    epoch
    contractAddress
    rewardAmount
    checkpointedAt
    blockTimestamp
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

ACTIVE_SERVICE_EPOCH = """
query ActiveServiceEpoch($contractAddress: Bytes!) {
  activeServiceEpoches(
    where: {contractAddress: $contractAddress}
    orderBy: epoch
    orderDirection: desc
    first: 1
  ) {
    id
    contractAddress
    epoch
    activeServiceIds
    blockTimestamp
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
query ProtocolServices($lastId: Bytes!, $pageSize: Int!) {
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
    multisig
    instances
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
