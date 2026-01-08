# Gnosis Plugin

The Gnosis plugin integrates the Safe multisig and CowSwap protocols, providing robust asset management and trading capabilities on Gnosis Chain.

## CowSwap Integration

Iwa includes a fully-featured interface for trading on CowSwap, focusing on reliability and precision.

### Key Features

#### 1. Precision Trading ("Max" Button)
Handling the "Max" button in crypto UIs is notoriously difficult due to floating-point precision errors (e.g., swapping 1.0 ETH might fail if the user only has exactly 1.0 ETH due to gas or internal representation).

**Iwa's Solution:**
- When you click **Max**, the frontend does not send a number. It sends `amount: null`.
- The backend interprets `null` as the **exact** available balance of the wallet in `wei`.
- This ensures 0 dust remains and transactions never fail due to "insufficient funds" caused by the UI rounding down.

#### 2. Robust Balance Validation
To prevent failed orders, the backend validates balances *before* submitting to the CowSwap API.
- **Tolerance**: A tolerance of `0.0001` tokens is applied. If a user tries to swap slightly more than they have (due to UI staleness), the system automatically caps it to their max balance instead of failing.

#### 3. UX Enhancements
- **Auto-Refresh**: Confirmed trades automatically trigger a balance refresh in the UI.
- **Click-to-Swap**: Easily toggle sell/buy tokens.
- **MEV Protection**: CowSwap natively protects against MEV (Sandwich attacks).

## Safe (Multisig)

*Documentation coming soon.*
