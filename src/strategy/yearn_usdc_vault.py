from brownie import Contract


def main(start_block, start_usdc_wei, end_block):
    if start_block < 13513457:
        # TODO: i think there have been multiple vaults. not sure the best way to pick the best one for each block range
        return None

    usdc_vault = Contract("0xa354F35829Ae975e850e23e9615b11Da1B3dC4DE")

    start_pps = usdc_vault.pricePerShare(block_identifier=start_block)
    end_pps = usdc_vault.pricePerShare(block_identifier=end_block)

    pps_delta = end_pps - start_pps
    pps_decimal_shift = 1e6

    usdc_wei_delta = start_usdc_wei * pps_delta // pps_decimal_shift

    return start_usdc_wei + usdc_wei_delta
