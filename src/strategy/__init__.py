from .curve_tricrypto2 import main as curve_tricrypto2
from .hodl_eth import main as hodl_eth
from .uniswap_v2_single_sided import main as uniswap_v2_single_sided
from .yearn_vault_tricrypto2 import main as yearn_vault_tricrypto2
from .yearn_vault_usdc import main as yearn_vault_usdc

_ALL__ = [
    curve_tricrypto2,
    hodl_eth,
    uniswap_v2_single_sided,
    yearn_vault_usdc,
    yearn_vault_tricrypto2,
]
