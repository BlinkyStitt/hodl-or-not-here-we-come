from src.uniswap_v1 import get_exchange


def main(start_block, in_token, in_wei, end_block):
    """Trade in_token on Uniswap V! for ETH and hold it until end_block.

    uniswap v1 is the oldest and still has okay liquidity, so it works for now.
    TODO: use 1inch's on-chain exchange?
    """
    exchange = get_exchange(in_token)

    # at start_block. trade in token to ETH
    eth_wei = exchange.getTokenToEthInputPrice(in_wei, block_identifier=start_block)

    # at end_block. trade ETH back to the original token
    end_wei = exchange.getEthToTokenInputPrice(eth_wei, block_identifier=end_block)

    return end_wei
