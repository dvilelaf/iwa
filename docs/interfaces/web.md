# Web Interface

Iwa provides a modern, responsive Web UI built with **FastAPI** (backend) and **Vanilla JS/CSS** (frontend). It prioritizes speed, simplicity, and direct blockchain interaction.

## Dashboard

The dashboard provides an at-a-glance view of your financial autonomy:

- **Wallet Balance**: Real-time native (xDAI/ETH) and ERC20 balances.
- **Recent Activity**: List of latest transactions and CowSwap orders.
- **Quick Actions**: One-click access to Swap, Wrap, and Send.

## Features

### Swapping (CowSwap)
Located at `/swap`, this interface allows for gasless (paid in sell token) protected swaps.
- **Supports**: Native (xDAI) <-> Wrapped (WXDAI) seamless wrapping.

### Service Manager (Olas)
A dedicated panel for managing autonomous agents.
- View Service State (Pre-Registration, Active, Deployed, Terminated).
- One-click actions to **Fund**, **Stake**, and **Unstake**.

## Running

The web interface is available at `http://localhost:8080`.

```bash
just web
```
