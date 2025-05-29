import asyncio
import argparse
import json
import requests
import sys
import datetime
import certifi

from settings import Settings
from redis import redis_client
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from typing import Dict, Optional
from notifications import notifications_api


settings = Settings()

async def main():
    await notifications_api.send_email('awesomecosmonaut@gmail.com', 'we have started', 'start')
    await asyncio.sleep(5)
    await notifications_api.send_email('awesomecosmonaut@gmail.com', 'we have ended', 'end')


asyncio.run(main())
