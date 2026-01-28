"""Script to verify ChainlistRPC functionality."""

from iwa.core.chainlist import ChainlistRPC


def main() -> None:
    """Run the verification script."""
    print("Initializing ChainlistRPC...")
    chainlist = ChainlistRPC()

    print("Fetching data...")
    chainlist.fetch_data()

    gnosis_chain_id = 100
    print(f"\n--- Gnosis Chain (ID: {gnosis_chain_id}) ---")

    all_rpcs = chainlist.get_rpcs(gnosis_chain_id)
    print(f"Total RPCs found: {len(all_rpcs)}")

    https_rpcs = chainlist.get_https_rpcs(gnosis_chain_id)
    print(f"HTTPS RPCs ({len(https_rpcs)}):")
    for url in https_rpcs[:5]:
        print(f"  - {url}")
    if len(https_rpcs) > 5:
        print("  ... and more")

    wss_rpcs = chainlist.get_wss_rpcs(gnosis_chain_id)
    print(f"WSS RPCs ({len(wss_rpcs)}):")
    for url in wss_rpcs[:5]:
        print(f"  - {url}")
    if len(wss_rpcs) > 5:
        print("  ... and more")

    print("\nTracking info for first 5 RPCs:")
    for node in all_rpcs[:5]:
        print(
            f"  - {node.url}: Tracking={node.is_tracking} (Privacy={node.privacy}, Tracking={node.tracking})"
        )


if __name__ == "__main__":
    main()
