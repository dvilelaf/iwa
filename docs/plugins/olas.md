# Olas Plugin

The Olas plugin allows Iwa to interact with the [Olas (formerly Autonolas)](https://olas.network) ecosystem, enabling the deployment and management of autonomous services.

## Features

- **Service Registry**: Mint and manage Services and Agents as NFTs on-chain.
- **Staking**: Stake services in Olas staking contracts to earn rewards.
- **Service Management**:
    - **Create**: Define new services with specific agent configurations.
    - **Deploy**: Spin up agent instances (currently utilizing local Docker or similar).
    - **Fund**: Easy tools to fund master and agent safes.

## Workflows

### Staking a Service

1. **Minting**: Create a service on the registry.
2. **Bonding**: Operators bond assets to the service.
3. **Deploying**: The service reaches the `DEPLOYED` state.
4. **Staking**: Choose a staking contract (Alpine, Everest, etc.) and call `stake()`.
   - *Note*: Iwa filters staking contracts to prevent mismatches (e.g., trying to stake a service with a low security deposit into a high-requirement contract).
