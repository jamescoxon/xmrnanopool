#TODO
# Add api
# Store block shares in single redis (json?)
from monero.wallet import Wallet
from monero.backends.jsonrpc import JSONRPCWallet

import time, requests, sys, redis, logging
from decimal import *
getcontext().prec = 30
from jcnanolib import nano

sys.path.append( 'changenow-api-python' )
from changenow_api.client import api_wrapper
from changenow_api.exceptions import ChangeNowApiError

import settings

w = Wallet(JSONRPCWallet(port=28088))

r = redis.Redis(decode_responses=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger()

monero_address = w.address()
monero_balance = w.balance()

logging.info(monero_address)
logging.info(monero_balance)

nano_address = settings.deposit_address
wallet_seed = settings.wallet_seed
index_pos = settings.index

api_key = settings.api_key

def min_exchange(from_ticker):
    try:
        response = api_wrapper('MIN_AMOUNT', from_ticker=from_ticker, to_ticker='nano')
    except ChangeNowApiError as err:
        logging.info(err)
    return response

def transaction_status(transaction_id, api_key):
    try:
        response = api_wrapper('TX_STATUS',  api_key=api_key, id=transaction_id)
    except ChangeNowApiError as err:
        logging.info(err)
    return response

def check_estimate(from_ticker, amount, api_key):
    try:
        response = api_wrapper('ESTIMATED', fixed_rate=False, api_key=api_key, from_ticker=from_ticker, amount=str(amount), to_ticker='nano')
    except ChangeNowApiError as err:
        logging.info(err)
    return response

def send_transaction(from_ticker, amount, nano_address, api_key):
    try:
        response = api_wrapper('CREATE_TX', address=nano_address, fixed_rate=False, api_key=api_key, from_ticker=from_ticker, amount=float(amount), to_ticker='nano')
    except ChangeNowApiError as err:
        logging.info(err)
    return response

approx_fee = 0.0001
from_ticker = 'xmr'

logging.info('Rx all Nano')
result = nano.process_pending(nano_address, index_pos, wallet_seed)
logging.info(result)

if r.exists('last_block'):
    last_block = r.get('last_block')
else:
    r.set('last_block', 0)
    last_block = 0

logging.info('Waiting for XMR deposit')

while True:
    # Check Minimum
    minimum_exchange = min_exchange(from_ticker)
    logging.info(minimum_exchange)

    monero_balance = w.balance()
    logging.info('XMR Balance: {}'.format(monero_balance))

    if Decimal(monero_balance) >= (Decimal(minimum_exchange['minAmount']) + Decimal(approx_fee)):

        last_transaction = w.incoming(min_height=int(last_block))
        if len(last_transaction) > 0:
            logging.info('{} {}'.format(last_transaction[0], w.confirmations(last_transaction[0])))
            if int(w.confirmations(last_transaction[0])) < 10:
                logging.info('await confirmation: {}'.format(int(w.confirmations(last_transaction[0]))))
                time.sleep(30)
                continue

            logging.info(last_transaction)
            logging.info('Setting last_block')

            last_block = int(last_transaction[0].transaction.height) + 1
            r.set('last_block', last_block)
            r.set('last_amount', str(last_transaction[0].amount))

            logging.info('Get latest pool data')
            x = requests.get('http://{}/1/workers'.format(settings.proxyapi_url))
            worker_json = x.json()

            total_shares = 0
            worker_shares = {}
            for worker in worker_json['workers']:
#                logging.info('{} {}'.format(worker[0], worker[3]))

                current_shares = int(worker[3])
                # Calculate accepted shares for this round
                if r.exists(worker[0]):
                    total_worker_shares = int(r.get(worker[0]))
                else:
                    total_worker_shares = 0

                accepted_shares = current_shares - total_worker_shares

                # Add to our dict
                worker_shares[worker[0]] = accepted_shares

                # Store in Redis the total accepted shares
                r.set(worker[0], current_shares)
                # Store in Redis the accepted shares for this round
                r.set('{}-shares-{}'.format(str(last_block), worker[0]), accepted_shares)

                total_shares = total_shares + accepted_shares

            check_total = 0

            # Setup Exchange
            amount = Decimal(monero_balance) - Decimal(approx_fee)
            if r.exists('exchange_address'):
                logging.info('already have exchange address, get from redis')
                payinAddress = r.get('exchange_address')
            else:
                logging.info('get new exchange address')
                transaction_detail = send_transaction(from_ticker, str(amount), settings.deposit_address, api_key)
                logging.info(transaction_detail)
                transaction_id = transaction_detail['id']
                payinAddress = transaction_detail['payinAddress']
                r.set('exchange_address', payinAddress)

            try:
                txs = w.transfer(payinAddress, Decimal(amount))
                logging.info(txs)
            except:
                logging.info('XMR not ready, transfer to exchange failed')
                time.sleep(10)
                continue

            exchange_status = 'starting'
            while exchange_status != 'finished':
                status_response = transaction_status(transaction_id, api_key)
                exchange_status = status_response['status']
                logging.info(exchange_status)
                time.sleep(10)
            else:
                r.delete('exchange_address')

            # TODO add timeout
            nano_total_amount_raw = 0
            while Decimal(nano_total_amount_raw) <= Decimal(1000000):
                # Nano amount (we will get this by parsing account)
                result = nano.process_pending(nano_address, index_pos, wallet_seed)
                logging.info(result)
                nano_total_amount_raw = Decimal(nano.get_account_balance(nano_address))

            time.sleep(5)

            for worker in worker_shares:

                # Calculate share
                nano_share_raw = Decimal(nano_total_amount_raw) * (Decimal(worker_shares[worker]) / Decimal(total_shares))
                logging.info('{} {} {} {} {}'.format(worker, worker_shares[worker], total_shares, nano_share_raw, nano_total_amount_raw))

                # Send share of Nano to worker
                if Decimal(nano_share_raw) > Decimal(0):
                    result = nano.send_xrb(worker, nano_share_raw, nano_address, index_pos, wallet_seed)
                    logging.info(result)

                # Add up all the shares to check that it matches original amount
                check_total = check_total + nano_share_raw

                r.set('{}-nano-{}'.format(str(last_block), worker), int(nano_share_raw))

            if Decimal(check_total) == Decimal(nano_total_amount_raw):
                check_adds_up = True
            else:
                check_adds_up = False

            logging.info('{} {} {}'.format(int(check_total), nano_total_amount_raw, check_adds_up ))

    time.sleep(30)
