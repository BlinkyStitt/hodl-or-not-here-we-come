from src.yearn import vault_earnings


def main(start_block, start_token, start_wei, end_block):
    if start_block < 13513457:
        # TODO: i think there have been multiple vaults. not sure the best way to pick the best one for each block range
        return None

    return vault_earnings(
        "0xa354F35829Ae975e850e23e9615b11Da1B3dC4DE",
        start_block,
        start_token,
        start_wei,
        end_block,
    )
