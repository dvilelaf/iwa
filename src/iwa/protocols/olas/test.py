from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from triton.config import TritonConfig
from pathlib import Path
from triton.constants import CONFIG_PATH
from triton.key_storage import TritonWallet
from triton.models import ServiceConfig
from triton.contracts.service import ServiceManagerContract, ServiceRegistryContract
from triton.service import Service
import logging
from triton.contracts.staking import StakingContract
from triton.constants import (
    OLAS_TOKEN_ADDRESS_GNOSIS,
)
from triton.contracts.erc20 import ERC20Contract


if __name__ == '__main__':

    staking_contract = StakingContract("0x6c65430515c70a3f5E62107CC301685B7D46f991")
    erc20_contract = ERC20Contract(OLAS_TOKEN_ADDRESS_GNOSIS)

    config = TritonConfig().load()

    # New service
    service_config = config.create_service("trader_alpha")
    service = Service(service_config)

    service.create(
        erc20_contract=erc20_contract,
        bond_amount=staking_contract.min_staking_deposit,
    )
    config.save()

    # Existent service
    # service_config = config.get_service_by_name("trader_alpha")
    # print(service.get())

    service.activate_registration()
    service.register_agent()
    config.save()

    service.deploy()
    config.save()

    service.stake(staking_contract)
    config.save()

    service.unstake(staking_contract)
    config.save()

    service.terminate()
    service.unbond()
