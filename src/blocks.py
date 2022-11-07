from brownie import web3


def find_block_at(search_timestamp):
    """
    Finds a block with a timestamp close to the `search_timestamp`.
    TODO: this isn't perfect, but it works well enough
    """
    latest_block = web3.eth.getBlock("latest")

    average_block_time = get_average_block_time(latest_block)

    # TODO: how much of a buffer should we add?
    blocks_to_search = (
        (latest_block.timestamp - search_timestamp) / average_block_time * 2
    )

    # we don't want to go too far back in time. so lets make an educated guess at the the first block to bother checking
    first_block_num = max(latest_block.number - blocks_to_search, 0)

    last_block_num = latest_block.number

    num_queries = 0
    needle = None
    mid_block = None
    while (first_block_num <= last_block_num) and (needle is None):
        mid_block_num = int((first_block_num + last_block_num) / 2)

        num_queries += 1
        mid_block = web3.eth.getBlock(mid_block_num)

        if mid_block.timestamp == search_timestamp:
            needle = mid_block
        else:
            if search_timestamp < mid_block.timestamp:
                last_block_num = mid_block_num - 1
            else:
                first_block_num = mid_block_num + 1

    if needle is None:
        # return the closest block
        if mid_block is None:
            needle = latest_block
        else:
            needle = mid_block

    return needle


def get_average_block_time(latest_block, span=10_000):
    # get the block gap blocks ago
    # TODO: what if latest_block.number < span?
    old_block = web3.eth.getBlock(latest_block.number - span)

    # average block time
    return (latest_block.timestamp - old_block.timestamp) / span
