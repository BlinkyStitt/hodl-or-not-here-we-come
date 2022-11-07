from brownie import Contract

UNISWAP_V1_FACTORY = Contract("0xc0a47dFe034B400B47bDaD5FecDa2621de6c4d95")


def get_exchange(token_address):
    exchange = UNISWAP_V1_FACTORY.getExchange(token_address)
    return Contract(exchange)

